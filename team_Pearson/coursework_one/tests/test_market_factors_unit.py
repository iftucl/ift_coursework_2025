"""Unit tests for modules.transform.market_factors.

Tests cover:
- _compute_momentum: cumulative return calculation and edge cases
- _compute_rolling_vol: annualised volatility
- _compute_beta: covariance / variance calculation
- _compute_liquidity: average dollar volume
- _compute_log_market_cap: ln(price × shares) with guard conditions
- _to_float_or_none: type coercion helper
"""

from __future__ import annotations

import math
import sys
from datetime import date

import pytest

try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from modules.transform.market_factors import (
    build_market_factors,
    _compute_beta,
    _compute_dividend_stability,
    _compute_ebitda_to_ev,
    _compute_ep_ratio,
    _compute_garch_vol,
    _compute_liquidity,
    _compute_log_market_cap,
    _compute_momentum,
    _compute_payout_ratio,
    _compute_realized_vol,
    _compute_rolling_vol,
    _latest_financial_value,
    _to_float_or_none,
)
import modules.transform.market_factors as market_factors_mod

pytestmark = pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_returns():
    """Daily returns of 0.001 (small positive constant)."""
    import pandas as pd
    return pd.Series([0.001] * 300)


@pytest.fixture
def volatile_returns():
    """Alternating +1% / -1% returns."""
    import pandas as pd
    pattern = [0.01, -0.01] * 150
    return pd.Series(pattern)


@pytest.fixture
def market_returns(flat_returns):
    import pandas as pd
    return pd.Series([0.0008] * 300)


# ---------------------------------------------------------------------------
# _compute_momentum
# ---------------------------------------------------------------------------

class TestComputeMomentum:
    def test_positive_momentum(self, flat_returns):
        result = _compute_momentum(flat_returns, window=63)
        assert result is not None
        assert result > 0

    def test_momentum_with_skip(self, flat_returns):
        result_no_skip = _compute_momentum(flat_returns, window=252)
        result_with_skip = _compute_momentum(flat_returns, window=252, skip=21)
        # Both should be positive; skipping most-recent month changes the value slightly
        assert result_no_skip is not None
        assert result_with_skip is not None

    def test_returns_none_for_insufficient_data(self):
        import pandas as pd
        tiny = pd.Series([0.01] * 5)
        result = _compute_momentum(tiny, window=63)
        assert result is None

    def test_zero_returns_give_zero_momentum(self):
        import pandas as pd
        zeros = pd.Series([0.0] * 100)
        result = _compute_momentum(zeros, window=63)
        assert result is not None
        assert abs(result) < 1e-10


# ---------------------------------------------------------------------------
# _compute_rolling_vol
# ---------------------------------------------------------------------------

class TestComputeRollingVol:
    def test_flat_returns_give_near_zero_vol(self, flat_returns):
        vol = _compute_rolling_vol(flat_returns, window=60)
        assert vol is not None
        assert vol < 0.05  # very low volatility

    def test_volatile_returns_give_higher_vol(self, volatile_returns):
        vol = _compute_rolling_vol(volatile_returns, window=60)
        assert vol is not None
        assert vol > 0.05

    def test_returns_none_for_insufficient_data(self):
        import pandas as pd
        tiny = pd.Series([0.01] * 5)
        result = _compute_rolling_vol(tiny, window=60)
        assert result is None

    def test_vol_is_annualised(self, flat_returns):
        """Vol should be daily_std * sqrt(252)."""
        import pandas as pd
        std_daily = float(flat_returns.iloc[-60:].std(ddof=1))
        expected_annual = std_daily * math.sqrt(252)
        vol = _compute_rolling_vol(flat_returns, window=60)
        assert vol is not None
        assert abs(vol - expected_annual) < 1e-6


class TestComputeRealizedVol:
    def test_flat_returns_give_expected_realized_vol(self, flat_returns):
        realized = _compute_realized_vol(flat_returns, window=60)
        assert realized is not None
        expected = abs(0.001) * math.sqrt(252)
        assert abs(realized - expected) < 1e-6

    def test_returns_none_for_insufficient_data(self):
        import pandas as pd
        tiny = pd.Series([0.01] * 5)
        result = _compute_realized_vol(tiny, window=60)
        assert result is None


