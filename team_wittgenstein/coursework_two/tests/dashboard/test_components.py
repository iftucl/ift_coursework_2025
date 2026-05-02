"""Tests for dashboard.lib.components.

Components mostly call st.markdown(html, unsafe_allow_html=True). We mock
st.markdown to capture what HTML each helper produces, and verify the
shape (correct CSS classes, content, attributes).
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dashboard"))

from lib import components as c  # noqa: E402


def _capture_markdown_calls():
    """Returns a context manager that captures st.markdown calls.

    Yields a list of (html_string, kwargs) tuples for each st.markdown call.
    """
    return patch.object(c.st, "markdown")


# ---------------------------------------------------------------------------
# kpi_card
# ---------------------------------------------------------------------------


class TestKpiCard:
    def test_label_and_value_in_html(self):
        with _capture_markdown_calls() as mock_md:
            c.kpi_card("Sharpe Ratio", "0.63")
        html = mock_md.call_args[0][0]
        assert "Sharpe Ratio" in html
        assert "0.63" in html
        assert 'class="kpi-card"' in html

    def test_with_delta_positive(self):
        with _capture_markdown_calls() as mock_md:
            c.kpi_card("Test", "1.0", delta="+0.1", delta_positive=True)
        html = mock_md.call_args[0][0]
        assert "kpi-delta-positive" in html
        assert "+0.1" in html

    def test_with_delta_negative(self):
        with _capture_markdown_calls() as mock_md:
            c.kpi_card("Test", "1.0", delta="-0.1", delta_positive=False)
        html = mock_md.call_args[0][0]
        assert "kpi-delta-negative" in html

    def test_delta_neutral_when_positive_is_none(self):
        with _capture_markdown_calls() as mock_md:
            c.kpi_card("Test", "1.0", delta="info text", delta_positive=None)
        html = mock_md.call_args[0][0]
        # Neutral delta uses kpi-sub class
        assert "kpi-sub" in html

    def test_with_sub(self):
        with _capture_markdown_calls() as mock_md:
            c.kpi_card("Test", "1.0", sub="Benchmark 0.45")
        html = mock_md.call_args[0][0]
        assert "Benchmark 0.45" in html

    def test_value_only(self):
        with _capture_markdown_calls() as mock_md:
            c.kpi_card("Just a label", "42")
        html = mock_md.call_args[0][0]
        assert "Just a label" in html
        assert "42" in html
        # No delta classes
        assert "kpi-delta-positive" not in html
        assert "kpi-delta-negative" not in html


# ---------------------------------------------------------------------------
# section_header
# ---------------------------------------------------------------------------


class TestSectionHeader:
    def test_title_only(self):
        with _capture_markdown_calls() as mock_md:
            c.section_header("Performance")
        html = mock_md.call_args[0][0]
        assert "Performance" in html
        assert 'class="section-header"' in html

    def test_with_subtitle(self):
        with _capture_markdown_calls() as mock_md:
            c.section_header("Performance", "Headline metrics")
        html = mock_md.call_args[0][0]
        assert "Performance" in html
        assert "Headline metrics" in html


# ---------------------------------------------------------------------------
# Badges
# ---------------------------------------------------------------------------


class TestBadge:
    def test_returns_html_string(self):
        result = c.badge("Active", "success")
        assert "Active" in result
        assert "badge-success" in result

    def test_default_kind_is_info(self):
        result = c.badge("Note")
        assert "badge-info" in result


class TestStatusPill:
    def test_passed(self):
        result = c.status_pill(True)
        assert "OK" in result
        assert "badge-success" in result

    def test_failed(self):
        result = c.status_pill(False)
        assert "FAIL" in result
        assert "badge-danger" in result

    def test_custom_text(self):
        assert "Done" in c.status_pill(True, true_text="Done")
        assert "Stop" in c.status_pill(False, false_text="Stop")


class TestDbStatusBadge:
    def test_connected(self):
        result = c.db_status_badge(True)
        assert "Database connected" in result
        assert "badge-success" in result

    def test_disconnected(self):
        result = c.db_status_badge(False)
        assert "Database offline" in result
        assert "badge-danger" in result


# ---------------------------------------------------------------------------
# Other components
# ---------------------------------------------------------------------------


class TestInfoPanel:
    def test_renders_title_and_body(self):
        with _capture_markdown_calls() as mock_md:
            c.info_panel("Heads up", "This is a note")
        html = mock_md.call_args[0][0]
        assert "Heads up" in html
        assert "This is a note" in html


class TestHeroHeader:
    def test_renders_title_and_subtitle(self):
        with _capture_markdown_calls() as mock_md:
            c.hero_header("Main title", "Subtitle here")
        html = mock_md.call_args[0][0]
        assert "Main title" in html
        assert "Subtitle here" in html

    def test_no_subtitle_works(self):
        with _capture_markdown_calls() as mock_md:
            c.hero_header("Just title")
        html = mock_md.call_args[0][0]
        assert "Just title" in html


# ---------------------------------------------------------------------------
# page_setup - just verify it calls the right Streamlit functions
# ---------------------------------------------------------------------------


class TestPageSetup:
    def test_calls_set_page_config(self):
        with patch.object(c.st, "set_page_config") as mock_config, patch.object(
            c.st, "markdown"
        ):
            c.page_setup("My Page", icon="🎯")
        mock_config.assert_called_once()
        kwargs = mock_config.call_args[1]
        assert "My Page" in kwargs["page_title"]
        assert kwargs["page_icon"] == "🎯"
        assert kwargs["layout"] == "wide"

    def test_injects_css(self):
        with patch.object(c.st, "set_page_config"), patch.object(
            c.st, "markdown"
        ) as mock_md:
            c.page_setup("Page")
        # Should have called markdown at least once with the CSS
        assert mock_md.called
        first_call_html = mock_md.call_args[0][0]
        assert "<style>" in first_call_html
