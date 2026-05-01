from __future__ import annotations

"""Publish formal portfolio recommendation objects from stored CW2 portfolio targets."""

import json
import sys
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

try:
    from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot
    from team_Pearson.coursework_two.modules.utils.governance import (
        RECOMMENDATION_VERSION_KEYS,
        resolve_version_bundle,
        select_version_fields,
    )
except ModuleNotFoundError:  # pragma: no cover - import-path fallback for direct module execution
    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot
    from team_Pearson.coursework_two.modules.utils.governance import (
        RECOMMENDATION_VERSION_KEYS,
        resolve_version_bundle,
        select_version_fields,
    )

_SCHEMA = "systematic_equity"


def publish_recommendation_from_config(
    *,
    run_date: str,
    config_path: str | None = None,
    db_engine: Engine | None = None,
    recommendation_name: str | None = None,
) -> Dict[str, Any]:
    """Materialize a formal recommendation package from the latest eligible CW2 snapshot."""

    config = _load_config(config_path)
    engine = db_engine or _load_shared_db_engine()
    ensure_recommendation_schema(engine)

    requested_date = date.fromisoformat(str(run_date))
    recommendation_cfg = dict(config.get("recommendation") or {})
    portfolio_name = str(
        recommendation_cfg.get("portfolio_name")
        or (config.get("portfolio_construction") or {}).get("portfolio_name")
        or "cw2_core_equity"
    )
    as_of_date = _resolve_recommendation_as_of_date(engine, requested_date, portfolio_name)
    if as_of_date is None:
        raise ValueError(
            f"No portfolio_target_positions found for portfolio={portfolio_name} on or before {requested_date.isoformat()}"
        )

    targets = _load_portfolio_targets(engine, as_of_date, portfolio_name)
    if not targets:
        raise ValueError(
            f"No non-zero portfolio_target_positions found for portfolio={portfolio_name} as_of_date={as_of_date.isoformat()}"
        )

    symbols = [str(row["symbol"]) for row in targets]
    factor_scores = _load_factor_scores(engine, as_of_date, symbols)
    overlay_lookup = _load_overlay_lookup(engine, as_of_date, symbols)

    recommendation_id = str(uuid.uuid4())
    generated_name = recommendation_name or _default_recommendation_name(
        as_of_date=as_of_date,
        portfolio_name=portfolio_name,
    )
    header = _build_recommendation_header(
        recommendation_id=recommendation_id,
        recommendation_name=generated_name,
        as_of_date=as_of_date,
        portfolio_name=portfolio_name,
        targets=targets,
        factor_scores=factor_scores,
        overlay_lookup=overlay_lookup,
        config=config,
    )
    items = _build_recommendation_items(
        recommendation_id=recommendation_id,
        targets=targets,
        factor_scores=factor_scores,
        overlay_lookup=overlay_lookup,
    )
    events = [
        {
            "recommendation_id": recommendation_id,
            "event_type": "proposed",
            "event_timestamp": datetime.now(timezone.utc),
            "actor": "system",
            "notes": "Recommendation created from stored CW2 portfolio_target_positions.",
            "payload_json": json.dumps(
                {
                    "as_of_date": as_of_date.isoformat(),
                    "portfolio_name": portfolio_name,
                    "num_positions": len(items),
                },
                sort_keys=True,
            ),
        }
    ]

    _write_header(engine, header)
    _write_items(engine, items)
    _write_events(engine, events)
    record_quality_snapshot(
        engine=engine,
        dataset_name="portfolio_recommendations",
        run_id=recommendation_id,
        run_date=as_of_date,
        quality_report=_build_recommendation_quality_report(header=header, items=items),
    )
    return {
        "recommendation_id": recommendation_id,
        "recommendation_name": generated_name,
        "as_of_date": as_of_date.isoformat(),
        "portfolio_name": portfolio_name,
        "num_items": len(items),
        "status": header["recommendation_status"],
    }


