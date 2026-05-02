from __future__ import annotations

"""Shared PIT time semantics helpers for CW1/CW2 transform code."""

import os


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def financial_publish_fallback_enabled() -> bool:
    """Return whether legacy financial publish-date fallback remains enabled.

    Strict mode is the default. When disabled, downstream readers treat
    ``publish_date`` as the only PIT availability field for
    ``financial_observations``. Setting ``CW1_ALLOW_FINANCIAL_PUBLISH_FALLBACK``
    restores the legacy compatibility path through ``as_of`` and ``report_date``.
    """

    return _env_flag("CW1_ALLOW_FINANCIAL_PUBLISH_FALLBACK", default=False)


def financial_publish_value_expr(
    *,
    publish_col: str = "publish_date",
    as_of_col: str = "as_of",
    report_col: str = "report_date",
) -> str:
    """Return the SQL expression used to read financial availability dates."""

    if financial_publish_fallback_enabled():
        return f"COALESCE({publish_col}, {as_of_col}, {report_col})"
    return publish_col


def financial_publish_cutoff_predicate(
    cutoff_param: str,
    *,
    publish_col: str = "publish_date",
    as_of_col: str = "as_of",
    report_col: str = "report_date",
) -> str:
    """Return the SQL predicate enforcing PIT cutoff on financial rows."""

    cutoff_param = str(cutoff_param).strip()
    if not cutoff_param:
        raise ValueError("financial publish cutoff requires cutoff_param")
    expr = financial_publish_value_expr(
        publish_col=publish_col,
        as_of_col=as_of_col,
        report_col=report_col,
    )
    return f"{expr} <= :{cutoff_param}"
