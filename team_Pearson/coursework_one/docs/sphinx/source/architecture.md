# Architecture Overview

## 1. Objective

Provide a reproducible CW1 pipeline that can start from a fresh environment, ingest multi-source data, enforce quality checks, and persist analytics-ready datasets for Coursework Two.

## 2. System Architecture

```{figure} _static/diagrams/system_architecture.svg
:alt: End-to-end architecture of the CW1 data pipeline
:width: 100%
:align: center

Figure 1. End-to-end architecture of the CW1 data pipeline.
```

The figure documents the implemented architecture around five coordinated layers:

<div>（1）<code>Inputs</code>: dynamic universe control in PostgreSQL, Source A structured market/fundamental extraction, and Source B unstructured news extraction.</div>
<div>（2）<code>Core Pipeline</code>: extraction, normalization and quality checks, curated atomic loading, and final factor construction.</div>
<div>（3）<code>Curated Storage</code>: MinIO source-layer replay storage together with PostgreSQL curated atomics and factor persistence.</div>
<div>（4）<code>Governance &amp; Audit</code>: run audit, quality evidence, metadata governance, and the local run-log mirror.</div>
<div>（5）<code>Optional Serving</code>: MongoDB news indexing for searchable serving of Source B records.</div>

Current implementation: dynamic universe selection, trading-day market inputs, quarterly financial atomics, MinIO source-layer replay storage, PostgreSQL curated storage and factor persistence, daily factor construction, and optional MongoDB news serving.

Implementation note:
- the atomic layer is incrementally materialized per work unit;
- run-level manifest/materialization state tracks planned, reused, skipped, failed, and completed units;
- final factor construction starts only after the manifest completion gate is satisfied.
- team-specific Docker networking is defined in the Pearson override file rather than in the repository-level compose file, so submission changes remain confined to the team folder.

## 3. End-to-End Data Flow

<div>（1）Resolve runtime parameters with precedence: <code>CLI &gt; .env &gt; config/conf.yaml &gt; defaults</code>.</div>
<div>（2）Read dynamic universe from PostgreSQL <code>systematic_equity.company_static</code>.</div>
<div>（3）Plan run-level work units and orchestration state (symbols, Source B symbol-month windows, materialization reuse, completion gate).</div>
<div>（4）Run extraction:</div>
<ul style="margin-top: 0.2rem; margin-bottom: 0.2rem;">
<li>Source A: market and fundamentals</li>
<li>Source B: news and sentiment</li>
</ul>
<div>（5）Archive raw payloads to MinIO for replay and auditability.</div>
<div>（6）Normalize atomic records and accumulate quality evidence as work units complete.</div>
<div>（7）Incrementally upsert curated atomic data to PostgreSQL in bounded batches:</div>
<ul style="margin-top: 0.2rem; margin-bottom: 0.2rem;">
<li><code>factor_observations</code></li>
<li><code>financial_observations</code></li>
<li><code>pipeline_runs</code></li>
</ul>
<div>（8）After all planned atomic units reach a terminal manifest state, compute final factors (<code>modules.transform.factors</code>) and write back to curated factors.</div>
<div>（9）Index Source B records into MongoDB <code>ift_cw.news_articles</code> by default after successful runs (<code>Main.py</code> and scheduler/orchestrator scripts); disable explicitly with <code>--no-index-mongo</code>.</div>
<ul style="margin-top: 0.2rem; margin-bottom: 0.2rem;">
<li>Mongo indexing is intentionally handled as a post-run serving step (best-effort).</li>
</ul>
<div>（10）Persist metadata governance state:</div>
<ul style="margin-top: 0.2rem; margin-bottom: 0.2rem;">
<li><code>dataset_registry</code></li>
<li><code>schema_versions</code></li>
<li><code>lineage_edges</code></li>
<li><code>quality_snapshots</code></li>
</ul>

## 4. Storage Topology

### MinIO (raw data lake)

- `raw/source_a/pricing_fundamentals/run_date={YYYY-MM-DD}/year={YYYY}/symbol={SYMBOL}.json`
- `raw/source_b/news/run_date={YYYY-MM-DD}/year={YYYY}/month={MM}/symbol={SYMBOL}.jsonl`

### PostgreSQL (curated, audit, metadata)

- Curated data:
  - `systematic_equity.factor_observations`
  - `systematic_equity.financial_observations`
- Run audit:
  - `systematic_equity.pipeline_runs`
- Metadata management:
  - `systematic_equity.dataset_registry`
  - `systematic_equity.schema_versions`
  - `systematic_equity.lineage_edges`
  - `systematic_equity.quality_snapshots`

### MongoDB (serving index; enabled by default in `Main.py` and scheduler/orchestrator scripts)

- `ift_cw.news_articles`

## 5. Reliability and Idempotency

| Control point | Mechanism |
| --- | --- |
| Factor deduplication | Unique key `(symbol, observation_date, factor_name)` |
| Financial deduplication | Unique key `(symbol, report_date, metric_name)` |
| Rerun safety | Upsert-based loaders in output layer |
| Run traceability | `pipeline_runs` status lifecycle (`running/success/failed`) |

## 6. Scheduling and Frequency Flexibility

- Main runtime supports `--run-date` and `--frequency`.
- Scheduler wrapper supports frequency selection:
  `--only daily,weekly,monthly,quarterly`.
- Auto job script is intentionally fixed to daily for production default behavior.

## 7. Quality and Security Gates

| Area | Tooling / script |
| --- | --- |
| Data consistency | `scripts/validate_pipeline_data.py` |
| Automated tests | `pytest` with coverage threshold (`>=80%`) |
| Static security checks | `bandit` |
| Dependency vulnerability checks | `safety` |

## 8. Acceptance Checklist (From Zero)

<div>（1）Start containers (PostgreSQL, MongoDB, MinIO).</div>
<div>（2）Run schema bootstrap (<code>scripts/init_db.py</code>).</div>
<div>（3）Execute pipeline run (<code>Main.py</code> or small-sample wrapper).</div>
<div>（4）Validate loaded data (<code>validate_pipeline_data.py</code>).</div>
<div>（5）Confirm records exist in all required stores.</div>
