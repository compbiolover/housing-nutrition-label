#!/usr/bin/env python3
"""Phase 1 – Shelby County Assessor parcel data ingest via ArcGIS REST API.

Pulls:
  • BaseMap/Assessor  – parcel polygons + ownership fields
  • Parcel/CertParcel_NOAttrib – CAMA tables (ASSR_DWELDAT, ASSR_ASMT)
and joins all three on PARID.
"""

import logging, sys, time, pathlib, math
import requests, pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
BASE_URL    = "https://gis.shelbycountytn.gov/public/rest/services/BaseMap/Assessor/MapServer"
CAMA_URL    = "https://gis.shelbycountytn.gov/public/rest/services/Parcel/CertParcel_NOAttrib/MapServer"
OUT_DIR     = pathlib.Path(__file__).resolve().parent
SAMPLE_N    = 1_000          # matches the API's default pagination limit
TIMEOUT     = 60             # seconds per HTTP call
RETRIES     = 3
BACKOFF     = 2              # exponential back-off multiplier
PARID_BATCH = 100            # PARIDs per CAMA query request

# CAMA table IDs and the fields we want from each
CAMA_TABLES = {
    "dweldat": {
        "table_id": 3,
        "fields": ["PARID", "YRBLT", "EFFYR", "STORIES", "EXTWALL", "BSMT",
                   "SFLA", "GRADE", "COND", "CDU", "STYLE", "RMBED",
                   "FIXBATH", "HEAT", "FUEL"],
    },
    "asmt": {
        "table_id": 1,
        "fields": ["PARID", "RTOTAPR", "APRLAND", "APRBLDG"],
    },
}

# ── Helpers ──────────────────────────────────────────────────────────────────
def _get(url: str, params: dict | None = None) -> dict:
    """GET with retries, timeout, and JSON validation."""
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, params={**(params or {}), "f": "json"}, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"ArcGIS error: {data['error']}")
            return data
        except Exception as exc:
            log.warning("Attempt %d/%d failed: %s", attempt, RETRIES, exc)
            if attempt == RETRIES:
                raise
            time.sleep(BACKOFF ** attempt)


def _post(url: str, data: dict | None = None) -> dict:
    """POST (form-encoded) with retries, timeout, and JSON validation.

    Used for queries with long WHERE clauses (PARID IN …) that exceed GET URL limits.
    """
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.post(url, data={**(data or {}), "f": "json"}, timeout=TIMEOUT)
            r.raise_for_status()
            result = r.json()
            if "error" in result:
                raise RuntimeError(f"ArcGIS error: {result['error']}")
            return result
        except Exception as exc:
            log.warning("Attempt %d/%d failed: %s", attempt, RETRIES, exc)
            if attempt == RETRIES:
                raise
            time.sleep(BACKOFF ** attempt)


def discover_layers() -> list[dict]:
    """Return metadata for every layer on the MapServer."""
    info = _get(BASE_URL)
    layers = info.get("layers", [])
    log.info("MapServer has %d layer(s)", len(layers))
    return layers


def layer_fields(layer_id: int) -> list[dict]:
    """Fetch field definitions for a single layer."""
    meta = _get(f"{BASE_URL}/{layer_id}")
    return meta.get("fields", [])


