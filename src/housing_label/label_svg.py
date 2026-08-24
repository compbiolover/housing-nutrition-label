#!/usr/bin/env python3
"""The printable sheet: the whole label as one page of vector, for paper.

``badge.py`` renders the label small enough to sit in somebody else's sidebar.
This renders the opposite artifact — every dimension, the two headline axes, the
running-cost line, and the full disclaimer, laid out on one US Letter page — for
the two things a reader does with a label once they care about the house: print
it, and put it in a file next to the inspection report.

Why a second renderer rather than screenshotting the page
---------------------------------------------------------
The web card is HTML, and HTML has no page. Everything about it that works on a
screen — a scrollable column, rows that open on tap, a dark theme, a layout that
reflows at 380px — is either meaningless or actively wrong once the thing is a
sheet of paper. So the two surfaces are drawn separately and constrained
differently:

* **The sheet has an edge.** Content is budgeted against ``PAGE_H`` and the row
  pitch is fixed, so a 13-dimension label lands inside one page rather than
  breaking across two at whatever point the browser chose. Nothing is hidden to
  achieve that: the disclosure panels the screen hides behind a tap are the one
  thing left off, because their numbers are the API's own ``details`` and a page
  that carried all thirteen of them would be a booklet, not a label.
* **The sheet has no dark mode.** Paper is white and toner is expensive, so
  ``theme`` defaults to ``light`` here where the badge defaults to ``auto``.
  Dark is still available for an SVG that will be embedded in a dark document.
* **Colour is never the only channel.** Every grade appears as a letter *and* a
  bar length *and* a number, so the sheet survives a grayscale printer, a fax,
  and a photocopy of a photocopy — the same rule the site follows for colour
  blindness, which paper enforces far more often.

Drawn as text, not as paths
---------------------------
Every string is a real ``<text>`` element, so the sheet stays searchable,
selectable, and re-editable in Illustrator or Inkscape after it leaves here.
That costs the same thing it costs the badge: no web fonts and no text
measurement, so every element is positioned absolutely and long strings are
truncated or wrapped against an *estimated* advance width (``_ADVANCE``) that
deliberately over-estimates. A line that comes out short is a layout that
breathes; a line that comes out long is a layout that collides.

Two further constraints the badge doesn't have, both from print tooling:

* **No ``dominant-baseline``.** Browsers honour it; several print and design
  applications do not, and a grade letter that slides out of its chip in
  Illustrator is a broken document. Vertical centring here is arithmetic
  (``_center_baseline``) against the font size.
* **Physical units on the root.** ``width="8.5in"`` (with a px ``viewBox``)
  means the file imports and prints at true size instead of at whatever a
  consumer guesses 816 user units means.

Everything caller-supplied — the address, the location label, the caveats — goes
through ``_esc`` and a width cap, the same as in ``badge.py``: an SVG is a
document a browser will parse if it is ever opened directly.
"""

from __future__ import annotations

import math

# badge.py is where the SVG primitives and the grade palette live; importing
# them (rather than restating them) is what keeps a printed grade the same
# colour as the same grade on the site and on an embedder's page. The palette
# has a drift test against docs/label-core.js — see tests/test_badge.py — and
# that test protects this file for free.
from housing_label.badge import (
    FONT, GRADE_COLORS, GRADE_INK, HOME, THEME_NAMES, UNSCORED, UNSCORED_INK,
    WORDMARK, _esc, _ordinal, _theme_css,
)
from housing_label.confidence import year_built_display
from housing_label.legal import DISCLAIMER, DISCLAIMER_SHORT

# ── The page ─────────────────────────────────────────────────────────────────
# US Letter at the 96 px/in the SVG user unit is defined against. A4 is narrower
# (8.27in), so a Letter-width sheet scales down to fit it; the reverse — an A4
# sheet on Letter — would leave a margin nobody asked for on the wider paper.
PAGE_W = 816
PAGE_H = 1056
# 0.5in. Below this, consumer inkjets start clipping, and the sheet is meant to
# come out of whatever printer is in the house.
PAD = 48
COL = PAGE_W - 2 * PAD

