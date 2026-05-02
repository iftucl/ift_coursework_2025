from __future__ import annotations

"""Execution simulation helpers for the CW2 backtest engine."""

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

_WEIGHT_TOL = 1e-12
CASH_SYMBOL = "_CASH"


@dataclass(frozen=True)
class ExecutionSimulationResult:
    """Executed portfolio state with flat all-in cost diagnostics."""

    requested_weights: Dict[str, float]
    executed_weights: Dict[str, float]
    requested_turnover: float
    requested_turnover_contrib: Dict[str, float]
    executed_turnover: float
    executed_turnover_contrib: Dict[str, float]
    fixed_cost: float
    bid_ask_cost: float
    slippage_cost: float
    total_cost: float
    cash_start_weight: float
    cash_after_execution_weight: float
    unfilled_buy_weight: float
    unfilled_sell_weight: float
    liquidity_clipped: bool
    max_participation_used: Optional[float]
    trade_records: List[Dict[str, Any]]
    notes: Dict[str, Any]


def estimate_dollar_adv(
    price_panel: pd.DataFrame,
    volume_panel: pd.DataFrame,
    *,
    as_of_date: date,
    lookback_days: int = 20,
    min_history_days: int = 5,
    max_forward_fill_days: int = 5,
) -> Dict[str, float]:
    """Estimate trailing average daily dollar volume per symbol."""
    if price_panel is None or price_panel.empty or volume_panel is None or volume_panel.empty:
        return {}

    prices = price_panel.copy()
    prices.index = pd.to_datetime(prices.index, errors="coerce").date
    prices = prices.sort_index().apply(pd.to_numeric, errors="coerce")

    volumes = volume_panel.copy()
    volumes.index = pd.to_datetime(volumes.index, errors="coerce").date
    volumes = volumes.sort_index().apply(pd.to_numeric, errors="coerce")

    all_days = sorted(
        {d for d in prices.index if d is not None} | {d for d in volumes.index if d is not None}
    )
    if not all_days:
        return {}

    prices = prices.reindex(all_days).ffill(limit=max(0, int(max_forward_fill_days)))
    volumes = volumes.reindex(all_days)

    adv: Dict[str, float] = {}
    for symbol in sorted(set(prices.columns) | set(volumes.columns)):
        if str(symbol) == CASH_SYMBOL:
            continue
        series = pd.to_numeric(prices.get(symbol), errors="coerce") * pd.to_numeric(
            volumes.get(symbol), errors="coerce"
        )
        history = (
            series.loc[[d for d in all_days if d <= as_of_date]]
            .dropna()
            .tail(max(1, int(lookback_days)))
        )
        if len(history) < max(1, int(min_history_days)):
            continue
        adv[str(symbol)] = float(history.mean())
    return adv


def compute_open_gap_returns(
    open_panel: pd.DataFrame,
    close_panel: pd.DataFrame,
    *,
    execution_date: date,
    trading_calendar: Sequence[date],
) -> Dict[str, float]:
    """Compute execution-day open gaps versus the previous observed close."""
    if open_panel is None or open_panel.empty or close_panel is None or close_panel.empty:
        return {}

    ordered_days = sorted({d for d in trading_calendar if d is not None})
    prev_candidates = [d for d in ordered_days if d < execution_date]
    if not prev_candidates:
        return {}
    previous_day = prev_candidates[-1]

    opens = open_panel.copy()
    opens.index = pd.to_datetime(opens.index, errors="coerce").date
    opens = opens.apply(pd.to_numeric, errors="coerce")

    closes = close_panel.copy()
    closes.index = pd.to_datetime(closes.index, errors="coerce").date
    closes = closes.apply(pd.to_numeric, errors="coerce")

    gaps: Dict[str, float] = {}
    for symbol in sorted(set(opens.columns) | set(closes.columns)):
        if str(symbol) == CASH_SYMBOL:
            continue
        open_px = _frame_value(opens, execution_date, symbol)
        prev_close = _frame_value(closes, previous_day, symbol)
        if open_px is None or prev_close is None or prev_close <= 0:
            continue
        gaps[str(symbol)] = float(open_px / prev_close - 1.0)
    return gaps


