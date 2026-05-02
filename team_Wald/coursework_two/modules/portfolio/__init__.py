"""Portfolio construction layer for CW2.

Implements Part A §A5 of the master guide:

    * :class:`modules.portfolio.portfolio_constructor.PortfolioConstructor`
      — orchestrates screen → weight → constrain with a 60/40 percentile
      buffer rule for turnover reduction, plus dedicated value-only and
      sentiment-only variants.
    * :func:`modules.portfolio.constraints.apply_constraints` — iterative
      enforcement of the 5% per-stock and 25% per-sector caps with
      proportional excess redistribution.
    * :mod:`modules.portfolio.weighting` — three weighting schemes
      (equal-weight, score-weight, inverse-volatility).
"""

from modules.portfolio.constraints import apply_constraints
from modules.portfolio.portfolio_constructor import PortfolioConstructor
from modules.portfolio.weighting import (
    compute_equal_weight,
    compute_inverse_volatility_weight,
    compute_score_weight,
)

__all__ = [
    'PortfolioConstructor',
    'apply_constraints',
    'compute_equal_weight',
    'compute_score_weight',
    'compute_inverse_volatility_weight',
]
