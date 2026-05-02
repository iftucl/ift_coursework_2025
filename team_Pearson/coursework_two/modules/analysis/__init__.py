from __future__ import annotations

"""CW2 performance analysis orchestration."""

import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from team_Pearson.coursework_two.modules.analysis.benchmark_metrics import (
    compute_benchmark_absolute_metrics,
)
from team_Pearson.coursework_two.modules.analysis.covariance_risk import (
    compute_covariance_diagnostics,
    load_weight_sets,
)
from team_Pearson.coursework_two.modules.analysis.factor_attribution import (
    compute_factor_attribution,
)
from team_Pearson.coursework_two.modules.analysis.regime_attribution import (
    classify_period_regimes,
    compute_regime_attribution,
)
from team_Pearson.coursework_two.modules.analysis.relative_metrics import compute_relative_metrics
from team_Pearson.coursework_two.modules.analysis.scorecard import compute_scorecard
from team_Pearson.coursework_two.modules.analysis.static_baseline import build_static_baseline_path
from team_Pearson.coursework_two.modules.analysis.universe_benchmark import build_universe_ew_path
from team_Pearson.coursework_two.modules.backtest.data_loader import (
    get_month_end_trading_days,
    load_trading_calendar,
    shift_trading_day,
)
from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot

_SCHEMA = "systematic_equity"


