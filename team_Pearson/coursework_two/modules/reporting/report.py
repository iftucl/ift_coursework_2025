from __future__ import annotations

"""Database-backed backtest reporting with chart artifacts and SQL registry."""

import hashlib
import json
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import PercentFormatter
from sqlalchemy import text
from sqlalchemy.engine import Engine

plt.switch_backend("Agg")

_REPO_ROOT = Path(__file__).resolve().parents[4]

try:
    from team_Pearson.coursework_two.modules.analysis.benchmark_metrics import (
        compute_benchmark_absolute_metrics,
    )
    from team_Pearson.coursework_two.modules.backtest.writer import (
        compute_config_hash,
        ensure_backtest_schema,
    )
    from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot
    from team_Pearson.coursework_two.modules.utils.governance import (
        REPORTING_VERSION_KEYS,
        resolve_version_bundle,
        select_version_fields,
    )
except ModuleNotFoundError:  # pragma: no cover - import-path fallback for direct module execution
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_two.modules.analysis.benchmark_metrics import (
        compute_benchmark_absolute_metrics,
    )
    from team_Pearson.coursework_two.modules.backtest.writer import (
        compute_config_hash,
        ensure_backtest_schema,
    )
    from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot
    from team_Pearson.coursework_two.modules.utils.governance import (
        REPORTING_VERSION_KEYS,
        resolve_version_bundle,
        select_version_fields,
    )

_SCHEMA = "systematic_equity"
_DEFAULT_PRIMARY_BENCHMARK = "SPY"


def _repo_relative_path(path: Path | str) -> str:
    """Return a portable repository-relative path when the artifact is in repo."""

    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return str(candidate)


def _resolve_artifact_path(path: Path | str) -> Path:
    """Resolve repo-relative artifact paths independently of the caller cwd."""

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    repo_candidate = _REPO_ROOT / candidate
    if repo_candidate.exists() or str(candidate).startswith("team_Pearson/"):
        return repo_candidate
    return candidate


def generate_backtest_report_from_config(
    *,
    run_id: str,
    config_path: str | None = None,
    db_engine: Engine | None = None,
    report_name: str | None = None,
    output_dir: str | None = None,
) -> Dict[str, Any]:
    """Generate charts and markdown from stored backtest/analysis results."""

    config = _load_config(config_path)
    engine = db_engine or _load_shared_db_engine()
    ensure_backtest_schema(engine)
    ensure_reporting_schema(engine)

    run_row = _load_run_row(engine, run_id)
    if run_row is None:
        raise ValueError(f"backtest run not found: {run_id}")

    resolved_report_name = str(report_name or f"{run_row['run_name']}_report")
    root_output_dir = Path(output_dir) if output_dir else _default_output_root(config)
    report_dir = root_output_dir / resolved_report_name
    report_dir.mkdir(parents=True, exist_ok=True)

    report_inputs = _load_report_inputs(engine, run_id)
    report_id = _resolve_existing_report_id(engine, run_id, resolved_report_name) or str(
        uuid.uuid4()
    )
    lineage_context = _load_report_lineage_context(engine, run_row)
    artifact_package = build_backtest_report_artifacts(
        report_dir=report_dir,
        report_name=resolved_report_name,
        run_row=run_row,
        report_inputs=report_inputs,
        config=config,
        report_id=report_id,
        lineage_context=lineage_context,
    )

    report_id = _upsert_report_header(
        engine,
        run_id=run_id,
        report_name=resolved_report_name,
        output_dir=str(report_dir),
        run_row=run_row,
        config=config,
        summary=artifact_package["summary"],
    )
    _replace_report_artifacts(
        engine,
        report_id=report_id,
        run_id=run_id,
        artifacts=artifact_package["artifacts"],
    )
    result = {
        "report_id": report_id,
        "run_id": str(run_id),
        "report_name": resolved_report_name,
        "output_dir": str(report_dir),
        "artifact_count": len(artifact_package["artifacts"]),
        "markdown_path": artifact_package["summary"]["markdown_path"],
        "json_path": artifact_package["summary"]["json_path"],
        "chart_paths": artifact_package["summary"]["chart_paths"],
        "snapshot_id": artifact_package["summary"].get("snapshot_id"),
        "portfolio_snapshot_id": artifact_package["summary"].get("portfolio_snapshot_id"),
        "config_hash": artifact_package["summary"].get("config_hash"),
    }
    record_quality_snapshot(
        engine=engine,
        dataset_name="backtest_reports",
        run_id=report_id,
        run_date=run_row.get("end_date") or datetime.now(timezone.utc),
        quality_report=_build_report_quality_report(result),
    )

    return result