def _webmercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Convert Web Mercator (EPSG:3857) x,y to WGS84 lon,lat."""
    R = 20037508.342789244
    lon = x * 180.0 / R
    lat = math.degrees(math.atan(math.exp(y * math.pi / R))) * 2.0 - 90.0
    return lon, lat


def _polygon_centroid(rings: list) -> tuple[float, float] | tuple[None, None]:
    """Return the centroid (x, y) of the outer ring of a polygon."""
    if not rings or not rings[0]:
        return None, None
    outer = rings[0]
    n = len(outer)
    if n < 3:
        return None, None
    cx = cy = 0.0
    area = 0.0
    for i in range(n - 1):
        x0, y0 = outer[i][0], outer[i][1]
        x1, y1 = outer[i + 1][0], outer[i + 1][1]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area /= 2.0
    if area == 0:
        cx = sum(v[0] for v in outer) / n
        cy = sum(v[1] for v in outer) / n
        return cx, cy
    cx /= (6.0 * area)
    cy /= (6.0 * area)
    return cx, cy


LAYER_PAGE = 100   # records per paginated parcel request

def query_layer(layer_id: int, max_records: int = SAMPLE_N) -> pd.DataFrame:
    """Pull up to *max_records* features (all attributes + centroid) from a layer.

    Paginates in pages of LAYER_PAGE to avoid server timeouts on large geometry payloads.
    """
    url  = f"{BASE_URL}/{layer_id}/query"
    rows = []
    offset = 0
    while len(rows) < max_records:
        page_size = min(LAYER_PAGE, max_records - len(rows))
        data = _get(url, {
            "where":             "1=1",
            "outFields":         "*",
            "returnGeometry":    "true",
            "resultRecordCount": page_size,
            "resultOffset":      offset,
        })
        features = data.get("features", [])
        if not features:
            break
        for feat in features:
            row  = feat["attributes"]
            geom = feat.get("geometry")
            lat  = lon = None
            if geom and "rings" in geom:
                mx, my = _polygon_centroid(geom["rings"])
                if mx is not None:
                    lon, lat = _webmercator_to_wgs84(mx, my)
            row["latitude"]  = lat
            row["longitude"] = lon
            rows.append(row)
        log.info("  Parcel page offset=%d → %d rows (total so far: %d)",
                 offset, len(features), len(rows))
        offset += len(features)
        if len(features) < page_size:
            break   # server returned a short page – no more records
    return pd.DataFrame(rows)


def _strip_prefixes(df: pd.DataFrame) -> pd.DataFrame:
    """Strip fully-qualified schema prefixes from column names.

    E.g. "GISWEB.GISADMIN.Parcels.OBJECTID" → "OBJECTID".
    Falls back to the original name if stripping would create a duplicate.
    """
    stripped = [c.rsplit(".", 1)[-1] for c in df.columns]
    seen: set[str] = set()
    dupes: set[str] = set()
    for s in stripped:
        if s in seen:
            dupes.add(s)
        seen.add(s)
    new_cols = [
        short if short not in dupes else orig
        for orig, short in zip(df.columns, stripped)
    ]
    renamed = sum(1 for o, n in zip(df.columns, new_cols) if o != n)
    df.columns = new_cols
    log.info("  Renamed %d column(s) (stripped schema prefix)", renamed)
    return df


def query_cama_table(table_id: int, parids: list[str], fields: list[str],
                     batch_size: int = PARID_BATCH) -> pd.DataFrame:
    """Query a CAMA table from the CertParcel service, filtered to *parids*.

    Splits the PARID list into batches of *batch_size* to stay within URL limits.
    Returns a single DataFrame with the requested *fields* (prefixes stripped).
    """
    url = f"{CAMA_URL}/{table_id}/query"
    out_fields = ",".join(fields)
    all_rows: list[dict] = []

    batches = [parids[i:i + batch_size] for i in range(0, len(parids), batch_size)]
    log.info("  Querying CAMA table %d in %d batch(es) of ≤%d PARIDs…",
             table_id, len(batches), batch_size)

    for idx, batch in enumerate(batches, 1):
        quoted = ",".join(f"'{p}'" for p in batch)
        where  = f"PARID IN ({quoted})"
        data   = _post(url, {
            "where":          where,
            "outFields":      out_fields,
            "returnGeometry": "false",
        })
        features = data.get("features", [])
        all_rows.extend(feat["attributes"] for feat in features)
        log.info("    Batch %d/%d → %d rows", idx, len(batches), len(features))

    if not all_rows:
        log.warning("  No rows returned from CAMA table %d", table_id)
        return pd.DataFrame(columns=fields)

    df = pd.DataFrame(all_rows)
    df = _strip_prefixes(df)
    log.info("  CAMA table %d: %d rows × %d cols", table_id, *df.shape)
    return df


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    log.info("Discovering layers at %s", BASE_URL)
    layers = discover_layers()
    for ly in layers:
        log.info("  Layer %d: %s", ly["id"], ly["name"])

    # Pick the first (primary) parcel layer for the sample pull
    target = layers[0]
    log.info("Fetching fields for layer %d (%s)…", target["id"], target["name"])
    fields = layer_fields(target["id"])
    log.info("  %d fields available", len(fields))

    log.info("Querying %d-record sample…", SAMPLE_N)
    df = query_layer(target["id"])
    log.info("  Received %d records × %d columns", *df.shape)

    # Strip schema prefixes
    df = _strip_prefixes(df)

    # Deduplicate on OBJECTID if present
    if "OBJECTID" in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=["OBJECTID"])
        if (dropped := before - len(df)):
            log.warning("Dropped %d duplicate rows", dropped)

    # ── CAMA join ────────────────────────────────────────────────────────────
    # Collect the PARIDs we fetched so we can filter the CAMA tables
    if "PARID" not in df.columns:
        log.error("PARID column not found in parcel data – cannot join CAMA tables.")
        log.error("Available columns: %s", list(df.columns))
        sys.exit(1)

    parids = df["PARID"].dropna().str.strip().unique().tolist()
    log.info("Fetching CAMA data for %d unique PARIDs…", len(parids))

    cama_cfg = CAMA_TABLES["dweldat"]
    log.info("Pulling ASSR_DWELDAT (table %d)…", cama_cfg["table_id"])
    df_dweldat = query_cama_table(cama_cfg["table_id"], parids, cama_cfg["fields"])

    cama_cfg2 = CAMA_TABLES["asmt"]
    log.info("Pulling ASSR_ASMT (table %d)…", cama_cfg2["table_id"])
    df_asmt = query_cama_table(cama_cfg2["table_id"], parids, cama_cfg2["fields"])

    # Normalize PARID whitespace in CAMA frames before joining
    for cdf in (df_dweldat, df_asmt):
        if "PARID" in cdf.columns:
            cdf["PARID"] = cdf["PARID"].astype(str).str.strip()

    # Deduplicate CAMA frames on PARID (keep first) to prevent row explosion on join
    for name, cdf in [("DWELDAT", df_dweldat), ("ASMT", df_asmt)]:
        if "PARID" in cdf.columns:
            before = len(cdf)
            cdf.drop_duplicates(subset=["PARID"], keep="first", inplace=True)
            if (dropped := before - len(cdf)):
                log.warning("%s had %d duplicate PARID row(s) – kept first", name, dropped)

    df["PARID"] = df["PARID"].astype(str).str.strip()

    # Left-join so every parcel row is preserved even if no CAMA match
    df = df.merge(df_dweldat, on="PARID", how="left", suffixes=("", "_dweldat"))
    df = df.merge(df_asmt,    on="PARID", how="left", suffixes=("", "_asmt"))
    log.info("After CAMA joins: %d rows × %d cols", *df.shape)

    # ── Save ─────────────────────────────────────────────────────────────────
    out_path = OUT_DIR / "shelby_parcels_sample.csv"
    df.to_csv(out_path, index=False)
    log.info("Saved → %s", out_path)

    # ── Summary ──────────────────────────────────────────────────────────────
    n_dweldat_matched  = df["YRBLT"].notna().sum() if "YRBLT" in df.columns else 0
    n_asmt_matched     = df["RTOTAPR"].notna().sum() if "RTOTAPR" in df.columns else 0
    has_coords         = df["latitude"].notna().sum()

    print("\n╔══ INGEST SUMMARY ═══════════════════════════════════════╗")
    print(f"║ Layers discovered : {len(layers):<36}║")
    for ly in layers:
        print(f"║   {ly['id']:>2}. {ly['name']:<44}║")
    print(f"║ Target layer      : {target['name']:<36}║")
    print(f"║ Fields (parcel)   : {len(fields):<36}║")
    print(f"║ Records fetched   : {len(df):<36}║")
    print(f"║ Records with coords: {has_coords:<35}║")
    print(f"╠══ CAMA JOIN RESULTS ════════════════════════════════════╣")
    print(f"║ ASSR_DWELDAT (tbl 3) matched : {n_dweldat_matched:<25}║")
    print(f"║   Fields added               : {len(CAMA_TABLES['dweldat']['fields']) - 1:<25}║")
    print(f"║ ASSR_ASMT (tbl 1) matched    : {n_asmt_matched:<25}║")
    print(f"║   Fields added               : {len(CAMA_TABLES['asmt']['fields']) - 1:<25}║")
    print(f"║ Total columns in output      : {df.shape[1]:<25}║")
    print(f"║ Output                       : {out_path.name:<25}║")
    print("╚════════════════════════════════════════════════════════╝\n")

    print("Sample columns:", ", ".join(df.columns[:10]), "…" if len(df.columns) > 10 else "")
    if not df.empty:
        print("\nFirst row preview:")
        print(df.iloc[0].to_string())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
