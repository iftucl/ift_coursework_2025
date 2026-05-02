from __future__ import annotations

"""Run deterministic sensitivity scenarios around the formal CW2 baseline."""

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

_SCHEMA = "systematic_equity"
_DEFAULT_BASELINE_CONFIG = (
    CW2_ROOT / "config" / "experiments" / "formal" / "cw2_formal_20260420_fund_ra3_s30_t50.yaml"
)
_DEFAULT_OUTPUT_ROOT = CW2_ROOT / "outputs" / "robustness" / "sensitivity"
_DEFAULT_START_DATE = "2021-04-20"
_DEFAULT_END_DATE = "2026-04-20"
_DEFAULT_BASELINE_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"


@dataclass(frozen=True)
class ScenarioSpec:
    test_key: str
    scenario_key: str
    description: str
    config_override: Dict[str, Any]
    requires_snapshot_refresh: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the deterministic CW2 sensitivity suite around the formal quarterly-rebalanced baseline."
    )
    parser.add_argument("--cw2-config", default=str(_DEFAULT_BASELINE_CONFIG))
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--start-date", default=_DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=_DEFAULT_END_DATE)
    parser.add_argument("--company-limit", type=int, default=1000)
    parser.add_argument(
        "--tests",
        default="all",
        help="Comma-separated deterministic test ids (1-8) or 'all'.",
    )
    parser.add_argument(
        "--scenario-keys",
        default="",
        help="Optional comma-separated scenario keys to run. When set, only matching scenarios are executed.",
    )
    parser.add_argument(
        "--skip-existing-snapshots",
        action="store_true",
        help="Skip scenario snapshot dates that already exist for the scenario portfolio.",
    )
    parser.add_argument(
        "--refresh-market-factors",
        action="store_true",
        help="Refresh market factors before rebuilding snapshots. Defaults to false for restore-based reruns.",
    )
    parser.add_argument(
        "--output-root",
        default=str(_DEFAULT_OUTPUT_ROOT),
        help="Directory for generated scenario configs and summary artifacts.",
    )
    parser.add_argument(
        "--report-output-dir",
        default=None,
        help="Optional override for report output root. Defaults under the sensitivity output root.",
    )
    parser.add_argument(
        "--run-prefix",
        default="cw2_sensitivity",
        help="Prefix for generated backtest run names.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write scenario configs and summary manifests without running snapshots/backtests.",
    )
    parser.add_argument(
        "--fast-summary-only",
        action="store_true",
        help=(
            "Run scenario backtests and summary metrics only. This skips per-scenario "
            "analysis/report bundles so the final requirement/evidence pack can be "
            "built centrally."
        ),
    )
    parser.add_argument(
        "--summary-tag",
        default="",
        help="Optional suffix for manifest/summary artifact names so batch runs do not overwrite each other.",
    )
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


def _baseline_normal_weights(config: Mapping[str, Any]) -> Dict[str, float]:
    regime_cfg = dict((config.get("regime") or {}))
    normal = dict((regime_cfg.get("normal") or {}))
    ordered = {
        "quality": float(normal.get("quality", 0.0)),
        "value": float(normal.get("value", 0.0)),
        "market_technical": float(normal.get("market_technical", 0.0)),
        "sentiment": float(normal.get("sentiment", 0.0)),
        "dividend": float(normal.get("dividend", 0.0)),
    }
    total = sum(ordered.values())
    if total <= 0.0:
        raise ValueError("baseline regime.normal weights are invalid")
    return {key: value / total for key, value in ordered.items()}


def _shift_regime_weight(
    weights: Mapping[str, float],
    factor_name: str,
    delta: float,
) -> Dict[str, float]:
    base = {str(key): float(value) for key, value in weights.items()}
    if factor_name not in base:
        raise KeyError(f"unknown factor weight: {factor_name}")

    current = float(base[factor_name])
    target = current + float(delta)
    if target < 0.0 or target > 1.0:
        raise ValueError(
            f"weight shift infeasible for factor={factor_name} delta={delta}: target={target}"
        )

    other_keys = [key for key in base if key != factor_name]
    other_total = sum(base[key] for key in other_keys)
    if not other_keys:
        return {factor_name: 1.0}
    if other_total <= 0.0 and target < 1.0 - 1e-12:
        raise ValueError("cannot redistribute weight away from a fully concentrated base")

    out: Dict[str, float] = {factor_name: target}
    residual = 1.0 - target
    if other_total <= 0.0:
        share = residual / float(len(other_keys))
        out.update({key: share for key in other_keys})
    else:
        for key in other_keys:
            out[key] = residual * float(base[key]) / float(other_total)

    total = sum(out.values())
    if total <= 0.0:
        raise ValueError("shifted weights collapsed to zero")
    normalized = {key: value / total for key, value in out.items()}
    for key, value in normalized.items():
        if value < -1e-10:
            raise ValueError(f"negative shifted weight for {key}: {value}")
    return normalized


