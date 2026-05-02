# CW2 Strategy Design And Selection Decision Log

This note documents the design logic that led to the formal CW2 strategy:

- formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- formal portfolio: `cw2_formal_20260420_fund_ra3_s30_t50`
- formal config:
  `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- primary benchmark: `SPY`
- secondary comparison: `universe_ew`
- construction-layer control: `static_baseline`

The purpose is to preserve the professional reasoning behind the final strategy
without requiring readers to inspect obsolete raw sweep folders.

## Design Principles

The final strategy was selected under five constraints.

1. Point-in-time discipline. Factor, financial, price, dividend, sentiment, and
   benchmark inputs must only use information available by the relevant
   snapshot date.
2. Horizon alignment. The strategy uses quarterly-native target generation
   because the core signals are fundamental, dividend, medium-term technical,
   and regime-aware signals rather than high-frequency signals.
3. Mechanism clarity. Regime switching changes composite-alpha weights, not the
   trading frequency or the portfolio mandate.
4. Investability. Candidate selection must pass liquidity, market-cap,
   volatility, factor-coverage, issuer-deduplication, single-name, sector, and
   turnover controls.
5. Selection discipline. Parameter upgrades are accepted only when they improve
   the strategy within the declared validation boundary. Development-only
   improvements are not promoted to the formal strategy without a clean
   validation basis.

## Strategy Architecture

The formal model combines five first-level factor groups:

| Factor Group | Role In The Strategy |
|---|---|
| Quality | Rewards profitable, financially stronger firms and supports stress resilience. |
| Value | Adds valuation discipline through price-to-fundamental signals. |
| Market/Technical | Captures medium-term price continuation in normal market states. |
| Sentiment | Retained as a first-level group; formal stress weight is small and normal weight is zero. |
| Dividend | Adds defensive income and payout-quality information, especially in stress regimes. |

Composite alpha uses explicit regime weights from the formal YAML. IC-based
dynamic weighting is disabled in the formal configuration, which makes the
reported model easier to audit: each rebalance uses the Normal or Stress weight
vector selected by the VIX and term-spread regime classifier.

The alpha signal is then converted into a long-only portfolio through:

- investable universe screening
- global ranking with hybrid candidate selection
- volatility and factor-coverage risk guards
- issuer-level deduplication
- covariance-aware mean-variance weighting using the formal
  `fundamental_factor` covariance model
- single-name, sector, and turnover constraints
- one-day execution lag and a 15 bps all-in transaction cost assumption

The `fundamental_factor` covariance model is a risk model rather than an alpha
signal. It decomposes asset covariance as `Sigma = X F X' + D`, where `X`
contains style and sector exposures, `F` is the shrunk covariance of estimated
factor returns, and `D` is specific residual risk. The formal style exposure set
is `market_beta`, `size`, `value`, `momentum`, `quality`, `volatility`,
`liquidity`, and `dividend`, with sector exposures enabled. This design allows
the optimizer to account for common systematic risk across selected names,
rather than weighting stocks only by standalone alpha rank or standalone
volatility.

## Parameter Search Logic

The selection path had four stages.

| Stage | Evidence Kept | Purpose | Outcome |
|---|---|---|---|
| Coarse mini sweep | `config/experiments/mini_sweep/`; raw mini-sweep output folders are not tracked | Screen broad construction choices over covariance method, risk aversion, sector cap, and turnover cap. | Identified the useful region: `fundamental_factor`, `risk_aversion=3.0`, `turnover_cap=0.50`. |
| Micro-alpha sweep | `outputs/micro_alpha_sweeps/20260429T021834Z/` | Refine the best region around risk aversion and sector cap. | Selected `fund_ra3_s30_t50`. |
| Active-band research check | `docs/research_upgrade_activeband_20260428.md` | Test whether active-risk bands improve the optimizer. | Active-band improved development-period results but could not be promoted because no clean holdout remained. |
| Formal run | `outputs/formal_sweeps/20260429T031646Z/` and formal report | Freeze the final formal run and report. | Formal run id `6905e84b-9e16-4106-8c0f-cd9ecce56728`. |

## Coarse Mini Sweep Finding

The useful mini sweep batch was `20260429T003853Z`. It compared twelve
construction candidates:

- covariance method: `diagonal_shrinkage`, `fundamental_factor`,
  `statistical_factor`
