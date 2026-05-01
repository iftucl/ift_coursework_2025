"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : REAL historical value_metrics backfill from yfinance annual reports
Project : CW2 - Value-Sentiment Investment Strategy

Goal
----
CW1's single-snapshot ``value_metrics`` table forces CW2's point-in-time
loader to fall back to today's ratios for every historical rebalance.
This script replaces that limitation with a **real** historical series
by fetching annual income statements + balance sheets from yfinance
(which carries 4–5 fiscal years of data) and combining them with the
daily price history already stored in CW1's Postgres.

At each month-end in the backtest window we:

    1. Identify the most recent fiscal-year-end ``report_date`` that
       satisfies ``report_date + reporting_lag_days <= rebalance_date``
       (90-day lag — matches the config).
    2. Pull the Net Income, EBITDA, Total Debt, Common Stock Equity
       and Ordinary Shares Number lines from that annual report.
    3. Read the adjusted close price at the month-end from the
       ``daily_prices`` table already in Postgres.
    4. Compute:

           EPS      = NetIncome / SharesOutstanding
           BVPS     = CommonStockEquity / SharesOutstanding
           MktCap   = Price × SharesOutstanding
           EV       ≈ MktCap + TotalDebt - CashAndEquivalents
           P/E      = Price / EPS
           P/B      = Price / BVPS
           EV/EBITDA = EV / EBITDA
           D/E      = TotalDebt / CommonStockEquity
           DivYield = sum(trailing-4-quarter dividends) / Price

       using only data available on or before the report date.
    5. Upsert one row per (company, month-end) into
       ``systematic_equity.value_metrics``.

This is **real yfinance data** — no price-scaling approximations, no
synthetic extrapolation. Every ratio traces back to a GAAP line item
on an annual report that was publicly available at the rebalance date.
The only design choice is the 90-day reporting lag (standard PIT
convention — Fama-French use 6 months; we use 3 months per the
master guide §A6) and the choice of the **latest available** annual
report, which is the canonical PIT rule.

Coverage realism
----------------
yfinance annual coverage varies per ticker — large caps have 4–5 years,
some foreign tickers have 2–3. When an annual report is unavailable the
row is skipped (NaN propagates harmlessly through the value pipeline's
`np.where` guards). Stocks with zero annual reports fall back to the
2026-04-15 snapshot via the existing fallback logic — this is the
minority-case safety net, not the main path.

Runtime
-------
Roughly 10–20 minutes for ~600 tickers with yfinance's live rate
limiting. A ``ThreadPoolExecutor`` with 8 workers and per-ticker retry
keeps throughput reasonable while respecting yfinance's sliding-window
limits. Set ``--tickers AAPL MSFT`` for a smoke test.

Usage
-----
::

    poetry run python -m modules.data.backfill_real_yfinance_history \
        --start 2020-01-01 --end 2026-04-15

Fully idempotent — ``ON CONFLICT DO UPDATE`` refreshes every row.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import yaml
import yfinance as yf
from sqlalchemy import create_engine, engine, text

LOG_FMT = '%(asctime)s | %(name)-42s | %(levelname)-7s | %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('backfill_real_yfinance_history')

# Silence yfinance's own noisy logger during bulk fetches
logging.getLogger('yfinance').setLevel(logging.ERROR)

REPORTING_LAG_DAYS = 90   # Matches config/backtest_config.yaml

# Row-level lines we pull from yfinance's annual frames. The lookups
# are resilient to the ticker-specific variations yfinance emits — we
# try the canonical line name first, then fall back to common aliases.
INCOME_LINES = {
    'net_income': ['Net Income', 'Net Income Common Stockholders',
                   'Net Income Continuous Operations'],
    'ebitda': ['EBITDA', 'Normalized EBITDA'],
}
BALANCE_LINES = {
    'total_debt': ['Total Debt', 'Net Debt'],
    'equity': ['Common Stock Equity', 'Stockholders Equity',
               'Total Equity Gross Minority Interest'],
    'shares': ['Ordinary Shares Number', 'Share Issued'],
    'cash': ['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments',
             'Cash Financial'],
}


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


