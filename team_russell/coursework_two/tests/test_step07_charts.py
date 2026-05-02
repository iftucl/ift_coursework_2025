"""Tests for step07_final_charts.py — make_nav, shade_regimes, compute_annual_returns."""

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import step07_final_charts as s07

# ── shared fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def returns_df():
    """6-period returns DataFrame with 5 quintiles, 10 stocks each."""
    np.random.seed(7)
    periods = [
        (
            pd.Timestamp("2022-03-31") + pd.DateOffset(months=3 * i),
            pd.Timestamp("2022-06-30") + pd.DateOffset(months=3 * i),
        )
        for i in range(6)
    ]
    rows = []
    for s, e in periods:
        for q in range(1, 6):
            for i in range(10):
                rows.append(
                    {
                        "symbol": f"Q{q}SYM{i:02d}",
                        "start_date": s,
                        "end_date": e,
                        "quintile": q,
                        "gross_return": np.random.uniform(-0.05, 0.12),
                    }
                )
    return pd.DataFrame(rows)


# ── make_nav ──────────────────────────────────────────────────────────────────


class TestMakeNav:
    def test_returns_two_items(self, returns_df):
        result = s07.make_nav(returns_df, quintile=1)
        assert len(result) == 2

    def test_dates_is_list(self, returns_df):
        dates, _ = s07.make_nav(returns_df, quintile=1)
        assert isinstance(dates, list)

    def test_nav_is_array(self, returns_df):
        _, nav = s07.make_nav(returns_df, quintile=1)
        assert isinstance(nav, np.ndarray)

    def test_nav_starts_at_100(self, returns_df):
        _, nav = s07.make_nav(returns_df, quintile=1)
        assert nav[0] == pytest.approx(100.0)

    def test_dates_and_nav_same_length(self, returns_df):
        dates, nav = s07.make_nav(returns_df, quintile=1)
        assert len(dates) == len(nav)

    def test_nav_length_is_periods_plus_one(self, returns_df):
        n_periods = returns_df["start_date"].nunique()
        _, nav = s07.make_nav(returns_df, quintile=1)
        assert len(nav) == n_periods + 1

    def test_nav_always_positive(self, returns_df):
        for q in range(1, 6):
            _, nav = s07.make_nav(returns_df, q)
            assert (nav > 0).all()

    def test_positive_returns_nav_above_100(self):
        """All large positive gross returns -> final NAV > 100."""
        periods = [
            (pd.Timestamp("2022-03-31"), pd.Timestamp("2022-06-30")),
            (pd.Timestamp("2022-06-30"), pd.Timestamp("2022-09-30")),
        ]
        rows = []
        for s, e in periods:
            for i in range(5):
                rows.append(
                    {
                        "symbol": f"SYM{i}",
                        "start_date": s,
                        "end_date": e,
                        "quintile": 1,
                        "gross_return": 0.10,  # 10% per quarter well above TC
                    }
                )
        df = pd.DataFrame(rows)
        _, nav = s07.make_nav(df, quintile=1)
        assert nav[-1] > 100.0

    def test_negative_returns_nav_below_100(self):
        """Consistent negative gross returns (below TC threshold) -> final NAV < 100."""
        periods = [
            (pd.Timestamp("2022-03-31"), pd.Timestamp("2022-06-30")),
            (pd.Timestamp("2022-06-30"), pd.Timestamp("2022-09-30")),
        ]
        rows = []
        for s, e in periods:
            for i in range(5):
                rows.append(
                    {
                        "symbol": f"SYM{i}",
                        "start_date": s,
                        "end_date": e,
                        "quintile": 1,
                        "gross_return": -0.05,  # -5% gross + TC -> clearly negative net
                    }
                )
        df = pd.DataFrame(rows)
        _, nav = s07.make_nav(df, quintile=1)
        assert nav[-1] < 100.0

    def test_only_filters_correct_quintile(self, returns_df):
        """NAV for Q1 and Q5 differ when returns differ."""
        _, nav_q1 = s07.make_nav(returns_df, quintile=1)
        _, nav_q5 = s07.make_nav(returns_df, quintile=5)
        # With different random returns, the two NAVs should differ
        assert not np.allclose(nav_q1, nav_q5)

    def test_tc_deduction_applied(self):
        """Net return should be gross - TC; verify NAV compounds net correctly."""
        s, e = pd.Timestamp("2022-03-31"), pd.Timestamp("2022-06-30")
        gross = 0.05
        rows = [
            {
                "symbol": f"SYM{i}",
                "start_date": s,
                "end_date": e,
                "quintile": 1,
                "gross_return": gross,
            }
            for i in range(5)
        ]
        df = pd.DataFrame(rows)
        _, nav = s07.make_nav(df, quintile=1)
        expected_final = 100 * (1 + gross - s07.TC_RT)
        assert nav[-1] == pytest.approx(expected_final)

    def test_dates_first_element_is_start_date(self, returns_df):
        dates, _ = s07.make_nav(returns_df, quintile=1)
        first_start = returns_df["start_date"].min()
        assert dates[0] == first_start