def simulate_trade_execution(
    target_weights: Mapping[str, float],
    drifted_weights: Mapping[str, float],
    *,
    portfolio_value: float,
    transaction_cost_bps: float,
    cost_model: str = "flat_total_bps",
    adv_by_symbol: Optional[Mapping[str, float]] = None,
    open_gap_returns: Optional[Mapping[str, float]] = None,
    enable_liquidity_clipping: bool = True,
    max_adv_participation: float = 0.05,
    base_slippage_bps: float = 0.0,
    open_execution_penalty_bps: float = 0.0,
    gap_slippage_multiplier: float = 0.0,
    participation_slippage_bps: float = 0.0,
    bid_ask_spread_model: str = "none",
    fixed_bid_ask_spread_bps: float = 0.0,
    bid_ask_crossing_fraction: float = 0.0,
    bid_ask_adv_low_threshold: float = 1_000_000.0,
    bid_ask_adv_medium_threshold: float = 10_000_000.0,
    bid_ask_spread_bps_low_adv: float = 12.0,
    bid_ask_spread_bps_medium_adv: float = 6.0,
    bid_ask_spread_bps_high_adv: float = 2.0,
) -> ExecutionSimulationResult:
    """Simulate a capacity-aware execution step with explicit cash carry.

    The default path treats ``transaction_cost_bps`` as the full all-in trading-cost
    assumption. ``decomposed_components`` remains available for compatibility tests.
    """
    resolved_cost_model = str(cost_model or "flat_total_bps").strip().lower()
    if resolved_cost_model not in {"flat_total_bps", "decomposed_components"}:
        raise ValueError("cost_model must be 'flat_total_bps' or 'decomposed_components'")

    requested_weights = _normalize_with_implicit_cash(target_weights, fallback_to_cash=True)
    starting_weights = _normalize_with_implicit_cash(drifted_weights, fallback_to_cash=True)

    requested_turnover, requested_turnover_contrib = _compute_risky_turnover(
        requested_weights,
        starting_weights,
    )
    if requested_turnover <= _WEIGHT_TOL:
        return ExecutionSimulationResult(
            requested_weights=requested_weights,
            executed_weights=dict(starting_weights),
            requested_turnover=requested_turnover,
            requested_turnover_contrib=requested_turnover_contrib,
            executed_turnover=0.0,
            executed_turnover_contrib={symbol: 0.0 for symbol in requested_turnover_contrib},
            fixed_cost=0.0,
            bid_ask_cost=0.0,
            slippage_cost=0.0,
            total_cost=0.0,
            cash_start_weight=float(starting_weights.get(CASH_SYMBOL, 0.0)),
            cash_after_execution_weight=float(starting_weights.get(CASH_SYMBOL, 0.0)),
            unfilled_buy_weight=0.0,
            unfilled_sell_weight=0.0,
            liquidity_clipped=False,
            max_participation_used=0.0,
            trade_records=[],
            notes={"reason": "no_trade"},
        )

    clean_adv = {
        str(symbol): float(value)
        for symbol, value in (adv_by_symbol or {}).items()
        if value is not None and math.isfinite(float(value)) and float(value) > 0
    }
    clean_gaps = {
        str(symbol): float(value)
        for symbol, value in (open_gap_returns or {}).items()
        if value is not None and math.isfinite(float(value))
    }

    risky_symbols = sorted(
        {
            symbol
            for symbol in set(requested_weights) | set(starting_weights)
            if symbol != CASH_SYMBOL
        }
    )
    cash_start = float(starting_weights.get(CASH_SYMBOL, 0.0))
    executed_risky = {
        symbol: float(starting_weights.get(symbol, 0.0))
        for symbol in risky_symbols
        if float(starting_weights.get(symbol, 0.0)) > _WEIGHT_TOL
    }

    desired_sells = {
        symbol: max(
            0.0,
            float(starting_weights.get(symbol, 0.0)) - float(requested_weights.get(symbol, 0.0)),
        )
        for symbol in risky_symbols
    }
    desired_buys = {
        symbol: max(
            0.0,
            float(requested_weights.get(symbol, 0.0)) - float(starting_weights.get(symbol, 0.0)),
        )
        for symbol in risky_symbols
    }

    liquidity_caps = {
        symbol: _liquidity_capacity_weight(
            symbol,
            portfolio_value=portfolio_value,
            adv_by_symbol=clean_adv,
            enable_liquidity_clipping=enable_liquidity_clipping,
            max_adv_participation=max_adv_participation,
        )
        for symbol in risky_symbols
    }

    actual_sells: Dict[str, float] = {}
    clipped_sell_symbols: List[str] = []
    actual_sell_total = 0.0
    for symbol in risky_symbols:
        desired = desired_sells.get(symbol, 0.0)
        cap = float(liquidity_caps.get(symbol, math.inf))
        executed = min(desired, cap)
        actual_sells[symbol] = executed
        if desired - executed > _WEIGHT_TOL:
            clipped_sell_symbols.append(symbol)
        actual_sell_total += executed
        if executed > _WEIGHT_TOL:
            remaining = max(0.0, executed_risky.get(symbol, 0.0) - executed)
            if remaining > _WEIGHT_TOL:
                executed_risky[symbol] = remaining
            else:
                executed_risky.pop(symbol, None)

    buy_caps = {
        symbol: min(
            desired_buys.get(symbol, 0.0),
            float(liquidity_caps.get(symbol, math.inf)),
        )
        for symbol in risky_symbols
    }
    capped_buy_total = sum(buy_caps.values())
    cash_available = max(0.0, cash_start + actual_sell_total)
    buy_scale = (
        min(1.0, cash_available / capped_buy_total) if capped_buy_total > _WEIGHT_TOL else 1.0
    )

    actual_buys: Dict[str, float] = {}
    clipped_buy_symbols: List[str] = []
    actual_buy_total = 0.0
    for symbol in risky_symbols:
        desired = desired_buys.get(symbol, 0.0)
        executed = float(buy_caps.get(symbol, 0.0)) * buy_scale
        actual_buys[symbol] = executed
        if desired - executed > _WEIGHT_TOL:
            clipped_buy_symbols.append(symbol)
        if executed > _WEIGHT_TOL:
            executed_risky[symbol] = executed_risky.get(symbol, 0.0) + executed
            actual_buy_total += executed

    cash_after_execution = max(0.0, cash_start + actual_sell_total - actual_buy_total)
    executed_weights = _normalize_with_implicit_cash(
        {
            **executed_risky,
            CASH_SYMBOL: cash_after_execution,
        },
        fallback_to_cash=True,
    )

    executed_turnover, executed_turnover_contrib = _compute_risky_turnover(
        executed_weights,
        starting_weights,
    )
    fixed_cost = transaction_cost_from_turnover(executed_turnover, transaction_cost_bps)

    bid_ask_cost = 0.0
    slippage_cost = 0.0
    max_participation_used: Optional[float] = 0.0
    per_symbol_participation: Dict[str, Optional[float]] = {}
    per_symbol_bid_ask_spread_bps: Dict[str, float] = {}
    per_symbol_bid_ask_cost: Dict[str, float] = {}
    per_symbol_gap_penalty_bps: Dict[str, float] = {}
    per_symbol_participation_penalty_bps: Dict[str, float] = {}
    per_symbol_slippage_bps: Dict[str, float] = {}
    per_symbol_slippage_cost: Dict[str, float] = {}
    for symbol in risky_symbols:
        actual_trade_weight = float(actual_buys.get(symbol, 0.0)) + float(
            actual_sells.get(symbol, 0.0)
        )
        if actual_trade_weight <= _WEIGHT_TOL:
            per_symbol_participation[symbol] = None
            per_symbol_bid_ask_spread_bps[symbol] = 0.0
            per_symbol_bid_ask_cost[symbol] = 0.0
            per_symbol_gap_penalty_bps[symbol] = 0.0
            per_symbol_participation_penalty_bps[symbol] = 0.0
            per_symbol_slippage_bps[symbol] = 0.0
            per_symbol_slippage_cost[symbol] = 0.0
            continue
        participation = _participation_ratio(
            symbol,
            trade_weight=actual_trade_weight,
            portfolio_value=portfolio_value,
            adv_by_symbol=clean_adv,
        )
        if participation is not None:
            max_participation_used = max(float(max_participation_used or 0.0), float(participation))
        per_symbol_participation[symbol] = participation
        if resolved_cost_model == "decomposed_components":
            bid_ask_spread_bps = _estimate_bid_ask_spread_bps(
                symbol,
                adv_by_symbol=clean_adv,
                model=bid_ask_spread_model,
                fixed_bid_ask_spread_bps=fixed_bid_ask_spread_bps,
                adv_low_threshold=bid_ask_adv_low_threshold,
                adv_medium_threshold=bid_ask_adv_medium_threshold,
                spread_bps_low_adv=bid_ask_spread_bps_low_adv,
                spread_bps_medium_adv=bid_ask_spread_bps_medium_adv,
                spread_bps_high_adv=bid_ask_spread_bps_high_adv,
            )
        else:
            bid_ask_spread_bps = 0.0
        per_symbol_bid_ask_spread_bps[symbol] = float(bid_ask_spread_bps)
        symbol_bid_ask_cost = (
            actual_trade_weight
            * max(0.0, float(bid_ask_crossing_fraction))
            * max(0.0, float(bid_ask_spread_bps))
            / 10000.0
        )
        if resolved_cost_model != "decomposed_components":
            symbol_bid_ask_cost = 0.0
        per_symbol_bid_ask_cost[symbol] = symbol_bid_ask_cost
        bid_ask_cost += symbol_bid_ask_cost
        if resolved_cost_model == "decomposed_components":
            gap_penalty_bps = (
                abs(float(clean_gaps.get(symbol, 0.0)))
                * 10000.0
                * max(0.0, float(gap_slippage_multiplier))
            )
        else:
            gap_penalty_bps = 0.0
        per_symbol_gap_penalty_bps[symbol] = gap_penalty_bps
        if resolved_cost_model == "decomposed_components":
            participation_penalty_bps = float(participation or 0.0) * max(
                0.0, float(participation_slippage_bps)
            )
        else:
            participation_penalty_bps = 0.0
        per_symbol_participation_penalty_bps[symbol] = participation_penalty_bps
        if resolved_cost_model == "decomposed_components":
            symbol_slippage_bps = (
                max(0.0, float(base_slippage_bps))
                + max(0.0, float(open_execution_penalty_bps))
                + gap_penalty_bps
                + participation_penalty_bps
            )
        else:
            symbol_slippage_bps = 0.0
        per_symbol_slippage_bps[symbol] = symbol_slippage_bps
        symbol_slippage_cost = actual_trade_weight * symbol_slippage_bps / 10000.0
        per_symbol_slippage_cost[symbol] = symbol_slippage_cost
        slippage_cost += symbol_slippage_cost

    liquidity_clipped = bool(clipped_buy_symbols or clipped_sell_symbols)
    trade_records: List[Dict[str, Any]] = []
    for symbol in risky_symbols:
        requested_buy_weight = float(desired_buys.get(symbol, 0.0))
        requested_sell_weight = float(desired_sells.get(symbol, 0.0))
        requested_trade_weight = requested_buy_weight + requested_sell_weight
        executed_buy_weight = float(actual_buys.get(symbol, 0.0))
        executed_sell_weight = float(actual_sells.get(symbol, 0.0))
        executed_trade_weight = executed_buy_weight + executed_sell_weight
        unfilled_weight = max(0.0, requested_trade_weight - executed_trade_weight)
        if (
            requested_trade_weight <= _WEIGHT_TOL
            and executed_trade_weight <= _WEIGHT_TOL
            and unfilled_weight <= _WEIGHT_TOL
        ):
            continue
        if requested_buy_weight > _WEIGHT_TOL and requested_sell_weight <= _WEIGHT_TOL:
            trade_side = "buy"
        elif requested_sell_weight > _WEIGHT_TOL and requested_buy_weight <= _WEIGHT_TOL:
            trade_side = "sell"
        else:
            trade_side = "mixed"
        liquidity_capacity_weight = float(liquidity_caps.get(symbol, math.inf))
        if not math.isfinite(liquidity_capacity_weight):
            liquidity_capacity_weight = None
        fixed_transaction_cost = transaction_cost_from_turnover(
            executed_trade_weight,
            transaction_cost_bps,
        )
        bid_ask_cost_component = float(per_symbol_bid_ask_cost.get(symbol, 0.0))
        slippage_cost_component = float(per_symbol_slippage_cost.get(symbol, 0.0))
        trade_records.append(
            {
                "symbol": str(symbol),
                "target_weight": float(target_weights.get(symbol, 0.0)),
                "drifted_weight": float(starting_weights.get(symbol, 0.0)),
                "requested_weight": float(requested_weights.get(symbol, 0.0)),
                "executed_weight": float(executed_weights.get(symbol, 0.0)),
                "trade_side": trade_side,
                "requested_buy_weight": requested_buy_weight,
                "requested_sell_weight": requested_sell_weight,
                "requested_trade_weight": requested_trade_weight,
                "executed_buy_weight": executed_buy_weight,
                "executed_sell_weight": executed_sell_weight,
                "executed_trade_weight": executed_trade_weight,
                "unfilled_weight": unfilled_weight,
                "requested_notional": requested_trade_weight * float(portfolio_value),
                "executed_notional": executed_trade_weight * float(portfolio_value),
                "adv_usd": clean_adv.get(symbol),
                "liquidity_capacity_weight": liquidity_capacity_weight,
                "liquidity_clipped": bool(
                    symbol in clipped_buy_symbols or symbol in clipped_sell_symbols
                ),
                "participation_ratio": per_symbol_participation.get(symbol),
                "bid_ask_spread_bps": float(per_symbol_bid_ask_spread_bps.get(symbol, 0.0)),
                "gap_return": float(clean_gaps.get(symbol, 0.0)),
                "gap_penalty_bps": float(per_symbol_gap_penalty_bps.get(symbol, 0.0)),
                "participation_penalty_bps": float(
                    per_symbol_participation_penalty_bps.get(symbol, 0.0)
                ),
                "slippage_bps": float(per_symbol_slippage_bps.get(symbol, 0.0)),
                "fixed_transaction_cost": fixed_transaction_cost,
                "bid_ask_cost": bid_ask_cost_component,
                "slippage_cost": slippage_cost_component,
                "total_cost": fixed_transaction_cost
                + bid_ask_cost_component
                + slippage_cost_component,
            }
        )
    notes: Dict[str, Any] = {
        "clipped_buy_symbols": clipped_buy_symbols,
        "clipped_sell_symbols": clipped_sell_symbols,
        "missing_adv_symbols": [symbol for symbol in risky_symbols if symbol not in clean_adv],
    }

    return ExecutionSimulationResult(
        requested_weights=requested_weights,
        executed_weights=executed_weights,
        requested_turnover=requested_turnover,
        requested_turnover_contrib=requested_turnover_contrib,
        executed_turnover=executed_turnover,
        executed_turnover_contrib=executed_turnover_contrib,
        fixed_cost=fixed_cost,
        bid_ask_cost=bid_ask_cost,
        slippage_cost=slippage_cost,
        total_cost=fixed_cost + bid_ask_cost + slippage_cost,
        cash_start_weight=cash_start,
        cash_after_execution_weight=float(executed_weights.get(CASH_SYMBOL, 0.0)),
        unfilled_buy_weight=sum(max(0.0, desired_buys[s] - actual_buys[s]) for s in risky_symbols),
        unfilled_sell_weight=sum(
            max(0.0, desired_sells[s] - actual_sells[s]) for s in risky_symbols
        ),
        liquidity_clipped=liquidity_clipped,
        max_participation_used=max_participation_used,
        trade_records=trade_records,
        notes=notes,
    )