# Estimated advance width as a fraction of the font size, per weight. There is no
# web font and no way to measure text, so these are deliberately generous: the
# system stack resolves to Segoe UI, Roboto, or SF depending on the machine, and
# the widest of those has to fit.
_ADVANCE = {400: 0.52, 600: 0.55, 700: 0.57, 800: 0.58}

# Mirrors GROUP_LABEL in docs/label-core.js. Context dimensions are shown and not
# graded (see simulate/dimensions.py); the heading is the only place that says so
# on a sheet with no room for the paragraph.
_GROUPS = [
    ("construction", "The building itself"),
    ("location", "The site & environment"),
    ("context", "Neighborhood context (not graded)"),
]
_AXES = [
    ("The building", "construction", "how it is built — envelope, materials, hazard"),
    ("The site", "location", "what surrounds it — air, noise, water, services"),
]

_CONF_RANK = {"low": 1, "moderate": 2, "high": 3}
_CONF_WORD = {"low": "Low", "moderate": "Moderate", "high": "High"}

# The glyph channel (●/◐/○) that the web card pairs with its word is dropped
# here. At 9.5px on paper the three glyphs are one dot of ink apart, and unlike a
# screen there is no zoom — so the sheet carries the word alone.
_WALL_LABELS = {
    "frame": "wood frame", "brick": "brick", "brick-frame": "brick veneer",
    "block": "concrete block", "icf": "ICF", "sip": "SIP", "steel": "steel frame",
    "stone": "stone", "vinyl": "vinyl-sided frame",
}


# ── Text metrics (estimated — see the module docstring) ──────────────────────
def _num(v) -> str:
    """Compact number for an attribute: 12.0 → 12, 12.50 → 12.5."""
    s = f"{float(v):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _text_w(text: str, size: float, weight: int = 400) -> float:
    return len(text) * size * _ADVANCE[weight]


def _fit(text, width: float, size: float, weight: int = 400) -> str:
    """One line, truncated with an ellipsis if it would overrun ``width``."""
    text = " ".join(str(text).split())
    if not text or _text_w(text, size, weight) <= width:
        return text
    keep = max(1, int(width / (size * _ADVANCE[weight])) - 1)
    return text[:keep].rstrip(" ,;:·") + "…"


def _wrap(text, width: float, size: float, weight: int = 400, max_lines: int = 2) -> list[str]:
    """Greedy word wrap to at most ``max_lines``; the overflow is ellipsised onto
    the last line rather than dropped, so a truncated caveat still reads as one."""
    words = " ".join(str(text).split()).split(" ")
    if words == [""]:
        return []
    lines, cur, i = [], "", 0
    while i < len(words):
        trial = words[i] if not cur else cur + " " + words[i]
        if not cur or _text_w(trial, size, weight) <= width:
            cur, i = trial, i + 1
            continue
        lines.append(cur)
        cur = ""
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
        i = len(words)
    if i < len(words) and lines:
        lines[-1] = _fit(lines[-1] + " " + " ".join(words[i:]), width, size, weight)
    return lines


def _center_baseline(cy: float, size: float) -> float:
    """Baseline that visually centres a line of ``size`` on ``cy``.

    Not ``dominant-baseline="central"``: browsers honour that attribute, several
    print and design applications quietly ignore it, and a grade letter sitting
    outside its chip in Illustrator is a broken document. 0.355em is the usual
    cap-height/2 for the system stack.
    """
    return cy + size * 0.355


