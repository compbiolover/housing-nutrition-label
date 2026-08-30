#!/usr/bin/env python3
"""Tests for the site icons (scripts/build_icons.py).

Guards the drift that put the pre-Harbor palette on the iOS home screen: the
CSS moved to Harbor, the hand-maintained favicon.ico / apple-touch-icon.png did
not, and nothing failed. Two directions are checked here —

  * the committed icon files match what the generator produces (the same
    assertion CI runs with --check), so a palette edit that skips the rebuild
    fails; and
  * the generator's PALETTE still matches the CSS custom properties it claims to
    mirror, so editing docs/style.css alone fails rather than silently leaving
    the icons a shade behind.

This file alone:  pytest tests/test_icons.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parent.parent

_GENERATOR = _ROOT / "scripts" / "build_icons.py"
_spec = importlib.util.spec_from_file_location("build_icons", _GENERATOR)
if _spec is None or _spec.loader is None:      # renamed/moved generator
    raise ImportError(f"cannot load the icon generator at {_GENERATOR} — did it move?")
build_icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_icons)

STYLE = _ROOT / "docs" / "style.css"


def _css_var(name: str) -> str:
    """The value of a `--name: #hex;` custom property in style.css (first hit,
    i.e. the light-theme :root block)."""
    m = re.search(rf"^\s*--{re.escape(name)}:\s*(#[0-9a-fA-F]{{3,8}})\s*;",
                  STYLE.read_text(), re.MULTILINE)
    assert m, f"--{name} not found in {STYLE.name}"
    return m.group(1).lower()


def test_committed_icons_match_the_generator():
    """Every generated icon on disk is byte-identical to a fresh render."""
    for path, want in build_icons.build().items():
        assert path.exists(), f"{path.name} is missing — run scripts/build_icons.py"
        assert path.read_bytes() == want, (
            f"{path.name} is out of date — run `python scripts/build_icons.py`")


def test_svg_geometry_is_derived_from_the_shared_constants():
    """The SVG is generated from the same ROOF/BODY/DOOR constants the rasters
    draw from. Moving a constant must move the markup — if the SVG ever goes back
    to being a hand-written literal, the vector and bitmap marks can drift apart
    silently, which is the failure this whole module exists to prevent."""
    before = build_icons.svg()
    original = build_icons.BODY
    try:
        build_icons.BODY = (7.0, 15.5, 25.0, 26.0)      # widen the house
        assert build_icons.svg() != before, "SVG markup ignored a geometry change"
    finally:
        build_icons.BODY = original
    assert build_icons.svg() == before                   # restored cleanly


def test_palette_tracks_the_stylesheet():
    """The icon palette mirrors docs/style.css, so a brand change there cannot
    quietly leave the icons on the old colours."""
    assert build_icons.PALETTE["tile"].lower() == _css_var("navy")
    assert build_icons.PALETTE["door"].lower() == _css_var("navy")
    assert build_icons.PALETTE["roof"].lower() == _css_var("accent-on-dark")
    assert build_icons.PALETTE["body"].lower() == _css_var("bg")


def test_data_green_is_not_used_as_a_brand_colour():
    """style.css scopes --green to score-bar fills ("grades keep their own
    scale"). A green roof read as a grade signal — as though the label were
    rating itself — which is why the mark moved to Harbor."""
    green = _css_var("green")
    assert green not in {v.lower() for v in build_icons.PALETTE.values()}
    assert green not in (_ROOT / "docs" / "favicon.svg").read_text().lower()


def test_apple_touch_icon_is_opaque_and_180px():
    """iOS masks the icon itself and composites it over the wallpaper, so any
    transparency would show the user's background through the corners."""
    from PIL import Image
    img = Image.open(_ROOT / "docs" / "apple-touch-icon.png")
    assert img.size == (180, 180), img.size
    assert img.mode == "RGB", f"{img.mode} — must be opaque, iOS applies its own mask"


def test_favicon_ico_carries_the_small_bitmaps():
    """A tab renders at 16px; shipping only a large bitmap leaves the browser to
    downscale it badly."""
    from PIL import Image
    ico = Image.open(_ROOT / "docs" / "favicon.ico")
    assert {(16, 16), (32, 32)} <= set(ico.info["sizes"]), ico.info["sizes"]


def test_pages_reference_the_icons_and_theme_colour():
    """Each page links all three icons and declares the brand navy, so browser
    chrome matches the tile."""
    navy = _css_var("navy")
    for page in sorted((_ROOT / "docs").glob("*.html")):
        html = page.read_text()
        for ref in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
            assert ref in html, f"{page.name} does not reference {ref}"
        assert f'name="theme-color" content="{navy}"' in html, page.name
