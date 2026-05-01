from __future__ import annotations

import argparse

import pytest

from modules.utils.args_parser import build_parser, parse_csv_lower_list, valid_date


def test_valid_date_accepts_iso_date():
    assert valid_date("2026-02-14") == "2026-02-14"


def test_valid_date_rejects_invalid_format():
    with pytest.raises(argparse.ArgumentTypeError):
        valid_date("2026/02/14")


def test_parse_csv_lower_list_normalizes_and_dedupes():
    out = parse_csv_lower_list("source_a, source_b, SOURCE_A")
    assert out == ["source_a", "source_b"]


def test_parse_csv_lower_list_empty_tokens_are_removed():
    out = parse_csv_lower_list(" , source_a, , ")
    assert out == ["source_a"]


def test_build_parser_parses_enabled_extractors_as_list():
    parser = build_parser()
    args = parser.parse_args(
        [
            "--frequency",
            "daily",
            "--enabled-extractors",
            "source_a,source_b",
        ]
    )
    assert args.enabled_extractors == ["source_a", "source_b"]


def test_build_parser_allows_missing_frequency_for_config_default():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.frequency is None
