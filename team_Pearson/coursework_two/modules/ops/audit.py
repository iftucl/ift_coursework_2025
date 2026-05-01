from __future__ import annotations

"""CW2 operational readiness audit for the hybrid batch + daily-risk architecture."""

import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy import text
from sqlalchemy.engine import Engine
from team_Pearson.coursework_two.modules.ops.monitoring import summarize_kafka_event_audit
from team_Pearson.coursework_two.modules.utils.config_contract import (
    validate_shared_runtime_contract,
)

try:
    from team_Pearson.coursework_one.modules.utils.kafka import audit_kafka_connectivity
except ModuleNotFoundError:  # pragma: no cover - import-path fallback for direct module execution
    import sys

    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_one.modules.utils.kafka import audit_kafka_connectivity

from team_Pearson.coursework_two.modules.backtest.data_loader import (
    align_signal_snapshot_counts,
    get_month_end_trading_days,
    load_signal_snapshot_counts,
    load_trading_calendar,
    shift_trading_day,
)
from team_Pearson.coursework_two.modules.backtest.engine import _load_shared_db_engine

_SCHEMA = os.getenv("POSTGRES_SCHEMA", "systematic_equity")
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WEIGHT_TOLERANCE = 0.01
_TURNOVER_TOLERANCE = 1e-6
_COST_TOLERANCE = 1e-6
_NAV_TOLERANCE = 1e-6

_SQL_TABLE_GROUPS: Dict[str, List[str]] = {
    "curated_core": [
        "factor_observations",
        "financial_observations",
        "benchmark_prices",
    ],
    "cw2_features": [
        "feature_universe_screen",
        "feature_sub_scores",
        "feature_factor_scores",
        "feature_risk_overlay",
        "portfolio_target_positions",
        "portfolio_construction_diagnostics",
        "feature_snapshot_registry",
        "portfolio_snapshot_registry",
        "model_input_manifests",
    ],
    "backtest": [
        "backtest_runs",
        "backtest_holdings",
        "backtest_execution_ledger",
        "backtest_performance",
        "backtest_metrics",
    ],
    "analysis": [
        "backtest_benchmark_nav",
        "backtest_benchmark_metrics",
        "backtest_relative_metrics",
        "backtest_regime_attribution",
        "backtest_covariance_metrics",
        "backtest_covariance_contributions",
        "backtest_scorecard",
    ],
    "intraday_overlay": [
        "backtest_intraday_events",
        "backtest_intraday_daily_state",
    ],
    "ops": [
        "ops_event_log",
        "ops_kafka_consumer_ack",
        "ops_kafka_dead_letter",
        "ops_kafka_lag_snapshots",
        "ops_health_snapshots",
        "portfolio_update_decisions",
    ],
    "recommendations": [
        "portfolio_recommendations",
        "portfolio_recommendation_items",
        "portfolio_recommendation_events",
        "portfolio_recommendation_decisions",
    ],
}


def run_audit_from_config(
    *,
    cw1_config_path: str,
    cw2_config_path: str,
    db_engine: Engine | None = None,
) -> Dict[str, Any]:
    """Run a read-only readiness audit across storage, feature history, and backtest prerequisites."""

    cw1_cfg = _load_yaml(cw1_config_path)
    cw2_cfg = _load_yaml(cw2_config_path)
    config_contract = validate_shared_runtime_contract(cw1_cfg, cw2_cfg)
    engine = db_engine or _load_shared_db_engine()

    sql_report = _audit_sql(engine)
    signal_history = _audit_signal_history(engine, cw2_cfg)
    minio_report = _audit_minio(cw1_cfg)
    mongo_report = _audit_mongo(cw1_cfg)
    mongo_report["sentiment_pipeline"] = _audit_sentiment_pipeline_bridge(
        engine,
        cw1_cfg=cw1_cfg,
        cw2_cfg=cw2_cfg,
    )
    redis_report = _audit_redis()
    kafka_report = _audit_kafka(cw1_cfg, cw2_cfg)
    kafka_event_audit = _audit_kafka_event_audit(
        engine,
        cw1_cfg=cw1_cfg,
        cw2_cfg=cw2_cfg,
    )
    kafka_report["event_audit"] = kafka_event_audit
    semantic_checks = _audit_semantic_checks(engine, cw2_cfg)

    operating_model = _build_operating_model(cw1_cfg, cw2_cfg)
    readiness = _summarize_readiness(
        sql_report=sql_report,
        signal_history=signal_history,
        minio_report=minio_report,
        mongo_report=mongo_report,
        redis_report=redis_report,
        kafka_report=kafka_report,
        kafka_event_audit=kafka_event_audit,
        semantic_checks=semantic_checks,
    )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema": _SCHEMA,
        "config_contract": config_contract,
        "operating_model": operating_model,
        "execution_assurance": _build_execution_assurance_model(
            cw2_cfg,
            kafka_event_audit=kafka_event_audit,
        ),
        "storage": {
            "postgresql": sql_report["connectivity"],
            "minio": minio_report,
            "mongo": mongo_report,
            "redis": redis_report,
            "kafka": kafka_report,
        },
        "sql_tables": sql_report["tables"],
        "signal_history": signal_history,
        "semantic_checks": semantic_checks,
        "readiness": readiness,
    }


def _load_yaml(path: str) -> Dict[str, Any]:
    cfg_path = Path(path)
    default_cw2 = Path(__file__).resolve().parents[2] / "config" / "conf.yaml"
    if cfg_path.resolve() == default_cw2.resolve():
        from team_Pearson.coursework_two.modules.utils.config_validation import load_cw2_config

        return load_cw2_config(str(cfg_path))
    with cfg_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _validated_identifier(value: str) -> str:
    candidate = str(value).strip()
    if not _VALID_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return candidate