def _load_cw1_conf(cw2_config: dict) -> dict:
    with open(cw2_config['cw1']['config_path'], 'r') as fh:
        cw1 = yaml.safe_load(fh)
    return cw1[cw2_config['cw1']['env_type']]


def build_engine(cw2_config: dict):
    env_profile = _load_cw1_conf(cw2_config)
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
# DB helpers
# ---------------------------------------------------------------------------

def load_universe(eng) -> list:
    sql = text(
        "SELECT DISTINCT TRIM(company_id) AS ticker "
        "FROM systematic_equity.value_metrics ORDER BY 1"
    )
    with eng.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [r[0] for r in rows]


def load_price_panel(eng) -> pd.DataFrame:
    sql = text(
        "SELECT TRIM(symbol) AS symbol, cob_date, adj_close_price "
        "FROM systematic_equity.daily_prices "
        "WHERE adj_close_price IS NOT NULL"
    )
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, parse_dates=['cob_date'])
    df['symbol'] = df['symbol'].str.upper()
    panel = df.pivot(index='cob_date', columns='symbol', values='adj_close_price').sort_index()
    panel.index.name = 'date'
    logger.info('Price panel: %d dates × %d symbols', len(panel), len(panel.columns))
    return panel


# ---------------------------------------------------------------------------
# yfinance annual fetch
# ---------------------------------------------------------------------------

@dataclass
class AnnualReport:
    """One fiscal year-end fundamental snapshot for a single ticker."""
    report_date: pd.Timestamp
    net_income: float
    ebitda: float
    total_debt: float
    equity: float
    shares: float
    cash: float
    dividends_ttm: float  # dividends paid in the 12 months ending at report_date


def _first_matching(frame: pd.DataFrame, candidates: list) -> Optional[pd.Series]:
    """Return the first row in ``frame`` whose index matches any candidate."""
    if frame is None or frame.empty:
        return None
    for name in candidates:
        if name in frame.index:
            return frame.loc[name]
    return None


def _safe_float(x) -> float:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def fetch_annual_reports(ticker: str, max_retries: int = 3) -> list:
    """Fetch 4–5 years of annual fundamentals from yfinance.

    :returns: list of :class:`AnnualReport`, newest first. Empty on failure.
    """
    for attempt in range(max_retries):
        try:
            t = yf.Ticker(ticker)
            income = t.income_stmt
            balance = t.balance_sheet
            try:
                dividends = t.dividends  # Series indexed by date
                # yfinance returns a tz-aware DatetimeIndex (America/New_York).
                # Drop the timezone so comparisons against naive report_date
                # Timestamps (which we build from the annual-frame column
                # labels) do not raise TypeError.
                if len(dividends) > 0 and dividends.index.tz is not None:
                    dividends = dividends.copy()
                    dividends.index = dividends.index.tz_convert(None)
            except Exception:
                dividends = pd.Series(dtype=float)

            if income is None or income.empty or balance is None or balance.empty:
                return []

            ni_row = _first_matching(income, INCOME_LINES['net_income'])
            ebitda_row = _first_matching(income, INCOME_LINES['ebitda'])
            debt_row = _first_matching(balance, BALANCE_LINES['total_debt'])
            equity_row = _first_matching(balance, BALANCE_LINES['equity'])
            shares_row = _first_matching(balance, BALANCE_LINES['shares'])
            cash_row = _first_matching(balance, BALANCE_LINES['cash'])

            if ni_row is None or debt_row is None or equity_row is None:
                return []

            reports = []
            for col in income.columns:
                try:
                    report_date = pd.Timestamp(col)
                except Exception:
                    continue

                # TTM dividends from actual cash distributions paid in the
                # 12 months ending at the report date. If dividends is empty
                # (non-dividend payers), defaults to 0 → yield = 0.
                div_ttm = 0.0
                if len(dividends) > 0:
                    div_start = report_date - pd.Timedelta(days=365)
                    div_ttm = float(
                        dividends[(dividends.index > div_start)
                                  & (dividends.index <= report_date)].sum()
                    )

                reports.append(AnnualReport(
                    report_date=report_date,
                    net_income=_safe_float(ni_row.get(col)),
                    ebitda=_safe_float(ebitda_row.get(col)) if ebitda_row is not None else np.nan,
                    total_debt=_safe_float(debt_row.get(col)),
                    equity=_safe_float(equity_row.get(col)),
                    shares=_safe_float(shares_row.get(col)) if shares_row is not None else np.nan,
                    cash=_safe_float(cash_row.get(col)) if cash_row is not None else 0.0,
                    dividends_ttm=div_ttm,
                ))

            reports.sort(key=lambda r: r.report_date, reverse=True)
            return reports

        except Exception as exc:  # pylint: disable=broad-except
            if attempt < max_retries - 1:
                time.sleep(1.5 ** attempt)
                continue
            logger.warning('yfinance failed for %s: %s', ticker, exc)
            return []
    return []


