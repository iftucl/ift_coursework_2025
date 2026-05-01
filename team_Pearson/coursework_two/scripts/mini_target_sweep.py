#!/usr/bin/env python3
"""Run a small target-only hyperparameter sweep for CW2 portfolio construction.

The script intentionally reuses already-materialized feature tables and rebuilds
only portfolio target weights. It is meant for development-time parameter
screening, not for exhaustive production tuning.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import yaml
from sqlalchemy import text
from sqlalchemy.engine import Engine

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
for path in (str(CW1_ROOT), str(REPO_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_one.modules.transform.cw2_features import (  # noqa: E402
    _build_carried_forward_portfolio_targets,
    _load_previous_portfolio_target_snapshot,
    _replace_rows_for_scope,
    _should_refresh_portfolio_targets,
)
from team_Pearson.coursework_two.modules.backtest import run_backtest_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.backtest.data_loader import (  # noqa: E402
    _build_portfolio_covariance_context,
    _load_feature_bundle_for_date,
)
from team_Pearson.coursework_two.modules.portfolio.construction import (  # noqa: E402
    build_portfolio_targets,
)
from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    default_cw2_config,
    load_env_layers,
    load_yaml,
    month_end_trading_days,
)

DEFAULT_RISK_AVERSIONS = (3.0, 4.0)
DEFAULT_MAX_SECTOR_WEIGHTS = (0.20, 0.25)
DEFAULT_COVARIANCE_METHODS = (
    "diagonal_shrinkage",
    "fundamental_factor",
    "statistical_factor",
)
DEFAULT_TURNOVER_CAPS = (0.50,)


def _repo_relative_path(path: Path | str) -> str:
    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(candidate)


PORTFOLIO_TARGET_ALLOWED_COLS = [
    "as_of_date",
    "portfolio_name",
    "symbol",
    "selection_rank",
    "selected_signal",
    "target_weight",
    "weighting_scheme",
    "ranking_mode",
    "ranking_score",
    "composite_alpha",
    "regime",
    "gics_sector",
    "country",
    "previous_weight",
    "trade_weight",
    "turnover_cap",
    "realized_turnover",
    "turnover_limited",
    "source",
]

DIAGNOSTIC_ALLOWED_COLS = [
    "snapshot_id",
    "as_of_date",
    "portfolio_name",
    "symbol",
    "candidate_rank",
    "selected_signal",
    "selection_drop_reason",
    "gics_sector",
    "country",
    "ranking_mode",
    "ranking_score",
    "composite_alpha",
    "optimizer_requested",
    "optimizer_applied",
    "raw_preference_weight",
    "pre_constraint_weight",
    "constrained_weight",
    "final_target_weight",
    "previous_weight",
    "constraint_weight_delta",
    "turnover_weight_delta",
    "total_weight_delta",
    "sector_weight_pre_constraint",
    "sector_weight_post_constraint",
    "sector_weight_final",
    "max_single_weight",
    "max_sector_weight",
    "single_name_cap_binding",
    "sector_cap_binding",
    "turnover_limited",
    "turnover_cap",
    "realized_turnover",
    "covariance_method",
    "optimizer_fallback_reason",
    "diagnostic_json",
]


@dataclass(frozen=True)
class SweepCandidate:
    candidate_id: str
    covariance_method: str
    risk_aversion: float
    max_sector_weight: float
    turnover_cap: float
    portfolio_name: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a 12-cell target-only CW2 covariance/risk parameter sweep."
    )
    parser.add_argument("--base-config", default=default_cw2_config())
    parser.add_argument("--start-date", default="2021-04-20")
    parser.add_argument("--end-date", default="2026-04-20")
    parser.add_argument(
        "--portfolio-prefix",
        default="cw2_ms_20260420",
        help="Prefix for generated portfolio_name values.",
    )
    parser.add_argument(
        "--run-prefix",
        default=None,
        help="Prefix for generated backtest run_name values. Defaults to portfolio-prefix plus UTC timestamp.",
    )
    parser.add_argument(
        "--output-dir",
        default="team_Pearson/coursework_two/outputs/mini_sweeps",
    )
    parser.add_argument(
        "--config-dir",
        default="team_Pearson/coursework_two/config/experiments/mini_sweep",
    )
    parser.add_argument(
        "--all-month-ends",
        action="store_true",
        help="Build every month-end snapshot instead of only scheduled rebalance snapshots.",
    )
    parser.add_argument(
        "--limit-candidates",
        type=int,
        default=0,
        help="Optional dev guard to run only the first N candidates.",
    )
    parser.add_argument(
        "--covariance-methods",
        default=",".join(DEFAULT_COVARIANCE_METHODS),
        help="Comma-separated covariance methods to include in the sweep.",
    )
    parser.add_argument(
        "--risk-aversions",
        default=",".join(str(value) for value in DEFAULT_RISK_AVERSIONS),
        help="Comma-separated risk_aversion values to include in the sweep.",
    )
    parser.add_argument(
        "--max-sector-weights",
        default=",".join(str(value) for value in DEFAULT_MAX_SECTOR_WEIGHTS),
        help="Comma-separated max_sector_weight values to include in the sweep.",
    )
    parser.add_argument(
        "--turnover-caps",
        default=",".join(str(value) for value in DEFAULT_TURNOVER_CAPS),
        help="Comma-separated turnover_cap values to include in the sweep.",
    )
    parser.add_argument(
        "--no-backtest",
        action="store_true",
        help="Only rebuild target positions and skip backtests/ranking metrics.",
    )
    return parser


def _parse_csv_strings(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _parse_csv_floats(value: str) -> List[float]:
    parsed: List[float] = []
    for item in _parse_csv_strings(value):
        parsed.append(float(item))
    return parsed


def _method_slug(method: str) -> str:
    mapping = {
        "diagonal_shrinkage": "diag",
        "fundamental_factor": "fund",
        "statistical_factor": "stat",
        "factor_model": "stat",
        "pca_factor": "stat",
    }
    return mapping.get(str(method).strip().lower(), str(method).strip().lower())


def _pct_slug(value: float) -> str:
    return str(int(round(float(value) * 100)))


def _candidate_grid(
    portfolio_prefix: str,
    *,
    covariance_methods: Iterable[str] = DEFAULT_COVARIANCE_METHODS,
    risk_aversions: Iterable[float] = DEFAULT_RISK_AVERSIONS,
    max_sector_weights: Iterable[float] = DEFAULT_MAX_SECTOR_WEIGHTS,
    turnover_caps: Iterable[float] = DEFAULT_TURNOVER_CAPS,
) -> List[SweepCandidate]:
    candidates: List[SweepCandidate] = []
    for method in covariance_methods:
        for risk_aversion in risk_aversions:
            for max_sector_weight in max_sector_weights:
                for turnover_cap in turnover_caps:
                    candidate_id = (
                        f"{_method_slug(method)}_ra{risk_aversion:g}_"
                        f"s{_pct_slug(max_sector_weight)}_t{_pct_slug(turnover_cap)}"
                    )
                    candidates.append(
                        SweepCandidate(
                            candidate_id=candidate_id,
                            covariance_method=method,
                            risk_aversion=float(risk_aversion),
                            max_sector_weight=float(max_sector_weight),
                            turnover_cap=float(turnover_cap),
                            portfolio_name=f"{portfolio_prefix}_{candidate_id}",
                        )
                    )
    return candidates


def _apply_candidate_config(
    base_config: Mapping[str, Any],
    candidate: SweepCandidate,
    *,
    end_date: date,
) -> Dict[str, Any]:
    cfg = deepcopy(dict(base_config))
    portfolio_cfg = cfg.setdefault("portfolio_construction", {})
    covariance_cfg = portfolio_cfg.setdefault("covariance", {})
    backtest_cfg = cfg.setdefault("backtest", {})
    recommendation_cfg = cfg.setdefault("recommendation", {})

    portfolio_cfg["portfolio_name"] = candidate.portfolio_name
    portfolio_cfg["max_sector_weight"] = candidate.max_sector_weight
    portfolio_cfg["turnover_cap"] = candidate.turnover_cap
    covariance_cfg["method"] = candidate.covariance_method
    covariance_cfg["risk_aversion"] = candidate.risk_aversion

    backtest_cfg["portfolio_name"] = candidate.portfolio_name
    backtest_cfg["end_date"] = end_date.isoformat()
    recommendation_cfg["portfolio_name"] = candidate.portfolio_name
    return cfg


def _scheduled_snapshot_dates(month_ends: List[date], config: Mapping[str, Any]) -> List[date]:
    if not month_ends:
        return []
    frequency = (
        str((config.get("backtest") or {}).get("rebalance_frequency") or "monthly").strip().lower()
    )
    if frequency == "monthly":
        return list(month_ends)
    if frequency == "quarterly":
        return [
            rebalance_date
            for idx, rebalance_date in enumerate(month_ends)
            if idx == 0 or rebalance_date.month in {3, 6, 9, 12}
        ]
    if frequency == "semiannual":
        return [
            rebalance_date
            for idx, rebalance_date in enumerate(month_ends)
            if idx == 0 or rebalance_date.month in {6, 12}
        ]
    if frequency == "annual":
        return [
            rebalance_date
            for idx, rebalance_date in enumerate(month_ends)
            if idx == 0 or rebalance_date.month == 12
        ]
    return list(month_ends)


def _with_as_of(records: Iterable[Mapping[str, Any]], as_of_date: date) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for record in records:
        row = dict(record)
        row.setdefault("as_of_date", as_of_date)
        out.append(row)
    return out


def _persist_target_snapshot(
    *,
    as_of_date: date,
    portfolio_name: str,
    target_records: List[Dict[str, Any]],
    diagnostic_records: List[Dict[str, Any]],
) -> Dict[str, int]:
    scope = {"as_of_date": as_of_date, "portfolio_name": portfolio_name}
    target_count = _replace_rows_for_scope(
        table_name="portfolio_target_positions",
        rows=target_records,
        allowed_cols=PORTFOLIO_TARGET_ALLOWED_COLS,
        conflict_cols=["as_of_date", "portfolio_name", "symbol"],
        scope_cols=["as_of_date", "portfolio_name"],
        scope_values=scope,
    )
    diagnostic_count = _replace_rows_for_scope(
        table_name="portfolio_construction_diagnostics",
        rows=diagnostic_records,
        allowed_cols=DIAGNOSTIC_ALLOWED_COLS,
        conflict_cols=["as_of_date", "portfolio_name", "symbol"],
        scope_cols=["as_of_date", "portfolio_name"],
        scope_values=scope,
    )
    return {
        "portfolio_targets": int(target_count),
        "portfolio_diagnostics": int(diagnostic_count),
    }


def _rebuild_candidate_targets(
    *,
    engine: Engine,
    config: Dict[str, Any],
    candidate: SweepCandidate,
    snapshot_dates: List[date],
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for as_of_date in snapshot_dates:
        bundle = _load_feature_bundle_for_date(engine, as_of_date)
        factor_scores = _with_as_of(bundle.get("factor_scores") or [], as_of_date)
        risk_overlay = _with_as_of(bundle.get("risk_overlay") or [], as_of_date)
        universe_screen = _with_as_of(bundle.get("universe_screen") or [], as_of_date)
        company_info = dict(bundle.get("company_info") or {})
        previous_target_as_of, previous_targets = _load_previous_portfolio_target_snapshot(
            as_of_date,
            portfolio_name=candidate.portfolio_name,
        )

        if not factor_scores:
            counts = _persist_target_snapshot(
                as_of_date=as_of_date,
                portfolio_name=candidate.portfolio_name,
                target_records=[],
                diagnostic_records=[],
            )
            results.append(
                {
                    "as_of_date": as_of_date.isoformat(),
                    "status": "missing_factor_scores",
                    **counts,
                }
            )
            continue

        should_refresh = _should_refresh_portfolio_targets(
            as_of_date,
            config=config,
            previous_target_records=previous_targets,
        )
        diagnostics = None
        covariance_meta: Dict[str, Any] = {}
        if should_refresh:
            covariance_matrix, covariance_meta = _build_portfolio_covariance_context(
                engine,
                as_of_date,
                [str(row.get("symbol")) for row in factor_scores],
                config,
            )
            targets, diagnostics = build_portfolio_targets(
                factor_scores,
                risk_overlay,
                universe_screen,
                company_info,
                covariance_matrix=covariance_matrix,
                covariance_meta=covariance_meta,
                previous_positions=previous_targets,
                config=config,
                return_diagnostics=True,
            )
            default_source = "mini_target_sweep"
            status = "refreshed"
        else:
            targets = _build_carried_forward_portfolio_targets(
                as_of_date=as_of_date,
                portfolio_name=candidate.portfolio_name,
                previous_target_records=previous_targets,
            )
            default_source = "mini_target_sweep_carry"
            status = "carried_forward"

        target_records = [
            {
                **dict(record),
                "source": str(record.get("source") or default_source),
            }
            for record in targets
        ]
        snapshot_id = str(uuid.uuid4())
        diagnostic_records = (
            [{**dict(row), "snapshot_id": snapshot_id} for row in diagnostics.records]
            if diagnostics is not None
            else []
        )
        counts = _persist_target_snapshot(
            as_of_date=as_of_date,
            portfolio_name=candidate.portfolio_name,
            target_records=target_records,
            diagnostic_records=diagnostic_records,
        )
        results.append(
            {
                "as_of_date": as_of_date.isoformat(),
                "status": status,
                "previous_target_as_of_date": (
                    previous_target_as_of.isoformat() if previous_target_as_of is not None else None
                ),
                "covariance_method": covariance_meta.get("covariance_method"),
                "covariance_fallback_used": covariance_meta.get("covariance_fallback_used"),
                **counts,
            }
        )
    return results


def _metric_lookup(engine: Engine, run_id: str) -> Dict[str, float]:
    sql = text("""
        SELECT metric_group, metric_name, metric_value
        FROM systematic_equity.backtest_metrics
        WHERE run_id = :run_id
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    metrics: Dict[str, float] = {}
    for row in rows:
        key = str(row["metric_name"])
        try:
            metrics[key] = float(row["metric_value"])
        except (TypeError, ValueError):
            continue
    return metrics