def normalize_long_only_weights(
    raw_weights: Mapping[str, float],
    *,
    long_only: bool = True,
) -> Dict[str, float]:
    """Clean and normalize target weights to sum to one."""
    cleaned: Dict[str, float] = {}
    for symbol, value in raw_weights.items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(weight):
            continue
        if long_only and weight < -_WEIGHT_TOL:
            raise ValueError(f"Negative weight encountered in long-only mode: {symbol}={weight}")
        if weight > _WEIGHT_TOL:
            cleaned[str(symbol)] = weight

    total = sum(cleaned.values())
    if total <= _WEIGHT_TOL:
        return {}
    return {symbol: weight / total for symbol, weight in cleaned.items()}


def compute_drifted_weights(
    prev_weights: Mapping[str, float],
    prev_returns: Mapping[str, float],
) -> Dict[str, float]:
    """Compute start-of-period drifted weights from prior target weights."""
    base = normalize_long_only_weights(prev_weights)
    if not base:
        return {}

    portfolio_return = 0.0
    for symbol, weight in base.items():
        portfolio_return += weight * float(prev_returns.get(symbol, 0.0))

    denominator = 1.0 + portfolio_return
    if denominator <= 0:
        logger.warning(
            "backtest_execution: portfolio return %.6f invalidates drift denominator; falling back to normalized prior weights",
            portfolio_return,
        )
        return base

    drifted: Dict[str, float] = {}
    for symbol, weight in base.items():
        symbol_return = float(prev_returns.get(symbol, 0.0))
        drifted[symbol] = weight * (1.0 + symbol_return) / denominator
    return normalize_long_only_weights(drifted)


