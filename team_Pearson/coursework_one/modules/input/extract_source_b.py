from __future__ import annotations

"""Source B extractor: routed historical/incremental news -> daily sentiment atomics.

Data source strategy:
- **Historical windows on or before ``av_cutoff_date``:** route to Alpha Vantage
  ``NEWS_SENTIMENT`` when a valid AV key is available. This path is useful for
  historical rebuilds, but production reproducibility can also rely on archived
  raw files already stored in MinIO.
- **Incremental windows after ``av_cutoff_date``:** route to Finnhub
  ``company-news`` for ongoing free-tier-friendly refreshes.
- **Cross-cutoff windows:** split the request by date, fetch from both providers,
  then merge and de-duplicate into one symbol/date stream.

All routed news feeds flow into a unified Loughran-McDonald sentiment-scoring
pipeline via ``pysentiment2`` (with a small lexical fallback), so the curated
atomics remain methodologically consistent regardless of upstream provider.

Pipeline contract:
1) ingest raw news JSON and persist replayable snapshots to MinIO
2) transform title/summary text into daily atomic records such as
   ``news_sentiment_daily`` and ``news_article_count_daily``
3) derive lightweight event proxies that downstream ``CW2`` can use for
   event-driven risk actions
"""

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set
from urllib.parse import urlparse

import requests

from .symbol_filter import filter_symbols

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    """Serialize date-like objects in raw Source B payloads."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# Alpha Vantage constants
# ---------------------------------------------------------------------------

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
_ALPHA_KEY_PLACEHOLDERS = {
    "",
    "YOUR_KEY",
    "YOUR_API_KEY_HERE",
    "ALPHA_VANTAGE_API_KEY",
    "REPLACE_WITH_YOUR_KEY",
}
ALPHA_VANTAGE_THROTTLE_SECONDS = float(os.getenv("ALPHA_VANTAGE_THROTTLE_SECONDS", "1.0"))
ALPHA_VANTAGE_MAX_RETRIES = int(os.getenv("ALPHA_VANTAGE_MAX_RETRIES", "3"))
ALPHA_VANTAGE_RETRY_BACKOFF_SECONDS = float(os.getenv("ALPHA_VANTAGE_RETRY_BACKOFF_SECONDS", "5.0"))
SOURCE_B_INCREMENTAL_BUFFER_DAYS = int(os.getenv("SOURCE_B_INCREMENTAL_BUFFER_DAYS", "7"))

# ---------------------------------------------------------------------------
# Sentiment backend (L-M lexicon via pysentiment2)
# ---------------------------------------------------------------------------

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

_FALLBACK_POSITIVE = {
    "gain",
    "growth",
    "profit",
    "strong",
    "beat",
    "improve",
    "upside",
    "upgrade",
    "positive",
}
_FALLBACK_NEGATIVE = {
    "loss",
    "decline",
    "weak",
    "miss",
    "downgrade",
    "risk",
    "negative",
    "drop",
    "fall",
}

_EARNINGS_KEYWORDS = (
    "earnings",
    "eps",
    "guidance",
    "revenue",
    "quarterly results",
    "quarter results",
)
_EARNINGS_NEGATIVE_KEYWORDS = (
    "miss",
    "missed estimates",
    "below expectations",
    "cuts guidance",
    "cut guidance",
    "weak outlook",
    "profit warning",
    "revenue miss",
    "eps miss",
)
_RATING_DOWNGRADE_KEYWORDS = (
    "downgrade",
    "downgraded",
    "cut to",
    "lowered to",
    "underperform",
    "underweight",
    "sell rating",
)
_RATING_UPGRADE_KEYWORDS = (
    "upgrade",
    "upgraded",
    "raised to",
    "overweight",
    "outperform",
    "buy rating",
)

_SOURCE_B_NORMALIZED_SCHEMA_VERSION = "v2"
_SOURCE_B_PROVIDER_PAYLOAD_VERSION_DEFAULTS = {
    "alpha_vantage": "news_sentiment_v1",
    "finnhub": "company_news_v1",
}
_SOURCE_B_RAW_OBJECT_RE = re.compile(
    r"^raw/source_b/news/run_date=(\d{4}-\d{2}-\d{2})/year=(\d{4})/month=(\d{2})/symbol=([A-Za-z0-9.\-]+)\.jsonl$"
)

_LM_ANALYZER = None
_SENTIMENT_BACKEND_LOGGED = False
_RAW_ARCHIVE_INDEX_CACHE: Dict[tuple[str, str, bool], Dict[tuple[str, str, str], str]] = {}


def _ensure_sentiment_backend() -> None:
    """Initialize sentiment backend once and log which backend is active."""
    global _LM_ANALYZER, _SENTIMENT_BACKEND_LOGGED
    if _LM_ANALYZER is None:
        try:
            import pysentiment2 as ps  # type: ignore

            _LM_ANALYZER = ps.LM()
        except Exception:
            _LM_ANALYZER = False

    if not _SENTIMENT_BACKEND_LOGGED:
        if _LM_ANALYZER:
            logger.info("source_b sentiment_backend=lm_lexicon")
        else:
            logger.warning(
                "source_b sentiment_backend=fallback_lexicon reason=pysentiment2_unavailable"
            )
        _SENTIMENT_BACKEND_LOGGED = True


# ---------------------------------------------------------------------------
# Symbol filtering
# ---------------------------------------------------------------------------


def _filter_symbols_for_source_b(symbols: List[str], config: Optional[Dict[str, Any]]) -> List[str]:
    """Filter and deduplicate symbols for Source B ingestion."""
    out = filter_symbols(
        symbols=symbols,
        config=config,
        section=None,
        default_skip_suffix=True,
        default_regex=r"^[A-Z0-9]+$",
    )
    skipped = len({str(s).strip().upper() for s in symbols if str(s).strip()}) - len(out)
    if skipped > 0:
        logger.info("source_b symbol filter skipped %s symbols by policy", skipped)
    return out


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _resolve_alpha_key(config: Optional[Dict[str, Any]]) -> str:
    """Resolve Alpha Vantage API key from env/config with placeholder filtering."""

    def _sanitize(value: Any) -> str:
        cleaned = str(value or "").strip()
        if cleaned.upper() in _ALPHA_KEY_PLACEHOLDERS:
            return ""
        return cleaned

    api_cfg = (config or {}).get("api") or {}
    legacy_cfg = (config or {}).get("alpha_vantage") or {}
    return (
        _sanitize(os.getenv("ALPHA_VANTAGE_API_KEY"))
        or _sanitize(os.getenv("ALPHA_VANTAGE_KEY"))
        or _sanitize(api_cfg.get("alpha_vantage_key") or legacy_cfg.get("api_key"))
    )


def _resolve_av_cutoff_date(config: Optional[Dict[str, Any]]) -> Optional[date]:
    """Resolve the AV -> Finnhub cutoff date from config.

    Dates on or before this value use Alpha Vantage; dates after use Finnhub.
    Returns ``None`` if not configured (meaning: use AV for everything when a
    key is available, fall back to Finnhub otherwise).
    """
    source_b_cfg = (config or {}).get("source_b") or {}
    raw = str(source_b_cfg.get("av_cutoff_date") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        logger.warning("source_b: invalid av_cutoff_date=%r, ignoring", raw)
        return None


def _resolve_source_b_strict_time(config: Optional[Dict[str, Any]]) -> bool:
    """Resolve strict timestamp policy for Source B article rows."""
    source_cfg = (config or {}).get("source_b") or {}
    raw = source_cfg.get("strict_time", False)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


# ---------------------------------------------------------------------------
# MinIO helpers
# ---------------------------------------------------------------------------


def _minio_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Resolve MinIO connection config using env-over-config precedence."""
    cfg = dict((config or {}).get("minio") or {})
    cfg["endpoint"] = os.getenv("MINIO_ENDPOINT", cfg.get("endpoint"))
    cfg["access_key"] = os.getenv("MINIO_ACCESS_KEY", cfg.get("access_key"))
    cfg["secret_key"] = os.getenv("MINIO_SECRET_KEY", cfg.get("secret_key"))
    cfg["bucket"] = os.getenv("MINIO_BUCKET", cfg.get("bucket"))

    endpoint_raw = str(cfg.get("endpoint", "") or "").strip()
    is_https = endpoint_raw.startswith("https://")
    endpoint = endpoint_raw.replace("http://", "").replace("https://", "")
    cfg["endpoint"] = endpoint
    if cfg.get("secure") is None:
        cfg["secure"] = is_https
    return cfg