def run_full_analysis(
    run_id: str,
    db_engine: Engine,
    config: dict,
    robustness_run_id_25bps: Optional[str] = None,
) -> dict:
    """Run the full analysis pipeline and persist all outputs."""
    ensure_analysis_schema(db_engine)
    run_context = load_analysis_run_context(run_id, db_engine, config)
    threshold = float(run_context["analysis_config"]["stress_vix_threshold"])
    period_regimes = classify_period_regimes(db_engine, run_context["periods"], threshold)

    # Analysis comparison contract:
    # - The stored benchmark_ticker is the external primary market path
    #   (SPY in the formal configuration).
    # - universe_ew is a gross same-universe opportunity-set comparison.
    # - static_baseline is a tradable construction-layer control and is net of
    #   the configured trading-cost assumption.
    benchmark_records = []
    benchmark_records.extend(_build_external_benchmark_nav(run_context, period_regimes))
    universe_rows, universe_weights = build_universe_ew_path(run_context, db_engine, period_regimes)
    static_rows, static_weights = build_static_baseline_path(run_context, db_engine, period_regimes)
    benchmark_records.extend(universe_rows)
    benchmark_records.extend(static_rows)
    _upsert_rows(
        db_engine,
        table_name="backtest_benchmark_nav",
        rows=benchmark_records,
        allowed_cols=[
            "run_id",
            "execution_date",
            "period_end_date",
            "series_name",
            "nav",
            "period_return",
            "gross_return",
            "risk_free_return",
            "turnover",
            "gross_turnover",
            "transaction_cost",
            "num_holdings",
            "regime",
        ],
        conflict_cols=["run_id", "period_end_date", "series_name"],
    )
    benchmark_metric_rows = compute_benchmark_absolute_metrics(
        benchmark_records, run_id=str(run_id)
    )
    _upsert_rows(
        db_engine,
        table_name="backtest_benchmark_metrics",
        rows=benchmark_metric_rows,
        allowed_cols=[
            "run_id",
            "series_name",
            "metric_name",
            "metric_value",
            "metric_unit",
        ],
        conflict_cols=["run_id", "series_name", "metric_name"],
    )

    weight_sets = load_weight_sets(
        run_context,
        db_engine,
        universe_weights=universe_weights,
        static_weights=static_weights,
    )
    covariance_metric_rows, covariance_contribution_rows = compute_covariance_diagnostics(
        run_context,
        db_engine,
        strategy_weights=weight_sets["strategy"],
        universe_weights=weight_sets["universe_ew"],
        static_weights=weight_sets["static_baseline"],
    )
    _upsert_rows(
        db_engine,
        table_name="backtest_covariance_metrics",
        rows=covariance_metric_rows,
        allowed_cols=[
            "run_id",
            "rebalance_date",
            "period_end_date",
            "series_name",
            "versus_series",
            "metric_name",
            "metric_value",
            "metric_unit",
            "covariance_method",
            "lookback_days",
        ],
        conflict_cols=[
            "run_id",
            "rebalance_date",
            "period_end_date",
            "series_name",
            "versus_series",
            "metric_name",
        ],
    )
    _upsert_rows(
        db_engine,
        table_name="backtest_covariance_contributions",
        rows=covariance_contribution_rows,
        allowed_cols=[
            "run_id",
            "rebalance_date",
            "period_end_date",
            "series_name",
            "dimension_type",
            "dimension_name",
            "portfolio_weight",
            "risk_contribution_pct",
            "component_volatility_contribution",
            "covariance_method",
            "lookback_days",
        ],
        conflict_cols=[
            "run_id",
            "rebalance_date",
            "period_end_date",
            "series_name",
            "dimension_type",
            "dimension_name",
        ],
    )

    relative_metrics = compute_relative_metrics(run_context, db_engine)
    _upsert_rows(
        db_engine,
        table_name="backtest_relative_metrics",
        rows=relative_metrics,
        allowed_cols=[
            "run_id",
            "versus_series",
            "metric_name",
            "metric_value",
            "metric_unit",
        ],
        conflict_cols=["run_id", "versus_series", "metric_name"],
    )

    regime_rows = compute_regime_attribution(run_context, db_engine, period_regimes=period_regimes)
    _upsert_rows(
        db_engine,
        table_name="backtest_regime_attribution",
        rows=regime_rows,
        allowed_cols=[
            "run_id",
            "regime",
            "versus_series",
            "n_periods",
            "strategy_ann_return",
            "versus_ann_return",
            "excess_ann_return",
            "strategy_ann_vol",
            "versus_ann_vol",
            "strategy_sharpe",
            "versus_sharpe",
            "strategy_max_dd",
            "versus_max_dd",
            "hit_rate",
        ],
        conflict_cols=["run_id", "regime", "versus_series"],
    )

    factor_rows = compute_factor_attribution(run_context, db_engine)
    _upsert_rows(
        db_engine,
        table_name="backtest_factor_attribution",
        rows=factor_rows,
        allowed_cols=[
            "run_id",
            "rebalance_date",
            "period_end_date",
            "factor_name",
            "strategy_exposure",
            "universe_exposure",
            "active_exposure",
            "factor_spread_return",
            "contribution_proxy",
            "top_bucket_size",
            "bottom_bucket_size",
            "attribution_method",
        ],
        conflict_cols=["run_id", "rebalance_date", "factor_name"],
    )

    scorecard_rows = compute_scorecard(
        db_engine,
        run_id=run_id,
        config=run_context["config"],
        robustness_run_id_25bps=robustness_run_id_25bps,
    )
    _upsert_rows(
        db_engine,
        table_name="backtest_scorecard",
        rows=scorecard_rows,
        allowed_cols=["run_id", "criterion_id", "criterion_name", "passed", "evidence"],
        conflict_cols=["run_id", "criterion_id"],
    )

    result = {
        "universe_ew_periods": sum(
            1 for row in benchmark_records if row["series_name"] == "universe_ew"
        ),
        "static_baseline_periods": sum(
            1 for row in benchmark_records if row["series_name"] == "static_baseline"
        ),
        "benchmark_metric_rows": len(benchmark_metric_rows),
        "covariance_metric_rows": len(covariance_metric_rows),
        "covariance_contribution_rows": len(covariance_contribution_rows),
        "factor_attribution_rows": len(factor_rows),
        "scorecard_passed": sum(1 for row in scorecard_rows if row.get("passed") is True),
        "scorecard_total": len(scorecard_rows),
    }
    run_date = max(
        (period["period_end_date"] for period in run_context["periods"]),
        default=run_context["run_row"]["end_date"],
    )
    record_quality_snapshot(
        engine=db_engine,
        dataset_name="backtest_scorecard",
        run_id=str(run_id),
        run_date=run_date,
        quality_report=_build_analysis_quality_report(run_id=str(run_id), result=result),
    )
    return result


def ensure_analysis_schema(engine: Engine) -> None:
    """Create or migrate the analysis schema."""
    schema_path = Path(__file__).resolve().parents[2] / "sql" / "cw2_analysis_schema.sql"
    sql_text = schema_path.read_text(encoding="utf-8")
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.execute(sql_text)
        raw_conn.commit()
    finally:
        raw_conn.close()


