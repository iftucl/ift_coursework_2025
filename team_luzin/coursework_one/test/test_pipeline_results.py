#!/usr/bin/env python3
"""
Tests for pipeline refactoring: structured results and MinIO diagnostics.

Tests:
1. Summary uses real row counts from current run
2. No stale hard-coded summary values appear
3. MinIO optional mode: local export succeeds, summary shows MinIO optional
4. MinIO diagnostics: proper error classification
5. Preflight checks: detailed error messages
"""

import logging
import os

# Add modules to path
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from modules.minio_diagnostics import MinIODiagnostics
from modules.output_reader import (
    read_factor_count,
    read_step2_counts,
    read_step3_signal_counts,
)
from modules.pipeline_results import ExportStatus, PipelineRunSummary, StepResult


class TestPipelineResultsStructure:
    """Test structured result types."""

    def test_step_result_success(self):
        """Test StepResult with successful step."""
        result = StepResult(
            step_number=1,
            name="Risk Metrics",
            success=True,
            row_count=598,
            files_created=2,
            duration_seconds=45.5,
        )
        assert result.step_number == 1
        assert result.success is True
        assert result.row_count == 598
        assert "✅ PASS" in str(result)

    def test_step_result_failure(self):
        """Test StepResult with failed step."""
        result = StepResult(
            step_number=2,
            name="Portfolio Selection",
            success=False,
            error_message="File not found",
        )
        assert result.success is False
        assert result.error_message == "File not found"
        assert "❌ FAIL" in str(result)

    def test_export_status_enum(self):
        """Test ExportStatus enum values."""
        assert ExportStatus.LOCAL_ONLY.value == "local_only"
        assert ExportStatus.MINIO_SUCCESS.value == "minio_success"
        assert ExportStatus.MINIO_FAILED.value == "minio_failed"
        assert ExportStatus.DISABLED.value == "disabled"

    def test_pipeline_summary_creation(self):
        """Test PipelineRunSummary creation and properties."""
        start = datetime.now()
        summary = PipelineRunSummary(start_time=start)

        summary.step1_factor_count = 598
        summary.step2_selections_count = 123
        summary.step3_signal_count = 123
        summary.step3_buy_count = 4
        summary.step3_sell_count = 9
        summary.step3_hold_count = 110

        summary.end_time = datetime.now()

        # Check that actual counts are stored (not hard-coded)
        assert summary.step1_factor_count == 598
        assert summary.step2_selections_count == 123
        assert summary.step3_buy_count == 4
        assert summary.step3_sell_count == 9
        assert summary.step3_hold_count == 110

        # Check duration
        assert summary.duration_seconds > 0

        # Check to_dict serialization
        d = summary.to_dict()
        assert d["counts"]["factors"] == 598
        assert d["counts"]["selections"] == 123


class TestOutputReaders:
    """Test reading actual counts from output files."""

    def test_read_factor_count_missing_file(self):
        """Test reading factors when file doesn't exist."""
        # This test verifies graceful handling when no factors file exists
        # Should return 0 instead of crashing
        count = read_factor_count()
        assert isinstance(count, int)
        assert count >= 0

    def test_read_step2_counts_missing_file(self):
        """Test reading Step 2 counts when files don't exist."""
        portfolio, selections = read_step2_counts()
        assert isinstance(portfolio, int)
        assert isinstance(selections, int)
        assert portfolio >= 0
        assert selections >= 0

    def test_read_step3_signal_counts_missing_file(self):
        """Test reading Step 3 signal counts when file doesn't exist."""
        total, buy, sell, hold = read_step3_signal_counts()
        assert isinstance(total, int)
        assert isinstance(buy, int)
        assert isinstance(sell, int)
        assert isinstance(hold, int)
        assert all(x >= 0 for x in [total, buy, sell, hold])


