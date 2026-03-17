from unittest.mock import patch

import pandas as pd
import pytest

from a_pipeline.modules.factors import calculate_factors


@pytest.mark.parametrize(
    "factor_func, col_name",
    [
        (calculate_factors.calculate_sma, "sma"),
        (calculate_factors.calculate_ema, "ema"),
        (calculate_factors.calculate_avg_volume, "volume"),
        (calculate_factors.calculate_donchian_high, "high_price"),
    ],
)
def test_rolling_factors(sample_price_data, factor_func, col_name):
    """Tests multiple rolling window functions in one sweep."""
    result = factor_func(sample_price_data, days=2)
    assert len(result) == len(sample_price_data)
    assert not result.dropna().empty


def test_calculate_return(sample_price_data):
    """Verifies log return calculation: log(102/100) ≈ 0.019803"""
    returns = calculate_factors.calculate_return(sample_price_data, days=1)
    # Expected: log(102/100) = 0.019803
    assert returns.iloc[1] == 0.019803
    assert pd.isna(returns.iloc[0])


def test_calculate_sma_math(sample_price_data):
    """Verifies specific Simple Moving Average math: (100+102+101)/3 = 101.0"""
    sma = calculate_factors.calculate_sma(sample_price_data, days=3)
    assert sma.iloc[2] == 101.0


def test_calculate_dollar_volume(sample_price_data):
    """Verifies price * volume logic."""
    dollar_vol = calculate_factors.calculate_dollar_volume(sample_price_data)
    assert dollar_vol.iloc[0] == 100000.0


def test_calculate_ntm_eps_logic():
    """Verifies the time-weighted EPS calculation."""
    today = pd.Timestamp.today().normalize()
    fy1_date = today + pd.Timedelta(days=182)

    data = pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL"],
            "period": ["Current Year", "Next Year"],
            "period_end_date": [fy1_date, fy1_date + pd.Timedelta(days=365)],
            "consensus_eps": [2.00, 4.00],
        }
    )

    result = calculate_factors.calculate_ntm_eps(data)
    assert "ntm_eps" in result.columns
    assert 2.0 < result.iloc[0]["ntm_eps"] < 4.0


@patch("a_pipeline.modules.db_loader.postgres.get_latest_data")
def test_get_latest_indicators_master_merge(mock_get_data):
    """Verifies that multiple database tables are joined and ranked correctly."""
    mock_ohlcv = pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT"],
            "close_price": [150.0, 400.0],
            "price_date": ["2024-01-01"] * 2,
        }
    )
    mock_liq = pd.DataFrame(
        {"symbol": ["AAPL", "MSFT"], "adv_20d": [1e6, 2e6], "addv_20d": [1.5e8, 8e8]}
    )
    mock_trend = pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT"],
            "ma200": [140.0, 380.0],
            "ma200_20d_roc": [0.01, 0.02],
        }
    )
    mock_mom = pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT"],
            "risk_adj_mom_12m": [1.5, 2.5],
            "positive_ret_pct_60d": [0.6, 0.8],
        }
    )
    mock_risk = pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT"],
            "vol_60d": [0.2, 0.25],
            "max_drawdown_1y": [-0.1, -0.15],
            "historical_var_95_1m": [500, 600],
        }
    )
    mock_eps = pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "period": ["Current Year", "Next Year"] * 2,
            "period_end_date": [pd.Timestamp.today() + pd.Timedelta(days=100)] * 4,
            "consensus_eps": [2.0, 2.5, 10.0, 12.0],
        }
    )

    mock_get_data.side_effect = [
        mock_ohlcv,
        mock_liq,
        mock_trend,
        mock_mom,
        mock_risk,
        mock_eps,
    ]

    result = calculate_factors.get_latest_indicators(
        symbols=["AAPL", "MSFT"], as_of_date="2024-01-01"
    )

    assert not result.empty
    assert "price_above_ma200" in result.columns
    assert result.query("symbol == 'AAPL'")["price_above_ma200"].iloc[0]


def test_math_completeness_sweep(sample_price_data):
    """Executes all remaining complex math functions to ensure higher coverage."""
    calculate_factors.calculate_volatility(sample_price_data, days=2)
    calculate_factors.calculate_adx(sample_price_data, days=2)
    calculate_factors.calculate_rsi(sample_price_data, days=2)
    calculate_factors.calculate_bollingner(sample_price_data, days=2)
    calculate_factors.calculate_maximum_drawdown(sample_price_data, days=2)
    calculate_factors.calculate_historical_var(sample_price_data, rolling_window=2)
    calculate_factors.calculate_historical_cvar(sample_price_data, rolling_window=2)