class TestComputeGarchVol:
    def test_garch_vol_positive_for_nonzero_returns(self, volatile_returns):
        vol = _compute_garch_vol(volatile_returns, window=60)
        assert vol is not None
        assert vol > 0

    def test_garch_vol_none_for_insufficient_data(self):
        import pandas as pd
        tiny = pd.Series([0.01] * 5)
        result = _compute_garch_vol(tiny, window=60)
        assert result is None

    def test_garch_vol_reacts_more_than_flat_series(self, flat_returns, volatile_returns):
        flat_vol = _compute_garch_vol(flat_returns, window=60)
        volatile_vol = _compute_garch_vol(volatile_returns, window=60)
        assert flat_vol is not None
        assert volatile_vol is not None
        assert volatile_vol > flat_vol


# ---------------------------------------------------------------------------
# _compute_beta
# ---------------------------------------------------------------------------

class TestComputeBeta:
    def test_perfectly_correlated_gives_beta_near_ratio(self):
        import pandas as pd
        # Stock returns = 2 × market returns → beta ≈ 2.0
        market = pd.Series([0.01, -0.01, 0.02, -0.02] * 63)
        stock = market * 2.0
        beta = _compute_beta(stock, market, window=252)
        assert beta is not None
        assert abs(beta - 2.0) < 0.01

    def test_uncorrelated_returns_give_near_zero_beta(self):
        import pandas as pd
        import numpy as np
        rng = np.random.default_rng(42)
        market = pd.Series(rng.normal(0, 0.01, 300))
        stock = pd.Series(rng.normal(0, 0.01, 300))
        beta = _compute_beta(stock, market, window=252)
        # Beta should be close to 0 for truly independent series
        assert beta is not None
        assert abs(beta) < 0.5

    def test_returns_none_for_zero_variance_market(self):
        import pandas as pd
        market = pd.Series([0.0] * 300)
        stock = pd.Series([0.01] * 300)
        beta = _compute_beta(stock, market, window=252)
        assert beta is None

    def test_returns_none_for_insufficient_data(self):
        import pandas as pd
        market = pd.Series([0.01] * 10)
        stock = pd.Series([0.01] * 10)
        beta = _compute_beta(stock, market, window=252)
        assert beta is None


# ---------------------------------------------------------------------------
# _compute_liquidity
# ---------------------------------------------------------------------------

class TestComputeLiquidity:
    def test_basic_liquidity_calculation(self):
        import pandas as pd
        prices = pd.Series([100.0] * 20)
        volumes = pd.Series([1_000_000.0] * 20)
        liq = _compute_liquidity(prices, volumes, window=20)
        assert liq is not None
        assert abs(liq - 100_000_000.0) < 1.0

    def test_returns_none_for_insufficient_data(self):
        import pandas as pd
        prices = pd.Series([100.0] * 5)
        volumes = pd.Series([1_000_000.0] * 5)
        liq = _compute_liquidity(prices, volumes, window=20)
        assert liq is None


# ---------------------------------------------------------------------------
# _compute_log_market_cap
# ---------------------------------------------------------------------------

class TestComputeLogMarketCap:
    def test_valid_inputs(self):
        result = _compute_log_market_cap(150.0, 1_000_000_000.0)
        assert result is not None
        assert abs(result - math.log(150.0 * 1_000_000_000.0)) < 1e-9

    def test_zero_price_returns_none(self):
        assert _compute_log_market_cap(0.0, 1_000_000.0) is None

    def test_negative_price_returns_none(self):
        assert _compute_log_market_cap(-10.0, 1_000_000.0) is None

    def test_none_price_returns_none(self):
        assert _compute_log_market_cap(None, 1_000_000.0) is None

    def test_none_shares_returns_none(self):
        assert _compute_log_market_cap(150.0, None) is None

    def test_zero_shares_returns_none(self):
        assert _compute_log_market_cap(150.0, 0.0) is None


# ---------------------------------------------------------------------------
# _to_float_or_none
# ---------------------------------------------------------------------------

class TestMomentum6m:
    def test_6m_momentum_positive(self):
        import pandas as pd
        returns = pd.Series([0.001] * 200)
        result = _compute_momentum(returns, 126)
        assert result is not None
        assert result > 0

    def test_6m_momentum_insufficient_data(self):
        import pandas as pd
        returns = pd.Series([0.001] * 30)
        result = _compute_momentum(returns, 126)
        assert result is None


