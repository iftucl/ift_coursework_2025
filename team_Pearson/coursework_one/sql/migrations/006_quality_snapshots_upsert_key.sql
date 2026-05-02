-- Migration 006: make quality_snapshots idempotent per run/dataset snapshot.
--
-- Historical duplicate rows can exist for the same logical snapshot when the
-- same run_id + run_date + dataset_name was written multiple times. Keep the
-- most recent row and enforce a uniqueness constraint so writers can upsert.

WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY run_id, run_date, dataset_name
            ORDER BY created_at DESC, id DESC
        ) AS rn
    FROM systematic_equity.quality_snapshots
    WHERE run_id IS NOT NULL
)
DELETE FROM systematic_equity.quality_snapshots AS qs
USING ranked
WHERE qs.id = ranked.id
  AND ranked.rn > 1;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uniq_quality_snapshot_run_dataset'
          AND conrelid = 'systematic_equity.quality_snapshots'::regclass
    ) THEN
        ALTER TABLE systematic_equity.quality_snapshots
        ADD CONSTRAINT uniq_quality_snapshot_run_dataset
            UNIQUE (run_id, run_date, dataset_name);
    END IF;
END $$;
