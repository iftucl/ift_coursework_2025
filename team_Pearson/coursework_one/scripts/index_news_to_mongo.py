from __future__ import annotations

"""Build searchable MongoDB index from Source B raw news in MinIO."""

import argparse
import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import yaml
from minio import Minio
from pymongo import UpdateOne
from pymongo.collection import Collection

from modules.utils.mongo import build_mongo_collection, resolve_mongo_db
from modules.utils.env import load_dotenv_if_exists

try:
    import langid  # type: ignore

    _LANGID_AVAILABLE = True
except Exception:  # pragma: no cover - optional runtime dependency fallback
    langid = None
    _LANGID_AVAILABLE = False

DEFAULT_COLLECTION = "news_articles"
DEFAULT_MINIO_PREFIX = "raw/source_b/news/"
SYMBOL_IN_OBJECT_RE = re.compile(r"/symbol=([^/]+)(?:/|\.jsonl$)")
RUN_DATE_IN_OBJECT_RE = re.compile(r"/run_date=(\d{4}-\d{2}-\d{2})/")
MAX_TITLE_LEN = 1024
MAX_SUMMARY_LEN = 8192
MIN_LANG_TEXT_LEN = 20

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
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_config(config_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parents[1] / cfg_path
    cfg = _load_yaml(str(cfg_path))
    minio_cfg = dict(cfg.get("minio") or {})
    mongo_cfg = dict(cfg.get("mongo") or {})
    return minio_cfg, mongo_cfg


def _read_env_or_cfg(env_key: str, cfg: dict[str, Any], cfg_key: str, default: str = "") -> str:
    raw = os.getenv(env_key, str(cfg.get(cfg_key, default) or default))
    return str(raw).strip()


def _build_minio_client(minio_cfg: dict[str, Any]) -> tuple[Minio, str]:
    endpoint = _read_env_or_cfg("MINIO_ENDPOINT", minio_cfg, "endpoint")
    access_key = _read_env_or_cfg("MINIO_ACCESS_KEY", minio_cfg, "access_key")
    secret_key = _read_env_or_cfg("MINIO_SECRET_KEY", minio_cfg, "secret_key")
    bucket = _read_env_or_cfg("MINIO_BUCKET", minio_cfg, "bucket")

    if not endpoint or not access_key or not secret_key or not bucket:
        raise RuntimeError("Missing MinIO config. Check MINIO_* env vars or config/conf.yaml.")

    secure = str(minio_cfg.get("secure", "false")).lower() in {"1", "true", "yes"}
    endpoint = endpoint.removeprefix("http://").removeprefix("https://")
    return (
        Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        ),
        bucket,
    )


def _normalize_title(title: str) -> str:
    return " ".join(str(title).strip().lower().split())


