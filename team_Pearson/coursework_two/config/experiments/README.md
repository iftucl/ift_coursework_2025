# Experiment Configs

This directory contains reproducible strategy-selection evidence. It is not a
set of alternative final strategies.

The final formal strategy is:

`formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`

The default coursework-two config also matches that formal strategy:

`../conf.yaml`

## Directory Meaning

| Path | Purpose |
|---|---|
| `formal/` | Final formal configuration and one retained S25 comparator. Use `cw2_formal_20260420_fund_ra3_s30_t50.yaml` for the reported strategy. |
| `micro_alpha/` | Fine search around the selected `fundamental_factor` covariance method, risk aversion, and sector-cap region. |
| `mini_sweep/` | Coarse search over covariance method, risk aversion, sector cap, and turnover cap. |
| root `cw2_*_20260420.yaml` files | Earlier covariance-method development checks. These are retained as method-selection evidence only and are not final-report configs. |

For the full selection logic, see:

`team_Pearson/coursework_two/docs/strategy_design_decision_log_20260420.md`
