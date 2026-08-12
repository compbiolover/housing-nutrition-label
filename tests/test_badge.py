#!/usr/bin/env python3
"""The embeddable SVG badge (housing_label.badge).

No network and no FastAPI — the renderer is a pure function of a payload, which
is most of why it lives in its own module.

The badge is the one artifact that ends up on somebody else's page, under our
mark, outside our control once it is there. So the assertions here are weighted
towards the failures a third-party page can't fix and we might never see: a grade
coloured differently from the same grade on our own site, a fabricated letter
where the truth is "not scored", and caller text reaching markup unescaped.

Run directly:  python tests/test_badge.py
"""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET

from housing_label import badge

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_LABEL_CORE = _ROOT / "docs" / "label-core.js"

_SCORED = {
    "construction_score": 63.9, "construction_national_grade": "B",
    "location_score": 70.3, "location_national_grade": "B",
}


def _js_map(name: str) -> dict:
    """Parse `var NAME = { A: "#hex", ... };` out of docs/label-core.js."""
    src = _LABEL_CORE.read_text()
    m = re.search(rf"var\s+{re.escape(name)}\s*=\s*\{{(.*?)\}}", src, re.DOTALL)
    assert m, f"{name} not found in {_LABEL_CORE} — did the renderer move?"
    return dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"', m.group(1)))


def test_the_badge_palette_matches_the_page_it_will_sit_next_to():
    """A badge grading a home one colour while the site grades it another is
    worse than no badge — the reader can see both and has no way to tell which
    is stale. Editing docs/label-core.js alone must fail here."""
    assert badge.GRADE_COLORS == _js_map("GRADE_COLORS")
    assert badge.GRADE_INK == _js_map("GRADE_INK")


def test_every_style_and_theme_renders_well_formed_svg():
    for style in badge.STYLE_NAMES:
        for theme in badge.THEME_NAMES:
            svg = badge.render_badge(_SCORED, style=style, theme=theme,
                                     address="123 Main St, Memphis, TN")
            root = ET.fromstring(svg)          # raises on malformed markup
            assert root.tag.endswith("svg")
            geom = badge.FULL if style == "full" else badge.COMPACT
            assert root.get("width") == str(geom["w"])
            assert root.get("height") == str(geom["h"])
            assert root.get("viewBox") == f'0 0 {geom["w"]} {geom["h"]}'


def test_colour_and_letter_are_read_from_the_same_grade():
    """The chip fill and the letter on it can never disagree, for any grade."""
    for grade, colour in badge.GRADE_COLORS.items():
        svg = badge.render_badge(
            {"construction_national_grade": grade, "construction_score": 50,
             "location_national_grade": grade, "location_score": 50})
        assert svg.count(f'fill="{colour}"') == 2, grade
        letters = [e.text for e in ET.fromstring(svg).iter()
                   if e.tag.endswith("text") and e.text == grade]
        assert len(letters) == 2, f"{grade}: {letters}"


def test_an_unscored_axis_is_never_given_a_letter():
    """An axis can legitimately be unscored — offline, or a parcel with no tract.
    Printing "F" for "we don't know" would be a libel about somebody's house."""
    svg = badge.render_badge({}, style="full")
    assert "not scored" in svg
    assert badge.UNSCORED in svg
    for grade, colour in badge.GRADE_COLORS.items():
        assert colour not in svg, f"an unscored badge must not show {grade}"
    # Half-scored is the more likely case and must not promote the missing half.
    half = badge.render_badge({"construction_score": 63.9, "construction_national_grade": "B"})
    assert "not scored" in half and badge.GRADE_COLORS["B"] in half


def test_caller_text_cannot_reach_the_markup():
    """The address is caller-supplied and lands in a document a browser will
    parse if it is ever opened directly rather than through <img>."""
    hostile = '"><script>alert(1)</script><x y=\'z\' & more'
    svg = badge.render_badge(_SCORED, address=hostile)
    root = ET.fromstring(svg)                   # raises if it broke out of a tag
    # In the raw document it is inert text, not markup.
    assert "<script" not in svg and "</script>" not in svg
    assert "&lt;script&gt;" in svg
    assert "alert(1)" in svg, "the text should survive, escaped — not vanish"
    # And it reaches the aria-label attribute — which the quote in `hostile`
    # would have closed early. Round-tripping back to the original string is the
    # proof: the parser saw one attribute, not an attribute plus injected markup.
    assert badge._clip(hostile) in (root.get("aria-label") or "")


