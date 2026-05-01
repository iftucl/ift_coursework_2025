"""
Tests for the pipeline progress display module (modules/utils/progress.py).

Tests StageRecord data class, PipelineProgressManager lifecycle, stage
management, parallel stages, and summary/banner output.
"""

import time
from unittest.mock import patch

import pytest

from modules.utils.progress import PipelineProgressManager, StageRecord


class TestStageRecord:
    """Tests for the StageRecord data class."""

    def test_default_values(self):
        sr = StageRecord(name="Test Stage")
        assert sr.name == "Test Stage"
        assert sr.total == 0
        assert sr.completed == 0
        assert sr.success == 0
        assert sr.empty == 0
        assert sr.errors == 0
        assert sr.end_time is None

    def test_elapsed_without_end(self):
        sr = StageRecord(name="Running", start_time=time.time() - 5.0)
        assert sr.elapsed >= 4.5

    def test_elapsed_with_end(self):
        start = time.time() - 10.0
        end = start + 10.0
        sr = StageRecord(name="Done", start_time=start, end_time=end)
        assert sr.elapsed == pytest.approx(10.0, abs=0.1)

    def test_elapsed_str_seconds(self):
        start = time.time()
        sr = StageRecord(name="Quick", start_time=start, end_time=start + 30.0)
        assert sr.elapsed_str == "30.0s"

    def test_elapsed_str_minutes(self):
        start = time.time()
        sr = StageRecord(name="Long", start_time=start, end_time=start + 120.0)
        assert sr.elapsed_str == "2.0m"


