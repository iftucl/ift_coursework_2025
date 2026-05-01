from __future__ import annotations

"""Manage dynamic company universe overrides."""

import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import text

from modules.db import get_db_engine


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _ensure_table() -> None:
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS systematic_equity.company_universe_overrides (
                    symbol VARCHAR(50) PRIMARY KEY,
                    action VARCHAR(20) NOT NULL
                        CHECK (action IN ('include', 'exclude')),
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    reason TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_company_universe_overrides_action_active
                ON systematic_equity.company_universe_overrides (action, is_active)
                """
            )
        )


def _upsert(symbol: str, action: str, is_active: bool, reason: str) -> None:
    _ensure_table()
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO systematic_equity.company_universe_overrides
                    (symbol, action, is_active, reason, updated_at)
                VALUES
                    (:symbol, :action, :is_active, :reason, :updated_at)
                ON CONFLICT (symbol) DO UPDATE SET
                    action = EXCLUDED.action,
                    is_active = EXCLUDED.is_active,
                    reason = EXCLUDED.reason,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "symbol": symbol,
                "action": action,
                "is_active": is_active,
                "reason": reason or None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )


def _remove(symbol: str) -> None:
    _ensure_table()
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM systematic_equity.company_universe_overrides
                WHERE symbol = :symbol
                """
            ),
            {"symbol": symbol},
        )


def _list_rows(active_only: bool) -> None:
    _ensure_table()
    engine = get_db_engine()
    with engine.connect() as conn:
        if active_only:
            rows = conn.execute(
                text(
                    """
                    SELECT symbol, action, is_active, reason, updated_at
                    FROM systematic_equity.company_universe_overrides
                    WHERE is_active = TRUE
                    ORDER BY symbol
                    """
                )
            ).fetchall()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT symbol, action, is_active, reason, updated_at
                    FROM systematic_equity.company_universe_overrides
                    ORDER BY symbol
                    """
                )
            ).fetchall()

    if not rows:
        print("No overrides configured.")
        return
    print("symbol\taction\tis_active\treason\tupdated_at")
    for symbol, action, is_active, reason, updated_at in rows:
        print(f"{symbol}\t{action}\t{is_active}\t{reason or ''}\t{updated_at}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage company universe overrides.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_set = sub.add_parser("set", help="Create/update an override row.")
    p_set.add_argument("--symbol", required=True)
    p_set.add_argument("--action", choices=["include", "exclude"], required=True)
    p_set.add_argument(
        "--is-active",
        choices=["true", "false"],
        default="true",
        help="Whether this override is currently active.",
    )
    p_set.add_argument("--reason", default="")

    p_remove = sub.add_parser("remove", help="Delete an override row.")
    p_remove.add_argument("--symbol", required=True)

    p_list = sub.add_parser("list", help="List override rows.")
    p_list.add_argument("--active-only", action="store_true")

    args = parser.parse_args()
    _ = os.getenv("POSTGRES_HOST", "")

    if args.cmd == "set":
        symbol = _normalize_symbol(args.symbol)
        if not symbol:
            raise SystemExit("symbol is required")
        _upsert(
            symbol=symbol,
            action=str(args.action).strip().lower(),
            is_active=str(args.is_active).strip().lower() == "true",
            reason=str(args.reason or "").strip(),
        )
        print(f"Override saved: symbol={symbol} action={args.action} is_active={args.is_active}")
        return 0

    if args.cmd == "remove":
        symbol = _normalize_symbol(args.symbol)
        if not symbol:
            raise SystemExit("symbol is required")
        _remove(symbol)
        print(f"Override removed: symbol={symbol}")
        return 0

    if args.cmd == "list":
        _list_rows(bool(args.active_only))
        return 0

    raise SystemExit(f"Unsupported command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
