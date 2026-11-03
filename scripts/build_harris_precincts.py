"""Build docs/data/harris_precincts.json: Harris County 2024 voting precincts (TLC VTDs_24PG)
joined to 2024 U.S. Senate results (OpenElections), projected into the same SVG space as
docs/data/harris_outline.json so the wait-time dots overlay exactly.

Run in GitHub Actions (needs network to data.capitol.texas.gov)."""
import csv, glob, io, json, math, pathlib, sys, zipfile
import requests, shapefile
from pyproj import CRS, Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform

ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = ("https://data.capitol.texas.gov/dataset/4d8298d0-d176-4c19-b174-42837027b73e/resource/"
       "906f47e4-4e39-4156-b1bd-4969be0b2780/download/vtds_24pg.zip")
HARRIS_FIPS = 201

out = ROOT / "docs" / "data" / "harris_precincts.json"
work = pathlib.Path("/tmp/vtds"); work.mkdir(exist_ok=True)
print("downloading", URL, flush=True)
r = requests.get(URL, timeout=300, headers={"User-Agent": "Mozilla/5.0"})
r.raise_for_status()
zipfile.ZipFile(io.BytesIO(r.content)).extractall(work)
shp = sorted(glob.glob(str(work / "**" / "*.shp"), recursive=True))
print("shapefiles:", shp)
base = shp[0][:-4]
prj = pathlib.Path(base + ".prj")
src_crs = CRS.from_wkt(prj.read_text()) if prj.exists() else CRS.from_epsg(4326)
to_ll = Transformer.from_crs(src_crs, CRS.from_epsg(4326), always_xy=True).transform

rdr = shapefile.Reader(base)
fields = [f[0] for f in rdr.fields[1:]]
print("fields:", fields)

def fget(rec, *names):
    for n in names:
        if n in rec:
            return rec[n]
    return None

senate = {row["precinct"]: row for row in csv.DictReader(open(ROOT / "scripts" / "harris_senate_2024.csv"))}
outline = json.load(open(ROOT / "docs" / "data" / "harris_outline.json"))
lon0, lat1, k, s = outline["lon0"], outline["lat1"], outline["k"], outline["s"]

precincts, matched = {}, 0
for sr in rdr.iterShapeRecords():
    rec = sr.record.as_dict()
    cnty = fget(rec, "CNTY", "CNTYFIPS", "COUNTY", "CNTYKEY")
    cntyvtd = str(fget(rec, "CNTYVTD", "VTDKEY") or "")
    try:
        is_harris = int(cnty) == HARRIS_FIPS
    except Exception:
        is_harris = cntyvtd.startswith("201")
    if not is_harris:
        continue
    vtd = str(fget(rec, "VTD") or cntyvtd[3:]).strip()
    key = vtd.lstrip("0").zfill(4) if vtd.isdigit() else vtd.zfill(4)
    geom = transform(to_ll, shape(sr.shape.__geo_interface__)).simplify(0.00035, preserve_topology=True)
    if geom.is_empty:
        continue
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    d = ""
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            pts = [((x - lon0) * k * s, (lat1 - y) * s) for x, y in ring.coords]
            if len(pts) < 3:
                continue
            d += "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"
    res = senate.get(key)
    if res:
        matched += 1
    p = precincts.setdefault(key, {"d": ""})
    p["d"] += d
    if res:
        a, c, o = int(res["allred"]), int(res["cruz"]), int(res["other"])
        p.update(allred=a, cruz=c, other=o)

print(f"harris precincts: {len(precincts)}, matched to results: {matched}, results rows: {len(senate)}")
if len(precincts) < 500:
    sys.exit("too few Harris precincts found; check field names above")
json.dump({"source": "Texas Legislative Council VTDs_24PG; 2024 U.S. Senate results via OpenElections",
           "precincts": precincts}, open(out, "w"), separators=(",", ":"))
print("wrote", out, out.stat().st_size, "bytes")
