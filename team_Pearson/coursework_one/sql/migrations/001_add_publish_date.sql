-- Migration 001: Add publish_date to factor_observations for Point-in-Time (PIT) correctness.
--
-- publish_date represents the date on which data became publicly available
-- (e.g., SEC EDGAR filed date). It must satisfy: publish_date <= rebalance_date
-- to prevent look-ahead bias in backtesting.
--
-- Fallback when EDGAR filed date is unavailable: report_date + 45 days.

ALTER TABLE systematic_equity.factor_observations
    ADD COLUMN IF NOT EXISTS publish_date DATE;

COMMENT ON COLUMN systematic_equity.factor_observations.publish_date
    IS 'Point-in-time availability date. Primary: SEC EDGAR filed date. '
       'Fallback: source_report_date + 45 days. Must be <= rebalance_date.';

CREATE INDEX IF NOT EXISTS idx_factor_obs_publish_date
    ON systematic_equity.factor_observations (publish_date);

CREATE INDEX IF NOT EXISTS idx_factor_obs_symbol_publish_date
    ON systematic_equity.factor_observations (symbol, publish_date);
