from __future__ import annotations

__all__ = ["extract_source_a", "extract_source_b"]


def __getattr__(name: str):
    if name == "extract_source_a":
        from .extract_source_a import extract_source_a

        return extract_source_a
    if name == "extract_source_b":
        from .extract_source_b import extract_source_b

        return extract_source_b
    raise AttributeError(name)
