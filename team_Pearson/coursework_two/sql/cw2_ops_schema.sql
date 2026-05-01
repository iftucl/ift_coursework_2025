-- CW2 Operational Decision Schema
-- Stores rule-driven daily decisions about whether the platform should
-- monitor only, perform risk review, or execute a full rebalance flow.

CREATE TABLE IF NOT EXISTS systematic_equity.portfolio_update_decisions (
    decision_id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date                       DATE            NOT NULL,
    portfolio_name                 VARCHAR(100)    NOT NULL,
    decision_scope                 VARCHAR(30)     NOT NULL
        CHECK (decision_scope IN ('monitor_only', 'risk_review', 'full_rebalance', 'blocked')),
    recommended_mode               VARCHAR(40)     NOT NULL,
    reason_code                    VARCHAR(80)     NOT NULL,
    is_month_end_rebalance_day     BOOLEAN         NOT NULL DEFAULT FALSE,
    requires_human_review          BOOLEAN         NOT NULL DEFAULT FALSE,
    latest_snapshot_as_of_date     DATE,
    latest_recommendation_as_of_date DATE,
    signal_as_of_date              DATE,
    latest_snapshot_position_count INTEGER,
    trigger_symbol_count           INTEGER         NOT NULL DEFAULT 0,
    trigger_summary_json           JSONB,
    config_snapshot                JSONB,
    created_at                     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_portfolio_update_decision
        UNIQUE (run_date, portfolio_name)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_update_decisions_run_date
    ON systematic_equity.portfolio_update_decisions (run_date, portfolio_name);

ALTER TABLE systematic_equity.portfolio_update_decisions
    ALTER COLUMN portfolio_name TYPE VARCHAR(100);

ALTER TABLE systematic_equity.portfolio_update_decisions
    ADD COLUMN IF NOT EXISTS signal_as_of_date DATE;

-- Pipeline-level operational run ledger.
-- Stores one upserted execution record per scheduler-controlled pipeline key so
-- Airflow, Redis coordination, and Kafka lifecycle events can be joined to a
-- single SQL control-plane row.

CREATE TABLE IF NOT EXISTS systematic_equity.ops_pipeline_runs (
    ops_pipeline_run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_name                    VARCHAR(120)    NOT NULL,
    execution_key                    VARCHAR(255)    NOT NULL,
    trigger_source                   VARCHAR(40)     NOT NULL DEFAULT 'manual'
        CHECK (trigger_source IN ('manual', 'airflow', 'script', 'api')),
    airflow_dag_id                   VARCHAR(200),
    airflow_dag_run_id               VARCHAR(255),
    latest_task_id                   VARCHAR(200),
    latest_stage_name                VARCHAR(120),
    run_id                           VARCHAR(80),
    report_id                        VARCHAR(80),
    status                           VARCHAR(20)     NOT NULL DEFAULT 'running'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped', 'warning')),
    started_at                       TIMESTAMPTZ,
    completed_at                     TIMESTAMPTZ,
    duration_ms                      BIGINT,
    context_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    metrics_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    error_text                       TEXT,
    created_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_ops_pipeline_runs
        UNIQUE (pipeline_name, execution_key)
);

CREATE INDEX IF NOT EXISTS idx_ops_pipeline_runs_status
    ON systematic_equity.ops_pipeline_runs (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_pipeline_runs_airflow
    ON systematic_equity.ops_pipeline_runs (airflow_dag_id, airflow_dag_run_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_pipeline_runs_run_id
    ON systematic_equity.ops_pipeline_runs (run_id, updated_at DESC);

-- Stage-level operational run ledger.
-- Complements ops_pipeline_runs with per-stage timing, Redis lock metadata, and
-- result payloads for scheduler-visible execution checkpoints.

CREATE TABLE IF NOT EXISTS systematic_equity.ops_stage_runs (
    ops_stage_run_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_name                    VARCHAR(120)    NOT NULL,
    stage_name                       VARCHAR(120)    NOT NULL,
    execution_key                    VARCHAR(255)    NOT NULL,
    stage_order                      INTEGER,
    trigger_source                   VARCHAR(40)     NOT NULL DEFAULT 'manual'
        CHECK (trigger_source IN ('manual', 'airflow', 'script', 'api')),
    airflow_dag_id                   VARCHAR(200),
    airflow_dag_run_id               VARCHAR(255),
    airflow_task_id                  VARCHAR(200),
    run_id                           VARCHAR(80),
    report_id                        VARCHAR(80),
    stage_status                     VARCHAR(20)     NOT NULL DEFAULT 'started'
        CHECK (stage_status IN ('started', 'running', 'completed', 'failed', 'skipped', 'warning')),
    lock_name                        VARCHAR(255),
    lock_backend                     VARCHAR(40),
    lock_key                         VARCHAR(255),
    idempotency_key                  VARCHAR(255),
    started_at                       TIMESTAMPTZ,
    completed_at                     TIMESTAMPTZ,
    duration_ms                      BIGINT,
    payload_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    result_json                      JSONB           NOT NULL DEFAULT '{}'::JSONB,
    error_text                       TEXT,
    created_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_ops_stage_runs
        UNIQUE (pipeline_name, stage_name, execution_key)
);

CREATE INDEX IF NOT EXISTS idx_ops_stage_runs_status
    ON systematic_equity.ops_stage_runs (stage_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_stage_runs_pipeline
    ON systematic_equity.ops_stage_runs (pipeline_name, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_stage_runs_airflow
    ON systematic_equity.ops_stage_runs (airflow_dag_id, airflow_dag_run_id, airflow_task_id, updated_at DESC);

-- Operational monitoring event log.
-- Mirrors key Kafka-published events into a queryable SQL table so the
-- platform has an auditable ops trail even though Kafka is not the
-- canonical research store.

CREATE TABLE IF NOT EXISTS systematic_equity.ops_event_log (
    ops_event_log_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                         VARCHAR(255)    NOT NULL,
    event_time                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    event_type                       VARCHAR(80)     NOT NULL,
    producer_component               VARCHAR(80)     NOT NULL,
    topic_key                        VARCHAR(80),
    topic_name                       VARCHAR(200),
    run_id                           VARCHAR(80),
    symbol                           VARCHAR(20),
    severity                         VARCHAR(20)     NOT NULL DEFAULT 'info'
        CHECK (severity IN ('info', 'warning', 'critical')),
    publish_status                   VARCHAR(20)     NOT NULL DEFAULT 'recorded'
        CHECK (publish_status IN ('recorded', 'published', 'suppressed', 'disabled')),
    payload_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    created_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_ops_event_log
        UNIQUE (event_id, producer_component)
);

CREATE INDEX IF NOT EXISTS idx_ops_event_log_event_time
    ON systematic_equity.ops_event_log (event_time DESC);

CREATE INDEX IF NOT EXISTS idx_ops_event_log_run_id
    ON systematic_equity.ops_event_log (run_id, event_time DESC);

CREATE INDEX IF NOT EXISTS idx_ops_event_log_event_type
    ON systematic_equity.ops_event_log (event_type, event_time DESC);

-- Consumer-side acknowledgement log for Kafka event audit.
-- This closes the loop from producer-side publication into one SQL-backed
-- consumer trail with consumed / processed / failed / dead-lettered states.

CREATE TABLE IF NOT EXISTS systematic_equity.ops_kafka_consumer_ack (
    ops_kafka_consumer_ack_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                         VARCHAR(255)    NOT NULL,
    topic_name                       VARCHAR(200)    NOT NULL,
    consumer_group                   VARCHAR(120)    NOT NULL,
    consumer_component               VARCHAR(120)    NOT NULL,
    kafka_partition                  INTEGER         NOT NULL,
    kafka_offset                     BIGINT          NOT NULL,
    message_key                      VARCHAR(255),
    event_type                       VARCHAR(80),
    run_id                           VARCHAR(80),
    symbol                           VARCHAR(20),
    consumed_at                      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    processed_at                     TIMESTAMPTZ,
    ack_status                       VARCHAR(20)     NOT NULL DEFAULT 'consumed'
        CHECK (ack_status IN ('consumed', 'processed', 'failed', 'dead_lettered')),
    retry_count                      INTEGER         NOT NULL DEFAULT 0,
    last_error                       TEXT,
    payload_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    headers_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    created_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_ops_kafka_consumer_ack
        UNIQUE (topic_name, consumer_group, kafka_partition, kafka_offset)
);

CREATE INDEX IF NOT EXISTS idx_ops_kafka_consumer_ack_event_id
    ON systematic_equity.ops_kafka_consumer_ack (event_id, consumer_group, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_kafka_consumer_ack_status
    ON systematic_equity.ops_kafka_consumer_ack (ack_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_kafka_consumer_ack_group_time
    ON systematic_equity.ops_kafka_consumer_ack (consumer_group, consumed_at DESC);

-- SQL-backed dead-letter store for events that exceed the configured retry
-- budget inside the audit consumer.

CREATE TABLE IF NOT EXISTS systematic_equity.ops_kafka_dead_letter (
    ops_kafka_dead_letter_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                         VARCHAR(255)    NOT NULL,
    topic_name                       VARCHAR(200)    NOT NULL,
    consumer_group                   VARCHAR(120)    NOT NULL,
    consumer_component               VARCHAR(120)    NOT NULL,
    kafka_partition                  INTEGER         NOT NULL,
    kafka_offset                     BIGINT          NOT NULL,
    message_key                      VARCHAR(255),
    event_type                       VARCHAR(80),
    run_id                           VARCHAR(80),
    symbol                           VARCHAR(20),
    dead_letter_reason               VARCHAR(80)     NOT NULL,
    error_text                       TEXT,
    payload_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    headers_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    created_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_ops_kafka_dead_letter
        UNIQUE (topic_name, consumer_group, kafka_partition, kafka_offset)
);

CREATE INDEX IF NOT EXISTS idx_ops_kafka_dead_letter_created_at
    ON systematic_equity.ops_kafka_dead_letter (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_kafka_dead_letter_group
    ON systematic_equity.ops_kafka_dead_letter (consumer_group, created_at DESC);

-- Lag snapshots for Kafka consumer groups.
-- These snapshots make it possible to audit backlog and freshness without
-- requiring direct broker inspection at report time.

CREATE TABLE IF NOT EXISTS systematic_equity.ops_kafka_lag_snapshots (
    ops_kafka_lag_snapshot_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    consumer_group                   VARCHAR(120)    NOT NULL,
    topic_name                       VARCHAR(200)    NOT NULL,
    partition_id                     INTEGER         NOT NULL,
    committed_offset                 BIGINT,
    high_watermark                   BIGINT          NOT NULL DEFAULT 0,
    lag                              BIGINT          NOT NULL DEFAULT 0,
    lag_status                       VARCHAR(20)     NOT NULL DEFAULT 'ok'
        CHECK (lag_status IN ('ok', 'warning', 'error')),
    sampled_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_kafka_lag_snapshots_sampled_at
    ON systematic_equity.ops_kafka_lag_snapshots (sampled_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_kafka_lag_snapshots_group
    ON systematic_equity.ops_kafka_lag_snapshots (consumer_group, sampled_at DESC);

-- Operational health snapshots.
-- Persists periodic readiness/audit snapshots so infrastructure and pipeline
-- health can be reviewed over time without rebuilding state from logs.

CREATE TABLE IF NOT EXISTS systematic_equity.ops_health_snapshots (
    ops_health_snapshot_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_type                    VARCHAR(50)     NOT NULL,
    component                        VARCHAR(80)     NOT NULL,
    run_date                         DATE,
    status                           VARCHAR(20)     NOT NULL
        CHECK (status IN ('ok', 'partial', 'error', 'warning')),
    summary_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    details_json                     JSONB           NOT NULL DEFAULT '{}'::JSONB,
    created_at                       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_health_snapshots_created_at
    ON systematic_equity.ops_health_snapshots (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_health_snapshots_component
    ON systematic_equity.ops_health_snapshots (component, created_at DESC);
