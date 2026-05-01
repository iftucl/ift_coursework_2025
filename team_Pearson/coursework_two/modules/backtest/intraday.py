from __future__ import annotations

"""Daily, weekly, and event-driven risk overlay for the CW2 monthly backtest engine."""

import math
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from ..risk.actions import PendingRiskAction, build_action_event
from .execution import CASH_SYMBOL, compute_period_simple_returns, normalize_long_only_weights
from .performance import compute_gross_return

try:
    from team_Pearson.coursework_one.modules.utils.kafka import (
        publish_json_events,
        resolve_kafka_config,
    )
    from team_Pearson.coursework_two.modules.ops.monitoring import record_ops_event
except ModuleNotFoundError:  # pragma: no cover - import-path fallback
    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_one.modules.utils.kafka import (
        publish_json_events,
        resolve_kafka_config,
    )
    from team_Pearson.coursework_two.modules.ops.monitoring import record_ops_event

_CASH = CASH_SYMBOL
_WEIGHT_TOL = 1e-12


@dataclass
class DailyPosition:
    symbol: str
    weight: float
    entry_price: float
    is_cash: bool = False


@dataclass
class IntradayState:
    positions: Dict[str, DailyPosition]
    cash_weight: float
    current_target_variant: str
    pending_target_variant: Optional[str]
    vix_recovery_days: int
    pending_regime_event: Optional[Dict[str, Any]] = None
    stopped_symbols: set[str] = field(default_factory=set)
    pending_symbol_actions: Dict[str, PendingRiskAction] = field(default_factory=dict)
    event_cooldowns: Dict[str, int] = field(default_factory=dict)


@dataclass
class IntradayPeriodResult:
    period_gross_return: float
    total_intraday_cost: float
    final_weights: Dict[str, float]
    events: List[Dict[str, Any]]
    final_target_variant: str
    intraday_stop_loss_count: int
    intraday_regime_switch_count: int
    daily_state: List[Dict[str, Any]]


