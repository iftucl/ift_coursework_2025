"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Sentiment Analyzer — VADER-based news sentiment scoring
Project : CW1 - Value + News Sentiment Strategy

This module provides the sentiment analysis interface required by Issue 6
(Task 5.2).  It re-exports all functionality from ``sentiment_scorer.py``
using the naming convention specified in the project structure.

Key functions:
  - ``analyze_single_article(headline, description)`` — per-article VADER scoring
  - ``analyze_company_articles(company_id, articles)`` — per-company aggregation
  - ``compute_sentiment_score(avg_sentiment, positive_ratio, article_count)``
  - ``process_all_companies(all_articles, score_date)`` — batch processing

Sentiment Score formula::

    sentiment_score = (avg_compound_normalised * 0.5)
                    + (positive_ratio * 0.3)
                    + (volume_factor * 0.2)

Where:
  - avg_compound_normalised = (avg_compound + 1) / 2 * 100
  - positive_ratio = positive_count / total_count * 100
  - volume_factor = min(article_count / 20, 1.0) * 100

Academic references:
  - Hutto & Gilbert (2014), "VADER: A Parsimonious Rule-based Model for
    Sentiment Analysis of Social Media Text"
  - Tetlock (2007), "Giving Content to Investor Sentiment"
  - Baker & Wurgler (2006), "Investor Sentiment and the Cross-Section of
    Stock Returns"
"""

# Re-export all public functions from the implementation module
from modules.processing.sentiment_scorer import (  # noqa: F401
    aggregate_sentiment,
    compute_all_sentiment,
    deduplicate_articles,
    get_analyser,
    score_articles,
)


def analyze_single_article(headline: str, description: str = "") -> dict:
    """Run VADER sentiment analysis on a single article.

    :param headline: Article headline text
    :type headline: str
    :param description: Article description/summary text
    :type description: str
    :return: Dict with compound, pos, neg, neu scores and classification
    :rtype: dict
    """
    analyser = get_analyser()
    text = f"{headline}. {description}" if description else headline
    scores = analyser.polarity_scores(text)
    compound = scores["compound"]
    classification = "positive" if compound >= 0.05 else ("negative" if compound <= -0.05 else "neutral")
    return {
        "headline": headline,
        "compound": compound,
        "positive": scores["pos"],
        "negative": scores["neg"],
        "neutral": scores["neu"],
        "classification": classification,
    }


def analyze_company_articles(company_id: str, articles: list[dict]) -> dict:
    """Analyse all articles for a company and return aggregated sentiment.

    :param company_id: Company ticker symbol
    :type company_id: str
    :param articles: List of article dicts with headline and description
    :type articles: list[dict]
    :return: Dict with avg_sentiment, positive_ratio, article_count
    :rtype: dict
    """
    analyser = get_analyser()
    unique = deduplicate_articles(articles)
    scored = score_articles(analyser, unique)
    return aggregate_sentiment(company_id, scored)


def compute_sentiment_score(avg_sentiment: float, positive_ratio: float, article_count: int) -> float:
    """Compute the weighted Sentiment Score.

    :param avg_sentiment: Average VADER compound score (-1 to +1)
    :type avg_sentiment: float
    :param positive_ratio: Fraction of positive articles (0 to 1)
    :type positive_ratio: float
    :param article_count: Total number of articles
    :type article_count: int
    :return: Weighted sentiment score (0 to 100)
    :rtype: float
    """
    avg_norm = (avg_sentiment + 1) / 2 * 100
    pos_pct = positive_ratio * 100
    vol_factor = min(article_count / 20, 1.0) * 100
    return avg_norm * 0.5 + pos_pct * 0.3 + vol_factor * 0.2


def process_all_companies(all_articles: dict, score_date=None) -> list[dict]:
    """Process all companies' articles and return sentiment records.

    :param all_articles: Dict mapping ticker to list of article dicts
    :type all_articles: dict
    :param score_date: Date for the sentiment records
    :type score_date: date or None
    :return: List of sentiment score records for PostgreSQL
    :rtype: list[dict]
    """
    return compute_all_sentiment(all_articles, score_date)
