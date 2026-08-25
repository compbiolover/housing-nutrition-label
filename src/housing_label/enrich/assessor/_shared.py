"""Machinery every assessor adapter needs, so no adapter reimplements the risky parts.

Why this module exists
----------------------
The first adapter (Cook County, IL) worked out — over several review rounds and
three distinct bugs in one comparison function — how to decide *which parcel* an
address refers to without ever confidently naming the wrong one. That reasoning is
the dangerous part of an adapter, not the field mapping: a wrong parcel produces a
neighbour's house tagged ``observed`` at high confidence, which is strictly worse
than the area typical it replaces, because the reader has no reason to doubt it.

A second adapter that copied that logic would fork it, and the copy would not
receive the next fix. So the parcel-selection policy, the address comparison and
the request budget live here, and an adapter supplies only what is genuinely local:
its endpoints, its field names, and its own vocabulary translation.

What stays with the adapter
---------------------------
Anything that is a fact about one jurisdiction — the URLs, the id field, the
mapping tables, and how to reduce that jurisdiction's address strings to a
comparable form (a county whose parcel layer stores "3401 NEWARK ST NW WASHINGTON
DC 20016" in one field needs a different trim from one that keeps the city in a
separate column).
"""

from __future__ import annotations

import json
import logging
import re
import time

import requests

log = logging.getLogger(__name__)

# The budget for a WHOLE lookup, not per hop. An off-parcel address costs three
# requests (containment, buffer, characteristics), and giving each the full timeout
# would let a slow portal hold the label for three times the advertised budget on a
# host whose own HTTP allowance is 12 s for every upstream combined.
TIMEOUT = 4.0

# How far to look when the point lands off-parcel. Wide enough to cross a road and
# a front yard; the address, not the distance, is what actually decides.
SEARCH_RADIUS_M = 80

HEADERS = {"User-Agent": "housing-nutrition-label (assessor adapter)"}

# The longest a single socket read may block, and so the most the whole lookup can
# overshoot its deadline. See get_json for why this is not simply `remaining`.
_READ_SLICE_S = 1.0
_CHUNK_BYTES = 8192
_MAX_BYTES = 4 * 1024 * 1024

# County records refresh on their own schedule and assessment rolls advance, so a
# process-lifetime cache would let a long-lived worker serve an observed value —
# and its now-wrong roll date — for as long as it stayed up. Adapters key their
# cache on this bucket so entries age out without an eviction thread.
CACHE_TTL_S = 6 * 3600


