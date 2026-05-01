-- CW2 Feature Engineering Schema
-- Extends systematic_equity schema from CW1

-- Sub-variable scores after preprocessing (winsorize + neutralize + Z-score)
CREATE TABLE IF NOT EXISTS systematic_equity.feature_sub_scores (
    id              BIGSERIAL PRIMARY KEY,
    as_of_date      DATE            NOT NULL,
    symbol          VARCHAR(50)     NOT NULL,
    factor_group    VARCHAR(30)     NOT NULL
        CHECK (factor_group IN ('quality', 'value', 'market_technical', 'sentiment', 'dividend')),
    sub_variable    VARCHAR(50)     NOT NULL,
    raw_value       NUMERIC(18, 6),
    winsorized_value NUMERIC(18, 6),
    neutralized_value NUMERIC(18, 6),
    z_score         NUMERIC(18, 6),
    gics_sector     VARCHAR(60),
    source          VARCHAR(50)     NOT NULL DEFAULT 'cw2_feature_engine',
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_feature_sub_score
        UNIQUE (as_of_date, symbol, factor_group, sub_variable)
);

CREATE INDEX IF NOT EXISTS idx_feature_sub_scores_date_group
    ON systematic_equity.feature_sub_scores (as_of_date, factor_group);

CREATE INDEX IF NOT EXISTS idx_feature_sub_scores_symbol_date
    ON systematic_equity.feature_sub_scores (symbol, as_of_date);

