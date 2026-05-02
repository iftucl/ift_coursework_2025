"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : REAL price correction for CW1 daily_prices table
Project : CW2 - Value-Sentiment Investment Strategy

Why
---
A sanity audit of ``systematic_equity.daily_prices`` revealed that
CW1's yfinance price extraction introduced split-adjustment errors for
roughly 15 tickers (e.g. AAPL, GE, ADI, KLAC, LRCX, WDC, TPR, FTI,
STI, ITW, FMC, AHT.L, WLN.PA, FRES.L, ENR.DE). The median stored
price differs from the last stored price by >4× — the signature of
an un- or over-applied split. Known example::

    SELECT * FROM systematic_equity.daily_prices WHERE symbol='AAPL' AND cob_date='2026-04-14';
    ->  4.10

    $ python -c "import yfinance as yf; print(yf.Ticker('AAPL').history(period='5d'))"
    ->  258.83

These corrupt rows poison both the backtest returns (wrong PnL on
holdings) and any derived ratios computed from the price, so CW2's
factor signals pick up phantom value opportunities.

What it does
------------
1. Load the full ticker universe from Postgres.
2. For every ticker fetch a fresh adjusted-close series from yfinance
   using ``history(period='6y', auto_adjust=True)`` — yfinance's
   built-in split/dividend adjustment is the canonical reference.
3. Upsert the corrected rows into ``systematic_equity.daily_prices``
   via ``ON CONFLICT (symbol, cob_date) DO UPDATE``. Only the
   ``adj_close_price`` column is overwritten; other columns (open,
   high, low, volume, currency) are left untouched when already
   present, so we don't lose any metadata.

This is **real yfinance data end-to-end** — no synthetic extrapolation,
no interpolation. Every price is the split/dividend-adjusted close
published by yfinance at call time.

Usage
-----
::

    poetry run python -m modules.data.fix_prices_from_yfinance
    poetry run python -m modules.data.fix_prices_from_yfinance --tickers AAPL GE KLAC
    poetry run python -m modules.data.fix_prices_from_yfinance --only-corrupt   # default

The ``--only-corrupt`` switch restricts the fix to tickers whose
current stored last-price is >4× or <0.25× their stored median — the
heuristic used to find the affected set. Omit with ``--all`` to
re-pull every ticker (slower but guaranteed correct).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd
import yaml
import yfinance as yf
from sqlalchemy import create_engine, engine, text

LOG_FMT = '%(asctime)s | %(name)-32s | %(levelname)-7s | %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('fix_prices_from_yfinance')
logging.getLogger('yfinance').setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Config / engine helpers — mirror the DataLoader convention
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


# ---------------------------------------------------------------------------
# Corruption detection
# ---------------------------------------------------------------------------

def find_corrupt_tickers(eng) -> list:
    """Return tickers whose stored last price is >4× or <0.25× the median.

    This is the signature of a split-adjustment mistake — either the
    adjustment was applied twice or never. A 4× threshold is wider than
    any realistic 6-year rally so it flags only genuine glitches.
    """
    sql = text(
        """
        WITH stats AS (
            SELECT symbol,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY adj_close_price) AS median_px,
                   (SELECT adj_close_price FROM systematic_equity.daily_prices dp2
                    WHERE dp2.symbol = dp.symbol
                    ORDER BY cob_date DESC LIMIT 1) AS last_px
            FROM systematic_equity.daily_prices dp
            WHERE adj_close_price IS NOT NULL
            GROUP BY symbol
        )
        SELECT symbol FROM stats
        WHERE last_px IS NOT NULL AND median_px > 0
          AND (last_px / median_px < 0.25 OR last_px / median_px > 4.0)
        ORDER BY symbol
        """
    )
    with eng.connect() as conn:
        return [r[0] for r in conn.execute(sql).fetchall()]


def load_all_tickers(eng) -> list:
    sql = text(
        "SELECT DISTINCT TRIM(symbol) AS symbol FROM systematic_equity.daily_prices ORDER BY 1"
    )
    with eng.connect() as conn:
        return [r[0] for r in conn.execute(sql).fetchall()]


# ---------------------------------------------------------------------------
# yfinance fetch
# ---------------------------------------------------------------------------

def fetch_history(ticker: str, start: str = '2020-01-01',
                  end: Optional[str] = None,
                  max_retries: int = 3) -> pd.Series:
    """Pull a 6-year adjusted close series for ``ticker``.

    Using ``auto_adjust=True`` lets yfinance apply its canonical split
    and dividend adjustments — the series returned via ``Close`` is
    already the correct adjusted price for historical comparisons.
    """
    for attempt in range(max_retries):
        try:
            hist = yf.Ticker(ticker).history(
                start=start, end=end, auto_adjust=True, actions=False,
            )
            if hist is None or hist.empty:
                return pd.Series(dtype=float, name=ticker)
            closes = hist['Close'].copy()
            # yfinance returns a tz-aware DatetimeIndex — drop tz so joins
            # against the naive cob_date in Postgres are exact.
            if closes.index.tz is not None:
                closes.index = closes.index.tz_localize(None)
            closes.name = ticker
            return closes
        except Exception as exc:  # pylint: disable=broad-except
            if attempt < max_retries - 1:
                time.sleep(1.5 ** attempt)
                continue
            logger.warning('yfinance failed for %s: %s', ticker, exc)
            return pd.Series(dtype=float, name=ticker)
    return pd.Series(dtype=float, name=ticker)


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