# ── Primitives ───────────────────────────────────────────────────────────────
def _t(x, y, text, size, *, fill="var(--tx)", weight=None, anchor=None,
       ls=None, raw=False) -> str:
    attrs = [f'x="{_num(x)}"', f'y="{_num(y)}"', f'font-size="{_num(size)}"', f'fill="{fill}"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if ls is not None:
        attrs.append(f'letter-spacing="{_num(ls)}"')
    return f'<text {" ".join(attrs)}>{text if raw else _esc(text)}</text>'


def _rule(y, x=PAD, w=COL, color="var(--bd)") -> str:
    return (f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="1" '
            f'fill="{color}"/>')


def _chip(x, y, w, h, grade: str, size: float, rx: float = 4) -> str:
    """A grade letter on its own coloured field. Colour and letter are read from
    the same value, so they cannot disagree — and the letter is what carries the
    grade when the sheet is photocopied in black and white."""
    bg = GRADE_COLORS.get(grade, UNSCORED)
    ink = GRADE_INK.get(grade, UNSCORED_INK)
    return (f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
            f'rx="{_num(rx)}" fill="{bg}"/>'
            + _t(x + w / 2, _center_baseline(y + h / 2, size), grade, size,
                 fill=ink, weight=700, anchor="middle"))


def _bar(x, y, w, h, score, grade: str) -> str:
    """Score bar: a track, a fill as long as the score, and a hairline around
    both. The hairline is what keeps the bar legible when a printer drops light
    fills, and it is why an unscored row still reads as an empty bar rather than
    as nothing at all."""
    pct = 0.0 if score is None else max(0.0, min(100.0, float(score)))
    fill = GRADE_COLORS.get(grade, UNSCORED)
    out = (f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
           f'rx="{_num(h / 2)}" fill="var(--track)"/>')
    if pct > 0:
        out += (f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w * pct / 100)}" '
                f'height="{_num(h)}" rx="{_num(h / 2)}" fill="{fill}"/>')
    return out + (f'<rect x="{_num(x + 0.5)}" y="{_num(y + 0.5)}" width="{_num(w - 1)}" '
                  f'height="{_num(h - 1)}" rx="{_num(h / 2)}" fill="none" '
                  f'stroke="var(--bd)"/>')


# ── Payload reading ──────────────────────────────────────────────────────────
def _grade_of(d: dict) -> str:
    """The grade the API sent, falling back to the score's own band — the same
    rule (and the same thresholds) as ``gradeOf`` in docs/label-core.js. Returns
    an em dash rather than inventing a letter for an unscored dimension."""
    g = str(d.get("national_grade") or "")
    if g in GRADE_COLORS:
        return g
    s = d.get("score")
    if not isinstance(s, (int, float)):
        return "—"
    return "A" if s >= 80 else "B" if s >= 60 else "C" if s >= 40 else "D" if s >= 20 else "F"


def _composite_confidence(payload: dict):
    """Coverage-penalized composite confidence — the Python of
    ``compositeConfidence`` in docs/label-core.js, kept in step so the printed
    sheet and the screen it was printed from cannot report different data
    quality for the same house."""
    conf = payload.get("confidence") or {}
    dims = payload.get("dimensions") or []
    n_total = len(dims)
    ranks, n_scored = [], 0
    for d in dims:
        if isinstance(d.get("score"), (int, float)):
            n_scored += 1
            r = _CONF_RANK.get(conf.get(d.get("key")))
            if r:
                ranks.append(r)
    if not ranks or not n_total:
        return None
    # int(x + 0.5), not round(): JS Math.round is half-up and Python's round is
    # half-to-even, and 2.5 is a reachable average of three tiers.
    avg = int(sum(ranks) / len(ranks) + 0.5)
    capped = min(avg, min(ranks) + 1)
    coverage, n_missing = n_scored / n_total, n_total - n_scored
    rank = 1 if coverage <= 1 / 3 else max(1, capped - 1) if n_missing >= 2 else capped
    return {"tier": ["low", "moderate", "high"][rank - 1],
            "n_scored": n_scored, "n_total": n_total}


