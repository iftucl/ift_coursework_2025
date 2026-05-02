from __future__ import annotations

"""Rule-driven daily update decisions for the CW2 operating model."""

import json
import math
import os
from calendar import monthrange
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine
from team_Pearson.coursework_two.modules.backtest.data_loader import (
    get_month_end_trading_days,
    load_trading_calendar,
)
from team_Pearson.coursework_two.modules.backtest.engine import _load_shared_db_engine
from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot

_SCHEMA = "systematic_equity"


def run_update_decision_from_config(
    *,
    run_date: str,
    config_path: str | None = None,
    db_engine: Engine | None = None,
) -> Dict[str, Any]:
    """Materialize one rule-driven daily update decision."""

    config = _load_config(config_path)
    engine = db_engine or _load_shared_db_engine()
    ensure_update_decision_schema(engine)

    run_day = date.fromisoformat(str(run_date))
    portfolio_name = _resolve_portfolio_name(config)
    is_month_end = _is_month_end_rebalance_day(engine, run_day, config)
    latest_snapshot_as_of, latest_snapshot_position_count = _latest_portfolio_snapshot(
        engine,
        run_date=run_day,
        portfolio_name=portfolio_name,
    )
    latest_recommendation_as_of = _latest_recommendation_as_of_date(
        engine,
        run_date=run_day,
        portfolio_name=portfolio_name,
    )
    snapshot_symbols = _load_snapshot_symbols(
        engine,
        as_of_date=latest_snapshot_as_of,
        portfolio_name=portfolio_name,
    )
    signal_as_of_date = _resolve_signal_as_of_date(
        engine,
        run_date=run_day,
        symbols=snapshot_symbols,
    )
    trigger_summary = _event_trigger_summary(
        engine,
        run_date=run_day,
        signal_as_of_date=signal_as_of_date,
        config=config,
        symbols=snapshot_symbols,
    )
    monitoring_review = _monitoring_review_summary(
        engine,
        run_date=run_day,
        config=config,
        portfolio_name=portfolio_name,
        latest_snapshot_as_of=latest_snapshot_as_of,
    )
    trigger_summary["monitoring_review"] = monitoring_review
    decision_scope, recommended_mode, reason_code = classify_update_decision(
        run_date=run_day,
        is_month_end_rebalance_day=is_month_end,
        latest_snapshot_as_of=latest_snapshot_as_of,
        trigger_symbol_count=int(trigger_summary.get("trigger_symbol_count", 0)),
        monitoring_review_required=bool(monitoring_review.get("review_required", False)),
        approval_required=_approval_required(config),
        scheduled_rebalance_review_mode=_scheduled_rebalance_review_mode(config),
    )
    scheduled_review_mode = _scheduled_rebalance_review_mode(config)
    requires_human_review = decision_scope in {"risk_review", "blocked"} or (
        bool(monitoring_review.get("review_required", False))
        and (not is_month_end or scheduled_review_mode == "required")
    )

    payload = {
        "run_date": run_day,
        "portfolio_name": portfolio_name,
        "decision_scope": decision_scope,
        "recommended_mode": recommended_mode,
        "reason_code": reason_code,
        "is_month_end_rebalance_day": is_month_end,
        "requires_human_review": requires_human_review,
        "latest_snapshot_as_of_date": latest_snapshot_as_of,
        "latest_recommendation_as_of_date": latest_recommendation_as_of,
        "signal_as_of_date": signal_as_of_date,
        "latest_snapshot_position_count": latest_snapshot_position_count,
        "trigger_symbol_count": int(trigger_summary.get("trigger_symbol_count", 0)),
        "trigger_summary_json": json.dumps(trigger_summary, sort_keys=True),
        "config_snapshot": json.dumps(config, sort_keys=True),
    }
    _upsert_update_decision(engine, payload)
    result = {
        "run_date": run_day.isoformat(),
        "portfolio_name": portfolio_name,
        "decision_scope": decision_scope,
        "recommended_mode": recommended_mode,
        "reason_code": reason_code,
        "is_month_end_rebalance_day": is_month_end,
        "requires_human_review": requires_human_review,
        "latest_snapshot_as_of_date": (
            latest_snapshot_as_of.isoformat() if latest_snapshot_as_of else None
        ),
        "latest_recommendation_as_of_date": (
            latest_recommendation_as_of.isoformat() if latest_recommendation_as_of else None
        ),
        "signal_as_of_date": (signal_as_of_date.isoformat() if signal_as_of_date else None),
        "latest_snapshot_position_count": latest_snapshot_position_count,
        "trigger_summary": trigger_summary,
    }
    record_quality_snapshot(
        engine=engine,
        dataset_name="portfolio_update_decisions",
        run_id=f"{portfolio_name}:{run_day.isoformat()}",
        run_date=run_day,
        quality_report=_build_update_decision_quality_report(result),
    )

    return result


