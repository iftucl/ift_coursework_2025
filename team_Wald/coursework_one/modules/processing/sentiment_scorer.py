"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : VADER sentiment analysis for news articles
Project : CW1 - Value + News Sentiment Strategy

Applies the VADER (Valence Aware Dictionary and sEntiment Reasoner)
lexicon-based sentiment analyser to news headlines and descriptions,
then aggregates per-article scores into a company-level Sentiment Score.

VADER is specifically designed for social media and short-form text,
making it well-suited for news headlines.  It outputs:
  - positive: proportion of positive sentiment
  - negative: proportion of negative sentiment
  - neutral:  proportion of neutral sentiment
  - compound: normalised composite score (-1 to +1)

Company-level aggregation:
  1. Score each article's headline + description with VADER compound score
  2. Classify: compound >= 0.05 → positive, <= -0.05 → negative, else neutral
  3. Deduplicate articles by headline before aggregation
  4. Compute average compound score across all articles
  5. Compute positive ratio = positive_count / total_articles
  6. Compute Sentiment Score using weighted formula:
       sentiment_score = (avg_compound_normalised × 0.5)
                       + (positive_ratio × 0.3)
                       + (volume_factor × 0.2)
     Where:
       avg_compound_normalised = (avg_compound + 1) / 2 × 100
       positive_ratio_pct      = positive_count / total × 100
       volume_factor           = min(article_count / 20, 1.0) × 100

Academic references:
  - Hutto, C.J. & Gilbert, E. (2014), "VADER: A Parsimonious Rule-based
    Model for Sentiment Analysis of Social Media Text", AAAI ICWSM.
  - Tetlock, P.C. (2007), "Giving Content to Investor Sentiment", JF.
  - Baker, M. & Wurgler, J. (2006), "Investor Sentiment and the
    Cross-Section of Stock Returns", JF.