def compute_turnover(
    target_weights: Mapping[str, float],
    drifted_weights: Mapping[str, float],
    *,
    include_cash: bool = False,
) -> Tuple[float, Dict[str, float]]:
    """Compute total turnover and per-symbol turnover contribution.

    By default, the synthetic cash sleeve is excluded so turnover reflects
    risky-asset trading rather than doubling cash-to-risk transitions.
    """
    all_symbols = {
        symbol
        for symbol in set(target_weights) | set(drifted_weights)
        if include_cash or str(symbol) != CASH_SYMBOL
    }
    contribs: Dict[str, float] = {}
    for symbol in sorted(all_symbols):
        target = float(target_weights.get(symbol, 0.0))
        drifted = float(drifted_weights.get(symbol, 0.0))
        contribs[symbol] = abs(target - drifted)
    turnover = sum(contribs.values())
    return turnover, contribs


def compute_turnover_ratio(
    target_weights: Mapping[str, float],
    drifted_weights: Mapping[str, float],
    *,
    include_cash: bool = True,
) -> Tuple[float, Dict[str, float]]:
    """Compute the common one-way turnover ratio.

    This reports turnover as ``0.5 * Σ|Δw|`` across the full portfolio. Including
    the cash sleeve by default prevents the initial build from cash being
    understated in the reported turnover ratio.
    """

    gross_turnover, gross_contribs = compute_turnover(
        target_weights,
        drifted_weights,
        include_cash=include_cash,
    )
    return 0.5 * gross_turnover, {
        symbol: 0.5 * float(value) for symbol, value in gross_contribs.items()
    }