class TestEpRatio:
    def test_positive_eps_positive_price(self):
        result = _compute_ep_ratio(5.0, 100.0)
        assert result is not None
        assert abs(result - 0.05) < 1e-9

    def test_negative_eps_negative_ep(self):
        result = _compute_ep_ratio(-3.0, 50.0)
        assert result is not None
        assert result < 0

    def test_zero_price_returns_none(self):
        assert _compute_ep_ratio(5.0, 0.0) is None

    def test_none_eps_returns_none(self):
        assert _compute_ep_ratio(None, 100.0) is None


class TestEbitdaToEv:
    def test_basic_calculation(self):
        # EV = 1000 + 200 - 50 = 1150; EBITDA/EV = 100/1150
        result = _compute_ebitda_to_ev(100.0, 1000.0, 200.0, 50.0)
        assert result is not None
        assert abs(result - 100.0 / 1150.0) < 1e-9

    def test_no_debt_no_cash(self):
        result = _compute_ebitda_to_ev(100.0, 1000.0, None, None)
        assert result is not None
        assert abs(result - 0.1) < 1e-9

    def test_negative_ev_returns_none(self):
        # Cash > market_cap + debt → EV negative
        result = _compute_ebitda_to_ev(100.0, 500.0, 0.0, 600.0)
        assert result is None

    def test_none_ebitda_returns_none(self):
        assert _compute_ebitda_to_ev(None, 1000.0, 200.0, 50.0) is None

    def test_none_market_cap_returns_none(self):
        assert _compute_ebitda_to_ev(100.0, None, 200.0, 50.0) is None


class TestPayoutRatio:
    def test_normal_payout(self):
        result = _compute_payout_ratio(2.0, 5.0)
        assert result is not None
        assert abs(result - 0.4) < 1e-9

    def test_zero_eps_returns_none(self):
        assert _compute_payout_ratio(1.0, 0.0) is None

    def test_none_dps_returns_none(self):
        assert _compute_payout_ratio(None, 5.0) is None

    def test_unsustainable_payout_gt_1(self):
        result = _compute_payout_ratio(6.0, 5.0)
        assert result is not None
        assert result > 1.0  # CW2 penalises this


class TestDividendStability:
    def test_stable_dividends_score_high(self):
        import pandas as pd
        dates = pd.to_datetime([
            date(2019, 3, 31), date(2019, 6, 30), date(2019, 9, 30), date(2019, 12, 31),
            date(2020, 3, 31), date(2020, 6, 30), date(2020, 9, 30), date(2020, 12, 31),
            date(2021, 3, 31), date(2021, 6, 30), date(2021, 9, 30), date(2021, 12, 31),
            date(2022, 3, 31), date(2022, 6, 30), date(2022, 9, 30), date(2022, 12, 31),
            date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31),
        ])
        series = pd.Series([0.25] * len(dates), index=dates)
        stability = _compute_dividend_stability(series, date(2023, 12, 31))
        assert stability is not None
        assert 0.7 < stability <= 1.0

    def test_dividend_cut_scores_lower_than_stable_series(self):
        import pandas as pd
        stable_dates = pd.to_datetime([
            date(2019, 3, 31), date(2019, 6, 30), date(2019, 9, 30), date(2019, 12, 31),
            date(2020, 3, 31), date(2020, 6, 30), date(2020, 9, 30), date(2020, 12, 31),
            date(2021, 3, 31), date(2021, 6, 30), date(2021, 9, 30), date(2021, 12, 31),
            date(2022, 3, 31), date(2022, 6, 30), date(2022, 9, 30), date(2022, 12, 31),
            date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31),
        ])
        stable_series = pd.Series([0.25] * len(stable_dates), index=stable_dates)
        cut_series = pd.Series(
            [0.25] * 16 + [0.10] * 4,
            index=stable_dates,
        )
        stable_score = _compute_dividend_stability(stable_series, date(2023, 12, 31))
        cut_score = _compute_dividend_stability(cut_series, date(2023, 12, 31))
        assert stable_score is not None
        assert cut_score is not None
        assert cut_score < stable_score

    def test_insufficient_history_returns_none(self):
        import pandas as pd
        series = pd.Series(
            [0.25, 0.25, 0.25, 0.25],
            index=pd.to_datetime(["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"]),
        )
        stability = _compute_dividend_stability(series, date(2023, 12, 31))
        assert stability is None