# ── shade_regimes ─────────────────────────────────────────────────────────────


class TestShadeRegimes:
    def _make_ax(self):
        fig, ax = plt.subplots()
        return fig, ax

    def test_no_exception(self):
        fig, ax = self._make_ax()
        s07.shade_regimes(ax)  # should not raise
        plt.close(fig)

    def test_adds_patches(self):
        fig, ax = self._make_ax()
        before = len(ax.patches)
        s07.shade_regimes(ax)
        after = len(ax.patches)
        assert after > before
        plt.close(fig)

    def test_adds_three_shaded_regions(self):
        fig, ax = self._make_ax()
        s07.shade_regimes(ax)
        # Each regime adds one axvspan (a Polygon patch)
        assert len(ax.patches) == 3
        plt.close(fig)

    def test_adds_text_labels(self):
        fig, ax = self._make_ax()
        s07.shade_regimes(ax)
        # Should add one text annotation per regime
        assert len(ax.texts) == 3
        plt.close(fig)

    def test_text_labels_nonempty(self):
        fig, ax = self._make_ax()
        s07.shade_regimes(ax)
        for txt in ax.texts:
            assert txt.get_text().strip() != ""
        plt.close(fig)

    def test_no_figures_left_open(self):
        fig, ax = self._make_ax()
        before = len(plt.get_fignums())
        s07.shade_regimes(ax)
        after = len(plt.get_fignums())
        assert after == before  # shade_regimes doesn't create new figures
        plt.close(fig)


# ── compute_annual_returns ─────────────────────────────────────────────────────


def _make_annual_df(year=2020, q1_gross=0.06, other_gross=0.04, n_quarters=4):
    """Build a minimal DataFrame for annual return tests.

    Q1 stocks use q1_gross; Q2-Q5 use other_gross.
    All quarters end within `year` so they map to a single REGIMES entry.
    """
    rows = []
    for q_idx in range(n_quarters):
        s = pd.Timestamp(f"{year}-01-01") + pd.DateOffset(months=3 * q_idx)
        e = s + pd.DateOffset(months=3) - pd.DateOffset(days=1)
        # Clamp end_date so it stays within the target year
        if e.year > year:
            e = pd.Timestamp(f"{year}-12-31")
        for quintile in range(1, 6):
            gross = q1_gross if quintile == 1 else other_gross
            for i in range(4):
                rows.append(
                    {
                        "symbol": f"Q{quintile}SYM{i}",
                        "start_date": s,
                        "end_date": e,
                        "quintile": quintile,
                        "gross_return": gross,
                    }
                )
    return pd.DataFrame(rows)


