"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Auto-generated appendices F, G, H
Project : CW2 - Value-Sentiment Investment Strategy

Materialises the three appendices from Part C §C3 that are mechanically
generated rather than handwritten:

    * **Appendix F — Data quality summary** (CW1 coverage stats):
      sourced live from the CW1 PostgreSQL schema so the report
      reflects the actual state of the database at run time, not a
      stale snapshot.
    * **Appendix G — Code quality summary**: number of source files,
      LOC, test count, test:source ratio, and pyproject.toml linter
      configuration. Also checks whether each module package has an
      `__init__.py` with a docstring.
    * **Appendix H — Configuration dump**: the parsed
      backtest_config.yaml flattened to a long-format CSV so every
      parameter is explicitly visible in the report appendix
      (counters the "magic number" critique).

Each function takes the data source it needs and writes a CSV (or a
markdown table) to the supplied output directory. The functions are
deliberately independent of each other and of the rest of the pipeline
so they can be invoked from ``Main_CW2.py`` ad hoc, or from a CI step,
or from a manual ``poetry run python -m modules.analytics.appendices``.

Ref: Part C §C3 — Appendices.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import pandas as pd

from modules.data.cw1_schema import (
    DEFAULT_SCHEMA,
    TABLE_COMPANY_STATIC,
    TABLE_COMPOSITE_RANKINGS,
    TABLE_DAILY_PRICES,
    TABLE_SENTIMENT_SCORES,
    TABLE_VALUE_METRICS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Appendix F — Data quality summary
# ---------------------------------------------------------------------------

def build_data_quality_summary(data_loader) -> pd.DataFrame:
    """Build Appendix F — CW1 coverage and freshness summary.

    Queries the CW1 PostgreSQL schema for each table CW2 consumes and
    reports row counts, distinct ticker counts, and the most recent
    date present. All identifiers come from
    :mod:`modules.data.cw1_schema`, so any CW1 rename is caught at
    unit-test time.

    :param data_loader: Live :class:`modules.data.data_loader.DataLoader`
                        instance (we reuse its connection pool)
    :type data_loader: modules.data.data_loader.DataLoader
    :returns: DataFrame with one row per CW1 table, columns
              ``[table, row_count, distinct_companies, latest_date,
              earliest_date, status]``
    :rtype: pd.DataFrame
    """
    # pylint: disable=protected-access
    schema = getattr(data_loader, '_schema', DEFAULT_SCHEMA)
    rows = []

    table_specs = [
        (TABLE_COMPANY_STATIC, 'symbol', None),
        (TABLE_DAILY_PRICES, 'symbol', 'cob_date'),
        (TABLE_VALUE_METRICS, 'company_id', 'date'),
        (TABLE_SENTIMENT_SCORES, 'company_id', 'date'),
        (TABLE_COMPOSITE_RANKINGS, 'company_id', 'date'),
    ]

    from sqlalchemy import text
    for table, id_col, date_col in table_specs:
        try:
            base = f'SELECT COUNT(*) AS row_count, COUNT(DISTINCT {id_col}) AS distinct_companies'
            if date_col:
                base += f', MIN({date_col})::text AS earliest_date, MAX({date_col})::text AS latest_date'
            base += f' FROM {schema}.{table}'
            with data_loader._connection() as conn:
                result = conn.execute(text(base)).mappings().first()
            row = {
                'table': table,
                'row_count': int(result['row_count']) if result and result['row_count'] else 0,
                'distinct_companies': int(result['distinct_companies'])
                                       if result and result['distinct_companies'] else 0,
                'earliest_date': result.get('earliest_date') if date_col and result else None,
                'latest_date': result.get('latest_date') if date_col and result else None,
                'status': 'OK',
            }
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("data-quality query failed for %s: %s", table, exc)
            row = {
                'table': table,
                'row_count': 0,
                'distinct_companies': 0,
                'earliest_date': None,
                'latest_date': None,
                'status': f'ERROR: {exc}',
            }
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Appendix G — Code quality summary
# ---------------------------------------------------------------------------

def build_code_quality_summary(repo_root: Optional[str] = None) -> pd.DataFrame:
    """Build Appendix G — code-quality + test-coverage statistics.

    Walks the CW2 module tree and the test tree, counting source
    files, lines of code (excluding blank lines and comment-only
    lines), test files, test cases, and per-package init coverage.

    :param repo_root: Root directory to scan; defaults to the
                      coursework_two top-level (where this file lives)
    :type repo_root: str or None
    :returns: DataFrame with one row per (category, metric, value)
    :rtype: pd.DataFrame
    """
    if repo_root is None:
        # This file lives at coursework_two/modules/analytics/appendices.py
        # → parents[2] is coursework_two/
        from pathlib import Path
        repo_root = str(Path(__file__).resolve().parents[2])

    modules_dir = os.path.join(repo_root, 'modules')
    tests_dir = os.path.join(repo_root, 'tests')

    src_files = list(_walk_python(modules_dir))
    test_files = list(_walk_python(tests_dir))

    src_loc = sum(_count_loc(p) for p in src_files)
    test_loc = sum(_count_loc(p) for p in test_files)
    test_cases = sum(_count_test_cases(p) for p in test_files)

    init_files = [p for p in src_files if os.path.basename(p) == '__init__.py']
    documented_inits = sum(1 for p in init_files if _has_module_docstring(p))

    rows = [
        {'category': 'source', 'metric': 'python_files', 'value': len(src_files)},
        {'category': 'source', 'metric': 'lines_of_code', 'value': src_loc},
        {'category': 'source', 'metric': '__init__.py_files', 'value': len(init_files)},
        {'category': 'source', 'metric': 'documented___init__.py', 'value': documented_inits},
        {'category': 'tests', 'metric': 'test_files', 'value': len(test_files)},
        {'category': 'tests', 'metric': 'test_cases', 'value': test_cases},
        {'category': 'tests', 'metric': 'test_lines_of_code', 'value': test_loc},
        {
            'category': 'ratio',
            'metric': 'tests_per_source_file',
            'value': round(test_cases / max(1, len(src_files)), 2),
        },
        {
            'category': 'ratio',
            'metric': 'test_loc_per_source_loc',
            'value': round(test_loc / max(1, src_loc), 2),
        },
    ]
    return pd.DataFrame(rows)


def _walk_python(root: str):
    if not os.path.isdir(root):
        return
    for dirpath, _dirs, filenames in os.walk(root):
        # Skip cache + virtualenv directories
        if '__pycache__' in dirpath or '.venv' in dirpath:
            continue
        for fname in filenames:
            if fname.endswith('.py'):
                yield os.path.join(dirpath, fname)


def _count_loc(path: str) -> int:
    """Count non-blank, non-comment-only lines in a Python file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return 0
    loc = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('#'):
            continue
        loc += 1
    return loc


_TEST_DEF_RE = re.compile(r'^\s*def\s+test_\w+\s*\(')


def _count_test_cases(path: str) -> int:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return sum(1 for line in f if _TEST_DEF_RE.match(line))
    except OSError:
        return 0


def _has_module_docstring(path: str) -> bool:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            head = f.read(2048).lstrip()
    except OSError:
        return False
    return head.startswith('"""') or head.startswith("'''")


# ---------------------------------------------------------------------------
# Appendix H — Configuration dump
# ---------------------------------------------------------------------------

def build_config_dump(config: dict) -> pd.DataFrame:
    """Build Appendix H — the active backtest_config.yaml as a flat table.

    Recursively flattens the parsed config dict into one row per leaf
    parameter, with the dotted-path key, value, and value type. This
    way the report appendix shows every active parameter explicitly,
    leaving no "magic number" claims unanswered.

    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    :returns: DataFrame ``[parameter, value, type]``
    :rtype: pd.DataFrame
    """
    rows = []
    _flatten(config, prefix='', acc=rows)
    return pd.DataFrame(rows, columns=['parameter', 'value', 'type'])


def _flatten(obj, prefix: str, acc: list):
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f'{prefix}.{k}' if prefix else str(k)
            _flatten(v, key, acc)
    elif isinstance(obj, (list, tuple)):
        # Lists are stringified at the leaf — they're often short
        # enums (e.g. rebalance_months) so this is more readable than
        # exploding them into one row per element.
        acc.append({
            'parameter': prefix,
            'value': repr(list(obj)),
            'type': 'list',
        })
    else:
        acc.append({
            'parameter': prefix,
            'value': '' if obj is None else repr(obj) if isinstance(obj, str) else str(obj),
            'type': type(obj).__name__,
        })


# ---------------------------------------------------------------------------
# Convenience wrapper used by Main_CW2 step 8
# ---------------------------------------------------------------------------

def write_all_appendices(
    data_loader,
    config: dict,
    output_dir: str,
) -> dict:
    """Write Appendices F, G, H to ``output_dir/tables`` as CSV files.

    :param data_loader: Live DataLoader for Appendix F
    :type data_loader: modules.data.data_loader.DataLoader
    :param config: Parsed backtest_config.yaml dict for Appendix H
    :type config: dict
    :param output_dir: Top-level output directory (a ``tables/``
                       subdirectory will be created if it doesn't exist)
    :type output_dir: str
    :returns: Dict mapping appendix label to written file path
    :rtype: dict
    """
    tables_dir = os.path.join(output_dir, 'tables')
    os.makedirs(tables_dir, exist_ok=True)

    paths = {}

    try:
        f_df = build_data_quality_summary(data_loader)
        f_path = os.path.join(tables_dir, 'appendix_f_data_quality.csv')
        f_df.to_csv(f_path, index=False)
        paths['F'] = f_path
        logger.info("Appendix F (data quality) saved: %s", f_path)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Appendix F generation failed: %s", exc)

    try:
        g_df = build_code_quality_summary()
        g_path = os.path.join(tables_dir, 'appendix_g_code_quality.csv')
        g_df.to_csv(g_path, index=False)
        paths['G'] = g_path
        logger.info("Appendix G (code quality) saved: %s", g_path)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Appendix G generation failed: %s", exc)

    try:
        h_df = build_config_dump(config)
        h_path = os.path.join(tables_dir, 'appendix_h_config.csv')
        h_df.to_csv(h_path, index=False)
        paths['H'] = h_path
        logger.info("Appendix H (config dump) saved: %s (%d parameters)", h_path, len(h_df))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Appendix H generation failed: %s", exc)

    return paths