def classify_update_decision(
    *,
    run_date: date,
    is_month_end_rebalance_day: bool,
    latest_snapshot_as_of: Optional[date],
    trigger_symbol_count: int,
    monitoring_review_required: bool = False,
    approval_required: bool = True,
    scheduled_rebalance_review_mode: str = "required",
) -> Tuple[str, str, str]:
    """Classify the platform's next action for one run date."""

    if is_month_end_rebalance_day:
        if monitoring_review_required:
            if scheduled_rebalance_review_mode == "automatic":
                return (
                    "full_rebalance",
                    "operate",
                    "scheduled_month_end_rebalance_auto_monitoring_override",
                )
            if scheduled_rebalance_review_mode == "advisory":
                return (
                    "full_rebalance",
                    "operate",
                    "scheduled_month_end_rebalance_with_monitoring_flag",
                )
            return (
                "full_rebalance",
                "operate",
                "scheduled_month_end_rebalance_with_review_gate",
            )
        return "full_rebalance", "operate", "scheduled_month_end_rebalance"
    if latest_snapshot_as_of is None:
        return "blocked", "none", "missing_existing_portfolio_snapshot"
    if trigger_symbol_count > 0:
        return "risk_review", "risk_overlay_review", "adverse_event_proxy_triggered"
    if monitoring_review_required:
        return (
            "risk_review",
            ("prepare_recommendation_for_approval" if approval_required else "monitoring_review"),
            "monitoring_review_threshold_breached",
        )
    _ = run_date
    return "monitor_only", "none", "no_rebalance_or_adverse_trigger"


def _build_update_decision_quality_report(result: Dict[str, Any]) -> Dict[str, Any]:
    trigger_summary = dict(result.get("trigger_summary") or {})
    trigger_symbol_count = int(trigger_summary.get("trigger_symbol_count", 0) or 0)
    monitoring_review = dict(trigger_summary.get("monitoring_review") or {})
    latest_snapshot_count = result.get("latest_snapshot_position_count")
    decision_scope = str(result.get("decision_scope") or "unknown")
    latest_snapshot_available = result.get("latest_snapshot_as_of_date") is not None
    report = {
        "portfolio_name": str(result.get("portfolio_name") or ""),
        "decision_scope": decision_scope,
        "recommended_mode": str(result.get("recommended_mode") or "none"),
        "reason_code": str(result.get("reason_code") or ""),
        "latest_snapshot_available": latest_snapshot_available,
        "signal_as_of_date": result.get("signal_as_of_date"),
        "latest_snapshot_position_count": (
            int(latest_snapshot_count or 0) if latest_snapshot_count is not None else None
        ),
        "trigger_symbol_count": trigger_symbol_count,
        "monitoring_review_required": bool(monitoring_review.get("review_required", False)),
        "monitoring_review_reason_count": int(monitoring_review.get("reason_count", 0) or 0),
        "requires_human_review": bool(result.get("requires_human_review")),
        "is_month_end_rebalance_day": bool(result.get("is_month_end_rebalance_day")),
    }
    report["passed"] = bool(decision_scope != "blocked" and latest_snapshot_available)
    return report


def ensure_update_decision_schema(engine: Engine) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "sql" / "cw2_ops_schema.sql"
    sql_text = schema_path.read_text(encoding="utf-8")
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.execute(sql_text)
        raw_conn.commit()
    finally:
        raw_conn.close()


def _load_config(config_path: str | None) -> Dict[str, Any]:
    from team_Pearson.coursework_two.modules.utils.config_validation import load_cw2_config

    return load_cw2_config(config_path)


def _resolve_portfolio_name(config: Dict[str, Any]) -> str:
    recommendation_cfg = dict(config.get("recommendation") or {})
    portfolio_cfg = dict(config.get("portfolio_construction") or {})
    return str(
        recommendation_cfg.get("portfolio_name")
        or portfolio_cfg.get("portfolio_name")
        or "cw2_core_equity"
    )


def _approval_required(config: Dict[str, Any]) -> bool:
    recommendation_cfg = dict(config.get("recommendation") or {})
    return bool(recommendation_cfg.get("approval_required", True))


def _scheduled_rebalance_review_mode(config: Dict[str, Any]) -> str:
    recommendation_cfg = dict(config.get("recommendation") or {})
    monitoring_cfg = dict(recommendation_cfg.get("monitoring_review") or {})
    value = str(monitoring_cfg.get("scheduled_rebalance_review_mode") or "required").strip()
    lowered = value.lower()
    if lowered in {"required", "advisory", "automatic"}:
        return lowered
    return "required"