def apply_recommendation_decision(
    *,
    decision_type: str,
    actor: str,
    recommendation_id: str | None = None,
    recommendation_name: str | None = None,
    notes: str | None = None,
    config_path: str | None = None,
    db_engine: Engine | None = None,
) -> Dict[str, Any]:
    """Approve, reject, or publish an existing recommendation."""

    normalized_decision = str(decision_type or "").strip().lower()
    if normalized_decision not in {"approve", "reject", "publish"}:
        raise ValueError("decision_type must be one of: approve, reject, publish")
    if not str(actor or "").strip():
        raise ValueError("actor is required when recording a recommendation decision")
    if not recommendation_id and not recommendation_name:
        raise ValueError("recommendation_id or recommendation_name is required")

    config = _load_config(config_path)
    engine = db_engine or _load_shared_db_engine()
    ensure_recommendation_schema(engine)

    header = _load_recommendation_header(
        engine,
        recommendation_id=recommendation_id,
        recommendation_name=recommendation_name,
    )
    if header is None:
        raise ValueError("Recommendation not found for the supplied identifier")

    current_status = str(header.get("recommendation_status") or "proposed").strip().lower()
    approval_required = bool((config.get("recommendation") or {}).get("approval_required", True))
    new_status = _resolve_recommendation_status_transition(
        current_status=current_status,
        decision_type=normalized_decision,
        approval_required=approval_required,
    )
    now = datetime.now(timezone.utc)
    updated_row = {
        "recommendation_id": header["recommendation_id"],
        "recommendation_status": new_status,
        "approved_at": header.get("approved_at"),
        "approved_by": header.get("approved_by"),
        "decision_notes": notes,
        "updated_at": now,
    }
    if normalized_decision == "approve":
        updated_row["approved_at"] = now
        updated_row["approved_by"] = actor
    elif normalized_decision == "reject" and current_status != "approved":
        updated_row["approved_at"] = None
        updated_row["approved_by"] = None

    decision_payload = {
        "previous_status": current_status,
        "new_status": new_status,
        "approval_required": approval_required,
        "actor": actor,
    }
    _update_recommendation_status(engine, updated_row)
    _write_decisions(
        engine,
        [
            {
                "recommendation_id": header["recommendation_id"],
                "decision_type": normalized_decision,
                "actor": actor,
                "decision_timestamp": now,
                "notes": notes,
                "payload_json": json.dumps(decision_payload, sort_keys=True),
            }
        ],
    )
    _write_events(
        engine,
        [
            {
                "recommendation_id": header["recommendation_id"],
                "event_type": _decision_to_event_type(normalized_decision),
                "event_timestamp": now,
                "actor": actor,
                "notes": notes,
                "payload_json": json.dumps(decision_payload, sort_keys=True),
            }
        ],
    )
    return {
        "recommendation_id": str(header["recommendation_id"]),
        "recommendation_name": str(header["recommendation_name"]),
        "decision_type": normalized_decision,
        "status": new_status,
        "actor": actor,
        "approved_at": (
            updated_row["approved_at"].isoformat() if updated_row["approved_at"] else None
        ),
    }


def load_recommendation_package(
    *,
    recommendation_id: str | None = None,
    recommendation_name: str | None = None,
    config_path: str | None = None,
    db_engine: Engine | None = None,
) -> Dict[str, Any]:
    """Load a full recommendation package for downstream briefing and audit outputs."""

    if not recommendation_id and not recommendation_name:
        raise ValueError("recommendation_id or recommendation_name is required")

    _ = _load_config(config_path)
    engine = db_engine or _load_shared_db_engine()
    ensure_recommendation_schema(engine)

    header = _load_recommendation_header(
        engine,
        recommendation_id=recommendation_id,
        recommendation_name=recommendation_name,
    )
    if header is None:
        raise ValueError("Recommendation not found for the supplied identifier")

    items = _load_recommendation_items(engine, str(header["recommendation_id"]))
    events = _load_recommendation_events(engine, str(header["recommendation_id"]))
    decisions = _load_recommendation_decisions(engine, str(header["recommendation_id"]))

    return {
        "header": _decode_recommendation_row(header),
        "items": [_decode_recommendation_row(row) for row in items],
        "events": [_decode_recommendation_row(row) for row in events],
        "decisions": [_decode_recommendation_row(row) for row in decisions],
    }


