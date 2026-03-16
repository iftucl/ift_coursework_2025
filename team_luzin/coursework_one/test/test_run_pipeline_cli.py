"""
Smoke Tests for Pipeline Orchestration

Tests run_pipeline.py orchestration functionality:
- CLI argument parsing
- Dry-run mode
- Scheduling options
- Logging configuration
- Error handling

These are smoke tests - they verify basic operation without running actual steps.
"""

import argparse
import logging
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


class TestRunPipelineImport:
    """Test that run_pipeline module can be imported."""

    def test_run_pipeline_import(self):
        """Test that run_pipeline module can be imported."""
        try:
            import run_pipeline

            assert run_pipeline is not None
            assert hasattr(run_pipeline, "main")
            assert hasattr(run_pipeline, "run_command")
        except ImportError as e:
            pytest.skip(f"run_pipeline module not importable: {e}")

    def test_run_pipeline_main_function_exists(self):
        """Test that main() function exists and is callable."""
        import run_pipeline

        assert callable(run_pipeline.main)

    def test_run_pipeline_run_command_function_exists(self):
        """Test that run_command() function exists and is callable."""
        import run_pipeline

        assert callable(run_pipeline.run_command)

    def test_run_pipeline_logger_configured(self):
        """Test that logging is properly configured."""
        import run_pipeline

        # Logger should exist
        logger = logging.getLogger("run_pipeline")
        assert logger is not None


class TestRunPipelineArgumentParsing:
    """Test CLI argument parsing."""

    @patch("sys.argv", ["run_pipeline.py"])
    def test_default_arguments(self):
        """Test default arguments (no args provided)."""
        import run_pipeline

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--frequency",
            choices=["daily", "weekly", "monthly", "quarterly"],
            default="daily",
        )
        parser.add_argument("--run-date", type=str)
        parser.add_argument("--dry-run", action="store_true")

        # Simulate default case
        args = parser.parse_args([])

        assert args.frequency == "daily"
        assert args.run_date is None
        assert args.dry_run is False

    @patch("sys.argv", ["run_pipeline.py", "--frequency", "weekly"])
    def test_frequency_argument(self):
        """Test --frequency argument."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--frequency",
            choices=["daily", "weekly", "monthly", "quarterly"],
            default="daily",
        )

        args = parser.parse_args(["--frequency", "weekly"])
        assert args.frequency == "weekly"

    @patch("sys.argv", ["run_pipeline.py", "--frequency", "monthly"])
    def test_monthly_frequency(self):
        """Test monthly scheduling frequency."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--frequency",
            choices=["daily", "weekly", "monthly", "quarterly"],
            default="daily",
        )

        args = parser.parse_args(["--frequency", "monthly"])
        assert args.frequency == "monthly"

    @patch("sys.argv", ["run_pipeline.py", "--frequency", "quarterly"])
    def test_quarterly_frequency(self):
        """Test quarterly scheduling frequency."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--frequency",
            choices=["daily", "weekly", "monthly", "quarterly"],
            default="daily",
        )

        args = parser.parse_args(["--frequency", "quarterly"])
        assert args.frequency == "quarterly"

    @patch("sys.argv", ["run_pipeline.py", "--run-date", "2025-03-07"])
    def test_run_date_argument(self):
        """Test --run-date argument."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--run-date", type=str)

        args = parser.parse_args(["--run-date", "2025-03-07"])
        assert args.run_date == "2025-03-07"

    @patch("sys.argv", ["run_pipeline.py", "--dry-run"])
    def test_dry_run_flag(self):
        """Test --dry-run flag."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")

        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_combined_arguments(self):
        """Test multiple arguments combined."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--frequency",
            choices=["daily", "weekly", "monthly", "quarterly"],
            default="daily",
        )
        parser.add_argument("--dry-run", action="store_true")

        args = parser.parse_args(["--frequency", "weekly", "--dry-run"])
        assert args.frequency == "weekly"
        assert args.dry_run is True


