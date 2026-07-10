"""Compact columnar store for the bundled tract/county crosswalks.

The reference crosswalks (climate, health, wildfire, walkability, …) have ~85k
rows. Holding each row as a ``csv.DictReader`` dict of strings costs 60–190 MB per
table — enough to OOM a 512 MB instance once several are resident. This stores each
column once as a typed array (numeric → ``float64`` numpy, so values are byte-for-
byte identical to ``float(the_string)`` — no scoring drift; text → an interned
list) behind a geoid→row-index map, and rebuilds a plain row ``dict`` only on demand
in ``.get()`` / ``.values()``. The public surface quacks like the ``{geoid: row}``
dict the loaders returned before, so callers are unchanged.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np


class TractStore:
    """A ``{geoid: row-dict}`` mapping backed by per-column arrays.

    Implements the read-only mapping surface the crosswalk loaders use: ``get``
    (with default), ``values``, ``items``, ``__getitem__``, ``__iter__`` (keys,
    dict-style), ``__len__``, ``__contains__``. Row dicts are rebuilt on access —
    numeric cells come back as ``float`` (missing → ``None``, mirroring ``_num("")``)
    and text cells as the original string.
    """

    __slots__ = ("_idx", "_num", "_str", "_numcols", "_strcols")

    def __init__(self, idx: dict[str, int], num: dict[str, np.ndarray],
                 strc: dict[str, list], numcols: list[str], strcols: list[str]):
        self._idx = idx
        self._num = num
        self._str = strc
        self._numcols = numcols
        self._strcols = strcols

    def _row(self, geoid: str, i: int) -> dict:
        d: dict = {"geoid": geoid}
        for c in self._numcols:
            v = self._num[c][i]
            d[c] = None if v != v else float(v)   # NaN (missing) → None, like _num("")
        for c in self._strcols:
            d[c] = self._str[c][i]
        return d

    def get(self, geoid, default=None):
        i = self._idx.get(geoid)
        return self._row(geoid, i) if i is not None else default

    def __getitem__(self, geoid):
        i = self._idx[geoid]
        return self._row(geoid, i)

    def __contains__(self, geoid):
        return geoid in self._idx

    def __len__(self):
        return len(self._idx)

    def __iter__(self):
        return iter(self._idx)            # keys, like a dict

    def values(self):
        for g, i in self._idx.items():
            yield self._row(g, i)

    def items(self):
        for g, i in self._idx.items():
            yield g, self._row(g, i)

    # A columnar view for the one-time national-average / percentile builds, so
    # they can read a numeric column without rebuilding 85k row dicts.
    def column(self, name: str) -> np.ndarray | None:
        return self._num.get(name)


def load_tract_store(path: pathlib.Path, width: int) -> TractStore:
    """Load a crosswalk CSV/.csv.gz into a ``TractStore`` keyed by zero-padded geoid.

    Parsed with pandas' C reader so the columns land in typed arrays directly —
    a numeric column becomes a ``float64`` array (byte-identical to
    ``float(the_cell)``), text becomes an interned list — without ever holding
    85k Python row-dicts (which would spike RSS at load and not be returned to the
    OS). Empty cells become NaN (numeric) / ``""`` (text)."""
    import pandas as pd

    df = pd.read_csv(path, dtype={"geoid": str},
                     compression="gzip" if path.suffix == ".gz" else "infer",
                     keep_default_na=False, na_values=[""], low_memory=False)
    geo = df["geoid"].fillna("").astype(str).str.strip().str.zfill(width)
    keep = (geo != "").to_numpy()          # drop blank GEOIDs before indexing
    geo = geo[keep].tolist()
    idx = {g: i for i, g in enumerate(geo)}

    num: dict[str, np.ndarray] = {}
    strc: dict[str, list] = {}
    numcols: list[str] = []
    strcols: list[str] = []
    for c in df.columns:
        if c == "geoid":
            continue
        s = df[c][keep]
        if pd.api.types.is_numeric_dtype(s):
            num[c] = s.to_numpy(dtype=np.float64)
            numcols.append(c)
        else:
            strc[c] = _intern(s.fillna("").astype(str).tolist())
            strcols.append(c)
    return TractStore(idx, num, strc, numcols, strcols)


def _intern(vals: list) -> list:
    """Intern/dedupe text so 85k rows share a handful of repeated strings."""
    cache: dict = {}
    out = []
    for v in vals:
        s = "" if v is None else str(v)
        hit = cache.get(s)
        if hit is None:
            hit = cache[s] = sys.intern(s)
        out.append(hit)
    return out
