# Current Best CW2 Strategy Snapshot

Snapshot time: 2026-04-29

## Selected Candidate

- Candidate: `fund_ra3_s30_t50`
- Covariance method: `fundamental_factor`
- Risk aversion: `3.0`
- Max sector weight: `0.30`
- Turnover cap: `0.50`
- Formal portfolio name: `cw2_formal_20260420_fund_ra3_s30_t50`
- Formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Micro sweep validation run id: `c7777a65-a520-4c68-a9a3-f71d141f0db2`

## Performance

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

## Saved Artifacts

- Formal config: `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- Formal sweep ranking: `team_Pearson/coursework_two/outputs/formal_sweeps/20260429T031646Z/ranking.csv`
- Formal report: `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`
- Micro sweep config: `team_Pearson/coursework_two/config/experiments/micro_alpha/cw2_microalpha_20260420_fund_ra3_s30_t50.yaml`
- Sweep ranking: `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/ranking.csv`
- Sweep manifest: `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/manifest.json`
- Ranking JSON: `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/ranking.json`

## Database State

- Target positions were written for 20 quarterly rebalance snapshots.
- Backtest performance contains 59 monthly records for the selected run.
- Metrics were persisted in `systematic_equity.backtest_metrics`.

## Interpretation

The earlier covariance-only comparison showed `diagonal_shrinkage` was the stronger isolated baseline. After the micro parameter search, the best combined configuration is currently `fundamental_factor` with `risk_aversion=3.0`, `max_sector_weight=30%`, and `turnover_cap=50%`.
