"""SEC EDGAR XBRL API extractor for fundamental financial data.

Fetches company facts from the SEC EDGAR XBRL REST API (free, no key required).
Provides Point-in-Time (PIT) correctness using the ``filed`` date from each
10-K/10-Q filing — the date on which the data became publicly available.

Rate limit: EDGAR requests ≤ 10 req/s.  We use a TokenBucket set to 8 req/s
(conservative) backed by Redis.

Metrics extracted per filing (mapped to ``financial_observations``):

* ``total_revenue``
* ``gross_profit``
* ``operating_income``
* ``ebitda`` (approximated as operating_income + D&A when direct tag absent)
* ``net_income``
* ``total_assets``
* ``total_liabilities``
* ``stockholders_equity``
* ``total_debt`` (long-term + short-term)
* ``shares_outstanding``
* ``eps_basic``

All values are in USD when the filing is reported in USD; for the current
teacher-provided universe this is typically the dominant case.

Example usage::

    from modules.extract.edgar_xbrl import fetch_company_facts, extract_financial_records

    facts = fetch_company_facts("AAPL")
    records = extract_financial_records("AAPL", facts, backfill_years=5)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from modules.utils.resilience import get_circuit_breaker, get_token_bucket, retry_with_backoff

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EDGAR_BASE_URL = "https://data.sec.gov"
EDGAR_COMPANY_FACTS_URL = EDGAR_BASE_URL + "/api/xbrl/companyfacts/CIK{cik}.json"
EDGAR_SUBMISSIONS_URL = EDGAR_BASE_URL + "/submissions/CIK{cik}.json"

# EDGAR requires a descriptive User-Agent with contact info.
_USER_AGENT = "team-pearson-ift-coursework contact@example.com"

# XBRL taxonomy tags mapped to our internal metric names.
# Multiple tags listed in priority order (first match wins).
_METRIC_TAG_MAP: Dict[str, List[str]] = {
    "total_revenue": [
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:SalesRevenueNet",
    ],
    "gross_profit": ["us-gaap:GrossProfit"],
    "operating_income": [
        "us-gaap:OperatingIncomeLoss",
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "net_income": [
        "us-gaap:NetIncomeLoss",
        "us-gaap:ProfitLoss",
    ],
    "total_assets": ["us-gaap:Assets"],
    "total_liabilities": ["us-gaap:Liabilities"],
    "stockholders_equity": [
        "us-gaap:StockholdersEquity",
        "us-gaap:StockholdersEquityAttributableToParent",
    ],
    "long_term_debt": [
        "us-gaap:LongTermDebt",
        "us-gaap:LongTermDebtNoncurrent",
    ],
    "short_term_debt": [
        "us-gaap:ShortTermBorrowings",
        "us-gaap:DebtCurrent",
    ],
    "shares_outstanding": [
        "us-gaap:CommonStockSharesOutstanding",
        "us-gaap:SharesOutstanding",
    ],
    "eps_basic": [
        "us-gaap:EarningsPerShareBasic",
    ],
    "depreciation_amortization": [
        "us-gaap:DepreciationDepletionAndAmortization",
        "us-gaap:DepreciationAndAmortization",
    ],
    "cash_and_equivalents": [
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:CashCashEquivalentsAndShortTermInvestments",
    ],
}

# Accepted SEC form types for financial data.
_ACCEPTED_FORMS = {"10-K", "10-Q"}

# PIT fallback: if filed date is missing, add this offset to the period end date.
_PIT_FALLBACK_DAYS = 45

_RATE = 8  # requests per second (conservative vs EDGAR's 10/s limit)
_PERIOD = 1  # 1-second window

# ---------------------------------------------------------------------------
# Resilience singletons
# ---------------------------------------------------------------------------

_cb = get_circuit_breaker("edgar", failure_threshold=5, recovery_timeout=120)
_tb = get_token_bucket("edgar", rate=_RATE, period=_PERIOD)


# ---------------------------------------------------------------------------
# CIK lookup
# ---------------------------------------------------------------------------


def _ticker_to_cik(ticker: str) -> Optional[str]:
    """Resolve a ticker symbol to a zero-padded 10-digit SEC CIK.

    Uses the EDGAR company tickers JSON endpoint (no rate limit on this call).

    :param ticker: Stock ticker symbol (e.g. ``'AAPL'``).
    :type ticker: str
    :returns: Zero-padded CIK string, or ``None`` if not found.
    :rtype: str | None
    """
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("edgar: CIK lookup failed: %s", exc)
        return None

    ticker_upper = ticker.upper()
    for entry in data.values():
        if str(entry.get("ticker", "")).upper() == ticker_upper:
            return str(entry["cik_str"]).zfill(10)
    return None


# ---------------------------------------------------------------------------
# Company facts fetch
# ---------------------------------------------------------------------------


@retry_with_backoff(max_retries=3, base_delay=2.0, max_delay=30.0, service="edgar")
def _fetch_facts_raw(cik: str) -> Dict[str, Any]:
    """Fetch raw company facts JSON from EDGAR for a given CIK.

    :param cik: Zero-padded 10-digit CIK.
    :type cik: str
    :returns: Parsed JSON dict from EDGAR.
    :rtype: dict[str, Any]
    :raises requests.HTTPError: On non-200 response.
    """
    _tb.acquire()
    url = EDGAR_COMPANY_FACTS_URL.format(cik=cik)
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json()


@_cb.protect
def fetch_company_facts(ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch and return SEC EDGAR company facts for *ticker*.

    :param ticker: Stock ticker symbol.
    :type ticker: str
    :returns: Parsed EDGAR company facts JSON, or ``None`` on failure.
    :rtype: dict[str, Any] | None
    """
    cik = _ticker_to_cik(ticker)
    if not cik:
        logger.warning("edgar: no CIK found for ticker=%s", ticker)
        return None
    try:
        facts = _fetch_facts_raw(cik)
        logger.debug("edgar: fetched facts for ticker=%s cik=%s", ticker, cik)
        return facts
    except Exception as exc:
        logger.error("edgar: failed to fetch facts ticker=%s: %s", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# Record extraction
# ---------------------------------------------------------------------------


def _parse_edgar_date(value: Any) -> Optional[date]:
    """Parse YYYY-MM-DD string to ``date``; return ``None`` on failure.

    :param value: Raw date string from EDGAR.
    :returns: Parsed date or ``None``.
    :rtype: date | None
    """
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _get_tag_units(facts: Dict[str, Any], tag_full: str) -> Optional[Dict[str, Any]]:
    """Resolve XBRL tag from company facts to its units dict.

    :param facts: Raw EDGAR company facts JSON.
    :param tag_full: Full tag string like ``'us-gaap:Assets'``.
    :returns: Units sub-dict or ``None`` if tag absent.
    :rtype: dict | None
    """
    taxonomy, tag = tag_full.split(":", 1)
    try:
        return facts["facts"][taxonomy][tag]["units"]
    except (KeyError, TypeError):
        return None


def _extract_metric_filings(
    facts: Dict[str, Any],
    metric_name: str,
    tags: List[str],
    cutoff_date: date,
    start_date: date,
) -> List[Dict[str, Any]]:
    """Extract all filings for one metric from EDGAR facts within the date range.

    Applies PIT: ``publish_date = filed`` (or ``end + 45d`` fallback).
    Only includes 10-K and 10-Q forms.

    :param facts: Raw EDGAR company facts JSON.
    :param metric_name: Our internal metric name (e.g. ``'total_revenue'``).
    :param tags: XBRL tags to try in priority order.
    :param cutoff_date: Latest observation date to include.
    :param start_date: Earliest observation date to include.
    :returns: List of raw filing dicts with metric/PIT fields populated.
    :rtype: list[dict]
    """
    results: List[Dict[str, Any]] = []

    for tag_full in tags:
        units = _get_tag_units(facts, tag_full)
        if not units:
            continue

        # EDGAR returns multiple unit types; USD is standard for financials.
        rows = units.get("USD") or units.get("shares") or []
        if not rows:
            continue

        seen_keys: set = set()
        for row in rows:
            form = str(row.get("form", ""))
            if form not in _ACCEPTED_FORMS:
                continue

            end_date = _parse_edgar_date(row.get("end"))
            if end_date is None or end_date < start_date or end_date > cutoff_date:
                continue

            filed_date = _parse_edgar_date(row.get("filed"))
            publish_date = (
                filed_date if filed_date else end_date + timedelta(days=_PIT_FALLBACK_DAYS)
            )

            val = row.get("val")
            if val is None:
                continue

            # Deduplicate by (end_date, form) — keep first tag match (priority order).
            key = (end_date, form)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            period_type = "annual" if form == "10-K" else "quarterly"

            results.append(
                {
                    "metric_name": metric_name,
                    "metric_value": float(val),
                    "report_date": end_date,
                    "publish_date": publish_date,
                    "publish_date_source": "edgar_xbrl",
                    "period_type": period_type,
                    "form": form,
                    "filed_date": filed_date,
                    "source_tag": tag_full,
                }
            )

        if results:
            break  # First tag with data wins; no need to try lower-priority tags

    return results


def extract_financial_records(
    symbol: str,
    facts: Dict[str, Any],
    *,
    backfill_years: int = 5,
    as_of: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Convert raw EDGAR company facts into ``financial_observations`` records.

    :param symbol: Stock ticker symbol.
    :type symbol: str
    :param facts: Raw EDGAR company facts JSON from :func:`fetch_company_facts`.
    :type facts: dict
    :param backfill_years: Number of years of history to extract.
    :type backfill_years: int
    :param as_of: Reference date (defaults to today). Filings after this date excluded.
    :type as_of: date | None
    :returns: List of dicts ready for :func:`~modules.output.load.load_financial_observations`.
    :rtype: list[dict]
    """
    if not facts:
        return []

    cutoff = as_of or date.today()
    extraction_as_of = cutoff
    start = cutoff - timedelta(days=backfill_years * 365 + 90)  # slight buffer

    records: List[Dict[str, Any]] = []

    for metric_name, tags in _METRIC_TAG_MAP.items():
        filings = _extract_metric_filings(facts, metric_name, tags, cutoff, start)
        for f in filings:
            records.append(
                {
                    "symbol": symbol,
                    "report_date": f["report_date"],
                    "metric_name": f["metric_name"],
                    "metric_value": f["metric_value"],
                    "currency": "USD",
                    "period_type": f["period_type"],
                    "metric_definition": "provider_reported",
                    "source": "edgar_xbrl",
                    "value_source": "edgar_xbrl",
                    "as_of": extraction_as_of,
                    "publish_date": f["publish_date"],
                    "publish_date_source": f.get("publish_date_source") or "edgar_xbrl",
                }
            )

    # Derived: total_debt = long_term_debt + short_term_debt
    records.extend(_derive_total_debt(symbol, records))

    # Derived: ebitda = operating_income + depreciation_amortization
    records.extend(_derive_ebitda(symbol, records))

    # Derived: roe = net_income / stockholders_equity
    records.extend(_derive_roe(symbol, records))

    logger.info(
        "edgar: extracted symbol=%s records=%s backfill_years=%s",
        symbol,
        len(records),
        backfill_years,
    )
    return records


def _derive_total_debt(symbol: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derive total_debt = long_term_debt + short_term_debt per report_date.

    :param symbol: Stock ticker.
    :param records: Existing extracted records.
    :returns: New derived total_debt records.
    :rtype: list[dict]
    """
    from collections import defaultdict

    by_date: Dict[date, Dict[str, Any]] = defaultdict(dict)
    for r in records:
        if r["metric_name"] in ("long_term_debt", "short_term_debt"):
            by_date[r["report_date"]][r["metric_name"]] = r

    derived = []
    for report_date, metrics in by_date.items():
        ltd = metrics.get("long_term_debt")
        std = metrics.get("short_term_debt")
        if ltd is None and std is None:
            continue
        val = (ltd["metric_value"] if ltd else 0.0) + (std["metric_value"] if std else 0.0)
        ref = ltd or std
        derived.append(
            {
                "symbol": symbol,
                "report_date": report_date,
                "metric_name": "total_debt",
                "metric_value": val,
                "currency": "USD",
                "period_type": ref["period_type"],
                "metric_definition": "normalized",
                "source": "edgar_xbrl_derived",
                "value_source": "edgar_xbrl_derived",
                "as_of": ref["as_of"],
                "publish_date": ref["publish_date"],
                "publish_date_source": ref.get("publish_date_source") or "edgar_xbrl",
            }
        )
    return derived


def _derive_roe(symbol: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derive roe = net_income / stockholders_equity per report_date.

    ROE (Return on Equity) measures capital efficiency.
    Negative equity produces a meaningful negative ROE only when net_income > 0;
    rows where both are negative are discarded to avoid misleading positive values.

    :param symbol: Stock ticker.
    :param records: Existing extracted records.
    :returns: New derived roe records.
    :rtype: list[dict]
    """
    from collections import defaultdict

    by_date: Dict[date, Dict[str, Any]] = defaultdict(dict)
    for r in records:
        if r["metric_name"] in ("net_income", "stockholders_equity"):
            by_date[r["report_date"]][r["metric_name"]] = r

    derived = []
    for report_date, metrics in by_date.items():
        ni = metrics.get("net_income")
        eq = metrics.get("stockholders_equity")
        if ni is None or eq is None:
            continue
        ni_val = ni["metric_value"]
        eq_val = eq["metric_value"]
        if eq_val == 0:
            continue
        # Discard distorted ROE: negative equity + negative earnings
        if eq_val < 0 and ni_val < 0:
            continue
        roe = ni_val / eq_val
        derived.append(
            {
                "symbol": symbol,
                "report_date": report_date,
                "metric_name": "roe",
                "metric_value": roe,
                "currency": "USD",
                "period_type": ni["period_type"],
                "metric_definition": "normalized",
                "source": "edgar_xbrl_derived",
                "value_source": "edgar_xbrl_derived",
                "as_of": ni["as_of"],
                "publish_date": ni["publish_date"],
                "publish_date_source": ni.get("publish_date_source") or "edgar_xbrl",
            }
        )
    return derived


def _derive_ebitda(symbol: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derive ebitda = operating_income + depreciation_amortization per report_date.

    :param symbol: Stock ticker.
    :param records: Existing extracted records.
    :returns: New derived ebitda records.
    :rtype: list[dict]
    """
    from collections import defaultdict

    by_date: Dict[date, Dict[str, Any]] = defaultdict(dict)
    for r in records:
        if r["metric_name"] in ("operating_income", "depreciation_amortization"):
            by_date[r["report_date"]][r["metric_name"]] = r

    derived = []
    for report_date, metrics in by_date.items():
        oi = metrics.get("operating_income")
        da = metrics.get("depreciation_amortization")
        if oi is None:
            continue
        val = oi["metric_value"] + (da["metric_value"] if da else 0.0)
        derived.append(
            {
                "symbol": symbol,
                "report_date": report_date,
                "metric_name": "ebitda",
                "metric_value": val,
                "currency": "USD",
                "period_type": oi["period_type"],
                "metric_definition": "normalized",
                "source": "edgar_xbrl_derived",
                "value_source": "edgar_xbrl_derived",
                "as_of": oi["as_of"],
                "publish_date": oi["publish_date"],
                "publish_date_source": oi.get("publish_date_source") or "edgar_xbrl",
            }
        )
    return derived


# ---------------------------------------------------------------------------
# Bulk runner
# ---------------------------------------------------------------------------


def run_edgar_extraction(
    symbols: List[str],
    *,
    backfill_years: int = 5,
    as_of: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Fetch and extract EDGAR financial records for a list of symbols.

    :param symbols: List of ticker symbols to process.
    :type symbols: list[str]
    :param backfill_years: Years of history to extract per symbol.
    :type backfill_years: int
    :param as_of: Reference date for cutoff. Defaults to today.
    :type as_of: date | None
    :returns: All extracted financial observation records.
    :rtype: list[dict]
    """
    all_records: List[Dict[str, Any]] = []
    total = len(symbols)

    for idx, symbol in enumerate(symbols, 1):
        logger.info("edgar: processing %s/%s symbol=%s", idx, total, symbol)
        facts = fetch_company_facts(symbol)
        if facts is None:
            logger.warning("edgar: skipping symbol=%s (no facts returned)", symbol)
            continue
        records = extract_financial_records(
            symbol, facts, backfill_years=backfill_years, as_of=as_of
        )
        all_records.extend(records)

    logger.info("edgar: total records extracted=%s symbols=%s", len(all_records), total)
    return all_records
