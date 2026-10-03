#!/usr/bin/env python3
"""Build the coverage page (``docs/coverage.html``) from the adapter registry.

Where does the label carry an *observed* building record rather than a modelled
one? The honest answer changes every time an assessor adapter lands, and a page
that says it by hand is a page that goes stale the day after it is written. So
this page is generated, like ``accuracy.html``, from the things that are already
the truth:

* ``enrich.assessor.ADAPTERS`` — which county FIPS each adapter answers for. A
  county is on the map because an adapter is registered for it, not because
  somebody coloured it in.
* ``data/year_built_county.csv`` — the ACS housing-unit count per county, the
  same table the label's year-built fallback reads. "Homes covered" is the sum
  over an adapter's counties, and the national row is the denominator.
* ``research/accuracy/results.json`` — the measured accuracy, for the
  jurisdictions that have been measured. The page never states an accuracy
  number for a jurisdiction that has not been.

What is curated here, keyed per adapter module so a new adapter fails loudly
until it is described: its display name, the date it landed, which record fields
it supplies, and its end-to-end verification (sample drawn at random from the
source, geocoded exactly as the product does, then looked up). Those numbers come
from the verification run recorded in each adapter's own module docstring.

The county map is a separate asset, ``docs/coverage-map.svg``: every US county as
a path keyed ``c<FIPS>``, drawn once from the Census Bureau's cartographic
boundaries (via the ``us-atlas`` package, which projects them to Albers USA). It
carries no colours. The page colours covered counties with a generated CSS
block, so the map only needs redrawing if county geometry changes, which is why
``--map`` is the only mode that touches the network.

Usage::

    python scripts/build_coverage.py --write   # regenerate docs/coverage.html
    python scripts/build_coverage.py --check   # exit 1 if the page is stale (CI)
    python scripts/build_coverage.py --map     # redraw docs/coverage-map.svg (network)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich.assessor import ADAPTERS  # noqa: E402
from housing_label.enrich.assessor.base import AssessorRecord  # noqa: E402
from housing_label.legal import DISCLAIMER  # noqa: E402

PAGE = _ROOT / "docs" / "coverage.html"
MAP = _ROOT / "docs" / "coverage-map.svg"
UNITS_CSV = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
RESULTS = _ROOT / "research" / "accuracy" / "results.json"

#: The us-atlas release the map is drawn from. Pinned so a redraw is
#: reproducible; ISC-licensed, derived from Census cartographic boundary files.
ATLAS_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/counties-albers-10m.json"

FIELDS = ("year_built", "sqft", "stories", "construction", "foundation", "condition")
FIELD_LABELS = {
    "year_built": "Year built", "sqft": "Floor area", "stories": "Storeys",
    "construction": "Wall", "foundation": "Foundation", "condition": "Condition",
}

# ── What each adapter is, in words ──────────────────────────────────────────────
# Keyed by module name (``housing_label.enrich.assessor.<key>``). `fields` is what
# the adapter can put on a label, not what every record carries — a condominium
# unit, for instance, never reports a storey count. `verified` is the end-to-end
# check from the module's docstring: homes drawn at random from the source,
# geocoded through the Census matcher, then looked up. `accuracy` names the
# jurisdiction in results.json when there is a measured benchmark, and takes the
# place of `verified` (the benchmark is the stronger statement).
CURATED: dict[str, dict] = {
    "cook_il": {
        "name": "Cook County, Illinois", "short": "Cook County, IL",
        "since": "2026-08-24",
        "fields": ("year_built", "sqft", "stories", "construction", "foundation",
                   "condition"),
        "accuracy": "cook",
    },
    "dc": {
        "name": "Washington, DC", "short": "Washington, DC",
        "since": "2026-08-24",
        "fields": ("year_built", "sqft", "stories", "construction", "condition"),
        "accuracy": "dc",
    },
    "fl": {
        "name": "Florida (all 67 counties)", "short": "Florida",
        "since": "2026-08-28",
        "fields": ("year_built", "sqft"),
        "verified": {"sample": 26, "resolved": 21, "wrong": 0},
    },
    "ct": {
        "name": "Connecticut (all 169 towns)", "short": "Connecticut",
        "since": "2026-09-01",
        "fields": ("year_built", "sqft"),
        "verified": {"sample": 103, "resolved": 64, "wrong": 0},
    },
    # The 2026-10 adapters. Samples are homes drawn at random from each source;
    # "resolved" is over the whole sample, so geocoding failures count against it.
    "la": {
        "name": "Los Angeles County, California", "short": "Los Angeles County",
        "since": "2026-10-03",
        "fields": ("year_built", "sqft"),
        "verified": {"sample": 430, "resolved": 358, "wrong": 0},
    },
    "nyc": {
        "name": "New York City (five boroughs)", "short": "New York City",
        "since": "2026-10-03",
        "fields": ("year_built", "sqft", "stories", "foundation"),
        "verified": {"sample": 507, "resolved": 452, "wrong": 2,
                     "note": "Neither from the adapter: a Census street substitution "
                             "(now caught before lookup) and a city data swap of "
                             "twin lots with the same year."},
    },
    "phl": {
        "name": "Philadelphia, Pennsylvania", "short": "Philadelphia",
        "since": "2026-10-03",
        "fields": ("year_built", "sqft", "stories", "foundation", "condition"),
        "verified": {"sample": 450, "resolved": 396, "wrong": 0},
    },
    "nc": {
        "name": "North Carolina (46 of 100 counties)", "short": "North Carolina",
        "since": "2026-10-03",
        "fields": ("year_built",),
        "verified": {"sample": 300, "resolved": 210, "wrong": 0},
    },
    "md": {
        "name": "Maryland (all 24 jurisdictions)", "short": "Maryland",
        "since": "2026-10-03",
        "fields": ("year_built", "sqft", "stories", "construction"),
        "verified": {"sample": 150, "resolved": 117, "wrong": 0},
    },
    "nys": {
        "name": "New York State (33 opt-in counties)", "short": "New York State",
        "since": "2026-10-03",
        "fields": ("year_built", "sqft"),
        "verified": {"sample": 200, "resolved": 104, "wrong": 0},
    },
    "ma": {
        "name": "Massachusetts (all 14 counties)", "short": "Massachusetts",
        "since": "2026-10-03",
        "fields": ("year_built", "sqft", "stories"),
        "verified": {"sample": 260, "resolved": 196, "wrong": 1,
                     "note": "A Census street substitution (21 Longwood Ave returned "
                             "as 21 Linwood Ave, 3 km away), now caught before "
                             "lookup."},
    },
}


# ── inputs ──────────────────────────────────────────────────────────────────────


def county_units() -> tuple[dict[str, int], int]:
    """ACS housing units per county, and the national total (the ``00000`` row)."""
    units, national = {}, 0
    with UNITS_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            geoid, n = row["geoid"].strip(), int(float(row["units"] or 0))
            if geoid == "00000":
                national = n
            elif len(geoid) == 5:
                units[geoid] = n
    if not national:
        raise SystemExit(f"{UNITS_CSV} has no national (00000) row")
    return units, national


def adapters_by_module() -> dict[str, object]:
    mods = {}
    for mod in ADAPTERS.values():
        mods[mod.__name__.rsplit(".", 1)[-1]] = mod
    return mods


#: Connecticut's planning regions, which the Census Bureau adopted in place of its
#: eight counties. The map predates them, so they have no name there.
CT_REGIONS = {
    "09110": "Capitol Planning Region", "09120": "Greater Bridgeport Planning Region",
    "09130": "Lower Connecticut River Valley Planning Region",
    "09140": "Naugatuck Valley Planning Region",
    "09150": "Northeastern Connecticut Planning Region",
    "09160": "Northwest Hills Planning Region",
    "09170": "South Central Connecticut Planning Region",
    "09180": "Southeastern Connecticut Planning Region",
    "09190": "Western Connecticut Planning Region",
}


def county_names() -> dict[str, str]:
    """County names by FIPS, read from the map asset (``data-n``) so the page's
    county list and the map's tooltips can never name a county differently."""
    import re
    if not MAP.exists():
        return {}
    svg = MAP.read_text(encoding="utf-8")
    return dict(re.findall(r'id="c(\d{5})" data-n="([^"]*)"', svg))