def _build_minio_client(minio_cfg: Dict[str, Any]):
    """Construct a MinIO client from resolved config."""
    from minio import Minio

    return Minio(
        endpoint=minio_cfg["endpoint"],
        access_key=minio_cfg["access_key"],
        secret_key=minio_cfg["secret_key"],
        secure=minio_cfg.get("secure", False),
    )


# ---------------------------------------------------------------------------
# Date/window helpers
# ---------------------------------------------------------------------------


def _shift_months_date(d: date, months: int) -> date:
    """Shift date by calendar months, clamping day to month-end."""
    total = d.year * 12 + (d.month - 1) + months
    year = total // 12
    month = (total % 12) + 1
    first_of_target = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    month_end_day = (next_month - timedelta(days=1)).day
    return first_of_target.replace(day=min(d.day, month_end_day))


def _month_windows(run_date: str, backfill_years: int) -> List[tuple[date, date]]:
    """Return month windows as (month_start, fetch_end<=run_date) covering backfill horizon."""
    end = datetime.strptime(run_date, "%Y-%m-%d").date()
    years = int(backfill_years)
    if years <= 0:
        return [(end.replace(day=1), end)]

    start_anchor = _shift_months_date(end, -(12 * years))
    start_date = start_anchor

    out: List[tuple[date, date]] = []
    cur = date(start_date.year, start_date.month, 1)
    while cur <= end:
        if cur.month == 12:
            next_month = date(cur.year + 1, 1, 1)
        else:
            next_month = date(cur.year, cur.month + 1, 1)
        month_end = next_month - timedelta(days=1)
        fetch_end = month_end if month_end <= end else end
        if fetch_end >= start_date:
            out.append((cur, fetch_end))
        cur = next_month
    return out


def _natural_month_end(month_start: date) -> date:
    """Return the natural month-end for a given month-start date."""
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return next_month - timedelta(days=1)


# ---------------------------------------------------------------------------
# MinIO object paths
# ---------------------------------------------------------------------------


def _raw_object_path(symbol: str, run_date: str, month_end: date) -> str:
    """Build deterministic MinIO object key for monthly Source B JSONL."""
    month = month_end.strftime("%m")
    year = month_end.strftime("%Y")
    return (
        "raw/source_b/news/" f"run_date={run_date}/year={year}/month={month}/symbol={symbol}.jsonl"
    )


def _monthly_current_object_path(symbol: str, month_start: date) -> str:
    """Build stable object key for merged current-month Source B JSONL."""
    return (
        "raw/source_b/news_current/"
        f"year={month_start.strftime('%Y')}/month={month_start.strftime('%m')}/"
        f"symbol={symbol}.jsonl"
    )


def _cursor_object_path(symbol: str, month_start: date) -> str:
    """Build stable per-symbol per-month cursor path for incremental ingestion."""
    return (
        "raw/source_b/news_cursor/"
        f"year={month_start.strftime('%Y')}/month={month_start.strftime('%m')}/symbol={symbol}.json"
    )


# ---------------------------------------------------------------------------
# MinIO read/write
# ---------------------------------------------------------------------------


def _save_raw_to_minio(
    config: Optional[Dict[str, Any]],
    symbol: str,
    run_date: str,
    month_end: date,
    articles: List[Dict[str, Any]],
) -> None:
    """Persist monthly deduplicated Source B articles as JSONL in MinIO."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return

    try:
        client = _build_minio_client(minio_cfg)
        bucket = minio_cfg["bucket"]
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        key = _raw_object_path(symbol, run_date, month_end)
        jsonl = "\n".join(
            json.dumps(a, ensure_ascii=False, default=_json_default) for a in articles
        )
        data = jsonl.encode("utf-8")
        client.put_object(
            bucket,
            key,
            data=BytesIO(data),
            length=len(data),
            content_type="application/json",
        )
    except Exception as exc:  # pragma: no cover - external service dependent
        logger.warning("source_b raw archive skipped for %s %s: %r", symbol, month_end, exc)


def _parse_jsonl_articles(data: str, *, fallback_symbol: str) -> List[Dict[str, Any]]:
    """Parse JSONL content into normalized article records."""
    records: List[Dict[str, Any]] = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = None
        if not isinstance(parsed, dict):
            continue
        normalized = _normalize_article(parsed, fallback_symbol=fallback_symbol)
        if normalized is not None:
            records.append(normalized)
    return records


def _raw_archive_index_cache_key(minio_cfg: Dict[str, Any]) -> tuple[str, str, bool]:
    """Build a stable cache key for Source B raw archive discovery."""
    return (
        str(minio_cfg.get("endpoint") or "").strip(),
        str(minio_cfg.get("bucket") or "").strip(),
        bool(minio_cfg.get("secure", False)),
    )


def _build_raw_archive_index(
    config: Optional[Dict[str, Any]],
) -> Dict[tuple[str, str, str], str]:
    """Index latest raw Source B archive object for each (year, month, symbol)."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return {}

    cache_key = _raw_archive_index_cache_key(minio_cfg)
    cached = _RAW_ARCHIVE_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        client = _build_minio_client(minio_cfg)
        bucket = minio_cfg["bucket"]
        latest_by_month: Dict[tuple[str, str, str], tuple[str, str]] = {}
        for obj in client.list_objects(bucket, prefix="raw/source_b/news/", recursive=True):
            object_name = str(getattr(obj, "object_name", "") or "").strip()
            match = _SOURCE_B_RAW_OBJECT_RE.match(object_name)
            if not match:
                continue
            run_date_str, year_str, month_str, symbol = match.groups()
            month_key = (year_str, month_str, symbol.upper())
            existing = latest_by_month.get(month_key)
            if existing is None or run_date_str > existing[0]:
                latest_by_month[month_key] = (run_date_str, object_name)
        index = {month_key: object_name for month_key, (_, object_name) in latest_by_month.items()}
    except Exception:
        index = {}

    _RAW_ARCHIVE_INDEX_CACHE[cache_key] = index
    return index