def load_analysis_run_context(run_id: str, db_engine: Engine, config: dict) -> Dict[str, Any]:
    """Load immutable run metadata and reconstruct monthly backtest periods."""
    run_row = _load_run_row(run_id, db_engine)
    if run_row is None:
        raise ValueError(f"backtest run not found: {run_id}")

    current_config = deepcopy(config or {})
    snapshot_backtest = deepcopy((run_row.get("config_snapshot", {}) or {}).get("backtest") or {})
    current_backtest = deepcopy((current_config.get("backtest") or {}))
    effective_backtest = {**current_backtest, **snapshot_backtest}

    current_analysis = deepcopy(current_backtest.get("analysis") or {})
    snapshot_analysis = deepcopy(snapshot_backtest.get("analysis") or {})
    effective_backtest["analysis"] = {**snapshot_analysis, **current_analysis}

    effective_config = deepcopy(current_config)
    effective_config["backtest"] = effective_backtest

    analysis_cfg = deepcopy(effective_backtest.get("analysis") or {})
    if "stress_vix_threshold" not in analysis_cfg:
        analysis_cfg["stress_vix_threshold"] = (effective_config.get("regime") or {}).get(
            "vix_stress_threshold"
        ) or 25
    if "primary_benchmark" not in analysis_cfg:
        analysis_cfg["primary_benchmark"] = str(run_row["benchmark_ticker"])
    if "secondary_benchmark" not in analysis_cfg:
        analysis_cfg["secondary_benchmark"] = "universe_ew"
    if "universe_ew_deduct_cost" not in analysis_cfg:
        analysis_cfg["universe_ew_deduct_cost"] = False
    if "static_baseline_cost_bps" not in analysis_cfg:
        analysis_cfg["static_baseline_cost_bps"] = float(run_row["transaction_cost_bps"])
    if "static_baseline_normal_weights" not in analysis_cfg:
        analysis_cfg["static_baseline_normal_weights"] = deepcopy(
            (effective_config.get("regime") or {}).get("normal")
            or {
                "quality": 0.20,
                "value": 0.20,
                "market_technical": 0.30,
                "sentiment": 0.20,
                "dividend": 0.10,
            }
        )

    trading_calendar = load_trading_calendar(
        db_engine,
        run_row["start_date"],
        run_row["end_date"] + timedelta(days=max(10, int(run_row["execution_lag"]) * 3)),
        benchmark_ticker=str(run_row["benchmark_ticker"]),
    )
    rebalance_dates = get_month_end_trading_days(trading_calendar)
    execution_lag = int(run_row["execution_lag"])
    while rebalance_dates:
        try:
            shift_trading_day(trading_calendar, rebalance_dates[-1], execution_lag)
            break
        except ValueError:
            rebalance_dates.pop()
    if len(rebalance_dates) < 2:
        raise ValueError(
            "Insufficient executable rebalance dates in analysis context after trimming terminal incomplete periods"
        )
    performance_lookup = _load_strategy_performance(run_id, db_engine)
    periods: List[Dict[str, Any]] = []
    for idx in range(len(rebalance_dates) - 1):
        rebalance_date = rebalance_dates[idx]
        execution_date = shift_trading_day(trading_calendar, rebalance_date, execution_lag)
        period_end_date = shift_trading_day(
            trading_calendar, rebalance_dates[idx + 1], execution_lag
        )
        perf = performance_lookup.get(period_end_date, {})
        periods.append(
            {
                "rebalance_date": rebalance_date,
                "execution_date": execution_date,
                "period_end_date": period_end_date,
                "strategy_net_return": perf.get("net_return"),
                "strategy_gross_return": perf.get("gross_return"),
                "strategy_nav": perf.get("portfolio_nav"),
                "benchmark_return": perf.get("benchmark_return"),
                "benchmark_nav": perf.get("benchmark_nav"),
                "risk_free_return": perf.get("risk_free_return"),
                "vix_snapshot": perf.get("vix_level"),
                "strategy_regime": perf.get("regime"),
            }
        )

    return {
        "run_id": run_id,
        "run_row": run_row,
        "config": effective_config,
        "analysis_config": analysis_cfg,
        "periods": periods,
    }


def load_analysis_config(config_path: str | None = None) -> Dict[str, Any]:
    """Load the CW2 YAML config for an analysis run."""
    from team_Pearson.coursework_two.modules.utils.config_validation import load_cw2_config

    return load_cw2_config(config_path)


