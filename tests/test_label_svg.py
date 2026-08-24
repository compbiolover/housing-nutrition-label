#!/usr/bin/env python3
"""The printable sheet (housing_label.label_svg).

No network and no FastAPI — like the badge, the renderer is a pure function of a
payload, which is most of why it lives in its own module.

The sheet is the copy of the label that leaves the browser: it gets printed,
filed, emailed, and read months later by somebody who was never at the screen.
So the assertions here lean on the failures that only show up off-screen and
that nobody would see in review — a page that silently grew to two, a grade that
exists only as a colour, a letter invented for a dimension that was never
scored, and caller text reaching markup unescaped.

Run directly:  python tests/test_label_svg.py
"""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET

from housing_label import badge, label_svg
from housing_label.legal import DISCLAIMER

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_LABEL_CORE = _ROOT / "docs" / "label-core.js"

_DIMS = [
    ("resilience", "Disaster Resilience", "construction", 65.1, "B", 62),
    ("energy", "Energy Efficiency", "construction", 78.0, "B", 81),
    ("durability", "Durability", "construction", 46.1, "C", 44),
    ("environmental", "Environmental Footprint", "construction", 65.1, "B", 66),
    ("infrastructure", "Infrastructure Burden", "construction", 59.1, "C", 57),
    ("air_quality", "Air Quality", "location", 55.3, "C", 51),
    ("noise", "Noise", "location", 23.8, "D", 21),
    ("walkability", "Walkability", "location", 70.3, "B", 72),
    ("climate", "Climate Projections", "location", 46.4, "C", 45),
    ("solar", "Solar Potential", "location", 47.3, "C", 47),
    ("water", "Water Quality", "location", 100.0, "A", 99),
    ("health", "Health Impact", "context", 71.6, "B", 70),
    ("socioeconomic", "Socioeconomic", "context", 50.0, "C", 50),
]


def _payload(**over) -> dict:
    """A full 13-dimension payload, in the shape simulate.house.label_payload
    returns — the worst case for the one-page budget."""
    p = {
        "dimensions": [
            {"key": k, "label": lab, "kind": kind, "score": s,
             "national_grade": g, "national_percentile": pct}
            for k, lab, kind, s, g, pct in _DIMS],
        "confidence": {k: "moderate" for k, *_ in _DIMS},
        "composite_score": 59.9, "composite_national_grade": "C",
        "construction_score": 63.9, "construction_national_grade": "B",
        "location_score": 70.3, "location_national_grade": "B",
        "metrics": {"eui_kbtu_sqft_yr": 41.2, "fiscal_ratio": 0.76,
                    "est_monthly_energy_cost": 133},
        "cost": {"annualEnergyCost": 1602, "expectedAnnualLoss": 193},
        "baseline_cost": {"annualEnergyCost": 1750, "expectedAnnualLoss": 210,
                          "label": "a same-size 2000-era frame home"},
        "house": {"construction": "frame", "year_built": 1955, "sqft": 1400,
                  "lat": 35.13, "lon": -89.99},
        "location": {"label": "Shelby County, TN", "county_name": "Shelby County",
                     "climate_zone": "3A"},
        "caveats": ["Infrastructure Burden falls back to the pilot cost model "
                    "outside Shelby County, TN."],
        "disclaimer": DISCLAIMER,
    }
    p.update(over)
    return p


def _texts(svg: str) -> list[str]:
    root = ET.fromstring(svg)
    return [(e.text or "") for e in root.iter() if e.tag.endswith("text")]


def test_a_stand_in_year_prints_as_a_range_not_a_bare_number():
    """The printable sheet is the surface most likely to outlive its context — it
    gets saved, mailed and filed away from the page that explains it. A tract
    typical printed as a bare year becomes, on paper, an assertion about the
    building that nobody can trace back."""
    payload = _payload(building={"year_built": {"value": 1955, "status": "assumed",
                                                "typical_range": [1932, 1996]}})
    svg = label_svg.render_sheet(payload)
    assert "1932\u20131996 (area typical)" in svg
    assert "built 1955" not in svg, "the bare year must not also appear"


