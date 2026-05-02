"""Operational helpers for CW2 runtime readiness, audit, monitoring, and daily update decisions."""

__all__ = [
    "run_audit_from_config",
    "run_kafka_event_audit_from_config",
    "run_monitor_from_config",
    "run_update_decision_from_config",
]


def __getattr__(name: str):
    if name == "run_audit_from_config":
        from .audit import run_audit_from_config

        return run_audit_from_config
    if name == "run_monitor_from_config":
        from .monitoring import run_monitor_from_config

        return run_monitor_from_config
    if name == "run_kafka_event_audit_from_config":
        from .kafka_audit import run_kafka_event_audit_from_config

        return run_kafka_event_audit_from_config
    if name == "run_update_decision_from_config":
        from .update_policy import run_update_decision_from_config

        return run_update_decision_from_config
    raise AttributeError(name)
