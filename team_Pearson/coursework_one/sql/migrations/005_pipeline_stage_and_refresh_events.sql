-- Migration 005: persist append-only stage telemetry and dataset refresh history.

CREATE TABLE IF NOT EXISTS systematic_equity.pipeline_stage_events (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    stage_name VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('running', 'ok', 'warning', 'failed', 'skipped')),
    rows_in INT,
    rows_out INT,
    elapsed_ms INT,
    details_json JSONB,
    event_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_stage_events_run_stage
    ON systematic_equity.pipeline_stage_events (run_id, stage_name, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_stage_events_status
    ON systematic_equity.pipeline_stage_events (status, event_at DESC);

CREATE TABLE IF NOT EXISTS systematic_equity.dataset_refresh_events (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    run_date DATE NOT NULL,
    dataset_name VARCHAR(128) NOT NULL
        REFERENCES systematic_equity.dataset_registry(dataset_name),
    stage_name VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('ok', 'warning', 'failed', 'skipped')),
    rows_written INT DEFAULT 0,
    details_json JSONB,
    event_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dataset_refresh_events_run_dataset
    ON systematic_equity.dataset_refresh_events (run_date, dataset_name, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_dataset_refresh_events_stage_status
    ON systematic_equity.dataset_refresh_events (stage_name, status, event_at DESC);

COMMENT ON TABLE systematic_equity.pipeline_stage_events
    IS 'Append-only stage-level telemetry emitted by Main.py for run orchestration and scheduler observability.';

COMMENT ON TABLE systematic_equity.dataset_refresh_events
    IS 'Append-only dataset refresh log by run and stage. Preserves historical write evidence instead of overwriting counters.';
