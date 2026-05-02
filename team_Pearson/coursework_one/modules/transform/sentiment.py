"""Loughran-McDonald (L-M) sentiment scoring for financial news articles.

Scores raw article dicts (from Alpha Vantage or Finnhub) using the Loughran-McDonald
financial-domain lexicon via ``pysentiment2``.  The L-M lexicon was designed
specifically for financial text and avoids the general-language bias of VADER
(e.g. "liability" is neutral in VADER but negative in finance).

Sentiment score formula (L-M standard)::

    score = (positive_count - negative_count) / max(total_tokens, 1)

Output range: [-1, 1].

Aggregated daily factors written to ``factor_observations``:

* ``sentiment_7d_avg``  — 7-day rolling average score (short-term signal)
* ``sentiment_30d_avg`` — 30-day rolling average score (medium-term signal)
* ``sentiment_dispersion_7d`` — 7-day rolling std dev (disagreement/uncertainty signal)
* ``article_count_7d``  — article count in the last 7 days
* ``article_count_30d`` — article count in the last 30 days

These replace the previous VADER-based ``sentiment_30d_avg`` and
``article_count_30d`` factors in the pipeline.

Example usage::

    from modules.transform.sentiment import score_articles, aggregate_daily_sentiment

    articles = [{"symbol": "AAPL", "publish_date": date(2024,1,5),
                 "headline": "Apple beats earnings estimates",
                 "summary": "Revenue grew 8% year-over-year..."}]
    scored = score_articles(articles)
    factor_records = aggregate_daily_sentiment(scored)
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# L-M lexicon initialisation (lazy)
# ---------------------------------------------------------------------------

_lm_scorer: Any = None
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
    "increase",
    "record",
    "exceed",
}
_FALLBACK_NEGATIVE = {
    "loss",
    "decline",
    "weak",
    "miss",
    "downgrade",
    "negative",
    "decrease",
    "layoff",
    "restructur",
    "writedown",
    "impairment",
    "bankruptcy",
    "default",
    "lawsuit",
    "fine",
    "penalty",
}

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _get_lm_scorer() -> Any:
    """Return shared pysentiment2 LM scorer instance (lazy init).

    :returns: ``pysentiment2.LM()`` instance, or ``None`` if unavailable.
    :rtype: Any
    """
    global _lm_scorer
    if _lm_scorer is not None:
        return _lm_scorer
    try:
        import pysentiment2 as ps2  # type: ignore

        _lm_scorer = ps2.LM()
        logger.info("sentiment: pysentiment2 L-M lexicon loaded successfully")
        return _lm_scorer
    except Exception as exc:
        logger.warning(
            "sentiment: pysentiment2 unavailable (%s). "
            "Using minimal fallback lexicon — scores will be approximate.",
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Token-level scoring
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> List[str]:
    """Lowercase and split text into alphabetic tokens.

    :param text: Raw input text.
    :type text: str
    :returns: List of lowercase word tokens.
    :rtype: list[str]
    """
    return [t for t in _TOKEN_RE.split(text.lower()) if t]


def _score_text_lm(text: str, scorer: Any) -> Tuple[int, int, int]:
    """Score *text* with the L-M lexicon.

    :param text: Concatenated headline + summary.
    :param scorer: pysentiment2 LM instance.
    :returns: ``(positive_count, negative_count, total_tokens)`` tuple.
    :rtype: tuple[int, int, int]
    """
    tokens = scorer.tokenize(text)
    score = scorer.get_score(tokens)
    pos = int(score.get("Positive", 0))
    neg = int(score.get("Negative", 0))
    return pos, neg, max(len(tokens), 1)


def _score_text_fallback(text: str) -> Tuple[int, int, int]:
    """Minimal fallback scorer using hand-crafted financial terms.

    :param text: Concatenated headline + summary.
    :returns: ``(positive_count, negative_count, total_tokens)`` tuple.
    :rtype: tuple[int, int, int]
    """
    tokens = _tokenize(text)
    pos = sum(1 for t in tokens if t in _FALLBACK_POSITIVE)
    neg = sum(1 for t in tokens if t in _FALLBACK_NEGATIVE)
    return pos, neg, max(len(tokens), 1)


def _compute_sentiment_score(headline: str, summary: str) -> Optional[float]:
    """Compute L-M sentiment score for a single article.

    Score formula: (positive - negative) / total_tokens ∈ [-1, 1].

    :param headline: Article headline.
    :type headline: str
    :param summary: Article summary or body excerpt.
    :type summary: str
    :returns: Sentiment score in [-1, 1], or ``None`` if text is empty.
    :rtype: float | None
    """
    text = f"{headline} {summary}".strip()
    if not text:
        return None

    scorer = _get_lm_scorer()
    if scorer is not None:
        pos, neg, total = _score_text_lm(text, scorer)
    else:
        pos, neg, total = _score_text_fallback(text)

    return (pos - neg) / total


# ---------------------------------------------------------------------------
# Article-level scoring
# ---------------------------------------------------------------------------


def score_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add L-M sentiment score to each article dict.

    Mutates input dicts in place (adds ``sentiment_score`` key).
    Articles with empty text or no publish_date are scored as ``None``.

    :param articles: List of article dicts (from AV/Finnhub extractors).
    :type articles: list[dict]
    :returns: Same list with ``sentiment_score`` field populated.
    :rtype: list[dict]
    """
    scored_count = 0
    for article in articles:
        headline = str(article.get("headline") or "")
        summary = str(article.get("summary") or "")
        score = _compute_sentiment_score(headline, summary)
        article["sentiment_score"] = score
        if score is not None:
            scored_count += 1

    logger.info(
        "sentiment: scored %s/%s articles with L-M lexicon",
        scored_count,
        len(articles),
    )
    return articles


