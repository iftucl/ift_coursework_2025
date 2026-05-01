"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Unit tests for SignalCombiner (composite + screening)
Project : CW2 - Value-Sentiment Investment Strategy

Tests the composite-score formula (0.6 × value_pctl + 0.4 × sentiment_norm),
scale alignment between the value z-score and sentiment normalisation,
and the three screening filters (value > 0, confidence > 0.3, D/E < 2.0)
plus the top-quintile invest_decision flag.

Coverage target: 85%+
"""

import numpy as np
import pandas as pd
import pytest

from modules.signals.signal_combiner import SignalCombiner


@pytest.fixture
def value_signals():
    return pd.DataFrame({
        'company_id': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'],
        'value_score': [2.5, 1.5, 0.5, -0.5, -1.5,
                        2.0, 1.0, 0.0, -1.0, -2.0],
    })


@pytest.fixture
def sentiment_signals():
    return pd.DataFrame({
        'company_id': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'],
        'sentiment_score': [0.6, 0.4, 0.2, 0.0, -0.2,
                            0.5, 0.3, 0.1, -0.1, -0.3],
        'confidence': [0.9, 0.8, 0.7, 0.6, 0.5,
                       0.4, 0.35, 0.32, 0.20, 0.10],
    })


@pytest.fixture
def value_df():
    return pd.DataFrame({
        'company_id': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'],
        'debt_equity': [0.5, 1.0, 1.5, 1.8, 2.5, 0.3, 0.8, 1.2, 1.6, 3.0],
    })


class TestSignalCombiner:

    def test_composite_score_present(self, base_config, value_signals, sentiment_signals, value_df):
        combiner = SignalCombiner(base_config)
        result = combiner.compute(value_signals, sentiment_signals, value_df)
        assert 'composite_score' in result.columns
        assert 'invest_decision' in result.columns
        assert 'is_eligible' in result.columns

    def test_screening_excludes_negative_value(self, base_config, value_signals, sentiment_signals, value_df):
        combiner = SignalCombiner(base_config)
        result = combiner.compute(value_signals, sentiment_signals, value_df)
        # Stocks with value_score <= 0 must not be eligible
        ineligible_neg_value = result[result['value_score'] <= 0]
        assert (~ineligible_neg_value['is_eligible']).all()

    def test_screening_excludes_low_confidence(self, base_config, value_signals, sentiment_signals, value_df):
        combiner = SignalCombiner(base_config)
        result = combiner.compute(value_signals, sentiment_signals, value_df)
        # Confidence threshold defaults to 0.3
        too_low = result[result['confidence'] <= 0.3]
        assert (~too_low['is_eligible']).all()

    def test_screening_excludes_high_debt_equity(self, base_config, value_signals, sentiment_signals, value_df):
        combiner = SignalCombiner(base_config)
        result = combiner.compute(value_signals, sentiment_signals, value_df)
        too_levered = result[result['debt_equity'] > 2.0]
        assert (~too_levered['is_eligible']).all()

    def test_invest_decision_top_quintile(self, base_config, value_signals, sentiment_signals, value_df):
        combiner = SignalCombiner(base_config)
        result = combiner.compute(value_signals, sentiment_signals, value_df)
        invest_count = result['invest_decision'].sum()
        eligible_count = result['is_eligible'].sum()
        # Top 20% should be flagged for investment (with floor of 1)
        if eligible_count >= 5:
            assert invest_count == max(1, int(eligible_count * 0.20))
        else:
            assert invest_count <= eligible_count

    def test_weighting_six_four(self, base_config, value_signals, sentiment_signals, value_df):
        """Composite must equal 0.6×value_pctl + 0.4×sentiment_norm."""
        combiner = SignalCombiner(base_config)
        result = combiner.compute(value_signals, sentiment_signals, value_df).dropna(subset=['composite_score'])
        # Reconstruct expected composite for one ID
        if len(result) == 0:
            pytest.skip("No eligible rows for composite reconstruction")
        row = result.iloc[0]
        expected = 0.6 * row['value_pctl'] + 0.4 * row['sentiment_norm']
        assert abs(row['composite_score'] - expected) < 1e-8

    def test_value_pctl_in_range(self, base_config, value_signals, sentiment_signals, value_df):
        combiner = SignalCombiner(base_config)
        result = combiner.compute(value_signals, sentiment_signals, value_df)
        valid = result['value_pctl'].dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_sentiment_norm_in_range(self, base_config, value_signals, sentiment_signals, value_df):
        combiner = SignalCombiner(base_config)
        result = combiner.compute(value_signals, sentiment_signals, value_df)
        # (-1, +1) → (0, 100)
        assert (result['sentiment_norm'] >= 0).all()
        assert (result['sentiment_norm'] <= 100).all()
