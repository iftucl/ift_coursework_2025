from __future__ import annotations

"""Quality checks for normalized factor observation records."""

from dataclasses import dataclass, field
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


@dataclass
class QualityAccumulator:
    """Incrementally accumulate quality metrics across record batches."""

    row_count: int = 0
    missing_values: int = 0
    missing_required: int = 0
    invalid_frequency: int = 0
    non_numeric_or_non_finite: int = 0
    duplicates: int = 0
    _seen: set[Tuple[Any, Any, Any]] = field(default_factory=set)

    def update(self, records: List[Dict[str, Any]]) -> None:
        """Update counters with one normalized record batch."""
        for record in records:
            self.row_count += 1
            if record.get("factor_value") is None:
                self.missing_values += 1
            if _is_missing_required(record):
                self.missing_required += 1
            if _is_invalid_frequency(record.get("metric_frequency")):
                self.invalid_frequency += 1
            if _is_non_finite_number(record.get("factor_value")):
                self.non_numeric_or_non_finite += 1

            key = (
                record.get("symbol"),
                record.get("factor_name"),
                record.get("observation_date"),
            )
            if key in self._seen:
                self.duplicates += 1
            else:
                self._seen.add(key)

    def update_report(self, report: Dict[str, Any]) -> None:
        """Merge a previously computed per-unit quality report into the totals."""
        self.row_count += int(report.get("row_count", 0) or 0)
        self.missing_values += int(report.get("missing_values", 0) or 0)
        self.missing_required += int(report.get("missing_required", 0) or 0)
        self.invalid_frequency += int(report.get("invalid_frequency", 0) or 0)
        self.non_numeric_or_non_finite += int(report.get("non_numeric_or_non_finite", 0) or 0)
        self.duplicates += int(report.get("duplicates", 0) or 0)

    def report(self) -> Dict[str, Any]:
        """Return the accumulated quality report using the legacy schema."""
        passed = (self.missing_required == 0) and (self.invalid_frequency == 0)
        return {
            "row_count": self.row_count,
            "missing_values": self.missing_values,
            "duplicates": self.duplicates,
            "missing_required": self.missing_required,
            "invalid_frequency": self.invalid_frequency,
            "non_numeric_or_non_finite": self.non_numeric_or_non_finite,
            "passed": passed,
        }


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
    accumulator = QualityAccumulator()
    accumulator.update(records)
    return accumulator.report()