def ensure_recommendation_schema(engine: Engine) -> None:
    """Create or migrate the SQL objects used by recommendation publishing."""

    schema_path = Path(__file__).resolve().parents[2] / "sql" / "cw2_recommendation_schema.sql"
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


def _resolve_recommendation_as_of_date(
    engine: Engine,
    requested_date: date,
    portfolio_name: str,
) -> Optional[date]:
    sql = text(f"""
        SELECT MAX(as_of_date) AS as_of_date
        FROM {_SCHEMA}.portfolio_target_positions
        WHERE portfolio_name = :portfolio_name
          AND as_of_date <= :requested_date
          AND COALESCE(target_weight, 0) > 0
        """)
    with engine.connect() as conn:
        row = (
            conn.execute(
                sql,
                {
                    "portfolio_name": portfolio_name,
                    "requested_date": requested_date,
                },
            )
            .mappings()
            .first()
        )
    return row["as_of_date"] if row and row["as_of_date"] else None


def _load_portfolio_targets(
    engine: Engine, as_of_date: date, portfolio_name: str
) -> List[Dict[str, Any]]:
    sql = text(f"""
        SELECT
            symbol,
            selection_rank,
            target_weight,
            weighting_scheme,
            ranking_mode,
            ranking_score,
            composite_alpha,
            regime,
            gics_sector,
            country,
            previous_weight,
            trade_weight,
            turnover_limited
        FROM {_SCHEMA}.portfolio_target_positions
        WHERE as_of_date = :as_of_date
          AND portfolio_name = :portfolio_name
          AND COALESCE(target_weight, 0) > 0
        ORDER BY selection_rank, symbol
        """)
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sql, {"as_of_date": as_of_date, "portfolio_name": portfolio_name}
            )
            .mappings()
            .all()
        ]


def _load_factor_scores(
    engine: Engine, as_of_date: date, symbols: List[str]
) -> Dict[str, Dict[str, Any]]:
    if not symbols:
        return {}
    sql = text(f"""
        SELECT
            symbol,
            quality_score,
            value_score,
            market_technical_score,
            sentiment_score,
            dividend_score,
            composite_alpha,
            regime,
            vix_level
        FROM {_SCHEMA}.feature_factor_scores
        WHERE as_of_date = :as_of_date
          AND symbol = ANY(:symbols)
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"as_of_date": as_of_date, "symbols": symbols}).mappings().all()
    return {str(row["symbol"]): dict(row) for row in rows}


def _load_overlay_lookup(
    engine: Engine, as_of_date: date, symbols: List[str]
) -> Dict[str, Dict[str, Any]]:
    if not symbols:
        return {}
    sql = text(f"""
        SELECT
            symbol,
            missing_factor_pct,
            factor_groups_present,
            pass_market_cap,
            pass_liquidity,
            pass_volatility,
            pass_factor_coverage,
            pass_data_quality,
            pass_all
        FROM {_SCHEMA}.feature_risk_overlay
        WHERE as_of_date = :as_of_date
          AND symbol = ANY(:symbols)
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"as_of_date": as_of_date, "symbols": symbols}).mappings().all()
    return {str(row["symbol"]): dict(row) for row in rows}


def _load_recommendation_header(
    engine: Engine,
    *,
    recommendation_id: str | None = None,
    recommendation_name: str | None = None,
) -> Dict[str, Any] | None:
    if recommendation_id:
        sql = text(f"""
            SELECT *
            FROM {_SCHEMA}.portfolio_recommendations
            WHERE recommendation_id = :recommendation_id
            """)
        params = {"recommendation_id": recommendation_id}
    else:
        sql = text(f"""
            SELECT *
            FROM {_SCHEMA}.portfolio_recommendations
            WHERE recommendation_name = :recommendation_name
            """)
        params = {"recommendation_name": recommendation_name}
    with engine.connect() as conn:
        row = conn.execute(sql, params).mappings().first()
    return dict(row) if row else None


