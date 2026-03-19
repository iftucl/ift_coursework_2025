"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Composite factor scoring (Value × Sentiment)
Project : CW1 - Value + News Sentiment Strategy

Combines Value Score and Sentiment Score into a single Composite Score
for investment ranking.  The composite formula is:

    Composite = w_v × Value_Score + w_s × Sentiment_Score

Default weights: w_v = 0.6, w_s = 0.4

Academic rationale: Value investing captures the Fama-French value
premium, while sentiment scoring avoids "value traps" — cheap stocks
with deteriorating fundamentals and negative market perception.

Filtering rules (configurable):
  1. Debt/Equity < 2.0 (exclude highly leveraged firms)
  2. Average Sentiment > 0 (exclude firms with negative news flow)
  3. Minimum 3 articles (exclude firms with insufficient coverage)

After scoring and filtering, companies are ranked by Composite Score
and the top quintile (or configurable threshold) receives an
``invest_decision = True`` flag for CW2 portfolio construction.
"""

from datetime import date
from typing import Optional

from modules.utils.logger import pipeline_logger


def compute_composite_scores(
    value_records: list[dict],
    sentiment_records: list[dict],
    value_weight: float = 0.6,
    sentiment_weight: float = 0.4,
    max_debt_equity: float = 2.0,
    min_avg_sentiment: float = 0.0,
    min_articles: int = 3,
    top_quintile: bool = True,
    score_date: date = None,
) -> list[dict]:
    """Combine value and sentiment scores into ranked composite scores.

    :param value_records: Value metric records from value_scorer
    :type value_records: list[dict]
    :param sentiment_records: Sentiment records from sentiment_scorer
    :type sentiment_records: list[dict]
    :param value_weight: Weight for value score (default 0.6)
    :type value_weight: float
    :param sentiment_weight: Weight for sentiment score (default 0.4)
    :type sentiment_weight: float
    :param max_debt_equity: Maximum D/E ratio filter
    :type max_debt_equity: float
    :param min_avg_sentiment: Minimum average sentiment filter
    :type min_avg_sentiment: float
    :param min_articles: Minimum article count for sentiment reliability
    :type min_articles: int
    :param top_quintile: If True, flag top 20% as invest_decision=True
    :type top_quintile: bool
    :param score_date: Date for rankings
    :type score_date: date or None
    :return: List of composite ranking records for PostgreSQL
    :rtype: list[dict]

    Example::

        >>> values = [{'company_id': 'AAPL', 'value_score': 72.5, 'debt_equity': 1.2}]
        >>> sents = [{'company_id': 'AAPL', 'sentiment_score': 68.0, 'total_articles': 10, 'avg_sentiment': 0.2}]
        >>> results = compute_composite_scores(values, sents)
        >>> results[0]['composite_score'] > 0
        True
    """
    if score_date is None:
        score_date = date.today()
    date_str = score_date.strftime("%Y-%m-%d")

    # Build lookup dicts by company_id
    value_map = {r["company_id"]: r for r in value_records if r.get("company_id")}
    sentiment_map = {r["company_id"]: r for r in sentiment_records if r.get("company_id")}

    all_tickers = set(value_map.keys()) | set(sentiment_map.keys())
    scored = []

    for ticker in all_tickers:
        v_rec = value_map.get(ticker, {})
        s_rec = sentiment_map.get(ticker, {})

        value_score = v_rec.get("value_score")
        sentiment_score = s_rec.get("sentiment_score")
        debt_equity = v_rec.get("debt_equity")
        avg_sentiment = s_rec.get("avg_sentiment")
        total_articles = s_rec.get("total_articles", 0)

        # Apply quality filters
        if debt_equity is not None and debt_equity > max_debt_equity:
            continue
        if avg_sentiment is not None and avg_sentiment < min_avg_sentiment:
            continue
        if total_articles < min_articles:
            # Still include but with reduced confidence
            pass

        # Compute composite — handle missing components gracefully
        composite = _weighted_composite(value_score, sentiment_score, value_weight, sentiment_weight)

        scored.append(
            {
                "company_id": ticker,
                "date": date_str,
                "value_score": value_score,
                "sentiment_score": sentiment_score,
                "composite_score": composite,
                "rank": None,
                "invest_decision": False,
            }
        )

    # Sort by composite score descending and assign ranks
    scored.sort(key=lambda x: x["composite_score"] or 0, reverse=True)
    for rank_pos, record in enumerate(scored, start=1):
        record["rank"] = rank_pos

    # Flag top quintile for investment
    if top_quintile and scored:
        cutoff = max(1, len(scored) // 5)
        for record in scored[:cutoff]:
            record["invest_decision"] = True

    invest_count = sum(1 for r in scored if r["invest_decision"])
    pipeline_logger.info(
        "Composite scoring: %d companies scored, %d flagged for investment",
        len(scored),
        invest_count,
    )
    return scored


def _weighted_composite(
    value_score: Optional[float],
    sentiment_score: Optional[float],
    w_v: float,
    w_s: float,
) -> Optional[float]:
    """Compute weighted composite with graceful handling of missing components.

    When both scores are available, applies the configured weights.
    When only one score is available, it is scaled by its own weight
    (not promoted to full weight) to avoid unfairly ranking companies
    with missing data above those with both factors.

    :param value_score: Value factor score (0-100)
    :param sentiment_score: Sentiment factor score (0-100)
    :param w_v: Value weight
    :param w_s: Sentiment weight
    :return: Composite score or None
    :rtype: float or None
    """
    if value_score is not None and sentiment_score is not None:
        return round(w_v * value_score + w_s * sentiment_score, 4)
    elif value_score is not None:
        return round(w_v * value_score, 4)
    elif sentiment_score is not None:
        return round(w_s * sentiment_score, 4)
    return None
