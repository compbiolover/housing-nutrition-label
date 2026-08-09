#!/usr/bin/env python3
"""The embeddable badge: a scored label rendered as a standalone SVG.

Until now the label existed in three forms — JSON, terminal ASCII, and DOM built
by ``docs/label-core.js`` — and every one of them requires the reader to be on
this site or holding this payload. There was nothing a third party could put on
their own page, which meant there was nothing whose display could be licensed,
and nothing to carry the mark anywhere it wasn't already.

An SVG is the format that fixes that, for one reason: it renders inside a plain
``<img src=…>``. No script, no CORS, no build step, no framework on the host
page. That is also the constraint the whole file is written around —

* **No links.** Browsers disable ``<a>`` inside an ``<img>``-loaded SVG, so the
  badge cannot click through to anything. The embed snippet therefore wraps it in
  an anchor host-side (see ``EMBED_SNIPPET``), and the wordmark is drawn into the
  image so attribution survives even when someone drops the anchor.
* **No web fonts.** A font-family that isn't on the reader's machine silently
  falls back, so nothing here may depend on text measuring a particular width.
  Every element is positioned absolutely and long text is truncated by character
  count rather than fitted.
* **Everything is untrusted.** The address is caller-supplied and lands in
  markup that a browser will parse as a document if it is ever opened directly.
  It goes through ``_esc`` and a length cap, and no other caller input reaches
  the output at all.

Two grades, not one
-------------------
The badge shows **the building** and **the site** as separate grades, which is
the same refusal ``research/building-vs-location-subscores.md`` argues for and
the site's own headline already makes. A single letter would travel further and
would be the wrong number: the two axes disagreeing is the information, and a
composite that hides a D behind an A is exactly the summary a badge is most
tempted to print.
"""

from __future__ import annotations

# ── Palette ───────────────────────────────────────────────────────────────────
# Mirrors GRADE_COLORS / GRADE_INK in docs/label-core.js; tests/test_badge.py
# fails if the two drift, because a badge grading a home one colour while the
# page behind it grades the same home another is worse than no badge.
GRADE_COLORS = {"A": "#16a34a", "B": "#84cc16", "C": "#eab308", "D": "#f97316", "F": "#dc2626"}
GRADE_INK = {"A": "#0f172a", "B": "#0f172a", "C": "#0f172a", "D": "#0f172a", "F": "#ffffff"}
UNSCORED = "#64748b"          # the slate label-core.js falls back to
UNSCORED_INK = "#ffffff"

# Surface tokens, per theme. Light mirrors --card/--border/--text/--muted in
# docs/style.css; dark mirrors that file's prefers-color-scheme block. The badge
# sits on somebody else's page, so it paints its own ground rather than
# inheriting one it can't see.
THEMES = {
    "light": {"bg": "#fffdf9", "border": "#e8e3da", "text": "#22262e", "muted": "#6b6960"},
    "dark": {"bg": "#18202e", "border": "#29313f", "text": "#e8e6e0", "muted": "#9b988e"},
}
THEME_NAMES = ("auto", "light", "dark")

# No web fonts are available (see the module docstring), so this is the ordinary
# system stack and the layout must not depend on what it resolves to.
FONT = ("system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif")

WORDMARK = "HOUSING NUTRITION LABEL™"
HOME = "housinglabel.dev"

# The address is the only free text on the badge. Capped rather than fitted,
# because without a known font there is no width to fit to.
MAX_ADDRESS = 44

STYLE_NAMES = ("full", "compact")

# ── Geometry ──────────────────────────────────────────────────────────────────
# Expressed once, as the constants the markup is generated from, so the two
# variants cannot drift apart in the way a pair of hand-written literals would
# (the lesson scripts/build_icons.py records).
FULL = {
    "w": 360, "h": 116, "pad": 14,
    "axis_y": 46, "axis_h": 52, "axis_gap": 10,
    "chip_w": 30, "chip_h": 24,
}
# Wider than the wordmark strictly needs. The mark and the chips are positioned
# from opposite edges, so the gap between them is the only slack absorbing a
# fallback font wider than the one this was measured against — and a badge whose
# wordmark runs into its grades is the one failure a host page can't fix.
COMPACT = {"w": 300, "h": 40, "pad": 8, "chip_w": 26, "chip_h": 24}

