-- CW2 Reporting Schema
-- Stores report runs and artifact manifests generated from SQL-backed backtest/analysis results.

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_reports (
    report_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id               UUID            NOT NULL REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    report_name          VARCHAR(120)    NOT NULL,
    report_type          VARCHAR(40)     NOT NULL DEFAULT 'performance_summary'
        CHECK (report_type IN ('performance_summary')),
    report_status        VARCHAR(20)     NOT NULL DEFAULT 'generated'
        CHECK (report_status IN ('generated', 'failed')),
    output_dir           TEXT            NOT NULL,
    model_version        VARCHAR(60),
    factor_definition_version VARCHAR(60),
    covariance_method_version VARCHAR(60),
    risk_overlay_policy_version VARCHAR(60),
    backtest_engine_version VARCHAR(60),
    reporting_version    VARCHAR(60),
    config_snapshot      JSONB,
    summary_json         JSONB,
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_backtest_report
        UNIQUE (run_id, report_name)
);

CREATE INDEX IF NOT EXISTS idx_backtest_reports_run
    ON systematic_equity.backtest_reports (run_id, created_at);

ALTER TABLE systematic_equity.backtest_reports
    ADD COLUMN IF NOT EXISTS model_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_reports
    ADD COLUMN IF NOT EXISTS factor_definition_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_reports
    ADD COLUMN IF NOT EXISTS covariance_method_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_reports
    ADD COLUMN IF NOT EXISTS risk_overlay_policy_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_reports
    ADD COLUMN IF NOT EXISTS backtest_engine_version VARCHAR(60);

ALTER TABLE systematic_equity.backtest_reports
    ADD COLUMN IF NOT EXISTS reporting_version VARCHAR(60);

CREATE TABLE IF NOT EXISTS systematic_equity.backtest_report_artifacts (
    id                   BIGSERIAL       PRIMARY KEY,
    report_id            UUID            NOT NULL REFERENCES systematic_equity.backtest_reports(report_id) ON DELETE CASCADE,
    run_id               UUID            NOT NULL REFERENCES systematic_equity.backtest_runs(run_id) ON DELETE CASCADE,
    artifact_name        VARCHAR(100)    NOT NULL,
    artifact_role        VARCHAR(20)     NOT NULL
        CHECK (artifact_role IN ('markdown', 'chart', 'json', 'dataset')),
    artifact_format      VARCHAR(10)     NOT NULL,
    artifact_path        TEXT            NOT NULL,
    artifact_metadata    JSONB,
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_backtest_report_artifact
        UNIQUE (report_id, artifact_name)
);

ALTER TABLE systematic_equity.backtest_report_artifacts
    DROP CONSTRAINT IF EXISTS backtest_report_artifacts_artifact_role_check;

ALTER TABLE systematic_equity.backtest_report_artifacts
    ADD CONSTRAINT backtest_report_artifacts_artifact_role_check
    CHECK (artifact_role IN ('markdown', 'chart', 'json', 'dataset'));

CREATE INDEX IF NOT EXISTS idx_backtest_report_artifacts_run
    ON systematic_equity.backtest_report_artifacts (run_id, artifact_role, created_at);