def _scenario_portfolio_name(base_portfolio_name: str, scenario_key: str) -> str:
    base_slug = _slugify(base_portfolio_name)
    scenario_slug = _slugify(scenario_key)
    candidate = f"{base_slug}_{scenario_slug}"
    if len(candidate) <= 50:
        return candidate

    # PostgreSQL feature tables cap portfolio_name at VARCHAR(50), so keep the
    # human-readable prefix short and fall back to the scenario slug when needed.
    compact_prefix = base_slug[:16].rstrip("_") or "cw2"
    compact_candidate = f"{compact_prefix}_{scenario_slug}"
    if len(compact_candidate) <= 50:
        return compact_candidate
    return compact_candidate[:50].rstrip("_")


def _selected_tests(raw_value: str) -> set[str]:
    cleaned = str(raw_value or "all").strip().lower()
    if cleaned in {"all", "*"}:
        return {str(i) for i in range(1, 9)}
    return {
        part.strip()
        for part in cleaned.split(",")
        if part.strip() and part.strip() in {str(i) for i in range(1, 9)}
    }


def _selected_scenario_keys(raw_value: str) -> set[str]:
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return set()
    return {_slugify(part.strip()) for part in cleaned.split(",") if part.strip()}


def _build_test1_cost_scenarios() -> List[ScenarioSpec]:
    return [
        ScenarioSpec(
            test_key="1",
            scenario_key="cost_10bps",
            description="Transaction cost sensitivity at 10 bps.",
            config_override={
                "backtest": {
                    "transaction_cost_bps": 10,
                    "execution": {"fallback_transaction_cost_bps": 10},
                    "intraday_triggers": {"transaction_cost_bps": 10},
                }
            },
        ),
        ScenarioSpec(
            test_key="1",
            scenario_key="cost_15bps_mainline",
            description="Mainline transaction cost at 15 bps.",
            config_override={
                "backtest": {
                    "transaction_cost_bps": 15,
                    "execution": {"fallback_transaction_cost_bps": 15},
                    "intraday_triggers": {"transaction_cost_bps": 15},
                }
            },
        ),
        ScenarioSpec(
            test_key="1",
            scenario_key="cost_25bps",
            description="Transaction cost sensitivity at 25 bps.",
            config_override={
                "backtest": {
                    "transaction_cost_bps": 25,
                    "execution": {"fallback_transaction_cost_bps": 25},
                    "intraday_triggers": {"transaction_cost_bps": 25},
                }
            },
        ),
        ScenarioSpec(
            test_key="1",
            scenario_key="cost_40bps",
            description="Transaction cost sensitivity at 40 bps.",
            config_override={
                "backtest": {
                    "transaction_cost_bps": 40,
                    "execution": {"fallback_transaction_cost_bps": 40},
                    "intraday_triggers": {"transaction_cost_bps": 40},
                }
            },
        ),
    ]


def _build_test2_window_scenarios() -> List[ScenarioSpec]:
    return [
        ScenarioSpec(
            test_key="2",
            scenario_key="window_minus_6m",
            description="Backtest window shifted six months earlier.",
            config_override={"backtest": {"start_date": "2020-10-20"}},
        ),
        ScenarioSpec(
            test_key="2",
            scenario_key="window_minus_3m",
            description="Backtest window shifted three months earlier.",
            config_override={"backtest": {"start_date": "2021-01-20"}},
        ),
        ScenarioSpec(
            test_key="2",
            scenario_key="window_mainline",
            description="Mainline backtest window.",
            config_override={"backtest": {"start_date": "2021-04-20"}},
        ),
        ScenarioSpec(
            test_key="2",
            scenario_key="window_plus_3m",
            description="Backtest window shifted three months later.",
            config_override={"backtest": {"start_date": "2021-07-20"}},
        ),
        ScenarioSpec(
            test_key="2",
            scenario_key="window_plus_6m",
            description="Backtest window shifted six months later.",
            config_override={"backtest": {"start_date": "2021-10-20"}},
        ),
    ]