def _load_latest_raw_month_articles(
    config: Optional[Dict[str, Any]],
    symbol: str,
    month_start: date,
) -> List[Dict[str, Any]]:
    """Load the latest archived raw month snapshot for one symbol from MinIO."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return []

    symbol_key = str(symbol or "").strip().upper()
    month_key = (month_start.strftime("%Y"), month_start.strftime("%m"), symbol_key)
    object_key = _build_raw_archive_index(config).get(month_key)
    if not object_key:
        return []

    try:
        client = _build_minio_client(minio_cfg)
        obj = client.get_object(minio_cfg["bucket"], object_key)
        try:
            data = obj.read().decode("utf-8")
        finally:
            obj.close()
            obj.release_conn()
    except Exception:
        return []

    return _parse_jsonl_articles(data, fallback_symbol=symbol_key)


def _source_b_supporting_objects_exist(
    config: Optional[Dict[str, Any]],
    *,
    symbol: str,
    run_date: str,
    month_start: date,
) -> bool:
    """Return True when the required MinIO support objects exist for one symbol-month.

    For months before the AV/Finnhub cutoff month, a canonical archived raw month
    object is sufficient for reuse. ``news_current`` / ``news_cursor`` are runtime
    incremental state and should not block reuse of closed historical months.
    For the cutoff month and later, require the incremental support objects.
    """
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return False

    try:
        cutoff_date = _resolve_av_cutoff_date(config)
        cutoff_month_start = cutoff_date.replace(day=1) if cutoff_date is not None else None
        if cutoff_month_start is not None and month_start < cutoff_month_start:
            month_key = (
                month_start.strftime("%Y"),
                month_start.strftime("%m"),
                str(symbol or "").strip().upper(),
            )
            return bool(_build_raw_archive_index(config).get(month_key))

        client = _build_minio_client(minio_cfg)
        bucket = minio_cfg["bucket"]
        expected_keys = [
            _raw_object_path(symbol, run_date, month_start),
            _monthly_current_object_path(symbol, month_start),
            _cursor_object_path(symbol, month_start),
        ]
        for key in expected_keys:
            client.stat_object(bucket, key)
        return True
    except Exception:
        return False


def _load_current_month_articles(
    config: Optional[Dict[str, Any]],
    symbol: str,
    month_start: date,
) -> List[Dict[str, Any]]:
    """Load merged current-month Source B records from MinIO JSONL."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return []

    try:
        client = _build_minio_client(minio_cfg)
        obj = client.get_object(
            minio_cfg["bucket"], _monthly_current_object_path(symbol, month_start)
        )
        try:
            data = obj.read().decode("utf-8")
        finally:
            obj.close()
            obj.release_conn()
    except Exception:
        return []

    return _parse_jsonl_articles(data, fallback_symbol=symbol)


def _save_current_month_articles(
    config: Optional[Dict[str, Any]],
    symbol: str,
    month_start: date,
    articles: List[Dict[str, Any]],
) -> None:
    """Persist merged current-month Source B records as stable JSONL."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return

    try:
        client = _build_minio_client(minio_cfg)
        bucket = minio_cfg["bucket"]
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        key = _monthly_current_object_path(symbol, month_start)
        jsonl = "\n".join(
            json.dumps(a, ensure_ascii=False, default=_json_default) for a in articles
        )
        data = jsonl.encode("utf-8")
        client.put_object(
            bucket,
            key,
            data=BytesIO(data),
            length=len(data),
            content_type="application/json",
        )
    except Exception as exc:  # pragma: no cover - external service dependent
        logger.warning(
            "source_b current-month save skipped for %s %s: %r", symbol, month_start, exc
        )


# ---------------------------------------------------------------------------
# MinIO cursor (incremental checkpoint)
# ---------------------------------------------------------------------------


def _load_month_cursor(
    config: Optional[Dict[str, Any]], symbol: str, month_start: date
) -> Optional[date]:
    """Load last_ingested_date for one symbol-month cursor from MinIO."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return None

    try:
        client = _build_minio_client(minio_cfg)
        obj = client.get_object(minio_cfg["bucket"], _cursor_object_path(symbol, month_start))
        try:
            payload = json.loads(obj.read().decode("utf-8"))
        finally:
            obj.close()
            obj.release_conn()
    except Exception:
        return None

    raw = str((payload or {}).get("last_ingested_date") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _load_month_cursor_closed(
    config: Optional[Dict[str, Any]], symbol: str, month_start: date
) -> bool:
    """Load optional is_closed flag for one symbol-month cursor from MinIO."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return False

    try:
        client = _build_minio_client(minio_cfg)
        obj = client.get_object(minio_cfg["bucket"], _cursor_object_path(symbol, month_start))
        try:
            payload = json.loads(obj.read().decode("utf-8"))
        finally:
            obj.close()
            obj.release_conn()
    except Exception:
        return False

    raw = (payload or {}).get("is_closed", False)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def _save_month_cursor(
    config: Optional[Dict[str, Any]],
    symbol: str,
    month_start: date,
    last_ingested_date: date,
    *,
    is_closed: bool = False,
) -> None:
    """Persist/update last_ingested_date cursor for one symbol-month."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return

    payload = {
        "symbol": symbol,
        "month_start": month_start.isoformat(),
        "last_ingested_date": last_ingested_date.isoformat(),
        "is_closed": bool(is_closed),
        "updated_at": datetime.utcnow().isoformat(),
    }

    try:
        client = _build_minio_client(minio_cfg)
        bucket = minio_cfg["bucket"]
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        client.put_object(
            bucket,
            _cursor_object_path(symbol, month_start),
            data=BytesIO(data),
            length=len(data),
            content_type="application/json",
        )
    except Exception as exc:  # pragma: no cover - external service dependent
        logger.warning("source_b cursor update skipped for %s %s: %r", symbol, month_start, exc)


# ---------------------------------------------------------------------------
# Article normalization & dedup
# ---------------------------------------------------------------------------


def _coerce_publish_date_text(value: Any) -> str:
    """Normalize provider publish dates to ``YYYY-MM-DD`` text."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

    sanitized = raw.replace("Z", "+00:00")
    for candidate in (sanitized, sanitized[:10]):
        try:
            return datetime.fromisoformat(candidate).date().isoformat()
        except ValueError:
            continue
    return ""


def _publish_date_to_time_published(value: Any) -> str:
    """Convert a provider publish-date field into compact UTC timestamp text."""
    publish_date = _coerce_publish_date_text(value)
    if not publish_date:
        return ""
    return publish_date.replace("-", "") + "T000000"


def _coerce_time_published_text(value: Any, *, publish_date: str = "") -> tuple[str, str]:
    """Normalize timestamps to compact UTC text and record time precision."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y%m%dT%H%M%S"), "timestamp"
    if isinstance(value, date):
        return value.strftime("%Y%m%dT000000"), "date"

    raw = str(value or "").strip()
    if raw:
        if len(raw) >= 15 and raw[:8].isdigit():
            return raw[:15], "timestamp"
        if raw.isdigit() and len(raw) in {10, 13}:
            try:
                ts = int(raw)
                if len(raw) == 13:
                    ts //= 1000
                parsed = datetime.fromtimestamp(ts, tz=timezone.utc)
                return parsed.strftime("%Y%m%dT%H%M%S"), "timestamp"
            except (ValueError, OSError):
                pass
        sanitized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(sanitized)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.strftime("%Y%m%dT%H%M%S"), "timestamp"
        except ValueError:
            pass

    if publish_date:
        return _publish_date_to_time_published(publish_date), "date"
    return "", "missing"