def _r(v: float) -> int:
    """JS Math.round semantics (half up), so a printed dollar figure rounds the
    way the same figure rounded on screen."""
    return int(math.floor(v + 0.5))


def _annuity(years: int, rate: float) -> float:
    return years if rate == 0 else (1 - (1 + rate) ** -years) / rate


def _cost_pv(house: dict, comparable: dict, rate: float = 0.04):
    """Present value over a 30-year mortgage of the annual (energy + expected
    loss) gap against a comparable. Mirrors ``costPv`` in docs/label-core.js —
    tests/test_label_svg.py fails if that file's horizon or discount rate moves
    without this one following."""
    if not house or not comparable:
        return None
    e = house.get("annualEnergyCost") is not None and comparable.get("annualEnergyCost") is not None
    lo = house.get("expectedAnnualLoss") is not None and comparable.get("expectedAnnualLoss") is not None
    if not e and not lo:
        return None
    d = ((comparable["annualEnergyCost"] - house["annualEnergyCost"]) if e else 0) \
        + ((comparable["expectedAnnualLoss"] - house["expectedAnnualLoss"]) if lo else 0)
    return d * _annuity(30, rate)


def _round_money(v: float) -> float:
    a = abs(v)
    if a < 1000:
        return _r(v / 50) * 50
    mag = 10 ** (int(math.floor(math.log10(a))) - 1)
    return _r(v / mag) * mag


def _money(v: float) -> str:
    return "$" + f"{abs(_r(v)):,}"


# ── Sections ─────────────────────────────────────────────────────────────────
def _masthead(out: list, source: str, y: float) -> float:
    out.append(_t(PAD, y, WORDMARK, 11, weight=700, ls=0.8))
    out.append(_t(PAD + COL, y, source, 10.5, fill="var(--mu)", anchor="end"))
    out.append(_rule(y + 10))
    return y + 34


def _identity(out: list, payload: dict, address, y: float) -> float:
    """Address, context, and the composite — the block that says which house this
    is. The composite sits right, at the size the eye lands on first, because a
    sheet handed to somebody else has to answer "what is this" before "how good"."""
    loc = payload.get("location") or {}
    house = payload.get("house") or {}
    score_w = 150                       # reserved for the composite block
    title_w = COL - score_w - 24

    heading = address or loc.get("label") or ""
    # Both halves or neither: a payload carrying one coordinate is a payload with
    # no location, and half a coordinate is not a heading.
    if not heading and house.get("lat") is not None and house.get("lon") is not None:
        heading = f'{house["lat"]}, {house["lon"]}'
    top = y
    for line in _wrap(heading, title_w, 21, 700, max_lines=2):
        out.append(_t(PAD, y + 16, line, 21, weight=700, fill="var(--hd)"))
        y += 26
    meta = " · ".join(
        [b for b in (loc.get("county_name"),
                     f'IECC {loc["climate_zone"]}' if loc.get("climate_zone") else None) if b])
    if meta:
        out.append(_t(PAD, y + 12, _fit(meta, title_w, 11.5), 11.5, fill="var(--mu)"))
        y += 18
    bits = []
    if house.get("construction"):
        bits.append(_WALL_LABELS.get(house["construction"], house["construction"]))
    yb = year_built_display(payload.get("building"))
    if yb:
        bits.append(f"built {yb}")
    elif house.get("year_built"):
        bits.append(f'built {house["year_built"]}')
    if house.get("sqft") is not None:
        bits.append(f'{_r(house["sqft"]):,} sqft')
    st = payload.get("structure") or {}
    if st.get("num_units") and st["num_units"] > 1:
        bits.append(f'{st["num_units"]}-unit building')
    if bits:
        out.append(_t(PAD, y + 12, _fit(" · ".join(bits), title_w, 11.5), 11.5,
                      fill="var(--mu)"))
        y += 18

    # The composite. "59.9" alone is not a quantity, so the denominator and a
    # one-word caption say what it is before the grade chip has to.
    comp = payload.get("composite_score")
    grade = payload.get("composite_national_grade") or "—"
    right = PAD + COL
    out.append(_t(right, top + 10, "OVERALL", 9, fill="var(--mu)", weight=600,
                  ls=0.7, anchor="end"))
    shown = "N/A" if comp is None else f"{float(comp):.1f}"
    out.append(_t(right - 52, top + 44, shown, 32, weight=800, fill="var(--hd)", anchor="end"))
    if comp is not None:
        out.append(_t(right - 48, top + 44, "/100", 12, fill="var(--mu)", weight=600))
    out.append(_chip(right - 42, top + 54, 42, 42, grade, 24, rx=6))
    return max(y, top + 104)


