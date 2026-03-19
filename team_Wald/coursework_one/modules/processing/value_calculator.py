"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Value Calculator — computes financial ratios from raw data
Project : CW1 - Value + News Sentiment Strategy

Calculates the five key financial ratios from raw financial statement data
(income statement, balance sheet, cash flow) when pre-computed values from
Yahoo Finance's ``Ticker.info`` are unavailable.  Also provides percentile-
ranking and composite Value Score computation.

Ratios calculated:
  1. P/E  ratio      — Price / Earnings Per Share
  2. P/B  ratio      — Market Cap / Book Value (Stockholders' Equity)
  3. EV/EBITDA       — Enterprise Value / EBITDA
  4. Dividend Yield  — Annual Dividends / Market Cap
  5. Debt/Equity     — Total Debt / Stockholders' Equity

This module satisfies Issue 5 / Task 5.1 from the project specification:
  - Read raw financial data (from MinIO or directly from extraction)
  - Calculate P/E, P/B, EV/EBITDA, Dividend Yield, Debt/Equity
  - Rank all 678 companies into percentiles (0-100)
  - Compute Value Score = average of percentiles (excluding D/E filter)
  - Handle missing data: average the remaining ratios

Academic foundation:
  - Fama & French (1993), "Common risk factors in the returns on stocks
    and bonds", JFE.
  - Greenblatt (2006), "The Little Book That Beats the Market".
"""

from datetime import date
from typing import Optional

import numpy as np

from modules.utils.logger import pipeline_logger

# ---------------------------------------------------------------------------
# Field aliases — yfinance uses different names across versions/endpoints
# ---------------------------------------------------------------------------

_NET_INCOME_ALIASES = [
    "Net Income",
    "NetIncome",
    "Net Income Common Stockholders",
    "NetIncomeCommonStockholders",
    "Net Income From Continuing Operations",
]

_EBITDA_ALIASES = [
    "EBITDA",
    "Ebitda",
    "Normalized EBITDA",
    "NormalizedEBITDA",
]

_OPERATING_INCOME_ALIASES = [
    "Operating Income",
    "OperatingIncome",
    "Operating Revenue",
    "EBIT",
    "Ebit",
]

_DEPRECIATION_ALIASES = [
    "Depreciation And Amortization",
    "DepreciationAndAmortization",
    "Depreciation",
    "Reconciled Depreciation",
    "ReconciledDepreciation",
]

_TOTAL_REVENUE_ALIASES = [
    "Total Revenue",
    "TotalRevenue",
    "Operating Revenue",
    "OperatingRevenue",
]

_STOCKHOLDERS_EQUITY_ALIASES = [
    "Stockholders Equity",
    "StockholdersEquity",
    "Common Stock Equity",
    "CommonStockEquity",
    "Total Equity Gross Minority Interest",
    "TotalEquityGrossMinorityInterest",
    "Stockholders' Equity",
]

_TOTAL_DEBT_ALIASES = [
    "Total Debt",
    "TotalDebt",
    "Net Debt",
    "NetDebt",
    "Long Term Debt",
    "LongTermDebt",
    "Long Term Debt And Capital Lease Obligation",
    "LongTermDebtAndCapitalLeaseObligation",
]

_TOTAL_ASSETS_ALIASES = [
    "Total Assets",
    "TotalAssets",
]

_CASH_ALIASES = [
    "Cash And Cash Equivalents",
    "CashAndCashEquivalents",
    "Cash Cash Equivalents And Short Term Investments",
    "CashCashEquivalentsAndShortTermInvestments",
    "Cash Financial",
    "CashFinancial",
]

_DIVIDENDS_PAID_ALIASES = [
    "Cash Dividends Paid",
    "CashDividendsPaid",
    "Common Stock Dividend Paid",
    "CommonStockDividendPaid",
    "Payment Of Dividends",
]

_SHARES_OUTSTANDING_ALIASES = [
    "Share Issued",
    "ShareIssued",
    "Ordinary Shares Number",
    "OrdinarySharesNumber",
    "Basic Average Shares",
    "BasicAverageShares",
    "Diluted Average Shares",
    "DilutedAverageShares",
]

_BASIC_EPS_ALIASES = [
    "Basic EPS",
    "BasicEPS",
    "Diluted EPS",
    "DilutedEPS",
]

_INTEREST_EXPENSE_ALIASES = [
    "Interest Expense",
    "InterestExpense",
    "Interest Expense Non Operating",
    "InterestExpenseNonOperating",
    "Net Interest Income",
    "NetInterestIncome",
]

_TAX_EXPENSE_ALIASES = [
    "Tax Provision",
    "TaxProvision",
    "Income Tax Expense",
    "IncomeTaxExpense",
]

_TOTAL_LIABILITIES_ALIASES = [
    "Total Liabilities Net Minority Interest",
    "TotalLiabilitiesNetMinorityInterest",
    "Total Liabilities",
    "TotalLiabilities",
    "Total Non Current Liabilities Net Minority Interest",
    "TotalNonCurrentLiabilitiesNetMinorityInterest",
]


# ---------------------------------------------------------------------------
# Helper: extract a value from serialised financial statement dict
# ---------------------------------------------------------------------------


def _extract_field(statement: dict, aliases: list[str], allow_zero: bool = True) -> Optional[float]:
    """Extract a numeric value from a financial statement dict, trying
    multiple field name aliases.

    The statement dict has the structure::

        { "Field Name": {"2024-09-30": 12345, ...}, ... }

    Returns the most recent non-null value for the first matching alias.

    :param statement: Serialised financial statement dict
    :type statement: dict
    :param aliases: List of field name aliases to try
    :type aliases: list[str]
    :param allow_zero: If True, accept 0.0 as a valid value (default True)
    :type allow_zero: bool
    :return: Numeric value or None
    :rtype: float or None
    """
    if not statement or not isinstance(statement, dict):
        return None

    for alias in aliases:
        if alias in statement:
            row = statement[alias]
            if isinstance(row, dict):
                # Get most recent non-null value (dates sorted descending)
                for dt in sorted(row.keys(), reverse=True):
                    val = _safe_float(row[dt])
                    if val is not None and (allow_zero or val != 0.0):
                        return val
            else:
                val = _safe_float(row)
                if val is not None:
                    return val
    return None


def _safe_float(val) -> Optional[float]:
    """Convert a value to float, returning None for invalid inputs.

    :param val: Value to convert
    :return: Float or None if invalid/non-finite
    :rtype: float or None
    """
    if val is None:
        return None
    try:
        f = float(val)
        if np.isfinite(f):
            return f
        return None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Individual ratio calculators (Task 5.1 specification)
# ---------------------------------------------------------------------------


def calculate_pe_ratio(financials: dict, company_info: dict = None) -> Optional[float]:
    """Calculate Price-to-Earnings ratio from raw financial data.

    Multi-source cascade:
      1. Pre-computed from company_info (trailingPE or pe_ratio)
      2. Market Cap / Net Income (quarterly statements)
      3. Market Cap / Net Income (annual statements)
      4. Raw Ticker.info net_income_raw fallback
      5. Price / Basic EPS (quarterly or annual)

    :param financials: Dict with 'income_statement', 'balance_sheet', 'cash_flow'
    :type financials: dict
    :param company_info: Optional pre-computed info dict from yfinance
    :type company_info: dict or None
    :return: P/E ratio or None
    :rtype: float or None
    """
    # Try pre-computed first
    if company_info:
        val = _safe_float(company_info.get("pe_ratio"))
        if val is not None:
            return val

    ci = company_info or {}
    income = financials.get("income_statement", {})
    annual_income = financials.get("annual_income_statement", {})
    balance = financials.get("balance_sheet", {})
    annual_balance = financials.get("annual_balance_sheet", {})
    market_cap = _safe_float(ci.get("market_cap"))

    # Method 1: Market Cap / Net Income (quarterly → annual → raw Ticker.info)
    net_income = (
        _extract_field(income, _NET_INCOME_ALIASES)
        or _extract_field(annual_income, _NET_INCOME_ALIASES)
        or _safe_float(ci.get("net_income_raw"))
    )

    if market_cap and net_income and net_income != 0:
        return round(market_cap / net_income, 4)

    # Method 2: from EPS field (quarterly → annual)
    eps = _extract_field(income, _BASIC_EPS_ALIASES) or _extract_field(annual_income, _BASIC_EPS_ALIASES)
    if eps and eps != 0:
        shares = (
            _extract_field(balance, _SHARES_OUTSTANDING_ALIASES)
            or _extract_field(annual_balance, _SHARES_OUTSTANDING_ALIASES)
            or _safe_float(ci.get("shares_outstanding"))
        )
        if market_cap and shares and shares > 0:
            price = market_cap / shares
            return round(price / eps, 4)
        # Try current_price directly
        price = _safe_float(ci.get("current_price"))
        if price and price > 0:
            return round(price / eps, 4)

    # Method 3: current_price / trailing_eps from Ticker.info
    trailing_eps = _safe_float(ci.get("trailing_eps"))
    price = _safe_float(ci.get("current_price"))
    if trailing_eps and trailing_eps != 0 and price and price > 0:
        return round(price / trailing_eps, 4)

    return None


def calculate_pb_ratio(financials: dict, company_info: dict = None) -> Optional[float]:
    """Calculate Price-to-Book ratio from raw financial data.

    Multi-source cascade:
      1. Pre-computed from company_info (priceToBook)
      2. Market Cap / Equity (quarterly balance sheet)
      3. Market Cap / Equity (annual balance sheet)
      4. Market Cap / Raw Ticker.info stockholders_equity
      5. Price / bookValue from Ticker.info

    :param financials: Dict with financial statements
    :type financials: dict
    :param company_info: Optional pre-computed info dict
    :type company_info: dict or None
    :return: P/B ratio or None
    :rtype: float or None
    """
    if company_info:
        val = _safe_float(company_info.get("pb_ratio"))
        if val is not None:
            return val

    ci = company_info or {}
    balance = financials.get("balance_sheet", {})
    annual_balance = financials.get("annual_balance_sheet", {})
    market_cap = _safe_float(ci.get("market_cap"))

    # Try equity from quarterly → annual → raw Ticker.info
    equity = (
        _extract_field(balance, _STOCKHOLDERS_EQUITY_ALIASES)
        or _extract_field(annual_balance, _STOCKHOLDERS_EQUITY_ALIASES)
        or _safe_float(ci.get("stockholders_equity"))
    )

    if market_cap and equity and equity != 0:
        return round(market_cap / equity, 4)

    # Fallback: bookValue * sharesOutstanding for equity estimate
    book_value = _safe_float(ci.get("book_value"))
    shares = _safe_float(ci.get("shares_outstanding"))
    if market_cap and book_value and shares and book_value != 0 and shares > 0:
        equity_est = book_value * shares
        if equity_est != 0:
            return round(market_cap / equity_est, 4)

    # Fallback: Price / bookValue per share
    price = _safe_float(ci.get("current_price"))
    if price and book_value and book_value != 0:
        return round(price / book_value, 4)

    return None


def calculate_ev_ebitda(financials: dict, company_info: dict = None) -> Optional[float]:
    """Calculate Enterprise Value to EBITDA from raw financial data.

    EV = Market Cap + Total Debt - Cash
    EBITDA from income statement, or Operating Income + D&A as fallback.

    Multi-source cascade:
      1. Pre-computed from company_info (enterpriseToEbitda)
      2. Raw Ticker.info fields (enterpriseValue / ebitda)
      3. Enterprise Value (raw or computed) / ebitda_raw from Ticker.info
      4. EV / EBITDA from quarterly financial statements
      5. EV / EBITDA from annual financial statements
      6. EV / (Operating Income + D&A) fallback
      7. EV / (Net Income + Interest + Tax + D&A) fallback

    :param financials: Dict with financial statements
    :type financials: dict
    :param company_info: Optional pre-computed info dict
    :type company_info: dict or None
    :return: EV/EBITDA ratio or None
    :rtype: float or None
    """
    if company_info:
        val = _safe_float(company_info.get("ev_ebitda"))
        if val is not None:
            return val

    ci = company_info or {}

    # Method 1: Raw Ticker.info fields (enterpriseValue / ebitda)
    ev_raw = _safe_float(ci.get("enterprise_value"))
    ebitda_info = _safe_float(ci.get("ebitda_raw"))
    if ev_raw and ebitda_info and ebitda_info > 0:
        return round(ev_raw / ebitda_info, 4)

    income = financials.get("income_statement", {})
    balance = financials.get("balance_sheet", {})
    cash_flow = financials.get("cash_flow", {})
    annual_income = financials.get("annual_income_statement", {})
    annual_balance = financials.get("annual_balance_sheet", {})
    annual_cash_flow = financials.get("annual_cash_flow", {})

    market_cap = _safe_float(ci.get("market_cap"))
    if not market_cap:
        return None

    # --- Determine Enterprise Value (None-aware: 0.0 is valid) ---
    # Prefer raw EV from Ticker.info; fallback: compute from components
    ev = ev_raw
    if ev is None:
        total_debt = _extract_field(balance, _TOTAL_DEBT_ALIASES)
        if total_debt is None:
            total_debt = _safe_float(ci.get("total_debt_raw"))
        if total_debt is None:
            total_debt = _extract_field(annual_balance, _TOTAL_DEBT_ALIASES)
        if total_debt is None:
            total_debt = 0.0

        cash = _extract_field(balance, _CASH_ALIASES)
        if cash is None:
            cash = _safe_float(ci.get("total_cash"))
        if cash is None:
            cash = _extract_field(annual_balance, _CASH_ALIASES)
        if cash is None:
            cash = 0.0

        ev = market_cap + total_debt - cash

    # --- Determine EBITDA from all sources (None-aware) ---
    ebitda = None

    # Source 1: ebitda_raw from Ticker.info (catches cases where EV was
    # computed manually but ebitda_raw is available)
    if ebitda_info is not None and ebitda_info > 0:
        ebitda = ebitda_info

    # Source 2: Quarterly financial statements
    if ebitda is None:
        ebitda = _extract_field(income, _EBITDA_ALIASES)

    # Source 3: Annual financial statements
    if ebitda is None:
        ebitda = _extract_field(annual_income, _EBITDA_ALIASES)

    # Source 4: Operating Income + Depreciation (None-aware)
    if ebitda is None:
        op_income = _extract_field(income, _OPERATING_INCOME_ALIASES)
        if op_income is None:
            op_income = _safe_float(ci.get("operating_income"))
        if op_income is None:
            op_income = _extract_field(annual_income, _OPERATING_INCOME_ALIASES)

        depreciation = _extract_field(cash_flow, _DEPRECIATION_ALIASES)
        if depreciation is None:
            depreciation = _extract_field(income, _DEPRECIATION_ALIASES)
        if depreciation is None:
            depreciation = _extract_field(annual_cash_flow, _DEPRECIATION_ALIASES)
        if depreciation is None:
            depreciation = _extract_field(annual_income, _DEPRECIATION_ALIASES)

        if op_income is not None:
            ebitda = op_income + abs(depreciation if depreciation is not None else 0.0)

    # Source 5: Net Income + Interest + Tax + D&A (None-aware)
    if ebitda is None:
        net_income = _extract_field(income, _NET_INCOME_ALIASES)
        if net_income is None:
            net_income = _safe_float(ci.get("net_income_raw"))
        if net_income is None:
            net_income = _extract_field(annual_income, _NET_INCOME_ALIASES)

        if net_income is not None:
            interest = _extract_field(income, _INTEREST_EXPENSE_ALIASES)
            if interest is None:
                interest = _extract_field(annual_income, _INTEREST_EXPENSE_ALIASES)
            if interest is None:
                interest = 0.0

            tax = _extract_field(income, _TAX_EXPENSE_ALIASES)
            if tax is None:
                tax = _extract_field(annual_income, _TAX_EXPENSE_ALIASES)
            if tax is None:
                tax = 0.0

            depreciation = _extract_field(cash_flow, _DEPRECIATION_ALIASES)
            if depreciation is None:
                depreciation = _extract_field(annual_cash_flow, _DEPRECIATION_ALIASES)
            if depreciation is None:
                depreciation = 0.0

            ebitda = net_income + abs(interest) + abs(tax) + abs(depreciation)

    if ebitda is not None and ebitda != 0:
        return round(ev / ebitda, 4)

    return None


def calculate_dividend_yield(financials: dict, company_info: dict = None) -> Optional[float]:
    """Calculate Dividend Yield from raw financial data.

    Dividend Yield = |Dividends Paid| / Market Cap
    (Dividends paid is negative in cash flow statements.)

    If no dividend data exists but market_cap is available, returns 0
    (the company does not pay dividends — 0% yield is real data).

    :param financials: Dict with financial statements
    :type financials: dict
    :param company_info: Optional pre-computed info dict
    :type company_info: dict or None
    :return: Dividend yield or None
    :rtype: float or None
    """
    if company_info:
        val = _safe_float(company_info.get("dividend_yield"))
        if val is not None:
            return val

    ci = company_info or {}
    cash_flow = financials.get("cash_flow", {})
    annual_cash_flow = financials.get("annual_cash_flow", {})
    market_cap = _safe_float(ci.get("market_cap"))

    # Try quarterly cash flow first, then annual
    dividends = _extract_field(cash_flow, _DIVIDENDS_PAID_ALIASES)
    if dividends is None:
        dividends = _extract_field(annual_cash_flow, _DIVIDENDS_PAID_ALIASES)

    if dividends is not None and market_cap and market_cap > 0:
        div_yield = abs(dividends) / market_cap
        return round(div_yield * 100, 6)

    # No dividend data but we have market_cap → company doesn't pay dividends = 0%
    if market_cap and market_cap > 0:
        return 0.0

    return None


def calculate_debt_equity(financials: dict, company_info: dict = None) -> Optional[float]:
    """Calculate Debt-to-Equity ratio from raw financial data.

    D/E = Total Debt / Stockholders' Equity

    Multi-source cascade:
      1. Pre-computed from company_info (debtToEquity)
      2. Raw Ticker.info fields (totalDebt / stockholdersEquity)
      3. Quarterly balance sheet (total_debt / equity)
      4. Annual balance sheet fallback
      5. Cross-source: Ticker.info debt with statement equity (and vice versa)
      6. Total Liabilities / Equity as last resort
      7. Equity from Assets - Liabilities when direct equity unavailable
      8. If equity exists but no debt found → 0 (debt-free company)

    :param financials: Dict with financial statements
    :type financials: dict
    :param company_info: Optional pre-computed info dict
    :type company_info: dict or None
    :return: Debt/Equity ratio (percentage format) or None
    :rtype: float or None
    """
    if company_info:
        val = _safe_float(company_info.get("debt_equity"))
        if val is not None:
            return val

    ci = company_info or {}
    balance = financials.get("balance_sheet", {})
    annual_balance = financials.get("annual_balance_sheet", {})

    # --- Gather debt from all sources (None-aware: 0.0 is valid) ---
    td_raw = _safe_float(ci.get("total_debt_raw"))
    total_debt = _extract_field(balance, _TOTAL_DEBT_ALIASES)
    if total_debt is None:
        total_debt = td_raw
    if total_debt is None:
        total_debt = _extract_field(annual_balance, _TOTAL_DEBT_ALIASES)

    # --- Gather equity from all sources (None-aware: 0.0 is valid) ---
    eq_raw = _safe_float(ci.get("stockholders_equity"))
    equity = _extract_field(balance, _STOCKHOLDERS_EQUITY_ALIASES)
    if equity is None:
        equity = eq_raw
    if equity is None:
        equity = _extract_field(annual_balance, _STOCKHOLDERS_EQUITY_ALIASES)

    # Fallback: equity = Total Assets - Total Liabilities
    if equity is None:
        assets = _extract_field(balance, _TOTAL_ASSETS_ALIASES)
        if assets is None:
            assets = _safe_float(ci.get("total_assets"))
        if assets is None:
            assets = _extract_field(annual_balance, _TOTAL_ASSETS_ALIASES)
        liabilities = _extract_field(balance, _TOTAL_LIABILITIES_ALIASES)
        if liabilities is None:
            liabilities = _safe_float(ci.get("total_liabilities"))
        if liabilities is None:
            liabilities = _extract_field(annual_balance, _TOTAL_LIABILITIES_ALIASES)
        if assets is not None and liabilities is not None:
            equity = assets - liabilities

    # Compute D/E if we have both (allow negative equity from buybacks)
    if total_debt is not None and equity is not None and equity != 0:
        return round((total_debt / equity) * 100, 4)

    # Fallback: Total Liabilities / Equity (allow negative equity)
    if equity is not None and equity != 0:
        total_liab = _safe_float(ci.get("total_liabilities"))
        if total_liab is None:
            total_liab = _extract_field(balance, _TOTAL_LIABILITIES_ALIASES)
        if total_liab is None:
            total_liab = _extract_field(annual_balance, _TOTAL_LIABILITIES_ALIASES)
        if total_liab is not None:
            return round((total_liab / equity) * 100, 4)
        # No debt data at all but equity exists → debt-free company
        return 0.0

    # Last resort: if we have debt and assets, estimate equity from assets
    if total_debt is not None:
        assets = _extract_field(balance, _TOTAL_ASSETS_ALIASES)
        if assets is None:
            assets = _safe_float(ci.get("total_assets"))
        if assets is None:
            assets = _extract_field(annual_balance, _TOTAL_ASSETS_ALIASES)
        if assets is not None and assets > 0:
            equity_est = assets - total_debt
            if equity_est != 0:
                return round((total_debt / equity_est) * 100, 4)

    # Last resort: Total Liabilities / Total Assets as leverage proxy
    if equity is None or equity == 0:
        liabilities = _extract_field(balance, _TOTAL_LIABILITIES_ALIASES)
        if liabilities is None:
            liabilities = _safe_float(ci.get("total_liabilities"))
        if liabilities is None:
            liabilities = _extract_field(annual_balance, _TOTAL_LIABILITIES_ALIASES)
        assets = _extract_field(balance, _TOTAL_ASSETS_ALIASES)
        if assets is None:
            assets = _safe_float(ci.get("total_assets"))
        if assets is None:
            assets = _extract_field(annual_balance, _TOTAL_ASSETS_ALIASES)
        if liabilities is not None and assets is not None and assets > 0:
            # Return as percentage: (liabilities/assets)*100
            return round((liabilities / assets) * 100, 4)

    return None


# ---------------------------------------------------------------------------
# Ratio enhancement: fill missing ratios from raw financials
# ---------------------------------------------------------------------------


def enhance_company_info(company_info: dict, financials: dict) -> dict:
    """Enhance a company_info dict by calculating any missing ratios
    from the raw financial statement data.

    This is the key fallback mechanism: when ``fetch_company_info()``
    returns partial data, this function fills in the gaps from
    ``fetch_financial_data()`` results.

    :param company_info: Existing company info (may have some ratios)
    :type company_info: dict
    :param financials: Raw financial statements dict
    :type financials: dict
    :return: Enhanced company_info with calculated ratios filled in
    :rtype: dict
    """
    if not financials:
        return company_info

    enhanced = dict(company_info)

    # Calculate each ratio only if not already present
    if _safe_float(enhanced.get("pe_ratio")) is None:
        pe = calculate_pe_ratio(financials, enhanced)
        if pe is not None:
            enhanced["pe_ratio"] = pe
            pipeline_logger.debug(
                "Calculated P/E=%.2f for %s from financials",
                pe,
                enhanced.get("symbol", "?"),
            )

    if _safe_float(enhanced.get("pb_ratio")) is None:
        pb = calculate_pb_ratio(financials, enhanced)
        if pb is not None:
            enhanced["pb_ratio"] = pb
            pipeline_logger.debug(
                "Calculated P/B=%.2f for %s from financials",
                pb,
                enhanced.get("symbol", "?"),
            )

    if _safe_float(enhanced.get("ev_ebitda")) is None:
        ev = calculate_ev_ebitda(financials, enhanced)
        if ev is not None:
            enhanced["ev_ebitda"] = ev
            pipeline_logger.debug(
                "Calculated EV/EBITDA=%.2f for %s from financials",
                ev,
                enhanced.get("symbol", "?"),
            )

    if _safe_float(enhanced.get("dividend_yield")) is None:
        dy = calculate_dividend_yield(financials, enhanced)
        if dy is not None:
            enhanced["dividend_yield"] = dy

    if _safe_float(enhanced.get("debt_equity")) is None:
        de = calculate_debt_equity(financials, enhanced)
        if de is not None:
            enhanced["debt_equity"] = de

    return enhanced


def calculate_ratios_from_financials(ticker: str, financials: dict, market_cap: float = None) -> dict:
    """Calculate all five ratios from raw financial data for a single company.

    Used as the primary calculator when ``fetch_company_info()`` returns
    no pre-computed ratios.  Constructs a minimal company_info dict from
    the raw financial statements.

    :param ticker: Company ticker symbol
    :type ticker: str
    :param financials: Raw financial statements dict
    :type financials: dict
    :param market_cap: Market capitalisation (needed for P/E, P/B, EV/EBITDA)
    :type market_cap: float or None
    :return: Dict with calculated ratio fields
    :rtype: dict
    """
    info = {"symbol": ticker, "market_cap": market_cap}

    info["pe_ratio"] = calculate_pe_ratio(financials, info)
    info["pb_ratio"] = calculate_pb_ratio(financials, info)
    info["ev_ebitda"] = calculate_ev_ebitda(financials, info)
    info["dividend_yield"] = calculate_dividend_yield(financials, info)
    info["debt_equity"] = calculate_debt_equity(financials, info)

    # Only return if at least one ratio was calculated
    has_any = any(
        _safe_float(info.get(k)) is not None
        for k in ("pe_ratio", "pb_ratio", "ev_ebitda", "dividend_yield", "debt_equity")
    )
    if has_any:
        calculated = [
            k
            for k in ("pe_ratio", "pb_ratio", "ev_ebitda", "dividend_yield", "debt_equity")
            if _safe_float(info.get(k)) is not None
        ]
        pipeline_logger.info(
            "Calculated %d ratios for %s from financials: %s",
            len(calculated),
            ticker,
            ", ".join(calculated),
        )
        return info

    return {}


# ---------------------------------------------------------------------------
# Percentile ranking and Value Score (Task 5.1 specification)
# ---------------------------------------------------------------------------


def rank_companies(all_company_ratios: list[dict]) -> list[dict]:
    """Rank all companies by percentile (0-100) for each ratio.

    For P/E, P/B, EV/EBITDA: lower is better (inverted rank).
    For Dividend Yield: higher is better (keep rank as-is).
    Debt/Equity is NOT ranked — used only as a filter.

    :param all_company_ratios: List of company info dicts with ratio fields
    :type all_company_ratios: list[dict]
    :return: List of dicts with percentile rank fields added
    :rtype: list[dict]
    """
    if not all_company_ratios:
        return []

    scoring_metrics = {
        "pe_ratio": [],
        "pb_ratio": [],
        "ev_ebitda": [],
        "dividend_yield": [],
    }

    # Apply data quality rules — preserve originals for storage
    original_pe = {}
    original_ev = {}
    for company in all_company_ratios:
        sym = company.get("symbol", "")
        pe = _safe_float(company.get("pe_ratio"))
        ev = _safe_float(company.get("ev_ebitda"))
        original_pe[sym] = pe
        original_ev[sym] = ev
        if pe is not None and pe < 0:
            pipeline_logger.info(
                "Excluding negative P/E (%.2f) for %s from ranking",
                pe,
                company.get("symbol"),
            )
            company["pe_ratio"] = None
        elif pe is not None and pe > 500:
            pipeline_logger.info(
                "Capping extreme P/E (%.2f) for %s from ranking",
                pe,
                company.get("symbol"),
            )
            company["pe_ratio"] = None
        # Negative EV/EBITDA → exclude from ranking (not meaningful for value)
        if ev is not None and ev < 0:
            pipeline_logger.info(
                "Excluding negative EV/EBITDA (%.2f) for %s from ranking",
                ev,
                company.get("symbol"),
            )
            company["ev_ebitda"] = None

    # Collect values for ranking
    for company in all_company_ratios:
        for key in scoring_metrics:
            scoring_metrics[key].append(_safe_float(company.get(key)))

    # Compute percentile ranks
    ranks = {}
    for key, values in scoring_metrics.items():
        ranks[key] = _percentile_rank(values)

    # Invert for lower-is-better metrics
    invert_metrics = {"pe_ratio", "pb_ratio", "ev_ebitda"}

    results = []
    for idx, company in enumerate(all_company_ratios):
        record = dict(company)
        sym = company.get("symbol", "")
        # Restore original P/E for storage (was nulled for ranking only)
        orig_pe = original_pe.get(sym)
        if orig_pe is not None and record.get("pe_ratio") is None:
            record["pe_ratio"] = orig_pe
        # Restore original EV/EBITDA for storage (was nulled for ranking only)
        orig_ev = original_ev.get(sym)
        if orig_ev is not None and record.get("ev_ebitda") is None:
            record["ev_ebitda"] = orig_ev
        for key in scoring_metrics:
            rank_val = ranks[key][idx]
            if rank_val is not None:
                if key in invert_metrics:
                    record[f"{key}_pctile"] = round((1.0 - rank_val) * 100, 2)
                else:
                    record[f"{key}_pctile"] = round(rank_val * 100, 2)
            else:
                record[f"{key}_pctile"] = None
        results.append(record)

    return results


def compute_value_score(ranked_companies: list[dict], score_date: date = None) -> list[dict]:
    """Compute composite Value Score from percentile-ranked data.

    Value Score = average of available percentile ranks, scaled 0-100.
    Missing metrics are excluded from the average (handle missing data).

    This is the final output function that produces records ready for
    PostgreSQL ``value_metrics`` table.

    :param ranked_companies: Output from ``rank_companies()``
    :type ranked_companies: list[dict]
    :param score_date: Date to assign to the scores (default: today)
    :type score_date: date or None
    :return: List of value metric records for PostgreSQL upsert
    :rtype: list[dict]
    """
    if score_date is None:
        score_date = date.today()

    pctile_keys = ["pe_ratio_pctile", "pb_ratio_pctile", "ev_ebitda_pctile", "dividend_yield_pctile"]

    results = []
    for company in ranked_companies:
        available = [company[k] for k in pctile_keys if company.get(k) is not None]
        value_score = float(np.mean(available)) if available else None

        # Convert dividend_yield and debt_equity from yfinance % format to decimal
        raw_dy = _safe_float(company.get("dividend_yield"))
        raw_de = _safe_float(company.get("debt_equity"))

        results.append(
            {
                "company_id": company.get("symbol", ""),
                "date": score_date.strftime("%Y-%m-%d"),
                "pe_ratio": _safe_float(company.get("pe_ratio")),
                "pb_ratio": _safe_float(company.get("pb_ratio")),
                "ev_ebitda": _safe_float(company.get("ev_ebitda")),
                "dividend_yield": round(raw_dy / 100, 6) if raw_dy is not None else None,
                "debt_equity": round(raw_de / 100, 6) if raw_de is not None else None,
                "value_score": round(value_score, 4) if value_score is not None else None,
            }
        )

    scored_count = sum(1 for r in results if r["value_score"] is not None)
    pipeline_logger.info("Computed value scores for %d/%d companies", scored_count, len(results))
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _percentile_rank(values: list) -> list:
    """Compute percentile ranks for a list of values, handling NaN/None.

    Returns a rank between 0 and 1 for each value, or None if the
    original value was missing.

    :param values: List of numeric values (may contain None)
    :type values: list
    :return: List of percentile ranks (0-1) or None
    :rtype: list
    """
    valid_pairs = [(i, v) for i, v in enumerate(values) if v is not None and np.isfinite(v)]
    result = [None] * len(values)

    if len(valid_pairs) < 2:
        for i, v in valid_pairs:
            result[i] = 0.5
        return result

    sorted_pairs = sorted(valid_pairs, key=lambda x: x[1])
    n = len(sorted_pairs)
    for rank_position, (original_idx, _) in enumerate(sorted_pairs):
        result[original_idx] = rank_position / (n - 1) if n > 1 else 0.5

    return result
