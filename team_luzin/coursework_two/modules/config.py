from __future__ import annotations

import json
from pathlib import Path


def load_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    base_dir = config_path.parent.parent.resolve()
    paths = config.setdefault("paths", {})
    paths["cw1_analytics_dir"] = str((base_dir / paths["cw1_analytics_dir"]).resolve())
    paths["output_dir"] = str((base_dir / paths["output_dir"]).resolve())
    if "sp500_csv" in paths:
        paths["sp500_csv"] = str((base_dir / paths["sp500_csv"]).resolve())
    return config