def _performance_summary(engine: Engine, run_id: str) -> Dict[str, Optional[float]]:
    sql = text("""
        SELECT
            AVG(num_holdings) AS avg_holdings,
            AVG(turnover) AS avg_turnover,
            AVG(gross_turnover) AS avg_gross_turnover
        FROM systematic_equity.backtest_performance
        WHERE run_id = :run_id
        """)
    with engine.connect() as conn:
        row = conn.execute(sql, {"run_id": run_id}).mappings().one()
    out: Dict[str, Optional[float]] = {}
    for key, value in dict(row).items():
        try:
            out[key] = None if value is None else float(value)
        except (TypeError, ValueError):
            out[key] = None
    return out


def _score_row(row: Dict[str, Any]) -> Dict[str, Any]:
    max_drawdown = float(row.get("max_drawdown") or math.inf)
    avg_turnover = float(row.get("avg_monthly_turnover") or math.inf)
    beta = row.get("beta")
    avg_holdings = float(row.get("avg_holdings") or 0.0)
    beta_value = float(beta) if beta is not None else math.nan
    failures: List[str] = []
    if max_drawdown > 20.0:
        failures.append("max_drawdown_gt_20pct")
    if avg_turnover > 20.0:
        failures.append("avg_monthly_turnover_gt_20pct")
    if not math.isfinite(beta_value) or beta_value < 0.85 or beta_value > 1.10:
        failures.append("beta_outside_0.85_1.10")
    if avg_holdings < 25.0:
        failures.append("avg_holdings_below_25")
    return {
        **row,
        "eligible": not failures,
        "constraint_failures": ";".join(failures),
    }


