# Orchestration and Eventing

## Airflow Coverage

The platform now uses Airflow beyond the original upstream-only scope.

### Recurring DAG

`cw1_pipeline_and_docs`

- runs the scheduled `CW1` pipeline
- validates curated data
- builds Sphinx HTML
- writes one daily `CW2` update decision
- triggers rebalance-anchor-gated `CW2 operate`

### Scheduled monthly CW2 DAGs

`cw2_backtest_analysis_report`

- preflight readiness audit
- backtest
- analyse
- report
- reference verification
- Kafka audit
- context cleanup

`cw2_monthly_snapshot_backfill`

- historical month-end `portfolio_target_positions` backfill
- post-backfill readiness audit
- Kafka audit
- context cleanup

## Scheduler-Safe Wrappers

Airflow uses wrapper scripts rather than embedding large business logic in DAG files.

Examples:

- `scripts/run_scheduled_pipeline.py`
- `coursework_two/scripts/run_update_decision.py`
- `coursework_two/scripts/run_operated_flow.py`
- `coursework_two/scripts/run_backtest_analysis_report.py`
- `coursework_two/scripts/backfill_monthly_snapshots.py`
- `coursework_two/scripts/run_readiness_audit.py`
- `coursework_two/scripts/run_kafka_event_audit.py`
- `coursework_two/scripts/run_full_chain.py`

## Kafka Role

Kafka is an **optional event bus**, not the canonical data store.

Its role is:

- fan out structured news events
- fan out daily event proxies
- fan out requested risk actions
- fan out executed risk actions
- fan out run-status events

This lets multiple downstream consumers react without overloading the SQL truth path.
Consumer audit state is then written back into SQL through
`ops_kafka_consumer_ack`, `ops_kafka_dead_letter`, and
`ops_kafka_lag_snapshots`, with `cw2_kafka_audit_consumer` keeping the live
consumer side fresh between scheduled audits.

## Current Topic Families

- `cw1.news.structured.v1`
- `cw1.event.proxies.v1`
- `cw2.risk.actions.requested.v1`
- `cw2.risk.actions.executed.v1`
- `platform.runs.status.v1`

## Operational Principle

The platform uses a hybrid model:

- **batch core**
  - SQL truth
  - MinIO replay
  - Airflow orchestration

- **control plane**
  - Redis runtime locks
  - SQL-backed pipeline/stage trace
  - quality snapshots and readiness gates

- **incremental event layer**
  - Kafka fan-out
  - daily update decisions
  - daily risk actions
  - status notifications

This keeps the system production-style and auditable without turning the whole stack into a stream-native trading platform.
