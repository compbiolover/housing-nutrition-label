#!/usr/bin/env python3
"""Offline tests for the Census batch geocoder (no network, no pytest).

The response fixtures below are real bytes captured from
``geocoding.geo.census.gov/geocoder/geographies/addressbatch``, so the parser is
tested against the endpoint's actual output rather than an idealised version of
it. Nothing here goes out to the network.

This file alone:  pytest tests/test_geocode.py
"""

import io

from housing_label import batch as B
from housing_label import geocode as G

# Captured verbatim. Note two things the parser has to survive: the coordinate
# pair is LONGITUDE first, and the No_Match row is three fields wide, not twelve.
REAL_RESPONSE = (
    '"1","1600 Pennsylvania Ave NW, Washington, DC, 20500","Match","Exact",'
    '"1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",'
    '"-77.03518753691,38.89869893252","76225813","L","11","001","980000","1034"\n'
    '"2","350 Fifth Ave, New York, NY, 10118","Match","Exact",'
    '"350 5TH AVE, NEW YORK, NY, 10118",'
    '"-73.985077152891,40.747848600317","59653473","L","36","061","007600","1001"\n'
    '"3","not a real address at all, Nowhere, ZZ, 00000","No_Match"\n'
)


def test_coordinates_are_not_inverted():
    """The single most dangerous field in this response.

    The Census returns "lon,lat". Reading it in order puts the White House at
    latitude -77, which is not a latitude — but nothing downstream would object:
    a tract would still resolve, a score would still come out, and every parcel
    in the book would be silently in the wrong place.
    """
    res = G.parse_response(REAL_RESPONSE)["1"]
    assert res.matched
    assert 38.0 < res.lat < 39.0, f"latitude looks like a longitude: {res.lat}"
    assert -78.0 < res.lon < -77.0, f"longitude looks like a latitude: {res.lon}"
    # And the sanity check that catches a swap even if the ranges ever overlap:
    # every US latitude is positive, every US longitude negative.
    assert res.lat > 0 > res.lon


def test_tract_geoid_is_assembled_from_state_county_tract():
    res = G.parse_response(REAL_RESPONSE)
    assert res["1"].tract == "11001980000" and len(res["1"].tract) == 11
    assert res["1"].county_fips == "11001"
    assert res["1"].state_fips == "11"
    assert res["2"].tract == "36061007600"      # Manhattan


def test_unmatched_rows_are_short_and_carry_no_guessed_geography():
    res = G.parse_response(REAL_RESPONSE)["3"]
    assert res.matched is False
    assert res.status == "No_Match"
    assert res.lat is None and res.lon is None and res.tract is None


def test_results_join_by_id_not_position():
    """The endpoint does not promise to return rows in the order they were sent.
    Zipping the lists would attach each parcel's geography to a different parcel
    — every row plausible, every row wrong."""
    lines = REAL_RESPONSE.strip().split("\n")
    shuffled = "\n".join([lines[2], lines[0], lines[1]]) + "\n"
    res = G.parse_response(shuffled)
    assert res["1"].tract == "11001980000"      # still the White House
    assert res["2"].tract == "36061007600"
    assert res["3"].matched is False


def test_ids_the_endpoint_drops_are_reported_not_lost(monkey=None):
    """A row that comes back in neither the matches nor the misses must still
    produce a result, or it vanishes from a book being reconciled."""
    real = G._request_chunk
    G._request_chunk = lambda payload, session=None: '"1","x","No_Match"\n'
    try:
        out = G.geocode_chunk([("1", "a", "b", "TN", "1"), ("2", "c", "d", "TN", "2")])
    finally:
        G._request_chunk = real
    assert set(out) == {"1", "2"}
    assert out["2"].matched is False and "not returned" in out["2"].status