# ---------------------------------------------------------------------------
# Ratio computation
# ---------------------------------------------------------------------------

def _pick_report(reports: list, as_of: pd.Timestamp) -> Optional[AnnualReport]:
    """Return the most recent report whose (date + lag) is on or before as_of."""
    cutoff = as_of - pd.Timedelta(days=REPORTING_LAG_DAYS)
    candidates = [r for r in reports if r.report_date <= cutoff]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.report_date)


def compute_row(
    ticker: str,
    as_of: pd.Timestamp,
    price: float,
    report: AnnualReport,
) -> Optional[dict]:
    """Combine a report + a price into a single value_metrics row.

    Returns ``None`` when the input is too degenerate to produce
    usable ratios (e.g. zero shares outstanding, zero equity).
    """
    if price is None or price <= 0 or not np.isfinite(price):
        return None
    if report is None:
        return None

    shares = report.shares
    equity = report.equity
    ni = report.net_income
    ebitda = report.ebitda
    debt = report.total_debt
    cash = report.cash if np.isfinite(report.cash) else 0.0
    div_ttm = report.dividends_ttm

    # Shares are critical for P/E and P/B. Without them no ratio is valid.
    if not np.isfinite(shares) or shares <= 0:
        return None

    mkt_cap = price * shares
    eps = ni / shares if np.isfinite(ni) and ni != 0 else np.nan
    bvps = equity / shares if np.isfinite(equity) and equity != 0 else np.nan

    pe = price / eps if np.isfinite(eps) and eps != 0 else None
    pb = price / bvps if np.isfinite(bvps) and bvps > 0 else None
    de = debt / equity if np.isfinite(debt) and np.isfinite(equity) and equity > 0 else None

    if np.isfinite(ebitda) and ebitda > 0:
        ev = mkt_cap + (debt if np.isfinite(debt) else 0.0) - cash
        ev_eb = ev / ebitda if ev > 0 else None
    else:
        ev_eb = None

    div_yield = div_ttm / price if div_ttm > 0 else 0.0

    return {
        'company_id': ticker,
        'date': as_of.strftime('%Y-%m-%d'),
        'pe_ratio': pe,
        'pb_ratio': pb,
        'ev_ebitda': ev_eb,
        'dividend_yield': div_yield,
        'debt_equity': de,
        'value_score': None,
    }


# ---------------------------------------------------------------------------
# Month-end anchor generation
# ---------------------------------------------------------------------------

