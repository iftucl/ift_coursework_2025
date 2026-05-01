# CW2 Formal Strategy Briefing

This briefing is the tracked formal summary of the current formal CW2
strategy. It replaces older generated operational briefing snapshots from
earlier development experiments.

## Formal Strategy Identity

- Formal run date: `2026-04-20`
- Formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Formal portfolio name: `cw2_formal_20260420_fund_ra3_s30_t50`
- Formal config:
  `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- Formal report:
  `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`
- Rebalance design: quarterly-native target generation and quarterly execution
- Primary benchmark: `SPY`
- Secondary comparison: `universe_ew`
- Construction-layer control: `static_baseline`

## Core Design

The strategy is a long-only U.S. equity portfolio that converts five first-level
factor groups into a composite alpha:

- Quality
- Value
- Market/Technical
- Sentiment
- Dividend

The formal configuration uses a VIX and term-spread regime signal to switch
between predefined Normal and Stress composite-alpha weights. IC-based dynamic
factor weighting is disabled in the formal run, so the reported strategy is
defined by the explicit regime weights in the formal YAML.

Portfolio construction is not a pure top-ranked stock list. The formal stack
uses investable-universe screening, global alpha ranking, hybrid selection,
issuer-level deduplication, pre-selection volatility and factor-coverage risk
guards, and covariance-aware mean-variance weighting.

## Formal Portfolio Parameters

| Component | Formal Setting |
|---|---:|
| covariance method | `fundamental_factor` |
| factor covariance style exposures | `market_beta`, `size`, `value`, `momentum`, `quality`, `volatility`, `liquidity`, `dividend` |
| sector exposures in risk model | enabled |
| factor covariance shrinkage | `0.10` |
| specific variance floor ratio | `0.05` |
| risk aversion | `3.0` |
| sector cap | `0.30` |
| turnover cap | `0.50` |
| max single-name weight | `0.05` |
| top alpha percentile | `0.12` |
| hybrid min names | `25` |
| hybrid max names | `35` |
| minimum target weight | `0.005` |
| transaction cost | `15 bps` |
| execution lag | `1 trading day` |

## Factor Covariance Risk Model

The formal `fundamental_factor` covariance model is a portfolio risk model, not
a sixth alpha factor. The five alpha groups determine expected-return ranking;
the covariance model determines how much diversification risk the optimizer is
taking when it converts those alpha scores into weights.

The implemented risk model follows the form `Sigma = X F X' + D`. `X` contains
PIT-clean style exposures and sector exposures, `F` is the shrunk covariance
matrix of estimated factor returns, and `D` is stock-specific residual variance
with a configured floor. This lets the optimizer recognize that two stocks can
share hidden systematic risk even when their individual alpha scores are both
high.

In the formal configuration, the style exposures are `market_beta`, `size`,
`value`, `momentum`, `quality`, `volatility`, `liquidity`, and `dividend`;
sector exposures are also included. The covariance matrix is annualized before
optimization and is used with `risk_aversion = 3.0`, the `5%` single-name cap,
the `30%` sector cap, and the `50%` turnover cap.

## Benchmark Contract

`SPY` is the primary benchmark because the report evaluates whether the strategy
adds value relative to broad investable U.S. equity market exposure. `SPY` is
treated as a buy-and-hold market reference and is not charged the strategy's
execution cost model.

`universe_ew` is a secondary same-opportunity-set comparison. It shows whether
the factor and construction engine adds value beyond naive equal weighting over
the investable universe. It is reported gross of trading costs because its role
is to isolate opportunity-set and factor-selection value rather than model a
tradable implementation.

`static_baseline` is the construction-layer control. It uses the same CW2 factor
stack but removes dynamic formal construction choices and is charged the same
configured `15 bps` cost assumption, so it is the closest tradable comparison
for the marginal value of the optimizer and formal portfolio process.

## Headline Formal Results

The formal 59-period backtest covers `2021-04-20` to `2026-04-20`.

| Metric | Formal Strategy |
|---|---:|
| total return | `74.115402%` |
| annualized return | `11.939622%` |
| annualized volatility | `15.816019%` |
| Sharpe ratio | `0.582195` |
| max drawdown | `17.130802%` |
| raw beta vs SPY | `0.955289` |
| information ratio vs SPY | `0.125923` |
| information ratio vs universe_ew | `0.451518` |
| trade blotter rows | `855` |
| scheduled execution rows | `855` |
| intraday action rows | `0` |

The formal strategy outperforms the primary `SPY` benchmark on total return and
annualized return, while preserving a beta below one and reducing max drawdown
relative to `SPY`. Relative to `universe_ew` and `static_baseline`, the result
supports the claim that the factor construction and optimizer add value beyond
naive diversification and beyond the static construction control.

## Selection Evidence

The final `ra3/s30/t50` configuration is not an isolated single run. It is the
end point of a documented selection path:

- design and selection decision log:
  `team_Pearson/coursework_two/docs/strategy_design_decision_log_20260420.md`
- coarse parameter search through mini sweep configs
- micro-alpha sweep evidence under
  `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/`
- formal sweep confirmation under
  `team_Pearson/coursework_two/outputs/formal_sweeps/20260429T031646Z/`
- formal report materialization for run id
  `6905e84b-9e16-4106-8c0f-cd9ecce56728`

The active-band research note is intentionally retained at
`team_Pearson/coursework_two/docs/research_upgrade_activeband_20260428.md`.
That note explains why a higher development-period active-band candidate was not
adopted as the formal strategy: its improvement was development-only after the
available holdout had already been consumed. Using it as the final formal model
would therefore create a methodological look-ahead concern.

## Current Interpretation

The formal strategy should be described as a quarterly-native, regime-aware,
factor-driven, covariance-aware long-only portfolio with practical liquidity,
turnover, issuer-deduplication, sector, and single-name controls.

It should not be described as an intraday trading strategy. The formal run has
drawdown brake and intraday trigger modules disabled, and its trade blotter is
driven by scheduled quarterly execution rows only.
