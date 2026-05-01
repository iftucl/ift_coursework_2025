from __future__ import annotations

"""Unstructured extractor (Source B): Alpha Vantage news text -> daily sentiment atomics.

Pipeline contract:
1) ingest_source_b_raw: fetch raw news JSON and persist run snapshots to MinIO
2) transform_source_b_features: compute sentiment from title/summary and emit daily records
"""

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

import requests

from .symbol_filter import filter_symbols

logger = logging.getLogger(__name__)

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
_ALPHA_KEY_PLACEHOLDERS = {
    "",
    "YOUR_KEY",
    "YOUR_API_KEY_HERE",
    "ALPHA_VANTAGE_API_KEY",
    "REPLACE_WITH_YOUR_KEY",
}
# Throttle between API calls (seconds). Keep configurable for reproducibility.
ALPHA_VANTAGE_THROTTLE_SECONDS = float(os.getenv("ALPHA_VANTAGE_THROTTLE_SECONDS", "1.0"))
# Retry policy for transient/rate-limit responses.
ALPHA_VANTAGE_MAX_RETRIES = int(os.getenv("ALPHA_VANTAGE_MAX_RETRIES", "3"))
ALPHA_VANTAGE_RETRY_BACKOFF_SECONDS = float(os.getenv("ALPHA_VANTAGE_RETRY_BACKOFF_SECONDS", "5.0"))
SOURCE_B_INCREMENTAL_BUFFER_DAYS = int(os.getenv("SOURCE_B_INCREMENTAL_BUFFER_DAYS", "3"))

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# Minimal fallback lexicon if pysentiment2 is unavailable in runtime.
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

_LM_ANALYZER = None
_SENTIMENT_BACKEND_LOGGED = False


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
                "source_b sentiment_backend=fallback_lexicon " "reason=pysentiment2_unavailable"
            )
        _SENTIMENT_BACKEND_LOGGED = True


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


def _resolve_source_b_strict_time(config: Optional[Dict[str, Any]]) -> bool:
    """Resolve strict timestamp policy for Source B article rows."""
    source_cfg = (config or {}).get("source_b") or {}
    raw = source_cfg.get("strict_time", False)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


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
    # If not explicitly provided, infer secure from the endpoint scheme.
    if cfg.get("secure") is None:
        cfg["secure"] = is_https
    return cfg


def _month_end_dates(run_date: str, backfill_years: int) -> List[date]:
    """Return inclusive month-end dates for the requested backfill window."""
    end = datetime.strptime(run_date, "%Y-%m-%d").date()
    years = int(backfill_years)
    if years <= 0:
        return [end]
    start = _shift_months_date(end, -(12 * years))
    months: List[date] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        if cur.month == 12:
            next_month = date(cur.year + 1, 1, 1)
        else:
            next_month = date(cur.year, cur.month + 1, 1)
        month_end = next_month.fromordinal(next_month.toordinal() - 1)
        if start <= month_end <= end:
            months.append(month_end)
        cur = next_month
    return months


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


def _month_time_range(month_end: date) -> tuple[str, str]:
    """Build Alpha Vantage NEWS_SENTIMENT time_from/time_to range for one month."""
    month_start = month_end.replace(day=1)
    return (
        month_start.strftime("%Y%m%dT0000"),
        month_end.strftime("%Y%m%dT2359"),
    )


def _date_time_range(start_date: date, end_date: date) -> tuple[str, str]:
    """Build Alpha Vantage NEWS_SENTIMENT time_from/time_to range for any date span."""
    return (
        start_date.strftime("%Y%m%dT0000"),
        end_date.strftime("%Y%m%dT2359"),
    )


def _natural_month_end(month_start: date) -> date:
    """Return the natural month-end for a given month-start date."""
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return next_month - timedelta(days=1)


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
        from minio import Minio

        client = Minio(
            endpoint=minio_cfg["endpoint"],
            access_key=minio_cfg["access_key"],
            secret_key=minio_cfg["secret_key"],
            secure=minio_cfg.get("secure", False),
        )
        bucket = minio_cfg["bucket"]
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        key = _raw_object_path(symbol, run_date, month_end)
        jsonl = "\n".join(json.dumps(a, ensure_ascii=False) for a in articles)
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
        from minio import Minio

        client = Minio(
            endpoint=minio_cfg["endpoint"],
            access_key=minio_cfg["access_key"],
            secret_key=minio_cfg["secret_key"],
            secure=minio_cfg.get("secure", False),
        )
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
        records.append(_normalize_article(parsed))
    return records


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
        from minio import Minio

        client = Minio(
            endpoint=minio_cfg["endpoint"],
            access_key=minio_cfg["access_key"],
            secret_key=minio_cfg["secret_key"],
            secure=minio_cfg.get("secure", False),
        )
        bucket = minio_cfg["bucket"]
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        key = _monthly_current_object_path(symbol, month_start)
        jsonl = "\n".join(json.dumps(a, ensure_ascii=False) for a in articles)
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