def _normalize_topics(value: Any) -> tuple[List[str], list[str]]:
    """Normalize provider topics into a list of strings."""
    if value in (None, ""):
        return [], []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()], []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else [], ["topics_scalar_coerced"]
    return [], ["topics_invalid_type"]


def _normalize_ticker_hits(value: Any, symbol: str) -> tuple[List[Dict[str, str]], list[str]]:
    """Normalize provider ticker-association payloads into a stable list."""
    issues: list[str] = []
    normalized: List[Dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                ticker = str(item.get("ticker") or item.get("symbol") or "").strip().upper()
            else:
                ticker = str(item or "").strip().upper()
            if ticker:
                normalized.append({"ticker": ticker})
            else:
                issues.append("ticker_hit_item_invalid")
    elif value not in (None, ""):
        issues.append("ticker_hits_invalid_type")

    if not normalized and symbol:
        normalized = [{"ticker": symbol}]
    return normalized, issues


def _normalize_url(value: Any) -> tuple[str, list[str]]:
    """Return canonical article URL or blank if malformed."""
    raw = str(value or "").strip()
    if not raw:
        return "", []
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return raw, []
    return "", ["invalid_url"]


def _resolve_provider_payload_version(article: Dict[str, Any], provider: str) -> str:
    """Resolve provider payload version from explicit fields or provider defaults."""
    for key in (
        "provider_payload_version",
        "payload_version",
        "provider_version",
        "provider_schema_version",
    ):
        raw = str(article.get(key) or "").strip()
        if raw:
            return raw
    return _SOURCE_B_PROVIDER_PAYLOAD_VERSION_DEFAULTS.get(provider, "unknown")


def _normalize_article(
    article: Dict[str, Any], *, fallback_symbol: str = ""
) -> Optional[Dict[str, Any]]:
    """Normalize provider/raw article fields into one stable JSONL schema.

    Handles both AV (``title``, ``time_published``, ``ticker_sentiment``) and
    Finnhub (``headline``, ``publish_date``) field conventions.
    """
    if not isinstance(article, dict):
        return None

    symbol = (
        str(article.get("symbol") or article.get("ticker") or fallback_symbol or "").strip().upper()
    )
    title = str(article.get("title") or article.get("headline") or "").strip()
    summary = str(article.get("summary") or "").strip()
    data_source = str(article.get("data_source") or "").strip().lower()
    if not data_source:
        source_hint = str(article.get("source") or article.get("source_name") or "").strip().lower()
        if source_hint == "finnhub":
            data_source = "finnhub"
        elif article.get("ticker_sentiment"):
            data_source = "alpha_vantage"

    validation_errors: list[str] = []
    publish_date = _coerce_publish_date_text(article.get("publish_date"))
    if article.get("publish_date") not in (None, "", publish_date) and not publish_date:
        validation_errors.append("invalid_publish_date")
    time_published, time_precision = _coerce_time_published_text(
        article.get("time_published") or article.get("time_published_utc"),
        publish_date=publish_date,
    )
    if article.get("time_published") not in (None, "", time_published) and not time_published:
        validation_errors.append("invalid_time_published")

    raw_ticker_hits = article.get("ticker_hits") or article.get("ticker_sentiment") or []
    ticker_hits, ticker_issues = _normalize_ticker_hits(raw_ticker_hits, symbol)
    topics, topic_issues = _normalize_topics(article.get("topics"))
    url, url_issues = _normalize_url(article.get("url"))
    validation_errors.extend(ticker_issues)
    validation_errors.extend(topic_issues)
    validation_errors.extend(url_issues)
    if not title and not summary:
        validation_errors.append("missing_text")

    return {
        "article_id": str(article.get("article_id") or article.get("id") or ""),
        "symbol": symbol,
        "ticker": symbol,
        "publish_date": publish_date,
        "time_published": time_published,
        "time_precision": time_precision,
        "title": title,
        "headline": title,
        "summary": summary,
        "url": url,
        "source": str(article.get("source") or article.get("source_name") or "").strip(),
        "data_source": data_source,
        "provider_payload_version": _resolve_provider_payload_version(article, data_source),
        "normalized_schema_version": _SOURCE_B_NORMALIZED_SCHEMA_VERSION,
        "schema_validation_status": "valid" if not validation_errors else "warning",
        "schema_validation_errors": sorted(set(validation_errors)),
        "topics": topics,
        "ticker_hits": ticker_hits,
        "category": str(article.get("category") or "").strip(),
        "lang": str(article.get("lang") or "").strip().lower(),
    }


def _article_dedupe_key(article: Dict[str, Any]) -> str:
    """Build article dedupe key: article_id -> url -> source+title+date."""
    article_id = str(article.get("article_id") or article.get("id") or "").strip()
    if article_id:
        return f"article_id:{article_id.lower()}"

    url = str(article.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"

    ts = str(article.get("time_published") or "").strip()
    pub_date = ts[:8] if len(ts) >= 8 and ts[:8].isdigit() else ""
    source = str(article.get("source") or article.get("source_name") or "").strip().lower()
    title = str(article.get("title") or article.get("headline") or "").strip().lower()
    return f"src_title_date:{source}|{title}|{pub_date}"


def _dedupe_articles(
    feed: Iterable[Dict[str, Any]], *, fallback_symbol: str = ""
) -> List[Dict[str, Any]]:
    """Deduplicate one symbol-month article feed."""
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in feed:
        article = _normalize_article(raw, fallback_symbol=fallback_symbol)
        if article is None:
            continue
        key = _article_dedupe_key(article)
        if key in seen:
            continue
        seen.add(key)
        out.append(article)
    return out


def _merge_month_articles(
    existing_articles: Iterable[Dict[str, Any]],
    incoming_articles: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge existing+incoming month records with incoming overwrite on dedupe-key match."""
    merged: Dict[str, Dict[str, Any]] = {}
    for article in existing_articles:
        normalized = _normalize_article(article)
        if normalized is None:
            continue
        merged[_article_dedupe_key(normalized)] = normalized
    for article in incoming_articles:
        normalized = _normalize_article(article)
        if normalized is None:
            continue
        merged[_article_dedupe_key(normalized)] = normalized
    return list(merged.values())


# ---------------------------------------------------------------------------
# Sentiment scoring (L-M lexicon)
# ---------------------------------------------------------------------------


def _tokenize_text(text: str) -> List[str]:
    """Tokenize free text into lowercase alphanumeric tokens."""
    return [t for t in _TOKEN_SPLIT_RE.split(text.lower()) if t]


def _score_text(text: str) -> float:
    """Score sentiment using LM lexicon if available, otherwise fallback lexicon."""
    _ensure_sentiment_backend()

    if _LM_ANALYZER:
        tokens = _LM_ANALYZER.tokenize(text)
        stats = _LM_ANALYZER.get_score(tokens)
        pos = float(stats.get("Positive", 0.0))
        neg = float(stats.get("Negative", 0.0))
        return (pos - neg) / (pos + neg + 1.0)

    tokens = _tokenize_text(text)
    pos = sum(1 for t in tokens if t in _FALLBACK_POSITIVE)
    neg = sum(1 for t in tokens if t in _FALLBACK_NEGATIVE)
    return float((pos - neg) / (pos + neg + 1.0))


def compute_sentiment_scores(feed: Iterable[Dict[str, Any]]) -> List[float]:
    """Compute per-article sentiment scores from title/summary."""
    scores: List[float] = []
    for article in feed:
        title = str(article.get("title") or article.get("headline") or "")
        summary = str(article.get("summary") or "")
        text = (title + " " + summary).strip()
        if not text:
            continue
        scores.append(_score_text(text))
    return scores


def _detect_event_proxy_flags(text: str) -> Dict[str, bool]:
    """Infer lightweight free-data event tags from article text."""
    normalized = str(text or "").strip().lower()
    if not normalized:
        return {
            "earnings_related": False,
            "earnings_negative": False,
            "rating_downgrade": False,
            "rating_upgrade": False,
        }
    earnings_related = any(keyword in normalized for keyword in _EARNINGS_KEYWORDS)
    earnings_negative = earnings_related and any(
        keyword in normalized for keyword in _EARNINGS_NEGATIVE_KEYWORDS
    )
    return {
        "earnings_related": earnings_related,
        "earnings_negative": earnings_negative,
        "rating_downgrade": any(keyword in normalized for keyword in _RATING_DOWNGRADE_KEYWORDS),
        "rating_upgrade": any(keyword in normalized for keyword in _RATING_UPGRADE_KEYWORDS),
    }


def _article_observation_date(
    article: Dict[str, Any], default_date: str, strict_time: bool = False
) -> tuple[Optional[str], bool]:
    """Resolve article date from payload; optionally drop rows with missing timestamp."""
    raw = str(article.get("time_published") or "").strip()
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}", False
    publish_date = _coerce_publish_date_text(article.get("publish_date"))
    if publish_date:
        return publish_date, False
    if strict_time:
        return None, False
    return default_date, True


# ---------------------------------------------------------------------------
# Alpha Vantage API fetch (historical data source)
# ---------------------------------------------------------------------------


def _date_time_range(start_date: date, end_date: date) -> tuple[str, str]:
    """Build Alpha Vantage NEWS_SENTIMENT time_from/time_to range for any date span."""
    return (
        start_date.strftime("%Y%m%dT0000"),
        end_date.strftime("%Y%m%dT2359"),
    )


def _fetch_news_for_range(
    symbol: str,
    api_key: str,
    *,
    time_from: str,
    time_to: str,
) -> Dict[str, Any]:
    """Fetch one symbol-range NEWS_SENTIMENT payload with retry/backoff."""
    parsed = urlparse(ALPHA_VANTAGE_BASE_URL)
    if parsed.scheme != "https" or parsed.netloc != "www.alphavantage.co":
        raise RuntimeError("Invalid Alpha Vantage base URL configuration.")

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": symbol,
        "time_from": time_from,
        "time_to": time_to,
        "limit": 200,
        "apikey": api_key,
    }

    last_err: Exception | None = None
    for attempt in range(ALPHA_VANTAGE_MAX_RETRIES + 1):
        try:
            response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=(5, 30))
            response.raise_for_status()
            payload = response.json()

            if "Error Message" in payload:
                raise RuntimeError(payload["Error Message"])
            if "Information" in payload:
                raise RuntimeError(payload["Information"])
            if "Note" in payload:
                raise RuntimeError(payload["Note"])

            return payload
        except Exception as exc:
            last_err = exc
            if attempt < ALPHA_VANTAGE_MAX_RETRIES:
                time.sleep(ALPHA_VANTAGE_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise

    raise last_err or RuntimeError("Unknown Alpha Vantage error")


def _fetch_av_articles(
    symbol: str, fetch_start: date, fetch_end: date, api_key: str
) -> List[Dict[str, Any]]:
    """Fetch Alpha Vantage NEWS_SENTIMENT articles for one symbol/date window."""
    time_from, time_to = _date_time_range(fetch_start, fetch_end)
    payload = _fetch_news_for_range(symbol, api_key, time_from=time_from, time_to=time_to)
    articles = _dedupe_articles(payload.get("feed") or [], fallback_symbol=symbol)
    time.sleep(ALPHA_VANTAGE_THROTTLE_SECONDS)
    return articles


# ---------------------------------------------------------------------------
# Finnhub API fetch (incremental data source)
# ---------------------------------------------------------------------------


def _get_finnhub_api_key() -> Optional[str]:
    """Return configured Finnhub API key, if available."""
    from modules.extract.finnhub_news import _get_api_key

    return _get_api_key()


def _fetch_finnhub_articles(
    symbol: str, fetch_start: date, fetch_end: date
) -> List[Dict[str, Any]]:
    """Fetch Finnhub articles for one symbol/date window."""
    from modules.extract.finnhub_news import fetch_news_for_symbol

    api_key = _get_finnhub_api_key()
    if not api_key:
        return []
    return fetch_news_for_symbol(
        symbol,
        from_date=fetch_start,
        to_date=fetch_end,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Provider routing: AV (historical) -> Finnhub (incremental)
# ---------------------------------------------------------------------------


def _fetch_provider_articles(
    symbol: str,
    *,
    fetch_start: date,
    fetch_end: date,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Fetch articles from the appropriate provider based on the date window.

    Routing logic:
    - If the window falls entirely on or before ``av_cutoff_date``, use Alpha Vantage.
    - If the window falls entirely after ``av_cutoff_date``, use Finnhub.
    - If the window spans the cutoff, split into two sub-windows and merge results.
    - If no AV key is available, fall back to Finnhub for the entire window.
    """
    av_cutoff = _resolve_av_cutoff_date(config)
    av_key = _resolve_alpha_key(config)

    # No AV key or no cutoff configured -> use Finnhub for everything
    if not av_key or av_cutoff is None:
        if not av_key and av_cutoff is not None:
            logger.warning(
                "source_b: av_cutoff_date configured but ALPHA_VANTAGE_API_KEY missing, "
                "falling back to Finnhub for symbol=%s %s..%s",
                symbol,
                fetch_start,
                fetch_end,
            )
        return _fetch_finnhub_or_empty(symbol, fetch_start, fetch_end)

    # Entire window is historical -> AV only
    if fetch_end <= av_cutoff:
        logger.debug(
            "source_b: AV route symbol=%s %s..%s (historical)",
            symbol,
            fetch_start,
            fetch_end,
        )
        return _fetch_av_articles(symbol, fetch_start, fetch_end, av_key)

    # Entire window is incremental -> Finnhub only
    if fetch_start > av_cutoff:
        logger.debug(
            "source_b: Finnhub route symbol=%s %s..%s (incremental)",
            symbol,
            fetch_start,
            fetch_end,
        )
        return _fetch_finnhub_or_empty(symbol, fetch_start, fetch_end)

    # Window spans the cutoff -> split and merge
    logger.debug(
        "source_b: split route symbol=%s AV=%s..%s Finnhub=%s..%s",
        symbol,
        fetch_start,
        av_cutoff,
        av_cutoff + timedelta(days=1),
        fetch_end,
    )
    av_articles = _fetch_av_articles(symbol, fetch_start, av_cutoff, av_key)
    finnhub_start = av_cutoff + timedelta(days=1)
    finnhub_articles = _fetch_finnhub_or_empty(symbol, finnhub_start, fetch_end)
    return _dedupe_articles(av_articles + finnhub_articles)


def _fetch_finnhub_or_empty(
    symbol: str, fetch_start: date, fetch_end: date
) -> List[Dict[str, Any]]:
    """Fetch Finnhub articles; return empty list on failure instead of raising."""
    try:
        return _fetch_finnhub_articles(symbol, fetch_start, fetch_end)
    except Exception as exc:
        logger.warning(
            "source_b provider_warning symbol=%s provider=finnhub window=%s..%s error=%r",
            symbol,
            fetch_start,
            fetch_end,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Ingest one symbol-month
# ---------------------------------------------------------------------------


def _build_backfill_start_date(run_date: str, backfill_years: int) -> date:
    """Return inclusive backfill start date for one run."""
    run_dt = datetime.strptime(run_date, "%Y-%m-%d").date()
    years = int(backfill_years)
    return run_dt if years <= 0 else _shift_months_date(run_dt, -(12 * years))


def _filter_articles_to_window(
    articles: Iterable[Dict[str, Any]],
    *,
    symbol: str,
    fetch_start: date,
    fetch_end: date,
) -> List[Dict[str, Any]]:
    """Keep only articles whose resolved observation date falls inside one window."""
    filtered: List[Dict[str, Any]] = []
    default_obs_date = fetch_start.isoformat()
    for article in articles:
        normalized = _normalize_article(article, fallback_symbol=symbol)
        if normalized is None:
            continue
        obs_date_text, _ = _article_observation_date(
            normalized, default_obs_date, strict_time=False
        )
        if not obs_date_text:
            continue
        try:
            obs_date = datetime.strptime(obs_date_text, "%Y-%m-%d").date()
        except ValueError:
            continue
        if fetch_start <= obs_date <= fetch_end:
            filtered.append(normalized)
    return _dedupe_articles(filtered, fallback_symbol=symbol)


def _load_replayable_month_articles(
    config: Optional[Dict[str, Any]],
    *,
    symbol: str,
    month_start: date,
    fetch_start: date,
    fetch_end: date,
) -> List[Dict[str, Any]]:
    """Load replayable month articles from stable current view or archived raw snapshot."""
    current_articles = _load_current_month_articles(config, symbol, month_start)
    current_window_articles = _filter_articles_to_window(
        current_articles,
        symbol=symbol,
        fetch_start=fetch_start,
        fetch_end=fetch_end,
    )
    if current_window_articles:
        return current_window_articles

    raw_articles = _load_latest_raw_month_articles(config, symbol, month_start)
    return _filter_articles_to_window(
        raw_articles,
        symbol=symbol,
        fetch_start=fetch_start,
        fetch_end=fetch_end,
    )


def _ingest_symbol_month(
    *,
    symbol: str,
    run_date: str,
    month_start: date,
    fetch_end: date,
    backfill_start_date: date,
    config: Optional[Dict[str, Any]] = None,
    force_replay: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fetch, merge, archive, and checkpoint one Source B symbol-month window."""
    run_dt = datetime.strptime(run_date, "%Y-%m-%d").date()
    initial_fetch_start = month_start
    if month_start == date(backfill_start_date.year, backfill_start_date.month, 1):
        initial_fetch_start = max(initial_fetch_start, backfill_start_date)

    natural_month_end = _natural_month_end(month_start)
    cutoff_date = _resolve_av_cutoff_date(config)
    cutoff_month_start = cutoff_date.replace(day=1) if cutoff_date is not None else None
    can_replay_history = cutoff_month_start is not None and month_start < cutoff_month_start
    if can_replay_history:
        replay_articles = _load_replayable_month_articles(
            config,
            symbol=symbol,
            month_start=month_start,
            fetch_start=initial_fetch_start,
            fetch_end=fetch_end,
        )
        if replay_articles:
            _save_current_month_articles(config, symbol, month_start, replay_articles)
            replay_last_ingested = min(fetch_end, natural_month_end, run_dt)
            _save_month_cursor(
                config,
                symbol,
                month_start,
                replay_last_ingested,
                is_closed=(replay_last_ingested >= natural_month_end),
            )
            return {
                "symbol": symbol,
                "month_start": month_start.isoformat(),
                "month_end": natural_month_end.isoformat(),
                "fetch_start": initial_fetch_start.isoformat(),
                "fetch_end": fetch_end.isoformat(),
                "feed": replay_articles,
                "ingestion_mode": "archive_replay",
            }

    if not force_replay and _load_month_cursor_closed(config, symbol, month_start):
        return None

    buffer_days = max(0, int(SOURCE_B_INCREMENTAL_BUFFER_DAYS))
    last_ingested = None if force_replay else _load_month_cursor(config, symbol, month_start)

    if last_ingested is None:
        fetch_start = initial_fetch_start
    else:
        fetch_start = max(month_start, last_ingested - timedelta(days=buffer_days))

    if fetch_start > fetch_end:
        return None

    fetched_articles = _fetch_provider_articles(
        symbol,
        fetch_start=fetch_start,
        fetch_end=fetch_end,
        config=config,
    )
    existing_articles = _load_current_month_articles(config, symbol, month_start)
    merged_month_articles = _merge_month_articles(existing_articles, fetched_articles)
    _save_raw_to_minio(config, symbol, run_date, month_start, fetched_articles)
    _save_current_month_articles(config, symbol, month_start, merged_month_articles)

    new_last_ingested = min(fetch_end, run_dt)
    _save_month_cursor(
        config,
        symbol,
        month_start,
        new_last_ingested,
        is_closed=(new_last_ingested >= natural_month_end),
    )
    return {
        "symbol": symbol,
        "month_start": month_start.isoformat(),
        "month_end": natural_month_end.isoformat(),
        "fetch_start": fetch_start.isoformat(),
        "fetch_end": fetch_end.isoformat(),
        "feed": fetched_articles,
        "ingestion_mode": "provider_fetch",
    }


# ---------------------------------------------------------------------------
# Bulk ingest
# ---------------------------------------------------------------------------


def ingest_source_b_raw(
    symbols: List[str],
    run_date: str,
    backfill_years: int,
    frequency: str,
    config: Optional[Dict[str, Any]] = None,
    failed_months_out: Optional[List[Dict[str, str]]] = None,
    skip_month_keys: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Ingest raw Source B payloads from AV (historical) + Finnhub (incremental)."""
    _ = frequency
    if os.getenv("CW1_TEST_MODE") == "1":
        return []

    windows = _month_windows(run_date, backfill_years)
    backfill_start_date = _build_backfill_start_date(run_date, backfill_years)
    target_symbols = _filter_symbols_for_source_b(symbols, config)
    if not target_symbols:
        logger.info("source_b: no symbols left after filtering policy")
        return []

    raw_payloads: List[Dict[str, Any]] = []
    skipped = {str(x) for x in (skip_month_keys or set())}

    for symbol in target_symbols:
        for month_start, fetch_end in windows:
            month_key = (
                f"{str(symbol).strip().upper()}:"
                f"{month_start.isoformat()}:{fetch_end.isoformat()}"
            )
            if month_key in skipped:
                continue
            try:
                payload = _ingest_symbol_month(
                    symbol=symbol,
                    run_date=run_date,
                    month_start=month_start,
                    fetch_end=fetch_end,
                    backfill_start_date=backfill_start_date,
                    config=config,
                )
                if payload is not None:
                    raw_payloads.append(payload)
            except Exception as exc:
                logger.warning("source_b fetch failed for %s %s: %r", symbol, month_start, exc)
                if failed_months_out is not None:
                    failed_months_out.append(
                        {
                            "symbol": symbol,
                            "month_start": str(month_start),
                            "reason": f"{exc!r}",
                        }
                    )

    return raw_payloads


# ---------------------------------------------------------------------------
# Transform: raw payloads -> daily sentiment/count atomic records
# ---------------------------------------------------------------------------


def transform_source_b_features(
    raw_payloads: List[Dict[str, Any]],
    symbols: List[str],
    run_date: str,
    frequency: str,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Transform raw Source B payloads into daily sentiment/count atomic records."""
    if os.getenv("CW1_TEST_MODE") == "1":
        out: List[Dict[str, Any]] = []
        for symbol in symbols:
            out.append(
                {
                    "symbol": symbol,
                    "observation_date": run_date,
                    "factor_name": "news_sentiment_daily",
                    "factor_value": 0.0,
                    "source": "av+finnhub",
                    "metric_frequency": "daily",
                    "source_report_date": run_date,
                }
            )
            out.append(
                {
                    "symbol": symbol,
                    "observation_date": run_date,
                    "factor_name": "news_article_count_daily",
                    "factor_value": 1.0,
                    "source": "av+finnhub",
                    "metric_frequency": "daily",
                    "source_report_date": run_date,
                }
            )
        return out

    strict_time = _resolve_source_b_strict_time(config)
    records: List[Dict[str, Any]] = []
    daily_sentiments: Dict[tuple[str, str], List[float]] = {}
    daily_counts: Dict[tuple[str, str], int] = {}
    daily_earnings_counts: Dict[tuple[str, str], int] = {}
    daily_earnings_negative_counts: Dict[tuple[str, str], int] = {}
    daily_rating_downgrade_counts: Dict[tuple[str, str], int] = {}
    daily_rating_upgrade_counts: Dict[tuple[str, str], int] = {}
    inferred_time_keys: set[tuple[str, str]] = set()
    time_fallback_count = 0
    time_drop_count = 0
    schema_warning_count = 0
    validation_issue_counts: Dict[str, int] = {}

    for payload in raw_payloads:
        symbol = str(payload.get("symbol") or "").strip().upper()
        default_obs_date = str(
            payload.get("fetch_start")
            or payload.get("month_start")
            or payload.get("month_end")
            or ""
        ).strip()
        feed = payload.get("feed") or []
        if not symbol or not default_obs_date:
            continue
        for article in feed:
            if str(article.get("schema_validation_status") or "valid").strip().lower() != "valid":
                schema_warning_count += 1
                for issue in article.get("schema_validation_errors") or []:
                    issue_key = str(issue or "").strip()
                    if issue_key:
                        validation_issue_counts[issue_key] = int(
                            validation_issue_counts.get(issue_key, 0) + 1
                        )
            obs_date, inferred = _article_observation_date(
                article, default_obs_date, strict_time=strict_time
            )
            if not obs_date:
                time_drop_count += 1
                continue
            key = (symbol, obs_date)
            if inferred:
                time_fallback_count += 1
                inferred_time_keys.add(key)
            daily_counts[key] = int(daily_counts.get(key, 0) + 1)

            title = str(article.get("title") or article.get("headline") or "")
            summary = str(article.get("summary") or "")
            text = (title + " " + summary).strip()
            if not text:
                continue
            score = _score_text(text)
            score = max(-1.0, min(1.0, float(score)))
            daily_sentiments.setdefault(key, []).append(score)
            flags = _detect_event_proxy_flags(text)
            if flags["earnings_related"]:
                daily_earnings_counts[key] = int(daily_earnings_counts.get(key, 0) + 1)
            if flags["earnings_negative"]:
                daily_earnings_negative_counts[key] = int(
                    daily_earnings_negative_counts.get(key, 0) + 1
                )
            if flags["rating_downgrade"]:
                daily_rating_downgrade_counts[key] = int(
                    daily_rating_downgrade_counts.get(key, 0) + 1
                )
            if flags["rating_upgrade"]:
                daily_rating_upgrade_counts[key] = int(daily_rating_upgrade_counts.get(key, 0) + 1)

    for (symbol, obs_date), scores in sorted(daily_sentiments.items()):
        key = (symbol, obs_date)
        records.append(
            {
                "symbol": symbol,
                "observation_date": obs_date,
                "factor_name": "news_sentiment_daily",
                "factor_value": float(sum(scores) / len(scores)),
                "source": "av+finnhub",
                "metric_frequency": frequency,
                "source_report_date": obs_date,
                "publish_date": obs_date,
                "timestamp_inferred": 1 if key in inferred_time_keys else 0,
            }
        )
    for (symbol, obs_date), count in sorted(daily_counts.items()):
        key = (symbol, obs_date)
        records.append(
            {
                "symbol": symbol,
                "observation_date": obs_date,
                "factor_name": "news_article_count_daily",
                "factor_value": float(count),
                "source": "av+finnhub",
                "metric_frequency": frequency,
                "source_report_date": obs_date,
                "publish_date": obs_date,
                "timestamp_inferred": 1 if key in inferred_time_keys else 0,
            }
        )

    event_daily_specs = (
        ("earnings_news_count_daily", daily_earnings_counts),
        ("earnings_negative_news_count_daily", daily_earnings_negative_counts),
        ("rating_downgrade_count_daily", daily_rating_downgrade_counts),
        ("rating_upgrade_count_daily", daily_rating_upgrade_counts),
    )
    for factor_name, aggregate in event_daily_specs:
        for (symbol, obs_date), count in sorted(aggregate.items()):
            key = (symbol, obs_date)
            records.append(
                {
                    "symbol": symbol,
                    "observation_date": obs_date,
                    "factor_name": factor_name,
                    "factor_value": float(count),
                    "source": "av+finnhub",
                    "metric_frequency": frequency,
                    "source_report_date": obs_date,
                    "publish_date": obs_date,
                    "timestamp_inferred": 1 if key in inferred_time_keys else 0,
                }
            )

    if time_fallback_count or time_drop_count:
        logger.warning(
            "source_b_time_quality strict_time=%s "
            "fallback_to_default_obs_date=%s dropped_missing_time=%s",
            strict_time,
            time_fallback_count,
            time_drop_count,
        )
    if schema_warning_count:
        logger.warning(
            "source_b_schema_quality warning_articles=%s issue_counts=%s",
            schema_warning_count,
            json.dumps(validation_issue_counts, sort_keys=True),
        )

    return records


def build_source_b_kafka_payloads(
    *,
    raw_payload: Optional[Dict[str, Any]],
    records: Sequence[Dict[str, Any]],
    run_id: str,
    run_date: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build Kafka-ready structured-news and daily event-proxy payloads."""
    news_events: List[Dict[str, Any]] = []
    event_proxy_events: List[Dict[str, Any]] = []

    payload = dict(raw_payload or {})
    symbol = str(payload.get("symbol") or "").strip().upper()
    feed = payload.get("feed") or []
    default_obs_date = str(
        payload.get("fetch_start")
        or payload.get("month_start")
        or payload.get("month_end")
        or run_date
    ).strip()

    for article in feed:
        title = str(article.get("title") or article.get("headline") or "").strip()
        summary = str(article.get("summary") or "").strip()
        text = (title + " " + summary).strip()
        obs_date, inferred = _article_observation_date(article, default_obs_date, strict_time=False)
        flags = _detect_event_proxy_flags(text)
        event_source = str(article.get("data_source") or article.get("source") or "source_b")
        news_events.append(
            {
                "event_id": f"{run_id}:{symbol}:{_article_dedupe_key(article)}",
                "event_type": "news_article_structured",
                "source": event_source,
                "normalized_schema_version": str(
                    article.get("normalized_schema_version") or _SOURCE_B_NORMALIZED_SCHEMA_VERSION
                ),
                "provider_payload_version": _resolve_provider_payload_version(
                    article, event_source
                ),
                "run_id": run_id,
                "run_date": run_date,
                "symbol": symbol,
                "observation_date": obs_date,
                "publish_date": _coerce_publish_date_text(article.get("publish_date")) or obs_date,
                "time_published": str(article.get("time_published") or "").strip() or None,
                "time_precision": str(article.get("time_precision") or "").strip() or None,
                "timestamp_inferred": bool(inferred),
                "schema_validation_status": str(article.get("schema_validation_status") or "valid"),
                "schema_validation_errors": list(article.get("schema_validation_errors") or []),
                "url": str(article.get("url") or "").strip() or None,
                "title": title or None,
                "summary": summary or None,
                "sentiment_score": _score_text(text) if text else None,
                **flags,
            }
        )

    allowed_factor_names = {
        "news_sentiment_daily",
        "news_article_count_daily",
        "earnings_news_count_daily",
        "earnings_negative_news_count_daily",
        "rating_downgrade_count_daily",
        "rating_upgrade_count_daily",
    }
    for record in records:
        factor_name = str(record.get("factor_name") or "").strip()
        if factor_name not in allowed_factor_names:
            continue
        record_symbol = str(record.get("symbol") or symbol).strip().upper()
        obs_date = str(record.get("observation_date") or "").strip()
        event_proxy_events.append(
            {
                "event_id": f"{run_id}:{record_symbol}:{factor_name}:{obs_date}",
                "event_type": "daily_event_proxy",
                "source": str(record.get("source") or "source_b").strip() or "source_b",
                "run_id": run_id,
                "run_date": run_date,
                "symbol": record_symbol,
                "observation_date": obs_date,
                "publish_date": str(record.get("publish_date") or obs_date).strip() or obs_date,
                "factor_name": factor_name,
                "factor_value": record.get("factor_value"),
                "metric_frequency": record.get("metric_frequency"),
                "source_report_date": record.get("source_report_date"),
                "timestamp_inferred": bool(int(record.get("timestamp_inferred") or 0)),
            }
        )

    return {
        "news_structured": news_events,
        "event_proxies": event_proxy_events,
    }


# ---------------------------------------------------------------------------
# Single-window entry point (used by Airflow DAG)
# ---------------------------------------------------------------------------


def extract_source_b_window(
    *,
    symbol: str,
    run_date: str,
    month_start: date,
    fetch_end: date,
    backfill_years: int,
    frequency: str,
    config: Optional[Dict[str, Any]] = None,
    force_replay: bool = False,
) -> Dict[str, Any]:
    """Run one symbol-month Source B unit and return records plus summary details."""
    if os.getenv("CW1_TEST_MODE") == "1":
        records = transform_source_b_features([], [symbol], run_date, frequency, config=config)
        return {"raw_payload": None, "records": records, "article_count": 0}

    payload = _ingest_symbol_month(
        symbol=symbol,
        run_date=run_date,
        month_start=month_start,
        fetch_end=fetch_end,
        backfill_start_date=_build_backfill_start_date(run_date, backfill_years),
        config=config,
        force_replay=force_replay,
    )
    raw_payloads = [payload] if payload is not None else []
    records = transform_source_b_features(
        raw_payloads,
        [symbol],
        run_date,
        frequency,
        config=config,
    )
    return {
        "raw_payload": payload,
        "records": records,
        "article_count": len((payload or {}).get("feed") or []),
    }


# ---------------------------------------------------------------------------
# End-to-end entry point
# ---------------------------------------------------------------------------


def extract_source_b(
    symbols: List[str],
    run_date: str,
    backfill_years: int,
    frequency: str,
    config: Optional[Dict[str, Any]] = None,
    failed_months_out: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Run Source B end-to-end (ingest + transform)."""
    raw_payloads = ingest_source_b_raw(
        symbols,
        run_date,
        backfill_years,
        frequency,
        config=config,
        failed_months_out=failed_months_out,
    )
    return transform_source_b_features(raw_payloads, symbols, run_date, frequency, config=config)
