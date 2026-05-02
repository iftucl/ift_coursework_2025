# Robustness Report Evidence Pack

This is the directly readable overview for the report group.
Use this file first, then open the linked tables / figures inside each part folder.

## Formal Baseline And Cadence

- Formal baseline: `cw2_formal_20260420_fund_ra3_s30_t50`.
- Formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`.
- Target-weight generation and actual rebalancing are both quarterly.
- Performance rows, NAV, Sharpe, drawdown, IR, and turnover are measured monthly from the holding-period backtest.
- Monthly monitoring / snapshot backfill is operational readiness evidence only; it is not monthly portfolio re-optimisation or monthly rebalancing.
- Do not use the 2026-04-24 report as the robustness baseline because it predates the PIT fix and formal parameter selection.

## Requirement Map

### Part 1 - Deterministic Sensitivity

- Test 1: Trading Cost Sensitivity. Checks whether strategy performance survives less optimistic execution-cost assumptions.
- Test 2: Backtest Window Start Sensitivity. Checks whether results depend excessively on a particular sample start date.
- Test 3: Concentration Sensitivity. Checks whether alpha depends on one specific portfolio breadth choice.
- Test 4: Factor Weight Perturbation Sensitivity. Checks whether the normal-regime factor weights sit on an overfitted spike.
- Test 5: Regime Threshold Sensitivity. Checks whether regime switching depends too strongly on one exact threshold choice.
- Test 6: Drawdown Brake Sensitivity. Measures the return, drawdown, and turnover trade-off created by the drawdown brake design.
- Test 7: Banded Selector Sensitivity. Measures the churn-versus-performance trade-off from different entry and exit band widths.
- Test 8: No-Trade Band and Per-Name Cap Sensitivity. Measures how trade-size constraints suppress unnecessary surviving-name rebalancing.

### Part 2 - Ablation Study

- Ablation A: Factor Ablation. Removes one factor at a time to test its marginal contribution.
- Ablation B: Mechanism Ablation. Removes one mechanism at a time to test whether it improves the strategy.
- Ablation C: Optimizer Ablation. Replaces the main optimizer with simpler alternatives to test whether the optimizer adds risk-adjusted value.

### Part 3 - Sub-Period Analysis

- Sub-Period 1: Fixed Historical Windows. Compares performance across named market windows such as recovery, bear, and bull periods.
- Sub-Period 2: Regime Decomposition. Splits performance into normal, stress, and all-period views.

### Part 4 - Stochastic Robustness

- Test 9: Stationary Block Bootstrap. Resamples the realized monthly return path while preserving short-range serial dependence.
- Test 10: Monte Carlo Cost Perturbation. Randomizes execution costs to test whether net performance survives cost uncertainty.
- Test 11: Bayesian / Dirichlet Weight Neighbourhood. Perturbs factor weights around the baseline normal-regime allocation to test local robustness.
- Test 12: Rolling Out-of-Sample. Uses rolling estimation windows and one-step-forward evaluation to test out-of-sample decay.
- Test 13: Monte Carlo Path Simulation. Simulates long-run return paths from the empirical return distribution fit.

### Part 5 - Output Packaging

- Per-test tables and conclusion paragraphs. Provides report-ready evidence for each block.
- Comprehensive robustness dashboard. Provides the top-level acceptance and summary view across the whole robustness section.

## Part 1 Deterministic Sensitivity

- Index: `../REPORT_EVIDENCE_INDEX.md`
- Test 1 notes: `test_01_notes.md`
- Test 2 notes: `test_02_notes.md`
- Test 3 notes: `test_03_notes.md`
- Test 4 notes: `test_04_notes.md`
- Test 5 notes: `test_05_notes.md`
- Test 6 notes: `test_06_notes.md`
- Test 7 notes: `test_07_notes.md`
- Test 8 notes: `test_08_notes.md`

## Part 2 Ablation Study

- Ablation B notes: `ablation_block_b_notes.md`

## Part 3 Sub-Period Analysis

- Fixed windows notes: `subperiod_fixed_windows_notes.md`
- Regime decomposition notes: `subperiod_regime_decomposition_notes.md`
- Coverage note: `subperiod_coverage_note.md`

## Part 4 Stochastic Robustness

- Test 9 notes: `test_9_notes.md`
- Test 10 notes: `test_10_notes.md`
- Test 11 notes: `test_11_notes.md`
- Test 11 report-ready summary: `test11_report_ready_summary.md`
- Test 12 notes: `test_12_notes.md`
- Test 13 notes: `test_13_notes.md`
- General stochastic notes: `stochastic_report_ready_notes.md`

## Part 5 Dashboard and Conclusions

- Dashboard notes: `dashboard_notes.md`
- Acceptance matrix: `acceptance_matrix.csv`
- Stochastic dashboard: `stochastic_dashboard.csv`
- Requirement report: `robustness_requirement_report.md`

## Part 1 - Test 1

# Test 1 - Trading Cost Sensitivity

## Table
- Source table: `test_01_table.csv`
- Figure: `test_01_chart.png`

## Writing Notes
This test contains 4 scenarios. The best observed Sharpe in this block is 0.593, with annualized return 12.123%.
Use the table to compare the full scenario set, and use the bar chart to describe whether the mainline configuration remains inside a stable neighbourhood rather than standing on an isolated spike.
All scenarios keep positive excess return versus static baseline.

- Extra reference NAV chart: `test_01_nav_reference.png`

## Part 1 - Test 4

# Test 4 - Factor Weight Perturbation Sensitivity

## Table
- Source table: `test_04_table.csv`
- Figure: `test_04_chart.png`

## Writing Notes
This test contains 5 scenarios. The best observed Sharpe in this block is 0.636, with annualized return 12.944%.
Use the table to compare the full scenario set, and use the bar chart to describe whether the mainline configuration remains inside a stable neighbourhood rather than standing on an isolated spike.
All scenarios keep positive excess return versus static baseline.

- Extra reference NAV chart: `test_04_nav_reference.png`

## Part 2 - Ablation B

# Ablation Block B

- Source table: `ablation_block_b_table.csv`
- Figure: `ablation_block_b_chart.png`

## Writing Notes
Block B compares 6 ablation scenarios. The highest Sharpe in this block is 0.762 and the corresponding annualized return is 16.487%.
The report should explain whether removing a factor or mechanism lowers risk-adjusted performance, or whether a component appears redundant or even harmful in the current sample.

## Part 3 - Fixed windows

# Sub-Period 1 - Fixed Windows

- Source table: `subperiod_fixed_windows_table.csv`
- Figure: `subperiod_fixed_windows_chart.png`

## Writing Notes
Use the table to discuss each historical window separately.
Rows with `n_periods = 0` are unavailable because the current baseline series starts in June 2021.
- Coverage note: `subperiod_coverage_note.md`

## Part 4 - Test 11

# Factor-weight Dirichlet Neighbourhood

- Source table: `test_11_table.csv`

## Writing Notes
This is the current report-usable Test 11 rerun set built from full reruns around sampled regime.normal factor weights.
The current loose / medium / tight bands use 2 reruns per grouped scenario row in the acceptance summary.
Use this section as local-robustness evidence, but avoid overstating it as a 200-path neighbourhood study.

## Part 4 - Test 11 report-ready summary

# Test 11 Report-ready Summary

This table is built from the formal fast factor-weight neighbourhood reruns and is used by the web robustness view.

| sample_band | start_date | end_date | sample_count | annualized_return_mean_pct | sharpe_mean | excess_return_mean_pct | max_drawdown_mean_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| loose | 2021-04-20 | 2026-04-20 | 2 | 10.814 | 0.519 | 3.198 | 18.814 |
| medium | 2021-04-20 | 2026-04-20 | 2 | 11.583 | 0.563 | 3.968 | 18.365 |
| tight | 2021-04-20 | 2026-04-20 | 2 | 10.538 | 0.501 | 2.922 | 19.442 |

## Part 4 - General stochastic notes

# Stochastic Robustness Report-Ready Notes

Test 9 uses stationary block bootstrap on the realized monthly return series from the quarterly-rebalanced strategy. The central annualized return is 12.51%, the central Sharpe is 0.788, and the 90% annualized-return interval is 3.27% to 22.31%.

Test 10 perturbs realized trading costs with epsilon ~ N(0, 0.3^2). The central Sharpe is 0.770, P(Sharpe > 0.50) is 100.0%, and the worst-5% Sharpe CVaR is 0.765.






Test 12 evaluates a rolling 24-period in-sample / 1-period out-of-sample chain. Out-of-sample annualized return is 16.62%, Sharpe is 1.100, and hit rate versus benchmark is 48.5%.

Test 13 simulates long-run paths from the empirical mean/covariance fit. The annualized-return percentiles are -0.37% / 6.97% / 12.37% / 18.18% / 26.63%, with central Sharpe 0.768.

## Part 5 - Dashboard

# Part 5 Packaging

Use `acceptance_matrix.csv` to explain which blocks are complete, which are partial, and why.
Use `stochastic_dashboard.csv` and `baseline_scorecard.csv` for the top-level robustness summary paragraph.
Use `robustness_requirement_report.md` as the long-form internal reference, not as the final polished report text.
