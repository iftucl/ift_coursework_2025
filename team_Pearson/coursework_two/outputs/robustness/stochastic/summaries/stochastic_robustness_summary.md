# Stochastic Robustness Summary

| Method | Scenario | Class | P50 Ann Return | P50 Sharpe | P50 Max DD | Positive Return Prob |
|---|---|---:|---:|---:|---:|---:|
| bootstrap | stationary_block_e6m | core | 12.51% | 0.788 | -15.50% | 99.0% |
| local_weight_perturbation | loose_alpha_100 | auxiliary | 14.14% | 0.868 | -16.90% | 100.0% |
| local_weight_perturbation | medium_alpha_250 | auxiliary | 14.18% | 0.881 | -16.72% | 100.0% |
| local_weight_perturbation | tight_alpha_500 | auxiliary | 14.22% | 0.883 | -16.80% | 100.0% |
| monte_carlo | garch_base | core | 12.44% | 0.788 | -18.69% | 93.8% |
| monte_carlo | garch_stress_1_5xvol | core | 7.76% | 0.250 | -45.37% | 68.8% |
| monte_carlo | garch_stress_2xvol | stress_only | -31.04% | -0.314 | -95.84% | 25.1% |

Notes:
- `bootstrap` (requirement-style Test 9 output) and `monte_carlo:garch_base` / `garch_stress_1_5xvol` are the main stochastic robustness references.
- `monte_carlo:garch_stress_2xvol` should be interpreted as an extreme stress test, not the central robustness case.
- `local_weight_perturbation` tests only nearby portfolio-weight perturbations around realized holdings, so it is intentionally narrower than a full strategy rerun.