def _confidence_line(out: list, payload: dict, y: float) -> float:
    cc = _composite_confidence(payload)
    if not cc:
        return y
    text = (f'Overall is the average of the {cc["n_scored"]} dimensions scored here, '
            f'out of {cc["n_total"]}. Data quality: {_CONF_WORD[cc["tier"]]}.')
    out.append(_t(PAD, y + 10, _fit(text, COL, 10.5), 10.5, fill="var(--mu)"))
    return y + 22


def _caveats(out: list, payload: dict, y: float) -> float:
    """Caveats land above the numbers they qualify, the same order the card uses:
    a note that a row rests on a pilot cost model changes how that row is read,
    and a reader who meets it underneath thirteen rows has already read them."""
    for c in payload.get("caveats") or []:
        lines = _wrap(c, COL - 22, 10, max_lines=2)
        if not lines:
            continue
        h = 10 + 13 * len(lines)
        out.append(f'<rect x="{PAD}" y="{_num(y)}" width="{COL}" height="{_num(h)}" '
                   f'rx="3" fill="var(--note)"/>')
        out.append(f'<rect x="{PAD}" y="{_num(y)}" width="3" height="{_num(h)}" '
                   f'fill="var(--noteline)"/>')
        for i, line in enumerate(lines):
            out.append(_t(PAD + 12, y + 15 + i * 13, line, 10, fill="var(--tx)"))
        y += h + 8
    return y


def _axis_pair(out: list, payload: dict, y: float) -> float:
    """The two headline grades, side by side and the same size. A buyer asks two
    questions, not one, and the composite above averages them away."""
    if all(payload.get(f"{k}_score") is None for _cap, k, _b in _AXES):
        return y
    cell_w, gap, h = (COL - 14) / 2, 14, 82
    for i, (cap, key, blurb) in enumerate(_AXES):
        x = PAD + i * (cell_w + gap)
        score = payload.get(f"{key}_score")
        grade = payload.get(f"{key}_national_grade") or "—"
        out.append(f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(cell_w)}" '
                   f'height="{h}" rx="6" fill="none" stroke="var(--bd)"/>')
        out.append(_t(x + 14, y + 20, cap.upper(), 9, fill="var(--mu)", weight=600, ls=0.7))
        if score is None:
            out.append(_t(x + 14, y + 45, "Not scored", 17, weight=700, fill="var(--mu)"))
        else:
            pct = _r(float(score))
            out.append(_t(x + 14, y + 46, str(pct), 22, weight=800, fill="var(--hd)"))
            out.append(_t(x + 14 + _text_w(str(pct), 22, 800) + 5, y + 46,
                          f"{_ordinal(pct)} percentile", 10, fill="var(--mu)", weight=600))
        out.append(_chip(x + cell_w - 44, y + 16, 32, 32, grade, 19, rx=5))
        for j, line in enumerate(_wrap(blurb, cell_w - 28, 9.5, max_lines=2)):
            out.append(_t(x + 14, y + 62 + j * 12, line, 9.5, fill="var(--mu)"))
    y += h + 8

    # Two grades that disagree are the point of splitting them, but a reader shown
    # "A" and "D" with no gloss assumes one of them is wrong.
    b, s = payload.get("construction_score"), payload.get("location_score")
    if b is not None and s is not None and abs(_r(b - s)) >= 20:
        note = ("A well-built home in a demanding place: the structure beats most US homes, "
                "its surroundings do not." if b > s else
                "A modest structure in a strong place: the surroundings beat most US homes, "
                "the building does not.")
        note += " Both are national percentiles, so they are read the same way."
        lines = _wrap(note, COL, 10, max_lines=2)
        for i, line in enumerate(lines):
            out.append(_t(PAD, y + 10 + i * 12, line, 10, fill="var(--mu)"))
        y += 12 * len(lines) + 6
    return y


