"""Tests for step04_turnover.py — turnover and sector weight computations."""

import numpy as np
import pandas as pd
import pytest
import step04_turnover as s04

# ── compute_turnover ──────────────────────────────────────────────────────────


class TestComputeTurnover:
    def _make_df(self, memberships_by_period):
        """Build a returns-style DataFrame from {date: [symbols]} dict."""
        rows = []
        dates = sorted(memberships_by_period.keys())
        for i, d in enumerate(dates):
            end = dates[i + 1] if i + 1 < len(dates) else d + pd.DateOffset(months=3)
            symbols = memberships_by_period[d]
            for sym in symbols:
                rows.append(
                    {
                        "start_date": d,
                        "end_date": end,
                        "symbol": sym,
                        "quintile": 1,
                        "gross_return": 0.02,
                        "net_return": 0.016,
                    }
                )
        return pd.DataFrame(rows)

    def test_zero_turnover_when_identical(self):
        d1 = pd.Timestamp("2022-03-31")
        d2 = pd.Timestamp("2022-06-30")
        symbols = [f"SYM{i}" for i in range(20)]
        df = self._make_df({d1: symbols, d2: symbols})
        result = s04.compute_turnover(df)
        assert len(result) == 1
        assert result.iloc[0]["turnover_rate"] == pytest.approx(0.0)

    def test_full_turnover_when_disjoint(self):
        d1 = pd.Timestamp("2022-03-31")
        d2 = pd.Timestamp("2022-06-30")
        symbols_1 = [f"OLD{i}" for i in range(20)]
        symbols_2 = [f"NEW{i}" for i in range(20)]
        df = self._make_df({d1: symbols_1, d2: symbols_2})
        result = s04.compute_turnover(df)
        assert result.iloc[0]["turnover_rate"] == pytest.approx(100.0)

    def test_partial_turnover(self):
        d1 = pd.Timestamp("2022-03-31")
        d2 = pd.Timestamp("2022-06-30")
        old = [f"STAY{i}" for i in range(10)] + [f"OLD{i}" for i in range(10)]
        new = [f"STAY{i}" for i in range(10)] + [f"NEW{i}" for i in range(10)]
        df = self._make_df({d1: old, d2: new})
        result = s04.compute_turnover(df)
        assert 0 < result.iloc[0]["turnover_rate"] < 100

    def test_returns_one_fewer_rows_than_periods(self):
        dates = [pd.Timestamp("2022-03-31") + pd.DateOffset(months=3 * i) for i in range(4)]
        d = {dt: [f"SYM{j}" for j in range(20)] for dt in dates}
        df = self._make_df(d)
        result = s04.compute_turnover(df)
        assert len(result) == len(dates) - 1

    def test_has_required_columns(self):
        d1 = pd.Timestamp("2022-03-31")
        d2 = pd.Timestamp("2022-06-30")
        df = self._make_df({d1: ["A", "B", "C", "D", "E"] * 4, d2: ["A", "B", "C", "D", "E"] * 4})
        result = s04.compute_turnover(df)
        for col in ["turnover_rate"]:
            assert col in result.columns


# ── compute_sector_weights ────────────────────────────────────────────────────


class TestComputeSectorWeights:
    def _make_sector_df(self):
        np.random.seed(3)
        periods = [
            ("2022-03-31", "2022-06-30"),
            ("2022-06-30", "2022-09-30"),
        ]
        sectors = ["Technology", "Financials", "Health Care", "Industrials", "Energy"]
        rows = []
        for s, e in periods:
            for q in range(1, 6):
                for i in range(10):
                    rows.append(
                        {
                            "start_date": pd.Timestamp(s),
                            "end_date": pd.Timestamp(e),
                            "symbol": f"Q{q}SYM{i:02d}",
                            "quintile": q,
                            "gross_return": 0.02,
                            "net_return": 0.016,
                        }
                    )
        return pd.DataFrame(rows)

    def _make_sector_map(self):
        sectors = ["Technology", "Financials", "Health Care", "Industrials", "Energy"]
        return {
            f"Q{q}SYM{i:02d}": sectors[i % len(sectors)] for q in range(1, 6) for i in range(10)
        }

    def test_returns_dataframe(self):
        df = self._make_sector_df()
        sector_map = self._make_sector_map()
        result = s04.compute_sector_weights(df, sector_map)
        assert isinstance(result, pd.DataFrame)

    def test_has_required_columns(self):
        df = self._make_sector_df()
        sector_map = self._make_sector_map()
        result = s04.compute_sector_weights(df, sector_map)
        for col in ["sector", "w_q1", "w_universe"]:
            assert col in result.columns

    def test_weights_sum_to_100_per_period(self):
        df = self._make_sector_df()
        sector_map = self._make_sector_map()
        result = s04.compute_sector_weights(df, sector_map)
        for period, grp in result.groupby("period_date"):
            assert grp["w_q1"].sum() == pytest.approx(100.0, abs=0.1)

    def test_active_weight_is_q1_minus_universe(self):
        df = self._make_sector_df()
        sector_map = self._make_sector_map()
        result = s04.compute_sector_weights(df, sector_map)
        assert "active_weight" in result.columns
        expected = result["w_q1"] - result["w_universe"]
        pd.testing.assert_series_equal(
            result["active_weight"].round(6),
            expected.round(6),
            check_names=False,
        )

    def test_empty_sector_map_returns_empty_dataframe(self):
        df = self._make_sector_df()
        result = s04.compute_sector_weights(df, {})
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_unknown_sector_excluded_from_output(self):
        # Stocks mapped to "Unknown" should not appear as a sector row
        df = self._make_sector_df()
        # Map every symbol to Unknown
        all_syms = df["symbol"].unique()
        unknown_map = {sym: "Unknown" for sym in all_syms}
        result = s04.compute_sector_weights(df, unknown_map)
        # No non-Unknown sector → no rows
        assert result.empty or "Unknown" not in result["sector"].values

    def test_period_with_no_q1_stocks_skipped(self):
        # All stocks in Q5 — no quintile==1 rows → total_q1 == 0 → period skipped
        df = pd.DataFrame(
            {
                "start_date": [pd.Timestamp("2022-03-31")] * 10,
                "end_date": [pd.Timestamp("2022-06-30")] * 10,
                "symbol": [f"S{i}" for i in range(10)],
                "quintile": [5] * 10,  # all Q5, none Q1
                "gross_return": [0.02] * 10,
                "net_return": [0.016] * 10,
            }
        )
        sector_map = {f"S{i}": "Technology" for i in range(10)}
        result = s04.compute_sector_weights(df, sector_map)
        assert result.empty