def _pit_publish_cutoff_predicate(
    cutoff_param: str, *, fallback_expr: str = "observation_date"
) -> str:
    cutoff_param = str(cutoff_param).strip()
    fallback_expr = str(fallback_expr).strip()
    if not cutoff_param or not fallback_expr:
        raise ValueError("publish cutoff predicate requires cutoff_param and fallback_expr")
    return f"COALESCE(publish_date, {fallback_expr}) <= :{cutoff_param}"


def _signal_as_of_min_coverage_ratio() -> float:
    raw = str(os.getenv("CW2_FEATURE_ASOF_MIN_SYMBOL_COVERAGE_RATIO", "0.60")).strip()
    try:
        ratio = float(raw)
    except ValueError:
        ratio = 0.60
    return max(0.0, min(1.0, ratio))


def _resolve_signal_as_of_date(
    engine: Engine,
    *,
    run_date: date,
    symbols: Sequence[str],
) -> Optional[date]:
    clean_symbols = sorted(
        {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    )
    if not clean_symbols:
        return None

    min_symbols = max(
        1,
        math.ceil(len(set(clean_symbols)) * _signal_as_of_min_coverage_ratio()),
    )
    price_anchor_sql = text(f"""
            SELECT observation_date AS signal_as_of_date
            FROM {_SCHEMA}.factor_observations
            WHERE symbol IN :symbols
              AND factor_name = 'adjusted_close_price'
              AND observation_date <= :run_date
              AND {_pit_publish_cutoff_predicate("run_date")}
            GROUP BY observation_date
            HAVING COUNT(DISTINCT symbol) >= :min_symbols
            ORDER BY observation_date DESC
            LIMIT 1
            """).bindparams(bindparam("symbols", expanding=True))
    generic_sql = text(f"""
            SELECT observation_date AS signal_as_of_date
            FROM {_SCHEMA}.factor_observations
            WHERE symbol IN :symbols
              AND observation_date <= :run_date
              AND {_pit_publish_cutoff_predicate("run_date")}
            GROUP BY observation_date
            HAVING COUNT(DISTINCT symbol) >= :min_symbols
            ORDER BY observation_date DESC
            LIMIT 1
            """).bindparams(bindparam("symbols", expanding=True))
    params = {
        "symbols": clean_symbols,
        "run_date": run_date,
        "min_symbols": min_symbols,
    }
    with engine.connect() as conn:
        row = conn.execute(price_anchor_sql, params).mappings().first()
        if row and row["signal_as_of_date"]:
            return row["signal_as_of_date"]
        row = conn.execute(generic_sql, params).mappings().first()
    return row["signal_as_of_date"] if row and row["signal_as_of_date"] else None


def _resolve_rebalance_frequency(config: Dict[str, Any]) -> str:
    bt_cfg = dict(config.get("backtest") or {})
    portfolio_cfg = dict(config.get("portfolio_construction") or {})
    value = str(
        bt_cfg.get("rebalance_frequency")
        or portfolio_cfg.get("target_generation_frequency")
        or "monthly"
    ).strip()
    lowered = value.lower()
    if lowered in {"monthly", "quarterly", "semiannual", "annual"}:
        return lowered
    return "monthly"


def _is_month_end_rebalance_day(engine: Engine, run_date: date, config: Dict[str, Any]) -> bool:
    benchmark_ticker = str((config.get("backtest") or {}).get("benchmark_ticker") or "SPY")
    month_last_day = monthrange(run_date.year, run_date.month)[1]
    month_start = run_date.replace(day=1)
    month_end = run_date.replace(day=month_last_day)
    trading_days = load_trading_calendar(
        engine,
        month_start,
        month_end,
        benchmark_ticker=benchmark_ticker,
    )
    anchors = get_month_end_trading_days(trading_days)
    frequency = _resolve_rebalance_frequency(config)
    if frequency == "monthly":
        return run_date in anchors

    allowed_months = {
        "quarterly": {3, 6, 9, 12},
        "semiannual": {6, 12},
        "annual": {12},
    }.get(frequency, set())
    return any(anchor == run_date and anchor.month in allowed_months for anchor in anchors)


def _latest_portfolio_snapshot(
    engine: Engine,
    *,
    run_date: date,
    portfolio_name: str,
) -> Tuple[Optional[date], Optional[int]]:
    registry_sql = text(f"""
        SELECT as_of_date, num_positions
        FROM {_SCHEMA}.portfolio_snapshot_registry
        WHERE portfolio_name = :portfolio_name
          AND as_of_date <= :run_date
          AND snapshot_status = 'completed'
        ORDER BY as_of_date DESC
        LIMIT 1
        """)
    with engine.connect() as conn:
        row = (
            conn.execute(
                registry_sql,
                {"portfolio_name": portfolio_name, "run_date": run_date},
            )
            .mappings()
            .first()
        )
        if row is not None:
            count_value = row.get("num_positions")
            return row["as_of_date"], (int(count_value) if count_value is not None else None)

        fallback_sql = text(f"""
            SELECT as_of_date, COUNT(*) AS num_positions
            FROM {_SCHEMA}.portfolio_target_positions
            WHERE portfolio_name = :portfolio_name
              AND as_of_date <= :run_date
              AND COALESCE(target_weight, 0) > 0
            GROUP BY as_of_date
            ORDER BY as_of_date DESC
            LIMIT 1
            """)
        row = (
            conn.execute(
                fallback_sql,
                {"portfolio_name": portfolio_name, "run_date": run_date},
            )
            .mappings()
            .first()
        )
    if row is None:
        return None, None
    return row["as_of_date"], int(row["num_positions"])


def _latest_recommendation_as_of_date(
    engine: Engine,
    *,
    run_date: date,
    portfolio_name: str,
) -> Optional[date]:
    sql = text(f"""
        SELECT as_of_date
        FROM {_SCHEMA}.portfolio_recommendations
        WHERE portfolio_name = :portfolio_name
          AND as_of_date <= :run_date
        ORDER BY as_of_date DESC, created_at DESC
        LIMIT 1
        """)
    with engine.connect() as conn:
        row = (
            conn.execute(
                sql,
                {"portfolio_name": portfolio_name, "run_date": run_date},
            )
            .mappings()
            .first()
        )
    return None if row is None else row["as_of_date"]


def _resolve_monitoring_review_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    recommendation_cfg = dict(config.get("recommendation") or {})
    portfolio_cfg = dict(config.get("portfolio_construction") or {})
    backtest_cfg = dict(config.get("backtest") or {})
    monitoring_cfg = dict(recommendation_cfg.get("monitoring_review") or {})
    intraday_cfg = dict(backtest_cfg.get("intraday_triggers") or {})
    return {
        "enabled": bool(monitoring_cfg.get("enabled", False)),
        "mandate_breach_requires_review": bool(
            monitoring_cfg.get("mandate_breach_requires_review", True)
        ),
        "turnover_review_threshold": max(
            0.0,
            float(
                monitoring_cfg.get(
                    "min_expected_turnover_for_review",
                    intraday_cfg.get("mid_frequency_min_turnover", 0.0),
                )
                or 0.0
            ),
        ),
        "max_realized_tracking_error": _optional_float(
            monitoring_cfg.get("max_realized_tracking_error")
        ),
        "max_ex_ante_tracking_error": _optional_float(
            monitoring_cfg.get("max_ex_ante_tracking_error")
        ),
        "tracking_error_versus_series": str(
            monitoring_cfg.get("tracking_error_versus_series")
            or backtest_cfg.get("benchmark_ticker")
            or "SPY"
        ),
        "weight_sum_tolerance": max(
            0.0, float(monitoring_cfg.get("weight_sum_tolerance", 0.01) or 0.01)
        ),
        "no_trade_band_weight": max(
            0.0, float(portfolio_cfg.get("no_trade_band_weight", 0.0) or 0.0)
        ),
        "approval_required": _approval_required(config),
    }


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return float(value)


def _load_snapshot_symbols(
    engine: Engine,
    *,
    as_of_date: Optional[date],
    portfolio_name: str,
) -> List[str]:
    if as_of_date is None:
        return []
    sql = text(f"""
        SELECT symbol
        FROM {_SCHEMA}.portfolio_target_positions
        WHERE portfolio_name = :portfolio_name
          AND as_of_date = :as_of_date
          AND COALESCE(target_weight, 0) > 0
        ORDER BY selection_rank NULLS LAST, symbol
        """)
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {"portfolio_name": portfolio_name, "as_of_date": as_of_date},
        ).fetchall()
    return [str(row[0]) for row in rows if str(row[0]).strip()]


