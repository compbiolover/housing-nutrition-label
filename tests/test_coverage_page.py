#!/usr/bin/env python3
"""The coverage page says what the adapter registry says, and nothing more.

``docs/coverage.html`` is generated (``scripts/build_coverage.py``) for the same
reason ``accuracy.html`` is: a page that claims coverage by hand is wrong the day
an adapter lands. These pin the parts a reader relies on — the committed page
matches the registry, every registered adapter is described, every covered
county is actually on the map, and no accuracy figure appears for a jurisdiction
nobody measured. No network.

This file alone: ``pytest tests/test_coverage_page.py``
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load():
    path = _ROOT / "scripts" / "build_coverage.py"
    spec = importlib.util.spec_from_file_location("build_coverage", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load()


def test_the_committed_page_matches_the_registry():
    """The same assertion CI runs with --check."""
    page = (_ROOT / "docs" / "coverage.html").read_text(encoding="utf-8")
    assert page == B.render(B.model()), (
        "docs/coverage.html is stale; run python scripts/build_coverage.py --write")


def test_every_registered_adapter_is_described_and_nothing_else():
    from housing_label.enrich.assessor import ADAPTERS
    registered = {m.__name__.rsplit(".", 1)[-1] for m in ADAPTERS.values()}
    assert registered == set(B.CURATED)


def test_homes_are_summed_from_the_registry_without_double_counting():
    """Connecticut registers both its legacy counties and its planning regions;
    the unit table carries only one of the two, so the state is counted once."""
    m = B.model()
    units, _ = B.county_units()
    for row in m["adapters"]:
        assert row["homes"] == sum(units.get(f, 0) for f in row["counties"])
    assert m["total"] == sum(r["homes"] for r in m["adapters"])
    assert 0 < m["share_pct"] < 100


def test_every_mapped_covered_county_is_colored():
    """A county the registry covers and the map draws must get a fill rule — the
    failure is a covered county left gray, which reads as 'not covered'."""
    svg = (_ROOT / "docs" / "coverage-map.svg").read_text(encoding="utf-8")
    drawn = set(re.findall(r'id="c(\d{5})"', svg))
    page = (_ROOT / "docs" / "coverage.html").read_text(encoding="utf-8")
    m = B.model()
    covered = {f for r in m["adapters"] for f in r["counties"]}
    on_map = covered & drawn
    assert on_map, "no covered county is drawn on the map at all"
    for f in on_map:
        assert f"#covmap #c{f}" in page, f"county {f} is covered but not colored"
    # Every registered county the map lacks is a code the map's vintage predates
    # (Connecticut's planning regions), never an ordinary county that went missing.
    assert {f for f in covered - drawn if not f.startswith("091")} == set()


def test_accuracy_figures_appear_only_where_measured():
    m = B.model()
    results = B.accuracy_results()
    for row in m["adapters"]:
        if "measured" in row:
            assert row["measured"]["jurisdiction"] in results
        else:
            assert row["verified"]["sample"] > 0


def test_tiers_follow_the_fields():
    assert B.depth(["year_built"]) == 1
    assert B.depth(["year_built", "sqft"]) == 2
    assert B.depth(["year_built", "foundation"]) == 3


def test_the_page_is_in_every_pages_nav():
    for page in ("index", "methodology", "examples", "label", "setup", "reference",
                 "accuracy", "coverage"):
        html = (_ROOT / "docs" / f"{page}.html").read_text(encoding="utf-8")
        assert 'href="coverage.html"' in html, f"{page}.html has no Coverage link"


def test_the_map_tooltip_can_name_every_countys_state():
    """"Cumberland" alone is eight different counties. Every state is carried, not
    only the covered ones, because an uncovered county gets a tooltip too."""
    import json
    bc = _load()
    data = json.loads(bc.tooltip_data(bc.model()))
    assert data["s"]["34"] == "NJ" and data["s"]["53"] == "WA"
    covered_states = {f[:2] for f in data["c"]}
    assert covered_states <= set(data["s"])


def test_the_map_tooltip_is_placed_against_its_own_container():
    """The tooltip was positioned inside the card but measured from the map below
    the card's heading, so it landed a heading's height above the pointer and ran
    off the screen near an edge. It must measure from its own offset parent and be
    clamped inside it, and its text must not go through innerHTML."""
    script = _load()._SCRIPT
    assert "tip.offsetParent" in script
    assert "Math.max(pad, Math.min(x, pb.width - w - pad))" in script
    assert "tip.innerHTML" not in script
