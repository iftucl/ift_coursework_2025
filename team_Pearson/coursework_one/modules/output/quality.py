from __future__ import annotations

"""Quality checks for normalized factor observation records."""

from typing import Any, Dict, List, Optional, Tuple

from .data_contract import ALLOWED_FREQUENCIES


def _is_missing_required(r: Dict[str, Any]) -> bool:
    """Return True when required record fields are missing/blank."""
    return (
        not r.get("symbol")
        or not r.get("observation_date")
        or not r.get("factor_name")
        or not r.get("source")
        or not r.get("metric_frequency")
    )


def _is_invalid_frequency(freq: Optional[str]) -> bool:
    """Return True when frequency is missing or outside allowed set."""
    if freq is None:
        return True
    return str(freq).strip().lower() not in ALLOWED_FREQUENCIES


def _is_non_finite_number(x: Any) -> bool:
    """Return True for non-numeric, NaN, or infinite numeric values."""
    # factor_value should be float or None after normalize; still guard.
    if x is None:
        return False
    if not isinstance(x, (int, float)):
        return True
    try:
        # NaN or inf checks
        if x != x:
            return True
        if x == float("inf") or x == float("-inf"):
            return True
    except Exception:
        return True
    return False


def run_quality_checks(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run data quality checks and return a summary report.

    Parameters
    ----------
    records:
        Normalized records from :func:`modules.output.normalize.normalize_records`.

    Returns
    -------
    dict[str, Any]
        Quality report with counts such as ``row_count``, ``missing_values``,
        ``duplicates``, ``missing_required``, ``invalid_frequency``,
        ``non_numeric_or_non_finite``, and ``passed``.
    """
    row_count = len(records)
    missing_values = sum(1 for r in records if r.get("factor_value") is None)
    missing_required = sum(1 for r in records if _is_missing_required(r))
    invalid_frequency = sum(1 for r in records if _is_invalid_frequency(r.get("metric_frequency")))
    non_numeric_or_non_finite = sum(
        1 for r in records if _is_non_finite_number(r.get("factor_value"))
    )

    # Duplicates by DB unique key
    seen: set[Tuple[Any, Any, Any]] = set()
    duplicates = 0
    for r in records:
        key = (r.get("symbol"), r.get("factor_name"), r.get("observation_date"))
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)

    # Overall pass/fail (simple, explainable)
    passed = (missing_required == 0) and (invalid_frequency == 0)

    return {
        "row_count": row_count,
        "missing_values": missing_values,
        "duplicates": duplicates,
        "missing_required": missing_required,
        "invalid_frequency": invalid_frequency,
        "non_numeric_or_non_finite": non_numeric_or_non_finite,
        "passed": passed,
    }