-- First-level factor scores (aggregated from sub-variables)
CREATE TABLE IF NOT EXISTS systematic_equity.feature_factor_scores (
    id              BIGSERIAL PRIMARY KEY,
    as_of_date      DATE            NOT NULL,
    symbol          VARCHAR(50)     NOT NULL,
    quality_score   NUMERIC(18, 6),
    value_score     NUMERIC(18, 6),
    market_technical_score NUMERIC(18, 6),
    sentiment_score NUMERIC(18, 6),
    dividend_score  NUMERIC(18, 6),
    composite_alpha NUMERIC(18, 6),
    regime          VARCHAR(20)     NOT NULL DEFAULT 'normal'
        CHECK (regime IN ('normal', 'stress')),
    vix_level       NUMERIC(10, 4),
    source          VARCHAR(50)     NOT NULL DEFAULT 'cw2_feature_engine',
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_feature_factor_score
        UNIQUE (as_of_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_feature_factor_scores_date
    ON systematic_equity.feature_factor_scores (as_of_date);

CREATE INDEX IF NOT EXISTS idx_feature_factor_scores_symbol
    ON systematic_equity.feature_factor_scores (symbol, as_of_date);

CREATE INDEX IF NOT EXISTS idx_feature_factor_scores_regime
    ON systematic_equity.feature_factor_scores (as_of_date, regime);

-- Investable universe screen (eligibility before alpha portfolio selection)
CREATE TABLE IF NOT EXISTS systematic_equity.feature_universe_screen (
    id              BIGSERIAL PRIMARY KEY,
    as_of_date      DATE            NOT NULL,
    symbol          VARCHAR(50)     NOT NULL,
    country         VARCHAR(32),
    gics_sector     VARCHAR(60),
    log_market_cap  NUMERIC(18, 6),
    liquidity_20d   NUMERIC(18, 2),
    pass_country    BOOLEAN         NOT NULL DEFAULT TRUE,
    pass_market_cap BOOLEAN         NOT NULL DEFAULT TRUE,
    pass_liquidity  BOOLEAN         NOT NULL DEFAULT TRUE,
    pass_all        BOOLEAN         NOT NULL DEFAULT TRUE,
    source          VARCHAR(50)     NOT NULL DEFAULT 'cw2_universe_screen',
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_feature_universe_screen
        UNIQUE (as_of_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_feature_universe_screen_date
    ON systematic_equity.feature_universe_screen (as_of_date, pass_all);

ALTER TABLE systematic_equity.feature_universe_screen
    ADD COLUMN IF NOT EXISTS country VARCHAR(32);

ALTER TABLE systematic_equity.feature_universe_screen
    ADD COLUMN IF NOT EXISTS gics_sector VARCHAR(60);

ALTER TABLE systematic_equity.feature_universe_screen
    ADD COLUMN IF NOT EXISTS log_market_cap NUMERIC(18, 6);

ALTER TABLE systematic_equity.feature_universe_screen
    ADD COLUMN IF NOT EXISTS liquidity_20d NUMERIC(18, 2);

ALTER TABLE systematic_equity.feature_universe_screen
    ADD COLUMN IF NOT EXISTS pass_country BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.feature_universe_screen
    ADD COLUMN IF NOT EXISTS pass_market_cap BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.feature_universe_screen
    ADD COLUMN IF NOT EXISTS pass_liquidity BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.feature_universe_screen
    ADD COLUMN IF NOT EXISTS pass_all BOOLEAN NOT NULL DEFAULT TRUE;

-- Risk overlay results (pass/fail per filter)
CREATE TABLE IF NOT EXISTS systematic_equity.feature_risk_overlay (
    id              BIGSERIAL PRIMARY KEY,
    as_of_date      DATE            NOT NULL,
    symbol          VARCHAR(50)     NOT NULL,
    log_market_cap  NUMERIC(18, 6),
    liquidity_20d   NUMERIC(18, 2),
    volatility_60d  NUMERIC(18, 6),
    missing_factor_pct NUMERIC(5, 4),
    factor_groups_present SMALLINT,
    pass_market_cap BOOLEAN         NOT NULL DEFAULT TRUE,
    pass_liquidity  BOOLEAN         NOT NULL DEFAULT TRUE,
    pass_volatility BOOLEAN         NOT NULL DEFAULT TRUE,
    pass_factor_coverage BOOLEAN    NOT NULL DEFAULT TRUE,
    pass_data_quality BOOLEAN       NOT NULL DEFAULT TRUE,
    pass_all        BOOLEAN         NOT NULL DEFAULT TRUE,
    source          VARCHAR(50)     NOT NULL DEFAULT 'cw2_risk_overlay',
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_feature_risk_overlay
        UNIQUE (as_of_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_feature_risk_overlay_date
    ON systematic_equity.feature_risk_overlay (as_of_date, pass_all);

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS log_market_cap NUMERIC(18, 6);

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS liquidity_20d NUMERIC(18, 2);

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS volatility_60d NUMERIC(18, 6);

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS missing_factor_pct NUMERIC(5, 4);

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS factor_groups_present SMALLINT;

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS pass_market_cap BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS pass_liquidity BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS pass_volatility BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS pass_factor_coverage BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS pass_data_quality BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.feature_risk_overlay
    ADD COLUMN IF NOT EXISTS pass_all BOOLEAN NOT NULL DEFAULT TRUE;

-- Portfolio target positions (final selected portfolio after eligibility + risk overlay)
CREATE TABLE IF NOT EXISTS systematic_equity.portfolio_target_positions (
    id              BIGSERIAL PRIMARY KEY,
    as_of_date      DATE            NOT NULL,
    portfolio_name  VARCHAR(100)    NOT NULL DEFAULT 'cw2_core_equity',
    symbol          VARCHAR(50)     NOT NULL,
    selection_rank  INTEGER         NOT NULL,
    selected_signal BOOLEAN         NOT NULL DEFAULT TRUE,
    target_weight   NUMERIC(12, 8)  NOT NULL,
    weighting_scheme VARCHAR(20)    NOT NULL DEFAULT 'equal',
    ranking_mode    VARCHAR(20)     NOT NULL DEFAULT 'global'
        CHECK (ranking_mode IN ('global', 'sector_relative', 'blended')),
    ranking_score   NUMERIC(12, 8),
    composite_alpha NUMERIC(18, 6),
    regime          VARCHAR(20)
        CHECK (regime IN ('normal', 'stress')),
    gics_sector     VARCHAR(60),
    country         VARCHAR(32),
    previous_weight NUMERIC(12, 8),
    trade_weight    NUMERIC(12, 8),
    turnover_cap    NUMERIC(12, 8),
    realized_turnover NUMERIC(12, 8),
    turnover_limited BOOLEAN        NOT NULL DEFAULT FALSE,
    source          VARCHAR(50)     NOT NULL DEFAULT 'cw2_portfolio_construction',
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_portfolio_target_position
        UNIQUE (as_of_date, portfolio_name, symbol)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_target_positions_date
    ON systematic_equity.portfolio_target_positions (as_of_date, portfolio_name, selection_rank);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS portfolio_name VARCHAR(100) NOT NULL DEFAULT 'cw2_core_equity';

ALTER TABLE systematic_equity.portfolio_target_positions
    ALTER COLUMN portfolio_name TYPE VARCHAR(100);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS selection_rank INTEGER;

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS selected_signal BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS target_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS weighting_scheme VARCHAR(20) NOT NULL DEFAULT 'equal';

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS ranking_mode VARCHAR(20) NOT NULL DEFAULT 'global';

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS ranking_score NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS composite_alpha NUMERIC(18, 6);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS regime VARCHAR(20);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS gics_sector VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS country VARCHAR(32);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS previous_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS trade_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS turnover_cap NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS realized_turnover NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_target_positions
    ADD COLUMN IF NOT EXISTS turnover_limited BOOLEAN NOT NULL DEFAULT FALSE;

-- Portfolio construction diagnostics (pre-constraint weights, bound caps, and final deltas)
CREATE TABLE IF NOT EXISTS systematic_equity.portfolio_construction_diagnostics (
    id                      BIGSERIAL PRIMARY KEY,
    snapshot_id             UUID,
    as_of_date              DATE            NOT NULL,
    portfolio_name          VARCHAR(100)    NOT NULL DEFAULT 'cw2_core_equity',
    symbol                  VARCHAR(50)     NOT NULL,
    candidate_rank          INTEGER,
    selected_signal         BOOLEAN         NOT NULL DEFAULT FALSE,
    selection_drop_reason   VARCHAR(40),
    gics_sector             VARCHAR(60),
    country                 VARCHAR(32),
    ranking_mode            VARCHAR(20),
    ranking_score           NUMERIC(12, 8),
    composite_alpha         NUMERIC(18, 6),
    optimizer_requested     VARCHAR(30),
    optimizer_applied       VARCHAR(30),
    raw_preference_weight   NUMERIC(18, 8),
    pre_constraint_weight   NUMERIC(12, 8),
    constrained_weight      NUMERIC(12, 8),
    final_target_weight     NUMERIC(12, 8),
    previous_weight         NUMERIC(12, 8),
    constraint_weight_delta NUMERIC(12, 8),
    turnover_weight_delta   NUMERIC(12, 8),
    total_weight_delta      NUMERIC(12, 8),
    sector_weight_pre_constraint NUMERIC(12, 8),
    sector_weight_post_constraint NUMERIC(12, 8),
    sector_weight_final     NUMERIC(12, 8),
    max_single_weight       NUMERIC(12, 8),
    max_sector_weight       NUMERIC(12, 8),
    single_name_cap_binding BOOLEAN         NOT NULL DEFAULT FALSE,
    sector_cap_binding      BOOLEAN         NOT NULL DEFAULT FALSE,
    turnover_limited        BOOLEAN         NOT NULL DEFAULT FALSE,
    turnover_cap            NUMERIC(12, 8),
    realized_turnover       NUMERIC(12, 8),
    covariance_method       VARCHAR(60),
    optimizer_fallback_reason VARCHAR(60),
    diagnostic_json         JSONB,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_portfolio_construction_diag
        UNIQUE (as_of_date, portfolio_name, symbol)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_construction_diag_date
    ON systematic_equity.portfolio_construction_diagnostics (as_of_date, portfolio_name, candidate_rank);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ALTER COLUMN portfolio_name TYPE VARCHAR(100);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS snapshot_id UUID;

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS candidate_rank INTEGER;

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS selected_signal BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS selection_drop_reason VARCHAR(40);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS gics_sector VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS country VARCHAR(32);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS ranking_mode VARCHAR(20);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS ranking_score NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS composite_alpha NUMERIC(18, 6);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS optimizer_requested VARCHAR(30);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS optimizer_applied VARCHAR(30);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS raw_preference_weight NUMERIC(18, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS pre_constraint_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS constrained_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS final_target_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS previous_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS constraint_weight_delta NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS turnover_weight_delta NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS total_weight_delta NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS sector_weight_pre_constraint NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS sector_weight_post_constraint NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS sector_weight_final NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS max_single_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS max_sector_weight NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS single_name_cap_binding BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS sector_cap_binding BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS turnover_limited BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS turnover_cap NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS realized_turnover NUMERIC(12, 8);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS covariance_method VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS optimizer_fallback_reason VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_construction_diagnostics
    ADD COLUMN IF NOT EXISTS diagnostic_json JSONB;

-- Feature snapshot registry (one row per PIT-clean CW2 build request)
CREATE TABLE IF NOT EXISTS systematic_equity.feature_snapshot_registry (
    snapshot_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requested_as_of_date DATE            NOT NULL,
    as_of_date           DATE            NOT NULL,
    snapshot_status      VARCHAR(30)     NOT NULL DEFAULT 'completed'
        CHECK (snapshot_status IN ('completed', 'blocked_scoring', 'blocked_portfolio')),
    scoring_universe     INTEGER         NOT NULL DEFAULT 0,
    investable_universe  INTEGER         NOT NULL DEFAULT 0,
    min_scoring_universe INTEGER         NOT NULL DEFAULT 0,
    min_investable_universe INTEGER      NOT NULL DEFAULT 0,
    allow_factor_scoring BOOLEAN         NOT NULL DEFAULT TRUE,
    allow_portfolio_construction BOOLEAN NOT NULL DEFAULT TRUE,
    factor_row_count     INTEGER         NOT NULL DEFAULT 0,
    financial_row_count  INTEGER         NOT NULL DEFAULT 0,
    previous_position_count INTEGER      NOT NULL DEFAULT 0,
    vix_level            NUMERIC(10, 4),
    model_version        VARCHAR(60),
    factor_definition_version VARCHAR(60),
    covariance_method    VARCHAR(60),
    covariance_method_version VARCHAR(60),
    risk_overlay_policy_version VARCHAR(60),
    covariance_symbol_count INTEGER,
    config_snapshot      JSONB,
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_feature_snapshot_registry
        UNIQUE (requested_as_of_date, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_feature_snapshot_registry_asof
    ON systematic_equity.feature_snapshot_registry (as_of_date, snapshot_status);

ALTER TABLE systematic_equity.feature_snapshot_registry
    ADD COLUMN IF NOT EXISTS model_version VARCHAR(60);

ALTER TABLE systematic_equity.feature_snapshot_registry
    ADD COLUMN IF NOT EXISTS factor_definition_version VARCHAR(60);

ALTER TABLE systematic_equity.feature_snapshot_registry
    ADD COLUMN IF NOT EXISTS covariance_method_version VARCHAR(60);

ALTER TABLE systematic_equity.feature_snapshot_registry
    ADD COLUMN IF NOT EXISTS risk_overlay_policy_version VARCHAR(60);

-- Portfolio snapshot registry (aggregated metadata about one portfolio snapshot)
CREATE TABLE IF NOT EXISTS systematic_equity.portfolio_snapshot_registry (
    id                  BIGSERIAL PRIMARY KEY,
    snapshot_id         UUID            REFERENCES systematic_equity.feature_snapshot_registry(snapshot_id) ON DELETE SET NULL,
    as_of_date          DATE            NOT NULL,
    portfolio_name      VARCHAR(100)    NOT NULL,
    snapshot_status     VARCHAR(30)     NOT NULL DEFAULT 'completed'
        CHECK (snapshot_status IN ('completed', 'blocked_portfolio', 'carried_forward')),
    num_positions       SMALLINT        NOT NULL DEFAULT 0,
    gross_target_weight NUMERIC(12, 8),
    avg_composite_alpha NUMERIC(18, 6),
    expected_turnover   NUMERIC(12, 8),
    weighting_scheme    VARCHAR(30),
    ranking_mode        VARCHAR(20),
    regime              VARCHAR(20),
    model_version       VARCHAR(60),
    factor_definition_version VARCHAR(60),
    covariance_method_version VARCHAR(60),
    risk_overlay_policy_version VARCHAR(60),
    summary_json        JSONB,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uniq_portfolio_snapshot_registry
        UNIQUE (as_of_date, portfolio_name)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshot_registry_asof
    ON systematic_equity.portfolio_snapshot_registry (as_of_date, portfolio_name);

ALTER TABLE systematic_equity.portfolio_snapshot_registry
    ALTER COLUMN portfolio_name TYPE VARCHAR(100);

ALTER TABLE systematic_equity.portfolio_snapshot_registry
    DROP CONSTRAINT IF EXISTS portfolio_snapshot_registry_snapshot_status_check;

ALTER TABLE systematic_equity.portfolio_snapshot_registry
    ADD CONSTRAINT portfolio_snapshot_registry_snapshot_status_check
    CHECK (snapshot_status IN ('completed', 'blocked_portfolio', 'carried_forward'));

ALTER TABLE systematic_equity.portfolio_snapshot_registry
    ADD COLUMN IF NOT EXISTS model_version VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_snapshot_registry
    ADD COLUMN IF NOT EXISTS factor_definition_version VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_snapshot_registry
    ADD COLUMN IF NOT EXISTS covariance_method_version VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_snapshot_registry
    ADD COLUMN IF NOT EXISTS risk_overlay_policy_version VARCHAR(60);

-- Model input manifests (audit trail of what went into feature / portfolio generation)
CREATE TABLE IF NOT EXISTS systematic_equity.model_input_manifests (
    manifest_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id         UUID            REFERENCES systematic_equity.feature_snapshot_registry(snapshot_id) ON DELETE CASCADE,
    as_of_date          DATE            NOT NULL,
    manifest_type       VARCHAR(40)     NOT NULL
        CHECK (manifest_type IN ('feature_input', 'risk_input', 'portfolio_input', 'recommendation_input')),
    payload_json        JSONB           NOT NULL,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_input_manifests_snapshot
    ON systematic_equity.model_input_manifests (snapshot_id, manifest_type);
