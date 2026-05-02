from __future__ import annotations

"""Shared version-governance helpers for CW2 persisted artifacts."""

from typing import Any, Dict, Iterable, Mapping

FEATURE_VERSION_KEYS = (
    "model_version",
    "factor_definition_version",
    "covariance_method_version",
    "risk_overlay_policy_version",
)

RECOMMENDATION_VERSION_KEYS = FEATURE_VERSION_KEYS + ("recommendation_version",)

BACKTEST_VERSION_KEYS = FEATURE_VERSION_KEYS + ("backtest_engine_version",)

REPORTING_VERSION_KEYS = (
    "model_version",
    "factor_definition_version",
    "covariance_method_version",
    "risk_overlay_policy_version",
    "backtest_engine_version",
    "reporting_version",
)

DEFAULT_VERSION_BUNDLE: Dict[str, str] = {
    "model_version": "cw2-model-2026.04",
    "factor_definition_version": "cw2-factor-spec-2026.04",
    "covariance_method_version": "cw2-covariance-2026.04",
    "risk_overlay_policy_version": "cw2-risk-overlay-2026.04",
    "recommendation_version": "cw2-recommendation-2026.04",
    "backtest_engine_version": "cw2-backtest-2026.04",
    "reporting_version": "cw2-reporting-2026.04",
}


def resolve_version_bundle(config: Mapping[str, Any] | None) -> Dict[str, str]:
    """Resolve the effective CW2 version bundle from config with stable defaults."""

    root_cfg = dict(config or {})
    governance_cfg = dict(root_cfg.get("governance") or {})
    configured_versions = dict(governance_cfg.get("versions") or {})
    out: Dict[str, str] = {}
    for key, default_value in DEFAULT_VERSION_BUNDLE.items():
        value = configured_versions.get(key)
        normalized = str(value).strip() if value is not None else ""
        out[key] = normalized or default_value
    return out


def select_version_fields(
    bundle: Mapping[str, Any],
    keys: Iterable[str],
) -> Dict[str, str]:
    """Select a stable subset of version fields for one persisted object type."""

    selected: Dict[str, str] = {}
    for key in keys:
        value = bundle.get(key)
        if value is None:
            continue
        selected[key] = str(value)
    return selected
