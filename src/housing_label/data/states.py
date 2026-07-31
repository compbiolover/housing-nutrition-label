"""US state identity — FIPS ↔ USPS codes, and the Census division each state sits in.

Several parts of the pipeline need a state, keyed differently. `Location.state_fips`
(and the first two digits of any county FIPS) is numeric; `data/assessment.py` keys its
property-tax classification table by USPS code, because that is how legal sources refer
to states. This module is the single crosswalk between them.

Data
----
Inline literals, not a bundled CSV — state codes are stable identifiers, not a data feed
with a vintage. Same convention as ``data/utility_rates.py``, whose ``_STATE_RATES`` table
carries the same pairs embedded in its value tuples; ``tests/test_states.py`` asserts the
two agree, so a typo in either is caught.

Census divisions are the standard nine-way grouping of the four Census regions, used here
to sequence the per-state classification research and to report coverage by region.

Resolution
----------
``usps_for_fips`` / ``fips_for_usps`` return ``None`` for anything unrecognized rather
than raising, so a caller with a missing or malformed geography degrades to "no state"
instead of failing. Both tolerate the messy inputs a CSV cell or a geocoder can produce
(ints, floats that lost a leading zero, NaN, stray whitespace, mixed case).

Caveats
-------
``STATE_FIPS_TO_USPS`` includes Puerto Rico ("72") so a PR county FIPS resolves to a real
code rather than silently reading as "no state". PR is deliberately NOT in
``SCORED_JURISDICTIONS``: it has ACS property-tax data (72 municipios in
``property_tax_county.csv``) but no rows at all in ``govfinance_county.csv``, so the
Infrastructure Burden cost side falls back to the national average there.

American Samoa (60), Guam (66), the Northern Mariana Islands (69) and the US Virgin
Islands (78) are absent entirely. They carry no rows in any fiscal, socioeconomic, or
home-value crosswalk in this repo, so the dimension cannot score them at all — including
them here would imply a coverage that does not exist.
"""

from __future__ import annotations

# 2-digit state FIPS → USPS postal code. 50 states + DC + PR.
STATE_FIPS_TO_USPS: dict[str, str] = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "72": "PR",
}

USPS_TO_STATE_FIPS: dict[str, str] = {u: f for f, u in STATE_FIPS_TO_USPS.items()}

# Jurisdictions the Infrastructure Burden dimension can actually score end to end, and
# therefore the ones eligible to carry a property-tax classification rule: the 50 states
# plus DC. See the module docstring for why PR and the four small territories are out.
SCORED_JURISDICTIONS: frozenset[str] = frozenset(STATE_FIPS_TO_USPS.values()) - {"PR"}

# USPS → Census division. One source of truth for the regional rollout sequence, the
# coverage report, and any future regional grouping. DC is grouped with South Atlantic,
# as the Census Bureau does.
CENSUS_DIVISION: dict[str, str] = {
    # Northeast
    **{s: "New England" for s in ("CT", "ME", "MA", "NH", "RI", "VT")},
    **{s: "Middle Atlantic" for s in ("NJ", "NY", "PA")},
    # Midwest
    **{s: "East North Central" for s in ("IL", "IN", "MI", "OH", "WI")},
    **{s: "West North Central" for s in ("IA", "KS", "MN", "MO", "NE", "ND", "SD")},
    # South
    **{s: "South Atlantic" for s in ("DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV")},
    **{s: "East South Central" for s in ("AL", "KY", "MS", "TN")},
    **{s: "West South Central" for s in ("AR", "LA", "OK", "TX")},
    # West
    **{s: "Mountain" for s in ("AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY")},
    **{s: "Pacific" for s in ("AK", "CA", "HI", "OR", "WA")},
}


def normalize_state_fips(value) -> str | None:
    """Best-effort 2-digit state FIPS from a messy value.

    Accepts ints and floats that lost a leading zero or gained a ``.0`` from CSV type
    inference (``6`` / ``6.0`` → ``"06"``), zero-pads short strings, and returns ``None``
    for missing/NaN/blank. Mirrors ``enrich/region_context.normalize_fips``, which does
    the same job for 5-digit county codes.
    """
    if value is None or value != value:               # None or NaN (NaN != NaN)
        return None
    if isinstance(value, (int, float)):               # incl. numpy float64 (a float subclass)
        return str(int(value)).zfill(2)
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    if s.endswith(".0"):                              # "47.0" from float-parsed CSV
        s = s[:-2]
    return s.zfill(2)


def usps_for_fips(state_fips) -> str | None:
    """USPS code for a state FIPS, or ``None`` if unrecognized.

    A 5-digit county FIPS also works — only the first two digits are read — so callers
    holding a county code don't need to slice it themselves.
    """
    fips = normalize_state_fips(state_fips)
    return STATE_FIPS_TO_USPS.get(fips[:2]) if fips else None


def fips_for_usps(usps: str | None) -> str | None:
    """2-digit state FIPS for a USPS code, or ``None`` if unrecognized. Case-insensitive."""
    if not usps:
        return None
    return USPS_TO_STATE_FIPS.get(str(usps).strip().upper())


def division_for_usps(usps: str | None) -> str | None:
    """Census division for a USPS code, or ``None`` (PR and the territories have none)."""
    if not usps:
        return None
    return CENSUS_DIVISION.get(str(usps).strip().upper())