def run_analysis_from_config(
    *,
    run_id: str,
    config_path: str | None = None,
    db_engine: Engine | None = None,
    robustness_run_id_25bps: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for launching analysis from CW2 config."""
    config = load_analysis_config(config_path)
    if db_engine is None:
        from team_Pearson.coursework_two.modules.backtest.engine import _load_shared_db_engine

        db_engine = _load_shared_db_engine()
    return run_full_analysis(
        run_id=run_id,
        db_engine=db_engine,
        config=config,
        robustness_run_id_25bps=robustness_run_id_25bps,
    )


def _build_external_benchmark_nav(
    run_context: Dict[str, Any],
    period_regimes: Dict[date, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    run_id = str(run_context["run_id"])
    run_row = dict(run_context.get("run_row") or {})
    analysis_cfg = dict(run_context.get("analysis_config") or {})
    series_name = str(
        run_row.get("benchmark_ticker") or analysis_cfg.get("primary_benchmark") or "SPY"
    )
    rows: List[Dict[str, Any]] = []
    for period in run_context["periods"]:
        regime_row = period_regimes.get(period["period_end_date"], {})
        rows.append(
            {
                "run_id": run_id,
                "execution_date": period.get("execution_date"),
                "period_end_date": period["period_end_date"],
                "series_name": series_name,
                "nav": period.get("benchmark_nav"),
                "period_return": period.get("benchmark_return"),
                "gross_return": None,
                "risk_free_return": period.get("risk_free_return"),
                "turnover": None,
                "gross_turnover": None,
                "transaction_cost": None,
                "num_holdings": None,
                "regime": regime_row.get("regime"),
            }
        )
    return rows


def _load_run_row(run_id: str, db_engine: Engine) -> Optional[Dict[str, Any]]:
    import json

    sql = text(f"""
        SELECT run_id, start_date, end_date, rebalance_freq, execution_lag,
               transaction_cost_bps, weighting, top_n, benchmark_ticker, config_snapshot
        FROM {_SCHEMA}.backtest_runs
        WHERE run_id = :run_id
        """)
    with db_engine.connect() as conn:
        row = conn.execute(sql, {"run_id": run_id}).mappings().first()
    if row is None:
        return None
    out = dict(row)
    config_snapshot = out.get("config_snapshot")
    if isinstance(config_snapshot, str):
        out["config_snapshot"] = json.loads(config_snapshot)
    elif config_snapshot is None:
        out["config_snapshot"] = {}
    return out


def _build_analysis_quality_report(*, run_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    failures: list[str] = []
    if int(result.get("universe_ew_periods") or 0) <= 0:
        failures.append("universe_ew_periods_missing")
    if int(result.get("static_baseline_periods") or 0) <= 0:
        failures.append("static_baseline_periods_missing")
    if int(result.get("scorecard_total") or 0) <= 0:
        failures.append("scorecard_rows_missing")
    report = {
        "stage_name": "cw2_analysis",
        "contract_version": "cw2-quality-v2",
        "run_id": run_id,
        "row_count": int(result.get("scorecard_total") or 0),
        "universe_ew_periods": int(result.get("universe_ew_periods") or 0),
        "static_baseline_periods": int(result.get("static_baseline_periods") or 0),
        "benchmark_metric_rows": int(result.get("benchmark_metric_rows") or 0),
        "covariance_metric_rows": int(result.get("covariance_metric_rows") or 0),
        "covariance_contribution_rows": int(result.get("covariance_contribution_rows") or 0),
        "scorecard_passed": int(result.get("scorecard_passed") or 0),
        "scorecard_total": int(result.get("scorecard_total") or 0),
        "failures": failures,
        "warnings": [],
    }
    report["passed"] = len(failures) == 0
    return report


def _load_strategy_performance(run_id: str, db_engine: Engine) -> Dict[date, Dict[str, Any]]:
    sql = text(f"""
        SELECT execution_date, period_end_date, gross_return, net_return, benchmark_return,
               risk_free_return, portfolio_nav, benchmark_nav, regime, vix_level
        FROM {_SCHEMA}.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    with db_engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    return {row["period_end_date"]: dict(row) for row in rows}


def _upsert_rows(
    engine: Engine,
    *,
    table_name: str,
    rows: List[Dict[str, Any]],
    allowed_cols: List[str],
    conflict_cols: List[str],
) -> int:
    if not rows:
        return 0

    insert_cols = ", ".join(allowed_cols)
    bind_cols = ", ".join(f":{col}" for col in allowed_cols)
    update_cols = [col for col in allowed_cols if col not in conflict_cols]
    update_sql = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)
    sql = text(f"""
        INSERT INTO {_SCHEMA}.{table_name} ({insert_cols})
        VALUES ({bind_cols})
        ON CONFLICT ({", ".join(conflict_cols)})
        DO UPDATE SET {update_sql}
        """)
    cleaned = [{col: _normalize_bind_value(row.get(col)) for col in allowed_cols} for row in rows]
    with engine.begin() as conn:
        conn.execute(sql, cleaned)
    return len(cleaned)


def _normalize_bind_value(value: Any) -> Any:
    if isinstance(value, dict):
        return json.dumps(_json_safe_value(value), sort_keys=True)
    if isinstance(value, (list, tuple)):
        return json.dumps(_json_safe_value(list(value)), sort_keys=True)
    return _json_safe_value(value)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe_value(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(inner) for inner in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if hasattr(value, "item"):
        try:
            return _json_safe_value(value.item())
        except Exception:
            return value
    return value


__all__ = [
    "run_full_analysis",
    "load_analysis_config",
    "load_analysis_run_context",
    "run_analysis_from_config",
]
