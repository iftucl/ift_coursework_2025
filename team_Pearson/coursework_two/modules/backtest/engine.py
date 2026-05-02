from __future__ import annotations

"""Main orchestration engine for CW2 holding-period backtests.

The formal strategy generates target weights and rebalances quarterly, while
the engine records monthly holding-period performance for risk, turnover, and
benchmark analytics.
"""

import logging
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy.engine import Engine

from ..ops.monitoring import ensure_ops_monitoring_schema
from ..ops.quality import record_quality_snapshot
from .data_loader import (
    align_signal_snapshot_counts,
    get_month_end_trading_days,
    load_adjusted_close_prices,
    load_benchmark_prices,
    load_daily_volumes,
    load_factor_panel,
    load_high_prices,
    load_low_prices,
    load_open_prices,
    load_regime_target_maps,
    load_risk_free_period_returns,
    load_signal_snapshot_counts,
    load_signals,
    load_term_spread_series,
    load_trading_calendar,
    load_vix_level,
    load_vix_series,
    shift_trading_day,
)
from .execution import (
    compute_drifted_weights,
    compute_open_gap_returns,
    compute_period_simple_returns,
    compute_turnover_ratio,
    estimate_dollar_adv,
    normalize_long_only_weights,
    simulate_trade_execution,
)
from .intraday import run_intraday_period
from .metrics import compute_backtest_metrics
from .performance import compute_gross_return, compute_net_return, update_benchmark_nav, update_nav
from .writer import (
    create_backtest_run,
    ensure_backtest_schema,
    mark_backtest_completed,
    mark_backtest_failed,
    write_cash_ledger,
    write_execution_ledger,
    write_holdings,
    write_intraday_daily_state,
    write_intraday_events,
    write_metrics,
    write_performance,
)

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Monthly backtest engine operating on precomputed CW2 portfolio signals."""

    def __init__(self, config: Dict[str, Any], db_engine: Engine):
        self.config = deepcopy(config or {})
        self.db = db_engine
        self.bt_cfg = self._normalize_backtest_config(self.config.get("backtest") or {})
        self.run_config_snapshot = deepcopy(self.config)
        self.run_config_snapshot["backtest"] = {
            **(self.run_config_snapshot.get("backtest") or {}),
            "start_date": self.bt_cfg["start_date"].isoformat(),
            "end_date": self.bt_cfg["end_date"].isoformat(),
            "lookback_years": int(self.bt_cfg["lookback_years"]),
        }
        if not self.bt_cfg["long_only"]:
            raise ValueError("CW2 backtest currently supports only long-only portfolios")

    def run(self, run_name: str) -> str:
        """Execute the full backtest and return ``run_id``."""
        ensure_backtest_schema(self.db)
        ensure_ops_monitoring_schema(self.db)
        run_id = create_backtest_run(
            self.db, run_name=run_name, config_snapshot=self.run_config_snapshot
        )
        try:
            rebalance_dates, trading_calendar = self._get_rebalance_dates()
            if len(rebalance_dates) < 2:
                raise ValueError(
                    "At least two rebalance dates are required to form one realized period"
                )
            self._validate_signal_history(rebalance_dates)

            max_ffill = int(self.bt_cfg["max_forward_fill_days"])
            execution_lag = int(self.bt_cfg["execution_lag"])
            benchmark_end_date = shift_trading_day(
                trading_calendar,
                rebalance_dates[-1],
                execution_lag,
            )
            benchmark_prices = load_benchmark_prices(
                self.db,
                self.bt_cfg["benchmark_ticker"],
                rebalance_dates[0],
                benchmark_end_date,
                lookback_days=max_ffill,
            )
            if benchmark_prices.empty:
                raise ValueError(
                    f"Benchmark prices not found for ticker={self.bt_cfg['benchmark_ticker']}"
                )
            self._validate_benchmark_history(
                benchmark_prices,
                trading_calendar=trading_calendar,
                start_date=rebalance_dates[0],
                end_date=benchmark_end_date,
            )

            nav = float(self.bt_cfg["initial_nav"])
            benchmark_nav = float(self.bt_cfg["initial_nav"])
            prev_weights: Dict[str, float] = {}
            prev_returns: Dict[str, float] = {}
            all_holdings: List[Dict[str, Any]] = []
            all_performance: List[Dict[str, Any]] = []
            all_intraday_events: List[Dict[str, Any]] = []
            all_intraday_daily_state: List[Dict[str, Any]] = []
            all_cash_ledger: List[Dict[str, Any]] = []
            all_execution_ledger: List[Dict[str, Any]] = []
            intraday_cfg = dict(self.bt_cfg["intraday_triggers"])
            execution_cfg = dict(self.bt_cfg["execution"])
            drawdown_brake_cfg = dict(self.bt_cfg["drawdown_brake"])
            drawdown_brake_active = False
            scheduled_rebalance_dates = set(self._scheduled_rebalance_dates(rebalance_dates))
            last_signal_regime: Optional[str] = None
            intraday_stop_lookback = (
                int(intraday_cfg.get("stop_loss_vol_lookback_days", 0))
                if str(intraday_cfg.get("stop_loss_mode", "fixed_pct")).strip().lower()
                == "vol_scaled"
                else 0
            )
            price_history_lookback = max(
                max_ffill,
                int(execution_cfg["adv_lookback_days"]),
                intraday_stop_lookback,
            )
            period_schedule = [
                {
                    "execution_date": shift_trading_day(
                        trading_calendar, rebalance_dates[period_idx], execution_lag
                    ),
                    "period_end_date": shift_trading_day(
                        trading_calendar,
                        rebalance_dates[period_idx + 1],
                        execution_lag,
                    ),
                }
                for period_idx in range(len(rebalance_dates) - 1)
            ]
            risk_free_returns = load_risk_free_period_returns(self.db, period_schedule)

            for idx in range(len(rebalance_dates) - 1):
                rebalance_date = rebalance_dates[idx]
                execution_date = shift_trading_day(trading_calendar, rebalance_date, execution_lag)
                next_execution_date = shift_trading_day(
                    trading_calendar,
                    rebalance_dates[idx + 1],
                    execution_lag,
                )

                drifted_weights = compute_drifted_weights(prev_weights, prev_returns)
                scheduled_rebalance = rebalance_date in scheduled_rebalance_dates
                if scheduled_rebalance:
                    signals = load_signals(
                        self.db,
                        rebalance_date,
                        self.bt_cfg["portfolio_name"],
                    )
                    target_weights, _, period_regime = self._resolve_period_target_weights(
                        signals,
                        drifted_weights,
                    )
                    if period_regime:
                        last_signal_regime = period_regime
                else:
                    signals = []
                    target_weights = normalize_long_only_weights(drifted_weights)
                    period_regime = last_signal_regime
                (
                    drawdown_brake_active,
                    drawdown_brake_drawdown,
                    drawdown_brake_fraction,
                ) = _evaluate_drawdown_brake(
                    nav_history=[float(self.bt_cfg["initial_nav"])]
                    + [float(row["portfolio_nav"]) for row in all_performance],
                    currently_active=drawdown_brake_active,
                    config=drawdown_brake_cfg,
                )
                if drawdown_brake_active and drawdown_brake_fraction > 0.0:
                    target_weights = _apply_drawdown_brake_to_targets(
                        target_weights,
                        de_risk_fraction=drawdown_brake_fraction,
                    )
                symbols = sorted(
                    {sym for sym in set(target_weights) | set(drifted_weights) if sym != "_CASH"}
                )
                close_panel = (
                    load_adjusted_close_prices(
                        self.db,
                        symbols,
                        execution_date,
                        next_execution_date,
                        lookback_days=price_history_lookback,
                    )
                    if symbols
                    else None
                )
                open_panel = (
                    load_open_prices(
                        self.db,
                        symbols,
                        execution_date,
                        next_execution_date,
                        lookback_days=price_history_lookback,
                    )
                    if symbols
                    else None
                )
                volume_panel = (
                    load_daily_volumes(
                        self.db,
                        symbols,
                        execution_date,
                        next_execution_date,
                        lookback_days=int(execution_cfg["adv_lookback_days"]),
                    )
                    if symbols
                    else None
                )
                adv_by_symbol = (
                    estimate_dollar_adv(
                        close_panel,
                        volume_panel,
                        as_of_date=execution_date,
                        lookback_days=int(execution_cfg["adv_lookback_days"]),
                        min_history_days=int(execution_cfg["min_adv_history_days"]),
                        max_forward_fill_days=max_ffill,
                    )
                    if symbols
                    else {}
                )
                open_gap_returns = (
                    compute_open_gap_returns(
                        open_panel,
                        close_panel,
                        execution_date=execution_date,
                        trading_calendar=trading_calendar,
                    )
                    if symbols
                    else {}
                )
                execution_result = simulate_trade_execution(
                    target_weights,
                    drifted_weights,
                    portfolio_value=max(
                        0.0,
                        float(execution_cfg["assumed_aum"]) * float(nav),
                    ),
                    transaction_cost_bps=float(self.bt_cfg["transaction_cost_bps"]),
                    cost_model=str(execution_cfg["cost_model"]),
                    adv_by_symbol=adv_by_symbol,
                    open_gap_returns=open_gap_returns,
                    enable_liquidity_clipping=bool(execution_cfg["enable_liquidity_clipping"]),
                    max_adv_participation=float(execution_cfg["max_adv_participation"]),
                    base_slippage_bps=float(execution_cfg["base_slippage_bps"]),
                    open_execution_penalty_bps=float(execution_cfg["open_execution_penalty_bps"]),
                    gap_slippage_multiplier=float(execution_cfg["gap_slippage_multiplier"]),
                    participation_slippage_bps=float(execution_cfg["participation_slippage_bps"]),
                    bid_ask_spread_model=str(execution_cfg["bid_ask_spread_model"]),
                    fixed_bid_ask_spread_bps=float(execution_cfg["fixed_bid_ask_spread_bps"]),
                    bid_ask_crossing_fraction=float(execution_cfg["bid_ask_crossing_fraction"]),
                    bid_ask_adv_low_threshold=float(execution_cfg["bid_ask_adv_low_threshold"]),
                    bid_ask_adv_medium_threshold=float(
                        execution_cfg["bid_ask_adv_medium_threshold"]
                    ),
                    bid_ask_spread_bps_low_adv=float(execution_cfg["bid_ask_spread_bps_low_adv"]),
                    bid_ask_spread_bps_medium_adv=float(
                        execution_cfg["bid_ask_spread_bps_medium_adv"]
                    ),
                    bid_ask_spread_bps_high_adv=float(execution_cfg["bid_ask_spread_bps_high_adv"]),
                )

                if symbols:
                    period_returns, period_return_metadata = compute_period_simple_returns(
                        close_panel,
                        trading_calendar,
                        execution_date,
                        next_execution_date,
                        max_forward_fill_days=max_ffill,
                    )
                else:
                    period_returns = {}
                    period_return_metadata = {}

                intraday_result = None
                if symbols and intraday_cfg.get("enabled", False):
                    if scheduled_rebalance:
                        normal_targets, stress_targets = load_regime_target_maps(
                            self.db,
                            rebalance_date,
                            self.bt_cfg["portfolio_name"],
                            config=self.config,
                        )
                        if not normal_targets:
                            normal_targets = dict(execution_result.requested_weights)
                        if not stress_targets:
                            stress_targets = dict(execution_result.requested_weights)
                    else:
                        normal_targets = dict(execution_result.requested_weights)
                        stress_targets = dict(execution_result.requested_weights)

                    intraday_symbols = sorted(
                        set(symbols) | set(normal_targets) | set(stress_targets)
                    )
                    price_panel = close_panel
                    if set(intraday_symbols) != set(symbols):
                        price_panel = load_adjusted_close_prices(
                            self.db,
                            intraday_symbols,
                            execution_date,
                            next_execution_date,
                            lookback_days=price_history_lookback,
                        )
                        open_panel = load_open_prices(
                            self.db,
                            intraday_symbols,
                            execution_date,
                            next_execution_date,
                            lookback_days=price_history_lookback,
                        )
                    high_panel = load_high_prices(
                        self.db,
                        intraday_symbols,
                        execution_date,
                        next_execution_date,
                        lookback_days=price_history_lookback,
                    )
                    low_panel = load_low_prices(
                        self.db,
                        intraday_symbols,
                        execution_date,
                        next_execution_date,
                        lookback_days=price_history_lookback,
                    )
                    execution_idx = trading_calendar.index(execution_date)
                    vix_start = trading_calendar[max(0, execution_idx - 1)]
                    vix_series = load_vix_series(
                        self.db,
                        vix_start,
                        next_execution_date,
                    )
                    term_spread_series = load_term_spread_series(
                        self.db,
                        vix_start,
                        next_execution_date,
                    )
                    event_signal_panels: Dict[str, Any] = {}
                    if intraday_cfg.get("event_driven_enabled", False):
                        event_factor_names: List[str] = []
                        if intraday_cfg.get("news_sentiment_shock_enabled", False):
                            event_factor_names.extend(
                                [
                                    "sentiment_surprise",
                                    "sentiment_7d_avg",
                                    "article_count_30d",
                                ]
                            )
                        if intraday_cfg.get("earnings_event_enabled", False):
                            event_factor_names.extend(
                                [
                                    "earnings_publication_flag",
                                    "earnings_negative_news_count_daily",
                                    "earnings_news_count_daily",
                                ]
                            )
                        if intraday_cfg.get("rating_downgrade_event_enabled", False):
                            event_factor_names.extend(
                                [
                                    "rating_downgrade_count_daily",
                                    "rating_upgrade_count_daily",
                                ]
                            )
                        for factor_name in sorted(set(event_factor_names)):
                            event_signal_panels[factor_name] = load_factor_panel(
                                self.db,
                                intraday_symbols,
                                execution_date,
                                next_execution_date,
                                factor_name=factor_name,
                                lookback_days=0,
                            )
                    intraday_result = run_intraday_period(
                        execution_date=execution_date,
                        next_execution_date=next_execution_date,
                        normal_target_weights=normal_targets,
                        stress_target_weights=stress_targets,
                        trading_calendar=trading_calendar,
                        price_panel=price_panel,
                        open_panel=open_panel,
                        high_panel=high_panel,
                        low_panel=low_panel,
                        vix_series=vix_series,
                        term_spread_series=term_spread_series,
                        event_signal_panels=event_signal_panels,
                        initial_target_variant=period_regime or "normal",
                        config={"backtest": self.bt_cfg},
                        starting_weights=execution_result.executed_weights,
                        monitor_engine=self.db,
                        monitor_run_id=run_id,
                    )
                period_price_quality = self._summarize_period_price_quality(period_return_metadata)

                if intraday_result is not None:
                    gross_return = float(intraday_result.period_gross_return)
                    transaction_cost = float(execution_result.total_cost) + float(
                        intraday_result.total_intraday_cost
                    )
                    cash_end_weight = float(intraday_result.final_weights.get("_CASH", 0.0))
                else:
                    gross_return = compute_gross_return(
                        execution_result.executed_weights, period_returns
                    )
                    transaction_cost = float(execution_result.total_cost)
                    cash_end_weight = float(execution_result.executed_weights.get("_CASH", 0.0))
                benchmark_return = self._compute_benchmark_return(
                    benchmark_prices,
                    trading_calendar,
                    execution_date,
                    next_execution_date,
                    max_forward_fill_days=max_ffill,
                )
                risk_free_return = float(risk_free_returns.get(next_execution_date, 0.0))
                net_return = compute_net_return(gross_return, transaction_cost)
                nav = update_nav(nav, gross_return, transaction_cost)
                benchmark_nav = update_benchmark_nav(benchmark_nav, benchmark_return)
                vix_level = load_vix_level(self.db, rebalance_date)

                period_holdings = self._build_holdings_records(
                    rebalance_date=rebalance_date,
                    execution_date=execution_date,
                    target_weights=target_weights,
                    executed_weights=execution_result.executed_weights,
                    drifted_weights=drifted_weights,
                    requested_turnover_contrib=execution_result.requested_turnover_contrib,
                    turnover_contrib=execution_result.executed_turnover_contrib,
                    signals=signals,
                    regime=period_regime,
                )
                period_execution_ledger = self._build_execution_ledger_records(
                    rebalance_date=rebalance_date,
                    execution_date=execution_date,
                    execution_result=execution_result,
                    period_return_metadata=period_return_metadata,
                )
                requested_turnover_ratio, _ = compute_turnover_ratio(
                    execution_result.requested_weights,
                    drifted_weights,
                    include_cash=True,
                )
                executed_turnover_ratio, _ = compute_turnover_ratio(
                    execution_result.executed_weights,
                    drifted_weights,
                    include_cash=True,
                )
                performance_record = {
                    "execution_date": execution_date,
                    "period_end_date": next_execution_date,
                    "gross_return": gross_return,
                    "net_return": net_return,
                    "benchmark_return": benchmark_return,
                    "risk_free_return": risk_free_return,
                    "excess_return": net_return - benchmark_return,
                    "portfolio_nav": nav,
                    "benchmark_nav": benchmark_nav,
                    "turnover": float(executed_turnover_ratio),
                    "requested_turnover": float(requested_turnover_ratio),
                    "gross_turnover": float(execution_result.executed_turnover),
                    "gross_requested_turnover": float(execution_result.requested_turnover),
                    "transaction_cost": transaction_cost,
                    "fixed_transaction_cost": float(execution_result.fixed_cost),
                    "bid_ask_cost": float(execution_result.bid_ask_cost),
                    "slippage_cost": float(execution_result.slippage_cost),
                    "num_holdings": len(
                        [
                            sym
                            for sym, weight in execution_result.executed_weights.items()
                            if sym != "_CASH" and float(weight) > 1e-12
                        ]
                    ),
                    "regime": (
                        intraday_result.final_target_variant
                        if intraday_result is not None
                        else period_regime
                    ),
                    "vix_level": vix_level,
                    "cash_start_weight": float(execution_result.cash_start_weight),
                    "cash_after_execution_weight": float(
                        execution_result.cash_after_execution_weight
                    ),
                    "cash_end_weight": cash_end_weight,
                    "unfilled_buy_weight": float(execution_result.unfilled_buy_weight),
                    "unfilled_sell_weight": float(execution_result.unfilled_sell_weight),
                    "liquidity_clipped": bool(execution_result.liquidity_clipped),
                    "max_participation_used": execution_result.max_participation_used,
                    **period_price_quality,
                    "drawdown_brake_active": bool(drawdown_brake_active),
                    "drawdown_brake_drawdown": float(drawdown_brake_drawdown),
                    "drawdown_brake_fraction": float(drawdown_brake_fraction),
                    "intraday_stop_loss_count": int(
                        intraday_result.intraday_stop_loss_count
                        if intraday_result is not None
                        else 0
                    ),
                    "intraday_regime_switch_count": int(
                        intraday_result.intraday_regime_switch_count
                        if intraday_result is not None
                        else 0
                    ),
                    "intraday_cost": float(
                        intraday_result.total_intraday_cost if intraday_result is not None else 0.0
                    ),
                }

                all_holdings.extend(period_holdings)
                all_execution_ledger.extend(period_execution_ledger)
                all_performance.append(performance_record)
                all_cash_ledger.append(
                    {
                        "rebalance_date": rebalance_date,
                        "execution_date": execution_date,
                        "period_end_date": next_execution_date,
                        "cash_start_weight": float(execution_result.cash_start_weight),
                        "cash_after_execution_weight": float(
                            execution_result.cash_after_execution_weight
                        ),
                        "cash_end_weight": cash_end_weight,
                        "requested_turnover": float(requested_turnover_ratio),
                        "executed_turnover": float(executed_turnover_ratio),
                        "gross_requested_turnover": float(execution_result.requested_turnover),
                        "gross_executed_turnover": float(execution_result.executed_turnover),
                        "fixed_transaction_cost": float(execution_result.fixed_cost),
                        "bid_ask_cost": float(execution_result.bid_ask_cost),
                        "slippage_cost": float(execution_result.slippage_cost),
                        "total_cost": transaction_cost,
                        "unfilled_buy_weight": float(execution_result.unfilled_buy_weight),
                        "unfilled_sell_weight": float(execution_result.unfilled_sell_weight),
                        "liquidity_clipped": bool(execution_result.liquidity_clipped),
                        "max_participation_used": execution_result.max_participation_used,
                        "drawdown_brake_active": bool(drawdown_brake_active),
                        "drawdown_brake_drawdown": float(drawdown_brake_drawdown),
                        "drawdown_brake_fraction": float(drawdown_brake_fraction),
                    }
                )

                if intraday_result is not None:
                    # ``final_weights`` already represent the fully drifted end-of-period
                    # state after daily overlay actions, so the next loop must carry these
                    # weights forward without applying an additional return vector.
                    prev_weights = dict(intraday_result.final_weights)
                    prev_returns = {}
                    all_intraday_events.extend(intraday_result.events)
                    if intraday_cfg.get("save_daily_state", False):
                        all_intraday_daily_state.extend(intraday_result.daily_state)
                else:
                    prev_weights = dict(execution_result.executed_weights)
                    prev_returns = {
                        symbol: float(period_returns.get(symbol, 0.0))
                        for symbol in execution_result.executed_weights
                    }

            metrics = compute_backtest_metrics(
                all_performance,
                initial_nav=float(self.bt_cfg["initial_nav"]),
            )
            write_holdings(self.db, run_id, all_holdings)
            write_performance(self.db, run_id, all_performance)
            write_cash_ledger(self.db, run_id, all_cash_ledger)
            write_execution_ledger(self.db, run_id, all_execution_ledger)
            write_intraday_events(
                self.db,
                run_id,
                all_intraday_events,
                config_snapshot=self.run_config_snapshot,
            )
            if intraday_cfg.get("save_daily_state", False):
                write_intraday_daily_state(self.db, run_id, all_intraday_daily_state)
            write_metrics(self.db, run_id, metrics)
            run_date = (
                all_performance[-1]["period_end_date"]
                if all_performance
                else self.bt_cfg["end_date"]
            )
            record_quality_snapshot(
                engine=self.db,
                dataset_name="backtest_runs",
                run_id=run_id,
                run_date=run_date,
                quality_report=_build_backtest_quality_report(
                    run_name=run_name,
                    performance_records=all_performance,
                    holding_records=all_holdings,
                    cash_ledger_records=all_cash_ledger,
                    execution_ledger_records=all_execution_ledger,
                    intraday_events=all_intraday_events,
                    intraday_daily_state=all_intraday_daily_state,
                    metrics=metrics,
                ),
            )
            mark_backtest_completed(self.db, run_id, config_snapshot=self.run_config_snapshot)
            return run_id
        except Exception as exc:
            record_quality_snapshot(
                engine=self.db,
                dataset_name="backtest_runs",
                run_id=run_id,
                run_date=self.bt_cfg["end_date"],
                quality_report={
                    "run_name": run_name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "passed": False,
                },
            )
            mark_backtest_failed(self.db, run_id, config_snapshot=self.run_config_snapshot)
            raise

    def _get_rebalance_dates(self) -> tuple[List[date], List[date]]:
        calendar_start = self.bt_cfg["start_date"]
        calendar_end = self.bt_cfg["end_date"] + timedelta(
            days=max(10, int(self.bt_cfg["execution_lag"]) * 3)
        )
        trading_calendar = load_trading_calendar(
            self.db,
            calendar_start,
            calendar_end,
            benchmark_ticker=self.bt_cfg["benchmark_ticker"],
        )
        if not trading_calendar:
            raise ValueError("Trading calendar could not be loaded from current CW1 datasets")

        frequency = str(self.bt_cfg["rebalance_frequency"]).strip().lower()
        if frequency not in {"monthly", "quarterly", "semiannual", "annual"}:
            raise NotImplementedError(f"Unsupported rebalance frequency: {frequency}")
        rebalance_dates = get_month_end_trading_days(trading_calendar)
        execution_lag = int(self.bt_cfg["execution_lag"])

        # Drop trailing anchor dates that cannot be executed at T+lag because the
        # available trading calendar or price history stops before that point.
        while rebalance_dates:
            try:
                shift_trading_day(trading_calendar, rebalance_dates[-1], execution_lag)
                break
            except ValueError:
                dropped = rebalance_dates.pop()
                logger.warning(
                    "backtest_engine: dropping terminal rebalance date without executable T+lag anchor "
                    "rebalance_date=%s execution_lag=%s",
                    dropped,
                    execution_lag,
                )

        if len(rebalance_dates) < 2:
            raise ValueError(
                "Insufficient executable rebalance dates after trimming terminal incomplete periods. "
                "Load more recent benchmark/price history or generate earlier portfolio snapshots."
            )
        return rebalance_dates, trading_calendar

    def _scheduled_rebalance_dates(self, rebalance_dates: List[date]) -> List[date]:
        frequency = str(self.bt_cfg["rebalance_frequency"]).strip().lower()
        if frequency == "monthly":
            return list(rebalance_dates)
        if frequency == "quarterly":
            scheduled: List[date] = []
            for idx, rebalance_date in enumerate(rebalance_dates):
                if idx == 0 or rebalance_date.month in {3, 6, 9, 12}:
                    scheduled.append(rebalance_date)
            return scheduled
        if frequency == "semiannual":
            scheduled = []
            for idx, rebalance_date in enumerate(rebalance_dates):
                if idx == 0 or rebalance_date.month in {6, 12}:
                    scheduled.append(rebalance_date)
            return scheduled
        if frequency == "annual":
            scheduled = []
            for idx, rebalance_date in enumerate(rebalance_dates):
                if idx == 0 or rebalance_date.month == 12:
                    scheduled.append(rebalance_date)
            return scheduled
        raise NotImplementedError(f"Unsupported rebalance frequency: {frequency}")

    def _resolve_period_target_weights(
        self,
        signals: List[Dict[str, Any]],
        drifted_weights: Mapping[str, float],
    ) -> tuple[Dict[str, float], str, Optional[str]]:
        min_eligible = int(self.bt_cfg["min_eligible_universe"])

        if signals and len(signals) >= min_eligible:
            raw_weights = {
                str(row["symbol"]): float(row["target_weight"])
                for row in signals
                if row.get("target_weight") is not None
            }
            target_weights = normalize_long_only_weights(
                raw_weights,
                long_only=bool(self.bt_cfg["long_only"]),
            )
            if not target_weights:
                logger.warning(
                    "backtest_engine: signal snapshot is present but target weights are empty after normalization"
                )
                carried = normalize_long_only_weights(drifted_weights)
                return carried, "carry", None
            regime = _first_non_null([row.get("regime") for row in signals])
            return target_weights, "signal", regime

        if signals:
            logger.warning(
                "backtest_engine: rebalance skipped due to insufficient eligible signals count=%d min=%d",
                len(signals),
                min_eligible,
            )
        else:
            logger.warning("backtest_engine: rebalance skipped due to missing signal snapshot")

        carried = normalize_long_only_weights(drifted_weights)
        return carried, "carry", None

    def _validate_signal_history(self, rebalance_dates: List[date]) -> None:
        """Require enough frequency-aligned signal snapshots before launching a backtest."""
        if not rebalance_dates:
            raise ValueError("No rebalance dates available for backtest validation")

        scheduled_rebalance_dates = self._scheduled_rebalance_dates(rebalance_dates)
        signal_counts = load_signal_snapshot_counts(
            self.db,
            portfolio_name=self.bt_cfg["portfolio_name"],
            start_date=scheduled_rebalance_dates[0],
            end_date=scheduled_rebalance_dates[-1],
        )
        if not signal_counts:
            raise ValueError(
                "No portfolio_target_positions snapshots found inside the requested backtest window. "
                "Generate historical CW2 portfolio snapshots first."
            )

        min_eligible = int(self.bt_cfg["min_eligible_universe"])
        aligned_counts = align_signal_snapshot_counts(signal_counts, scheduled_rebalance_dates)
        aligned_dates = [
            rebalance_date
            for rebalance_date in scheduled_rebalance_dates
            if int(aligned_counts.get(rebalance_date, {}).get("count", 0)) >= min_eligible
        ]
        if len(aligned_dates) >= 2:
            return

        sample_dates = ", ".join(
            f"{as_of_date.isoformat()}({signal_counts[as_of_date]})"
            for as_of_date in sorted(signal_counts)[-5:]
        )
        raise ValueError(
            "Insufficient rebalance-aligned signal history for backtest. "
            f"Need at least 2 rebalance-aligned snapshots with >= {min_eligible} names for "
            f"portfolio_name={self.bt_cfg['portfolio_name']} at frequency={self.bt_cfg['rebalance_frequency']}, "
            f"but found {len(aligned_dates)}. "
            f"Available snapshot dates/counts: {sample_dates or 'none'}."
        )

    def _validate_benchmark_history(
        self,
        benchmark_prices: Any,
        *,
        trading_calendar: List[date],
        start_date: date,
        end_date: date,
    ) -> None:
        required_days = [
            trading_day for trading_day in trading_calendar if start_date <= trading_day <= end_date
        ]
        if not required_days:
            raise ValueError("Benchmark validation window is empty after calendar alignment")

        observed_days: set[date] = set()
        for raw_value in getattr(benchmark_prices, "index", []):
            if raw_value is None:
                continue
            if isinstance(raw_value, datetime):
                observed_days.add(raw_value.date())
                continue
            if isinstance(raw_value, date):
                observed_days.add(raw_value)
                continue
            to_date = getattr(raw_value, "date", None)
            if callable(to_date):
                try:
                    observed = to_date()
                except Exception:  # pragma: no cover - defensive conversion guard
                    observed = None
                if isinstance(observed, date):
                    observed_days.add(observed)

        missing_days = [
            trading_day for trading_day in required_days if trading_day not in observed_days
        ]
        max_missing = int(self.bt_cfg["benchmark_max_missing_trading_days"])
        if len(missing_days) <= max_missing:
            return

        sample = ", ".join(trading_day.isoformat() for trading_day in missing_days[:5])
        raise ValueError(
            "Benchmark price history is incomplete for the requested trading calendar. "
            f"ticker={self.bt_cfg['benchmark_ticker']} missing_days={len(missing_days)} "
            f"allowed_missing_days={max_missing} sample_missing_dates={sample or 'none'}"
        )

    def _compute_benchmark_return(
        self,
        benchmark_prices: Any,
        trading_calendar: List[date],
        execution_date: date,
        next_execution_date: date,
        *,
        max_forward_fill_days: int,
    ) -> float:
        benchmark_panel = benchmark_prices.to_frame(name=self.bt_cfg["benchmark_ticker"])
        returns, _ = compute_period_simple_returns(
            benchmark_panel,
            trading_calendar,
            execution_date,
            next_execution_date,
            max_forward_fill_days=max_forward_fill_days,
        )
        return float(returns.get(self.bt_cfg["benchmark_ticker"], 0.0))

    def _build_holdings_records(
        self,
        *,
        rebalance_date: date,
        execution_date: date,
        target_weights: Mapping[str, float],
        executed_weights: Mapping[str, float],
        drifted_weights: Mapping[str, float],
        requested_turnover_contrib: Mapping[str, float],
        turnover_contrib: Mapping[str, float],
        signals: List[Dict[str, Any]],
        regime: Optional[str],
    ) -> List[Dict[str, Any]]:
        signal_lookup = {str(row["symbol"]): row for row in signals}
        ordered_symbols = sorted(
            {
                symbol
                for symbol in set(target_weights) | set(executed_weights) | set(drifted_weights)
                if symbol != "_CASH"
            },
            key=lambda sym: (
                -float(executed_weights.get(sym, target_weights.get(sym, 0.0))),
                sym,
            ),
        )
        records: List[Dict[str, Any]] = []
        for symbol in ordered_symbols:
            signal = signal_lookup.get(symbol, {})
            records.append(
                {
                    "rebalance_date": rebalance_date,
                    "execution_date": execution_date,
                    "symbol": symbol,
                    "target_weight": float(target_weights.get(symbol, 0.0)),
                    "executed_weight": float(executed_weights.get(symbol, 0.0)),
                    "drifted_weight": float(drifted_weights.get(symbol, 0.0)),
                    "requested_turnover_contrib": float(
                        requested_turnover_contrib.get(symbol, 0.0)
                    ),
                    "turnover_contrib": float(turnover_contrib.get(symbol, 0.0)),
                    "execution_clipped": abs(
                        float(executed_weights.get(symbol, 0.0))
                        - float(target_weights.get(symbol, 0.0))
                    )
                    > 1e-10,
                    "composite_alpha": signal.get("composite_alpha"),
                    "gics_sector": signal.get("gics_sector"),
                    "regime": regime or signal.get("regime"),
                }
            )
        return records

    @staticmethod
    def _build_execution_ledger_records(
        *,
        rebalance_date: date,
        execution_date: date,
        execution_result: Any,
        period_return_metadata: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        metadata = period_return_metadata or {}
        return [
            {
                "rebalance_date": rebalance_date,
                "execution_date": execution_date,
                **record,
                "had_forward_fill": bool(
                    metadata.get(str(record.get("symbol") or ""), {}).get(
                        "used_forward_fill", False
                    )
                ),
                "forward_fill_days": int(
                    metadata.get(str(record.get("symbol") or ""), {}).get("forward_fill_days", 0)
                    or 0
                ),
            }
            for record in execution_result.trade_records
        ]

    @staticmethod
    def _summarize_period_price_quality(
        period_return_metadata: Mapping[str, Mapping[str, Any]],
    ) -> Dict[str, int]:
        symbol_count = 0
        day_count = 0
        for meta in period_return_metadata.values():
            forward_fill_days = max(0, int(meta.get("forward_fill_days", 0) or 0))
            if forward_fill_days > 0 or bool(meta.get("used_forward_fill", False)):
                symbol_count += 1
            day_count += forward_fill_days
        return {
            "forward_filled_symbol_count": symbol_count,
            "forward_fill_day_count": day_count,
        }

    @staticmethod
    def _normalize_backtest_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
        lookback_years = int(cfg.get("lookback_years", 5))
        end_date = _resolve_end_date(cfg.get("end_date"))
        start_date = _resolve_start_date(
            cfg.get("start_date"),
            end_date=end_date,
            lookback_years=lookback_years,
        )
        out = {
            "start_date": start_date,
            "end_date": end_date,
            "lookback_years": lookback_years,
            "rebalance_frequency": str(cfg.get("rebalance_frequency", "monthly")),
            "execution_lag": int(cfg.get("execution_lag", 1)),
            "transaction_cost_bps": float(cfg.get("transaction_cost_bps", 15)),
            "long_only": bool(cfg.get("long_only", True)),
            "weighting": str(cfg.get("weighting", "equal")),
            "top_n": int(cfg.get("top_n", 25)),
            "benchmark_ticker": str(cfg.get("benchmark_ticker", "SPY")),
            "portfolio_name": str(cfg.get("portfolio_name", "cw2_core_equity")),
            "initial_nav": float(cfg.get("initial_nav", 1.0)),
            "min_eligible_universe": int(cfg.get("min_eligible_universe", 15)),
            "max_forward_fill_days": int(cfg.get("max_forward_fill_days", 5)),
            "benchmark_max_missing_trading_days": int(
                cfg.get("benchmark_max_missing_trading_days", 0)
            ),
            "execution": BacktestEngine._normalize_execution_config(
                cfg.get("execution") or {},
                default_bps=float(cfg.get("transaction_cost_bps", 15)),
                default_ffill=int(cfg.get("max_forward_fill_days", 5)),
            ),
            "drawdown_brake": BacktestEngine._normalize_drawdown_brake_config(
                cfg.get("drawdown_brake") or {}
            ),
            "intraday_triggers": BacktestEngine._normalize_intraday_triggers(
                cfg.get("intraday_triggers") or {},
                default_bps=float(cfg.get("transaction_cost_bps", 15)),
                default_ffill=int(cfg.get("max_forward_fill_days", 5)),
            ),
        }
        if out["start_date"] >= out["end_date"]:
            raise ValueError("backtest.start_date must be earlier than backtest.end_date")
        if out["execution_lag"] < 1:
            raise ValueError("backtest.execution_lag must be >= 1 trading day")
        return out

    @staticmethod
    def _normalize_execution_config(
        cfg: Dict[str, Any],
        *,
        default_bps: float,
        default_ffill: int,
    ) -> Dict[str, Any]:
        return {
            "cost_model": str(cfg.get("cost_model", "flat_total_bps")),
            "assumed_aum": float(cfg.get("assumed_aum", 10_000_000.0)),
            "enable_liquidity_clipping": bool(cfg.get("enable_liquidity_clipping", True)),
            "adv_lookback_days": int(cfg.get("adv_lookback_days", 20)),
            "min_adv_history_days": int(cfg.get("min_adv_history_days", 5)),
            "max_adv_participation": float(cfg.get("max_adv_participation", 0.05)),
            "base_slippage_bps": float(cfg.get("base_slippage_bps", 0.0)),
            "open_execution_penalty_bps": float(cfg.get("open_execution_penalty_bps", 0.0)),
            "gap_slippage_multiplier": float(cfg.get("gap_slippage_multiplier", 0.0)),
            "participation_slippage_bps": float(cfg.get("participation_slippage_bps", 0.0)),
            "bid_ask_spread_model": str(cfg.get("bid_ask_spread_model", "none")),
            "fixed_bid_ask_spread_bps": float(cfg.get("fixed_bid_ask_spread_bps", 0.0)),
            "bid_ask_crossing_fraction": float(cfg.get("bid_ask_crossing_fraction", 0.0)),
            "bid_ask_adv_low_threshold": float(cfg.get("bid_ask_adv_low_threshold", 1_000_000.0)),
            "bid_ask_adv_medium_threshold": float(
                cfg.get("bid_ask_adv_medium_threshold", 10_000_000.0)
            ),
            "bid_ask_spread_bps_low_adv": float(cfg.get("bid_ask_spread_bps_low_adv", 12.0)),
            "bid_ask_spread_bps_medium_adv": float(cfg.get("bid_ask_spread_bps_medium_adv", 6.0)),
            "bid_ask_spread_bps_high_adv": float(cfg.get("bid_ask_spread_bps_high_adv", 2.0)),
            "fallback_transaction_cost_bps": float(
                cfg.get("fallback_transaction_cost_bps", default_bps)
            ),
            "max_forward_fill_days": int(cfg.get("max_forward_fill_days", default_ffill)),
        }

    @staticmethod
    def _normalize_drawdown_brake_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "lookback_periods": int(cfg.get("lookback_periods", 12)),
            "threshold_pct": float(cfg.get("threshold_pct", 0.15)),
            "recovery_drawdown_pct": float(cfg.get("recovery_drawdown_pct", 0.08)),
            "de_risk_fraction": float(cfg.get("de_risk_fraction", 0.35)),
        }

    @staticmethod
    def _normalize_intraday_triggers(
        cfg: Dict[str, Any],
        *,
        default_bps: float,
        default_ffill: int,
    ) -> Dict[str, Any]:
        vix_recovery_threshold = float(cfg.get("vix_recovery_threshold", 25.0))
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "stock_stop_loss_pct": float(cfg.get("stock_stop_loss_pct", -0.09)),
            "stop_loss_mode": str(cfg.get("stop_loss_mode", "fixed_pct")).strip().lower(),
            "stop_loss_vol_lookback_days": int(cfg.get("stop_loss_vol_lookback_days", 20)),
            "stop_loss_min_history_days": int(cfg.get("stop_loss_min_history_days", 10)),
            "stop_loss_vol_multiplier": float(cfg.get("stop_loss_vol_multiplier", 2.5)),
            "stop_loss_min_abs_pct": float(cfg.get("stop_loss_min_abs_pct", 0.05)),
            "stop_loss_max_abs_pct": float(cfg.get("stop_loss_max_abs_pct", 0.15)),
            "vix_spike_pct": float(cfg.get("vix_spike_pct", 0.25)),
            "vix_spike_min_level": float(cfg.get("vix_spike_min_level", vix_recovery_threshold)),
            "term_spread_confirm_enabled": bool(cfg.get("term_spread_confirm_enabled", False)),
            "term_spread_stress_threshold": float(cfg.get("term_spread_stress_threshold", 0.0)),
            "vix_hard_stress_level": float(cfg.get("vix_hard_stress_level", 35.0)),
            "vix_recovery_threshold": float(cfg.get("vix_recovery_threshold", 25.0)),
            "vix_recovery_consecutive_days": int(cfg.get("vix_recovery_consecutive_days", 4)),
            "regime_switch_mode": str(cfg.get("regime_switch_mode", "next_day_rebalance")),
            "allow_reentry_after_stop_loss": bool(cfg.get("allow_reentry_after_stop_loss", False)),
            "mid_frequency_rebalance_enabled": bool(
                cfg.get("mid_frequency_rebalance_enabled", False)
            ),
            "mid_frequency_rebalance_weekday": int(cfg.get("mid_frequency_rebalance_weekday", 0)),
            "mid_frequency_min_turnover": float(cfg.get("mid_frequency_min_turnover", 0.05)),
            "event_driven_enabled": bool(cfg.get("event_driven_enabled", False)),
            "news_sentiment_shock_enabled": bool(cfg.get("news_sentiment_shock_enabled", False)),
            "news_sentiment_surprise_threshold": float(
                cfg.get("news_sentiment_surprise_threshold", -0.20)
            ),
            "news_sentiment_min_article_count": float(
                cfg.get("news_sentiment_min_article_count", 8.0)
            ),
            "news_sentiment_trim_fraction": float(cfg.get("news_sentiment_trim_fraction", 0.25)),
            "earnings_event_enabled": bool(cfg.get("earnings_event_enabled", False)),
            "earnings_require_publication_flag": bool(
                cfg.get("earnings_require_publication_flag", True)
            ),
            "earnings_negative_news_min_count": float(
                cfg.get("earnings_negative_news_min_count", 2.0)
            ),
            "earnings_trim_fraction": float(cfg.get("earnings_trim_fraction", 0.40)),
            "rating_downgrade_event_enabled": bool(
                cfg.get("rating_downgrade_event_enabled", False)
            ),
            "rating_downgrade_min_count": float(cfg.get("rating_downgrade_min_count", 2.0)),
            "rating_trim_fraction": float(cfg.get("rating_trim_fraction", 0.20)),
            "event_cooldown_days": int(cfg.get("event_cooldown_days", 5)),
            "transaction_cost_bps": float(cfg.get("transaction_cost_bps", default_bps)),
            "save_daily_state": bool(cfg.get("save_daily_state", False)),
            "max_forward_fill_days": int(cfg.get("max_forward_fill_days", default_ffill)),
        }


def load_backtest_config(config_path: str | None = None) -> Dict[str, Any]:
    """Load the CW2 YAML config for a backtest run."""
    from team_Pearson.coursework_two.modules.utils.config_validation import load_cw2_config

    return load_cw2_config(config_path)


def run_backtest_from_config(
    *,
    run_name: str,
    config_path: str | None = None,
    db_engine: Engine | None = None,
    config_override: Optional[Dict[str, Any]] = None,
) -> str:
    """Convenience wrapper for launching the backtest from CW2 config."""
    config = load_backtest_config(config_path)
    if config_override:
        config = _deep_merge_dicts(config, config_override)
    engine = db_engine or _load_shared_db_engine()
    return BacktestEngine(config, engine).run(run_name)


def _deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _load_shared_db_engine() -> Engine:
    repo_root = Path(__file__).resolve().parents[4]
    cw1_root = repo_root / "team_Pearson" / "coursework_one"
    if str(cw1_root) not in sys.path:
        sys.path.insert(0, str(cw1_root))
    from modules.db import get_db_engine

    return get_db_engine()


def _coerce_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _resolve_end_date(value: Any) -> date:
    if value is None:
        return _today_utc()
    text = str(value).strip().lower()
    if text in {"", "auto", "today", "latest", "none", "null"}:
        return _today_utc()
    return _coerce_date(value)


def _resolve_start_date(value: Any, *, end_date: date, lookback_years: int) -> date:
    if value is None:
        return _subtract_years(end_date, lookback_years)
    text = str(value).strip().lower()
    if text in {"", "auto", "rolling", "dynamic", "none", "null"}:
        return _subtract_years(end_date, lookback_years)
    return _coerce_date(value)


def _subtract_years(anchor: date, years: int) -> date:
    try:
        return anchor.replace(year=anchor.year - int(years))
    except ValueError:
        # Handle leap-day anchors by snapping to Feb 28 in the target year.
        return anchor.replace(month=2, day=28, year=anchor.year - int(years))


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _first_non_null(values: List[Any]) -> Optional[str]:
    for value in values:
        if value is not None:
            return str(value)
    return None


def _evaluate_drawdown_brake(
    *,
    nav_history: List[float],
    currently_active: bool,
    config: Mapping[str, Any],
) -> tuple[bool, float, float]:
    if not bool(config.get("enabled", False)):
        return False, 0.0, 0.0
    history = [float(value) for value in nav_history if value is not None and float(value) > 0.0]
    if not history:
        return False, 0.0, 0.0
    lookback = max(1, int(config.get("lookback_periods", 12)))
    window = history[-lookback:]
    current_nav = float(window[-1])
    trailing_peak = max(window)
    if trailing_peak <= 0.0:
        return False, 0.0, 0.0
    drawdown = max(0.0, 1.0 - current_nav / trailing_peak)
    threshold = max(0.0, float(config.get("threshold_pct", 0.15)))
    recovery = max(0.0, float(config.get("recovery_drawdown_pct", 0.08)))
    if currently_active:
        active = drawdown >= recovery
    else:
        active = drawdown >= threshold
    fraction = float(config.get("de_risk_fraction", 0.0)) if active else 0.0
    return active, drawdown, max(0.0, min(1.0, fraction))


def _apply_drawdown_brake_to_targets(
    target_weights: Mapping[str, float],
    *,
    de_risk_fraction: float,
) -> Dict[str, float]:
    fraction = max(0.0, min(1.0, float(de_risk_fraction)))
    if fraction <= 0.0:
        return {str(symbol): float(weight) for symbol, weight in target_weights.items()}
    scaled = {
        str(symbol): float(weight) * (1.0 - fraction)
        for symbol, weight in target_weights.items()
        if str(symbol) != "_CASH" and float(weight) > 0.0
    }
    scaled["_CASH"] = scaled.get("_CASH", 0.0) + fraction
    return scaled


def _build_backtest_quality_report(
    *,
    run_name: str,
    performance_records: List[Dict[str, Any]],
    holding_records: List[Dict[str, Any]],
    cash_ledger_records: List[Dict[str, Any]],
    execution_ledger_records: List[Dict[str, Any]],
    intraday_events: List[Dict[str, Any]],
    intraday_daily_state: List[Dict[str, Any]],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    period_count = len(performance_records)
    metric_count = len(metrics)
    failures: List[str] = []
    warnings: List[str] = []
    if period_count <= 0:
        failures.append("performance_rows_missing")
    if metric_count <= 0:
        failures.append("metrics_missing")
    if len(cash_ledger_records) != period_count:
        failures.append("cash_ledger_period_count_mismatch")
    if not holding_records:
        warnings.append("holding_rows_missing")
    report = {
        "stage_name": "cw2_backtest",
        "contract_version": "cw2-quality-v2",
        "run_name": run_name,
        "row_count": period_count,
        "period_count": period_count,
        "holding_row_count": len(holding_records),
        "cash_ledger_row_count": len(cash_ledger_records),
        "execution_ledger_row_count": len(execution_ledger_records),
        "intraday_event_count": len(intraday_events),
        "intraday_daily_state_row_count": len(intraday_daily_state),
        "metric_count": metric_count,
        "liquidity_clipped_periods": sum(
            1 for row in performance_records if bool(row.get("liquidity_clipped"))
        ),
        "forward_filled_periods": sum(
            1
            for row in performance_records
            if int(row.get("forward_filled_symbol_count", 0) or 0) > 0
        ),
        "forward_filled_symbol_total": sum(
            int(row.get("forward_filled_symbol_count", 0) or 0) for row in performance_records
        ),
        "forward_fill_day_total": sum(
            int(row.get("forward_fill_day_count", 0) or 0) for row in performance_records
        ),
        "final_portfolio_nav": (
            float(performance_records[-1]["portfolio_nav"]) if performance_records else None
        ),
        "final_benchmark_nav": (
            float(performance_records[-1]["benchmark_nav"]) if performance_records else None
        ),
        "cash_ledger_matches_period_count": len(cash_ledger_records) == period_count,
        "failures": failures,
        "warnings": warnings,
    }
    report["passed"] = len(failures) == 0
    return report