def test_a_year_about_the_building_still_prints_plainly():
    payload = _payload(building={"year_built": {"value": 1955, "status": "observed"}})
    assert "built 1955" in label_svg.render_sheet(payload)


def test_a_payload_with_no_provenance_block_falls_back_to_the_house_year():
    """Older callers and the badge path build a payload with no `building` key. They
    must keep rendering, not lose the year."""
    assert "built 1955" in label_svg.render_sheet(_payload())


def test_every_theme_renders_well_formed_svg():
    for theme in badge.THEME_NAMES:
        svg = label_svg.render_sheet(_payload(), address="123 Main St", theme=theme)
        ET.fromstring(svg)   # raises on malformed markup


def test_an_unknown_theme_is_an_error_not_a_silent_fallback():
    """A typo'd query parameter should be a 400 at the edge. A sheet that
    rendered light for ``theme=drak`` would leave the caller unable to tell the
    difference between a rejected value and an ignored one."""
    try:
        label_svg.render_sheet(_payload(), theme="drak")
    except ValueError as exc:
        assert "drak" in str(exc)
    else:
        raise AssertionError("an unknown theme must raise")


def test_a_full_label_still_fits_one_letter_page():
    """The whole point of a second renderer. A 13-dimension label with a cost
    strip, a caveat, and a two-line address is the worst case this has to hold,
    and a sheet that spills 20px onto a second page prints as two sheets — one of
    which is a footer."""
    svg = label_svg.render_sheet(
        _payload(), address="1234 Cooper Street, Memphis, Tennessee 38104",
        generated="2026-08-22")
    w, h = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups()
    assert int(w) == label_svg.PAGE_W
    assert int(h) <= label_svg.PAGE_H, f"sheet is {h}px tall, one page is {label_svg.PAGE_H}"


def test_the_root_carries_physical_units():
    """``width="8.5in"`` is what makes the file import and print at true size
    instead of at whatever a consumer decides 816 user units mean."""
    svg = label_svg.render_sheet(_payload())
    root = ET.fromstring(svg)
    assert root.get("width") == "8.5in", root.get("width")
    assert root.get("height", "").endswith("in"), root.get("height")
    assert root.get("viewBox", "").startswith("0 0 816 ")


def test_the_palette_is_the_badges_palette():
    """A printed grade and the same grade on the site must be the same colour —
    the reader can hold both up next to each other, which is more than they can
    do with two browser tabs. Sharing the constants is the mechanism; this is the
    assertion that they are still shared (tests/test_badge.py in turn pins them
    to docs/label-core.js)."""
    assert label_svg.GRADE_COLORS is badge.GRADE_COLORS
    svg = label_svg.render_sheet(_payload())
    for grade in ("A", "B", "C", "D"):
        assert badge.GRADE_COLORS[grade] in svg, grade


def test_colour_is_never_the_only_channel():
    """Grayscale printers, photocopies, and colour blindness all destroy the
    same channel. Every grade on the sheet must also be readable as a letter and
    as a number, so nothing is lost when the colour is."""
    svg = label_svg.render_sheet(_payload())
    drawn = _texts(svg)
    for _k, _lab, _kind, score, grade, _pct in _DIMS:
        assert grade in drawn, f"{grade} is drawn as a fill but never as a letter"
        assert f"{score:.1f}" in drawn, f"{score} has no printed number"


def test_an_unscored_dimension_is_never_given_a_letter():
    """An axis or a row can legitimately be unscored (a parcel with no tract, an
    upstream outage). A sheet that printed "F" for "we don't know" would be a
    libel about somebody's house, and on paper it is one nobody can refresh."""
    svg = label_svg.render_sheet(_payload(
        dimensions=[{"key": "noise", "label": "Noise", "kind": "location",
                     "score": None, "national_grade": "—"}],
        location_score=None, location_national_grade=None,
        composite_score=None, composite_national_grade=None))
    drawn = " ".join(_texts(svg))
    assert "F" not in drawn.replace("Footprint", "")
    assert "Not scored" in drawn or "No data here" in drawn
    assert badge.GRADE_COLORS["F"] not in svg