# ---------------------------------------------------------------------------
# Daily aggregation
# ---------------------------------------------------------------------------


def _rolling_windows(
    daily_scores: Dict[date, List[float]],
    daily_counts: Dict[date, int],
    all_dates: List[date],
    window_days: int,
) -> Dict[date, Tuple[Optional[float], int]]:
    """Compute rolling window averages and counts for each date.

    :param daily_scores: Mapping of date → list of sentiment scores.
    :param daily_counts: Mapping of date → article count.
    :param all_dates: Sorted list of all trading dates to produce outputs for.
    :param window_days: Rolling window size in calendar days.
    :returns: Mapping of date → (average_score, article_count) for the window.
    :rtype: dict[date, tuple[float | None, int]]
    """
    result: Dict[date, Tuple[Optional[float], int]] = {}
    for obs_date in all_dates:
        window_start = obs_date - timedelta(days=window_days - 1)
        scores: List[float] = []
        count = 0
        d = window_start
        while d <= obs_date:
            scores.extend(daily_scores.get(d, []))
            count += daily_counts.get(d, 0)
            d += timedelta(days=1)
        avg = sum(scores) / len(scores) if scores else None
        result[obs_date] = (avg, count)
    return result


def aggregate_daily_sentiment(
    scored_articles: List[Dict[str, Any]],
    *,
    output_frequency: str = "daily",
) -> List[Dict[str, Any]]:
    """Aggregate scored articles into daily factor_observations records.

    Produces six factor types per symbol per date:

    * ``sentiment_7d_avg``
    * ``sentiment_30d_avg``
    * ``sentiment_dispersion_7d``
    * ``article_count_7d``
    * ``article_count_30d``
    * ``sentiment_surprise``

    :param scored_articles: Articles with ``sentiment_score`` field (from :func:`score_articles`).
    :type scored_articles: list[dict]
    :param output_frequency: Passed through to record metadata. Currently only ``'daily'`` used.
    :type output_frequency: str
    :returns: List of dicts ready for :func:`~modules.output.load.load_curated`.
    :rtype: list[dict]
    """
    # Group by (symbol, publish_date)
    by_symbol: Dict[str, Dict[date, List[Optional[float]]]] = defaultdict(lambda: defaultdict(list))
    source_by_symbol: Dict[str, str] = {}

    for article in scored_articles:
        symbol = str(article.get("symbol") or "").strip().upper()
        pub_date = article.get("publish_date")
        score = article.get("sentiment_score")

        if not symbol or pub_date is None:
            continue
        if isinstance(pub_date, str):
            try:
                from datetime import datetime as dt

                pub_date = dt.strptime(pub_date[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

        by_symbol[symbol][pub_date].append(score)
        source_by_symbol[symbol] = str(article.get("data_source") or "av+finnhub")

    records: List[Dict[str, Any]] = []

    for symbol, date_scores in by_symbol.items():
        source_label = source_by_symbol.get(symbol, "av+finnhub")

        daily_scores: Dict[date, List[float]] = {}
        daily_counts: Dict[date, int] = {}
        for d, scores in date_scores.items():
            valid = [s for s in scores if s is not None]
            daily_scores[d] = valid
            daily_counts[d] = len(scores)

        all_dates = sorted(date_scores.keys())

        windows_7 = _rolling_windows(daily_scores, daily_counts, all_dates, 7)
        windows_30 = _rolling_windows(daily_scores, daily_counts, all_dates, 30)

        for obs_date in all_dates:
            avg_7, count_7 = windows_7[obs_date]
            avg_30, count_30 = windows_30[obs_date]

            base = {
                "symbol": symbol,
                "observation_date": obs_date,
                "source": source_label,
                "metric_frequency": output_frequency,
                "source_report_date": obs_date,
                "publish_date": obs_date,
            }

            records.append({**base, "factor_name": "sentiment_7d_avg", "factor_value": avg_7})
            records.append({**base, "factor_name": "sentiment_30d_avg", "factor_value": avg_30})

            # sentiment_dispersion_7d: std dev of article scores in 7-day window.
            # High dispersion = disagreement across sources = uncertainty signal.
            window_start_7 = obs_date - timedelta(days=6)
            disp_scores: List[float] = []
            d = window_start_7
            while d <= obs_date:
                disp_scores.extend(daily_scores.get(d, []))
                d += timedelta(days=1)
            if len(disp_scores) >= 2:
                mean = sum(disp_scores) / len(disp_scores)
                variance = sum((s - mean) ** 2 for s in disp_scores) / (len(disp_scores) - 1)
                dispersion = math.sqrt(variance)
            else:
                dispersion = None
            records.append(
                {**base, "factor_name": "sentiment_dispersion_7d", "factor_value": dispersion}
            )

            records.append(
                {**base, "factor_name": "article_count_7d", "factor_value": float(count_7)}
            )
            records.append(
                {**base, "factor_name": "article_count_30d", "factor_value": float(count_30)}
            )

            # sentiment_surprise: 7d_avg - 30d_avg
            # Captures momentum/inflection in sentiment (positive = improving, negative = deteriorating)
            if avg_7 is not None and avg_30 is not None:
                surprise = avg_7 - avg_30
                records.append(
                    {**base, "factor_name": "sentiment_surprise", "factor_value": surprise}
                )

    # Drop records with null factor_value for score factors (count factors always valid)
    records = [
        r
        for r in records
        if r["factor_name"].startswith("article_count") or r["factor_value"] is not None
    ]

    logger.info(
        "sentiment: aggregated %s factor records from %s scored articles",
        len(records),
        len(scored_articles),
    )
    return records
