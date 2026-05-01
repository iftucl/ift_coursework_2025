-- Migration 003: Add publish_date to financial_observations for Point-in-Time (PIT) correctness.
--
-- publish_date = the date the filing became publicly available.
--   Primary source: EDGAR XBRL `filed` date (already extracted by edgar_xbrl.py).
--   Fallback: report_date + 45 days (conservative SEC filing lag estimate).
--
-- as_of = the date the pipeline fetched this record from the data provider.
-- The two serve different purposes:
--   publish_date  → PIT filtering (publish_date <= rebalance_date)
--   as_of         → data audit / replay lineage
--
-- Backfill strategy: copy as_of into publish_date for existing rows. This is
-- conservative (as_of >= true publish_date), so no look-ahead bias is introduced.
-- Future pipeline runs will populate publish_date directly from EDGAR filed date.

ALTER TABLE systematic_equity.financial_observations
    ADD COLUMN IF NOT EXISTS publish_date DATE;

COMMENT ON COLUMN systematic_equity.financial_observations.publish_date
    IS 'Point-in-time availability date. Primary: SEC EDGAR filed date. '
       'Fallback: report_date + 45 days. Must be <= rebalance_date for PIT correctness.';

-- Backfill from as_of (conservative: as_of >= true publish_date)
UPDATE systematic_equity.financial_observations
SET    publish_date = as_of
WHERE  publish_date IS NULL
  AND  as_of IS NOT NULL;

-- Backfill remaining rows with report_date + 45 days
UPDATE systematic_equity.financial_observations
SET    publish_date = report_date + INTERVAL '45 days'
WHERE  publish_date IS NULL
  AND  report_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_financial_obs_publish_date
    ON systematic_equity.financial_observations (publish_date);

CREATE INDEX IF NOT EXISTS idx_financial_obs_symbol_publish_date
    ON systematic_equity.financial_observations (symbol, publish_date);