- risk aversion: `3.0`, `4.0`
- sector cap: `0.20`, `0.25`
- turnover cap: `0.50`

The top candidate was:

| Candidate | Covariance | Risk Aversion | Sector Cap | Ann Return | Sharpe | IR | MDD |
|---|---|---:|---:|---:|---:|---:|---:|
| `fund_ra3_s25_t50` | `fundamental_factor` | `3.0` | `0.25` | `11.781409%` | `0.575151` | `0.105371` | `17.254137%` |

This result was not treated as the final strategy. Its role was to identify the
promising construction region. The later micro-alpha sweep then tested whether a
slightly wider sector cap around the same construction family improved the
formal objective.

## Micro-Alpha Refinement

The micro-alpha sweep at `outputs/micro_alpha_sweeps/20260429T021834Z/` compared
the refined candidate set around the mini-sweep winner.

| Rank | Candidate | Risk Aversion | Sector Cap | Ann Return | Sharpe | IR vs SPY | MDD |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `fund_ra3_s30_t50` | `3.0` | `0.30` | `11.939622%` | `0.582195` | `0.125923` | `17.130802%` |
| 2 | `fund_ra3_s25_t50` | `3.0` | `0.25` | `11.781409%` | `0.575151` | `0.105371` | `17.254137%` |
| 3 | `fund_ra2.5_s30_t50` | `2.5` | `0.30` | `11.388235%` | `0.553124` | `0.059603` | `17.440207%` |
| 4 | `fund_ra2.5_s25_t50` | `2.5` | `0.25` | `11.247105%` | `0.547150` | `0.040065` | `17.513210%` |

This is the direct evidence for selecting `risk_aversion=3.0` and
`max_sector_weight=0.30`. The `0.30` sector cap did not remove sector control;
it allowed the optimizer enough flexibility to express diversified alpha while
still preventing a single sector from dominating the portfolio.

## Why Active-Band Was Not Adopted

The active-band research note is intentionally retained in:

`team_Pearson/coursework_two/docs/research_upgrade_activeband_20260428.md`

That work showed a higher development-period candidate:

| Candidate | Scope | Sharpe | Interpretation |
|---|---|---:|---|
| `activeband_0125_025` | development-period research upgrade | `0.625678` | Improved development-period optimization result, not a clean final out-of-sample result. |

The key methodological issue is that the available holdout had already been
used in the previous search stage. Promoting the active-band result to the
formal strategy would therefore mix development-period improvement with an
already-consumed validation window. The final report deliberately keeps the
cleaner `ra3/s30` formal strategy rather than adopting a development-only
upgrade with a higher apparent Sharpe.

This decision is central to the strategy's credibility. It shows that the final
model was not selected by simply chasing the highest observed backtest metric.

## Final Formal Run

The formal run confirmed the selected candidate:

| Metric | Formal `fund_ra3_s30_t50` |
|---|---:|
| run id | `6905e84b-9e16-4106-8c0f-cd9ecce56728` |
| total return | `74.115402%` |
| annualized return | `11.939622%` |
| annualized volatility | `15.816019%` |
| Sharpe ratio | `0.582195` |
| max drawdown | `17.130802%` |
| information ratio vs SPY | `0.125923` |
| information ratio vs universe_ew | `0.451518` |
| raw beta vs SPY | `0.955289` |
| average holdings | `34.474576` |
| average monthly one-way turnover | `15.352812%` |

The formal run is therefore best described as a quarterly-native, regime-aware,
factor-driven, covariance-aware long-only U.S. equity strategy. Its value
proposition is not that it eliminates market risk. It remains a long-only equity
portfolio. Its contribution is the controlled conversion of economically
motivated alpha signals into an investable portfolio that improves return and
drawdown characteristics relative to the defined benchmark and control series.

## What To Keep And What To Ignore

The raw mini-sweep output directory is not part of the Git-tracked evidence set.
Its useful conclusion is summarized in this note. The retained evidence chain is:

- final formal config under `config/experiments/formal/`
- micro-alpha configs under `config/experiments/micro_alpha/`
- micro-alpha ranking under `outputs/micro_alpha_sweeps/20260429T021834Z/`
- formal sweep ranking under `outputs/formal_sweeps/20260429T031646Z/`
- active-band decision note under `docs/research_upgrade_activeband_20260428.md`
- formal report and `repro/` reference files

This keeps the repository professional and reproducible while avoiding obsolete
or misleading raw output folders.