"""

from datetime import date

from modules.utils.logger import pipeline_logger

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    VADER_AVAILABLE = True
except ImportError:
    SentimentIntensityAnalyzer = None
    VADER_AVAILABLE = False


def get_analyser():
    """Create and return a VADER SentimentIntensityAnalyzer.

    :return: VADER analyser or None if not installed
    :rtype: SentimentIntensityAnalyzer or None
    """
    if not VADER_AVAILABLE:
        pipeline_logger.warning("vaderSentiment not installed — sentiment disabled")
        return None
    return SentimentIntensityAnalyzer()


def score_text(analyser, text: str) -> dict:
    """Score a single text string using VADER.

    :param analyser: Initialised VADER analyser
    :param text: Text to analyse (headline, description, or combined)
    :type text: str
    :return: Dict with compound, pos, neg, neu scores
    :rtype: dict

    Example::

        >>> a = get_analyser()
        >>> result = score_text(a, 'Apple posts record quarterly revenue')
        >>> result['compound'] > 0
        True
    """
    if analyser is None or not text or not text.strip():
        return {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}
    scores = analyser.polarity_scores(text)
    return {
        "compound": scores["compound"],
        "pos": scores["pos"],
        "neg": scores["neg"],
        "neu": scores["neu"],
    }


def score_headline(analyser, headline: str) -> dict:
    """Score a single headline using VADER (backward-compatible alias).

    :param analyser: Initialised VADER analyser
    :param headline: News headline text
    :type headline: str
    :return: Dict with compound, pos, neg, neu scores
    :rtype: dict
    """
    return score_text(analyser, headline)


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """Remove duplicate articles based on headline text.

    Addresses the data quality requirement: "Duplicate articles —
    Same headline appears twice → Deduplicate before scoring."

    :param articles: List of article dicts
    :type articles: list[dict]
    :return: Deduplicated list (preserves first occurrence)
    :rtype: list[dict]
    """
    seen_headlines = set()
    unique = []
    for article in articles:
        headline = (article.get("headline") or "").strip().lower()
        if headline and headline not in seen_headlines:
            seen_headlines.add(headline)
            unique.append(article)
        elif not headline:
            unique.append(article)
    removed = len(articles) - len(unique)
    if removed > 0:
        pipeline_logger.info("Deduplicated %d duplicate articles", removed)
    return unique


def score_articles(analyser, articles: list[dict]) -> list[dict]:
    """Score all articles for a single company.

    Analyses both headline and description per the specification
    (Issue 6: "Runs VADER sentiment analysis on headline + description").
    Adds VADER scores to each article dict in-place and returns
    the enriched list.

    :param analyser: Initialised VADER analyser
    :param articles: List of article dicts with 'headline' field
    :type articles: list[dict]
    :return: Articles enriched with 'vader_compound', 'vader_pos', etc.
    :rtype: list[dict]
    """
    for article in articles:
        headline = article.get("headline", "")
        description = article.get("description", "")
        combined_text = f"{headline}. {description}".strip() if description else headline
        scores = score_text(analyser, combined_text)
        article["vader_compound"] = scores["compound"]
        article["vader_pos"] = scores["pos"]
        article["vader_neg"] = scores["neg"]
        article["vader_neu"] = scores["neu"]
        # Classify using standard VADER thresholds
        compound = scores["compound"]
        if compound >= 0.05:
            article["sentiment_class"] = "positive"
        elif compound <= -0.05:
            article["sentiment_class"] = "negative"
        else:
            article["sentiment_class"] = "neutral"
    return articles


def aggregate_sentiment(
    company_id: str,
    scored_articles: list[dict],
    score_date: date = None,
) -> dict:
    """Aggregate article-level scores into a company Sentiment Score.

    :param company_id: Company ticker symbol
    :type company_id: str
    :param scored_articles: Articles with VADER scores
    :type scored_articles: list[dict]
    :param score_date: Date for the aggregate score
    :type score_date: date or None
    :return: Aggregated sentiment record for PostgreSQL
    :rtype: dict

    Example::

        >>> a = get_analyser()
        >>> arts = score_articles(a, [{'headline': 'Revenue up 20%'}])
        >>> agg = aggregate_sentiment('AAPL', arts)
        >>> agg['total_articles']
        1
    """
    if score_date is None:
        score_date = date.today()

    total = len(scored_articles)
    if total == 0:
        return {
            "company_id": company_id,
            "date": score_date.strftime("%Y-%m-%d"),
            "avg_sentiment": None,
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "total_articles": 0,
            "positive_ratio": None,
            "sentiment_score": None,
        }

    compounds = [a.get("vader_compound", 0.0) for a in scored_articles]
    positive_count = sum(1 for a in scored_articles if a.get("sentiment_class") == "positive")
    negative_count = sum(1 for a in scored_articles if a.get("sentiment_class") == "negative")
    neutral_count = total - positive_count - negative_count

    avg_compound = sum(compounds) / total
    positive_ratio = positive_count / total

    # Weighted sentiment score formula (per role_instructions specification):
    #   sentiment_score = (avg_compound_normalised × 0.5)
    #                   + (positive_ratio_pct × 0.3)
    #                   + (volume_factor × 0.2)
    avg_compound_normalised = (avg_compound + 1.0) / 2.0 * 100.0
    positive_ratio_pct = positive_ratio * 100.0
    volume_factor = min(total / 20.0, 1.0) * 100.0
    sentiment_score = avg_compound_normalised * 0.5 + positive_ratio_pct * 0.3 + volume_factor * 0.2

    return {
        "company_id": company_id,
        "date": score_date.strftime("%Y-%m-%d"),
        "avg_sentiment": round(avg_compound, 4),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
        "total_articles": total,
        "positive_ratio": round(positive_ratio, 4),
        "sentiment_score": round(sentiment_score, 4),
    }


def compute_all_sentiment(
    all_articles: dict,
    score_date: date = None,
) -> list[dict]:
    """Compute VADER sentiment scores for every company in the universe.

    :param all_articles: Dict mapping ticker → list of article dicts
    :type all_articles: dict
    :param score_date: Date for all scores
    :type score_date: date or None
    :return: List of aggregated sentiment records
    :rtype: list[dict]

    Example::

        >>> articles = {'AAPL': [{'headline': 'Apple beats earnings'}]}
        >>> results = compute_all_sentiment(articles)
        >>> results[0]['company_id']
        'AAPL'
    """
    analyser = get_analyser()
    results = []
    for ticker, articles in all_articles.items():
        unique_articles = deduplicate_articles(articles)
        scored = score_articles(analyser, unique_articles)
        agg = aggregate_sentiment(ticker, scored, score_date)
        results.append(agg)

    scored_count = sum(1 for r in results if r["sentiment_score"] is not None)
    pipeline_logger.info("Computed sentiment for %d companies (%d with scores)", len(results), scored_count)
    return results
