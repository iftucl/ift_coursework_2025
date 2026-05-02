# Marker Quick Guide

If a marker only wants the fastest route to understand the implemented project,
the best five pages to read first are:

1. [Architecture Overview](architecture.md)
   This is the best one-page summary of the full platform scope from `CW1`
   ingestion through `CW2` portfolio intelligence, orchestration, eventing,
   reporting, and reproducibility.
2. [Data Implementation](data_implementation.md)
   This shows where data actually lives, which stores are authoritative, and
   what is persisted at each stage of the pipeline.
3. [CW2 Core Modules](cw2_core_modules.md)
   This is the fastest way to understand the current `CW2` production path from
   feature generation and alpha construction through research, recommendation,
   and operations.
4. [Backtest, Analysis, and Reporting](backtest_reporting.md)
   This explains how stored portfolio targets are evaluated, analysed, rendered
   into reports, and checked against the tracked reference run.
5. [Benchmark Methodology](benchmark_methodology.md)
   This explains why `SPY` is the primary benchmark, why `universe_ew` is kept
   gross as a same-universe opportunity-set comparison, and why
   `static_baseline` is charged trading costs as a tradable construction-layer
   control.

## What These Five Pages Cover Together

Read together, these four pages cover:

- data collection and upstream curation
- storage design and control-plane persistence
- factor engineering, risk overlay, and portfolio construction
- benchmark hierarchy and cost-treatment logic
- backtest realism, analysis outputs, and reporting
- the current audited and reproducible operating model

## If More Detail Is Needed

The next most useful follow-up pages are:

- [CW2 Pipeline](cw2_pipeline.md) for the strategy layer and stored outputs
- [Orchestration and Eventing](orchestration_eventing.md) for Airflow and Kafka
- [API Reference](api_reference.rst) for autodoc-backed module and function documentation
- [CW2 Current Reproduction Runbook](cw2_reproduction.md) for the live rerun path
