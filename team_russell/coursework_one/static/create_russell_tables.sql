-- Team Russell: Additional tables for value + quality factor pipeline
-- Run against fift database after the lecturer's create_tables.sql

-- Daily price history and shares outstanding
CREATE TABLE IF NOT EXISTS systematic_equity.price_history (
    symbol          CHAR(12) NOT NULL REFERENCES systematic_equity.company_static(symbol),
    price_date      DATE NOT NULL,
    closing_price   NUMERIC(18,4),
    shares_outstanding BIGINT,
    PRIMARY KEY (symbol, price_date)
);

-- Annual financial statement data (raw inputs for factor computation)
CREATE TABLE IF NOT EXISTS systematic_equity.financials (
    symbol                  CHAR(12) NOT NULL REFERENCES systematic_equity.company_static(symbol),
    period_date             DATE NOT NULL,
    total_assets            NUMERIC(20,2),
    total_liabilities       NUMERIC(20,2),
    net_income_ttm          NUMERIC(20,2),
    ebitda_ttm              NUMERIC(20,2),
    total_debt              NUMERIC(20,2),
    cash_and_equivalents    NUMERIC(20,2),
    book_value              NUMERIC(20,2),
    revenue                 NUMERIC(20,2),
    PRIMARY KEY (symbol, period_date)
);

-- Composite value + quality factor scores (yearly rebalance)
CREATE TABLE IF NOT EXISTS systematic_equity.factor_values (
    symbol              CHAR(12) NOT NULL REFERENCES systematic_equity.company_static(symbol),
    period_date         DATE NOT NULL,
    run_id              TEXT,
    market_cap          NUMERIC(20,2),
    book_value          NUMERIC(20,2),
    enterprise_value    NUMERIC(20,2),
    pb                  NUMERIC(12,6),
    pe                  NUMERIC(12,6),
    ev_ebitda           NUMERIC(12,6),
    roe                 NUMERIC(12,6),
    percentile_pb       NUMERIC(6,4),
    percentile_pe       NUMERIC(6,4),
    percentile_ev_ebitda NUMERIC(6,4),
    percentile_roe      NUMERIC(6,4),
    value_score         NUMERIC(6,4),
    quality_score       NUMERIC(6,4),
    composite_score     NUMERIC(6,4),
    PRIMARY KEY (symbol, period_date)
);

-- Migration: add new columns if the tables already exist

-- [0.2.0] revenue
ALTER TABLE systematic_equity.financials
    ADD COLUMN IF NOT EXISTS revenue NUMERIC(20,2);

-- [0.4.0] new fields for expanded factor metrics
ALTER TABLE systematic_equity.financials
    ADD COLUMN IF NOT EXISTS gross_profit         NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS free_cash_flow       NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS current_assets       NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS current_liabilities  NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS annual_dividend_rate NUMERIC(12,6);

-- [0.2.0] factor_values additions
ALTER TABLE systematic_equity.factor_values
    ADD COLUMN IF NOT EXISTS run_id TEXT,
    ADD COLUMN IF NOT EXISTS roe NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS percentile_roe NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS quality_score NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS composite_score NUMERIC(6,4);

-- [0.4.0] factor_values: drop old columns, add new metric + scoring columns
ALTER TABLE systematic_equity.factor_values
    DROP COLUMN IF EXISTS enterprise_value,
    DROP COLUMN IF EXISTS pb,
    DROP COLUMN IF EXISTS pe,
    DROP COLUMN IF EXISTS ev_ebitda,
    DROP COLUMN IF EXISTS roe,
    DROP COLUMN IF EXISTS percentile_pb,
    DROP COLUMN IF EXISTS percentile_pe,
    DROP COLUMN IF EXISTS percentile_ev_ebitda,
    DROP COLUMN IF EXISTS percentile_roe,
    ADD COLUMN IF NOT EXISTS bp               NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ey               NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS cfy              NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS dy               NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS gpa              NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS wca              NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ltde             NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS roa              NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS z_bp             NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS z_ey             NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS z_cfy            NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS z_dy             NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS z_gpa            NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS z_wca            NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS z_ltde           NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS z_roa            NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS composite_percentile NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS quintile         SMALLINT;

-- value_score / quality_score / composite_score already exist;
-- they now hold z-scores (unbounded) instead of 0-1 percentiles.

-- Indexes for fast querying by rebalance date, score, and quintile
CREATE INDEX IF NOT EXISTS idx_fv_rebalance       ON systematic_equity.factor_values (period_date);
CREATE INDEX IF NOT EXISTS idx_fv_rebalance_score ON systematic_equity.factor_values (period_date, composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_fv_quintile        ON systematic_equity.factor_values (period_date, quintile);
