from __future__ import annotations

"""Metadata registry, lineage, and quality snapshot persistence."""

import json
import os
from typing import Any

from sqlalchemy import text

from modules.db import get_db_engine


def _metadata_enabled() -> bool:
    return os.getenv("CW1_TEST_MODE") != "1"


def bootstrap_metadata_catalog() -> None:
    """Upsert baseline dataset registry, schema version, and lineage entries."""
    if not _metadata_enabled():
        return

    dataset_rows = [
        {
            "dataset_name": "company_static",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.company_static",
            "owner_role": "Role 5",
            "refresh_frequency": "ad_hoc",
            "primary_key_def": "symbol",
            "description": "Dynamic investable universe source table.",
        },
        {
            "dataset_name": "source_a_raw_pricing_fundamentals",
            "storage_type": "minio",
            "storage_location": "csreport/raw/source_a/pricing_fundamentals/",
            "owner_role": "Role 6",
            "refresh_frequency": "daily",
            "primary_key_def": "object_key",
            "description": "Source A raw market/fundamental payloads.",
        },
        {
            "dataset_name": "source_b_raw_news",
            "storage_type": "minio",
            "storage_location": "csreport/raw/source_b/news/",
            "owner_role": "Role 7",
            "refresh_frequency": "daily",
            "primary_key_def": "object_key",
            "description": "Source B raw news payloads in JSONL.",
        },
        {
            "dataset_name": "factor_observations",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.factor_observations",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "primary_key_def": "symbol,observation_date,factor_name",
            "description": "Atomic and final factors in long format.",
        },
        {
            "dataset_name": "financial_observations",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.financial_observations",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "primary_key_def": "symbol,report_date,metric_name",
            "description": "Atomic financial observations from providers.",
        },
        {
            "dataset_name": "pipeline_runs",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.pipeline_runs",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "primary_key_def": "run_id",
            "description": "Run-level operational audit table.",
        },
        {
            "dataset_name": "news_articles",
            "storage_type": "mongodb",
            "storage_location": "ift_cw.news_articles",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "primary_key_def": "_id",
            "description": "Searchable news index built from MinIO raw layer.",
        },
    ]

    schema_rows = [
        (
            "factor_observations",
            "v1",
            {
                "columns": [
                    "symbol",
                    "observation_date",
                    "factor_name",
                    "factor_value",
                    "source",
                    "metric_frequency",
                    "source_report_date",
                ]
            },
            "Initial curated factor schema.",
        ),
        (
            "financial_observations",
            "v1",
            {
                "columns": [
                    "symbol",
                    "report_date",
                    "metric_name",
                    "metric_value",
                    "currency",
                    "period_type",
                    "metric_definition",
                    "source",
                    "as_of",
                ]
            },
            "Initial financial observation schema.",
        ),
        (
            "news_articles",
            "v1",
            {
                "fields": [
                    "_id",
                    "url",
                    "source",
                    "time_published",
                    "published_at",
                    "title",
                    "summary",
                    "tickers",
                    "symbols",
                    "topics",
                    "lang",
                ]
            },
            "Initial Mongo news index schema with compatibility aliases.",
        ),
    ]

    lineage_rows = [
        (
            "company_static",
            "factor_observations",
            "universe_selection_and_factor_pipeline",
        ),
        (
            "source_a_raw_pricing_fundamentals",
            "factor_observations",
            "extract_source_a_normalize_load",
        ),
        (
            "source_a_raw_pricing_fundamentals",
            "financial_observations",
            "extract_source_a_financial_load",
        ),
        (
            "source_b_raw_news",
            "factor_observations",
            "extract_source_b_sentiment_features",
        ),
        (
            "source_b_raw_news",
            "news_articles",
            "index_news_to_mongo",
        ),
    ]

    upsert_dataset_sql = text(
        """
        INSERT INTO systematic_equity.dataset_registry (
            dataset_name, storage_type, storage_location, owner_role, refresh_frequency,
            primary_key_def, description, is_active
        ) VALUES (
            :dataset_name, :storage_type, :storage_location, :owner_role, :refresh_frequency,
            :primary_key_def, :description, TRUE
        )
        ON CONFLICT (dataset_name) DO UPDATE
        SET storage_type = EXCLUDED.storage_type,
            storage_location = EXCLUDED.storage_location,
            owner_role = EXCLUDED.owner_role,
            refresh_frequency = EXCLUDED.refresh_frequency,
            primary_key_def = EXCLUDED.primary_key_def,
            description = EXCLUDED.description,
            is_active = TRUE,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    reset_schema_current_sql = text(
        """
        UPDATE systematic_equity.schema_versions
        SET is_current = FALSE, valid_to = CURRENT_TIMESTAMP
        WHERE dataset_name = :dataset_name
          AND is_current = TRUE
          AND version_tag <> :version_tag
        """
    )
    upsert_schema_sql = text(
        """
        INSERT INTO systematic_equity.schema_versions (
            dataset_name, version_tag, schema_json, is_current, change_note
        ) VALUES (
            :dataset_name, :version_tag, CAST(:schema_json AS jsonb), TRUE, :change_note
        )
        ON CONFLICT (dataset_name, version_tag) DO UPDATE
        SET schema_json = EXCLUDED.schema_json,
            is_current = TRUE,
            valid_to = NULL,
            change_note = EXCLUDED.change_note
        """
    )
    upsert_lineage_sql = text(
        """
        INSERT INTO systematic_equity.lineage_edges (
            upstream_dataset, downstream_dataset, transformation_step, is_active
        ) VALUES (
            :upstream_dataset, :downstream_dataset, :transformation_step, TRUE
        )
        ON CONFLICT (upstream_dataset, downstream_dataset, transformation_step) DO UPDATE
        SET is_active = TRUE
        """
    )

    engine = get_db_engine()
    with engine.begin() as conn:
        for row in dataset_rows:
            conn.execute(upsert_dataset_sql, row)

        for dataset_name, version_tag, schema_json, change_note in schema_rows:
            conn.execute(
                reset_schema_current_sql,
                {"dataset_name": dataset_name, "version_tag": version_tag},
            )
            conn.execute(
                upsert_schema_sql,
                {
                    "dataset_name": dataset_name,
                    "version_tag": version_tag,
                    "schema_json": json.dumps(schema_json, ensure_ascii=False, sort_keys=True),
                    "change_note": change_note,
                },
            )

        for upstream, downstream, step in lineage_rows:
            conn.execute(
                upsert_lineage_sql,
                {
                    "upstream_dataset": upstream,
                    "downstream_dataset": downstream,
                    "transformation_step": step,
                },
            )


def write_quality_snapshot(
    *,
    run_id: str,
    run_date: str,
    dataset_name: str,
    quality_report: dict[str, Any] | None,
) -> None:
    """Persist one run-level quality report snapshot."""
    if not _metadata_enabled():
        return

    report = dict(quality_report or {})
    passed = report.get("passed")
    if passed is True:
        status = "pass"
    elif passed is False:
        status = "fail"
    else:
        status = "unknown"

    sql = text(
        """
        INSERT INTO systematic_equity.quality_snapshots (
            run_id, run_date, dataset_name, quality_report, status
        ) VALUES (
            :run_id, :run_date, :dataset_name, CAST(:quality_report AS jsonb), :status
        )
        """
    )
    params = {
        "run_id": run_id,
        "run_date": run_date,
        "dataset_name": dataset_name,
        "quality_report": json.dumps(report, ensure_ascii=False, sort_keys=True),
        "status": status,
    }
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(sql, params)
