from __future__ import annotations

"""Search indexed news articles in MongoDB."""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.utils.env import load_dotenv_if_exists  # noqa: E402
from modules.utils.mongo import (  # noqa: E402
    build_mongo_collection,
    load_mongo_cfg,
    resolve_mongo_db,
)

DEFAULT_COLLECTION = "news_articles"


def _parse_date_floor(value: str) -> datetime:
    raw = value.strip()
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(raw, "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_date_ceil_exclusive(value: str) -> datetime:
    raw = value.strip()
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
    return dt + timedelta(days=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search MongoDB indexed news articles.")
    parser.add_argument("--config", default="config/conf.yaml")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--q", default="", help="Full-text query string.")
    parser.add_argument("--symbol", default="", help="Symbol filter (e.g. AAPL).")
    parser.add_argument(
        "--ticker",
        default="",
        help="Legacy alias of --symbol; kept for backward compatibility.",
    )
    parser.add_argument("--from", dest="from_date", default="", help="Inclusive date/time.")
    parser.add_argument("--to", dest="to_date", default="", help="Exclusive date/time.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--mongo-db", default="", help="Mongo database name.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv_if_exists(PROJECT_ROOT / ".env")

    mongo_cfg = load_mongo_cfg(args.config, PROJECT_ROOT)
    mongo_db = resolve_mongo_db(args.mongo_db, mongo_cfg)
    mongo_client, coll = build_mongo_collection(mongo_cfg, args.collection, mongo_db)

    try:
        query: dict[str, Any] = {}
        sort_spec: list[tuple[str, Any]] = [("time_published", -1)]
        projection: dict[str, Any] = {
            "_id": 0,
            "title": 1,
            "summary": 1,
            "url": 1,
            "time_published": 1,
            "source": 1,
            "symbols": 1,
            "tickers": 1,
            "topics": 1,
            "lang": 1,
        }

        q = str(args.q or "").strip()
        if q:
            query["$text"] = {"$search": q}
            projection["score"] = {"$meta": "textScore"}
            sort_spec = [("score", {"$meta": "textScore"}), ("time_published", -1)]

        symbol = str(args.symbol or args.ticker or "").strip().upper()
        if symbol:
            query["symbols"] = symbol

        time_filter: dict[str, Any] = {}
        if args.from_date:
            time_filter["$gte"] = _parse_date_floor(args.from_date)
        if args.to_date:
            time_filter["$lt"] = _parse_date_ceil_exclusive(args.to_date)
        if time_filter:
            query["time_published"] = time_filter

        cursor = coll.find(query, projection).sort(sort_spec).limit(max(1, int(args.limit)))
        rows = list(cursor)
        print(json.dumps({"count": len(rows)}, ensure_ascii=False))
        for row in rows:
            if isinstance(row.get("time_published"), datetime):
                row["time_published"] = row["time_published"].astimezone(UTC).isoformat()
            print(json.dumps(row, ensure_ascii=False))
        return 0
    finally:
        mongo_client.close()


if __name__ == "__main__":
    raise SystemExit(main())
