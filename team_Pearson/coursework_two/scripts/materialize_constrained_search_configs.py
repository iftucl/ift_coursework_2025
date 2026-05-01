#!/usr/bin/env python3
"""Materialize pre-declared constrained-search candidate configs.

This keeps the search space explicit: candidate definitions live in a manifest,
and configs are generated mechanically from a validated baseline config.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import yaml


def _set_nested(mapping: dict[str, Any], dotted_key: str, value: Any) -> None:
    cursor: Any = mapping
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        if part not in cursor or not isinstance(cursor[part], dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


def materialize(manifest_path: Path, overwrite: bool) -> list[Path]:
    manifest = yaml.safe_load(manifest_path.read_text())
    base_path = Path(manifest["base_config"])
    base_cfg = yaml.safe_load(base_path.read_text())
    written: list[Path] = []

    for candidate in manifest.get("candidates", []):
        overrides = candidate.get("overrides")
        if not overrides:
            continue
        target_path = Path(candidate["config_path"])
        if target_path.exists() and not overwrite:
            continue
        cfg = copy.deepcopy(base_cfg)
        for dotted_key, value in overrides.items():
            _set_nested(cfg, dotted_key, value)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=False))
        written.append(target_path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    written = materialize(args.manifest, overwrite=args.overwrite)
    for path in written:
        print(path)
    print({"written_count": len(written)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