UPDATE_SQL = text(
    """
    UPDATE systematic_equity.daily_prices
    SET adj_close_price = :adj_close_price,
        ingestion_timestamp = NOW()
    WHERE symbol = :symbol AND cob_date = :cob_date
    """
)

# Fallback insert for rows that do not yet exist in the table. The
# ``currency`` column is NOT NULL so we always hand it a sentinel
# placeholder — yfinance does not report currency per quote, but we
# can default to USD here because the purpose of this script is to
# correct stale price values and the currency is purely informational
# for downstream reporting (all value-metric scaling uses the
# adjusted-close number, not the currency).
INSERT_SQL = text(
    """
    INSERT INTO systematic_equity.daily_prices
        (symbol, cob_date, adj_close_price, currency)
    VALUES (:symbol, :cob_date, :adj_close_price, :currency)
    ON CONFLICT (symbol, cob_date) DO UPDATE SET
        adj_close_price = EXCLUDED.adj_close_price,
        ingestion_timestamp = NOW()
    """
)


def _currency_for(symbol: str) -> str:
    """Infer reporting currency from CW1's ticker-suffix convention."""
    s = symbol.upper()
    if s.endswith('.L'):
        return 'GBP'
    if s.endswith(('.PA', '.AS', '.DE', '.MC', '.MI', '.BR', '.LS')):
        return 'EUR'
    if s.endswith('.TO'):
        return 'CAD'
    if s.endswith(('.SW', '.S')):
        return 'CHF'
    return 'USD'


def upsert_prices(eng, records: list, chunk: int = 5000) -> int:
    """Correct existing adj_close rows, insert truly-new ones with currency."""
    if not records:
        return 0
    updated = 0
    with eng.begin() as conn:
        for i in range(0, len(records), chunk):
            batch = records[i:i + chunk]
            for row in batch:
                row['currency'] = _currency_for(row['symbol'])
            conn.execute(INSERT_SQL, batch)
            updated += len(batch)
    return updated


def process_ticker(ticker: str) -> list:
    closes = fetch_history(ticker)
    if len(closes) == 0:
        return []
    rows = []
    for dt, px in closes.items():
        if not np.isfinite(px) or px <= 0:
            continue
        rows.append({
            'symbol': ticker,
            'cob_date': pd.Timestamp(dt).strftime('%Y-%m-%d'),
            'adj_close_price': float(px),
        })
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Overwrite adj_close_price in daily_prices with real yfinance data'
    )
    parser.add_argument('--config', default='config/backtest_config.yaml')
    parser.add_argument('--tickers', nargs='*', default=None,
                        help='Optional ticker whitelist (space-separated)')
    parser.add_argument('--workers', type=int, default=6)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--only-corrupt', action='store_true', default=True,
                       help='(default) only fix tickers with suspect median/last ratios')
    scope.add_argument('--all', dest='only_corrupt', action='store_false',
                       help='re-fetch every ticker in the universe')
    args = parser.parse_args()

    with open(args.config, 'r') as fh:
        cw2_config = yaml.safe_load(fh)

    eng = build_engine(cw2_config)

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers]
        logger.info('Using %d explicit tickers', len(tickers))
    elif args.only_corrupt:
        tickers = find_corrupt_tickers(eng)
        logger.info('Found %d corrupt tickers: %s', len(tickers),
                    ', '.join(tickers[:20]) + (' …' if len(tickers) > 20 else ''))
    else:
        tickers = load_all_tickers(eng)
        logger.info('Will refresh all %d tickers in the universe', len(tickers))

    if not tickers:
        logger.info('Nothing to fix — database looks clean')
        return

    all_rows = []
    ok = 0
    failed = 0
    start_wall = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fut_to_tkr = {pool.submit(process_ticker, t): t for t in tickers}
        for i, fut in enumerate(as_completed(fut_to_tkr), 1):
            tkr = fut_to_tkr[fut]
            try:
                rows = fut.result()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning('%s crashed: %s', tkr, exc)
                rows = []
            if rows:
                ok += 1
                all_rows.extend(rows)
            else:
                failed += 1
            if i % 25 == 0 or i == len(tickers):
                logger.info('[%d/%d] last=%s ok=%d fail=%d rows=%d',
                            i, len(tickers), tkr, ok, failed, len(all_rows))

    logger.info('Fetched %d rows across %d tickers in %.1fs (%d failed)',
                len(all_rows), ok, time.time() - start_wall, failed)

    if all_rows:
        n = upsert_prices(eng, all_rows)
        logger.info('Upserted %d REAL price rows', n)


if __name__ == '__main__':
    main()
