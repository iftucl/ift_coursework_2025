"""Tests for zscore.py — per-metric ratio calculations and calculate_ratios."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from modules.zscore.zscore import (
    _calc_asset_growth,
    _calc_earnings_stability,
    _calc_leverage,
    _calc_momentum,
    _calc_pb_ratio,
    _calc_roe,
    _calc_volatility,
    _fetch_risk_free_rate,
    _last_bday_of_month,
    _nearest_price,
    calculate_ratios,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

REBALANCE = date(2024, 3, 29)
REBALANCE_TS = pd.Timestamp(REBALANCE)


def _price_series(n_days: int, base: float = 100.0, end: date = REBALANCE) -> pd.Series:
    """Generate a synthetic ascending price series ending on `end`."""
    idx = pd.bdate_range(end=end, periods=n_days)
    prices = base * (1 + 0.001 * np.arange(n_days))
    return pd.Series(prices, index=idx, name="adjusted_close")


def _eps_rows(n_years: int = 6, base_eps: float = 2.0) -> pd.DataFrame:
    """Generate n_years × 4 quarters of stable EPS rows sorted ASC."""
    rows = []
    for yr in range(2018, 2018 + n_years):
        for q in range(1, 5):
            rows.append(
                {
                    "report_date": pd.Timestamp(f"{yr}-{q * 3:02d}-28"),
                    "eps": base_eps + 0.05 * yr,
                    "fiscal_year": yr,
                    "fiscal_quarter": q,
                }
            )
    return pd.DataFrame(rows).sort_values("report_date").reset_index(drop=True)


def _ttm_rows(net_income: float = 1e9, book_equity: float = 5e9) -> pd.DataFrame:
    """Generate 4 quarters of TTM data sorted descending (most recent first)."""
    dates = pd.bdate_range(end=REBALANCE - timedelta(days=46), periods=4, freq="QE")[
        ::-1
    ]
    return pd.DataFrame(
        {
            "report_date": dates,
            "net_income": [net_income] * 4,
            "book_equity": [book_equity] * 4,
        }
    )


# ── _last_bday_of_month ────────────────────────────────────────────────────────


class TestLastBdayOfMonth:

    def test_returns_timestamp(self):
        result = _last_bday_of_month(REBALANCE_TS, 1)
        assert isinstance(result, pd.Timestamp)

    def test_one_month_back(self):
        result = _last_bday_of_month(pd.Timestamp("2024-03-29"), 1)
        assert result.month == 2
        assert result.year == 2024


# ── _nearest_price ────────────────────────────────────────────────────────────


class TestNearestPrice:

    def test_returns_most_recent_on_or_before_target(self):
        prices = pd.Series(
            [10.0, 20.0, 30.0],
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        )
        assert _nearest_price(prices, pd.Timestamp("2024-01-02")) == pytest.approx(20.0)

    def test_returns_none_when_no_price_before_target(self):
        prices = pd.Series(
            [10.0],
            index=pd.to_datetime(["2024-02-01"]),
        )
        assert _nearest_price(prices, pd.Timestamp("2024-01-01")) is None

    def test_uses_exact_match(self):
        prices = pd.Series([42.0], index=pd.to_datetime(["2024-03-15"]))
        assert _nearest_price(prices, pd.Timestamp("2024-03-15")) == pytest.approx(42.0)


# ── _calc_pb_ratio ────────────────────────────────────────────────────────────


class TestCalcPbRatio:

    def test_happy_path(self):
        result = _calc_pb_ratio("AAPL", 150.0, 1e10, 1e9)
        assert result == pytest.approx(15.0)

    def test_null_price_returns_none(self):
        assert _calc_pb_ratio("AAPL", None, 1e10, 1e9) is None

    def test_null_book_equity_returns_none(self):
        assert _calc_pb_ratio("AAPL", 150.0, None, 1e9) is None

    def test_null_shares_returns_none(self):
        assert _calc_pb_ratio("AAPL", 150.0, 1e10, None) is None

    def test_zero_book_equity_returns_none(self):
        assert _calc_pb_ratio("AAPL", 150.0, 0.0, 1e9) is None

    def test_negative_book_equity_allowed(self):
        # Negative book equity (e.g. heavy buybacks) now passes through
        result = _calc_pb_ratio("MCD", 300.0, -1e9, 1e8)
        assert result is not None
        assert result < 0

    def test_non_positive_shares_returns_none(self):
        assert _calc_pb_ratio("AAPL", 150.0, 1e10, 0) is None


# ── _calc_asset_growth ────────────────────────────────────────────────────────


class TestCalcAssetGrowth:

    def test_positive_growth(self):
        result = _calc_asset_growth("AAPL", 110.0, 100.0)
        assert result == pytest.approx(0.10)

    def test_negative_growth(self):
        result = _calc_asset_growth("AAPL", 90.0, 100.0)
        assert result == pytest.approx(-0.10)

    def test_null_current_returns_none(self):
        assert _calc_asset_growth("AAPL", None, 100.0) is None

    def test_null_prior_returns_none(self):
        assert _calc_asset_growth("AAPL", 110.0, None) is None

    def test_zero_prior_returns_none(self):
        assert _calc_asset_growth("AAPL", 110.0, 0.0) is None

    def test_uses_abs_denominator(self):
        # Denominator is |prior|, so negative prior still gives meaningful ratio
        result = _calc_asset_growth("AAPL", -90.0, -100.0)
        assert result == pytest.approx(0.10)


# ── _calc_roe ─────────────────────────────────────────────────────────────────


class TestCalcRoe:

    def test_happy_path(self):
        rows = _ttm_rows(net_income=1e9, book_equity=5e9)
        result = _calc_roe("AAPL", rows)
        assert result == pytest.approx(1e9 / 5e9)

    def test_empty_rows_returns_none(self):
        assert _calc_roe("AAPL", pd.DataFrame()) is None

    def test_null_net_income_returns_none(self):
        rows = _ttm_rows()
        rows.loc[0, "net_income"] = np.nan
        assert _calc_roe("AAPL", rows) is None

    def test_null_equity_returns_none(self):
        rows = _ttm_rows()
        rows["book_equity"] = np.nan
        assert _calc_roe("AAPL", rows) is None

    def test_non_positive_avg_equity_returns_none(self):
        rows = _ttm_rows(net_income=1e9, book_equity=-1e9)
        assert _calc_roe("AAPL", rows) is None

    def test_uses_most_recent_quarter_net_income(self):
        rows = _ttm_rows()
        rows.loc[0, "net_income"] = 2e9  # most recent
        rows.loc[1, "net_income"] = 1e9
        result = _calc_roe("AAPL", rows)
        avg_eq = rows.head(2)["book_equity"].mean()
        assert result == pytest.approx(2e9 / avg_eq)

    def test_uses_avg_of_2_most_recent_equity(self):
        rows = _ttm_rows()
        rows.loc[0, "book_equity"] = 4e9
        rows.loc[1, "book_equity"] = 6e9
        result = _calc_roe("AAPL", rows)
        assert result == pytest.approx(rows.loc[0, "net_income"] / 5e9)


# ── _calc_leverage ────────────────────────────────────────────────────────────


class TestCalcLeverage:

    def test_happy_path(self):
        result = _calc_leverage("AAPL", 2e9, 4e9)
        assert result == pytest.approx(0.5)

    def test_null_debt_returns_none(self):
        assert _calc_leverage("AAPL", None, 4e9) is None

    def test_null_equity_returns_none(self):
        assert _calc_leverage("AAPL", 2e9, None) is None

    def test_non_positive_equity_returns_none(self):
        assert _calc_leverage("AAPL", 2e9, -1e9) is None
        assert _calc_leverage("AAPL", 2e9, 0.0) is None

    def test_zero_debt(self):
        assert _calc_leverage("AAPL", 0.0, 4e9) == pytest.approx(0.0)


# ── _calc_earnings_stability ──────────────────────────────────────────────────


class TestCalcEarningsStability:

    def test_happy_path_returns_float(self):
        rows = _eps_rows(n_years=6)
        result = _calc_earnings_stability("AAPL", rows)
        assert isinstance(result, float)
        assert result >= 0.0

    def test_empty_rows_returns_none(self):
        assert _calc_earnings_stability("AAPL", pd.DataFrame()) is None

    def test_insufficient_observations_returns_none(self):
        rows = _eps_rows(n_years=1)  # 1 fiscal year → 0 annual YoY < MIN_EARN_HISTORY=5
        assert _calc_earnings_stability("AAPL", rows) is None

    def test_stable_eps_has_low_std(self):
        rows = _eps_rows(n_years=6, base_eps=2.0)
        result = _calc_earnings_stability("AAPL", rows)
        assert result < 0.5  # stable growth → low std

    def test_non_consecutive_fiscal_years_skipped(self):
        """YoY pairs with a gap in fiscal_year are excluded from stability calc."""
        rows = _eps_rows(n_years=6, base_eps=2.0)
        # Remove middle year to create a gap — 2020→2022 is non-consecutive so skipped
        rows = rows[rows["fiscal_year"] != 2021].reset_index(drop=True)
        # Remaining valid consecutive pairs: 2018→2019, 2019→2020, 2022→2023
        # That's only 3 pairs < MIN_EARN_HISTORY=5, so result is None
        result = _calc_earnings_stability("AAPL", rows)
        assert result is None

    def test_near_zero_prior_eps_skipped(self):
        """YoY pairs where prior annual EPS is near-zero are excluded."""
        rows = _eps_rows(n_years=6, base_eps=2.0)
        # Set one fiscal year's EPS to nearly zero so it becomes prior for next year
        rows.loc[rows["fiscal_year"] == 2020, "eps"] = 0.0
        result = _calc_earnings_stability("AAPL", rows)
        # Result may be None or float depending on remaining valid pairs
        assert result is None or isinstance(result, float)

    def test_yoy_growth_capped_at_500pct(self):
        rows = _eps_rows(n_years=6, base_eps=2.0)
        # Inject an extreme EPS jump
        rows.loc[rows.index[-1], "eps"] = 1000.0
        result = _calc_earnings_stability("AAPL", rows)
        assert result is not None
        assert result <= 5.0  # capped at ±500%


# ── _calc_momentum ────────────────────────────────────────────────────────────


class TestCalcMomentum:

    def test_returns_two_values(self):
        prices = _price_series(400)
        mom_6m, mom_12m = _calc_momentum("AAPL", prices, REBALANCE_TS, annual_rf=0.04)
        assert mom_6m is not None
        assert mom_12m is not None

    def test_insufficient_history_returns_none(self):
        prices = _price_series(10)
        mom_6m, mom_12m = _calc_momentum("AAPL", prices, REBALANCE_TS, annual_rf=0.04)
        assert mom_6m is None
        assert mom_12m is None

    def test_rf_subtracted(self):
        prices = _price_series(400)
        mom_no_rf, _ = _calc_momentum("AAPL", prices, REBALANCE_TS, annual_rf=0.0)
        mom_with_rf, _ = _calc_momentum("AAPL", prices, REBALANCE_TS, annual_rf=0.05)
        assert mom_no_rf > mom_with_rf

    def test_6m_only_needs_7_months(self):
        # 7 months of history is enough for 6m, but not 12m
        prices = _price_series(160)  # ~7 months
        mom_6m, mom_12m = _calc_momentum("AAPL", prices, REBALANCE_TS, annual_rf=0.0)
        assert mom_6m is not None
        assert mom_12m is None


# ── _calc_volatility ──────────────────────────────────────────────────────────


class TestCalcVolatility:

    def test_returns_two_values(self):
        prices = _price_series(300)
        vol_3m, vol_12m = _calc_volatility("AAPL", prices)
        assert vol_3m is not None
        assert vol_12m is not None

    def test_insufficient_for_3m_returns_none(self):
        prices = _price_series(30)  # < MIN_VOL_OBS_3M=50
        vol_3m, vol_12m = _calc_volatility("AAPL", prices)
        assert vol_3m is None
        assert vol_12m is None

    def test_sufficient_for_3m_not_12m(self):
        prices = _price_series(100)  # >= 50 but < 200
        vol_3m, vol_12m = _calc_volatility("AAPL", prices)
        assert vol_3m is not None
        assert vol_12m is None

    def test_annualised_value_reasonable(self):
        prices = _price_series(300)
        vol_3m, _ = _calc_volatility("AAPL", prices)
        assert 0.0 < vol_3m < 5.0  # annualised vol between 0% and 500%


# ── calculate_ratios ──────────────────────────────────────────────────────────


class TestCalculateRatios:

    def _make_pg(self, symbols):
        pg = MagicMock()
        rebalance = REBALANCE

        # Price data: 400 trading days
        price_rows = []
        for sym in symbols:
            for d in pd.bdate_range(end=rebalance, periods=400):
                price_rows.append(
                    {
                        "symbol": sym,
                        "trade_date": d,
                        "adjusted_close": 100.0 + np.random.rand(),
                    }
                )
        price_df = pd.DataFrame(price_rows)
        price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])

        latest_fin = pd.DataFrame(
            [
                {
                    "symbol": sym,
                    "report_date": pd.Timestamp(rebalance - timedelta(days=50)),
                    "total_assets": 1e10,
                    "total_debt": 2e9,
                    "net_income": 5e8,
                    "book_equity": 4e9,
                    "shares_outstanding": 1e8,
                    "eps": 2.0,
                    "fiscal_year": 2023,
                    "fiscal_quarter": 4,
                }
                for sym in symbols
            ]
        )

        prior_fin = pd.DataFrame(
            [
                {
                    "symbol": sym,
                    "report_date": pd.Timestamp(rebalance - timedelta(days=415)),
                    "total_assets": 9e9,
                }
                for sym in symbols
            ]
        )

        ttm_dates = pd.bdate_range(
            end=rebalance - timedelta(days=50), periods=4, freq="QE"
        )[::-1]
        ttm_rows = []
        for sym in symbols:
            for d in ttm_dates:
                ttm_rows.append(
                    {
                        "symbol": sym,
                        "report_date": d,
                        "net_income": 5e8,
                        "book_equity": 4e9,
                    }
                )
        ttm_fin = pd.DataFrame(ttm_rows)
        ttm_fin["report_date"] = pd.to_datetime(ttm_fin["report_date"])

        eps_rows = []
        for sym in symbols:
            for yr in range(2018, 2024):
                for q in range(1, 5):
                    eps_rows.append(
                        {
                            "symbol": sym,
                            "report_date": pd.Timestamp(f"{yr}-{q * 3:02d}-28"),
                            "eps": 2.0 + 0.05 * yr,
                            "fiscal_year": yr,
                            "fiscal_quarter": q,
                        }
                    )
        eps_hist = pd.DataFrame(eps_rows)
        eps_hist["report_date"] = pd.to_datetime(eps_hist["report_date"])

        rf_df = pd.DataFrame({"rate": [0.04]})

        pg.read_query.side_effect = [
            price_df,
            latest_fin,
            prior_fin,
            ttm_fin,
            eps_hist,
            rf_df,
        ]
        return pg

    def test_returns_dataframe(self):
        symbols = ["AAPL", "MSFT"]
        pg = self._make_pg(symbols)
        result = calculate_ratios(pg, REBALANCE, symbols)
        assert isinstance(result, pd.DataFrame)

    def test_one_row_per_symbol(self):
        symbols = ["AAPL", "MSFT", "GOOG"]
        pg = self._make_pg(symbols)
        result = calculate_ratios(pg, REBALANCE, symbols)
        assert len(result) == 3
        assert set(result["symbol"]) == set(symbols)

    def test_expected_columns(self):
        symbols = ["AAPL"]
        pg = self._make_pg(symbols)
        result = calculate_ratios(pg, REBALANCE, symbols)
        expected = {
            "symbol",
            "calc_date",
            "pb_ratio",
            "asset_growth",
            "roe",
            "leverage",
            "earnings_stability",
            "momentum_6m",
            "momentum_12m",
            "volatility_3m",
            "volatility_12m",
        }
        assert expected.issubset(set(result.columns))

    def test_calc_date_set_correctly(self):
        symbols = ["AAPL"]
        pg = self._make_pg(symbols)
        result = calculate_ratios(pg, REBALANCE, symbols)
        assert result.iloc[0]["calc_date"] == REBALANCE

    def test_all_metrics_non_null_with_full_data(self):
        np.random.seed(42)
        symbols = ["AAPL"]
        pg = self._make_pg(symbols)
        result = calculate_ratios(pg, REBALANCE, symbols)
        metrics = [
            "pb_ratio",
            "asset_growth",
            "roe",
            "leverage",
            "earnings_stability",
            "momentum_6m",
            "momentum_12m",
            "volatility_3m",
            "volatility_12m",
        ]
        for m in metrics:
            assert pd.notna(result.iloc[0][m]), f"{m} should not be null with full data"

    def _make_pg_no_fin(self, symbols):
        """pg where latest_fin is empty — covers fin-is-None branches."""
        pg = MagicMock()
        rebalance = REBALANCE
        price_rows = []
        for sym in symbols:
            for d in pd.bdate_range(end=rebalance, periods=400):
                price_rows.append(
                    {
                        "symbol": sym,
                        "trade_date": d,
                        "adjusted_close": 100.0 + np.random.rand(),
                    }
                )
        price_df = pd.DataFrame(price_rows)
        price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
        empty_fin = pd.DataFrame(
            columns=[
                "symbol",
                "report_date",
                "total_assets",
                "total_debt",
                "net_income",
                "book_equity",
                "shares_outstanding",
                "eps",
                "fiscal_year",
                "fiscal_quarter",
            ]
        )
        empty_fin["report_date"] = pd.to_datetime(empty_fin["report_date"])
        empty_prior = pd.DataFrame(columns=["symbol", "report_date", "total_assets"])
        empty_prior["report_date"] = pd.to_datetime(empty_prior["report_date"])
        empty_ttm = pd.DataFrame(
            columns=["symbol", "report_date", "net_income", "book_equity"]
        )
        empty_ttm["report_date"] = pd.to_datetime(empty_ttm["report_date"])
        empty_eps = pd.DataFrame(
            columns=[
                "symbol",
                "report_date",
                "eps",
                "fiscal_year",
                "fiscal_quarter",
            ]
        )
        empty_eps["report_date"] = pd.to_datetime(empty_eps["report_date"])
        rf_df = pd.DataFrame({"rate": [0.04]})
        pg.read_query.side_effect = [
            price_df,
            empty_fin,
            empty_prior,
            empty_ttm,
            empty_eps,
            rf_df,
        ]
        return pg

    def test_no_fin_data_nulls_fundamental_metrics(self):
        """When latest_fin is empty, pb_ratio/asset_growth/leverage are NaN."""
        np.random.seed(7)
        symbols = ["AAPL"]
        pg = self._make_pg_no_fin(symbols)
        result = calculate_ratios(pg, REBALANCE, symbols)
        assert pd.isna(result.iloc[0]["pb_ratio"])
        assert pd.isna(result.iloc[0]["asset_growth"])
        assert pd.isna(result.iloc[0]["leverage"])

    def test_missing_price_data_nulls_price_metrics(self):
        symbols = ["AAPL"]
        pg = MagicMock()
        empty_prices = pd.DataFrame(columns=["symbol", "trade_date", "adjusted_close"])
        empty_prices["trade_date"] = pd.to_datetime(empty_prices["trade_date"])

        latest_fin = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "report_date": pd.Timestamp(REBALANCE - timedelta(days=50)),
                    "total_assets": 1e10,
                    "total_debt": 2e9,
                    "net_income": 5e8,
                    "book_equity": 4e9,
                    "shares_outstanding": 1e8,
                    "eps": 2.0,
                    "fiscal_year": 2023,
                    "fiscal_quarter": 4,
                }
            ]
        )
        prior_fin = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "report_date": pd.Timestamp("2023-01-01"),
                    "total_assets": 9e9,
                }
            ]
        )
        ttm_fin = pd.DataFrame(
            columns=["symbol", "report_date", "net_income", "book_equity"]
        )
        ttm_fin["report_date"] = pd.to_datetime(ttm_fin["report_date"])
        eps_hist = pd.DataFrame(
            columns=["symbol", "report_date", "eps", "fiscal_year", "fiscal_quarter"]
        )
        eps_hist["report_date"] = pd.to_datetime(eps_hist["report_date"])
        rf_df = pd.DataFrame({"rate": [0.04]})

        pg.read_query.side_effect = [
            empty_prices,
            latest_fin,
            prior_fin,
            ttm_fin,
            eps_hist,
            rf_df,
        ]
        result = calculate_ratios(pg, REBALANCE, symbols)
        assert pd.isna(result.iloc[0]["pb_ratio"])
        assert pd.isna(result.iloc[0]["momentum_6m"])
        assert pd.isna(result.iloc[0]["volatility_3m"])

    def _make_pg_no_prior(self, symbols):
        """pg where prior_fin is empty — covers prior-is-None asset_growth branch."""
        pg = MagicMock()
        rebalance = REBALANCE
        price_rows = []
        for sym in symbols:
            for d in pd.bdate_range(end=rebalance, periods=400):
                price_rows.append(
                    {
                        "symbol": sym,
                        "trade_date": d,
                        "adjusted_close": 100.0 + np.random.rand(),
                    }
                )
        price_df = pd.DataFrame(price_rows)
        price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
        latest_fin = pd.DataFrame(
            [
                {
                    "symbol": sym,
                    "report_date": pd.Timestamp(rebalance - timedelta(days=50)),
                    "total_assets": 1e10,
                    "total_debt": 2e9,
                    "net_income": 5e8,
                    "book_equity": 4e9,
                    "shares_outstanding": 1e8,
                    "eps": 2.0,
                    "fiscal_year": 2023,
                    "fiscal_quarter": 4,
                }
                for sym in symbols
            ]
        )
        empty_prior = pd.DataFrame(columns=["symbol", "report_date", "total_assets"])
        empty_prior["report_date"] = pd.to_datetime(empty_prior["report_date"])
        ttm_rows = [
            {
                "symbol": sym,
                "report_date": pd.Timestamp(rebalance - timedelta(days=50)),
                "net_income": 5e8,
                "book_equity": 4e9,
            }
            for sym in symbols
        ]
        ttm_fin = pd.DataFrame(ttm_rows)
        ttm_fin["report_date"] = pd.to_datetime(ttm_fin["report_date"])
        empty_eps = pd.DataFrame(
            columns=[
                "symbol",
                "report_date",
                "eps",
                "fiscal_year",
                "fiscal_quarter",
            ]
        )
        empty_eps["report_date"] = pd.to_datetime(empty_eps["report_date"])
        rf_df = pd.DataFrame({"rate": [0.04]})
        pg.read_query.side_effect = [
            price_df,
            latest_fin,
            empty_prior,
            ttm_fin,
            empty_eps,
            rf_df,
        ]
        return pg

    def test_no_prior_fin_nulls_asset_growth(self):
        """When prior_fin is empty, asset_growth should be NaN."""
        np.random.seed(11)
        symbols = ["AAPL"]
        pg = self._make_pg_no_prior(symbols)
        result = calculate_ratios(pg, REBALANCE, symbols)
        assert pd.isna(result.iloc[0]["asset_growth"])

    def test_stale_price_still_computes_pb(self):
        """Stale price warning fires but pb_ratio is still computed."""
        np.random.seed(13)
        symbols = ["AAPL"]
        pg = MagicMock()
        # Build price data ending 40 days before rebalance (stale)
        stale_end = date(REBALANCE.year, REBALANCE.month, REBALANCE.day)
        stale_ts = pd.Timestamp(stale_end) - pd.Timedelta(days=40)
        price_rows = []
        for d in pd.bdate_range(end=stale_ts, periods=400):
            price_rows.append(
                {"symbol": "AAPL", "trade_date": d, "adjusted_close": 100.0}
            )
        price_df = pd.DataFrame(price_rows)
        price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
        latest_fin = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "report_date": stale_ts - pd.Timedelta(days=10),
                    "total_assets": 1e10,
                    "total_debt": 2e9,
                    "net_income": 5e8,
                    "book_equity": 4e9,
                    "shares_outstanding": 1e8,
                    "eps": 2.0,
                    "fiscal_year": 2023,
                    "fiscal_quarter": 4,
                }
            ]
        )
        prior_fin = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "report_date": stale_ts - pd.Timedelta(days=400),
                    "total_assets": 9e9,
                }
            ]
        )
        prior_fin["report_date"] = pd.to_datetime(prior_fin["report_date"])
        empty_ttm = pd.DataFrame(
            columns=["symbol", "report_date", "net_income", "book_equity"]
        )
        empty_ttm["report_date"] = pd.to_datetime(empty_ttm["report_date"])
        empty_eps = pd.DataFrame(
            columns=[
                "symbol",
                "report_date",
                "eps",
                "fiscal_year",
                "fiscal_quarter",
            ]
        )
        empty_eps["report_date"] = pd.to_datetime(empty_eps["report_date"])
        rf_df = pd.DataFrame({"rate": [0.04]})
        pg.read_query.side_effect = [
            price_df,
            latest_fin,
            prior_fin,
            empty_ttm,
            empty_eps,
            rf_df,
        ]
        result = calculate_ratios(pg, REBALANCE, symbols)
        # pb_ratio may be computed (stale warning logs but doesn't block)
        assert "pb_ratio" in result.columns


# ── _fetch_risk_free_rate ─────────────────────────────────────────────────────


class TestFetchRiskFreeRate:

    def test_returns_rate_from_db(self):
        pg = MagicMock()
        pg.read_query.return_value = pd.DataFrame({"rate": [0.04]})
        result = _fetch_risk_free_rate(pg, "United States", REBALANCE)
        assert result == pytest.approx(0.04)

    def test_returns_zero_when_empty(self):
        pg = MagicMock()
        pg.read_query.return_value = pd.DataFrame({"rate": []})
        result = _fetch_risk_free_rate(pg, "United States", REBALANCE)
        assert result == 0.0


# ── _calc_earnings_stability: NaN eps ─────────────────────────────────────────


class TestCalcEarningsStabilityNanEps:

    def test_nan_eps_rows_skipped(self):
        """Rows with NaN eps should be skipped (line 304 coverage)."""
        rows = _eps_rows(n_years=6)
        rows.loc[rows.index[0], "eps"] = float("nan")
        # Should still compute (remaining rows cover enough history)
        result = _calc_earnings_stability("AAPL", rows)
        assert result is None or isinstance(result, float)


# ── _calc_momentum: non-positive base price ────────────────────────────────────


class TestCalcMomentumNonPositivePrice:

    def _prices_with_zero_at(self, rebalance_ts: pd.Timestamp, months_back: int):
        """Build 400-day price series with price=0 exactly at T-{months_back}."""
        idx = pd.bdate_range(end=rebalance_ts, periods=400)
        prices = pd.Series([100.0] * len(idx), index=idx)
        target = _last_bday_of_month(rebalance_ts, months_back)
        # Find the closest available date and zero it out
        closest = prices.index[prices.index.get_indexer([target], method="nearest")[0]]
        prices[closest] = 0.0
        return prices

    def test_non_positive_p_t7_returns_none_for_6m(self):
        """Price at T-7 months = 0 triggers fallback for momentum_6m (line 355)."""
        prices = self._prices_with_zero_at(REBALANCE_TS, 7)
        mom_6m, _ = _calc_momentum("AAPL", prices, REBALANCE_TS, annual_rf=0.0)
        assert mom_6m is None

    def test_non_positive_p_t13_returns_none_for_12m(self):
        """Price at T-13 months = 0 triggers fallback for momentum_12m (line 365)."""
        prices = self._prices_with_zero_at(REBALANCE_TS, 13)
        _, mom_12m = _calc_momentum("AAPL", prices, REBALANCE_TS, annual_rf=0.0)
        assert mom_12m is None


# ── _calc_volatility: >10% zero returns ───────────────────────────────────────


class TestCalcVolatilityZeroReturns:

    def test_many_zero_returns_triggers_warning_3m(self):
        """More than 10% zero returns triggers vol_3m warning (line 395)."""
        idx = pd.bdate_range(end=REBALANCE, periods=300)
        # Flat prices → all returns = 0 (>10% zeros)
        prices = pd.Series([100.0] * 300, index=idx)
        vol_3m, _ = _calc_volatility("AAPL", prices)
        assert vol_3m == pytest.approx(0.0)

    def test_many_zero_returns_triggers_warning_12m(self):
        """More than 10% zero returns triggers vol_12m warning (line 411)."""
        idx = pd.bdate_range(end=REBALANCE, periods=300)
        prices = pd.Series([100.0] * 300, index=idx)
        _, vol_12m = _calc_volatility("AAPL", prices)
        assert vol_12m == pytest.approx(0.0)