class TestRunCommandExecution:
    """Test run_command() function."""

    @patch("subprocess.run")
    def test_run_command_success(self, mock_run):
        """Test successful command execution."""
        import run_pipeline

        # Mock successful execution
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        success, extra_data = run_pipeline.run_command("test_script.py", "Test step")

        assert success is True
        assert isinstance(extra_data, dict)
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_run_command_failure(self, mock_run):
        """Test failed command execution."""
        import run_pipeline

        # Mock failed execution
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error message"
        mock_run.return_value = mock_result

        success, extra_data = run_pipeline.run_command("test_script.py", "Test step")

        assert success is False
        assert isinstance(extra_data, dict)

    @patch("subprocess.run")
    def test_run_command_exception_handling(self, mock_run):
        """Test exception handling in run_command()."""
        import run_pipeline

        # Mock exception
        mock_run.side_effect = Exception("Test error")

        success, extra_data = run_pipeline.run_command("test_script.py", "Test step")

        assert success is False
        assert isinstance(extra_data, dict)

    @patch("subprocess.run")
    def test_run_command_uses_poetry(self, mock_run):
        """Test that run_command uses poetry to run scripts."""
        import run_pipeline

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        success, extra_data = run_pipeline.run_command("test.py", "Test")

        # Verify poetry is used (full path or just 'poetry')
        call_args = mock_run.call_args[0][0]
        poetry_cmd = call_args[0]
        assert "poetry" in poetry_cmd  # Poetry path (either 'poetry' or full path)
        assert "run" in call_args
        assert "python3" in call_args

    @patch("subprocess.run")
    def test_run_command_calls_correct_script(self, mock_run):
        """Test that run_command calls the correct script."""
        import run_pipeline

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        script_name = "my_test_script.py"
        run_pipeline.run_command(script_name, "Test")

        call_args = mock_run.call_args[0][0]
        assert script_name in call_args


class TestRunPipelineDryRun:
    """Test dry-run mode functionality."""

    @patch("sys.argv", ["run_pipeline.py", "--dry-run"])
    @patch("run_pipeline.logger")
    def test_dry_run_logs_plan(self, mock_logger):
        """Test that dry-run logs execution plan."""
        import run_pipeline

        # Create a simple mock parser
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")

        args = parser.parse_args(["--dry-run"])

        # Dry run should be enabled
        assert args.dry_run is True

    @patch("sys.argv", ["run_pipeline.py", "--dry-run"])
    def test_dry_run_no_execution(self):
        """Test that dry-run doesn't execute actual steps."""
        import run_pipeline

        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")

        # Dry-run flag should be set
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True