def _make_id(url: str | None, source: str, time_published: str, title: str) -> str:
    if url and url.strip():
        key = url.strip().lower()
    else:
        normalized_title = _normalize_title(title)
        key = f"{source.strip()}|{time_published.strip()}|{normalized_title}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _parse_time_published(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=0, minute=0, second=0)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _extract_topics(raw_topics: Any) -> list[str]:
    if not isinstance(raw_topics, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for topic in raw_topics:
        if isinstance(topic, dict):
            token = str(topic.get("topic") or "").strip().lower()
        else:
            token = str(topic).strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _extract_tickers(raw_item: dict[str, Any], object_symbol: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    symbol = object_symbol.strip().upper()
    if symbol:
        out.append(symbol)
        seen.add(symbol)

    hits = raw_item.get("ticker_hits") or raw_item.get("ticker_sentiment") or []
    if isinstance(hits, list):
        for hit in hits:
            if isinstance(hit, dict):
                ticker = str(hit.get("ticker") or "").strip().upper()
            else:
                ticker = str(hit).strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            out.append(ticker)

    for field in ("symbol", "ticker"):
        top_level = str(raw_item.get(field) or "").strip().upper()
        if top_level and top_level not in seen:
            seen.add(top_level)
            out.append(top_level)
    return out


def _ensure_indexes(coll: Collection) -> None:
    logger.info("mongo_indexes ensure_start collection=%s", coll.name)
    coll.create_index(
        [("title", "text"), ("summary", "text")],
        name="idx_text_title_summary",
    )
    coll.create_index([("time_published", 1)], name="idx_time_published")
    coll.create_index([("tickers", 1)], name="idx_tickers")
    coll.create_index(
        [("tickers", 1), ("time_published", -1)],
        name="idx_tickers_time_published_desc",
    )
    coll.create_index([("published_at", 1)], name="idx_published_at")
    coll.create_index([("url", 1)], name="idx_url_unique", unique=True, sparse=True)
    coll.create_index([("last_seen_run_date", 1)], name="idx_last_seen_run_date")
    coll.create_index(
        [("last_seen_run_date", 1), ("time_published", -1)],
        name="idx_last_seen_run_date_time_published_desc",
    )
    logger.info("mongo_indexes ensure_done collection=%s", coll.name)


def _iter_jsonl_rows_stream(response: Any) -> Iterator[dict[str, Any]]:
    buf = ""
    for chunk in response.stream(amt=1024 * 64):
        if not chunk:
            continue
        buf += chunk.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj

    tail = buf.strip()
    if tail:
        try:
            obj = json.loads(tail)
            if isinstance(obj, dict):
                yield obj
        except json.JSONDecodeError:
            pass


def _parse_symbol_from_object_name(object_name: str) -> str:
    match = SYMBOL_IN_OBJECT_RE.search(object_name)
    if not match:
        return ""
    return str(match.group(1)).strip().upper()


def _parse_run_date_from_object_name(object_name: str) -> str:
    match = RUN_DATE_IN_OBJECT_RE.search(object_name)
    if not match:
        return ""
    return str(match.group(1)).strip()


def _parse_optional_dt(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(raw, "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _truncate_text(value: str, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _infer_language(text: str) -> tuple[str | None, float | None]:
    """Infer language via langid; return (lang, confidence) or (None, None)."""
    if not _LANGID_AVAILABLE:
        return None, None
    compact = " ".join(str(text or "").split())
    if len(compact) < MIN_LANG_TEXT_LEN:
        return None, None
    try:
        lang, score = langid.classify(compact)  # type: ignore[attr-defined]
        return str(lang).strip().lower() or None, float(score)
    except Exception:
        return None, None


def _build_query_prefix(base_prefix: str, run_date: str | None) -> str:
    prefix = base_prefix
    if not prefix.endswith("/"):
        prefix += "/"
    if run_date:
        prefix += f"run_date={run_date}/"
    return prefix


def index_news(
    coll: Collection,
    minio_client: Minio,
    bucket: str,
    prefix: str,
    batch_size: int,
    symbol_filter: set[str],
    since_dt: datetime | None,
    until_dt: datetime | None,
    dry_run: bool,
    run_date: str | None,
) -> dict[str, int]:
    stats = {
        "objects_scanned": 0,
        "articles_seen": 0,
        "articles_filtered_by_time": 0,
        "ops_submitted": 0,
        "bulk_calls": 0,
        "docs_upserted": 0,
        "docs_matched": 0,
        "docs_modified": 0,
    }
    ops: list[UpdateOne] = []

    logger.info(
        "index_news start bucket=%s prefix=%s batch_size=%s symbol_filter_size=%s dry_run=%s",
        bucket,
        prefix,
        batch_size,
        len(symbol_filter),
        dry_run,
    )

    for obj in minio_client.list_objects(bucket, prefix=prefix, recursive=True):
        object_name = str(obj.object_name)
        if not object_name.endswith(".jsonl"):
            continue

        object_symbol = _parse_symbol_from_object_name(object_name)
        if symbol_filter and object_symbol not in symbol_filter:
            continue

        stats["objects_scanned"] += 1
        response = minio_client.get_object(bucket, object_name)
        try:
            for row in _iter_jsonl_rows_stream(response):
                stats["articles_seen"] += 1
                url = str(row.get("url") or "").strip()
                source = str(row.get("source") or "").strip()
                title = _truncate_text(row.get("title") or "", MAX_TITLE_LEN)
                summary = _truncate_text(row.get("summary") or "", MAX_SUMMARY_LEN)
                lang_raw = str(row.get("lang") or "").strip().lower()
                time_raw = str(
                    row.get("time_published") or row.get("time_published_utc") or ""
                ).strip()
                doc_id = _make_id(
                    url=url or None, source=source, time_published=time_raw, title=title
                )
                published_at = _parse_time_published(time_raw)
                if since_dt or until_dt:
                    if published_at is None:
                        stats["articles_filtered_by_time"] += 1
                        continue
                    if since_dt and published_at < since_dt:
                        stats["articles_filtered_by_time"] += 1
                        continue
                    if until_dt and published_at >= until_dt:
                        stats["articles_filtered_by_time"] += 1
                        continue
                tickers = _extract_tickers(row, object_symbol=object_symbol)
                effective_run_date = str(run_date or "").strip()
                if not effective_run_date:
                    effective_run_date = _parse_run_date_from_object_name(object_name)
                infer_text = (title + "\n" + summary).strip()
                inferred_lang, inferred_score = _infer_language(infer_text)

                if lang_raw:
                    lang = lang_raw
                    lang_source = "raw"
                elif inferred_lang:
                    lang = inferred_lang
                    lang_source = "inferred"
                else:
                    lang = "unknown"
                    lang_source = "unknown"

                doc: dict[str, Any] = {
                    "_id": doc_id,
                    "url": url or None,
                    "source": source,
                    "time_published": published_at,
                    "published_at": published_at,  # compatibility alias
                    "title": title,
                    "summary": summary,
                    "topics": _extract_topics(row.get("topics")),
                    "lang": lang,
                    "lang_raw": lang_raw or None,
                    "lang_inferred": inferred_lang,
                    "lang_infer_confidence": inferred_score,
                    "lang_source": lang_source,
                    "ingested_at": datetime.now(UTC),
                    "last_seen_run_date": effective_run_date or None,
                }
                ops.append(
                    UpdateOne(
                        {"_id": doc_id},
                        {
                            "$set": doc,
                            "$setOnInsert": {"first_seen_run_date": effective_run_date or None},
                            "$addToSet": {
                                "tickers": {"$each": tickers},
                                "symbols": {"$each": tickers},  # compatibility alias
                                "minio_object_keys": object_name,
                            },
                        },
                        upsert=True,
                    )
                )
                stats["ops_submitted"] += 1

                if len(ops) >= batch_size:
                    if not dry_run:
                        result = coll.bulk_write(ops, ordered=False)
                        stats["bulk_calls"] += 1
                        stats["docs_upserted"] += int(result.upserted_count)
                        stats["docs_matched"] += int(result.matched_count)
                        stats["docs_modified"] += int(result.modified_count)
                    ops = []
        except Exception as exc:
            logger.exception(
                "object_process_failed object=%s bucket=%s error=%r",
                object_name,
                bucket,
                exc,
            )
            continue
        finally:
            response.close()
            response.release_conn()

    if ops and not dry_run:
        result = coll.bulk_write(ops, ordered=False)
        stats["bulk_calls"] += 1
        stats["docs_upserted"] += int(result.upserted_count)
        stats["docs_matched"] += int(result.matched_count)
        stats["docs_modified"] += int(result.modified_count)
    logger.info(
        "index_news done objects_scanned=%s articles_seen=%s filtered_by_time=%s ops_submitted=%s "
        "bulk_calls=%s upserted=%s matched=%s modified=%s",
        stats["objects_scanned"],
        stats["articles_seen"],
        stats["articles_filtered_by_time"],
        stats["ops_submitted"],
        stats["bulk_calls"],
        stats["docs_upserted"],
        stats["docs_matched"],
        stats["docs_modified"],
    )
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Index Source B raw news JSONL in MinIO into MongoDB searchable collection."
    )
    parser.add_argument("--config", default="config/conf.yaml")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument(
        "--run-date", default=None, help="Filter MinIO keys by run_date=YYYY-MM-DD."
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help="Optional symbol filter. Can repeat: --symbol AAPL --symbol MSFT",
    )
    parser.add_argument(
        "--since", default="", help="Filter news time_published >= this timestamp/date."
    )
    parser.add_argument(
        "--until", default="", help="Filter news time_published < this timestamp/date."
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--prefix", default=DEFAULT_MINIO_PREFIX)
    parser.add_argument("--skip-indexes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default=os.getenv("CW1_LOG_LEVEL", "INFO"))
    parser.add_argument("--mongo-db", default="", help="Mongo database name.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv_if_exists(project_root / ".env")
    _configure_logging(args.log_level)
    if not _LANGID_AVAILABLE:
        logger.warning("langid_unavailable language_inference_disabled fallback=unknown")
    mongo_client = None
    try:
        minio_cfg, mongo_cfg = _resolve_config(args.config)
        minio_client, bucket = _build_minio_client(minio_cfg)
        mongo_db = resolve_mongo_db(args.mongo_db, mongo_cfg)
        mongo_client, coll = build_mongo_collection(mongo_cfg, args.collection, mongo_db)

        if not args.skip_indexes and not args.dry_run:
            _ensure_indexes(coll)

        prefix = _build_query_prefix(args.prefix, args.run_date)
        symbol_filter = {str(s).strip().upper() for s in args.symbol if str(s).strip()}
        since_dt = _parse_optional_dt(args.since)
        until_dt = _parse_optional_dt(args.until)
        stats = index_news(
            coll=coll,
            minio_client=minio_client,
            bucket=bucket,
            prefix=prefix,
            batch_size=max(1, int(args.batch_size)),
            symbol_filter=symbol_filter,
            since_dt=since_dt,
            until_dt=until_dt,
            dry_run=bool(args.dry_run),
            run_date=args.run_date,
        )
        print(
            json.dumps(
                {
                    "collection": args.collection,
                    "mongo_db": mongo_db,
                    "prefix": prefix,
                    "since": since_dt.isoformat() if since_dt else None,
                    "until": until_dt.isoformat() if until_dt else None,
                    **stats,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        logger.exception("index_news_to_mongo_failed error=%r", exc)
        print(
            json.dumps(
                {
                    "error": repr(exc),
                    "collection": args.collection,
                    "mongo_db": str(args.mongo_db or "").strip() or None,
                    "run_date": args.run_date,
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
