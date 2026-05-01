-- CW2 Portfolio Recommendation Schema
-- Formal recommendation layer built on top of portfolio_target_positions

CREATE TABLE IF NOT EXISTS systematic_equity.portfolio_recommendations (
    recommendation_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_name  VARCHAR(100)    NOT NULL UNIQUE,
    as_of_date           DATE            NOT NULL,
    portfolio_name       VARCHAR(100)    NOT NULL,
    recommendation_status VARCHAR(20)    NOT NULL DEFAULT 'proposed'
        CHECK (recommendation_status IN ('proposed', 'approved', 'rejected', 'published')),
    benchmark_ticker     VARCHAR(20),
    regime               VARCHAR(20),
    weighting_scheme     VARCHAR(30),
    ranking_mode         VARCHAR(20),
    num_positions        SMALLINT,
    gross_target_weight  NUMERIC(12, 8),
    expected_turnover    NUMERIC(12, 8),
    avg_composite_alpha  NUMERIC(18, 6),
    model_version        VARCHAR(60),
    factor_definition_version VARCHAR(60),
    covariance_method_version VARCHAR(60),
    risk_overlay_policy_version VARCHAR(60),
    recommendation_version VARCHAR(60),
    config_snapshot      JSONB,
    summary_json         JSONB,
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    approved_at          TIMESTAMPTZ,
    approved_by          VARCHAR(100),
    decision_notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_portfolio_recommendations_date
    ON systematic_equity.portfolio_recommendations (as_of_date, portfolio_name);

ALTER TABLE systematic_equity.portfolio_recommendations
    ALTER COLUMN portfolio_name TYPE VARCHAR(100);

ALTER TABLE systematic_equity.portfolio_recommendations
    ADD COLUMN IF NOT EXISTS model_version VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_recommendations
    ADD COLUMN IF NOT EXISTS factor_definition_version VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_recommendations
    ADD COLUMN IF NOT EXISTS covariance_method_version VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_recommendations
    ADD COLUMN IF NOT EXISTS risk_overlay_policy_version VARCHAR(60);

ALTER TABLE systematic_equity.portfolio_recommendations
    ADD COLUMN IF NOT EXISTS recommendation_version VARCHAR(60);

CREATE TABLE IF NOT EXISTS systematic_equity.portfolio_recommendation_items (
    id                  BIGSERIAL       PRIMARY KEY,
    recommendation_id   UUID            NOT NULL REFERENCES systematic_equity.portfolio_recommendations(recommendation_id) ON DELETE CASCADE,
    symbol              VARCHAR(50)     NOT NULL,
    selection_rank      INTEGER,
    target_weight       NUMERIC(12, 8)  NOT NULL,
    previous_weight     NUMERIC(12, 8),
    trade_weight        NUMERIC(12, 8),
    position_action     VARCHAR(20)     NOT NULL
        CHECK (position_action IN ('new_entry', 'increase', 'decrease', 'hold')),
    composite_alpha     NUMERIC(18, 6),
    quality_score       NUMERIC(18, 6),
    value_score         NUMERIC(18, 6),
    market_technical_score NUMERIC(18, 6),
    sentiment_score     NUMERIC(18, 6),
    dividend_score      NUMERIC(18, 6),
    gics_sector         VARCHAR(60),
    country             VARCHAR(32),
    regime              VARCHAR(20),
    weighting_scheme    VARCHAR(30),
    ranking_mode        VARCHAR(20),
    ranking_score       NUMERIC(12, 8),
    turnover_limited    BOOLEAN         NOT NULL DEFAULT FALSE,
    rationale_json      JSONB,

    CONSTRAINT uniq_portfolio_recommendation_item
        UNIQUE (recommendation_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_recommendation_items_recommendation
    ON systematic_equity.portfolio_recommendation_items (recommendation_id, selection_rank);

CREATE TABLE IF NOT EXISTS systematic_equity.portfolio_recommendation_events (
    id                  BIGSERIAL       PRIMARY KEY,
    recommendation_id   UUID            NOT NULL REFERENCES systematic_equity.portfolio_recommendations(recommendation_id) ON DELETE CASCADE,
    event_type          VARCHAR(20)     NOT NULL
        CHECK (event_type IN ('proposed', 'approved', 'rejected', 'published')),
    event_timestamp     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    actor               VARCHAR(100),
    notes               TEXT,
    payload_json        JSONB
);

CREATE INDEX IF NOT EXISTS idx_portfolio_recommendation_events_recommendation
    ON systematic_equity.portfolio_recommendation_events (recommendation_id, event_timestamp);

CREATE TABLE IF NOT EXISTS systematic_equity.portfolio_recommendation_decisions (
    id                  BIGSERIAL       PRIMARY KEY,
    recommendation_id   UUID            NOT NULL REFERENCES systematic_equity.portfolio_recommendations(recommendation_id) ON DELETE CASCADE,
    decision_type       VARCHAR(20)     NOT NULL
        CHECK (decision_type IN ('approve', 'reject', 'publish')),
    actor               VARCHAR(100)    NOT NULL,
    decision_timestamp  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    notes               TEXT,
    payload_json        JSONB
);

CREATE INDEX IF NOT EXISTS idx_portfolio_recommendation_decisions_recommendation
    ON systematic_equity.portfolio_recommendation_decisions (recommendation_id, decision_timestamp);