class TestToFloatOrNone:
    def test_int_converted(self):
        assert _to_float_or_none(42) == 42.0

    def test_string_number_converted(self):
        assert _to_float_or_none("3.14") == pytest.approx(3.14)

    def test_none_returns_none(self):
        assert _to_float_or_none(None) is None

    def test_nan_returns_none(self):
        assert _to_float_or_none(float("nan")) is None

    def test_inf_returns_none(self):
        assert _to_float_or_none(float("inf")) is None

    def test_invalid_string_returns_none(self):
        assert _to_float_or_none("not_a_number") is None


# ---------------------------------------------------------------------------
# _latest_financial_value
# ---------------------------------------------------------------------------

class TestLatestFinancialValue:
    def _make_fin_df(self):
        import pandas as pd
        return pd.DataFrame([
            {
                "symbol": "AAPL",
                "metric_name": "eps_basic",
                "report_date": date(2023, 3, 31),
                "publish_date": date(2023, 4, 28),
                "metric_value": 1.5,
            },
            {
                "symbol": "AAPL",
                "metric_name": "eps_basic",
                "report_date": date(2023, 6, 30),
                "publish_date": date(2023, 7, 28),
                "metric_value": 1.8,
            },
            {
                "symbol": "AAPL",
                "metric_name": "eps_basic",
                "report_date": date(2023, 9, 30),
                "publish_date": date(2023, 10, 27),
                "metric_value": 2.0,
            },
            {
                "symbol": "MSFT",
                "metric_name": "eps_basic",
                "report_date": date(2023, 9, 30),
                "publish_date": date(2023, 10, 25),
                "metric_value": 3.0,
            },
        ])

    def test_returns_latest_value_on_or_before_cutoff(self):
        df = self._make_fin_df()
        val = _latest_financial_value(df, "AAPL", "eps_basic", date(2023, 7, 31))
        assert val == pytest.approx(1.8)

    def test_returns_most_recent_when_multiple_in_range(self):
        df = self._make_fin_df()
        val = _latest_financial_value(df, "AAPL", "eps_basic", date(2023, 12, 31))
        assert val == pytest.approx(2.0)

    def test_returns_none_when_no_data_before_cutoff(self):
        df = self._make_fin_df()
        val = _latest_financial_value(df, "AAPL", "eps_basic", date(2022, 1, 1))
        assert val is None

    def test_returns_none_for_missing_symbol(self):
        df = self._make_fin_df()
        val = _latest_financial_value(df, "GOOG", "eps_basic", date(2024, 1, 1))
        assert val is None

    def test_returns_none_for_missing_metric(self):
        df = self._make_fin_df()
        val = _latest_financial_value(df, "AAPL", "nonexistent_metric", date(2024, 1, 1))
        assert val is None

    def test_correct_symbol_isolation(self):
        """AAPL and MSFT data must not bleed across symbols."""
        df = self._make_fin_df()
        aapl_val = _latest_financial_value(df, "AAPL", "eps_basic", date(2024, 1, 1))
        msft_val = _latest_financial_value(df, "MSFT", "eps_basic", date(2024, 1, 1))
        assert aapl_val == pytest.approx(2.0)
        assert msft_val == pytest.approx(3.0)

    def test_excludes_rows_not_yet_published_at_cutoff(self):
        df = self._make_fin_df()
        val = _latest_financial_value(df, "AAPL", "eps_basic", date(2023, 7, 15))
        assert val == pytest.approx(1.5)


class _FakeRows:
    def __init__(self, rows, keys):
        self._rows = rows
        self._keys = keys

    def fetchall(self):
        return list(self._rows)

    def keys(self):
        return list(self._keys)


class _FakeConn:
    def __init__(self, rows=None):
        self.rows = rows
        self.executed = []

    def execute(self, stmt, params):
        self.executed.append((stmt, params))
        if self.rows is None:
            return None
        return _FakeRows(self.rows[0], self.rows[1])


class _FakeConnectCtx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, conn):
        self.conn = conn

    def connect(self):
        return _FakeConnectCtx(self.conn)

    def begin(self):
        return _FakeConnectCtx(self.conn)


def test_load_price_data_normalizes_result(monkeypatch):
    rows = [
        ("AAPL", date(2024, 1, 2), "adjusted_close_price", "101.5"),
        ("AAPL", date(2024, 1, 2), "daily_return", "0.01"),
    ]
    conn = _FakeConn((rows, ["symbol", "observation_date", "factor_name", "factor_value"]))
    import modules.db as db_mod

    monkeypatch.setattr(db_mod, "get_db_engine", lambda: _FakeEngine(conn))
    df = market_factors_mod._load_price_data(["AAPL"], date(2024, 1, 1), date(2024, 1, 3))

    assert list(df["symbol"]) == ["AAPL", "AAPL"]
    assert df["observation_date"].iloc[0] == date(2024, 1, 2)
    assert df["factor_value"].iloc[0] == pytest.approx(101.5)