def _cost_strip(out: list, payload: dict, y: float) -> float:
    """The running-cost headline, as a present value over a 30-year mortgage. The
    referent travels with the number: "$2,600 more" beside a house reads as a
    price difference unless it says what it is measured against."""
    house, base = payload.get("cost"), payload.get("baseline_cost")
    pv = _cost_pv(house, base)
    if pv is None:
        return y
    same = abs(pv) < 1
    label = (base or {}).get("label") or "a typical comparable here"
    out.append(_rule(y))
    out.append(_t(PAD, y + 18, "COST TO RUN, OVER A 30-YEAR MORTGAGE", 9,
                  fill="var(--mu)", weight=600, ls=0.7))
    if same:
        out.append(_t(PAD, y + 42, "About the same to run", 19, weight=800, fill="var(--hd)"))
        out.append(_t(PAD, y + 60, _fit(f"as {label}", COL, 10.5), 10.5, fill="var(--mu)"))
    else:
        word = "less" if pv > 0 else "more"
        head = f"{_money(_round_money(pv))} {word} to run"
        out.append(_t(PAD, y + 42, _fit(head, COL, 19, 800), 19, weight=800, fill="var(--hd)"))
        per_year = _r(abs(pv / _annuity(30, 0.04)) / 10) * 10
        out.append(_t(PAD, y + 60, _fit(f"than {label} — about {_money(per_year)} a year",
                                        COL, 10.5), 10.5, fill="var(--mu)"))
    monthly = (payload.get("metrics") or {}).get("est_monthly_energy_cost")
    if monthly is not None:
        out.append(_t(PAD + COL, y + 42, f"Energy bill about ${_r(monthly):,} a month", 10.5,
                      fill="var(--mu)", anchor="end"))
    out.append(_t(PAD + COL, y + 60, "Energy and likely disaster losses only — not price, "
                                     "tax, or upkeep", 9, fill="var(--mu)", anchor="end"))
    out.append(_rule(y + 70))
    return y + 80


def _dim_rows(out: list, payload: dict, y: float) -> float:
    """The thirteen rows, grouped the way a buyer's question splits: is the
    problem the house, or the block? Each row carries the name, the bar, the
    number, the letter, and — in the caption — the percentile spelled out, since
    "17th US" reads as a rank from the top when it means the opposite."""
    dims = payload.get("dimensions") or []
    conf = payload.get("confidence") or {}
    by_kind: dict[str, list] = {}
    for d in dims:
        by_kind.setdefault(d.get("kind") or "", []).append(d)
    order = [(k, lab) for k, lab in _GROUPS if by_kind.get(k)]
    grouped = len(order) > 1 and sum(len(v) for _k, v in by_kind.items()) == sum(
        len(by_kind[k]) for k, _lab in order)
    if not grouped:
        order = [("", "")]
        by_kind = {"": dims}

    note_w, score_x, chip_x = 190, PAD + COL - 34, PAD + COL - 28
    for key, group_label in order:
        if group_label:
            out.append(_t(PAD, y + 10, group_label.upper(), 9, fill="var(--mu)",
                          weight=600, ls=0.7))
            y += 20
        for d in by_kind[key]:
            score, grade = d.get("score"), _grade_of(d)
            scored = isinstance(score, (int, float))
            name_w = COL - note_w - 90
            out.append(_t(PAD, y + 11, _fit(d.get("label") or d.get("key") or "", name_w, 12, 600),
                          12, weight=600))
            notes = []
            if isinstance(d.get("national_percentile"), (int, float)):
                notes.append(f'Beats {_r(d["national_percentile"])}% of US homes')
            tier = conf.get(d.get("key"))
            if tier in _CONF_WORD:
                notes.append(f"{_CONF_WORD[tier]} data")
            if not scored:
                notes = ["No data here — left out of Overall"]
            if notes:
                out.append(_t(score_x - 46, y + 11,
                              _fit(" · ".join(notes), note_w, 9.5), 9.5,
                              fill="var(--mu)", anchor="end"))
            if scored:
                out.append(_t(score_x, y + 11, f"{float(score):.1f}", 11.5,
                              weight=700, anchor="end"))
            out.append(_chip(chip_x, y + 1, 28, 15, grade if scored else "—", 10.5, rx=3))
            out.append(_bar(PAD, y + 18, COL, 7, score if scored else None, grade))
            y += 31
        y += 2
    return y


