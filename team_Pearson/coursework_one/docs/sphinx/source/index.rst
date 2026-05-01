Team Pearson Investment Platform
================================

This site documents the **full Team Pearson production-style investment platform**:

- `CW1` upstream ingestion, normalization, quality, and storage
- `CW2` factor engineering, composite alpha, risk overlay, and portfolio construction
- database-backed backtest, analysis, recommendation, and report generation
- Airflow orchestration, SQL-backed control-plane trace, and automated Sphinx builds
- exact CW2 reproduction workflow through frozen release bundles and reference verification
- Kafka event fan-out for structured news, event proxies, risk actions, and run-status events

The current architecture is **hybrid and auditable**:

- raw and replayable data in `MinIO`
- structured truth in `PostgreSQL`
- searchable news in `MongoDB`
- runtime resilience state in `Redis`
- persisted control-plane trace in `ops_pipeline_runs`, `ops_stage_runs`, and `quality_snapshots`
- incremental event fan-out in `Kafka`

For a marking-oriented fast pass, start with `Marker Quick Guide` before
drilling into the full architecture, data, and API pages.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   marker_quick_guide
   installation
   usage
   architecture
   data_implementation
   cw2_pipeline
   benchmark_methodology
   cw2_core_modules
   backtest_reporting
   cw2_robustness_web
   orchestration_eventing
   cw2_reproduction
   cw2_handoff
   module_reference
   api_reference
   compliance
