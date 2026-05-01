# Data Version Proof

- Baseline run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Baseline portfolio: `cw2_formal_20260420_fund_ra3_s30_t50`
- PIT cutoff date: `2026-04-20`
- PIT rule: factor rows require `observation_date <= 2026-04-20` and `publish_date <= 2026-04-20` where available.
- Financial rows require `publish_date <= 2026-04-20` where available.

## Key Counts

- `factor_observations`: count/distinct=17641612, min_date=2015-04-06, max_date=2026-04-20, min_publish=2015-04-06, max_publish=2026-04-20
- `financial_observations`: count/distinct=112715, min_date=2021-01-23, max_date=2026-03-31, min_publish=2021-02-16, max_publish=2026-04-20
- `benchmark_prices`: count/distinct=2777, min_date=2015-04-06, max_date=2026-04-20, min_publish=None, max_publish=None
- `backtest_performance`: count/distinct=59, min_date=2021-06-01, max_date=2026-04-01, min_publish=None, max_publish=None
- `portfolio_target_positions`: count/distinct=20, min_date=2021-06-30, max_date=2026-03-31, min_publish=None, max_publish=None
- `portfolio_snapshot_registry`: count/distinct=20, min_date=2021-06-30, max_date=2026-03-31, min_publish=None, max_publish=None
- `backtest_factor_attribution`: count/distinct=285, min_date=2021-06-30, max_date=2026-02-27, min_publish=None, max_publish=None
- `backtest_covariance_metrics`: count/distinct=1113, min_date=2021-10-29, max_date=2026-02-27, min_publish=None, max_publish=None
- `backtest_covariance_contributions`: count/distinct=18639, min_date=2021-10-29, max_date=2026-02-27, min_publish=None, max_publish=None
- `backtest_regime_attribution`: count/distinct=6, min_date=None, max_date=None, min_publish=None, max_publish=None
- `backtest_scorecard`: count/distinct=5, min_date=None, max_date=None, min_publish=None, max_publish=None

## Baseline Metrics

- Total return: 74.115402%
- Annualised return: 11.939622%
- Annualised volatility: 15.816019%
- Max drawdown: 17.130802%
- Sharpe ratio: 0.582195
- Primary benchmark: universe_ew
- Secondary benchmark / market reference: SPY

## Attribution / Scorecard Tables

- `backtest_factor_attribution`: 285 rows
- `backtest_covariance_metrics`: 1113 rows
- `backtest_covariance_contributions`: 18639 rows
- `backtest_regime_attribution`: 6 rows
- `backtest_scorecard`: 5 rows

These tables were generated for the formal run and are included in this package.