def _build_operating_model(cw1_cfg: Dict[str, Any], cw2_cfg: Dict[str, Any]) -> Dict[str, Any]:
    bt_cfg = dict(cw2_cfg.get("backtest") or {})
    intraday_cfg = dict(bt_cfg.get("intraday_triggers") or {})
    portfolio_cfg = dict(cw2_cfg.get("portfolio_construction") or {})
    regime_cfg = dict(cw2_cfg.get("regime") or {})
    return {
        "architecture": "hybrid_batch_core_plus_daily_risk_overlay_with_event_bus",
        "alpha_signal_frequency": str(bt_cfg.get("rebalance_frequency", "monthly")),
        "portfolio_rebalance_frequency": str(bt_cfg.get("rebalance_frequency", "monthly")),
        "risk_overlay_frequency": (
            "daily" if intraday_cfg.get("enabled", False) else "scheduled_only"
        ),
        "execution_lag_days": int(bt_cfg.get("execution_lag", 1)),
        "weighting_engine": str(portfolio_cfg.get("weighting", "equal")),
        "regime_engine": str(regime_cfg.get("mode", "threshold")),
        "benchmark_ticker": str(
            bt_cfg.get(
                "benchmark_ticker",
                cw1_cfg.get("market_factors", {}).get("benchmark_ticker", "SPY"),
            )
        ),
        "raw_storage": "minio",
        "structured_store": "postgresql",
        "search_store": "mongo",
        "runtime_state_store": "redis",
        "event_bus": "kafka" if _kafka_enabled(cw1_cfg, cw2_cfg) else "disabled",
    }


def _build_execution_assurance_model(
    cw2_cfg: Dict[str, Any], *, kafka_event_audit: Dict[str, Any]
) -> Dict[str, Any]:
    recommendation_cfg = dict(cw2_cfg.get("recommendation") or {})
    return {
        "backtest_execution_mode": "simulated_portfolio_execution",
        "operate_mode_execution": "recommendation_workflow_only",
        "kafka_event_processing_scope": str(
            kafka_event_audit.get("processing_scope") or "internal_audit_consumer"
        ),
        "external_executor_present": False,
        "external_broker_order_routing": "not_implemented_in_repo",
        "confirms_external_execution": bool(
            kafka_event_audit.get("confirms_external_execution", False)
        ),
        "recommendation_publication_available": True,
        "recommendation_requires_approval": bool(recommendation_cfg.get("approval_required", True)),
        "real_money_trading_enabled": False,
    }


def _audit_sql(engine: Engine) -> Dict[str, Any]:
    connectivity: Dict[str, Any] = {"status": "ok", "ping": True}
    tables: Dict[str, Dict[str, Any]] = {}

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        for group_name, table_names in _SQL_TABLE_GROUPS.items():
            group_rows: Dict[str, Any] = {}
            for table_name in table_names:
                safe_schema = _validated_identifier(_SCHEMA)
                safe_table_name = _validated_identifier(table_name)
                exists = bool(
                    conn.execute(
                        text("""
                            SELECT EXISTS (
                                SELECT 1
                                FROM information_schema.tables
                                WHERE table_schema = :schema
                                  AND table_name = :table_name
                            )
                            """),
                        {"schema": _SCHEMA, "table_name": table_name},
                    ).scalar()
                )
                row_count: Optional[int] = None
                if exists:
                    row_count = int(
                        conn.execute(
                            text(
                                f"SELECT COUNT(*) FROM {safe_schema}.{safe_table_name}"  # nosec B608
                            )
                        ).scalar()
                        or 0
                    )
                group_rows[table_name] = {
                    "exists": exists,
                    "row_count": row_count,
                }
            tables[group_name] = group_rows
    return {"connectivity": connectivity, "tables": tables}


def _audit_signal_history(engine: Engine, cw2_cfg: Dict[str, Any]) -> Dict[str, Any]:
    bt_cfg = dict(cw2_cfg.get("backtest") or {})
    end_date = _resolve_end_date(bt_cfg.get("end_date"))
    start_date = _resolve_start_date(
        bt_cfg.get("start_date"),
        end_date=end_date,
        lookback_years=int(bt_cfg.get("lookback_years", 5)),
    )
    portfolio_name = str(bt_cfg.get("portfolio_name", "cw2_core_equity"))
    min_eligible = int(bt_cfg.get("min_eligible_universe", 15))
    execution_lag = int(bt_cfg.get("execution_lag", 0))
    calendar_end = end_date + timedelta(days=max(10, execution_lag * 3))
    trading_calendar = load_trading_calendar(
        engine,
        start_date,
        calendar_end,
        benchmark_ticker=bt_cfg.get("benchmark_ticker"),
    )
    rebalance_dates = get_month_end_trading_days(trading_calendar)
    while rebalance_dates:
        try:
            shift_trading_day(trading_calendar, rebalance_dates[-1], execution_lag)
            break
        except ValueError:
            rebalance_dates.pop()
    raw_counts = load_signal_snapshot_counts(
        engine,
        portfolio_name=portfolio_name,
        start_date=start_date,
        end_date=end_date,
    )
    aligned_counts = align_signal_snapshot_counts(raw_counts, rebalance_dates)

    aligned = []
    for rebalance_date in rebalance_dates:
        aligned_row = aligned_counts.get(
            rebalance_date,
            {"snapshot_as_of_date": None, "count": 0},
        )
        count = int(aligned_row["count"])
        snapshot_as_of_date = aligned_row["snapshot_as_of_date"]
        aligned.append(
            {
                "as_of_date": rebalance_date.isoformat(),
                "snapshot_as_of_date": (
                    snapshot_as_of_date.isoformat() if snapshot_as_of_date is not None else None
                ),
                "count": count,
                "meets_min_eligible_universe": count >= min_eligible,
            }
        )

    qualifying = [row for row in aligned if row["meets_min_eligible_universe"]]
    return {
        "portfolio_name": portfolio_name,
        "window_start": start_date.isoformat(),
        "window_end": end_date.isoformat(),
        "rebalance_frequency": str(bt_cfg.get("rebalance_frequency", "monthly")),
        "aligned_month_end_snapshots": aligned,
        "qualifying_snapshot_count": len(qualifying),
        "min_eligible_universe": min_eligible,
        "backtest_ready": len(qualifying) >= 2,
    }


