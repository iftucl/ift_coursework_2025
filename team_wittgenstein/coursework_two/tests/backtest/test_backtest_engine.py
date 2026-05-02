"""Tests for backtest_engine — Steps 3-6 of the 130/30 backtest.

Pure metric functions are tested with hand-built DataFrames.
DB-touching helpers (_fetch_positions, _fetch_prices_at_dates) and the
run_backtest orchestrator are tested with a mocked PostgresConnection.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from modules.backtest.backtest_engine import (
    BacktestConfig,
    _compute_drift_adjusted_weights,
    _compute_gross_return,
    _compute_stock_returns,
    _compute_turnover,
    _fetch_positions,
    _fetch_prices_at_dates,
    run_backtest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _positions(symbols, directions, weights):
    return pd.DataFrame(
        {"symbol": symbols, "direction": directions, "final_weight": weights}
    )


def _returns(symbols, values):
    return pd.Series(values, index=symbols)


# ---------------------------------------------------------------------------
# TestComputeStockReturns
# ---------------------------------------------------------------------------


class TestComputeStockReturns:

    def test_basic_return(self):
        """(110/100) - 1 = 0.10 for a single stock."""
        pos = _positions(["A"], ["long"], [0.5])
        price_t = pd.Series({"A": 100.0})
        price_t1 = pd.Series({"A": 110.0})
        result = _compute_stock_returns(pos, price_t, price_t1)
        assert pytest.approx(result["A"], rel=1e-9) == 0.10

    def test_missing_price_excluded(self):
        """Symbols missing a price at either date are dropped."""
        pos = _positions(["A", "B"], ["long", "long"], [0.5, 0.5])
        price_t = pd.Series({"A": 100.0})  # B missing
        price_t1 = pd.Series({"A": 110.0, "B": 200.0})
        result = _compute_stock_returns(pos, price_t, price_t1)
        assert "A" in result.index
        assert "B" not in result.index

    def test_zero_price_excluded(self):
        """Symbols with price_t == 0 are dropped to avoid division by zero."""
        pos = _positions(["A"], ["long"], [0.5])
        price_t = pd.Series({"A": 0.0})
        price_t1 = pd.Series({"A": 10.0})
        result = _compute_stock_returns(pos, price_t, price_t1)
        assert result.empty

    def test_negative_return(self):
        """Price decline produces negative return."""
        pos = _positions(["A"], ["long"], [0.5])
        price_t = pd.Series({"A": 200.0})
        price_t1 = pd.Series({"A": 150.0})
        result = _compute_stock_returns(pos, price_t, price_t1)
        assert pytest.approx(result["A"], rel=1e-9) == -0.25


# ---------------------------------------------------------------------------
# TestComputeGrossReturn
# ---------------------------------------------------------------------------


class TestComputeGrossReturn:

    def test_long_only(self):
        """Gross = Σ(w_long × r). Short book absent."""
        pos = _positions(["A", "B"], ["long", "long"], [0.65, 0.65])
        rets = _returns(["A", "B"], [0.10, 0.20])
        gross, long_ret, short_ret = _compute_gross_return(pos, rets)
        assert pytest.approx(long_ret, rel=1e-9) == 0.65 * 0.10 + 0.65 * 0.20
        assert pytest.approx(short_ret, rel=1e-9) == 0.0
        assert pytest.approx(gross, rel=1e-9) == long_ret

    def test_gross_equals_long_minus_short(self):
        """gross = long_ret - short_ret (spec Step 3)."""
        pos = _positions(
            ["A", "B", "C"],
            ["long", "long", "short"],
            [0.65, 0.65, 0.30],
        )
        rets = _returns(["A", "B", "C"], [0.10, 0.05, 0.08])
        gross, long_ret, short_ret = _compute_gross_return(pos, rets)
        assert pytest.approx(gross, rel=1e-9) == long_ret - short_ret

    def test_short_rising_hurts_portfolio(self):
        """When a short position rises, gross return falls."""
        # Long flat, short rises 10% → short contribution hurts gross
        pos = _positions(["A", "B"], ["long", "short"], [1.30, 0.30])
        rets = _returns(["A", "B"], [0.0, 0.10])
        gross, long_ret, short_ret = _compute_gross_return(pos, rets)
        assert gross < 0
        assert pytest.approx(gross, rel=1e-9) == -0.30 * 0.10

    def test_short_falling_helps_portfolio(self):
        """When a short position falls, gross return is positive."""
        pos = _positions(["A", "B"], ["long", "short"], [1.30, 0.30])
        rets = _returns(["A", "B"], [0.0, -0.10])
        gross, _, _ = _compute_gross_return(pos, rets)
        assert gross > 0
        assert pytest.approx(gross, rel=1e-9) == 0.30 * 0.10

    def test_missing_return_symbol_dropped(self):
        """Positions without a return are silently excluded."""
        pos = _positions(["A", "B"], ["long", "long"], [0.65, 0.65])
        rets = _returns(["A"], [0.10])  # B has no return
        gross, long_ret, _ = _compute_gross_return(pos, rets)
        assert pytest.approx(long_ret, rel=1e-9) == 0.65 * 0.10

    def test_130_30_market_neutral_scenario(self):
        """130/30 with equal long/short returns → gross ≈ net market return."""
        # All stocks return 5%; net exposure = 1.0 → gross ≈ 5%
        pos = _positions(
            ["A", "B"],
            ["long", "short"],
            [1.30, 0.30],
        )
        rets = _returns(["A", "B"], [0.05, 0.05])
        gross, _, _ = _compute_gross_return(pos, rets)
        assert pytest.approx(gross, rel=1e-9) == 1.30 * 0.05 - 0.30 * 0.05


# ---------------------------------------------------------------------------
# TestComputeDriftAdjustedWeights
# ---------------------------------------------------------------------------


class TestComputeDriftAdjustedWeights:

    def test_weights_preserve_scale(self):
        """Drift-adjusted weights preserve the original weight scale (unnormalised)."""
        prev = _positions(["A", "B", "C"], ["long"] * 3, [0.50, 0.30, 0.20])
        rets = _returns(["A", "B", "C"], [0.0, 0.0, 0.0])
        w = _compute_drift_adjusted_weights(prev, rets)
        # With zero returns, drift weights == original weights, sum = 1.0
        assert pytest.approx(w.sum(), abs=1e-9) == 1.0

    def test_no_returns_weights_unchanged(self):
        """With zero returns, drift-adjusted weights equal original weights."""
        prev = _positions(["A", "B"], ["long"] * 2, [0.60, 0.40])
        rets = _returns(["A", "B"], [0.0, 0.0])
        w = _compute_drift_adjusted_weights(prev, rets)
        assert pytest.approx(w["A"], rel=1e-9) == 0.60
        assert pytest.approx(w["B"], rel=1e-9) == 0.40

    def test_higher_return_increases_relative_weight(self):
        """Stock with higher return gets larger drift-adjusted weight."""
        prev = _positions(["A", "B"], ["long"] * 2, [0.50, 0.50])
        rets = _returns(["A", "B"], [0.20, 0.0])
        w = _compute_drift_adjusted_weights(prev, rets)
        assert w["A"] > w["B"]

    def test_missing_return_treated_as_zero(self):
        """Symbol missing from returns gets r=0 (price unchanged)."""
        prev = _positions(["A", "B"], ["long"] * 2, [0.50, 0.50])
        rets = _returns(["A"], [0.10])  # B missing → r=0
        w = _compute_drift_adjusted_weights(prev, rets)
        # A: 0.50 * 1.10 = 0.55, B: 0.50 * 1.0 = 0.50
        assert pytest.approx(w["A"], rel=1e-9) == 0.55
        assert pytest.approx(w["B"], rel=1e-9) == 0.50
        assert w["A"] > w["B"]

    def test_formula_correctness(self):
        """Drift-adjusted weight = final_weight × (1 + r) — unnormalised."""
        prev = _positions(["A", "B"], ["long"] * 2, [0.60, 0.40])
        rets = _returns(["A", "B"], [0.10, 0.20])
        w = _compute_drift_adjusted_weights(prev, rets)
        assert pytest.approx(w["A"], rel=1e-9) == 0.60 * 1.10
        assert pytest.approx(w["B"], rel=1e-9) == 0.40 * 1.20


# ---------------------------------------------------------------------------
# TestComputeTurnover
# ---------------------------------------------------------------------------


class TestComputeTurnover:

    def test_first_period_no_previous(self):
        """First period: turnover = 0 (treated as pre-invested, no entry cost)."""
        pos = _positions(["A", "B"], ["long", "short"], [1.30, 0.30])
        rets = _returns(["A", "B"], [0.05, 0.05])
        turnover = _compute_turnover(pos, None, rets)
        assert pytest.approx(turnover, abs=1e-9) == 0.0

    def test_identical_portfolio_after_drift(self):
        """If new weights exactly match drift-adjusted weights, turnover = 0."""
        prev = _positions(["A", "B"], ["long"] * 2, [0.50, 0.50])
        rets = _returns(["A", "B"], [0.0, 0.0])  # no drift
        # new weights = same as drift-adjusted
        curr = _positions(["A", "B"], ["long"] * 2, [0.50, 0.50])
        turnover = _compute_turnover(curr, prev, rets)
        assert pytest.approx(turnover, abs=1e-9) == 0.0

    def test_full_replacement(self):
        """Completely replacing all positions generates maximum turnover."""
        prev = _positions(["A", "B"], ["long"] * 2, [0.65, 0.65])
        rets = _returns(["A", "B"], [0.0, 0.0])
        curr = _positions(["C", "D"], ["long"] * 2, [0.65, 0.65])
        turnover = _compute_turnover(curr, prev, rets)
        # drift: A=0.65, B=0.65 (zero returns → no drift)
        # exit A(0.65) + exit B(0.65) + enter C(0.65) + enter D(0.65) = 2.60
        assert pytest.approx(turnover, rel=1e-9) == 2.60

    def test_partial_rebalance(self):
        """Partial weight shift produces correct absolute difference."""
        prev = _positions(["A"], ["long"], [0.50])
        rets = _returns(["A"], [0.0])  # no drift → w'_A = 0.50
        curr = _positions(["A"], ["long"], [0.60])
        turnover = _compute_turnover(curr, prev, rets)
        assert pytest.approx(turnover, rel=1e-9) == 0.10

    def test_drift_reduces_turnover(self):
        """When a stock drifts toward new target, turnover < naive weight diff."""
        # Stock A rises 20% → drifts from 0.50 to higher; new target also higher
        prev = _positions(["A", "B"], ["long"] * 2, [0.50, 0.50])
        rets = _returns(["A", "B"], [0.20, 0.0])
        # After drift: A ~ 0.545, B ~ 0.455
        curr = _positions(["A", "B"], ["long"] * 2, [0.55, 0.45])
        turnover_with_drift = _compute_turnover(curr, prev, rets)

        # Without drift (naive): |0.55-0.50| + |0.45-0.50| = 0.10
        turnover_naive = abs(0.55 - 0.50) + abs(0.45 - 0.50)
        assert turnover_with_drift < turnover_naive

    def test_direction_flip_counts_close_plus_open(self):
        """Long→short flip: turnover = old_drift + new_weight, not |diff|."""
        # long 5% → short 3% (zero returns so no drift)
        prev = _positions(["A"], ["long"], [0.05])
        rets = _returns(["A"], [0.0])
        curr = _positions(["A"], ["short"], [0.03])
        turnover = _compute_turnover(curr, prev, rets)
        # close long 0.05 + open short 0.03 = 0.08, not |0.03 - 0.05| = 0.02
        assert pytest.approx(turnover, rel=1e-9) == 0.08

    def test_spec_example(self):
        """Spec example: Turnover=7.9%, short=30% → trading cost=0.020%."""
        # With turnover=0.079: trading_cost = 0.079 * 0.0025 = 0.0001975 ≈ 0.020%
        # short_notional=0.30: borrow_cost = 0.30 * 0.0075/12 = 0.0001875 ≈ 0.019%
        # total ≈ 0.039% = 0.00039
        trading_cost = 0.079 * 0.0025
        borrow_cost = 0.30 * 0.0075 / 12
        total = trading_cost + borrow_cost
        assert pytest.approx(trading_cost * 100, abs=0.001) == 0.020
        assert pytest.approx(borrow_cost * 100, abs=0.001) == 0.019
        assert pytest.approx(total * 100, abs=0.001) == 0.039


# ---------------------------------------------------------------------------
# TestFetchPositions (DB helper)
# ---------------------------------------------------------------------------


class TestFetchPositions:

    def test_calls_db_with_expected_query(self):
        """SQL selects all portfolio_positions ordered by date and symbol."""
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        _fetch_positions(db)

        args, _ = db.read_query.call_args
        sql = args[0]
        assert "FROM team_wittgenstein.portfolio_positions" in sql
        assert "rebalance_date, symbol, direction, final_weight" in sql
        assert "ORDER BY rebalance_date, symbol" in sql

    def test_returns_dataframe_from_db(self):
        """Whatever read_query returns is passed through."""
        expected = pd.DataFrame(
            {
                "rebalance_date": [date(2024, 1, 31)],
                "symbol": ["AAPL"],
                "direction": ["long"],
                "final_weight": [0.05],
            }
        )
        db = MagicMock()
        db.read_query.return_value = expected
        result = _fetch_positions(db)
        pd.testing.assert_frame_equal(result, expected)


# ---------------------------------------------------------------------------
# TestFetchPricesAtDates (DB helper)
# ---------------------------------------------------------------------------


class TestFetchPricesAtDates:

    def test_empty_db_returns_empty(self):
        """No price rows returned -> empty DataFrame."""
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        result = _fetch_prices_at_dates(db, [date(2024, 1, 31)])
        assert result.empty

    def test_none_db_returns_empty(self):
        """read_query returning None is handled gracefully."""
        db = MagicMock()
        db.read_query.return_value = None
        result = _fetch_prices_at_dates(db, [date(2024, 1, 31)])
        assert result.empty

    def test_pivots_to_wide(self):
        """Long-format price rows are pivoted to (date x symbol) DataFrame."""
        raw = pd.DataFrame(
            {
                "symbol": ["A", "B", "A", "B"],
                "ref_date": [
                    date(2024, 1, 31),
                    date(2024, 1, 31),
                    date(2024, 2, 29),
                    date(2024, 2, 29),
                ],
                "adjusted_close": [100.0, 200.0, 110.0, 195.0],
            }
        )
        db = MagicMock()
        db.read_query.return_value = raw
        result = _fetch_prices_at_dates(db, [date(2024, 1, 31), date(2024, 2, 29)])
        # Wide format: 2 rows (dates), 2 columns (symbols)
        assert result.shape == (2, 2)
        assert result.loc[date(2024, 1, 31), "A"] == 100.0
        assert result.loc[date(2024, 2, 29), "B"] == 195.0

    def test_dates_embedded_in_sql(self):
        """The dates passed in are interpolated into the SQL string."""
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        _fetch_prices_at_dates(db, [date(2024, 1, 31), date(2024, 2, 29)])

        args, _ = db.read_query.call_args
        sql = args[0]
        assert "'2024-01-31'" in sql
        assert "'2024-02-29'" in sql
        assert "FROM team_wittgenstein.price_data" in sql


# ---------------------------------------------------------------------------
# TestRunBacktest (orchestrator with mocked DB + benchmark)
# ---------------------------------------------------------------------------


class TestRunBacktest:

    def _make_positions_df(self, rebalance_dates):
        """Build a portfolio_positions DataFrame with 2 longs + 1 short per date."""
        rows = []
        for d in rebalance_dates:
            rows.extend(
                [
                    {
                        "rebalance_date": d,
                        "symbol": "A",
                        "direction": "long",
                        "final_weight": 0.7,
                    },
                    {
                        "rebalance_date": d,
                        "symbol": "B",
                        "direction": "long",
                        "final_weight": 0.6,
                    },
                    {
                        "rebalance_date": d,
                        "symbol": "C",
                        "direction": "short",
                        "final_weight": 0.3,
                    },
                ]
            )
        return pd.DataFrame(rows)

    def _make_price_grid(self, rebalance_dates):
        """Build a price_grid (DataFrame indexed by date, columns are symbols)."""
        prices = pd.DataFrame(
            index=rebalance_dates, columns=["A", "B", "C"], dtype=float
        )
        # Linear ramp so each period has a different return
        for i, d in enumerate(rebalance_dates):
            prices.loc[d] = [100 + i * 5, 200 + i * 4, 50 + i * 2]
        return prices

    def test_empty_positions_raises(self):
        """No portfolio_positions in DB -> RuntimeError."""
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        config = BacktestConfig()
        with pytest.raises(RuntimeError, match="portfolio_positions is empty"):
            run_backtest(db, config)

    def test_empty_benchmark_raises(self):
        """benchmark_returns table empty -> RuntimeError."""
        rebalance_dates = [date(2024, 1, 31), date(2024, 2, 29)]
        positions_df = self._make_positions_df(rebalance_dates)

        db = MagicMock()
        db.read_query.return_value = positions_df

        with patch(
            "modules.backtest.backtest_engine.load_benchmark_from_db"
        ) as mock_load:
            mock_load.return_value = pd.Series(dtype=float)
            with pytest.raises(RuntimeError, match="benchmark_returns is empty"):
                run_backtest(db, BacktestConfig())

    def test_full_flow_produces_results(self):
        """End-to-end: 3 dates -> 2 monthly returns with cumulative_return."""
        rebalance_dates = [
            date(2024, 1, 31),
            date(2024, 2, 29),
            date(2024, 3, 31),
        ]
        positions_df = self._make_positions_df(rebalance_dates)
        price_grid = self._make_price_grid(rebalance_dates)

        # Long-format raw price rows for _fetch_prices_at_dates
        raw_prices = price_grid.stack().reset_index()
        raw_prices.columns = ["ref_date", "symbol", "adjusted_close"]

        benchmark = pd.Series(
            [0.01, 0.02],
            index=[date(2024, 2, 29), date(2024, 3, 31)],
        )

        db = MagicMock()
        # _fetch_positions then _fetch_prices_at_dates
        db.read_query.side_effect = [positions_df, raw_prices]

        with patch(
            "modules.backtest.backtest_engine.load_benchmark_from_db",
            return_value=benchmark,
        ):
            result = run_backtest(db, BacktestConfig(scenario_id="test"))

        # 3 rebalance dates -> 2 holding periods -> 2 return rows
        assert len(result) == 2
        assert (result["scenario_id"] == "test").all()
        # cumulative_return last value should equal compounded net returns
        expected_cum = (1 + result["net_return"]).prod() - 1
        assert pytest.approx(result["cumulative_return"].iloc[-1], rel=1e-9) == (
            expected_cum
        )

    def test_missing_prices_skips_period(self):
        """Period skipped (with warning) when prices are missing for either date."""
        rebalance_dates = [
            date(2024, 1, 31),
            date(2024, 2, 29),
            date(2024, 3, 31),
        ]
        positions_df = self._make_positions_df(rebalance_dates)

        # Drop Mar prices so the Feb -> Mar period is skipped (Mar missing).
        # The Jan -> Feb period still has both endpoints and produces a result.
        full_grid = self._make_price_grid(rebalance_dates)
        partial = full_grid.drop(index=[date(2024, 3, 31)])
        raw_prices = partial.stack().reset_index()
        raw_prices.columns = ["ref_date", "symbol", "adjusted_close"]

        benchmark = pd.Series(
            [0.01, 0.02],
            index=[date(2024, 2, 29), date(2024, 3, 31)],
        )

        db = MagicMock()
        db.read_query.side_effect = [positions_df, raw_prices]

        with patch(
            "modules.backtest.backtest_engine.load_benchmark_from_db",
            return_value=benchmark,
        ):
            result = run_backtest(db, BacktestConfig())

        # Only the Jan -> Feb period produces a return; Feb -> Mar is skipped
        assert len(result) == 1
        assert result.iloc[0]["rebalance_date"] == date(2024, 2, 29)

    def test_missing_start_date_skips_period(self):
        """Period skipped when prices missing for the start (t) date."""
        rebalance_dates = [
            date(2024, 1, 31),
            date(2024, 2, 29),
            date(2024, 3, 31),
        ]
        positions_df = self._make_positions_df(rebalance_dates)

        # Drop Jan prices so the Jan -> Feb period is skipped (t missing).
        # Feb -> Mar still has both endpoints and produces a result.
        full_grid = self._make_price_grid(rebalance_dates)
        partial = full_grid.drop(index=[date(2024, 1, 31)])
        raw_prices = partial.stack().reset_index()
        raw_prices.columns = ["ref_date", "symbol", "adjusted_close"]

        benchmark = pd.Series(
            [0.01, 0.02],
            index=[date(2024, 2, 29), date(2024, 3, 31)],
        )

        db = MagicMock()
        db.read_query.side_effect = [positions_df, raw_prices]

        with patch(
            "modules.backtest.backtest_engine.load_benchmark_from_db",
            return_value=benchmark,
        ):
            result = run_backtest(db, BacktestConfig())

        # Jan -> Feb is skipped (start missing); Feb -> Mar produces a result
        assert len(result) == 1
        assert result.iloc[0]["rebalance_date"] == date(2024, 3, 31)

    def test_all_periods_skipped_returns_empty(self):
        """If every holding period is skipped (e.g. all prices missing for a
        common date), run_backtest returns an empty DataFrame instead of
        crashing on missing columns during sort_values/cumprod."""
        rebalance_dates = [
            date(2024, 1, 31),
            date(2024, 2, 29),
            date(2024, 3, 31),
        ]
        positions_df = self._make_positions_df(rebalance_dates)

        # Drop Feb prices - both Jan->Feb and Feb->Mar periods need Feb,
        # so both holding periods are skipped and results stays empty.
        full_grid = self._make_price_grid(rebalance_dates)
        partial = full_grid.drop(index=[date(2024, 2, 29)])
        raw_prices = partial.stack().reset_index()
        raw_prices.columns = ["ref_date", "symbol", "adjusted_close"]

        benchmark = pd.Series(
            [0.01, 0.02],
            index=[date(2024, 2, 29), date(2024, 3, 31)],
        )

        db = MagicMock()
        db.read_query.side_effect = [positions_df, raw_prices]

        with patch(
            "modules.backtest.backtest_engine.load_benchmark_from_db",
            return_value=benchmark,
        ):
            result = run_backtest(db, BacktestConfig())

        # Should return an empty DataFrame, not raise
        assert isinstance(result, pd.DataFrame)
        assert result.empty
