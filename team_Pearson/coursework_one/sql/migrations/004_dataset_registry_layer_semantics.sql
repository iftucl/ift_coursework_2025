-- Migration 004: make dataset_registry carry research-platform semantics,
-- not just physical storage coordinates.

ALTER TABLE systematic_equity.dataset_registry
    ADD COLUMN IF NOT EXISTS logical_layer VARCHAR(32)
        CHECK (logical_layer IN (
            'raw','staging','core','feature','portfolio',
            'analytics','audit','serving','reference'
        ));

ALTER TABLE systematic_equity.dataset_registry
    ADD COLUMN IF NOT EXISTS time_key_column VARCHAR(64);

ALTER TABLE systematic_equity.dataset_registry
    ADD COLUMN IF NOT EXISTS availability_column VARCHAR(64);

ALTER TABLE systematic_equity.dataset_registry
    ADD COLUMN IF NOT EXISTS supports_pit BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN systematic_equity.dataset_registry.logical_layer
    IS 'Logical research-platform layer (raw/staging/core/feature/etc.).';

COMMENT ON COLUMN systematic_equity.dataset_registry.time_key_column
    IS 'Primary event/report/observation date column for the dataset.';

COMMENT ON COLUMN systematic_equity.dataset_registry.availability_column
    IS 'Public-availability/PIT gate column, typically publish_date when relevant.';

COMMENT ON COLUMN systematic_equity.dataset_registry.supports_pit
    IS 'Whether downstream consumers must respect availability_column for PIT correctness.';

CREATE INDEX IF NOT EXISTS idx_dataset_registry_layer_active
    ON systematic_equity.dataset_registry (logical_layer, is_active);
