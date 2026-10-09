"""State-level layer for the hosted map, built from the snapshot in data/districts.pmtiles (so it always matches the tiles):
state outlines, each state's seat counts, population-weighted dissimilarity of its districts, and two-party vote share.

    python make_states_layer.py      (needs state_votes.json from state_votes.py)
Writes data/states.geojson, data/states.json (picker, with bboxes) and updates data/stats.json."""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

SITE = Path(__file__).resolve().parent.parent   # the repository folder
DATA = SITE / "data"
HERE = Path(__file__).parent
NAMES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
         "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
         "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
         "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
         "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
         "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
         "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
         "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
         "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
         "WI": "Wisconsin", "WY": "Wyoming"}
BBOX_OVERRIDE = {"AK": [-170.0, 51.2, -129.5, 71.6]}   # the Aleutians cross the antimeridian
MIN_PART_DEG2 = 0.002                                   # drop specks smaller than ~25 km2

votes = json.loads((HERE / "state_votes.json").read_text())
raw = gpd.read_file(DATA / "districts.pmtiles", layer="districts", ZOOM_LEVEL=6)   # outlines: small urban districts are still present at this zoom
raw = raw.to_crs(4326)                                                              # tile reader returns Web Mercator
print(len(raw), "tile pieces read at zoom 6")
full = gpd.read_file(DATA / "districts.pmtiles", layer="districts")                  # attributes: all districts survive here

# attributes: one row per district (they repeat on every tile piece)
att = full.drop(columns="geometry").drop_duplicates(["plan", "st", "lab"])
rows = []
for st, g in att.groupby("st"):
    r = {"st": st, "name": NAMES[st]}
    for plan, key in (("enacted", "e"), ("optimized", "o")):
        p = g[g.plan == plan]
        r["k"] = int(len(p))
        r[key + "D"] = int((p.winner == "D").sum())
        r[key + "Diss"] = round(float(np.average(p["diss"].astype(float), weights=p["pop"].astype(float))), 4)
    D, R = votes[st]
    r["voteD"] = round(D / (D + R), 4)
    r["pop"] = int(att[(att.st == st) & (att.plan == "enacted")]["pop"].sum())
    rows.append(r)
tab = pd.DataFrame(rows).set_index("st")

# state outlines: union of the enacted-plan pieces at zoom 4
feats = []
for st, g in raw[raw.plan == "enacted"].groupby("st"):
    u = unary_union([geom.buffer(0) for geom in g.geometry])
    parts = [p for p in (u.geoms if u.geom_type == "MultiPolygon" else [u]) if p.area >= MIN_PART_DEG2] or [u]
    parts = [Polygon(q.exterior) for q in parts]      # fill holes left by tiny districts dropped from low-zoom tiles
    u = MultiPolygon(parts) if len(parts) > 1 else parts[0]
    u = u.simplify(0.015, preserve_topology=True)
    polys = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
    polys = [Polygon(q.exterior) for q in polys]      # simplifying can pinch off specks: fill again
    u = MultiPolygon(polys) if len(polys) > 1 else polys[0]
    feats.append({"st": st, "geometry": u})
states = gpd.GeoDataFrame(feats, crs=4326).set_index("st").join(tab).reset_index()
states["pop"] = states["pop"].astype(int)
states.to_file(DATA / "states.geojson", driver="GeoJSON", COORDINATE_PRECISION=3)

# picker list with bounding boxes
out = []
for _, r in states.iterrows():
    x0, y0, x1, y1 = (BBOX_OVERRIDE.get(r.st) or list(r.geometry.bounds))
    out.append({"st": r.st, "name": r["name"], "k": int(r.k), "bbox": [round(v, 3) for v in (x0, y0, x1, y1)],
                "voteD": float(r.voteD), "eD": int(r.eD), "oD": int(r.oD),
                "eDiss": float(r.eDiss), "oDiss": float(r.oDiss)})
(DATA / "states.json").write_text(json.dumps(out, separators=(",", ":")))

# national numbers: keep the existing dissimilarity figures, add seat shares and vote share
stats = json.loads((DATA / "stats.json").read_text())
D = sum(v[0] for v in votes.values())
R = sum(v[1] for v in votes.values())
stats["voteD"] = round(D / (D + R), 4)
assert stats["districts"] == int(tab.k.sum()), "stats.json and tiles disagree on the district count"
assert stats["enacted_D"] == int(tab.eD.sum()) and stats["opt_D"] == int(tab.oD.sum()), "seat counts disagree"
(DATA / "stats.json").write_text(json.dumps(stats))
print(json.dumps(stats))
print("states.geojson %.0f KB, states.json %.0f KB" % ((DATA / "states.geojson").stat().st_size / 1e3,
                                                        (DATA / "states.json").stat().st_size / 1e3))
print(tab.loc[["IL", "TX", "UT", "DE", "WY"]].to_string())
