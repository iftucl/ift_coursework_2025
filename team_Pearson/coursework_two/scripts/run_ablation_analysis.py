from __future__ import annotations

"""Run requirement-aligned ablation scenarios around the formal CW2 baseline."""

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd
import yaml
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"

for path in (str(REPO_ROOT), str(CW1_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_one.modules.transform.cw2_features import (  # noqa: E402
    build_and_load_cw2_features,
)
from team_Pearson.coursework_two.modules.analysis import run_analysis_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.backtest import run_backtest_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.reporting import (  # noqa: E402
    generate_backtest_report_from_config,
)
from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    default_cw1_config,
    existing_portfolio_target_count,
    load_env_layers,
    load_scheduler_symbols,
    load_yaml,
    print_json,
    quarter_end_trading_days,
)
from team_Pearson.coursework_two.scripts.run_sensitivity_analysis import (  # noqa: E402
    _compute_relative_metric_map,
)

_SCHEMA = "systematic_equity"
_DEFAULT_BASELINE_CONFIG = (
    CW2_ROOT / "config" / "experiments" / "formal" / "cw2_formal_20260420_fund_ra3_s30_t50.yaml"
)
_DEFAULT_OUTPUT_ROOT = CW2_ROOT / "outputs" / "robustness" / "ablation"
_DEFAULT_START_DATE = "2021-04-20"
_DEFAULT_END_DATE = "2026-04-20"


@dataclass(frozen=True)
class AblationSpec:
    block_key: str
    scenario_key: str
    description: str
    config_override: Dict[str, Any]
    requires_snapshot_refresh: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run CW2 ablation scenarios aligned with the coursework requirement sheet."
    )
    parser.add_argument("--cw2-config", default=str(_DEFAULT_BASELINE_CONFIG))
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--start-date", default=_DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=_DEFAULT_END_DATE)
    parser.add_argument("--company-limit", type=int, default=1000)
    parser.add_argument(
        "--blocks",
        default="all",
        help="Comma-separated ablation block ids (A,B,C) or 'all'.",
    )
    parser.add_argument(
        "--scenario-keys",
        default="",
        help="Optional comma-separated scenario keys to run.",
    )
    parser.add_argument(
        "--skip-existing-snapshots",
        action="store_true",
        help="Skip scenario snapshot dates that already exist for the scenario portfolio.",
    )
    parser.add_argument("--output-root", default=str(_DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report-output-dir", default=None)
    parser.add_argument("--run-prefix", default="cw2_ablation")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fast-summary-only",
        action="store_true",
        help=(
            "Run scenario backtests and summary metrics only. This skips per-scenario "
            "analysis/report bundles so the final requirement/evidence pack can be built centrally."
        ),
    )
    parser.add_argument("--summary-tag", default="")
    return parser


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(dict(base))
    for key, value in dict(override).items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").lower()
    return slug or "scenario"


def _baseline_portfolio_name(config: Mapping[str, Any]) -> str:
    portfolio_cfg = dict((config.get("portfolio_construction") or {}))
    backtest_cfg = dict((config.get("backtest") or {}))
    return str(
        portfolio_cfg.get("portfolio_name")
        or backtest_cfg.get("portfolio_name")
        or "cw2_core_equity"
    )


def _scenario_portfolio_name(base_portfolio_name: str, scenario_key: str) -> str:
    base_slug = _slugify(base_portfolio_name)
    scenario_slug = _slugify(scenario_key)
    candidate = f"{base_slug}_{scenario_slug}"
    if len(candidate) <= 50:
        return candidate
    compact_prefix = base_slug[:16].rstrip("_") or "cw2"
    compact_candidate = f"{compact_prefix}_{scenario_slug}"
    if len(compact_candidate) <= 50:
        return compact_candidate
    return compact_candidate[:50].rstrip("_")


def _selected_blocks(raw_value: str) -> set[str]:
    cleaned = str(raw_value or "all").strip().upper()
    if cleaned in {"ALL", "*"}:
        return {"A", "B", "C"}
    return {
        part.strip().upper()
        for part in cleaned.split(",")
        if part.strip().upper() in {"A", "B", "C"}
    }


def _selected_scenario_keys(raw_value: str) -> set[str]:
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return set()
    return {_slugify(part.strip()) for part in cleaned.split(",") if part.strip()}


def _normalize_weights(weights: Mapping[str, float]) -> Dict[str, float]:
    total = sum(float(value) for value in weights.values())
    if total <= 0:
        raise ValueError("invalid zero-sum weights")
    return {str(key): float(value) / total for key, value in weights.items()}


def _zero_out_factor(weights: Mapping[str, float], factor_name: str) -> Dict[str, float]:
    out = {str(key): float(value) for key, value in weights.items()}
    if factor_name not in out:
        raise KeyError(f"unknown factor {factor_name}")
    out[factor_name] = 0.0
    return _normalize_weights(out)


def _equal_weight_factor_map(weights: Mapping[str, float]) -> Dict[str, float]:
    keys = [str(key) for key in weights.keys()]
    share = 1.0 / float(len(keys))
    return {key: share for key in keys}


def _baseline_regime_weights(base_config: Mapping[str, Any], regime_name: str) -> Dict[str, float]:
    regime_cfg = dict((base_config.get("regime") or {}))
    weights = dict((regime_cfg.get(regime_name) or {}))
    return {str(key): float(value) for key, value in weights.items()}


def _build_ablation_a(base_config: Mapping[str, Any]) -> List[AblationSpec]:
    normal = _baseline_regime_weights(base_config, "normal")
    stress = _baseline_regime_weights(base_config, "stress")
    factor_names = ["sentiment", "dividend", "quality", "value", "market_technical"]
    scenarios: List[AblationSpec] = []
    for factor_name in factor_names:
        scenarios.append(
            AblationSpec(
                block_key="A",
                scenario_key=f"no_{factor_name}",
                description=f"Disable {factor_name} from both normal and stress factor blends.",
                config_override={
                    "regime": {
                        "normal": _zero_out_factor(normal, factor_name),
                        "stress": _zero_out_factor(stress, factor_name),
                    }
                },
                requires_snapshot_refresh=True,
            )
        )
    scenarios.append(
        AblationSpec(
            block_key="A",
            scenario_key="equal_weight",
            description="Set all factor groups to equal weights across normal and stress regimes.",
            config_override={
                "regime": {
                    "normal": _equal_weight_factor_map(normal),
                    "stress": _equal_weight_factor_map(stress),
                }
            },
            requires_snapshot_refresh=True,
        )
    )
    return scenarios


def _build_ablation_b(base_config: Mapping[str, Any]) -> List[AblationSpec]:
    normal = _baseline_regime_weights(base_config, "normal")
    return [
        AblationSpec(
            block_key="B",
            scenario_key="no_regime_switch",
            description="Force static normal weights without regime switching.",
            config_override={
                "regime": {
                    "stress": normal,
                    "vix_stress_threshold": 999.0,
                    "vix_exit_threshold": 998.0,
                }
            },
            requires_snapshot_refresh=True,
        ),
        AblationSpec(
            block_key="B",
            scenario_key="no_risk_overlay",
            description="Disable risk overlay hard filters and optional blacklists.",
            config_override={
                "risk_overlay": {
                    "min_market_cap_log": None,
                    "min_liquidity_20d": None,
                    "max_volatility_60d_percentile": 1.0,
                    "max_missing_factor_pct": 1.0,
                    # Keep the scenario config valid under the current Pydantic model
                    # while relaxing the overlay to its least restrictive allowed state.
                    "min_factor_groups_present": 1,
                    "required_factor_groups": [],
                    "optional_percentile_blacklists": [],
                }
            },
            requires_snapshot_refresh=True,
        ),
        AblationSpec(
            block_key="B",
            scenario_key="no_drawdown_brake",
            description="Disable the drawdown brake mechanism.",
            config_override={"backtest": {"drawdown_brake": {"enabled": False}}},
            requires_snapshot_refresh=False,
        ),
        AblationSpec(
            block_key="B",
            scenario_key="no_intraday_trigger",
            description="Disable intraday triggers and event-driven overlays.",
            config_override={"backtest": {"intraday_triggers": {"enabled": False}}},
            requires_snapshot_refresh=False,
        ),
        AblationSpec(
            block_key="B",
            scenario_key="no_liquidity_clipping",
            description="Disable liquidity clipping during execution.",
            config_override={"backtest": {"execution": {"enable_liquidity_clipping": False}}},
            requires_snapshot_refresh=False,
        ),
        AblationSpec(
            block_key="B",
            scenario_key="no_sector_constraint",
            description="Relax sector cap fully to 100%.",
            config_override={"portfolio_construction": {"max_sector_weight": 1.0}},
            requires_snapshot_refresh=True,
        ),
    ]


def _weighting_override(name: str) -> Dict[str, Any]:
    return {
        "portfolio_construction": {"weighting": name},
        "backtest": {"weighting": name},
    }


def _build_ablation_c() -> List[AblationSpec]:
    return [
        AblationSpec(
            block_key="C",
            scenario_key="equal_weight",
            description="Equal-weighted optimizer ablation.",
            config_override=_weighting_override("equal"),
            requires_snapshot_refresh=True,
        ),
        AblationSpec(
            block_key="C",
            scenario_key="score_weighted",
            description="Score-weighted optimizer ablation.",
            config_override=_weighting_override("score_weighted"),
            requires_snapshot_refresh=True,
        ),
        AblationSpec(
            block_key="C",
            scenario_key="inverse_volatility",
            description="Inverse-volatility weighting ablation.",
            config_override=_weighting_override("inverse_volatility"),
            requires_snapshot_refresh=True,
        ),
        AblationSpec(
            block_key="C",
            scenario_key="mainline_mv",
            description="Mainline mean-variance optimizer control.",
            config_override=_weighting_override("mean_variance"),
            requires_snapshot_refresh=True,
        ),
    ]


def build_ablation_scenarios(base_config: Mapping[str, Any]) -> List[AblationSpec]:
    scenarios: List[AblationSpec] = []
    scenarios.extend(_build_ablation_a(base_config))
    scenarios.extend(_build_ablation_b(base_config))
    scenarios.extend(_build_ablation_c())
    return scenarios


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(dict(payload), fh, sort_keys=False)


def _artifact_path(directory: Path, stem: str, suffix: str, tag: str) -> Path:
    cleaned = _slugify(tag) if str(tag or "").strip() else ""
    filename = f"{stem}_{cleaned}{suffix}" if cleaned else f"{stem}{suffix}"
    return directory / filename


def _materialize_scenario_snapshots(
    *,
    cw1_config_path: str,
    cw2_config_path: str,
    start_date: date,
    end_date: date,
    company_limit: int,
    skip_existing: bool,
) -> Dict[str, Any]:
    cw2_cfg = load_yaml(cw2_config_path)
    portfolio_name = _baseline_portfolio_name(cw2_cfg)
    symbols = load_scheduler_symbols(
        company_limit=int(company_limit),
        cw1_config_path=str(cw1_config_path),
        as_of_date=end_date,
    )
    quarter_ends = quarter_end_trading_days(
        start_date=start_date,
        end_date=end_date,
        cw2_config_path=str(cw2_config_path),
    )

    processed = 0
    skipped = 0
    results: List[Dict[str, Any]] = []
    for as_of_date in quarter_ends:
        existing = existing_portfolio_target_count(
            as_of_date=as_of_date,
            portfolio_name=portfolio_name,
        )
        if skip_existing and existing > 0:
            skipped += 1
            results.append(
                {
                    "as_of_date": as_of_date.isoformat(),
                    "status": "skipped_existing",
                    "existing_positions": existing,
                }
            )
            continue
        summary = build_and_load_cw2_features(
            run_date=as_of_date.isoformat(),
            symbols=symbols,
            config_path=str(cw2_config_path),
        )
        processed += 1
        results.append({"as_of_date": as_of_date.isoformat(), "status": "processed", **summary})

    return {
        "portfolio_name": portfolio_name,
        "symbol_count": len(symbols),
        "quarter_end_count": len(quarter_ends),
        "processed_count": processed,
        "skipped_existing_count": skipped,
        "results": results,
    }


def _load_metric_map(run_id: str) -> Dict[str, float]:
    sql = text(f"""
        SELECT metric_group, metric_name, metric_value
        FROM {_SCHEMA}.backtest_metrics
        WHERE run_id = :run_id
        """)
    engine = get_db_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    return {
        f"{row['metric_group']}.{row['metric_name']}": float(row["metric_value"])
        for row in rows
        if row.get("metric_value") is not None
    }


def _load_relative_metric_map(run_id: str) -> Dict[str, float]:
    sql = text(f"""
        SELECT versus_series, metric_name, metric_value
        FROM {_SCHEMA}.backtest_relative_metrics
        WHERE run_id = :run_id
        """)
    engine = get_db_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    return {
        f"{row['versus_series']}.{row['metric_name']}": float(row["metric_value"])
        for row in rows
        if row.get("metric_value") is not None
    } or _compute_relative_metric_map(run_id)


def _scenario_run_name(prefix: str, spec: AblationSpec) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{spec.block_key}_{_slugify(spec.scenario_key)}_{ts}"


def _scenario_report_name(run_name: str) -> str:
    return f"{run_name}_report"


def _scenario_summary_record(
    *,
    spec: AblationSpec,
    run_id: str,
    run_name: str,
    config_path: Path,
    report_output: Optional[Mapping[str, Any]],
    portfolio_name: Optional[str],
) -> Dict[str, Any]:
    metrics = _load_metric_map(run_id)
    relative = _load_relative_metric_map(run_id)
    return {
        "block_key": spec.block_key,
        "scenario_key": spec.scenario_key,
        "description": spec.description,
        "run_id": run_id,
        "run_name": run_name,
        "config_path": str(config_path),
        "portfolio_name": portfolio_name,
        "report_output_dir": (
            str(report_output.get("output_dir")) if report_output is not None else None
        ),
        "return.annualized_return": metrics.get("return.annualized_return"),
        "risk_adjusted.sharpe_ratio": metrics.get("risk_adjusted.sharpe_ratio"),
        "risk.max_drawdown": metrics.get("risk.max_drawdown"),
        "risk.annualized_volatility": metrics.get("risk.annualized_volatility"),
        "portfolio.avg_holdings": metrics.get("portfolio.avg_holdings"),
        "portfolio.avg_monthly_recorded_turnover": metrics.get("portfolio.avg_monthly_turnover"),
        "portfolio.annualized_turnover_ratio": metrics.get("portfolio.annualized_turnover_ratio"),
        "static_baseline.excess_return_annualized": relative.get(
            "static_baseline.excess_return_annualized"
        ),
        "universe_ew.excess_return_annualized": relative.get(
            "universe_ew.excess_return_annualized"
        ),
        "SPY.excess_return_annualized": relative.get("SPY.excess_return_annualized"),
    }


def _summaries_to_markdown(records: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Ablation Summary",
        "",
        "| Block | Scenario | Ann Return | Sharpe | Max DD | Avg Monthly Recorded Turnover |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in records:

        def _fmt_pct(value: Any) -> str:
            return "NA" if value is None or pd.isna(value) else f"{float(value):.3f}%"

        def _fmt_num(value: Any) -> str:
            return "NA" if value is None or pd.isna(value) else f"{float(value):.3f}"

        lines.append(
            f"| {item.get('block_key')} | {item.get('scenario_key')} | {_fmt_pct(item.get('return.annualized_return'))} | {_fmt_num(item.get('risk_adjusted.sharpe_ratio'))} | {_fmt_pct(item.get('risk.max_drawdown'))} | {_fmt_pct(item.get('portfolio.avg_monthly_recorded_turnover'))} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_layers()

    start_date = date.fromisoformat(str(args.start_date))
    end_date = date.fromisoformat(str(args.end_date))
    output_root = Path(str(args.output_root)).resolve()
    report_root = (
        Path(str(args.report_output_dir)).resolve()
        if args.report_output_dir
        else output_root / "reports"
    )
    config_output_root = output_root / "configs"
    summary_output_root = output_root / "summaries"
    base_config_path = Path(str(args.cw2_config)).resolve()
    base_config = load_yaml(str(base_config_path))
    base_portfolio_name = _baseline_portfolio_name(base_config)

    selected_blocks = _selected_blocks(str(args.blocks))
    selected_scenarios = _selected_scenario_keys(str(args.scenario_keys))
    scenarios = [
        spec
        for spec in build_ablation_scenarios(base_config)
        if spec.block_key in selected_blocks
        and (not selected_scenarios or _slugify(spec.scenario_key) in selected_scenarios)
    ]
    if not scenarios:
        raise ValueError("no ablation scenarios selected")

    manifest: List[Dict[str, Any]] = []
    for spec in scenarios:
        merged_config = _deep_merge(base_config, spec.config_override)
        scenario_portfolio_name = None
        if spec.requires_snapshot_refresh:
            scenario_portfolio_name = _scenario_portfolio_name(
                base_portfolio_name, spec.scenario_key
            )
            merged_config = _deep_merge(
                merged_config,
                {
                    "portfolio_construction": {"portfolio_name": scenario_portfolio_name},
                    "backtest": {"portfolio_name": scenario_portfolio_name},
                },
            )

        scenario_config_path = config_output_root / f"{spec.block_key}_{spec.scenario_key}.yaml"
        _write_yaml(scenario_config_path, merged_config)
        record: Dict[str, Any] = {
            "block_key": spec.block_key,
            "scenario_key": spec.scenario_key,
            "description": spec.description,
            "config_path": str(scenario_config_path),
            "requires_snapshot_refresh": spec.requires_snapshot_refresh,
            "portfolio_name": scenario_portfolio_name,
        }
        if args.dry_run:
            manifest.append(record)
            continue

        if spec.requires_snapshot_refresh:
            record["snapshot_summary"] = _materialize_scenario_snapshots(
                cw1_config_path=str(args.cw1_config),
                cw2_config_path=str(scenario_config_path),
                start_date=start_date,
                end_date=end_date,
                company_limit=int(args.company_limit),
                skip_existing=bool(args.skip_existing_snapshots),
            )

        run_name = _scenario_run_name(str(args.run_prefix), spec)
        run_id = run_backtest_from_config(run_name=run_name, config_path=str(scenario_config_path))
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
                spec=spec,
                run_id=run_id,
                run_name=run_name,
                config_path=scenario_config_path,
                report_output=report_output,
                portfolio_name=scenario_portfolio_name,
            )
        )
        record["analysis"] = analysis_output
        record["report"] = dict(report_output) if report_output is not None else None
        manifest.append(record)

    summary_output_root.mkdir(parents=True, exist_ok=True)
    summary_json = _artifact_path(
        summary_output_root, "ablation_manifest", ".json", str(args.summary_tag)
    )
    summary_json.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    summary_csv = None
    summary_md = None
    if not args.dry_run:
        summary_csv = _artifact_path(
            summary_output_root, "ablation_summary", ".csv", str(args.summary_tag)
        )
        summary_md = _artifact_path(
            summary_output_root, "ablation_summary", ".md", str(args.summary_tag)
        )
        summary_df = pd.DataFrame(manifest)
        summary_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")
        summary_md.write_text(
            _summaries_to_markdown(summary_df.to_dict(orient="records")), encoding="utf-8"
        )

    print_json(
        {
            "scenario_count": len(manifest),
            "blocks_selected": sorted(selected_blocks),
            "scenario_keys_selected": sorted(selected_scenarios),
            "dry_run": bool(args.dry_run),
            "manifest_path": str(summary_json),
            "csv_path": str(summary_csv) if summary_csv is not None else None,
            "markdown_path": str(summary_md) if summary_md is not None else None,
            "scenarios": manifest,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
