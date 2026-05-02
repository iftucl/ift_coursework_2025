from __future__ import annotations

"""Run requirement-style Test 11 using factor-weight Dirichlet neighbourhood reruns."""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"

for path in (str(REPO_ROOT), str(CW1_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from team_Pearson.coursework_two.modules.analysis import run_analysis_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.backtest import run_backtest_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.reporting import (  # noqa: E402
    generate_backtest_report_from_config,
)
from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    default_cw1_config,
    load_env_layers,
    load_yaml,
    print_json,
)
from team_Pearson.coursework_two.scripts.run_sensitivity_analysis import (  # noqa: E402
    ScenarioSpec,
    _artifact_path,
    _baseline_normal_weights,
    _baseline_portfolio_name,
    _deep_merge,
    _materialize_scenario_snapshots,
    _scenario_portfolio_name,
    _scenario_report_name,
    _scenario_run_name,
    _scenario_summary_record,
    _summaries_to_markdown,
)

_DEFAULT_BASELINE_CONFIG = (
    CW2_ROOT / "config" / "experiments" / "formal" / "cw2_formal_20260420_fund_ra3_s30_t50.yaml"
)
_DEFAULT_OUTPUT_ROOT = CW2_ROOT / "outputs" / "robustness" / "test11_factor_neighbourhood"


@dataclass(frozen=True)
class DirichletSpec:
    key: str
    concentration: float
    sample_count: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Test 11 as factor-weight Dirichlet neighbourhood reruns around regime.normal baseline weights."
    )
    parser.add_argument("--cw2-config", default=str(_DEFAULT_BASELINE_CONFIG))
    parser.add_argument(
        "--cw1-config",
        default=default_cw1_config(),
    )
    parser.add_argument("--start-date", default="2021-04-20")
    parser.add_argument("--end-date", default="2026-04-20")
    parser.add_argument("--company-limit", type=int, default=1000)
    parser.add_argument("--output-root", default=str(_DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report-output-dir", default=None)
    parser.add_argument("--run-prefix", default="cw2_test11_factor_nbhd")
    parser.add_argument("--skip-existing-snapshots", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fast-summary-only",
        action="store_true",
        help=(
            "Run scenario backtests and summary metrics only. This skips per-scenario "
            "analysis/report bundles so the final evidence pack can use central figures."
        ),
    )
    parser.add_argument("--seed", type=int, default=20260420)
    parser.add_argument("--summary-tag", default="")
    parser.add_argument("--loose-count", type=int, default=3)
    parser.add_argument("--medium-count", type=int, default=3)
    parser.add_argument("--tight-count", type=int, default=3)
    parser.add_argument("--loose-alpha", type=float, default=100.0)
    parser.add_argument("--medium-alpha", type=float, default=250.0)
    parser.add_argument("--tight-alpha", type=float, default=500.0)
    return parser


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(dict(payload), fh, sort_keys=False)


def _dirichlet_specs(args: argparse.Namespace) -> List[DirichletSpec]:
    return [
        DirichletSpec("loose", float(args.loose_alpha), int(args.loose_count)),
        DirichletSpec("medium", float(args.medium_alpha), int(args.medium_count)),
        DirichletSpec("tight", float(args.tight_alpha), int(args.tight_count)),
    ]


def _sample_dirichlet_weights(
    baseline_weights: Mapping[str, float],
    *,
    concentration: float,
    sample_count: int,
    rng: np.random.Generator,
) -> List[Dict[str, float]]:
    factor_names = list(baseline_weights.keys())
    baseline = np.asarray([float(baseline_weights[name]) for name in factor_names], dtype=float)
    eps = 1e-4
    alpha = np.maximum(baseline * float(concentration), eps)
    samples: List[Dict[str, float]] = []
    for _ in range(sample_count):
        draw = rng.dirichlet(alpha)
        cleaned = np.where(draw < 1e-8, 0.0, draw)
        cleaned = cleaned / cleaned.sum()
        samples.append({name: float(value) for name, value in zip(factor_names, cleaned)})
    return samples


def _weight_columns(weights: Mapping[str, float]) -> Dict[str, float]:
    return {f"regime.normal.{key}": float(value) for key, value in weights.items()}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_layers()

    start_date = date.fromisoformat(str(args.start_date))
    end_date = date.fromisoformat(str(args.end_date))
    output_root = Path(str(args.output_root)).resolve()
    config_output_root = output_root / "configs"
    summary_output_root = output_root / "summaries"
    report_root = (
        Path(str(args.report_output_dir)).resolve()
        if args.report_output_dir
        else (output_root / "reports")
    )
    base_config_path = Path(str(args.cw2_config)).resolve()
    base_config = load_yaml(str(base_config_path))
    baseline_weights = _baseline_normal_weights(base_config)
    base_portfolio_name = _baseline_portfolio_name(base_config)
    rng = np.random.default_rng(int(args.seed))

    manifest: List[Dict[str, Any]] = []
    scenario_counter = 0
    for spec in _dirichlet_specs(args):
        if spec.sample_count <= 0:
            continue
        sampled_weights = _sample_dirichlet_weights(
            baseline_weights,
            concentration=spec.concentration,
            sample_count=spec.sample_count,
            rng=rng,
        )
        for sample_index, sampled in enumerate(sampled_weights, start=1):
            scenario_counter += 1
            scenario_key = (
                f"test11_{spec.key}_alpha_{int(round(spec.concentration))}_{sample_index:02d}"
            )
            scenario = ScenarioSpec(
                test_key="11",
                scenario_key=scenario_key,
                description=(
                    "Factor-weight Dirichlet neighbourhood rerun around regime.normal baseline "
                    f"(band={spec.key}, alpha={spec.concentration:.0f}, sample={sample_index})."
                ),
                config_override={"regime": {"normal": sampled}},
                requires_snapshot_refresh=True,
            )

            merged_config = _deep_merge(base_config, scenario.config_override)
            scenario_portfolio_name = _scenario_portfolio_name(
                base_portfolio_name, scenario.scenario_key
            )
            merged_config = _deep_merge(
                merged_config,
                {
                    "portfolio_construction": {"portfolio_name": scenario_portfolio_name},
                    "backtest": {"portfolio_name": scenario_portfolio_name},
                },
            )

            scenario_config_path = (
                config_output_root / f"{scenario.test_key}_{scenario.scenario_key}.yaml"
            )
            _write_yaml(scenario_config_path, merged_config)
            record: Dict[str, Any] = {
                "test_key": scenario.test_key,
                "scenario_key": scenario.scenario_key,
                "description": scenario.description,
                "config_path": str(scenario_config_path),
                "portfolio_name": scenario_portfolio_name,
                "neighbourhood_band": spec.key,
                "dirichlet_alpha": float(spec.concentration),
                "sample_index": sample_index,
                **_weight_columns(sampled),
            }

            if args.dry_run:
                manifest.append(record)
                continue

            snapshot_summary = _materialize_scenario_snapshots(
                cw1_config_path=str(args.cw1_config),
                cw2_config_path=str(scenario_config_path),
                start_date=start_date,
                end_date=end_date,
                company_limit=int(args.company_limit),
                skip_existing=bool(args.skip_existing_snapshots),
            )
            record["snapshot_summary"] = snapshot_summary

            run_name = _scenario_run_name(str(args.run_prefix), scenario)
            run_id = run_backtest_from_config(
                run_name=run_name, config_path=str(scenario_config_path)
            )
            if args.fast_summary_only:
                analysis_output = {"skipped": True, "reason": "fast_summary_only"}
                report_output = None
            else:
                analysis_output = run_analysis_from_config(
                    run_id=run_id, config_path=str(scenario_config_path)
                )
                report_output = generate_backtest_report_from_config(
                    run_id=run_id,
                    config_path=str(scenario_config_path),
                    report_name=_scenario_report_name(run_name),
                    output_dir=str(report_root),
                )
            record.update(
                _scenario_summary_record(
                    spec=scenario,
                    run_id=run_id,
                    run_name=run_name,
                    report_output=report_output,
                    config_path=scenario_config_path,
                    portfolio_name=scenario_portfolio_name,
                )
            )
            record["analysis"] = analysis_output
            record["report"] = dict(report_output) if report_output is not None else None
            manifest.append(record)

    summary_output_root.mkdir(parents=True, exist_ok=True)
    summary_json = _artifact_path(
        summary_output_root,
        "test11_factor_neighbourhood_manifest",
        ".json",
        str(args.summary_tag),
    )
    summary_json.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    summary_csv = None
    summary_md = None
    if not args.dry_run:
        summary_csv = _artifact_path(
            summary_output_root,
            "test11_factor_neighbourhood_summary",
            ".csv",
            str(args.summary_tag),
        )
        summary_md = _artifact_path(
            summary_output_root,
            "test11_factor_neighbourhood_summary",
            ".md",
            str(args.summary_tag),
        )
        summary_df = pd.DataFrame(manifest)
        summary_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")
        summary_md.write_text(
            _summaries_to_markdown(summary_df.to_dict(orient="records")),
            encoding="utf-8",
        )

    print_json(
        {
            "ok": True,
            "dry_run": bool(args.dry_run),
            "seed": int(args.seed),
            "scenario_count": len(manifest),
            "summary_json": str(summary_json),
            "summary_csv": (str(summary_csv) if summary_csv is not None else None),
            "summary_md": (str(summary_md) if summary_md is not None else None),
            "bands": [
                {
                    "key": spec.key,
                    "alpha": spec.concentration,
                    "sample_count": spec.sample_count,
                }
                for spec in _dirichlet_specs(args)
                if spec.sample_count > 0
            ],
            "scenarios": manifest,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
