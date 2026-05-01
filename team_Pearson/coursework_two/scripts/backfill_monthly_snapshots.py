from __future__ import annotations

"""Backfill missing CW2 month-end snapshots from already-materialized upstream data.

Month-end snapshots remain the storage and audit anchor even when the active
target-generation cadence is less frequent. In those off-cycle months, the
downstream CW2 feature pipeline may carry forward the previous target set
instead of refreshing a new rebalance.
"""

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
for path in (str(CW1_ROOT), str(REPO_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.modules.ops.runtime_control import (  # noqa: E402
    build_runtime_context_snapshot,
    build_runtime_metrics_snapshot,
    emit_scheduler_stage_event,
    merge_stage_context,
    record_runtime_quality_snapshot,
    record_scheduler_pipeline_state,
    record_scheduler_stage_state,
    runtime_lock,
)
from team_Pearson.coursework_two.modules.utils.config_contract import (  # noqa: E402
    validate_shared_runtime_contract,
)
from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    coerce_bool,
    coerce_optional_int,
    default_cw1_config,
    default_cw2_config,
    existing_portfolio_target_count,
    load_env_layers,
    load_scheduler_symbols,
    load_yaml,
    month_end_trading_days,
    print_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill missing CW2 month-end snapshots, honoring the configured "
            "target-generation cadence for refresh vs carry-forward behavior."
        )
    )
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=default_cw2_config())
    parser.add_argument("--company-limit", default=None)
    parser.add_argument(
        "--skip-existing",
        default="true",
        help=(
            "true/false. Skip month-end snapshot dates that already have "
            "portfolio_target_positions."
        ),
    )
    parser.add_argument(
        "--refresh-market-factors",
        default="true",
        help="true/false. Recompute historical market_factors across the requested window before CW2 snapshot backfill.",
    )
    parser.add_argument("--context-path", default=None)
    parser.add_argument("--pipeline-name", default="cw2_monthly_snapshot_backfill")
    parser.add_argument("--runtime-lock-ttl-seconds", type=int, default=6 * 60 * 60)
    return parser


def _market_factor_dependencies() -> tuple[Any, Any, Any]:
    from team_Pearson.coursework_one.modules.output.load import load_curated
    from team_Pearson.coursework_one.modules.output.normalize import normalize_records
    from team_Pearson.coursework_one.modules.transform.market_factors import build_market_factors

    return build_market_factors, normalize_records, load_curated


def _cw2_feature_builder() -> Any:
    from team_Pearson.coursework_one.modules.transform.cw2_features import (
        build_and_load_cw2_features,
    )

    return build_and_load_cw2_features


def _portfolio_name_from_cw2_config(cw2_cfg: Dict[str, Any]) -> str:
    portfolio_cfg = dict(cw2_cfg.get("portfolio_construction") or {})
    backtest_cfg = dict(cw2_cfg.get("backtest") or {})
    return str(
        portfolio_cfg.get("portfolio_name")
        or backtest_cfg.get("portfolio_name")
        or "cw2_core_equity"
    )


def _materialize_market_factor_history(
    *,
    start_date: date,
    end_date: date,
    symbols: list[str],
    cw1_config_path: str,
) -> Dict[str, Any]:
    load_env_layers()
    cw1_cfg = load_yaml(cw1_config_path)
    benchmark_ticker = (
        str(((cw1_cfg.get("market_factors") or {}).get("benchmark_ticker")) or "SPY").strip()
        or "SPY"
    )
    build_market_factors, normalize_records, load_curated = _market_factor_dependencies()

    if not symbols:
        return {
            "computed_rows": 0,
            "loaded_rows": 0,
            "benchmark_ticker": benchmark_ticker,
            "stats": {},
        }

    records = build_market_factors(
        symbols,
        start_date=start_date,
        end_date=end_date,
        output_frequency="daily",
        benchmark_ticker=benchmark_ticker,
    )
    normalized = normalize_records(records)
    stats: Dict[str, int] = {}
    loaded_rows = int(load_curated(normalized, dry_run=False, stats_out=stats))
    return {
        "computed_rows": len(normalized),
        "loaded_rows": loaded_rows,
        "benchmark_ticker": benchmark_ticker,
        "stats": stats,
    }


