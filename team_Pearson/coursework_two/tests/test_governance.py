"""Unit tests for CW2 governance version helpers."""

from __future__ import annotations

from team_Pearson.coursework_two.modules.utils.governance import (
    resolve_version_bundle,
    select_version_fields,
)


def test_governance_helpers_fill_defaults_and_skip_none_values():
    bundle = resolve_version_bundle({"governance": {"versions": {"model_version": "model-v2"}}})

    selected = select_version_fields(
        {**bundle, "recommendation_version": None},
        ["model_version", "recommendation_version"],
    )

    assert selected == {"model_version": "model-v2"}