def _load_snapshot_monitoring_rows(
    engine: Engine,
    *,
    as_of_date: date,
    portfolio_name: str,
) -> List[Dict[str, Any]]:
    sql = text(f"""
        SELECT
            symbol,
            target_weight,
            gics_sector,
            trade_weight,
            realized_turnover
        FROM {_SCHEMA}.portfolio_target_positions
        WHERE portfolio_name = :portfolio_name
          AND as_of_date = :as_of_date
          AND COALESCE(target_weight, 0) > 0
        ORDER BY selection_rank NULLS LAST, symbol
        """)
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sql,
                {"portfolio_name": portfolio_name, "as_of_date": as_of_date},
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def _summarize_mandate_checks(
    snapshot_rows: Sequence[Dict[str, Any]],
    config: Dict[str, Any],
    *,
    weight_sum_tolerance: float,
) -> Dict[str, Any]:
    portfolio_cfg = dict(config.get("portfolio_construction") or {})
    min_names = int(portfolio_cfg.get("min_names", 1) or 1)
    max_single_weight_limit = _optional_float(portfolio_cfg.get("max_single_weight"))
    max_sector_weight_limit = _optional_float(portfolio_cfg.get("max_sector_weight"))

    weights = [max(0.0, float(row.get("target_weight") or 0.0)) for row in snapshot_rows]
    position_count = len(weights)
    total_weight = float(sum(weights))
    max_single_weight_observed = max(weights) if weights else None
    sector_totals: Dict[str, float] = defaultdict(float)
    missing_sector_count = 0
    for row, weight in zip(snapshot_rows, weights):
        sector = str(row.get("gics_sector") or "").strip()
        if not sector:
            missing_sector_count += 1
            continue
        sector_totals[sector] += weight

    max_sector_name = None
    max_sector_weight_observed = None
    if sector_totals:
        max_sector_name, max_sector_weight_observed = max(
            sector_totals.items(), key=lambda item: item[1]
        )

    breaches: List[str] = []
    if position_count < min_names:
        breaches.append("min_names")
    if (
        max_single_weight_limit is not None
        and max_single_weight_observed is not None
        and max_single_weight_observed > max_single_weight_limit + 1e-8
    ):
        breaches.append("max_single_weight")
    if (
        max_sector_weight_limit is not None
        and max_sector_weight_observed is not None
        and max_sector_weight_observed > max_sector_weight_limit + 1e-8
    ):
        breaches.append("max_sector_weight")
    if abs(total_weight - 1.0) > weight_sum_tolerance + 1e-8:
        breaches.append("weight_sum")

    return {
        "position_count": position_count,
        "min_names": min_names,
        "weight_sum": total_weight,
        "weight_sum_tolerance": weight_sum_tolerance,
        "max_single_weight_observed": max_single_weight_observed,
        "max_single_weight_limit": max_single_weight_limit,
        "max_sector_name": max_sector_name,
        "max_sector_weight_observed": max_sector_weight_observed,
        "max_sector_weight_limit": max_sector_weight_limit,
        "missing_sector_count": missing_sector_count,
        "breach_count": len(breaches),
        "breaches": breaches,
    }