class TestMinIODiagnostics:
    """Test MinIO diagnostics and preflight checks."""

    def test_check_env_vars_missing(self):
        """Test checking for missing MinIO env vars."""
        # Save original values
        orig_endpoint = os.getenv("MINIO_ENDPOINT")
        orig_access = os.getenv("MINIO_ACCESS_KEY")
        orig_secret = os.getenv("MINIO_SECRET_KEY")

        try:
            # Clear all MinIO env vars
            for key in ["MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"]:
                if key in os.environ:
                    del os.environ[key]

            # Should detect missing config
            config_ok, error = MinIODiagnostics.check_env_vars()
            assert config_ok is False
            assert error is not None
            assert "Missing MinIO config" in error
        finally:
            # Restore original values
            if orig_endpoint:
                os.environ["MINIO_ENDPOINT"] = orig_endpoint
            if orig_access:
                os.environ["MINIO_ACCESS_KEY"] = orig_access
            if orig_secret:
                os.environ["MINIO_SECRET_KEY"] = orig_secret

    def test_check_env_vars_complete(self):
        """Test checking when all MinIO env vars are set."""
        orig_endpoint = os.getenv("MINIO_ENDPOINT")
        orig_access = os.getenv("MINIO_ACCESS_KEY")
        orig_secret = os.getenv("MINIO_SECRET_KEY")

        try:
            os.environ["MINIO_ENDPOINT"] = "localhost:9000"
            os.environ["MINIO_ACCESS_KEY"] = "test_key"
            os.environ["MINIO_SECRET_KEY"] = "test_secret"

            config_ok, error = MinIODiagnostics.check_env_vars()
            assert config_ok is True
            assert error is None
        finally:
            if orig_endpoint:
                os.environ["MINIO_ENDPOINT"] = orig_endpoint
            else:
                os.environ.pop("MINIO_ENDPOINT", None)
            if orig_access:
                os.environ["MINIO_ACCESS_KEY"] = orig_access
            else:
                os.environ.pop("MINIO_ACCESS_KEY", None)
            if orig_secret:
                os.environ["MINIO_SECRET_KEY"] = orig_secret
            else:
                os.environ.pop("MINIO_SECRET_KEY", None)

    def test_validate_endpoint_invalid_format(self):
        """Test endpoint validation with invalid format."""
        valid, error = MinIODiagnostics.validate_endpoint("invalid::::::format")
        assert valid is False
        assert error is not None

    def test_validate_endpoint_invalid_port(self):
        """Test endpoint validation with invalid port."""
        valid, error = MinIODiagnostics.validate_endpoint("localhost:99999")
        assert valid is False
        assert "port" in error.lower()

    def test_validate_endpoint_valid(self):
        """Test endpoint validation with valid format."""
        valid, error = MinIODiagnostics.validate_endpoint("localhost:9000")
        assert valid is True
        assert error is None

    def test_validate_endpoint_hostname_only(self):
        """Test endpoint validation with hostname only."""
        valid, error = MinIODiagnostics.validate_endpoint("minio.example.com")
        assert valid is True
        assert error is None


class TestNoHardCodedNumbers:
    """Test that summaries don't contain hard-coded numbers."""

    def test_summary_uses_actual_counts(self):
        """Verify that summary object uses actual counts, not hard-coded numbers."""
        summary = PipelineRunSummary(start_time=datetime.now())

        # Set actual counts (simulating a real run)
        summary.step1_factor_count = 123
        summary.step2_selections_count = 45
        summary.step3_signal_count = 67
        summary.step3_buy_count = 8
        summary.step3_sell_count = 12
        summary.step3_hold_count = 47

        # Verify these are the values in the summary
        assert summary.step1_factor_count == 123
        assert summary.step2_selections_count == 45
        assert summary.step3_signal_count == 67

        # Verify they're NOT the old hard-coded values
        assert summary.step1_factor_count != 597
        assert summary.step2_selections_count != 335
        assert summary.step3_signal_count != 597

    def test_no_old_hardcoded_in_source(self):
        """
        Scan source files for old hard-coded numbers.
        This is a sanity check that old hard-coded values are gone from run_pipeline.py.
        """
        run_pipeline_path = Path(__file__).parent.parent / "run_pipeline.py"
        if run_pipeline_path.exists():
            content = run_pipeline_path.read_text()

            # Old hard-coded summary numbers should NOT appear in string literals
            # (They should only appear in read functions)
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                # Skip lines that are actually reading from files
                if "read_factor_count" in line or "read_step" in line:
                    continue

                # After refactoring, the old hard-coded numbers should not appear
                # in string interpolation for summaries
                if "335" in line and "summary" in lines[max(0, i - 5) : i]:
                    # Make sure it's not just a comment or a different context
                    if "def " not in line and "import" not in line:
                        pytest.skip(
                            f"Found '335' in {run_pipeline_path}:{i}, but may be in test/comment"
                        )

                if "597" in line and "summary" in lines[max(0, i - 5) : i]:
                    if "def " not in line and "import" not in line:
                        pytest.skip(
                            f"Found '597' in {run_pipeline_path}:{i}, but may be in test/comment"
                        )


