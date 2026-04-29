"""Analytics layer for CW2.

Implements Part A §A7 of the master guide:

    * :mod:`modules.analytics.performance` — annualised return /
      volatility, Sharpe (Lo 2002), Sortino, Calmar, Information Ratio,
      max drawdown, drawdown series, monthly heatmap, top-N drawdowns.
    * :mod:`modules.analytics.risk` — historical VaR/CVaR (95% / 99%) and
      Fama-French 5-factor regression with Newey-West HAC SEs (6 lags).
    * :mod:`modules.analytics.turnover` — per-rebalance and aggregate
      one-way turnover plus cumulative cost impact.
    * :mod:`modules.analytics.diversification` — HHI, effective N,
      sector concentration, time-series diversification.
    * :mod:`modules.analytics.pitfalls` — Part C §C2 Table 11 generator
      that audits every classic backtesting pitfall against the
      mitigation actually present in this codebase.
"""

from modules.analytics.appendices import (
    build_code_quality_summary,
    build_config_dump,
    build_data_quality_summary,
    write_all_appendices,
)
from modules.analytics.diversification import (
    compute_diversification_metrics,
    compute_diversification_over_time,
    compute_sector_allocation,
)
from modules.analytics.performance import (
    compute_cumulative_returns,
    compute_drawdown_series,
    compute_monthly_returns,
    compute_performance_summary,
    compute_rolling_sharpe,
    compute_top_drawdowns,
)
from modules.analytics.pitfalls import build_pitfalls_table
from modules.analytics.risk import (
    compute_cvar,
    compute_fama_french_regression,
    compute_var,
)
from modules.analytics.turnover import (
    compute_turnover_per_rebalance,
    compute_turnover_summary,
)

__all__ = [
    'compute_performance_summary',
    'compute_drawdown_series',
    'compute_cumulative_returns',
    'compute_rolling_sharpe',
    'compute_monthly_returns',
    'compute_top_drawdowns',
    'compute_var',
    'compute_cvar',
    'compute_fama_french_regression',
    'compute_turnover_summary',
    'compute_turnover_per_rebalance',
    'compute_diversification_metrics',
    'compute_diversification_over_time',
    'compute_sector_allocation',
    'build_pitfalls_table',
    'build_data_quality_summary',
    'build_code_quality_summary',
    'build_config_dump',
    'write_all_appendices',
]
