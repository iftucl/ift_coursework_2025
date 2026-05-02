#!/usr/bin/env python3
"""
Investment Strategy Pipeline - Main Entry Point

This is a thin wrapper around run_pipeline.py for convenience.
All orchestration logic is in run_pipeline.py.

Usage:
  poetry run python3 main.py [OPTIONS]

CLI Options:
  --frequency {daily,weekly,monthly,quarterly}    Scheduling frequency (default: daily)
  --run-date YYYY-MM-DD                          Explicit run date
  --dry-run                                       Show execution plan without running
  --help                                          Display help message

Examples:
  poetry run python3 main.py
      → Run daily (default)

  poetry run python3 main.py --frequency weekly
      → Run weekly strategy

  poetry run python3 main.py --dry-run
      → Show execution plan without running

Exit Codes:
  0 = Success
  1 = Failure (check pipeline.log)
"""

from run_pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())
