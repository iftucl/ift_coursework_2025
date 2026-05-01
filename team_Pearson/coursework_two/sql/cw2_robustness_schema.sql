-- CW2 Robustness Schema
-- Stores robustness evidence packs and row-level CSV payloads for the web dashboard.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS systematic_equity.robustness_reports (
    robustness_report_id UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    report_name          VARCHAR(180)  NOT NULL,
    report_scope         VARCHAR(80)   NOT NULL DEFAULT 'robustness_outputs',
    report_status        VARCHAR(30)   NOT NULL DEFAULT 'generated'
        CHECK (report_status IN ('generated', 'failed')),
    output_root          TEXT          NOT NULL,
    source_run_id        UUID,
    summary_json         JSONB,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_robustness_report
        UNIQUE (report_name, output_root)
);

ALTER TABLE systematic_equity.robustness_reports
    ADD COLUMN IF NOT EXISTS report_scope VARCHAR(80) NOT NULL DEFAULT 'robustness_outputs';

ALTER TABLE systematic_equity.robustness_reports
    ADD COLUMN IF NOT EXISTS report_status VARCHAR(30) NOT NULL DEFAULT 'generated';

ALTER TABLE systematic_equity.robustness_reports
    ADD COLUMN IF NOT EXISTS output_root TEXT;

ALTER TABLE systematic_equity.robustness_reports
    ADD COLUMN IF NOT EXISTS source_run_id UUID;

ALTER TABLE systematic_equity.robustness_reports
    ADD COLUMN IF NOT EXISTS summary_json JSONB;

ALTER TABLE systematic_equity.robustness_reports
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE systematic_equity.robustness_reports
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_robustness_reports_name_created
    ON systematic_equity.robustness_reports (report_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_robustness_reports_source_run
    ON systematic_equity.robustness_reports (source_run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS systematic_equity.robustness_report_artifacts (
    id                   BIGSERIAL     PRIMARY KEY,
    robustness_report_id UUID          NOT NULL
        REFERENCES systematic_equity.robustness_reports(robustness_report_id)
        ON DELETE CASCADE,
    artifact_name        TEXT          NOT NULL,
    artifact_group       VARCHAR(120)  NOT NULL,
    artifact_role        VARCHAR(40)   NOT NULL,
    artifact_path        TEXT          NOT NULL,
    row_count            INTEGER,
    artifact_metadata    JSONB,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_robustness_report_artifact
        UNIQUE (robustness_report_id, artifact_name)
);

CREATE INDEX IF NOT EXISTS idx_robustness_artifacts_report_group
    ON systematic_equity.robustness_report_artifacts
    (robustness_report_id, artifact_group, artifact_role);

CREATE TABLE IF NOT EXISTS systematic_equity.robustness_report_rows (
    id                   BIGSERIAL     PRIMARY KEY,
    robustness_report_id UUID          NOT NULL
        REFERENCES systematic_equity.robustness_reports(robustness_report_id)
        ON DELETE CASCADE,
    dataset_name         TEXT          NOT NULL,
    row_number           INTEGER       NOT NULL,
    row_payload          JSONB         NOT NULL,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_robustness_report_row
        UNIQUE (robustness_report_id, dataset_name, row_number)
);

CREATE INDEX IF NOT EXISTS idx_robustness_rows_report_dataset
    ON systematic_equity.robustness_report_rows
    (robustness_report_id, dataset_name, row_number);
