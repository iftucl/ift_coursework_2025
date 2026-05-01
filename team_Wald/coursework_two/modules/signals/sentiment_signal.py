"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Quality-weighted sentiment scoring
Project : CW2 - Value-Sentiment Investment Strategy

UPGRADE from CW1: Replaces volume-weighted sentiment aggregation
(volume_factor = min(count/20, 1)) with a 4-component quality
weighting system.

Problem: CW1's volume_factor rewards noise — 50 wire copies of the
same press release count as 50× more signal.  Tetlock (2011): stale
reprints degrade signal quality.

Solution — 4-Component Quality Weight:
  w_i = w_source × w_relevance × w_recency × w_length

  Component        Method                                  Range
  Source credibility  Tier lookup (Reuters=1.0, SeekingAlpha=0.4)  0.3–1.0
  Relevance          Company in headline +0.5, body +0.3          0–1.0
  Recency            Exponential decay: e^(-ln2/7 × days_old)    0–1.0
  Substantiveness    min(word_count/500, 1.0)                    0–1.0

Aggregation: S = Sum(w_i × VADER_i) / Sum(w_i)
Consistency multiplier: c = max(0, 1 - 2 × std)
Bayesian shrinkage: S_final = (n × S_adj) / (n + k)
Confidence = n / (n + k)

