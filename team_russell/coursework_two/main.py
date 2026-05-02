"""CW2 Pipeline — Team RUSSEL Systematic Equity Strategy.

Single entry point that runs all pipeline steps in order.

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/main.py

----------------------------------------------------------------
PHASE 1 -- DATA BUILD  (writes to PostgreSQL + CSV)
----------------------------------------------------------------
  Step 01  WRDS/Compustat pull -- US + European TTM fundamentals
           SKIPPED by default (needs WRDS credentials + PostgreSQL)
  Step 02  Extend to Dec 2015 -- builds full 40-quarter dataset
           Outputs: stock_returns_10year.csv

----------------------------------------------------------------
PHASE 2 -- ANALYSIS  (all read stock_returns_10year.csv)
----------------------------------------------------------------
  Step 03  IC analysis -- Spearman IC per quarter (40 periods)
  Step 04  Turnover analysis -- 40 quarters
  Step 05  Buffer zone robustness test -- 40 quarters
  Step 06  Benchmark comparison (SPY, MSCI World, MSCI ACWI)
  Step 07  Final presentation charts (10-year NAV, Q1 vs Q5, annual returns table)
  Step 08  Factor attribution -- Value vs Quality vs Momentum vs Composite
  Step 09  Long-short portfolio (optional robustness test)

Charts produced:
  01_10year_nav.png              -- PRIMARY: 10-year quintile NAV
  02_q1_vs_q5.png               -- Q1 vs Q5 all quintiles
  03_ic_per_period.png           -- IC per quarter (40 periods)
  04_benchmark_comparison.png    -- Q1 vs SPY / MSCI World / MSCI ACWI
  05_buffer_zone.png             -- Buffer zone robustness test
  06_turnover_per_period.png     -- Quarterly turnover bar chart
  07_sector_active_weights.png   -- Sector active weights vs universe
  07c_q1_annual_returns_table.png -- Long-only Q1 annual return by year (2016–2025)
  08_factor_attribution_nav.png  -- Single-factor vs composite NAV
  09_factor_attribution_bar.png  -- Per-quarter factor attribution bars
  10_long_short_cumulative.png   -- Long-short vs long-only NAV
"""

import sys
import time
import traceback
from pathlib import Path

SCRIPTS = Path(__file__).parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

# ── Pipeline definition ───────────────────────────────────────────────────────
# Each entry: (display_number, module_name, phase)
# Step 01 (WRDS pull) is excluded by default -- needs credentials + live DB.
# Step 09 (long-short) is included as an optional robustness test.
PIPELINE = [
    # ── PHASE 1: Data Build ──────────────────────────────────────────────────
    # ("01", "step01_wrds_pull", "build"),   # needs WRDS credentials + PostgreSQL
    # ("02", "step02_extend_2015", "build"), # needs PostgreSQL; pre-built CSV included
    # ── PHASE 2: Analysis ────────────────────────────────────────────────────
    ("03", "step03_ic_analysis", "analysis"),
    ("04", "step04_turnover", "analysis"),
    ("05", "step05_buffer_zone", "analysis"),
    ("06", "step06_benchmark", "analysis"),
    ("07", "step07_final_charts", "analysis"),
    ("08", "step08_factor_attribution", "analysis"),
    ("09", "step09_long_short", "analysis"),
]

# Charts expected in results/charts/ after a full run
EXPECTED_CHARTS = [
    ("01_10year_nav.png", "PRIMARY: 10-year quintile NAV"),
    ("02_q1_vs_q5.png", "Q1 vs Q5 all quintiles"),
    ("03_ic_per_period.png", "IC per quarter (40 periods)"),
    ("04_benchmark_comparison.png", "Q1 vs SPY / MSCI World / ACWI"),
    ("05_buffer_zone.png", "Buffer zone robustness test"),
    ("06_turnover_per_period.png", "Quarterly turnover bar chart"),
    ("07_sector_active_weights.png", "Sector active weights vs universe"),
    ("07c_q1_annual_returns_table.png", "Long-only Q1 annual return by year (2016–2025)"),
    ("08_factor_attribution_nav.png", "Factor attribution NAV"),
    ("09_factor_attribution_bar.png", "Factor attribution per-quarter bars"),
    ("10_long_short_cumulative.png", "Long-short vs long-only NAV"),
]


def run_step(number: str, module_name: str) -> bool:
    """Import and run a single pipeline step. Returns True on success."""
    print(f"\n{'='*65}")
    print(f"  STEP {number}  --  {module_name}")
    print(f"{'='*65}")
    t0 = time.time()
    try:
        import importlib

        mod = importlib.import_module(module_name)
        mod.main()
        elapsed = time.time() - t0
        print(f"\n  OK  Step {number} completed in {elapsed:.1f}s")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"\n  FAILED  Step {number} after {elapsed:.1f}s: {e}")
        traceback.print_exc()
        return False


def main():
    print("=" * 65)
    print("  RUSSEL CW2 PIPELINE  --  Systematic Equity Strategy")
    print("  3-Factor: Value 35% + Quality 35% + Momentum 30%")
    print("=" * 65)
    print(f"\n  {len(PIPELINE)} steps  |  Steps 01–02 skipped (pre-built CSV included)")

    results = {}
    t_total = time.time()
    cur_phase = None

    for number, module_name, phase in PIPELINE:
        if phase != cur_phase:
            cur_phase = phase
            label = (
                "DATA BUILD  (writes to PostgreSQL + CSV)"
                if phase == "build"
                else "ANALYSIS   (reads from stock_returns_10year.csv)"
            )
            print(f"\n\n{'--'*32}")
            print(f"  PHASE: {label}")
            print(f"{'--'*32}")

        ok = run_step(number, module_name)
        results[number] = ok

        if not ok:
            ans = input(f"\n  Step {number} failed. Continue? [y/N]: ").strip().lower()
            if ans != "y":
                print("\n  Pipeline stopped.")
                break

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - t_total
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)

    print(f"\n\n{'='*65}")
    print("  PIPELINE SUMMARY")
    print(f"{'='*65}")

    prev_phase = None
    for number, module_name, phase in PIPELINE:
        if number not in results:
            continue
        if phase != prev_phase:
            prev_phase = phase
            print(f"\n  {'Data Build' if phase == 'build' else 'Analysis'}:")
        status = "OK    " if results[number] else "FAILED"
        print(f"    Step {number}  {status}  {module_name}")

    print(f"\n  {passed} passed  |  {failed} failed  |  {elapsed/60:.1f} min total")

    # ── Output file check ─────────────────────────────────────────────────────
    charts_dir = Path(__file__).parent / "results" / "charts"
    print(f"\n  Charts ({charts_dir.name}/):")
    for fname, desc in EXPECTED_CHARTS:
        mark = "OK" if (charts_dir / fname).exists() else "MISSING"
        print(f"    {mark:<7}  {fname:<40}  {desc}")

    print(f"\n{'='*65}\n")


if __name__ == "__main__":
    main()
