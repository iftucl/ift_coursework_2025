from __future__ import annotations

__all__ = [
    "normalize_records",
    "normalize_financial_records",
    "run_quality_checks",
    "load_curated",
    "load_financial_observations",
]


def __getattr__(name: str):
    if name == "normalize_records":
        from .normalize import normalize_records

        return normalize_records
    if name == "normalize_financial_records":
        from .normalize import normalize_financial_records

        return normalize_financial_records
    if name == "run_quality_checks":
        from .quality import run_quality_checks

        return run_quality_checks
    if name == "load_curated":
        from .load import load_curated

        return load_curated
    if name == "load_financial_observations":
        from .load import load_financial_observations

        return load_financial_observations
    raise AttributeError(name)