Ref: Part A §A3
"""

import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SentimentSignal:
    """Compute quality-weighted sentiment scores.

    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, config: dict):
        self._half_life = config['sentiment']['half_life_days']
        self._source_tiers = config['sentiment']['source_tiers']
        self._tier_weights = config['sentiment']['tier_weights']
        self._shrinkage_k = config['scoring']['shrinkage_k_sentiment']
        self._min_confidence = config['scoring']['min_sentiment_confidence']

        # Build source → weight lookup from tier config
        self._source_weight_map = {}
        for tier_name, domains in self._source_tiers.items():
            weight = self._tier_weights.get(tier_name, self._tier_weights['default'])
            for domain in domains:
                self._source_weight_map[domain] = weight

    def compute(
        self,
        sentiment_df: pd.DataFrame,
        rebalance_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """Compute quality-weighted sentiment scores for all companies.

        Detection logic:
          - If sentiment_df contains 'headline', 'source_domain', 'word_count'
            columns → article-level data from MongoDB → apply full 4-component
            quality weighting (source × relevance × recency × length).
          - Otherwise → aggregated CW1 data from PostgreSQL → apply Bayesian
            shrinkage and consistency adjustment to existing scores.

        :param sentiment_df: Sentiment data (article-level or aggregated)
        :type sentiment_df: pd.DataFrame
        :param rebalance_date: Current rebalance date for recency calc
        :type rebalance_date: pd.Timestamp
        :returns: DataFrame with company_id, sentiment_score, confidence
        :rtype: pd.DataFrame
        """
        # Detect data format: article-level vs aggregated
        is_article_level = (
            'headline' in sentiment_df.columns and
            'source_domain' in sentiment_df.columns
        )

        if is_article_level and len(sentiment_df) > 0:
            logger.info("Using article-level 4-component quality weighting")
            df = self._compute_article_level_sentiment(sentiment_df, rebalance_date)
        else:
            logger.info("Using aggregated sentiment with quality approximation")
            df = sentiment_df.copy()
            if 'company_id' in df.columns:
                df = df.set_index('company_id')
            df = self._compute_quality_adjusted_sentiment(df, rebalance_date)
            df = self._apply_consistency_multiplier(df)
            df = self._apply_bayesian_shrinkage(df)

        result = df[['final_sentiment', 'confidence']].reset_index()
        result.rename(columns={
            'index': 'company_id',
            'final_sentiment': 'sentiment_score',
        }, inplace=True)
        if result.columns[0] != 'company_id':
            result = result.rename(columns={result.columns[0]: 'company_id'})

        scored = result['sentiment_score'].notna().sum()
        logger.info(
            "Quality-weighted sentiment: %d/%d companies scored (%.1f%% with confidence > %.2f)",
            scored, len(result),
            (result['confidence'] > self._min_confidence).mean() * 100 if len(result) > 0 else 0,
            self._min_confidence,
        )
        return result

    def _compute_article_level_sentiment(
        self,
        articles_df: pd.DataFrame,
        rebalance_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """Apply full 4-component quality weighting at article level.

        For each article, computes:
          w_i = w_source × w_relevance × w_recency × w_length

        Then aggregates per company:
          S = Sum(w_i × VADER_i) / Sum(w_i)
          consistency = max(0, 1 - 2 × weighted_std)
          S_final = (n × S × consistency) / (n + k)

        :param articles_df: Article-level DataFrame from MongoDB with columns:
                            company_id, headline, source_domain, word_count,
                            article_date, vader_compound
        :type articles_df: pd.DataFrame
        :param rebalance_date: Current rebalance date
        :type rebalance_date: pd.Timestamp
        :returns: DataFrame indexed by company_id with final_sentiment, confidence
        :rtype: pd.DataFrame
        """
        df = articles_df.copy()

        # --- Component 1: Source credibility (0.3–1.0) ---
        df['w_source'] = df['source_domain'].apply(self._get_source_weight)

        # --- Component 2: Relevance (0–1.0), per Part A §A3 ----------
        # Per the master guide: +0.5 when the company name is in the
        # headline, +0.3 when it is mentioned in the body
        # (description), +0.2 when the article is at least 500 words
        # long (a substantive long-form piece).
        #
        # Matching is performed against (a) the company_name field if
        # CW1 propagated it, and (b) the ticker symbol as a fallback,
        # so that wire-only stories with no company name still get
        # credit when they explicitly reference the ticker.
        df['w_relevance'] = self._compute_relevance(df)

        # --- Component 3: Recency decay (0–1.0) ---
        # e^(-ln2/half_life × days_old), 7-day half-life
        if 'article_date' in df.columns:
            df['days_old'] = (rebalance_date - pd.to_datetime(df['article_date'])).dt.days.clip(lower=0)
        else:
            df['days_old'] = 0
        decay_rate = math.log(2) / self._half_life
        df['w_recency'] = np.exp(-decay_rate * df['days_old'])

        # --- Component 4: Substantiveness (0–1.0) ---
        # min(word_count / 500, 1.0)
        wc = df['word_count'].fillna(0).astype(float)
        df['w_length'] = (wc / 500.0).clip(upper=1.0)

        # --- Composite quality weight ---
        df['w_quality'] = df['w_source'] * df['w_relevance'] * df['w_recency'] * df['w_length']

        # --- VADER compound score ---
        # If vader_compound is available from CW1 scoring, use it
        # Otherwise score the headline (requires vaderSentiment)
        if 'vader_compound' not in df.columns or df['vader_compound'].isna().all():
            df['vader_compound'] = self._score_headlines(df['headline'])

        # --- Aggregate per company ---
        def _aggregate_company(group):
            w = group['w_quality'].values
            v = group['vader_compound'].fillna(0).values
            n = len(group)

            if w.sum() == 0:
                return pd.Series({
                    'final_sentiment': 0.0,
                    'confidence': 0.0,
                })

            # Weighted average sentiment
            weighted_sent = np.average(v, weights=w)

            # Weighted standard deviation for consistency
            weighted_var = np.average((v - weighted_sent) ** 2, weights=w)
            weighted_std = np.sqrt(weighted_var) if weighted_var > 0 else 0.0

            # Consistency multiplier: c = max(0, 1 - 2 × std)
            consistency = max(0.0, 1.0 - 2.0 * weighted_std)

            # Bayesian shrinkage: S_final = (n × S × c) / (n + k)
            k = float(self._shrinkage_k)
            final_sent = (n * weighted_sent * consistency) / (n + k)
            confidence = n / (n + k)

            return pd.Series({
                'final_sentiment': final_sent,
                'confidence': confidence,
            })

        result = df.groupby('company_id').apply(_aggregate_company, include_groups=False)

        logger.info(
            "Article-level aggregation: %d companies, avg %.1f articles/company",
            len(result), df.groupby('company_id').size().mean(),
        )
        return result

    @staticmethod
    def _compute_relevance(df: pd.DataFrame) -> pd.Series:
        """Compute the per-article relevance weight (Part A §A3).

        Implements the additive scheme from the master guide literally:

            +0.5  if the company name (or ticker) appears in the headline
            +0.3  if the company name (or ticker) appears in the body
                  (description / summary text)
            +0.2  if the article is at least 500 words long

        Articles with none of those signals get a small floor weight
        (0.05) so the component never collapses to zero — without that
        floor, multiplying through ``w_source × w_relevance × ...``
        would zero out every weight for sources that publish only
        short wire copy.

        Matching is case-insensitive and uses both ``company_name``
        (from CW1's MongoDB document, propagated through
        :meth:`modules.data.data_loader.DataLoader._normalise_articles`)
        and ``company_id`` (the ticker) so that wire stories without a
        company-name field still get credit.

        :param df: Article-level DataFrame with ``headline``,
                   ``description``, ``word_count`` and at least one of
                   ``company_name`` / ``company_id``
        :type df: pd.DataFrame
        :returns: Relevance weight per article, clipped to [0.05, 1.0]
        :rtype: pd.Series
        """
        # Prepare lower-case search corpora
        headlines = df.get('headline', pd.Series([''] * len(df), index=df.index))
        bodies = df.get('description', pd.Series([''] * len(df), index=df.index))
        headlines = headlines.fillna('').astype(str).str.lower()
        bodies = bodies.fillna('').astype(str).str.lower()

        # Build the per-row "needles" we will look for. Prefer the
        # human-readable company_name; always include the ticker as a
        # fallback so cross-references like "AAPL" still match.
        names = (
            df.get('company_name', pd.Series([''] * len(df), index=df.index))
            .fillna('').astype(str).str.lower()
        )
        tickers = (
            df.get('company_id', pd.Series([''] * len(df), index=df.index))
            .fillna('').astype(str).str.lower()
        )

        def _contains_any(text: str, name: str, ticker: str) -> bool:
            """True if ``name`` or ``ticker`` appears in ``text``."""
            if not text:
                return False
            if name and len(name) >= 2 and name in text:
                return True
            if ticker and len(ticker) >= 2 and ticker in text:
                return True
            return False

        in_headline = pd.Series(
            [_contains_any(h, n, t) for h, n, t in zip(headlines, names, tickers)],
            index=df.index,
        )
        in_body = pd.Series(
            [_contains_any(b, n, t) for b, n, t in zip(bodies, names, tickers)],
            index=df.index,
        )

        # Word-count threshold for the +0.2 substantive bonus
        wc = df.get('word_count', pd.Series([0] * len(df), index=df.index))
        wc = pd.to_numeric(wc, errors='coerce').fillna(0).astype(float)
        is_long = wc >= 500

        relevance = (
            0.5 * in_headline.astype(float)
            + 0.3 * in_body.astype(float)
            + 0.2 * is_long.astype(float)
        )
        # Floor at 0.05 so all-miss articles still get a tiny weight
        relevance = relevance.clip(lower=0.05, upper=1.0)
        return relevance

    def _get_source_weight(self, domain: str) -> float:
        """Look up source credibility weight from tier configuration.

        :param domain: Source domain string (e.g. 'reuters.com')
        :type domain: str
        :returns: Credibility weight (0.3–1.0)
        :rtype: float
        """
        if not domain or not isinstance(domain, str):
            return self._tier_weights.get('default', 0.3)

        domain_lower = domain.lower().strip()
        # Check exact match first
        if domain_lower in self._source_weight_map:
            return self._source_weight_map[domain_lower]
        # Check partial match (e.g. 'reuters.com' in 'www.reuters.com')
        for known_domain, weight in self._source_weight_map.items():
            if known_domain in domain_lower:
                return weight
        return self._tier_weights.get('default', 0.3)

    def _score_headlines(self, headlines: pd.Series) -> pd.Series:
        """Score headlines with VADER if compound scores not available.

        :param headlines: Series of headline strings
        :type headlines: pd.Series
        :returns: Series of VADER compound scores
        :rtype: pd.Series
        """
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            analyser = SentimentIntensityAnalyzer()
            return headlines.fillna('').apply(
                lambda h: analyser.polarity_scores(h)['compound'] if h else 0.0
            )
        except ImportError:
            logger.warning("vaderSentiment not available — using zero scores")
            return pd.Series(0.0, index=headlines.index)

    def _compute_quality_adjusted_sentiment(
        self,
        df: pd.DataFrame,
        rebalance_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """Apply quality adjustments to CW1 aggregated sentiment data.

        Since CW1 stores aggregated sentiment scores (not article-level),
        we enhance the signal using:
        1. Article count → quality proxy (more articles = more reliable)
        2. Recency decay based on score date vs rebalance date
        3. Positive ratio → consistency indicator

        In a full implementation with MongoDB article-level data, the
        4-component quality weight (source × relevance × recency × length)
        would be applied per article before aggregation.

        :param df: CW1 sentiment DataFrame indexed by company_id
        :type df: pd.DataFrame
        :param rebalance_date: Current rebalance date
        :type rebalance_date: pd.Timestamp
        :returns: DataFrame with adjusted_sentiment column
        :rtype: pd.DataFrame
        """
        # Base sentiment: avg_sentiment from VADER compound (-1 to +1)
        df['base_sentiment'] = df['avg_sentiment'].astype(float).fillna(0.0)

        # Recency decay: penalise stale sentiment data
        if 'date' in df.columns:
            df['days_old'] = (rebalance_date - pd.to_datetime(df['date'])).dt.days
            decay_rate = math.log(2) / self._half_life
            df['recency_weight'] = np.exp(-decay_rate * df['days_old'].clip(lower=0))
        else:
            df['recency_weight'] = 1.0

        # Source quality proxy: use positive_ratio as consistency signal
        # Higher positive ratio + higher article count = more reliable
        df['quality_proxy'] = np.where(
            df['total_articles'] > 0,
            np.minimum(df['total_articles'] / 10.0, 1.0),  # Saturates at 10 articles
            0.0,
        )

        # Quality-adjusted sentiment
        df['adjusted_sentiment'] = (
            df['base_sentiment'] * df['recency_weight'] * df['quality_proxy']
        )

        return df

    def _apply_consistency_multiplier(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply consistency multiplier to penalise mixed-signal stocks.

        If a company has both strongly positive and negative articles,
        the standard deviation of sentiment will be high, reducing
        the multiplier.

        Consistency: c = max(0, 1 - 2 × std)

        Since CW1 stores only aggregated metrics, we approximate
        sentiment standard deviation from positive/negative ratios.

        :param df: DataFrame with adjusted_sentiment column
        :type df: pd.DataFrame
        :returns: DataFrame with consistency column
        :rtype: pd.DataFrame
        """
        # Approximate std from positive/negative split
        # If all articles are positive or all negative, std ≈ 0 → consistency ≈ 1
        # If 50/50 split, std is high → consistency drops
        pos_ratio = df['positive_ratio'].astype(float).fillna(0.5)

        # Binary entropy as proxy for dispersion: highest at p=0.5
        # This maps to an approximate compound std
        estimated_std = (pos_ratio * (1 - pos_ratio)).apply(np.sqrt)  # Bernoulli std

        df['consistency'] = (1 - 2 * estimated_std).clip(lower=0)
        df['consistent_sentiment'] = df['adjusted_sentiment'] * df['consistency']

        logger.info(
            "Consistency multiplier: mean=%.3f, min=%.3f, max=%.3f",
            df['consistency'].mean(), df['consistency'].min(), df['consistency'].max(),
        )
        return df

    def _apply_bayesian_shrinkage(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply Bayesian shrinkage toward zero for low-coverage stocks.

        S_final = (n × S_adj) / (n + k)
        Confidence = n / (n + k)

        Where n = total_articles and k = shrinkage_k (default 5).
        Stocks with few articles are pulled toward zero (no opinion),
        reducing false signals from sparse data.

        :param df: DataFrame with consistent_sentiment column
        :type df: pd.DataFrame
        :returns: DataFrame with final_sentiment and confidence columns
        :rtype: pd.DataFrame
        """
        n = df['total_articles'].fillna(0).astype(float)
        k = float(self._shrinkage_k)

        df['confidence'] = n / (n + k)
        df['final_sentiment'] = (
            n * df['consistent_sentiment'] / (n + k)
        )

        # Replace NaN/inf with 0
        df['final_sentiment'] = df['final_sentiment'].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        df['confidence'] = df['confidence'].fillna(0.0)

        logger.info(
            "Bayesian shrinkage (k=%d): mean confidence=%.3f, %d with confidence > %.2f",
            int(k), df['confidence'].mean(),
            (df['confidence'] > self._min_confidence).sum(),
            self._min_confidence,
        )
        return df
