BEGIN;

ALTER TABLE systematic_equity.financial_observations
    ALTER COLUMN metric_value TYPE NUMERIC(24,6);

COMMIT;