def test_chunk_larger_than_the_endpoint_limit_is_refused():
    try:
        G.geocode_chunk([("i", "s", "c", "ST", "0")] * (G.MAX_BATCH + 1))
    except ValueError as exc:
        assert str(G.MAX_BATCH) in str(exc)
    else:
        raise AssertionError("an oversized chunk should be refused")


def test_transport_failure_costs_one_chunk_not_the_run():
    real = G._request_chunk

    def boom(payload, session=None):
        raise RuntimeError("connection reset")

    G._request_chunk = boom
    try:
        out = list(G.geocode_rows([{"id": "a", "address": "1 Main St, Memphis, TN"},
                                   {"id": "b", "address": "2 Main St, Memphis, TN"}]))
    finally:
        G._request_chunk = real
    assert len(out) == 2
    assert all(not r.matched and "connection reset" in r.status for r in out)


def test_split_address_shapes():
    assert G.split_address("1600 Pennsylvania Ave NW, Washington, DC, 20500") == (
        "1600 Pennsylvania Ave NW", "Washington", "DC", "20500")
    # ZIP riding along with the state rather than as its own field.
    assert G.split_address("350 Fifth Ave, New York, NY 10118") == (
        "350 Fifth Ave", "New York", "NY", "10118")
    assert G.split_address("123 Main St, Memphis, TN") == (
        "123 Main St", "Memphis", "TN", "")
    assert G.split_address("123 Main St") == ("123 Main St", "", "", "")
    assert G.split_address("") == ("", "", "", "")


# ── The pre-pass, as batch.py uses it ────────────────────────────────────────
def _fake_geocode(mapping):
    """Patch the transport to answer from a {id: (lat, lon, tract)} mapping."""
    def fake(payload, session=None):
        import csv as _csv
        out = []
        for row in _csv.reader(io.StringIO(payload)):
            rid = row[0]
            hit = mapping.get(rid)
            if hit is None:
                out.append(f'"{rid}","in","No_Match"')
                continue
            lat, lon, tract = hit
            out.append(f'"{rid}","in","Match","Exact","matched","{lon},{lat}",'
                       f'"0","L","{tract[:2]}","{tract[2:5]}","{tract[5:]}","0"')
        return "\n".join(out) + "\n"
    return fake


def test_geocode_pass_fills_geography_and_clears_the_address():
    """Clearing the address matters: parse_row rejects a row carrying both an
    address and geography, so leaving it set would break the very rows the
    pre-pass just fixed."""
    rows = [{"id": "A", "address": "1 Main St, Memphis, TN"}]
    real = G._request_chunk
    G._request_chunk = _fake_geocode({"g0": (35.15, -89.85, "47157003100")})
    try:
        summary = B.geocode_pass(rows)
    finally:
        G._request_chunk = real
    assert summary == {"geocoded": 1, "matched": 1, "unmatched": 0}
    assert rows[0]["tract"] == "47157003100"
    assert rows[0]["county_fips"] == "47157"
    assert rows[0]["lat"] == 35.15 and rows[0]["lon"] == -89.85
    assert "address" not in rows[0]
    # And the fixed-up row now scores like any pre-joined one.
    rec = next(B.score_rows(rows, allow_network=False))
    assert rec["error"] is None and rec["n_scored"] == 13


def test_duplicate_ids_each_get_their_own_geography():
    """Real exports repeat ids — the same property on two loans is routine.

    Keying the round trip on the caller's id collapsed the join, so only the last
    row of each duplicate group got its geography and the rest silently kept
    none; it also sent colliding keys to the endpoint, making the reply ambiguous
    before the join was even attempted.
    """
    rows = [
        {"id": "DUP", "address": "1 Main St, Memphis, TN"},
        {"id": "DUP", "address": "2 Other Ave, Chicago, IL"},
        {"id": "DUP", "address": "nowhere at all"},
    ]
    real = G._request_chunk
    # Keyed by the SHADOW ids the pass generates, proving the caller's id is not
    # what goes over the wire.
    G._request_chunk = _fake_geocode({"g0": (35.15, -89.85, "47157003100"),
                                      "g1": (41.88, -87.63, "17031081500")})
    try:
        summary = B.geocode_pass(rows)
    finally:
        G._request_chunk = real

    assert summary == {"geocoded": 3, "matched": 2, "unmatched": 1}
    assert rows[0]["tract"] == "47157003100"      # Memphis
    assert rows[1]["tract"] == "17031081500"      # Chicago, not overwritten
    assert "tract" not in rows[2]
    assert rows[2]["_geocode_status"] == "No_Match"
    # The caller's id is theirs; the pass neither reads nor rewrites it.
    assert [r["id"] for r in rows] == ["DUP", "DUP", "DUP"]


