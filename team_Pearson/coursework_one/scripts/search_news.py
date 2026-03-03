from __future__ import annotations

"""Search indexed news articles in MongoDB."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from pymongo import MongoClient

DEFAULT_COLLECTION = "news_articles"


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_mongo_cfg(config_path: str) -> dict[str, Any]:
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parents[1] / cfg_path
    cfg = _load_yaml(str(cfg_path))
    return dict(cfg.get("mongo") or {})


def _read_env_or_cfg(env_key: str, cfg: dict[str, Any], cfg_key: str, default: str = "") -> str:
    raw = os.getenv(env_key, str(cfg.get(cfg_key, default) or default))
    return str(raw).strip()


def _resolve_mongo_db(cli_mongo_db: str, mongo_cfg: dict[str, Any]) -> str:
    cli_value = str(cli_mongo_db or "").strip()
    if cli_value:
        return cli_value
    env_value = str(os.getenv("MONGO_DB", "")).strip()
    if env_value:
        return env_value
    cfg_value = str(mongo_cfg.get("database", "")).strip()
    if cfg_value:
        return cfg_value
    return "ift_cw"


def _build_collection(mongo_cfg: dict[str, Any], collection_name: str, mongo_db: str):
    host = _read_env_or_cfg("MONGO_HOST", mongo_cfg, "host", "localhost")
    port = int(_read_env_or_cfg("MONGO_PORT", mongo_cfg, "port", "27019"))
    uri = os.getenv("MONGO_URI", "").strip()
    if uri:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    else:
        client = MongoClient(host=host, port=port, serverSelectionTimeoutMS=5000)
    return client[mongo_db][collection_name]


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
    parser.add_argument("--ticker", default="", help="Ticker filter (e.g. AAPL).")
    parser.add_argument("--from", dest="from_date", default="", help="Inclusive date/time.")
    parser.add_argument("--to", dest="to_date", default="", help="Exclusive date/time.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--mongo-db", default="", help="Mongo database name.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    mongo_cfg = _resolve_mongo_cfg(args.config)
    mongo_db = _resolve_mongo_db(args.mongo_db, mongo_cfg)
    coll = _build_collection(mongo_cfg, args.collection, mongo_db)

    query: dict[str, Any] = {}
    sort_spec: list[tuple[str, Any]] = [("time_published", -1)]
    projection: dict[str, Any] = {
        "_id": 0,
        "title": 1,
        "summary": 1,
        "url": 1,
        "time_published": 1,
        "source": 1,
        "tickers": 1,
        "topics": 1,
        "lang": 1,
    }

    q = str(args.q or "").strip()
    if q:
        query["$text"] = {"$search": q}
        projection["score"] = {"$meta": "textScore"}
        sort_spec = [("score", {"$meta": "textScore"}), ("time_published", -1)]

    ticker = str(args.ticker or "").strip().upper()
    if ticker:
        query["tickers"] = ticker

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


if __name__ == "__main__":
    raise SystemExit(main())