def transaction_cost_from_turnover(turnover: float, transaction_cost_bps: float) -> float:
    """Convert turnover into an all-in cost fraction."""
    return max(float(turnover), 0.0) * max(float(transaction_cost_bps), 0.0) / 10000.0


def compute_period_simple_returns(
    price_panel: pd.DataFrame,
    trading_calendar: Sequence[date],
    start_date: date,
    end_date: date,
    *,
    max_forward_fill_days: int = 5,
) -> Tuple[Dict[str, float], Dict[str, Dict[str, Any]]]:
    """Compute simple holding-period returns with controlled forward-fill and delisting logic."""
    if price_panel is None or price_panel.empty:
        return {}, {}

    window_start = start_date - timedelta(days=max(10, max_forward_fill_days * 3))
    calendar_window = [
        d
        for d in sorted({d for d in trading_calendar if d is not None})
        if window_start <= d <= end_date
    ]
    if not calendar_window:
        raise ValueError("Trading calendar window is empty for the requested holding period")

    returns: Dict[str, float] = {}
    metadata: Dict[str, Dict[str, Any]] = {}
    for symbol in price_panel.columns:
        symbol_returns, meta = _compute_symbol_period_return(
            price_panel[symbol],
            calendar_window,
            start_date,
            end_date,
            max_forward_fill_days=max_forward_fill_days,
        )
        returns[str(symbol)] = symbol_returns
        metadata[str(symbol)] = meta
    return returns, metadata


