# Deterministic Sensitivity Summary

| Test | Scenario | Ann Return | Sharpe | Max DD | Avg Monthly Recorded Turnover |
|---|---|---:|---:|---:|---:|
| 1 | cost_10bps | 12.123% | 0.593 | 17.019% | 15.353% |
| 1 | cost_15bps_mainline | 11.940% | 0.582 | 17.131% | 15.353% |
| 1 | cost_25bps | 11.573% | 0.561 | 17.354% | 15.353% |
| 1 | cost_40bps | 11.024% | 0.530 | 17.689% | 15.353% |
| 2 | window_mainline | 11.940% | 0.582 | 17.131% | 15.353% |
| 2 | window_minus_3m | 11.330% | 0.568 | 17.131% | 14.610% |
| 2 | window_minus_6m | 10.780% | 0.554 | 17.131% | 13.936% |
| 2 | window_plus_3m | 11.957% | 0.562 | 17.131% | 14.385% |
| 2 | window_plus_6m | 11.360% | 0.516 | 17.130% | 14.249% |
| 3 | concentration_broader | 10.755% | 0.513 | 19.542% | 15.170% |
| 3 | concentration_mainline | 10.850% | 0.515 | 19.573% | 15.459% |
| 3 | concentration_tighter | 11.089% | 0.528 | 19.573% | 15.532% |
| 4 | factor_equal_weight | 10.642% | 0.505 | 21.735% | 15.919% |
| 4 | factor_quality_down_5pct | 11.698% | 0.569 | 17.834% | 15.431% |
| 4 | factor_quality_up_5pct | 10.043% | 0.472 | 19.820% | 15.565% |
| 4 | factor_value_down_5pct | 10.177% | 0.483 | 19.340% | 15.324% |
| 4 | factor_value_up_5pct | 12.944% | 0.636 | 15.699% | 15.534% |
| 5 | regime_disabled | 8.997% | 0.424 | 17.656% | 15.699% |
| 5 | regime_less_sensitive | 10.159% | 0.479 | 19.844% | 15.390% |
| 5 | regime_mainline | 10.850% | 0.515 | 19.573% | 15.459% |
| 5 | regime_more_sensitive | 10.102% | 0.466 | 20.604% | 15.380% |
| 6 | brake_aggressive | 7.016% | 0.322 | 12.980% | 19.246% |
| 6 | brake_mainline | 9.291% | 0.462 | 12.702% | 19.187% |
| 6 | brake_mild | 10.989% | 0.551 | 15.291% | 16.572% |
| 6 | brake_off | 11.940% | 0.582 | 17.131% | 15.353% |
| 6 | brake_staircase | 11.143% | 0.562 | 15.533% | 15.983% |
| 7 | band_medium | 11.194% | 0.537 | 18.522% | 15.214% |
| 7 | band_narrow | 10.912% | 0.521 | 19.108% | 15.283% |
| 7 | band_none | 10.720% | 0.509 | 19.690% | 15.218% |
| 7 | band_wide | 10.841% | 0.516 | 19.556% | 15.152% |
| 8 | trade_constraint_medium | 10.916% | 0.518 | 19.574% | 15.490% |
| 8 | trade_constraint_none | 10.850% | 0.515 | 19.573% | 15.459% |
| 8 | trade_constraint_strong | 10.939% | 0.519 | 19.584% | 15.443% |
| 8 | trade_constraint_weak | 10.865% | 0.516 | 19.580% | 15.478% |