def _summarize_turnover_check(
    snapshot_rows: Sequence[Dict[str, Any]],
    *,
    turnover_review_threshold: float,
) -> Dict[str, Any]:
    implied_one_way_turnover = float(
        sum(abs(float(row.get("trade_weight") or 0.0)) for row in snapshot_rows) / 2.0
    )
    realized_turnover_values = [
        float(row["realized_turnover"])
        for row in snapshot_rows
        if row.get("realized_turnover") is not None
    ]
    stored_realized_turnover = max(realized_turnover_values) if realized_turnover_values else None
    expected_turnover = (
        stored_realized_turnover
        if stored_realized_turnover is not None
        else implied_one_way_turnover
    )
    review_required = bool(
        turnover_review_threshold > 0.0 and expected_turnover >= turnover_review_threshold - 1e-8
    )
    return {
        "turnover_review_threshold": turnover_review_threshold,
        "implied_one_way_turnover": implied_one_way_turnover,
        "stored_realized_turnover": stored_realized_turnover,
        "expected_turnover": expected_turnover,
        "review_required": review_required,
    }


def _load_latest_backtest_monitoring_metrics(
    engine: Engine,
    *,
    portfolio_name: str,
    run_date: date,
    versus_series: str,
) -> Dict[str, Any]:
    run_sql = text(f"""
        SELECT run_id, run_name, end_date, created_at
        FROM {_SCHEMA}.backtest_runs
        WHERE status = 'completed'
          AND end_date <= :run_date
          AND (
                COALESCE(config_snapshot -> 'backtest' ->> 'portfolio_name', '') = :portfolio_name
             OR COALESCE(config_snapshot -> 'portfolio_construction' ->> 'portfolio_name', '') = :portfolio_name
             OR run_name LIKE :portfolio_name_prefix
          )
        ORDER BY end_date DESC, completed_at DESC NULLS LAST, created_at DESC
        LIMIT 1
        """)
    realized_sql = text(f"""
        SELECT metric_value
        FROM {_SCHEMA}.backtest_relative_metrics
        WHERE run_id = :run_id
          AND versus_series = :versus_series
          AND metric_name = 'tracking_error'
        LIMIT 1
        """)
    ex_ante_sql = text(f"""
        SELECT metric_value, rebalance_date, period_end_date
        FROM {_SCHEMA}.backtest_covariance_metrics
        WHERE run_id = :run_id
          AND versus_series = :versus_series
          AND metric_name = 'ex_ante_tracking_error_ann'
        ORDER BY period_end_date DESC, rebalance_date DESC
        LIMIT 1
        """)

    with engine.connect() as conn:
        run_row = (
            conn.execute(
                run_sql,
                {
                    "run_date": run_date,
                    "portfolio_name": portfolio_name,
                    "portfolio_name_prefix": f"{portfolio_name}%",
                },
            )
            .mappings()
            .first()
        )
        if run_row is None:
            return {
                "available": False,
                "versus_series": versus_series,
            }
        realized_row = (
            conn.execute(
                realized_sql,
                {"run_id": run_row["run_id"], "versus_series": versus_series},
            )
            .mappings()
            .first()
        )
        ex_ante_row = (
            conn.execute(
                ex_ante_sql,
                {"run_id": run_row["run_id"], "versus_series": versus_series},
            )
            .mappings()
            .first()
        )

    return {
        "available": True,
        "versus_series": versus_series,
        "run_id": str(run_row["run_id"]),
        "run_name": str(run_row["run_name"]),
        "run_end_date": (
            run_row["end_date"].isoformat() if run_row.get("end_date") is not None else None
        ),
        "realized_tracking_error": (
            float(realized_row["metric_value"])
            if realized_row is not None and realized_row.get("metric_value") is not None
            else None
        ),
        "ex_ante_tracking_error_ann": (
            float(ex_ante_row["metric_value"])
            if ex_ante_row is not None and ex_ante_row.get("metric_value") is not None
            else None
        ),
        "latest_ex_ante_rebalance_date": (
            ex_ante_row["rebalance_date"].isoformat()
            if ex_ante_row is not None and ex_ante_row.get("rebalance_date") is not None
            else None
        ),
        "latest_ex_ante_period_end_date": (
            ex_ante_row["period_end_date"].isoformat()
            if ex_ante_row is not None and ex_ante_row.get("period_end_date") is not None
            else None
        ),
    }


