# Embodied Carbon — Real Building Footprint (USA Structures)

> **What this backs:** `src/housing_label/enrich/footprint.py` + the footprint path in
> `data/embodied_carbon.py`. Implements the geometry PR's flagged future work:
> *"an actual footprint polygon (FEMA USA Structures) would remove the shape-factor
> assumption."* **Date:** 2026-07-10. Constraint unchanged: open / keyless /
> redistributable.

---

## What changed

The geometry-aware embodied model estimated a home's **footprint** as
`floor_area / stories` and its **perimeter** as `4.1·√footprint` (a shape factor).
Two live improvements now replace those estimates with real data on the network path:

1. **Real footprint area + perimeter** from FEMA/ORNL **USA Structures**. When a
   building is found at the geocoded point, the model uses its actual footprint area
   and (geodesic) perimeter, and derives the number of levels as
   `floor_area / footprint_area`. This removes both the shape-factor perimeter *and*
   the stories guess.
2. **Real NSI stories wired through.** NSI already returned `num_story`, but the live
   path discarded it before the embodied model, so **every real address was scored as
   1-story**. It is now carried into the config (and used whenever a footprint isn't
   available).

Both are **network-only** and degrade to the previous shape-factor estimate offline
or when no building is found — so the offline golden snapshot is unchanged (no score
regression).

## Data source

**FEMA / Oak Ridge National Lab — USA Structures** (national building-footprint
inventory, ~125M structures >450 sq ft, all 50 states + DC + territories; national
view currency Nov 2023). Keyless, read-only ArcGIS REST `Query` service:

```
https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/USA_Structures_View/FeatureServer/0/query
```

Point-in-polygon query: `geometry=lon,lat`, `geometryType=esriGeometryPoint`,
`inSR=4326`, `spatialRel=esriSpatialRelIntersects`, `returnGeometry=true`,
`outSR=4326`, `outFields=SQMETERS,OCC_CLS`, `f=json`. **License: CC BY 4.0** —
attribution "FEMA / ORNL USA Structures" (surfaced in the footprint result + docs).

### Two gotchas handled
- **Area:** use the ORNL-precomputed **`SQMETERS`** (true 2-D footprint). The
  service's `Shape__Area`/`Shape__Length` are returned in **Web Mercator** and are
  inflated by ~`1/cos²(lat)` (≈ +65% at 39° N) — **not used**.
- **Perimeter:** there is no real-world perimeter attribute, so it is computed
  **geodesically** (haversine sum over the returned lon/lat rings). Verified against a
  live sample: geodesic 389.4 m vs the distorted `Shape__Length` 500.9 m (× cos 38.9°
  ≈ 390 — confirming the fix).

### Reliability
Empty features (rural / <450 sq ft / no building) → `None` (fall back to estimate);
multiple footprints on a shared edge → take the largest `SQMETERS`; network/service
failure → `None` after retries. Same best-effort posture as the existing NFHL/NSI
lookups. Results are `@lru_cache`d on rounded coordinates, and the whole lookup is
gated by `allow_network` (double-guarded, mirroring `structure.py`).

## Model use

`embodied_intensity_kgm2(..., footprint_area_m2, footprint_perimeter_m)`: when both
are present, `footprint = area`, `perimeter = perimeter`, and levels =
`max(1, floor_area / area)`; roof scales with `footprint × pitch`, envelope with
`perimeter × story_height × levels`, foundation from the real slab + perimeter walls.
When absent, the prior `floor_area/stories` + `4.1·√footprint` estimate is used.

## Score impact

Offline: **none** (golden unchanged — no network → estimate path). Live addresses now
reflect the building's true footprint and story count. Example (constructed NSI
record, 1,400 sqft, 2-story, 95 m² footprint): environmental 60.6 (1-story estimate) →
62.1 (real compact footprint). A sprawling 1-story home moves the other way. The
effect is a per-building correction, not a global shift.

## Flow

`resolve_location` (network) → `footprint_for_point` → `Location.footprint_area_m2 /
footprint_perimeter_m` → `_autofill_construction_from_nsi` sets `cfg[...]` (and
`cfg["stories"]` from NSI) → `build_parcel_row` → `model_parcel_environment` →
`embodied_intensity`.

## Caveats & further work

- USA Structures has no **stories** field and `HEIGHT` is frequently null, so stories
  come from NSI (or are derived from footprint + floor area) — not from the footprint
  service.
- Footprint area is a **2-D** footprint; complex roofs / multi-wing plans are
  approximated by the single polygon.
- The remaining embodied estimates called out previously — the **assembly allocations**
  (how AWC lumber/panel totals split across floor/wall/roof) and the **heavy-masonry
  wall factors** — are unchanged and still representative estimates; firming those needs
  a per-assembly takeoff source (BEAM/Athena run per archetype), a separate effort.
