from __future__ import annotations

"""Normalization helpers for curated pipeline records."""

import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional


def _to_iso_date(x: Any) -> Optional[str]:
    """
    Convert common date-like inputs to 'YYYY-MM-DD' string.
    Returns None if input is None/empty.
    """
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date().isoformat()
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        if s.lower() in {"nat", "nan", "none", "null"}:
            return None
        # Best-effort: accept 'YYYY-MM-DD...' (with time)
        return s[:10]
    # Unknown type -> keep None so quality can flag missing/invalid
    return None


def _to_float_or_none(x: Any) -> Optional[float]:
    """
    Convert to float when possible.
    Treat '', 'nan', 'None' as None. Return None on unparseable values.
    """
    if x is None:
        return None
    if isinstance(x, (int, float)):
        if not math.isfinite(float(x)):
            return None
        return float(x)

    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        if s.lower() in {"nan", "none", "null"}:
            return None
        # remove common thousands separators
        s = s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None

    # Unhandled type
    return None


def normalize_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize records into the shared output schema.

    Parameters
    ----------
    records:
        Raw records from extractors. Field aliases are tolerated (for example
        ``value`` or ``factor_value``).

    Returns
    -------
    list[dict[str, Any]]
        Records with standardized keys and types:
        ``symbol``, ``observation_date``, ``factor_name``, ``factor_value``,
        ``source``, ``metric_frequency``, ``source_report_date``, ``run_id``.
    """
    normalized: List[Dict[str, Any]] = []

    for rec in records:
        symbol = rec.get("symbol")

        obs_date_raw = rec.get("observation_date") or rec.get("date") or rec.get("as_of")
        observation_date = _to_iso_date(obs_date_raw)

        factor_name = rec.get("factor_name") or rec.get("metric") or "unknown_factor"

        # Prefer explicit factor_value if present, otherwise fall back to value
        raw_value = rec.get("factor_value") if "factor_value" in rec else rec.get("value")
        factor_value = _to_float_or_none(raw_value)

        source = rec.get("source", "unknown")

        freq = rec.get("metric_frequency") or rec.get("frequency") or "unknown"
        metric_frequency = str(freq).strip().lower() if freq is not None else "unknown"

        source_report_date = _to_iso_date(rec.get("source_report_date"))

        # Invalid observation_date rows are dropped at contract boundary.
        if observation_date is None:
            continue

        normalized.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": factor_name,
                "factor_value": factor_value,
                "source": source,
                "metric_frequency": metric_frequency,
                "source_report_date": source_report_date,
                "run_id": rec.get("run_id"),
            }
        )

    return normalized


def normalize_financial_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize atomic financial records for ``financial_observations``."""
    normalized: List[Dict[str, Any]] = []

    for rec in records:
        symbol = rec.get("symbol")
        metric_name = rec.get("metric_name") or rec.get("factor_name")
        metric_name = str(metric_name).strip() if metric_name is not None else ""
        if not metric_name:
            continue

        # Financial atomics must carry a real filing date.
        # Never infer it from observation/as-of date.
        report_date = _to_iso_date(rec.get("report_date") or rec.get("source_report_date"))
        as_of = _to_iso_date(rec.get("as_of") or rec.get("observation_date"))
        metric_value = _to_float_or_none(
            rec.get("metric_value") if "metric_value" in rec else rec.get("value")
        )

        currency = str(rec.get("currency") or "unknown").strip().upper()
        if not currency:
            currency = "UNKNOWN"

        period_type = (
            str(
                rec.get("period_type")
                or rec.get("metric_frequency")
                or rec.get("frequency")
                or "unknown"
            )
            .strip()
            .lower()
        )
        metric_definition = (
            str(rec.get("metric_definition") or rec.get("definition") or "provider_reported")
            .strip()
            .lower()
        )
        source = rec.get("source", "unknown")

        if report_date is None:
            continue

        normalized.append(
            {
                "symbol": symbol,
                "report_date": report_date,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "currency": currency,
                "period_type": period_type,
                "source": source,
                "as_of": as_of,
                "metric_definition": metric_definition,
                "run_id": rec.get("run_id"),
            }
        )

    return normalized
