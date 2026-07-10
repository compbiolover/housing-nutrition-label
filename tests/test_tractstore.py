#!/usr/bin/env python3
"""Tests for the compact columnar crosswalk store (data/_tractstore.py).

Runs standalone (``python tests/test_tractstore.py``) or via pytest.
"""

from __future__ import annotations

import gzip
import pathlib
import sys
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data._tractstore import load_tract_store  # noqa: E402


def _store(rows_csv: str, width: int, gz: bool = False):
    # The store reads the file fully into memory, so the temp dir can be removed
    # right after loading — TemporaryDirectory cleans it up reliably.
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / ("t.csv.gz" if gz else "t.csv")
        if gz:
            with gzip.open(p, "wt", newline="") as f:
                f.write(rows_csv)
        else:
            p.write_text(rows_csv)
        return load_tract_store(p, width)


def test_columnar_roundtrip_types_and_missing():
    csv = ("geoid,county_name,eal_rate,risk\n"
           "06037,Los Angeles,0.0012,High\n"
           "47157,Shelby,,Low\n")            # missing numeric → None
    s = _store(csv, 5)
    la = s.get("06037")
    assert la["eal_rate"] == 0.0012 and la["county_name"] == "Los Angeles" and la["risk"] == "High"
    assert la["geoid"] == "06037"
    sh = s.get("47157")
    assert sh["eal_rate"] is None            # blank numeric cell → None (like _num(""))
    assert "99999" not in s and s.get("99999") is None


def test_blank_geoid_row_is_dropped_not_keyed_as_national():
    """A blank GEOID must NOT be zfilled into '00000' and poison the national row."""
    csv = ("geoid,val\n"
           "00000,999\n"                     # the real national row
           ",42\n"                           # blank GEOID — must be dropped
           "06037,7\n")
    s = _store(csv, 5)
    assert len(s) == 2                        # blank row dropped
    assert s.get("00000")["val"] == 999       # national row intact, not overwritten by 42
    assert s.get("06037")["val"] == 7


def test_zero_pads_and_reads_gzip():
    s = _store("geoid,val\n6037,3\n", 5, gz=True)   # 4-digit → zero-padded to 5
    assert s.get("06037")["val"] == 3
    assert list(s) == ["06037"] and [r["val"] for r in s.values()] == [3]


def _run_all():
    import types
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and isinstance(v, types.FunctionType)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