def test_caller_text_cannot_reach_the_markup():
    """The address, the location label, and the caveats are caller-supplied and
    land in a document a browser will parse if the file is opened directly."""
    hostile = "<script>alert(1)</script>"
    svg = label_svg.render_sheet(
        _payload(caveats=[hostile], location={"label": hostile, "county_name": hostile}),
        address=hostile)
    ET.fromstring(svg)
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_the_sheet_avoids_what_print_tooling_does_not_render():
    """Two rules the badge doesn't need. ``dominant-baseline`` is honoured by
    browsers and ignored by several design applications, which slides every grade
    letter out of its chip; ``foreignObject`` is HTML smuggled into an SVG and
    renders in browsers only, which is exactly the trap a DOM-serialising
    "export" falls into."""
    svg = label_svg.render_sheet(_payload())
    assert "dominant-baseline" not in svg
    assert "foreignObject" not in svg
    # Nothing may be fetched at render time either: a sheet that needed the
    # network would print blank from a folder on a laptop with no wifi.
    assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "")
    assert "<image" not in svg and "@import" not in svg


def test_text_is_text():
    """Not paths. A sheet whose text is outlined cannot be searched, selected,
    corrected, or read by a screen reader — and the address is the field most
    likely to need correcting after the fact."""
    svg = label_svg.render_sheet(_payload(), address="123 Main St")
    assert "<path" not in svg
    assert "123 Main St" in " ".join(_texts(svg))


def test_the_notice_is_carried_in_full():
    """Paper travels furthest from our fine print, so the sheet draws the whole
    disclaimer rather than the short form the badge has room for."""
    svg = label_svg.render_sheet(_payload())
    root = ET.fromstring(svg)
    drawn = " ".join(" ".join(_texts(svg)).split())
    assert DISCLAIMER in drawn, "the full notice is not drawn on the face"
    assert [e.text for e in root.iter() if e.tag.endswith("desc")] == [DISCLAIMER]


def test_the_footer_says_where_and_when():
    """A grade on a loose sheet with no source and no date is the copy that gets
    misread a year later."""
    svg = label_svg.render_sheet(_payload(), generated="2026-08-22")
    drawn = " ".join(_texts(svg))
    assert badge.HOME in drawn
    assert "2026-08-22" in drawn
    # And it is optional: a sheet rendered without one says nothing rather than
    # inventing today's date, because the date that matters is the scoring date.
    undated = _texts(label_svg.render_sheet(_payload()))
    assert not any(t.startswith(badge.WORDMARK) and "scored" in t for t in undated)


def test_the_running_cost_matches_the_web_renderers_arithmetic():
    """The sheet re-implements costPv() in Python. A horizon or discount rate
    that moves in docs/label-core.js and not here would print a different dollar
    figure than the screen it was printed from — for the same house, on the same
    day."""
    js = _LABEL_CORE.read_text(encoding="utf-8")
    m = re.search(r"annuityFactor\(\s*(\d+)\s*,\s*rate == null \? ([\d.]+)", js)
    assert m, "costPv() moved in label-core.js — re-check the horizon and rate"
    years, rate = int(m.group(1)), float(m.group(2))
    assert (years, rate) == (30, 0.04), (years, rate)
    # The band's second rate is read the same way.
    assert "costPv(house, baseline, 0.02)" in js

    house = {"annualEnergyCost": 1602, "expectedAnnualLoss": 193}
    comp = {"annualEnergyCost": 1750, "expectedAnnualLoss": 210}
    expected = (1750 - 1602 + 210 - 193) * label_svg._annuity(years, rate)
    assert abs(label_svg._cost_pv(house, comp) - expected) < 1e-9
    # Nothing to compare against → no strip, rather than a zero that reads as
    # "the same to run".
    assert label_svg._cost_pv({"annualEnergyCost": 1}, {"expectedAnnualLoss": 1}) is None