def _load_month_cursor(
    config: Optional[Dict[str, Any]], symbol: str, month_start: date
) -> Optional[date]:
    """Load last_ingested_date for one symbol-month cursor from MinIO."""
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return None

    try:
        from minio import Minio

        client = Minio(
            endpoint=minio_cfg["endpoint"],
            access_key=minio_cfg["access_key"],
            secret_key=minio_cfg["secret_key"],
            secure=minio_cfg.get("secure", False),
        )
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
        from minio import Minio

        client = Minio(
            endpoint=minio_cfg["endpoint"],
            access_key=minio_cfg["access_key"],
            secret_key=minio_cfg["secret_key"],
            secure=minio_cfg.get("secure", False),
        )
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
        from minio import Minio

        client = Minio(
            endpoint=minio_cfg["endpoint"],
            access_key=minio_cfg["access_key"],
            secret_key=minio_cfg["secret_key"],
            secure=minio_cfg.get("secure", False),
        )
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


def _normalize_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only required raw fields for lightweight monthly JSONL objects."""
    return {
        "article_id": str(article.get("article_id") or article.get("id") or ""),
        "time_published": str(article.get("time_published") or ""),
        "title": str(article.get("title") or ""),
        "summary": str(article.get("summary") or ""),
        "url": str(article.get("url") or ""),
        "source": str(article.get("source") or article.get("source_name") or ""),
        "topics": article.get("topics") or [],
        "ticker_hits": article.get("ticker_sentiment") or [],
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
    title = str(article.get("title") or "").strip().lower()
    return f"src_title_date:{source}|{title}|{pub_date}"


def _dedupe_articles(feed: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate monthly news feed by URL (fallback title+timestamp)."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for raw in feed:
        article = _normalize_article(raw)
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
        merged[_article_dedupe_key(normalized)] = normalized
    for article in incoming_articles:
        normalized = _normalize_article(article)
        merged[_article_dedupe_key(normalized)] = normalized
    return list(merged.values())


def _fetch_news_for_month(symbol: str, month_end: date, api_key: str) -> Dict[str, Any]:
    """Fetch one symbol-month NEWS_SENTIMENT payload with retry/backoff."""
    parsed = urlparse(ALPHA_VANTAGE_BASE_URL)
    if parsed.scheme != "https" or parsed.netloc != "www.alphavantage.co":
        raise RuntimeError("Invalid Alpha Vantage base URL configuration.")

    time_from, time_to = _month_time_range(month_end)
    return _fetch_news_for_range(symbol, api_key, time_from=time_from, time_to=time_to)


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
                # Rate limit / transient message.
                raise RuntimeError(payload["Note"])

            return payload
        except Exception as exc:
            last_err = exc
            # Backoff only if we might recover (rate limit / transient issues)
            if attempt < ALPHA_VANTAGE_MAX_RETRIES:
                time.sleep(ALPHA_VANTAGE_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise

    # Unreachable, but keeps type-checkers happy.
    raise last_err or RuntimeError("Unknown Alpha Vantage error")


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
        title = str(article.get("title") or "")
        summary = str(article.get("summary") or "")
        text = (title + " " + summary).strip()
        if not text:
            continue
        scores.append(_score_text(text))
    return scores


def _article_observation_date(
    article: Dict[str, Any], default_date: str, strict_time: bool = False
) -> tuple[Optional[str], bool]:
    """Resolve article date from payload; optionally drop rows with missing timestamp."""
    raw = str(article.get("time_published") or "").strip()
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}", False
    if strict_time:
        return None, False
    return default_date, True


def ingest_source_b_raw(
    symbols: List[str],
    run_date: str,
    backfill_years: int,
    frequency: str,
    config: Optional[Dict[str, Any]] = None,
    failed_months_out: Optional[List[Dict[str, str]]] = None,
    skip_month_keys: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Ingest raw Source B payloads from Alpha Vantage news endpoint."""
    _ = frequency  # Source B extraction cadence is independent from output sampling label.
    if os.getenv("CW1_TEST_MODE") == "1":
        return []

    api_key = _resolve_alpha_key(config)
    if not api_key:
        logger.warning("source_b skipped: alpha_vantage key missing")
        return []

    windows = _month_windows(run_date, backfill_years)
    run_dt = datetime.strptime(run_date, "%Y-%m-%d").date()
    years = int(backfill_years)
    backfill_start_date = run_dt if years <= 0 else _shift_months_date(run_dt, -(12 * years))
    first_month_start = windows[0][0] if windows else None
    buffer_days = max(0, int(SOURCE_B_INCREMENTAL_BUFFER_DAYS))
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
                if _load_month_cursor_closed(config, symbol, month_start):
                    continue

                last_ingested = _load_month_cursor(config, symbol, month_start)
                if last_ingested is None:
                    fetch_start = month_start
                    if first_month_start is not None and month_start == first_month_start:
                        fetch_start = max(fetch_start, backfill_start_date)
                else:
                    fetch_start = max(month_start, last_ingested - timedelta(days=buffer_days))

                if fetch_start > fetch_end:
                    continue

                time_from, time_to = _date_time_range(fetch_start, fetch_end)
                payload = _fetch_news_for_range(
                    symbol, api_key, time_from=time_from, time_to=time_to
                )
                fetched_articles = _dedupe_articles(payload.get("feed") or [])
                existing_articles = _load_current_month_articles(config, symbol, month_start)
                merged_month_articles = _merge_month_articles(existing_articles, fetched_articles)
                _save_raw_to_minio(config, symbol, run_date, month_start, fetched_articles)
                _save_current_month_articles(config, symbol, month_start, merged_month_articles)
                natural_month_end = _natural_month_end(month_start)
                new_last_ingested = min(fetch_end, run_dt)
                _save_month_cursor(
                    config,
                    symbol,
                    month_start,
                    new_last_ingested,
                    is_closed=(new_last_ingested >= natural_month_end),
                )
                raw_payloads.append(
                    {
                        "symbol": symbol,
                        "month_start": month_start.isoformat(),
                        "month_end": natural_month_end.isoformat(),
                        "fetch_start": fetch_start.isoformat(),
                        "fetch_end": fetch_end.isoformat(),
                        "feed": fetched_articles,
                    }
                )
                time.sleep(ALPHA_VANTAGE_THROTTLE_SECONDS)
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
                    "source": "extractor_b",
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
                    "source": "extractor_b",
                    "metric_frequency": "daily",
                    "source_report_date": run_date,
                }
            )
        return out

    strict_time = _resolve_source_b_strict_time(config)
    records: List[Dict[str, Any]] = []
    daily_sentiments: Dict[tuple[str, str], List[float]] = {}
    daily_counts: Dict[tuple[str, str], int] = {}
    inferred_time_keys: set[tuple[str, str]] = set()
    time_fallback_count = 0
    time_drop_count = 0
    for payload in raw_payloads:
        symbol = str(payload.get("symbol") or "").strip()
        # New schema uses fetch_start as fallback anchor; keep backward compatibility
        # with older payloads that only carried month_end.
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

            title = str(article.get("title") or "")
            summary = str(article.get("summary") or "")
            text = (title + " " + summary).strip()
            if not text:
                continue
            score = _score_text(text)
            # Hard cap for safety/contract consistency.
            score = max(-1.0, min(1.0, float(score)))
            daily_sentiments.setdefault(key, []).append(score)

    for (symbol, obs_date), scores in sorted(daily_sentiments.items()):
        key = (symbol, obs_date)
        records.append(
            {
                "symbol": symbol,
                "observation_date": obs_date,
                "factor_name": "news_sentiment_daily",
                "factor_value": float(sum(scores) / len(scores)),
                "source": "extractor_b",
                "metric_frequency": "daily",
                "source_report_date": obs_date,
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
                "source": "extractor_b",
                "metric_frequency": "daily",
                "source_report_date": obs_date,
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

    return records


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
