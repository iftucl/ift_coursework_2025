Architecture Overview
=====================

Eight-Stage Pipeline
--------------------

.. list-table::
   :header-rows: 1
   :widths: 18 32 50

   * - Stage
     - Main Modules
     - Responsibility
   * - 1. Configuration
     - ``config/``, ``modules/utils``
     - Load YAML, validate schema, and materialize scenario settings.
   * - 2. PIT Inputs
     - PostgreSQL, CW1-derived tables
     - Provide point-in-time factor, financial, benchmark, and universe data.
   * - 3. Feature Scoring
     - ``modules/feature``
     - Compute five-factor signals and composite alpha scores.
   * - 4. Universe Screening
     - ``modules/portfolio/universe_screen.py``
     - Select investable names using liquidity, data quality, and eligibility rules.
   * - 5. Construction
     - ``modules/portfolio/construction.py``
     - Estimate continuous target weights with risk and turnover constraints.
   * - 6. Backtest
     - ``modules/backtest``
     - Execute quarterly rebalances and record monthly holding-period performance.
   * - 7. Analysis
     - ``modules/analysis``, ``modules/risk``
     - Produce benchmark, attribution, covariance risk, and regime diagnostics.
   * - 8. Reporting
     - ``modules/reporting``, ``scripts/export_*``, ``api/``
     - Assemble evidence packs, browser views, and investor-facing reports.

Data Flow
---------

Browser selections become scenario configs. The API layer validates the request,
creates a job, runs scripts and modules, persists outputs, then returns artifacts to
dashboard and report views. Formal outputs are treated as evidence and kept separate
from temporary workbench state.
