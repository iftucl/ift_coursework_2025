# CW2 Research Upgrade Snapshot

This note freezes the current end state of the April 28, 2026 CW2 research
upgrade work so later experiments can recover the exact parameter choice,
selection logic, and methodological boundaries.

## Scope

The strategy family in this note is the corrected `n30` quarterly-native CW2
portfolio construction stack. No new factors were added in this round. The work
focused on:

- development-period constrained parameter selection
- one prior holdout confirmation for the pre-active-band configuration
- a development-only mean-variance research upgrade using active-band
  constraints

## Methodology Boundary

This workflow should be read in two stages.

### Stage 1: constrained development search

- development / selection period: `2021-04-20` to `2024-09-30`
- holdout period used once: `2024-10-01` to `2026-04-20`
- objective: maximize Sharpe subject to pre-declared constraints
- candidate set: discrete, pre-declared, and local to the incumbent parameter
  neighborhood rather than a continuous global search

The round-1 search first selected:

- `risk_aversion = 5.0`
- `max_sector_weight = 0.22`

Best development-period run from stage 1:

- run id: `47663a1e-8adb-45f4-b9d1-5e3df5bd15df`
- manifest:
  `config/ablation/n30_dev_constrained_search_20260427.yaml`
- headline metrics:
  - annualized return: `12.479429%`
  - Sharpe: `0.610304`
  - max drawdown: `18.647627%`
  - information ratio vs `universe_ew`: `0.579233`

The associated holdout validation was then consumed once with:

- config:
  `config/ablation/ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_sector022_holdout_isolated.yaml`
- run id: `742e8ade-efa1-464a-9a08-b38a6144aefe`

This means that holdout window is no longer clean for subsequent parameter
search or model-selection claims.

### Stage 2: development-only active-band research upgrade

After the holdout had already been consumed, a second research round was run on
the same development period only. Its purpose was not to claim a new final
out-of-sample winner, but to test whether a more professional constrained
mean-variance formulation improves the strategy family.

The active-band search is defined by:

- manifest:
  `config/ablation/n30_dev_activeband_search_20260428.yaml`
- generated configs:
  `config/ablation/*activeband*_dev_isolated.yaml`
- scoring script:
  `scripts/score_constrained_search.py`

The active-band parameters constrain the optimizer's active deviation around the
anchor portfolio using:

- `max_active_overweight`
- `max_active_underweight`

This is a research-upgrade layer on top of the existing regularized
mean-variance setup rather than a factor-definition change.

## Frozen Current Best Development Configuration

As of this snapshot, the best development-period research-upgrade candidate is:

- `risk_aversion = 5.0`
- `max_sector_weight = 0.22`
- `max_active_overweight = 0.0125`
- `max_active_underweight = 0.025`

Frozen config path:

- `config/ablation/ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_sector022_activeband0125_025_dev_isolated.yaml`

Best development-period run:

- run id: `a720a496-e9bc-42e4-9b78-3f19c010a2cf`

Headline metrics:

- annualized return: `12.802950%`
- Sharpe: `0.625678`
- max drawdown: `18.135674%`
- information ratio vs `universe_ew`: `0.646253`
- raw beta vs `SPY`: `0.955341`
- avg monthly one-way turnover: `18.353063%`
- scorecard passed: `3`

## Final Ranking Of The Active-Band Development Search

Eligible candidates ranked by the pre-declared objective and constraints:

1. `activeband_0125_025`
   - run id: `a720a496-e9bc-42e4-9b78-3f19c010a2cf`
   - Sharpe: `0.625678`
2. `activeband_015_030`
   - run id: `e896e358-b15b-4d7a-9c8c-0a6130033f58`
   - Sharpe: `0.616064`
3. `activeband_010_020`
   - run id: `b5dddb37-c97f-43f4-8183-bce452099333`
   - Sharpe: `0.613915`
4. `incumbent_riskav5_sector022`
   - run id: `47663a1e-8adb-45f4-b9d1-5e3df5bd15df`
   - Sharpe: `0.610304`

## Interpretation

The current research conclusion is:

- active-band constrained mean-variance improves the strategy on the
  development period
- the best active-band setting is currently `0.0125 / 0.025`
- this result is a development-period research-upgrade finding, not a fresh
  final out-of-sample claim

Accordingly, the correct methodological statement is:

- the previous holdout result remains the only clean holdout confirmation from
  the first constrained-search round
- the active-band winner is the current best research candidate to carry
  forward into any later, newly defined validation design

## Recovery Rule

If later experiments underperform or the workspace needs to be restored to the
current best research-upgrade state, resume from:

- config:
  `config/ablation/ic_informed_prior_nosent_exec_tighter_mainline_inst_quarterly_qnative_v2_mainline_pitfix_n30_riskav5_sector022_activeband0125_025_dev_isolated.yaml`
- run id:
  `a720a496-e9bc-42e4-9b78-3f19c010a2cf`
- methodology note:
  this candidate is the best development-period result after the holdout was
  already consumed in stage 1
