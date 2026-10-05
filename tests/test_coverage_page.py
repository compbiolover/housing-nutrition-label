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


def test_the_map_tooltip_never_leaves_the_visible_part_of_its_card():
    """The tooltip hung off the screen near an edge. ``tipPosition`` is run in Node
    against each edge, for a pointer and for a finger, and for a card scrolled half
    out of view: the box must always land inside the visible bounds."""
    import json
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = B._SCRIPT
    fn = script[script.index("function tipPosition"):script.index("(function () {")]
    cases = []
    full = {"left": 0, "top": 0, "right": 360, "bottom": 700}
    scrolled = {"left": 0, "top": 300, "right": 360, "bottom": 700}  # top 300 px off screen
    tight = {"left": 0, "top": 500, "right": 360, "bottom": 700}     # 200 px left on screen
    # The card's top 300 px scrolled away: the bounds run from the top of the screen
    # (300 px below the card's top edge, in the card's coordinates) to its bottom.
    offtop = {"left": 0, "top": 300, "right": 360, "bottom": 1084}
    for b in (full, scrolled, tight, offtop):
        for px in (0, 5, 180, 355, 360):
            for py in sorted({b["top"], b["top"] + 5, 450, 695, 700, 305} & set(range(b["top"], b["bottom"] + 1))):
                for touch in (False, True):
                    cases.append([px, py, 272, 110, b, touch])
    js = fn + "process.stdout.write(JSON.stringify(" + json.dumps(cases) + \
        ".map(function (c) { return tipPosition.apply(null, c); })));"
    out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True,
                                    check=True).stdout)
    for (px, py, w, h, b, touch), pos in zip(cases, out):
        assert b["left"] <= pos["x"] and pos["x"] + w <= b["right"], (px, py, touch, pos)
        assert b["top"] <= pos["y"] and pos["y"] + h <= b["bottom"], (px, py, touch, pos)
    # And a tap with room above puts the tooltip above the finger, not under it,
    # and one at the very top of the screen puts it below, clear of the finger.
    above = out[cases.index([180, 450, 272, 110, full, True])]
    assert above["y"] + 110 <= 450
    below = out[cases.index([180, 305, 272, 110, offtop, True])]
    assert below["y"] >= 305


def test_the_map_tooltip_text_never_goes_through_innerhtml():
    assert "tip.innerHTML" not in B._SCRIPT


def test_the_observed_fields_read_as_one_phrase():
    assert B.observed_phrase(["year_built", "sqft", "stories"]) == "Year built, floor area, stories"
    assert set(B.FIELD_PHRASES) == set(B.FIELD_LABELS)