def _summarize_tracking_error_checks(
    backtest_metrics: Dict[str, Any],
    *,
    versus_series: str,
    max_realized_tracking_error: Optional[float],
    max_ex_ante_tracking_error: Optional[float],
) -> Dict[str, Any]:
    realized_tracking_error = _optional_float(backtest_metrics.get("realized_tracking_error"))
    ex_ante_tracking_error = _optional_float(backtest_metrics.get("ex_ante_tracking_error_ann"))
    breaches: List[str] = []
    if (
        max_realized_tracking_error is not None
        and realized_tracking_error is not None
        and realized_tracking_error > max_realized_tracking_error + 1e-8
    ):
        breaches.append("realized_tracking_error")
    if (
        max_ex_ante_tracking_error is not None
        and ex_ante_tracking_error is not None
        and ex_ante_tracking_error > max_ex_ante_tracking_error + 1e-8
    ):
        breaches.append("ex_ante_tracking_error_ann")
    return {
        "available": bool(backtest_metrics.get("available", False)),
        "versus_series": versus_series,
        "run_id": backtest_metrics.get("run_id"),
        "run_name": backtest_metrics.get("run_name"),
        "run_end_date": backtest_metrics.get("run_end_date"),
        "realized_tracking_error": realized_tracking_error,
        "max_realized_tracking_error": max_realized_tracking_error,
        "ex_ante_tracking_error_ann": ex_ante_tracking_error,
        "max_ex_ante_tracking_error": max_ex_ante_tracking_error,
        "latest_ex_ante_rebalance_date": backtest_metrics.get("latest_ex_ante_rebalance_date"),
        "latest_ex_ante_period_end_date": backtest_metrics.get("latest_ex_ante_period_end_date"),
        "breach_count": len(breaches),
        "breaches": breaches,
        "review_required": bool(breaches),
    }


