from __future__ import annotations

"""Company universe access layer for PostgreSQL."""

import os
from typing import List, Optional

from sqlalchemy import text

from .db_connection import get_db_engine

UNIVERSE_SELECT_SQL = {
    "company_static": """
    SELECT DISTINCT symbol
    FROM systematic_equity.company_static
    {where_clause}
    ORDER BY symbol
    """,
    "equity_static": """
    SELECT DISTINCT symbol
    FROM systematic_equity.equity_static
    {where_clause}
    ORDER BY symbol
    """,
}

UNIVERSE_COUNT_SQL = {
    "company_static": text("SELECT COUNT(*) FROM systematic_equity.company_static;"),
    "equity_static": text("SELECT COUNT(*) FROM systematic_equity.equity_static;"),
}


def _test_mode_symbols(limit: Optional[int]) -> list[str]:
    """Return deterministic symbol sample for test mode runs."""
    symbols = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA"]
    if limit is None:
        return symbols
    return symbols[:limit]


def _normalize_country_allowlist(country_allowlist: Optional[object]) -> List[str]:
    """Normalize country allowlist into unique uppercase codes."""
    if not country_allowlist:
        return []
    if isinstance(country_allowlist, str):
        items = [x for x in country_allowlist.split(",")]
    elif isinstance(country_allowlist, list):
        items = country_allowlist
    else:
        raise ValueError(
            "Invalid country_allowlist="
            f"{country_allowlist!r}. Expected list or comma-separated string."
        )
    out = []
    for country in items:
        c = str(country).strip().upper()
        if c and c not in out:
            out.append(c)
    return out


def _dedupe_symbols(symbols: List[str]) -> List[str]:
    """Deduplicate symbols while preserving original order."""
    seen = set()
    out: List[str] = []
    for raw in symbols:
        s = str(raw).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _apply_universe_overrides(
    base_symbols: List[str],
    override_rows: List[tuple[str, str, bool]],
) -> List[str]:
    """Apply include/exclude overrides on top of base universe symbols."""
    base_set = {str(s).strip().upper() for s in base_symbols if str(s).strip()}
    final_set = set(base_set)

    include_symbols: List[str] = []
    for raw_symbol, raw_action, raw_is_active in override_rows:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        action = str(raw_action or "").strip().lower()
        is_active = bool(raw_is_active)

        if action == "exclude":
            if is_active:
                final_set.discard(symbol)
            continue
        if action == "include":
            if is_active:
                final_set.add(symbol)
                include_symbols.append(symbol)
            continue

    # Keep base order first, then additional include symbols in alpha order.
    base_ordered = [s for s in base_symbols if str(s).strip().upper() in final_set]
    included_only = sorted(
        s for s in {str(x).strip().upper() for x in include_symbols} if s not in base_set
    )
    out = [str(s).strip().upper() for s in base_ordered]
    out.extend(included_only)
    return _dedupe_symbols(out)


def get_company_universe(
    company_limit: Optional[int], country_allowlist: Optional[object] = None
) -> list[str]:
    """Return company symbols from ``systematic_equity.company_static``.

    Parameters
    ----------
    company_limit:
        Maximum number of symbols to return. ``None`` or values ``<=0`` mean unlimited.
    country_allowlist:
        Optional list of country codes (e.g., ``["US", "GB"]``). If provided,
        only symbols from those countries are returned.

    Returns
    -------
    list[str]
        Ordered list of symbols. In test mode (``CW1_TEST_MODE=1``), returns a
        deterministic stub list.
    """
    limit: Optional[int]
    if company_limit is None:
        limit = None
    else:
        parsed_limit = int(company_limit)
        limit = None if parsed_limit <= 0 else parsed_limit
    countries = _normalize_country_allowlist(country_allowlist)

    if os.getenv("CW1_TEST_MODE") == "1":
        return _test_mode_symbols(limit)

    engine = get_db_engine()
    with engine.connect() as conn:
        errors = []
        for table_name in ("company_static", "equity_static"):
            params = {}
            where_clause = ""
            if countries:
                placeholders = []
                for i, country in enumerate(countries):
                    key = f"country_{i}"
                    placeholders.append(f":{key}")
                    params[key] = country
                where_clause = f"WHERE country IN ({', '.join(placeholders)})"

            sql = text(UNIVERSE_SELECT_SQL[table_name].format(where_clause=where_clause))
            try:
                rows = conn.execute(sql, params).fetchall()
                base_symbols = _dedupe_symbols([str(r[0]).strip().upper() for r in rows])

                try:
                    override_rows = conn.execute(
                        text(
                            """
                            SELECT symbol, action, is_active
                            FROM systematic_equity.company_universe_overrides
                            """
                        )
                    ).fetchall()
                    merged = _apply_universe_overrides(base_symbols, list(override_rows))
                except Exception:
                    merged = base_symbols

                if limit is not None:
                    return merged[:limit]
                return merged
            except Exception as exc:
                errors.append(f"{table_name}: {exc}")

    raise RuntimeError(
        "Unable to read universe table from PostgreSQL. Tried "
        "systematic_equity.company_static and systematic_equity.equity_static. "
        "Run seed script: `poetry run python scripts/seed_universe_from_sqlite.py`. "
        f"Details: {errors}"
    )


def get_company_count() -> int:
    """
    Return total number of companies in systematic_equity.company_static.
    """
    if os.getenv("CW1_TEST_MODE") == "1":
        return len(_test_mode_symbols(10_000))

    engine = get_db_engine()
    with engine.connect() as conn:
        errors = []
        for table_name in ("company_static", "equity_static"):
            sql = UNIVERSE_COUNT_SQL[table_name]
            try:
                return int(conn.execute(sql).scalar_one())
            except Exception as exc:
                errors.append(f"{table_name}: {exc}")

    raise RuntimeError(
        "Unable to count universe rows from PostgreSQL. Tried "
        "systematic_equity.company_static and systematic_equity.equity_static. "
        "Run seed script: `poetry run python scripts/seed_universe_from_sqlite.py`. "
        f"Details: {errors}"
    )


if __name__ == "__main__":
    total = get_company_count()
    top10 = get_company_universe(10)

    print(f"Company count: {total}")
    print("Top 10 company symbols:")
    for symbol in top10:
        print(symbol)
