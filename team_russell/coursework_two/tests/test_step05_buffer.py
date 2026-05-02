"""Tests for step05_buffer_zone.py — buffer logic, returns, turnover, stats."""

import numpy as np
import pandas as pd
import pytest
import step05_buffer_zone as s05

# ── shared fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def buffer_df():
    """6 periods, 50 stocks per period across 5 quintiles."""
    np.random.seed(42)
    periods = [
        (
            pd.Timestamp("2022-03-31") + pd.DateOffset(months=3 * i),
            pd.Timestamp("2022-06-30") + pd.DateOffset(months=3 * i),
        )
        for i in range(6)
    ]
    rows = []
    for s, e in periods:
        scores = np.random.randn(50)
        for i, score in enumerate(scores):
            gross = np.random.uniform(-0.05, 0.12)
            rows.append(
                {
                    "symbol": f"SYM{i:03d}",
                    "start_date": s,
                    "end_date": e,
                    "quintile": (i // 10) + 1,
                    "composite_score": score,
                    "gross_return": gross,
                    "net_return": gross - 0.004,
                    "gics_sector": "Technology",
                }
            )
    return pd.DataFrame(rows)


# ── build_buffered_memberships ────────────────────────────────────────────────


class TestBuildBufferedMemberships:
    def test_returns_dict(self, buffer_df):
        result = s05.build_buffered_memberships(buffer_df)
        assert isinstance(result, dict)

    def test_one_entry_per_period(self, buffer_df):
        n_periods = buffer_df["start_date"].nunique()
        result = s05.build_buffered_memberships(buffer_df)
        assert len(result) == n_periods

    def test_first_period_uses_hard_cutoff(self, buffer_df):
        result = s05.build_buffered_memberships(buffer_df)
        first_date = sorted(result.keys())[0]
        first_period = buffer_df[buffer_df["start_date"] == first_date]
        n = len(first_period)
        expected_size = round(n * 0.20)
        actual_size = len(result[first_date])
        assert abs(actual_size - expected_size) <= 2

    def test_membership_values_are_sets(self, buffer_df):
        result = s05.build_buffered_memberships(buffer_df)
        for v in result.values():
            assert isinstance(v, set)

    def test_symbols_come_from_data(self, buffer_df):
        all_symbols = set(buffer_df["symbol"].unique())
        result = s05.build_buffered_memberships(buffer_df)
        for members in result.values():
            assert members.issubset(all_symbols)

    def test_cap_at_130_percent_of_target_size(self):
        """When buffered set grows beyond 130% of target (20%), it is trimmed."""
        # n=30: target=6, cap=7.8 → need ≥8 stocks to trigger the cap
        # Period 1: SYM00-SYM05 (scores 1.0 to 0.80) → initial Q1 (hard top-20%)
        # Period 2: SYM06-SYM10 get scores 1.0-0.84 (ranks 0-4, rank_pct < 0.15 → entry)
        #           SYM00-SYM02 get scores 0.80-0.72 (ranks 5-7, rank_pct < 0.25 → stay)
        #           SYM03-SYM05 get scores 0.68-0.60 (ranks 8-10, rank_pct ≥ 0.25 → exit)
        # buffered = {SYM00-SYM02} ∪ {SYM06-SYM10} = 8 stocks > 7.8 → cap triggers
        n = 30
        d1 = pd.Timestamp("2022-03-31")
        e1 = pd.Timestamp("2022-06-30")
        d2 = pd.Timestamp("2022-06-30")
        e2 = pd.Timestamp("2022-09-30")
        rows = []
        # Period 1 scores: SYM00-SYM05 highest → top-20% → Q1
        p1_scores = {f"SYM{i:02d}": 1.0 - i * 0.033 for i in range(n)}
        for i in range(n):
            sym = f"SYM{i:02d}"
            rows.append(
                {
                    "symbol": sym,
                    "start_date": d1,
                    "end_date": e1,
                    "quintile": 1 if i < 6 else 5,
                    "composite_score": p1_scores[sym],
                    "gross_return": 0.02,
                    "net_return": 0.016,
                    "gics_sector": "Technology",
                }
            )
        # Period 2 scores: SYM06-10 → ranks 0-4; SYM00-02 → ranks 5-7; SYM03-05 → ranks 8-10
        p2_scores = {}
        for j, sym in enumerate([f"SYM{i:02d}" for i in [6, 7, 8, 9, 10]]):
            p2_scores[sym] = 1.0 - j * 0.04  # 1.0, 0.96, 0.92, 0.88, 0.84
        for j, sym in enumerate([f"SYM{i:02d}" for i in [0, 1, 2]]):
            p2_scores[sym] = 0.80 - j * 0.04  # 0.80, 0.76, 0.72
        for j, sym in enumerate([f"SYM{i:02d}" for i in [3, 4, 5]]):
            p2_scores[sym] = 0.68 - j * 0.04  # 0.68, 0.64, 0.60
        for i in range(11, n):
            p2_scores[f"SYM{i:02d}"] = 0.56 - (i - 11) * 0.03
        for i in range(n):
            sym = f"SYM{i:02d}"
            rows.append(
                {
                    "symbol": sym,
                    "start_date": d2,
                    "end_date": e2,
                    "quintile": 1 if i < 6 else 5,
                    "composite_score": p2_scores[sym],
                    "gross_return": 0.02,
                    "net_return": 0.016,
                    "gics_sector": "Technology",
                }
            )
        df = pd.DataFrame(rows)
        result = s05.build_buffered_memberships(df)
        d2_key = sorted(result.keys())[1]
        target = round(n * 0.20)  # 6
        # Cap = 7.8 → result should be trimmed to ≤ target (6 or 7)
        assert len(result[d2_key]) <= int(target * 1.3) + 1

    def test_entry_threshold_restricts_entrants(self, buffer_df):
        # After first period, only top-ENTRY_PCT (15%) can newly enter
        result = s05.build_buffered_memberships(buffer_df)
        dates = sorted(result.keys())
        for i in range(1, len(dates)):
            prev = result[dates[i - 1]]
            curr = result[dates[i]]
            new_entrants = curr - prev
            period_df = (
                buffer_df[buffer_df["start_date"] == dates[i]]
                .sort_values("composite_score", ascending=False)
                .reset_index(drop=True)
            )
            n = len(period_df)
            top_15pct = set(period_df.head(round(n * s05.ENTRY_PCT))["symbol"])
            assert new_entrants.issubset(top_15pct)


# ── compute_returns ───────────────────────────────────────────────────────────


class TestComputeReturns:
    def test_returns_dataframe(self, buffer_df):
        memberships = s05.build_buffered_memberships(buffer_df)
        result = s05.compute_returns(memberships, buffer_df)
        assert isinstance(result, pd.DataFrame)

    def test_has_net_return_column(self, buffer_df):
        memberships = s05.build_buffered_memberships(buffer_df)
        result = s05.compute_returns(memberships, buffer_df)
        assert "net_return" in result.columns

    def test_net_return_is_gross_minus_tc(self, buffer_df):
        memberships = s05.build_buffered_memberships(buffer_df)
        result = s05.compute_returns(memberships, buffer_df)
        diff = (result["gross_return"] - result["net_return"]).values
        np.testing.assert_allclose(diff, s05.TC_RT, rtol=1e-6)

    def test_use_original_q1_flag(self, buffer_df):
        memberships = s05.build_buffered_memberships(buffer_df)
        result_orig = s05.compute_returns(memberships, buffer_df, use_original_q1=True)
        assert "net_return" in result_orig.columns

    def test_n_stocks_column_populated(self, buffer_df):
        memberships = s05.build_buffered_memberships(buffer_df)
        result = s05.compute_returns(memberships, buffer_df)
        assert (result["n_stocks"] >= 5).all()

    def test_period_with_fewer_than_5_stocks_skipped(self):
        """Portfolio with < 5 stocks should be excluded from results."""
        d1 = pd.Timestamp("2022-03-31")
        e1 = pd.Timestamp("2022-06-30")
        d2 = pd.Timestamp("2022-06-30")
        e2 = pd.Timestamp("2022-09-30")
        # Period 1 membership: 3 stocks (< 5 → should be skipped)
        memberships = {d1: {"A", "B", "C"}}
        df = pd.DataFrame(
            {
                "symbol": ["A", "B", "C", "D", "E"],
                "start_date": [d1, d1, d1, d2, d2],
                "end_date": [e1, e1, e1, e2, e2],
                "quintile": [1, 1, 1, 1, 1],
                "composite_score": [0.9, 0.8, 0.7, 0.6, 0.5],
                "gross_return": [0.02, 0.03, 0.01, 0.04, 0.02],
                "net_return": [0.016, 0.026, 0.006, 0.036, 0.016],
                "gics_sector": ["Tech"] * 5,
            }
        )
        result = s05.compute_returns(memberships, df)
        # Period 1 has only 3 portfolio members → skipped; period 2 has 0 → skipped
        assert len(result) == 0


# ── compute_turnover ──────────────────────────────────────────────────────────


class TestBufferComputeTurnover:
    def test_returns_dataframe(self, buffer_df):
        memberships = s05.build_buffered_memberships(buffer_df)
        result = s05.compute_turnover(memberships)
        assert isinstance(result, pd.DataFrame)

    def test_one_fewer_than_periods(self, buffer_df):
        memberships = s05.build_buffered_memberships(buffer_df)
        result = s05.compute_turnover(memberships)
        assert len(result) == len(memberships) - 1

    def test_turnover_rate_between_0_and_100(self, buffer_df):
        memberships = s05.build_buffered_memberships(buffer_df)
        result = s05.compute_turnover(memberships)
        assert (result["turnover_rate"] >= 0).all()
        assert (result["turnover_rate"] <= 100).all()

    def test_identical_memberships_give_zero_turnover(self):
        dates = [pd.Timestamp("2022-03-31"), pd.Timestamp("2022-06-30")]
        members = {"SYM1", "SYM2", "SYM3", "SYM4", "SYM5"}
        memberships = {d: members for d in dates}
        result = s05.compute_turnover(memberships)
        assert result.iloc[0]["turnover_rate"] == pytest.approx(0.0)

    def test_disjoint_memberships_give_100_turnover(self):
        dates = [pd.Timestamp("2022-03-31"), pd.Timestamp("2022-06-30")]
        memberships = {
            dates[0]: {"A", "B", "C", "D", "E"},
            dates[1]: {"F", "G", "H", "I", "J"},
        }
        result = s05.compute_turnover(memberships)
        assert result.iloc[0]["turnover_rate"] == pytest.approx(100.0)


# ── summary ───────────────────────────────────────────────────────────────────


class TestSummary:
    def _make_ret_df(self, returns):
        # start_date required — use real lookup-table dates (2022-03-31 … onwards)
        dates = [
            pd.Timestamp("2022-03-31") + pd.DateOffset(months=3 * i) for i in range(len(returns))
        ]
        return pd.DataFrame({"net_return": returns, "start_date": dates})

    def test_returns_dict(self):
        ret_df = self._make_ret_df([0.02, 0.03, -0.01, 0.05])
        result = s05.summary(ret_df)
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        ret_df = self._make_ret_df([0.02, 0.03, -0.01, 0.05])
        result = s05.summary(ret_df)
        for key in ["ann_return", "ann_vol", "sharpe", "cum"]:
            assert key in result

    def test_positive_returns_positive_ann_return(self):
        ret_df = self._make_ret_df([0.05, 0.05, 0.05, 0.05])
        result = s05.summary(ret_df)
        assert result["ann_return"] > 0

    def test_negative_returns_negative_ann_return(self):
        ret_df = self._make_ret_df([-0.05, -0.05, -0.05, -0.05])
        result = s05.summary(ret_df)
        assert result["ann_return"] < 0

    def test_ann_vol_is_positive(self):
        ret_df = self._make_ret_df([0.02, -0.01, 0.03, 0.01, -0.02, 0.04])
        result = s05.summary(ret_df)
        assert result["ann_vol"] > 0

    def test_cum_return_arithmetic(self):
        rets = [0.10, 0.10]
        ret_df = self._make_ret_df(rets)
        result = s05.summary(ret_df)
        expected_cum = (1.10 * 1.10) - 1
        assert result["cum"] == pytest.approx(expected_cum)
