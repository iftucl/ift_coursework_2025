from __future__ import annotations

"""Build Sphinx documentation for the shared Team Pearson platform site."""

import argparse
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.utils.env import load_dotenv_if_exists  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI parser for Sphinx documentation builds."""
    parser = argparse.ArgumentParser(
        description="Build Sphinx HTML docs for the shared CW1 + CW2 platform site."
    )
    parser.add_argument("--builder", default="html", help="Sphinx builder name (default: html).")
    parser.add_argument("--clean", action="store_true", help="Delete existing build output first.")
    parser.add_argument("--source-dir", default="docs/sphinx/source")
    parser.add_argument("--output-dir", default="docs/sphinx/build/html")
    return parser


def main() -> int:
    """CLI entrypoint for Sphinx builds."""
    args = build_parser().parse_args()
    load_dotenv_if_exists(PROJECT_ROOT / ".env")

    source_dir = (PROJECT_ROOT / args.source_dir).resolve()
    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    doctree_dir = (PROJECT_ROOT / "docs" / "sphinx" / "build" / "doctrees").resolve()

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    doctree_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "sphinx",
        "-b",
        args.builder,
        "-d",
        str(doctree_dir),
        str(source_dir),
        str(output_dir),
    ]
    subprocess.run(  # nosec B603
        cmd,
        check=True,
        cwd=str(PROJECT_ROOT),
    )
    print(str(output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
