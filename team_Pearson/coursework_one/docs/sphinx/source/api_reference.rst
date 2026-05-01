API Reference
=============

This page is the autodoc-backed layer of the shared Team Pearson platform site.
Unlike the architecture and usage pages, the content below is imported directly
from module docstrings and function docstrings in the repository.
That means keeping the core `CW2` docstrings complete is part of the maintained
documentation workflow, not a separate optional write-up.

CW2 Main Entrypoint
-------------------

.. automodule:: team_Pearson.coursework_two.Main
   :members:
   :private-members:
   :member-order: bysource

CW2 Scheduler Wrappers
----------------------

.. automodule:: team_Pearson.coursework_two.scripts.run_full_chain
   :members:
   :private-members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.scripts.run_backtest_analysis_report
   :members:
   :private-members:
   :member-order: bysource

CW2 Feature Engineering And Alpha
---------------------------------

.. automodule:: team_Pearson.coursework_two.modules.feature.preprocessing
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.feature.factor_engine
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.feature.composite_alpha
   :members:
   :member-order: bysource

CW2 Portfolio Construction And Risk
-----------------------------------

.. automodule:: team_Pearson.coursework_two.modules.portfolio.universe_screen
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.risk.overlay
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.risk.covariance
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.portfolio.construction
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.risk.actions
   :members:
   :member-order: bysource

CW2 Research And Persistence
----------------------------

.. automodule:: team_Pearson.coursework_two.modules.backtest.engine
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.backtest.writer
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.analysis.relative_metrics
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.analysis.regime_attribution
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.analysis.covariance_risk
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.analysis.scorecard
   :members:
   :member-order: bysource

CW2 Reporting And Recommendation
--------------------------------

.. automodule:: team_Pearson.coursework_two.modules.recommendation.publisher
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.reporting.report
   :members:
   :member-order: bysource

CW2 Operations, Audit, And Config
---------------------------------

.. automodule:: team_Pearson.coursework_two.modules.utils.config_validation
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.ops.audit
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.ops.runtime_control
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.ops.monitoring
   :members:
   :member-order: bysource

.. automodule:: team_Pearson.coursework_two.modules.ops.kafka_audit
   :members:
   :member-order: bysource
