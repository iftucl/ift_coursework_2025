# CW2 Pipeline

## Role of CW2

`CW2` is the portfolio intelligence layer built on top of the curated `CW1` data estate.

It consumes:

- factor atomics from `factor_observations`
- PIT-clean financial observations
- benchmark and macro data
- news-derived sentiment and event proxies

It produces:

- first-level factor sub-scores
- regime-aware factor scores
- risk overlay decisions
- final month-end portfolio targets
- daily update-decision records
- recommendation objects
- control-plane and lineage records for downstream backtest/report runs

## First-Level Factors

The current factor framework has five groups:

1. `quality`
   - `ebitda_margin`
   - `roe`
   - `debt_to_equity_inv`

2. `value`
   - `book_to_price`
   - `earnings_to_price`
   - `ebitda_to_ev`

3. `market_technical`
   - `momentum_1m`
   - `momentum_6m`
   - `momentum_12_1m`

   Note: CW1 stores the source field for `momentum_12_1m` as `momentum_12m`.
   The calculation already skips the most recent 21 trading days, so the CW2
   name reflects the true 12-1M economic definition rather than a different
   database calculation.

4. `sentiment`
   - `sentiment_7d_avg`
   - `sentiment_30d_avg`
   - `sentiment_surprise`

5. `dividend`
   - `dividend_yield`
   - `dividend_stability`
   - `payout_sustainability`

The current formal feature stack keeps `sentiment` as one of the five first-level
factor groups. Its normal-regime weight is `0.00`, while its stress-regime
weight is `0.05`; therefore sentiment is stored and available, but it is only a
small defensive stress-regime input in the formal strategy.

## Second-Level Composite Alpha

CW2 combines first-level scores into `composite_alpha` under two regimes:

- `normal`
- `stress`

The regime engine currently uses:

- `VIX`
- `term spread`
- hysteresis persistence / exit rules from config

This avoids a purely single-signal volatility regime design.

## Portfolio Construction

The portfolio construction layer is:

- configured-cadence target generation
- global ranking
- `hybrid` selection
- long-only
- constrained mean-variance using the configured covariance risk model

Current default portfolio policy:

- target generation frequency `quarterly`
- `top_pct = 0.12`
- `hybrid_min_n = 25`
- `hybrid_max_n = 35`
- `min_names = 25`
- single-name cap `5%`
- sector cap `30%`
- turnover cap `50%`
- risk aversion `3.0`
- covariance method `fundamental_factor`

`backtest.top_n` still exists in config, but it is retained mainly as legacy run
metadata rather than as the primary stock-selection control.

The formal covariance model is a factor covariance risk model, not another
alpha factor group. It uses `Sigma = X F X' + D`, with style exposures
(`market_beta`, `size`, `value`, `momentum`, `quality`, `volatility`,
`liquidity`, and `dividend`) plus sector exposures. `F` is the shrunk covariance
of estimated factor returns and `D` is stock-specific residual risk with a
configured floor.

## Recommendation Workflow

The latest stored `portfolio_target_positions` can be published as:

- `proposed`
- `approved`
- `rejected`
- `published`

Each recommendation stores:

- item weights
- previous vs current trade deltas
- factor rationale
- workflow events and decisions

## Daily Update Decisions

CW2 also materializes a small operational layer that classifies each run date
into one of:

- `monitor_only`
- `risk_review`
- `full_rebalance`
- `blocked`

This keeps incremental upstream refreshes and formal portfolio updates separate.

## Snapshot and Manifest Layer

CW2 also writes:

- `feature_snapshot_registry`
- `portfolio_snapshot_registry`
- `model_input_manifests`
- `ops_pipeline_runs`
- `ops_stage_runs`
- `quality_snapshots`

This makes portfolio generation auditable by `as_of_date`.

## Research Execution and Reproducibility

Stored month-end `portfolio_target_positions` feed the downstream research loop:

- stored-strategy backtest
- database-backed analysis outputs
- markdown/json reporting artifacts
- reference verification against the frozen latest-run contract

The latest exact-reproduction workflow is documented under
`team_Pearson/coursework_two/repro/`.
