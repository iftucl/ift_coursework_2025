# CW2 Handoff for Robustness Testing

Date: 2026-04-29

This file is retained as micro-alpha selection evidence. It is not the current
GitHub delivery entry point. For the current formal strategy handoff, start
from `START_HERE_DELIVERY_BUNDLE.md`,
`REFERENCE_STRATEGY_SUMMARY.md`, and
`team_Pearson/coursework_two/docs/formal_strategy_briefing_20260420.md`.

## Current State

The current best configuration has been promoted from the micro-alpha sweep into a formal configuration and formal report. It has already been run on the 5-year full processed universe, reusing the existing database features.

- Backtest window: `2021-04-20` to `2026-04-20`
- Selected candidate: `fund_ra3_s30_t50`
- Formal portfolio name: `cw2_formal_20260420_fund_ra3_s30_t50`
- Formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Micro sweep validation run id: `c7777a65-a520-4c68-a9a3-f71d141f0db2`
- Covariance method: `fundamental_factor`
- Risk aversion: `3.0`
- Max sector weight: `0.30`
- Turnover cap: `0.50`

## Current Best Metrics

- Total return: `74.115402%`
- Annualized return: `11.939622%`
- Annualized volatility: `15.816019%`
- Sharpe ratio: `0.582195`
- Information ratio: `0.125923`
- Max drawdown: `17.130802%`
- Beta: `0.955289`
- Average monthly turnover: `15.352812%`
- Average holdings: `34.474576`
- SPY benchmark total return: `67.755749%`
- Universe equal-weight benchmark total return: `55.281900%`
- Excess annualized return vs universe_ew: `2.576214%`
- Information ratio vs universe_ew: `0.451518`

## Key Files to Hand Off

- Current GitHub delivery entry point:
  `START_HERE_DELIVERY_BUNDLE.md`
- Current reference summary:
  `REFERENCE_STRATEGY_SUMMARY.md`
- Formal strategy briefing:
  `team_Pearson/coursework_two/docs/formal_strategy_briefing_20260420.md`
- Exact reproduction contract:
  `team_Pearson/coursework_two/repro/reference_run_20260420.json`
- Optional release-bundle instructions:
  `team_Pearson/coursework_two/repro/README.md`
- Formal best config:
  `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- Formal sweep ranking:
  `team_Pearson/coursework_two/outputs/formal_sweeps/20260429T031646Z/ranking.csv`
- Formal report:
  `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`
- Micro sweep config:
  `team_Pearson/coursework_two/config/experiments/micro_alpha/cw2_microalpha_20260420_fund_ra3_s30_t50.yaml`
- Sweep ranking:
  `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/ranking.csv`
- Sweep manifest:
  `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/manifest.json`
- Ranking JSON:
  `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/ranking.json`
- Current best snapshot:
  `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/current_best_snapshot.md`
- Sweep runner:
  `team_Pearson/coursework_two/scripts/mini_target_sweep.py`

## Database State Required

The ranking and metrics are not fully reproducible from files alone unless the next owner also has the same database state.

Important persisted tables include:

- `systematic_equity.portfolio_target_positions`
- `systematic_equity.portfolio_construction_diagnostics`
- `systematic_equity.backtest_performance`
- `systematic_equity.backtest_metrics`
- Existing feature tables used by the target-only sweep, including factor scores, risk overlay, universe screen, company information, prices, and benchmark data.

For exact database-state replay, generate the optional formal release assets
from `team_Pearson/coursework_two/scripts/export_repro_bundle.sh` as documented
in `team_Pearson/coursework_two/repro/README.md`. Historical local
`handoff_exports/` folders are intentionally not part of the Git-tracked
reproduction path.

For the selected portfolio:

- Target positions were written for 20 quarterly rebalance snapshots.
- Backtest performance has 59 monthly records.
- Formal metrics were persisted under run id `6905e84b-9e16-4106-8c0f-cd9ecce56728`.
- Internal benchmark metrics for `universe_ew` were materialized under the same formal run id.
- Micro sweep validation metrics were persisted under run id `c7777a65-a520-4c68-a9a3-f71d141f0db2`.

## Reproduction Command

The 4-cell micro sweep was run with:

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/scripts/mini_target_sweep.py \
  --base-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s25_t50.yaml \
  --start-date 2021-04-20 \
  --end-date 2026-04-20 \
  --portfolio-prefix cw2_microalpha_20260420 \
  --config-dir team_Pearson/coursework_two/config/experiments/micro_alpha \
  --output-dir team_Pearson/coursework_two/outputs/micro_alpha_sweeps \
  --covariance-methods fundamental_factor \
  --risk-aversions 2.5,3.0 \
  --max-sector-weights 0.25,0.30 \
  --turnover-caps 0.50
```

## What the Next Owner Should Do First

1. Confirm they can read the database and reproduce the selected run metrics from `backtest_metrics`.
2. Use the formal config/report as the current candidate baseline for robustness testing.
3. If robustness tests change the selected parameters, regenerate the formal report under a new report name.
4. Keep `diagonal_shrinkage` as a benchmark because it was stronger in the earlier isolated covariance-only comparison.

## Suggested Robustness Tests

Recommended fast tests:

- Compare `fundamental_factor` against `diagonal_shrinkage` and `statistical_factor` using the selected parameter values.
- Run sector cap sensitivity around `0.25`, `0.30`, and `0.35`.
- Run turnover sensitivity around `0.40`, `0.50`, and `0.60`.
- Run risk aversion sensitivity around `2.5`, `3.0`, `3.5`, and `4.0`.
- Test one shorter subperiod, such as `2021-04-20` to `2023-12-31`, and one later subperiod, such as `2024-01-01` to `2026-04-20`.
- Check whether outperformance survives after transaction costs and whether max drawdown remains below the project risk threshold.

## Current Interpretation

The strategy is currently an enhanced-equity strategy with controlled beta and
moderate alpha. `SPY` is the primary external market benchmark, while
`universe_ew` is the secondary same-opportunity-set comparison. The best result
comes from combining a more institution-style `fundamental_factor` risk model
with a slightly looser sector cap. The improvement is incremental rather than
dramatic, so robustness testing should focus on whether the selected parameters
are stable rather than overfit to one sweep.
