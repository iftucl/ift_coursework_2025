"""Signal-construction layer for CW2.

Implements the two CW1 → CW2 upgrades documented in Part A §A2 / §A3:

    * :class:`modules.signals.value_signal.ValueSignal` — the MSCI
      Enhanced Value 4-stage pipeline (flip → winsorize → cross-sectional
      z → within-sector restandardisation → cap & Bayesian shrinkage),
      replacing CW1's cross-sectional percentile rank.
    * :class:`modules.signals.sentiment_signal.SentimentSignal` —
      4-component quality-weighted VADER aggregation
      (source × relevance × recency × length) with consistency multiplier
      and Bayesian shrinkage, replacing CW1's volume-weighted scoring.
    * :class:`modules.signals.signal_combiner.SignalCombiner` — composite
      ``0.6 × value_pctl + 0.4 × sentiment_norm`` with the screening
      filters (value > 0, sentiment confidence > 0.3, D/E < 2.0, top 20%).
"""

from modules.signals.sentiment_signal import SentimentSignal
from modules.signals.signal_combiner import SignalCombiner
from modules.signals.value_signal import ValueSignal

__all__ = ['ValueSignal', 'SentimentSignal', 'SignalCombiner']
