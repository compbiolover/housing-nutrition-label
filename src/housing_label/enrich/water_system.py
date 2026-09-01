#!/usr/bin/env python3
"""Public water system at a lat/lon — which utility, if any, serves this point.

The Water Quality dimension scores EPA SDWIS drinking-water compliance, which is a
property of a **community water system**, and joined it to a parcel by county. That
broadcasts a county aggregate onto every home in it, including homes on a private
well that are not on any system at all — a measurement of a population the
household is not part of. Until now the only way to say so was for the owner to
tell us (``water_source=well``).

This module supplies the missing join. Source: the **EPA Office of Research and
Development Public Water System Service Area Boundaries** (keyless ArcGIS
FeatureServer) — 44,000+ community water systems covering ~99% of the US
population served by one, plus non-community systems. A point-in-polygon query
returns the PWSID serving that point, or nothing.

Three answers, not a boolean
----------------------------
EPA is explicit that the layer "cannot definitively determine if a specific
address is served" and should be used as a first step, so a caller has to be able
to tell three cases apart. Two are ``status`` values on a returned dict; the third
is deliberately not a value at all:

  * ``{"status": "served", ...}``  — inside a community system's mapped area;
    carries its PWSID.
  * ``{"status": "outside", ...}`` — inside no mapped community area. Evidence of a
    private well, not proof of one: ~40% of the boundaries are EPA-modeled rather
    than authoritative, and a small system may not be mapped at all.
  * **unknown** — never a ``status``. Either ``None`` (off-network, or the caller
    skipped the lookup) or a raised ``ServiceAreaUnavailable`` (the service was
    unreachable). Kept out of the status vocabulary on purpose: an outage that
    could be read as ``outside`` would unscore a dimension for every address while
    it lasted, and an exception cannot be mistaken for an answer or cached as one.

Non-community systems (a campground, a school, a factory) are filtered out: they
are not what SDWIS's community-water-system compliance measures, and a home inside
one is not served by it.

Attribution: US EPA ORD, Public Water System Service Area Boundaries (v3). US
federal government work.
"""

from __future__ import annotations

from functools import lru_cache

from housing_label import utils
from housing_label.config import BACKOFF, HEADERS, RETRIES, TIMEOUT


class ServiceAreaUnavailable(RuntimeError):
    """The EPA service-area layer could not be reached (every retry failed).

    Distinct from a point genuinely falling outside every mapped system: an
    outage that read as "outside" would unscore Water Quality for every address
    while it lasted, and cache that. Raised so the caller degrades without caching.
    """


_URL = ("https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/"
        "Water_System_Boundaries/FeatureServer/0/query")

_OUT_FIELDS = ("PWSID,PWS_Name,Service_Area_Type,Population_Served_Count,"
               "Model_Method,Data_Provider_Type")

# Service_Area_Type values that are NOT a community water system. SDWIS
# community-system compliance does not describe them, and living inside the
# footprint of a school's or campground's own well is not being served by it.
_NON_COMMUNITY = ("non-community", "noncommunity", "transient", "non-transient")


def _is_community(attrs: dict) -> bool:
    """True when the feature is a community water system's service area."""
    kind = str(attrs.get("Service_Area_Type") or "").strip().lower()
    if not kind:
        # The CWS layer's own rows sometimes carry a descriptive area type
        # ("Residential Area") rather than a system class. An unlabelled row in
        # this service is a community system; only an explicit non-community
        # marker excludes it.
        return True
    return not any(marker in kind for marker in _NON_COMMUNITY)


def _provenance(attrs: dict) -> str:
    """How this boundary was drawn — authoritative, or EPA-modeled.

    ~40% of the layer is modeled from building footprints, population density and
    service-connection counts. That is a materially weaker claim than a boundary a
    state or utility supplied, and the label should be able to say which it has.
    """
    provider = str(attrs.get("Data_Provider_Type") or "").strip()
    method = str(attrs.get("Model_Method") or "").strip()
    if method:
        return f"EPA-modeled ({method})"
    return provider or "reported boundary"


def _query(lat: float, lon: float) -> list[dict]:
    """Point-in-polygon against the service-area layer; returns attribute dicts.

    Raises ``ServiceAreaUnavailable`` when every attempt fails, so a transient
    outage is distinguishable from a genuine miss.
    """
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": _OUT_FIELDS,
        "returnGeometry": "false",
        "f": "json",
    }
    for attempt in range(1, RETRIES + 1):
        try:
            r = utils.http_session().get(_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json() or {}
            if "error" in data:
                # ArcGIS returns HTTP 200 with an error body for transient
                # conditions (rate limit / overload), so this has to be treated as
                # a failure or the retry loop never gets a chance.
                raise RuntimeError("arcgis error response")
            return [f.get("attributes") or {} for f in (data.get("features") or [])]
        except Exception as exc:  # noqa: BLE001
            if attempt == RETRIES:
                raise ServiceAreaUnavailable(
                    f"EPA service-area query failed after {RETRIES} attempts: {exc}"
                ) from exc
            utils.retry_wait(attempt, BACKOFF)
    return []   # unreachable (the loop returns or raises); kept for the type


@lru_cache(maxsize=4096)
def _system_at(lat: float, lon: float, allow_network: bool) -> dict | None:
    if not allow_network:
        return None
    community = [a for a in _query(lat, lon) if _is_community(a)]
    if not community:
        return {"status": "outside", "pwsid": None, "name": None,
                "population_served": None, "provenance": None, "source": _SOURCE}
    # Overlapping service areas happen (a wholesaler over a retailer). The system
    # serving the most people is the likelier retail provider at a dwelling.
    def _pop(a):
        try:
            return float(a.get("Population_Served_Count") or 0)
        except (TypeError, ValueError):
            return 0.0
    best = max(community, key=_pop)
    return {
        "status": "served",
        "pwsid": (str(best.get("PWSID") or "").strip() or None),
        "name": (str(best.get("PWS_Name") or "").strip() or None),
        "population_served": int(_pop(best)) or None,
        "provenance": _provenance(best),
        "source": _SOURCE,
    }


_SOURCE = "EPA ORD Public Water System Service Area Boundaries"


def water_system_for_point(lat: float, lon: float,
                           allow_network: bool = True) -> dict | None:
    """Return the community water system serving (lat, lon), or the fact that none
    is mapped there.

    Result keys: ``status`` (``served`` | ``outside``), ``pwsid``, ``name``,
    ``population_served``, ``provenance`` (reported vs EPA-modeled), ``source``.

    Returns None off-network (status unknown — the caller keeps its default).
    Raises ``ServiceAreaUnavailable`` when the EPA service itself is unreachable,
    so a transient outage is not cached as "this house is on a well".
    """
    return _system_at(round(float(lat), 6), round(float(lon), 6), allow_network)