def _footer(out: list, payload: dict, y: float, generated, source: str) -> float:
    """The fine print, in full. On a screen the notice is one scroll from the
    numbers; on paper it is one glance, and a sheet that leaves the house is the
    copy most likely to be read with nothing of ours anywhere near it — so this
    carries the whole disclaimer rather than the short form the badge uses."""
    metrics = payload.get("metrics") or {}
    bits = []
    if metrics.get("eui_kbtu_sqft_yr") is not None:
        bits.append(f'Uses {metrics["eui_kbtu_sqft_yr"]:.1f} kBTU per sqft a year (EUI)')
    if metrics.get("fiscal_ratio") is not None:
        bits.append(f'Tax and fees cover {metrics["fiscal_ratio"]:.2f}× the cost to serve it')
    if bits:
        out.append(_t(PAD, y + 10, _fit("  ·  ".join(bits), COL, 9.5), 9.5, fill="var(--mu)"))
        y += 18
    out.append(_rule(y))
    y += 14
    for line in _wrap(payload.get("disclaimer") or DISCLAIMER, COL, 8.5, max_lines=5):
        out.append(_t(PAD, y + 8, line, 8.5, fill="var(--mu)"))
        y += 11
    stamp = [f"{WORDMARK} · {source}"]
    if generated:
        stamp.append(f"scored {generated}")
    out.append(_t(PAD, y + 12, _fit(" · ".join(stamp), COL, 8.5), 8.5, fill="var(--mu)"))
    return y + 18


# ── The sheet ────────────────────────────────────────────────────────────────
def validate_theme(theme: str) -> None:
    """Raise ValueError on an unknown theme.

    Exposed separately from ``render_sheet`` so a caller can refuse a bad
    parameter *before* paying for a scoring pass. The rendering is the cheap end
    of ``GET /label.svg``; the label behind it is a dozen federal datasets and a
    metered unit of somebody's daily allowance, and a typo in a cosmetic
    parameter should cost neither.
    """
    if theme not in THEME_NAMES:
        raise ValueError(f"unknown theme {theme!r}; choose one of: {', '.join(THEME_NAMES)}")


def _sheet_css(theme: str) -> str:
    """The badge's theme tokens plus the two this renderer adds. Same shape, so a
    reader who has both files open sees one system, not two."""
    css = _theme_css(theme)
    extra = ("--track:#eceae4;--note:#f4f1ea;--noteline:#c9a227;--hd:#13233d")
    dark = ("--track:#232b3a;--note:#1e2634;--noteline:#c9a227;--hd:#e8e6e0")
    css += f":root{{{extra if theme != 'dark' else dark}}}"
    if theme == "auto":
        css += f"@media(prefers-color-scheme:dark){{:root{{{dark}}}}}"
    return css