def main() -> int:
    args = build_parser().parse_args()
    load_env_layers()
    start_date = date.fromisoformat(str(args.start_date))
    end_date = date.fromisoformat(str(args.end_date))
    skip_existing = coerce_bool(args.skip_existing, default=True)
    refresh_market_factors = coerce_bool(args.refresh_market_factors, default=True)
    company_limit = coerce_optional_int(args.company_limit)
    build_and_load_cw2_features = _cw2_feature_builder()
    cw1_cfg = load_yaml(str(args.cw1_config))
    cw2_cfg = load_yaml(str(args.cw2_config))
    engine = get_db_engine()
    contract = validate_shared_runtime_contract(
        cw1_cfg,
        cw2_cfg,
    )
    portfolio_name = _portfolio_name_from_cw2_config(cw2_cfg)
    pipeline_name = (
        str(getattr(args, "pipeline_name", "") or "cw2_monthly_snapshot_backfill").strip()
        or "cw2_monthly_snapshot_backfill"
    )
    execution_key = (
        f"{pipeline_name}:{portfolio_name}:{start_date.isoformat()}:"
        f"{end_date.isoformat()}:{company_limit or 'full'}"
    )
    lock_name = f"cw2:monthly_snapshot_backfill:{portfolio_name}:{start_date.isoformat()}:{end_date.isoformat()}"

    with runtime_lock(
        lock_name=lock_name,
        ttl_seconds=int(args.runtime_lock_ttl_seconds),
        raise_on_locked=True,
    ) as lock_handle:
        started_at = datetime.now(timezone.utc)
        start_payload = {
            "pipeline_name": pipeline_name,
            "portfolio_name": portfolio_name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "company_limit": company_limit,
            "refresh_market_factors": refresh_market_factors,
            "context_path": str(args.context_path or ""),
            "lock_name": lock_name,
        }
        record_scheduler_pipeline_state(
            engine=engine,
            pipeline_name=pipeline_name,
            execution_key=execution_key,
            status="running",
            stage_name="monthly_snapshot_backfill",
            started_at=started_at,
            context=start_payload,
        )
        record_scheduler_stage_state(
            engine=engine,
            pipeline_name=pipeline_name,
            stage_name="monthly_snapshot_backfill",
            execution_key=execution_key,
            stage_status="started",
            stage_order=10,
            started_at=started_at,
            lock_handle=lock_handle,
            lock_name=lock_name,
            idempotency_key=f"{pipeline_name}:{execution_key}:started",
            payload=start_payload,
        )
        emit_scheduler_stage_event(
            cw2_cfg,
            engine=engine,
            producer_component="cw2.scheduler.monthly_snapshot_backfill",
            stage_name="monthly_snapshot_backfill",
            stage_status="started",
            execution_key=execution_key,
            payload=start_payload,
        )
        try:
            symbols = load_scheduler_symbols(
                company_limit=company_limit,
                cw1_config_path=str(args.cw1_config),
                as_of_date=end_date,
            )
            market_factor_backfill = None
            if refresh_market_factors:
                market_factor_backfill = _materialize_market_factor_history(
                    start_date=start_date,
                    end_date=end_date,
                    symbols=symbols,
                    cw1_config_path=str(args.cw1_config),
                )
            month_ends = month_end_trading_days(
                start_date=start_date,
                end_date=end_date,
                cw2_config_path=str(args.cw2_config),
            )

            results = []
            processed = 0
            skipped = 0
            for as_of_date in month_ends:
                existing_count = existing_portfolio_target_count(
                    as_of_date=as_of_date,
                    portfolio_name=portfolio_name,
                )
                if skip_existing and existing_count > 0:
                    skipped += 1
                    results.append(
                        {
                            "as_of_date": as_of_date.isoformat(),
                            "status": "skipped_existing",
                            "existing_positions": existing_count,
                        }
                    )
                    continue

                summary = build_and_load_cw2_features(
                    run_date=as_of_date.isoformat(),
                    symbols=symbols,
                    config_path=str(args.cw2_config),
                )
                processed += 1
                results.append(
                    {
                        "as_of_date": as_of_date.isoformat(),
                        "status": "processed",
                        **summary,
                    }
                )

            payload = {
                "config_contract": contract,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "portfolio_name": portfolio_name,
                "symbol_count": len(symbols),
                "market_factor_backfill": market_factor_backfill,
                "month_end_count": len(month_ends),
                "processed_count": processed,
                "refresh_market_factors": refresh_market_factors,
                "skipped_existing_count": skipped,
                "results": results,
            }
            context_path = str(args.context_path or "").strip() or None
            merged_context = merge_stage_context(
                context_path,
                {
                    "monthly_snapshot_backfill": {
                        "portfolio_name": portfolio_name,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "processed_count": processed,
                        "skipped_existing_count": skipped,
                        "symbol_count": len(symbols),
                    }
                },
            )
            finished_at = datetime.now(timezone.utc)
            record_runtime_quality_snapshot(
                engine=engine,
                stage_name="cw2_monthly_snapshot_backfill",
                execution_key=execution_key,
                run_date=end_date,
                passed=True,
                warnings=[],
                row_count=processed,
                extra={
                    "portfolio_name": portfolio_name,
                    "month_end_count": len(month_ends),
                    "skipped_existing_count": skipped,
                    "refresh_market_factors": refresh_market_factors,
                },
            )
            record_scheduler_stage_state(
                engine=engine,
                pipeline_name=pipeline_name,
                stage_name="monthly_snapshot_backfill",
                execution_key=execution_key,
                stage_status="completed",
                stage_order=10,
                started_at=started_at,
                completed_at=finished_at,
                lock_handle=lock_handle,
                lock_name=lock_name,
                idempotency_key=f"{pipeline_name}:{execution_key}:completed",
                payload=start_payload,
                result={
                    "processed_count": processed,
                    "skipped_existing_count": skipped,
                    "symbol_count": len(symbols),
                },
            )
            record_scheduler_pipeline_state(
                engine=engine,
                pipeline_name=pipeline_name,
                execution_key=execution_key,
                status="completed",
                stage_name="monthly_snapshot_backfill",
                started_at=started_at,
                completed_at=finished_at,
                context=build_runtime_context_snapshot(
                    merged_context,
                    context_path=context_path,
                    stage_name="monthly_snapshot_backfill",
                    extra={
                        "pipeline_name": pipeline_name,
                        "portfolio_name": portfolio_name,
                    },
                ),
                metrics=build_runtime_metrics_snapshot(
                    payload,
                    extra={"stage_status": "completed"},
                ),
            )
            emit_scheduler_stage_event(
                cw2_cfg,
                engine=engine,
                producer_component="cw2.scheduler.monthly_snapshot_backfill",
                stage_name="monthly_snapshot_backfill",
                stage_status="completed",
                execution_key=execution_key,
                payload={
                    "pipeline_name": pipeline_name,
                    "portfolio_name": portfolio_name,
                    "processed_count": processed,
                    "skipped_existing_count": skipped,
                    "symbol_count": len(symbols),
                },
            )
            print_json(payload)
            return 0
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            record_runtime_quality_snapshot(
                engine=engine,
                stage_name="cw2_monthly_snapshot_backfill",
                execution_key=execution_key,
                run_date=end_date,
                passed=False,
                failures=[str(exc)],
                row_count=0,
                extra={"portfolio_name": portfolio_name},
            )
            record_scheduler_stage_state(
                engine=engine,
                pipeline_name=pipeline_name,
                stage_name="monthly_snapshot_backfill",
                execution_key=execution_key,
                stage_status="failed",
                stage_order=10,
                started_at=started_at,
                completed_at=finished_at,
                lock_handle=lock_handle,
                lock_name=lock_name,
                idempotency_key=f"{pipeline_name}:{execution_key}:failed",
                payload=start_payload,
                error_text=str(exc),
            )
            record_scheduler_pipeline_state(
                engine=engine,
                pipeline_name=pipeline_name,
                execution_key=execution_key,
                status="failed",
                stage_name="monthly_snapshot_backfill",
                started_at=started_at,
                completed_at=finished_at,
                context=build_runtime_context_snapshot(
                    {
                        **start_payload,
                        "monthly_snapshot_backfill": {
                            "portfolio_name": portfolio_name,
                            "start_date": start_date.isoformat(),
                            "end_date": end_date.isoformat(),
                        },
                    },
                    context_path=str(args.context_path or "").strip() or None,
                    stage_name="monthly_snapshot_backfill",
                    extra={"pipeline_name": pipeline_name, "error_text": str(exc)},
                ),
                metrics=build_runtime_metrics_snapshot(
                    {},
                    extra={"stage_status": "failed"},
                ),
                error_text=str(exc),
            )
            emit_scheduler_stage_event(
                cw2_cfg,
                engine=engine,
                producer_component="cw2.scheduler.monthly_snapshot_backfill",
                stage_name="monthly_snapshot_backfill",
                stage_status="failed",
                execution_key=execution_key,
                severity="critical",
                payload={
                    "pipeline_name": pipeline_name,
                    "portfolio_name": portfolio_name,
                    "error_text": str(exc),
                },
            )
            raise


if __name__ == "__main__":
    raise SystemExit(main())
