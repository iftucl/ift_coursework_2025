from __future__ import annotations

"""Audit Source B historical/incremental transition duplicates in Mongo.

This script validates the *effective* indexed news layer used by research and
search workflows. It checks whether the AV/Finnhub transition window contains
duplicate article URLs after indexing into ``news_articles``.
"""

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pymongo.collection import Collection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.utils.env import load_dotenv_if_exists  # noqa: E402
from modules.utils.mongo import build_mongo_collection, resolve_mongo_db  # noqa: E402

DEFAULT_COLLECTION = "news_articles"

logger = logging.getLogger(__name__)


def _configure_logging(level_raw: str) -> None:
    level = str(level_raw or "INFO").strip().upper()
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(getattr(logging, level, logging.INFO))
        return
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve_config(config_path: str) -> dict[str, Any]:
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = PROJECT_ROOT / cfg_path
    return _load_yaml(str(cfg_path))


def _parse_optional_dt(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime value {raw!r}. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ.")


def _build_match_query(*, since_dt: datetime | None, until_dt: datetime | None) -> dict[str, Any]:
    match: dict[str, Any] = {
        "url": {"$type": "string", "$ne": ""},
    }
    if since_dt or until_dt:
        time_query: dict[str, Any] = {}
        if since_dt is not None:
            time_query["$gte"] = since_dt
        if until_dt is not None:
            time_query["$lt"] = until_dt
        match["time_published"] = time_query
    return match


def _build_duplicate_url_pipeline(
    *, since_dt: datetime | None, until_dt: datetime | None
) -> list[dict[str, Any]]:
    match = _build_match_query(since_dt=since_dt, until_dt=until_dt)
    return [
        {"$match": match},
        {
            "$group": {
                "_id": "$url",
                "count": {"$sum": 1},
                "sources": {"$addToSet": "$source"},
                "symbols": {"$addToSet": "$symbols"},
                "first_seen": {"$min": "$time_published"},
                "last_seen": {"$max": "$time_published"},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]


def _flatten_symbols(raw_groups: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    queue = list(raw_groups) if isinstance(raw_groups, list) else [raw_groups]
    while queue:
        item = queue.pop(0)
        if isinstance(item, list):
            queue.extend(item)
            continue
        token = str(item or "").strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def audit_duplicate_urls(
    coll: Collection,
    *,
    since_dt: datetime | None,
    until_dt: datetime | None,
    sample_limit: int,
) -> dict[str, Any]:
    match = _build_match_query(since_dt=since_dt, until_dt=until_dt)
    groups = list(
        coll.aggregate(_build_duplicate_url_pipeline(since_dt=since_dt, until_dt=until_dt))
    )

    samples = []
    for row in groups[: max(0, int(sample_limit))]:
        samples.append(
            {
                "url": str(row.get("_id") or ""),
                "count": int(row.get("count") or 0),
                "sources": sorted(
                    {str(item).strip() for item in (row.get("sources") or []) if str(item).strip()}
                ),
                "symbols": _flatten_symbols(row.get("symbols") or []),
                "first_seen": row.get("first_seen"),
                "last_seen": row.get("last_seen"),
            }
        )

    duplicate_group_count = len(groups)
    duplicate_document_count = sum(int(row.get("count") or 0) for row in groups)
    duplicate_excess_count = sum(max(int(row.get("count") or 0) - 1, 0) for row in groups)
    return {
        "status": "ok" if duplicate_group_count == 0 else "warning",
        "articles_in_window": int(coll.count_documents(match)),
        "duplicate_url_group_count": duplicate_group_count,
        "duplicate_url_document_count": duplicate_document_count,
        "duplicate_url_excess_count": duplicate_excess_count,
        "duplicate_url_samples": samples,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit duplicate Source B article URLs around the AV/Finnhub transition "
            "window using the indexed Mongo news_articles collection."
        )
    )
    parser.add_argument("--config", default="config/conf.yaml")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--since", required=True, help="Inclusive lower bound.")
    parser.add_argument("--until", required=True, help="Exclusive upper bound.")
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument(
        "--fail-on-duplicates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Return non-zero when duplicate URLs are found.",
    )
    parser.add_argument("--log-level", default=os.getenv("CW1_LOG_LEVEL", "INFO"))
    parser.add_argument("--mongo-db", default="", help="Mongo database name.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv_if_exists(PROJECT_ROOT / ".env")
    _configure_logging(args.log_level)

    mongo_client = None
    try:
        cfg = _resolve_config(args.config)
        mongo_cfg = dict(cfg.get("mongo") or {})
        source_b_cfg = dict(cfg.get("source_b") or {})
        mongo_db = resolve_mongo_db(args.mongo_db, mongo_cfg)
        mongo_client, coll = build_mongo_collection(mongo_cfg, args.collection, mongo_db)
        since_dt = _parse_optional_dt(args.since)
        until_dt = _parse_optional_dt(args.until)
        if since_dt is None or until_dt is None:
            raise ValueError("--since and --until are required")
        if since_dt >= until_dt:
            raise ValueError("--since must be earlier than --until")

        report = audit_duplicate_urls(
            coll,
            since_dt=since_dt,
            until_dt=until_dt,
            sample_limit=max(1, int(args.sample_limit)),
        )
        payload = {
            "collection": args.collection,
            "mongo_db": mongo_db,
            "window_since": since_dt.isoformat(),
            "window_until": until_dt.isoformat(),
            "configured_av_cutoff_date": str(source_b_cfg.get("av_cutoff_date") or "") or None,
            **report,
        }
        print(json.dumps(payload, ensure_ascii=False, default=str))
        if report["duplicate_url_group_count"] > 0 and bool(args.fail_on_duplicates):
            return 2
        return 0
    except Exception as exc:
        logger.exception("audit_source_b_boundary_failed error=%r", exc)
        print(
            json.dumps(
                {
                    "error": repr(exc),
                    "collection": args.collection,
                    "mongo_db": str(args.mongo_db or "").strip() or None,
                    "since": args.since,
                    "until": args.until,
                },
                ensure_ascii=False,
            )
        )
        return 1
    finally:
        if mongo_client is not None:
            mongo_client.close()


if __name__ == "__main__":
    raise SystemExit(main())