def test_load_financial_data_normalizes_publish_date(monkeypatch):
    rows = [
        ("AAPL", date(2024, 1, 1), "eps_basic", "1.25", "edgar", date(2024, 2, 10)),
    ]
    conn = _FakeConn((rows, ["symbol", "report_date", "metric_name", "metric_value", "source", "publish_date"]))
    import modules.db as db_mod

    monkeypatch.setattr(db_mod, "get_db_engine", lambda: _FakeEngine(conn))
    df = market_factors_mod._load_financial_data(
        ["AAPL"], date(2024, 1, 1), date(2024, 3, 1), ["eps_basic"]
    )

    assert df["report_date"].iloc[0] == date(2024, 1, 1)
    assert df["publish_date"].iloc[0] == date(2024, 2, 10)
    assert df["metric_value"].iloc[0] == pytest.approx(1.25)
    assert df["source"].iloc[0] == "edgar"
    assert "publish_date AS publish_date" in str(conn.executed[0][0])


def test_load_financial_data_can_enable_legacy_publish_fallback(monkeypatch):
    rows = [
        ("AAPL", date(2024, 1, 1), "eps_basic", "1.25", "edgar", date(2024, 2, 10)),
    ]
    conn = _FakeConn((rows, ["symbol", "report_date", "metric_name", "metric_value", "source", "publish_date"]))
    import modules.db as db_mod

    monkeypatch.setattr(db_mod, "get_db_engine", lambda: _FakeEngine(conn))
    monkeypatch.setenv("CW1_ALLOW_FINANCIAL_PUBLISH_FALLBACK", "true")
    market_factors_mod._load_financial_data(
        ["AAPL"], date(2024, 1, 1), date(2024, 3, 1), ["eps_basic"]
    )

    assert "COALESCE(publish_date, as_of, report_date) AS publish_date" in str(
        conn.executed[0][0]
    )


def test_load_benchmark_returns_empty(monkeypatch):
    conn = _FakeConn(([], ["price_date", "daily_return"]))
    import modules.db as db_mod

    monkeypatch.setattr(db_mod, "get_db_engine", lambda: _FakeEngine(conn))
    series = market_factors_mod._load_benchmark_returns(date(2024, 1, 1), date(2024, 1, 3))
    assert series.empty