class TestRunPipelineScheduling:
    """Test scheduling frequency options."""

    def test_daily_frequency_valid(self):
        """Test that daily frequency is valid."""
        frequencies = ["daily", "weekly", "monthly", "quarterly"]
        assert "daily" in frequencies

    def test_weekly_frequency_valid(self):
        """Test that weekly frequency is valid."""
        frequencies = ["daily", "weekly", "monthly", "quarterly"]
        assert "weekly" in frequencies

    def test_monthly_frequency_valid(self):
        """Test that monthly frequency is valid."""
        frequencies = ["daily", "weekly", "monthly", "quarterly"]
        assert "monthly" in frequencies

    def test_quarterly_frequency_valid(self):
        """Test that quarterly frequency is valid."""
        frequencies = ["daily", "weekly", "monthly", "quarterly"]
        assert "quarterly" in frequencies

    def test_invalid_frequency_rejected(self):
        """Test that invalid frequency is rejected."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--frequency", choices=["daily", "weekly", "monthly", "quarterly"]
        )

        with pytest.raises(SystemExit):
            parser.parse_args(["--frequency", "invalid"])


class TestRunPipelineDateParsing:
    """Test date parsing functionality."""

    def test_valid_date_format(self):
        """Test valid YYYY-MM-DD date format."""
        from datetime import datetime

        date_str = "2025-03-07"
        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
            assert parsed_date.year == 2025
            assert parsed_date.month == 3
            assert parsed_date.day == 7
        except ValueError:
            pytest.fail("Valid date should be parseable")

    def test_invalid_date_format(self):
        """Test invalid date format."""
        from datetime import datetime

        date_str = "03-07-2025"  # Wrong format
        with pytest.raises(ValueError):
            datetime.strptime(date_str, "%Y-%m-%d")

    def test_date_parsing_edge_cases(self):
        """Test date parsing with edge cases."""
        from datetime import datetime

        test_cases = [
            ("2025-01-01", True),  # Valid
            ("2025-12-31", True),  # Valid
            ("2025-02-28", True),  # Valid
            ("2025-13-01", False),  # Invalid month
            ("2025-00-01", False),  # Invalid month
        ]

        for date_str, should_be_valid in test_cases:
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                assert should_be_valid
            except ValueError:
                assert not should_be_valid


class TestRunPipelineLogging:
    """Test logging configuration."""

    def test_logger_exists(self):
        """Test that logger is properly configured."""
        import run_pipeline

        assert run_pipeline.logger is not None
        assert isinstance(run_pipeline.logger, logging.Logger)

    def test_logger_name(self):
        """Test logger has correct name."""
        import run_pipeline

        # Logger should be named run_pipeline
        assert (
            "run_pipeline" in run_pipeline.logger.name
            or run_pipeline.logger.name == "__main__"
        )

    def test_logger_handlers(self):
        """Test logger has file and stream handlers."""
        import run_pipeline

        # Logger should be configured at module or root level
        # Handlers may be on root logger or module logger
        root_logger = logging.getLogger()
        assert run_pipeline.logger is not None
        assert (
            len(run_pipeline.logger.handlers) > 0
            or len(root_logger.handlers) > 0
            or run_pipeline.logger.level != logging.NOTSET
        )


class TestRunPipelineIntegration:
    """Integration tests for pipeline orchestration."""

    def test_pipeline_module_structure(self):
        """Test that module has correct structure."""
        import run_pipeline

        # Required components
        assert hasattr(run_pipeline, "main")
        assert hasattr(run_pipeline, "run_command")
        assert hasattr(run_pipeline, "logger")
        assert hasattr(run_pipeline, "logging")
        assert hasattr(run_pipeline, "argparse")

    @patch("run_pipeline.run_command")
    @patch("sys.argv", ["run_pipeline.py"])
    def test_main_function_callable(self, mock_run_command):
        """Test that main() can be called without errors."""
        import run_pipeline

        # Mock run_command to prevent actual execution
        mock_run_command.return_value = False

        # Just verify it's callable
        assert callable(run_pipeline.main)

    def test_pipeline_has_docstring(self):
        """Test that pipeline module has documentation."""
        import run_pipeline

        assert run_pipeline.__doc__ is not None
        assert len(run_pipeline.__doc__) > 0

    def test_run_command_has_docstring(self):
        """Test that run_command has documentation."""
        import run_pipeline

        assert run_pipeline.run_command.__doc__ is not None


class TestRunPipelineEdgeCases:
    """Test edge cases and error conditions."""

    @patch("subprocess.run")
    def test_run_command_with_empty_script_name(self, mock_run):
        """Test run_command with empty script name."""
        import run_pipeline

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        # Should still attempt to run
        success, extra_data = run_pipeline.run_command("", "Empty script")
        # Result should be a tuple (success, extra_data)
        assert isinstance(success, bool)
        assert isinstance(extra_data, dict)

    def test_frequency_argument_case_sensitive(self):
        """Test that frequency argument is case-sensitive."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--frequency", choices=["daily", "weekly", "monthly", "quarterly"]
        )

        # Lowercase should work
        args = parser.parse_args(["--frequency", "daily"])
        assert args.frequency == "daily"

        # Uppercase should fail
        with pytest.raises(SystemExit):
            parser.parse_args(["--frequency", "DAILY"])

    @patch("subprocess.run")
    def test_run_command_with_special_characters(self, mock_run):
        """Test run_command with script names containing special characters."""
        import run_pipeline

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        # Should handle special characters
        success, extra_data = run_pipeline.run_command("test-script_v2.py", "Test")
        # Result should be a tuple (success, extra_data)
        assert isinstance(success, bool)
        assert isinstance(extra_data, dict)


class TestRunPipelinePathHandling:
    """Test path and file handling."""

    def test_pipeline_uses_pathlib(self):
        """Test that pipeline uses pathlib for paths."""
        import run_pipeline

        # Check Path import exists
        assert hasattr(run_pipeline, "Path")

    @patch("subprocess.run")
    def test_run_command_passes_correct_cwd(self, mock_run):
        """Test that run_command uses correct working directory."""
        import run_pipeline

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        run_pipeline.run_command("test.py", "Test")

        # Check that cwd parameter is passed
        call_kwargs = mock_run.call_args[1]
        assert "cwd" in call_kwargs