def test_rows_without_an_id_do_not_get_one_invented():
    """Writing a generated id into the customer's row would surface in the output
    as though they had supplied it."""
    rows = [{"address": "1 Main St, Memphis, TN"}]
    real = G._request_chunk
    G._request_chunk = _fake_geocode({"g0": (35.15, -89.85, "47157003100")})
    try:
        B.geocode_pass(rows)
    finally:
        G._request_chunk = real
    assert rows[0]["tract"] == "47157003100"
    assert "id" not in rows[0]


def test_geocode_pass_leaves_rows_that_already_have_a_tract():
    """Re-geocoding a parcel whose geography the customer supplied would spend a
    request to replace better data with worse."""
    rows = [{"id": "A", "address": "1 Main St", "tract": "47157003100"}]
    real = G._request_chunk
    G._request_chunk = lambda payload, session=None: (_ for _ in ()).throw(
        AssertionError("must not call the geocoder"))
    try:
        summary = B.geocode_pass(rows)
    finally:
        G._request_chunk = real
    assert summary == {"geocoded": 0, "matched": 0, "unmatched": 0}
    assert rows[0]["tract"] == "47157003100"


def test_caller_supplied_coordinates_are_not_overwritten():
    """Their lat/lon is likelier the rooftop point; the geocoder's is an
    interpolated match along the street centreline."""
    rows = [{"id": "A", "address": "1 Main St, Memphis, TN",
             "lat": "35.1", "lon": "-89.9"}]
    real = G._request_chunk
    G._request_chunk = _fake_geocode({"g0": (35.15, -89.85, "47157003100")})
    try:
        B.geocode_pass(rows)
    finally:
        G._request_chunk = real
    assert rows[0]["lat"] == "35.1" and rows[0]["lon"] == "-89.9"
    assert rows[0]["tract"] == "47157003100"      # geography still filled in


def test_unmatched_row_reports_the_geocoder_reason():
    """Not a generic scoring failure — the geocoder already answered, and the
    output should say what it said rather than blaming the scorer."""
    rows = [{"id": "A", "address": "nowhere at all"}]
    real = G._request_chunk
    G._request_chunk = _fake_geocode({})
    try:
        B.geocode_pass(rows)
    finally:
        G._request_chunk = real
    rec = next(B.score_rows(rows, allow_network=False))
    assert rec["id"] == "A"
    assert rec["error"] and "No_Match" in rec["error"]


def test_run_batch_geocode_end_to_end():
    inp = io.StringIO('id,address,year_built\nA,"1 Main St, Memphis, TN",1995\n')
    out = io.StringIO()
    real = G._request_chunk
    G._request_chunk = _fake_geocode({"g0": (35.15, -89.85, "47157003100")})
    try:
        summary = B.run_batch(inp, out, allow_network=False, geocode=True)
    finally:
        G._request_chunk = real
    assert summary["scored"] == 1 and summary["failed"] == 0
    assert summary["geocode"] == {"geocoded": 1, "matched": 1, "unmatched": 0}

    import csv as _csv
    row = next(_csv.DictReader(io.StringIO(out.getvalue())))
    assert row["tract"] == "47157003100" and row["n_scored"] == "13"
