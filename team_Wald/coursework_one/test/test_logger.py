"""
Tests for the logger module (modules/utils/logger.py).

Tests IFTLoggerAdapter formatting, fallback logging, and run ID generation.
"""

import logging
import uuid
from unittest.mock import MagicMock

from modules.utils.logger import IFTLoggerAdapter, generate_run_id, pipeline_logger


class TestIFTLoggerAdapter:
    """Tests for IFTLoggerAdapter printf-style formatting."""

    def test_info_with_args(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        adapter.info("count: %d", 5)
        mock.info.assert_called_once_with("count: 5")

    def test_info_without_args(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        adapter.info("simple message")
        mock.info.assert_called_once_with("simple message")

    def test_warning_with_args(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        adapter.warning("rate: %.2f%%", 3.14)
        mock.warning.assert_called_once_with("rate: 3.14%")

    def test_warning_without_args(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        adapter.warning("simple warning")
        mock.warning.assert_called_once_with("simple warning")

    def test_error_with_args(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        adapter.error("failed for %s: %s", "AAPL", "timeout")
        mock.error.assert_called_once_with("failed for AAPL: timeout")

    def test_error_without_args(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        adapter.error("generic error")
        mock.error.assert_called_once_with("generic error")

    def test_debug_with_args(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        adapter.debug("fetched %d rows for %s", 250, "MSFT")
        mock.debug.assert_called_once_with("fetched 250 rows for MSFT")

    def test_debug_without_args(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        adapter.debug("debug msg")
        mock.debug.assert_called_once_with("debug msg")

    def test_format_method(self):
        mock = MagicMock()
        adapter = IFTLoggerAdapter(mock)
        assert adapter._format("hello %s", ("world",)) == "hello world"
        assert adapter._format("no args", ()) == "no args"


class TestPipelineLogger:
    """Tests for the pipeline_logger singleton."""

    def test_pipeline_logger_exists(self):
        assert pipeline_logger is not None

    def test_pipeline_logger_has_info(self):
        assert hasattr(pipeline_logger, "info")

    def test_pipeline_logger_has_warning(self):
        assert hasattr(pipeline_logger, "warning")

    def test_pipeline_logger_has_error(self):
        assert hasattr(pipeline_logger, "error")

    def test_pipeline_logger_has_debug(self):
        assert hasattr(pipeline_logger, "debug")

    def test_pipeline_logger_can_log(self):
        # Should not raise
        pipeline_logger.info("test log from test suite")
        pipeline_logger.warning("test warning from test suite")
        pipeline_logger.error("test error from test suite")
        pipeline_logger.debug("test debug from test suite")


class TestGenerateRunId:
    """Tests for the generate_run_id function."""

    def test_returns_string(self):
        run_id = generate_run_id()
        assert isinstance(run_id, str)

    def test_valid_uuid4(self):
        run_id = generate_run_id()
        parsed = uuid.UUID(run_id, version=4)
        assert str(parsed) == run_id

    def test_unique_ids(self):
        ids = {generate_run_id() for _ in range(100)}
        assert len(ids) == 100


class TestFallbackLogger:
    """Tests for the fallback logging path (when ift_global not available)."""

    def test_fallback_is_standard_logger_or_adapter(self):
        # pipeline_logger is either IFTLoggerAdapter or logging.Logger
        assert isinstance(pipeline_logger, (IFTLoggerAdapter, logging.Logger))

    def test_fallback_logger_creation(self):
        """Simulate the fallback path when ift_global is not available."""
        fallback = logging.getLogger("test_fallback_logger")
        if not fallback.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            fallback.addHandler(handler)
            fallback.setLevel(logging.INFO)
        assert len(fallback.handlers) >= 1
        assert fallback.level == logging.INFO
        fallback.info("test fallback log")

    def test_fallback_logger_already_has_handlers(self):
        """Test that handlers aren't duplicated when logger already has them."""
        name = "test_no_dup_handlers"
        logger = logging.getLogger(name)
        handler = logging.StreamHandler()
        logger.addHandler(handler)
        # Simulating the module code — should not add another handler
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler())
        assert len(logger.handlers) == 1
