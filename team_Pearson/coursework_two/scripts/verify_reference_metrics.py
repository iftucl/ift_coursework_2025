from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

DEFAULT_REFERENCE = Path("team_Pearson/coursework_two/repro/reference_run_20260420.json")

METRIC_KEYS = (
    "total_return",
    "annualized_return",
    "annualized_volatility",
    "sharpe_ratio",
    "max_drawdown",
    "information_ratio_vs_primary",
    "benchmark_total_return",
    "excess_return_vs_primary",
)

META_KEYS = (
    "start_date",
    "end_date",
    "rebalance_frequency",
    "primary_benchmark",
    "benchmark_ticker",
    "transaction_cost_bps",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _close_enough(lhs: float, rhs: float, tol: float) -> bool:
    return math.isclose(lhs, rhs, rel_tol=0.0, abs_tol=tol)


def _lookup_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _compare_value(
    *,
    key_path: str,
    actual_value: Any,
    expected_value: Any,
    tolerance: float,
    failures: list[str],
) -> None:
    if actual_value is None:
        failures.append(
            f"Missing expected value for {key_path}: expected {expected_value!r}, got None"
        )
        return
    if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
        try:
            actual_num = float(actual_value)
            expected_num = float(expected_value)
        except (TypeError, ValueError):
            failures.append(
                f"Numeric mismatch for {key_path}: expected {expected_value!r}, got {actual_value!r}"
            )
            return
        if not _close_enough(actual_num, expected_num, tolerance):
            failures.append(
                f"Numeric mismatch for {key_path}: expected {expected_num:.6f}, got {actual_num:.6f}"
            )
        return
    if actual_value != expected_value:
        failures.append(
            f"Value mismatch for {key_path}: expected {expected_value!r}, got {actual_value!r}"
        )


def verify_summary_against_reference(
    *,
    summary: dict[str, Any],
    reference: dict[str, Any],
    tolerance: float,
) -> tuple[list[str], dict[str, bool]]:
    reference_run = dict(reference.get("reference_run") or {})
    expected_metrics = dict(reference_run.get("expected_metrics") or {})
    expected_row_counts = dict(reference_run.get("expected_row_counts") or {})
    expected_latest_dates = dict(reference_run.get("expected_latest_dates") or {})
    expected_sample_values = dict(reference_run.get("expected_sample_values") or {})
    expected_hashes = dict(reference_run.get("expected_hashes") or {})

    failures: list[str] = []
    layer_status = {
        "layer_1_metadata_and_metrics": True,
        "layer_2_row_counts_and_latest_dates": True,
        "layer_3_sample_values_and_hashes": True,
    }

    layer_1_failures: list[str] = []
    for key in META_KEYS:
        expected_value = reference_run[key]
        actual_value = summary.get(key)
        if actual_value != expected_value:
            layer_1_failures.append(
                f"Metadata mismatch for {key}: expected {expected_value!r}, got {actual_value!r}"
            )
    for key in METRIC_KEYS:
        expected_value = float(expected_metrics[key])
        actual_value = summary.get(key)
        if actual_value is None:
            layer_1_failures.append(
                f"Metric missing for {key}: expected {expected_value:.6f}, got None"
            )
            continue
        actual_num = float(actual_value)
        if not _close_enough(actual_num, expected_value, tolerance):
            layer_1_failures.append(
                f"Metric mismatch for {key}: expected {expected_value:.6f}, got {actual_num:.6f}"
            )
    if layer_1_failures:
        layer_status["layer_1_metadata_and_metrics"] = False
        failures.extend(layer_1_failures)

    layer_2_failures: list[str] = []
    for key_path, expected_value in expected_row_counts.items():
        _compare_value(
            key_path=key_path,
            actual_value=_lookup_path(summary, key_path),
            expected_value=expected_value,
            tolerance=tolerance,
            failures=layer_2_failures,
        )
    for key_path, expected_value in expected_latest_dates.items():
        _compare_value(
            key_path=key_path,
            actual_value=_lookup_path(summary, key_path),
            expected_value=expected_value,
            tolerance=tolerance,
            failures=layer_2_failures,
        )
    if layer_2_failures:
        layer_status["layer_2_row_counts_and_latest_dates"] = False
        failures.extend(layer_2_failures)

    layer_3_failures: list[str] = []
    for key_path, expected_value in expected_sample_values.items():
        _compare_value(
            key_path=key_path,
            actual_value=_lookup_path(summary, key_path),
            expected_value=expected_value,
            tolerance=tolerance,
            failures=layer_3_failures,
        )
    for key_path, expected_value in expected_hashes.items():
        _compare_value(
            key_path=key_path,
            actual_value=_lookup_path(summary, key_path),
            expected_value=expected_value,
            tolerance=tolerance,
            failures=layer_3_failures,
        )
    if layer_3_failures:
        layer_status["layer_3_sample_values_and_hashes"] = False
        failures.extend(layer_3_failures)

    return failures, layer_status


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a generated CW2 report summary against the tracked latest reference metrics."
    )
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--reference-json", default=str(DEFAULT_REFERENCE))
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.001,
        help="Absolute tolerance for numeric metric comparisons.",
    )
    args = parser.parse_args()

    summary = _load_json(Path(args.summary_path))
    reference = _load_json(Path(args.reference_json))
    failures, layer_status = verify_summary_against_reference(
        summary=summary,
        reference=reference,
        tolerance=args.tolerance,
    )

    if failures:
        print("Reference metric verification failed:")
        for item in failures:
            print(f"- {item}")
        return 1

    print("Reference metric verification passed.")
    for layer_name, passed in layer_status.items():
        print(f"{layer_name}: {'passed' if passed else 'failed'}")
    print(f"Summary path: {args.summary_path}")
    print(f"Reference path: {args.reference_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
