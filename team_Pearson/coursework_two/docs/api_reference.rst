API Reference
=============

Public Entrypoints
------------------

.. py:module:: team_Pearson.coursework_two.Main

``Main.py``
   Command-line orchestration for config loading, monitor/update-decision flows,
   backtest execution, and report workflows.

.. py:module:: team_Pearson.coursework_two.api.main

``api/main.py``
   FastAPI application for browser cards, scenario management, job execution,
   robustness artifacts, report generation, export, and LLM connector calls.

Core Modules
------------

.. py:module:: team_Pearson.coursework_two.modules.feature.factor_engine

``modules/feature/factor_engine.py``
   PIT factor scoring and composite feature generation.

.. py:module:: team_Pearson.coursework_two.modules.portfolio.construction

``modules/portfolio/construction.py``
   Target portfolio construction, optimizer inputs, constraints, and diagnostics.

.. py:module:: team_Pearson.coursework_two.modules.backtest.engine

``modules/backtest/engine.py``
   Holding-period backtest engine, quarterly rebalance handling, NAV, turnover, and
   performance statistics.

.. py:module:: team_Pearson.coursework_two.modules.robustness.persistence

``modules/robustness/persistence.py``
   Robustness artifact classification and report-evidence persistence.
