# CW2 Exact Reproduction

This directory defines the formal exact-reproduction contract for the
current formal CW2 reference run.

The repository tracks:

- the current formal reference metrics in
  `team_Pearson/coursework_two/repro/reference_run_20260420.json`
- the current formal human-readable summary in
  `team_Pearson/coursework_two/repro/reference_summary_20260420.md`
- helper scripts to export, restore, and verify the frozen reproducibility
  bundle

The repository does **not** track the large Docker-level data bundle itself.
Exact frozen-state reproduction of the formal reference run requires two GitHub
release assets generated from the formal local environment:

- `cw2_postgres_export_20260420_formal_s30.tar.gz`
- `cw2_upstream_export_20260420_formal_s30.tar.gz`

Older qnative release assets must not be used as the formal 6905 reproduction
bundle.

Current formal run identity:

- run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- run name: `cw2_formal_20260420_fund_ra3_s30_t50`
- config: `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- report: `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`

Formal release assets should be created with:

```bash
team_Pearson/coursework_two/scripts/export_repro_bundle.sh \
  --export-date 20260420 \
  --label formal_s30 \
  --reference-run-id 6905e84b-9e16-4106-8c0f-cd9ecce56728 \
  --reference-run-name cw2_formal_20260420_fund_ra3_s30_t50 \
  --config-path team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

The export script writes tarballs, `.sha256` sidecars, and a JSON manifest to
`team_Pearson/coursework_two/outputs/handoff/`.

## Publishing The GitHub Release

Use the release checklist in
`team_Pearson/coursework_two/repro/github_release_checklist_20260420.md`.

That checklist records:

- the suggested release tag and title
- the exact five files to upload to GitHub Releases
- the command that generates checksum sidecars for the formal bundle
- a copy-paste release body for the GitHub UI

## Exact Reproduction Flow

From a fresh clone:

1. Start the existing project containers exactly as documented in the main
   README.
2. Download the matching GitHub release assets for the formal reference run.
3. Restore the frozen PostgreSQL, MongoDB, and MinIO state:

```bash
team_Pearson/coursework_two/scripts/restore_repro_bundle.sh \
  --bundle-dir /path/to/downloaded-release-assets
```

4. Load `.env` as usual.
5. Re-render the formal saved run from the restored frozen database state:

```bash
team_Pearson/coursework_one/.venv/bin/python \
  team_Pearson/coursework_two/scripts/run_backtest_analysis_report.py \
  --run-id 6905e84b-9e16-4106-8c0f-cd9ecce56728 \
  --report-name cw2_formal_fund_ra3_s30_t50_20260420_report \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

6. Verify the regenerated report against the tracked reference metrics:

```bash
team_Pearson/coursework_one/.venv/bin/python \
  team_Pearson/coursework_two/scripts/verify_reference_metrics.py \
  --summary-path team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report_summary.json
```

## Important Scope Note

Older qnative recovery snapshots are historical material only and should not be
presented as the exact GitHub reproducibility bundle for formal run
`6905e84b-9e16-4106-8c0f-cd9ecce56728`.
