# Reference Strategy Summary

This note is intended to travel with the code archive. The codebase contains a
wider set of optional features than the strategy actually reported in the
coursework. This document therefore states which configuration should now be
treated as the current formal baseline, what it actively used, and which
implemented modules were not switched on in the final reported setup.

## Current Formal Baseline

- Formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Formal run name: `cw2_formal_20260420_fund_ra3_s30_t50`
- Pinned configuration: `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- Formal report: `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report`
- Formal summary: `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report_summary.json`
- Primary benchmark: `SPY`
- Secondary comparison: `universe_ew`
- Construction-layer control: `static_baseline`

This configuration should be treated as authoritative when interpreting the
current CW2 formal strategy. The codebase shows what is possible; this pinned
configuration shows what should now be treated as the operative baseline.

## Historical Release Boundary

Older frozen handoff assets under `team_Pearson/coursework_two/outputs/handoff/`
and legacy qnative reports may exist in local workspaces or old release
packages, but they are not the current Git-tracked reproduction path. They
should not be used as the current formal reference. For current strategy
interpretation and benchmark discussion, the formal run above takes precedence.

## Strategy Actually Used

- Universe scope: US equities only, with additional investable-universe screens on size and liquidity.
- Factor groups used in the composite model: quality, value, market technical, sentiment, and dividend.
- Regime model: VIX and term-spread hysteresis.
- Normal-regime factor weights: quality `0.18`, value `0.24`, market technical `0.43`, sentiment `0.00`, dividend `0.15`.
- Stress-regime factor weights: quality `0.40`, value `0.10`, market technical `0.05`, sentiment `0.05`, dividend `0.40`.
- Preprocessing: winsorisation at `2.5%`, minimum `30` observations, sector neutralisation by `gics_sector`.
- Risk overlay: `volatility_60d` screen plus optional percentile blacklists on `garch_vol_60d` and `realized_vol_60d`, with at least three factor groups required and quality, value, and market technical treated as mandatory.
- Portfolio construction: quarterly target generation, long-only, fundamental-factor covariance-aware mean-variance weighting, hybrid selection with a 25-35 name range, `5%` maximum single-name weight, `30%` maximum sector weight, `50%` turnover cap, and risk aversion `3.0`.
- Factor covariance risk model: `covariance.method = fundamental_factor`, with style exposures `market_beta`, `size`, `value`, `momentum`, `quality`, `volatility`, `liquidity`, and `dividend`, plus sector exposures. This is the optimizer's risk model and should not be confused with the five alpha factor groups.
- Backtest setup: quarterly rebalance, one-day execution lag, `15 bps` transaction cost, `SPY` as the primary benchmark, `universe_ew` as the secondary comparison, and `static_baseline` as the construction-layer control.

## Important Interpretation Note

The formal configuration name no longer uses the legacy `nosent` label. The
sentiment group remains part of the five-factor architecture and is stored in
the feature tables. In the formal regime weights, sentiment carries zero weight
in the normal regime and a small residual weight of `0.05` in the stress regime.

## Implemented In Code But Not Used In The Benchmark Strategy

- Drawdown brake: implemented, but `enabled: false`.
- Intraday trigger framework: implemented, but `enabled: false`.
- Event-driven intraday actions: implemented, but `event_driven_enabled: false`.
- News-sentiment shock trigger: implemented, but `news_sentiment_shock_enabled: false`.
- Earnings-triggered intraday actions: implemented, but `earnings_event_enabled: false`.
- Rating-downgrade intraday actions: implemented, but `rating_downgrade_event_enabled: false`.
- Mid-frequency rebalancing inside the intraday module: implemented, but `mid_frequency_rebalance_enabled: false`.
- IC-based dynamic regime reweighting: implemented, but `ic_weighting.enabled: false`.

In short, the formal strategy is a quarterly, long-only, factor-covariance-aware
mean-variance portfolio driven primarily by quality, value, market-technical,
and dividend information, with regime conditioning from VIX and the term spread.
The codebase includes richer intraday and event-driven controls, but those
controls were designed as optional extensions and were not active in the formal
configuration.

## Reproduction Boundary

This summary is sufficient to identify the intended formal specification. It is
not, on its own, enough to reproduce the exact reported performance numbers.
Exact numerical reproduction still depends on the matching runtime state and
report artefacts for run `6905e84b-9e16-4106-8c0f-cd9ecce56728`, or on a frozen
release package generated with the formal run id and formal configuration.
