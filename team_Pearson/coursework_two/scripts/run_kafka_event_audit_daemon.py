from __future__ import annotations

"""Dedicated long-running Kafka audit consumer for CW2 event topics."""

import argparse
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.modules.ops.runtime_control import (  # noqa: E402
    acquire_runtime_lock,
    release_runtime_lock,
)
from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    default_cw1_config,
    default_cw2_config,
    load_env_layers,
    print_json,
)
from team_Pearson.coursework_two.scripts.run_kafka_event_audit import run_audit_cycle  # noqa: E402

_STOP_EVENT = threading.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    print_json(
        {
            "status": "stopping",
            "signal": signum,
            "stopped_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    _STOP_EVENT.set()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CW2 Kafka audit consumer as a dedicated daemon."
    )
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=default_cw2_config())
    parser.add_argument("--pipeline-name", default="cw2_kafka_audit_consumer")
    parser.add_argument("--stage-name", default="consume_and_audit")
    parser.add_argument("--poll-interval-seconds", type=int, default=30)
    parser.add_argument("--max-messages", type=int, default=200)
    parser.add_argument("--poll-timeout-ms", type=int, default=1000)
    parser.add_argument("--max-idle-polls", type=int, default=10)
    parser.add_argument("--runtime-lock-name", default="cw2_kafka_audit_consumer")
    parser.add_argument("--runtime-lock-ttl-seconds", type=int, default=300)
    parser.add_argument("--once", action="store_true")
    return parser


def _register_signal_handlers() -> None:
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_signal)


def main() -> int:
    args = build_parser().parse_args()
    _STOP_EVENT.clear()
    load_env_layers()
    _register_signal_handlers()
    engine = get_db_engine()
    poll_interval_seconds = max(1, int(args.poll_interval_seconds or 30))
    lock_ttl_seconds = max(poll_interval_seconds + 30, int(args.runtime_lock_ttl_seconds or 300))

    while not _STOP_EVENT.is_set():
        handle = acquire_runtime_lock(
            lock_name=str(args.runtime_lock_name or "cw2_kafka_audit_consumer"),
            ttl_seconds=lock_ttl_seconds,
            raise_on_locked=False,
        )
        if not handle.acquired:
            print_json(
                {
                    "status": "waiting_for_lock",
                    "lock_name": handle.requested_name,
                    "redis_key": handle.redis_key,
                    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            if args.once:
                return 0
            _STOP_EVENT.wait(poll_interval_seconds)
            continue

        try:
            exit_code, summary = run_audit_cycle(
                engine=engine,
                cw1_config=str(args.cw1_config),
                cw2_config=str(args.cw2_config),
                pipeline_name=str(args.pipeline_name or "cw2_kafka_audit_consumer"),
                stage_name=str(args.stage_name or "consume_and_audit"),
                context_path=None,
                max_messages=int(args.max_messages or 200),
                poll_timeout_ms=int(args.poll_timeout_ms or 1000),
                max_idle_polls=int(args.max_idle_polls or 3),
                audit_overrides={
                    "consumer_component": "cw2.kafka_audit_daemon",
                },
                producer_component="cw2.kafka_audit_daemon",
            )
            print_json(summary)
            if args.once:
                return exit_code
        finally:
            release_runtime_lock(handle)

        _STOP_EVENT.wait(poll_interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
