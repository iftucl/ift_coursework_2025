"""Unit tests for the CW2 backtest execution layer."""

import math
from datetime import date

import pandas as pd
from team_Pearson.coursework_two.modules.backtest.execution import (
    compute_drifted_weights,
    compute_open_gap_returns,
    compute_period_simple_returns,
    compute_turnover,
    compute_turnover_ratio,
    estimate_dollar_adv,
    normalize_long_only_weights,
    simulate_trade_execution,
    transaction_cost_from_turnover,
)
from team_Pearson.coursework_two.modules.backtest.performance import (
    compute_gross_return,
    compute_net_return,
    update_nav,
)


def test_drifted_weights_first_period():
    assert compute_drifted_weights({}, {}) == {}


def test_drifted_weights_after_returns():
    prev_weights = {"A": 0.5, "B": 0.5}
    prev_returns = {"A": 0.10, "B": -0.05}

    out = compute_drifted_weights(prev_weights, prev_returns)
    portfolio_return = 0.5 * 0.10 + 0.5 * -0.05
    expected_a = 0.5 * 1.10 / (1.0 + portfolio_return)
    expected_b = 0.5 * 0.95 / (1.0 + portfolio_return)

    assert math.isclose(out["A"], expected_a, rel_tol=0, abs_tol=1e-8)
    assert math.isclose(out["B"], expected_b, rel_tol=0, abs_tol=1e-8)
    assert math.isclose(sum(out.values()), 1.0, rel_tol=0, abs_tol=1e-8)


def test_drifted_weights_handles_cash_sleeve():
    prev_weights = {"A": 0.4, "B": 0.4, "_CASH": 0.2}
    prev_returns = {"A": 0.10, "B": -0.05}

    out = compute_drifted_weights(prev_weights, prev_returns)
    assert "_CASH" in out
    assert math.isclose(sum(out.values()), 1.0, rel_tol=0, abs_tol=1e-8)
    assert out["_CASH"] > 0.0


def test_turnover_full_rebuild():
    target = {f"S{i}": 1.0 / 25.0 for i in range(25)}
    turnover, contrib = compute_turnover(target, {})
    assert math.isclose(turnover, 1.0, rel_tol=0, abs_tol=1e-8)
    assert len(contrib) == 25


def test_turnover_no_change():
    weights = {"A": 0.5, "B": 0.5}
    turnover, contrib = compute_turnover(weights, weights)
    assert turnover == 0.0
    assert contrib == {"A": 0.0, "B": 0.0}