def _load_recommendation_items(engine: Engine, recommendation_id: str) -> List[Dict[str, Any]]:
    sql = text(f"""
        SELECT *
        FROM {_SCHEMA}.portfolio_recommendation_items
        WHERE recommendation_id = :recommendation_id
        ORDER BY selection_rank, symbol
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"recommendation_id": recommendation_id}).mappings().all()
    return [dict(row) for row in rows]


def _load_recommendation_events(engine: Engine, recommendation_id: str) -> List[Dict[str, Any]]:
    sql = text(f"""
        SELECT *
        FROM {_SCHEMA}.portfolio_recommendation_events
        WHERE recommendation_id = :recommendation_id
        ORDER BY event_timestamp, id
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"recommendation_id": recommendation_id}).mappings().all()
    return [dict(row) for row in rows]


def _load_recommendation_decisions(engine: Engine, recommendation_id: str) -> List[Dict[str, Any]]:
    sql = text(f"""
        SELECT *
        FROM {_SCHEMA}.portfolio_recommendation_decisions
        WHERE recommendation_id = :recommendation_id
        ORDER BY decision_timestamp, id
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"recommendation_id": recommendation_id}).mappings().all()
    return [dict(row) for row in rows]


def _build_recommendation_header(
    *,
    recommendation_id: str,
    recommendation_name: str,
    as_of_date: date,
    portfolio_name: str,
    targets: List[Dict[str, Any]],
    factor_scores: Dict[str, Dict[str, Any]],
    overlay_lookup: Dict[str, Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    benchmark_ticker = str((config.get("backtest") or {}).get("benchmark_ticker", "SPY"))
    version_bundle = select_version_fields(
        resolve_version_bundle(config), RECOMMENDATION_VERSION_KEYS
    )
    regime = _first_non_null([row.get("regime") for row in targets]) or "normal"
    weighting_scheme = _first_non_null([row.get("weighting_scheme") for row in targets])
    ranking_mode = _first_non_null([row.get("ranking_mode") for row in targets])
    expected_turnover = sum(abs(_safe_float(row.get("trade_weight")) or 0.0) for row in targets)
    avg_alpha = _average([_safe_float(row.get("composite_alpha")) for row in targets])
    summary_json = _build_summary_json(
        targets, factor_scores, overlay_lookup, regime, version_bundle
    )
    config_snapshot = {
        "portfolio_construction": deepcopy(config.get("portfolio_construction") or {}),
        "regime": deepcopy(config.get("regime") or {}),
        "recommendation": deepcopy(config.get("recommendation") or {}),
        "governance": {"versions": version_bundle},
    }
    return {
        "recommendation_id": recommendation_id,
        "recommendation_name": recommendation_name,
        "as_of_date": as_of_date,
        "portfolio_name": portfolio_name,
        "recommendation_status": "proposed",
        "benchmark_ticker": benchmark_ticker,
        "regime": regime,
        "weighting_scheme": weighting_scheme,
        "ranking_mode": ranking_mode,
        "num_positions": len(targets),
        "gross_target_weight": sum(_safe_float(row.get("target_weight")) or 0.0 for row in targets),
        "expected_turnover": expected_turnover,
        "avg_composite_alpha": avg_alpha,
        **version_bundle,
        "config_snapshot": json.dumps(config_snapshot, sort_keys=True),
        "summary_json": json.dumps(summary_json, sort_keys=True),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "approved_at": None,
        "approved_by": None,
        "decision_notes": None,
    }


def _build_summary_json(
    targets: List[Dict[str, Any]],
    factor_scores: Dict[str, Dict[str, Any]],
    overlay_lookup: Dict[str, Dict[str, Any]],
    regime: str,
    version_bundle: Dict[str, str],
) -> Dict[str, Any]:
    sector_weights: Dict[str, float] = {}
    top_positions = []
    effective_bets = 0.0
    for row in targets:
        symbol = str(row["symbol"])
        weight = float(_safe_float(row.get("target_weight")) or 0.0)
        sector = str(row.get("gics_sector") or "Unknown")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weight
        effective_bets += weight * weight
        top_positions.append(
            {
                "symbol": symbol,
                "weight": weight,
                "alpha": _safe_float(row.get("composite_alpha")),
            }
        )
    top_positions.sort(key=lambda rec: (-float(rec["weight"]), str(rec["symbol"])))
    selected_overlay = [overlay_lookup.get(str(row["symbol"]), {}) for row in targets]
    avg_missing = _average([_safe_float(row.get("missing_factor_pct")) for row in selected_overlay])
    avg_groups = _average(
        [_safe_float(row.get("factor_groups_present")) for row in selected_overlay]
    )
    return {
        "regime": regime,
        "version_bundle": version_bundle,
        "sector_weights": {k: round(v, 8) for k, v in sorted(sector_weights.items())},
        "top_positions": top_positions[:5],
        "effective_number_of_positions": (
            round(1.0 / effective_bets, 4) if effective_bets > 0 else None
        ),
        "selected_avg_missing_factor_pct": avg_missing,
        "selected_avg_factor_groups_present": avg_groups,
        "selected_avg_quality_score": _average(
            [
                _safe_float(factor_scores.get(str(row["symbol"]), {}).get("quality_score"))
                for row in targets
            ]
        ),
        "selected_avg_value_score": _average(
            [
                _safe_float(factor_scores.get(str(row["symbol"]), {}).get("value_score"))
                for row in targets
            ]
        ),
        "selected_avg_market_technical_score": _average(
            [
                _safe_float(factor_scores.get(str(row["symbol"]), {}).get("market_technical_score"))
                for row in targets
            ]
        ),
        "selected_avg_sentiment_score": _average(
            [
                _safe_float(factor_scores.get(str(row["symbol"]), {}).get("sentiment_score"))
                for row in targets
            ]
        ),
        "selected_avg_dividend_score": _average(
            [
                _safe_float(factor_scores.get(str(row["symbol"]), {}).get("dividend_score"))
                for row in targets
            ]
        ),
    }


def _build_recommendation_quality_report(
    *,
    header: Dict[str, Any],
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total_weight = sum(float(_safe_float(item.get("target_weight")) or 0.0) for item in items)
    item_count = len(items)
    header_positions = int(header.get("num_positions") or 0)
    positive_weights = all(
        float(_safe_float(item.get("target_weight")) or 0.0) > 0.0 for item in items
    )
    rationale_present = all(bool(str(item.get("rationale_json") or "").strip()) for item in items)
    count_matches = header_positions == item_count
    weight_sum_near_one = abs(total_weight - 1.0) <= 0.05
    report = {
        "recommendation_id": str(header.get("recommendation_id") or ""),
        "recommendation_status": str(header.get("recommendation_status") or "unknown"),
        "as_of_date": (
            header["as_of_date"].isoformat()
            if isinstance(header.get("as_of_date"), date)
            else str(header.get("as_of_date") or "")
        ),
        "item_count": item_count,
        "header_num_positions": header_positions,
        "gross_target_weight": round(total_weight, 8),
        "max_single_weight": max(
            (float(_safe_float(item.get("target_weight")) or 0.0) for item in items),
            default=0.0,
        ),
        "item_count_matches_header": count_matches,
        "weight_sum_near_one": weight_sum_near_one,
        "all_items_positive_weight": positive_weights,
        "all_items_have_rationale": rationale_present,
    }
    report["passed"] = bool(
        item_count > 0
        and count_matches
        and weight_sum_near_one
        and positive_weights
        and rationale_present
    )
    return report


def _build_recommendation_items(
    *,
    recommendation_id: str,
    targets: List[Dict[str, Any]],
    factor_scores: Dict[str, Dict[str, Any]],
    overlay_lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in targets:
        symbol = str(row["symbol"])
        previous_weight = float(_safe_float(row.get("previous_weight")) or 0.0)
        target_weight = float(_safe_float(row.get("target_weight")) or 0.0)
        trade_weight = float(_safe_float(row.get("trade_weight")) or 0.0)
        factor_row = factor_scores.get(symbol, {})
        overlay_row = overlay_lookup.get(symbol, {})
        position_action = _classify_position_action(previous_weight, trade_weight, target_weight)
        rationale = {
            "position_action": position_action,
            "regime": row.get("regime"),
            "alpha_rank": row.get("selection_rank"),
            "trade_weight": trade_weight,
            "turnover_limited": bool(row.get("turnover_limited")),
            "risk_overlay": {
                "pass_all": overlay_row.get("pass_all"),
                "missing_factor_pct": _safe_float(overlay_row.get("missing_factor_pct")),
                "factor_groups_present": _safe_float(overlay_row.get("factor_groups_present")),
            },
            "factor_scores": {
                "quality": _safe_float(factor_row.get("quality_score")),
                "value": _safe_float(factor_row.get("value_score")),
                "market_technical": _safe_float(factor_row.get("market_technical_score")),
                "sentiment": _safe_float(factor_row.get("sentiment_score")),
                "dividend": _safe_float(factor_row.get("dividend_score")),
            },
        }
        items.append(
            {
                "recommendation_id": recommendation_id,
                "symbol": symbol,
                "selection_rank": row.get("selection_rank"),
                "target_weight": target_weight,
                "previous_weight": previous_weight,
                "trade_weight": trade_weight,
                "position_action": position_action,
                "composite_alpha": _safe_float(row.get("composite_alpha")),
                "quality_score": _safe_float(factor_row.get("quality_score")),
                "value_score": _safe_float(factor_row.get("value_score")),
                "market_technical_score": _safe_float(factor_row.get("market_technical_score")),
                "sentiment_score": _safe_float(factor_row.get("sentiment_score")),
                "dividend_score": _safe_float(factor_row.get("dividend_score")),
                "gics_sector": row.get("gics_sector"),
                "country": row.get("country"),
                "regime": row.get("regime"),
                "weighting_scheme": row.get("weighting_scheme"),
                "ranking_mode": row.get("ranking_mode"),
                "ranking_score": _safe_float(row.get("ranking_score")),
                "turnover_limited": bool(row.get("turnover_limited")),
                "rationale_json": json.dumps(rationale, sort_keys=True),
            }
        )
    return items


def _write_header(engine: Engine, row: Dict[str, Any]) -> None:
    sql = text(f"""
        INSERT INTO {_SCHEMA}.portfolio_recommendations (
            recommendation_id,
            recommendation_name,
            as_of_date,
            portfolio_name,
            recommendation_status,
            benchmark_ticker,
            regime,
            weighting_scheme,
            ranking_mode,
            num_positions,
            gross_target_weight,
            expected_turnover,
            avg_composite_alpha,
            model_version,
            factor_definition_version,
            covariance_method_version,
            risk_overlay_policy_version,
            recommendation_version,
            config_snapshot,
            summary_json,
            created_at,
            updated_at,
            approved_at,
            approved_by,
            decision_notes
        )
        VALUES (
            :recommendation_id,
            :recommendation_name,
            :as_of_date,
            :portfolio_name,
            :recommendation_status,
            :benchmark_ticker,
            :regime,
            :weighting_scheme,
            :ranking_mode,
            :num_positions,
            :gross_target_weight,
            :expected_turnover,
            :avg_composite_alpha,
            :model_version,
            :factor_definition_version,
            :covariance_method_version,
            :risk_overlay_policy_version,
            :recommendation_version,
            CAST(:config_snapshot AS JSONB),
            CAST(:summary_json AS JSONB),
            :created_at,
            :updated_at,
            :approved_at,
            :approved_by,
            :decision_notes
        )
        """)
    with engine.begin() as conn:
        conn.execute(sql, row)


def _write_items(engine: Engine, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    sql = text(f"""
        INSERT INTO {_SCHEMA}.portfolio_recommendation_items (
            recommendation_id,
            symbol,
            selection_rank,
            target_weight,
            previous_weight,
            trade_weight,
            position_action,
            composite_alpha,
            quality_score,
            value_score,
            market_technical_score,
            sentiment_score,
            dividend_score,
            gics_sector,
            country,
            regime,
            weighting_scheme,
            ranking_mode,
            ranking_score,
            turnover_limited,
            rationale_json
        )
        VALUES (
            :recommendation_id,
            :symbol,
            :selection_rank,
            :target_weight,
            :previous_weight,
            :trade_weight,
            :position_action,
            :composite_alpha,
            :quality_score,
            :value_score,
            :market_technical_score,
            :sentiment_score,
            :dividend_score,
            :gics_sector,
            :country,
            :regime,
            :weighting_scheme,
            :ranking_mode,
            :ranking_score,
            :turnover_limited,
            CAST(:rationale_json AS JSONB)
        )
        """)
    with engine.begin() as conn:
        conn.execute(sql, rows)


def _write_events(engine: Engine, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    sql = text(f"""
        INSERT INTO {_SCHEMA}.portfolio_recommendation_events (
            recommendation_id,
            event_type,
            event_timestamp,
            actor,
            notes,
            payload_json
        )
        VALUES (
            :recommendation_id,
            :event_type,
            :event_timestamp,
            :actor,
            :notes,
            CAST(:payload_json AS JSONB)
        )
        """)
    with engine.begin() as conn:
        conn.execute(sql, rows)


def _write_decisions(engine: Engine, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    sql = text(f"""
        INSERT INTO {_SCHEMA}.portfolio_recommendation_decisions (
            recommendation_id,
            decision_type,
            actor,
            decision_timestamp,
            notes,
            payload_json
        )
        VALUES (
            :recommendation_id,
            :decision_type,
            :actor,
            :decision_timestamp,
            :notes,
            CAST(:payload_json AS JSONB)
        )
        """)
    with engine.begin() as conn:
        conn.execute(sql, rows)


def _update_recommendation_status(engine: Engine, row: Dict[str, Any]) -> None:
    sql = text(f"""
        UPDATE {_SCHEMA}.portfolio_recommendations
        SET recommendation_status = :recommendation_status,
            approved_at = :approved_at,
            approved_by = :approved_by,
            decision_notes = :decision_notes,
            updated_at = :updated_at
        WHERE recommendation_id = :recommendation_id
        """)
    with engine.begin() as conn:
        conn.execute(sql, row)


def _resolve_recommendation_status_transition(
    *,
    current_status: str,
    decision_type: str,
    approval_required: bool,
) -> str:
    if current_status == "published":
        raise ValueError(
            "Published recommendations are immutable and cannot receive further decisions"
        )
    if decision_type == "approve":
        if current_status == "rejected":
            raise ValueError(
                "Rejected recommendations cannot be approved without republishing a new recommendation"
            )
        return "approved"
    if decision_type == "reject":
        if current_status == "published":
            raise ValueError("Published recommendations cannot be rejected")
        return "rejected"
    if decision_type == "publish":
        if approval_required and current_status != "approved":
            raise ValueError("Recommendation must be approved before it can be published")
        if current_status == "rejected":
            raise ValueError("Rejected recommendations cannot be published")
        return "published"
    raise ValueError(f"Unsupported recommendation decision_type={decision_type}")


def _decision_to_event_type(decision_type: str) -> str:
    return {
        "approve": "approved",
        "reject": "rejected",
        "publish": "published",
    }[decision_type]


def _classify_position_action(
    previous_weight: float, trade_weight: float, target_weight: float
) -> str:
    eps = 1.0e-10
    if previous_weight <= eps and target_weight > eps:
        return "new_entry"
    if trade_weight > eps:
        return "increase"
    if trade_weight < -eps:
        return "decrease"
    return "hold"


def _average(values: List[Optional[float]]) -> Optional[float]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_recommendation_name(*, as_of_date: date, portfolio_name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{portfolio_name}_{as_of_date.isoformat()}_{ts}"


def _first_non_null(values: List[Any]) -> Optional[str]:
    for value in values:
        if value is not None and str(value).strip():
            return str(value)
    return None


def _decode_recommendation_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key in ("config_snapshot", "summary_json", "rationale_json", "payload_json"):
        value = out.get(key)
        if isinstance(value, str):
            try:
                out[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return out