def test_composite_confidence_follows_the_web_renderers_rules():
    """Same rollup as compositeConfidence() in label-core.js: capped one tier
    above the weakest, dropped a tier when two or more dimensions are missing,
    floored at Low when coverage is a third or less."""
    def cc(tiers, scores=None):
        scores = scores if scores is not None else [1] * len(tiers)
        return label_svg._composite_confidence({
            "dimensions": [{"key": str(i), "score": s} for i, s in enumerate(scores)],
            "confidence": {str(i): t for i, t in enumerate(tiers)}})

    assert cc(["high", "high", "high"])["tier"] == "high"
    # One Low drags the average down and caps the rest one tier above it.
    assert cc(["high", "high", "low"])["tier"] == "moderate"
    # Two dimensions unscored costs a tier even when what was scored is solid.
    assert cc(["high", "high", "high", "high"], [1, 1, None, None])["tier"] == "moderate"
    # A third or less of the roster scored → Low, whatever the tiers say.
    assert cc(["high", "high", "high"], [1, None, None])["tier"] == "low"
    assert cc([], []) is None


def test_wrapping_never_overflows_and_never_drops_text_silently():
    """There is no font to measure against (see the module docstring), so the
    estimate has to be the conservative side of every real system font — and text
    that doesn't fit has to end in an ellipsis rather than vanishing."""
    long = "Constitution Avenue Northwest " * 6
    lines = label_svg._wrap(long, 300, 12, max_lines=2)
    assert len(lines) == 2
    assert lines[-1].endswith("…"), lines
    for line in lines:
        assert label_svg._text_w(line, 12) <= 300 + 1e-9, line
    assert label_svg._wrap("", 300, 12) == []
    # A word longer than the column is kept (truncated), never dropped.
    assert label_svg._fit("x" * 500, 100, 12).endswith("…")