def _audit_minio(cw1_cfg: Dict[str, Any]) -> Dict[str, Any]:
    minio_cfg = dict(cw1_cfg.get("minio") or {})
    endpoint = _env_or_cfg("MINIO_ENDPOINT", minio_cfg, "endpoint")
    access_key = _env_or_cfg("MINIO_ACCESS_KEY", minio_cfg, "access_key")
    secret_key = _env_or_cfg("MINIO_SECRET_KEY", minio_cfg, "secret_key")
    bucket = _env_or_cfg("MINIO_BUCKET", minio_cfg, "bucket")
    secure = str(minio_cfg.get("secure", "false")).lower() in {"1", "true", "yes"}

    report: Dict[str, Any] = {
        "status": "unknown",
        "endpoint": endpoint,
        "bucket": bucket,
    }
    try:
        from minio import Minio  # type: ignore

        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        bucket_exists = bool(client.bucket_exists(bucket))
        prefixes = [
            "raw/source_a/",
            "raw/source_b/news/",
            "raw/source_b/news_current/",
            "raw/source_b/news_cursor/",
        ]
        prefix_counts = {}
        if bucket_exists:
            for prefix in prefixes:
                prefix_counts[prefix] = sum(
                    1 for _ in client.list_objects(bucket, prefix=prefix, recursive=True)
                )
        report.update(
            {
                "status": "ok" if bucket_exists else "missing_bucket",
                "bucket_exists": bucket_exists,
                "prefix_object_counts": prefix_counts,
            }
        )
    except Exception as exc:  # pragma: no cover - depends on runtime services
        report.update({"status": "error", "error": repr(exc)})
    return report


def _audit_mongo(cw1_cfg: Dict[str, Any]) -> Dict[str, Any]:
    report: Dict[str, Any] = {"status": "unknown"}
    try:
        from team_Pearson.coursework_one.modules.utils.mongo import (
            build_mongo_client,
            resolve_mongo_db,
        )

        mongo_cfg = dict(cw1_cfg.get("mongo") or {})
        mongo_db = resolve_mongo_db("", mongo_cfg)
        client = build_mongo_client(mongo_cfg)
        try:
            client.admin.command("ping")
            collection = client[mongo_db]["news_articles"]
            report.update(
                {
                    "status": "ok",
                    "database": mongo_db,
                    "collection": "news_articles",
                    "document_count": int(collection.count_documents({})),
                }
            )
        finally:
            client.close()
    except Exception as exc:  # pragma: no cover - depends on runtime services
        report.update({"status": "error", "error": repr(exc)})
    return report


