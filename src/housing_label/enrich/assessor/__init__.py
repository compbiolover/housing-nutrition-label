#!/usr/bin/env python3
"""County assessor adapters: the first *observed* construction data in the label.

Everything else the label knows about a building is modeled or typical. NSI's
material and occupancy are imputed from regional distributions wherever
``attr_source`` is not ``"P"``; the year built is a census-tract quantile. This
package is where a value can finally come from somebody who went and looked.

Coverage is per-county and always will be — there is no national source (see
``research/parcel-level-data-research.md``) — so the point of this package is the
*seam*, not the count. Adding a county is one small module and one line in
:data:`ADAPTERS`.

Off by default
--------------
``assessor_for_point`` returns ``None`` unless ``ASSESSOR_ADAPTERS`` is set to a
truthy value. This adds an upstream to ``/label``'s critical path on a 512 MB
instance with a ~12 s budget for all upstreams combined, and a new network
dependency should be switched on deliberately by whoever watches the latency
graphs, not by a merge.

Keeping the gate also makes the feature measurable: ``scripts/measure_accuracy.py``
runs the benchmark with it off and on and reports both, so "what does the adapter
actually buy" is a number rather than an argument.

Precedence
----------
Above NSI and above any area typical, below the reader. The order the label
applies is: what the visitor entered, then what the county observed, then NSI's
structure record, then the tract's year-built distribution, then a global
default. An observed value outranks a modeled one — that is the whole point —
but the person standing in the house still outranks the county, whose record can
be decades stale or simply wrong.
"""

from __future__ import annotations

import logging
import os

from housing_label.enrich.assessor import cook_il
from housing_label.enrich.assessor.base import (  # noqa: F401  (re-exported)
    CONDITION_VALUES, CONSTRUCTION_VALUES, FOUNDATION_VALUES, AssessorRecord,
)

log = logging.getLogger(__name__)

ENABLE_ENV = "ASSESSOR_ADAPTERS"

# county FIPS → the module that answers for it. One entry per county an adapter
# covers, so resolution is a dict lookup rather than a scan.
ADAPTERS = {fips: cook_il for fips in cook_il.COUNTY_FIPS}


def enabled() -> bool:
    """Whether adapters may be queried at all (``ASSESSOR_ADAPTERS``)."""
    raw = (os.environ.get(ENABLE_ENV) or "").strip().lower()
    return raw not in ("", "0", "off", "false", "no")


def adapter_for_county(county_fips: str | None):
    """The adapter covering this county, or None. Does not consult the gate."""
    if not county_fips:
        return None
    return ADAPTERS.get(str(county_fips).strip().zfill(5))


def assessor_for_point(lat: float | None, lon: float | None,
                       county_fips: str | None,
                       address: str | None = None) -> AssessorRecord | None:
    """What the county assessor says is standing at this point, or None.

    None covers every uninteresting case identically — adapters disabled, no
    adapter for this county, no coordinates, the county has no record here, or
    the lookup failed — because the caller's response to all of them is the same:
    keep what it had. Distinguishing them would invite a caller to treat an
    outage as evidence of absence, which is the mistake ``NSIUnavailable`` exists
    to prevent one layer up.
    """
    if lat is None or lon is None or not enabled():
        return None
    adapter = adapter_for_county(county_fips)
    if adapter is None:
        return None
    try:
        return adapter.lookup(float(lat), float(lon), address)
    except Exception as exc:  # noqa: BLE001
        # An adapter is supposed to swallow its own failures; this is the belt to
        # that braces, so a badly-behaved one still cannot break a label.
        log.debug("assessor adapter %s raised for %s: %s", adapter.__name__,
                  county_fips, exc)
        return None
