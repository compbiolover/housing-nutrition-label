#!/usr/bin/env python3
"""Tests for the README sync helper (scripts/sync_readme.py).

Guards the "stays in sync as the code grows" mechanism: the committed README's
generated dimension roster must match what the script produces from the code, and
the generated block must list exactly the engine's DIMENSIONS. No network.

Run directly:  python tests/test_sync_readme.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.simulate.dimensions import DIMENSIONS  # noqa: E402


def _load():
    """Import scripts/sync_readme.py by path (it's a script, not a package module)."""
    path = _ROOT / "scripts" / "sync_readme.py"
    spec = importlib.util.spec_from_file_location("sync_readme", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_block_lists_every_dimension():
    mod = _load()
    block = mod.generate_block()
    for _key, label in DIMENSIONS:
        assert label in block, f"missing dimension {label!r} in generated block"
    # Count sentence matches the roster length (13 → "thirteen").
    assert mod._cardinal(len(DIMENSIONS)) in block


def test_readme_is_in_sync_with_code():
    """The committed README must already contain the current generated block —
    the same assertion CI runs with --check."""
    mod = _load()
    text = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert mod._apply(text, mod.generate_block()) == text, (
        "README.md is out of sync — run `python scripts/sync_readme.py --write`")


def test_apply_is_idempotent():
    mod = _load()
    text = (_ROOT / "README.md").read_text(encoding="utf-8")
    block = mod.generate_block()
    once = mod._apply(text, block)
    assert mod._apply(once, block) == once


if __name__ == "__main__":
    test_generated_block_lists_every_dimension()
    test_readme_is_in_sync_with_code()
    test_apply_is_idempotent()
    print("sync_readme tests passed")