class TestPipelineProgressManagerInit:
    """Tests for PipelineProgressManager initialisation."""

    def test_init(self):
        pm = PipelineProgressManager()
        assert pm._live is None
        assert pm._current_task_id is None
        assert pm._stages == []
        assert pm._current_stage is None
        assert pm._stats == {}

    @patch("modules.utils.progress.Live")
    def test_start_creates_live(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        assert pm._pipeline_start > 0
        mock_live_cls.return_value.start.assert_called_once()
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_stop_closes_live(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.stop()
        mock_live_cls.return_value.stop.assert_called_once()
        assert pm._live is None

    @patch("modules.utils.progress.Live")
    def test_stop_without_start(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.stop()  # should not raise


class TestPipelineProgressStages:
    """Tests for sequential stage management."""

    @patch("modules.utils.progress.Live")
    def test_begin_stage(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Extraction", total=100)
        assert pm._current_stage is not None
        assert pm._current_stage.name == "Extraction"
        assert pm._current_stage.total == 100
        assert pm._current_task_id is not None
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_begin_stage_closes_previous(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Stage 1", total=50)
        first = pm._current_stage
        pm.begin_stage("Stage 2", total=30)
        assert first.end_time is not None
        assert pm._current_stage.name == "Stage 2"
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_advance_success(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Test", total=10)
        pm.advance("item 1", "success")
        assert pm._current_stage.completed == 1
        assert pm._current_stage.success == 1
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_advance_empty(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Test", total=10)
        pm.advance("item 1", "empty")
        assert pm._current_stage.empty == 1
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_advance_error(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Test", total=10)
        pm.advance("item 1", "error")
        assert pm._current_stage.errors == 1
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_advance_without_stage_no_crash(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.advance("orphan", "success")  # should not raise
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_complete_stage(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Test", total=5)
        pm.advance("a", "success")
        pm.advance("b", "success")
        pm.complete_stage()
        assert pm._current_stage.end_time is not None
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_complete_stage_fills_remaining(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Test", total=5)
        pm.advance("a", "success")
        pm.complete_stage()
        # Should have advanced the remaining 4 items
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_complete_stage_without_stage(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.complete_stage()  # should not raise
        pm.stop()


class TestPipelineProgressParallelStages:
    """Tests for parallel stage management."""

    @patch("modules.utils.progress.Live")
    def test_begin_parallel_stages(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_parallel_stages({"FX Rates": 4, "News": 678})
        assert "FX Rates" in pm._parallel_stages
        assert "News" in pm._parallel_stages
        assert len(pm._parallel_tasks) == 2
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_advance_parallel(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_parallel_stages({"FX": 4, "News": 10})
        pm.advance_parallel("FX", "GBPUSD=X: 250 rates", "success")
        assert pm._parallel_stages["FX"].success == 1
        assert pm._parallel_stages["FX"].completed == 1
        pm.advance_parallel("News", "AAPL: 5 articles", "success")
        pm.advance_parallel("News", "MSFT: 0 articles", "empty")
        pm.advance_parallel("News", "XYZ: timeout", "error")
        assert pm._parallel_stages["News"].success == 1
        assert pm._parallel_stages["News"].empty == 1
        assert pm._parallel_stages["News"].errors == 1
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_advance_parallel_unknown_stage(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_parallel_stages({"FX": 4})
        pm.advance_parallel("Unknown", "test", "success")  # should not raise
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_complete_parallel_stages(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_parallel_stages({"FX": 2, "News": 3})
        fx_stage = pm._parallel_stages["FX"]
        pm.advance_parallel("FX", "", "success")
        pm.advance_parallel("FX", "", "success")
        pm.advance_parallel("News", "", "success")
        pm.complete_parallel_stages()
        assert fx_stage.end_time is not None
        assert pm._parallel_tasks == {}
        assert pm._parallel_stages == {}
        pm.stop()


class TestPipelineProgressHelpers:
    """Tests for helper methods: update_stats, log, spinner, print_banner, etc."""

    @patch("modules.utils.progress.Live")
    def test_update_stats(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.update_stats("Tickers", 678)
        assert pm._stats["Tickers"] == "678"
        pm.stop()

    @patch("modules.utils.progress.Live")
    def test_log_with_live(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.log("Test message", style="bold")
        pm.stop()

    def test_log_without_live(self):
        pm = PipelineProgressManager()
        pm.log("Offline message", style="dim")  # should not raise

    @patch("modules.utils.progress.Live")
    def test_spinner_context_manager(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        with pm.spinner("Loading..."):
            pass  # spinner should complete without error
        pm.stop()

    @patch("modules.utils.progress.console")
    def test_print_banner(self, mock_console):
        pm = PipelineProgressManager()
        pm.print_banner("Pipeline Start", "CW1 Value + Sentiment")
        mock_console.print.assert_called()

    @patch("modules.utils.progress.console")
    def test_print_banner_no_subtitle(self, mock_console):
        pm = PipelineProgressManager()
        pm.print_banner("Simple Title")
        mock_console.print.assert_called()

    @patch("modules.utils.progress.console")
    def test_print_summary_no_stages(self, mock_console):
        pm = PipelineProgressManager()
        pm._pipeline_start = time.time() - 5.0
        pm.print_summary()
        mock_console.print.assert_called()

    @patch("modules.utils.progress.console")
    def test_print_summary_with_stages(self, mock_console):
        pm = PipelineProgressManager()
        pm._pipeline_start = time.time() - 30.0
        s1 = StageRecord(name="Extract", total=100, completed=100, success=95, empty=3, errors=2)
        s1.end_time = s1.start_time + 20.0
        s2 = StageRecord(name="Transform", total=50, completed=50, success=50, empty=0, errors=0)
        s2.end_time = s2.start_time + 10.0
        pm._stages = [s1, s2]
        pm.print_summary()
        mock_console.print.assert_called()

    @patch("modules.utils.progress.console")
    def test_print_summary_minutes_format(self, mock_console):
        pm = PipelineProgressManager()
        pm._pipeline_start = time.time() - 120.0
        pm._stages = [StageRecord(name="Long", total=10, completed=10, success=10)]
        pm._stages[0].end_time = pm._stages[0].start_time + 90.0
        pm.print_summary()
        mock_console.print.assert_called()

    @patch("modules.utils.progress.console")
    def test_print_results_table(self, mock_console):
        pm = PipelineProgressManager()
        headers = ["Rank", "Company", "Score"]
        rows = [["1", "AAPL", "85.3"], ["2", "MSFT", "82.1"]]
        pm.print_results_table("Top Companies", headers, rows)
        mock_console.print.assert_called()

    @patch("modules.utils.progress.console")
    def test_print_results_table_with_styles(self, mock_console):
        pm = PipelineProgressManager()
        headers = ["Rank", "Company", "Score"]
        rows = [["1", "AAPL", "85.3"]]
        pm.print_results_table("Results", headers, rows, styles=["dim", "bold", "green"])
        mock_console.print.assert_called()

    def test_build_layout(self):
        pm = PipelineProgressManager()
        pm._stats = {"Tickers": "678", "Prices": "5600"}
        layout = pm._build_layout()
        assert layout is not None

    def test_build_layout_empty_stats(self):
        pm = PipelineProgressManager()
        layout = pm._build_layout()
        assert layout is not None

    @patch("modules.utils.progress.Live")
    def test_refresh_with_live(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm._refresh()  # should call live.update
        pm.stop()

    def test_refresh_without_live(self):
        pm = PipelineProgressManager()
        pm._refresh()  # should not raise


class TestPipelineProgressStopWithActiveStage:
    """Test edge cases around stopping with active stages."""

    @patch("modules.utils.progress.Live")
    def test_stop_with_active_stage(self, mock_live_cls):
        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Active", total=100)
        pm.advance("item", "success")
        pm.stop()
        assert pm._current_stage.end_time is not None
