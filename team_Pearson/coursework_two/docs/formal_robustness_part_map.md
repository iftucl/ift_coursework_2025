# Formal Robustness Part Map

This note is the source-of-truth map for running robustness after the formal S30 handoff.

## Baseline

- Formal config: `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- Formal portfolio: `cw2_formal_20260420_fund_ra3_s30_t50`
- Formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Formal report source: the 2026-04-29 formal handoff, not the 2026-04-24 report.
- Final report primary baseline: `SPY`.
- Supporting internal comparator: `universe_ew` / same-universe equal weight.

## Cadence

- Target-weight generation is quarterly.
- Actual execution/rebalancing is quarterly with the configured execution lag.
- Backtest performance rows are monthly holding-period records used for NAV, return, Sharpe, IR, drawdown, and turnover.
- Monthly monitoring, monthly snapshots, and monthly readiness backfill are operational controls. They are not monthly portfolio re-optimisation and not monthly rebalance decisions.

## Part 1 - Deterministic Sensitivity

Use `scripts/run_sensitivity_analysis.py`. It starts from the formal config and keeps target generation / execution quarterly unless a scenario is explicitly testing a practical assumption. Test 4 uses the tuned five key scenarios: equal factor weights plus quality up/down 5 percentage points and value up/down 5 percentage points.

## Part 2 - Ablation

Use `scripts/run_ablation_analysis.py`. It starts from the formal config and isolates factor, mechanism, and optimizer contributions. Ablations that require new target weights rebuild quarterly target snapshots rather than monthly targets.

## Part 3 - Sub-Period Analysis

Use `scripts/run_subperiod_analysis.py`. It reads the formal run id and slices the monthly performance records into market windows and regime states. The monthly rows are measurement periods, not rebalance events.

## Part 4 - Stochastic Robustness

Use `scripts/run_stochastic_robustness.py`, `scripts/build_stochastic_acceptance_pack.py`, and `scripts/run_test11_factor_neighbourhood.py`. Bootstrap, Monte Carlo, rolling OOS, and path simulation are calibrated on monthly realized return records from the quarterly-rebalanced formal strategy. Test 11 reruns local factor-weight neighbourhoods using quarterly target generation.

## Part 5 - Evidence Packaging

Use `scripts/build_robustness_requirement_report.py`, `scripts/build_report_evidence_pack.py`, and `scripts/build_report_evidence_readme.py`. Generated evidence should state the formal config/run id, SPY as the final report primary baseline, the quarterly execution cadence, the monthly performance-measurement convention, and the exclusion of the 2026-04-24 report.
