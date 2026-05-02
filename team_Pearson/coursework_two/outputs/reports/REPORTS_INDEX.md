# CW2 Reports Index

This index tracks report-facing CW2 outputs that should be visible to reviewers.
Generated bulky CSV, PNG, PDF, DOCX, and ZIP artifacts remain outside normal
source control unless explicitly packaged for handoff.

| Status | Report family | Run id / scope | Config path | Output location | Notes |
|---|---|---|---|---|---|
| mainline | Formal S30 baseline | `6905e84b-9e16-4106-8c0f-cd9ecce56728` | `config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml` | `inputs/formal_slim_6905_20260420_extracted/formal_slim_6905_20260420/key_artifacts/formal_report` | Teacher-facing baseline; quarterly target generation and quarterly rebalance, monthly performance records. |
| evidence | Robustness evidence pack | `formal_fast_6905_20260429` | `config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml` | `outputs/robustness/report_evidence` | Part 1-Part 5 robustness evidence aligned to the formal SPY baseline. |
| evidence | Requirement revision tables | `formal_fast_6905_20260429` | `config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml` | `outputs/robustness/report_evidence` | Final robustness wording and SPY-specific correction tables for the report revision workflow. |
| active | Web report studio history | local session scope | `web/main.js`, `api/main.py` | `outputs/web_state/ai_reports` | Local AI report registry and text-based PDF exports. API keys remain session-local and hidden. |
| archived | Legacy report handoff | legacy scope | superseded | `outputs/robustness/report_handoff` | Migrated to `report_evidence` naming when present; not the preferred final reference. |

## Reproducibility Notes

- Formal baseline run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Formal portfolio: `cw2_formal_20260420_fund_ra3_s30_t50`
- Data cutoff: `2026-04-20`
- Latest formal quarterly target snapshot: `2026-03-31`
- Baseline benchmark for the final report: `SPY`

The formal strategy is not a monthly rebalance. Target weights are generated
quarterly, trades execute on the configured lag, and monthly rows record holding
period returns, turnover, Sharpe, IR, drawdown, and monitoring diagnostics.