def build_backtest_report_artifacts(
    *,
    report_dir: Path,
    report_name: str,
    run_row: Dict[str, Any],
    report_inputs: Dict[str, pd.DataFrame],
    config: Dict[str, Any],
    report_id: str | None = None,
    lineage_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Pure artifact builder used by the DB-backed report mode and unit tests."""

    performance_df = _ensure_datetime_frame(
        report_inputs.get("performance", pd.DataFrame()), "period_end_date"
    )
    if performance_df.empty:
        raise ValueError(
            "backtest_performance is empty; generate backtest results before requesting a report"
        )

    benchmark_nav_df = _ensure_datetime_frame(
        report_inputs.get("benchmark_nav", pd.DataFrame()), "period_end_date"
    )
    holdings_df = _ensure_datetime_frame(
        report_inputs.get("holdings", pd.DataFrame()),
        "rebalance_date",
    )
    holdings_df = _ensure_datetime_frame(holdings_df, "execution_date")
    metrics_df = report_inputs.get("metrics", pd.DataFrame()).copy()
    relative_metrics_df = report_inputs.get("relative_metrics", pd.DataFrame()).copy()
    benchmark_metrics_df = report_inputs.get("benchmark_metrics", pd.DataFrame()).copy()
    scorecard_df = report_inputs.get("scorecard", pd.DataFrame()).copy()
    covariance_df = _ensure_datetime_frame(
        report_inputs.get("covariance_contributions", pd.DataFrame()),
        "period_end_date",
    )
    covariance_df = _ensure_datetime_frame(covariance_df, "rebalance_date")
    regime_df = report_inputs.get("regime_attribution", pd.DataFrame()).copy()
    trade_blotter_df = _ensure_datetime_frame(
        report_inputs.get("trade_blotter", pd.DataFrame()),
        "trade_date",
    )
    trade_blotter_df = _ensure_datetime_frame(trade_blotter_df, "execution_date")
    trade_blotter_df = _normalize_trade_blotter_labels(
        trade_blotter_df,
        rebalance_frequency=run_row.get("rebalance_freq"),
    )
    trade_sort_cols = [
        col
        for col in [
            "trade_date",
            "execution_date",
            "source_layer",
            "action_type",
            "symbol",
        ]
        if col in trade_blotter_df.columns
    ]
    if trade_sort_cols:
        trade_blotter_df = trade_blotter_df.sort_values(trade_sort_cols, kind="stable")

    analysis_cfg = dict(((config.get("backtest") or {}).get("analysis") or {}))
    primary_benchmark = str(analysis_cfg.get("primary_benchmark") or _DEFAULT_PRIMARY_BENCHMARK)
    secondary_benchmark = str(analysis_cfg.get("secondary_benchmark") or "universe_ew")
    if benchmark_metrics_df.empty and not benchmark_nav_df.empty:
        benchmark_metrics_df = pd.DataFrame(compute_benchmark_absolute_metrics(benchmark_nav_df))

    artifacts: List[Dict[str, Any]] = []
    chart_paths: Dict[str, str] = {}

    nav_chart_path = report_dir / "nav_vs_benchmarks.png"
    _plot_nav_chart(
        performance_df=performance_df,
        benchmark_nav_df=benchmark_nav_df,
        run_row=run_row,
        output_path=nav_chart_path,
    )
    artifacts.append(
        _artifact_record(
            "nav_vs_benchmarks",
            "chart",
            nav_chart_path,
            {
                "series": [
                    "strategy",
                    str(run_row.get("benchmark_ticker") or "benchmark"),
                    "universe_ew",
                    "static_baseline",
                ]
            },
        )
    )
    chart_paths["nav_vs_benchmarks"] = _repo_relative_path(nav_chart_path)

    drawdown_chart_path = report_dir / "drawdown_comparison.png"
    _plot_drawdown_chart(
        performance_df=performance_df,
        benchmark_nav_df=benchmark_nav_df,
        primary_benchmark=primary_benchmark,
        secondary_benchmark=secondary_benchmark,
        output_path=drawdown_chart_path,
    )
    artifacts.append(
        _artifact_record(
            "drawdown_comparison",
            "chart",
            drawdown_chart_path,
            {"primary_benchmark": primary_benchmark},
        )
    )
    chart_paths["drawdown_comparison"] = _repo_relative_path(drawdown_chart_path)

    turnover_chart_path = report_dir / "turnover_and_cost.png"
    _plot_turnover_cost_chart(performance_df=performance_df, output_path=turnover_chart_path)
    artifacts.append(_artifact_record("turnover_and_cost", "chart", turnover_chart_path, {}))
    chart_paths["turnover_and_cost"] = _repo_relative_path(turnover_chart_path)

    if not covariance_df.empty:
        risk_chart_path = report_dir / "latest_sector_risk_contribution.png"
        created = _plot_latest_risk_contribution_chart(
            covariance_df=covariance_df, output_path=risk_chart_path
        )
        if created:
            artifacts.append(
                _artifact_record(
                    "latest_sector_risk_contribution",
                    "chart",
                    risk_chart_path,
                    {"dimension_type": "sector"},
                )
            )
            chart_paths["latest_sector_risk_contribution"] = _repo_relative_path(risk_chart_path)

    summary = _build_report_summary(
        report_name=report_name,
        run_row=run_row,
        performance_df=performance_df,
        metrics_df=metrics_df,
        benchmark_metrics_df=benchmark_metrics_df,
        relative_metrics_df=relative_metrics_df,
        scorecard_df=scorecard_df,
        benchmark_nav_df=benchmark_nav_df,
        holdings_df=holdings_df,
        trade_blotter_df=trade_blotter_df,
        chart_paths=chart_paths,
        config=config,
        analysis_cfg=analysis_cfg,
        primary_benchmark=primary_benchmark,
        secondary_benchmark=secondary_benchmark,
        report_id=report_id,
        lineage_context=lineage_context or {},
    )
    summary.setdefault("version_bundle", {})
    summary["version_bundle"]["reporting_version"] = resolve_version_bundle(config)[
        "reporting_version"
    ]

    trade_blotter_path = None
    if not trade_blotter_df.empty:
        trade_blotter_path = report_dir / "trade_blotter.csv"
        export_cols = [
            col
            for col in [
                "trade_date",
                "execution_date",
                "source_layer",
                "record_granularity",
                "action_type",
                "action_scope",
                "action_family",
                "urgency",
                "symbol",
                "trade_side",
                "weight_before",
                "weight_after",
                "requested_trade_weight",
                "executed_trade_weight",
                "unfilled_weight",
                "execution_price",
                "requested_notional",
                "executed_notional",
                "adv_usd",
                "liquidity_capacity_weight",
                "participation_ratio",
                "had_forward_fill",
                "forward_fill_days",
                "transaction_cost",
                "fixed_transaction_cost",
                "bid_ask_cost",
                "slippage_cost",
                "total_cost",
                "liquidity_clipped",
                "reason_code",
                "regime_before",
                "regime_after",
                "source_table",
                "blotter_id",
            ]
            if col in trade_blotter_df.columns
        ]
        trade_blotter_export = trade_blotter_df.copy()
        trade_blotter_export.loc[:, export_cols].to_csv(trade_blotter_path, index=False)
        artifacts.append(
            _artifact_record(
                "trade_blotter",
                "dataset",
                trade_blotter_path,
                {
                    "row_count": int(len(trade_blotter_export)),
                    "source_layers": sorted(
                        {
                            str(value)
                            for value in trade_blotter_export.get(
                                "source_layer", pd.Series(dtype=object)
                            )
                            .dropna()
                            .tolist()
                        }
                    ),
                },
            )
        )

    markdown_path = report_dir / "report.md"
    markdown_text = _build_report_markdown(
        summary=summary,
        metrics_df=metrics_df,
        benchmark_metrics_df=benchmark_metrics_df,
        relative_metrics_df=relative_metrics_df,
        scorecard_df=scorecard_df,
        regime_df=regime_df,
        trade_blotter_df=trade_blotter_df,
        chart_paths=chart_paths,
        root_dir=report_dir,
        trade_blotter_path=trade_blotter_path,
    )
    markdown_path.write_text(markdown_text, encoding="utf-8")
    artifacts.append(_artifact_record("report_markdown", "markdown", markdown_path, {}))

    json_path = report_dir / "report_summary.json"
    summary["markdown_path"] = _repo_relative_path(markdown_path)
    summary["json_path"] = _repo_relative_path(json_path)
    summary["chart_paths"] = chart_paths
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    artifacts.append(_artifact_record("report_summary", "json", json_path, {}))
    return {
        "summary": summary,
        "artifacts": artifacts,
    }


def _build_report_quality_report(result: Dict[str, Any]) -> Dict[str, Any]:
    chart_paths = dict(result.get("chart_paths") or {})
    markdown_path = _resolve_artifact_path(str(result.get("markdown_path") or ""))
    json_path = _resolve_artifact_path(str(result.get("json_path") or ""))
    report_dir = _resolve_artifact_path(str(result.get("output_dir") or "."))
    report_name = str(result.get("report_name") or "")
    artifact_count = int(result.get("artifact_count") or 0)
    failures: List[str] = []
    warnings: List[str] = []
    if artifact_count < 2:
        failures.append("artifact_count_below_minimum")
    if not markdown_path.exists():
        failures.append("markdown_missing")
    if not json_path.exists():
        failures.append("report_summary_missing")
    if not report_dir.exists():
        failures.append("output_dir_missing")
    if "nav_vs_benchmarks" not in chart_paths:
        warnings.append("nav_chart_missing")
    report = {
        "stage_name": "cw2_report",
        "contract_version": "cw2-quality-v2",
        "report_name": report_name,
        "output_dir": str(report_dir),
        "row_count": artifact_count,
        "artifact_count": artifact_count,
        "chart_count": len(chart_paths),
        "markdown_exists": markdown_path.exists(),
        "json_exists": json_path.exists(),
        "output_dir_exists": report_dir.exists(),
        "has_nav_chart": "nav_vs_benchmarks" in chart_paths,
        "failures": failures,
        "warnings": warnings,
    }
    report["passed"] = len(failures) == 0
    return report


def ensure_reporting_schema(engine: Engine) -> None:
    """Create or migrate the SQL objects used by report registry storage."""

    schema_path = Path(__file__).resolve().parents[2] / "sql" / "cw2_reporting_schema.sql"
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


def _load_shared_db_engine() -> Engine:
    repo_root = Path(__file__).resolve().parents[4]
    cw1_root = repo_root / "team_Pearson" / "coursework_one"
    if str(cw1_root) not in sys.path:
        sys.path.insert(0, str(cw1_root))
    from modules.db import get_db_engine

    return get_db_engine()


def _default_output_root(config: Dict[str, Any]) -> Path:
    reporting_cfg = dict(config.get("reporting") or {})
    configured = reporting_cfg.get("output_dir")
    if configured:
        path = Path(str(configured))
        if path.is_absolute():
            return path
        return _REPO_ROOT / path
    return Path(__file__).resolve().parents[2] / "outputs" / "reports"


def _load_run_row(engine: Engine, run_id: str) -> Dict[str, Any] | None:
    sql = text("""
        SELECT *
        FROM systematic_equity.backtest_runs
        WHERE run_id = :run_id
        """)
    with engine.connect() as conn:
        row = conn.execute(sql, {"run_id": run_id}).mappings().first()
    return dict(row) if row else None


def _load_report_inputs(engine: Engine, run_id: str) -> Dict[str, pd.DataFrame]:
    return {
        "holdings": _read_sql_df(
            engine,
            """
            SELECT *
            FROM systematic_equity.backtest_holdings
            WHERE run_id = :run_id
            ORDER BY rebalance_date, symbol
            """,
            {"run_id": run_id},
        ),
        "performance": _read_sql_df(
            engine,
            """
            SELECT *
            FROM systematic_equity.backtest_performance
            WHERE run_id = :run_id
            ORDER BY period_end_date
            """,
            {"run_id": run_id},
        ),
        "metrics": _read_sql_df(
            engine,
            """
            SELECT *
            FROM systematic_equity.backtest_metrics
            WHERE run_id = :run_id
            ORDER BY metric_group, metric_name
            """,
            {"run_id": run_id},
        ),
        "relative_metrics": _read_sql_df(
            engine,
            """
            SELECT *
            FROM systematic_equity.backtest_relative_metrics
            WHERE run_id = :run_id
            ORDER BY versus_series, metric_name
            """,
            {"run_id": run_id},
        ),
        "benchmark_metrics": _read_sql_df_optional(
            engine,
            table_name="backtest_benchmark_metrics",
            sql="""
            SELECT *
            FROM systematic_equity.backtest_benchmark_metrics
            WHERE run_id = :run_id
            ORDER BY series_name, metric_name
            """,
            params={"run_id": run_id},
        ),
        "scorecard": _read_sql_df_optional(
            engine,
            table_name="backtest_scorecard",
            sql="""
            SELECT *
            FROM systematic_equity.backtest_scorecard
            WHERE run_id = :run_id
            ORDER BY criterion_id
            """,
            params={"run_id": run_id},
        ),
        "benchmark_nav": _read_sql_df_optional(
            engine,
            table_name="backtest_benchmark_nav",
            sql="""
            SELECT *
            FROM systematic_equity.backtest_benchmark_nav
            WHERE run_id = :run_id
            ORDER BY series_name, period_end_date
            """,
            params={"run_id": run_id},
        ),
        "regime_attribution": _read_sql_df_optional(
            engine,
            table_name="backtest_regime_attribution",
            sql="""
            SELECT *
            FROM systematic_equity.backtest_regime_attribution
            WHERE run_id = :run_id
            ORDER BY regime, versus_series
            """,
            params={"run_id": run_id},
        ),
        "trade_blotter": _read_sql_df_optional(
            engine,
            table_name="backtest_trade_blotter",
            sql="""
            SELECT *
            FROM systematic_equity.backtest_trade_blotter
            WHERE run_id = :run_id
            ORDER BY trade_date, execution_date, source_layer, action_type, symbol
            """,
            params={"run_id": run_id},
        ),
        "covariance_contributions": _read_sql_df_optional(
            engine,
            table_name="backtest_covariance_contributions",
            sql="""
            SELECT *
            FROM systematic_equity.backtest_covariance_contributions
            WHERE run_id = :run_id
            ORDER BY rebalance_date, series_name, dimension_type, risk_contribution_pct DESC
            """,
            params={"run_id": run_id},
        ),
    }


def _resolve_existing_report_id(engine: Engine, run_id: str, report_name: str) -> str | None:
    sql = text("""
        SELECT report_id
        FROM systematic_equity.backtest_reports
        WHERE run_id = :run_id
          AND report_name = :report_name
        """)
    with engine.connect() as conn:
        value = conn.execute(sql, {"run_id": run_id, "report_name": report_name}).scalar()
    return str(value) if value is not None else None


def _load_report_lineage_context(engine: Engine, run_row: Dict[str, Any]) -> Dict[str, Any]:
    run_config = _coerce_mapping(run_row.get("config_snapshot"))
    backtest_cfg = _coerce_mapping(run_config.get("backtest"))
    recommendation_cfg = _coerce_mapping(run_config.get("recommendation"))
    portfolio_name = str(
        backtest_cfg.get("portfolio_name")
        or recommendation_cfg.get("portfolio_name")
        or "cw2_core_equity"
    )
    window_start = _coerce_date(run_row.get("start_date"))
    window_end = _coerce_date(run_row.get("end_date"))
    sql = text("""
        SELECT
            psr.id AS portfolio_snapshot_id,
            psr.snapshot_id,
            psr.as_of_date AS portfolio_as_of_date,
            psr.snapshot_status AS portfolio_snapshot_status,
            fsr.requested_as_of_date,
            fsr.as_of_date AS feature_as_of_date,
            fsr.snapshot_status AS feature_snapshot_status
        FROM systematic_equity.portfolio_snapshot_registry AS psr
        LEFT JOIN systematic_equity.feature_snapshot_registry AS fsr
            ON fsr.snapshot_id = psr.snapshot_id
        WHERE psr.portfolio_name = :portfolio_name
          AND psr.as_of_date BETWEEN :window_start AND :window_end
        ORDER BY psr.as_of_date, psr.id
        """)
    rows: List[Dict[str, Any]]
    with engine.connect() as conn:
        result = conn.execute(
            sql,
            {
                "portfolio_name": portfolio_name,
                "window_start": window_start,
                "window_end": window_end,
            },
        ).mappings()
        rows = [dict(row) for row in result]
        if not rows:
            fallback_sql = text("""
                SELECT
                    psr.id AS portfolio_snapshot_id,
                    psr.snapshot_id,
                    psr.as_of_date AS portfolio_as_of_date,
                    psr.snapshot_status AS portfolio_snapshot_status,
                    fsr.requested_as_of_date,
                    fsr.as_of_date AS feature_as_of_date,
                    fsr.snapshot_status AS feature_snapshot_status
                FROM systematic_equity.portfolio_snapshot_registry AS psr
                LEFT JOIN systematic_equity.feature_snapshot_registry AS fsr
                    ON fsr.snapshot_id = psr.snapshot_id
                WHERE psr.portfolio_name = :portfolio_name
                  AND psr.as_of_date <= :window_end
                ORDER BY psr.as_of_date DESC, psr.id DESC
                LIMIT 1
                """)
            rows = [
                dict(row)
                for row in conn.execute(
                    fallback_sql,
                    {"portfolio_name": portfolio_name, "window_end": window_end},
                ).mappings()
            ]
        manifest_payload = None
        if rows and rows[-1].get("snapshot_id") is not None:
            manifest_sql = text("""
                SELECT payload_json
                FROM systematic_equity.model_input_manifests
                WHERE snapshot_id = :snapshot_id
                  AND manifest_type = 'portfolio_input'
                ORDER BY created_at DESC
                LIMIT 1
                """)
            manifest_payload = conn.execute(
                manifest_sql, {"snapshot_id": rows[-1]["snapshot_id"]}
            ).scalar()
    latest = rows[-1] if rows else {}
    manifest_mapping = _coerce_mapping(manifest_payload)
    return {
        "portfolio_name": portfolio_name,
        "snapshot_id": (str(latest["snapshot_id"]) if latest.get("snapshot_id") else None),
        "portfolio_snapshot_id": (
            int(latest["portfolio_snapshot_id"])
            if latest.get("portfolio_snapshot_id") is not None
            else None
        ),
        "requested_as_of_date": _date_to_iso(latest.get("requested_as_of_date")),
        "feature_as_of_date": _date_to_iso(latest.get("feature_as_of_date")),
        "portfolio_as_of_date": _date_to_iso(latest.get("portfolio_as_of_date")),
        "feature_snapshot_status": latest.get("feature_snapshot_status"),
        "portfolio_snapshot_status": latest.get("portfolio_snapshot_status"),
        "lineage_window": {
            "window_start": _date_to_iso(window_start),
            "window_end": _date_to_iso(window_end),
            "snapshot_count": len(rows),
            "first_portfolio_as_of_date": (
                _date_to_iso(rows[0].get("portfolio_as_of_date")) if rows else None
            ),
            "latest_portfolio_as_of_date": (
                _date_to_iso(rows[-1].get("portfolio_as_of_date")) if rows else None
            ),
        },
        "source_table_row_counts": _coerce_mapping(manifest_mapping.get("source_table_row_counts")),
        "latest_upstream_dates": _coerce_mapping(manifest_mapping.get("latest_upstream_dates")),
        "manifest_type": "portfolio_input" if manifest_mapping else None,
    }


def _read_sql_df(engine: Engine, sql: str, params: Dict[str, Any]) -> pd.DataFrame:
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        columns = list(result.keys())
        rows = [
            [float(value) if isinstance(value, Decimal) else value for value in row]
            for row in result.fetchall()
        ]
        return pd.DataFrame(rows, columns=columns)


def _read_sql_df_optional(
    engine: Engine,
    *,
    table_name: str,
    sql: str,
    params: Dict[str, Any],
) -> pd.DataFrame:
    if not _table_exists(engine, table_name):
        return pd.DataFrame()
    return _read_sql_df(engine, sql, params)


def _table_exists(engine: Engine, table_name: str) -> bool:
    sql = text("""
        SELECT EXISTS (
            SELECT 1
            FROM (
                SELECT table_schema AS schema_name, table_name
                FROM information_schema.tables
                UNION ALL
                SELECT table_schema AS schema_name, table_name
                FROM information_schema.views
            ) AS relations
            WHERE schema_name = :schema_name
              AND table_name = :table_name
        ) AS exists_flag
        """)
    with engine.connect() as conn:
        row = (
            conn.execute(sql, {"schema_name": _SCHEMA, "table_name": table_name}).mappings().first()
        )
    return bool(row and row["exists_flag"])


def _ensure_datetime_frame(df: pd.DataFrame, column: str) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return df.copy()
    out = df.copy()
    out[column] = pd.to_datetime(out[column])
    return out


def _canonical_rebalance_frequency(value: Any) -> str:
    candidate = str(value or "monthly").strip().lower()
    return candidate or "monthly"


def _scheduled_source_layer(rebalance_frequency: Any) -> str:
    return f"{_canonical_rebalance_frequency(rebalance_frequency)}_rebalance"


def _scheduled_action_type(rebalance_frequency: Any) -> str:
    return f"{_scheduled_source_layer(rebalance_frequency)}_execution"


def _normalize_trade_blotter_labels(
    trade_blotter_df: pd.DataFrame, *, rebalance_frequency: Any
) -> pd.DataFrame:
    if trade_blotter_df.empty:
        return trade_blotter_df.copy()

    out = trade_blotter_df.copy()
    scheduled_mask = _scheduled_trade_mask(out)

    if not scheduled_mask.any():
        return out

    source_layer = _scheduled_source_layer(rebalance_frequency)
    action_type = _scheduled_action_type(rebalance_frequency)

    if "source_layer" in out.columns:
        out.loc[scheduled_mask, "source_layer"] = source_layer
    if "action_type" in out.columns:
        out.loc[scheduled_mask, "action_type"] = action_type
    if "blotter_id" in out.columns:
        out.loc[scheduled_mask, "blotter_id"] = out.loc[scheduled_mask, "blotter_id"].map(
            lambda value: _normalize_scheduled_blotter_id(
                value,
                rebalance_frequency=rebalance_frequency,
            )
        )

    return out


def _normalize_scheduled_blotter_id(value: Any, *, rebalance_frequency: Any) -> str:
    prefix = f"{_canonical_rebalance_frequency(rebalance_frequency)}:"
    text = str(value or "")
    if not text:
        return prefix
    _, sep, remainder = text.partition(":")
    if not sep:
        return prefix + text
    return prefix + remainder


def _scheduled_trade_mask(trade_blotter_df: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=trade_blotter_df.index)
    if "source_table" in trade_blotter_df.columns:
        mask = mask | trade_blotter_df["source_table"].astype(str).eq("backtest_execution_ledger")
    if "action_family" in trade_blotter_df.columns:
        mask = mask | trade_blotter_df["action_family"].astype(str).eq("scheduled_rebalance")
    if "source_layer" in trade_blotter_df.columns:
        mask = mask | trade_blotter_df["source_layer"].astype(str).str.endswith("_rebalance")
    if "action_type" in trade_blotter_df.columns:
        mask = mask | trade_blotter_df["action_type"].astype(str).str.endswith(
            "_rebalance_execution"
        )
    return mask


def _plot_nav_chart(
    *,
    performance_df: pd.DataFrame,
    benchmark_nav_df: pd.DataFrame,
    run_row: Dict[str, Any],
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    plotted_series = {"strategy"}
    ax.plot(
        performance_df["period_end_date"],
        performance_df["portfolio_nav"],
        label="strategy",
        linewidth=2.2,
    )
    if (
        "benchmark_nav" in performance_df.columns
        and not performance_df["benchmark_nav"].isna().all()
    ):
        label = str(run_row.get("benchmark_ticker") or "benchmark")
        ax.plot(
            performance_df["period_end_date"],
            performance_df["benchmark_nav"],
            label=label,
            linewidth=1.8,
        )
        plotted_series.add(str(label))
    if not benchmark_nav_df.empty:
        for series_name, grp in benchmark_nav_df.groupby("series_name"):
            series_label = str(series_name)
            if series_label in plotted_series:
                continue
            ax.plot(
                grp["period_end_date"],
                grp["nav"],
                label=series_label,
                linewidth=1.4,
                alpha=0.9,
            )
            plotted_series.add(series_label)
    ax.set_title("Portfolio NAV vs Benchmarks")
    ax.set_ylabel("NAV")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    _format_date_axis(ax)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _plot_drawdown_chart(
    *,
    performance_df: pd.DataFrame,
    benchmark_nav_df: pd.DataFrame,
    primary_benchmark: str,
    secondary_benchmark: str,
    output_path: Path,
) -> None:
    strategy_dd = _drawdown_series(performance_df["portfolio_nav"])
    benchmark_series_name = primary_benchmark
    benchmark_series = None
    if primary_benchmark == secondary_benchmark and "benchmark_nav" in performance_df.columns:
        benchmark_series = performance_df["benchmark_nav"]
    elif not benchmark_nav_df.empty:
        bench_rows = benchmark_nav_df.loc[benchmark_nav_df["series_name"] == primary_benchmark]
        if not bench_rows.empty:
            aligned = (
                bench_rows[["period_end_date", "nav"]]
                .rename(columns={"nav": "benchmark_nav"})
                .set_index("period_end_date")
                .reindex(performance_df["period_end_date"])
                .reset_index(drop=True)
            )
            benchmark_series = aligned["benchmark_nav"]
    if benchmark_series is None and "benchmark_nav" in performance_df.columns:
        benchmark_series_name = secondary_benchmark
        benchmark_series = performance_df["benchmark_nav"]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(performance_df["period_end_date"], strategy_dd, label="strategy", linewidth=2.0)
    if benchmark_series is not None:
        ax.plot(
            performance_df["period_end_date"],
            _drawdown_series(pd.Series(benchmark_series)),
            label=str(benchmark_series_name),
            linewidth=1.6,
        )
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("Drawdown Comparison")
    ax.set_ylabel("Drawdown")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    _format_date_axis(ax)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _plot_turnover_cost_chart(*, performance_df: pd.DataFrame, output_path: Path) -> None:
    fig, ax1 = plt.subplots(figsize=(11, 5.5))
    turnover = performance_df["turnover"].fillna(0.0)
    cost_bps = performance_df["transaction_cost"].fillna(0.0) * 10000.0
    ax1.bar(
        performance_df["period_end_date"],
        turnover,
        width=20,
        alpha=0.55,
        color="#366092",
        label="one-way turnover ratio",
    )
    ax1.set_ylabel("Turnover Ratio")
    ax1.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax1.grid(True, axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(
        performance_df["period_end_date"],
        cost_bps,
        color="#c0504d",
        linewidth=1.8,
        label="transaction cost (bps)",
    )
    ax2.set_ylabel("Cost (bps)")
    ax1.set_title("One-Way Turnover Ratio and Transaction Cost by Period")
    handles_1, labels_1 = ax1.get_legend_handles_labels()
    handles_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(handles_1 + handles_2, labels_1 + labels_2, loc="best")
    _format_date_axis(ax1)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _plot_regime_return_chart(*, performance_df: pd.DataFrame, output_path: Path) -> None:
    regime_summary = (
        performance_df.assign(net_return=performance_df["net_return"].fillna(0.0))
        .groupby("regime", dropna=False)["net_return"]
        .agg(["mean", "count"])
        .reset_index()
    )
    regime_summary["regime"] = regime_summary["regime"].fillna("unknown")
    fig, ax = plt.subplots(figsize=(8, 4.8))
    colors = [
        "#70ad47" if str(regime).lower() == "normal" else "#c0504d"
        for regime in regime_summary["regime"]
    ]
    ax.bar(regime_summary["regime"], regime_summary["mean"], color=colors, alpha=0.85)
    for idx, row in regime_summary.iterrows():
        ax.text(
            idx,
            float(row["mean"]),
            f"n={int(row['count'])}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("Average Net Return by Strategy Regime")
    ax.set_ylabel("Average Net Return")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _plot_latest_risk_contribution_chart(*, covariance_df: pd.DataFrame, output_path: Path) -> bool:
    sector_rows = covariance_df.loc[
        (covariance_df["series_name"] == "strategy") & (covariance_df["dimension_type"] == "sector")
    ].copy()
    if sector_rows.empty:
        return False
    latest_date = sector_rows["rebalance_date"].max()
    latest_rows = sector_rows.loc[sector_rows["rebalance_date"] == latest_date].copy()
    latest_rows = latest_rows.sort_values("risk_contribution_pct", ascending=True).tail(10)
    if latest_rows.empty:
        return False

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.barh(
        latest_rows["dimension_name"],
        latest_rows["risk_contribution_pct"],
        color="#5b9bd5",
        alpha=0.85,
    )
    ax.set_title(
        f"Latest Sector Risk Contribution ({pd.Timestamp(latest_date).date().isoformat()})"
    )
    ax.set_xlabel("Risk Contribution")
    ax.xaxis.set_major_formatter(PercentFormatter(100.0))
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return True


def _format_date_axis(ax: plt.Axes) -> None:
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for label in ax.get_xticklabels():
        label.set_rotation(30)
        label.set_ha("right")


def _drawdown_series(nav: pd.Series) -> pd.Series:
    nav = pd.to_numeric(nav, errors="coerce").ffill()
    peak = nav.cummax()
    return (nav / peak) - 1.0


def _build_report_summary(
    *,
    report_name: str,
    run_row: Dict[str, Any],
    performance_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    benchmark_metrics_df: pd.DataFrame,
    relative_metrics_df: pd.DataFrame,
    scorecard_df: pd.DataFrame,
    benchmark_nav_df: pd.DataFrame,
    holdings_df: pd.DataFrame,
    trade_blotter_df: pd.DataFrame,
    chart_paths: Dict[str, str],
    config: Dict[str, Any],
    analysis_cfg: Dict[str, Any],
    primary_benchmark: str,
    secondary_benchmark: str,
    report_id: str | None,
    lineage_context: Dict[str, Any],
) -> Dict[str, Any]:
    metric_lookup = {
        (str(row["metric_group"]), str(row["metric_name"])): _safe_float(row.get("metric_value"))
        for _, row in metrics_df.iterrows()
    }
    relative_lookup = {
        (str(row["versus_series"]), str(row["metric_name"])): _safe_float(row.get("metric_value"))
        for _, row in relative_metrics_df.iterrows()
    }
    benchmark_metric_lookup = {
        (str(row["series_name"]), str(row["metric_name"])): _safe_float(row.get("metric_value"))
        for _, row in benchmark_metrics_df.iterrows()
    }
    benchmark_absolute_metrics: Dict[str, Dict[str, Optional[float]]] = {}
    benchmark_execution_metrics: Dict[str, Dict[str, Optional[float]]] = {}
    benchmark_series = sorted(
        {
            str(series)
            for series in benchmark_metrics_df.get("series_name", pd.Series(dtype=str))
            .dropna()
            .tolist()
        }
    )
    for series_name in benchmark_series:
        benchmark_absolute_metrics[series_name] = {
            "total_return": benchmark_metric_lookup.get((series_name, "total_return")),
            "annualized_return": benchmark_metric_lookup.get((series_name, "annualized_return")),
            "gross_annualized_return": benchmark_metric_lookup.get(
                (series_name, "gross_annualized_return")
            ),
            "annualized_volatility": benchmark_metric_lookup.get(
                (series_name, "annualized_volatility")
            ),
            "max_drawdown": benchmark_metric_lookup.get((series_name, "max_drawdown")),
            "sharpe_ratio": benchmark_metric_lookup.get((series_name, "sharpe_ratio")),
            "sortino_ratio": benchmark_metric_lookup.get((series_name, "sortino_ratio")),
            "mar_ratio": (
                benchmark_metric_lookup.get((series_name, "mar_ratio"))
                if benchmark_metric_lookup.get((series_name, "mar_ratio")) is not None
                else benchmark_metric_lookup.get((series_name, "calmar_ratio"))
            ),
            "calmar_ratio": benchmark_metric_lookup.get((series_name, "calmar_ratio")),
            "hit_rate_positive_periods": (
                benchmark_metric_lookup.get((series_name, "hit_rate_positive_periods"))
                if benchmark_metric_lookup.get((series_name, "hit_rate_positive_periods"))
                is not None
                else benchmark_metric_lookup.get((series_name, "hit_rate"))
            ),
            "hit_rate": benchmark_metric_lookup.get((series_name, "hit_rate")),
        }
        benchmark_execution_metrics[series_name] = {
            "avg_monthly_turnover_one_way": benchmark_metric_lookup.get(
                (series_name, "avg_monthly_turnover_one_way")
            ),
            "avg_monthly_turnover_two_way": benchmark_metric_lookup.get(
                (series_name, "avg_monthly_turnover_two_way")
            ),
            "annualized_turnover_ratio_one_way": benchmark_metric_lookup.get(
                (series_name, "annualized_turnover_ratio_one_way")
            ),
            "annualized_turnover_ratio_two_way": benchmark_metric_lookup.get(
                (series_name, "annualized_turnover_ratio_two_way")
            ),
            "avg_transaction_cost_bps": benchmark_metric_lookup.get(
                (series_name, "avg_transaction_cost_bps")
            ),
            "total_cost_drag": benchmark_metric_lookup.get((series_name, "total_cost_drag")),
        }
    scorecard_passed = (
        _count_true_flags(scorecard_df["passed"])
        if not scorecard_df.empty and "passed" in scorecard_df.columns
        else None
    )
    scorecard_total = int(len(scorecard_df)) if not scorecard_df.empty else 0
    trade_blotter_row_count = int(len(trade_blotter_df)) if not trade_blotter_df.empty else 0
    scheduled_execution_row_count = (
        int(_scheduled_trade_mask(trade_blotter_df).sum()) if not trade_blotter_df.empty else 0
    )
    intraday_action_row_count = (
        int((trade_blotter_df["source_layer"] == "intraday_overlay").sum())
        if not trade_blotter_df.empty and "source_layer" in trade_blotter_df.columns
        else 0
    )
    liquidity_clipped_trade_rows = (
        _count_true_flags(trade_blotter_df["liquidity_clipped"])
        if not trade_blotter_df.empty and "liquidity_clipped" in trade_blotter_df.columns
        else 0
    )
    forward_filled_trade_rows = (
        _count_true_flags(trade_blotter_df["had_forward_fill"])
        if not trade_blotter_df.empty and "had_forward_fill" in trade_blotter_df.columns
        else 0
    )
    requested_turnover_series = (
        pd.to_numeric(performance_df["requested_turnover"], errors="coerce")
        if "requested_turnover" in performance_df.columns
        else pd.Series(dtype=float)
    )
    executed_turnover_series = (
        pd.to_numeric(performance_df["turnover"], errors="coerce")
        if "turnover" in performance_df.columns
        else pd.Series(dtype=float)
    )
    requested_gross_turnover_series = (
        pd.to_numeric(performance_df["gross_requested_turnover"], errors="coerce")
        if "gross_requested_turnover" in performance_df.columns
        else pd.Series(dtype=float)
    )
    executed_gross_turnover_series = (
        pd.to_numeric(performance_df["gross_turnover"], errors="coerce")
        if "gross_turnover" in performance_df.columns
        else pd.Series(dtype=float)
    )
    turnover_shortfall_series = (
        (requested_turnover_series - executed_turnover_series).clip(lower=0.0)
        if not requested_turnover_series.empty and not executed_turnover_series.empty
        else pd.Series(dtype=float)
    )
    unfilled_buy_series = (
        pd.to_numeric(performance_df["unfilled_buy_weight"], errors="coerce")
        if "unfilled_buy_weight" in performance_df.columns
        else pd.Series(dtype=float)
    )
    unfilled_sell_series = (
        pd.to_numeric(performance_df["unfilled_sell_weight"], errors="coerce")
        if "unfilled_sell_weight" in performance_df.columns
        else pd.Series(dtype=float)
    )
    unfilled_total_series = (
        unfilled_buy_series.fillna(0.0) + unfilled_sell_series.fillna(0.0)
        if not unfilled_buy_series.empty or not unfilled_sell_series.empty
        else pd.Series(dtype=float)
    )
    liquidity_clipped_periods = (
        _count_true_flags(performance_df["liquidity_clipped"])
        if "liquidity_clipped" in performance_df.columns
        else 0
    )
    forward_filled_symbol_series = (
        pd.to_numeric(performance_df["forward_filled_symbol_count"], errors="coerce")
        if "forward_filled_symbol_count" in performance_df.columns
        else pd.Series(dtype=float)
    )
    forward_fill_day_series = (
        pd.to_numeric(performance_df["forward_fill_day_count"], errors="coerce")
        if "forward_fill_day_count" in performance_df.columns
        else pd.Series(dtype=float)
    )
    forward_filled_periods = (
        int((forward_filled_symbol_series.fillna(0.0) > 0.0).sum())
        if not forward_filled_symbol_series.empty
        else 0
    )
    max_participation_series = (
        pd.to_numeric(performance_df["max_participation_used"], errors="coerce")
        if "max_participation_used" in performance_df.columns
        else pd.Series(dtype=float)
    )
    version_bundle = {
        key: value
        for key, value in {
            "model_version": run_row.get("model_version"),
            "factor_definition_version": run_row.get("factor_definition_version"),
            "covariance_method_version": run_row.get("covariance_method_version"),
            "risk_overlay_policy_version": run_row.get("risk_overlay_policy_version"),
            "backtest_engine_version": run_row.get("backtest_engine_version"),
        }.items()
        if value
    }
    run_config = _coerce_mapping(run_row.get("config_snapshot"))
    config_hash = str(run_row.get("config_hash") or "") or compute_config_hash(run_config or None)
    final_portfolio_nav = _safe_float(
        performance_df["portfolio_nav"].iloc[-1]
        if not performance_df.empty and "portfolio_nav" in performance_df.columns
        else None
    )
    final_benchmark_nav = _safe_float(
        performance_df["benchmark_nav"].iloc[-1]
        if not performance_df.empty and "benchmark_nav" in performance_df.columns
        else None
    )
    latest_materialized_dates = {
        "performance_period_end_date": _latest_iso_datetime(performance_df, "period_end_date"),
        "holdings_rebalance_date": _latest_iso_datetime(holdings_df, "rebalance_date"),
        "trade_blotter_trade_date": _latest_iso_datetime(trade_blotter_df, "trade_date"),
        "benchmark_nav_period_end_date": _latest_iso_datetime(benchmark_nav_df, "period_end_date"),
        "portfolio_snapshot_as_of_date": lineage_context.get("portfolio_as_of_date"),
        "feature_snapshot_as_of_date": lineage_context.get("feature_as_of_date"),
    }
    sample_rebalance_dates = _distinct_iso_dates(holdings_df, "rebalance_date", limit=10)
    sample_holdings = _sample_holdings_payload(holdings_df, limit=10)
    trade_blotter_hash_columns = [
        col
        for col in [
            "trade_date",
            "execution_date",
            "source_layer",
            "action_type",
            "symbol",
            "trade_side",
            "requested_trade_weight",
            "executed_trade_weight",
            "transaction_cost",
            "reason_code",
        ]
        if col in trade_blotter_df.columns
    ]
    holdings_hash_columns = [
        col
        for col in [
            "rebalance_date",
            "execution_date",
            "symbol",
            "target_weight",
            "executed_weight",
            "composite_alpha",
            "gics_sector",
        ]
        if col in holdings_df.columns
    ]
    benchmark_methodology = _build_benchmark_methodology(
        benchmark_ticker=str(run_row.get("benchmark_ticker") or "SPY"),
        primary_benchmark=primary_benchmark,
        secondary_benchmark=secondary_benchmark,
        analysis_cfg=analysis_cfg,
    )
    risk_model_methodology = _build_risk_model_methodology(config)
    uses_risk_free = False
    if not performance_df.empty and "risk_free_return" in performance_df.columns:
        rf_series = pd.to_numeric(performance_df["risk_free_return"], errors="coerce").dropna()
        uses_risk_free = not rf_series.empty and bool((rf_series.abs() > 0).any())
    sharpe_sortino_convention = (
        "us_treasury_3m_period_return" if uses_risk_free else "zero_risk_free_rate_legacy_fallback"
    )
    return {
        "contract_version": "cw2-report-summary-v2",
        "report_name": report_name,
        "report_id": report_id,
        "run_id": str(run_row["run_id"]),
        "run_name": str(run_row["run_name"]),
        "config_hash": config_hash or None,
        "snapshot_id": lineage_context.get("snapshot_id"),
        "portfolio_snapshot_id": lineage_context.get("portfolio_snapshot_id"),
        "portfolio_name": lineage_context.get("portfolio_name"),
        "requested_as_of_date": lineage_context.get("requested_as_of_date"),
        "feature_snapshot_status": lineage_context.get("feature_snapshot_status"),
        "portfolio_snapshot_status": lineage_context.get("portfolio_snapshot_status"),
        "lineage_window": dict(lineage_context.get("lineage_window") or {}),
        "source_table_row_counts": dict(lineage_context.get("source_table_row_counts") or {}),
        "latest_upstream_dates": dict(lineage_context.get("latest_upstream_dates") or {}),
        "start_date": str(run_row["start_date"]),
        "end_date": str(run_row["end_date"]),
        "rebalance_frequency": str(run_row.get("rebalance_freq") or "monthly"),
        "benchmark_ticker": str(run_row.get("benchmark_ticker") or "SPY"),
        "transaction_cost_bps": _safe_float(run_row.get("transaction_cost_bps")),
        "primary_benchmark": primary_benchmark,
        "secondary_benchmark": secondary_benchmark,
        "benchmark_methodology": benchmark_methodology,
        "risk_model_methodology": risk_model_methodology,
        "risk_metric_conventions": {
            "sharpe_ratio": sharpe_sortino_convention,
            "sortino_ratio": sharpe_sortino_convention,
            "mar_ratio": "annualized_return_divided_by_full_period_max_drawdown",
            "strategy_hit_rate": "share_of_periods_strategy_return_exceeded_benchmark_ticker_return",
            "information_ratio": "arithmetic_annualized_mean_excess_return_divided_by_annualized_tracking_error",
            "beta_raw": "covariance_of_raw_strategy_and_benchmark_returns_divided_by_benchmark_return_variance",
            "beta_raw_purpose": "descriptive_benchmark_sensitivity_indicator_used_to_summarize_raw_return_co_movement_and_market_exposure_not_a_capm_pricing_parameter",
        },
        "risk_free_series_name": "us_treasury_3m" if uses_risk_free else None,
        "risk_free_return_method": (
            "daily_forward_filled_calendar_day_compounding_from_annualized_percent_yield"
            if uses_risk_free
            else "not_used"
        ),
        "periods": int(len(performance_df)),
        "analysis_available": _analysis_inputs_present(
            benchmark_nav_df=benchmark_nav_df,
            benchmark_metrics_df=benchmark_metrics_df,
            relative_metrics_df=relative_metrics_df,
            scorecard_df=scorecard_df,
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version_bundle": version_bundle,
        "latest_materialized_dates": latest_materialized_dates,
        "sample_rebalance_dates": sample_rebalance_dates,
        "sample_holdings": sample_holdings,
        "holdings_head_hash": _hash_frame_rows(
            holdings_df,
            columns=holdings_hash_columns,
            limit=10,
        ),
        "trade_blotter_head_hash": _hash_frame_rows(
            trade_blotter_df,
            columns=trade_blotter_hash_columns,
            limit=10,
        ),
        "trade_blotter_full_hash": _hash_frame_rows(
            trade_blotter_df,
            columns=trade_blotter_hash_columns,
        ),
        "final_portfolio_nav": final_portfolio_nav,
        "final_benchmark_nav": final_benchmark_nav,
        "total_return": metric_lookup.get(("return", "total_return")),
        "annualized_return": metric_lookup.get(("return", "annualized_return")),
        "gross_annualized_return": metric_lookup.get(("return", "gross_annualized_return")),
        "benchmark_total_return": metric_lookup.get(("return", "benchmark_total_return")),
        "annualized_volatility": metric_lookup.get(("risk", "annualized_volatility")),
        "max_drawdown": metric_lookup.get(("risk", "max_drawdown")),
        "beta_raw": (
            metric_lookup.get(("risk", "beta_raw"))
            if metric_lookup.get(("risk", "beta_raw")) is not None
            else metric_lookup.get(("risk", "beta"))
        ),
        "beta": (
            metric_lookup.get(("risk", "beta"))
            if metric_lookup.get(("risk", "beta")) is not None
            else metric_lookup.get(("risk", "beta_raw"))
        ),
        "sharpe_ratio": metric_lookup.get(("risk_adjusted", "sharpe_ratio")),
        "mar_ratio": (
            metric_lookup.get(("risk_adjusted", "mar_ratio"))
            if metric_lookup.get(("risk_adjusted", "mar_ratio")) is not None
            else metric_lookup.get(("risk_adjusted", "calmar_ratio"))
        ),
        "calmar_ratio": (
            metric_lookup.get(("risk_adjusted", "calmar_ratio"))
            if metric_lookup.get(("risk_adjusted", "calmar_ratio")) is not None
            else metric_lookup.get(("risk_adjusted", "mar_ratio"))
        ),
        "hit_rate_vs_benchmark_ticker": (
            metric_lookup.get(("risk_adjusted", "hit_rate_vs_benchmark_ticker"))
            if metric_lookup.get(("risk_adjusted", "hit_rate_vs_benchmark_ticker")) is not None
            else metric_lookup.get(("risk_adjusted", "hit_rate"))
        ),
        "hit_rate": (
            metric_lookup.get(("risk_adjusted", "hit_rate"))
            if metric_lookup.get(("risk_adjusted", "hit_rate")) is not None
            else metric_lookup.get(("risk_adjusted", "hit_rate_vs_benchmark_ticker"))
        ),
        "information_ratio_vs_primary": relative_lookup.get(
            (primary_benchmark, "information_ratio")
        ),
        "excess_return_vs_primary": relative_lookup.get(
            (primary_benchmark, "excess_return_annualized")
        ),
        "benchmark_absolute_metrics": benchmark_absolute_metrics,
        "benchmark_execution_metrics": benchmark_execution_metrics,
        "avg_monthly_turnover_one_way": (
            metric_lookup.get(("portfolio", "avg_monthly_turnover_one_way"))
            if metric_lookup.get(("portfolio", "avg_monthly_turnover_one_way")) is not None
            else metric_lookup.get(("portfolio", "avg_monthly_turnover"))
        ),
        "avg_monthly_turnover": (
            metric_lookup.get(("portfolio", "avg_monthly_turnover"))
            if metric_lookup.get(("portfolio", "avg_monthly_turnover")) is not None
            else metric_lookup.get(("portfolio", "avg_monthly_turnover_one_way"))
        ),
        "annualized_turnover_ratio_one_way": (
            metric_lookup.get(("portfolio", "annualized_turnover_ratio_one_way"))
            if metric_lookup.get(("portfolio", "annualized_turnover_ratio_one_way")) is not None
            else metric_lookup.get(("portfolio", "annualized_turnover_ratio"))
        ),
        "annualized_turnover_ratio": (
            metric_lookup.get(("portfolio", "annualized_turnover_ratio"))
            if metric_lookup.get(("portfolio", "annualized_turnover_ratio")) is not None
            else metric_lookup.get(("portfolio", "annualized_turnover_ratio_one_way"))
        ),
        "avg_monthly_turnover_two_way": (
            metric_lookup.get(("portfolio", "avg_monthly_turnover_two_way"))
            if metric_lookup.get(("portfolio", "avg_monthly_turnover_two_way")) is not None
            else metric_lookup.get(("portfolio", "avg_monthly_gross_turnover"))
        ),
        "avg_monthly_gross_turnover": (
            metric_lookup.get(("portfolio", "avg_monthly_gross_turnover"))
            if metric_lookup.get(("portfolio", "avg_monthly_gross_turnover")) is not None
            else metric_lookup.get(("portfolio", "avg_monthly_turnover_two_way"))
        ),
        "annualized_turnover_ratio_two_way": metric_lookup.get(
            ("portfolio", "annualized_turnover_ratio_two_way")
        ),
        "avg_requested_turnover": _pct_points(_safe_float(requested_turnover_series.mean())),
        "avg_executed_turnover": _pct_points(_safe_float(executed_turnover_series.mean())),
        "avg_requested_gross_turnover": _pct_points(
            _safe_float(requested_gross_turnover_series.mean())
        ),
        "avg_executed_gross_turnover": _pct_points(
            _safe_float(executed_gross_turnover_series.mean())
        ),
        "avg_turnover_shortfall": _pct_points(_safe_float(turnover_shortfall_series.mean())),
        "avg_unfilled_buy_weight": _pct_points(_safe_float(unfilled_buy_series.mean())),
        "avg_unfilled_sell_weight": _pct_points(_safe_float(unfilled_sell_series.mean())),
        "max_unfilled_total_weight": _pct_points(_safe_float(unfilled_total_series.max())),
        "avg_max_participation_used": _pct_points(_safe_float(max_participation_series.mean())),
        "liquidity_clipped_periods": liquidity_clipped_periods,
        "liquidity_clipped_trade_rows": liquidity_clipped_trade_rows,
        "forward_filled_periods": forward_filled_periods,
        "forward_filled_symbol_total": (
            int(forward_filled_symbol_series.fillna(0.0).sum())
            if not forward_filled_symbol_series.empty
            else 0
        ),
        "forward_fill_day_total": (
            int(forward_fill_day_series.fillna(0.0).sum())
            if not forward_fill_day_series.empty
            else 0
        ),
        "forward_filled_trade_rows": forward_filled_trade_rows,
        "scorecard_passed": scorecard_passed,
        "scorecard_total": scorecard_total,
        "chart_count": len(chart_paths),
        "trade_blotter_row_count": trade_blotter_row_count,
        "scheduled_execution_row_count": scheduled_execution_row_count,
        "intraday_action_row_count": intraday_action_row_count,
        "holdings_row_count": int(len(holdings_df)) if not holdings_df.empty else 0,
    }


def _analysis_inputs_present(
    *,
    benchmark_nav_df: pd.DataFrame,
    benchmark_metrics_df: pd.DataFrame,
    relative_metrics_df: pd.DataFrame,
    scorecard_df: pd.DataFrame,
) -> bool:
    return any(
        not df.empty
        for df in (
            benchmark_nav_df,
            benchmark_metrics_df,
            relative_metrics_df,
            scorecard_df,
        )
    )


def _build_benchmark_methodology(
    *,
    benchmark_ticker: str,
    primary_benchmark: str,
    secondary_benchmark: str,
    analysis_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Return report-facing benchmark roles and cost treatments.

    The methodology mirrors the analysis contract: the configured primary
    benchmark is the external market reference (SPY in the formal configuration),
    universe_ew is a gross opportunity-set comparison, and static_baseline is a
    net-of-cost tradable construction-layer control.
    """
    universe_ew_deduct_cost = bool(analysis_cfg.get("universe_ew_deduct_cost", False))
    static_baseline_cost_bps = _safe_float(analysis_cfg.get("static_baseline_cost_bps"))
    universe_cost = (
        "net_of_configured_trading_costs" if universe_ew_deduct_cost else "gross_of_trading_costs"
    )

    def describe(series_name: str) -> tuple[str, str]:
        if series_name == benchmark_ticker:
            return (
                f"{benchmark_ticker} buy-and-hold market benchmark path from the stored backtest benchmark series",
                "no_strategy_execution_cost_model",
            )
        if series_name == "universe_ew":
            return (
                "dynamic equal-weight comparison over the investable universe at each backtest period",
                universe_cost,
            )
        if series_name == "static_baseline":
            return (
                "static normal-weight baseline built on the same CW2 factor stack and reconstituted each period",
                "net_of_configured_trading_costs",
            )
        return ("additional benchmark or comparison series", "series_specific")

    primary_description, primary_cost = describe(primary_benchmark)
    secondary_description, secondary_cost = describe(secondary_benchmark)
    return {
        "secondary_benchmark": {
            "series_name": secondary_benchmark,
            "description": secondary_description,
            "cost_treatment": secondary_cost,
        },
        "primary_benchmark": {
            "series_name": primary_benchmark,
            "description": primary_description,
            "cost_treatment": primary_cost,
        },
        "static_baseline": {
            "series_name": "static_baseline",
            "description": "static normal-weight baseline built on the same CW2 factor stack and reconstituted each period",
            "cost_treatment": "net_of_configured_trading_costs",
            "configured_cost_bps": static_baseline_cost_bps,
            "execution_metrics_reported_separately": True,
        },
    }


def _build_risk_model_methodology(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return report-facing covariance risk model settings."""

    portfolio_cfg = _coerce_mapping(config.get("portfolio"))
    covariance_cfg = _coerce_mapping(portfolio_cfg.get("covariance"))
    backtest_cfg = _coerce_mapping(config.get("backtest"))
    analysis_cfg = _coerce_mapping(backtest_cfg.get("analysis"))
    analysis_covariance_cfg = _coerce_mapping(analysis_cfg.get("covariance"))
    method = str(covariance_cfg.get("method") or "n/a")
    style_factors = covariance_cfg.get("style_factors") or []
    if not isinstance(style_factors, list):
        style_factors = []
    return {
        "portfolio_covariance_method": method,
        "analysis_covariance_method": str(analysis_covariance_cfg.get("method") or method),
        "model_type": (
            "fundamental_factor_covariance" if method == "fundamental_factor" else method
        ),
        "formula": "Sigma = X F X' + D",
        "style_factors": [str(item) for item in style_factors],
        "include_sector_factors": bool(covariance_cfg.get("include_sector_factors", False)),
        "factor_cov_shrinkage": _safe_float(covariance_cfg.get("factor_cov_shrinkage")),
        "specific_variance_floor_ratio": _safe_float(
            covariance_cfg.get("specific_variance_floor_ratio")
        ),
        "annualize_covariance": bool(covariance_cfg.get("annualize_covariance", True)),
        "risk_aversion": _safe_float(covariance_cfg.get("risk_aversion")),
    }


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _date_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    return raw[:10] if raw else None


def _latest_iso_datetime(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    series = pd.to_datetime(frame[column], errors="coerce")
    latest = series.max()
    if pd.isna(latest):
        return None
    return latest.date().isoformat()


def _distinct_iso_dates(frame: pd.DataFrame, column: str, *, limit: int) -> List[str]:
    if frame.empty or column not in frame.columns or limit <= 0:
        return []
    series = pd.to_datetime(frame[column], errors="coerce").dropna()
    unique_dates = sorted({value.date().isoformat() for value in series})
    return unique_dates[:limit]


def _sample_holdings_payload(frame: pd.DataFrame, *, limit: int) -> List[Dict[str, Any]]:
    if frame.empty or limit <= 0:
        return []
    columns = [
        col
        for col in [
            "rebalance_date",
            "execution_date",
            "symbol",
            "target_weight",
            "executed_weight",
            "composite_alpha",
            "gics_sector",
        ]
        if col in frame.columns
    ]
    if not columns:
        return []
    sample = frame[columns].head(limit).copy()
    return [_normalize_hash_value(record) for record in sample.to_dict(orient="records")]


def _hash_frame_rows(
    frame: pd.DataFrame, *, columns: Sequence[str], limit: int | None = None
) -> str | None:
    if frame.empty or not columns:
        return None
    sample = frame.loc[:, list(columns)]
    if limit is not None:
        sample = sample.head(limit)
    records = sample.to_dict(orient="records")
    normalized = [_normalize_hash_value(record) for record in records]
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_hash_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_hash_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_hash_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return _normalize_hash_value(value.item())
        except Exception:
            return str(value)
    return value


def _count_true_flags(series: pd.Series) -> int:
    values = (
        series.astype("boolean")
        if str(series.dtype) == "boolean"
        else pd.Series(series, copy=False).map(_to_bool_or_none).astype("boolean")
    )
    return int(values.fillna(False).sum())


def _to_bool_or_none(value: Any) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text_value = str(value).strip().lower()
    if text_value in {"true", "t", "1", "yes", "y"}:
        return True
    if text_value in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _build_report_markdown(
    *,
    summary: Dict[str, Any],
    metrics_df: pd.DataFrame,
    benchmark_metrics_df: pd.DataFrame,
    relative_metrics_df: pd.DataFrame,
    scorecard_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    trade_blotter_df: pd.DataFrame,
    chart_paths: Dict[str, str],
    root_dir: Path,
    trade_blotter_path: Path | None,
) -> str:
    lines = [
        f"# CW2 Backtest Report: {summary['report_name']}",
        "",
        "## Overview",
        f"- Run ID: `{summary['run_id']}`",
        f"- Backtest run name: `{summary['run_name']}`",
        f"- Window: `{summary['start_date']}` to `{summary['end_date']}`",
        f"- Rebalance frequency: `{summary['rebalance_frequency']}`",
        f"- Benchmark ticker: `{summary['benchmark_ticker']}`",
        f"- Primary benchmark for analysis: `{summary['primary_benchmark']}`",
        f"- Transaction cost assumption (all-in): `{_fmt_bps(summary.get('transaction_cost_bps'))}`",
        f"- Model version: `{summary.get('version_bundle', {}).get('model_version', 'n/a')}`",
        f"- Backtest engine version: `{summary.get('version_bundle', {}).get('backtest_engine_version', 'n/a')}`",
        f"- Reporting version: `{summary.get('version_bundle', {}).get('reporting_version', 'n/a')}`",
        f"- Generated at: `{summary['generated_at']}`",
        "",
        "## Performance Snapshot",
        f"- Total return: {_fmt_pct(summary.get('total_return'))}",
        f"- Annualized return: {_fmt_pct(summary.get('annualized_return'))}",
        f"- Gross annualized return: {_fmt_pct(summary.get('gross_annualized_return'))}",
        f"- Annualized volatility: {_fmt_pct(summary.get('annualized_volatility'))}",
        f"- Max drawdown: {_fmt_pct(summary.get('max_drawdown'))}",
        f"- Sharpe ratio: {_fmt_num(summary.get('sharpe_ratio'))}",
        f"- MAR ratio (full-period max drawdown): {_fmt_num(summary.get('mar_ratio'))}",
        f"- Excess annualized return vs primary benchmark: {_fmt_pct(summary.get('excess_return_vs_primary'))}",
        f"- Information ratio vs primary benchmark: {_fmt_num(summary.get('information_ratio_vs_primary'))}",
        f"- Hit rate vs benchmark ticker: {_fmt_pct(summary.get('hit_rate_vs_benchmark_ticker'))}",
        f"- Average monthly turnover ratio (one-way): {_fmt_pct(summary.get('avg_monthly_turnover_one_way'))}",
        f"- Average monthly turnover ratio (two-way): {_fmt_pct(summary.get('avg_monthly_turnover_two_way'))}",
        f"- Annualized turnover ratio (one-way): {_fmt_pct(summary.get('annualized_turnover_ratio_one_way'))}",
        f"- Raw beta vs benchmark ticker: {_fmt_num(summary.get('beta_raw'))}",
        "",
        "## Execution Realism",
        f"- Average requested turnover ratio (one-way): {_fmt_pct(summary.get('avg_requested_turnover'))}",
        f"- Average executed turnover ratio (one-way): {_fmt_pct(summary.get('avg_executed_turnover'))}",
        f"- Average requested traded weight (two-way): {_fmt_pct(summary.get('avg_requested_gross_turnover'))}",
        f"- Average executed traded weight (two-way): {_fmt_pct(summary.get('avg_executed_gross_turnover'))}",
        f"- Average turnover shortfall from clipping: {_fmt_pct(summary.get('avg_turnover_shortfall'))}",
        f"- Liquidity-clipped periods: `{summary.get('liquidity_clipped_periods', 0)}`",
        f"- Average unfilled buy weight: {_fmt_pct(summary.get('avg_unfilled_buy_weight'))}",
        f"- Average unfilled sell weight: {_fmt_pct(summary.get('avg_unfilled_sell_weight'))}",
        f"- Max total unfilled weight in a period: {_fmt_pct(summary.get('max_unfilled_total_weight'))}",
        f"- Average max participation used: {_fmt_pct(summary.get('avg_max_participation_used'))}",
        f"- Forward-filled periods: `{summary.get('forward_filled_periods', 0)}`",
        f"- Forward-filled symbol observations: `{summary.get('forward_filled_symbol_total', 0)}`",
        f"- Forward-filled symbol-days: `{summary.get('forward_fill_day_total', 0)}`",
        "",
        "## Trade Blotter",
        f"- Unified trade blotter rows: `{summary.get('trade_blotter_row_count', 0)}`",
        f"- Scheduled execution rows: `{summary.get('scheduled_execution_row_count', 0)}`",
        f"- Intraday action rows: `{summary.get('intraday_action_row_count', 0)}`",
        f"- Liquidity-clipped blotter rows: `{summary.get('liquidity_clipped_trade_rows', 0)}`",
        f"- Forward-filled blotter rows: `{summary.get('forward_filled_trade_rows', 0)}`",
        (
            f"- Full CSV artifact: `{trade_blotter_path.resolve().relative_to(root_dir.resolve()).as_posix()}`"
            if trade_blotter_path is not None
            else "- Full CSV artifact: `n/a`"
        ),
        "",
        "Turnover convention:",
        "Reported turnover uses the common one-way ratio (0.5 * sum of absolute weight changes). Two-way traded weight is also shown as the full sum of absolute weight changes.",
        "",
        "## Benchmark Construction Notes",
        f"- `{summary.get('primary_benchmark')}` is the primary benchmark for analysis; cost treatment is `{summary.get('benchmark_methodology', {}).get('primary_benchmark', {}).get('cost_treatment', 'n/a')}`.",
        f"- `{summary.get('secondary_benchmark')}` is retained as an additional comparison series; cost treatment is `{summary.get('benchmark_methodology', {}).get('secondary_benchmark', {}).get('cost_treatment', 'n/a')}`.",
        f"- `static_baseline` is rebuilt on the same CW2 factor stack and is net of configured trading costs (`{_fmt_bps(summary.get('benchmark_methodology', {}).get('static_baseline', {}).get('configured_cost_bps'))}`); benchmark execution metrics are shown separately when available.",
        (
            "- Sharpe and Sortino ratios are reported relative to period-aligned `us_treasury_3m` risk-free returns, compounded across each holding window from the daily annualized yield series."
            if summary.get("risk_free_series_name")
            else "- Sharpe and Sortino ratios fall back to a zero risk-free-rate basis for legacy runs without stored risk-free period returns."
        ),
        "- Information ratio is reported as arithmetic annualized mean excess return divided by annualized tracking error.",
        "- `beta_raw` is reported as covariance beta on raw strategy and benchmark returns; risk-free rate is not subtracted.",
        "- `beta_raw` is retained as a descriptive exposure metric for how strongly strategy returns co-move with the benchmark ticker, which helps interpret market sensitivity in volatility and drawdown terms; it is not intended as a CAPM pricing parameter.",
        "- `MAR ratio` is reported as annualized return divided by full-period maximum drawdown; report readers still accept legacy `calmar_ratio` rows from older runs as a backward-compatible fallback.",
        "",
        "## Portfolio Risk Model Notes",
        f"- Portfolio covariance method: `{summary.get('risk_model_methodology', {}).get('portfolio_covariance_method', 'n/a')}`.",
        f"- Analysis covariance method: `{summary.get('risk_model_methodology', {}).get('analysis_covariance_method', 'n/a')}`.",
        f"- Factor covariance form: `{summary.get('risk_model_methodology', {}).get('formula', 'n/a')}`.",
        f"- Style exposures: `{', '.join(summary.get('risk_model_methodology', {}).get('style_factors') or []) or 'n/a'}`.",
        f"- Sector exposures included: `{summary.get('risk_model_methodology', {}).get('include_sector_factors', 'n/a')}`.",
        "- This covariance model is the optimizer's risk model. It is separate from the five composite-alpha factor groups and is used to estimate shared systematic risk across holdings.",
        "",
        "## Charts",
    ]
    for name, path_str in chart_paths.items():
        rel = _resolve_artifact_path(path_str).resolve().relative_to(root_dir.resolve())
        lines.extend(
            [
                f"### {name.replace('_', ' ').title()}",
                f"![{name}]({rel.as_posix()})",
                "",
            ]
        )

    lines.extend(
        [
            "## Metrics Table",
            "",
            "| Group | Metric | Value | Unit |",
            "|---|---|---:|---|",
        ]
    )
    deprecated_metric_aliases = {
        ("risk_adjusted", "calmar_ratio"): ("risk_adjusted", "mar_ratio"),
        ("risk_adjusted", "hit_rate"): (
            "risk_adjusted",
            "hit_rate_vs_benchmark_ticker",
        ),
        ("risk", "beta"): ("risk", "beta_raw"),
        ("portfolio", "avg_monthly_turnover"): (
            "portfolio",
            "avg_monthly_turnover_one_way",
        ),
        ("portfolio", "annualized_turnover_ratio"): (
            "portfolio",
            "annualized_turnover_ratio_one_way",
        ),
        ("portfolio", "avg_monthly_gross_turnover"): (
            "portfolio",
            "avg_monthly_turnover_two_way",
        ),
    }
    metric_pairs_present = {
        (str(row.get("metric_group")), str(row.get("metric_name")))
        for _, row in metrics_df.iterrows()
    }
    for _, row in metrics_df.iterrows():
        pair = (str(row.get("metric_group")), str(row.get("metric_name")))
        if (
            pair in deprecated_metric_aliases
            and deprecated_metric_aliases[pair] in metric_pairs_present
        ):
            continue
        lines.append(
            f"| {row.get('metric_group')} | {row.get('metric_name')} | {_fmt_metric_value(row.get('metric_value'), row.get('metric_unit'))} | {row.get('metric_unit') or '-'} |"
        )

    if not benchmark_metrics_df.empty:
        lines.extend(
            [
                "",
                "## Benchmark Absolute Metrics",
                "",
                "| Series | Total Return | Ann Return | Ann Vol | Max Drawdown | Sharpe | Sortino | MAR |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        metric_lookup = {
            (str(row["series_name"]), str(row["metric_name"])): (
                row.get("metric_value"),
                row.get("metric_unit"),
            )
            for _, row in benchmark_metrics_df.iterrows()
        }
        series_names = sorted(
            {str(series) for series in benchmark_metrics_df["series_name"].dropna().tolist()}
        )
        for series_name in series_names:
            lines.append(
                "| "
                + " | ".join(
                    [
                        series_name,
                        _fmt_metric_value(
                            *metric_lookup.get((series_name, "total_return"), (None, "%"))
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get((series_name, "annualized_return"), (None, "%"))
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get((series_name, "annualized_volatility"), (None, "%"))
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get((series_name, "max_drawdown"), (None, "%"))
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get((series_name, "sharpe_ratio"), (None, "x"))
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get((series_name, "sortino_ratio"), (None, "x"))
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get(
                                (series_name, "mar_ratio"),
                                metric_lookup.get((series_name, "calmar_ratio"), (None, "x")),
                            )
                        ),
                    ]
                )
                + " |"
            )

        lines.extend(
            [
                "",
                "## Benchmark Execution Metrics",
                "",
                "| Series | Avg Turnover (One-Way) | Avg Turnover (Two-Way) | Annualized Turnover (One-Way) | Avg Transaction Cost | Total Cost Drag |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for series_name in series_names:
            lines.append(
                "| "
                + " | ".join(
                    [
                        series_name,
                        _fmt_metric_value(
                            *metric_lookup.get(
                                (series_name, "avg_monthly_turnover_one_way"),
                                (None, "%"),
                            )
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get(
                                (series_name, "avg_monthly_turnover_two_way"),
                                (None, "%"),
                            )
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get(
                                (series_name, "annualized_turnover_ratio_one_way"),
                                (None, "%"),
                            )
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get(
                                (series_name, "avg_transaction_cost_bps"),
                                (None, "bps"),
                            )
                        ),
                        _fmt_metric_value(
                            *metric_lookup.get(
                                (series_name, "total_cost_drag"),
                                (None, "%"),
                            )
                        ),
                    ]
                )
                + " |"
            )

    if not relative_metrics_df.empty:
        lines.extend(
            [
                "",
                "## Relative Metrics",
                "",
                "| Versus | Metric | Value | Unit |",
                "|---|---|---:|---|",
            ]
        )
        for _, row in relative_metrics_df.iterrows():
            lines.append(
                f"| {row.get('versus_series')} | {row.get('metric_name')} | {_fmt_metric_value(row.get('metric_value'), row.get('metric_unit'))} | {row.get('metric_unit') or '-'} |"
            )

    if not regime_df.empty:
        _append_regime_attribution_tables(
            lines,
            regime_df,
            primary_benchmark=str(summary.get("primary_benchmark") or _DEFAULT_PRIMARY_BENCHMARK),
            secondary_benchmark=str(summary.get("secondary_benchmark") or "universe_ew"),
        )

    if not scorecard_df.empty:
        lines.extend(
            [
                "",
                "## Scorecard",
                "",
                "| Criterion | Passed | Evidence |",
                "|---|---|---|",
            ]
        )
        for _, row in scorecard_df.iterrows():
            evidence = row.get("evidence")
            if isinstance(evidence, str):
                evidence_text = evidence
            else:
                evidence_text = json.dumps(evidence, sort_keys=True)
            lines.append(
                f"| {row.get('criterion_name')} | {row.get('passed')} | `{evidence_text}` |"
            )

    if not trade_blotter_df.empty:
        preview_cols = [
            col
            for col in [
                "trade_date",
                "source_layer",
                "action_type",
                "symbol",
                "trade_side",
                "weight_before",
                "weight_after",
                "requested_trade_weight",
                "executed_trade_weight",
                "unfilled_weight",
                "liquidity_clipped",
                "had_forward_fill",
                "forward_fill_days",
                "transaction_cost",
                "reason_code",
            ]
            if col in trade_blotter_df.columns
        ]
        preview_df = trade_blotter_df.loc[:, preview_cols].head(20).copy()
        lines.extend(
            [
                "",
                "## Trade Blotter Preview",
                "",
                "| "
                + " | ".join(col.replace("_", " ").title() for col in preview_df.columns)
                + " |",
                "|" + "|".join(["---"] * len(preview_df.columns)) + "|",
            ]
        )
        for _, row in preview_df.iterrows():
            values = [_fmt_trade_blotter_cell(row.get(col)) for col in preview_df.columns]
            lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines) + "\n"


def _fmt_trade_blotter_cell(value: Any) -> str:
    if pd.isna(value):
        return "-"
    if isinstance(value, (pd.Timestamp, datetime)):
        return str(value.date())
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _artifact_record(name: str, role: str, path: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "artifact_name": name,
        "artifact_role": role,
        "artifact_format": path.suffix.lstrip("."),
        "artifact_path": str(path),
        "artifact_metadata": metadata,
    }


def _upsert_report_header(
    engine: Engine,
    *,
    run_id: str,
    report_name: str,
    output_dir: str,
    run_row: Dict[str, Any],
    config: Dict[str, Any],
    summary: Dict[str, Any],
) -> str:
    payload = _build_report_header_payload(
        run_id=run_id,
        report_name=report_name,
        output_dir=output_dir,
        run_row=run_row,
        config=config,
        summary=summary,
    )
    sql = text("""
        INSERT INTO systematic_equity.backtest_reports (
            report_id,
            run_id,
            report_name,
            report_type,
            report_status,
            output_dir,
            model_version,
            factor_definition_version,
            covariance_method_version,
            risk_overlay_policy_version,
            backtest_engine_version,
            reporting_version,
            config_snapshot,
            summary_json,
            created_at,
            updated_at
        )
        VALUES (
            :report_id,
            :run_id,
            :report_name,
            'performance_summary',
            'generated',
            :output_dir,
            :model_version,
            :factor_definition_version,
            :covariance_method_version,
            :risk_overlay_policy_version,
            :backtest_engine_version,
            :reporting_version,
            CAST(:config_snapshot AS JSONB),
            CAST(:summary_json AS JSONB),
            :created_at,
            :updated_at
        )
        ON CONFLICT (run_id, report_name)
        DO UPDATE SET
            report_status = EXCLUDED.report_status,
            output_dir = EXCLUDED.output_dir,
            model_version = EXCLUDED.model_version,
            factor_definition_version = EXCLUDED.factor_definition_version,
            covariance_method_version = EXCLUDED.covariance_method_version,
            risk_overlay_policy_version = EXCLUDED.risk_overlay_policy_version,
            backtest_engine_version = EXCLUDED.backtest_engine_version,
            reporting_version = EXCLUDED.reporting_version,
            config_snapshot = EXCLUDED.config_snapshot,
            summary_json = EXCLUDED.summary_json,
            updated_at = EXCLUDED.updated_at
        RETURNING report_id
        """)
    with engine.begin() as conn:
        row = conn.execute(sql, payload).mappings().first()
    return str(row["report_id"])


def _build_report_header_payload(
    *,
    run_id: str,
    report_name: str,
    output_dir: str,
    run_row: Dict[str, Any],
    config: Dict[str, Any],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    report_id = str(uuid.uuid4())
    version_bundle = select_version_fields(resolve_version_bundle(config), REPORTING_VERSION_KEYS)
    inherited_versions = {
        "model_version": run_row.get("model_version"),
        "factor_definition_version": run_row.get("factor_definition_version"),
        "covariance_method_version": run_row.get("covariance_method_version"),
        "risk_overlay_policy_version": run_row.get("risk_overlay_policy_version"),
        "backtest_engine_version": run_row.get("backtest_engine_version"),
    }
    resolved_versions = {
        key: str(inherited_versions.get(key) or version_bundle.get(key))
        for key in REPORTING_VERSION_KEYS
        if inherited_versions.get(key) or version_bundle.get(key)
    }
    return {
        "report_id": report_id,
        "run_id": run_id,
        "report_name": report_name,
        "output_dir": output_dir,
        **resolved_versions,
        "config_snapshot": json.dumps(
            {
                "reporting": dict(config.get("reporting") or {}),
                "governance": {"versions": resolved_versions},
            },
            sort_keys=True,
        ),
        "summary_json": json.dumps(summary, sort_keys=True),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _replace_report_artifacts(
    engine: Engine,
    *,
    report_id: str,
    run_id: str,
    artifacts: Sequence[Dict[str, Any]],
) -> None:
    delete_sql = text("""
        DELETE FROM systematic_equity.backtest_report_artifacts
        WHERE report_id = :report_id
        """)
    insert_sql = text("""
        INSERT INTO systematic_equity.backtest_report_artifacts (
            report_id,
            run_id,
            artifact_name,
            artifact_role,
            artifact_format,
            artifact_path,
            artifact_metadata,
            created_at
        )
        VALUES (
            :report_id,
            :run_id,
            :artifact_name,
            :artifact_role,
            :artifact_format,
            :artifact_path,
            CAST(:artifact_metadata AS JSONB),
            :created_at
        )
        """)
    with engine.begin() as conn:
        conn.execute(delete_sql, {"report_id": report_id})
        for artifact in artifacts:
            conn.execute(
                insert_sql,
                {
                    "report_id": report_id,
                    "run_id": run_id,
                    "artifact_name": artifact["artifact_name"],
                    "artifact_role": artifact["artifact_role"],
                    "artifact_format": artifact["artifact_format"],
                    "artifact_path": artifact["artifact_path"],
                    "artifact_metadata": json.dumps(
                        artifact.get("artifact_metadata") or {}, sort_keys=True
                    ),
                    "created_at": datetime.now(timezone.utc),
                },
            )


def _append_regime_attribution_tables(
    lines: List[str],
    regime_df: pd.DataFrame,
    *,
    primary_benchmark: str,
    secondary_benchmark: str,
) -> None:
    df = regime_df.copy()
    if df.empty:
        return

    df["regime"] = df["regime"].astype(str)
    df["versus_series"] = df["versus_series"].astype(str)
    numeric_cols = [
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
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    regime_order = {"all": 0, "normal": 1, "stress": 2}
    preferred_versus = list(
        dict.fromkeys(
            [
                primary_benchmark,
                secondary_benchmark,
                "static_baseline",
                *sorted(df["versus_series"].dropna().unique().tolist()),
            ]
        )
    )
    versus_order = {name: idx for idx, name in enumerate(preferred_versus)}
    df["_regime_order"] = df["regime"].str.lower().map(regime_order).fillna(99)
    df["_versus_order"] = df["versus_series"].map(versus_order).fillna(99)
    df = df.sort_values(["_regime_order", "_versus_order", "versus_series"])

    lines.extend(
        [
            "",
            "## Backtest Regime Attribution Table",
            "",
            "Rows in this table are generated directly from `systematic_equity.backtest_regime_attribution`. The regime buckets are post-hoc VIX-based market-state labels used for attribution analysis.",
            "",
            "| Regime | Versus | N | Strategy Ann Return | Versus Ann Return | Excess Ann Return | Strategy Ann Vol | Versus Ann Vol | Strategy Sharpe | Versus Sharpe | Strategy MDD | Versus MDD | Hit Rate |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for _, row in df.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("regime")),
                    str(row.get("versus_series")),
                    _fmt_int(row.get("n_periods")),
                    _fmt_pct(row.get("strategy_ann_return")),
                    _fmt_pct(row.get("versus_ann_return")),
                    _fmt_pct(row.get("excess_ann_return")),
                    _fmt_pct(row.get("strategy_ann_vol")),
                    _fmt_pct(row.get("versus_ann_vol")),
                    _fmt_num(row.get("strategy_sharpe")),
                    _fmt_num(row.get("versus_sharpe")),
                    _fmt_pct(row.get("strategy_max_dd")),
                    _fmt_pct(row.get("versus_max_dd")),
                    _fmt_pct(row.get("hit_rate")),
                ]
            )
            + " |"
        )

    market_state_headers = [
        "Market State",
        "N",
        "Strategy Ann Return",
        "Strategy Sharpe",
        "Strategy MDD",
    ]
    for versus in preferred_versus:
        market_state_headers.extend([f"Excess vs {versus}", f"Hit vs {versus}"])
    market_state_alignment = [
        "---",
        "---:",
        "---:",
        "---:",
        "---:",
        *["---:" for _ in preferred_versus for _ in range(2)],
    ]

    lines.extend(
        [
            "",
            "## Post-Hoc Market-State Attribution Summary",
            "",
            "This summary pivots the same attribution output into one row per market state, so the period distribution and benchmark-relative results can be read directly.",
            "",
            "| " + " | ".join(market_state_headers) + " |",
            "| " + " | ".join(market_state_alignment) + " |",
        ]
    )
    for regime in ["all", "normal", "stress"]:
        state_rows = df.loc[df["regime"].str.lower() == regime]
        if state_rows.empty:
            continue
        first = state_rows.iloc[0]
        cells = [
            regime,
            _fmt_int(first.get("n_periods")),
            _fmt_pct(first.get("strategy_ann_return")),
            _fmt_num(first.get("strategy_sharpe")),
            _fmt_pct(first.get("strategy_max_dd")),
        ]
        for versus in preferred_versus:
            match = state_rows.loc[state_rows["versus_series"] == versus]
            if match.empty:
                cells.extend(["-", "-"])
            else:
                row = match.iloc[0]
                cells.extend(
                    [
                        _fmt_pct(row.get("excess_ann_return")),
                        _fmt_pct(row.get("hit_rate")),
                    ]
                )
        lines.append("| " + " | ".join(cells) + " |")


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def _pct_points(value: Any) -> Optional[float]:
    number = _safe_float(value)
    return None if number is None else number * 100.0


def _fmt_pct(value: Any) -> str:
    number = _safe_float(value)
    # Metrics and analysis tables already persist `%`-labelled values as percentage points.
    # Do not scale them again at the reporting layer.
    return "-" if number is None else f"{number:.2f}%"


def _fmt_num(value: Any) -> str:
    number = _safe_float(value)
    return "-" if number is None else f"{number:.3f}"


def _fmt_int(value: Any) -> str:
    number = _safe_float(value)
    return "-" if number is None else str(int(number))


def _fmt_bps(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    rendered = f"{number:.4f}".rstrip("0").rstrip(".")
    return f"{rendered} bps"


def _fmt_metric_value(value: Any, unit: Any) -> str:
    if str(unit or "").lower() == "%":
        return _fmt_pct(value)
    if str(unit or "").lower() == "bps":
        number = _safe_float(value)
        return "-" if number is None else f"{number:.1f}"
    return _fmt_num(value)
