# Supporting Dense Housing (Apartments, Townhomes, Condos) — Research & Roadmap

Research backing the roadmap item: *"properly support housing that is denser than
single-family detached — apartments, townhomes, and condominiums."* Today the label
is built entirely on single-family detached parcels and silently mis-scores anything
denser. This document records the diagnosis (what breaks and why), a multi-source
methodology review (how dense housing *should* be scored), the key design decision,
and a phased implementation plan.

---

## Bottom line

The engine has **no concept of building/structure type.** A dense address is scored as
a one-unit, 2,000-sqft detached house on its own lot, with its home value guessed from
the county single-family median. "Multi-unit" support today is a single arithmetic
trick — `build_parcel_row` divides only *value* and *lot acreage* by the unit count —
so of the nine dimensions **only Infrastructure meaningfully responds to density,
Environmental shifts slightly, and Energy does not respond at all** (despite the docs
advertising a shared-wall bonus that isn't implemented).

Fixing this is a **multi-PR program** with one foundational unlock — **detecting the
structure type and unit count from an address** (national datasets exist: FEMA USA
Structures, the USACE National Structure Inventory) — and then adopting established
per-dimension methods (FEMA Hazus occupancy classes, ENERGY STAR / ResStock multifamily
benchmarks, condo "value-per-door" valuation). The pivotal design choice is the **unit
of analysis**: score a *representative dwelling unit in its building context*.

---

## Part 1 — Diagnosis: why it doesn't work today

### Root cause: zero structure-type awareness
Nothing in `src/housing_label` branches on building type. A tree-wide search for
`condo|apartment|multifamily|townhome|structure_type|land_use|NUMUNIT` finds only doc
strings and the hidden `duplex`/`quadplex` presets. The Shelby CAMA field that encodes
style (`STYLE`) is ingested (`ingest/shelby_parcels.py:43`) and preserved
(`ingest/clean.py:15`) but **never read by any model**; the condo-unit fields
(`UNITNO`, `UNITDESC`) are dropped in cleaning (`ingest/clean.py:42`); and the pipeline
pulls only the single-family dwelling table `ASSR_DWELDAT`, never the commercial /
multifamily tables. Every model treats its input as one detached dwelling with its own
roof, foundation, exterior shell, and yard.

### The "multi-unit = fraction of a single-family home" model
`build_parcel_row` (`simulate/dimensions.py:126-150`) is the only place the unit count
is read into the model, and it divides **only** two fields:

```python
per_unit_acres = float(cfg.get("lot_acres", 0.25)) / units
per_unit_value = float(cfg.get("value", 160_000)) / units
# SFLA (sqft), EXTWALL, BSMT, COND, GRADE, YRBLT: unchanged, taken as per-unit
```

So `units` moves the label through exactly two channels: per-unit **value** (→
Infrastructure tax revenue and dollar EALs) and per-unit **lot acreage** (→
Infrastructure DU/acre and Environmental outdoor water).

### Per-dimension response to `units` today
| Dimension | Responds to units? | How |
|---|---|---|
| Infrastructure | **Yes (primary)** | `lot ÷ units` → DU/acre → road/water/police cost curves; fiscal ratio rises with density |
| Environmental | Weakly | smaller per-unit lot → less outdoor irrigation water |
| Energy | **No** | detached SF archetype; **no party-wall / shared-system term exists** |
| Resilience | No (score) | EAL-rate based; only the dollar loss scales with per-unit value |
| Durability, Health, Socioeconomic, Walkability, Climate | No | unit-blind |

### Docs-vs-code discrepancy (a correctness bug)
`methodology.html:96` and `examples.html:277` advertise a *"multi-unit shared-wall
bonus: 2 units = 0.85×, 3–4 = 0.80×, 5+ = 0.75×"* and *"the shared-wall efficiency bonus
cuts energy 25%."* **Neither exists in the engine.** The real `ENVELOPE_EUI_FACTOR` is
`{"icf": 0.92, "sip": 0.95}` and there is no unit-count factor anywhere. The declining
"Energy/Unit/Mo" figures in the examples table come only from the presets' smaller
per-unit sqft, not from any shared-wall model.

### Prioritized failure modes (what a real dense address gets wrong)
- **P0 — no type/units signal from an address.** The geocoder returns neither; the web
  form has no units or building-type field; everything defaults to `units=1, sqft=2000`
  detached (`simulate/location.py:41-57`, `house.py:665`, `dimensions.py:126`).
- **P0 — value auto-fill is the ACS single-family/owner-occupied median** (B25077,
  `house.py:1392-1397` → `propertytax.py:84-93`). For an apartment building every dollar
  figure is off by ~N units; for a condo the per-unit split double-divides a value that
  is already one unit.
- **P1 — Durability** credits each stacked unit its own roof/foundation/structural shell
  (`durability.py:116-125`) — meaningless for a 4th-floor condo.
- **P1 — Energy** uses NREL ResStock detached-single-family archetypes with no
  party-wall credit (`energy.py:101-108,166`), biasing attached forms to *higher* EUI →
  *worse* Energy scores, the opposite of reality.
- **P1 — Infrastructure** hard-codes "1 dwelling unit per parcel"
  (`infrastructure.py:47-49,338-339`) and extrapolates Memphis-sprawl cost curves past
  their calibration for true mid-rise density.
- **P2 — Resilience** fragility is wood-frame-detached (Hazus wood-frame damage ratios;
  no mid-rise concrete/steel construction type; per-parcel flood exposure applied to
  every floor of a stacked building). **P2 — Environmental** assumes a private yard and a
  fixed 2.65 occupancy (`environmental.py:155,246-271`; `RMBED` forced to NaN).
- **P3 — UI** exposes only 5 single-family presets plus a "compare 1–4 units" what-if;
  the multi-unit presets exist but are hidden from the website.

**Summary:** a townhome is the *least* wrong (detached-ish, own roof, fee-simple). A
condo is scored as if it owned the whole building. An apartment building is outside the
model's universe entirely.

---

## Part 2 — The key design decision: unit of analysis

Score a **representative dwelling unit in its building context.** Introduce explicit
`structure_type` (detached / townhome / low-rise MF / mid-rise / high-rise), `num_units`,
and `stories`; each dimension then uses the *unit* where the resident experiences it
(interior systems, in-unit energy, the unit's value) and the *building* where physics is
shared (structural shell, roof, foundation, party walls, central systems, density).

- **Condo** — owned per unit; value = the unit; shell/roof/systems = building. Score the
  unit; attribute shared elements at building level.
- **Apartment** — whole-building income property; the resident still occupies one unit.
  Score a representative unit; value via income / "value-per-door", not the SF median.
- **Townhome** — attached fee-simple; a narrow single-family **plus** a party-wall energy
  credit. Closest to today's model.

*Alternatives:* whole-building-only (loses the per-unit view the label is about) and
strict per-unit (can't represent shared physics) — both rejected. This framing is the
crux to confirm before the Phase 2 per-dimension build.

---

## Part 3 — Per-dimension methodology (adopt, don't invent)

- **Structure/type detection** — spatially join the geocoded point to a national
  building dataset (below) for occupancy type, stories, and footprint; layer assessor
  land-use codes where available.
- **Resilience** — use **FEMA Hazus occupancy classes**: RES1 (single-family) vs
  RES3A–RES3F (multifamily, binned by unit count), each with its own depth-damage and
  fragility functions; add mid-rise concrete/steel/podium construction types; make flood
  exposure floor-aware (upper units are safer); base the dollar loss on the correct value.
- **Energy** — the real **attached/party-wall envelope credit** (attached and stacked
  units have far less exterior surface per unit) plus **multifamily EUI archetypes**
  (NREL ResStock multifamily; ENERGY STAR Portfolio Manager multifamily national median
  source EUI ≈ 106 kBtu/sqft/yr), and central-system representation. This is where the
  promised shared-wall bonus becomes real and defensible.
- **Durability** — shared systems (roof, foundation, shell) attributed at building level;
  unit-level systems (interior finishes, in-unit HVAC / water heater) per unit.
- **Environmental** — per-unit / per-capita framing (multifamily is greener per unit:
  shared walls, smaller units, less exterior); drop private-yard irrigation for stacked
  units; occupancy from actual bedroom count.
- **Infrastructure** — use the real unit count for DU/acre instead of the `lot÷units`
  proxy; fix the revenue side to per-unit value × units; recalibrate/flag cost curves for
  genuine mid-rise density.
- **Value/tax** — condo = per-unit comparable value (don't re-divide); apartment =
  income / value-per-door; stop applying the SF owner-occupied median to dense buildings.
- **Location dimensions** (health, socioeconomic, walkability, climate) — unchanged; they
  are already location-only and unit-agnostic.

---

## Part 4 — External data sources

Structure type + unit count (the foundational enabler):
- **FEMA USA Structures** — ~125M building footprints with occupancy type
  (`OCC_CLS` / `PRIM_OCC`), public, national. <https://gis-fema.hub.arcgis.com/pages/usa-structures>
- **USACE National Structure Inventory (NSI)** — ~123M structures with stories, square
  footage, and occupancy type, public, national.
  <https://www.hec.usace.army.mil/confluence/nsi/>
- **Census Bureau** address / housing-unit counts by block; assessor land-use codes
  (jurisdiction-specific; e.g. NY 210 one-family vs 411 apartment).

Per-dimension methodology:
- **FEMA Hazus** occupancy classes RES1 / RES3A–F and their damage functions.
  <https://www.fema.gov/floodplain-management/tools-resources/hazus>
- **DOE ENERGY STAR Portfolio Manager** multifamily benchmarking + **NREL ResStock**
  multifamily archetypes. <https://www.energystar.gov/buildings/benchmark>,
  <https://resstock.nrel.gov/>
- Condo/apartment valuation: "value-per-door" and income-capitalization approaches
  (Appraisal Institute, *The Valuation of Condominiums, Cooperatives, and PUDs*).

---

## Part 5 — Phased roadmap

- **Phase 0 — Correctness floor + honesty (this PR).** Remove the false shared-wall
  energy claim from the docs; add a caveat that fires for multi-unit input warning that
  several dimensions use single-family assumptions; commit this research doc.
- **Phase 1 — Detect structure type + unit count from an address.** New
  `enrich/structure.py` + national data (USA Structures / NSI), spatial join on the
  geocoded point, add `structure_type`/`num_units`/`stories` to `Location`, expose in the
  payload, and add a web-form building-type + unit-count field. *The highest-leverage
  unlock.*
- **Phase 2 — Per-dimension multifamily methodology** (Resilience / Energy / Durability /
  Environmental / Infrastructure) per Part 3. Confirm the unit-of-analysis framing first.
- **Phase 3 — Value / tax basis** for condos and apartments (Part 3).
- **Phase 4 — UX & presentation** — building-type-aware presets, building context on the
  label, per-unit framing, confidence flags.
- **Phase 5 — Multifamily reference data / local grades** — the offline dataset is
  single-family only, so multifamily local percentile grades need a reference set (folds
  into the "scale beyond Shelby County" epic).

## Verification approach
Score known apartment, condo, and townhome addresses against a nearby single-family
address; confirm type/units detection (Phase 1), sane dollar figures (Phase 3), and that
Energy/Resilience/Durability move in the right direction for attached/stacked forms
(Phase 2). Unit tests per new lookup and per dimension (mirror `tests/test_utility_rates.py`);
regression test that single-family scores are unchanged when `structure_type = detached`.

---

## Reuse (existing patterns)
`data/*.py` FIPS/latlon lookups with US-average fallback (`egrid.py`, `govfinance.py`,
`propertytax.py`, `utility_rates.py`) are the template for the structure lookup;
`simulate/location.py::resolve_location` is where to thread the new fields; the `enrich/*`
row-model functions already take injected params (climate zone, grid factor, rates), so
structure/unit params attach the same way; the `/density` plumbing and the
`duplex`/`quadplex` presets (`house.py:334-353`) are reusable scaffolding.
