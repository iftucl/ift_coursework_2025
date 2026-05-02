-- Migration 007: add run-level source coverage contract evidence table.

CREATE TABLE IF NOT EXISTS systematic_equity.source_coverage_audit (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    run_date DATE NOT NULL,
    source_name VARCHAR(32) NOT NULL
        CHECK (source_name IN ('source_a', 'source_b')),
    symbol VARCHAR(50) NOT NULL,
    parent_in_universe BOOLEAN NOT NULL DEFAULT TRUE,
    policy_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    routing_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    expected_in_run BOOLEAN NOT NULL DEFAULT FALSE,
    realized_in_run BOOLEAN NOT NULL DEFAULT FALSE,
    content_available BOOLEAN,
    status VARCHAR(32) NOT NULL,
    reason_code VARCHAR(64),
    details_json JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uniq_source_coverage_audit
        UNIQUE (run_id, run_date, source_name, symbol)
);

CREATE INDEX IF NOT EXISTS idx_source_coverage_audit_run_source
    ON systematic_equity.source_coverage_audit (run_date, source_name, status);