_AXES = (("THE BUILDING", "construction"), ("THE SITE", "location"))


def _esc(text) -> str:
    """XML-escape caller text. Quotes included: this lands in attributes too."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def _ordinal(n: int) -> str:
    """1 → 1st. Mirrors ordSuffix() in docs/label-core.js, teens included."""
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _clip(text: str, limit: int = MAX_ADDRESS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,") + "…"


def _axis(payload: dict, key: str) -> tuple[str, int | None]:
    """The (grade, percentile) pair for one headline axis.

    Falls back to an em dash and None rather than inventing a grade: an axis can
    legitimately be unscored (offline, or a parcel with no tract), and a badge
    that printed "F" for "we don't know" would be a libel about somebody's house.
    """
    grade = payload.get(f"{key}_national_grade")
    grade = grade if grade in GRADE_COLORS else "—"
    score = payload.get(f"{key}_score")
    return grade, (None if score is None else round(float(score)))


def _theme_css(theme: str) -> str:
    """CSS custom properties for the requested theme.

    ``auto`` ships both and lets the reader's own setting choose. A media query
    inside an SVG is honoured even when the SVG is loaded through ``<img>``,
    which is the only reason the badge can be theme-aware at all on a page whose
    background it cannot see.
    """
    light, dark = THEMES["light"], THEMES["dark"]
    base = dark if theme == "dark" else light
    css = (":root{"
           f"--bg:{base['bg']};--bd:{base['border']};"
           f"--tx:{base['text']};--mu:{base['muted']}}}")
    if theme == "auto":
        css += ("@media(prefers-color-scheme:dark){:root{"
                f"--bg:{dark['bg']};--bd:{dark['border']};"
                f"--tx:{dark['text']};--mu:{dark['muted']}}}}}")
    return css


def _chip(x: float, y: float, w: float, h: float, grade: str, size: float) -> str:
    """A grade letter on its own coloured field — the one element that carries
    colour, and the reason colour and letter can never disagree: both are read
    from the same `grade`."""
    bg = GRADE_COLORS.get(grade, UNSCORED)
    ink = GRADE_INK.get(grade, UNSCORED_INK)
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{bg}"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2}" fill="{ink}" font-size="{size}" '
            f'font-weight="700" text-anchor="middle" dominant-baseline="central">'
            f'{_esc(grade)}</text>')


def _full(payload: dict, address: str | None, theme: str) -> str:
    g = FULL
    pad = g["pad"]
    cells = []
    cell_w = (g["w"] - 2 * pad - g["axis_gap"]) / 2
    for i, (cap, key) in enumerate(_AXES):
        grade, pct = _axis(payload, key)
        x = pad + i * (cell_w + g["axis_gap"])
        y = g["axis_y"]
        reading = "not scored" if pct is None else f"{pct}{_ordinal(pct)} percentile"
        cells.append(
            f'<rect x="{x}" y="{y}" width="{cell_w}" height="{g["axis_h"]}" rx="6" '
            f'fill="none" stroke="var(--bd)"/>'
            f'<text x="{x + 11}" y="{y + 17}" fill="var(--mu)" font-size="9" '
            f'font-weight="600" letter-spacing="0.6">{cap}</text>'
            f'<text x="{x + 11}" y="{y + 38}" fill="var(--tx)" font-size="12">'
            f'{reading}</text>'
            + _chip(x + cell_w - g["chip_w"] - 10, y + (g["axis_h"] - g["chip_h"]) / 2,
                    g["chip_w"], g["chip_h"], grade, 14))
    sub = _esc(_clip(address)) if address else ""
    subline = (f'<text x="{pad}" y="{36}" fill="var(--mu)" font-size="11">{sub}</text>'
               if sub else "")
    return (
        f'<rect x="0.5" y="0.5" width="{g["w"] - 1}" height="{g["h"] - 1}" rx="10" '
        f'fill="var(--bg)" stroke="var(--bd)"/>'
        f'<text x="{pad}" y="21" fill="var(--tx)" font-size="11" font-weight="700" '
        f'letter-spacing="0.7">{WORDMARK}</text>'
        + subline +
        "".join(cells) +
        f'<text x="{pad}" y="{g["h"] - 10}" fill="var(--mu)" font-size="9.5">{HOME}</text>')


def _compact(payload: dict, address: str | None, theme: str) -> str:
    # `address` is deliberately dropped here: at 40px tall there is no line for it
    # that wouldn't be truncated to uselessness, and a badge that shows half an
    # address is worse than one that shows none. Callers who need it use `full`.
    g = COMPACT
    pad = g["pad"]
    chips = []
    for i, (cap, key) in enumerate(_AXES):
        grade, _pct = _axis(payload, key)
        x = g["w"] - pad - (2 - i) * (g["chip_w"] + 4) + 4
        chips.append(_chip(x, (g["h"] - g["chip_h"]) / 2, g["chip_w"], g["chip_h"], grade, 13))
    return (
        f'<rect x="0.5" y="0.5" width="{g["w"] - 1}" height="{g["h"] - 1}" rx="8" '
        f'fill="var(--bg)" stroke="var(--bd)"/>'
        f'<text x="{pad}" y="17" fill="var(--tx)" font-size="9" font-weight="700" '
        f'letter-spacing="0.5">{WORDMARK}</text>'
        f'<text x="{pad}" y="30" fill="var(--mu)" font-size="8.5">'
        f'BUILDING &#183; SITE</text>' + "".join(chips))


_RENDERERS = {"full": (_full, FULL), "compact": (_compact, COMPACT)}


def render_badge(payload: dict, *, style: str = "full", theme: str = "auto",
                 address: str | None = None) -> str:
    """Render a scored label payload as a self-contained SVG document.

    ``payload`` is what ``simulate.house.label_payload`` returns. Only the two
    headline axes are read, so a trimmed payload works and a badge never depends
    on a field the API might stop sending.

    Raises ValueError on an unknown style or theme — an unrecognised query
    parameter should be a 400 at the edge, not a silent fallback that leaves a
    caller wondering why ``theme=drak`` looks the same as no theme at all.
    """
    if style not in _RENDERERS:
        raise ValueError(f"unknown badge style {style!r}; choose one of: "
                         f"{', '.join(STYLE_NAMES)}")
    if theme not in THEME_NAMES:
        raise ValueError(f"unknown badge theme {theme!r}; choose one of: "
                         f"{', '.join(THEME_NAMES)}")
    draw, geom = _RENDERERS[style]
    body = draw(payload, address, theme)
    grades = ", ".join(f"{cap.lower().removeprefix('the ')} {_axis(payload, k)[0]}"
                       for cap, k in _AXES)
    # <title> is the accessible name a screen reader reads out of an <img>-loaded
    # SVG, and the alt text most embedders will forget to write.
    title = f"Housing Nutrition Label: {grades}"
    if address:
        title += f" — {_clip(address)}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{geom["w"]}" '
        f'height="{geom["h"]}" viewBox="0 0 {geom["w"]} {geom["h"]}" '
        f'role="img" aria-label="{_esc(title)}" font-family="{FONT}">'
        f'<title>{_esc(title)}</title>'
        f'<style>{_theme_css(theme)}</style>'
        f'{body}</svg>')


EMBED_SNIPPET = (
    '<a href="https://housinglabel.dev/label.html">\n'
    '  <img src="{api}/badge?address={address}" width="360" height="116"\n'
    '       alt="Housing Nutrition Label — the building and the site, graded">\n'
    '</a>'
)
