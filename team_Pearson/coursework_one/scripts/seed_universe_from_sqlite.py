from __future__ import annotations

"""Seed PostgreSQL universe table from the teacher-provided SQLite database."""

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

# Make script robust when executed as a file path from arbitrary cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.db.db_connection import get_db_engine  # noqa: E402
from modules.utils.env import load_dotenv_if_exists  # noqa: E402


def default_sqlite_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "000.Database" / "SQL" / "Equity.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed systematic_equity.company_static from SQLite.")
    p.add_argument(
        "--sqlite-path",
        default=str(default_sqlite_path()),
        help="Path to source SQLite Equity.db file.",
    )
    return p.parse_args()


def load_equity_static(sqlite_path: Path) -> pd.DataFrame:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")

    with sqlite3.connect(str(sqlite_path)) as con:
        df = pd.read_sql_query(
            """
            SELECT symbol, security, gics_sector, gics_industry, country, region
            FROM equity_static
            """,
            con,
        )
    df = df.dropna(subset=["symbol"]).drop_duplicates(subset=["symbol"]).copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    return df[df["symbol"] != ""]


def seed_company_static(df: pd.DataFrame) -> int:
    engine = get_db_engine()
    columns = ["symbol", "security", "gics_sector", "gics_industry", "country", "region"]
    frame = df.reindex(columns=columns).astype(object)
    rows = frame.where(pd.notna(frame), None).to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS systematic_equity;"))
        conn.execute(text("""
                CREATE TABLE IF NOT EXISTS systematic_equity.company_static (
                    symbol TEXT PRIMARY KEY,
                    security TEXT,
                    gics_sector TEXT,
                    gics_industry TEXT,
                    country TEXT,
                    region TEXT
                );
                """))
        conn.execute(text("TRUNCATE TABLE systematic_equity.company_static;"))
        if rows:
            conn.execute(
                text("""
                    INSERT INTO systematic_equity.company_static (
                        symbol,
                        security,
                        gics_sector,
                        gics_industry,
                        country,
                        region
                    )
                    VALUES (
                        :symbol,
                        :security,
                        :gics_sector,
                        :gics_industry,
                        :country,
                        :region
                    )
                    """),
                rows,
            )
    return int(len(rows))


def main() -> int:
    load_dotenv_if_exists(PROJECT_ROOT / ".env")
    args = parse_args()
    source_path = Path(args.sqlite_path).expanduser().resolve()
    df = load_equity_static(source_path)
    rows = seed_company_static(df)
    print(f"Seed completed: inserted {rows} rows into systematic_equity.company_static")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
