"""Tests for _table_utils.py — save_table_png rendering utility."""

import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # non-interactive backend
import _table_utils as tu
import matplotlib.pyplot as plt
import numpy as np
import pytest

# ── helpers ───────────────────────────────────────────────────────────────────


def _simple_call(tmp_path, **kwargs):
    """Call save_table_png with minimal required args, overridable via kwargs."""
    defaults = dict(
        headers=["Name", "Value"],
        rows=[["Alpha", "0.05"], ["Beta", "1.20"]],
        title="Test Table",
        filepath=tmp_path / "out.png",
    )
    defaults.update(kwargs)
    tu.save_table_png(**defaults)
    return defaults["filepath"]


# ── TestSaveTablePng ──────────────────────────────────────────────────────────


class TestSaveTablePng:
    def test_creates_file(self, tmp_path):
        fp = _simple_call(tmp_path)
        assert fp.exists()

    def test_file_is_nonempty(self, tmp_path):
        fp = _simple_call(tmp_path)
        assert fp.stat().st_size > 0

    def test_png_magic_bytes(self, tmp_path):
        fp = _simple_call(tmp_path)
        with open(fp, "rb") as f:
            magic = f.read(8)
        assert magic == b"\x89PNG\r\n\x1a\n"

    def test_custom_title(self, tmp_path):
        # Just verifies no exception is raised with a custom title
        fp = _simple_call(tmp_path, title="Custom Title")
        assert fp.exists()

    def test_single_row(self, tmp_path):
        fp = _simple_call(tmp_path, rows=[["OnlyRow", "42"]])
        assert fp.exists()

    def test_many_rows(self, tmp_path):
        rows = [[f"Row{i}", str(i * 0.01)] for i in range(20)]
        fp = _simple_call(tmp_path, rows=rows)
        assert fp.exists()

    def test_three_columns(self, tmp_path):
        fp = _simple_call(
            tmp_path,
            headers=["A", "B", "C"],
            rows=[["1", "2", "3"], ["4", "5", "6"]],
        )
        assert fp.exists()

    def test_highlight_rows(self, tmp_path):
        fp = _simple_call(tmp_path, highlight_rows=[0])
        assert fp.exists()

    def test_bold_rows(self, tmp_path):
        fp = _simple_call(tmp_path, bold_rows=[1])
        assert fp.exists()

    def test_footnote(self, tmp_path):
        fp = _simple_call(tmp_path, footnote="* annualised figure")
        assert fp.exists()

    def test_custom_figsize(self, tmp_path):
        fp = _simple_call(tmp_path, figsize=(14, 5))
        assert fp.exists()

    def test_custom_fontsize(self, tmp_path):
        fp = _simple_call(tmp_path, fontsize=8)
        assert fp.exists()

    def test_custom_col_widths(self, tmp_path):
        fp = _simple_call(tmp_path, col_widths=[3, 1])
        assert fp.exists()

    def test_col_widths_normalised(self, tmp_path):
        # Widths that don't sum to 1 should still work (function normalises them)
        fp = _simple_call(tmp_path, col_widths=[10, 50])
        assert fp.exists()

    def test_highlight_and_bold_overlap(self, tmp_path):
        fp = _simple_call(
            tmp_path,
            rows=[["A", "1"], ["B", "2"], ["C", "3"]],
            highlight_rows=[1],
            bold_rows=[1],
        )
        assert fp.exists()

    def test_no_figures_left_open(self, tmp_path):
        before = len(plt.get_fignums())
        _simple_call(tmp_path)
        after = len(plt.get_fignums())
        assert after == before  # figure was closed

    def test_filepath_as_string(self, tmp_path):
        # filepath can be a str (Path wrapping handles it)
        fp = str(tmp_path / "str_path.png")
        tu.save_table_png(
            headers=["X"],
            rows=[["1"]],
            title="T",
            filepath=fp,
        )
        assert Path(fp).exists()

    def test_empty_highlight_and_bold_lists(self, tmp_path):
        fp = _simple_call(tmp_path, highlight_rows=[], bold_rows=[])
        assert fp.exists()

    def test_alternating_row_colors_applied(self, tmp_path):
        # Smoke test: 4 rows triggers both even and odd row styling
        rows = [[f"R{i}", str(i)] for i in range(4)]
        fp = _simple_call(tmp_path, rows=rows)
        assert fp.exists()
