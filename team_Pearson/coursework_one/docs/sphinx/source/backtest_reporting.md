# Backtest, Analysis, and Reporting

## Backtest Design

The CW2 backtest engine is database-backed and stored-strategy driven.

Inputs come from:

- `portfolio_target_positions`
- benchmark and macro series
- price and liquidity history needed for execution realism and benchmark continuity

Outputs are written to SQL tables under the `systematic_equity` schema.

Adjacent CW2 operational state is also persisted in SQL through:

- `portfolio_update_decisions`
- `ops_pipeline_runs`
- `ops_stage_runs`
- `quality_snapshots`

## Execution Realism

The current backtest is not a naive frictionless simulation.

It includes:

- transaction costs in basis points
- slippage
- opening execution penalty
- ADV participation limits
- liquidity clipping
- executed vs requested turnover
- explicit cash ledger

## Intraperiod Overlay

Inside each monthly holding period the engine can apply:

- stop-loss exits
- `VIX`/term-spread regime switching
- weekly target rebalancing
- event-driven trims from:
  - negative news sentiment
  - negative earnings-news after publication
  - rating-downgrade news proxies

## Analysis Layer

The analysis pipeline produces:

- benchmark NAV comparison
- relative metrics
- regime attribution
- covariance risk diagnostics
- scorecard evaluation

This turns the backtest into a proper analytical workflow rather than a single NAV series.

The benchmark hierarchy is documented separately in
[Benchmark Methodology](benchmark_methodology.md). In the formal configuration,
`SPY` is the primary benchmark, `universe_ew` is the gross same-universe
opportunity-set comparison, and `static_baseline` is the net-of-cost
construction-layer control.

## Reporting Layer

The reporting module renders:

- charts
- markdown report
- json summary

It also persists the report artifact manifest into SQL so outputs remain auditable.

Recent runs additionally carry config hashes, lineage windows, and report-level
snapshot identifiers so a rendered report can be traced back to a concrete
portfolio snapshot and scheduler execution record.

## Exact Reproduction

The formal CW2 reference run is not described only by an ad hoc
local report directory. The repository also tracks:

- a frozen reference contract in `coursework_two/repro/reference_run_20260420.json`
- human-readable run notes in `coursework_two/repro/reference_summary_20260420.md`
- export / restore / verify scripts for the frozen release bundle

The monthly Airflow research DAG includes a dedicated verification stage so the
regenerated `report_summary.json` can be checked against the tracked reference
metrics before the pipeline is treated as complete.

## Practical CLI Modes

Relevant `CW2` modes are:

- `features`
- `operate`
- `update-decision`
- `backtest`
- `analyse`
- `backtest-and-analyse`
- `report`
- `audit`
- `monitor`
- `full-run`

These together form a full script-driven and database-backed research loop.