def test_turnover_ignores_cash_sleeve_by_default():
    target = {"A": 1.0}
    drifted = {"A": 0.7, "_CASH": 0.3}

    turnover, contrib = compute_turnover(target, drifted)

    assert math.isclose(turnover, 0.3, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(contrib["A"], 0.3, rel_tol=0, abs_tol=1e-12)


def test_turnover_ratio_uses_common_one_way_convention_including_cash():
    target = {"A": 1.0}
    drifted = {"_CASH": 1.0}

    turnover_ratio, contrib = compute_turnover_ratio(target, drifted)

    assert math.isclose(turnover_ratio, 1.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(contrib["A"], 0.5, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(contrib["_CASH"], 0.5, rel_tol=0, abs_tol=1e-12)


def test_nav_update_with_cost():
    gross = 0.02
    cost = 0.0015
    nav = update_nav(1.0, gross, cost)
    assert math.isclose(nav, (1.0 + gross) * (1.0 - cost), rel_tol=0, abs_tol=1e-12)
    assert math.isclose(
        compute_net_return(gross, cost),
        (1.0 + gross) * (1.0 - cost) - 1.0,
        rel_tol=0,
        abs_tol=1e-12,
    )


def test_nav_update_first_period_cost():
    target = {f"S{i}": 1.0 / 25.0 for i in range(25)}
    turnover, _ = compute_turnover(target, {})
    cost = transaction_cost_from_turnover(turnover, 15)
    assert math.isclose(turnover, 1.0, rel_tol=0, abs_tol=1e-8)
    assert math.isclose(cost, 0.0015, rel_tol=0, abs_tol=1e-12)


def test_skip_when_below_min_universe():
    carried = normalize_long_only_weights({"A": 0.6, "B": 0.4})
    assert carried == {"A": 0.6, "B": 0.4}
    turnover, _ = compute_turnover(carried, carried)
    assert turnover == 0.0
    assert compute_gross_return(carried, {"A": 0.10, "B": 0.0}) == 0.06


def test_delisted_stock_forward_fill():
    idx = [
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 12),
        date(2026, 1, 13),
        date(2026, 1, 14),
    ]
    panel = pd.DataFrame(
        {
            "AAA": [100.0, 102.0, None, None, None, None, None, None, None],
        },
        index=idx,
    )

    returns, meta = compute_period_simple_returns(
        panel,
        idx,
        date(2026, 1, 5),
        date(2026, 1, 14),
        max_forward_fill_days=5,
    )
    assert math.isclose(returns["AAA"], 0.0, rel_tol=0, abs_tol=1e-12)
    assert meta["AAA"]["delisted_assumed"] is True


def test_forward_fill_short_gap_uses_last_price():
    idx = [
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
    ]
    panel = pd.DataFrame({"AAA": [100.0, 101.0, None, None]}, index=idx)
    returns, meta = compute_period_simple_returns(
        panel,
        idx,
        date(2026, 1, 5),
        date(2026, 1, 7),
        max_forward_fill_days=5,
    )
    assert math.isclose(returns["AAA"], 0.0, rel_tol=0, abs_tol=1e-12)
    assert meta["AAA"]["used_forward_fill"] is True
    assert meta["AAA"]["forward_fill_days"] == 2


def test_estimate_dollar_adv_uses_trailing_window():
    idx = [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    ]
    prices = pd.DataFrame({"AAA": [10.0, 11.0, 12.0, 13.0, 14.0]}, index=idx)
    volumes = pd.DataFrame({"AAA": [100.0, 100.0, 100.0, 100.0, 100.0]}, index=idx)

    adv = estimate_dollar_adv(
        prices,
        volumes,
        as_of_date=date(2026, 1, 9),
        lookback_days=3,
        min_history_days=2,
        max_forward_fill_days=5,
    )

    assert math.isclose(
        adv["AAA"],
        (12.0 * 100.0 + 13.0 * 100.0 + 14.0 * 100.0) / 3.0,
        rel_tol=0,
        abs_tol=1e-12,
    )


def test_compute_open_gap_returns_uses_previous_close():
    open_panel = pd.DataFrame({"AAA": [101.0]}, index=[date(2026, 1, 6)])
    close_panel = pd.DataFrame({"AAA": [100.0, 103.0]}, index=[date(2026, 1, 5), date(2026, 1, 6)])
    gaps = compute_open_gap_returns(
        open_panel,
        close_panel,
        execution_date=date(2026, 1, 6),
        trading_calendar=[date(2026, 1, 5), date(2026, 1, 6)],
    )
    assert math.isclose(gaps["AAA"], 0.01, rel_tol=0, abs_tol=1e-12)


def test_simulate_trade_execution_clips_buy_and_keeps_cash():
    result = simulate_trade_execution(
        {"AAA": 1.0},
        {"_CASH": 1.0},
        portfolio_value=1_000_000.0,
        transaction_cost_bps=15.0,
        adv_by_symbol={"AAA": 1_000_000.0},
        open_gap_returns={"AAA": 0.0},
        enable_liquidity_clipping=True,
        max_adv_participation=0.10,
        base_slippage_bps=0.0,
        open_execution_penalty_bps=0.0,
        gap_slippage_multiplier=0.0,
        participation_slippage_bps=0.0,
    )

    assert result.liquidity_clipped is True
    assert math.isclose(result.executed_weights["AAA"], 0.10, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.executed_weights["_CASH"], 0.90, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.requested_turnover, 1.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.executed_turnover, 0.10, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.unfilled_buy_weight, 0.90, rel_tol=0, abs_tol=1e-12)
    assert len(result.trade_records) == 1
    trade = result.trade_records[0]
    assert trade["symbol"] == "AAA"
    assert trade["trade_side"] == "buy"
    assert math.isclose(trade["requested_trade_weight"], 1.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["executed_trade_weight"], 0.10, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["unfilled_weight"], 0.90, rel_tol=0, abs_tol=1e-12)
    assert trade["liquidity_clipped"] is True
    assert math.isclose(trade["participation_ratio"], 0.10, rel_tol=0, abs_tol=1e-12)


def test_simulate_trade_execution_adds_slippage_cost():
    result = simulate_trade_execution(
        {"AAA": 1.0},
        {"_CASH": 1.0},
        portfolio_value=1_000_000.0,
        transaction_cost_bps=15.0,
        cost_model="decomposed_components",
        adv_by_symbol={"AAA": 100_000_000.0},
        open_gap_returns={"AAA": 0.02},
        enable_liquidity_clipping=False,
        max_adv_participation=0.10,
        base_slippage_bps=3.0,
        open_execution_penalty_bps=2.0,
        gap_slippage_multiplier=0.25,
        participation_slippage_bps=0.0,
        bid_ask_spread_model="adv_tier",
        bid_ask_crossing_fraction=0.5,
    )

    assert math.isclose(result.executed_turnover, 1.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.fixed_cost, 0.0015, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.bid_ask_cost, 0.0001, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.slippage_cost, 0.0055, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.total_cost, 0.0071, rel_tol=0, abs_tol=1e-12)
    trade = result.trade_records[0]
    assert math.isclose(trade["gap_return"], 0.02, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["gap_penalty_bps"], 50.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["slippage_bps"], 55.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["fixed_transaction_cost"], 0.0015, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["bid_ask_cost"], 0.0001, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["slippage_cost"], 0.0055, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["total_cost"], 0.0071, rel_tol=0, abs_tol=1e-12)


def test_simulate_trade_execution_bid_ask_spread_adv_tier():
    result = simulate_trade_execution(
        {"AAA": 1.0},
        {"_CASH": 1.0},
        portfolio_value=1_000_000.0,
        transaction_cost_bps=0.0,
        cost_model="decomposed_components",
        adv_by_symbol={"AAA": 500_000.0},
        open_gap_returns={"AAA": 0.0},
        enable_liquidity_clipping=False,
        max_adv_participation=0.10,
        base_slippage_bps=0.0,
        open_execution_penalty_bps=0.0,
        gap_slippage_multiplier=0.0,
        participation_slippage_bps=0.0,
        bid_ask_spread_model="adv_tier",
        bid_ask_crossing_fraction=0.5,
        bid_ask_adv_low_threshold=1_000_000.0,
        bid_ask_adv_medium_threshold=10_000_000.0,
        bid_ask_spread_bps_low_adv=12.0,
        bid_ask_spread_bps_medium_adv=6.0,
        bid_ask_spread_bps_high_adv=2.0,
    )

    assert math.isclose(result.bid_ask_cost, 0.0006, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.total_cost, 0.0006, rel_tol=0, abs_tol=1e-12)


def test_simulate_trade_execution_defaults_to_flat_all_in_cost():
    result = simulate_trade_execution(
        {"AAA": 1.0},
        {"_CASH": 1.0},
        portfolio_value=1_000_000.0,
        transaction_cost_bps=15.0,
        adv_by_symbol={"AAA": 100_000_000.0},
        open_gap_returns={"AAA": 0.02},
        enable_liquidity_clipping=False,
        max_adv_participation=0.10,
        base_slippage_bps=3.0,
        open_execution_penalty_bps=2.0,
        gap_slippage_multiplier=0.25,
        participation_slippage_bps=25.0,
        bid_ask_spread_model="adv_tier",
        bid_ask_crossing_fraction=0.5,
        bid_ask_adv_low_threshold=1_000_000.0,
        bid_ask_adv_medium_threshold=10_000_000.0,
        bid_ask_spread_bps_low_adv=12.0,
        bid_ask_spread_bps_medium_adv=6.0,
        bid_ask_spread_bps_high_adv=2.0,
    )

    assert math.isclose(result.executed_turnover, 1.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.fixed_cost, 0.0015, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.bid_ask_cost, 0.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.slippage_cost, 0.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(result.total_cost, 0.0015, rel_tol=0, abs_tol=1e-12)
    trade = result.trade_records[0]
    assert math.isclose(trade["fixed_transaction_cost"], 0.0015, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["bid_ask_cost"], 0.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["slippage_cost"], 0.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(trade["total_cost"], 0.0015, rel_tol=0, abs_tol=1e-12)
