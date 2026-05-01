from __future__ import annotations

"""Runtime source-coverage contract helpers for CW1 orchestration."""

from typing import Any, Dict, Iterable, List, Optional

from modules.input.extract_source_a import _select_provider_order_for_symbol
from modules.input.extract_source_b import _filter_symbols_for_source_b
from modules.input.symbol_filter import filter_symbols

_SOURCE_A = "source_a"
_SOURCE_B = "source_b"


def initialize_source_coverage_contract(
    *,
    universe: List[str],
    config: Optional[Dict[str, Any]],
    enabled_extractors: Iterable[str],
    source_b_expected_windows: int,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Build per-source symbol coverage expectations before extraction starts."""
    cfg = config or {}
    enabled = {str(item).strip().lower() for item in enabled_extractors if str(item).strip()}
    ordered_universe = _dedupe_symbols(universe)

    source_a_policy = set(
        filter_symbols(
            symbols=ordered_universe,
            config=cfg,
            section=None,
            default_skip_suffix=True,
            default_regex=r"^[A-Z0-9]+$",
        )
    )
    source_b_policy = set(_filter_symbols_for_source_b(ordered_universe, cfg))

    tracker = {_SOURCE_A: {}, _SOURCE_B: {}}
    for symbol in ordered_universe:
        tracker[_SOURCE_A][symbol] = _build_source_a_row(
            symbol=symbol,
            config=cfg,
            source_a_policy=source_a_policy,
            enabled=_SOURCE_A in enabled,
        )
        tracker[_SOURCE_B][symbol] = _build_source_b_row(
            symbol=symbol,
            source_b_policy=source_b_policy,
            enabled=_SOURCE_B in enabled,
            expected_windows=source_b_expected_windows,
        )
    return tracker


def mark_source_a_result(
    tracker: Dict[str, Dict[str, Dict[str, Any]]],
    symbol: str,
    *,
    outcome: str,
    raw_records: int = 0,
    loaded_rows: int = 0,
    reason: Optional[str] = None,
) -> None:
    """Record one source_a symbol outcome."""
    state = _lookup_state(tracker, _SOURCE_A, symbol)
    if state is None or not state.get("expected_in_run"):
        return

    details = dict(state.get("details") or {})
    details["raw_records"] = int(details.get("raw_records") or 0) + int(raw_records)
    details["loaded_rows"] = int(details.get("loaded_rows") or 0) + int(loaded_rows)
    if reason:
        details["last_reason"] = str(reason)
    state["details"] = details

    normalized = str(outcome or "").strip().lower()
    if normalized in {"reused", "success"}:
        state["realized_in_run"] = True
        state["content_available"] = bool(
            int(details.get("raw_records") or 0) > 0 or int(details.get("loaded_rows") or 0) > 0
        )
        state["status"] = "aligned" if state["content_available"] else "realized_empty"
        state["reason_code"] = (
            "materialization_reused" if normalized == "reused" else "source_a_processed"
        )
        return

    if normalized == "failed":
        state["status"] = "missing_or_failed"
        state["reason_code"] = "source_a_failed"
        return

    if normalized == "skipped":
        reason_text = str(reason or "").strip().lower()
        if "unavailable" in reason_text or "no_data" in reason_text or "no data" in reason_text:
            state["realized_in_run"] = True
            state["content_available"] = False
            state["status"] = "realized_empty"
            state["reason_code"] = "source_a_unavailable_or_empty"
            return
        state["status"] = "missing_or_failed"
        state["reason_code"] = "source_a_unexpected_skip"


def mark_source_b_window_result(
    tracker: Dict[str, Dict[str, Dict[str, Any]]],
    symbol: str,
    *,
    outcome: str,
    article_count: int = 0,
    loaded_rows: int = 0,
    reason: Optional[str] = None,
) -> None:
    """Record one source_b symbol-month outcome."""
    state = _lookup_state(tracker, _SOURCE_B, symbol)
    if state is None or not state.get("expected_in_run"):
        return

    details = dict(state.get("details") or {})
    details["articles_observed"] = int(details.get("articles_observed") or 0) + int(article_count)
    details["loaded_rows"] = int(details.get("loaded_rows") or 0) + int(loaded_rows)
    if reason:
        failures = list(details.get("failure_reasons") or [])
        if len(failures) < 5:
            failures.append(str(reason))
        details["failure_reasons"] = failures

    normalized = str(outcome or "").strip().lower()
    if normalized == "reused":
        details["reused_windows"] = int(details.get("reused_windows") or 0) + 1
    elif normalized == "success":
        details["succeeded_windows"] = int(details.get("succeeded_windows") or 0) + 1
    elif normalized == "failed":
        details["failed_windows"] = int(details.get("failed_windows") or 0) + 1
    state["details"] = details


def finalize_source_coverage_contract(
    tracker: Dict[str, Dict[str, Dict[str, Any]]],
    *,
    config: Optional[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Finalize per-symbol rows and compute one run-level coverage report."""
    cfg = dict((config or {}).get("source_coverage_contract") or {})
    rows: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {"sources": {}}

    for source_name in (_SOURCE_A, _SOURCE_B):
        source_rows = []
        for state in tracker.get(source_name, {}).values():
            finalized = _finalize_row(source_name=source_name, state=state)
            source_rows.append(finalized)
            rows.append(finalized)
        summary["sources"][source_name] = _summarize_source_rows(source_rows)

    max_missing_source_a = int(cfg.get("max_missing_source_a_symbols", 0))
    max_missing_source_b = int(cfg.get("max_missing_source_b_symbols", 0))
    source_a_missing = int(summary["sources"][_SOURCE_A]["unexpected_missing_count"])
    source_b_missing = int(summary["sources"][_SOURCE_B]["unexpected_missing_count"])
    failures: List[str] = []
    if source_a_missing > max_missing_source_a:
        failures.append(
            f"source_a_unexpected_missing={source_a_missing}>max_missing_source_a_symbols={max_missing_source_a}"
        )
    if source_b_missing > max_missing_source_b:
        failures.append(
            f"source_b_unexpected_missing={source_b_missing}>max_missing_source_b_symbols={max_missing_source_b}"
        )
    summary.update(
        {
            "max_missing_source_a_symbols": max_missing_source_a,
            "max_missing_source_b_symbols": max_missing_source_b,
            "failures": failures,
            "passed": not failures,
        }
    )
    return rows, summary


def summarize_source_coverage_counts(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact detail payload for stage and refresh events."""
    source_a = dict((report.get("sources") or {}).get(_SOURCE_A) or {})
    source_b = dict((report.get("sources") or {}).get(_SOURCE_B) or {})
    return {
        "passed": bool(report.get("passed")),
        "failures": list(report.get("failures") or []),
        "source_a": {
            "expected_count": int(source_a.get("expected_count") or 0),
            "realized_count": int(source_a.get("realized_count") or 0),
            "unexpected_missing_count": int(source_a.get("unexpected_missing_count") or 0),
        },
        "source_b": {
            "expected_count": int(source_b.get("expected_count") or 0),
            "realized_count": int(source_b.get("realized_count") or 0),
            "unexpected_missing_count": int(source_b.get("unexpected_missing_count") or 0),
            "realized_empty_count": int(source_b.get("realized_empty_count") or 0),
        },
    }


def _build_source_a_row(
    *,
    symbol: str,
    config: Dict[str, Any],
    source_a_policy: set[str],
    enabled: bool,
) -> Dict[str, Any]:
    row = _base_row(symbol=symbol, source_name=_SOURCE_A)
    if not enabled:
        row["status"] = "stage_disabled"
        row["reason_code"] = "source_a_stage_disabled"
        return row
    if symbol not in source_a_policy:
        row["status"] = "excluded_by_policy"
        row["reason_code"] = "symbol_filter_policy"
        return row
    row["policy_eligible"] = True
    provider_order = _select_provider_order_for_symbol(symbol, config)
    row["details"]["provider_order"] = list(provider_order)
    if not provider_order:
        row["routing_eligible"] = False
        row["status"] = "excluded_by_routing"
        row["reason_code"] = "no_provider_route"
        return row
    row["expected_in_run"] = True
    row["status"] = "expected"
    row["reason_code"] = "scheduled"
    return row


def _build_source_b_row(
    *,
    symbol: str,
    source_b_policy: set[str],
    enabled: bool,
    expected_windows: int,
) -> Dict[str, Any]:
    row = _base_row(symbol=symbol, source_name=_SOURCE_B)
    row["details"]["expected_windows"] = int(max(0, expected_windows))
    if not enabled:
        row["status"] = "stage_disabled"
        row["reason_code"] = "source_b_stage_disabled"
        return row
    if symbol not in source_b_policy:
        row["status"] = "excluded_by_policy"
        row["reason_code"] = "symbol_filter_policy"
        return row
    row["policy_eligible"] = True
    row["expected_in_run"] = True
    row["status"] = "expected"
    row["reason_code"] = "scheduled"
    return row


def _base_row(*, symbol: str, source_name: str) -> Dict[str, Any]:
    return {
        "source_name": source_name,
        "symbol": str(symbol).strip().upper(),
        "parent_in_universe": True,
        "policy_eligible": False,
        "routing_eligible": True,
        "expected_in_run": False,
        "realized_in_run": False,
        "content_available": None,
        "status": "not_scheduled",
        "reason_code": "not_scheduled",
        "details": {},
    }


def _dedupe_symbols(symbols: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _lookup_state(
    tracker: Dict[str, Dict[str, Dict[str, Any]]], source_name: str, symbol: str
) -> Optional[Dict[str, Any]]:
    return (tracker.get(source_name) or {}).get(str(symbol).strip().upper())


def _finalize_row(*, source_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(state)
    details = dict(row.get("details") or {})
    if not row.get("expected_in_run"):
        row["content_available"] = (
            bool(row["content_available"]) if row.get("content_available") is not None else None
        )
        row["details"] = details
        return row

    if source_name == _SOURCE_A:
        if not row.get("realized_in_run"):
            row["status"] = "missing_or_failed"
            row["reason_code"] = row.get("reason_code") or "source_a_missing_execution"
        row["content_available"] = bool(row.get("content_available"))
        row["details"] = details
        return row

    expected_windows = int(details.get("expected_windows") or 0)
    completed_windows = int(details.get("reused_windows") or 0) + int(
        details.get("succeeded_windows") or 0
    )
    failed_windows = int(details.get("failed_windows") or 0)
    if failed_windows > 0:
        row["status"] = "missing_or_failed"
        row["reason_code"] = "failed_windows_present"
        row["realized_in_run"] = False
    elif completed_windows < expected_windows:
        row["status"] = "missing_or_failed"
        row["reason_code"] = "incomplete_window_coverage"
        row["realized_in_run"] = False
    else:
        row["realized_in_run"] = True
        row["content_available"] = bool(
            int(details.get("articles_observed") or 0) > 0
            or int(details.get("loaded_rows") or 0) > 0
        )
        row["status"] = "aligned" if row["content_available"] else "realized_empty"
        row["reason_code"] = (
            "articles_observed" if row["content_available"] else "no_articles_in_window"
        )
    if row.get("content_available") is None:
        row["content_available"] = False
    row["details"] = details
    return row


def _summarize_source_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    parent_count = len(rows)
    expected_rows = [row for row in rows if row.get("expected_in_run")]
    realized_rows = [row for row in expected_rows if row.get("realized_in_run")]
    policy_excluded_rows = [row for row in rows if row.get("status") == "excluded_by_policy"]
    routing_excluded_rows = [row for row in rows if row.get("status") == "excluded_by_routing"]
    missing_rows = [row for row in expected_rows if not row.get("realized_in_run")]
    realized_empty_rows = [row for row in realized_rows if not row.get("content_available")]
    content_rows = [row for row in realized_rows if row.get("content_available")]
    return {
        "parent_universe_count": parent_count,
        "policy_eligible_count": sum(1 for row in rows if row.get("policy_eligible")),
        "routing_eligible_count": sum(1 for row in rows if row.get("routing_eligible")),
        "expected_count": len(expected_rows),
        "realized_count": len(realized_rows),
        "content_available_count": len(content_rows),
        "realized_empty_count": len(realized_empty_rows),
        "policy_excluded_count": len(policy_excluded_rows),
        "routing_excluded_count": len(routing_excluded_rows),
        "unexpected_missing_count": len(missing_rows),
        "unexpected_missing_symbols": [str(row["symbol"]) for row in missing_rows[:20]],
        "policy_excluded_symbols": [str(row["symbol"]) for row in policy_excluded_rows[:20]],
        "routing_excluded_symbols": [str(row["symbol"]) for row in routing_excluded_rows[:20]],
    }