def test_a_long_address_is_truncated_rather_than_fitted():
    """There is no web font, so there is no width to fit to (see the module
    docstring). Truncation is by character count and must be visible."""
    svg = badge.render_badge(_SCORED, address="9" * 200 + " Street")
    ET.fromstring(svg)
    assert "…" in svg
    # The address is the only caller text on the badge, so it's found by its own
    # content rather than by being the longest string drawn — the standing
    # footnote line (housinglabel.dev + the disclaimer) is longer than any
    # address is allowed to be, and it is not what this budget governs.
    drawn = [e.text or "" for e in ET.fromstring(svg).iter() if e.tag.endswith("text")]
    address = max((t for t in drawn if t.startswith("9")), key=len, default="")
    assert address, drawn
    assert len(address) <= badge.MAX_ADDRESS, address
    # Whitespace is collapsed, so a padded address doesn't eat the budget.
    assert "  " not in badge._clip("a     b")


def test_auto_is_the_only_theme_that_ships_two_palettes():
    """`auto` is why the badge can suit a page whose background it cannot see —
    a media query inside an SVG is honoured even through <img>."""
    auto = badge.render_badge(_SCORED, theme="auto")
    assert "prefers-color-scheme:dark" in auto
    assert badge.THEMES["light"]["bg"] in auto and badge.THEMES["dark"]["bg"] in auto
    light = badge.render_badge(_SCORED, theme="light")
    assert "prefers-color-scheme" not in light
    assert badge.THEMES["light"]["bg"] in light and badge.THEMES["dark"]["bg"] not in light
    dark = badge.render_badge(_SCORED, theme="dark")
    assert "prefers-color-scheme" not in dark
    assert badge.THEMES["dark"]["bg"] in dark


def test_the_mark_is_drawn_in_rather_than_left_to_the_embedder():
    """Browsers disable <a> inside an <img>-loaded SVG, so the badge cannot link
    anywhere. Attribution therefore has to survive in the pixels."""
    for style in badge.STYLE_NAMES:
        svg = badge.render_badge(_SCORED, style=style)
        assert badge.WORDMARK in svg, style
        assert "™" in svg, style
    assert badge.HOME in badge.render_badge(_SCORED, style="full")
    # And the snippet the docs hand out supplies the click-through host-side.
    assert "<a href=" in badge.EMBED_SNIPPET and "alt=" in badge.EMBED_SNIPPET


def test_an_unknown_style_or_theme_is_an_error_not_a_silent_fallback():
    """`theme=drak` looking identical to no theme leaves a caller debugging a
    badge that was never going to change."""
    for bad in ({"style": "enormous"}, {"theme": "drak"}):
        try:
            badge.render_badge(_SCORED, **bad)
        except ValueError as exc:
            assert "choose one of" in str(exc), exc
        else:
            raise AssertionError(f"{bad} should have raised")


def test_percentiles_read_as_english_including_the_teens():
    assert badge._ordinal(1) == "st" and badge._ordinal(2) == "nd" and badge._ordinal(3) == "rd"
    assert badge._ordinal(11) == "th" and badge._ordinal(12) == "th" and badge._ordinal(13) == "th"
    assert badge._ordinal(21) == "st" and badge._ordinal(111) == "th"
    assert "64th percentile" in badge.render_badge(_SCORED)


def _drawn_text(svg: str) -> str:
    """Only what a reader sees — <text> content, not <title> or aria-label."""
    return " ".join(e.text or "" for e in ET.fromstring(svg).iter()
                    if e.tag.endswith("text"))


def test_compact_drops_the_address_from_the_face_but_not_from_the_name():
    """At 40px there is no line for an address that wouldn't be truncated to
    uselessness, so compact doesn't draw one. The accessible name still carries
    it: a screen-reader user should be told which house is being graded, and
    the embedder published that address by choosing to embed it."""
    addr = "123 Main St, Memphis"
    compact = badge.render_badge(_SCORED, style="compact", address=addr)
    assert addr not in _drawn_text(compact)
    assert addr in (ET.fromstring(compact).get("aria-label") or "")
    assert addr in _drawn_text(badge.render_badge(_SCORED, style="full", address=addr))


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
