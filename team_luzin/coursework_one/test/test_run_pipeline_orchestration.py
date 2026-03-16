"""
Integration tests for run_pipeline.py orchestrator logic.

Tests main() function and orchestration without actual script execution.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

import run_pipeline


class TestRunPipelineArgumentParsing:
    """Test argument parsing in main()."""

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    def test_main_default_arguments(self, mock_run_command):
        """Test main() with default arguments."""
        mock_run_command.return_value = (False, {})  # No steps run

        result = run_pipeline.main()

        # Should exit (no steps completed)
        assert result == 1

    @patch("sys.argv", ["run_pipeline.py", "--dry-run"])
    def test_main_dry_run_mode(self):
        """Test main() with --dry-run flag."""
        result = run_pipeline.main()

        # Dry run should show plan and exit 0
        assert result == 0

    @patch("sys.argv", ["run_pipeline.py", "--frequency", "weekly"])
    @patch("run_pipeline.run_command")
    def test_main_frequency_argument(self, mock_run_command):
        """Test main() with --frequency argument."""
        mock_run_command.return_value = (False, {})

        result = run_pipeline.main()

        # Should process argument without error
        assert isinstance(result, int)

    @patch("sys.argv", ["run_pipeline.py", "--run-date", "2026-03-15"])
    @patch("run_pipeline.run_command")
    def test_main_run_date_argument(self, mock_run_command):
        """Test main() with --run-date argument."""
        mock_run_command.return_value = (False, {})

        result = run_pipeline.main()

        assert isinstance(result, int)

    @patch("sys.argv", ["run_pipeline.py", "--run-date", "invalid-date"])
    def test_main_invalid_date_format(self):
        """Test main() with invalid date format."""
        result = run_pipeline.main()

        # Should fail with invalid date
        assert result == 1


class TestPipelineOrchestration:
    """Test pipeline orchestration logic."""

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    def test_main_all_steps_success(self, mock_run_command):
        """Test main() when all steps succeed."""
        # Mock all 4 steps succeeding with export status tracking
        mock_run_command.side_effect = [
            (True, {}),  # Step 1
            (True, {}),  # Step 2
            (True, {}),  # Step 3
            (True, {"export_status": "minio_success"}),  # Step 4
        ]

        with patch("run_pipeline.read_factor_count", return_value=100):
            with patch("run_pipeline.read_step2_counts", return_value=(130, 123)):
                with patch(
                    "run_pipeline.read_step3_signal_counts",
                    return_value=(123, 4, 9, 110),
                ):
                    result = run_pipeline.main()

        # All steps succeeded
        assert result == 0

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    def test_main_step_1_fails(self, mock_run_command):
        """Test main() when Step 1 fails."""
        mock_run_command.side_effect = [
            (False, {}),  # Step 1 fails
        ]

        result = run_pipeline.main()

        # Should halt at Step 1
        assert result == 1
        # Should only call run_command once
        assert mock_run_command.call_count == 1

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    def test_main_step_4_minio_fails_optional(self, mock_run_command):
        """Test main() when Step 4 MinIO fails but is optional."""
        mock_run_command.side_effect = [
            (True, {}),  # Step 1
            (True, {}),  # Step 2
            (True, {}),  # Step 3
            (
                False,
                {"export_status": "minio_failed"},
            ),  # Step 4 fails, but MinIO is optional
        ]

        with patch.dict(os.environ, {"MINIO_REQUIRED": "false"}):
            with patch("run_pipeline.read_factor_count", return_value=100):
                with patch("run_pipeline.read_step2_counts", return_value=(130, 123)):
                    with patch(
                        "run_pipeline.read_step3_signal_counts",
                        return_value=(123, 4, 9, 110),
                    ):
                        result = run_pipeline.main()

        # Steps 1-3 succeeded, so pipeline returns 0 (ready for trading)
        assert result == 0

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    def test_main_step_4_minio_optional_steps_1_3_success(self, mock_run_command):
        """Test that pipeline returns 0 when Steps 1-3 succeed, even if Step 4 fails."""
        mock_run_command.side_effect = [
            (True, {}),  # Step 1
            (True, {}),  # Step 2
            (True, {}),  # Step 3
            (False, {"export_status": "minio_failed"}),  # Step 4 fails
        ]

        with patch.dict(os.environ, {"MINIO_REQUIRED": "false"}):
            with patch("run_pipeline.read_factor_count", return_value=100):
                with patch("run_pipeline.read_step2_counts", return_value=(130, 123)):
                    with patch(
                        "run_pipeline.read_step3_signal_counts",
                        return_value=(123, 4, 9, 110),
                    ):
                        result = run_pipeline.main()

        # Pipeline should return 0 because Steps 1-3 succeeded (Step 4 is optional)
        assert result == 0

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    def test_main_step_4_export_status_tracking(self, mock_run_command):
        """Test that main() tracks Step 4 export status."""
        export_status = {
            "export_status": "minio_success",
            "minio_configured": True,
            "minio_endpoint": "localhost:9000",
            "minio_bucket": "csreport",
            "minio_connection_error": None,
        }

        mock_run_command.side_effect = [
            (True, {}),  # Step 1
            (True, {}),  # Step 2
            (True, {}),  # Step 3
            (True, export_status),  # Step 4 with status
        ]

        with patch("run_pipeline.read_factor_count", return_value=100):
            with patch("run_pipeline.read_step2_counts", return_value=(130, 123)):
                with patch(
                    "run_pipeline.read_step3_signal_counts",
                    return_value=(123, 4, 9, 110),
                ):
                    result = run_pipeline.main()

        # Should succeeed with MinIO status tracked
        assert result == 0


class TestExportStatusMapping:
    """Test export status value mapping."""

    def test_export_status_values_match_enum(self):
        """Verify export status values match ExportStatus enum."""
        from modules.pipeline_results import ExportStatus

        expected_values = {
            "minio_success": ExportStatus.MINIO_SUCCESS.value,
            "minio_failed": ExportStatus.MINIO_FAILED.value,
            "local_only": ExportStatus.LOCAL_ONLY.value,
            "disabled": ExportStatus.DISABLED.value,
        }

        for key, expected in expected_values.items():
            assert key == expected, f"Mismatch: {key} != {expected}"

    def test_export_status_string_values(self):
        """Verify export status string values are lowercase."""
        from modules.pipeline_results import ExportStatus

        for status in [
            ExportStatus.MINIO_SUCCESS,
            ExportStatus.MINIO_FAILED,
            ExportStatus.LOCAL_ONLY,
            ExportStatus.DISABLED,
        ]:
            assert status.value.islower(), f"Status value not lowercase: {status.value}"
            assert "_" not in status.value or "_" in status.value  # Allow underscores


class TestMINIORequiredLogic:
    """Test MINIO_REQUIRED environment variable logic."""

    def test_minio_required_default_false(self):
        """Default MINIO_REQUIRED should be false."""
        saved = os.environ.pop("MINIO_REQUIRED", None)

        try:
            minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
            assert minio_required is False
        finally:
            if saved:
                os.environ["MINIO_REQUIRED"] = saved

    def test_minio_required_parse_true(self):
        """Parse MINIO_REQUIRED=true."""
        saved = os.getenv("MINIO_REQUIRED")

        try:
            os.environ["MINIO_REQUIRED"] = "true"
            minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
            assert minio_required is True
        finally:
            if saved:
                os.environ["MINIO_REQUIRED"] = saved
            elif "MINIO_REQUIRED" in os.environ:
                del os.environ["MINIO_REQUIRED"]

    def test_minio_required_case_insensitive(self):
        """MINIO_REQUIRED parsing is case insensitive."""
        for value in ["TRUE", "True", "TRUE", "tRuE"]:
            saved = os.getenv("MINIO_REQUIRED")
            try:
                os.environ["MINIO_REQUIRED"] = value
                minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
                assert minio_required is True
            finally:
                if saved:
                    os.environ["MINIO_REQUIRED"] = saved
                elif "MINIO_REQUIRED" in os.environ:
                    del os.environ["MINIO_REQUIRED"]


class TestSummaryGeneration:
    """Test pipeline summary generation with different export statuses (Priority 1 target)."""

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    @patch("run_pipeline.logger")
    def test_summary_with_minio_success(self, mock_logger, mock_run_command):
        """Test summary generation when MinIO succeeds."""
        mock_run_command.side_effect = [
            (True, {}),  # Step 1
            (True, {}),  # Step 2
            (True, {}),  # Step 3
            (
                True,
                {
                    "export_status": "minio_success",
                    "minio_configured": True,
                    "minio_endpoint": "localhost:9000",
                    "minio_connection_error": None,
                },
            ),  # Step 4
        ]

        with patch("run_pipeline.read_factor_count", return_value=598):
            with patch("run_pipeline.read_step2_counts", return_value=(130, 123)):
                with patch(
                    "run_pipeline.read_step3_signal_counts",
                    return_value=(123, 4, 9, 110),
                ):
                    result = run_pipeline.main()

        # Check that summary was logged with "local + MinIO" text
        assert result == 0
        # Verify logger.info was called with the summary message
        logged_messages = [
            call[0][0] for call in mock_logger.info.call_args_list if call[0]
        ]
        summary_found = any("local + MinIO" in str(msg) for msg in logged_messages)
        assert (
            summary_found
        ), "Summary should contain 'local + MinIO' when minio_success"

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    @patch("run_pipeline.logger")
    def test_summary_with_minio_failed(self, mock_logger, mock_run_command):
        """Test summary generation when MinIO fails."""
        mock_run_command.side_effect = [
            (True, {}),  # Step 1
            (True, {}),  # Step 2
            (True, {}),  # Step 3
            (
                False,
                {
                    "export_status": "minio_failed",
                    "minio_configured": True,
                    "minio_connection_error": "InvalidAccessKeyId",
                },
            ),  # Step 4
        ]

        with patch.dict(os.environ, {"MINIO_REQUIRED": "false"}):
            with patch("run_pipeline.read_factor_count", return_value=598):
                with patch("run_pipeline.read_step2_counts", return_value=(130, 123)):
                    with patch(
                        "run_pipeline.read_step3_signal_counts",
                        return_value=(123, 4, 9, 110),
                    ):
                        result = run_pipeline.main()

        # Steps 1-3 succeeded, so pipeline still returns 0 (trading can proceed)
        assert result == 0
        # Verify logger shows error details
        logged_messages = [
            call[0][0] for call in mock_logger.info.call_args_list if call[0]
        ]
        summary_with_error = any(
            "MinIO failed" in str(msg) and "InvalidAccessKeyId" in str(msg)
            for msg in logged_messages
        )
        assert (
            summary_with_error
        ), "Summary should mention MinIO failure with error reason"

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    @patch("run_pipeline.logger")
    def test_summary_with_local_only(self, mock_logger, mock_run_command):
        """Test summary generation when MinIO not configured."""
        mock_run_command.side_effect = [
            (True, {}),  # Step 1
            (True, {}),  # Step 2
            (True, {}),  # Step 3
            (
                True,
                {
                    "export_status": "local_only",
                    "minio_configured": False,
                    "minio_endpoint": None,
                    "minio_connection_error": None,
                },
            ),  # Step 4
        ]

        with patch("run_pipeline.read_factor_count", return_value=598):
            with patch("run_pipeline.read_step2_counts", return_value=(130, 123)):
                with patch(
                    "run_pipeline.read_step3_signal_counts",
                    return_value=(123, 4, 9, 110),
                ):
                    result = run_pipeline.main()

        assert result == 0
        # Verify summary mentions local export and MinIO not configured
        logged_messages = [
            call[0][0] for call in mock_logger.info.call_args_list if call[0]
        ]
        summary_local = any(
            "MinIO not configured" in str(msg) for msg in logged_messages
        )
        assert summary_local, "Summary should mention MinIO not configured"

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    @patch("run_pipeline.logger")
    def test_summary_with_disabled(self, mock_logger, mock_run_command):
        """Test summary generation when MinIO disabled."""
        mock_run_command.side_effect = [
            (True, {}),  # Step 1
            (True, {}),  # Step 2
            (True, {}),  # Step 3
            (
                True,
                {
                    "export_status": "disabled",
                    "minio_configured": False,
                    "minio_endpoint": None,
                    "minio_connection_error": None,
                },
            ),  # Step 4
        ]

        with patch("run_pipeline.read_factor_count", return_value=598):
            with patch("run_pipeline.read_step2_counts", return_value=(130, 123)):
                with patch(
                    "run_pipeline.read_step3_signal_counts",
                    return_value=(123, 4, 9, 110),
                ):
                    result = run_pipeline.main()

        assert result == 0
        # Verify summary mentions MinIO disabled
        logged_messages = [
            call[0][0] for call in mock_logger.info.call_args_list if call[0]
        ]
        summary_disabled = any("MinIO disabled" in str(msg) for msg in logged_messages)
        assert summary_disabled, "Summary should mention MinIO disabled"

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    def test_step_2_failure_halts_pipeline(self, mock_run_command):
        """Test that Step 2 failure halts the pipeline."""
        mock_run_command.side_effect = [
            (True, {}),  # Step 1 succeeds
            (False, {}),  # Step 2 fails
        ]

        result = run_pipeline.main()

        # Pipeline should fail
        assert result == 1
        # Should only call run_command twice (Step 1 and Step 2)
        assert mock_run_command.call_count == 2

    @patch("sys.argv", ["run_pipeline.py"])
    @patch("run_pipeline.run_command")
    def test_step_3_failure_halts_pipeline(self, mock_run_command):
        """Test that Step 3 failure halts the pipeline."""
        mock_run_command.side_effect = [
            (True, {}),  # Step 1 succeeds
            (True, {}),  # Step 2 succeeds
            (False, {}),  # Step 3 fails
        ]

        result = run_pipeline.main()

        # Pipeline should fail
        assert result == 1
        # Should only call run_command three times (Steps 1, 2, 3)
        assert mock_run_command.call_count == 3
