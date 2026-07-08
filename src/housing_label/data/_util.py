"""Small shared helpers for the bundled-data lookup modules (``data/*``).

These modules each parse a bundled CSV of raw string cells; ``num`` is the one
coercion they all need and previously each copied verbatim.
"""
from __future__ import annotations


def num(v) -> float | None:
    """Coerce a CSV cell to ``float``; return ``None`` for blank/None/non-numeric."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
