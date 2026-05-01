CREATE SCHEMA IF NOT EXISTS systematic_equity;

-- Company universe: seeded from teacher-provided SQLite via seed_universe_from_sqlite.py
CREATE TABLE IF NOT EXISTS systematic_equity.company_static (
    symbol TEXT PRIMARY KEY,
    security TEXT,
    gics_sector TEXT,
    gics_industry TEXT,
    country TEXT,
    region TEXT
);

CREATE TABLE IF NOT EXISTS systematic_equity.factor_observations (
    id SERIAL PRIMARY KEY,

    symbol VARCHAR(50) NOT NULL,
    observation_date DATE NOT NULL,
    factor_name VARCHAR(50) NOT NULL,
    factor_value NUMERIC(18,6),

    source VARCHAR(50),

    metric_frequency VARCHAR(20)
        CHECK (metric_frequency IN ('daily','weekly','monthly','quarterly','annual','unknown')),

    source_report_date DATE,
    publish_date DATE,       -- PIT: date data became publicly available (e.g. SEC filed date)

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uniq_observation
    UNIQUE (symbol, observation_date, factor_name)
);

CREATE INDEX IF NOT EXISTS idx_factor_obs_symbol
    ON systematic_equity.factor_observations (symbol);

CREATE INDEX IF NOT EXISTS idx_factor_obs_observation_date
    ON systematic_equity.factor_observations (observation_date);

CREATE INDEX IF NOT EXISTS idx_factor_obs_symbol_factor_date
    ON systematic_equity.factor_observations (symbol, factor_name, observation_date);

CREATE INDEX IF NOT EXISTS idx_factor_obs_factor_date
    ON systematic_equity.factor_observations (factor_name, observation_date);

CREATE INDEX IF NOT EXISTS idx_factor_obs_publish_date
    ON systematic_equity.factor_observations (publish_date);

CREATE INDEX IF NOT EXISTS idx_factor_obs_symbol_publish_date
    ON systematic_equity.factor_observations (symbol, publish_date);

CREATE TABLE IF NOT EXISTS systematic_equity.financial_observations (
    id SERIAL PRIMARY KEY,

    symbol VARCHAR(50) NOT NULL,
    report_date DATE NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC(24,6),

    currency VARCHAR(16),
    period_type VARCHAR(20)
        CHECK (period_type IN ('annual','quarterly','ttm','snapshot','unknown')),
    metric_definition VARCHAR(50)
        CHECK (metric_definition IN ('provider_reported','normalized','estimated','unknown')),

    source VARCHAR(50),
    value_source VARCHAR(64),
    as_of DATE,
    publish_date DATE,       -- PIT: SEC filing date (or report_date + 45d fallback)
    publish_date_source VARCHAR(64),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uniq_financial_observation
    UNIQUE (symbol, report_date, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_financial_obs_symbol
    ON systematic_equity.financial_observations (symbol);

CREATE INDEX IF NOT EXISTS idx_financial_obs_report_date
    ON systematic_equity.financial_observations (report_date);

CREATE INDEX IF NOT EXISTS idx_financial_obs_publish_date
    ON systematic_equity.financial_observations (publish_date);

ALTER TABLE IF EXISTS systematic_equity.financial_observations
    ADD COLUMN IF NOT EXISTS value_source VARCHAR(64);

ALTER TABLE IF EXISTS systematic_equity.financial_observations
    ADD COLUMN IF NOT EXISTS publish_date_source VARCHAR(64);

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

CREATE TABLE IF NOT EXISTS systematic_equity.dataset_registry (
    dataset_name VARCHAR(128) PRIMARY KEY,
    storage_type VARCHAR(32) NOT NULL
        CHECK (storage_type IN ('postgresql', 'mongodb', 'minio', 'file')),
    storage_location TEXT NOT NULL,
    owner_role VARCHAR(64),
    refresh_frequency VARCHAR(20)
        CHECK (refresh_frequency IN ('daily','weekly','monthly','quarterly','annual','ad_hoc')),
    logical_layer VARCHAR(32)
        CHECK (logical_layer IN (
            'raw','staging','core','feature','portfolio',
            'analytics','audit','serving','reference'
        )),
    time_key_column VARCHAR(64),
    availability_column VARCHAR(64),
    supports_pit BOOLEAN NOT NULL DEFAULT FALSE,
    primary_key_def TEXT,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

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

CREATE INDEX IF NOT EXISTS idx_dataset_registry_layer_active
    ON systematic_equity.dataset_registry (logical_layer, is_active);

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uniq_quality_snapshot_run_dataset
        UNIQUE (run_id, run_date, dataset_name)
);

CREATE INDEX IF NOT EXISTS idx_quality_snapshots_run_dataset
    ON systematic_equity.quality_snapshots (run_date, dataset_name);

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

-- Benchmark daily prices (e.g. SPY).
-- Kept separate from factor_observations: this is reference/benchmark data,
-- not an alpha factor. Used for beta computation, portfolio attribution,
-- and Sharpe / Information ratio calculation.
CREATE TABLE IF NOT EXISTS systematic_equity.benchmark_prices (
    id          BIGSERIAL PRIMARY KEY,
    ticker      VARCHAR(20)     NOT NULL,
    price_date  DATE            NOT NULL,
    close_price NUMERIC(18, 6)  NOT NULL,
    daily_return NUMERIC(18, 8),
    source      VARCHAR(50)     NOT NULL DEFAULT 'yfinance',
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_benchmark_price UNIQUE (ticker, price_date)
);

CREATE INDEX IF NOT EXISTS idx_benchmark_prices_ticker_date
    ON systematic_equity.benchmark_prices (ticker, price_date DESC);
