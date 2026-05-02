import pandas as pd
import pytest

from modules.factors import fetch_factors


def test_calculate_ntm_eps_logic(mocker):
    """Verify time-weighted interpolation between FY1 and FY2."""
    # Freeze time to mid-year (182.5 days left)
    mock_today = pd.Timestamp("2025-07-02")
    mocker.patch("pandas.Timestamp.today", return_value=mock_today)

    data = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "period": "Current Year",
                "period_end_date": "2025-12-31",
                "consensus_eps": 10.0,
            },
            {
                "symbol": "AAPL",
                "period": "Next Year",
                "period_end_date": "2026-12-31",
                "consensus_eps": 20.0,
            },
        ]
    )

    result = fetch_factors.calculate_ntm_eps(data)

    # Mid-year should result in a blend roughly halfway between 10 and 20
    # weight_fy1 = ~0.5, weight_fy2 = ~0.5 -> result ~15.0
    assert 14.0 <= result.iloc[0]["ntm_eps"] <= 16.0
    assert result.iloc[0]["symbol"] == "AAPL"


def test_calculate_ntm_eps_empty():
    """Ensure it handles empty data without crashing."""
    result = fetch_factors.calculate_ntm_eps(None)
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_apply_weight_capping(mocker):
    """Test that the iterative loop respects Health Care and Stock caps."""
    # Mock config: 30% sector cap, 10% stock cap
    mock_config = {"health_sector_cap": 0.30, "stock_cap": 0.10}
    mocker.patch("modules.factors.fetch_factors.load_config", return_value=mock_config)

    # Create 20 stocks. Give one Health Care stock a massive score so it gets huge weight initially.
    data = []
    for i in range(20):
        data.append(
            {
                "symbol": f"S{i}",
                "gics_sector": "Health Care" if i < 5 else "Technology",
                "total_score": (
                    100.0 if i == 0 else 1.0
                ),  # Stock 0 will start with huge weight
            }
        )
    df = pd.DataFrame(data)

    result = fetch_factors.apply_weight(df)

    # Assertions
    assert result["weight"].sum() == pytest.approx(1.0)
    assert result["weight"].max() <= 0.10 + 1e-9  # Individual stock cap respected

    hc_total = result[result["gics_sector"] == "Health Care"]["weight"].sum()
    assert hc_total <= 0.30 + 1e-9  # Sector cap respected


@pytest.fixture
def mock_ohlcv():
    return pd.DataFrame([{"symbol": "AAPL", "close_price": 150.0}])


def test_get_latest_indicators_merge(mocker):
    # Ensure mock_risk has the required column
    mock_ohlcv = pd.DataFrame([{"symbol": "AAPL", "close_price": 150.0}])
    mock_liq = pd.DataFrame(
        [{"symbol": "AAPL", "adv_20d": 1000000, "addv_20d": 150000000}]
    )
    mock_trend = pd.DataFrame(
        [{"symbol": "AAPL", "ma200": 140.0, "ma200_20d_roc": 0.01}]
    )
    mock_mom = pd.DataFrame(
        [{"symbol": "AAPL", "risk_adj_mom_12m": 0.5, "positive_ret_pct_60d": 0.6}]
    )
    # ADD THE MISSING COLUMN HERE:
    mock_risk = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "vol_60d": 0.2,
                "max_drawdown_1y": 0.15,
                "historical_var_95_1m": 200.0,  # <--- Fix
            }
        ]
    )
    mock_eps = pd.DataFrame([{"symbol": "AAPL", "ntm_eps": 5.0}])

    mocker.patch(
        "modules.db_loader.postgres.get_latest_data",
        side_effect=[mock_ohlcv, mock_liq, mock_trend, mock_mom, mock_risk, mock_eps],
    )

    mocker.patch(
        "modules.factors.fetch_factors.calculate_ntm_eps", return_value=mock_eps
    )

    result = fetch_factors.get_latest_indicators(["AAPL"], "2025-01-01")
    assert "var_pct" in result.columns
    assert result.iloc[0]["var_pct"] == 0.02


def test_apply_scoring_with_omission(mocker):
    """Test that weights re-normalize when a factor is omitted."""

    # Create a small DF with all factor columns
    df = pd.DataFrame(
        [
            {
                "risk_adj_mom_12m": 1.0,
                "positive_ret_pct_60d": 1.0,
                "forward_earning_yields": 1.0,
                "ma200_20d_roc": 1.0,
                "vol_60d": 1.0,
                "max_drawdown_1y": 1.0,
                "var_pct": 1.0,
                "adv_20d": 1.0,
                "addv_20d": 1.0,
            }
        ]
    )

    # Test omitting 'momentum'
    result = fetch_factors.apply_scoring(df, omit_factor="momentum")
    assert "total_score" in result.columns
    # If momentum is omitted, its score shouldn't crash the calculation


def test_wait_for_postgres_retry_logic(mocker):

    # Mock time.sleep so the test is instant
    mocker.patch("time.sleep")
    # Mock connection to fail then succeed
    mocker.patch(
        "modules.db_loader.postgres.check_connection", side_effect=[False, True]
    )

    assert fetch_factors.wait_for_postgres() is True


def test_wait_for_postgres_failure(mocker):

    mocker.patch("time.sleep")
    # Mock connection to always fail
    mocker.patch("modules.db_loader.postgres.check_connection", return_value=False)

    with pytest.raises(ConnectionError):
        fetch_factors.wait_for_postgres()
