# Robustness Requirement Report

- Main run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Formal baseline: `cw2_formal_20260420_fund_ra3_s30_t50`.
- Cadence: quarterly target generation and quarterly execution; monthly rows are holding-period performance records.
- Exclusion: the 2026-04-24 report is not used because it predates the PIT fix and formal parameter selection.
- Deterministic tests completed: 8 / 8
- Stochastic scenarios captured: 7

## Deterministic Completion

| Test | Scenario Count | Completed |
|---|---:|---|
| 1 | 4 | Yes |
| 2 | 5 | Yes |
| 3 | 3 | Yes |
| 4 | 5 | Yes |
| 5 | 4 | Yes |
| 6 | 5 | Yes |
| 7 | 4 | Yes |
| 8 | 4 | Yes |

## Stochastic

| Method | Scenario | Class | P50 Ann Return | P50 Sharpe | P50 Max DD | Positive Return Prob |
|---|---|---|---:|---:|---:|---:|
| bootstrap | stationary_block_e6m | core | 12.510% | 0.788 | -15.503% | 98.950% |
| local_weight_perturbation | loose_alpha_100 | auxiliary | 14.142% | 0.868 | -16.897% | 100.000% |
| local_weight_perturbation | medium_alpha_250 | auxiliary | 14.184% | 0.881 | -16.718% | 100.000% |
| local_weight_perturbation | tight_alpha_500 | auxiliary | 14.216% | 0.883 | -16.802% | 100.000% |
| monte_carlo | garch_base | core | 12.442% | 0.788 | -18.694% | 93.750% |
| monte_carlo | garch_stress_1_5xvol | core | 7.758% | 0.250 | -45.373% | 68.850% |
| monte_carlo | garch_stress_2xvol | stress_only | -31.039% | -0.314 | -95.841% | 25.050% |

## Stochastic Acceptance

| Test | Scenario | Status | P50 Ann Return / OOS Ann Return | P50 Sharpe / OOS Sharpe |
|---|---|---|---:|---:|
| test_9 | stationary_block_bootstrap | completed | 12.510% | 0.788 |
| test_10 | cost_multiplier_sigma_30pct | completed | 12.391% | 0.770 |
| test_10 | cost_multiplier_sigma_50pct | completed | 12.389% | 0.770 |
| test_10 | flat_extra_25bps | completed | 11.452% | 0.712 |
| test_11 | factor_weight_loose | completed | 10.814% | 0.519 |
| test_11 | factor_weight_medium | completed | 11.583% | 0.563 |
| test_11 | factor_weight_tight | completed | 10.538% | 0.501 |
| test_12 | rolling_24p_is_1p_oos | completed | 16.623% | 1.100 |
| test_13 | empirical_mean_covariance | completed | 12.365% | 0.768 |

## Acceptance Matrix

| Requirement Group | Item | Status | Detail |
|---|---|---|---|
| Part 1 Deterministic | Deterministic Test 1 | completed | scenario_count=4 |
| Part 1 Deterministic | Deterministic Test 2 | completed | scenario_count=5 |
| Part 1 Deterministic | Deterministic Test 3 | completed | scenario_count=3 |
| Part 1 Deterministic | Deterministic Test 4 | completed | scenario_count=5 |
| Part 1 Deterministic | Deterministic Test 5 | completed | scenario_count=4 |
| Part 1 Deterministic | Deterministic Test 6 | completed | scenario_count=5 |
| Part 1 Deterministic | Deterministic Test 7 | completed | scenario_count=4 |
| Part 1 Deterministic | Deterministic Test 8 | completed | scenario_count=4 |
| Part 2 Ablation | Ablation Block A | pending | scenario_count=0 |
| Part 2 Ablation | Ablation Block B | completed | scenario_count=6 |
| Part 2 Ablation | Ablation Block C | pending | scenario_count=0 |
| Part 3 Subperiod | Fixed Window Subperiod Tables | completed | rows=15; unavailable_rows=0 |
| Part 3 Subperiod | Normal / Stress / All Regime Decomposition | pending | rows=0 |
| Part 4 Stochastic | Test 9 | completed | scenario_count=1; path_count_max=2000 |
| Part 4 Stochastic | Test 10 | completed | scenario_count=3; path_count_max=10000 |
| Part 4 Stochastic | Test 11 | completed | scenario_count=3; path_count_max=2 |
| Part 4 Stochastic | Test 12 | completed | scenario_count=1; path_count_max=0 |
| Part 4 Stochastic | Test 13 | completed | scenario_count=1; path_count_max=10000 |
| Part 5 Packaging | Per-test tables and conclusion paragraphs | completed | acceptance_rows=9 |
| Part 5 Packaging | Comprehensive robustness dashboard | completed | dashboard_rows=10 |

## Fixed Sub-Periods

Code-aligned coverage note: rows with `N Periods = 0` are unavailable because the current baseline series begins after those requested windows, not because the analysis was skipped.

