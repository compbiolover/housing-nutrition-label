#!/usr/bin/env python3
"""Tests for the docs-site sync helper (scripts/sync_docs.py).

Guards the "Setup / Reference pages stay in sync with the code" mechanism: the
committed HTML's generated regions must match what the script produces from the
live constants, every managed region's markers must exist, and the curated
display metadata must cover exactly the code's dimensions / walls / conditions /
foundations / upgrade flags / presets (drift in either direction fails here — the
same assertion CI runs with --check). No network.

Run directly:  python tests/test_sync_docs.py
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
from housing_label.simulate.house import (  # noqa: E402
    CONSTRUCTION_FACTOR, CONDITION_FACTOR, FOUNDATION_FACTOR, PRESETS, BONUS_FLAGS,
)


def _load():
    """Import scripts/sync_docs.py by path (it's a script, not a package module)."""
    path = _ROOT / "scripts" / "sync_docs.py"
    spec = importlib.util.spec_from_file_location("sync_docs", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_metadata_covers_the_code_exactly():
    """The curated metadata must line up with the code constants (both ways) —
    this is the drift guard that _validate() enforces at generate time."""
    mod = _load()
    mod._validate()   # raises SystemExit on any mismatch
    assert set(mod.DIM_META) == {k for k, _ in DIMENSIONS}
    assert set(mod.CONSTRUCTION_META) == set(CONSTRUCTION_FACTOR)
    assert set(mod.CONDITION_META) == set(CONDITION_FACTOR)
    assert set(mod.FOUNDATION_META) == set(FOUNDATION_FACTOR)
    assert set(mod.SHORT_UPGRADE) == set(BONUS_FLAGS)


def test_every_dimension_and_preset_is_rendered():
    mod = _load()
    dims_block = mod.gen_ref_dimensions()
    for _key, label in DIMENSIONS:
        assert label in dims_block, f"missing dimension {label!r} in generated block"
    assert mod._cardinal(len(DIMENSIONS)) in dims_block   # "13 → thirteen" count sentence

    presets_block = mod.gen_ref_presets()
    for name in PRESETS:
        assert f">{name}<" in presets_block, f"missing preset {name!r} in generated block"


def test_upgrade_and_flag_tables_cover_every_flag():
    """Every resilience-upgrade flag appears in the Reference upgrades tables and
    the Setup CLI-flag table, so a new BONUS_FLAG can't ship undocumented."""
    mod = _load()
    upgrade_flags = {row[2] for _title, rows in mod.UPGRADE_GROUPS for row in rows}
    assert upgrade_flags == set(BONUS_FLAGS)

    flag_table = mod.gen_setup_feature_flags()
    for flag in BONUS_FLAGS:
        assert f'--{flag.replace("_", "-")}' in flag_table, f"missing CLI flag for {flag!r}"


def test_pages_are_in_sync_with_code():
    """The committed HTML must already contain the current generated blocks — the
    same assertion CI runs with `python scripts/sync_docs.py --check`."""
    mod = _load()
    for _rid, path, _gen in mod.REGIONS:
        pass  # touch REGIONS so a bad definition surfaces here
    for path in {p for _rid, p, _gen in mod.REGIONS}:
        text = path.read_text(encoding="utf-8")
        updated = text
        for rid, rpath, gen in mod.REGIONS:
            if rpath == path:
                updated = mod._apply(updated, rid, mod._block(rid, gen))
        assert updated == text, (
            f"{path.name} is out of sync — run `python scripts/sync_docs.py --write`")


def test_apply_is_idempotent():
    mod = _load()
    rid, path, gen = mod.REGIONS[0]
    text = path.read_text(encoding="utf-8")
    block = mod._block(rid, gen)
    once = mod._apply(text, rid, block)
    assert mod._apply(once, rid, block) == once


def _run_all():
    test_metadata_covers_the_code_exactly()
    test_every_dimension_and_preset_is_rendered()
    test_upgrade_and_flag_tables_cover_every_flag()
    test_pages_are_in_sync_with_code()
    test_apply_is_idempotent()
    print("sync_docs tests passed")


if __name__ == "__main__":
    _run_all()