def _build_test3_concentration_scenarios() -> List[ScenarioSpec]:
    return [
        ScenarioSpec(
            test_key="3",
            scenario_key="concentration_tighter",
            description="More concentrated hybrid selection.",
            config_override={
                "portfolio_construction": {
                    "hybrid_min_n": 20,
                    "hybrid_max_n": 25,
                    "top_pct": 0.08,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="3",
            scenario_key="concentration_mainline",
            description="Mainline hybrid concentration.",
            config_override={
                "portfolio_construction": {
                    "hybrid_min_n": 25,
                    "hybrid_max_n": 35,
                    "top_pct": 0.12,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="3",
            scenario_key="concentration_broader",
            description="More diversified hybrid selection.",
            config_override={
                "portfolio_construction": {
                    "hybrid_min_n": 30,
                    "hybrid_max_n": 45,
                    "top_pct": 0.15,
                }
            },
            requires_snapshot_refresh=True,
        ),
    ]


def _build_test4_factor_weight_scenarios(
    baseline_weights: Mapping[str, float],
) -> List[ScenarioSpec]:
    key_factors = ("quality", "value")
    scenarios: List[ScenarioSpec] = [
        ScenarioSpec(
            test_key="4",
            scenario_key="factor_equal_weight",
            description="Equal-weight normal regime control.",
            config_override={
                "regime": {
                    "normal": {
                        "quality": 0.20,
                        "value": 0.20,
                        "market_technical": 0.20,
                        "sentiment": 0.20,
                        "dividend": 0.20,
                    }
                }
            },
            requires_snapshot_refresh=True,
        )
    ]
    for factor_name in key_factors:
        if factor_name not in baseline_weights:
            continue
        for direction, delta in (("up", 0.05), ("down", -0.05)):
            try:
                shifted = _shift_regime_weight(baseline_weights, factor_name, delta)
            except ValueError:
                continue
            scenarios.append(
                ScenarioSpec(
                    test_key="4",
                    scenario_key=f"factor_{factor_name}_{direction}_5pct",
                    description=(
                        f"Key tuned Test 4 check: normal-regime {factor_name} weight shifted "
                        f"{'up' if delta > 0 else 'down'} by 5 percentage points."
                    ),
                    config_override={"regime": {"normal": shifted}},
                    requires_snapshot_refresh=True,
                )
            )
    return scenarios


def _build_test5_regime_scenarios(
    baseline_weights: Mapping[str, float],
) -> List[ScenarioSpec]:
    return [
        ScenarioSpec(
            test_key="5",
            scenario_key="regime_more_sensitive",
            description="Lower stress and exit thresholds for regime switching.",
            config_override={
                "regime": {
                    "vix_stress_threshold": 20,
                    "vix_exit_threshold": 18,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="5",
            scenario_key="regime_mainline",
            description="Mainline regime thresholds.",
            config_override={
                "regime": {
                    "vix_stress_threshold": 22,
                    "vix_exit_threshold": 20,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="5",
            scenario_key="regime_less_sensitive",
            description="Higher stress and exit thresholds for regime switching.",
            config_override={
                "regime": {
                    "vix_stress_threshold": 25,
                    "vix_exit_threshold": 22,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="5",
            scenario_key="regime_disabled",
            description="No regime switching; stress weights forced to normal.",
            config_override={
                "regime": {
                    "stress": dict(baseline_weights),
                    "vix_stress_threshold": 999.0,
                    "vix_exit_threshold": 998.0,
                }
            },
            requires_snapshot_refresh=True,
        ),
    ]


def _build_test6_brake_scenarios() -> List[ScenarioSpec]:
    return [
        ScenarioSpec(
            test_key="6",
            scenario_key="brake_off",
            description="Drawdown brake disabled.",
            config_override={"backtest": {"drawdown_brake": {"enabled": False}}},
        ),
        ScenarioSpec(
            test_key="6",
            scenario_key="brake_mild",
            description="Mild drawdown brake.",
            config_override={
                "backtest": {
                    "drawdown_brake": {
                        "enabled": True,
                        "threshold_pct": 0.12,
                        "recovery_drawdown_pct": 0.06,
                        "de_risk_fraction": 0.25,
                    }
                }
            },
        ),
        ScenarioSpec(
            test_key="6",
            scenario_key="brake_mainline",
            description="Mainline drawdown brake.",
            config_override={
                "backtest": {
                    "drawdown_brake": {
                        "enabled": True,
                        "threshold_pct": 0.12,
                        "recovery_drawdown_pct": 0.06,
                        "de_risk_fraction": 0.50,
                    }
                }
            },
        ),
        ScenarioSpec(
            test_key="6",
            scenario_key="brake_staircase",
            description="Staircase drawdown brake with hysteresis.",
            config_override={
                "backtest": {
                    "drawdown_brake": {
                        "enabled": True,
                        "threshold_pct": 0.08,
                        "recovery_drawdown_pct": 0.06,
                        "de_risk_fraction": 0.15,
                        "staged_thresholds_pct": [0.08, 0.12, 0.16],
                        "staged_de_risk_fractions": [0.15, 0.30, 0.50],
                    }
                }
            },
        ),
        ScenarioSpec(
            test_key="6",
            scenario_key="brake_aggressive",
            description="Aggressive drawdown brake.",
            config_override={
                "backtest": {
                    "drawdown_brake": {
                        "enabled": True,
                        "threshold_pct": 0.10,
                        "recovery_drawdown_pct": 0.06,
                        "de_risk_fraction": 0.75,
                    }
                }
            },
        ),
    ]


def _build_test7_band_scenarios() -> List[ScenarioSpec]:
    return [
        ScenarioSpec(
            test_key="7",
            scenario_key="band_none",
            description="No incumbent banding.",
            config_override={
                "portfolio_construction": {
                    "hybrid_min_n": 35,
                    "hybrid_max_n": 35,
                    "incumbent_exit_rank": 35,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="7",
            scenario_key="band_narrow",
            description="Narrow incumbent exit band.",
            config_override={
                "portfolio_construction": {
                    "hybrid_min_n": 25,
                    "hybrid_max_n": 25,
                    "incumbent_exit_rank": 35,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="7",
            scenario_key="band_medium",
            description="Medium incumbent exit band.",
            config_override={
                "portfolio_construction": {
                    "hybrid_min_n": 25,
                    "hybrid_max_n": 25,
                    "incumbent_exit_rank": 50,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="7",
            scenario_key="band_wide",
            description="Wide incumbent exit band.",
            config_override={
                "portfolio_construction": {
                    "hybrid_min_n": 25,
                    "hybrid_max_n": 25,
                    "incumbent_exit_rank": 60,
                }
            },
            requires_snapshot_refresh=True,
        ),
    ]


def _build_test8_trade_constraint_scenarios() -> List[ScenarioSpec]:
    return [
        ScenarioSpec(
            test_key="8",
            scenario_key="trade_constraint_none",
            description="No no-trade band and no per-name trade cap.",
            config_override={
                "portfolio_construction": {
                    "no_trade_band_weight": 0.0,
                    "per_name_max_trade_weight": 1.0,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="8",
            scenario_key="trade_constraint_weak",
            description="Weak no-trade band and per-name trade cap.",
            config_override={
                "portfolio_construction": {
                    "no_trade_band_weight": 0.005,
                    "per_name_max_trade_weight": 0.05,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="8",
            scenario_key="trade_constraint_medium",
            description="Medium no-trade band and per-name trade cap.",
            config_override={
                "portfolio_construction": {
                    "no_trade_band_weight": 0.01,
                    "per_name_max_trade_weight": 0.04,
                }
            },
            requires_snapshot_refresh=True,
        ),
        ScenarioSpec(
            test_key="8",
            scenario_key="trade_constraint_strong",
            description="Strong no-trade band and per-name trade cap.",
            config_override={
                "portfolio_construction": {
                    "no_trade_band_weight": 0.02,
                    "per_name_max_trade_weight": 0.03,
                }
            },
            requires_snapshot_refresh=True,
        ),
    ]


def build_deterministic_scenarios(base_config: Mapping[str, Any]) -> List[ScenarioSpec]:
    baseline_weights = _baseline_normal_weights(base_config)
    scenarios: List[ScenarioSpec] = []
    scenarios.extend(_build_test1_cost_scenarios())
    scenarios.extend(_build_test2_window_scenarios())
    scenarios.extend(_build_test3_concentration_scenarios())
    scenarios.extend(_build_test4_factor_weight_scenarios(baseline_weights))
    scenarios.extend(_build_test5_regime_scenarios(baseline_weights))
    scenarios.extend(_build_test6_brake_scenarios())
    scenarios.extend(_build_test7_band_scenarios())
    scenarios.extend(_build_test8_trade_constraint_scenarios())
    return scenarios


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(dict(payload), fh, sort_keys=False)


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
        results.append(
            {
                "as_of_date": as_of_date.isoformat(),
                "status": "processed",
                **summary,
            }
        )

    return {
        "portfolio_name": portfolio_name,
        "symbol_count": len(symbols),
        "quarter_end_count": len(quarter_ends),
        "processed_count": processed,
        "skipped_existing_count": skipped,
        "results": results,
    }


def _load_metric_map(run_id: str) -> Dict[str, float]:
    engine = get_db_engine()
    sql = text(f"""
        SELECT metric_group, metric_name, metric_value
        FROM {_SCHEMA}.backtest_metrics
        WHERE run_id = :run_id
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    return {
        f"{row['metric_group']}.{row['metric_name']}": float(row["metric_value"])
        for row in rows
        if row.get("metric_value") is not None
    }


def _load_relative_metric_map(run_id: str) -> Dict[str, float]:
    engine = get_db_engine()
    sql = text(f"""
        SELECT versus_series, metric_name, metric_value
        FROM {_SCHEMA}.backtest_relative_metrics
        WHERE run_id = :run_id
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    return {
        f"{row['versus_series']}.{row['metric_name']}": float(row["metric_value"])
        for row in rows
        if row.get("metric_value") is not None
    } or _compute_relative_metric_map(run_id)


def _annualized_return_from_decimal(values: Sequence[float]) -> Optional[float]:
    series = pd.Series(list(values), dtype=float).dropna()
    if series.empty:
        return None
    total = float((1.0 + series).prod())
    if total <= 0.0:
        return -100.0
    return float((total ** (12.0 / float(len(series))) - 1.0) * 100.0)


def _max_drawdown_from_decimal(values: Sequence[float]) -> Optional[float]:
    series = pd.Series(list(values), dtype=float).dropna()
    if series.empty:
        return None
    nav = (1.0 + series).cumprod()
    peak = nav.cummax()
    return float((nav / peak - 1.0).min() * 100.0)


def _compute_relative_metric_map(run_id: str) -> Dict[str, float]:
    """Fallback for fast reruns that skip the heavier analysis writer."""
    engine = get_db_engine()
    perf_sql = text(f"""
        SELECT period_end_date, net_return
        FROM {_SCHEMA}.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    bench_sql = text(f"""
        SELECT period_end_date, series_name, period_return
        FROM {_SCHEMA}.backtest_benchmark_nav
        WHERE run_id = :run_id
        ORDER BY period_end_date, series_name
        """)
    with engine.connect() as conn:
        perf = pd.read_sql(perf_sql, conn, params={"run_id": run_id})
        bench = pd.read_sql(bench_sql, conn, params={"run_id": run_id})
        if bench.empty:
            bench = pd.read_sql(
                bench_sql,
                conn,
                params={"run_id": _DEFAULT_BASELINE_RUN_ID},
            )
    if perf.empty or bench.empty:
        return {}
    perf["period_end_date"] = pd.to_datetime(perf["period_end_date"])
    perf["net_return"] = pd.to_numeric(perf["net_return"], errors="coerce")
    bench["period_end_date"] = pd.to_datetime(bench["period_end_date"])
    bench["period_return"] = pd.to_numeric(bench["period_return"], errors="coerce")
    strategy_ann = _annualized_return_from_decimal(perf["net_return"])
    strategy_total = float(((1.0 + perf["net_return"].dropna()).prod() - 1.0) * 100.0)
    strategy_dd = _max_drawdown_from_decimal(perf["net_return"])
    out: Dict[str, float] = {}
    for series_name, group in bench.groupby("series_name"):
        merged = perf.merge(
            group[["period_end_date", "period_return"]],
            on="period_end_date",
            how="inner",
        )
        if merged.empty:
            continue
        benchmark_returns = pd.to_numeric(merged["period_return"], errors="coerce")
        strategy_returns = pd.to_numeric(merged["net_return"], errors="coerce")
        benchmark_ann = _annualized_return_from_decimal(benchmark_returns)
        benchmark_total = float(((1.0 + benchmark_returns.dropna()).prod() - 1.0) * 100.0)
        benchmark_dd = _max_drawdown_from_decimal(benchmark_returns)
        excess = strategy_returns - benchmark_returns
        tracking_error = (
            float(excess.dropna().std(ddof=1) * (12.0**0.5) * 100.0)
            if len(excess.dropna()) > 1
            else None
        )
        prefix = str(series_name)
        if strategy_ann is not None and benchmark_ann is not None:
            out[f"{prefix}.excess_return_annualized"] = float(strategy_ann - benchmark_ann)
        out[f"{prefix}.excess_return_total"] = float(strategy_total - benchmark_total)
        if tracking_error not in (None, 0.0):
            out[f"{prefix}.tracking_error"] = tracking_error
            if strategy_ann is not None and benchmark_ann is not None:
                out[f"{prefix}.information_ratio"] = float(
                    (strategy_ann - benchmark_ann) / tracking_error
                )
        if strategy_dd is not None and benchmark_dd is not None:
            out[f"{prefix}.max_drawdown_delta"] = float(strategy_dd - benchmark_dd)
        valid = pd.concat([strategy_returns, benchmark_returns], axis=1).dropna()
        if not valid.empty:
            out[f"{prefix}.hit_rate"] = float((valid.iloc[:, 0] > valid.iloc[:, 1]).mean() * 100.0)
    return out


def _load_regime_metric_map(run_id: str) -> Dict[str, float]:
    engine = get_db_engine()
    sql = text(f"""
        SELECT regime, versus_series, excess_ann_return, strategy_max_dd, hit_rate
        FROM {_SCHEMA}.backtest_regime_attribution
        WHERE run_id = :run_id
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    out: Dict[str, float] = {}
    for row in rows:
        prefix = f"{row['regime']}.{row['versus_series']}"
        for column in ("excess_ann_return", "strategy_max_dd", "hit_rate"):
            if row.get(column) is not None:
                out[f"{prefix}.{column}"] = float(row[column])
    return out or _compute_regime_metric_map(run_id)


def _compute_regime_metric_map(run_id: str) -> Dict[str, float]:
    engine = get_db_engine()
    perf_sql = text(f"""
        SELECT period_end_date, net_return, regime
        FROM {_SCHEMA}.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    bench_sql = text(f"""
        SELECT period_end_date, series_name, period_return
        FROM {_SCHEMA}.backtest_benchmark_nav
        WHERE run_id = :run_id
        ORDER BY period_end_date, series_name
        """)
    with engine.connect() as conn:
        perf = pd.read_sql(perf_sql, conn, params={"run_id": run_id})
        bench = pd.read_sql(bench_sql, conn, params={"run_id": run_id})
        if bench.empty:
            bench = pd.read_sql(
                bench_sql,
                conn,
                params={"run_id": _DEFAULT_BASELINE_RUN_ID},
            )
    if perf.empty or bench.empty:
        return {}
    perf["period_end_date"] = pd.to_datetime(perf["period_end_date"])
    perf["net_return"] = pd.to_numeric(perf["net_return"], errors="coerce")
    bench["period_end_date"] = pd.to_datetime(bench["period_end_date"])
    bench["period_return"] = pd.to_numeric(bench["period_return"], errors="coerce")
    out: Dict[str, float] = {}
    for (regime, series_name), group in perf.merge(
        bench[["period_end_date", "series_name", "period_return"]],
        on="period_end_date",
        how="inner",
    ).groupby(["regime", "series_name"]):
        strategy_returns = pd.to_numeric(group["net_return"], errors="coerce")
        benchmark_returns = pd.to_numeric(group["period_return"], errors="coerce")
        strategy_ann = _annualized_return_from_decimal(strategy_returns)
        benchmark_ann = _annualized_return_from_decimal(benchmark_returns)
        prefix = f"{regime}.{series_name}"
        if strategy_ann is not None and benchmark_ann is not None:
            out[f"{prefix}.excess_ann_return"] = float(strategy_ann - benchmark_ann)
        strategy_dd = _max_drawdown_from_decimal(strategy_returns)
        if strategy_dd is not None:
            out[f"{prefix}.strategy_max_dd"] = float(strategy_dd)
        valid = pd.concat([strategy_returns, benchmark_returns], axis=1).dropna()
        if not valid.empty:
            out[f"{prefix}.hit_rate"] = float((valid.iloc[:, 0] > valid.iloc[:, 1]).mean() * 100.0)
    return out


def _load_brake_stats(run_id: str) -> Dict[str, Any]:
    engine = get_db_engine()
    sql = text(f"""
        SELECT period_end_date, drawdown_brake_active, drawdown_brake_fraction
        FROM {_SCHEMA}.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    active_rows = [row for row in rows if bool(row.get("drawdown_brake_active"))]
    return {
        "drawdown_brake_trigger_count": len(active_rows),
        "drawdown_brake_trigger_months": [str(row["period_end_date"]) for row in active_rows],
        "drawdown_brake_avg_fraction": (
            float(
                sum(float(row.get("drawdown_brake_fraction") or 0.0) for row in active_rows)
                / float(len(active_rows))
            )
            if active_rows
            else 0.0
        ),
    }


def _scenario_summary_record(
    *,
    spec: ScenarioSpec,
    run_id: str,
    run_name: str,
    report_output: Optional[Mapping[str, Any]],
    config_path: Path,
    portfolio_name: Optional[str],
) -> Dict[str, Any]:
    metric_map = _load_metric_map(run_id)
    relative_map = _load_relative_metric_map(run_id)
    regime_map = _load_regime_metric_map(run_id)
    brake_stats = _load_brake_stats(run_id) if spec.test_key == "6" else {}

    return {
        "test_key": spec.test_key,
        "scenario_key": spec.scenario_key,
        "description": spec.description,
        "run_id": run_id,
        "run_name": run_name,
        "config_path": str(config_path),
        "portfolio_name": portfolio_name,
        "report_output_dir": (
            str(report_output.get("output_dir")) if report_output is not None else None
        ),
        "return.annualized_return": metric_map.get("return.annualized_return"),
        "return.gross_annualized_return": metric_map.get("return.gross_annualized_return"),
        "portfolio.total_cost_drag": metric_map.get("portfolio.total_cost_drag"),
        "risk_adjusted.sharpe_ratio": metric_map.get("risk_adjusted.sharpe_ratio"),
        "risk.max_drawdown": metric_map.get("risk.max_drawdown"),
        "risk.annualized_volatility": metric_map.get("risk.annualized_volatility"),
        "portfolio.avg_holdings": metric_map.get("portfolio.avg_holdings"),
        "portfolio.avg_monthly_recorded_turnover": metric_map.get("portfolio.avg_monthly_turnover"),
        "portfolio.annualized_turnover_ratio": metric_map.get(
            "portfolio.annualized_turnover_ratio"
        ),
        "static_baseline.excess_return_annualized": relative_map.get(
            "static_baseline.excess_return_annualized"
        ),
        "static_baseline.excess_return_total": relative_map.get(
            "static_baseline.excess_return_total"
        ),
        "stress.static_baseline.excess_ann_return": regime_map.get(
            "stress.static_baseline.excess_ann_return"
        ),
        "stress.universe_ew.excess_ann_return": regime_map.get(
            "stress.universe_ew.excess_ann_return"
        ),
        **brake_stats,
    }


def _scenario_run_name(prefix: str, spec: ScenarioSpec) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{spec.test_key}_{_slugify(spec.scenario_key)}_{ts}"


def _scenario_report_name(run_name: str) -> str:
    return f"{run_name}_report"


def _artifact_path(directory: Path, stem: str, suffix: str, tag: str) -> Path:
    cleaned = _slugify(tag) if str(tag or "").strip() else ""
    filename = f"{stem}_{cleaned}{suffix}" if cleaned else f"{stem}{suffix}"
    return directory / filename


def _summaries_to_markdown(records: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Deterministic Sensitivity Summary",
        "",
        "| Test | Scenario | Annualized Return | Sharpe | Max Drawdown | Avg Monthly Recorded Turnover |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in records:
        ann_return = item.get("return.annualized_return")
        sharpe = item.get("risk_adjusted.sharpe_ratio")
        max_dd = item.get("risk.max_drawdown")
        turnover = item.get("portfolio.avg_monthly_recorded_turnover")
        lines.append(
            "| {test_key} | {scenario_key} | {ann_return} | {sharpe} | {max_dd} | {turnover} |".format(
                test_key=item.get("test_key"),
                scenario_key=item.get("scenario_key"),
                ann_return=(
                    f"{float(ann_return):.3f}%"
                    if ann_return is not None and pd.notna(ann_return)
                    else "NA"
                ),
                sharpe=(
                    f"{float(sharpe):.3f}" if sharpe is not None and pd.notna(sharpe) else "NA"
                ),
                max_dd=(
                    f"{float(max_dd):.3f}%" if max_dd is not None and pd.notna(max_dd) else "NA"
                ),
                turnover=(
                    f"{float(turnover):.3f}%"
                    if turnover is not None and pd.notna(turnover)
                    else "NA"
                ),
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = build_parser().parse_args()
    load_env_layers()

    start_date = date.fromisoformat(str(args.start_date))
    end_date = date.fromisoformat(str(args.end_date))
    output_root = Path(str(args.output_root)).resolve()
    report_root = (
        Path(str(args.report_output_dir)).resolve()
        if args.report_output_dir
        else (output_root / "reports")
    )
    config_output_root = output_root / "configs"
    summary_output_root = output_root / "summaries"
    base_config_path = Path(str(args.cw2_config)).resolve()
    base_config = load_yaml(str(base_config_path))
    base_portfolio_name = _baseline_portfolio_name(base_config)

    selected = _selected_tests(str(args.tests))
    selected_scenarios = _selected_scenario_keys(str(args.scenario_keys))
    scenarios = [
        spec
        for spec in build_deterministic_scenarios(base_config)
        if spec.test_key in selected
        and (not selected_scenarios or _slugify(spec.scenario_key) in selected_scenarios)
    ]
    if not scenarios:
        raise ValueError("no deterministic sensitivity scenarios selected")

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

        scenario_config_path = config_output_root / f"{spec.test_key}_{spec.scenario_key}.yaml"
        _write_yaml(scenario_config_path, merged_config)

        record: Dict[str, Any] = {
            "test_key": spec.test_key,
            "scenario_key": spec.scenario_key,
            "description": spec.description,
            "config_path": str(scenario_config_path),
            "requires_snapshot_refresh": spec.requires_snapshot_refresh,
            "portfolio_name": scenario_portfolio_name,
        }

        if args.dry_run:
            manifest.append(record)
            continue

        snapshot_summary = None
        if spec.requires_snapshot_refresh:
            snapshot_summary = _materialize_scenario_snapshots(
                cw1_config_path=str(args.cw1_config),
                cw2_config_path=str(scenario_config_path),
                start_date=start_date,
                end_date=end_date,
                company_limit=int(args.company_limit),
                skip_existing=bool(args.skip_existing_snapshots),
            )
            record["snapshot_summary"] = snapshot_summary

        run_name = _scenario_run_name(str(args.run_prefix), spec)
        run_id = run_backtest_from_config(
            run_name=run_name,
            config_path=str(scenario_config_path),
        )
        if args.fast_summary_only:
            analysis_output = {"skipped": True, "reason": "fast_summary_only"}
            report_output = None
        else:
            analysis_output = run_analysis_from_config(
                run_id=run_id,
                config_path=str(scenario_config_path),
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
        "deterministic_sensitivity_manifest",
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
            "deterministic_sensitivity_summary",
            ".csv",
            str(args.summary_tag),
        )
        summary_md = _artifact_path(
            summary_output_root,
            "deterministic_sensitivity_summary",
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
            "scenario_count": len(manifest),
            "tests_selected": sorted(selected),
            "scenario_keys_selected": sorted(selected_scenarios),
            "dry_run": bool(args.dry_run),
            "manifest_path": str(summary_json),
            "csv_path": (str(summary_csv) if summary_csv is not None else None),
            "markdown_path": (str(summary_md) if summary_md is not None else None),
            "scenarios": manifest,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