def _audit_sentiment_pipeline_bridge(
    engine: Engine,
    *,
    cw1_cfg: Dict[str, Any],
    cw2_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    bt_cfg = dict(cw2_cfg.get("backtest") or {})
    audit_cfg = dict(cw2_cfg.get("ops_audit") or {})
    end_date = _resolve_end_date(bt_cfg.get("end_date"))
    base_start_date = _resolve_start_date(
        bt_cfg.get("start_date"),
        end_date=end_date,
        lookback_years=int(bt_cfg.get("lookback_years", 5)),
    )
    lookback_days = max(7, int(audit_cfg.get("sentiment_coverage_lookback_days", 30)))
    max_lag_days = max(0, int(audit_cfg.get("sentiment_pipeline_max_lag_days", 3)))
    min_date_coverage_ratio = float(audit_cfg.get("min_article_factor_date_coverage_ratio", 0.80))
    window_start = max(base_start_date, end_date - timedelta(days=lookback_days - 1))
    mongo_stats = _load_recent_mongo_news_stats(cw1_cfg, start_date=window_start, end_date=end_date)
    try:
        pg_stats = _load_recent_pg_sentiment_stats(
            engine, start_date=window_start, end_date=end_date
        )
    except Exception as exc:  # pragma: no cover - runtime schema/service bound
        return {
            "status": "error",
            "window_start": window_start.isoformat(),
            "window_end": end_date.isoformat(),
            "lookback_days": lookback_days,
            "error": repr(exc),
        }

    mongo_publish_dates = int(mongo_stats.get("distinct_publish_dates") or 0)
    article_factor = dict(pg_stats.get("news_article_count_daily") or {})
    sentiment_factor = dict(pg_stats.get("news_sentiment_daily") or {})
    article_rows = int(article_factor.get("row_count") or 0)
    sentiment_rows = int(sentiment_factor.get("row_count") or 0)
    article_date_count = int(article_factor.get("distinct_date_count") or 0)
    sentiment_date_count = int(sentiment_factor.get("distinct_date_count") or 0)
    article_date_ratio = (
        float(article_date_count) / float(mongo_publish_dates) if mongo_publish_dates > 0 else None
    )
    sentiment_date_ratio = (
        float(sentiment_date_count) / float(mongo_publish_dates)
        if mongo_publish_dates > 0
        else None
    )
    latest_mongo_date = _parse_iso_date(mongo_stats.get("latest_publish_date"))
    latest_article_date = _parse_iso_date(article_factor.get("latest_observation_date"))
    latest_sentiment_date = _parse_iso_date(sentiment_factor.get("latest_observation_date"))
    article_lag_days = _date_lag_days(latest_mongo_date, latest_article_date)
    sentiment_lag_days = _date_lag_days(latest_mongo_date, latest_sentiment_date)

    status = "ok"
    if mongo_stats.get("status") == "error":
        status = "error"
    elif int(mongo_stats.get("document_count") or 0) <= 0:
        status = "no_recent_articles"
    elif article_rows <= 0:
        status = "missing_pg_article_counts"
    elif sentiment_rows <= 0:
        status = "missing_pg_sentiment"
    elif article_date_ratio is not None and article_date_ratio < min_date_coverage_ratio:
        status = "degraded"
    elif article_lag_days is not None and article_lag_days > max_lag_days:
        status = "degraded"
    elif sentiment_lag_days is not None and sentiment_lag_days > max_lag_days:
        status = "degraded"

    return {
        "status": status,
        "window_start": window_start.isoformat(),
        "window_end": end_date.isoformat(),
        "lookback_days": lookback_days,
        "max_allowed_lag_days": max_lag_days,
        "min_article_factor_date_coverage_ratio": min_date_coverage_ratio,
        "mongo_document_count": int(mongo_stats.get("document_count") or 0),
        "mongo_distinct_publish_dates": mongo_publish_dates,
        "mongo_latest_publish_date": mongo_stats.get("latest_publish_date"),
        "pg_news_article_count_daily": article_factor,
        "pg_news_sentiment_daily": sentiment_factor,
        "article_factor_date_coverage_ratio": article_date_ratio,
        "sentiment_factor_date_coverage_ratio": sentiment_date_ratio,
        "article_factor_lag_days": article_lag_days,
        "sentiment_factor_lag_days": sentiment_lag_days,
    }


def _load_recent_mongo_news_stats(
    cw1_cfg: Dict[str, Any],
    *,
    start_date: date,
    end_date: date,
) -> Dict[str, Any]:
    try:
        from team_Pearson.coursework_one.modules.utils.mongo import (
            build_mongo_client,
            resolve_mongo_db,
        )

        mongo_cfg = dict(cw1_cfg.get("mongo") or {})
        mongo_db = resolve_mongo_db("", mongo_cfg)
        client = build_mongo_client(mongo_cfg)
        try:
            collection = client[mongo_db]["news_articles"]
            since_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
            until_dt = datetime.combine(
                end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
            )
            match = {
                "published_at": {
                    "$gte": since_dt,
                    "$lt": until_dt,
                }
            }
            doc_count = int(collection.count_documents(match))
            latest_row = next(
                iter(
                    collection.find(match, {"published_at": 1, "_id": 0})
                    .sort("published_at", -1)
                    .limit(1)
                ),
                None,
            )
            distinct_dates = list(
                collection.aggregate(
                    [
                        {"$match": match},
                        {
                            "$group": {
                                "_id": {
                                    "$dateToString": {
                                        "format": "%Y-%m-%d",
                                        "date": "$published_at",
                                        "timezone": "UTC",
                                    }
                                }
                            }
                        },
                        {"$count": "count"},
                    ]
                )
            )
            latest_publish_date = None
            if latest_row and latest_row.get("published_at") is not None:
                latest_publish_date = latest_row["published_at"].date().isoformat()
            return {
                "document_count": doc_count,
                "distinct_publish_dates": (
                    int(distinct_dates[0]["count"]) if distinct_dates else 0
                ),
                "latest_publish_date": latest_publish_date,
            }
        finally:
            client.close()
    except Exception as exc:  # pragma: no cover - runtime dependency/service bound
        return {"status": "error", "error": repr(exc)}


def _load_recent_pg_sentiment_stats(
    engine: Engine,
    *,
    start_date: date,
    end_date: date,
) -> Dict[str, Dict[str, Any]]:
    safe_schema = _validated_identifier(_SCHEMA)
    sql = text(f"""
        SELECT
            factor_name,
            COUNT(*) AS row_count,
            COUNT(DISTINCT observation_date) AS distinct_date_count,
            MAX(observation_date) AS latest_observation_date
        FROM {safe_schema}.factor_observations
        WHERE factor_name IN ('news_article_count_daily', 'news_sentiment_daily')
          AND observation_date BETWEEN :start_date AND :end_date
        GROUP BY factor_name
        """)  # nosec B608
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sql,
                {"start_date": start_date, "end_date": end_date},
            )
            .mappings()
            .all()
        )
    out: Dict[str, Dict[str, Any]] = {
        "news_article_count_daily": {
            "row_count": 0,
            "distinct_date_count": 0,
            "latest_observation_date": None,
        },
        "news_sentiment_daily": {
            "row_count": 0,
            "distinct_date_count": 0,
            "latest_observation_date": None,
        },
    }
    for row in rows:
        factor_name = str(row.get("factor_name") or "")
        if factor_name not in out:
            continue
        latest_observation_date = row.get("latest_observation_date")
        out[factor_name] = {
            "row_count": int(row.get("row_count") or 0),
            "distinct_date_count": int(row.get("distinct_date_count") or 0),
            "latest_observation_date": (
                latest_observation_date.isoformat() if latest_observation_date is not None else None
            ),
        }
    return out


def _audit_redis() -> Dict[str, Any]:
    report: Dict[str, Any] = {"status": "unknown"}
    try:
        from team_Pearson.coursework_one.modules.utils.resilience import _get_redis

        client = _get_redis()
        if client is None:
            report.update({"status": "unavailable"})
            return report
        report.update(
            {
                "status": "ok",
                "ping": bool(client.ping()),
                "key_count": int(client.dbsize()),
            }
        )
    except Exception as exc:  # pragma: no cover - depends on runtime services
        report.update({"status": "error", "error": repr(exc)})
    return report


def _audit_kafka(cw1_cfg: Dict[str, Any], cw2_cfg: Dict[str, Any]) -> Dict[str, Any]:
    kafka_cfg = _merged_kafka_cfg(cw1_cfg, cw2_cfg)
    return audit_kafka_connectivity(kafka_cfg, default_client_id="team_pearson_audit")