def _monitoring_review_summary(
    engine: Engine,
    *,
    run_date: date,
    config: Dict[str, Any],
    portfolio_name: str,
    latest_snapshot_as_of: Optional[date],
) -> Dict[str, Any]:
    settings = _resolve_monitoring_review_settings(config)
    summary: Dict[str, Any] = {
        "enabled": bool(settings.get("enabled", False)),
        "status": "disabled",
        "review_required": False,
        "reason_count": 0,
        "review_reasons": [],
        "bands": {
            "no_trade_band_weight": settings.get("no_trade_band_weight"),
            "turnover_review_threshold": settings.get("turnover_review_threshold"),
            "max_realized_tracking_error": settings.get("max_realized_tracking_error"),
            "max_ex_ante_tracking_error": settings.get("max_ex_ante_tracking_error"),
        },
        "mandate_checks": {},
        "turnover_check": {},
        "tracking_error_checks": {
            "available": False,
            "versus_series": settings.get("tracking_error_versus_series"),
            "breach_count": 0,
            "breaches": [],
            "review_required": False,
        },
        "workflow": {
            "approval_required": bool(settings.get("approval_required", True)),
            "scheduled_rebalance_review_mode": _scheduled_rebalance_review_mode(config),
            "review_route": "monitor_only",
        },
    }
    if not bool(settings.get("enabled", False)):
        return summary
    if latest_snapshot_as_of is None:
        summary["status"] = "missing_snapshot"
        return summary

    snapshot_rows = _load_snapshot_monitoring_rows(
        engine,
        as_of_date=latest_snapshot_as_of,
        portfolio_name=portfolio_name,
    )
    mandate_checks = _summarize_mandate_checks(
        snapshot_rows,
        config,
        weight_sum_tolerance=float(settings.get("weight_sum_tolerance", 0.01) or 0.01),
    )
    turnover_check = _summarize_turnover_check(
        snapshot_rows,
        turnover_review_threshold=float(settings.get("turnover_review_threshold", 0.0) or 0.0),
    )
    backtest_metrics = _load_latest_backtest_monitoring_metrics(
        engine,
        portfolio_name=portfolio_name,
        run_date=run_date,
        versus_series=str(settings.get("tracking_error_versus_series") or "SPY"),
    )
    tracking_error_checks = _summarize_tracking_error_checks(
        backtest_metrics,
        versus_series=str(settings.get("tracking_error_versus_series") or "SPY"),
        max_realized_tracking_error=_optional_float(settings.get("max_realized_tracking_error")),
        max_ex_ante_tracking_error=_optional_float(settings.get("max_ex_ante_tracking_error")),
    )

    review_reasons: List[str] = []
    if bool(settings.get("mandate_breach_requires_review", True)):
        review_reasons.extend(f"mandate:{breach}" for breach in mandate_checks.get("breaches", []))
    if bool(turnover_check.get("review_required", False)):
        review_reasons.append("turnover:expected_turnover_above_threshold")
    review_reasons.extend(
        f"tracking_error:{breach}" for breach in tracking_error_checks.get("breaches", [])
    )
    review_required = bool(review_reasons)

    summary.update(
        {
            "status": "evaluated",
            "review_required": review_required,
            "reason_count": len(review_reasons),
            "review_reasons": review_reasons,
            "mandate_checks": mandate_checks,
            "turnover_check": turnover_check,
            "tracking_error_checks": tracking_error_checks,
            "workflow": {
                "approval_required": bool(settings.get("approval_required", True)),
                "scheduled_rebalance_review_mode": _scheduled_rebalance_review_mode(config),
                "review_route": (
                    "pm_risk_committee_review"
                    if review_required and bool(settings.get("approval_required", True))
                    else "pm_risk_review" if review_required else "monitor_only"
                ),
            },
        }
    )
    return summary


