"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Signal combination — composite score from value + sentiment
Project : CW2 - Value-Sentiment Investment Strategy

Combines the sector-relative value z-score and quality-weighted
sentiment score into a single composite using:

  Composite = 0.6 × Value_percentile + 0.4 × Sentiment_normalised

Scale alignment:
  - Value is z-score (−3 to +3) → converted to percentile rank [0, 100]
  - Sentiment is shrunk average (−1 to +1) → (final + 1)/2 × 100

Screening filters (updated from CW1):
  - Value score > 0 (above sector median)
  - Sentiment confidence > 0.3 (~2+ quality-weighted articles)
  - D/E < 2.0 (unchanged risk filter)
  - Top 20% of eligible → invest_decision = TRUE

Ref: Part A §A4
"""

import logging

import numpy as np
import pandas as pd
from scipy.stats import rankdata

logger = logging.getLogger(__name__)


class SignalCombiner:
    """Combine value and sentiment signals into composite scores.

    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, config: dict):
        self._value_weight = config['scoring']['value_weight']
        self._sentiment_weight = config['scoring']['sentiment_weight']
        self._max_de = config['scoring']['max_debt_equity']
        self._min_confidence = config['scoring']['min_sentiment_confidence']
        self._selection_pctl = config['scoring']['selection_percentile']

    def compute(
        self,
        value_signals: pd.DataFrame,
        sentiment_signals: pd.DataFrame,
        value_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute composite scores and flag investment decisions.

        Merges value and sentiment signals, applies scale alignment,
        screening filters, and flags the top quintile for investment.

        :param value_signals: DataFrame with company_id, value_score
        :type value_signals: pd.DataFrame
        :param sentiment_signals: DataFrame with company_id, sentiment_score, confidence
        :type sentiment_signals: pd.DataFrame
        :param value_df: DataFrame with company_id, debt_equity for filtering
        :type value_df: pd.DataFrame
        :returns: DataFrame with composite_score, rank, invest_decision per company
        :rtype: pd.DataFrame
        """
        # Merge all signals on company_id
        merged = value_signals[['company_id', 'value_score']].merge(
            sentiment_signals[['company_id', 'sentiment_score', 'confidence']],
            on='company_id',
            how='outer',
        )

        # Merge debt/equity for filtering
        de_cols = ['company_id', 'debt_equity'] if 'debt_equity' in value_df.columns else ['company_id']
        de_data = value_df[de_cols].copy()
        de_data['company_id'] = de_data['company_id'].str.strip()
        merged = merged.merge(de_data, on='company_id', how='left')

        # Scale alignment
        merged = self._align_scales(merged)

        # Compute weighted composite
        merged['composite_score'] = (
            self._value_weight * merged['value_pctl'] +
            self._sentiment_weight * merged['sentiment_norm']
        )

        # Apply screening filters
        merged = self._apply_screens(merged)

        # Rank by composite score (descending)
        valid = merged['composite_score'].notna()
        merged.loc[valid, 'rank'] = rankdata(
            -merged.loc[valid, 'composite_score'], method='ordinal'
        ).astype(int)

        # Flag top quintile as invest_decision = True
        merged = self._flag_investments(merged)

        invest_count = merged['invest_decision'].sum()
        logger.info(
            "Composite scoring: %d companies, %d eligible, %d flagged for investment",
            len(merged), merged['is_eligible'].sum(), invest_count,
        )
        return merged

    def _align_scales(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert value and sentiment to comparable 0–100 scales.

        Value z-score (−3 to +3) → percentile rank [0, 100]
        Sentiment (−1 to +1) → (x + 1) / 2 × 100 → [0, 100]

        :param df: Merged DataFrame with value_score and sentiment_score
        :type df: pd.DataFrame
        :returns: DataFrame with value_pctl and sentiment_norm columns
        :rtype: pd.DataFrame
        """
        # Value: convert z-score to percentile rank
        valid_value = df['value_score'].notna()
        df['value_pctl'] = np.nan
        if valid_value.sum() > 1:
            ranks = rankdata(df.loc[valid_value, 'value_score'], method='average')
            df.loc[valid_value, 'value_pctl'] = (ranks - 1) / (len(ranks) - 1) * 100

        # Sentiment: normalise from (-1, +1) to (0, 100)
        df['sentiment_norm'] = (df['sentiment_score'].fillna(0) + 1) / 2 * 100

        return df

    def _apply_screens(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply eligibility screening filters.

        Screens:
        1. Value score > 0 (above sector median)
        2. Sentiment confidence > min_confidence
        3. Debt/Equity < max_de

        :param df: DataFrame with all signal columns
        :type df: pd.DataFrame
        :returns: DataFrame with is_eligible column
        :rtype: pd.DataFrame
        """
        screen_value = df['value_score'].fillna(-999) > 0
        screen_confidence = df['confidence'].fillna(0) > self._min_confidence
        screen_de = (
            (df['debt_equity'].isna()) |
            (df['debt_equity'] <= self._max_de)
        )

        df['is_eligible'] = screen_value & screen_confidence & screen_de

        # Set composite to NaN for ineligible stocks
        df.loc[~df['is_eligible'], 'composite_score'] = np.nan

        logger.info(
            "Screening: %d passed value, %d passed confidence, %d passed D/E, %d total eligible",
            screen_value.sum(), screen_confidence.sum(), screen_de.sum(),
            df['is_eligible'].sum(),
        )
        return df

    def _flag_investments(self, df: pd.DataFrame) -> pd.DataFrame:
        """Flag top percentile of eligible stocks for investment.

        :param df: DataFrame with composite_score and is_eligible
        :type df: pd.DataFrame
        :returns: DataFrame with invest_decision column
        :rtype: pd.DataFrame
        """
        df['invest_decision'] = False
        eligible = df[df['is_eligible'] & df['composite_score'].notna()]

        if len(eligible) == 0:
            logger.warning("No eligible companies after screening")
            return df

        cutoff = max(1, int(len(eligible) * self._selection_pctl))
        top_indices = eligible.nsmallest(cutoff, 'rank').index
        df.loc[top_indices, 'invest_decision'] = True

        return df