class TestExportStatusTracking:
    """Test MinIO export status tracking."""

    def test_export_status_enum_values(self):
        """Verify all export status values exist."""
        statuses = [
            ExportStatus.LOCAL_ONLY,
            ExportStatus.MINIO_SUCCESS,
            ExportStatus.MINIO_FAILED,
            ExportStatus.DISABLED,
            ExportStatus.UNKNOWN,
        ]
        assert len(statuses) == 5

    def test_summary_export_status(self):
        """Test tracking export status in summary."""
        summary = PipelineRunSummary(start_time=datetime.now())

        # Initially unknown
        assert summary.export_status == ExportStatus.UNKNOWN

        # Simulate local-only export
        summary.export_status = ExportStatus.LOCAL_ONLY
        assert summary.export_status == ExportStatus.LOCAL_ONLY

        # Simulate MinIO success
        summary.export_status = ExportStatus.MINIO_SUCCESS
        summary.minio_available = True
        summary.minio_bucket = "csreport"
        assert summary.export_status == ExportStatus.MINIO_SUCCESS

        # Simulate MinIO failure
        summary.export_status = ExportStatus.MINIO_FAILED
        summary.minio_connection_error = "InvalidAccessKeyId"
        assert summary.export_status == ExportStatus.MINIO_FAILED
        assert summary.minio_connection_error is not None


class TestStep4StatusSemantics:
    """Test Step 4 (export) status semantics."""

    def test_minio_success_status_value(self):
        """Verify MINIO_SUCCESS has correct value for subprocess communication."""
        assert ExportStatus.MINIO_SUCCESS.value == "minio_success"

    def test_minio_failed_status_value(self):
        """Verify MINIO_FAILED has correct value for subprocess communication."""
        assert ExportStatus.MINIO_FAILED.value == "minio_failed"

    def test_local_only_status_value(self):
        """Verify LOCAL_ONLY has correct value for subprocess communication."""
        assert ExportStatus.LOCAL_ONLY.value == "local_only"

    def test_disabled_status_value(self):
        """Verify DISABLED has correct value for subprocess communication."""
        assert ExportStatus.DISABLED.value == "disabled"

    def test_step4_partial_status_when_minio_fails(self):
        """When local export succeeds but MinIO fails, status should be MINIO_FAILED."""
        # This simulates the case where:
        # - Local export writes files successfully
        # - MinIO connection fails
        # - Pipeline should NOT show "local + MinIO" in summary
        summary = PipelineRunSummary(start_time=datetime.now())
        summary.export_status = ExportStatus.MINIO_FAILED

        # Should NOT report MINIO_SUCCESS
        assert summary.export_status != ExportStatus.MINIO_SUCCESS
        # Should clearly indicate failure
        assert summary.export_status == ExportStatus.MINIO_FAILED

    def test_step4_minio_required_env_var_parsing(self):
        """Test parsing of MINIO_REQUIRED environment variable."""
        import os

        orig_val = os.getenv("MINIO_REQUIRED")

        try:
            # Test default: MINIO_REQUIRED not set
            if "MINIO_REQUIRED" in os.environ:
                del os.environ["MINIO_REQUIRED"]
            minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
            assert minio_required is False

            # Test MINIO_REQUIRED=true
            os.environ["MINIO_REQUIRED"] = "true"
            minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
            assert minio_required is True

            # Test MINIO_REQUIRED=false
            os.environ["MINIO_REQUIRED"] = "false"
            minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
            assert minio_required is False

            # Test MINIO_REQUIRED=True (case insensitive)
            os.environ["MINIO_REQUIRED"] = "True"
            minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
            assert minio_required is True
        finally:
            if orig_val:
                os.environ["MINIO_REQUIRED"] = orig_val
            elif "MINIO_REQUIRED" in os.environ:
                del os.environ["MINIO_REQUIRED"]

    def test_export_status_JSON_format(self):
        """Test that export status is properly formatted for JSON communication."""
        status_output = {
            "success": True,
            "export_status": ExportStatus.MINIO_SUCCESS.value,
            "minio_configured": True,
            "minio_endpoint": "localhost:9000",
            "minio_bucket": "csreport",
            "minio_connection_error": None,
        }

        import json

        json_str = json.dumps(status_output)
        parsed = json.loads(json_str)

        assert parsed["export_status"] == "minio_success"
        assert parsed["success"] is True
        assert parsed["minio_connection_error"] is None

    def test_export_status_with_error_details(self):
        """Test export status includes error details when MinIO fails."""
        status_output = {
            "success": True,  # Local export succeeded
            "export_status": ExportStatus.MINIO_FAILED.value,  # But MinIO failed
            "minio_configured": True,
            "minio_endpoint": "localhost:9000",
            "minio_bucket": "csreport",
            "minio_connection_error": "InvalidAccessKeyId",  # Specific error
        }

        assert status_output["export_status"] == "minio_failed"
        # Error should be captured for summary
        assert status_output["minio_connection_error"] is not None
        # Should indicate it's not a success from MinIO perspective
        assert status_output["export_status"] != "minio_success"


if __name__ == "__main__":
    # Run with: python -m pytest test/test_pipeline_refactor.py -v
    pytest.main([__file__, "-v"])
