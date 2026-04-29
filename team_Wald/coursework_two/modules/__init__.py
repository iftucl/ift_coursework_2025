"""CW2 — Value-Sentiment Investment Strategy package.

Top-level namespace for the modular backtesting pipeline that lives under
``coursework_two/modules``. The package is organised by concern, mirroring
the architecture documented in Part D §D1 of the CW2 Master Guide:

    * :mod:`modules.data` — point-in-time data access (CW1 PostgreSQL,
      MongoDB, Yahoo Finance benchmarks)
    * :mod:`modules.signals` — sector-relative value, quality-weighted
      sentiment, and the composite signal combiner
    * :mod:`modules.portfolio` — screening, weighting and constraint
      enforcement
    * :mod:`modules.backtest` — quarterly rebalance loop, T+1 execution,
      transaction costs
    * :mod:`modules.analytics` — performance, risk, turnover,
      diversification, and the backtesting-pitfalls audit
    * :mod:`modules.robustness` — sensitivity grids, stationary bootstrap,
      random-portfolio test
    * :mod:`modules.visualization` — all 14 charts and the QuantStats
      tearsheet

The package never reaches outside ``coursework_two/`` for code dependencies,
but reads from CW1's database tables for input data via ``data_loader``.
"""

__version__ = '2.0.0'
__author__ = 'Team 09 — UCL Institute of Finance & Technology'
