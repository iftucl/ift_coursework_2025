from __future__ import annotations

"""Fail if repository-controlled CW2 source files contain oversized artifacts."""

import argparse
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pre_commit_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "docs/_build",
    "htmlcov",
    "inputs",
    "outputs",
}
EXCLUDED_PREFIXES = (
    ".pytest_tmp",
    "pytest_tmp",
    "pytest-cache-files-",
)


def _is_excluded(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    if any(part.startswith(EXCLUDED_PREFIXES) for part in relative_parts):
        return True
    prefixes = {"/".join(relative_parts[:idx]) for idx in range(1, len(relative_parts) + 1)}
    return bool(prefixes & EXCLUDED_DIRS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-mb", type=float, default=5.0)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    max_bytes = int(float(args.max_mb) * 1024 * 1024)
    offenders: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or _is_excluded(path, root):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > max_bytes:
            offenders.append(path.relative_to(root))

    if offenders:
        print(f"Files above {args.max_mb:g} MB:")
        for path in offenders:
            print(f"- {path}")
        return 1
    print(f"No source-controlled CW2 files exceed {args.max_mb:g} MB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
