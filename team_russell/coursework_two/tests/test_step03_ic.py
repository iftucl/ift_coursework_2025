"""Tests for step03_ic_analysis.py — IC computation and performance stats."""

import numpy as np
import pandas as pd
import pytest
import step03_ic_analysis as s03

# ── compute_ic ────────────────────────────────────────────────────────────────


class TestComputeIc:
    def _make_df(self, n_periods=4, n_stocks=30, seed=0):
        np.random.seed(seed)
        rows = []
        periods = [
            ("2022-03-31", "2022-06-30"),
            ("2022-06-30", "2022-09-30"),
            ("2022-09-30", "2022-12-31"),
            ("2022-12-31", "2023-03-31"),
        ][:n_periods]
        for s, e in periods:
            scores = np.random.randn(n_stocks)
            returns = scores * 0.02 + np.random.randn(n_stocks) * 0.05
            for i in range(n_stocks):
                rows.append(
                    {
                        "start_date": pd.Timestamp(s),
                        "end_date": pd.Timestamp(e),
                        "composite_score": scores[i],
                        "gross_return": returns[i],
                        "quintile": (i % 5) + 1,
                    }
                )
        return pd.DataFrame(rows)

    def test_returns_dataframe(self):
        df = self._make_df()
        result = s03.compute_ic(df)
        assert isinstance(result, pd.DataFrame)

    def test_one_row_per_period(self):
        df = self._make_df(n_periods=4)
        result = s03.compute_ic(df)
        assert len(result) == 4

    def test_ic_column_present(self):
        df = self._make_df()
        result = s03.compute_ic(df)
        assert "ic" in result.columns

    def test_p_value_column_present(self):
        df = self._make_df()
        result = s03.compute_ic(df)
        assert "p_value" in result.columns

    def test_ic_range(self):
        df = self._make_df()
        result = s03.compute_ic(df)
        assert (result["ic"].dropna().abs() <= 1.0).all()

    def test_positive_signal_has_positive_mean_ic(self):
        # Strong positive signal: score directly predicts return
        np.random.seed(42)
        rows = []
        for period in range(6):
            s = pd.Timestamp("2022-01-01") + pd.DateOffset(months=3 * period)
            e = s + pd.DateOffset(months=3)
            scores = np.linspace(-2, 2, 50)
            returns = scores * 0.05 + np.random.randn(50) * 0.01
            for i in range(50):
                rows.append(
                    {
                        "start_date": s,
                        "end_date": e,
                        "composite_score": scores[i],
                        "gross_return": returns[i],
                        "quintile": (i % 5) + 1,
                    }
                )
        df = pd.DataFrame(rows)
        result = s03.compute_ic(df)
        assert result["ic"].mean() > 0

    def test_handles_single_period(self):
        df = self._make_df(n_periods=1)
        result = s03.compute_ic(df)
        assert len(result) == 1

    def test_n_stocks_column_present(self):
        df = self._make_df()
        result = s03.compute_ic(df)
        assert "n_stocks" in result.columns

    def test_period_with_fewer_than_10_stocks_skipped(self):
        # 4 stocks in period 1 → skipped; 30 stocks in period 2 → included
        rows = []
        for i in range(4):
            rows.append(
                {
                    "start_date": pd.Timestamp("2022-03-31"),
                    "end_date": pd.Timestamp("2022-06-30"),
                    "composite_score": float(i),
                    "gross_return": float(i) * 0.01,
                    "quintile": (i % 5) + 1,
                }
            )
        for i in range(30):
            rows.append(
                {
                    "start_date": pd.Timestamp("2022-06-30"),
                    "end_date": pd.Timestamp("2022-09-30"),
                    "composite_score": float(i),
                    "gross_return": float(i) * 0.02,
                    "quintile": (i % 5) + 1,
                }
            )
        df = pd.DataFrame(rows)
        result = s03.compute_ic(df)
        # Only the second period should appear — first skipped due to < 10 stocks
        assert len(result) == 1
        assert result.iloc[0]["start_date"] == pd.Timestamp("2022-06-30")


# ── print_performance_table (smoke test) ──────────────────────────────────────


class TestPrintPerformanceTable:
    def _make_inputs(self):
        np.random.seed(5)
        rows = []
        periods = [
            ("2022-03-31", "2022-06-30"),
            ("2022-06-30", "2022-09-30"),
        ]
        for s, e in periods:
            for q in range(1, 6):
                for i in range(10):
                    gross = np.random.uniform(-0.05, 0.10)
                    rows.append(
                        {
                            "start_date": pd.Timestamp(s),
                            "end_date": pd.Timestamp(e),
                            "quintile": q,
                            "composite_score": np.random.randn(),
                            "gross_return": gross,
                            "net_return": gross - 0.004,
                        }
                    )
        df = pd.DataFrame(rows)
        scores = np.random.randn(len(periods))
        ic_df = pd.DataFrame(
            {
                "start_date": [pd.Timestamp(p[0]) for p in periods],
                "end_date": [pd.Timestamp(p[1]) for p in periods],
                "ic": scores,
                "p_value": [0.1, 0.4],
                "n_stocks": [50, 50],
                "significant": [False, False],
            }
        )
        return df, ic_df

    def test_does_not_raise(self, capsys):
        df, ic_df = self._make_inputs()
        s03.print_performance_table(df, ic_df)
        captured = capsys.readouterr()
        assert "Q1" in captured.out