def test_load_and_store_benchmark_prices_upserts(monkeypatch):
    import pandas as pd
    import types
    import modules.db as db_mod

    hist = pd.DataFrame(
        {"Close": [100.0, 101.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )

    class _Ticker:
        def history(self, start, end, auto_adjust=True):
            return hist

    fake_yf = types.SimpleNamespace(Ticker=lambda _: _Ticker())
    conn = _FakeConn()
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    monkeypatch.setattr(db_mod, "get_db_engine", lambda: _FakeEngine(conn))

    market_factors_mod._load_and_store_benchmark_prices(date(2024, 1, 1), date(2024, 1, 4))

    assert len(conn.executed) == 1
    stmt, payload = conn.executed[0]
    assert "benchmark_prices" in str(stmt)
    assert len(payload) == 2
    assert payload[0]["ticker"] == "SPY"
    assert payload[0]["daily_return"] is None
    assert payload[1]["daily_return"] == pytest.approx(math.log(101.0) - math.log(100.0))


def test_load_and_store_macro_indicators_upserts_available_series(monkeypatch):
    import pandas as pd
    import types
    import modules.db as db_mod

    hist = pd.DataFrame(
        {"Close": [20.0, 21.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )

    class _Ticker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, start, end, auto_adjust=True):
            if self.ticker == "^VIX":
                return hist
            return pd.DataFrame()

    fake_yf = types.SimpleNamespace(Ticker=lambda ticker: _Ticker(ticker))
    conn = _FakeConn()
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    monkeypatch.setattr(db_mod, "get_db_engine", lambda: _FakeEngine(conn))

    market_factors_mod._load_and_store_macro_indicators(date(2024, 1, 1), date(2024, 1, 4))

    assert len(conn.executed) == 1
    stmt, payload = conn.executed[0]
    assert "factor_observations" in str(stmt)
    assert len(payload) == 2
    assert payload[0]["symbol"] == "_MACRO"
    assert payload[0]["factor_name"] == "vix_close"
    assert payload[0]["publish_date"] == date(2024, 1, 2)


def test_build_market_factors_uses_latest_available_trading_date_and_computes_liquidity(monkeypatch):
    import pandas as pd

    obs_dates = pd.date_range("2024-01-02", periods=24, freq="B")
    rows = []
    for idx, obs_ts in enumerate(obs_dates, start=1):
        obs_date = obs_ts.date()
        rows.extend(
            [
                ("AAPL", obs_date, "adjusted_close_price", float(100 + idx)),
                ("AAPL", obs_date, "daily_return", 0.01),
                ("AAPL", obs_date, "daily_volume", float(1_000_000 + idx)),
            ]
        )
    price_df = pd.DataFrame(
        rows,
        columns=["symbol", "observation_date", "factor_name", "factor_value"],
    )
    benchmark = pd.Series(dtype=float)
    fin_df = pd.DataFrame(
        [
            ("AAPL", date(2023, 12, 31), "shares_outstanding", 1_000_000_000.0, date(2024, 1, 15)),
        ],
        columns=["symbol", "report_date", "metric_name", "metric_value", "publish_date"],
    )

    monkeypatch.setattr(market_factors_mod, "_load_price_data", lambda *args, **kwargs: price_df)
    monkeypatch.setattr(market_factors_mod, "_load_benchmark_returns", lambda *args, **kwargs: benchmark)
    monkeypatch.setattr(market_factors_mod, "_load_financial_data", lambda *args, **kwargs: fin_df)

    records = build_market_factors(
        ["AAPL"],
        start_date=date(2024, 2, 5),
        end_date=date(2024, 2, 5),
        refresh_benchmark=False,
    )

    assert records
    assert {rec["observation_date"] for rec in records} == {"2024-02-02"}
    liquidity = [rec for rec in records if rec["factor_name"] == "liquidity_20d"]
    market_cap = [rec for rec in records if rec["factor_name"] == "log_market_cap"]
    assert len(liquidity) == 1
    assert liquidity[0]["factor_value"] > 0
    assert len(market_cap) == 1
    assert market_cap[0]["factor_value"] > 0


def test_build_market_factors_uses_mixed_source_bundle_when_same_source_bundle_missing(monkeypatch):
    import pandas as pd

    obs_dates = pd.date_range("2024-01-02", periods=24, freq="B")
    rows = []
    for idx, obs_ts in enumerate(obs_dates, start=1):
        obs_date = obs_ts.date()
        rows.extend(
            [
                ("AAPL", obs_date, "adjusted_close_price", float(100 + idx)),
                ("AAPL", obs_date, "daily_return", 0.01),
                ("AAPL", obs_date, "daily_volume", float(1_000_000 + idx)),
            ]
        )
    price_df = pd.DataFrame(
        rows,
        columns=["symbol", "observation_date", "factor_name", "factor_value"],
    )
    fin_df = pd.DataFrame(
        [
            ("AAPL", date(2023, 12, 31), "ebitda", 100.0, "edgar", date(2024, 1, 15)),
            ("AAPL", date(2023, 12, 31), "shares_outstanding", 1_000_000_000.0, "yfinance", date(2024, 1, 15)),
            ("AAPL", date(2023, 12, 31), "total_debt", 200.0, "edgar", date(2024, 1, 15)),
            ("AAPL", date(2023, 12, 31), "cash_and_equivalents", 50.0, "edgar", date(2024, 1, 15)),
        ],
        columns=["symbol", "report_date", "metric_name", "metric_value", "source", "publish_date"],
    )

    monkeypatch.setattr(market_factors_mod, "_load_price_data", lambda *args, **kwargs: price_df)
    monkeypatch.setattr(market_factors_mod, "_load_benchmark_returns", lambda *args, **kwargs: pd.Series(dtype=float))
    monkeypatch.setattr(market_factors_mod, "_load_financial_data", lambda *args, **kwargs: fin_df)

    records = build_market_factors(
        ["AAPL"],
        start_date=date(2024, 2, 5),
        end_date=date(2024, 2, 5),
        refresh_benchmark=False,
    )

    ebitda_to_ev = [rec for rec in records if rec["factor_name"] == "ebitda_to_ev"]
    assert len(ebitda_to_ev) == 1
    assert ebitda_to_ev[0]["factor_value"] is not None
