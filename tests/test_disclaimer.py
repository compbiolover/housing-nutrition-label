#!/usr/bin/env python3
"""The disclaimer reaches every surface the label does, in one wording.

``housing_label.legal`` is the source of truth (see that module for why the
notice travels with the label rather than living on a terms page). These tests
are the enforcement: a new renderer that forgets the notice, or a second copy of
the text that drifts from the first, fails here rather than shipping. No
network.

Run directly:  python tests/test_disclaimer.py
"""

from __future__ import annotations

import pathlib
import re
import sys
import xml.etree.ElementTree as ET

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label import badge  # noqa: E402
from housing_label.legal import DISCLAIMER, DISCLAIMER_SHORT  # noqa: E402
from housing_label.simulate.house import label_payload  # noqa: E402

_DOCS = _ROOT / "docs"
_LABEL_CORE = _DOCS / "label-core.js"


def _parts():
    """A minimal (cfg, r, label) triple — the same hand-rolled shape
    tests/test_label_payload.py scores, so no location resolve is needed."""
    cfg = {"year_built": 2000, "construction": "frame", "foundation": "slab",
           "condition": "average", "units": 1, "sqft": 2000, "lot_acres": 0.25,
           "flood_zone": "X", "value": 250000, "value_source": None,
           "lat": 35.13, "lon": -89.99}
    r = {"total_loss": 115.4, "fire_loss": 7.0, "total_score": 64.0}
    label = {
        "dimensions": [
            {"key": "resilience", "label": "Disaster Resilience", "score": 64.1,
             "national_grade": "B"},
            {"key": "energy", "label": "Energy Efficiency", "score": 77.0,
             "national_grade": "B"},
        ],
        "composite_score": 70.6, "composite_national_grade": "B", "n_scored": 2,
        "construction_score": 70.6, "construction_national_grade": "B",
        "construction_n_scored": 2, "construction_raw_mean": 70.6,
        "location_score": None, "location_national_grade": None,
        "location_n_scored": 0, "location_raw_mean": None,
        "resilience_site_score": None, "resilience_building_score": None,
        "resilience_building_multiplier": None,
        "metrics": {"est_monthly_energy_cost": 133.0},
        "census_tract": None, "location_notes": {}, "location": None,
    }
    return cfg, r, label


def test_the_payload_carries_the_notice():
    """Every consumer of the label — the CLI's --json, the HTTP API, the web
    renderer, and anyone else's code — reads the same field, so a label rendered
    off-site can carry the same notice ours does."""
    payload = label_payload(*_parts())
    assert payload["disclaimer"] == DISCLAIMER


def test_the_notice_says_both_halves():
    """'Not advice' alone tells a reader nothing about how much weight the number
    carries. What it *is* (a model, not a look at this house) is the useful half,
    and dropping either one is what makes fine print misleading."""
    for text in (DISCLAIMER, DISCLAIMER_SHORT):
        low = text.lower()
        assert "advice" in low
        assert "modeled estimate" in low
        assert "inspection" in low and "appraisal" in low
    assert "informational purposes only" in DISCLAIMER.lower()


def test_the_notice_is_ascii():
    """It is rendered into SVG, HTML, JSON, and a fixed-width terminal box. One
    of those is always the surface where a clever character breaks."""
    for text in (DISCLAIMER, DISCLAIMER_SHORT):
        assert text.isascii(), text


def _js_string(name: str) -> str:
    """Read a `var NAME = "..." + "...";` concatenation out of label-core.js."""
    src = _LABEL_CORE.read_text(encoding="utf-8")
    m = re.search(rf"var\s+{re.escape(name)}\s*=\s*(.*?);\n", src, re.DOTALL)
    assert m, f"{name} not found in {_LABEL_CORE} — did the renderer move?"
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))


def test_the_web_renderers_fallback_copy_has_not_drifted():
    """label-core.js keeps its own copy for payloads that predate the field (a
    cached response, an older self-hosted API, the Examples page's fixtures).
    Two disclaimers that disagree are worse than either alone."""
    assert _js_string("DISCLAIMER_FALLBACK") == DISCLAIMER


def test_the_card_renderer_draws_it():
    """Inside the card, which is the unit that gets screenshotted and embedded —
    not in the page footer, which travels with nothing."""
    src = _LABEL_CORE.read_text(encoding="utf-8")
    assert "legalNote(data)" in src, "renderCard() no longer draws the notice"
    assert "legalNote: legalNote" in src, "the note must stay exported (label-form.js)"
    # The views that draw tables instead of cards have to ask for it themselves.
    form = (_DOCS / "label-form.js").read_text(encoding="utf-8")
    assert form.count("LC.legalNote(") >= 2, "the timeline / density panels dropped it"


def test_every_page_on_the_site_carries_it():
    pages = sorted(_DOCS.glob("*.html"))
    assert pages, "no docs pages found"
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert DISCLAIMER in text, f"{page.name} has no disclaimer in its footer"


def test_the_readme_carries_it():
    """Prose, not the constant: the README sets parts of the notice in bold, so
    it is matched on the phrases that survive the markup rather than verbatim."""
    text = (_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "## disclaimer" in text
    assert "informational purposes only" in text
    assert "real estate advice" in text
    # The front door says it too — a reader who never scrolls still sees it.
    assert "informational purposes only" in text[:text.index("## current status")]


def test_the_badge_draws_the_notice_and_names_it_in_full():
    """The badge is the copy of the label read with none of our pages, and none
    of our fine print, anywhere near it. Both styles draw a notice; the full text
    rides along in <desc> for anyone who wants it spelled out."""
    for style in badge.STYLE_NAMES:
        svg = badge.render_badge(
            {"construction_score": 63.9, "construction_national_grade": "B",
             "location_score": 70.3, "location_national_grade": "B"},
            style=style, address="123 Main St, Memphis, TN")
        root = ET.fromstring(svg)
        drawn = " ".join(e.text or "" for e in root.iter() if e.tag.endswith("text"))
        assert "not advice" in drawn.lower(), f"{style}: nothing drawn on the face"
        desc = [e.text for e in root.iter() if e.tag.endswith("desc")]
        assert desc == [DISCLAIMER], f"{style}: {desc}"
        assert root.get("aria-describedby") == "hnl-disclaimer", style
        # The accessible name ends on the short form: it is announced on every
        # encounter with the image, so the paragraph belongs in <desc>.
        assert (root.get("aria-label") or "").endswith(DISCLAIMER_SHORT), style


def test_the_api_says_it_where_an_integrator_reads_it():
    """/docs is where somebody decides what these numbers are, and that happens
    before they ever look at a response body."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_the_api_says_it_where_an_integrator_reads_it "
              "(fastapi not installed)")
        return
    from housing_label.api import app
    spec = TestClient(app).get("/openapi.json").json()
    assert spec["info"]["description"] == DISCLAIMER


def test_the_embed_snippet_tells_the_embedder_too():
    """Most embedders paste this verbatim, and the alt text is the copy a reader
    with images off gets."""
    assert "not advice" in badge.EMBED_SNIPPET.lower()


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