def accuracy_results() -> dict:
    if not RESULTS.exists():
        return {}
    return (json.loads(RESULTS.read_text(encoding="utf-8")) or {}).get("jurisdictions") or {}


def _validate(mods: dict) -> None:
    """Every registered adapter is described here, and nothing else is."""
    missing = sorted(set(mods) - set(CURATED))
    stale = sorted(set(CURATED) - set(mods))
    if missing or stale:
        raise SystemExit(
            "scripts/build_coverage.py CURATED is out of step with the adapter "
            f"registry: undescribed {missing or '-'}, no longer registered "
            f"{stale or '-'}. Describe each new adapter in CURATED.")
    known = set(FIELDS)
    assert known <= set(AssessorRecord.__dataclass_fields__), "FIELDS drifted from AssessorRecord"
    for key, cfg in CURATED.items():
        bad = set(cfg["fields"]) - known
        if bad or "year_built" not in cfg["fields"]:
            raise SystemExit(f"{key}: fields {sorted(bad)} unknown, or no year_built")
        if not (cfg.get("accuracy") or cfg.get("verified")):
            raise SystemExit(f"{key}: neither a measured benchmark nor a verification run")
        dt.date.fromisoformat(cfg["since"])


def depth(fields) -> int:
    """How much of a building's record an adapter supplies, as a map tier.

    1 — year built only; 2 — year built and floor area; 3 — those plus at least
    one structural fact (storeys, wall, foundation or condition).
    """
    f = set(fields)
    if f & {"stories", "construction", "foundation", "condition"}:
        return 3
    return 2 if "sqft" in f else 1


TIER_LABELS = {1: "Year built", 2: "Year built + floor area",
               3: "Year built, floor area + structure"}


def model() -> dict:
    mods = adapters_by_module()
    _validate(mods)
    units, national = county_units()
    acc = accuracy_results()
    rows = []
    for key, mod in mods.items():
        cfg = CURATED[key]
        fips = sorted(mod.COUNTY_FIPS)
        homes = sum(units.get(f, 0) for f in fips)
        row = {
            "key": key, "name": cfg["name"], "short": cfg["short"],
            "source": getattr(mod, "NAME", key),
            "attribution": getattr(mod, "ATTRIBUTION", ""),
            "since": cfg["since"], "fields": list(cfg["fields"]),
            "depth": depth(cfg["fields"]), "counties": fips, "homes": homes,
        }
        juris = cfg.get("accuracy")
        if juris and juris in acc:
            a = acc[juris]
            row["measured"] = {
                "jurisdiction": juris,
                "sample": (a.get("benchmark") or {}).get("rows"),
                "resolved_pct": a.get("adapter_resolved_pct"),
                "wrong": a.get("parcel_mismatches"),
                "yb10_base": a["baseline"]["fields"]["year_built"].get("within_10yr_pct"),
                "yb10_adapter": a["adapter"]["fields"]["year_built"].get("within_10yr_pct"),
                "grade_base": a["baseline"]["grade_impact"]["building_axis"]["differs_pct"],
                "grade_adapter": a["adapter"]["grade_impact"]["building_axis"]["differs_pct"],
            }
            # The condominium half of a city is measured as its own jurisdiction
            # (see scripts/jurisdictions.py); carried beside the parent, not
            # averaged into it.
            for child, ca in acc.items():
                if child.startswith(juris + "-"):
                    row.setdefault("measured_children", []).append({
                        "jurisdiction": child,
                        "sample": (ca.get("benchmark") or {}).get("rows"),
                        "resolved_pct": ca.get("adapter_resolved_pct"),
                        "yb10_base": ca["baseline"]["fields"]["year_built"].get("within_10yr_pct"),
                        "yb10_adapter": ca["adapter"]["fields"]["year_built"].get("within_10yr_pct"),
                    })
        else:
            row["verified"] = dict(cfg["verified"])
        rows.append(row)
    rows.sort(key=lambda r: -r["homes"])
    total = sum(r["homes"] for r in rows)
    # Timeline: cumulative homes reachable, by the date each adapter landed.
    timeline, running = [], 0
    for since in sorted({r["since"] for r in rows}):
        landed = [r for r in rows if r["since"] == since]
        running += sum(r["homes"] for r in landed)
        timeline.append({"date": since, "homes": running,
                         "added": [r["short"] for r in landed]})
    covered = {f for r in rows for f in r["counties"]}
    states = {f[:2] for f in covered} - {"11"}     # DC is named separately
    return {
        "national": national, "total": total, "share_pct": 100.0 * total / national,
        "adapters": rows, "timeline": timeline,
        "counties": len({f for f in covered if f in units}),
        "states": len(states), "units": units,
    }


