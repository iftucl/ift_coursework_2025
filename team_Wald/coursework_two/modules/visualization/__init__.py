"""Visualization layer for CW2.

Implements all 14 charts (12 mandatory from Part C §C1 + 2 sophistication
upgrades — diversification over time and cost-impact drag) plus the
QuantStats HTML tearsheet for Appendix D.

Mandatory charts (Part C §C1):

    1. :func:`modules.visualization.charts.plot_cumulative_returns` —
       cumulative-return curves (4 portfolios + benchmark, log scale).
    2. :func:`modules.visualization.charts.plot_drawdown` — underwater
       drawdown chart for the combined portfolio.
    3. :func:`modules.visualization.charts.plot_monthly_heatmap` — 12 ×
       N-year monthly returns heatmap.
    4. :func:`modules.visualization.charts.plot_rolling_sharpe` — rolling
       12-month Sharpe ratio for each portfolio.
    5. :func:`modules.visualization.charts.plot_weight_sensitivity_heatmap`
       — Sharpe vs value/sentiment weight mix.
    6. :func:`modules.visualization.charts.plot_factor_loadings` —
       Fama-French 5-factor betas with 95% CIs and t-stats.
    7. :func:`modules.visualization.charts.plot_sector_allocation` —
       portfolio vs benchmark sector allocation.
    8. :func:`modules.visualization.charts.plot_random_portfolio_histogram`
       — strategy Sharpe overlaid on 10,000 random Sharpes.
    9. :func:`modules.visualization.charts.plot_threshold_sensitivity` —
       screening threshold sensitivity (top-% × D/E grid).
    10. :func:`modules.visualization.charts.plot_turnover_per_rebalance`
        — one-way turnover per rebalance date.
    11. :func:`modules.visualization.charts.plot_old_vs_new_value_scores`
        — sector concentration of top quintile under CW1 vs CW2 scoring.
    12. :func:`modules.visualization.charts.plot_pipeline_flowchart` —
        CW1 → CW2 architecture diagram.

Sophistication add-ons (mapped to Appendix B / E):

    13. :func:`modules.visualization.charts.plot_diversification_over_time`
        — effective N, sector count, max sector weight per rebalance.
    14. :func:`modules.visualization.charts.plot_cumulative_cost_impact`
        — per-rebalance and cumulative cost drag.

Plus :func:`modules.visualization.tearsheet.generate_tearsheet` for the
QuantStats HTML appendix.
"""

from modules.visualization.charts import (
    plot_cumulative_cost_impact,
    plot_cumulative_returns,
    plot_diversification_over_time,
    plot_drawdown,
    plot_factor_loadings,
    plot_monthly_heatmap,
    plot_old_vs_new_value_scores,
    plot_pipeline_flowchart,
    plot_random_portfolio_histogram,
    plot_rolling_sharpe,
    plot_sector_allocation,
    plot_threshold_sensitivity,
    plot_turnover_per_rebalance,
    plot_weight_sensitivity_heatmap,
)
from modules.visualization.tearsheet import generate_tearsheet

__all__ = [
    'plot_cumulative_returns',
    'plot_drawdown',
    'plot_monthly_heatmap',
    'plot_rolling_sharpe',
    'plot_weight_sensitivity_heatmap',
    'plot_factor_loadings',
    'plot_sector_allocation',
    'plot_random_portfolio_histogram',
    'plot_threshold_sensitivity',
    'plot_turnover_per_rebalance',
    'plot_old_vs_new_value_scores',
    'plot_pipeline_flowchart',
    'plot_diversification_over_time',
    'plot_cumulative_cost_impact',
    'generate_tearsheet',
]
