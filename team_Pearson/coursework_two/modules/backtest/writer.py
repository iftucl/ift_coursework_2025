from __future__ import annotations

"""PostgreSQL writers for the CW2 backtest engine."""

import hashlib
import json
import re
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

try:
    from team_Pearson.coursework_one.modules.utils.kafka import (
        publish_json_events,
        resolve_kafka_config,
    )
    from team_Pearson.coursework_two.modules.ops.monitoring import record_ops_event
    from team_Pearson.coursework_two.modules.utils.governance import (
        BACKTEST_VERSION_KEYS,
        resolve_version_bundle,
        select_version_fields,
    )
except ModuleNotFoundError:  # pragma: no cover - import-path fallback for direct module execution
    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_one.modules.utils.kafka import (
        publish_json_events,
        resolve_kafka_config,
    )
    from team_Pearson.coursework_two.modules.ops.monitoring import record_ops_event
    from team_Pearson.coursework_two.modules.utils.governance import (
        BACKTEST_VERSION_KEYS,
        resolve_version_bundle,
        select_version_fields,
    )

_SCHEMA = "systematic_equity"
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validated_identifier(value: str) -> str:
    candidate = str(value).strip()
    if not _VALID_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return candidate


def ensure_backtest_schema(engine: Engine, *, schema_path: str | None = None) -> None:
    """Create or migrate the CW2 backtest schema."""
    base_dir = Path(__file__).resolve().parents[2] / "sql"
    primary_path = Path(schema_path) if schema_path else base_dir / "cw2_backtest_schema.sql"
    intraday_path = base_dir / "cw2_intraday_schema.sql"
    sql_parts = [primary_path.read_text(encoding="utf-8")]
    if intraday_path.exists():
        sql_parts.append(intraday_path.read_text(encoding="utf-8"))
    sql_text = "\n\n".join(sql_parts)
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.execute(sql_text)
        raw_conn.commit()
    finally:
        raw_conn.close()


def create_backtest_run(
    engine: Engine,
    *,
    run_name: str,
    config_snapshot: Dict[str, Any],
) -> str:
    """Insert a ``backtest_runs`` row and return the generated run id."""
    run_id = str(uuid.uuid4())
    sql = text("""
        INSERT INTO systematic_equity.backtest_runs (
            run_id,
            run_name,
            start_date,
            end_date,
            rebalance_freq,
            execution_lag,
            transaction_cost_bps,
            weighting,
            top_n,
            benchmark_ticker,
            model_version,
            factor_definition_version,
            covariance_method_version,
            risk_overlay_policy_version,
            backtest_engine_version,
            config_hash,
            config_snapshot,
            status,
            created_at
        )
        VALUES (
            :run_id,
            :run_name,
            :start_date,
            :end_date,
            :rebalance_freq,
            :execution_lag,
            :transaction_cost_bps,
            :weighting,
            :top_n,
            :benchmark_ticker,
            :model_version,
            :factor_definition_version,
            :covariance_method_version,
            :risk_overlay_policy_version,
            :backtest_engine_version,
            :config_hash,
            CAST(:config_snapshot AS JSONB),
            'running',
            :created_at
        )
        """)
    payload = _build_backtest_run_payload(
        run_id=run_id,
        run_name=run_name,
        config_snapshot=config_snapshot,
    )
    with engine.begin() as conn:
        conn.execute(sql, payload)
    _publish_run_status_event(
        config_snapshot,
        {
            "event_id": f"{run_id}:running",
            "event_type": "backtest_run_status",
            "run_id": run_id,
            "run_name": run_name,
            "status": "running",
            "benchmark_ticker": payload["benchmark_ticker"],
            "created_at_utc": payload["created_at"],
        },
        engine=engine,
    )
    return run_id


