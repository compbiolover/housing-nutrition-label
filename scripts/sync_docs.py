#!/usr/bin/env python3
"""Keep the docs site's code-derived tables in sync with the scoring engine.

The Setup (``docs/setup.html``) and Reference (``docs/reference.html``) pages
duplicate a lot of *factual* data that actually lives in the Python code: the
dimension roster, the construction / condition / foundation / year-built
vulnerability factors, the resilience-upgrade multipliers, the presets, and the
CLI feature flags. Every one of those numbers is a source-of-truth constant in
``housing_label`` — so whenever the code changes, the pages silently drift.

This is the same problem ``scripts/sync_readme.py`` already solves for the
README's dimension roster; this script extends the idea to the website. It
regenerates the code-derived regions of both pages from the live constants, so
they can never go stale (and CI fails until the committed HTML matches).

Single sources of truth
-----------------------
* ``simulate.dimensions.DIMENSIONS`` / ``CONSTRUCTION_DRIVEN`` / ``LOCATION_DRIVEN``
  and ``GRADE_BY_CONSTRUCTION`` — the dimension roster and per-wall build grade.
* ``simulate.house`` — ``CONSTRUCTION_FACTOR`` / ``FLOOD_CONSTRUCTION_FACTOR`` /
  ``FIRE_CONSTRUCTION_FACTOR``, ``CONDITION_FACTOR``, ``FOUNDATION_FACTOR``, the
  ``BONUS_*`` upgrade multipliers, ``BONUS_FLAGS``, and ``PRESETS``.
* ``score.resilience`` — the continuous year-built code-era / fire-age anchors.

The *qualitative* prose (a dimension's "Measures" blurb, a wall type's notes,
etc.) is curated here alongside the constant it annotates, keyed so that adding
a new dimension / wall / upgrade / preset to the code raises a ``KeyError`` until
it is documented here — the drift guard runs in both directions.

Managed regions (everything between a marker pair is overwritten)::

    <!-- BEGIN AUTOGEN:<id> ... -->
    ... generated HTML ...
    <!-- END AUTOGEN:<id> -->

Usage::

    python scripts/sync_docs.py --write     # rewrite the managed regions in place
    python scripts/sync_docs.py --check      # exit 1 if a page is out of date (CI)

With neither flag it prints every generated block to stdout (a dry run).
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.simulate.dimensions import (  # noqa: E402
    DIMENSIONS, CONSTRUCTION_DRIVEN, LOCATION_DRIVEN, GRADE_BY_CONSTRUCTION,
)
from housing_label.simulate.house import (  # noqa: E402
    CONSTRUCTION_FACTOR, FLOOD_CONSTRUCTION_FACTOR, FIRE_CONSTRUCTION_FACTOR,
    CONDITION_FACTOR, FOUNDATION_FACTOR, PRESETS, BONUS_FLAGS,
    BONUS_SOLAR, BONUS_GENERATOR, BONUS_PASSIVE, BONUS_SPRINKLERS,
    BONUS_FIRE_SPRINKLERS, BONUS_SAFE_ROOM, BONUS_LEAK_DETECT, BONUS_SEISMIC_RET,
    BONUS_HURRICANE_STRAPS, BONUS_HIP_ROOF, BONUS_IMPACT_GARAGE_DOOR,
    BONUS_SEALED_ROOF_DECK, BONUS_METAL_ROOF, BONUS_REINFORCED_GABLE,
    BONUS_RING_SHANK_NAILS, BONUS_TRUSS_16OC,
    BONUS_FORTIFIED_ROOF, BONUS_FORTIFIED_SILVER, BONUS_FORTIFIED_GOLD,
    BONUS_CRIPPLE_WALL, BONUS_SEISMIC_HOLD_DOWNS, BONUS_AUTO_GAS_SHUTOFF,
    BONUS_ELEVATION_1FT, BONUS_ELEVATION_2FT, BONUS_ELEVATION_3FT,
    BONUS_FLOOD_VENTS, BONUS_BACKFLOW_VALVE,
)
from housing_label.score.resilience import (  # noqa: E402
    CODE_ERA_ANCHOR_YEARS, CODE_ERA_ANCHOR_FACTORS,
    FIRE_AGE_ANCHOR_YEARS, FIRE_AGE_ANCHOR_FACTORS,
)

REFERENCE = _ROOT / "docs" / "reference.html"
SETUP = _ROOT / "docs" / "setup.html"

# Written-out cardinals so the prose reads naturally for any plausible count.
_CARDINALS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
}


def _cardinal(n: int) -> str:
    return _CARDINALS.get(n, str(n))


# ── Curated display metadata (keyed by the code's own keys) ─────────────────────
# Each dict below is checked against the corresponding code constant at generate
# time, so a new dimension / wall / foundation / condition / upgrade / preset in
# the code fails loudly here until its human-facing row is filled in.

# Per-dimension catalog copy for the Reference page's "dimensions" table. Keyed by
# the DIMENSIONS key; `res` is the pre-built resolution-tag cell (HTML).
DIM_META = {
    "resilience": dict(
        measures="Expected annual loss from flood, tornado, earthquake &amp; fire",
        source="FEMA NFHL, FEMA NRI, USGS, NFPA base rate",
        res='<span class="tag point">point</span> <span class="tag tract">tract</span> '
            '<span class="tag config">+ config</span>'),
    "energy": dict(
        measures="Modeled energy use intensity vs. a ResStock building-type&times;climate-zone"
                 "&times;vintage benchmark",
        source="NREL ResStock 2024 (building type&times;zone&times;vintage + foundation/HVAC "
               "factors) + IECC climate zone + construction model",
        res='<span class="tag county">county</span> <span class="tag config">+ config</span>'),
    "durability": dict(
        measures="Building longevity from materials, build quality &amp; condition",
        source="Construction model",
        res='<span class="tag config">config</span>'),
    "environmental": dict(
        measures="Embodied + operational carbon over the building's life",
        source="Material carbon + eGRID2023 Rev 2 subregion grid average + NREL Cambium 2023 "
               "LRMER marginal factor",
        res='<span class="tag county">county</span> <span class="tag config">+ config</span>'),
    "infrastructure": dict(
        measures="Fiscal cost-to-serve vs. the revenue the parcel generates",
        source="Census of Governments spending + ACS tax model (per county)",
        res='<span class="tag county">county</span>'),
    "health": dict(
        measures="Neighborhood health outcomes (national percentile)",
        source="CDC PLACES",
        res='<span class="tag tract">tract</span>'),
    "air_quality": dict(
        measures="Ambient PM2.5 + ozone &amp; radon zone (national percentile)",
        source="CDC Tracking (PM2.5/ozone) + EPA radon zones",
        res='<span class="tag tract">tract</span> <span class="tag county">+ county radon</span>'),
    "noise": dict(
        measures="Transportation-noise exposure &mdash; % of residents at &ge;60&nbsp;dB "
                 "(national percentile)",
        source="US DOT BTS National Transportation Noise Map",
        res='<span class="tag tract">tract</span>'),
    "socioeconomic": dict(
        measures="Neighborhood socioeconomic index (national percentile)",
        source="Census ACS",
        res='<span class="tag tract">tract</span>'),
    "walkability": dict(
        measures="How walkable the location is",
        source="EPA National Walkability Index",
        res='<span class="tag tract">tract</span>'),
    "climate": dict(
        measures="Projected extreme heat, heavy precip/flood &amp; drought "
                 "(RCP4.5&ndash;8.5, mid-century)",
        source="NOAA/DOI CMRA (LOCA/NCA4)",
        res='<span class="tag county">county</span>'),
    "solar": dict(
        measures="Rooftop specific yield (kWh/kW&middot;yr) &mdash; production, $ saved &amp; "
                 "CO&#8322; avoided (national percentile)",
        source="PVGIS v5.2 on NREL NSRDB",
        res='<span class="tag county">county</span>'),
    "water": dict(
        measures="Community-water-system health-based violation exposure &mdash; % of residents "
                 "on a system with a recent violation (national percentile)",
        source="EPA SDWIS federal reporting",
        res='<span class="tag county">county</span>'),
}

# Per-wall label + notes for the "Wall / construction type" table. Order follows
# CONSTRUCTION_FACTOR. `short` is the concise label used in derived preset copy.
CONSTRUCTION_META = {
    "frame": dict(
        label="Wood frame", short="wood frame",
        notes="Light wood frame &mdash; the baseline; most vulnerable to wind/seismic"),
    "vinyl": dict(
        label="Vinyl-sided frame", short="vinyl-sided frame",
        notes="Wood frame with vinyl siding: slight wind benefit, slightly lower build grade"),
    "brick-frame": dict(
        label="Brick veneer / frame", short="brick veneer / frame",
        notes="Brick veneer over a wood frame &mdash; composite baseline"),
    "brick": dict(
        label="Brick (solid masonry)", short="solid brick",
        notes="Solid brick; better lateral resistance &amp; less combustible"),
    "block": dict(
        label="Concrete block (CMU)", short="concrete block",
        notes="Reinforced masonry; strong lateral resistance"),
    "stone": dict(
        label="Stone", short="stone",
        notes="Solid masonry; best of the traditional types"),
    "icf": dict(
        label="ICF (insulated concrete form)", short="ICF",
        notes="Monolithic concrete shell; huge wind/seismic &amp; fire benefit "
              "(finishes still flood-vulnerable)"),
    "sip": dict(
        label="SIP (structural insulated panel)", short="SIP",
        notes="Engineered wood composite; excellent racking resistance, frame-like fire behavior"),
}

# Condition rows: label + optional annotation. Order follows CONDITION_FACTOR.
CONDITION_META = {
    "unsound":   dict(label="Unsound", note="(worst)"),
    "poor":      dict(label="Poor", note=""),
    "fair":      dict(label="Fair", note=""),
    "average":   dict(label="Average", note="(baseline)"),
    "good":      dict(label="Good", note=""),
    "excellent": dict(label="Excellent", note="(best)"),
}

# Foundation rows: label + parenthetical + concise preset label. Order follows
# FOUNDATION_FACTOR.
FOUNDATION_META = {
    "slab":             dict(label="Slab", short="slab",
                             note="at/above grade; least flood loss"),
    "crawl":            dict(label="Crawl space", short="crawl space", note="baseline"),
    "partial-basement": dict(label="Partial basement", short="partial basement", note=""),
    "full-basement":    dict(label="Full basement", short="full basement", note="most flood loss"),
}

# Year-built code-era anchors (wind/seismic). Keyed by anchor year.
CODE_ERA_NOTES = {
    1940: "Pre-WWII: balloon framing, no engineered connections",
    1970: "Pre-modern seismic/wind codes (pre-1972 wind, pre-1971 seismic)",
    1990: "Early modern (ASCE&nbsp;7 wind), pre-Northridge detailing",
    2003: "Baseline &mdash; IBC maturity / ASCE&nbsp;7-02",
    2010: "Fully modern IBC / ASCE&nbsp;7-05&ndash;7-10",
}

# Fire wiring-era anchors. Keyed by anchor year.
FIRE_AGE_NOTES = {
    1950: "Knob-and-tube era (highest electrical-fire risk)",
    1975: "Aluminum branch-wiring era",
    2002: "Modern NM-B cable, pre-AFCI baseline",
    2010: "NEC&nbsp;2002+ AFCI / tamper-resistant receptacles",
}

# Concise upgrade names for derived preset copy. Must cover every BONUS_FLAGS entry.
SHORT_UPGRADE = {
    "solar": "solar", "backup_generator": "generator", "passive_house": "passive house",
    "tornado_safe_room": "safe room", "fire_sprinklers": "sprinklers",
    "leak_detection": "leak detection", "seismic_retrofit": "seismic retrofit",
    "hurricane_straps": "hurricane straps", "hip_roof": "hip roof",
    "impact_garage_door": "impact garage door", "sealed_roof_deck": "sealed roof deck",
    "metal_roof": "metal roof", "reinforced_gable": "reinforced gable",
    "ring_shank_nails": "ring-shank nails", "truss_16oc": "16&Prime; OC trusses",
    "fortified_roof": "FORTIFIED Roof", "fortified_silver": "FORTIFIED Silver",
    "fortified_gold": "FORTIFIED Gold", "cripple_wall_bracing": "cripple-wall bracing",
    "seismic_hold_downs": "seismic hold-downs", "auto_gas_shutoff": "auto gas shutoff",
    "elevation_1ft": "+1&nbsp;ft elevation", "elevation_2ft": "+2&nbsp;ft elevation",
    "elevation_3ft": "+3&nbsp;ft elevation", "flood_vents": "flood vents",
    "backflow_valve": "backflow valve",
}

# Resilience-upgrade tables, grouped as they appear on the Reference page. Each
# row is (curated label, code multiplier constant, flag-key it belongs to, factor
# cell HTML — None means "render the multiplier"). `flag` ties the row back to
# BONUS_FLAGS so coverage can be asserted (fire_sprinklers legitimately appears in
# two groups — General and Fire — so the union, not the list, is compared).
UPGRADE_GROUPS = [
    ("General (apply to flood, tornado &amp; seismic)", [
        ("Solar panels", BONUS_SOLAR, "solar", None),
        ("Backup generator / battery", BONUS_GENERATOR, "backup_generator", None),
        ("Passive-house certification", BONUS_PASSIVE, "passive_house", None),
        ("Fire sprinklers", BONUS_SPRINKLERS, "fire_sprinklers",
         f"{BONUS_SPRINKLERS:.2f} here, <strong>and {BONUS_FIRE_SPRINKLERS:.2f} on fire</strong>"),
    ]),
    ("Wind / tornado", [
        ("Tornado safe room (FEMA P-361)", BONUS_SAFE_ROOM, "tornado_safe_room", None),
        ("Hurricane straps (continuous load path)", BONUS_HURRICANE_STRAPS, "hurricane_straps", None),
        ("Hip roof", BONUS_HIP_ROOF, "hip_roof", None),
        ("Impact-rated garage door", BONUS_IMPACT_GARAGE_DOOR, "impact_garage_door", None),
        ("Sealed roof deck", BONUS_SEALED_ROOF_DECK, "sealed_roof_deck", None),
        ("Standing-seam metal roof", BONUS_METAL_ROOF, "metal_roof", None),
        ("Reinforced gable ends", BONUS_REINFORCED_GABLE, "reinforced_gable", None),
        ("Ring-shank nails", BONUS_RING_SHANK_NAILS, "ring_shank_nails", None),
        ("16&Prime; OC trusses", BONUS_TRUSS_16OC, "truss_16oc", None),
    ]),
    ("IBHS FORTIFIED (composite &mdash; supersedes the wind features above)", [
        ("FORTIFIED Roof", BONUS_FORTIFIED_ROOF, "fortified_roof", None),
        ("FORTIFIED Silver", BONUS_FORTIFIED_SILVER, "fortified_silver", None),
        ("FORTIFIED Gold", BONUS_FORTIFIED_GOLD, "fortified_gold", None),
    ]),
    ("Seismic", [
        ("Seismic retrofit / base isolation", BONUS_SEISMIC_RET, "seismic_retrofit", None),
        ("Cripple-wall bracing", BONUS_CRIPPLE_WALL, "cripple_wall_bracing", None),
        ("Seismic hold-downs", BONUS_SEISMIC_HOLD_DOWNS, "seismic_hold_downs", None),
        ("Automatic gas shut-off valve", BONUS_AUTO_GAS_SHUTOFF, "auto_gas_shutoff", None),
    ]),
    ("Flood", [
        ("Elevated +1&nbsp;ft above BFE", BONUS_ELEVATION_1FT, "elevation_1ft", None),
        ("Elevated +2&nbsp;ft", BONUS_ELEVATION_2FT, "elevation_2ft", None),
        ("Elevated +3&nbsp;ft", BONUS_ELEVATION_3FT, "elevation_3ft", None),
        ("Engineered flood vents", BONUS_FLOOD_VENTS, "flood_vents", None),
        ("Backflow-prevention valve", BONUS_BACKFLOW_VALVE, "backflow_valve", None),
        ("Smart leak detection", BONUS_LEAK_DETECT, "leak_detection", None),
    ]),
    ("Fire", [
        ("Fire sprinklers", BONUS_FIRE_SPRINKLERS, "fire_sprinklers",
         f"{BONUS_FIRE_SPRINKLERS:.2f} on the fire peril (~60% loss reduction)"),
    ]),
]

# Above-code CLI feature flags, grouped for the Setup page. Every BONUS_FLAGS
# entry must appear in exactly one group (asserted below).
FEATURE_FLAG_GROUPS = [
    ("Wind/Tornado", ["hurricane_straps", "hip_roof", "impact_garage_door",
                      "sealed_roof_deck", "metal_roof", "reinforced_gable",
                      "ring_shank_nails", "truss_16oc"]),
    ("FORTIFIED", ["fortified_roof", "fortified_silver", "fortified_gold"]),
    ("Seismic", ["cripple_wall_bracing", "seismic_hold_downs", "auto_gas_shutoff",
                 "seismic_retrofit"]),
    ("Flood", ["elevation_1ft", "elevation_2ft", "elevation_3ft", "flood_vents",
               "backflow_valve", "leak_detection"]),
    ("General", ["solar", "backup_generator", "passive_house", "tornado_safe_room",
                 "fire_sprinklers"]),
]


# ── Formatting helpers ──────────────────────────────────────────────────────────
def _f2(v: float) -> str:
    """Two-decimal factor (matches how the pages have always shown multipliers)."""
    return f"{v:.2f}"


def _mult(v: float) -> str:
    """Loss multiplier with the × suffix, e.g. 1.5×, 0.85× — at most two decimals,
    trailing zero trimmed but always at least one decimal (1.0×, not 1×)."""
    s = f"{v:.2f}"
    if s.endswith("0"):          # 1.60→1.6, 1.00→1.0; leaves 0.85 untouched
        s = s[:-1]
    return f"{s}&times;"


def _validate() -> None:
    """Fail loudly if the curated metadata and the code constants have drifted —
    the point of the whole exercise, run in both directions."""
    def _same(name, a, b):
        if set(a) != set(b):
            raise SystemExit(
                f"sync_docs: {name} is out of sync with the code.\n"
                f"  missing here: {sorted(set(b) - set(a))}\n"
                f"  extra here:   {sorted(set(a) - set(b))}")

    _same("DIM_META", DIM_META, dict(DIMENSIONS))
    _same("CONSTRUCTION_META", CONSTRUCTION_META, CONSTRUCTION_FACTOR)
    _same("CONDITION_META", CONDITION_META, CONDITION_FACTOR)
    _same("FOUNDATION_META", FOUNDATION_META, FOUNDATION_FACTOR)
    _same("SHORT_UPGRADE", SHORT_UPGRADE, {f: 1 for f in BONUS_FLAGS})

    upgrade_flags = {row[2] for _title, rows in UPGRADE_GROUPS for row in rows}
    _same("UPGRADE_GROUPS", {f: 1 for f in upgrade_flags}, {f: 1 for f in BONUS_FLAGS})

    flat = [f for _title, flags in FEATURE_FLAG_GROUPS for f in flags]
    if len(flat) != len(set(flat)):
        raise SystemExit("sync_docs: a flag is listed in two FEATURE_FLAG_GROUPS")
    _same("FEATURE_FLAG_GROUPS", {f: 1 for f in flat}, {f: 1 for f in BONUS_FLAGS})


# ── Region generators (return the inner HTML, markers added by _block) ──────────
def gen_ref_dimensions() -> str:
    n = len(DIMENSIONS)
    lines = [
        f'  <h2>The {_cardinal(n)} dimensions</h2>',
        '  <p>The composite is the mean of whichever dimensions could be scored '
        '(location dimensions are omitted, not zeroed, when their data/keys are '
        'unavailable). National grades use absolute thresholds: A&nbsp;&ge;&nbsp;80, '
        'B&nbsp;&ge;&nbsp;60, C&nbsp;&ge;&nbsp;40, D&nbsp;&ge;&nbsp;20, F&nbsp;&lt;&nbsp;20.</p>',
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Dimension</th><th>Measures</th><th>Data source</th>'
        '<th>Resolution</th></tr></thead>',
        '    <tbody>',
    ]
    for key, label in DIMENSIONS:
        m = DIM_META[key]
        lines.append(
            f'      <tr><td>{label}</td><td>{m["measures"]}</td>'
            f'<td>{m["source"]}</td><td>{m["res"]}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def gen_ref_construction() -> str:
    lines = [
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Type</th><th>Wind / seismic</th><th>Flood</th><th>Fire</th>'
        '<th>Build grade</th><th>Notes</th></tr></thead>',
        '    <tbody>',
    ]
    for key in CONSTRUCTION_FACTOR:
        m = CONSTRUCTION_META[key]
        lines.append(
            f'      <tr><td>{m["label"]}</td><td>{_f2(CONSTRUCTION_FACTOR[key])}</td>'
            f'<td>{_f2(FLOOD_CONSTRUCTION_FACTOR[key])}</td>'
            f'<td>{_f2(FIRE_CONSTRUCTION_FACTOR[key])}</td>'
            f'<td>{GRADE_BY_CONSTRUCTION[key]}</td><td>{m["notes"]}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def gen_ref_condition() -> str:
    lines = [
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Condition</th><th>Loss multiplier</th></tr></thead>',
        '    <tbody>',
    ]
    for key, factor in CONDITION_FACTOR.items():
        m = CONDITION_META[key]
        cell = f'{_mult(factor)} {m["note"]}'.strip()
        lines.append(f'      <tr><td>{m["label"]}</td><td>{cell}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def gen_ref_foundation() -> str:
    lines = [
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Foundation</th><th>Flood multiplier</th></tr></thead>',
        '    <tbody>',
    ]
    for key, factor in FOUNDATION_FACTOR.items():
        m = FOUNDATION_META[key]
        cell = f'{_mult(factor)} ({m["note"]})' if m["note"] else _mult(factor)
        lines.append(f'      <tr><td>{m["label"]}</td><td>{cell}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def _year_rows(years, factors, notes, label_first, label_last):
    """Anchor rows for a continuous year-built curve (first/last note the clamp)."""
    n = len(years)
    out = []
    for i, (yr, fac) in enumerate(zip(years, factors)):
        if i == 0:
            yr_label = f"{yr} or earlier"
        elif i == n - 1:
            yr_label = f"{yr} or later"
        else:
            yr_label = str(yr)
        out.append((yr_label, fac, notes[yr]))
    return out


def gen_ref_year_code() -> str:
    lines = [
        '  <p>The build-code era (wind/seismic) vulnerability is a <strong>continuous</strong> '
        'curve, linearly interpolated between the anchor years below and clamped beyond '
        'them &mdash; a 1969 and a 1970 build no longer differ by a cliff. <strong>Lower '
        'is better.</strong></p>',
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Anchor year</th><th>Code factor (wind/seismic)</th><th>Era</th></tr></thead>',
        '    <tbody>',
    ]
    for yr_label, fac, note in _year_rows(
            CODE_ERA_ANCHOR_YEARS, CODE_ERA_ANCHOR_FACTORS, CODE_ERA_NOTES, None, None):
        lines.append(f'      <tr><td>{yr_label}</td><td>{_mult(fac)}</td><td>{note}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def gen_ref_year_fire() -> str:
    lines = [
        '  <p>A separate <strong>continuous</strong> curve captures the electrical/wiring era '
        '(fire peril), interpolated between these anchors and clamped beyond them.</p>',
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Anchor year</th><th>Fire factor</th><th>Wiring era</th></tr></thead>',
        '    <tbody>',
    ]
    for yr_label, fac, note in _year_rows(
            FIRE_AGE_ANCHOR_YEARS, FIRE_AGE_ANCHOR_FACTORS, FIRE_AGE_NOTES, None, None):
        lines.append(f'      <tr><td>{yr_label}</td><td>{_mult(fac)}</td><td>{note}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def gen_ref_upgrades() -> str:
    lines = []
    for title, rows in UPGRADE_GROUPS:
        lines.append(f'  <h3>{title}</h3>')
        lines.append('  <div class="table-scroll"><table class="data-table">'
                     '<thead><tr><th>Upgrade</th><th>Factor</th></tr></thead><tbody>')
        for label, factor, _flag, cell in rows:
            value = cell if cell is not None else _f2(factor)
            lines.append(f'    <tr><td>{label}</td><td>{value}</td></tr>')
        lines.append('  </tbody></table></div>')
    return "\n".join(lines)


def _preset_profile(name: str, p: dict) -> str:
    """A readable, fully code-derived one-line profile for a preset."""
    constr = CONSTRUCTION_META[p["construction"]]["short"]
    parts = [f'{p["year_built"]} {constr}']
    units = int(p.get("units", 1) or 1)
    if units > 1:
        parts.append(f'{units} units &times; {int(p["sqft"]):,} sqft')
    else:
        parts.append(FOUNDATION_META[p["foundation"]]["short"])
    parts.append(p["condition"])
    parts.append(f'zone {p.get("flood_zone", "X")}')
    if p.get("value"):
        parts.append(f'${p["value"] // 1000:,}k')
    base = ", ".join(parts)
    ups = [SHORT_UPGRADE[f] for f in BONUS_FLAGS if p.get(f)]
    if ups:
        base += " &mdash; " + ", ".join(ups)
    return base


def gen_ref_presets() -> str:
    lines = [
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Preset</th><th>Profile</th></tr></thead>',
        '    <tbody>',
    ]
    for name, p in PRESETS.items():
        lines.append(f'      <tr><td>{name}</td><td>{_preset_profile(name, p)}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def gen_setup_presets() -> str:
    lines = [
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Preset</th><th>Description</th></tr></thead>',
        '    <tbody>',
    ]
    for name, p in PRESETS.items():
        lines.append(
            f'      <tr><td><code>{name}</code></td><td>{_preset_profile(name, p)}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def gen_setup_feature_flags() -> str:
    lines = [
        '  <div class="table-scroll"><table class="data-table">',
        '    <thead><tr><th>Category</th><th>Flags</th></tr></thead>',
        '    <tbody>',
    ]
    for category, flags in FEATURE_FLAG_GROUPS:
        cli = " ".join(f'<code>--{f.replace("_", "-")}</code>' for f in flags)
        lines.append(f'      <tr><td>{category}</td><td>{cli}</td></tr>')
    lines += ['    </tbody>', '  </table></div>']
    return "\n".join(lines)


def gen_setup_dimension_counts() -> str:
    """The House-Simulator intro paragraphs — the dimension count and the
    construction/location split (names and counts all derived from the code). The
    detailed data-source prose that follows stays curated in the page."""
    n = len(DIMENSIONS)
    # "construction-driven" as the pages count it = the construction dimensions plus
    # resilience, which blends the build (EAL modifiers) with location hazard exposure.
    constr_names = [k for k, _ in DIMENSIONS if k == "resilience" or k in CONSTRUCTION_DRIVEN]
    n_constr = len(constr_names)
    n_loc = len(LOCATION_DRIVEN)
    names = ", ".join(constr_names)
    return (
        f'  <p>The CLI simulator lets you define a hypothetical house and see its full '
        f'nutrition label &mdash; all {_cardinal(n)} dimensions &mdash; instantly.</p>\n'
        f'  <p>{_cardinal(n_constr).capitalize()} dimensions are '
        f'<strong>construction-driven</strong> ({names}) &mdash; modeled offline from the '
        f'house configuration; the other {_cardinal(n_loc)} are '
        f'<strong>location-driven</strong>, resolved by the house\'s census tract or county '
        f'(no API key needed).</p>')


# ── Region wiring ───────────────────────────────────────────────────────────────
# Each region: (id, target file, generator). The id is the AUTOGEN marker key.
REGIONS = [
    ("ref-dimensions", REFERENCE, gen_ref_dimensions),
    ("ref-construction", REFERENCE, gen_ref_construction),
    ("ref-condition", REFERENCE, gen_ref_condition),
    ("ref-foundation", REFERENCE, gen_ref_foundation),
    ("ref-year-code", REFERENCE, gen_ref_year_code),
    ("ref-year-fire", REFERENCE, gen_ref_year_fire),
    ("ref-upgrades", REFERENCE, gen_ref_upgrades),
    ("ref-presets", REFERENCE, gen_ref_presets),
    ("setup-dimension-counts", SETUP, gen_setup_dimension_counts),
    ("setup-presets", SETUP, gen_setup_presets),
    ("setup-feature-flags", SETUP, gen_setup_feature_flags),
]


def _begin(rid: str) -> str:
    return (f"<!-- BEGIN AUTOGEN:{rid} (managed by scripts/sync_docs.py — edits here are "
            f"overwritten; run `python scripts/sync_docs.py --write`) -->")


def _end(rid: str) -> str:
    return f"<!-- END AUTOGEN:{rid} -->"


def _block(rid: str, generator) -> str:
    """The full managed region (markers + generated body)."""
    return f"{_begin(rid)}\n{generator()}\n{_end(rid)}"


def _region_re(rid: str) -> re.Pattern:
    return re.compile(re.escape(_begin(rid)) + r".*?" + re.escape(_end(rid)), re.DOTALL)


def _apply(text: str, rid: str, block: str) -> str:
    if not _region_re(rid).search(text):
        raise SystemExit(
            f"sync_docs: markers for {rid!r} not found. Add this region where the "
            f"generated block should live:\n\n{block}\n")
    return _region_re(rid).sub(lambda _m: block, text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true",
                   help="Rewrite the managed regions in the HTML pages in place.")
    g.add_argument("--check", action="store_true",
                   help="Exit non-zero if a page is out of sync (for CI).")
    args = ap.parse_args()

    _validate()

    # Dry run: print each generated block without touching the files (no markers needed).
    if not args.write and not args.check:
        for rid, _path, generator in REGIONS:
            print(_block(rid, generator))
            print()
        return 0

    # Group regions per file so each file is read/written once.
    by_file: dict[pathlib.Path, list] = {}
    for rid, path, generator in REGIONS:
        by_file.setdefault(path, []).append((rid, generator))

    out_of_sync = False
    for path, regions in by_file.items():
        if not path.exists():
            print(f"sync_docs: {path} not found", file=sys.stderr)
            return 2
        text = original = path.read_text(encoding="utf-8")
        for rid, generator in regions:
            text = _apply(text, rid, _block(rid, generator))

        if args.check:
            if text != original:
                out_of_sync = True
                print(f"{path.relative_to(_ROOT)} is out of sync with the code.",
                      file=sys.stderr)
        elif args.write:
            if text != original:
                path.write_text(text, encoding="utf-8")
                print(f"{path.relative_to(_ROOT)} updated.")
            else:
                print(f"{path.relative_to(_ROOT)} already in sync.")

    if args.check:
        if out_of_sync:
            print("Run: python scripts/sync_docs.py --write", file=sys.stderr)
            return 1
        print("docs pages are in sync with the code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