def render_sheet(payload: dict, *, address: str | None = None, theme: str = "light",
                 generated: str | None = None, source: str = HOME) -> str:
    """Render a scored label payload as a one-page, self-contained SVG sheet.

    ``payload`` is what ``simulate.house.label_payload`` returns; only fields the
    web card already reads are used, and every one of them is optional, so a
    trimmed or older payload renders a sparser sheet rather than failing. Sparser,
    not smaller: the page is never shorter than ``PAGE_H``, because a sheet is a
    sheet — content that ends early leaves white space at the bottom, the way it
    would on paper, rather than cropping the page to the last line drawn. Content
    that overruns is what grows the file, onto a second page.

    ``theme`` defaults to ``light`` — this artifact exists to be printed, and
    paper has no dark mode. ``generated`` is a caller-formatted date stamped in
    the footer; it is a parameter rather than ``date.today()`` because the sheet
    should be reproducible from its payload, and because the date that matters is
    the one the label was *scored*, not the one the file was written.

    Raises ValueError on an unknown theme: an unrecognised query parameter should
    be a 400 at the edge, not a silent fallback.
    """
    validate_theme(theme)

    out: list[str] = []
    y = _masthead(out, source, PAD + 10)
    y = _identity(out, payload, address, y)
    y = _confidence_line(out, payload, y)
    y = _caveats(out, payload, y + 4)
    y = _axis_pair(out, payload, y + 4)
    y = _cost_strip(out, payload, y + 4)
    y = _dim_rows(out, payload, y + 6)
    y = _footer(out, payload, y, generated, source)
    height = max(PAGE_H, _r(y + PAD))

    grades = ", ".join(
        "{} {}".format(cap.lower().removeprefix("the "),
                       payload.get(f"{k}_national_grade") or "not scored")
        for cap, k, _b in _AXES)
    title = "Housing Nutrition Label"
    if address or (payload.get("location") or {}).get("label"):
        shown_addr = address or payload["location"]["label"]
        title += " \u2014 " + _fit(shown_addr, 400, 12)
    comp_grade = payload.get("composite_national_grade") or "not scored"
    title += f". Overall {comp_grade}; {grades}."
    title += f" {DISCLAIMER_SHORT}"

    return (
        # Physical units on the root with a px viewBox: the file prints and
        # imports at true size instead of at whatever a consumer decides 816 user
        # units mean. The page paints its own background — an SVG dropped on a
        # dark slide would otherwise show the slide through every gap.
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_num(PAGE_W / 96)}in" '
        f'height="{_num(height / 96)}in" viewBox="0 0 {PAGE_W} {height}" '
        f'role="img" aria-label="{_esc(title)}" aria-describedby="hnl-disclaimer" '
        f'font-family="{FONT}">'
        f'<title>{_esc(title)}</title>'
        f'<desc id="hnl-disclaimer">{_esc(payload.get("disclaimer") or DISCLAIMER)}</desc>'
        f'<style>{_sheet_css(theme)}</style>'
        f'<rect width="{PAGE_W}" height="{height}" fill="var(--bg)"/>'
        + "".join(out) + '</svg>')


def filename_for(address: str | None, *, ext: str = "svg") -> str:
    """A download filename that survives every filesystem: ASCII, lowercase, no
    spaces. ``housing-label-123-main-st-memphis-tn.svg``."""
    # ASCII alnum only: str.isalnum() is true for "ß" and "é", and a filename
    # that survives a browser download can still confuse a mail gateway or a
    # Windows share. Mirrors slugForFile() in docs/label-form.js.
    slug = "".join(c if (c.isascii() and c.isalnum()) else "-"
                   for c in (address or "").lower())
    slug = "-".join(p for p in slug.split("-") if p)[:60].strip("-")
    return f"housing-label-{slug}.{ext}" if slug else f"housing-label.{ext}"
