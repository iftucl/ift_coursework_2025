# Stochastic Robustness Acceptance Pack

## Test Status

| Test | Scenario | Status | P50 Ann Return / OOS Ann Return | P50 Sharpe / OOS Sharpe |
|---|---|---|---:|---:|
| test_9 | stationary_block_bootstrap | completed | 12.51% | 0.788 |
| test_10 | cost_multiplier_sigma_30pct | completed | 12.39% | 0.770 |
| test_10 | cost_multiplier_sigma_50pct | completed | 12.39% | 0.770 |
| test_10 | flat_extra_25bps | completed | 11.45% | 0.712 |
| test_11 | factor_weight_loose | completed | 10.81% | 0.519 |
| test_11 | factor_weight_medium | completed | 11.58% | 0.563 |
| test_11 | factor_weight_tight | completed | 10.54% | 0.501 |
| test_12 | rolling_24p_is_1p_oos | completed | 16.62% | 1.100 |
| test_13 | empirical_mean_covariance | completed | 12.37% | 0.768 |

## Conclusions

- Stationary Block Bootstrap delivers about 12.51% annualized return at the central estimate, about 0.788 Sharpe, and about 99.0% on the key positive-probability metric. Implementation status: completed. Directly mapped from existing stationary block bootstrap path metrics.
- Monte Carlo Cost Perturbation (sigma 30%) delivers about 12.39% annualized return at the central estimate, about 0.770 Sharpe, and about 100.0% on the key positive-probability metric. Implementation status: completed. Matches the requirement-sheet Monte Carlo cost perturbation with realized cost multiplier epsilon ~ N(0, 0.3^2).
- Monte Carlo Cost Perturbation (sigma 50%) delivers about 12.39% annualized return at the central estimate, about 0.770 Sharpe, and about 100.0% on the key positive-probability metric. Implementation status: completed. Stress version of Test 10 using wider cost multiplier dispersion.
- Flat +25bps Execution Drag delivers about 11.45% annualized return at the central estimate, about 0.712 Sharpe, and about 100.0% on the key positive-probability metric. Implementation status: completed. Requirement-sheet style cost robustness using turnover-linked 25bps incremental drag.
- Factor-weight Dirichlet Neighbourhood (loose) delivers about 10.81% annualized return at the central estimate, about 0.519 Sharpe, and about 100.0% on the key positive-probability metric. Implementation status: completed. Requirement-style reruns built from full snapshot refresh, backtest, analysis, and report generation for sampled regime.normal factor weights.
- Factor-weight Dirichlet Neighbourhood (medium) delivers about 11.58% annualized return at the central estimate, about 0.563 Sharpe, and about 100.0% on the key positive-probability metric. Implementation status: completed. Requirement-style reruns built from full snapshot refresh, backtest, analysis, and report generation for sampled regime.normal factor weights.
- Factor-weight Dirichlet Neighbourhood (tight) delivers about 10.54% annualized return at the central estimate, about 0.501 Sharpe, and about 100.0% on the key positive-probability metric. Implementation status: completed. Requirement-style reruns built from full snapshot refresh, backtest, analysis, and report generation for sampled regime.normal factor weights.
- Rolling Out-of-Sample (24P IS / 1P OOS) delivers about 16.62% annualized return at the central estimate, about 1.100 Sharpe, and about 48.5% on the key positive-probability metric. Implementation status: completed. Built directly from monthly return records of the quarterly-rebalanced strategy using rolling 24-period estimation windows and chained 1-period OOS evaluation.
- Monte Carlo Path Simulation from Empirical Mean/Covariance delivers about 12.37% annualized return at the central estimate, about 0.768 Sharpe, and about 94.5% on the key positive-probability metric. Implementation status: completed. Uses multivariate normal simulation fitted to realized monthly strategy and benchmark returns from the quarterly-rebalanced run.