def _event_trigger_summary(
    engine: Engine,
    *,
    run_date: date,
    signal_as_of_date: Optional[date],
    config: Dict[str, Any],
    symbols: Sequence[str],
) -> Dict[str, Any]:
    intraday_cfg = dict(((config.get("backtest") or {}).get("intraday_triggers") or {}))
    clean_symbols = sorted(
        {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    )
    summary = {
        "run_date": run_date.isoformat(),
        "signal_as_of_date": (signal_as_of_date.isoformat() if signal_as_of_date else None),
        "portfolio_symbol_count": len(clean_symbols),
        "news_trigger_count": 0,
        "earnings_trigger_count": 0,
        "rating_trigger_count": 0,
        "trigger_symbol_count": 0,
        "trigger_symbols": [],
    }
    if (
        not clean_symbols
        or signal_as_of_date is None
        or not bool(intraday_cfg.get("event_driven_enabled", False))
    ):
        return summary

    factor_names = [
        "sentiment_surprise",
        "article_count_30d",
        "earnings_publication_flag",
        "earnings_negative_news_count_daily",
        "rating_downgrade_count_daily",
    ]
    sql = (
        text(f"""
            SELECT symbol, factor_name, factor_value
            FROM {_SCHEMA}.factor_observations
            WHERE observation_date = :signal_as_of_date
              AND symbol IN :symbols
              AND factor_name IN :factor_names
            """)
        .bindparams(bindparam("symbols", expanding=True))
        .bindparams(bindparam("factor_names", expanding=True))
    )
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sql,
                {
                    "signal_as_of_date": signal_as_of_date,
                    "symbols": clean_symbols,
                    "factor_names": factor_names,
                },
            )
            .mappings()
            .all()
        )

    by_symbol: Dict[str, Dict[str, float]] = {}
    for row in rows:
        symbol = str(row["symbol"]).strip().upper()
        factor_name = str(row["factor_name"]).strip()
        factor_value = row["factor_value"]
        if factor_value is None:
            continue
        by_symbol.setdefault(symbol, {})[factor_name] = float(factor_value)

    trigger_symbols: set[str] = set()
    news_threshold = float(intraday_cfg.get("news_sentiment_surprise_threshold", -0.20))
    news_min_articles = float(intraday_cfg.get("news_sentiment_min_article_count", 5.0))
    earnings_min_negative = float(intraday_cfg.get("earnings_negative_news_min_count", 2.0))
    earnings_require_publication = bool(intraday_cfg.get("earnings_require_publication_flag", True))
    rating_min_downgrades = float(intraday_cfg.get("rating_downgrade_min_count", 2.0))

    for symbol, factors in by_symbol.items():
        if bool(intraday_cfg.get("news_sentiment_shock_enabled", False)):
            surprise = factors.get("sentiment_surprise")
            article_count = factors.get("article_count_30d")
            if (
                surprise is not None
                and article_count is not None
                and surprise <= news_threshold
                and article_count >= news_min_articles
            ):
                summary["news_trigger_count"] += 1
                trigger_symbols.add(symbol)

        if bool(intraday_cfg.get("earnings_event_enabled", False)):
            negative_count = factors.get("earnings_negative_news_count_daily")
            publication_flag = factors.get("earnings_publication_flag", 0.0)
            publication_ok = publication_flag >= 0.5 if earnings_require_publication else True
            if (
                publication_ok
                and negative_count is not None
                and negative_count >= earnings_min_negative
            ):
                summary["earnings_trigger_count"] += 1
                trigger_symbols.add(symbol)

        if bool(intraday_cfg.get("rating_downgrade_event_enabled", False)):
            downgrade_count = factors.get("rating_downgrade_count_daily")
            if downgrade_count is not None and downgrade_count >= rating_min_downgrades:
                summary["rating_trigger_count"] += 1
                trigger_symbols.add(symbol)

    summary["trigger_symbols"] = sorted(trigger_symbols)
    summary["trigger_symbol_count"] = len(trigger_symbols)
    return summary


def _upsert_update_decision(engine: Engine, payload: Dict[str, Any]) -> None:
    sql = text(f"""
        INSERT INTO {_SCHEMA}.portfolio_update_decisions (
            run_date,
            portfolio_name,
            decision_scope,
            recommended_mode,
            reason_code,
            is_month_end_rebalance_day,
            requires_human_review,
            latest_snapshot_as_of_date,
            latest_recommendation_as_of_date,
            signal_as_of_date,
            latest_snapshot_position_count,
            trigger_symbol_count,
            trigger_summary_json,
            config_snapshot
        )
        VALUES (
            :run_date,
            :portfolio_name,
            :decision_scope,
            :recommended_mode,
            :reason_code,
            :is_month_end_rebalance_day,
            :requires_human_review,
            :latest_snapshot_as_of_date,
            :latest_recommendation_as_of_date,
            :signal_as_of_date,
            :latest_snapshot_position_count,
            :trigger_symbol_count,
            CAST(:trigger_summary_json AS JSONB),
            CAST(:config_snapshot AS JSONB)
        )
        ON CONFLICT (run_date, portfolio_name)
        DO UPDATE SET
            decision_scope = EXCLUDED.decision_scope,
            recommended_mode = EXCLUDED.recommended_mode,
            reason_code = EXCLUDED.reason_code,
            is_month_end_rebalance_day = EXCLUDED.is_month_end_rebalance_day,
            requires_human_review = EXCLUDED.requires_human_review,
            latest_snapshot_as_of_date = EXCLUDED.latest_snapshot_as_of_date,
            latest_recommendation_as_of_date = EXCLUDED.latest_recommendation_as_of_date,
            signal_as_of_date = EXCLUDED.signal_as_of_date,
            latest_snapshot_position_count = EXCLUDED.latest_snapshot_position_count,
            trigger_symbol_count = EXCLUDED.trigger_symbol_count,
            trigger_summary_json = EXCLUDED.trigger_summary_json,
            config_snapshot = EXCLUDED.config_snapshot,
            updated_at = NOW()
        """)
    with engine.begin() as conn:
        conn.execute(sql, payload)
