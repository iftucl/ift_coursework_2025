# Benchmark Methodology

CW2 reports three comparison series. They are not interchangeable benchmarks:
each one answers a different evaluation question.

| Series | Role | Cost Treatment | Analytical Question |
| --- | --- | --- | --- |
| `SPY` | Primary benchmark | Buy-and-hold market reference with no strategy execution cost model | Does the strategy add value relative to passive U.S. equity market exposure? |
| `universe_ew` | Secondary same-universe opportunity-set comparison | Gross of trading costs by default | Does the strategy add value beyond naive equal-weight exposure to the same investable universe? |
| `static_baseline` | Construction-layer control | Net of configured trading costs, currently 15 bps in the formal configuration | What is the marginal value of dynamic construction, optimization, and regime-aware alpha design relative to a tradable static baseline? |

## Why `SPY` Is Primary

`SPY` is the formal primary benchmark because it represents the external passive
U.S. equity exposure that a long-only strategy must justify itself against. The
backtest stores the market benchmark path separately from strategy execution
costs, so `SPY` is treated as a buy-and-hold reference rather than as a
portfolio reconstructed by the CW2 execution engine.

## Why `universe_ew` Is Gross Of Costs

`universe_ew` is a same-universe reference index. At each backtest period it
equal-weights the available investable universe and measures the opportunity set
without applying the strategy execution-cost model.

This is deliberate. Its purpose is to separate stock-universe exposure from
active signal and construction decisions. Applying a trading-cost model to
`universe_ew` would turn it into a separate implementable strategy assumption
rather than a clean opportunity-set comparison. Comparing the net strategy
against gross `universe_ew` is also conservative for the strategy, because the
comparison line is not penalised for turnover.

## Why `static_baseline` Is Net Of Costs

`static_baseline` is a tradable construction-layer counterfactual. It is rebuilt
from the same CW2 factor stack and rebalance path, but removes the dynamic
regime-aware weighting and optimization choices that distinguish the main
strategy.

Because it is intended to be an implementable alternative portfolio, it is
charged the configured trading cost. In the formal configuration this is 15 bps.
That makes it the appropriate control for the marginal value of the construction
and regime design.

## Configuration Contract

The formal configuration follows this benchmark hierarchy:

- `primary_benchmark: SPY`
- `secondary_benchmark: universe_ew`
- `universe_ew_deduct_cost: false`
- `static_baseline_cost_bps: 15`

The report generator preserves this distinction in the benchmark methodology
section and in `report_summary.json`, so the markdown report, JSON summary, and
database-backed analysis tables use the same interpretation.
