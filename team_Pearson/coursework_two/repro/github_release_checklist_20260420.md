# GitHub Release Checklist For The 2026-04-20 CW2 Formal Run

This note is the publication checklist for the frozen GitHub release bundle that
supports exact reproduction of the current formal CW2 reference run.

Repository remote:

- `celiahkkd-byte/ift_coursework_2025_Team_Pearson`

Formal reference run:

- run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- run name: `cw2_formal_20260420_fund_ra3_s30_t50`
- config:
  `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- report:
  `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`

Suggested release identity:

- tag: `cw2-formal-s30-20260420`
- title: `CW2 formal S30 reference bundle - 2026-04-20`

## Generate The Release Assets

Run this from the repository root in the environment that contains the formal
run and its upstream data:

```bash
team_Pearson/coursework_two/scripts/export_repro_bundle.sh \
  --export-date 20260420 \
  --label formal_s30 \
  --reference-run-id 6905e84b-9e16-4106-8c0f-cd9ecce56728 \
  --reference-run-name cw2_formal_20260420_fund_ra3_s30_t50 \
  --config-path team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

## Upload These Five Files

Upload these generated files from `team_Pearson/coursework_two/outputs/handoff/`
to the GitHub release:

- `cw2_postgres_export_20260420_formal_s30.tar.gz`
- `cw2_upstream_export_20260420_formal_s30.tar.gz`
- `cw2_postgres_export_20260420_formal_s30.tar.gz.sha256`
- `cw2_upstream_export_20260420_formal_s30.tar.gz.sha256`
- `cw2_repro_bundle_20260420_formal_s30.json`

Do not upload older qnative recovery tarballs or any previous qnative export as
the formal release bundle.

## What The Teacher Should Do

1. Clone the repository.
2. Open the matching GitHub release and download the five assets above.
3. Start the project containers exactly as documented in
   `team_Pearson/coursework_two/README.md`.
4. Restore the frozen data state:

```bash
team_Pearson/coursework_two/scripts/restore_repro_bundle.sh \
  --bundle-dir /path/to/downloaded-release-assets
```

5. Re-render the saved formal run:

```bash
team_Pearson/coursework_one/.venv/bin/python \
  team_Pearson/coursework_two/scripts/run_backtest_analysis_report.py \
  --run-id 6905e84b-9e16-4106-8c0f-cd9ecce56728 \
  --report-name cw2_formal_fund_ra3_s30_t50_20260420_report \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

6. Verify the regenerated report against the checked-in reference contract:

```bash
team_Pearson/coursework_one/.venv/bin/python \
  team_Pearson/coursework_two/scripts/verify_reference_metrics.py \
  --summary-path team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report_summary.json
```

## Copy-Paste Release Body

Paste the block below into the GitHub release description after the formal
assets have been generated.

```md
Frozen CW2 reproducibility bundle for the formal reference run.

Reference run:
- run_id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- run_name: `cw2_formal_20260420_fund_ra3_s30_t50`
- config: `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- primary_benchmark: `SPY`
- secondary_benchmark: `universe_ew`
- construction_control: `static_baseline`

Reference metrics:
- total_return: `74.115402%`
- annualized_return: `11.939622%`
- annualized_volatility: `15.816019%`
- sharpe_ratio: `0.582195`
- max_drawdown: `17.130802%`
- information_ratio_vs_primary_spy: `0.125923`
- benchmark_total_return_spy: `67.755749%`
- excess_annualized_return_vs_primary_spy: `0.843966%`

This release contains the frozen PostgreSQL and upstream data bundle needed for
exact reproduction of the saved formal run from a fresh repository clone.

How to reproduce:
1. Clone this repository.
2. Start the containers documented in `team_Pearson/coursework_two/README.md`.
3. Download all assets from this release.
4. Restore them with:
   `team_Pearson/coursework_two/scripts/restore_repro_bundle.sh --bundle-dir /path/to/downloaded-release-assets`
5. Re-render the saved run with:
   `team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/scripts/run_backtest_analysis_report.py --run-id 6905e84b-9e16-4106-8c0f-cd9ecce56728 --report-name cw2_formal_fund_ra3_s30_t50_20260420_report --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
6. Verify the resulting report with:
   `team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/scripts/verify_reference_metrics.py --summary-path team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report_summary.json`

The exact acceptance contract is tracked in:
- `team_Pearson/coursework_two/repro/README.md`
- `team_Pearson/coursework_two/repro/reference_run_20260420.json`
```