def _compute_symbol_period_return(
    series: pd.Series,
    calendar_window: Sequence[date],
    start_date: date,
    end_date: date,
    *,
    max_forward_fill_days: int,
) -> Tuple[float, Dict[str, Any]]:
    raw = series.copy()
    raw.index = pd.to_datetime(raw.index, errors="coerce").date
    raw = pd.to_numeric(raw, errors="coerce").dropna().sort_index()

    reindexed = raw.reindex(calendar_window)
    filled = reindexed.ffill(limit=max_forward_fill_days)

    start_price = filled.get(start_date)
    if pd.isna(start_price):
        logger.warning(
            "backtest_execution: missing entry price after forward-fill symbol=%s start_date=%s",
            getattr(series, "name", "UNKNOWN"),
            start_date,
        )
        meta = {
            "entry_price": None,
            "exit_price": None,
            "used_forward_fill": False,
            "forward_fill_days": 0,
            "delisted_assumed": False,
            "missing_entry_price": True,
        }
        return 0.0, meta

    entry_price = float(start_price)
    filled_end_price = filled.get(end_date)

    holding_window = [d for d in calendar_window if start_date <= d <= end_date]
    forward_fill_mask = (
        reindexed.loc[holding_window].isna() & filled.loc[holding_window].notna()
        if holding_window
        else pd.Series(dtype=bool)
    )
    forward_fill_days = int(forward_fill_mask.sum()) if not forward_fill_mask.empty else 0
    used_forward_fill = forward_fill_days > 0
    delisted_assumed = False
    if pd.notna(filled_end_price):
        exit_price = float(filled_end_price)
    else:
        actual_window = raw[(raw.index >= start_date) & (raw.index <= end_date)]
        exit_price = float(actual_window.iloc[-1]) if not actual_window.empty else entry_price
        delisted_assumed = True

    simple_return = 0.0 if entry_price <= 0 else max(-1.0, exit_price / entry_price - 1.0)
    meta = {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "used_forward_fill": bool(used_forward_fill),
        "forward_fill_days": forward_fill_days,
        "delisted_assumed": bool(delisted_assumed),
        "missing_entry_price": False,
    }
    return simple_return, meta