def _audit_kafka_event_audit(
    engine: Engine,
    *,
    cw1_cfg: Dict[str, Any],
    cw2_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    kafka_cfg = _merged_kafka_cfg(cw1_cfg, cw2_cfg)
    return summarize_kafka_event_audit(
        engine,
        kafka_config=kafka_cfg,
        lookback_hours=24,
    )


def _audit_semantic_checks(engine: Engine, cw2_cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        "portfolio_target_positions": _audit_portfolio_target_semantics(engine, cw2_cfg),
        "backtest_execution_reconciliation": _audit_backtest_reconciliation(engine),
        "intraday_trade_blotter_consistency": _audit_intraday_trade_blotter(engine),
        "analysis_backtest_consistency": _audit_analysis_reconciliation(engine, cw2_cfg),
    }


def _audit_portfolio_target_semantics(engine: Engine, cw2_cfg: Dict[str, Any]) -> Dict[str, Any]:
    safe_schema = _validated_identifier(_SCHEMA)
    portfolio_cfg = dict(cw2_cfg.get("portfolio_construction") or {})
    min_names = int(
        portfolio_cfg.get(
            "min_names",
            portfolio_cfg.get("hybrid_min_n", portfolio_cfg.get("top_n", 0)),
        )
        or 0
    )
    max_single_weight = _safe_float(portfolio_cfg.get("max_single_weight")) or 1.0
    max_sector_weight = _safe_float(portfolio_cfg.get("max_sector_weight")) or 1.0
    try:
        summary_sql = text(f"""
            SELECT
                as_of_date,
                portfolio_name,
                COUNT(*) FILTER (
                    WHERE ABS(COALESCE(target_weight, 0.0)) > 1e-12
                ) AS non_zero_positions,
                COALESCE(SUM(target_weight), 0.0) AS total_weight,
                COALESCE(MAX(target_weight), 0.0) AS observed_max_single_weight
            FROM {safe_schema}.portfolio_target_positions
            GROUP BY as_of_date, portfolio_name
            ORDER BY as_of_date DESC, portfolio_name
            LIMIT 1
            """)  # nosec B608
        with engine.connect() as conn:
            row = conn.execute(summary_sql).mappings().first()
            if row is None:
                return {"status": "no_data", "checked_snapshot": None}
            sector_sql = text(f"""
                SELECT COALESCE(MAX(sector_weight), 0.0) AS observed_max_sector_weight
                FROM (
                    SELECT COALESCE(gics_sector, 'Unknown') AS sector_name,
                           COALESCE(SUM(target_weight), 0.0) AS sector_weight
                    FROM {safe_schema}.portfolio_target_positions
                    WHERE as_of_date = :as_of_date
                      AND portfolio_name = :portfolio_name
                    GROUP BY COALESCE(gics_sector, 'Unknown')
                ) AS sector_weights
                """)  # nosec B608
            sector_row = (
                conn.execute(
                    sector_sql,
                    {
                        "as_of_date": row["as_of_date"],
                        "portfolio_name": row["portfolio_name"],
                    },
                )
                .mappings()
                .first()
            )
        total_weight = _safe_float(row.get("total_weight")) or 0.0
        observed_max_single = _safe_float(row.get("observed_max_single_weight")) or 0.0
        observed_max_sector = (
            _safe_float((sector_row or {}).get("observed_max_sector_weight")) or 0.0
        )
        violations: List[str] = []
        if abs(total_weight - 1.0) > _WEIGHT_TOLERANCE:
            violations.append("target_weight_sum_outside_tolerance")
        if int(row.get("non_zero_positions") or 0) < min_names:
            violations.append("non_zero_positions_below_min_names")
        if observed_max_single > max_single_weight + _WEIGHT_TOLERANCE:
            violations.append("single_name_cap_breached")
        if observed_max_sector > max_sector_weight + _WEIGHT_TOLERANCE:
            violations.append("sector_cap_breached")
        return {
            "status": "ok" if not violations else "error",
            "checked_snapshot": {
                "as_of_date": row["as_of_date"].isoformat(),
                "portfolio_name": row["portfolio_name"],
            },
            "thresholds": {
                "min_names": min_names,
                "max_single_weight": max_single_weight,
                "max_sector_weight": max_sector_weight,
                "weight_sum_tolerance": _WEIGHT_TOLERANCE,
            },
            "observed": {
                "non_zero_positions": int(row.get("non_zero_positions") or 0),
                "total_weight": total_weight,
                "max_single_weight": observed_max_single,
                "max_sector_weight": observed_max_sector,
            },
            "violations": violations,
        }
    except Exception as exc:  # pragma: no cover - database/state dependent
        return {"status": "error", "error": repr(exc)}


def _audit_backtest_reconciliation(engine: Engine) -> Dict[str, Any]:
    latest_run = _latest_completed_run(engine)
    if latest_run is None:
        return {"status": "no_data", "run_id": None}
    safe_schema = _validated_identifier(_SCHEMA)
    run_id = latest_run["run_id"]
    try:
        counts_sql = text(f"""
            SELECT
                (SELECT COUNT(*) FROM {safe_schema}.backtest_performance WHERE run_id = :run_id) AS performance_rows,
                (SELECT COUNT(*) FROM {safe_schema}.backtest_cash_ledger WHERE run_id = :run_id) AS cash_ledger_rows,
                (SELECT COUNT(*) FROM {safe_schema}.backtest_execution_ledger WHERE run_id = :run_id) AS execution_rows
            """)  # nosec B608
        perf_cash_sql = text(f"""
            SELECT
                COUNT(*) AS matched_rows,
                COALESCE(MAX(ABS(COALESCE(cl.total_cost, 0.0) - COALESCE(bp.transaction_cost, 0.0))), 0.0) AS max_total_cost_diff,
                COALESCE(MAX(ABS(COALESCE(cl.executed_turnover, 0.0) - COALESCE(bp.turnover, 0.0))), 0.0) AS max_turnover_diff,
                COALESCE(MAX(ABS(COALESCE(cl.cash_end_weight, 0.0) - COALESCE(bp.cash_end_weight, 0.0))), 0.0) AS max_cash_end_weight_diff
            FROM {safe_schema}.backtest_cash_ledger AS cl
            JOIN {safe_schema}.backtest_performance AS bp
              ON bp.run_id = cl.run_id
             AND bp.period_end_date = cl.period_end_date
            WHERE cl.run_id = :run_id
            """)  # nosec B608
        exec_cash_sql = text(f"""
            SELECT
                COUNT(*) AS matched_rows,
                COALESCE(MAX(ABS(
                    COALESCE(exec_agg.total_cost, 0.0)
                    + COALESCE(intraday_agg.intraday_cost, 0.0)
                    - COALESCE(cl.total_cost, 0.0)
                )), 0.0) AS max_execution_cost_diff,
                COALESCE(MAX(ABS(
                    COALESCE(exec_agg.total_cost, 0.0) - COALESCE(cl.fixed_transaction_cost, 0.0)
                )), 0.0) AS max_fixed_cost_diff,
                COALESCE(MAX(ABS(COALESCE(exec_agg.gross_executed_turnover, 0.0) - COALESCE(cl.gross_executed_turnover, 0.0))), 0.0) AS max_gross_turnover_diff
            FROM (
                SELECT
                    run_id,
                    rebalance_date,
                    COALESCE(SUM(total_cost), 0.0) AS total_cost,
                    COALESCE(SUM(executed_trade_weight), 0.0) AS gross_executed_turnover
                FROM {safe_schema}.backtest_execution_ledger
                WHERE run_id = :run_id
                GROUP BY run_id, rebalance_date
            ) AS exec_agg
            LEFT JOIN (
                SELECT
                    cl.run_id,
                    cl.rebalance_date,
                    COALESCE(SUM(ie.transaction_cost), 0.0) AS intraday_cost
                FROM {safe_schema}.backtest_cash_ledger AS cl
                LEFT JOIN {safe_schema}.backtest_intraday_events AS ie
                  ON ie.run_id = cl.run_id
                 AND ie.event_date >= cl.execution_date
                 AND ie.event_date < cl.period_end_date
                WHERE cl.run_id = :run_id
                GROUP BY cl.run_id, cl.rebalance_date
            ) AS intraday_agg
              ON intraday_agg.run_id = exec_agg.run_id
             AND intraday_agg.rebalance_date = exec_agg.rebalance_date
            JOIN {safe_schema}.backtest_cash_ledger AS cl
              ON cl.run_id = exec_agg.run_id
             AND cl.rebalance_date = exec_agg.rebalance_date
            """)  # nosec B608
        with engine.connect() as conn:
            counts = dict(conn.execute(counts_sql, {"run_id": run_id}).mappings().first())
            perf_cash = dict(conn.execute(perf_cash_sql, {"run_id": run_id}).mappings().first())
            exec_cash = dict(conn.execute(exec_cash_sql, {"run_id": run_id}).mappings().first())
        violations: List[str] = []
        if int(counts.get("performance_rows") or 0) <= 0:
            violations.append("performance_rows_missing")
        if int(counts.get("cash_ledger_rows") or 0) != int(counts.get("performance_rows") or 0):
            violations.append("cash_ledger_row_count_mismatch")
        if (_safe_float(perf_cash.get("max_total_cost_diff")) or 0.0) > _COST_TOLERANCE:
            violations.append("cash_ledger_vs_performance_cost_mismatch")
        if (_safe_float(perf_cash.get("max_turnover_diff")) or 0.0) > _TURNOVER_TOLERANCE:
            violations.append("cash_ledger_vs_performance_turnover_mismatch")
        if (_safe_float(perf_cash.get("max_cash_end_weight_diff")) or 0.0) > _TURNOVER_TOLERANCE:
            violations.append("cash_end_weight_mismatch")
        if (_safe_float(exec_cash.get("max_execution_cost_diff")) or 0.0) > _COST_TOLERANCE:
            violations.append("execution_vs_cash_cost_mismatch")
        if (_safe_float(exec_cash.get("max_fixed_cost_diff")) or 0.0) > _COST_TOLERANCE:
            violations.append("execution_vs_cash_fixed_cost_mismatch")
        if (_safe_float(exec_cash.get("max_gross_turnover_diff")) or 0.0) > _TURNOVER_TOLERANCE:
            violations.append("execution_vs_cash_gross_turnover_mismatch")
        return {
            "status": "ok" if not violations else "error",
            "run_id": run_id,
            "run_name": latest_run.get("run_name"),
            "row_counts": {
                "performance_rows": int(counts.get("performance_rows") or 0),
                "cash_ledger_rows": int(counts.get("cash_ledger_rows") or 0),
                "execution_rows": int(counts.get("execution_rows") or 0),
            },
            "observed": {
                "max_total_cost_diff": _safe_float(perf_cash.get("max_total_cost_diff")) or 0.0,
                "max_turnover_diff": _safe_float(perf_cash.get("max_turnover_diff")) or 0.0,
                "max_cash_end_weight_diff": _safe_float(perf_cash.get("max_cash_end_weight_diff"))
                or 0.0,
                "max_execution_cost_diff": _safe_float(exec_cash.get("max_execution_cost_diff"))
                or 0.0,
                "max_fixed_cost_diff": _safe_float(exec_cash.get("max_fixed_cost_diff")) or 0.0,
                "max_gross_turnover_diff": _safe_float(exec_cash.get("max_gross_turnover_diff"))
                or 0.0,
            },
            "violations": violations,
        }
    except Exception as exc:  # pragma: no cover - database/state dependent
        return {"status": "error", "run_id": run_id, "error": repr(exc)}


def _audit_intraday_trade_blotter(engine: Engine) -> Dict[str, Any]:
    latest_run = _latest_completed_run(engine)
    if latest_run is None:
        return {"status": "no_data", "run_id": None}
    safe_schema = _validated_identifier(_SCHEMA)
    run_id = latest_run["run_id"]
    try:
        counts_sql = text(f"""
            SELECT
                (SELECT COUNT(*) FROM {safe_schema}.backtest_intraday_events WHERE run_id = :run_id) AS event_rows,
                (SELECT COUNT(*) FROM {safe_schema}.backtest_trade_blotter WHERE run_id = :run_id AND source_layer = 'intraday_overlay') AS blotter_rows,
                (
                    SELECT COUNT(*)
                    FROM {safe_schema}.backtest_trade_blotter
                    WHERE run_id = :run_id
                      AND source_layer = 'intraday_overlay'
                      AND (
                        (weight_after < weight_before AND trade_side IS DISTINCT FROM 'sell')
                        OR (weight_after > weight_before AND trade_side IS DISTINCT FROM 'buy')
                      )
                ) AS direction_conflicts
            """)  # nosec B608
        with engine.connect() as conn:
            row = dict(conn.execute(counts_sql, {"run_id": run_id}).mappings().first())
        event_rows = int(row.get("event_rows") or 0)
        blotter_rows = int(row.get("blotter_rows") or 0)
        direction_conflicts = int(row.get("direction_conflicts") or 0)
        if event_rows == 0 and blotter_rows == 0:
            return {
                "status": "not_applicable",
                "run_id": run_id,
                "event_rows": 0,
                "blotter_rows": 0,
            }
        violations: List[str] = []
        if event_rows != blotter_rows:
            violations.append("intraday_event_count_mismatch")
        if direction_conflicts > 0:
            violations.append("intraday_trade_direction_conflicts")
        return {
            "status": "ok" if not violations else "error",
            "run_id": run_id,
            "event_rows": event_rows,
            "blotter_rows": blotter_rows,
            "direction_conflicts": direction_conflicts,
            "violations": violations,
        }
    except Exception as exc:  # pragma: no cover - database/state dependent
        return {"status": "error", "run_id": run_id, "error": repr(exc)}


def _audit_analysis_reconciliation(engine: Engine, cw2_cfg: Dict[str, Any]) -> Dict[str, Any]:
    latest_run = _latest_completed_run(engine)
    if latest_run is None:
        return {"status": "no_data", "run_id": None}
    safe_schema = _validated_identifier(_SCHEMA)
    run_id = latest_run["run_id"]
    backtest_cfg = dict(cw2_cfg.get("backtest") or {})
    analysis_cfg = dict(backtest_cfg.get("analysis") or {})
    benchmark_ticker = str(
        latest_run.get("benchmark_ticker") or backtest_cfg.get("benchmark_ticker") or "SPY"
    )
    primary_benchmark = str(analysis_cfg.get("primary_benchmark") or benchmark_ticker)
    try:
        sql = text(f"""
            SELECT
                (SELECT period_end_date FROM {safe_schema}.backtest_performance WHERE run_id = :run_id ORDER BY period_end_date DESC LIMIT 1) AS latest_performance_date,
                (SELECT benchmark_nav FROM {safe_schema}.backtest_performance WHERE run_id = :run_id ORDER BY period_end_date DESC LIMIT 1) AS latest_performance_benchmark_nav,
                (SELECT period_end_date FROM {safe_schema}.backtest_benchmark_nav WHERE run_id = :run_id AND series_name = :benchmark_ticker ORDER BY period_end_date DESC LIMIT 1) AS latest_analysis_benchmark_date,
                (SELECT nav FROM {safe_schema}.backtest_benchmark_nav WHERE run_id = :run_id AND series_name = :benchmark_ticker ORDER BY period_end_date DESC LIMIT 1) AS latest_analysis_benchmark_nav,
                (SELECT COUNT(*) FROM {safe_schema}.backtest_relative_metrics WHERE run_id = :run_id AND versus_series = :primary_benchmark AND metric_name IN ('information_ratio', 'excess_return_annualized')) AS relative_metric_count
            """)  # nosec B608
        with engine.connect() as conn:
            row = dict(
                conn.execute(
                    sql,
                    {
                        "run_id": run_id,
                        "benchmark_ticker": benchmark_ticker,
                        "primary_benchmark": primary_benchmark,
                    },
                )
                .mappings()
                .first()
            )
        perf_date = _date_to_iso(row.get("latest_performance_date"))
        analysis_date = _date_to_iso(row.get("latest_analysis_benchmark_date"))
        perf_nav = _safe_float(row.get("latest_performance_benchmark_nav")) or 0.0
        analysis_nav = _safe_float(row.get("latest_analysis_benchmark_nav")) or 0.0
        relative_metric_count = int(row.get("relative_metric_count") or 0)
        violations: List[str] = []
        if perf_date is None:
            violations.append("performance_rows_missing")
        if analysis_date is None:
            violations.append("analysis_benchmark_rows_missing")
        if perf_date is not None and analysis_date is not None and perf_date != analysis_date:
            violations.append("analysis_benchmark_date_mismatch")
        if abs(perf_nav - analysis_nav) > _NAV_TOLERANCE:
            violations.append("analysis_benchmark_nav_mismatch")
        if relative_metric_count < 2:
            violations.append("relative_metrics_incomplete")
        return {
            "status": "ok" if not violations else "error",
            "run_id": run_id,
            "benchmark_ticker": benchmark_ticker,
            "primary_benchmark": primary_benchmark,
            "observed": {
                "latest_performance_date": perf_date,
                "latest_analysis_benchmark_date": analysis_date,
                "latest_performance_benchmark_nav": perf_nav,
                "latest_analysis_benchmark_nav": analysis_nav,
                "relative_metric_count": relative_metric_count,
            },
            "violations": violations,
        }
    except Exception as exc:  # pragma: no cover - database/state dependent
        return {"status": "error", "run_id": run_id, "error": repr(exc)}


def _latest_completed_run(engine: Engine) -> Optional[Dict[str, Any]]:
    safe_schema = _validated_identifier(_SCHEMA)
    sql = text(f"""
        SELECT run_id, run_name, benchmark_ticker, end_date, created_at
        FROM {safe_schema}.backtest_runs
        WHERE status = 'completed'
        ORDER BY end_date DESC, created_at DESC
        LIMIT 1
        """)  # nosec B608
    with engine.connect() as conn:
        row = conn.execute(sql).mappings().first()
    return dict(row) if row else None


def _summarize_readiness(
    *,
    sql_report: Dict[str, Any],
    signal_history: Dict[str, Any],
    minio_report: Dict[str, Any],
    mongo_report: Dict[str, Any],
    redis_report: Dict[str, Any],
    kafka_report: Dict[str, Any],
    kafka_event_audit: Dict[str, Any],
    semantic_checks: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    core_tables = sql_report["tables"]["curated_core"]
    feature_tables = sql_report["tables"]["cw2_features"]
    core_sql_ready = all(
        table_info["exists"] and int(table_info["row_count"] or 0) > 0
        for table_info in core_tables.values()
    )
    feature_pipeline_ready = all(
        feature_tables[name]["exists"] and int(feature_tables[name]["row_count"] or 0) > 0
        for name in (
            "feature_sub_scores",
            "feature_factor_scores",
            "feature_risk_overlay",
            "portfolio_target_positions",
        )
    )
    kafka_ready = (not bool(kafka_report.get("enabled"))) or kafka_report.get("status") == "ok"
    kafka_event_audit_ready = (not bool(kafka_report.get("enabled"))) or str(
        kafka_event_audit.get("status") or ""
    ).lower() in {"ok", "no_recent_activity", "disabled", "audit_disabled"}
    storage_ready = (
        all(report.get("status") == "ok" for report in (minio_report, redis_report))
        and _mongo_audit_ready(mongo_report)
        and kafka_ready
        and kafka_event_audit_ready
    )
    backtest_ready = bool(signal_history["backtest_ready"])
    analysis_tables = sql_report["tables"]["analysis"]
    analysis_materialized = any(
        table_info["exists"] and int(table_info["row_count"] or 0) > 0
        for table_info in analysis_tables.values()
    )
    recommendation_tables = sql_report["tables"]["recommendations"]
    recommendation_materialized = any(
        table_info["exists"] and int(table_info["row_count"] or 0) > 0
        for table_info in recommendation_tables.values()
    )
    semantic_statuses = [
        str(report.get("status") or "").lower() for report in semantic_checks.values()
    ]
    semantic_ready = all(
        status in {"ok", "not_applicable", "no_data", ""} for status in semantic_statuses
    )
    semantic_warnings_present = any(status == "warning" for status in semantic_statuses)
    overall_status = (
        "ready"
        if core_sql_ready
        and feature_pipeline_ready
        and storage_ready
        and backtest_ready
        and semantic_ready
        else "partial"
    )
    if not core_sql_ready:
        overall_status = "error"
    return {
        "overall_status": overall_status,
        "core_sql_ready": core_sql_ready,
        "feature_pipeline_ready": feature_pipeline_ready,
        "storage_ready": storage_ready,
        "kafka_ready": kafka_ready,
        "kafka_event_audit_ready": kafka_event_audit_ready,
        "backtest_ready": backtest_ready,
        "semantic_ready": semantic_ready,
        "semantic_warnings_present": semantic_warnings_present,
        "analysis_materialized": analysis_materialized,
        "recommendation_materialized": recommendation_materialized,
        "recommended_next_step": _recommended_next_step(
            core_sql_ready=core_sql_ready,
            feature_pipeline_ready=feature_pipeline_ready,
            storage_ready=storage_ready,
            kafka_event_audit_ready=kafka_event_audit_ready,
            backtest_ready=backtest_ready,
            semantic_ready=semantic_ready,
            analysis_materialized=analysis_materialized,
            recommendation_materialized=recommendation_materialized,
        ),
    }


def _recommended_next_step(
    *,
    core_sql_ready: bool,
    feature_pipeline_ready: bool,
    storage_ready: bool,
    kafka_event_audit_ready: bool,
    backtest_ready: bool,
    semantic_ready: bool,
    analysis_materialized: bool,
    recommendation_materialized: bool,
) -> str:
    if not core_sql_ready:
        return (
            "Repair PostgreSQL connectivity and curated-core population before any full-scale run."
        )
    if not storage_ready:
        if not kafka_event_audit_ready:
            return "Run the CW2 Kafka event-audit consumer and clear any lag/dead-letter backlog before claiming end-to-end event readiness."
        return "Repair MinIO/Mongo/Redis/Kafka connectivity before claiming production-grade end-to-end readiness."
    if not feature_pipeline_ready:
        return "Run the upstream-plus-CW2 feature pipeline until portfolio_target_positions is materialized."
    if not backtest_ready:
        return "Generate at least one earlier month-end portfolio snapshot so the backtest can form a realized holding period."
    if not semantic_ready:
        return "Resolve semantic consistency issues across portfolio targets, backtest ledgers, and analysis outputs before claiming full reproducibility."
    if not recommendation_materialized:
        return "Publish the formal recommendation layer from the latest stored portfolio targets before presenting end-user investment advice."
    if not analysis_materialized:
        return (
            "Run CW2 backtest first, then materialize the analysis layer from the resulting run_id."
        )
    return "The hybrid batch-core plus daily-risk-overlay stack is ready for larger-scale historical runs."


def _mongo_audit_ready(report: Dict[str, Any]) -> bool:
    if report.get("status") != "ok":
        return False
    sentiment_pipeline = dict(report.get("sentiment_pipeline") or {})
    return sentiment_pipeline.get("status") in {None, "ok", "no_recent_articles"}


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _env_or_cfg(env_key: str, cfg: Dict[str, Any], cfg_key: str, default: str = "") -> str:
    raw = os.getenv(env_key, str(cfg.get(cfg_key, default) or default))
    return str(raw).strip()


def _merged_kafka_cfg(cw1_cfg: Dict[str, Any], cw2_cfg: Dict[str, Any]) -> Dict[str, Any]:
    cw1_kafka = dict(cw1_cfg.get("kafka") or {})
    cw2_kafka = dict(cw2_cfg.get("kafka") or {})
    merged = dict(cw1_cfg)
    merged["kafka"] = {
        **cw1_kafka,
        **cw2_kafka,
        "topics": {
            **dict(cw1_kafka.get("topics") or {}),
            **dict(cw2_kafka.get("topics") or {}),
        },
        "audit_consumer": {
            **dict(cw1_kafka.get("audit_consumer") or {}),
            **dict(cw2_kafka.get("audit_consumer") or {}),
        },
    }
    return merged


def _kafka_enabled(cw1_cfg: Dict[str, Any], cw2_cfg: Dict[str, Any]) -> bool:
    kafka_cfg = dict((cw2_cfg.get("kafka") or cw1_cfg.get("kafka")) or {})
    return str(kafka_cfg.get("enabled", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_end_date(value: Any) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    text = str(value).strip().lower()
    if text in {"", "auto", "today", "latest", "none", "null"}:
        return datetime.now(timezone.utc).date()
    return date.fromisoformat(str(value))


def _resolve_start_date(value: Any, *, end_date: date, lookback_years: int) -> date:
    if value is None:
        return _subtract_years(end_date, lookback_years)
    text = str(value).strip().lower()
    if text in {"", "auto", "rolling", "dynamic", "none", "null"}:
        return _subtract_years(end_date, lookback_years)
    return date.fromisoformat(str(value))


def _parse_iso_date(value: Any) -> Optional[date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _date_to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = _parse_iso_date(value)
    return parsed.isoformat() if parsed is not None else None


def _date_lag_days(later: Optional[date], earlier: Optional[date]) -> Optional[int]:
    if later is None or earlier is None:
        return None
    return max(0, (later - earlier).days)


def _subtract_years(anchor: date, years: int) -> date:
    try:
        return anchor.replace(year=anchor.year - int(years))
    except ValueError:
        return anchor.replace(month=2, day=28, year=anchor.year - int(years))
