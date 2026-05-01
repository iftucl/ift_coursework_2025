"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : REAL historical sentiment backfill from Alpha Vantage NEWS_SENTIMENT
Project : CW2 - Value-Sentiment Investment Strategy

Why
---
CW1 stores a single aggregated sentiment snapshot (today's date) per
company. Article-level coverage in MongoDB is limited to ~18 rows — far
below the 50-company threshold the CW2 ``SentimentSignal`` uses to
trigger the article-level path. Consequently every historical rebalance
sees the same static cross-section of sentiment and the value+sentiment
backtest degenerates into a pure value play.

This script rebuilds a real historical ``sentiment_scores`` series from
Alpha Vantage's ``NEWS_SENTIMENT`` endpoint, which publishes pre-scored
financial articles tagged with ticker-level relevance and ticker-level
sentiment scores going back several years. Every row written is a REAL
sentiment observation — no synthetic extrapolation, no price-based
proxy. The only assumption is "Alpha Vantage's sentiment model is
acceptable" — the endpoint publishes its own sentiment_score_definition
on every call so the interpretation is fully disclosed.

Method
------
For each month-end anchor in [start, end]:
    1. Call ``NEWS_SENTIMENT`` with a 30-day ``time_from`` →
       ``time_to`` window ending at the anchor. No ticker filter — we
       want the global cross-section.
    2. Walk the returned feed. For every article ``a`` and every entry
       ``s`` in ``a['ticker_sentiment']`` with ``ticker in universe``
       and ``relevance_score >= MIN_RELEVANCE``, accumulate::

           sent[ticker].append((s.sentiment_score, s.relevance_score, label))

    3. Aggregate per ticker for the month::

           avg_sentiment     = relevance-weighted average of sentiment_score
           total_articles    = number of articles referencing the ticker
           positive_count    = count of articles with label ∈ {Bullish, Somewhat-Bullish}
           negative_count    = count of articles with label ∈ {Bearish, Somewhat-Bearish}
           neutral_count     = total - positive - negative
           positive_ratio    = positive_count / total
           sentiment_score   = (avg_sentiment + 1) / 2 × 100   (PDF §A3)

    4. Upsert one row per (ticker, month-end) into
       ``systematic_equity.sentiment_scores``.

Rate-limit hygiene
------------------
Alpha Vantage's free-tier cap is ~25 calls/day per key. The script
ships with nine keys (``ALPHA_VANTAGE_KEY_1..9`` in ``.env``) and
rotates through them round-robin. We make one call per month-anchor
and sleep briefly between calls so a full monthly run (~74 calls) fits
well inside the combined daily budget (~225 calls).

Usage
-----
::

    poetry run python -m modules.data.backfill_real_alpha_vantage_sentiment \
        --start 2020-01-01 --end 2026-04-15

    # Smoke test with just the last 3 months
    poetry run python -m modules.data.backfill_real_alpha_vantage_sentiment \
        --start 2026-01-01
"""

from __future__ import annotations

import argparse
import itertools
import logging
import os
import sys
import time
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import requests
import yaml
from sqlalchemy import create_engine, engine, text

LOG_FMT = '%(asctime)s | %(name)-42s | %(levelname)-7s | %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('alpha_vantage_sentiment')

ALPHA_VANTAGE_URL = 'https://www.alphavantage.co/query'
WINDOW_DAYS = 30                    # trailing-month news window per anchor
ARTICLE_LIMIT = 1000                # max items returned per call (premium / extended limit)
MIN_RELEVANCE = 0.25                # ignore passing mentions
RATE_LIMIT_SLEEP = 1.5              # seconds between calls to stay polite

# Alpha Vantage label → coarse class
POSITIVE_LABELS = {'Bullish', 'Somewhat-Bullish'}
NEGATIVE_LABELS = {'Bearish', 'Somewhat-Bearish'}


# ---------------------------------------------------------------------------
# Config / engine
# ---------------------------------------------------------------------------

def _env_or_yaml(yaml_val, env_var: str, default: Optional[str] = None) -> Optional[str]:
    if yaml_val not in (None, '', 'null'):
        return str(yaml_val)
    ev = os.environ.get(env_var)
    if ev:
        return ev
    return default


def build_engine(cw2_config: dict):
    with open(cw2_config['cw1']['config_path'], 'r') as fh:
        cw1 = yaml.safe_load(fh)
    env_profile = cw1[cw2_config['cw1']['env_type']]
    db = env_profile.get('config', {}).get('Database', {}).get('Postgres', {}) or {}

    username = _env_or_yaml(db.get('Username'), 'POSTGRES_USERNAME', 'postgres')
    password = _env_or_yaml(db.get('Password'), 'POSTGRES_PASSWORD')
    host = _env_or_yaml(db.get('Host'), 'POSTGRES_HOST_DEV', 'localhost')
    port = str(_env_or_yaml(db.get('Port'), 'POSTGRES_PORT_DEV', '5439'))
    database = _env_or_yaml(db.get('Database'), 'POSTGRES_DATABASE', 'fift')
    if password is None:
        raise RuntimeError('No Postgres password resolved')
    url = engine.URL.create(
        drivername='postgresql', username=username, password=password,
        host=host, port=port, database=database,
    )
    return create_engine(url, pool_pre_ping=True)


def load_universe(eng) -> set:
    sql = text(
        "SELECT DISTINCT TRIM(company_id) AS ticker "
        "FROM systematic_equity.value_metrics"
    )
    with eng.connect() as conn:
        return {r[0].upper() for r in conn.execute(sql).fetchall()}


# ---------------------------------------------------------------------------
# Alpha Vantage client
# ---------------------------------------------------------------------------

def load_api_keys() -> list:
    keys = []
    for i in range(1, 10):
        k = os.environ.get(f'ALPHA_VANTAGE_KEY_{i}')
        if k and k not in keys:
            keys.append(k)
    # Legacy single-key fallback
    solo = os.environ.get('ALPHA_VANTAGE_KEY')
    if solo and solo not in keys:
        keys.append(solo)
    if not keys:
        raise RuntimeError(
            'No Alpha Vantage API keys found. Set ALPHA_VANTAGE_KEY_1..9 in .env'
        )
    logger.info('Loaded %d Alpha Vantage API keys', len(keys))
    return keys


def _fmt(ts: pd.Timestamp) -> str:
    """Alpha Vantage wants ``YYYYMMDDTHHMM`` (UTC)."""
    return ts.strftime('%Y%m%dT%H%M')


def fetch_month_feed(
    time_from: pd.Timestamp,
    time_to: pd.Timestamp,
    api_key: str,
    max_retries: int = 3,
) -> list:
    """Pull the ``NEWS_SENTIMENT`` feed for a single month window.

    Returns an empty list on rate-limit or API error so the caller can
    rotate keys and move on.
    """
    params = {
        'function': 'NEWS_SENTIMENT',
        'time_from': _fmt(time_from),
        'time_to': _fmt(time_to),
        'limit': ARTICLE_LIMIT,
        'sort': 'EARLIEST',
        'apikey': api_key,
    }
    for attempt in range(max_retries):
        try:
            r = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
            r.raise_for_status()
            d = r.json()
        except Exception as exc:  # pylint: disable=broad-except
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            logger.warning('AV request failed: %s', exc)
            return []

        # Rate-limit / error signals from Alpha Vantage
        if 'Information' in d or 'Note' in d:
            msg = d.get('Information') or d.get('Note')
            logger.warning('AV rate-limit hit: %s', str(msg)[:120])
            return []
        feed = d.get('feed', [])
        if not isinstance(feed, list):
            return []
        return feed
    return []


# ---------------------------------------------------------------------------
# Monthly aggregation
# ---------------------------------------------------------------------------

def aggregate_feed_to_rows(
    feed: list,
    universe: set,
    anchor: pd.Timestamp,
) -> list:
    """Convert one month's raw feed into ticker-level DB rows."""
    if not feed:
        return []

    # per-ticker accumulator
    accum: dict = defaultdict(lambda: {
        'scores': [],
        'relevances': [],
        'labels': [],
    })
    for article in feed:
        for t in article.get('ticker_sentiment', []):
            try:
                ticker = str(t.get('ticker', '')).strip().upper()
                rel = float(t.get('relevance_score', 0) or 0)
                sc = float(t.get('ticker_sentiment_score', 0) or 0)
            except (TypeError, ValueError):
                continue
            if not ticker or ticker not in universe:
                continue
            if rel < MIN_RELEVANCE:
                continue
            accum[ticker]['scores'].append(sc)
            accum[ticker]['relevances'].append(rel)
            accum[ticker]['labels'].append(t.get('ticker_sentiment_label', 'Neutral'))

    date_str = anchor.strftime('%Y-%m-%d')
    rows = []
    for ticker, bucket in accum.items():
        scores = np.array(bucket['scores'], dtype=float)
        relevances = np.array(bucket['relevances'], dtype=float)
        labels = bucket['labels']
        n = len(scores)
        if n == 0:
            continue

        if relevances.sum() > 0:
            weighted = float(np.average(scores, weights=relevances))
        else:
            weighted = float(scores.mean())

        pos = sum(1 for lb in labels if lb in POSITIVE_LABELS)
        neg = sum(1 for lb in labels if lb in NEGATIVE_LABELS)
        neu = n - pos - neg
        pos_ratio = pos / n if n else 0.0
        sentiment_score = (max(-1.0, min(1.0, weighted)) + 1.0) / 2.0 * 100.0

        rows.append({
            'company_id': ticker,
            'date': date_str,
            'avg_sentiment': round(weighted, 4),
            'positive_count': pos,
            'negative_count': neg,
            'neutral_count': neu,
            'total_articles': n,
            'positive_ratio': round(pos_ratio, 4),
            'sentiment_score': round(sentiment_score, 4),
        })
    return rows


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

UPSERT_SQL = text(
    """
    INSERT INTO systematic_equity.sentiment_scores
        (company_id, date, avg_sentiment, positive_count, negative_count,
         neutral_count, total_articles, positive_ratio, sentiment_score)
    VALUES
        (:company_id, :date, :avg_sentiment, :positive_count, :negative_count,
         :neutral_count, :total_articles, :positive_ratio, :sentiment_score)
    ON CONFLICT (company_id, date) DO UPDATE SET
        avg_sentiment = EXCLUDED.avg_sentiment,
        positive_count = EXCLUDED.positive_count,
        negative_count = EXCLUDED.negative_count,
        neutral_count = EXCLUDED.neutral_count,
        total_articles = EXCLUDED.total_articles,
        positive_ratio = EXCLUDED.positive_ratio,
        sentiment_score = EXCLUDED.sentiment_score,
        ingestion_timestamp = NOW()
    """
)


def upsert_sentiment(eng, records: list, chunk: int = 2000) -> int:
    if not records:
        return 0
    total = 0
    with eng.begin() as conn:
        for i in range(0, len(records), chunk):
            conn.execute(UPSERT_SQL, records[i:i + chunk])
            total += len(records[i:i + chunk])
    return total


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

def monthly_anchors(start: pd.Timestamp, end: pd.Timestamp) -> list:
    out = []
    cur = pd.Timestamp(start).normalize().replace(day=1)
    while cur <= end:
        month_end = cur + pd.offsets.MonthEnd(0)
        out.append(min(month_end, pd.Timestamp(end)))
        cur = cur + pd.offsets.MonthBegin(1)
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Backfill REAL historical sentiment from Alpha Vantage'
    )
    parser.add_argument('--config', default='config/backtest_config.yaml')
    parser.add_argument('--start', default='2020-01-01')
    parser.add_argument('--end', default=None)
    args = parser.parse_args()

    with open(args.config, 'r') as fh:
        cw2_config = yaml.safe_load(fh)

    eng = build_engine(cw2_config)
    universe = load_universe(eng)
    logger.info('Universe: %d tickers', len(universe))

    api_keys = load_api_keys()
    key_cycle = itertools.cycle(api_keys)

    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.today()
    anchors = monthly_anchors(pd.Timestamp(args.start), end)
    logger.info('Month anchors: %d (%s → %s)', len(anchors), anchors[0], anchors[-1])

    all_records = []
    successful_months = 0
    for anchor in anchors:
        time_from = anchor - pd.Timedelta(days=WINDOW_DAYS)
        time_to = anchor
        api_key = next(key_cycle)

        feed = fetch_month_feed(time_from, time_to, api_key)
        rows = aggregate_feed_to_rows(feed, universe, anchor)

        if rows:
            successful_months += 1
            logger.info('%s: %d articles → %d tickers with sentiment',
                         anchor.strftime('%Y-%m'), len(feed), len(rows))
            all_records.extend(rows)
        else:
            logger.info('%s: no tickers matched (feed=%d, key=%s...)',
                         anchor.strftime('%Y-%m'), len(feed), api_key[:6])

        time.sleep(RATE_LIMIT_SLEEP)

    logger.info('Total rows generated: %d across %d months',
                len(all_records), successful_months)

    if all_records:
        n = upsert_sentiment(eng, all_records)
        logger.info('Upserted %d REAL sentiment_scores rows', n)
    else:
        logger.warning('No records produced — check Alpha Vantage rate limits')


if __name__ == '__main__':
    main()
