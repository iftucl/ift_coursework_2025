-- =============================================================================
-- UCL Institute of Finance & Technology
-- IFTE0003: Big Data in Quantitative Finance
-- Coursework 1 – PostgreSQL Schema for Value + News Sentiment Strategy
-- =============================================================================
-- Database: fift
-- Schema:   systematic_equity
--
-- Strategy: Identify undervalued companies (Fama-French value premium)
--           with positive news sentiment (Tetlock 2007, Baker-Wurgler 2006)
--           to construct a "smart value" portfolio that avoids value traps.
--
-- Design Principles:
--   1. All tables indexed by (company_id, date) for retrieval by company/year.
--   2. Upsert-safe via UNIQUE constraints (INSERT ... ON CONFLICT DO UPDATE).
--   3. ingestion_timestamp on every table for full audit traceability.
--   4. Flexible to company additions/removals from company_static.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS systematic_equity AUTHORIZATION postgres;

-- -------------------------------------------------------------------------
-- 1. company_static – Investable Universe (678 companies)
--    Seeded from the provided CSV via Docker postgres_seed.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fift.systematic_equity.company_static (
    "symbol"          VARCHAR(12)  PRIMARY KEY,
    "security"        TEXT         NOT NULL,
    "gics_sector"     TEXT,
    "gics_industry"   TEXT,
    "country"         CHAR(3),
    "region"          TEXT
);

-- -------------------------------------------------------------------------
-- 2. daily_prices – OHLCV + Adjusted Close for 678 tickers
--    5-year daily history for momentum confirmation and price-based
--    valuation metrics in CW2.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fift.systematic_equity.daily_prices (
    "symbol"              VARCHAR(12)   NOT NULL,
    "cob_date"            DATE          NOT NULL,
    "open_price"          NUMERIC(18,6),
    "high_price"          NUMERIC(18,6),
    "low_price"           NUMERIC(18,6),
    "close_price"         NUMERIC(18,6),
    "adj_close_price"     NUMERIC(18,6),
    "volume"              BIGINT,
    "currency"            CHAR(3)       NOT NULL DEFAULT 'USD',
    "ingestion_timestamp" TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("symbol", "cob_date")
);

CREATE INDEX IF NOT EXISTS idx_prices_cob
    ON fift.systematic_equity.daily_prices ("cob_date");

-- -------------------------------------------------------------------------
-- 3. value_metrics – Calculated financial ratios + percentile Value Score
--    Stores P/E, P/B, EV/EBITDA, Dividend Yield, Debt/Equity
--    plus composite Value Score (average of percentile ranks).
--    Ref: Fama & French (1993), Greenblatt (2006)
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fift.systematic_equity.value_metrics (
    "id"                  SERIAL,
    "company_id"          VARCHAR(12)   NOT NULL,
    "date"                DATE          NOT NULL,
    "pe_ratio"            NUMERIC(18,4),
    "pb_ratio"            NUMERIC(18,4),
    "ev_ebitda"           NUMERIC(18,4),
    "dividend_yield"      NUMERIC(18,6),
    "debt_equity"         NUMERIC(18,4),
    "value_score"         NUMERIC(10,4),
    "ingestion_timestamp" TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE ("company_id", "date")
);

CREATE INDEX IF NOT EXISTS idx_value_company
    ON fift.systematic_equity.value_metrics ("company_id");
CREATE INDEX IF NOT EXISTS idx_value_date
    ON fift.systematic_equity.value_metrics ("date");

-- -------------------------------------------------------------------------
-- 4. sentiment_scores – Aggregated VADER sentiment per company per period
--    Derived from GDELT news articles via VADER lexicon analysis.
--    Ref: Tetlock (2007), Hutto & Gilbert (2014) — VADER
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fift.systematic_equity.sentiment_scores (
    "id"                  SERIAL,
    "company_id"          VARCHAR(12)   NOT NULL,
    "date"                DATE          NOT NULL,
    "avg_sentiment"       NUMERIC(8,4),
    "positive_count"      INTEGER       DEFAULT 0,
    "negative_count"      INTEGER       DEFAULT 0,
    "neutral_count"       INTEGER       DEFAULT 0,
    "total_articles"      INTEGER       DEFAULT 0,
    "positive_ratio"      NUMERIC(8,4),
    "sentiment_score"     NUMERIC(10,4),
    "ingestion_timestamp" TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE ("company_id", "date")
);

CREATE INDEX IF NOT EXISTS idx_sentiment_company
    ON fift.systematic_equity.sentiment_scores ("company_id");
CREATE INDEX IF NOT EXISTS idx_sentiment_date
    ON fift.systematic_equity.sentiment_scores ("date");

-- -------------------------------------------------------------------------
-- 5. composite_rankings – Final factor combination and investment decision
--    Composite = 0.6 × Value Score + 0.4 × Sentiment Score
--    Filters: Debt/Equity < 2.0, Sentiment > 0
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fift.systematic_equity.composite_rankings (
    "id"                  SERIAL,
    "company_id"          VARCHAR(12)   NOT NULL,
    "date"                DATE          NOT NULL,
    "value_score"         NUMERIC(10,4),
    "sentiment_score"     NUMERIC(10,4),
    "composite_score"     NUMERIC(10,4),
    "rank"                INTEGER,
    "invest_decision"     BOOLEAN       DEFAULT FALSE,
    "ingestion_timestamp" TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE ("company_id", "date")
);

CREATE INDEX IF NOT EXISTS idx_composite_company
    ON fift.systematic_equity.composite_rankings ("company_id");
CREATE INDEX IF NOT EXISTS idx_composite_date
    ON fift.systematic_equity.composite_rankings ("date");
CREATE INDEX IF NOT EXISTS idx_composite_rank
    ON fift.systematic_equity.composite_rankings ("rank");

-- -------------------------------------------------------------------------
-- 6. fx_rates – Daily exchange rates for multi-currency universe
--    Required to normalise valuations to USD for cross-country comparison.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fift.systematic_equity.fx_rates (
    "currency_pair"       VARCHAR(12)   NOT NULL,
    "cob_date"            DATE          NOT NULL,
    "open_rate"           NUMERIC(18,8),
    "high_rate"           NUMERIC(18,8),
    "low_rate"            NUMERIC(18,8),
    "close_rate"          NUMERIC(18,8),
    "ingestion_timestamp" TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("currency_pair", "cob_date")
);

-- -------------------------------------------------------------------------
-- 7. ingestion_log – Pipeline run audit trail
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fift.systematic_equity.ingestion_log (
    "log_id"              SERIAL        PRIMARY KEY,
    "run_id"              VARCHAR(64)   NOT NULL,
    "run_timestamp"       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    "data_source"         VARCHAR(32)   NOT NULL,
    "symbol"              VARCHAR(12),
    "status"              VARCHAR(16)   NOT NULL,
    "rows_affected"       INTEGER       DEFAULT 0,
    "error_message"       TEXT,
    "run_frequency"       VARCHAR(16),
    "date_range_start"    DATE,
    "date_range_end"      DATE
);

CREATE INDEX IF NOT EXISTS idx_log_run
    ON fift.systematic_equity.ingestion_log ("run_id");

-- -------------------------------------------------------------------------
-- 8. pipeline_metadata – Tracks last successful run per source/ticker
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fift.systematic_equity.pipeline_metadata (
    "data_source"         VARCHAR(32)   NOT NULL,
    "symbol"              VARCHAR(12)   NOT NULL DEFAULT '__ALL__',
    "last_success_date"   DATE,
    "last_run_timestamp"  TIMESTAMPTZ,
    PRIMARY KEY ("data_source", "symbol")
);