class TestComputeAnnualReturns:
    def test_returns_dataframe(self):
        df = _make_annual_df()
        result = s07.compute_annual_returns(df)
        assert isinstance(result, pd.DataFrame)

    def test_expected_columns_present(self):
        df = _make_annual_df()
        result = s07.compute_annual_returns(df)
        for col in ("year", "q1_gross", "q1_net", "ew_net", "vs_bm", "result", "regime"):
            assert col in result.columns

    def test_one_row_per_year(self):
        df = pd.concat([_make_annual_df(2020), _make_annual_df(2021)], ignore_index=True)
        result = s07.compute_annual_returns(df)
        assert len(result) == 2

    def test_sorted_ascending_by_year(self):
        df = pd.concat([_make_annual_df(2021), _make_annual_df(2020)], ignore_index=True)
        result = s07.compute_annual_returns(df)
        assert list(result["year"]) == [2020, 2021]

    def test_vs_bm_up_when_q1_beats_ew(self):
        # Q1 gross (0.06) > EW gross blend → Q1 net > EW net
        df = _make_annual_df(q1_gross=0.06, other_gross=0.04)
        result = s07.compute_annual_returns(df)
        assert result.iloc[0]["vs_bm"] == "▲"

    def test_vs_bm_down_when_q1_lags_ew(self):
        # Q1 gross (0.02) < EW gross blend → Q1 net < EW net
        df = _make_annual_df(q1_gross=0.02, other_gross=0.08)
        result = s07.compute_annual_returns(df)
        assert result.iloc[0]["vs_bm"] == "▼"

    def test_result_ok_when_q1_net_positive(self):
        df = _make_annual_df(q1_gross=0.06)
        result = s07.compute_annual_returns(df)
        assert result.iloc[0]["result"] == "OK"

    def test_result_fail_when_q1_net_negative(self):
        # Gross well below TC so net is negative
        df = _make_annual_df(q1_gross=-0.05, other_gross=-0.03)
        result = s07.compute_annual_returns(df)
        assert result.iloc[0]["result"] == "FAIL"

    def test_q1_net_less_than_q1_gross(self):
        df = _make_annual_df(q1_gross=0.06)
        result = s07.compute_annual_returns(df)
        assert result.iloc[0]["q1_net"] < result.iloc[0]["q1_gross"]

    def test_returns_are_compounded_not_summed(self):
        """Annual net should equal (1 + gross - TC)^n_quarters - 1, not n * net_quarterly."""
        gross = 0.05
        tc = s07.TC_RT
        df = _make_annual_df(q1_gross=gross, other_gross=gross, n_quarters=4)
        result = s07.compute_annual_returns(df)
        expected = (1 + gross - tc) ** 4 - 1
        assert result.iloc[0]["q1_net"] == pytest.approx(expected, rel=1e-6)

    def test_year_outside_regimes_excluded(self):
        # 2000 is not in REGIMES dict → should produce no rows
        rows = []
        for i in range(5):
            rows.append(
                {
                    "symbol": f"SYM{i}",
                    "start_date": pd.Timestamp("2000-01-01"),
                    "end_date": pd.Timestamp("2000-03-31"),
                    "quintile": 1,
                    "gross_return": 0.05,
                }
            )
        df = pd.DataFrame(rows)
        result = s07.compute_annual_returns(df)
        assert len(result) == 0

    def test_regime_label_matches_dict(self):
        df = _make_annual_df(year=2020)
        result = s07.compute_annual_returns(df)
        assert result.iloc[0]["regime"] == s07.REGIMES[2020]

    def test_year_with_no_q1_stocks_is_skipped(self):
        # All stocks are Q2; no Q1 → year should be excluded
        df = _make_annual_df(year=2020)
        df["quintile"] = 2
        result = s07.compute_annual_returns(df)
        assert len(result) == 0

    def test_nan_gross_return_rows_dropped(self):
        df = _make_annual_df(year=2020)
        df.loc[df["quintile"] == 1, "gross_return"] = np.nan
        result = s07.compute_annual_returns(df)
        # All Q1 rows are NaN → no Q1 returns → year skipped
        assert len(result) == 0