# ── formatting ─────────────────────────────────────────────────────────────────


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def millions(n: int, dp: int = 1) -> str:
    return f"{n / 1e6:.{dp}f}M"


def homes_text(n: int) -> str:
    if n >= 1e6:
        return f"{n / 1e6:.1f} million"
    return f"{round(n, -3):,.0f}"


def pct(v, dp: int = 1) -> str:
    return "—" if v is None else f"{v:.{dp}f}%"


# ── charts (static SVG; styled by the page's CSS variables) ────────────────────


def share_bar(m: dict) -> str:
    """The country's housing as one 100% bar, one segment per adapter."""
    w, h = 1000, 28
    x, parts = 0.0, []
    for r in m["adapters"]:
        seg = w * r["homes"] / m["national"]
        if seg <= 0:
            continue
        parts.append(
            f'<rect class="seg" data-adapter="{esc(r["key"])}" x="{x:.1f}" y="0" '
            f'width="{max(seg - 2, 0.5):.1f}" height="{h}" rx="3">'
            f'<title>{esc(r["short"])}: {homes_text(r["homes"])} homes</title></rect>')
        x += seg
    return (f'<svg class="share" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
            f'role="img" aria-label="{pct(m["share_pct"])} of US homes have an observed '
            f'record source">'
            f'<rect class="track" x="0" y="0" width="{w}" height="{h}" rx="3"/>'
            + "".join(parts) + "</svg>")


def homes_bars(m: dict) -> str:
    """Homes covered per source, ranked. One series, so one colour."""
    rows = m["adapters"]
    row_h, gap, label_w, val_w, plot_w = 30, 8, 190, 90, 520
    width = label_w + plot_w + val_w
    height = len(rows) * (row_h + gap)
    top = max(r["homes"] for r in rows) or 1
    out = []
    for i, r in enumerate(rows):
        y = i * (row_h + gap)
        bw = max(plot_w * r["homes"] / top, 2)
        out.append(
            f'<g class="bar-row" data-adapter="{esc(r["key"])}" tabindex="0">'
            f'<title>{esc(r["name"])}: {r["homes"]:,} homes ({pct(100 * r["homes"] / m["national"], 2)}'
            f' of US housing)</title>'
            f'<rect class="hit" x="0" y="{y}" width="{width}" height="{row_h}"/>'
            f'<text class="lbl" x="{label_w - 12}" y="{y + row_h / 2}" dy="0.35em" '
            f'text-anchor="end">{esc(r["short"])}</text>'
            f'<rect class="bar" x="{label_w}" y="{y + 5}" width="{bw:.1f}" '
            f'height="{row_h - 10}" rx="4"/>'
            f'<text class="val" x="{label_w + bw + 8:.1f}" y="{y + row_h / 2}" '
            f'dy="0.35em">{homes_text(r["homes"])}</text></g>')
    return (f'<svg class="bars" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Homes covered by each source">{"".join(out)}</svg>')