| Window | Versus | N Periods | Strategy Ann Return | Sharpe | Max DD | Excess Ann Return |
|---|---|---:|---:|---:|---:|---:|
| 2021 Reopening | SPY | 7 | 14.947% | 1.272 | -4.595% | 0.078% |
| 2021 Reopening | static_baseline | 7 | 14.947% | 1.272 | -4.595% | 6.300% |
| 2021 Reopening | universe_ew | 7 | 14.947% | 1.272 | -4.595% | 5.047% |
| 2022 Bear | SPY | 12 | 1.493% | 0.075 | -17.131% | 9.696% |
| 2022 Bear | static_baseline | 12 | 1.493% | 0.075 | -17.131% | 0.490% |
| 2022 Bear | universe_ew | 12 | 1.493% | 0.075 | -17.131% | 2.982% |
| 2023 Recovery | SPY | 12 | 5.429% | 0.295 | -9.489% | -9.041% |
| 2023 Recovery | static_baseline | 12 | 5.429% | 0.295 | -9.489% | 7.693% |
| 2023 Recovery | universe_ew | 12 | 5.429% | 0.295 | -9.489% | -0.664% |
| 2024 Bull | SPY | 12 | 36.075% | 2.650 | -4.966% | 2.815% |
| 2024 Bull | static_baseline | 12 | 36.075% | 2.650 | -4.966% | 5.642% |
| 2024 Bull | universe_ew | 12 | 36.075% | 2.650 | -4.966% | 8.571% |
| 2025-2026 Recent | SPY | 16 | 7.592% | 0.530 | -7.653% | -0.180% |
| 2025-2026 Recent | static_baseline | 16 | 7.592% | 0.530 | -7.653% | 3.011% |
| 2025-2026 Recent | universe_ew | 16 | 7.592% | 0.530 | -7.653% | -0.025% |

## Ablation

| Block | Scenario | Ann Return | Sharpe | Max DD | Avg Monthly Recorded Turnover |
|---|---|---:|---:|---:|---:|
| B | no_regime_switch | 8.997% | 0.424 | 17.656% | 15.699% |
| B | no_risk_overlay | 16.487% | 0.762 | 20.205% | 16.658% |
| B | no_drawdown_brake | 11.940% | 0.582 | 17.131% | 15.353% |
| B | no_intraday_trigger | 11.940% | 0.582 | 17.131% | 15.353% |
| B | no_liquidity_clipping | 11.940% | 0.582 | 17.131% | 15.353% |
| B | no_sector_constraint | 10.846% | 0.514 | 19.573% | 15.450% |

## Deterministic Detail

| Test | Scenario | Ann Return | Sharpe | Max DD | Source |
|---|---|---:|---:|---:|---|
| 1 | cost_10bps | 12.123% | 0.593 | 17.019% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 1 | cost_15bps_mainline | 11.940% | 0.582 | 17.131% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 1 | cost_25bps | 11.573% | 0.561 | 17.354% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 1 | cost_40bps | 11.024% | 0.530 | 17.689% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 2 | window_mainline | 11.940% | 0.582 | 17.131% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 2 | window_minus_3m | 11.330% | 0.568 | 17.131% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 2 | window_minus_6m | 10.780% | 0.554 | 17.131% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 2 | window_plus_3m | 11.957% | 0.562 | 17.131% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 2 | window_plus_6m | 11.360% | 0.516 | 17.130% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 3 | concentration_broader | 10.755% | 0.513 | 19.542% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 3 | concentration_mainline | 10.850% | 0.515 | 19.573% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 3 | concentration_tighter | 11.089% | 0.528 | 19.573% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 4 | factor_equal_weight | 10.642% | 0.505 | 21.735% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 4 | factor_quality_down_5pct | 11.698% | 0.569 | 17.834% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 4 | factor_quality_up_5pct | 10.043% | 0.472 | 19.820% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 4 | factor_value_down_5pct | 10.177% | 0.483 | 19.340% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 4 | factor_value_up_5pct | 12.944% | 0.636 | 15.699% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 5 | regime_disabled | 8.997% | 0.424 | 17.656% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 5 | regime_less_sensitive | 10.159% | 0.479 | 19.844% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 5 | regime_mainline | 10.850% | 0.515 | 19.573% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 5 | regime_more_sensitive | 10.102% | 0.466 | 20.604% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 6 | brake_aggressive | 7.016% | 0.322 | 12.980% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 6 | brake_mainline | 9.291% | 0.462 | 12.702% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 6 | brake_mild | 10.989% | 0.551 | 15.291% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 6 | brake_off | 11.940% | 0.582 | 17.131% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 6 | brake_staircase | 11.143% | 0.562 | 15.533% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 7 | band_medium | 11.194% | 0.537 | 18.522% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 7 | band_narrow | 10.912% | 0.521 | 19.108% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 7 | band_none | 10.720% | 0.509 | 19.690% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 7 | band_wide | 10.841% | 0.516 | 19.556% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 8 | trade_constraint_medium | 10.916% | 0.518 | 19.574% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 8 | trade_constraint_none | 10.850% | 0.515 | 19.573% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 8 | trade_constraint_strong | 10.939% | 0.519 | 19.584% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
| 8 | trade_constraint_weak | 10.865% | 0.516 | 19.580% | deterministic_sensitivity_summary_formal_fast_6905_20260429.csv |
