"""Shared symbol filtering policy for input extractors."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _policy_for_section(
    config: Optional[Dict[str, Any]],
    section: Optional[str],
    default_skip_suffix: bool,
    default_regex: str,
) -> tuple[bool, str]:
    cfg = config or {}
    global_cfg = cfg.get("symbol_filter") or {}
    section_cfg = cfg.get(section) if section else {}
    section_cfg = section_cfg or {}

    skip_suffix_symbols = section_cfg.get(
        "skip_suffix_symbols",
        global_cfg.get("skip_suffix_symbols", default_skip_suffix),
    )
    symbol_regex_allow = section_cfg.get(
        "symbol_regex_allow",
        global_cfg.get("symbol_regex_allow", default_regex),
    )

    return bool(skip_suffix_symbols), str(symbol_regex_allow).strip()


def symbol_allowed(
    symbol: str,
    config: Optional[Dict[str, Any]],
    section: Optional[str] = None,
    *,
    default_skip_suffix: bool = False,
    default_regex: str = r"^[A-Z0-9.]+$",
) -> bool:
    """Return whether symbol passes configured filtering policy."""
    symbol_upper = str(symbol).strip().upper()
    if not symbol_upper:
        return False

    skip_suffix_symbols, symbol_regex_allow = _policy_for_section(
        config=config,
        section=section,
        default_skip_suffix=default_skip_suffix,
        default_regex=default_regex,
    )

    if skip_suffix_symbols and "." in symbol_upper:
        return False
    if symbol_regex_allow and not re.fullmatch(symbol_regex_allow, symbol_upper):
        return False
    return True


def filter_symbols(
    symbols: List[str],
    config: Optional[Dict[str, Any]],
    section: Optional[str] = None,
    *,
    default_skip_suffix: bool = False,
    default_regex: str = r"^[A-Z0-9.]+$",
) -> List[str]:
    """Filter + deduplicate symbols while preserving input order."""
    out: List[str] = []
    seen = set()
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if symbol in seen:
            continue
        if not symbol_allowed(
            symbol,
            config=config,
            section=section,
            default_skip_suffix=default_skip_suffix,
            default_regex=default_regex,
        ):
            continue
        seen.add(symbol)
        out.append(symbol)
    return out