def _build_backtest_run_payload(
    *,
    run_id: str,
    run_name: str,
    config_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    run_cfg = config_snapshot.get("backtest") or {}
    version_bundle = select_version_fields(
        resolve_version_bundle(config_snapshot), BACKTEST_VERSION_KEYS
    )
    config_hash = compute_config_hash(config_snapshot)
    return {
        "run_id": run_id,
        "run_name": run_name,
        "start_date": run_cfg.get("start_date"),
        "end_date": run_cfg.get("end_date"),
        "rebalance_freq": run_cfg.get("rebalance_frequency", "monthly"),
        "execution_lag": int(run_cfg.get("execution_lag", 1)),
        "transaction_cost_bps": float(run_cfg.get("transaction_cost_bps", 15.0)),
        "weighting": str(run_cfg.get("weighting", "equal")),
        "top_n": int(run_cfg.get("top_n", 25)),
        "benchmark_ticker": str(run_cfg.get("benchmark_ticker", "SPY")),
        **version_bundle,
        "config_hash": config_hash,
        "config_snapshot": json.dumps(config_snapshot),
        "created_at": datetime.now(timezone.utc),
    }


def compute_config_hash(config_snapshot: Dict[str, Any] | None) -> str | None:
    """Return a stable SHA-256 hash for a config snapshot."""

    if config_snapshot is None:
        return None
    payload = json.dumps(
        _normalize_hash_value(config_snapshot),
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
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return _normalize_hash_value(value.item())
        except Exception:
            return str(value)
    return value


def mark_backtest_completed(
    engine: Engine,
    run_id: str,
    *,
    config_snapshot: Dict[str, Any] | None = None,
) -> None:
    """Mark a backtest run as completed."""
    sql = text("""
        UPDATE systematic_equity.backtest_runs
        SET status = 'completed',
            completed_at = NOW()
        WHERE run_id = :run_id
        """)
    with engine.begin() as conn:
        conn.execute(sql, {"run_id": run_id})
    _publish_run_status_event(
        config_snapshot,
        {
            "event_id": f"{run_id}:completed",
            "event_type": "backtest_run_status",
            "run_id": run_id,
            "status": "completed",
            "created_at_utc": datetime.now(timezone.utc),
        },
        engine=engine,
    )


def mark_backtest_failed(
    engine: Engine,
    run_id: str,
    *,
    config_snapshot: Dict[str, Any] | None = None,
) -> None:
    """Mark a backtest run as failed."""
    sql = text("""
        UPDATE systematic_equity.backtest_runs
        SET status = 'failed',
            completed_at = NOW()
        WHERE run_id = :run_id
        """)
    with engine.begin() as conn:
        conn.execute(sql, {"run_id": run_id})
    _publish_run_status_event(
        config_snapshot,
        {
            "event_id": f"{run_id}:failed",
            "event_type": "backtest_run_status",
            "run_id": run_id,
            "status": "failed",
            "created_at_utc": datetime.now(timezone.utc),
        },
        engine=engine,
    )


def write_holdings(engine: Engine, run_id: str, records: Sequence[Dict[str, Any]]) -> int:
    """Upsert per-period holdings rows."""
    return _upsert_rows(
        engine,
        table_name="backtest_holdings",
        records=[{"run_id": run_id, **record} for record in records],
        allowed_cols=[
            "run_id",
            "rebalance_date",
            "execution_date",
            "symbol",
            "target_weight",
            "executed_weight",
            "drifted_weight",
            "requested_turnover_contrib",
            "turnover_contrib",
            "execution_clipped",
            "composite_alpha",
            "gics_sector",
            "regime",
        ],
        conflict_cols=["run_id", "rebalance_date", "symbol"],
    )


def write_performance(engine: Engine, run_id: str, records: Sequence[Dict[str, Any]]) -> int:
    """Upsert period performance rows."""
    return _upsert_rows(
        engine,
        table_name="backtest_performance",
        records=[{"run_id": run_id, **record} for record in records],
        allowed_cols=[
            "run_id",
            "execution_date",
            "period_end_date",
            "gross_return",
            "net_return",
            "benchmark_return",
            "risk_free_return",
            "excess_return",
            "portfolio_nav",
            "benchmark_nav",
            "turnover",
            "requested_turnover",
            "gross_turnover",
            "gross_requested_turnover",
            "transaction_cost",
            "fixed_transaction_cost",
            "bid_ask_cost",
            "slippage_cost",
            "num_holdings",
            "regime",
            "vix_level",
            "cash_start_weight",
            "cash_after_execution_weight",
            "cash_end_weight",
            "unfilled_buy_weight",
            "unfilled_sell_weight",
            "liquidity_clipped",
            "max_participation_used",
            "forward_filled_symbol_count",
            "forward_fill_day_count",
            "drawdown_brake_active",
            "drawdown_brake_drawdown",
            "drawdown_brake_fraction",
            "intraday_stop_loss_count",
            "intraday_regime_switch_count",
            "intraday_cost",
        ],
        conflict_cols=["run_id", "period_end_date"],
    )


def write_cash_ledger(engine: Engine, run_id: str, records: Sequence[Dict[str, Any]]) -> int:
    """Upsert period-level cash ledger rows."""
    return _upsert_rows(
        engine,
        table_name="backtest_cash_ledger",
        records=[{"run_id": run_id, **record} for record in records],
        allowed_cols=[
            "run_id",
            "rebalance_date",
            "execution_date",
            "period_end_date",
            "cash_start_weight",
            "cash_after_execution_weight",
            "cash_end_weight",
            "requested_turnover",
            "executed_turnover",
            "gross_requested_turnover",
            "gross_executed_turnover",
            "fixed_transaction_cost",
            "bid_ask_cost",
            "slippage_cost",
            "total_cost",
            "unfilled_buy_weight",
            "unfilled_sell_weight",
            "liquidity_clipped",
            "max_participation_used",
            "drawdown_brake_active",
            "drawdown_brake_drawdown",
            "drawdown_brake_fraction",
        ],
        conflict_cols=["run_id", "rebalance_date"],
    )


def write_execution_ledger(engine: Engine, run_id: str, records: Sequence[Dict[str, Any]]) -> int:
    """Upsert symbol-level execution ledger rows."""
    return _upsert_rows(
        engine,
        table_name="backtest_execution_ledger",
        records=[{"run_id": run_id, **record} for record in records],
        allowed_cols=[
            "run_id",
            "rebalance_date",
            "execution_date",
            "symbol",
            "target_weight",
            "drifted_weight",
            "requested_weight",
            "executed_weight",
            "trade_side",
            "requested_buy_weight",
            "requested_sell_weight",
            "requested_trade_weight",
            "executed_buy_weight",
            "executed_sell_weight",
            "executed_trade_weight",
            "unfilled_weight",
            "requested_notional",
            "executed_notional",
            "adv_usd",
            "liquidity_capacity_weight",
            "liquidity_clipped",
            "had_forward_fill",
            "forward_fill_days",
            "participation_ratio",
            "bid_ask_spread_bps",
            "gap_return",
            "gap_penalty_bps",
            "participation_penalty_bps",
            "slippage_bps",
            "fixed_transaction_cost",
            "bid_ask_cost",
            "slippage_cost",
            "total_cost",
        ],
        conflict_cols=["run_id", "rebalance_date", "symbol"],
    )


def write_intraday_events(
    engine: Engine,
    run_id: str,
    records: Sequence[Dict[str, Any]],
    *,
    config_snapshot: Dict[str, Any] | None = None,
) -> int:
    """Upsert daily trigger event rows."""
    inserted = _upsert_rows(
        engine,
        table_name="backtest_intraday_events",
        records=[
            {
                "run_id": run_id,
                **record,
                "symbol": str(record.get("symbol") or ""),
            }
            for record in records
        ],
        allowed_cols=[
            "run_id",
            "event_date",
            "event_type",
            "symbol",
            "action_scope",
            "action_family",
            "urgency",
            "reason_code",
            "entry_price",
            "open_price",
            "high_price",
            "low_price",
            "execution_price",
            "stop_loss_threshold",
            "weight_before",
            "weight_after",
            "regime_before",
            "regime_after",
            "vix_level",
            "vix_daily_return",
            "rebalance_scheduled_for",
            "transaction_cost",
            "expected_turnover",
            "expected_cost",
        ],
        conflict_cols=["run_id", "event_date", "event_type", "symbol"],
    )
    if inserted:
        published = publish_json_events(
            config_snapshot or {},
            topic_key="cw2_risk_actions_executed",
            default_topic="cw2.risk.actions.executed.v1",
            events=[{"run_id": run_id, **record} for record in records],
            key_field="symbol",
            default_client_id="team_pearson_cw2",
        )
        _record_ops_events(
            engine,
            config_snapshot,
            topic_key="cw2_risk_actions_executed",
            default_topic="cw2.risk.actions.executed.v1",
            producer_component="cw2.backtest_writer",
            events=[{"run_id": run_id, **record} for record in records],
            published_count=published,
        )
    return inserted


def write_intraday_daily_state(
    engine: Engine, run_id: str, records: Sequence[Dict[str, Any]]
) -> int:
    """Upsert optional daily state debug rows."""
    return _upsert_rows(
        engine,
        table_name="backtest_intraday_daily_state",
        records=[{"run_id": run_id, **record} for record in records],
        allowed_cols=[
            "run_id",
            "state_date",
            "symbol",
            "weight",
            "entry_price",
            "current_price",
            "unrealized_return",
            "regime",
            "is_cash",
        ],
        conflict_cols=["run_id", "state_date", "symbol"],
    )


def write_metrics(engine: Engine, run_id: str, metrics: Sequence[Dict[str, Any]]) -> int:
    """Upsert summary metrics rows."""
    return _upsert_rows(
        engine,
        table_name="backtest_metrics",
        records=[{"run_id": run_id, **record} for record in metrics],
        allowed_cols=[
            "run_id",
            "metric_group",
            "metric_name",
            "metric_value",
            "metric_unit",
        ],
        conflict_cols=["run_id", "metric_group", "metric_name"],
    )


def _upsert_rows(
    engine: Engine,
    *,
    table_name: str,
    records: Sequence[Dict[str, Any]],
    allowed_cols: List[str],
    conflict_cols: List[str],
) -> int:
    if not records:
        return 0

    safe_schema = _validated_identifier(_SCHEMA)
    safe_table = _validated_identifier(table_name)
    safe_allowed_cols = [_validated_identifier(col) for col in allowed_cols]
    safe_conflict_cols = [_validated_identifier(col) for col in conflict_cols]
    metadata = MetaData()
    table = Table(safe_table, metadata, schema=safe_schema, autoload_with=engine)
    cleaned = [{col: record.get(col) for col in allowed_cols} for record in records]
    update_cols = [col for col in safe_allowed_cols if col not in safe_conflict_cols]
    stmt = pg_insert(table).values(cleaned)
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=safe_conflict_cols,
        set_={col: getattr(stmt.excluded, col) for col in update_cols},
    )
    with engine.begin() as conn:
        conn.execute(upsert_stmt)
    return len(cleaned)


def _publish_run_status_event(
    config_snapshot: Dict[str, Any] | None,
    event: Dict[str, Any],
    *,
    engine: Engine | None = None,
) -> None:
    published = publish_json_events(
        config_snapshot or {},
        topic_key="platform_run_status",
        default_topic="platform.runs.status.v1",
        events=[event],
        key_field="run_id",
        default_client_id="team_pearson_cw2",
    )
    if engine is not None:
        _record_ops_events(
            engine,
            config_snapshot,
            topic_key="platform_run_status",
            default_topic="platform.runs.status.v1",
            producer_component="cw2.backtest_writer",
            events=[event],
            published_count=published,
        )


def _record_ops_events(
    engine: Engine,
    config_snapshot: Dict[str, Any] | None,
    *,
    topic_key: str,
    default_topic: str,
    producer_component: str,
    events: Sequence[Dict[str, Any]],
    published_count: int,
) -> None:
    resolved = resolve_kafka_config(config_snapshot or {}, default_client_id="team_pearson_cw2")
    publish_status = (
        "published"
        if published_count > 0
        else ("disabled" if not resolved.enabled else "suppressed")
    )
    topic_name = str(resolved.topics.get(topic_key, default_topic))
    for event in events:
        record_ops_event(
            engine=engine,
            event_id=event.get("event_id"),
            event_time=event.get("created_at_utc") or event.get("event_date"),
            event_type=str(event.get("event_type") or "kafka_event"),
            producer_component=producer_component,
            topic_key=topic_key,
            topic_name=topic_name,
            run_id=event.get("run_id"),
            symbol=event.get("symbol"),
            severity="info",
            publish_status=publish_status,
            payload=event,
        )
