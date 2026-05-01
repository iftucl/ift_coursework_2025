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
            "logical_layer": "core",
            "time_key_column": None,
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "symbol",
            "description": "Dynamic investable universe source table.",
        },
        {
            "dataset_name": "source_a_raw_pricing_fundamentals",
            "storage_type": "minio",
            "storage_location": "csreport/raw/source_a/{market,financial}/",
            "owner_role": "Role 6",
            "refresh_frequency": "daily",
            "logical_layer": "raw",
            "time_key_column": None,
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "object_key",
            "description": "Source A merged raw payloads stored as separate market and financial canonical objects.",
        },
        {
            "dataset_name": "source_b_raw_news",
            "storage_type": "minio",
            "storage_location": "csreport/raw/source_b/news/",
            "owner_role": "Role 7",
            "refresh_frequency": "daily",
            "logical_layer": "raw",
            "time_key_column": None,
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "object_key",
            "description": "Source B raw news payloads in JSONL.",
        },
        {
            "dataset_name": "factor_observations",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.factor_observations",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "feature",
            "time_key_column": "observation_date",
            "availability_column": "publish_date",
            "supports_pit": True,
            "primary_key_def": "symbol,observation_date,factor_name",
            "description": "Atomic and final factors in long format.",
        },
        {
            "dataset_name": "financial_observations",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.financial_observations",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "core",
            "time_key_column": "report_date",
            "availability_column": "publish_date",
            "supports_pit": True,
            "primary_key_def": "symbol,report_date,metric_name",
            "description": "Atomic financial observations from providers.",
        },
        {
            "dataset_name": "benchmark_prices",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.benchmark_prices",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "reference",
            "time_key_column": "price_date",
            "availability_column": "price_date",
            "supports_pit": True,
            "primary_key_def": "ticker,price_date",
            "description": "Benchmark and reference index prices used for beta and attribution.",
        },
        {
            "dataset_name": "pipeline_runs",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.pipeline_runs",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "run_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id",
            "description": "Run-level operational audit table.",
        },
        {
            "dataset_name": "pipeline_stage_events",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.pipeline_stage_events",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "event_at",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "id",
            "description": "Append-only stage telemetry for orchestration observability.",
        },
        {
            "dataset_name": "dataset_refresh_events",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.dataset_refresh_events",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "event_at",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "id",
            "description": "Append-only evidence of dataset refreshes by run and stage.",
        },
        {
            "dataset_name": "news_articles",
            "storage_type": "mongodb",
            "storage_location": "ift_cw.news_articles",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "serving",
            "time_key_column": "published_at",
            "availability_column": "published_at",
            "supports_pit": False,
            "primary_key_def": "_id",
            "description": "Searchable news index built from MinIO raw layer.",
        },
        {
            "dataset_name": "quality_snapshots",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.quality_snapshots",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "analytics",
            "time_key_column": "run_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "id",
            "description": "Run-level validation and data-quality outcomes.",
        },
        {
            "dataset_name": "source_coverage_audit",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.source_coverage_audit",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "run_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,run_date,source_name,symbol",
            "description": "Per-run cross-source coverage contract distinguishing policy exclusions from realized processing gaps.",
        },
        {
            "dataset_name": "feature_universe_screen",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.feature_universe_screen",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "feature",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "as_of_date,symbol",
            "description": "CW2 investable universe eligibility screen before alpha portfolio selection.",
        },
        {
            "dataset_name": "feature_sub_scores",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.feature_sub_scores",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "feature",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "as_of_date,symbol,factor_group,sub_variable",
            "description": "CW2 sub-variable scores after winsorization, neutralization, and Z-scoring.",
        },
        {
            "dataset_name": "feature_factor_scores",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.feature_factor_scores",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "feature",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "as_of_date,symbol",
            "description": "CW2 first-level factor scores and regime-aware composite alpha.",
        },
        {
            "dataset_name": "feature_risk_overlay",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.feature_risk_overlay",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "feature",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "as_of_date,symbol",
            "description": "CW2 risk overlay pass/fail results for portfolio eligibility.",
        },
        {
            "dataset_name": "portfolio_target_positions",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.portfolio_target_positions",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "portfolio",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "as_of_date,portfolio_name,symbol",
            "description": "Final selected CW2 target portfolio positions after eligibility and risk screening.",
        },
        {
            "dataset_name": "feature_snapshot_registry",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.feature_snapshot_registry",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "snapshot_id",
            "description": "PIT-clean CW2 snapshot registry recording requested vs resolved as-of dates and gating outcomes.",
        },
        {
            "dataset_name": "portfolio_snapshot_registry",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.portfolio_snapshot_registry",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "as_of_date,portfolio_name",
            "description": "Aggregated monthly portfolio snapshot metadata for audit and replay.",
        },
        {
            "dataset_name": "model_input_manifests",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.model_input_manifests",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "manifest_id",
            "description": "Immutable manifests of model inputs used by CW2 feature, risk, and portfolio generation.",
        },
        {
            "dataset_name": "portfolio_recommendations",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.portfolio_recommendations",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "serving",
            "time_key_column": "as_of_date",
            "availability_column": "as_of_date",
            "supports_pit": True,
            "primary_key_def": "recommendation_id",
            "description": "Formal top-level portfolio recommendation objects for approval and publication.",
        },
        {
            "dataset_name": "portfolio_recommendation_items",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.portfolio_recommendation_items",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "serving",
            "time_key_column": None,
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "recommendation_id,symbol",
            "description": "Item-level portfolio recommendation constituents with factor rationale.",
        },
        {
            "dataset_name": "portfolio_recommendation_events",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.portfolio_recommendation_events",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "event_timestamp",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "id",
            "description": "Append-only recommendation workflow event log.",
        },
        {
            "dataset_name": "portfolio_recommendation_decisions",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.portfolio_recommendation_decisions",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "decision_timestamp",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "id",
            "description": "Explicit human/system approval, rejection, and publication decisions for recommendations.",
        },
        {
            "dataset_name": "backtest_runs",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_runs",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": "end_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id",
            "description": "Top-level CW2 backtest run metadata and versioned configuration snapshots.",
        },
        {
            "dataset_name": "backtest_holdings",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_holdings",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": "rebalance_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,rebalance_date,symbol",
            "description": "Per-period realized holdings, requested weights, executed weights, and turnover attribution.",
        },
        {
            "dataset_name": "backtest_performance",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_performance",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": "period_end_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,period_end_date",
            "description": "Period-level gross/net returns, costs, cash, and benchmark comparisons for each backtest run.",
        },
        {
            "dataset_name": "backtest_cash_ledger",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_cash_ledger",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": "rebalance_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,rebalance_date",
            "description": "Formal cash ledger for executed turnover, liquidity clipping, and execution-cost audit.",
        },
        {
            "dataset_name": "backtest_metrics",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_metrics",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": None,
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,metric_group,metric_name",
            "description": "Summary return, risk, and turnover metrics computed from a completed backtest run.",
        },
        {
            "dataset_name": "backtest_intraday_events",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_intraday_events",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "audit",
            "time_key_column": "event_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "id",
            "description": "Append-only CW2 risk-action event log for stop-loss, regime, weekly, and event-driven overlays.",
        },
        {
            "dataset_name": "backtest_intraday_daily_state",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_intraday_daily_state",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "audit",
            "time_key_column": "state_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,state_date,symbol",
            "description": "Daily realized CW2 overlay state for audit and replay of risk actions through the holding period.",
        },
        {
            "dataset_name": "backtest_benchmark_nav",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_benchmark_nav",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": "period_end_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,period_end_date,series_name",
            "description": "Benchmark, universe, and static-baseline NAV paths aligned to the strategy backtest periods.",
        },
        {
            "dataset_name": "backtest_relative_metrics",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_relative_metrics",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": None,
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,versus_series,metric_name",
            "description": "Relative performance metrics versus configured benchmark series.",
        },
        {
            "dataset_name": "backtest_regime_attribution",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_regime_attribution",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": None,
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,regime,versus_series",
            "description": "Regime-sliced strategy versus benchmark attribution statistics.",
        },
        {
            "dataset_name": "backtest_covariance_metrics",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_covariance_metrics",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": "rebalance_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,rebalance_date,period_end_date,series_name,versus_series,metric_name",
            "description": "Ex-ante covariance diagnostics for strategy and benchmark weight sets.",
        },
        {
            "dataset_name": "backtest_covariance_contributions",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_covariance_contributions",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": "rebalance_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,rebalance_date,period_end_date,series_name,dimension_type,dimension_name",
            "description": "Risk-contribution decomposition from the covariance-aware analysis layer.",
        },
        {
            "dataset_name": "backtest_scorecard",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_scorecard",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "analytics",
            "time_key_column": None,
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_id,criterion_id",
            "description": "Structured CW2 backtest scorecard used for final analysis sign-off.",
        },
        {
            "dataset_name": "backtest_reports",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_reports",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "serving",
            "time_key_column": "created_at",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "report_id",
            "description": "Backtest report headers and versioned report-level metadata.",
        },
        {
            "dataset_name": "backtest_report_artifacts",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.backtest_report_artifacts",
            "owner_role": "Role 8",
            "refresh_frequency": "ad_hoc",
            "logical_layer": "serving",
            "time_key_column": "created_at",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "report_id,artifact_name",
            "description": "Chart, markdown, and JSON artifact manifest for each generated backtest report.",
        },
        {
            "dataset_name": "portfolio_update_decisions",
            "storage_type": "postgresql",
            "storage_location": "systematic_equity.portfolio_update_decisions",
            "owner_role": "Role 8",
            "refresh_frequency": "daily",
            "logical_layer": "audit",
            "time_key_column": "run_date",
            "availability_column": None,
            "supports_pit": False,
            "primary_key_def": "run_date,portfolio_name",
            "description": "Daily operating decision registry describing whether CW2 should monitor, review risk, rebalance, or block.",
        },
    ]

    schema_rows = [
        (
            "factor_observations",
            "v2",
            {
                "columns": [
                    "symbol",
                    "observation_date",
                    "factor_name",
                    "factor_value",
                    "source",
                    "metric_frequency",
                    "source_report_date",
                    "publish_date",
                ]
            },
            "Added PIT publish_date to curated factor schema.",
        ),
        (
            "financial_observations",
            "v3",
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
                    "value_source",
                    "as_of",
                    "publish_date",
                    "publish_date_source",
                ]
            },
            "Added explicit value-source and publish-date-source provenance to financial observations.",
        ),
        (
            "benchmark_prices",
            "v1",
            {
                "columns": [
                    "ticker",
                    "price_date",
                    "close_price",
                    "daily_return",
                    "source",
                ]
            },
            "Initial benchmark price schema.",
        ),
        (
            "pipeline_stage_events",
            "v1",
            {
                "columns": [
                    "run_id",
                    "stage_name",
                    "status",
                    "rows_in",
                    "rows_out",
                    "elapsed_ms",
                    "details_json",
                    "event_at",
                ]
            },
            "Initial append-only stage event schema.",
        ),
        (
            "dataset_refresh_events",
            "v1",
            {
                "columns": [
                    "run_id",
                    "run_date",
                    "dataset_name",
                    "stage_name",
                    "status",
                    "rows_written",
                    "details_json",
                    "event_at",
                ]
            },
            "Initial append-only dataset refresh event schema.",
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
        (
            "source_a_raw_pricing_fundamentals",
            "v5",
            {
                "fields": [
                    "symbol",
                    "run_date",
                    "as_of_date",
                    "rows",
                    "history",
                    "history[].observation_date",
                    "history[].Open",
                    "history[].High",
                    "history[].Low",
                    "history[].Close",
                    "history[].Dividends",
                    "history[].Volume",
                    "fundamentals",
                    "fundamentals.publish_date",
                    "fundamentals.publish_date_by_metric",
                    "fundamentals.publish_date_source_by_metric",
                    "fundamentals.value_source_by_metric",
                    "fundamentals.provider_values_by_metric",
                    "fundamentals.quarterly_fundamentals[].value_source_by_metric",
                    "fundamentals.quarterly_fundamentals[].provider_values_by_metric",
                    "fundamentals.quarterly_fundamentals[].publish_date_by_metric",
                    "fundamentals.quarterly_fundamentals[].publish_date_source_by_metric",
                    "total_debt",
                    "source_used",
                    "normalized_schema_version",
                    "provider_payload_version",
                    "schema_validation_status",
                    "schema_validation_errors",
                    "raw_layer",
                    "merge_policy",
                ]
            },
            "Normalized Source A raw market/financial schema with split MinIO objects and per-metric provider candidate storage.",
        ),
        (
            "source_b_raw_news",
            "v2",
            {
                "fields": [
                    "article_id",
                    "symbol",
                    "ticker",
                    "publish_date",
                    "time_published",
                    "time_precision",
                    "title",
                    "headline",
                    "summary",
                    "url",
                    "source",
                    "data_source",
                    "provider_payload_version",
                    "normalized_schema_version",
                    "schema_validation_status",
                    "schema_validation_errors",
                    "topics",
                    "ticker_hits",
                    "category",
                    "lang",
                ]
            },
            "Normalized Source B raw article schema with provider payload versioning and validation metadata.",
        ),
        (
            "source_coverage_audit",
            "v1",
            {
                "columns": [
                    "run_id",
                    "run_date",
                    "source_name",
                    "symbol",
                    "parent_in_universe",
                    "policy_eligible",
                    "routing_eligible",
                    "expected_in_run",
                    "realized_in_run",
                    "content_available",
                    "status",
                    "reason_code",
                    "details_json",
                    "updated_at",
                ]
            },
            "Initial symbol-level source coverage contract schema for CW1.",
        ),
        (
            "feature_universe_screen",
            "v1",
            {
                "columns": [
                    "as_of_date",
                    "symbol",
                    "country",
                    "gics_sector",
                    "log_market_cap",
                    "liquidity_20d",
                    "pass_country",
                    "pass_market_cap",
                    "pass_liquidity",
                    "pass_all",
                    "source",
                ]
            },
            "Initial CW2 investable universe screen schema.",
        ),
        (
            "feature_sub_scores",
            "v1",
            {
                "columns": [
                    "as_of_date",
                    "symbol",
                    "factor_group",
                    "sub_variable",
                    "raw_value",
                    "winsorized_value",
                    "neutralized_value",
                    "z_score",
                    "gics_sector",
                    "source",
                ]
            },
            "Initial CW2 sub-variable score schema.",
        ),
        (
            "feature_factor_scores",
            "v1",
            {
                "columns": [
                    "as_of_date",
                    "symbol",
                    "quality_score",
                    "value_score",
                    "market_technical_score",
                    "sentiment_score",
                    "dividend_score",
                    "composite_alpha",
                    "regime",
                    "vix_level",
                    "source",
                ]
            },
            "Initial CW2 first-level factor and composite alpha schema.",
        ),
        (
            "feature_risk_overlay",
            "v1",
            {
                "columns": [
                    "as_of_date",
                    "symbol",
                    "log_market_cap",
                    "liquidity_20d",
                    "volatility_60d",
                    "missing_factor_pct",
                    "factor_groups_present",
                    "pass_market_cap",
                    "pass_liquidity",
                    "pass_volatility",
                    "pass_factor_coverage",
                    "pass_data_quality",
                    "pass_all",
                    "source",
                ]
            },
            "Initial CW2 risk overlay schema.",
        ),
        (
            "portfolio_target_positions",
            "v1",
            {
                "columns": [
                    "as_of_date",
                    "portfolio_name",
                    "symbol",
                    "selection_rank",
                    "target_weight",
                    "weighting_scheme",
                    "composite_alpha",
                    "regime",
                    "gics_sector",
                    "country",
                    "source",
                ]
            },
            "Initial CW2 portfolio target position schema.",
        ),
        (
            "feature_snapshot_registry",
            "v1",
            {
                "columns": [
                    "snapshot_id",
                    "requested_as_of_date",
                    "as_of_date",
                    "snapshot_status",
                    "scoring_universe",
                    "investable_universe",
                    "min_scoring_universe",
                    "min_investable_universe",
                    "allow_factor_scoring",
                    "allow_portfolio_construction",
                    "factor_row_count",
                    "financial_row_count",
                    "previous_position_count",
                    "vix_level",
                    "covariance_method",
                    "covariance_symbol_count",
                    "config_snapshot",
                ]
            },
            "Initial CW2 PIT snapshot registry schema.",
        ),
        (
            "portfolio_snapshot_registry",
            "v1",
            {
                "columns": [
                    "snapshot_id",
                    "as_of_date",
                    "portfolio_name",
                    "snapshot_status",
                    "num_positions",
                    "gross_target_weight",
                    "avg_composite_alpha",
                    "expected_turnover",
                    "weighting_scheme",
                    "ranking_mode",
                    "regime",
                    "summary_json",
                ]
            },
            "Initial CW2 portfolio snapshot registry schema.",
        ),
        (
            "model_input_manifests",
            "v1",
            {
                "columns": [
                    "manifest_id",
                    "snapshot_id",
                    "as_of_date",
                    "manifest_type",
                    "payload_json",
                ]
            },
            "Initial model input manifest schema for CW2 feature, risk, portfolio, and recommendation flows.",
        ),
        (
            "portfolio_recommendations",
            "v1",
            {
                "columns": [
                    "recommendation_id",
                    "recommendation_name",
                    "as_of_date",
                    "portfolio_name",
                    "recommendation_status",
                    "benchmark_ticker",
                    "regime",
                    "weighting_scheme",
                    "ranking_mode",
                    "num_positions",
                    "gross_target_weight",
                    "expected_turnover",
                    "avg_composite_alpha",
                    "config_snapshot",
                    "summary_json",
                    "approved_at",
                    "approved_by",
                    "decision_notes",
                ]
            },
            "Initial formal portfolio recommendation header schema.",
        ),
        (
            "portfolio_recommendation_items",
            "v1",
            {
                "columns": [
                    "recommendation_id",
                    "symbol",
                    "selection_rank",
                    "target_weight",
                    "previous_weight",
                    "trade_weight",
                    "position_action",
                    "composite_alpha",
                    "quality_score",
                    "value_score",
                    "market_technical_score",
                    "sentiment_score",
                    "dividend_score",
                    "gics_sector",
                    "country",
                    "regime",
                    "weighting_scheme",
                    "ranking_mode",
                    "ranking_score",
                    "turnover_limited",
                    "rationale_json",
                ]
            },
            "Initial item-level formal portfolio recommendation schema.",
        ),
        (
            "portfolio_recommendation_events",
            "v1",
            {
                "columns": [
                    "recommendation_id",
                    "event_type",
                    "event_timestamp",
                    "actor",
                    "notes",
                    "payload_json",
                ]
            },
            "Initial recommendation event-log schema.",
        ),
        (
            "portfolio_recommendation_decisions",
            "v1",
            {
                "columns": [
                    "recommendation_id",
                    "decision_type",
                    "actor",
                    "decision_timestamp",
                    "notes",
                    "payload_json",
                ]
            },
            "Initial recommendation approval / rejection / publication decision schema.",
        ),
        (
            "backtest_runs",
            "v1",
            {
                "columns": [
                    "run_id",
                    "run_name",
                    "start_date",
                    "end_date",
                    "rebalance_freq",
                    "execution_lag",
                    "transaction_cost_bps",
                    "weighting",
                    "top_n",
                    "benchmark_ticker",
                    "model_version",
                    "factor_definition_version",
                    "covariance_method_version",
                    "risk_overlay_policy_version",
                    "backtest_engine_version",
                    "config_snapshot",
                    "status",
                ]
            },
            "Initial CW2 backtest run metadata schema.",
        ),
        (
            "backtest_holdings",
            "v1",
            {
                "columns": [
                    "run_id",
                    "rebalance_date",
                    "execution_date",
                    "symbol",
                    "target_weight",
                    "executed_weight",
                    "drifted_weight",
                    "turnover_contribution",
                    "requested_turnover_contribution",
                    "composite_alpha",
                    "regime",
                ]
            },
            "Initial realized backtest holdings schema.",
        ),
        (
            "backtest_performance",
            "v1",
            {
                "columns": [
                    "run_id",
                    "period_end_date",
                    "gross_return",
                    "net_return",
                    "benchmark_return",
                    "excess_return",
                    "portfolio_nav",
                    "benchmark_nav",
                    "turnover",
                    "transaction_cost",
                    "slippage_cost",
                    "cash_end_weight",
                    "regime",
                ]
            },
            "Initial period-level backtest performance schema.",
        ),
        (
            "backtest_cash_ledger",
            "v1",
            {
                "columns": [
                    "run_id",
                    "rebalance_date",
                    "execution_date",
                    "period_end_date",
                    "cash_start_weight",
                    "cash_after_execution_weight",
                    "cash_end_weight",
                    "requested_turnover",
                    "executed_turnover",
                    "total_cost",
                    "liquidity_clipped",
                ]
            },
            "Initial execution cash-ledger schema.",
        ),
        (
            "backtest_metrics",
            "v1",
            {
                "columns": [
                    "run_id",
                    "metric_group",
                    "metric_name",
                    "metric_value",
                    "metric_unit",
                ]
            },
            "Initial summary backtest metric schema.",
        ),
        (
            "backtest_intraday_events",
            "v1",
            {
                "columns": [
                    "run_id",
                    "event_date",
                    "event_type",
                    "symbol",
                    "action_scope",
                    "action_family",
                    "urgency",
                    "reason_code",
                    "expected_turnover",
                    "expected_cost",
                    "payload_json",
                ]
            },
            "Initial CW2 intraday/event-driven risk-action event schema.",
        ),
        (
            "backtest_intraday_daily_state",
            "v1",
            {
                "columns": [
                    "run_id",
                    "state_date",
                    "symbol",
                    "regime",
                    "weight",
                    "cash_weight",
                    "payload_json",
                ]
            },
            "Initial daily overlay state schema.",
        ),
        (
            "backtest_benchmark_nav",
            "v1",
            {
                "columns": [
                    "run_id",
                    "period_end_date",
                    "series_name",
                    "nav",
                    "period_return",
                    "num_holdings",
                    "regime",
                ]
            },
            "Initial backtest benchmark path schema.",
        ),
        (
            "backtest_relative_metrics",
            "v1",
            {
                "columns": [
                    "run_id",
                    "versus_series",
                    "metric_name",
                    "metric_value",
                    "metric_unit",
                ]
            },
            "Initial relative metric schema.",
        ),
        (
            "backtest_regime_attribution",
            "v1",
            {
                "columns": [
                    "run_id",
                    "regime",
                    "versus_series",
                    "n_periods",
                    "excess_ann_return",
                    "strategy_sharpe",
                    "hit_rate",
                ]
            },
            "Initial regime attribution schema.",
        ),
        (
            "backtest_covariance_metrics",
            "v1",
            {
                "columns": [
                    "run_id",
                    "rebalance_date",
                    "period_end_date",
                    "series_name",
                    "versus_series",
                    "metric_name",
                    "metric_value",
                    "covariance_method",
                    "lookback_days",
                ]
            },
            "Initial covariance diagnostics schema.",
        ),
        (
            "backtest_covariance_contributions",
            "v1",
            {
                "columns": [
                    "run_id",
                    "rebalance_date",
                    "period_end_date",
                    "series_name",
                    "dimension_type",
                    "dimension_name",
                    "risk_contribution_pct",
                    "component_volatility_contribution",
                    "covariance_method",
                    "lookback_days",
                ]
            },
            "Initial covariance contribution schema.",
        ),
        (
            "backtest_scorecard",
            "v1",
            {
                "columns": [
                    "run_id",
                    "criterion_id",
                    "criterion_name",
                    "passed",
                    "evidence",
                ]
            },
            "Initial structured backtest scorecard schema.",
        ),
        (
            "backtest_reports",
            "v1",
            {
                "columns": [
                    "report_id",
                    "run_id",
                    "report_name",
                    "output_dir",
                    "model_version",
                    "factor_definition_version",
                    "covariance_method_version",
                    "risk_overlay_policy_version",
                    "backtest_engine_version",
                    "reporting_version",
                    "config_snapshot",
                    "summary_json",
                ]
            },
            "Initial backtest report registry schema.",
        ),
        (
            "backtest_report_artifacts",
            "v1",
            {
                "columns": [
                    "report_id",
                    "run_id",
                    "artifact_name",
                    "artifact_role",
                    "artifact_format",
                    "artifact_path",
                    "artifact_metadata",
                ]
            },
            "Initial backtest report artifact manifest schema.",
        ),
        (
            "portfolio_update_decisions",
            "v1",
            {
                "columns": [
                    "run_date",
                    "portfolio_name",
                    "decision_scope",
                    "recommended_mode",
                    "reason_code",
                    "is_month_end_rebalance_day",
                    "requires_human_review",
                    "latest_snapshot_as_of_date",
                    "latest_recommendation_as_of_date",
                    "latest_snapshot_position_count",
                    "trigger_symbol_count",
                    "trigger_summary_json",
                    "config_snapshot",
                ]
            },
            "Initial daily portfolio update-decision schema.",
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
            "benchmark_prices",
            "factor_observations",
            "market_benchmark_enrichment",
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
        (
            "pipeline_runs",
            "pipeline_stage_events",
            "emit_stage_telemetry",
        ),
        (
            "pipeline_stage_events",
            "dataset_refresh_events",
            "emit_dataset_refresh_evidence",
        ),
        (
            "company_static",
            "source_coverage_audit",
            "source_coverage_contract_validation",
        ),
        (
            "source_a_raw_pricing_fundamentals",
            "source_coverage_audit",
            "source_coverage_contract_validation",
        ),
        (
            "source_b_raw_news",
            "source_coverage_audit",
            "source_coverage_contract_validation",
        ),
        (
            "company_static",
            "feature_universe_screen",
            "cw2_investable_universe_country_sector_screen",
        ),
        (
            "factor_observations",
            "feature_universe_screen",
            "cw2_investable_universe_size_liquidity_screen",
        ),
        (
            "factor_observations",
            "feature_sub_scores",
            "cw2_feature_engine_sub_scores",
        ),
        (
            "financial_observations",
            "feature_sub_scores",
            "cw2_feature_engine_sub_scores",
        ),
        (
            "feature_sub_scores",
            "feature_factor_scores",
            "cw2_factor_score_aggregation",
        ),
        (
            "feature_universe_screen",
            "feature_factor_scores",
            "cw2_factor_model_investable_universe_filter",
        ),
        (
            "feature_factor_scores",
            "feature_risk_overlay",
            "cw2_risk_overlay_screen",
        ),
        (
            "feature_universe_screen",
            "portfolio_target_positions",
            "cw2_portfolio_eligibility_gate",
        ),
        (
            "feature_factor_scores",
            "portfolio_target_positions",
            "cw2_portfolio_rank_and_select",
        ),
        (
            "feature_risk_overlay",
            "portfolio_target_positions",
            "cw2_portfolio_risk_gate",
        ),
        (
            "feature_factor_scores",
            "feature_snapshot_registry",
            "cw2_snapshot_registry_materialization",
        ),
        (
            "feature_risk_overlay",
            "portfolio_snapshot_registry",
            "cw2_portfolio_snapshot_materialization",
        ),
        (
            "portfolio_target_positions",
            "portfolio_recommendations",
            "cw2_recommendation_header_publish",
        ),
        (
            "portfolio_target_positions",
            "portfolio_recommendation_items",
            "cw2_recommendation_item_publish",
        ),
        (
            "portfolio_recommendations",
            "portfolio_recommendation_events",
            "cw2_recommendation_event_log",
        ),
        (
            "portfolio_recommendations",
            "portfolio_recommendation_decisions",
            "cw2_recommendation_decision_workflow",
        ),
        (
            "portfolio_target_positions",
            "portfolio_update_decisions",
            "cw2_daily_update_decision_gate",
        ),
        (
            "feature_factor_scores",
            "portfolio_update_decisions",
            "cw2_daily_event_trigger_review",
        ),
        (
            "portfolio_target_positions",
            "backtest_runs",
            "cw2_backtest_signal_snapshot_run",
        ),
        (
            "backtest_runs",
            "backtest_holdings",
            "cw2_backtest_realized_holdings",
        ),
        (
            "backtest_runs",
            "backtest_performance",
            "cw2_backtest_period_performance",
        ),
        (
            "backtest_runs",
            "backtest_cash_ledger",
            "cw2_backtest_cash_ledger",
        ),
        (
            "backtest_runs",
            "backtest_metrics",
            "cw2_backtest_summary_metrics",
        ),
        (
            "backtest_runs",
            "backtest_intraday_events",
            "cw2_intraday_overlay_event_log",
        ),
        (
            "backtest_runs",
            "backtest_intraday_daily_state",
            "cw2_intraday_overlay_daily_state",
        ),
        (
            "backtest_performance",
            "backtest_benchmark_nav",
            "cw2_analysis_benchmark_paths",
        ),
        (
            "backtest_holdings",
            "backtest_covariance_metrics",
            "cw2_analysis_covariance_diagnostics",
        ),
        (
            "backtest_holdings",
            "backtest_covariance_contributions",
            "cw2_analysis_covariance_diagnostics",
        ),
        (
            "backtest_performance",
            "backtest_relative_metrics",
            "cw2_analysis_relative_metrics",
        ),
        (
            "backtest_performance",
            "backtest_regime_attribution",
            "cw2_analysis_regime_attribution",
        ),
        (
            "backtest_relative_metrics",
            "backtest_scorecard",
            "cw2_analysis_scorecard",
        ),
        (
            "backtest_covariance_metrics",
            "backtest_scorecard",
            "cw2_analysis_scorecard",
        ),
        (
            "backtest_scorecard",
            "backtest_reports",
            "cw2_reporting_publish",
        ),
        (
            "backtest_reports",
            "backtest_report_artifacts",
            "cw2_reporting_artifact_manifest",
        ),
    ]

    upsert_dataset_sql = text("""
        INSERT INTO systematic_equity.dataset_registry (
            dataset_name, storage_type, storage_location, owner_role, refresh_frequency,
            logical_layer, time_key_column, availability_column, supports_pit,
            primary_key_def, description, is_active
        ) VALUES (
            :dataset_name, :storage_type, :storage_location, :owner_role, :refresh_frequency,
            :logical_layer, :time_key_column, :availability_column, :supports_pit,
            :primary_key_def, :description, TRUE
        )
        ON CONFLICT (dataset_name) DO UPDATE
        SET storage_type = EXCLUDED.storage_type,
            storage_location = EXCLUDED.storage_location,
            owner_role = EXCLUDED.owner_role,
            refresh_frequency = EXCLUDED.refresh_frequency,
            logical_layer = EXCLUDED.logical_layer,
            time_key_column = EXCLUDED.time_key_column,
            availability_column = EXCLUDED.availability_column,
            supports_pit = EXCLUDED.supports_pit,
            primary_key_def = EXCLUDED.primary_key_def,
            description = EXCLUDED.description,
            is_active = TRUE,
            updated_at = CURRENT_TIMESTAMP
        """)
    reset_schema_current_sql = text("""
        UPDATE systematic_equity.schema_versions
        SET is_current = FALSE, valid_to = CURRENT_TIMESTAMP
        WHERE dataset_name = :dataset_name
          AND is_current = TRUE
          AND version_tag <> :version_tag
        """)
    upsert_schema_sql = text("""
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
        """)
    upsert_lineage_sql = text("""
        INSERT INTO systematic_equity.lineage_edges (
            upstream_dataset, downstream_dataset, transformation_step, is_active
        ) VALUES (
            :upstream_dataset, :downstream_dataset, :transformation_step, TRUE
        )
        ON CONFLICT (upstream_dataset, downstream_dataset, transformation_step) DO UPDATE
        SET is_active = TRUE
        """)

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

    sql = text("""
        INSERT INTO systematic_equity.quality_snapshots (
            run_id, run_date, dataset_name, quality_report, status
        ) VALUES (
            :run_id, :run_date, :dataset_name, CAST(:quality_report AS jsonb), :status
        )
        ON CONFLICT (run_id, run_date, dataset_name) DO UPDATE
        SET
            quality_report = EXCLUDED.quality_report,
            status = EXCLUDED.status
        """)
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


def write_source_coverage_audit(
    *,
    run_id: str,
    run_date: str,
    rows: list[dict[str, Any]],
) -> int:
    """Persist one run-level batch of source coverage rows."""
    if not _metadata_enabled() or not rows:
        return 0

    sql = text("""
        INSERT INTO systematic_equity.source_coverage_audit (
            run_id,
            run_date,
            source_name,
            symbol,
            parent_in_universe,
            policy_eligible,
            routing_eligible,
            expected_in_run,
            realized_in_run,
            content_available,
            status,
            reason_code,
            details_json
        ) VALUES (
            :run_id,
            :run_date,
            :source_name,
            :symbol,
            :parent_in_universe,
            :policy_eligible,
            :routing_eligible,
            :expected_in_run,
            :realized_in_run,
            :content_available,
            :status,
            :reason_code,
            CAST(:details_json AS jsonb)
        )
        ON CONFLICT (run_id, run_date, source_name, symbol) DO UPDATE
        SET parent_in_universe = EXCLUDED.parent_in_universe,
            policy_eligible = EXCLUDED.policy_eligible,
            routing_eligible = EXCLUDED.routing_eligible,
            expected_in_run = EXCLUDED.expected_in_run,
            realized_in_run = EXCLUDED.realized_in_run,
            content_available = EXCLUDED.content_available,
            status = EXCLUDED.status,
            reason_code = EXCLUDED.reason_code,
            details_json = EXCLUDED.details_json,
            updated_at = NOW()
        """)

    engine = get_db_engine()
    with engine.begin() as conn:
        for row in rows:
            payload = {
                "run_id": run_id,
                "run_date": run_date,
                "source_name": str(row.get("source_name") or "").strip().lower(),
                "symbol": str(row.get("symbol") or "").strip().upper(),
                "parent_in_universe": bool(row.get("parent_in_universe", True)),
                "policy_eligible": bool(row.get("policy_eligible", False)),
                "routing_eligible": bool(row.get("routing_eligible", True)),
                "expected_in_run": bool(row.get("expected_in_run", False)),
                "realized_in_run": bool(row.get("realized_in_run", False)),
                "content_available": (
                    None
                    if row.get("content_available") is None
                    else bool(row.get("content_available"))
                ),
                "status": str(row.get("status") or "unknown").strip().lower(),
                "reason_code": str(row.get("reason_code") or "").strip().lower() or None,
                "details_json": json.dumps(
                    dict(row.get("details") or {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
            conn.execute(sql, payload)
    return len(rows)
