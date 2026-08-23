#!/usr/bin/env python3
"""Does the unknown year-built actually matter here? — the grade-sensitivity block.

``data/year_built.py`` says how wide the tract's plausible range is; this says
whether that width changes anything. The distinction is the whole point: a 27-year
span is irrelevant on a parcel whose grades never move across it, and worth acting
on where they swing two letters. So the interesting assertions here are about
**silence** as much as about content — the block must be absent whenever there is
nothing to tell the reader, because an always-present panel would train them to
ignore it.

The other load-bearing property is fidelity. The counterfactual re-scores by copying
the final cfg and changing one key, so it should reproduce, exactly, what a full
independent re-score at that year produces. A test pins that against the real
scoring path rather than trusting the shortcut.

No network: every case supplies a Census geography, so the bundled crosswalks do all
the work. Run standalone: ``python tests/test_year_built_sensitivity.py``
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label import batch as B  # noqa: E402
from housing_label.simulate.house import (  # noqa: E402
    YEAR_BUILT_DRIVEN, build_label_parts, label_payload,
)

# Two Shelby County, TN tracts at opposite ends of the vintage range, and one Palm
# Beach County, FL tract built almost all at once. Chosen from the bundled crosswalk
# so they are stable facts about committed data, not about a live service.
OLD_TRACT = "47157003100"      # ACS p25/median/p75 = 1935 / 1950 / 1963
NEW_TRACT = "47157021545"      # 2006 / 2012 / 2017
TIGHT_TRACT = "12099007850"    # 2019 / 2021 / 2023 — a 4-year spread


def _score(tract: str, **extra):
    """Score one address offline at ``tract``; returns (cfg, payload)."""
    parsed = B.parse_row({"lat": "35.15", "lon": "-89.85", "tract": tract, **extra})
    cfg, r, label = build_label_parts(
        lat=parsed["lat"], lon=parsed["lon"], geography=parsed["geography"],
        allow_network=False, **parsed["fields"])
    return cfg, label_payload(cfg, r, label)


def _sens(tract: str, **extra):
    return (_score(tract, **extra)[1]["building"]["year_built"]).get("sensitivity")


# ── it appears when, and only when, it has something to say ─────────────────────
def test_a_wide_tract_reports_what_moves():
    s = _sens(OLD_TRACT)
    assert s is not None, "a 28-year spread that shifts grades must be disclosed"
    assert s["low"]["year"] == 1935 and s["high"]["year"] == 1963
    assert s["current"]["year"] == 1950
    assert s["geo_level"] == "tract"
    assert s["moves"], "a reported block with nothing moving is the silent case"
    for key in s["moves"]:
        assert key in tuple(YEAR_BUILT_DRIVEN) + ("construction_axis",)


def test_a_tight_tract_stays_silent():
    """Built all at once, so the unknown year costs the reader nothing.

    This is the case the feature exists to NOT talk about. If it ever starts
    reporting here, the prompt has become noise everywhere.
    """
    assert _sens(TIGHT_TRACT) is None


def test_a_confirmed_year_removes_the_whole_disclosure():
    """Once the reader tells us the year, what the neighbours did stops bearing."""
    yb = _score(OLD_TRACT, year_built="2005")[1]["building"]["year_built"]
    assert yb["status"] == "confirmed"
    assert "sensitivity" not in yb
    assert "typical_range" not in yb


def test_a_preset_has_no_unknown_to_quantify():
    """A preset is a chosen hypothetical — its year is a decision, not a guess."""
    geo = B.parse_row({"lat": "35.15", "lon": "-89.85", "tract": OLD_TRACT})["geography"]
    _cfg, _r, label = build_label_parts(lat=35.15, lon=-89.85, preset="baseline",
                                        allow_network=False, geography=geo)
    assert "year_built_sensitivity" not in label


def test_an_overridden_dimension_suppresses_the_prompt():
    """A pinned score does not move with the year, so inviting a correction lies."""
    geo = B.parse_row({"lat": "35.15", "lon": "-89.85", "tract": OLD_TRACT})["geography"]
    _cfg, _r, label = build_label_parts(
        lat=35.15, lon=-89.85, allow_network=False, geography=geo,
        overrides={"durability": 50.0})
    assert "year_built_sensitivity" not in label


# ── the counterfactual is exact, not approximate ────────────────────────────────
def test_reported_grades_match_an_independent_rescore():
    """The shortcut must reproduce the real scoring path.

    The block is produced by copying the final cfg and changing one key. If that
    ever diverges from scoring the same address with that year supplied, the prompt
    would be quoting grades the label would never actually show.
    """
    s = _sens(OLD_TRACT)
    for side in ("low", "high"):
        year = s[side]["year"]
        _cfg, pay = _score(OLD_TRACT, year_built=str(year))
        actual = {d["key"]: d["national_grade"] for d in pay["dimensions"]
                  if d["key"] in YEAR_BUILT_DRIVEN}
        actual["construction_axis"] = pay["construction_national_grade"]
        assert actual == s[side]["grades"], (
            f"{side} endpoint ({year}) disagrees with a full re-score: "
            f"reported {s[side]['grades']}, actual {actual}")


def test_no_block_when_the_shown_year_is_not_this_distributions_median():
    """The block must describe the same house the grades do.

    The autofill precedence can pick NSI's tract median over an ACS row that only
    resolved nationally — NSI is more local, so it should. But the distribution
    still carries a median, and reporting it as ``current.year`` while
    ``current.grades`` describe the NSI year is a block that disagrees with itself.
    Reproduced before the fix: current.year said 1980 while the grades were a 1948
    house. Same invariant _building_block applies before drawing typical_range.
    """
    from housing_label.simulate.house import _year_built_sensitivity

    parsed = B.parse_row({"lat": "35.15", "lon": "-89.85", "tract": OLD_TRACT})
    cfg, _r, label = build_label_parts(
        lat=parsed["lat"], lon=parsed["lon"], geography=parsed["geography"],
        allow_network=False, **parsed["fields"])
    loc = label["location"]
    struct = {"structure_type": None, "num_units": 1, "stories": 1, "bldg_material": None}

    us = {"year_built": 1980, "p25": 1959, "p75": 2000, "spread": 41,
          "geo_level": "us", "resolved": False}
    loc.year_built_distribution = us

    disagreeing = dict(cfg)
    disagreeing["year_built"] = 1948            # NSI's tract median won the precedence
    assert _year_built_sensitivity(disagreeing, label, struct, loc) is None

    # The same distribution IS usable once the shown year is actually its median.
    agreeing = dict(cfg)
    agreeing["year_built"] = 1980
    assert _year_built_sensitivity(agreeing, label, struct, loc) is not None


def test_the_snapshot_is_not_disturbed_by_its_own_counterfactuals():
    """Two extra scoring passes must leave the real label untouched."""
    cfg, pay = _score(OLD_TRACT)
    assert cfg["year_built"] == 1950
    assert pay["house"]["year_built"] == 1950
    assert pay["building"]["year_built"]["value"] == 1950


def test_current_grades_are_the_labels_own():
    """The middle point is read off the snapshot, never re-derived.

    Re-deriving it would risk the prompt disagreeing with the grades printed a few
    inches above it — the one inconsistency a reader is guaranteed to notice.
    """
    _cfg, pay = _score(NEW_TRACT)
    s = pay["building"]["year_built"]["sensitivity"]
    shown = {d["key"]: d["national_grade"] for d in pay["dimensions"]
             if d["key"] in YEAR_BUILT_DRIVEN}
    shown["construction_axis"] = pay["construction_national_grade"]
    assert s["current"]["grades"] == shown


def test_moves_lists_only_dimensions_that_really_move():
    """Every named dimension must show more than one grade across the three points,
    and every unnamed one must show exactly one."""
    _cfg, pay = _score(NEW_TRACT)
    s = pay["building"]["year_built"]["sensitivity"]
    for key in tuple(YEAR_BUILT_DRIVEN) + ("construction_axis",):
        grades = {pt["grades"].get(key) for pt in (s["low"], s["current"], s["high"])}
        grades.discard(None)
        if key in s["moves"]:
            assert len(grades) > 1, f"{key} is listed as moving but shows {grades}"
        else:
            assert len(grades) <= 1, f"{key} moves ({grades}) but is not listed"


def test_environmental_is_not_claimed_to_move():
    """Its embodied leg is fixed at build and its operational leg rides kWh, so a
    different vintage does not move it. Pinned because quietly adding it to
    YEAR_BUILT_DRIVEN would make the prompt promise a change that never comes."""
    assert "environmental" not in YEAR_BUILT_DRIVEN


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