def cache_bucket() -> int:
    return int(time.time() // CACHE_TTL_S)


def deadline_from(given: float | None) -> float:
    """The shared budget's end instant. A caller that did not pass one gets a fresh
    full budget, which is right for a single direct call and is why the argument is
    optional rather than required."""
    return given if given is not None else time.monotonic() + TIMEOUT


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_json(url: str, params: dict, deadline: float):
    """One request against the shared budget. Raises if the budget is spent.

    ``requests``' timeout bounds the connect and the gap BETWEEN reads, not the
    total time spent reading — a portal dribbling one byte inside every window
    keeps the call alive indefinitely and blows the budget this function exists to
    enforce. So the body is streamed and the deadline checked as it arrives.

    Streaming alone does not make the budget wall-clock, because the check can only
    run once a chunk has ARRIVED: a gap shorter than the read timeout but longer
    than what is left would still be waited out in full, overshooting by nearly the
    whole budget. So the read timeout is also capped to a slice, which bounds any
    single stall — and therefore the overshoot — to ``_READ_SLICE_S`` rather than to
    the budget. The connect timeout keeps the full remainder: a slow handshake is
    the one wait that cannot be broken into slices.

    The slice is a deliberate trade. Too small and an ordinarily slow portal is cut
    off mid-body; at one second, against responses that are a single row and
    complete in well under that, a gap this long is already a stall rather than
    slowness.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("assessor lookup budget exhausted")
    r = requests.get(url, params=params, headers=HEADERS, stream=True,
                     timeout=(remaining, min(remaining, _READ_SLICE_S)))
    try:
        r.raise_for_status()
        chunks, size = [], 0
        for chunk in r.iter_content(_CHUNK_BYTES):
            if time.monotonic() >= deadline:
                raise TimeoutError("assessor lookup budget exhausted while reading")
            size += len(chunk)
            # These responses are a single row or a handful of parcels. A body
            # orders of magnitude larger is a misrouted query or a portal error
            # page, and reading it to the end would spend the budget on something
            # that cannot be an answer.
            if size > _MAX_BYTES:
                raise RuntimeError(f"assessor response exceeded {_MAX_BYTES} bytes")
            chunks.append(chunk)
        raw = b"".join(chunks).strip()
        # An empty 200 is a portal glitch, not an answer. Parsing it as `null`
        # would flow on as "no parcels here" and be CACHED as absence for the
        # bucket's lifetime — the same failure the ArcGIS-error check below
        # exists to stop, arriving by a quieter route. Raising keeps it in the
        # fail-open path, where it is not cached and stays diagnosable.
        if not raw:
            raise RuntimeError("empty response body from assessor upstream")
        body = json.loads(raw)
    finally:
        r.close()
    # ArcGIS reports failures in a 200 body rather than by status. Left unraised it
    # reads as "no parcels here", and because lookups are cached that turns a
    # transient portal error into a cached None for this point until eviction.
    if isinstance(body, dict) and body.get("error"):
        raise RuntimeError(f"upstream error: {body['error']}")
    return body


# --- addresses ----------------------------------------------------------------
#
# Street-type suffixes, mapped to a canonical form. They are NOT dropped: "213 MAIN
# ST" and "213 MAIN AVE" are different streets that can both exist within one
# buffer, and collapsing both to "MAIN" would let the wrong parcel pass the
# confirmation step and be reported as a confident "observed" answer — exactly what
# that step exists to prevent. They are canonicalised rather than compared raw
# because sources abbreviate differently ("STREET" vs "ST") for the same street.
#
# Directionals are neither dropped nor canonicalised: "213 W Main" and "213 E Main"
# are different houses, and in a quadrant city ("NEWARK ST NW" vs "NEWARK ST NE")
# they are different streets outright. They stay ordinary name tokens, which
# preserves them wherever they appear — leading, as Chicago writes them, or
# trailing, as Washington does.
SUFFIXES = {
    "st": "st", "street": "st", "ave": "ave", "avenue": "ave", "rd": "rd",
    "road": "rd", "dr": "dr", "drive": "dr", "ln": "ln", "lane": "ln",
    "ct": "ct", "court": "ct", "blvd": "blvd", "boulevard": "blvd",
    "pl": "pl", "place": "pl", "way": "way", "ter": "ter", "terrace": "ter",
    "pkwy": "pkwy", "parkway": "pkwy", "cir": "cir", "circle": "cir",
    "hwy": "hwy", "highway": "hwy", "trl": "trl", "trail": "trl",
}

# Everything from a unit marker onwards is dropped: a parcel layer writes
# "234 W STATION ST B12" for one condo, and a unit number must not decide whether
# two records describe the same building.
UNIT_MARKERS = frozenset({"apt", "unit", "ste", "suite", "#", "fl", "floor", "rm"})

#: The unit as a person writes it — "#305", "Apt 3-B", "Unit 12", "Suite 4". Only
#: the marked form, because that is the only form that is unambiguous in an
#: arbitrary jurisdiction: a bare trailing token is a unit in one city's records
#: and part of the street's name in another's, so reading it here would guess.
_TYPED_UNIT_RE = re.compile(
    r"(?:^|\s)(?:#|apt\.?|unit|ste\.?|suite)\s*([A-Za-z0-9\-]+)\s*$", re.I)


def unit_of(address: str | None) -> str | None:
    """The unit designator a person wrote into this address, or None.

    Each comma-separated part is examined, not just the end of the string. A
    reader writes "2123 California St NW #D7, Washington, DC" far more often than
    they leave the unit last, and matching only at the end found the unit in the
    second form and missed it in the first — which is the form the label's own
    address box produces.
    """
    for part in str(address or "").split(","):
        m = _TYPED_UNIT_RE.search(" ".join(part.split()))
        if m:
            return m.group(1)
    return None


def strip_unit(address: str | None) -> str:
    """``address`` with the marked unit removed, and nothing else changed."""
    parts, out = str(address or "").split(","), []
    for part in parts:
        cleaned = _TYPED_UNIT_RE.sub("", " ".join(part.split()))
        # A part that was ONLY the unit ("..., #D7, Washington") disappears
        # entirely rather than leaving an empty segment behind.
        if cleaned.strip():
            out.append(cleaned.strip())
    return ", ".join(out)


def with_unit(canonical: str | None, typed: str | None) -> str | None:
    """``canonical``, carrying the unit that only ``typed`` knows about.

    The geocoder's matched address is preferred everywhere else in this layer: it
    is the canonical spelling of the street, which is what confirms a parcel. But
    it is an address of a POINT, and a unit is not a point — the Census matcher
    drops "#D7" on the way through. So the one component the canonical form cannot
    carry is taken from what the reader actually typed.

    Without this the condominium path is unreachable from the product: every DC
    condo address arrives at the adapter with its unit already discarded, which
    looks exactly like a reader who never gave one, and the lookup correctly
    refuses. Nothing errors, nothing is logged, and a third of the city silently
    reads as "no assessor record".

    Nothing is invented. If the reader gave no unit, or the canonical form already
    carries one, it is returned untouched.
    """
    if not canonical:
        return canonical
    unit = unit_of(typed)
    if not unit or unit_of(canonical):
        return canonical
    # Beside the street, not after the ZIP. Consumers split this on the comma and
    # read the first part as the street; a unit tacked onto the end would sit in
    # the locality tail where the street parser never looks.
    head, sep, tail = canonical.partition(",")
    return f"{head.strip()} #{unit}{sep}{tail}"

# A trailing directional, which sits AFTER the street type in DC, Denver and every
# other quadrant-addressed city. It is part of the street's identity — 1234 Main St
# NW and 1234 Main St SE are different buildings — so it is never dropped, only
# stepped over when deciding which token is the street type.
QUADRANTS = frozenset({"nw", "ne", "sw", "se"})

# A trailing postal code marks the start of a locality tail whatever the source's
# formatting. Safe to key on because the house number has already been consumed by
# the time this is tested — a street-name token is not a bare five-digit number.
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def address_key(raw: str | None, locality: frozenset[str] = frozenset()):
    """``(house number, street-name tokens, canonical suffix)``, or None if unusable.

    Deliberately strict: the number is what separates 213 W Main from the 205 and
    209 that can sit closer to an interpolated geocode, and the street type is what
    separates 213 Main St from 213 Main Ave when a corner puts both inside one
    buffer. Only the unit and the locality are treated as noise.

    ``locality`` names tokens that begin a city/state tail for sources that run the
    whole mailing address into one field with no comma to split on — Washington's
    parcel layer stores "3401 NEWARK ST NW WASHINGTON DC 20016", where every token
    after the quadrant belongs to the city, not the street. It is per adapter
    because only the adapter knows which words those are for its jurisdiction.

    The suffix is returned separately from the name tokens so a record that omits it
    ("213 W MAIN") can still match one that has it, without letting two different
    street types match each other.
    """
    if not raw:
        return None
    head = str(raw).split(",")[0].strip().lower()
    tokens = [t.strip(".") for t in head.replace("#", " # ").split() if t.strip(".")]
    if not tokens or not tokens[0].isdigit():
        return None                       # no house number → nothing to anchor on
    number, rest = tokens[0], tokens[1:]
    # The city/state/ZIP tail is stripped FROM THE RIGHT, taking only the trailing
    # run of such tokens. Cutting at the first one anywhere in the string was wrong
    # for every street named after its own city: "401 WASHINGTON AVE SW WASHINGTON
    # DC 20024" truncated at token zero, leaving nothing, so address_key returned
    # None and no DC address on a Washington-named street could ever confirm a
    # parcel. The comment above always said "every token AFTER the quadrant" — the
    # code did not implement it. Real addresses: Washington Ave SW, Washington Cir
    # NW. The same shape waits in any jurisdiction whose name is also a street name,
    # which is most of them.
    end = len(rest)
    while end and (rest[end - 1] in locality or _ZIP_RE.match(rest[end - 1])):
        end -= 1
    rest = rest[:end]
    for i, t in enumerate(rest):          # a unit marker is noise wherever it sits
        if t in UNIT_MARKERS:
            rest = rest[:i]
            break
    # A source also writes the unit with no marker at all — "234 W STATION ST B12".
    # Only a trailing token that carries a digit AND sits directly after a street
    # type is taken as one: specific enough to catch "ST B12" while leaving "100
    # ROUTE 66" alone, where the digit-bearing token is the street's own name.
    #
    # BEFORE the suffix rule below, not after: with the unit still trailing, the
    # street type is no longer terminal and would never be recognised, so
    # "234 W STATION ST B12" and "234 W STATION ST" would parse differently and
    # fail to match. Inverting these two is a silent coverage loss, so the order
    # is pinned by a test.
    if len(rest) >= 2 and rest[-2] in SUFFIXES and any(c.isdigit() for c in rest[-1]):
        rest = rest[:-1]
    # Only a TERMINAL street type is a street type. Consuming the token wherever it
    # appeared collapsed "213 ST JOHN ST" onto "213 JOHN ST" and "100 PARK PLACE DR"
    # onto "100 PARK DR" — both real naming patterns, and both exactly the
    # confident-but-wrong "observed" match this comparison exists to reject.
    suffix = None
    if rest and rest[-1] in SUFFIXES:
        suffix = SUFFIXES[rest[-1]]
        rest = rest[:-1]
    elif len(rest) >= 2 and rest[-1] in QUADRANTS and rest[-2] in SUFFIXES:
        # ...or terminal except for a quadrant, which is what every address in a
        # quadrant-addressed city looks like. "2123 CALIFORNIA STREET NW" left
        # `street` sitting in the name tokens, so it never matched "2123
        # CALIFORNIA ST NW" — and DC's unit table spells the type out while its
        # parcel layer abbreviates, so the two could not be joined at all.
        #
        # The quadrant STAYS in the name tokens. It is not decoration: 1234 Main
        # St NW and 1234 Main St SE are different buildings, and folding the
        # quadrant away would make them equal.
        suffix = SUFFIXES[rest[-2]]
        rest = rest[:-2] + [rest[-1]]
    return (number, tuple(rest), suffix) if rest else None


def same_address(a: str | None, b: str | None,
                 locality: frozenset[str] = frozenset()) -> bool:
    """Whether two address strings name the same building.

    Every part must agree. An earlier revision accepted one street-name token set
    *containing* the other, which reads as tolerant and is not: it matches "MAIN" to
    "MAIN STATION", two different streets. The name tokens must be equal.

    The one asymmetry allowed is a missing street type on one side, since sources do
    not always both carry it. Two *different* types never match.
    """
    ka, kb = address_key(a, locality), address_key(b, locality)
    if ka is None or kb is None:
        return False
    if ka[0] != kb[0] or ka[1] != kb[1]:
        return False
    return ka[2] is None or kb[2] is None or ka[2] == kb[2]


# --- picking the parcel -------------------------------------------------------


def arcgis_parcels(url: str, lat: float, lon: float, out_fields: str,
                   distance_m: float = 0, *, deadline: float) -> list[dict]:
    """Parcel attributes at (or within ``distance_m`` of) a point.

    ``out_fields`` is always an explicit list and never ``*``. Some parcel layers
    carry owner names, mailing addresses and tax balances alongside the geometry;
    this label has no use for any of that and must not fetch it.
    """
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields, "returnGeometry": "false", "f": "json",
    }
    if distance_m:
        params["distance"] = str(distance_m)
        params["units"] = "esriSRUnit_Meter"
    body = get_json(url, params, deadline)
    return [(f or {}).get("attributes") or {}
            for f in ((body or {}).get("features") or [])]


def select_parcel(fetch, address: str | None, address_of, locality=frozenset()):
    """The parcel a point belongs to, or None. THE safety-critical decision.

    ``fetch(distance_m)`` returns candidate attribute dicts; ``address_of(attrs)``
    reads that source's address field.

    Point-in-polygon first: it is the only unambiguous answer and is used wherever
    it exists. It frequently does not. The Census geocoder interpolates a large
    share of addresses onto the street centerline, landing the point in the roadway
    between parcels — 38 m out in Barrington, 20 m in Washington, both with no
    polygon underneath. Widening to the NEAREST parcel is the obvious repair and it
    is wrong: at a 10 m buffer around 213 W Main the two nearest parcels are 205 and
    209, neither of them the one asked for.

    So the buffer is used only with the geocoder's own matched address in hand, and
    a parcel is accepted only when its address agrees, uniquely.

    Containment is confirmed against the address too. The same interpolation error
    that lands a point in the roadway can land it inside the *neighbour's* polygon —
    city lots are far narrower than the error — so a sole containing parcel is not
    by itself evidence. When it disagrees the search widens rather than giving up,
    since the buffer is anchored on the address and can still find the right parcel.
    """
    exact = fetch(0)
    if len(exact) == 1 and not address:
        # Nothing to confirm against. Containment alone is all there is, and it is
        # the answer wherever the geocode landed on real parcel geometry.
        return exact[0]
    if len(exact) == 1 and same_address(address, address_of(exact[0]), locality):
        return exact[0]
    if len(exact) > 1 or not address:
        # Overlapping parcels are ambiguous, and without an address there is
        # nothing to disambiguate a buffer with.
        return None
    hits = [a for a in fetch(SEARCH_RADIUS_M)
            if same_address(address, address_of(a), locality)]
    return hits[0] if len(hits) == 1 else None
