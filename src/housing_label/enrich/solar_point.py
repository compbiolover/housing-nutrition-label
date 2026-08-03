#!/usr/bin/env python3
"""Rooftop solar specific yield at a lat/lon — PVGIS queried at the parcel.

The Solar Potential dimension has been reading ``solar_yield_county.csv``, which
``scripts/build_solar.py`` builds by querying PVGIS **once per county, at that
county's Census-gazetteer internal point**, and then serving that single number to
every parcel in the county. That is not a county average — it is one arbitrary
location's answer, standing in for everywhere else.

PVGIS is natively a POINT api: it takes a lat/lon and returns the yield there. The
precision was always available and was being discarded at build time. This module
asks the same service the same question at the address the user actually entered.

Why it matters more than a bundled table suggests
-------------------------------------------------
Specific yield varies inside a county wherever terrain or coastal cloud does — a
marine layer along the coast against clear inland valleys, a windward slope against
a rain shadow, a high desert plateau against the basin below it. Counties in the
mountain West and along the Pacific are large enough to contain both ends of that
range, and Solar Potential is scored as a national percentile, so the error moves
the grade rather than just the kWh figure.

Commensurability
----------------
``PVGIS_PARAMS`` is the single definition of the query, imported by
``scripts/build_solar.py`` so the bundled county table and this live lookup cannot
drift apart. That matters because ``data/solar.py`` scores a yield against
breakpoints derived from the national distribution of COUNTY yields: a point value
produced under different assumptions (a different tilt, a different loss figure, a
different radiation database) would be scored on a curve built for a quantity it is
not. Same question, same units, same curve.

Attribution (CC BY 4.0): PVGIS © European Union, 2001-2024.
https://re.jrc.ec.europa.eu/
"""

from __future__ import annotations

import time
from functools import lru_cache

import requests

from housing_label.config import BACKOFF, HEADERS, RETRIES, TIMEOUT


class SolarDataUnavailable(RuntimeError):
    """PVGIS could not be reached (every retry failed).

    Deliberately distinct from "PVGIS has no data at this point". Both end up
    falling back to the county figure, but they are different facts about the
    label: one is a temporary outage, the other is a permanent property of the
    location (outside PVGIS-NSRDB coverage). ``scripts/build_solar.py`` collapses
    them into a single None, which is fine for a batch build that will be re-run
    and is not fine at request time — a reader deserves to know which one they got.
    """


PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"

# The canonical query: a building-mounted 1 kWp array at the optimal tilt facing
# south with 14% system losses, on PVGIS-NSRDB. With ``peakpower=1`` the returned
# annual energy E_y IS the specific yield in kWh/kWp/yr.
#
# scripts/build_solar.py imports this rather than restating it. Every field here is
# load-bearing for comparability with the bundled table — see the module docstring.
PVGIS_PARAMS = {
    "peakpower": "1", "loss": "14", "mountingplace": "building",
    "raddatabase": "PVGIS-NSRDB", "optimalinclination": "1", "aspect": "0",
    "outputformat": "json",
}


def parse_pvgis(payload: dict) -> tuple[float, float]:
    """(specific yield kWh/kWp/yr, in-plane irradiation kWh/m²/yr) from a response.

    Shared with the build script so the two paths cannot read the same response
    differently. Rounded to 1 dp exactly as the bundled CSV stores it, so a point
    lookup and a county lookup of the same coordinates agree to the last digit.
    """
    t = payload["outputs"]["totals"]["fixed"]
    return round(float(t["E_y"]), 1), round(float(t["H(i)_y"]), 1)


@lru_cache(maxsize=4096)
def _yield_at(lat: float, lon: float, allow_network: bool) -> dict | None:
    if not allow_network:
        return None
    params = dict(PVGIS_PARAMS, lat=f"{lat:.4f}", lon=f"{lon:.4f}")
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(PVGIS_URL, params=params, headers=HEADERS,
                             timeout=TIMEOUT)
            # PVGIS answers 400 for a point outside the selected radiation
            # database. That is a definitive "no data here", not a failure, so it
            # must not be retried and must not raise — the caller falls back to the
            # county figure, which is the same answer the label gave before.
            if r.status_code == 400:
                return None
            r.raise_for_status()
            y, irr = parse_pvgis(r.json())
            return {"yield_kwh_kwp": y, "irradiation": irr,
                    "source": "PVGIS v5.2 (PVGIS-NSRDB), queried at this parcel"}
        except Exception as exc:  # noqa: BLE001 — transient HTTP/JSON errors
            if attempt == RETRIES:
                raise SolarDataUnavailable(
                    f"PVGIS failed after {RETRIES} attempts: {exc}") from exc
            time.sleep(BACKOFF ** attempt)
    return None   # unreachable


def solar_yield_near(lat: float, lon: float,
                     allow_network: bool = True) -> dict | None:
    """Specific yield at a point, or None when there is no point-level answer.

    None means either off-network or outside PVGIS-NSRDB coverage (far-north
    Alaska, chiefly) — in both cases the caller keeps the county figure.

    Raises ``SolarDataUnavailable`` when PVGIS itself is unreachable, so an outage
    is reported as an outage rather than silently serving the county number under a
    parcel-level label.
    """
    return _yield_at(round(float(lat), 4), round(float(lon), 4), allow_network)