def _normalize_with_implicit_cash(
    raw_weights: Mapping[str, float],
    *,
    fallback_to_cash: bool,
) -> Dict[str, float]:
    cleaned = normalize_long_only_weights(raw_weights)
    if cleaned:
        return cleaned
    return {CASH_SYMBOL: 1.0} if fallback_to_cash else {}


def _compute_risky_turnover(
    target_weights: Mapping[str, float],
    drifted_weights: Mapping[str, float],
) -> Tuple[float, Dict[str, float]]:
    risky_symbols = sorted(
        {symbol for symbol in set(target_weights) | set(drifted_weights) if symbol != CASH_SYMBOL}
    )
    contribs = {
        symbol: abs(
            float(target_weights.get(symbol, 0.0)) - float(drifted_weights.get(symbol, 0.0))
        )
        for symbol in risky_symbols
    }
    return sum(contribs.values()), contribs


def _liquidity_capacity_weight(
    symbol: str,
    *,
    portfolio_value: float,
    adv_by_symbol: Mapping[str, float],
    enable_liquidity_clipping: bool,
    max_adv_participation: float,
) -> float:
    if not enable_liquidity_clipping:
        return math.inf
    adv = float(adv_by_symbol.get(symbol, 0.0))
    if adv <= 0 or portfolio_value <= 0:
        return math.inf
    return max(0.0, adv * max(0.0, float(max_adv_participation)) / float(portfolio_value))


def _participation_ratio(
    symbol: str,
    *,
    trade_weight: float,
    portfolio_value: float,
    adv_by_symbol: Mapping[str, float],
) -> Optional[float]:
    adv = float(adv_by_symbol.get(symbol, 0.0))
    if adv <= 0 or portfolio_value <= 0:
        return None
    return max(0.0, float(trade_weight) * float(portfolio_value) / adv)


def _estimate_bid_ask_spread_bps(
    symbol: str,
    *,
    adv_by_symbol: Mapping[str, float],
    model: str,
    fixed_bid_ask_spread_bps: float,
    adv_low_threshold: float,
    adv_medium_threshold: float,
    spread_bps_low_adv: float,
    spread_bps_medium_adv: float,
    spread_bps_high_adv: float,
) -> float:
    model_name = str(model or "none").strip().lower()
    if model_name == "none":
        return 0.0
    if model_name == "fixed":
        return max(0.0, float(fixed_bid_ask_spread_bps))

    adv = adv_by_symbol.get(str(symbol))
    if adv is None or not math.isfinite(float(adv)) or float(adv) <= 0:
        return max(0.0, float(spread_bps_medium_adv))
    adv_value = float(adv)
    if adv_value < float(adv_low_threshold):
        return max(0.0, float(spread_bps_low_adv))
    if adv_value < float(adv_medium_threshold):
        return max(0.0, float(spread_bps_medium_adv))
    return max(0.0, float(spread_bps_high_adv))


def _frame_value(panel: pd.DataFrame, dt: date, symbol: str) -> Optional[float]:
    if panel is None or panel.empty or dt not in panel.index or symbol not in panel.columns:
        return None
    value = pd.to_numeric(panel.at[dt, symbol], errors="coerce")
    if pd.isna(value):
        return None
    return float(value)
