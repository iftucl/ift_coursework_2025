# Ablation And Research Configs

This directory is not the final strategy entrypoint.

The final formal strategy is pinned at:

`team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`

The default coursework-two config is also aligned to that formal strategy:

`team_Pearson/coursework_two/config/conf.yaml`

The small set of YAML files retained here is development evidence for the
constrained-search and active-band research note:

`team_Pearson/coursework_two/docs/research_upgrade_activeband_20260428.md`

## Retained Evidence

| Config | Role |
|---|---|
| `n30_dev_constrained_search_20260427.yaml` | Stage 1 constrained-search manifest before the active-band research upgrade. |
| `n30_dev_activeband_search_20260428.yaml` | Stage 2 active-band development search manifest. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_dev_isolated.yaml` | Stage 1 development baseline candidate. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_dev_isolated.yaml` | Stage 1 risk-aversion candidate. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_ridge008_dev_isolated.yaml` | Stage 1 ridge-penalty candidate. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_ridge010_dev_isolated.yaml` | Stage 1 ridge-penalty candidate. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_turnover001_dev_isolated.yaml` | Stage 1 turnover-penalty candidate. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_sector022_dev_isolated.yaml` | Development baseline before active-band constraints. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_sector022_holdout_isolated.yaml` | Holdout validation consumed before active-band promotion was considered. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_sector022_activeband010_020_dev_isolated.yaml` | Active-band development candidate. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_sector022_activeband0125_025_dev_isolated.yaml` | Best active-band development candidate. |
| `ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_sector022_activeband015_030_dev_isolated.yaml` | Active-band development candidate. |

## Interpretation

These configs are included to document the research path and model-selection
discipline. They are not used to reproduce the final reported portfolio.

The active-band candidate improved development-period results, but it is not
the formal strategy because the clean holdout had already been consumed by the
previous constrained-search round. Promoting it directly would weaken the
out-of-sample claim.

Older monthly, qnative, equal-weight, and early mainline ablation configs were
removed from the delivery repository because they are no longer required for
formal strategy reproduction and were easy to confuse with the final S30
configuration.
