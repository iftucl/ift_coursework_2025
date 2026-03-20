from __future__ import annotations

import importlib

symbol_filter = importlib.import_module("modules.input.symbol_filter")


def test_filter_symbols_defaults_allow_suffix_and_dedup():
    out = symbol_filter.filter_symbols(["AAPL", "VOD.L", "aapl"], config={}, section="source_a")
    assert out == ["AAPL", "VOD.L"]


def test_filter_symbols_source_b_override_skips_suffix():
    cfg = {"source_b": {"skip_suffix_symbols": True, "symbol_regex_allow": r"^[A-Z0-9]+$"}}
    out = symbol_filter.filter_symbols(["AAPL", "VOD.L"], config=cfg, section="source_b")
    assert out == ["AAPL"]


def test_filter_symbols_global_policy_applies_when_no_section_override():
    cfg = {"symbol_filter": {"skip_suffix_symbols": True, "symbol_regex_allow": r"^[A-Z]+$"}}
    out = symbol_filter.filter_symbols(["AAPL", "BRK.B", "MSFT1"], config=cfg, section="source_a")
    assert out == ["AAPL"]
