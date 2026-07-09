#!/usr/bin/env python3
"""location.py — resolve an address or lat/lon to everything the label needs.

A single entry point, ``resolve_location``, turns a free-text address *or* a
lat/lon pair into a ``Location`` carrying the geographies and reference data the
dimensions depend on:

  • lat / lon
  • state FIPS, county FIPS (5-digit), county name, census tract GEOID
  • whether the point falls in a Census Urban Area (urban-core proxy)
  • IECC climate zone (bundled county lookup)
  • eGRID subregion + grid CO2 factor (bundled county lookup)
  • climate-hazard projection (bundled county lookup)

Geocoding uses the U.S. Census Geocoder (keyless): the ``onelineaddress``
endpoint for an address, the ``coordinates`` endpoint for a lat/lon. Both return
the geographies in one call. Network/lookup failures degrade gracefully —
fields are left ``None`` and recorded in ``notes`` rather than raising, so the
caller can still score the dimensions that don't need them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

from housing_label.config import TIMEOUT, RETRIES, BACKOFF, HEADERS
from housing_label.data import climate as climate_data
from housing_label.data import climate_projections as climate_proj_data
from housing_label.data import egrid as egrid_data
from housing_label.data import wildfire as wildfire_data

GEOCODER_ONELINE = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
GEOCODER_COORDS = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
BENCHMARK = "Public_AR_Current"
VINTAGE = "Current_Current"


@dataclass
class Location:
    """Everything the label needs about where a house sits."""
    lat: float
    lon: float
    state_fips: str | None = None
    county_fips: str | None = None        # 5-digit state+county GEOID
    county_name: str | None = None
    tract: str | None = None              # 11-digit tract GEOID
    place_label: str | None = None
    in_urban_area: bool | None = None
    climate_zone: str | None = None       # IECC zone, e.g. "4A"
    egrid_subregion: str | None = None
    egrid_factor: float | None = None     # kg CO2e / kWh
    climate_projection: dict | None = None  # CMIP6-LOCA2 hazard projection (tract→county→US)
    wildfire: dict | None = None          # FEMA NRI wildfire hazard (tract→county→US)
    # Building structure at this point (USACE National Structure Inventory). Best
    # effort — all None when NSI is unavailable or the point isn't a building.
    structure_type: str | None = None     # single_family | multifamily | manufactured | ...
    num_units: int | None = None          # residential unit count
    stories: int | None = None
    bldg_material: str | None = None      # wood | masonry | concrete | steel | manufactured | other
    # Auto-derived construction profile from NSI (best-effort estimates the user
    # can override). year_built is a census-area MEDIAN (not the real year); sqft
    # and foundation are from the addressed structure; construction is a coarse
    # wall-type guess from the Hazus material class.
    year_built: int | None = None
    sqft: float | None = None
    foundation: str | None = None         # slab | crawl | partial-basement | full-basement
    construction: str | None = None       # frame | vinyl | brick | block | stone | icf | sip (coarse)
    structure_source: str | None = None   # "NSI" when detected
    structure_attr_source: str | None = None  # NSI provenance: "P" parcel/observed, else modeled
    units_confidence: str | None = None   # "detected" (from NSI) | "estimated" (cluster heuristic)
    notes: dict = field(default_factory=dict)

    @property
    def county3(self) -> str | None:
        """3-digit county code (for Census ACS queries)."""
        return self.county_fips[2:] if self.county_fips else None

    @property
    def label(self) -> str:
        return self.place_label or self.county_name or f"{self.lat:.4f}, {self.lon:.4f}"


# ── Census geocoder ─────────────────────────────────────────────────────────────
def _get(url: str, params: dict) -> dict | None:
    """GET with retry/back-off; returns parsed JSON or None on failure."""
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa: BLE001
            if attempt == RETRIES:
                return None
            time.sleep(BACKOFF ** attempt)
    return None


def _parse_geographies(geo: dict) -> dict:
    """Pull the fields we care about out of a geocoder 'geographies' block."""
    out: dict = {}
    counties = geo.get("Counties") or []
    if counties:
        out["county_fips"] = str(counties[0].get("GEOID") or "").zfill(5) or None
        out["county_name"] = counties[0].get("NAME")
        out["state_fips"] = counties[0].get("STATE") or (out["county_fips"][:2] if out.get("county_fips") else None)
    tracts = geo.get("Census Tracts") or []
    if tracts:
        out["tract"] = str(tracts[0].get("GEOID") or "").zfill(11) or None
    places = geo.get("Incorporated Places") or []
    if places:
        out["place_label"] = places[0].get("NAME")
    out["in_urban_area"] = bool(geo.get("Urban Areas"))
    return out


def geocode_address(address: str) -> dict | None:
    """Address → {lat, lon, **geographies}. Returns None if no match."""
    data = _get(GEOCODER_ONELINE, {
        "address": address, "benchmark": BENCHMARK, "vintage": VINTAGE, "format": "json",
    })
    if not data:
        return None
    matches = (data.get("result") or {}).get("addressMatches") or []
    if not matches:
        return None
    m = matches[0]
    coords = m.get("coordinates") or {}
    out = {"lat": coords.get("y"), "lon": coords.get("x")}
    out.update(_parse_geographies(m.get("geographies") or {}))
    if out.get("place_label") is None:
        out["place_label"] = m.get("matchedAddress")
    return out


def geographies_for_coords(lat: float, lon: float) -> dict | None:
    """Lat/lon → geographies dict (county/state FIPS, tract, place, urban)."""
    data = _get(GEOCODER_COORDS, {
        "x": lon, "y": lat, "benchmark": BENCHMARK, "vintage": VINTAGE, "format": "json",
    })
    if not data:
        return None
    geo = (data.get("result") or {}).get("geographies")
    return _parse_geographies(geo) if geo else None


# ── Resolver ────────────────────────────────────────────────────────────────────
def resolve_location(
    address: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    *,
    allow_network: bool = True,
) -> Location:
    """Resolve an address or lat/lon into a fully-populated Location.

    Provide an ``address`` (preferred) or a ``lat``/``lon`` pair. If both are
    supplied the address takes precedence — it is geocoded and the lat/lon are
    ignored — so the chosen input is never silently dropped. Failures are
    recorded in ``loc.notes`` and leave the corresponding fields None.
    """
    notes: dict = {}

    if address:
        if not allow_network:
            raise ValueError("Geocoding an address requires network access.")
        geo = geocode_address(address)
        if not geo or geo.get("lat") is None:
            raise ValueError(f"Could not geocode address: {address!r}")
        loc = Location(lat=float(geo["lat"]), lon=float(geo["lon"]), notes=notes)
        _apply_geo(loc, geo)
    else:
        if lat is None or lon is None:
            raise ValueError("Provide either --address or both lat and lon.")
        loc = Location(lat=float(lat), lon=float(lon), notes=notes)
        if allow_network:
            geo = geographies_for_coords(loc.lat, loc.lon)
            if geo:
                _apply_geo(loc, geo)
            else:
                notes["geocoder"] = "lat/lon geocoding failed; FIPS/tract unavailable"
        else:
            notes["geocoder"] = "skipped (no network)"

    # Bundled reference lookups (offline, keyed on county FIPS).
    if loc.county_fips:
        loc.climate_zone = climate_data.climate_zone_for_county(loc.county_fips)
        if loc.climate_zone is None:
            notes["climate_zone"] = f"no climate-zone entry for county {loc.county_fips}"

    # Grid CO2 factor: the county's eGRID subregion when it maps, otherwise the
    # US-average fallback. egrid_for_county handles a missing/unmapped county, so
    # egrid_factor is always populated — the environmental model never silently
    # applies the Shelby pilot default to a non-Shelby (or unresolved) location.
    loc.egrid_subregion, loc.egrid_factor = egrid_data.egrid_for_county(loc.county_fips)
    if loc.county_fips and loc.egrid_subregion == egrid_data.US_AVG_LABEL:
        notes["egrid"] = f"county {loc.county_fips} not in eGRID crosswalk; using US average"

    # Climate projections: resolution-aware — resolve at the tract when one is
    # available (falling back to the parent county), else the county, else the
    # national average (always populated, never None). No tract crosswalk is
    # bundled today, so a resolved tract reports at the parent county.
    loc.climate_projection = (
        climate_proj_data.climate_projection_for_tract(loc.tract)
        if loc.tract
        else climate_proj_data.climate_projection_for_county(loc.county_fips)
    )
    if loc.county_fips and not loc.climate_projection.get("resolved"):
        notes["climate_projection"] = (
            f"county {loc.county_fips} not in climate crosswalk; using US average")

    # Wildfire (FEMA NRI): resolution-aware tract→county→national. Drives the
    # location-based "fire" hazard in the resilience EAL model. Always populated.
    loc.wildfire = (
        wildfire_data.wildfire_for_tract(loc.tract)
        if loc.tract
        else wildfire_data.wildfire_for_county(loc.county_fips)
    )
    if loc.county_fips and not loc.wildfire.get("resolved"):
        notes["wildfire"] = (
            f"county {loc.county_fips} not in NRI wildfire crosswalk; using US average")

    # Building structure (USACE NSI, live keyless API): what kind of building sits
    # here — single-family, multi-family, unit count, stories. Best effort; leaves
    # the fields None (with a note) when NSI is unavailable or off-network.
    if allow_network:
        from housing_label.enrich.structure import structure_for_point
        s = structure_for_point(loc.lat, loc.lon, allow_network=True)
        if s:
            loc.structure_type = s.get("structure_type")
            loc.num_units = s.get("num_units")
            loc.stories = s.get("stories")
            loc.bldg_material = s.get("bldg_material")
            # Auto-derived construction profile (best-effort estimates; NSI already
            # returns these — previously they were fetched but discarded).
            loc.year_built = s.get("year_built")
            loc.sqft = s.get("sqft")
            loc.foundation = s.get("foundation")
            loc.construction = s.get("construction")
            loc.structure_source = s.get("source")
            loc.structure_attr_source = s.get("attr_source")
            loc.units_confidence = s.get("units_confidence")
        else:
            notes["structure"] = "building type unknown (no NSI match, or NSI unavailable)"
    else:
        notes["structure"] = "skipped (no network)"

    return loc


def _apply_geo(loc: Location, geo: dict) -> None:
    loc.state_fips = geo.get("state_fips")
    loc.county_fips = geo.get("county_fips")
    loc.county_name = geo.get("county_name")
    loc.tract = geo.get("tract")
    loc.place_label = geo.get("place_label")
    loc.in_urban_area = geo.get("in_urban_area")