def monthly_anchors(start: pd.Timestamp, end: pd.Timestamp,
                    price_dates: pd.DatetimeIndex) -> list:
    out = []
    cur = pd.Timestamp(start).normalize().replace(day=1)
    while cur <= end:
        month_end = cur + pd.offsets.MonthEnd(0)
        mask = (price_dates >= cur) & (price_dates <= month_end)
        cands = price_dates[mask]
        if len(cands) > 0:
            out.append(cands[-1])
        cur = cur + pd.offsets.MonthBegin(1)
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def upsert_value_metrics(eng, records: list, chunk: int = 4000) -> int:
    if not records:
        return 0
    sql = text(
        """
        INSERT INTO systematic_equity.value_metrics
            (company_id, date, pe_ratio, pb_ratio, ev_ebitda,
             dividend_yield, debt_equity, value_score)
        VALUES
            (:company_id, :date, :pe_ratio, :pb_ratio, :ev_ebitda,
             :dividend_yield, :debt_equity, :value_score)
        ON CONFLICT (company_id, date) DO UPDATE SET
            pe_ratio = EXCLUDED.pe_ratio,
            pb_ratio = EXCLUDED.pb_ratio,
            ev_ebitda = EXCLUDED.ev_ebitda,
            dividend_yield = EXCLUDED.dividend_yield,
            debt_equity = EXCLUDED.debt_equity,
            value_score = EXCLUDED.value_score,
            ingestion_timestamp = NOW()
        """
    )
    total = 0
    with eng.begin() as conn:
        for i in range(0, len(records), chunk):
            conn.execute(sql, records[i:i + chunk])
            total += len(records[i:i + chunk])
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_ticker(
    ticker: str,
    anchors: list,
    price_panel: pd.DataFrame,
) -> list:
    """Fetch + compute all monthly rows for one ticker."""
    if ticker not in price_panel.columns:
        return []
    reports = fetch_annual_reports(ticker)
    if not reports:
        return []

    ticker_prices = price_panel[ticker].dropna()
    if len(ticker_prices) == 0:
        return []

    rows = []
    for anchor in anchors:
        report = _pick_report(reports, anchor)
        if report is None:
            continue
        # Most recent trading-day price ≤ anchor
        px_avail = ticker_prices[ticker_prices.index <= anchor]
        if len(px_avail) == 0:
            continue
        price = float(px_avail.iloc[-1])
        row = compute_row(ticker, anchor, price, report)
        if row is not None:
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description='Backfill REAL historical value_metrics from yfinance')
    parser.add_argument('--config', default='config/backtest_config.yaml')
    parser.add_argument('--start', default='2020-01-01')
    parser.add_argument('--end', default=None)
    parser.add_argument('--tickers', nargs='*', default=None,
                        help='Optional whitelist; omit to process full universe')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()

    with open(args.config, 'r') as fh:
        cw2_config = yaml.safe_load(fh)

    eng = build_engine(cw2_config)
    tickers = args.tickers or load_universe(eng)
    price_panel = load_price_panel(eng)

    end = pd.Timestamp(args.end) if args.end else price_panel.index.max()
    anchors = monthly_anchors(pd.Timestamp(args.start), end, price_panel.index)
    logger.info('Anchors: %d months (%s → %s)', len(anchors), anchors[0], anchors[-1])
    logger.info('Processing %d tickers with %d workers', len(tickers), args.workers)

    all_records = []
    ok = 0
    failed = 0
    start_wall = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fut_to_tkr = {
            pool.submit(process_ticker, tkr, anchors, price_panel): tkr
            for tkr in tickers
        }
        for i, fut in enumerate(as_completed(fut_to_tkr), 1):
            tkr = fut_to_tkr[fut]
            try:
                rows = fut.result()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning('%s crashed: %s', tkr, exc)
                rows = []
            if rows:
                ok += 1
                all_records.extend(rows)
            else:
                failed += 1
            if i % 25 == 0 or i == len(tickers):
                logger.info('[%d/%d] %s: %d rows (running totals ok=%d fail=%d rows=%d)',
                            i, len(tickers), tkr, len(rows), ok, failed, len(all_records))

    elapsed = time.time() - start_wall
    logger.info('Fetched %d rows across %d tickers in %.1fs (%d failed)',
                len(all_records), ok, elapsed, failed)

    if all_records:
        n = upsert_value_metrics(eng, all_records)
        logger.info('Upserted %d REAL historical value_metrics rows', n)
    else:
        logger.warning('Zero records produced — nothing upserted')


if __name__ == '__main__':
    main()
