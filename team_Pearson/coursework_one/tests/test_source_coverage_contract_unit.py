from __future__ import annotations

import modules.utils.source_coverage as coverage_mod


def test_initialize_source_coverage_contract_distinguishes_policy_and_routing():
    tracker = coverage_mod.initialize_source_coverage_contract(
        universe=["AAPL", "BRK.B", "ABC"],
        config={
            "symbol_filter": {
                "skip_suffix_symbols": True,
                "symbol_regex_allow": r"^[A-Z0-9]+$",
            },
            "routing": {
                "history_ticker_policy": "skip",
                "history_blocklist": ["ABC"],
            },
        },
        enabled_extractors=["source_a", "source_b"],
        source_b_expected_windows=2,
    )

    source_a = tracker["source_a"]
    source_b = tracker["source_b"]

    assert source_a["AAPL"]["expected_in_run"] is True
    assert source_a["AAPL"]["status"] == "expected"
    assert source_a["BRK.B"]["status"] == "excluded_by_policy"
    assert source_a["ABC"]["status"] == "excluded_by_routing"
    assert source_a["ABC"]["routing_eligible"] is False

    assert source_b["AAPL"]["expected_in_run"] is True
    assert source_b["BRK.B"]["status"] == "excluded_by_policy"
    assert source_b["ABC"]["expected_in_run"] is True
    assert source_b["ABC"]["details"]["expected_windows"] == 2


def test_finalize_source_coverage_contract_classifies_realized_empty_and_missing():
    tracker = coverage_mod.initialize_source_coverage_contract(
        universe=["AAPL", "MSFT", "GOOG"],
        config={"source_coverage_contract": {"max_missing_source_b_symbols": 0}},
        enabled_extractors=["source_b"],
        source_b_expected_windows=2,
    )

    coverage_mod.mark_source_b_window_result(
        tracker, "AAPL", outcome="success", article_count=3, loaded_rows=5
    )
    coverage_mod.mark_source_b_window_result(
        tracker, "AAPL", outcome="success", article_count=0, loaded_rows=0
    )
    coverage_mod.mark_source_b_window_result(
        tracker, "MSFT", outcome="success", article_count=0, loaded_rows=0
    )
    coverage_mod.mark_source_b_window_result(
        tracker, "MSFT", outcome="reused", article_count=0, loaded_rows=0
    )
    coverage_mod.mark_source_b_window_result(
        tracker, "GOOG", outcome="success", article_count=1, loaded_rows=2
    )
    coverage_mod.mark_source_b_window_result(tracker, "GOOG", outcome="failed", reason="timeout")

    rows, report = coverage_mod.finalize_source_coverage_contract(
        tracker,
        config={"source_coverage_contract": {"max_missing_source_b_symbols": 0}},
    )
    by_key = {(row["source_name"], row["symbol"]): row for row in rows}

    assert by_key[("source_b", "AAPL")]["status"] == "aligned"
    assert by_key[("source_b", "AAPL")]["content_available"] is True

    assert by_key[("source_b", "MSFT")]["status"] == "realized_empty"
    assert by_key[("source_b", "MSFT")]["content_available"] is False
    assert by_key[("source_b", "MSFT")]["reason_code"] == "no_articles_in_window"

    assert by_key[("source_b", "GOOG")]["status"] == "missing_or_failed"
    assert by_key[("source_b", "GOOG")]["realized_in_run"] is False
    assert by_key[("source_b", "GOOG")]["reason_code"] == "failed_windows_present"

    source_b_report = report["sources"]["source_b"]
    assert source_b_report["expected_count"] == 3
    assert source_b_report["realized_count"] == 2
    assert source_b_report["content_available_count"] == 1
    assert source_b_report["realized_empty_count"] == 1
    assert source_b_report["unexpected_missing_count"] == 1
    assert source_b_report["unexpected_missing_symbols"] == ["GOOG"]
    assert report["passed"] is False


def test_summarize_source_coverage_counts_returns_compact_payload():
    summary = coverage_mod.summarize_source_coverage_counts(
        {
            "passed": False,
            "failures": ["source_b_unexpected_missing=1>0"],
            "sources": {
                "source_a": {
                    "expected_count": 4,
                    "realized_count": 4,
                    "unexpected_missing_count": 0,
                },
                "source_b": {
                    "expected_count": 4,
                    "realized_count": 3,
                    "unexpected_missing_count": 1,
                    "realized_empty_count": 1,
                },
            },
        }
    )

    assert summary == {
        "passed": False,
        "failures": ["source_b_unexpected_missing=1>0"],
        "source_a": {
            "expected_count": 4,
            "realized_count": 4,
            "unexpected_missing_count": 0,
        },
        "source_b": {
            "expected_count": 4,
            "realized_count": 3,
            "unexpected_missing_count": 1,
            "realized_empty_count": 1,
        },
    }


def test_source_a_skipped_unavailable_is_realized_empty_not_missing():
    tracker = coverage_mod.initialize_source_coverage_contract(
        universe=["ANTM"],
        config={"source_coverage_contract": {"max_missing_source_a_symbols": 0}},
        enabled_extractors=["source_a"],
        source_b_expected_windows=0,
    )

    coverage_mod.mark_source_a_result(
        tracker,
        "ANTM",
        outcome="skipped",
        reason="source_a_no_data_returned",
    )

    rows, report = coverage_mod.finalize_source_coverage_contract(
        tracker,
        config={"source_coverage_contract": {"max_missing_source_a_symbols": 0}},
    )
    row = rows[0]

    assert row["source_name"] == "source_a"
    assert row["symbol"] == "ANTM"
    assert row["status"] == "realized_empty"
    assert row["realized_in_run"] is True
    assert row["content_available"] is False
    assert row["reason_code"] == "source_a_unavailable_or_empty"
    assert report["sources"]["source_a"]["unexpected_missing_count"] == 0
    assert report["sources"]["source_a"]["realized_empty_count"] == 1
    assert report["passed"] is True