def _rank_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scored = [_score_row(row) for row in rows]
    return sorted(
        scored,
        key=lambda row: (
            not bool(row.get("eligible")),
            -(float(row.get("sharpe_ratio") or -math.inf)),
            -(float(row.get("information_ratio") or -math.inf)),
            float(row.get("max_drawdown") or math.inf),
            float(row.get("avg_monthly_turnover") or math.inf),
        ),
    )


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(payload), sort_keys=False), encoding="utf-8")


def _write_outputs(
    output_dir: Path, ranked_rows: List[Dict[str, Any]], manifest: Dict[str, Any]
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (output_dir / "ranking.json").write_text(
        json.dumps(ranked_rows, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    if ranked_rows:
        fields = list(ranked_rows[0].keys())
        with (output_dir / "ranking.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(ranked_rows)


def main() -> int:
    args = build_parser().parse_args()
    load_env_layers()
    start_date = date.fromisoformat(str(args.start_date))
    end_date = date.fromisoformat(str(args.end_date))
    base_config_path = Path(args.base_config).resolve()
    base_config = load_yaml(str(base_config_path))
    engine = get_db_engine()

    sweep_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_prefix = str(args.run_prefix or f"{args.portfolio_prefix}_{sweep_stamp}")
    config_dir = Path(args.config_dir)
    output_dir = Path(args.output_dir) / sweep_stamp

    candidates = _candidate_grid(
        str(args.portfolio_prefix),
        covariance_methods=_parse_csv_strings(args.covariance_methods),
        risk_aversions=_parse_csv_floats(args.risk_aversions),
        max_sector_weights=_parse_csv_floats(args.max_sector_weights),
        turnover_caps=_parse_csv_floats(args.turnover_caps),
    )
    if int(args.limit_candidates or 0) > 0:
        candidates = candidates[: int(args.limit_candidates)]

    month_ends = month_end_trading_days(
        start_date=start_date,
        end_date=end_date,
        cw2_config_path=str(base_config_path),
    )
    snapshot_dates = (
        list(month_ends)
        if bool(args.all_month_ends)
        else _scheduled_snapshot_dates(month_ends, base_config)
    )
    if not snapshot_dates:
        raise ValueError("No snapshot dates resolved for mini target sweep.")

    rows: List[Dict[str, Any]] = []
    manifest: Dict[str, Any] = {
        "sweep_stamp": sweep_stamp,
        "base_config": _repo_relative_path(base_config_path),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "snapshot_dates": [item.isoformat() for item in snapshot_dates],
        "all_month_ends": bool(args.all_month_ends),
        "candidate_count": len(candidates),
        "candidates": [],
    }

    for ordinal, candidate in enumerate(candidates, start=1):
        config = _apply_candidate_config(base_config, candidate, end_date=end_date)
        config_path = config_dir / f"{candidate.portfolio_name}.yaml"
        _write_yaml(config_path, config)
        target_results = _rebuild_candidate_targets(
            engine=engine,
            config=config,
            candidate=candidate,
            snapshot_dates=snapshot_dates,
        )
        target_rows = sum(int(row.get("portfolio_targets") or 0) for row in target_results)
        diagnostic_rows = sum(int(row.get("portfolio_diagnostics") or 0) for row in target_results)

        row: Dict[str, Any] = {
            "rank": None,
            "candidate_id": candidate.candidate_id,
            "portfolio_name": candidate.portfolio_name,
            "config_path": str(config_path),
            "covariance_method": candidate.covariance_method,
            "risk_aversion": candidate.risk_aversion,
            "max_sector_weight": candidate.max_sector_weight,
            "turnover_cap": candidate.turnover_cap,
            "target_snapshot_count": len(snapshot_dates),
            "target_rows": target_rows,
            "diagnostic_rows": diagnostic_rows,
            "run_id": None,
            "run_name": None,
        }
        if not bool(args.no_backtest):
            run_name = f"{run_prefix}_{ordinal:02d}_{candidate.candidate_id}"
            run_id = run_backtest_from_config(
                run_name=run_name,
                config_path=str(config_path),
                db_engine=engine,
            )
            metrics = _metric_lookup(engine, run_id)
            perf = _performance_summary(engine, run_id)
            row.update(
                {
                    "run_id": run_id,
                    "run_name": run_name,
                    "annualized_return": metrics.get("annualized_return"),
                    "total_return": metrics.get("total_return"),
                    "benchmark_total_return": metrics.get("benchmark_total_return"),
                    "annualized_volatility": metrics.get("annualized_volatility"),
                    "sharpe_ratio": metrics.get("sharpe_ratio"),
                    "information_ratio": metrics.get("information_ratio"),
                    "max_drawdown": metrics.get("max_drawdown"),
                    "tracking_error": metrics.get("tracking_error"),
                    "beta": metrics.get("beta"),
                    "avg_monthly_turnover": metrics.get("avg_monthly_turnover"),
                    "avg_transaction_cost_bps": metrics.get("avg_transaction_cost_bps"),
                    **perf,
                }
            )
        rows.append(row)
        manifest["candidates"].append(
            {
                **row,
                "target_results": target_results,
            }
        )
        print(
            json.dumps(
                {
                    "status": "candidate_completed",
                    "candidate": candidate.candidate_id,
                    "ordinal": ordinal,
                    "candidate_count": len(candidates),
                    "target_rows": target_rows,
                    "run_id": row.get("run_id"),
                    "sharpe_ratio": row.get("sharpe_ratio"),
                    "information_ratio": row.get("information_ratio"),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    ranked_rows = _rank_rows(rows) if not bool(args.no_backtest) else rows
    for idx, row in enumerate(ranked_rows, start=1):
        row["rank"] = idx
    _write_outputs(output_dir, ranked_rows, manifest)
    print(
        json.dumps(
            {
                "status": "completed",
                "candidate_count": len(candidates),
                "output_dir": str(output_dir),
                "ranking_csv": str(output_dir / "ranking.csv"),
                "top_candidate": ranked_rows[0] if ranked_rows else None,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
