#!/usr/bin/env python3
"""location.py — resolve an address or lat/lon to everything the label needs.

A single entry point, ``resolve_location``, turns a free-text address *or* a
lat/lon pair into a ``Location`` carrying the geographies and reference data the
dimensions depend on:

  • lat / lon
  • state FIPS, county FIPS (5-digit), county name, census tract GEOID
  • whether the point falls in a Census Urban Area (urban-core proxy)
  • IECC climate zone (bundled county lookup)
  • eGRID subregion + grid CO2e factor (bundled county lookup)
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
from functools import lru_cache

import requests

from housing_label.config import TIMEOUT, RETRIES, BACKOFF, HEADERS
from housing_label.data import climate as climate_data
from housing_label.data import climate_projections as climate_proj_data
from housing_label.data import egrid as egrid_data
from housing_label.data import cambium as cambium_data
from housing_label.data import wildfire as wildfire_data
from housing_label.data import year_built as year_built_data
from housing_label.data import tornado as tornado_data

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
    # What the geocoder said it matched, verbatim ("213 W MAIN ST, BARRINGTON, ...").
    # Only set when an address was geocoded — a lat/lon caller never has one.
    matched_address: str | None = None
    in_urban_area: bool | None = None
    climate_zone: str | None = None       # IECC zone, e.g. "4A"
    egrid_subregion: str | None = None
    egrid_factor: float | None = None     # kg CO2e / kWh — eGRID subregion AVERAGE
    cambium_region: str | None = None     # NREL Cambium GEA region label (CONUS only)
    cambium_factor: float | None = None   # kg CO2e / kWh — long-run MARGINAL rate
    climate_projection: dict | None = None  # CMIP6-LOCA2 hazard projection (tract→county→US)
    wildfire: dict | None = None          # FEMA NRI wildfire hazard (tract→county→US)
    tornado: dict | None = None           # FEMA NRI tornado hazard (tract→county→US)
    # When the homes AROUND this point were built (ACS B25034/B25035, tract→county→US):
    # {year_built, p25, p75, spread, …}. An area typical with its spread attached —
    # the stand-in used when nobody has told us this building's real year, and the
    # only thing that says how wide a stand-in it is.
    year_built_distribution: dict | None = None
    # What the COUNTY ASSESSOR says is standing here (enrich/assessor) — the only
    # observed construction data in the label, and only in the handful of counties
    # with an adapter, only when ASSESSOR_ADAPTERS is on. None everywhere else,
    # which is the same thing the label did before adapters existed.
    assessor: object | None = None
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
    structure_unavailable: bool = False    # NSI unreachable this pass (don't cache the label)
    structure_attr_source: str | None = None  # NSI provenance: "P" parcel/observed, else modeled
    units_confidence: str | None = None   # "detected" (from NSI) | "estimated" (cluster heuristic)
    # Real building footprint (FEMA/ORNL USA Structures) — actual area + perimeter,
    # used by the embodied-carbon model in place of the shape-factor estimate.
    footprint_area_m2: float | None = None
    footprint_perimeter_m: float | None = None
    occ_cls: str | None = None            # USA Structures occupancy class (Residential/Commercial/…)
    # Is the point inside an incorporated municipality (Census TIGER PLACE,
    # MTFCC G4110 + FUNCSTAT A)? False means unincorporated county territory —
    # no city government serves or taxes it. None when no geocode resolved, which
    # is NOT the same as False and must not be read as one.
    incorporated: bool | None = None
    place_geoid: str | None = None        # 7-digit Census PLACE GEOID when incorporated
    # Community water system serving this point (EPA ORD service-area boundaries):
    # {status: served|outside, pwsid, name, population_served, provenance}. None
    # when the lookup was skipped or the service was unreachable — which is NOT
    # "outside", and must not be read as evidence of a private well.
    water_system: dict | None = None
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
    # Incorporated municipality, and the CDP trap.
    #
    # "Has a place name" is NOT the test. A Census Designated Place is a statistical
    # convenience with no government at all — Silver Spring, MD is a CDP of 80,000
    # people that has never been incorporated — so treating a named place as a
    # municipality gets it exactly backwards. The discriminator is MTFCC G4110
    # (Incorporated Place) with FUNCSTAT "A" (active general-purpose government);
    # G4210/FUNCSTAT "S" is a CDP. The geocoder's "Incorporated Places" layer
    # already excludes CDPs, so the check is belt-and-braces against a layer or
    # vintage change quietly folding them back in.
    #
    # An ABSENT layer means the point is in unincorporated county territory: the
    # geocoder omits "Incorporated Places" entirely rather than returning it empty
    # (verified against a rural point, which still returns Counties, Census Tracts,
    # States and more). So absence is the signal — but only when the rest of the
    # response is there to vouch for it.
    #
    # Every successful geocode returns the county layer, so its presence is the
    # evidence that this response is well-formed. Without it, "no places key"
    # cannot be distinguished from "the layer was not returned at all" (a failed
    # lookup, or a future API/layer change), and guessing False would hand an
    # unknown parcel the unincorporated discount. Unknown stays None, which the
    # cost model reads as "keep the full service bundle".
    resolved = bool(counties)
    places = geo.get("Incorporated Places") or []
    municipal = next((p for p in places
                      if str(p.get("MTFCC") or "").upper() == "G4110"
                      and str(p.get("FUNCSTAT") or "").upper() == "A"), None)
    if municipal is not None:
        out["place_label"] = municipal.get("NAME")
        # 7 digits (2-digit state + 5-digit place), zero-padded like the county and
        # tract GEOIDs above — a place in Alabama or Alaska leads with a zero.
        geoid = str(municipal.get("GEOID") or "").strip()
        out["place_geoid"] = geoid.zfill(7) if geoid else None
    out["incorporated"] = (municipal is not None) if resolved else None
    out["in_urban_area"] = bool(geo.get("Urban Areas"))
    return out


# The two Census geocoder calls were the only upstream lookups in the pipeline
# with no memoization, so anything that scores one place several times in a
# process — the density sweep, the /presets grid, a /label followed by either —
# paid a fresh round trip every pass. Both are pure lookups of static reference
# geography, so the sibling enrichers' pattern applies unchanged: the public
# function normalizes its inputs, then calls a cached inner. Failures (a None
# return) are cached too, which is deliberate — a geocoder that just refused this
# address will refuse it again inside the same request, and re-asking costs the
# full retry ladder. Sizes match the enrichers (4096 points ≈ a few MB of small
# dicts); the process is long-lived but the caches are bounded and LRU.
def _copy(d: dict | None) -> dict | None:
    return dict(d) if d is not None else None


@lru_cache(maxsize=4096)
def _geocode_address_cached(address: str) -> dict | None:
    return _geocode_address_uncached(address)


def geocode_address(address: str) -> dict | None:
    """Address → {lat, lon, **geographies}. Returns None if no match."""
    # Case and surrounding/inner whitespace don't change the answer, so they must
    # not split the cache: "123 Main St", "123  main st " are one lookup.
    key = " ".join(str(address or "").split()).casefold()
    if not key:
        return None
    # Hand out a copy: the cached dict is shared by every caller for the life of
    # the process, so one caller mutating it would poison the rest.
    return _copy(_geocode_address_cached(key))


def _geocode_address_uncached(address: str) -> dict | None:
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
    # Keep the matched address in its own key, not only as a place_label fallback.
    # The county-assessor adapters need it: the Census geocoder interpolates many
    # addresses along a street centerline, which puts the point in the roadway
    # where no parcel polygon exists, and the house number is the only thing that
    # can tell 213 W Main from the 205 and 209 that are nearer to it.
    out["matched_address"] = m.get("matchedAddress")
    if out.get("place_label") is None:
        out["place_label"] = out["matched_address"]
    return out


def geographies_for_coords(lat: float, lon: float) -> dict | None:
    """Lat/lon → geographies dict (county/state FIPS, tract, place, urban)."""
    # 6 dp ≈ 0.1 m — the same rounding the point enrichers use, and far finer than
    # the tract/county/place geography this returns.
    return _copy(_geographies_cached(round(float(lat), 6), round(float(lon), 6)))


@lru_cache(maxsize=4096)
def _geographies_cached(lat: float, lon: float) -> dict | None:
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
    geography: dict | None = None,
) -> Location:
    """Resolve an address or lat/lon into a fully-populated Location.

    Provide an ``address`` (preferred) or a ``lat``/``lon`` pair. If both are
    supplied the address takes precedence — it is geocoded and the lat/lon are
    ignored — so the chosen input is never silently dropped. Failures are
    recorded in ``loc.notes`` and leave the corresponding fields None.

    ``geography`` supplies the Census geography for the point directly, in the
    shape ``_parse_geographies`` returns (``county_fips``, ``tract``,
    ``state_fips``, ``county_name``, ``in_urban_area``, ``incorporated``,
    ``place_label``, ``place_geoid``). When given, the geocoder is not called and
    everything keyed off county/tract — climate zone, eGRID, Cambium, climate
    projections, wildfire, tornado — resolves from the bundled crosswalks as usual.
    It is rejected alongside ``address``: one says "I already know where this is",
    the other says "go look it up", and silently honouring one would drop the other.

    The narrow claim this rests on: the Census geocode is the ONLY network call
    needed to learn a point's county and tract, and every crosswalk keyed off them
    is bundled. It does NOT make the resolver network-free — ``structure_for_point``
    and ``footprint_for_point`` below still go out when ``allow_network`` is set,
    as do the parcel-level enrichers in the label build (water system, road noise,
    PVGIS). Those degrade to None on their own; the geography does not, and without
    it a Location carries no county and no tract, which silently unscores every
    location dimension. The golden snapshot ran that way for a long time and covered
    none of Health, Air Quality, Noise, Climate, Solar or Water. A caller who
    already knows the FIPS — a batch job with pre-joined geography, or a fixture
    pinning a known place — should not have to choose between a network call and no
    location signal at all.
    """
    notes: dict = {}

    if geography is not None:
        if address:
            raise ValueError(
                "Pass either address= or geography=, not both: geography says the "
                "point's county/tract are already known, address says to geocode "
                "for them.")
        if lat is None or lon is None:
            raise ValueError("geography= requires both lat and lon.")
        loc = Location(lat=float(lat), lon=float(lon), notes=notes)
        _apply_geo(loc, geography)
        notes["geocoder"] = "supplied by caller (not geocoded)"
    elif address:
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

    # Grid CO2e factor: the county's eGRID subregion when it maps, otherwise the
    # US-average fallback. egrid_for_county handles a missing/unmapped county, so
    # egrid_factor is always populated — the environmental model never silently
    # applies the Shelby pilot default to a non-Shelby (or unresolved) location.
    loc.egrid_subregion, loc.egrid_factor = egrid_data.egrid_for_county(loc.county_fips)
    if loc.county_fips and loc.egrid_subregion == egrid_data.US_AVG_LABEL:
        notes["egrid"] = f"county {loc.county_fips} not in eGRID crosswalk; using US average"

    # Marginal grid factor (NREL Cambium 2023 LRMER): the long-run marginal CO2e
    # rate used to credit solar/efficiency-avoided kWh in the environmental model.
    # CONUS-only — cambium_lrmer_for_county returns None outside the GEA regions
    # (Alaska, Hawai'i, Puerto Rico, or unmapped), leaving cambium_factor None so
    # the model falls back to the eGRID average (no marginal adjustment).
    cambium = cambium_data.cambium_lrmer_for_county(loc.county_fips)
    if cambium is not None:
        loc.cambium_region, loc.cambium_factor = cambium
    elif loc.county_fips:
        notes["cambium"] = (
            f"county {loc.county_fips} not in Cambium CONUS crosswalk; "
            "avoided kWh valued at the grid average (no marginal adjustment)")

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

    # Tornado (FEMA NRI): resolution-aware tract→county→national, exactly like
    # wildfire. Drives the "tornado" hazard in the resilience EAL model, replacing
    # the old SPC touchdown-count model with its nationally-applied Mid-South EF mix.
    loc.tornado = (
        tornado_data.tornado_for_tract(loc.tract)
        if loc.tract
        else tornado_data.tornado_for_county(loc.county_fips)
    )
    if loc.county_fips and not loc.tornado.get("resolved"):
        notes["tornado"] = (
            f"county {loc.county_fips} not in NRI tornado crosswalk; using US average")

    # Year-built distribution (ACS B25034/B25035): tract→county→national, same
    # shape as the hazard lookups above. This is NOT a fact about the building on
    # this parcel — it is when its neighbours were built, and how much they vary.
    # The label uses the median as a stand-in for an unknown year and the quartiles
    # to say how much of a stand-in it is. Unlike the hazard rows it can be None
    # (no geography resolved at all), so every reader must guard.
    loc.year_built_distribution = year_built_data.year_built_distribution_for(
        loc.tract, loc.county_fips)
    # Note the US fallback only when one actually happened. A None distribution is
    # not an unresolved one — it means the bundled tables were absent (a broken
    # install, or a source tree with nothing built), and the label then falls back
    # to NSI or its own default. Saying "using the US typical" there would describe
    # a number nobody used. The same None-is-not-False rule the rest of this
    # dataclass runs on: see `incorporated` and `water_system`.
    if (loc.county_fips and loc.year_built_distribution is not None
            and not loc.year_built_distribution.get("resolved")):
        notes["year_built"] = (
            f"county {loc.county_fips} not in the ACS year-built crosswalk; "
            f"using the US typical")

    # County assessor characteristics, where a county has an adapter and the
    # operator has switched them on. Deliberately BEFORE the NSI block so the note
    # ordering reads source-of-truth first; the autofill applies it per field over
    # anything NSI or the ACS distribution offers, and under anything the reader
    # entered. Fails open to None, so a county portal having a bad day is
    # indistinguishable from a county with no adapter — which is correct, because
    # the label's response to both is identical.
    if allow_network:
        from housing_label.enrich.assessor import assessor_for_point
        loc.assessor = assessor_for_point(loc.lat, loc.lon, loc.county_fips,
                                          address=loc.matched_address)
        if loc.assessor is not None:
            notes["assessor"] = (
                f"construction details observed by the {loc.assessor.source}"
                f" (parcel {loc.assessor.parcel_id})")

    # Building structure (USACE NSI, live keyless API): what kind of building sits
    # here — single-family, multi-family, unit count, stories. Best effort; leaves
    # the fields None (with a note) when NSI is unavailable or off-network.
    if allow_network:
        from housing_label.enrich.structure import structure_for_point, NSIUnavailable
        try:
            s = structure_for_point(loc.lat, loc.lon, allow_network=True)
        except NSIUnavailable:
            # Transient NSI outage — leave the building fields at their defaults but
            # flag it so the caller (API) doesn't cache this degraded "single-family
            # defaults" label onto the coordinate for the whole TTL.
            s = None
            loc.structure_unavailable = True
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
        elif loc.structure_unavailable:
            notes["structure"] = "NSI temporarily unavailable; building details are defaults"
        else:
            notes["structure"] = "building type unknown (no NSI match)"
        # Which public water system serves this point, if any (EPA ORD service-area
        # boundaries). This is the parcel->utility join the Water Quality dimension
        # was missing: without it, county community-water-system compliance was
        # broadcast onto homes that are on a private well and no system at all.
        # Best effort — an unreachable service leaves water_system None (unknown),
        # deliberately distinct from a mapped "outside".
        from housing_label.enrich.water_system import (
            water_system_for_point, ServiceAreaUnavailable)
        try:
            loc.water_system = water_system_for_point(loc.lat, loc.lon,
                                                      allow_network=allow_network)
        except ServiceAreaUnavailable:
            notes["water_system"] = ("EPA service-area layer unavailable; water "
                                     "source not detected")
        else:
            if loc.water_system and loc.water_system.get("status") == "outside":
                notes["water_system"] = ("no mapped community water system at this "
                                         "point (EPA service areas)")

        # Real footprint geometry (area + perimeter) for the embodied-carbon model,
        # independent of NSI — best effort, None when the point isn't a mapped building.
        from housing_label.enrich.footprint import footprint_for_point
        # NSI floor area ÷ stories ≈ the home's footprint — a hint to disambiguate
        # when a parcel geocode falls among several nearby buildings. Only when both
        # are valid (stories >= 1, sqft > 0); a bad story count is left as unknown.
        expected_fp = None
        if loc.sqft and loc.sqft > 0 and loc.stories and loc.stories >= 1:
            expected_fp = (loc.sqft * 0.092903) / loc.stories
        fp = footprint_for_point(loc.lat, loc.lon, allow_network=allow_network,
                                 expected_footprint_m2=expected_fp)
        if fp:
            loc.footprint_area_m2 = fp.get("footprint_area_m2")
            loc.footprint_perimeter_m = fp.get("footprint_perimeter_m")
            loc.occ_cls = fp.get("occ_cls")   # occupancy class → residential screen
        else:
            notes["footprint"] = "no USA Structures footprint (no mapped building at point, or service unavailable)"
    else:
        notes["structure"] = "skipped (no network)"

    return loc


def _apply_geo(loc: Location, geo: dict) -> None:
    loc.state_fips = geo.get("state_fips")
    loc.county_fips = geo.get("county_fips")
    loc.county_name = geo.get("county_name")
    loc.tract = geo.get("tract")
    loc.place_label = geo.get("place_label")
    loc.matched_address = geo.get("matched_address")
    loc.place_geoid = geo.get("place_geoid")
    loc.incorporated = geo.get("incorporated")
    loc.in_urban_area = geo.get("in_urban_area")