def run_intraday_period(
    *,
    execution_date: date,
    next_execution_date: date,
    normal_target_weights: Mapping[str, float],
    stress_target_weights: Mapping[str, float],
    trading_calendar: Sequence[date],
    price_panel: pd.DataFrame,
    open_panel: pd.DataFrame,
    high_panel: pd.DataFrame,
    low_panel: pd.DataFrame,
    vix_series: pd.Series,
    term_spread_series: Optional[pd.Series] = None,
    event_signal_panels: Optional[Mapping[str, pd.DataFrame]] = None,
    initial_target_variant: str,
    config: Dict[str, Any],
    starting_weights: Optional[Mapping[str, float]] = None,
    monitor_engine: Any | None = None,
    monitor_run_id: Optional[str] = None,
) -> IntradayPeriodResult:
    """Simulate a daily risk overlay inside one monthly holding period."""
    intraday_cfg = _normalize_intraday_config(config)
    kafka_cfg = {"kafka": dict((config or {}).get("kafka") or {})}
    if not intraday_cfg["enabled"]:
        return _monthly_equivalent_result(
            execution_date=execution_date,
            next_execution_date=next_execution_date,
            trading_calendar=trading_calendar,
            price_panel=price_panel,
            target_weights=_resolve_initial_target_map(
                initial_target_variant,
                normal_target_weights,
                stress_target_weights,
            ),
            initial_target_variant=initial_target_variant,
            max_forward_fill_days=intraday_cfg["max_forward_fill_days"],
        )

    holding_days = [
        d
        for d in sorted({d for d in trading_calendar if d is not None})
        if execution_date <= d <= next_execution_date
    ]
    if not holding_days:
        return IntradayPeriodResult(
            period_gross_return=0.0,
            total_intraday_cost=0.0,
            final_weights={},
            events=[],
            final_target_variant=_normalize_variant(initial_target_variant),
            intraday_stop_loss_count=0,
            intraday_regime_switch_count=0,
            daily_state=[],
        )

    close_history = _normalize_history_panel(price_panel)
    close_filled, close_raw = _prepare_price_frame(
        price_panel,
        holding_days,
        intraday_cfg["max_forward_fill_days"],
    )
    open_filled, open_raw = _prepare_price_frame(
        open_panel,
        holding_days,
        intraday_cfg["max_forward_fill_days"],
    )
    _, high_raw = _prepare_price_frame(
        high_panel,
        holding_days,
        intraday_cfg["max_forward_fill_days"],
    )
    _, low_raw = _prepare_price_frame(
        low_panel,
        holding_days,
        intraday_cfg["max_forward_fill_days"],
    )
    vix_filled = (
        pd.to_numeric(vix_series, errors="coerce")
        .reindex(holding_days)
        .ffill(limit=intraday_cfg["max_forward_fill_days"])
    )
    term_spread_filled = (
        pd.to_numeric(term_spread_series, errors="coerce")
        .reindex(holding_days)
        .ffill(limit=intraday_cfg["max_forward_fill_days"])
        if term_spread_series is not None
        else pd.Series(dtype=float)
    )
    signal_frames = _normalize_event_signal_panels(event_signal_panels, holding_days)

    normal_map = _clean_weight_map(normal_target_weights)
    stress_map = _clean_weight_map(stress_target_weights)
    initial_map = (
        _clean_weight_map(starting_weights)
        if starting_weights is not None
        else _resolve_initial_target_map(
            initial_target_variant,
            normal_map,
            stress_map,
        )
    )
    state = _initialize_state(
        target_weights=initial_map,
        execution_date=execution_date,
        open_prices=open_filled,
        close_prices=close_filled,
        initial_target_variant=initial_target_variant,
    )

    events: List[Dict[str, Any]] = []
    daily_state_rows: List[Dict[str, Any]] = []
    total_intraday_cost = 0.0
    stop_loss_count = 0
    regime_switch_count = 0
    gross_multiplier = 1.0
    missing_streaks: Dict[str, int] = {}

    for idx, current_day in enumerate(holding_days):
        prev_day = holding_days[idx - 1] if idx > 0 else None
        is_entry_day = idx == 0
        regime_rebalanced_today = False
        _step_event_cooldowns(state)

        open_weights, open_multiplier = _mark_to_open(
            state,
            current_day=current_day,
            previous_day=prev_day,
            open_prices=open_filled,
            close_prices=close_filled,
        )
        nav_to_open = gross_multiplier * open_multiplier

        if state.pending_target_variant and not is_entry_day:
            state, regime_cost, regime_event = _apply_pending_regime_rebalance(
                state,
                current_day=current_day,
                open_weights=open_weights,
                nav_to_open=nav_to_open,
                open_prices=open_filled,
                normal_target_weights=normal_map,
                stress_target_weights=stress_map,
                config=intraday_cfg,
            )
            if regime_event is not None:
                total_intraday_cost += regime_cost
                regime_switch_count += 1
                events.append(regime_event)
                regime_rebalanced_today = True
            open_weights = _weights_from_state(state)
        else:
            _apply_open_weights_to_state(state, open_weights)

        state, open_weights, symbol_action_cost, symbol_action_events = (
            _apply_pending_symbol_actions(
                state,
                current_day=current_day,
                open_weights=_weights_from_state(state),
                nav_to_open=nav_to_open,
                open_prices=open_filled,
                vix_filled=vix_filled,
                holding_days=holding_days,
                day_index=idx,
                config=intraday_cfg,
            )
        )
        if symbol_action_events:
            total_intraday_cost += symbol_action_cost
            events.extend(symbol_action_events)

        if not regime_rebalanced_today and _should_mid_frequency_rebalance(
            current_day=current_day,
            day_index=idx,
            holding_days=holding_days,
            is_entry_day=is_entry_day,
            config=intraday_cfg,
        ):
            weekly_turnover = _preview_rebalance_turnover(
                state=state,
                current_variant=state.current_target_variant,
                open_weights=_weights_from_state(state),
                normal_target_weights=normal_map,
                stress_target_weights=stress_map,
                config=intraday_cfg,
            )
            if weekly_turnover >= float(intraday_cfg["mid_frequency_min_turnover"]) - _WEIGHT_TOL:
                state.pending_target_variant = state.current_target_variant
                state.pending_regime_event = build_action_event(
                    PendingRiskAction(
                        event_type="weekly_target_rebalance",
                        action_scope="portfolio",
                        action_family="drift_rebalance",
                        urgency="medium",
                        reason_code="weekly_drift_recentering",
                        scheduled_for=current_day,
                    ),
                    event_date=current_day,
                    regime_before=state.current_target_variant,
                    regime_after=state.current_target_variant,
                    vix_level=_safe_float(vix_filled.get(current_day)),
                    vix_daily_return=_compute_vix_return(vix_filled, holding_days, idx),
                    rebalance_scheduled_for=current_day,
                    expected_turnover=weekly_turnover,
                    expected_cost=nav_to_open
                    * weekly_turnover
                    * float(intraday_cfg["transaction_cost_rate"]),
                )
                _publish_requested_risk_action(
                    kafka_cfg,
                    PendingRiskAction(
                        event_type="weekly_target_rebalance",
                        action_scope="portfolio",
                        action_family="drift_rebalance",
                        urgency="medium",
                        reason_code="weekly_drift_recentering",
                        scheduled_for=current_day,
                    ),
                    trigger_date=current_day,
                    regime_before=state.current_target_variant,
                    regime_after=state.current_target_variant,
                    metadata={
                        "expected_turnover": weekly_turnover,
                        "expected_cost": nav_to_open
                        * weekly_turnover
                        * float(intraday_cfg["transaction_cost_rate"]),
                    },
                    monitor_engine=monitor_engine,
                    monitor_run_id=monitor_run_id,
                )
                state, weekly_cost, weekly_event = _apply_pending_regime_rebalance(
                    state,
                    current_day=current_day,
                    open_weights=_weights_from_state(state),
                    nav_to_open=nav_to_open,
                    open_prices=open_filled,
                    normal_target_weights=normal_map,
                    stress_target_weights=stress_map,
                    config=intraday_cfg,
                )
                if weekly_event is not None:
                    total_intraday_cost += weekly_cost
                    events.append(weekly_event)

        close_values: Dict[str, float] = {}
        cash_close_value = float(state.cash_weight)
        stopped_today: set[str] = set()

        for symbol, position in list(state.positions.items()):
            if position.is_cash or position.weight <= _WEIGHT_TOL:
                continue
            weight_open = float(position.weight)
            close_price = _series_value(close_filled, current_day, symbol)
            open_price = _series_value(open_filled, current_day, symbol, fallback=close_price)
            observed_open_price = _series_value(open_raw, current_day, symbol)
            observed_high_price = _series_value(high_raw, current_day, symbol)
            observed_low_price = _series_value(low_raw, current_day, symbol)
            raw_close_present = _series_present(close_raw, current_day, symbol)
            missing_streaks[symbol] = 0 if raw_close_present else missing_streaks.get(symbol, 0) + 1

            if open_price is None or close_price is None:
                cash_close_value += weight_open
                stopped_today.add(symbol)
                state.stopped_symbols.add(symbol)
                continue

            if missing_streaks[symbol] > intraday_cfg["max_forward_fill_days"]:
                # Past the forward-fill horizon, treat the name as delisted and park it in cash.
                cash_close_value += weight_open
                stopped_today.add(symbol)
                state.stopped_symbols.add(symbol)
                continue

            if is_entry_day:
                close_values[symbol] = weight_open * _safe_ratio(
                    close_price, open_price, default=1.0
                )
                continue

            stop_loss_pct = _resolve_stop_loss_pct(
                symbol=symbol,
                current_day=current_day,
                close_history=close_history,
                config=intraday_cfg,
            )
            stop_price = position.entry_price * (1.0 + stop_loss_pct)
            stop_triggered = False
            execution_price: Optional[float] = None
            if observed_open_price is not None and observed_open_price <= stop_price:
                execution_price = observed_open_price
                close_value = weight_open
                stop_triggered = True
            elif _has_observed_intraday_bar(
                open_panel=open_raw,
                high_panel=high_raw,
                low_panel=low_raw,
                row_date=current_day,
                symbol=symbol,
            ) and (
                observed_low_price is not None
                and observed_high_price is not None
                and observed_low_price <= stop_price <= observed_high_price
            ):
                execution_price = stop_price
                close_value = weight_open * _safe_ratio(execution_price, open_price, default=1.0)
                stop_triggered = True
            else:
                close_value = weight_open * _safe_ratio(close_price, open_price, default=1.0)

            if stop_triggered:
                stop_cost = nav_to_open * close_value * intraday_cfg["transaction_cost_rate"]
                total_intraday_cost += stop_cost
                stop_loss_count += 1
                cash_close_value += close_value
                stopped_today.add(symbol)
                state.stopped_symbols.add(symbol)
                events.append(
                    build_action_event(
                        PendingRiskAction(
                            event_type="stock_stop_loss",
                            action_scope="symbol",
                            action_family="risk_exit",
                            urgency="high",
                            reason_code="stop_loss_barrier",
                            scheduled_for=current_day,
                            symbol=symbol,
                        ),
                        event_date=current_day,
                        entry_price=position.entry_price,
                        open_price=observed_open_price,
                        high_price=observed_high_price,
                        low_price=observed_low_price,
                        execution_price=execution_price,
                        stop_loss_threshold=stop_loss_pct,
                        weight_before=weight_open,
                        weight_after=0.0,
                        regime_before=state.current_target_variant,
                        regime_after=state.current_target_variant,
                        vix_level=_safe_float(vix_filled.get(current_day)),
                        vix_daily_return=_compute_vix_return(vix_filled, holding_days, idx),
                        transaction_cost=stop_cost,
                        expected_turnover=weight_open,
                        expected_cost=stop_cost,
                    )
                )
            else:
                close_values[symbol] = close_value

        for symbol in stopped_today:
            state.positions.pop(symbol, None)

        # ``open_multiplier`` is NAV_open / NAV_prev_close based on prior close weights.
        # ``close_multiplier`` is NAV_close / NAV_open based on normalized open weights.
        # Multiplying them yields the full-day NAV_close / NAV_prev_close exactly once.
        close_multiplier = cash_close_value + sum(close_values.values())
        gross_multiplier *= max(0.0, open_multiplier * close_multiplier)
        total_close = close_multiplier
        if total_close <= _WEIGHT_TOL:
            state.positions = {}
            state.cash_weight = 1.0
        else:
            next_positions: Dict[str, DailyPosition] = {}
            for symbol, close_value in close_values.items():
                position = state.positions.get(symbol)
                if position is None:
                    continue
                next_positions[symbol] = DailyPosition(
                    symbol=symbol,
                    weight=close_value / total_close,
                    entry_price=position.entry_price,
                    is_cash=False,
                )
            state.positions = next_positions
            state.cash_weight = max(0.0, cash_close_value / total_close)

        _update_vix_state(
            state,
            current_day=current_day,
            day_index=idx,
            holding_days=holding_days,
            vix_filled=vix_filled,
            term_spread_filled=term_spread_filled,
            config=intraday_cfg,
            kafka_config=kafka_cfg,
            monitor_engine=monitor_engine,
            monitor_run_id=monitor_run_id,
        )

        if idx < len(holding_days) - 1:
            _schedule_event_risk_actions(
                state,
                current_day=current_day,
                next_day=holding_days[idx + 1],
                signal_frames=signal_frames,
                config=intraday_cfg,
                kafka_config=kafka_cfg,
                monitor_engine=monitor_engine,
                monitor_run_id=monitor_run_id,
            )

        if intraday_cfg["save_daily_state"]:
            daily_state_rows.extend(
                _build_daily_state_rows(
                    state,
                    current_day=current_day,
                    close_prices=close_filled,
                )
            )

    final_weights = _weights_from_state(state)
    period_gross_return = max(-1.0, gross_multiplier - 1.0)

    return IntradayPeriodResult(
        period_gross_return=period_gross_return,
        total_intraday_cost=total_intraday_cost,
        final_weights=final_weights,
        events=events,
        final_target_variant=state.current_target_variant,
        intraday_stop_loss_count=stop_loss_count,
        intraday_regime_switch_count=regime_switch_count,
        daily_state=daily_state_rows,
    )