def test_a_bad_theme_can_be_refused_before_anything_is_scored():
    """``validate_theme`` is separate from the render so the endpoint can reject a
    typo without paying for a label first. Rendering is the cheap end of
    /label.svg; the scoring behind it is a dozen federal datasets and a metered
    unit of somebody's day."""
    label_svg.validate_theme("light")           # no exception
    for bad in ("drak", "", "LIGHT", None):
        try:
            label_svg.validate_theme(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was accepted as a theme")


def test_a_thin_payload_renders_rather_than_raising():
    """Every field is optional. A trimmed payload (an older self-hosted API, a
    cached response, a preset scored with no location) must produce a shorter
    sheet, not a 500."""
    # And a sparse sheet is still a full page: content that ends early leaves
    # white space at the bottom the way it would on paper, rather than cropping
    # the page to the last line drawn.
    empty = ET.fromstring(label_svg.render_sheet({}))
    assert empty.get("viewBox") == f"0 0 {label_svg.PAGE_W} {label_svg.PAGE_H}"

    for thin in ({}, {"dimensions": []}, {"dimensions": [{"key": "x"}]},
                 {"composite_score": 12.0},
                 # Half a coordinate: a payload with a lat and no lon is a payload
                 # with no location, not a crash.
                 {"house": {"lat": 35.13}}, {"house": {"lon": -89.99}},
                 {"house": {}}, {"location": {}}):
        ET.fromstring(label_svg.render_sheet(thin))


def test_the_download_name_survives_every_filesystem():
    assert label_svg.filename_for("1234 Cooper St, Memphis, TN 38104") == \
        "housing-label-1234-cooper-st-memphis-tn-38104.svg"
    assert label_svg.filename_for(None) == "housing-label.svg"
    assert label_svg.filename_for("../../etc/passwd") == "housing-label-etc-passwd.svg"
    name = label_svg.filename_for("Ünïcodé Straße 9, Köln")
    assert name.isascii() and " " not in name and "/" not in name, name
    # The button downloads through a blob, so the browser uses the name the page
    # picked, not the one the API sent — and two paths to the same file that name
    # it differently is a support question nobody can answer from the file.
    form = (_ROOT / "docs" / "label-form.js").read_text(encoding="utf-8")
    assert '"housing-label.svg"' in form, "the empty-caption name has drifted"
    assert '"housing-label-" + slug + ".svg"' in form


def test_the_frontend_asks_for_the_sheet_the_way_the_label_was_scored():
    """A saved sheet that dropped the reader's refinements would disagree with
    the label on screen — same address, different numbers, and no way to tell
    which is which once it is on paper. The button reuses the label's own query
    builder; this fails if that wiring is cut."""
    form = (_ROOT / "docs" / "label-form.js").read_text(encoding="utf-8")
    assert "/label.svg?" in form
    assert "buildDetectedParams().query" in form.split("function sheetQuery")[1][:400]


def test_the_export_buttons_wait_for_a_label_before_offering_one():
    """They live in the search form's own action row, which exists before any
    label does — so they ship disabled, and one function decides when they turn
    on. A button offering to export a label nobody has scored yet is a dead
    click, and a phone reader who scrolls to the foot of a thirteen-row card to
    find one is worse off than before it existed."""
    form = (_ROOT / "docs" / "label-form.js").read_text(encoding="utf-8")
    for cls in ("lf-print", "lf-svg"):
        assert f'class="reset {cls}" aria-disabled="true"' in form, \
            f"{cls} does not start unavailable"
        # aria-disabled, never the attribute: `disabled` drops a button out of the
        # tab order, so a keyboard or screen-reader user would not meet these two
        # — or the descriptions saying what they do — until after a label existed.
        # Dimming a control only sighted readers can find shows it to half the
        # audience. The guard below is what makes them inert instead.
        assert f'class="reset {cls}" disabled' not in form, f"{cls} is natively disabled"
    assert "function unavailable" in form and "function setAvailable" in form
    assert form.count("unavailable(") >= 3, "a press on an unavailable button is not guarded"
    # A sheet already being drawn owns its button until it lands. Availability is
    # otherwise recomputed from scratch on every render, so a mode switch or a
    # finished re-score during the fetch would hand the button back and let a
    # second press start a second download of the same sheet.
    assert "if (!drawing()) setAvailable(svgBtn" in form, \
        "a re-render can re-enable the button mid-download"
    assert 'aria-busy") === "true"' in form.split("function unavailable")[1][:220], \
        "busy must count as unavailable whoever set it"
    # Same rule for the density sweep, which dims its table rather than emptying it
    # while it re-scores: what is on screen then is the PREVIOUS answer, and
    # superseded is not printable. Every write of that class routes through one
    # setter, because the class is now part of the answer syncActions gives.
    assert 'classList.contains("is-busy")' in form.split("function syncActions")[1][:600], \
        "a re-scoring sweep counts as printable output"
    assert 'densResult.classList.add("is-busy")' not in form, "an is-busy write bypasses the setter"
    assert 'densResult.classList.remove("is-busy")' not in form, "an is-busy write bypasses the setter"
    # A refused press says which of the reasons it was — telling somebody to score
    # an address while a score is already running is both wrong and irritating —
    # and the explanation expires when the switch moves, so it never stands beside
    # a button that works again.
    assert "function whyUnavailable" in form and "function whySheetUnavailable" in form
    assert "if (busy) return" in form, "the reason does not distinguish a score in flight"
    assert "state.error) return" in form, "the reason does not distinguish a failed score"
    body = form.split("function syncActions", 1)[1].split("\n    function ", 1)[0]
    assert 'noteKind === "guard"' in body, \
        "a guard message can outlive the state that produced it"
    # The text and its kind are one fact, so only the setter writes either — a
    # direct write to the node leaves the kind describing a message that is gone.
    save = form.split("function saveSheet", 1)[1].split("\n    function ", 1)[0]
    assert "textContent = " not in save, "the save writes the note without its kind"
    assert save.count("actionsNote(") >= 3, "the save no longer reports through the note"
    # One switch, called from every place the answer can change: after a render,
    # and on both edges of a score.
    assert "function syncActions" in form
    assert form.count("syncActions()") >= 3, "the switch is not called from every path"
    # The old card-foot placement is gone from the markup and the stylesheet.
    assert "label-actions" not in form
    css = (_ROOT / "docs" / "label-core.css").read_text(encoding="utf-8")
    assert ".label-actions" not in css


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
