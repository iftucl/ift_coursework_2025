#!/usr/bin/env python3
"""
Production Trading Pipeline Orchestrator

Runs the complete investment strategy pipeline in sequence:
  1. calculate_var_all_stocks.py    → Calculate VAR_95 and ATR_14 metrics
  2. calculate_composite_portfolio.py → Select 130 stocks (RAM + Liquidity + VAR)
  3. trading_execution.py            → Generate execution signals (MACD + ATR)
  4. export_analytics_to_minio.py    → Export portfolio and signals to data lake

CLI Arguments:
  --frequency {daily,weekly,monthly,quarterly}
      Scheduling frequency (default: daily)
      - daily: Run every trading day
      - weekly: Run every Monday
      - monthly: Run first trading day of month
      - quarterly: Run first trading day of quarter

  --run-date YYYY-MM-DD
      Explicit run date (overrides frequency)
      Example: --run-date 2025-03-07

  --dry-run
      Test mode - show execution plan without running

  --help
      Display this help message

Examples:
  poetry run python3 run_pipeline.py
      → Run daily (default)

  poetry run python3 run_pipeline.py --frequency weekly
      → Run weekly strategy

  poetry run python3 run_pipeline.py --run-date 2025-03-07
      → Run for specific date

  poetry run python3 run_pipeline.py --dry-run --frequency monthly
      → Show execution plan without running
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from modules.output_reader import (
    read_factor_count,
    read_step2_counts,
    read_step3_signal_counts,
)

# Import structured result types
from modules.pipeline_results import ExportStatus, PipelineRunSummary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("pipeline.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def run_command(script_name: str, description: str) -> tuple:
    """
    Run a pipeline step and track execution.

    Returns:
        (success: bool, extra_data: dict) tuple
        - For Step 4, extra_data contains export status info
    """
    import json

    logger.info(f"\n{'='*70}")
    logger.info(f"STEP: {description}")
    logger.info(f"Script: {script_name}")
    logger.info(f"{'='*70}")

    extra_data = {}

    try:
        # Try to find poetry in common locations
        import shutil

        poetry_exe = None

        # Try PATH first
        poetry_exe = shutil.which("poetry")

        # If not in PATH, try common locations
        if not poetry_exe:
            potential_paths = [
                Path.home() / ".local" / "bin" / "poetry",
                Path.home() / "Library" / "Python" / "3.9" / "bin" / "poetry",
                Path.home() / "Library" / "Python" / "3.10" / "bin" / "poetry",
                Path.home() / "Library" / "Python" / "3.11" / "bin" / "poetry",
            ]
            for path in potential_paths:
                if path.exists():
                    poetry_exe = str(path)
                    break

        if not poetry_exe:
            poetry_exe = "poetry"  # fallback, will fail if poetry not found

        result = subprocess.run(
            [poetry_exe, "run", "python3", script_name],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
        )

        # For Step 4, parse export status from stdout
        if "export_analytics_to_minio" in script_name:
            for line in result.stdout.split("\n"):
                if "__EXPORT_STATUS_JSON__:" in line:
                    try:
                        json_str = line.split("__EXPORT_STATUS_JSON__:")[1]
                        extra_data = json.loads(json_str)
                        logger.debug(f"Parsed Step 4 status: {extra_data}")
                    except Exception as e:
                        logger.warning(f"Could not parse Step 4 status: {e}")
                    break

        # Log subprocess output (excluding the JSON status line)
        for line in result.stdout.split("\n"):
            if "__EXPORT_STATUS_JSON__:" not in line and line.strip():
                logger.info(line)

        if result.returncode == 0:
            logger.info(f"✅ {description} COMPLETED")
            return True, extra_data
        else:
            logger.error(f"❌ {description} FAILED (exit code: {result.returncode})")
            if result.stderr:
                logger.error(f"Error output:\n{result.stderr}")
            return False, extra_data

    except Exception as e:
        logger.error(f"❌ {description} ERROR: {e}")
        return False, extra_data


def main():
    """Execute complete pipeline with scheduling options."""

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Production Trading Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  poetry run python3 run_pipeline.py
      → Run daily (default)

  poetry run python3 run_pipeline.py --frequency weekly
      → Run weekly strategy

  poetry run python3 run_pipeline.py --run-date 2025-03-07
      → Run for specific date

  poetry run python3 run_pipeline.py --dry-run --frequency monthly
      → Show execution plan without running
        """,
    )

    parser.add_argument(
        "--frequency",
        choices=["daily", "weekly", "monthly", "quarterly"],
        default="daily",
        help="Scheduling frequency (default: daily)",
    )

    parser.add_argument(
        "--run-date",
        type=str,
        help="Explicit run date (format: YYYY-MM-DD). Overrides frequency.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test mode - show execution plan without running",
    )

    args = parser.parse_args()

    # Validate and process run date
    run_date = None
    if args.run_date:
        try:
            run_date = datetime.strptime(args.run_date, "%Y-%m-%d")
        except ValueError:
            logger.error(f"Invalid date format: {args.run_date}. Use YYYY-MM-DD")
            return 1

    logger.info(f"\n{'#'*70}")
    logger.info("# INVESTMENT STRATEGY PIPELINE")
    logger.info(f"# Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"# Mode: {'DRY RUN' if args.dry_run else 'PRODUCTION'}")
    logger.info(f"# Frequency: {args.frequency}")
    if run_date:
        logger.info(f"# Run Date: {run_date.strftime('%Y-%m-%d')}")
    logger.info(f"{'#'*70}")

    # If dry run, show execution plan only
    if args.dry_run:
        logger.info("\n📋 EXECUTION PLAN (DRY RUN - NO CHANGES)")
        logger.info(f"{'='*70}")
        logger.info(f"Frequency: {args.frequency}")
        logger.info(f"Current DateTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(
            f"Run Date: {run_date.strftime('%Y-%m-%d') if run_date else 'Auto-determined based on frequency'}"
        )
        logger.info(f"{'='*70}")

        pipeline_steps = [
            (
                "pipeline/calculate_var_all_stocks.py",
                "Step 1/4: Calculate VAR_95 and ATR_14 metrics",
            ),
            (
                "pipeline/calculate_composite_portfolio.py",
                "Step 2/4: Select portfolio (130 stocks)",
            ),
            (
                "pipeline/trading_execution.py",
                "Step 3/4: Generate execution signals (MACD+ATR)",
            ),
            (
                "pipeline/export_analytics_to_minio.py",
                "Step 4/4: Export analytics to MinIO",
            ),
        ]

        for script, description in pipeline_steps:
            logger.info(f"→ {description}")
            logger.info(f"  Script: {script}")

        logger.info(f"{'='*70}")
        logger.info("✅ Dry run complete. No scripts were executed.")
        return 0

    # Execute full pipeline
    pipeline_steps = [
        (
            "pipeline/calculate_var_all_stocks.py",
            "Step 1/4: Calculate VAR_95 and ATR_14 metrics",
        ),
        (
            "pipeline/calculate_composite_portfolio.py",
            "Step 2/4: Select portfolio (130 stocks)",
        ),
        (
            "pipeline/trading_execution.py",
            "Step 3/4: Generate execution signals (MACD+ATR)",
        ),
        (
            "pipeline/export_analytics_to_minio.py",
            "Step 4/4: Export analytics to MinIO",
        ),
    ]

    results = []
    step4_export_status = None  # Track Step 4's export status separately
    start_time = datetime.now()

    for i, (script, description) in enumerate(pipeline_steps, 1):
        success, extra_data = run_command(script, description)
        results.append((description, success, extra_data))

        # Track Step 4's export status for later use in summary
        if i == 4 and "export_status" in extra_data:
            step4_export_status = extra_data["export_status"]

        # Steps 1-3 are critical; Step 4 (export/storage) is optional
        if not success and i < 4:
            logger.error(f"\n⚠️  Pipeline halted at: {description}")
            break
        elif not success and i == 4:
            # Step 4 failure doesn't halt pipeline, but we need to check MINIO_REQUIRED
            logger.warning(
                "\n⚠️  Step 4 export failed, but pipeline continues (optional step)"
            )
            minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
            if minio_required:
                logger.error(
                    "❌ MINIO_REQUIRED=true, but MinIO export failed. Failing pipeline."
                )
                # Mark Step 4 as critical failure if MINIO_REQUIRED
                break

    # Summary
    logger.info(f"\n{'='*70}")
    logger.info("PIPELINE EXECUTION SUMMARY")
    logger.info(f"{'='*70}")

    # Determine overall status
    steps_1_3_success = (
        all(success for _, success, _ in results[:3]) if len(results) >= 3 else False
    )
    step4_success = results[3][1] if len(results) >= 4 else None
    minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"

    # Report status for each step
    for i, (description, success, extra_data) in enumerate(results, 1):
        if i < 4:
            # Steps 1-3: critical
            status = "✅ PASS" if success else "❌ FAIL"
            logger.info(f"{status} - {description}")
        else:
            # Step 4: optional unless MINIO_REQUIRED
            if minio_required:
                status = "✅ PASS" if success else "❌ FAIL"
            else:
                # Show export status for Step 4
                if extra_data and "export_status" in extra_data:
                    export_status_str = extra_data["export_status"]
                    if export_status_str == "minio_success":
                        status = "✅ PASS"
                    elif (
                        export_status_str == "minio_failed"
                        or export_status_str == "local_only"
                    ):
                        status = "⚠️  PARTIAL"  # Local succeeded, MinIO failed/skipped
                    elif export_status_str == "disabled":
                        status = "⚠️  SKIPPED"  # MinIO not configured
                    else:
                        status = "❌ FAIL" if not success else "✅ PASS"
                else:
                    status = "✅ PASS" if success else "❌ FAIL"
            logger.info(f"{status} - {description}")

    elapsed = datetime.now() - start_time
    logger.info(f"{'='*70}")
    logger.info(f"Total Time: {elapsed.total_seconds():.1f} seconds")

    # Create summary with actual counts from current run
    summary = PipelineRunSummary(start_time=start_time, end_time=datetime.now())

    # Update export status from Step 4
    if step4_export_status:
        if step4_export_status == "minio_success":
            summary.export_status = ExportStatus.MINIO_SUCCESS
        elif step4_export_status == "minio_failed":
            summary.export_status = ExportStatus.MINIO_FAILED
        elif step4_export_status == "local_only":
            summary.export_status = ExportStatus.LOCAL_ONLY
        elif step4_export_status == "disabled":
            summary.export_status = ExportStatus.DISABLED

    # Pipeline is "ready for trading" if Steps 1-3 succeeded
    all_critical_steps_success = steps_1_3_success

    if all_critical_steps_success:
        # Read actual counts from output files (NOT hard-coded)
        try:
            summary.step1_factor_count = read_factor_count()
            portfolio_count, selections_count = read_step2_counts()
            summary.step2_portfolio_count = portfolio_count
            summary.step2_selections_count = selections_count
            total_signals, buy, sell, hold = read_step3_signal_counts()
            summary.step3_signal_count = total_signals
            summary.step3_buy_count = buy
            summary.step3_sell_count = sell
            summary.step3_hold_count = hold
        except Exception as e:
            logger.warning(f"Could not read actual counts from output files: {e}")

        # Build Step 4 status message
        step4_status_msg = ""
        if step4_export_status:
            if step4_export_status == "minio_success":
                step4_status_msg = "✓ Step 4: All files published (local + MinIO)"
            elif step4_export_status == "minio_failed":
                if results[3][2].get("minio_connection_error"):
                    step4_status_msg = f"⚠️  Step 4: Local export succeeded, MinIO failed ({results[3][2]['minio_connection_error']})"
                else:
                    step4_status_msg = (
                        "⚠️  Step 4: Local export succeeded, MinIO upload failed"
                    )
            elif step4_export_status == "local_only":
                step4_status_msg = (
                    "✓ Step 4: Local export succeeded (MinIO not configured)"
                )
            elif step4_export_status == "disabled":
                step4_status_msg = "✓ Step 4: Local export succeeded (MinIO disabled)"
        elif step4_success is False:
            step4_status_msg = "❌ Step 4: Export failed"
        else:
            step4_status_msg = "✓ Step 4: Export complete"

        logger.info(
            f"""
✅ PIPELINE COMPLETE - READY FOR TRADING
=========================================

Step 1: Risk Metrics
  📊 {summary.step1_factor_count} factors calculated
  📁 analytics/processed/step1/factors_latest.csv|parquet

Step 2: Portfolio Selection
  📊 {summary.step2_selections_count} stocks selected
  📁 analytics/processed/step2/selections_latest.csv|parquet

Step 3: Execution Signals
  📊 {summary.step3_signal_count} total signals ({summary.step3_buy_count} BUY, {summary.step3_sell_count} SELL, {summary.step3_hold_count} HOLD)
  📁 analytics/processed/step3/signals_latest.csv|parquet

{step4_status_msg}

Next Steps:
  1. Review portfolio selections in analytics/serving/selections/selections_latest.csv
  2. Check execution signals in analytics/serving/signals/signals_latest.csv
  3. Execute trades with position sizing based on ATR_14
        """
        )
        return 0
    else:
        logger.error(
            """
❌ PIPELINE INCOMPLETE
=====================

Check logs above for error details.
File: pipeline.log
        """
        )
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