def _monthly_equivalent_result(
    *,
    execution_date: date,
    next_execution_date: date,
    trading_calendar: Sequence[date],
    price_panel: pd.DataFrame,
    target_weights: Mapping[str, float],
    initial_target_variant: str,
    max_forward_fill_days: int,
) -> IntradayPeriodResult:
    returns, _ = compute_period_simple_returns(
        price_panel,
        trading_calendar,
        execution_date,
        next_execution_date,
        max_forward_fill_days=max_forward_fill_days,
    )
    gross = compute_gross_return(target_weights, returns)
    final_weights = _drift_weights(target_weights, returns)
    return IntradayPeriodResult(
        period_gross_return=gross,
        total_intraday_cost=0.0,
        final_weights=final_weights,
        events=[],
        final_target_variant=_normalize_variant(initial_target_variant),
        intraday_stop_loss_count=0,
        intraday_regime_switch_count=0,
        daily_state=[],
    )


def _prepare_price_frame(
    panel: pd.DataFrame,
    holding_days: Sequence[date],
    max_forward_fill_days: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    raw = panel.copy() if panel is not None else pd.DataFrame()
    raw.index = pd.to_datetime(raw.index, errors="coerce").date
    raw = raw.sort_index().reindex(holding_days)
    raw = raw.apply(pd.to_numeric, errors="coerce")
    filled = raw.ffill(limit=max_forward_fill_days)
    return filled, raw


def _normalize_history_panel(panel: pd.DataFrame) -> pd.DataFrame:
    raw = panel.copy() if panel is not None else pd.DataFrame()
    raw.index = pd.to_datetime(raw.index, errors="coerce").date
    raw = raw.sort_index().apply(pd.to_numeric, errors="coerce")
    return raw


def _initialize_state(
    *,
    target_weights: Mapping[str, float],
    execution_date: date,
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    initial_target_variant: str,
) -> IntradayState:
    cleaned = _clean_weight_map(target_weights)
    positions: Dict[str, DailyPosition] = {}
    for symbol, weight in cleaned.items():
        close_price = _series_value(close_prices, execution_date, symbol)
        open_price = _series_value(open_prices, execution_date, symbol, fallback=close_price)
        entry_price = open_price or close_price or 1.0
        positions[symbol] = DailyPosition(
            symbol=symbol,
            weight=float(weight),
            entry_price=float(entry_price),
            is_cash=False,
        )
    return IntradayState(
        positions=positions,
        cash_weight=0.0,
        current_target_variant=_normalize_variant(initial_target_variant),
        pending_target_variant=None,
        vix_recovery_days=0,
    )


def _mark_to_open(
    state: IntradayState,
    *,
    current_day: date,
    previous_day: Optional[date],
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
) -> Tuple[Dict[str, float], float]:
    if previous_day is None:
        return _weights_from_state(state), 1.0

    values: Dict[str, float] = {}
    for symbol, position in state.positions.items():
        prev_close = _series_value(close_prices, previous_day, symbol)
        open_price = _series_value(open_prices, current_day, symbol, fallback=prev_close)
        if prev_close is None or open_price is None or prev_close <= 0:
            values[symbol] = float(position.weight)
        else:
            values[symbol] = float(position.weight) * float(open_price) / float(prev_close)
    values[_CASH] = float(state.cash_weight)
    total_open = sum(values.values())
    if total_open <= _WEIGHT_TOL:
        return {_CASH: 1.0}, 1.0
    return _normalize_full_weights(values), float(total_open)


def _apply_open_weights_to_state(state: IntradayState, open_weights: Mapping[str, float]) -> None:
    for symbol, position in list(state.positions.items()):
        if symbol in open_weights:
            position.weight = float(open_weights[symbol])
        else:
            state.positions.pop(symbol, None)
    state.cash_weight = float(open_weights.get(_CASH, 0.0))


def _apply_pending_regime_rebalance(
    state: IntradayState,
    *,
    current_day: date,
    open_weights: Mapping[str, float],
    nav_to_open: float,
    open_prices: pd.DataFrame,
    normal_target_weights: Mapping[str, float],
    stress_target_weights: Mapping[str, float],
    config: Dict[str, Any],
) -> Tuple[IntradayState, float, Optional[Dict[str, Any]]]:
    target_variant = _normalize_variant(state.pending_target_variant)
    target_map = stress_target_weights if target_variant == "stress" else normal_target_weights
    allow_reentry = bool(config.get("allow_reentry_after_stop_loss", False))
    target_total = _build_rebalance_target_total(
        target_map=target_map,
        open_weights=open_weights,
        stopped_symbols=state.stopped_symbols,
        allow_reentry=allow_reentry,
    )
    pre_trade = _normalize_full_weights(open_weights)
    cash_weight = float(pre_trade.get(_CASH, 0.0))
    target_total = _normalize_full_weights(target_total)
    turnover = _compute_total_turnover(target_total, pre_trade)
    cost = nav_to_open * turnover * float(config["transaction_cost_rate"])

    new_positions: Dict[str, DailyPosition] = {}
    for symbol, target_weight in target_total.items():
        if symbol == _CASH or target_weight <= _WEIGHT_TOL:
            continue
        prior_weight = float(pre_trade.get(symbol, 0.0))
        execution_price = _series_value(open_prices, current_day, symbol) or 1.0
        prior_position = state.positions.get(symbol)
        if prior_position is None or prior_weight <= _WEIGHT_TOL:
            entry_price = float(execution_price)
        elif target_weight > prior_weight + _WEIGHT_TOL:
            add_weight = target_weight - prior_weight
            entry_price = (
                prior_weight * float(prior_position.entry_price)
                + add_weight * float(execution_price)
            ) / target_weight
        else:
            entry_price = float(prior_position.entry_price)
        new_positions[symbol] = DailyPosition(
            symbol=symbol,
            weight=float(target_weight),
            entry_price=float(entry_price),
            is_cash=False,
        )

    state.positions = new_positions
    state.cash_weight = float(target_total.get(_CASH, 0.0))
    if allow_reentry and state.stopped_symbols:
        state.stopped_symbols.difference_update(new_positions)
    event = dict(state.pending_regime_event or {})
    if event:
        event["weight_before"] = max(0.0, 1.0 - cash_weight)
        event["weight_after"] = max(0.0, 1.0 - state.cash_weight)
        event["transaction_cost"] = cost
        if event.get("expected_turnover") is None:
            event["expected_turnover"] = turnover
        if event.get("expected_cost") is None:
            event["expected_cost"] = cost
    state.current_target_variant = target_variant
    state.pending_target_variant = None
    state.pending_regime_event = None
    return state, cost, event or None


def _apply_pending_symbol_actions(
    state: IntradayState,
    *,
    current_day: date,
    open_weights: Mapping[str, float],
    nav_to_open: float,
    open_prices: pd.DataFrame,
    vix_filled: pd.Series,
    holding_days: Sequence[date],
    day_index: int,
    config: Dict[str, Any],
) -> Tuple[IntradayState, Dict[str, float], float, List[Dict[str, Any]]]:
    due_actions = [
        action
        for action in state.pending_symbol_actions.values()
        if action.scheduled_for == current_day
    ]
    if not due_actions:
        normalized = _normalize_full_weights(open_weights)
        _apply_open_weights_to_state(state, normalized)
        return state, normalized, 0.0, []

    updated_weights = _normalize_full_weights(open_weights)
    total_cost = 0.0
    events: List[Dict[str, Any]] = []

    for action in due_actions:
        symbol = str(action.symbol or "").strip()
        before_weight = float(updated_weights.get(symbol, 0.0))
        if not symbol or before_weight <= _WEIGHT_TOL:
            state.pending_symbol_actions.pop(symbol, None)
            continue
        if action.event_type not in {
            "news_sentiment_trim",
            "earnings_negative_trim",
            "rating_downgrade_trim",
        }:
            state.pending_symbol_actions.pop(symbol, None)
            continue

        trim_fraction = min(1.0, max(0.0, float(action.trim_fraction or 0.0)))
        trim_weight = before_weight * trim_fraction
        after_weight = before_weight - trim_weight
        execution_price = _series_value(open_prices, current_day, symbol) or 1.0
        updated_weights[_CASH] = float(updated_weights.get(_CASH, 0.0)) + trim_weight
        if after_weight > _WEIGHT_TOL:
            updated_weights[symbol] = after_weight
        else:
            updated_weights.pop(symbol, None)
        action_cost = nav_to_open * trim_weight * float(config["transaction_cost_rate"])
        total_cost += action_cost

        position = state.positions.get(symbol)
        events.append(
            build_action_event(
                action,
                event_date=current_day,
                entry_price=(float(position.entry_price) if position is not None else None),
                open_price=execution_price,
                execution_price=execution_price,
                weight_before=before_weight,
                weight_after=max(0.0, after_weight),
                regime_before=state.current_target_variant,
                regime_after=state.current_target_variant,
                vix_level=_safe_float(vix_filled.get(current_day)),
                vix_daily_return=_compute_vix_return(vix_filled, holding_days, day_index),
                transaction_cost=action_cost,
                expected_turnover=trim_weight,
                expected_cost=action_cost,
            )
        )
        state.pending_symbol_actions.pop(symbol, None)

    updated_weights = _normalize_full_weights(updated_weights)
    _apply_open_weights_to_state(state, updated_weights)
    return state, updated_weights, total_cost, events


def _schedule_event_risk_actions(
    state: IntradayState,
    *,
    current_day: date,
    next_day: date,
    signal_frames: Mapping[str, pd.DataFrame],
    config: Dict[str, Any],
    kafka_config: Optional[Mapping[str, Any]] = None,
    monitor_engine: Any | None = None,
    monitor_run_id: Optional[str] = None,
) -> None:
    if not bool(config.get("event_driven_enabled", False)):
        return
    cooldown_days = max(0, int(config.get("event_cooldown_days", 5)))
    surprise_panel = signal_frames.get("sentiment_surprise")
    article_panel = signal_frames.get("article_count_30d")
    earnings_flag_panel = signal_frames.get("earnings_publication_flag")
    earnings_negative_panel = signal_frames.get("earnings_negative_news_count_daily")
    earnings_news_panel = signal_frames.get("earnings_news_count_daily")
    rating_downgrade_panel = signal_frames.get("rating_downgrade_count_daily")

    for symbol, position in state.positions.items():
        if position.is_cash or position.weight <= _WEIGHT_TOL:
            continue
        if state.event_cooldowns.get(symbol, 0) > 0:
            continue

        if bool(config.get("news_sentiment_shock_enabled", False)):
            surprise = _series_value(surprise_panel, current_day, symbol)
            article_count = _series_value(article_panel, current_day, symbol)
            threshold = float(config.get("news_sentiment_surprise_threshold", -0.15))
            min_articles = float(config.get("news_sentiment_min_article_count", 5.0))
            trim_fraction = min(
                1.0,
                max(0.0, float(config.get("news_sentiment_trim_fraction", 0.5))),
            )
            if (
                surprise is not None
                and article_count is not None
                and surprise <= threshold
                and article_count >= min_articles
            ):
                pending_action = PendingRiskAction(
                    event_type="news_sentiment_trim",
                    action_scope="symbol",
                    action_family="event_de_risk",
                    urgency="high",
                    reason_code="negative_sentiment_surprise",
                    scheduled_for=next_day,
                    symbol=symbol,
                    trim_fraction=trim_fraction,
                    metadata={
                        "trigger_date": current_day.isoformat(),
                        "sentiment_surprise": surprise,
                        "article_count_30d": article_count,
                    },
                )
                if _queue_symbol_risk_action(state, pending_action):
                    _publish_requested_risk_action(
                        kafka_config,
                        pending_action,
                        trigger_date=current_day,
                        regime_before=state.current_target_variant,
                        regime_after=state.current_target_variant,
                        monitor_engine=monitor_engine,
                        monitor_run_id=monitor_run_id,
                    )

        if bool(config.get("earnings_event_enabled", False)):
            publication_flag = _series_value(earnings_flag_panel, current_day, symbol)
            negative_count = _series_value(earnings_negative_panel, current_day, symbol)
            earnings_count = _series_value(earnings_news_panel, current_day, symbol)
            require_publication = bool(config.get("earnings_require_publication_flag", True))
            min_negative_count = float(config.get("earnings_negative_news_min_count", 1.0))
            trim_fraction = min(
                1.0,
                max(0.0, float(config.get("earnings_trim_fraction", 0.75))),
            )
            publication_ok = (publication_flag or 0.0) >= 0.5 if require_publication else True
            if (
                publication_ok
                and negative_count is not None
                and negative_count >= min_negative_count
            ):
                pending_action = PendingRiskAction(
                    event_type="earnings_negative_trim",
                    action_scope="symbol",
                    action_family="earnings_event",
                    urgency="high",
                    reason_code="negative_earnings_news_after_publication",
                    scheduled_for=next_day,
                    symbol=symbol,
                    trim_fraction=trim_fraction,
                    metadata={
                        "trigger_date": current_day.isoformat(),
                        "earnings_publication_flag": publication_flag,
                        "earnings_negative_news_count_daily": negative_count,
                        "earnings_news_count_daily": earnings_count,
                    },
                )
                if _queue_symbol_risk_action(state, pending_action):
                    _publish_requested_risk_action(
                        kafka_config,
                        pending_action,
                        trigger_date=current_day,
                        regime_before=state.current_target_variant,
                        regime_after=state.current_target_variant,
                        monitor_engine=monitor_engine,
                        monitor_run_id=monitor_run_id,
                    )

        if bool(config.get("rating_downgrade_event_enabled", False)):
            downgrade_count = _series_value(rating_downgrade_panel, current_day, symbol)
            min_downgrades = float(config.get("rating_downgrade_min_count", 1.0))
            trim_fraction = min(
                1.0,
                max(0.0, float(config.get("rating_trim_fraction", 0.35))),
            )
            if downgrade_count is not None and downgrade_count >= min_downgrades:
                pending_action = PendingRiskAction(
                    event_type="rating_downgrade_trim",
                    action_scope="symbol",
                    action_family="rating_event",
                    urgency="medium",
                    reason_code="analyst_downgrade_news",
                    scheduled_for=next_day,
                    symbol=symbol,
                    trim_fraction=trim_fraction,
                    metadata={
                        "trigger_date": current_day.isoformat(),
                        "rating_downgrade_count_daily": downgrade_count,
                    },
                )
                if _queue_symbol_risk_action(state, pending_action):
                    _publish_requested_risk_action(
                        kafka_config,
                        pending_action,
                        trigger_date=current_day,
                        regime_before=state.current_target_variant,
                        regime_after=state.current_target_variant,
                        monitor_engine=monitor_engine,
                        monitor_run_id=monitor_run_id,
                    )

        if symbol in state.pending_symbol_actions and cooldown_days > 0:
            state.event_cooldowns[symbol] = cooldown_days


def _normalize_event_signal_panels(
    signal_panels: Optional[Mapping[str, pd.DataFrame]],
    holding_days: Sequence[date],
) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for name, panel in (signal_panels or {}).items():
        if panel is None:
            out[str(name)] = pd.DataFrame()
            continue
        normalized = panel.copy()
        normalized.index = pd.to_datetime(normalized.index, errors="coerce").date
        normalized = normalized.sort_index().reindex(holding_days)
        out[str(name)] = normalized.apply(pd.to_numeric, errors="coerce")
    return out


def _step_event_cooldowns(state: IntradayState) -> None:
    if not state.event_cooldowns:
        return
    state.event_cooldowns = {
        symbol: days_left - 1
        for symbol, days_left in state.event_cooldowns.items()
        if int(days_left) > 1
    }


def _queue_symbol_risk_action(state: IntradayState, action: PendingRiskAction) -> bool:
    """Queue one symbol-level action, keeping the stronger action when multiple collide."""
    symbol = str(action.symbol or "").strip()
    if not symbol:
        return False
    existing = state.pending_symbol_actions.get(symbol)
    if existing is None:
        state.pending_symbol_actions[symbol] = action
        return True
    existing_trim = float(existing.trim_fraction or 0.0)
    new_trim = float(action.trim_fraction or 0.0)
    if new_trim > existing_trim + _WEIGHT_TOL:
        state.pending_symbol_actions[symbol] = action
        return True
    if math.isclose(new_trim, existing_trim, rel_tol=0.0, abs_tol=_WEIGHT_TOL):
        if _risk_urgency_rank(action.urgency) > _risk_urgency_rank(existing.urgency):
            state.pending_symbol_actions[symbol] = action
            return True
    return False


def _risk_urgency_rank(value: Any) -> int:
    text = str(value or "").strip().lower()
    if text == "high":
        return 3
    if text == "medium":
        return 2
    return 1


def _severity_from_urgency(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"critical"}:
        return "critical"
    if text in {"high", "medium"}:
        return "warning"
    return "info"


def _update_vix_state(
    state: IntradayState,
    *,
    current_day: date,
    day_index: int,
    holding_days: Sequence[date],
    vix_filled: pd.Series,
    term_spread_filled: pd.Series,
    config: Dict[str, Any],
    kafka_config: Optional[Mapping[str, Any]] = None,
    monitor_engine: Any | None = None,
    monitor_run_id: Optional[str] = None,
) -> None:
    vix_level = _safe_float(vix_filled.get(current_day))
    vix_return = _compute_vix_return(vix_filled, holding_days, day_index)
    term_spread_level = (
        _safe_float(term_spread_filled.get(current_day)) if term_spread_filled is not None else None
    )

    if state.current_target_variant == "stress":
        if vix_level is not None and vix_level < config["vix_recovery_threshold"]:
            state.vix_recovery_days += 1
        else:
            state.vix_recovery_days = 0
    else:
        state.vix_recovery_days = 0

    if day_index >= len(holding_days) - 1:
        return

    next_day = holding_days[day_index + 1]
    if (
        state.current_target_variant != "stress"
        and state.pending_target_variant is None
        and vix_return is not None
        and vix_return > config["vix_spike_pct"]
        and (vix_level is not None and vix_level >= config["vix_spike_min_level"])
        and _term_spread_confirms_stress(term_spread_level, vix_level=vix_level, config=config)
    ):
        state.pending_target_variant = "stress"
        pending_action = PendingRiskAction(
            event_type="vix_spike_regime",
            action_scope="portfolio",
            action_family="regime_switch",
            urgency="high",
            reason_code="macro_volatility_spike",
            scheduled_for=next_day,
            target_variant="stress",
        )
        state.pending_regime_event = build_action_event(
            pending_action,
            event_date=current_day,
            regime_before=state.current_target_variant,
            regime_after="stress",
            vix_level=vix_level,
            vix_daily_return=vix_return,
            rebalance_scheduled_for=next_day,
        )
        _publish_requested_risk_action(
            kafka_config,
            pending_action,
            trigger_date=current_day,
            regime_before=state.current_target_variant,
            regime_after="stress",
            metadata={
                "vix_level": vix_level,
                "vix_daily_return": vix_return,
                "term_spread_level": term_spread_level,
            },
            monitor_engine=monitor_engine,
            monitor_run_id=monitor_run_id,
        )
        return

    if (
        state.current_target_variant == "stress"
        and state.pending_target_variant is None
        and state.vix_recovery_days >= config["vix_recovery_consecutive_days"]
    ):
        state.pending_target_variant = "normal"
        pending_action = PendingRiskAction(
            event_type="vix_recovery_regime",
            action_scope="portfolio",
            action_family="regime_switch",
            urgency="medium",
            reason_code="macro_volatility_recovery",
            scheduled_for=next_day,
            target_variant="normal",
        )
        state.pending_regime_event = build_action_event(
            pending_action,
            event_date=current_day,
            regime_before=state.current_target_variant,
            regime_after="normal",
            vix_level=vix_level,
            vix_daily_return=vix_return,
            rebalance_scheduled_for=next_day,
        )
        _publish_requested_risk_action(
            kafka_config,
            pending_action,
            trigger_date=current_day,
            regime_before=state.current_target_variant,
            regime_after="normal",
            metadata={"vix_level": vix_level, "vix_daily_return": vix_return},
            monitor_engine=monitor_engine,
            monitor_run_id=monitor_run_id,
        )


def _build_daily_state_rows(
    state: IntradayState,
    *,
    current_day: date,
    close_prices: pd.DataFrame,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for symbol, position in state.positions.items():
        current_price = _series_value(close_prices, current_day, symbol)
        unrealized_return = None
        if current_price is not None and position.entry_price > 0:
            unrealized_return = current_price / position.entry_price - 1.0
        rows.append(
            {
                "state_date": current_day,
                "symbol": symbol,
                "weight": float(position.weight),
                "entry_price": float(position.entry_price),
                "current_price": current_price,
                "unrealized_return": unrealized_return,
                "regime": state.current_target_variant,
                "is_cash": False,
            }
        )
    if state.cash_weight > _WEIGHT_TOL:
        rows.append(
            {
                "state_date": current_day,
                "symbol": _CASH,
                "weight": float(state.cash_weight),
                "entry_price": None,
                "current_price": 1.0,
                "unrealized_return": 0.0,
                "regime": state.current_target_variant,
                "is_cash": True,
            }
        )
    return rows


def _publish_requested_risk_action(
    kafka_config: Optional[Mapping[str, Any]],
    action: PendingRiskAction,
    *,
    trigger_date: date,
    regime_before: Optional[str],
    regime_after: Optional[str],
    metadata: Optional[Mapping[str, Any]] = None,
    monitor_engine: Any | None = None,
    monitor_run_id: Optional[str] = None,
) -> None:
    payload = {
        "event_id": (
            f"{trigger_date.isoformat()}:{action.scheduled_for.isoformat()}:"
            f"{action.event_type}:{str(action.symbol or '').strip().upper()}"
        ),
        "event_type": action.event_type,
        "trigger_date": trigger_date,
        "scheduled_for": action.scheduled_for,
        "symbol": str(action.symbol or "").strip().upper(),
        "target_variant": action.target_variant,
        "trim_fraction": action.trim_fraction,
        "action_scope": action.action_scope,
        "action_family": action.action_family,
        "urgency": action.urgency,
        "reason_code": action.reason_code,
        "regime_before": regime_before,
        "regime_after": regime_after,
        "source": "cw2.intraday_overlay",
        "metadata": dict(action.metadata or {}),
    }
    if metadata:
        payload["metadata"].update({str(k): v for k, v in metadata.items()})
    published = publish_json_events(
        kafka_config or {},
        topic_key="cw2_risk_actions_requested",
        default_topic="cw2.risk.actions.requested.v1",
        events=[payload],
        key_field="symbol",
        default_client_id="team_pearson_cw2",
    )
    if monitor_engine is not None:
        resolved = resolve_kafka_config(kafka_config or {}, default_client_id="team_pearson_cw2")
        publish_status = (
            "published" if published > 0 else ("disabled" if not resolved.enabled else "suppressed")
        )
        topic_name = str(
            resolved.topics.get("cw2_risk_actions_requested", "cw2.risk.actions.requested.v1")
        )
        record_ops_event(
            engine=monitor_engine,
            event_id=payload["event_id"],
            event_time=payload["trigger_date"],
            event_type=payload["event_type"],
            producer_component="cw2.intraday_overlay",
            topic_key="cw2_risk_actions_requested",
            topic_name=topic_name,
            run_id=monitor_run_id,
            symbol=payload["symbol"],
            severity=_severity_from_urgency(payload.get("urgency")),
            publish_status=publish_status,
            payload=payload,
        )


def _resolve_initial_target_map(
    initial_target_variant: str,
    normal_target_weights: Mapping[str, float],
    stress_target_weights: Mapping[str, float],
) -> Dict[str, float]:
    variant = _normalize_variant(initial_target_variant)
    if variant == "stress" and stress_target_weights:
        return _clean_weight_map(stress_target_weights)
    if normal_target_weights:
        return _clean_weight_map(normal_target_weights)
    return _clean_weight_map(stress_target_weights)


def _drift_weights(weights: Mapping[str, float], returns: Mapping[str, float]) -> Dict[str, float]:
    values = {
        symbol: float(weight) * (1.0 + float(returns.get(symbol, 0.0)))
        for symbol, weight in weights.items()
        if symbol != _CASH and float(weight) > _WEIGHT_TOL
    }
    return _normalize_full_weights(values)


def _weights_from_state(state: IntradayState) -> Dict[str, float]:
    weights = {
        symbol: float(position.weight)
        for symbol, position in state.positions.items()
        if not position.is_cash and float(position.weight) > _WEIGHT_TOL
    }
    if state.cash_weight > _WEIGHT_TOL:
        weights[_CASH] = float(state.cash_weight)
    return _normalize_full_weights(weights)


def _build_rebalance_target_total(
    *,
    target_map: Mapping[str, float],
    open_weights: Mapping[str, float],
    stopped_symbols: set[str],
    allow_reentry: bool,
) -> Dict[str, float]:
    available_targets = {
        symbol: weight
        for symbol, weight in _clean_weight_map(target_map).items()
        if allow_reentry or symbol not in stopped_symbols
    }
    cash_weight = float(open_weights.get(_CASH, 0.0))
    investable_weight = 1.0 if allow_reentry else max(0.0, 1.0 - cash_weight)

    if available_targets and investable_weight > _WEIGHT_TOL:
        normalized_targets = normalize_long_only_weights(available_targets)
        target_total = {
            symbol: weight * investable_weight for symbol, weight in normalized_targets.items()
        }
    else:
        target_total = {}
    target_total[_CASH] = 0.0 if allow_reentry and available_targets else cash_weight
    return target_total


def _preview_rebalance_turnover(
    *,
    state: IntradayState,
    current_variant: str,
    open_weights: Mapping[str, float],
    normal_target_weights: Mapping[str, float],
    stress_target_weights: Mapping[str, float],
    config: Dict[str, Any],
) -> float:
    target_map = (
        stress_target_weights
        if _normalize_variant(current_variant) == "stress"
        else normal_target_weights
    )
    target_total = _normalize_full_weights(
        _build_rebalance_target_total(
            target_map=target_map,
            open_weights=open_weights,
            stopped_symbols=state.stopped_symbols,
            allow_reentry=bool(config.get("allow_reentry_after_stop_loss", False)),
        )
    )
    return _compute_total_turnover(target_total, _normalize_full_weights(open_weights))


def _should_mid_frequency_rebalance(
    *,
    current_day: date,
    day_index: int,
    holding_days: Sequence[date],
    is_entry_day: bool,
    config: Dict[str, Any],
) -> bool:
    if not bool(config.get("mid_frequency_rebalance_enabled", False)):
        return False
    if is_entry_day or day_index >= len(holding_days) - 1:
        return False
    return current_day.weekday() == int(config.get("mid_frequency_rebalance_weekday", 0))


def _normalize_intraday_config(config: Dict[str, Any]) -> Dict[str, Any]:
    backtest_cfg = (config.get("backtest") or {}) if "backtest" in config else {}
    raw = backtest_cfg.get("intraday_triggers") or config.get("intraday_triggers") or {}
    vix_recovery_threshold = float(raw.get("vix_recovery_threshold", 25.0))
    return {
        "enabled": bool(raw.get("enabled", False)),
        "stock_stop_loss_pct": float(raw.get("stock_stop_loss_pct", -0.09)),
        "stop_loss_mode": str(raw.get("stop_loss_mode", "fixed_pct")).strip().lower(),
        "stop_loss_vol_lookback_days": max(2, int(raw.get("stop_loss_vol_lookback_days", 20))),
        "stop_loss_min_history_days": max(2, int(raw.get("stop_loss_min_history_days", 10))),
        "stop_loss_vol_multiplier": max(0.0, float(raw.get("stop_loss_vol_multiplier", 2.5))),
        "stop_loss_min_abs_pct": max(0.0, float(raw.get("stop_loss_min_abs_pct", 0.05))),
        "stop_loss_max_abs_pct": max(0.0, float(raw.get("stop_loss_max_abs_pct", 0.15))),
        "vix_spike_pct": float(raw.get("vix_spike_pct", 0.25)),
        "vix_spike_min_level": float(raw.get("vix_spike_min_level", vix_recovery_threshold)),
        "term_spread_confirm_enabled": bool(raw.get("term_spread_confirm_enabled", False)),
        "term_spread_stress_threshold": float(raw.get("term_spread_stress_threshold", 0.0)),
        "vix_hard_stress_level": float(raw.get("vix_hard_stress_level", 35.0)),
        "vix_recovery_threshold": vix_recovery_threshold,
        "vix_recovery_consecutive_days": max(1, int(raw.get("vix_recovery_consecutive_days", 4))),
        "regime_switch_mode": str(raw.get("regime_switch_mode", "next_day_rebalance"))
        .strip()
        .lower(),
        "allow_reentry_after_stop_loss": bool(raw.get("allow_reentry_after_stop_loss", False)),
        "mid_frequency_rebalance_enabled": bool(raw.get("mid_frequency_rebalance_enabled", False)),
        "mid_frequency_rebalance_weekday": int(raw.get("mid_frequency_rebalance_weekday", 0)),
        "mid_frequency_min_turnover": max(0.0, float(raw.get("mid_frequency_min_turnover", 0.05))),
        "event_driven_enabled": bool(raw.get("event_driven_enabled", False)),
        "news_sentiment_shock_enabled": bool(raw.get("news_sentiment_shock_enabled", False)),
        "news_sentiment_surprise_threshold": float(
            raw.get("news_sentiment_surprise_threshold", -0.20)
        ),
        "news_sentiment_min_article_count": float(raw.get("news_sentiment_min_article_count", 8.0)),
        "news_sentiment_trim_fraction": float(raw.get("news_sentiment_trim_fraction", 0.25)),
        "earnings_event_enabled": bool(raw.get("earnings_event_enabled", False)),
        "earnings_require_publication_flag": bool(
            raw.get("earnings_require_publication_flag", True)
        ),
        "earnings_negative_news_min_count": float(raw.get("earnings_negative_news_min_count", 2.0)),
        "earnings_trim_fraction": float(raw.get("earnings_trim_fraction", 0.40)),
        "rating_downgrade_event_enabled": bool(raw.get("rating_downgrade_event_enabled", False)),
        "rating_downgrade_min_count": float(raw.get("rating_downgrade_min_count", 2.0)),
        "rating_trim_fraction": float(raw.get("rating_trim_fraction", 0.20)),
        "event_cooldown_days": int(raw.get("event_cooldown_days", 5)),
        "transaction_cost_bps": float(
            raw.get(
                "transaction_cost_bps",
                (backtest_cfg or config).get("transaction_cost_bps", 15),
            )
        ),
        "transaction_cost_rate": float(
            raw.get(
                "transaction_cost_bps",
                (backtest_cfg or config).get("transaction_cost_bps", 15),
            )
        )
        / 10000.0,
        "save_daily_state": bool(raw.get("save_daily_state", False)),
        "max_forward_fill_days": max(
            0,
            int(
                raw.get(
                    "max_forward_fill_days",
                    (backtest_cfg or config).get("max_forward_fill_days", 5),
                )
            ),
        ),
    }


def _clean_weight_map(weights: Mapping[str, float]) -> Dict[str, float]:
    clean = {
        str(symbol): float(weight)
        for symbol, weight in (weights or {}).items()
        if str(symbol).strip()
        and str(symbol).strip() != _CASH
        and _safe_float(weight) is not None
        and float(weight) > _WEIGHT_TOL
    }
    return normalize_long_only_weights(clean)


def _normalize_full_weights(weights: Mapping[str, float]) -> Dict[str, float]:
    clean: Dict[str, float] = {}
    total = 0.0
    for symbol, value in (weights or {}).items():
        weight = _safe_float(value)
        if weight is None or weight <= _WEIGHT_TOL:
            continue
        clean[str(symbol)] = float(weight)
        total += float(weight)
    if total <= _WEIGHT_TOL:
        return {}
    return {symbol: weight / total for symbol, weight in clean.items()}


def _compute_total_turnover(
    target_weights: Mapping[str, float], current_weights: Mapping[str, float]
) -> float:
    all_symbols = set(target_weights) | set(current_weights)
    return sum(
        abs(float(target_weights.get(symbol, 0.0)) - float(current_weights.get(symbol, 0.0)))
        for symbol in all_symbols
    )


def _compute_vix_return(
    vix_filled: pd.Series, holding_days: Sequence[date], day_index: int
) -> Optional[float]:
    if day_index <= 0:
        return None
    today = _safe_float(vix_filled.get(holding_days[day_index]))
    prev = _safe_float(vix_filled.get(holding_days[day_index - 1]))
    if today is None or prev is None or prev <= 0:
        return None
    return today / prev - 1.0


def _term_spread_confirms_stress(
    term_spread_level: Optional[float],
    *,
    vix_level: Optional[float],
    config: Dict[str, Any],
) -> bool:
    if vix_level is not None and vix_level >= float(config.get("vix_hard_stress_level", 35.0)):
        return True
    if not bool(config.get("term_spread_confirm_enabled", False)):
        return True
    if term_spread_level is None:
        return False
    return float(term_spread_level) <= float(config.get("term_spread_stress_threshold", 0.0))


def _resolve_stop_loss_pct(
    *,
    symbol: str,
    current_day: date,
    close_history: pd.DataFrame,
    config: Dict[str, Any],
) -> float:
    base_pct = float(config["stock_stop_loss_pct"])
    if str(config.get("stop_loss_mode", "fixed_pct")).strip().lower() != "vol_scaled":
        return base_pct

    realized_vol = _estimate_realized_volatility(
        close_history,
        symbol=symbol,
        current_day=current_day,
        lookback_days=int(config["stop_loss_vol_lookback_days"]),
        min_history_days=int(config["stop_loss_min_history_days"]),
    )
    if realized_vol is None:
        return base_pct

    scaled_abs = float(config["stop_loss_vol_multiplier"]) * float(realized_vol)
    min_abs = max(0.0, float(config["stop_loss_min_abs_pct"]))
    max_abs = max(min_abs, float(config["stop_loss_max_abs_pct"]))
    clipped_abs = min(max_abs, max(min_abs, scaled_abs))
    return -clipped_abs


def _estimate_realized_volatility(
    close_history: pd.DataFrame,
    *,
    symbol: str,
    current_day: date,
    lookback_days: int,
    min_history_days: int,
) -> Optional[float]:
    if close_history is None or close_history.empty or symbol not in close_history.columns:
        return None
    series = pd.to_numeric(close_history[symbol], errors="coerce")
    history = series.loc[
        [day for day in series.index if day is not None and day < current_day]
    ].dropna()
    if history.empty:
        return None
    trailing = history.tail(max(2, int(lookback_days) + 1))
    returns = trailing.pct_change().dropna()
    if len(returns) < max(1, int(min_history_days)):
        return None
    realized_vol = float(returns.std(ddof=0))
    if not math.isfinite(realized_vol) or realized_vol <= 0:
        return None
    return realized_vol


def _normalize_variant(value: Any) -> str:
    text = str(value or "normal").strip().lower()
    return "stress" if text == "stress" else "normal"


def _series_value(
    panel: pd.DataFrame,
    row_date: date,
    symbol: str,
    *,
    fallback: Optional[float] = None,
) -> Optional[float]:
    if panel is None or panel.empty or symbol not in panel.columns or row_date not in panel.index:
        return fallback
    value = _safe_float(panel.at[row_date, symbol])
    return fallback if value is None else value


def _series_present(panel: pd.DataFrame, row_date: date, symbol: str) -> bool:
    if panel is None or panel.empty or symbol not in panel.columns or row_date not in panel.index:
        return False
    return _safe_float(panel.at[row_date, symbol]) is not None


def _has_observed_intraday_bar(
    *,
    open_panel: pd.DataFrame,
    high_panel: pd.DataFrame,
    low_panel: pd.DataFrame,
    row_date: date,
    symbol: str,
) -> bool:
    return (
        _series_present(open_panel, row_date, symbol)
        and _series_present(high_panel, row_date, symbol)
        and _series_present(low_panel, row_date, symbol)
    )


def _safe_ratio(
    numerator: Optional[float], denominator: Optional[float], *, default: float
) -> float:
    if numerator is None or denominator is None or denominator <= 0:
        return default
    return float(numerator) / float(denominator)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
