"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Value factor scoring (percentile-rank composite)
Project : CW1 - Value + News Sentiment Strategy

Computes a composite Value Score for each company based on
percentile-rank normalisation of four fundamental ratios:

  1. P/E  ratio     — Price-to-Earnings (lower is cheaper)
  2. P/B  ratio     — Price-to-Book (lower is cheaper)
  3. EV/EBITDA      — Enterprise Value to EBITDA (lower is cheaper)
  4. Dividend Yield — Cash return to shareholders (higher is better)

Debt/Equity is **not** included in the Value Score average — it is used
only as a filter (D/E > 2.0 → exclude) in the composite scoring stage.

The Value Score is the average percentile rank across available scoring
metrics, scaled to 0-100.  Missing metrics are excluded from the average.

Data quality rules:
  - Negative P/E ratios are excluded from the P/E ranking (company may
    still receive scores from the other three ratios).
  - Extreme ratios (P/E > 500) are capped at the 99th percentile.

Academic foundation:
  - Fama, E.F. & French, K.R. (1993), "Common risk factors in the
    returns on stocks and bonds", JFE.
  - Greenblatt, J. (2006), "The Little Book That Beats the Market".

Design note: Ratios are fetched directly from Yahoo Finance's
``Ticker.info`` endpoint (pre-computed by Yahoo) rather than
recalculated from raw financial statements.  This is more reliable
and avoids data inconsistency issues with quarterly statement timing.
"""

from datetime import date
from typing import Optional

import numpy as np

from modules.utils.logger import pipeline_logger


def compute_value_scores(company_infos: list[dict], score_date: date = None) -> list[dict]:
    """Compute percentile-rank Value Scores for a list of companies.

    Steps:
      1. Extract the five ratio fields from each company's info dict.
      2. Rank each metric across the universe (percentile rank 0-1).
      3. Invert rank for P/E, P/B, EV/EBITDA, D/E (lower = better).
      4. Keep rank as-is for Dividend Yield (higher = better).
      5. Average available percentile ranks into composite Value Score.

    :param company_infos: List of dicts from yahoo_finance_extractor.fetch_company_info
    :type company_infos: list[dict]
    :param score_date: Date to assign to the scores (default: today)
    :type score_date: date or None
    :return: List of value metric record dicts ready for PostgreSQL upsert
    :rtype: list[dict]

    Example::

        >>> infos = [{'symbol': 'AAPL', 'pe_ratio': 28.5, 'pb_ratio': 40.1,
        ...           'ev_ebitda': 22.0, 'dividend_yield': 0.005, 'debt_equity': 1.5}]
        >>> scores = compute_value_scores(infos)
        >>> 'value_score' in scores[0]
        True
    """
    if score_date is None:
        score_date = date.today()

    valid_companies = [c for c in company_infos if c.get("symbol")]
    if not valid_companies:
        return []

    # Apply data quality rules before ranking — preserve originals for storage
    original_pe = {}
    original_ev = {}
    for company in valid_companies:
        sym = company["symbol"]
        pe = _safe_float(company.get("pe_ratio"))
        ev = _safe_float(company.get("ev_ebitda"))
        original_pe[sym] = pe
        original_ev[sym] = ev

        # Negative P/E → exclude from ranking (company has negative earnings)
        if pe is not None and pe < 0:
            company["pe_ratio"] = None
        # Extreme P/E > 500 → exclude from ranking
        elif pe is not None and pe > 500:
            company["pe_ratio"] = None

        # Negative EV/EBITDA → exclude from ranking (negative EBITDA is not meaningful for value)
        if ev is not None and ev < 0:
            company["ev_ebitda"] = None

    # Scoring metrics: P/E, P/B, EV/EBITDA, Dividend Yield
    # Debt/Equity is NOT included in score — used only as a filter
    scoring_metrics = {
        "pe_ratio": [],
        "pb_ratio": [],
        "ev_ebitda": [],
        "dividend_yield": [],
    }
    for company in valid_companies:
        for key in scoring_metrics:
            val = company.get(key)
            scoring_metrics[key].append(_safe_float(val))

    # Compute percentile ranks for each scoring metric
    ranks = {}
    for key, values in scoring_metrics.items():
        ranks[key] = _percentile_rank(values)

    # For P/E, P/B, EV/EBITDA: lower is better → invert the rank
    # For Dividend Yield: higher is better → keep as-is
    invert_metrics = {"pe_ratio", "pb_ratio", "ev_ebitda"}

    results = []
    for idx, company in enumerate(valid_companies):
        available_ranks = []
        for key in scoring_metrics:
            rank_val = ranks[key][idx]
            if rank_val is not None:
                if key in invert_metrics:
                    available_ranks.append(1.0 - rank_val)
                else:
                    available_ranks.append(rank_val)

        # Scale to 0-100 per specification
        value_score = float(np.mean(available_ranks) * 100.0) if available_ranks else None

        results.append(
            {
                "company_id": company["symbol"],
                "date": score_date.strftime("%Y-%m-%d"),
                # Use original P/E (before ranking exclusion) for storage/display
                "pe_ratio": original_pe.get(company["symbol"], _safe_float(company.get("pe_ratio"))),
                "pb_ratio": _safe_float(company.get("pb_ratio")),
                # Use original EV/EBITDA (before ranking exclusion) for storage/display
                "ev_ebitda": original_ev.get(company["symbol"], _safe_float(company.get("ev_ebitda"))),
                # yfinance dividendYield is in % form (e.g. 2.7 = 2.7%); convert to decimal (0.027)
                "dividend_yield": (
                    round(_safe_float(company.get("dividend_yield")) / 100, 6)
                    if _safe_float(company.get("dividend_yield")) is not None
                    else None
                ),
                # yfinance debtToEquity is in % form (e.g. 102.63); convert to ratio (1.0263)
                "debt_equity": (
                    round(_safe_float(company.get("debt_equity")) / 100, 6)
                    if _safe_float(company.get("debt_equity")) is not None
                    else None
                ),
                "value_score": round(value_score, 4) if value_score is not None else None,
            }
        )

    scored_count = sum(1 for r in results if r["value_score"] is not None)
    pipeline_logger.info("Computed value scores for %d/%d companies", scored_count, len(results))
    return results


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


def _safe_float(val) -> Optional[float]:
    """Convert a value to float, returning None for invalid inputs.

    :param val: Value to convert
    :return: Float or None
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