def timeline_chart(m: dict) -> str:
    """Cumulative homes with an observed-record source, by the date each landed."""
    pts = m["timeline"]
    w, h, pad_l, pad_r, pad_t, pad_b = 1000, 260, 70, 150, 20, 36
    d0 = dt.date.fromisoformat(pts[0]["date"]) - dt.timedelta(days=4)
    d1 = dt.date.fromisoformat(pts[-1]["date"]) + dt.timedelta(days=2)
    span = (d1 - d0).days or 1
    top = max(p["homes"] for p in pts)
    # A round axis maximum, in millions.
    step = 10e6 if top > 30e6 else 5e6
    ymax = step * (int(top // step) + 1)

    def X(d):
        return pad_l + (w - pad_l - pad_r) * (dt.date.fromisoformat(d) - d0).days / span

    def Y(v):
        return pad_t + (h - pad_t - pad_b) * (1 - v / ymax)

    grid = []
    v = 0.0
    while v <= ymax + 1:
        grid.append(f'<line class="grid" x1="{pad_l}" x2="{w - pad_r}" y1="{Y(v):.1f}" '
                    f'y2="{Y(v):.1f}"/><text class="axis" x="{pad_l - 10}" y="{Y(v):.1f}" '
                    f'dy="0.35em" text-anchor="end">{v / 1e6:.0f}M</text>')
        v += step
    # Step line: flat until the next adapter lands, then up.
    path = [f"M{X(pts[0]['date']):.1f} {Y(0):.1f}"]
    area = [f"M{X(pts[0]['date']):.1f} {Y(0):.1f}"]
    prev = 0
    for p in pts:
        x = X(p["date"])
        path.append(f"L{x:.1f} {Y(prev):.1f}L{x:.1f} {Y(p['homes']):.1f}")
        area.append(f"L{x:.1f} {Y(prev):.1f}L{x:.1f} {Y(p['homes']):.1f}")
        prev = p["homes"]
    xe = w - pad_r
    path.append(f"L{xe:.1f} {Y(prev):.1f}")
    area.append(f"L{xe:.1f} {Y(prev):.1f}L{xe:.1f} {Y(0):.1f}Z")
    marks = []
    for i, p in enumerate(pts):
        x, y = X(p["date"]), Y(p["homes"])
        added = ", ".join(p["added"])
        marks.append(
            f'<g class="pt"><title>{esc(p["date"])}: +{esc(added)} — '
            f'{homes_text(p["homes"])} homes</title>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5"/>'
            f'<text class="axis" x="{x:.1f}" y="{h - 12}" text-anchor="middle">'
            f'{dt.date.fromisoformat(p["date"]):%b %-d}</text></g>')
    end = pts[-1]
    label = (f'<text class="end" x="{xe + 10:.1f}" y="{Y(end["homes"]):.1f}" dy="0.35em">'
             f'{homes_text(end["homes"])}</text>'
             f'<text class="axis" x="{xe + 10:.1f}" y="{Y(end["homes"]) + 18:.1f}" dy="0.35em">'
             f'homes today</text>')
    return (f'<svg class="timeline" viewBox="0 0 {w} {h}" role="img" aria-label="Homes '
            f'with an observed-record source over time, reaching {homes_text(end["homes"])}">'
            + "".join(grid) + f'<path class="area" d="{"".join(area)}"/>'
            f'<path class="line" d="{"".join(path)}"/>' + "".join(marks) + label + "</svg>")


def dumbbells(rows: list[dict], lo_key: str, hi_key: str, unit_note: str,
              better_high: bool) -> str:
    """Baseline → with-assessor, one row per measured jurisdiction."""
    row_h, label_w, plot_w, pad_r = 46, 180, 320, 30
    w = label_w + plot_w + pad_r
    h = len(rows) * row_h + 38

    def X(v):
        return label_w + plot_w * v / 100.0

    out = []
    for t in (0, 25, 50, 75, 100):
        out.append(f'<line class="grid" x1="{X(t):.1f}" x2="{X(t):.1f}" y1="0" '
                   f'y2="{h - 26}"/><text class="axis" x="{X(t):.1f}" y="{h - 8}" '
                   f'text-anchor="middle">{t}%</text>')
    for i, r in enumerate(rows):
        y = i * row_h + row_h / 2 + 8
        a, b = r[lo_key], r[hi_key]
        if a is None or b is None:
            continue
        out.append(
            f'<g><title>{esc(r["label"])}: {a:.1f}% modelled → {b:.1f}% with the '
            f'assessor record ({esc(unit_note)})</title>'
            f'<text class="lbl" x="{label_w - 12}" y="{y:.1f}" dy="0.35em" '
            f'text-anchor="end">{esc(r["label"])}</text>'
            f'<line class="link" x1="{X(a):.1f}" x2="{X(b):.1f}" y1="{y:.1f}" y2="{y:.1f}"/>'
            f'<circle class="base" cx="{X(a):.1f}" cy="{y:.1f}" r="6"/>'
            f'<circle class="obs" cx="{X(b):.1f}" cy="{y:.1f}" r="7"/>'
            # Both ends labelled above their dots, so a falling value (fewer wrong
            # grades is the good direction) never runs into the row label.
            f'<text class="axis" x="{X(a):.1f}" y="{y - 12:.1f}" '
            f'text-anchor="middle">{a:.0f}%</text>'
            f'<text class="val" x="{X(b):.1f}" y="{y - 12:.1f}" '
            f'text-anchor="middle">{b:.0f}%</text></g>')
    return (f'<svg class="dumbbell" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{esc(unit_note)}, modelled versus with the assessor record">'
            + "".join(out) + "</svg>")


# ── the page ───────────────────────────────────────────────────────────────────


def county_css(m: dict) -> str:
    """One selector list per tier, colouring each covered county on the map."""
    by_tier: dict[int, list[str]] = {1: [], 2: [], 3: []}
    for r in m["adapters"]:
        by_tier[r["depth"]].extend(f"#c{f}" for f in r["counties"])
    # A county too small to see at this scale (the District, Manhattan) carries a
    # dot in the map asset; it is shown, in its tier's colour, only when covered.
    dots = {t: [f"#d{sel[2:]}" for sel in sels] for t, sels in by_tier.items()}
    return "\n".join(
        ",".join(f"#covmap {s}" for s in sorted(sels + dots[tier]))
        + f"{{fill:var(--tier-{tier})}}" for tier, sels in by_tier.items() if sels) + \
        "\n" + ",".join(f"#covmap {d}" for t in dots for d in sorted(dots[t])) + \
        "{display:inline}"


def tooltip_data(m: dict) -> str:
    """What the map's tooltip needs, keyed small: county → adapter, homes."""
    adapters = {r["key"]: {"n": r["short"], "f": [FIELD_LABELS[f] for f in r["fields"]],
                           "h": r["homes"], "d": r["depth"]}
                for r in m["adapters"]}
    counties = {}
    for r in m["adapters"]:
        for f in r["counties"]:
            counties[f] = [r["key"], m["units"].get(f)]
    return json.dumps({"a": adapters, "c": counties}, separators=(",", ":"),
                      sort_keys=True)


def field_matrix(m: dict) -> str:
    head = "".join(f"<th scope=\"col\">{esc(FIELD_LABELS[f])}</th>" for f in FIELDS)
    body = []
    for r in m["adapters"]:
        cells = "".join(
            '<td class="yes" aria-label="yes"><span class="dot"></span></td>'
            if f in r["fields"] else '<td class="no" aria-label="no">–</td>'
            for f in FIELDS)
        body.append(f'<tr><th scope="row">{esc(r["name"])}</th>{cells}</tr>')
    return (f'<div class="table-scroll"><table class="data-table matrix"><thead><tr>'
            f'<th scope="col">Source</th>{head}</tr></thead><tbody>{"".join(body)}'
            f'</tbody></table></div>')


def verification_table(m: dict) -> str:
    body = []
    for r in m["adapters"]:
        if "measured" in r:
            v = r["measured"]
            n, res, wrong = v["sample"], v["resolved_pct"], v["wrong"]
            how = '<a href="accuracy.html#{0}">measured benchmark</a>'.format(
                esc(v["jurisdiction"]))
        else:
            v = r["verified"]
            n, wrong = v["sample"], v["wrong"]
            res = 100.0 * v["resolved"] / v["sample"] if v["sample"] else None
            how = "random-sample check"
        meter = (f'<span class="meter" aria-hidden="true"><span style="width:{res:.0f}%">'
                 f'</span></span>' if res is not None else "")
        note = (v.get("note") if isinstance(v, dict) else None) or ""
        wrong_cell = "—" if wrong is None else str(wrong)
        if note:
            wrong_cell += f'<span class="fn">{esc(note)}</span>'
        body.append(
            f'<tr><th scope="row">{esc(r["name"])}</th><td>{n}</td>'
            f'<td class="res">{meter}<span>{pct(res, 0)}</span></td>'
            f'<td>{wrong_cell}</td><td>{how}</td></tr>')
    return ('<div class="table-scroll"><table class="data-table verify"><thead><tr>'
            '<th scope="col">Source</th><th scope="col">Homes sampled</th>'
            '<th scope="col">Answered with an observed record</th>'
            '<th scope="col">Wrong parcel</th><th scope="col">How</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def county_lists(m: dict) -> str:
    """Every covered county, by source — the map's county detail in a form a
    keyboard or a screen reader can reach. Making 3,142 map paths tab stops would
    be worse than useless; a list is the accessible equivalent."""
    from housing_label.data.states import usps_for_fips
    names = county_names()
    out = []
    for r in m["adapters"]:
        items = []
        for f in r["counties"]:
            # Listed at the grain the housing counts exist at. Connecticut is
            # registered under both its legacy counties and its planning regions;
            # only the regions carry ACS counts, so only they are listed, and the
            # state is not shown twice.
            homes = m["units"].get(f)
            if not homes:
                continue
            name = names.get(f) or CT_REGIONS.get(f) or f
            items.append((f"{name}, {usps_for_fips(f[:2]) or f[:2]}",
                          f" — {homes_text(homes)} homes"))
        items.sort()
        lis = "".join(f"<li>{esc(n)}{esc(t)}</li>" for n, t in items)
        noun = "county" if len(items) == 1 else "counties"
        if r["key"] == "ct":
            noun = "planning regions"
        out.append(f'<details><summary>{esc(r["name"])} &middot; {len(items)} '
                   f'{noun}</summary><ul class="counties">{lis}</ul></details>')
    return "".join(out)


def measured_rows(m: dict) -> list[dict]:
    rows = []
    for r in m["adapters"]:
        if "measured" in r:
            v = r["measured"]
            rows.append({"label": r["short"], **v})
            for c in r.get("measured_children", []):
                rows.append({"label": "DC condominiums" if r["key"] == "dc" else r["short"] + " condos", "grade_base": None,
                             "grade_adapter": None, **c})
    return rows


_STYLE = """
.cov { --tier-0:#ebe6dc; --tier-1:#86b6ef; --tier-2:#3987e5; --tier-3:#184f95;
  --series:#2a78d6; --series-soft:rgba(42,120,214,.14); --base:#a8a49a;
  --grid:#e8e3da; --ink:#22262e; --ink-2:#6b6960; --surface:#fffdf9; }
@media (prefers-color-scheme: dark) {
  .cov { --tier-0:#232c3b; --tier-1:#2a78d6; --tier-2:#6da7ec; --tier-3:#cde2fb;
    --series:#3987e5; --series-soft:rgba(57,135,229,.18); --base:#6f6c64;
    --grid:#29313f; --ink:#e8e6e0; --ink-2:#9b988e; --surface:#18202e; }
}
.cov main { max-width: 64rem; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
.cov .lede { font-size: 1.1rem; color: var(--ink-2); max-width: 46rem; margin-bottom: 1.5rem; }
.cov .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
  gap: .75rem; margin: 1.25rem 0 1rem; }
.cov .tile { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
  padding: .9rem 1rem; }
.cov .tile .num { font-size: 1.9rem; font-weight: 700; color: var(--ink); line-height: 1.1;
  font-variant-numeric: tabular-nums; }
.cov .tile .cap { color: var(--ink-2); font-size: .85rem; margin-top: .25rem; }
.cov .card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 1.1rem 1.1rem 1rem; margin: 1.25rem 0; }
.cov .card h2 { font-size: 1.25rem; margin-bottom: .25rem; }
.cov .card .sub { color: var(--ink-2); font-size: .9rem; margin-bottom: .9rem; }
.cov svg text { fill: var(--ink); font-size: 14px; font-family: inherit; }
.cov svg .axis { fill: var(--ink-2); font-size: 12px; }
.cov svg .grid { stroke: var(--grid); stroke-width: 1; }
.cov .share { width: 100%; height: 28px; display: block; }
.cov .share .track { fill: var(--tier-0); }
.cov .share .seg { fill: var(--series); }
.cov .share-cap { display: flex; justify-content: space-between; color: var(--ink-2);
  font-size: .85rem; margin-top: .35rem; }
.cov .map-wrap { position: relative; }
.cov #covmap svg { width: 100%; height: auto; display: block; }
.cov #covmap .c { fill: var(--tier-0); stroke: var(--surface); stroke-width: .35; }
.cov #covmap .s { fill: none; stroke: var(--surface); stroke-width: 1.2; pointer-events: none; }
.cov #covmap .c:hover, .cov #covmap .c.hl { stroke: var(--ink); stroke-width: 1; }
.cov .legend { display: flex; flex-wrap: wrap; gap: .4rem 1.1rem; font-size: .85rem;
  color: var(--ink-2); margin-top: .6rem; }
.cov .legend span::before { content: ""; display: inline-block; width: .85rem; height: .85rem;
  border-radius: 3px; margin-right: .4rem; vertical-align: -2px; background: var(--sw); }
.cov .tip { position: absolute; pointer-events: none; background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 6px; padding: .5rem .65rem; font-size: .85rem;
  box-shadow: 0 4px 14px rgba(0,0,0,.12); max-width: 17rem; line-height: 1.35; display: none; z-index: 5; }
.cov .tip b { display: block; }
.cov .tip .m { color: var(--ink-2); }
.cov .bars { width: 100%; height: auto; }
.cov .bars .bar { fill: var(--series); }
.cov .bars .hit { fill: transparent; }
.cov .bars .bar-row:hover .hit, .cov .bars .bar-row:focus .hit { fill: var(--series-soft); }
.cov .bars .bar-row:focus { outline: none; }
.cov .bars .val { fill: var(--ink-2); font-variant-numeric: tabular-nums; }
.cov .timeline { width: 100%; height: auto; }
.cov .timeline .line { fill: none; stroke: var(--series); stroke-width: 2; }
.cov .timeline .area { fill: var(--series-soft); }
.cov .timeline circle { fill: var(--series); stroke: var(--surface); stroke-width: 2; }
.cov .timeline .end { font-weight: 700; font-size: 16px; }
.cov .dumbbell { width: 100%; height: auto; }
.cov .dumbbell .link { stroke: var(--grid); stroke-width: 4; stroke-linecap: round; }
.cov .dumbbell .base { fill: var(--base); stroke: var(--surface); stroke-width: 2; }
.cov .dumbbell .obs { fill: var(--series); stroke: var(--surface); stroke-width: 2; }
.cov .dumbbell .val { font-weight: 600; font-variant-numeric: tabular-nums; }
.cov .key { display: flex; gap: 1.1rem; font-size: .85rem; color: var(--ink-2); margin: .25rem 0 .5rem; }
.cov .key i { display: inline-block; width: .8rem; height: .8rem; border-radius: 50%;
  margin-right: .35rem; vertical-align: -1px; background: var(--k); }
.cov .two { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 760px) { .cov .two { grid-template-columns: 1fr; } }
.cov .matrix td, .cov .matrix th { text-align: center; }
.cov .matrix th[scope=row], .cov .verify th[scope=row] { text-align: left; font-weight: 600; }
.cov .matrix .dot { display: inline-block; width: .7rem; height: .7rem; border-radius: 50%;
  background: var(--series); }
.cov .matrix .no { color: var(--ink-2); }
.cov .verify td { font-variant-numeric: tabular-nums; }
.cov .verify .res { white-space: nowrap; }
.cov .verify .fn { display: block; color: var(--ink-2); font-size: .8rem; line-height: 1.35;
  margin-top: .2rem; max-width: 22rem; }
.cov .meter { display: inline-block; width: 5rem; height: .5rem; border-radius: 3px;
  background: var(--tier-0); margin-right: .5rem; vertical-align: middle; overflow: hidden; }
.cov .meter span { display: block; height: 100%; background: var(--series); border-radius: 3px; }
.cov .bars .bar-row.dim .bar { opacity: .35; }
.cov .data-table tbody th { text-transform: none; letter-spacing: normal; background: none;
  color: var(--ink); font-size: .95rem; }
.cov #covmap .dot { display: none; stroke: var(--surface); stroke-width: 1.2; }
.cov details { border-top: 1px solid var(--border); padding: .45rem 0; }
.cov details summary { cursor: pointer; font-weight: 600; }
.cov .counties { columns: 3 13rem; margin: .5rem 0 .25rem 1.1rem; font-size: .9rem;
  color: var(--ink-2); }
.cov .notes li { margin: .4rem 0 .4rem 1.1rem; }
.cov .fine { opacity: .75; font-size: .85rem; }
"""

_SCRIPT = """
(function () {
  var holder = document.getElementById('covmap');
  var tip = document.getElementById('covtip');
  var data = JSON.parse(document.getElementById('coverage-data').textContent);
  function fmt(n) { return n == null ? '' : n >= 1e6 ? (n / 1e6).toFixed(1) + ' million'
    : Math.round(n).toLocaleString('en-US'); }
  function highlight(key) {
    var on = holder.querySelectorAll('.c.hl');
    for (var i = 0; i < on.length; i++) on[i].classList.remove('hl');
    if (!key) return;
    for (var f in data.c) if (data.c[f][0] === key) {
      ['c', 'd'].forEach(function (p) {
        var el = document.getElementById(p + f); if (el) el.classList.add('hl'); });
    }
  }
  function show(evt, el) {
    var f = el.id.slice(1), hit = data.c[f], name = el.getAttribute('data-n') || '';
    var h = '<b>' + name + '</b>';
    if (hit) {
      var a = data.a[hit[0]];
      h += '<span>' + a.n + '</span><span class="m">Observed: ' + a.f.join(', ') + '</span>';
      if (hit[1]) h += '<span class="m">' + fmt(hit[1]) + ' homes in this county</span>';
    } else {
      h += '<span class="m">Modelled building data (no assessor source yet)</span>';
    }
    tip.innerHTML = h; tip.style.display = 'block';
    var box = holder.getBoundingClientRect();
    var x = evt.clientX - box.left + 14, y = evt.clientY - box.top + 14;
    if (x + tip.offsetWidth > box.width) x = evt.clientX - box.left - tip.offsetWidth - 14;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  fetch('coverage-map.svg').then(function (r) { return r.ok ? r.text() : ''; }).then(function (svg) {
    if (!svg) return;
    holder.innerHTML = svg;
    holder.addEventListener('mousemove', function (e) {
      var el = e.target.closest ? e.target.closest('.c') : null;
      if (el) show(e, el); else tip.style.display = 'none';
    });
    holder.addEventListener('mouseleave', function () { tip.style.display = 'none'; });
  }).catch(function () {});
  var rows = document.querySelectorAll('.bar-row');
  for (var i = 0; i < rows.length; i++) (function (row) {
    var key = row.getAttribute('data-adapter');
    function on() { highlight(key);
      for (var j = 0; j < rows.length; j++) rows[j].classList.toggle('dim', rows[j] !== row); }
    function off() { highlight(null); for (var j = 0; j < rows.length; j++) rows[j].classList.remove('dim'); }
    row.addEventListener('mouseenter', on); row.addEventListener('focus', on);
    row.addEventListener('mouseleave', off); row.addEventListener('blur', off);
  })(rows[i]);
})();
"""

NAV = [("index.html", "Overview"), ("methodology.html", "Methodology"),
       ("examples.html", "Examples"), ("label.html", "Label"),
       ("coverage.html", "Coverage"), ("setup.html", "Setup"),
       ("reference.html", "Reference"),
       ("https://github.com/compbiolover/housing-nutrition-label", "GitHub")]


def render(m: dict) -> str:
    measured = measured_rows(m)
    newest = max(r["since"] for r in m["adapters"])
    tier_counts = {t: sum(r["homes"] for r in m["adapters"] if r["depth"] == t)
                   for t in (1, 2, 3)}
    current = ' class="active" aria-current="page"'
    nav = "".join(
        f'<li><a href="{h}"{current if h == "coverage.html" else ""}>{t}</a></li>'
        for h, t in NAV)
    legend = "".join(
        f'<span style="--sw:var(--tier-{t})">{esc(TIER_LABELS[t])} '
        f'({homes_text(tier_counts[t])} homes)</span>' for t in (3, 2, 1) if tier_counts[t])
    legend += '<span style="--sw:var(--tier-0)">Modelled only</span>'
    yb = dumbbells(measured, "yb10_base", "yb10_adapter",
                   "year built within ±10 years of the assessor's", True)
    grade_rows = [r for r in measured if r.get("grade_base") is not None]
    gr = dumbbells(grade_rows, "grade_base", "grade_adapter",
                   "building grade differs from the true attributes' grade", False)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coverage &mdash; Housing Nutrition Label</title>
<meta name="description" content="Where the Housing Nutrition Label reads an observed building record from the assessor instead of a modelled one: {homes_text(m['total'])} homes across {len(m['adapters'])} sources.">
<link rel="icon" href="favicon.svg" type="image/svg+xml" sizes="any">
<link rel="icon" href="favicon.ico" type="image/x-icon" sizes="any">
<link rel="apple-touch-icon" href="apple-touch-icon.png" sizes="180x180">
<meta name="theme-color" content="#13233d">
<link rel="stylesheet" href="style.css">
<style>{_STYLE}
{county_css(m)}
</style>
</head><body class="cov">
<!-- GENERATED by scripts/build_coverage.py — do not edit by hand. -->
<a href="#main" class="skip-link">Skip to content</a>
<nav>
  <a href="index.html" class="logo">Housing<span>Label</span>.dev</a>
  <button class="hamburger" aria-label="Menu">&#9776;</button>
  <ul>{nav}</ul>
</nav>
<main id="main">
<h1>Where the label reads the assessor's record</h1>
<p class="lede">Everywhere, the label <em>models</em> a building from national data: a
structure inventory and the census tract's year-built distribution. Where a county or
state publishes its assessment roll, the label reads what the assessor
<em>observed</em> instead &mdash; the actual year built, floor area and, in some places,
storeys, walls, foundation and condition. This page shows where that is true today.</p>

<div class="tiles">
  <div class="tile"><div class="num">{millions(m['total'])}</div><div class="cap">homes with an observed record source</div></div>
  <div class="tile"><div class="num">{m['share_pct']:.1f}%</div><div class="cap">of all US housing units</div></div>
  <div class="tile"><div class="num">{len(m['adapters'])}</div><div class="cap">assessor sources, queried live</div></div>
  <div class="tile"><div class="num">{m['counties']:,}</div><div class="cap">counties, in {m['states']} states and DC</div></div>
</div>

<div class="card">
  <h2>Share of US homes</h2>
  <p class="sub">Each segment is one source, sized by the housing units in the counties it answers for. Hover a segment for its name.</p>
  {share_bar(m)}
  <div class="share-cap"><span>{homes_text(m['total'])} covered</span><span>{homes_text(m['national'])} US housing units</span></div>
</div>

<div class="card map-wrap">
  <h2>Counties with an observed record source</h2>
  <p class="sub">Darker means more of the building comes from the record. Hover a county for what its assessor supplies; hover a source in the chart below to find its counties.</p>
  <div id="covmap" role="img" aria-label="Map of US counties shaded by how much of the building record the assessor supplies; the same detail is listed under Counties covered"><noscript><p>The interactive map needs JavaScript; the tables below carry the same information.</p></noscript></div>
  <div class="tip" id="covtip" role="tooltip"></div>
  <div class="legend">{legend}</div>
  <p class="sub" style="margin-top:.6rem">Every covered county is also listed, by source, under <a href="#county-list">Counties covered</a>.</p>
</div>

<div class="card">
  <h2>Homes covered, by source</h2>
  <p class="sub">ACS housing units in each source's counties.</p>
  {homes_bars(m)}
</div>

<div class="card">
  <h2>How coverage has grown</h2>
  <p class="sub">Homes reachable by an assessor source, by the date each one landed in the label.</p>
  {timeline_chart(m)}
</div>

<div class="card">
  <h2>What each source supplies</h2>
  <p class="sub">A field is only ever reported when the record unambiguously describes the home being scored &mdash; a tower's total floor area is never passed off as one condo's.</p>
  {field_matrix(m)}
</div>

<div class="card">
  <h2>Does the record make the label more accurate?</h2>
  <p class="sub">Measured where a benchmark exists: addresses drawn at random, scored from the address alone, compared with the assessor's own record. <a href="accuracy.html">Full methodology and caveats</a>.</p>
  <div class="key"><span><i style="--k:var(--base)"></i>Modelled</span><span><i style="--k:var(--series)"></i>With the assessor record</span></div>
  <div class="two">
    <div><h3>Year built within ±10 years</h3>{yb}</div>
    <div><h3>Building grade a reader sees is wrong</h3>{gr}</div>
  </div>
</div>

<div class="card">
  <h2>Is the right house found?</h2>
  <p class="sub">The dangerous failure is not a missing record but a neighbour's record shown as yours. Every source is checked end to end: homes drawn at random from the source itself, geocoded exactly as the label does, then looked up. When the address and the parcel do not agree, the label declines to guess and keeps its modelled value.</p>
  {verification_table(m)}
</div>

<div class="card" id="county-list">
  <h2>Counties covered</h2>
  <p class="sub">The map's county detail as a list, with ACS housing units per county.</p>
  {county_lists(m)}
</div>

<div class="card">
  <h2>What this page does and does not say</h2>
  <ul class="notes">
    <li><strong>A source is not a guarantee.</strong> Inside a covered county the label still falls back to its modelled values when the address cannot be matched to exactly one parcel, when the record omits a field, or when the assessor's service is slow. The "answered" rates above are the realistic share.</li>
    <li><strong>Serving is not measuring.</strong> Only the jurisdictions on the <a href="accuracy.html">accuracy page</a> carry measured accuracy figures. The others carry a verification run that checks the right parcel is found, which is a narrower claim.</li>
    <li><strong>Homes are ACS housing units</strong> in each source's counties, the same table the label uses for its year-built fallback. Some sources do not answer for every home in those counties (New York State's public layer, for instance, covers only the counties that opted in, and it is mapped that way).</li>
    <li><strong>Nothing is bundled.</strong> Every record is queried live from the publisher and cached briefly; owner names, mailing addresses and sale prices are never requested.</li>
    <li>What you enter on the label always wins over the assessor, and the assessor wins over the model.</li>
  </ul>
</div>

<p class="fine">{esc(DISCLAIMER)}</p>
<p class="fine">Generated from the adapter registry; newest source added {newest}. Regenerate with <code>python scripts/build_coverage.py --write</code>. County boundaries: US Census Bureau cartographic boundary files via us-atlas.</p>
</main>
<script type="application/json" id="coverage-data">{tooltip_data(m)}</script>
<script>{_SCRIPT}</script>
<script src="nav.js"></script>
</body></html>
"""


# ── the map asset ──────────────────────────────────────────────────────────────


def draw_map(topo: dict) -> str:
    """Every county as ``<path id="c<FIPS>">``, plus state borders, from TopoJSON."""
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def line(pts, close):
        px, py = round(pts[0][0], 1), round(pts[0][1], 1)
        segs = []
        for x, y in pts[1:]:
            x, y = round(x, 1), round(y, 1)
            dx, dy = round(x - px, 1), round(y - py, 1)
            if dx or dy:
                segs.append(f"{dx:g} {dy:g}".replace(" -", "-"))
                px, py = x, y
        if not segs:
            return ""    # a ring or arc smaller than the drawing's 0.1 px precision
        return f"M{round(pts[0][0], 1):g} {round(pts[0][1], 1):g}l" + " ".join(segs) + \
            ("z" if close else "")

    def ring(idx):
        pts = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.extend(a if not pts else a[1:])
        return pts

    def geom_path(g):
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        return "".join(line(ring(r), True) for poly in polys for r in poly)

    counties, dots = [], []
    for g in topo["objects"]["counties"]["geometries"]:
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        name = esc((g.get("properties") or {}).get("name", ""))
        counties.append(f'<path class="c" id="c{g["id"]}" data-n="{name}" d="{geom_path(g)}"/>')
        # Too small to find by eye or to hover: give it a dot the page can show.
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        pts = [p for poly in polys for r in poly for p in ring(r)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 20:
            dots.append(f'<circle class="c dot" id="d{g["id"]}" data-n="{name}" '
                        f'cx="{(max(xs) + min(xs)) / 2:.1f}" cy="{(max(ys) + min(ys)) / 2:.1f}" r="4"/>')
    # State borders as a mesh: each arc once, so shared borders are not stroked twice.
    used = set()
    for g in topo["objects"]["states"]["geometries"]:
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        for poly in polys:
            for r in poly:
                used.update(i if i >= 0 else ~i for i in r)
    mesh = "".join(line(arcs[i], False) for i in sorted(used))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 975 610" '
            'role="img" aria-label="US counties">' + "".join(counties)
            + f'<path class="s" d="{mesh}"/>' + "".join(dots) + '</svg>\n')


def fetch_map() -> str:
    import requests
    r = requests.get(ATLAS_URL, timeout=60)
    r.raise_for_status()
    return draw_map(r.json())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="rewrite docs/coverage.html")
    g.add_argument("--check", action="store_true", help="exit 1 if the page is stale")
    g.add_argument("--map", action="store_true", help="redraw docs/coverage-map.svg")
    args = ap.parse_args()
    if args.map:
        MAP.write_text(fetch_map(), encoding="utf-8")
        print(f"wrote {MAP.relative_to(_ROOT)}")
        return 0
    page = render(model())
    if args.check:
        if not MAP.exists():
            print(f"{MAP.relative_to(_ROOT)} is missing; run --map", file=sys.stderr)
            return 1
        if not PAGE.exists() or PAGE.read_text(encoding="utf-8") != page:
            print("docs/coverage.html is out of date with the adapter registry.\n"
                  "Run: python scripts/build_coverage.py --write", file=sys.stderr)
            return 1
        return 0
    if args.write:
        PAGE.write_text(page, encoding="utf-8")
        print(f"wrote {PAGE.relative_to(_ROOT)}")
        return 0
    sys.stdout.write(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
