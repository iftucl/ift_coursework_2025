DROP TABLE IF EXISTS systematic_equity.factor_observations;
DROP TABLE IF EXISTS systematic_equity.financial_observations;

CREATE SCHEMA IF NOT EXISTS systematic_equity;

CREATE TABLE systematic_equity.factor_observations (
    id SERIAL PRIMARY KEY,

    symbol VARCHAR(50) NOT NULL,
    observation_date DATE NOT NULL,
    factor_name VARCHAR(50) NOT NULL,
    factor_value NUMERIC(18,6),

    source VARCHAR(50),

    metric_frequency VARCHAR(20)
        CHECK (metric_frequency IN ('daily','weekly','monthly','quarterly','annual','unknown')),

    source_report_date DATE,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uniq_observation
    UNIQUE (symbol, observation_date, factor_name)
);

CREATE INDEX IF NOT EXISTS idx_factor_obs_symbol
    ON systematic_equity.factor_observations (symbol);

CREATE INDEX IF NOT EXISTS idx_factor_obs_observation_date
    ON systematic_equity.factor_observations (observation_date);

CREATE TABLE systematic_equity.financial_observations (
    id SERIAL PRIMARY KEY,

    symbol VARCHAR(50) NOT NULL,
    report_date DATE NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC(18,6),

    currency VARCHAR(16),
    period_type VARCHAR(20)
        CHECK (period_type IN ('annual','quarterly','ttm','snapshot','unknown')),
    metric_definition VARCHAR(50)
        CHECK (metric_definition IN ('provider_reported','normalized','estimated','unknown')),

    source VARCHAR(50),
    as_of DATE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uniq_financial_observation
    UNIQUE (symbol, report_date, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_financial_obs_symbol
    ON systematic_equity.financial_observations (symbol);

CREATE INDEX IF NOT EXISTS idx_financial_obs_report_date
    ON systematic_equity.financial_observations (report_date);

CREATE TABLE IF NOT EXISTS systematic_equity.pipeline_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    run_date DATE NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('running', 'success', 'failed')),
    frequency VARCHAR(20),
    backfill_years INT,
    company_limit INT,
    enabled_extractors TEXT,
    rows_written INT DEFAULT 0,
    error_message TEXT,
    error_traceback TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_run_date
    ON systematic_equity.pipeline_runs (run_date);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
    ON systematic_equity.pipeline_runs (status);

CREATE TABLE IF NOT EXISTS systematic_equity.company_universe_overrides (
    symbol VARCHAR(50) PRIMARY KEY,
    action VARCHAR(20) NOT NULL
        CHECK (action IN ('include', 'exclude')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_company_universe_overrides_action_active
    ON systematic_equity.company_universe_overrides (action, is_active);

CREATE TABLE IF NOT EXISTS systematic_equity.dataset_registry (
    dataset_name VARCHAR(128) PRIMARY KEY,
    storage_type VARCHAR(32) NOT NULL
        CHECK (storage_type IN ('postgresql', 'mongodb', 'minio', 'file')),
    storage_location TEXT NOT NULL,
    owner_role VARCHAR(64),
    refresh_frequency VARCHAR(20)
        CHECK (refresh_frequency IN ('daily','weekly','monthly','quarterly','annual','ad_hoc')),
    primary_key_def TEXT,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS systematic_equity.schema_versions (
    id SERIAL PRIMARY KEY,
    dataset_name VARCHAR(128) NOT NULL
        REFERENCES systematic_equity.dataset_registry(dataset_name),
    version_tag VARCHAR(40) NOT NULL,
    schema_json JSONB NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_to TIMESTAMPTZ,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    change_note TEXT,
    CONSTRAINT uniq_schema_version UNIQUE (dataset_name, version_tag)
);

CREATE INDEX IF NOT EXISTS idx_schema_versions_dataset_current
    ON systematic_equity.schema_versions (dataset_name, is_current);

CREATE TABLE IF NOT EXISTS systematic_equity.lineage_edges (
    id SERIAL PRIMARY KEY,
    upstream_dataset VARCHAR(128) NOT NULL,
    downstream_dataset VARCHAR(128) NOT NULL,
    transformation_step VARCHAR(128) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uniq_lineage_edge UNIQUE (upstream_dataset, downstream_dataset, transformation_step)
);

CREATE INDEX IF NOT EXISTS idx_lineage_downstream
    ON systematic_equity.lineage_edges (downstream_dataset);

CREATE TABLE IF NOT EXISTS systematic_equity.quality_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64),
    run_date DATE NOT NULL,
    dataset_name VARCHAR(128) NOT NULL,
    quality_report JSONB NOT NULL,
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('pass','warn','fail','unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quality_snapshots_run_dataset
    ON systematic_equity.quality_snapshots (run_date, dataset_name);
