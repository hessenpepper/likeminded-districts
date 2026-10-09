"""Build vector tiles (PMTiles) for the hosted map: district polygons + precinct polygons, enacted and best optimized.

    python build_tiles.py                 # all 50 states  -> C:\\gerry-compute\\tiles\\{districts,precincts}.pmtiles
    python build_tiles.py ri il           # a few states (test)  -> ...\\tiles_test\\
Run where states/*.gpkg and the result folders live (the office PC)."""
import glob
import json
import pickle
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import MultiPolygon, Polygon

BASE = Path(r"C:\gerry-compute")
STATE_DIRS = [BASE / "states", BASE / "laptop-data" / "states"]
RESULT_DIRS = [BASE / "out", BASE / "out_laptop", BASE / "seedcheck" / "out", BASE / "seedcheck_enacted" / "out",
               BASE / "overnight" / "out"]
ALL = ("al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok "
       "or pa ri sc sd tn tx ut vt va wa wv wi wy").split()
states = [s.lower() for s in sys.argv[1:]] or ALL
OUT = BASE / ("tiles_test" if sys.argv[1:] else "tiles")
OUT.mkdir(exist_ok=True)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def find_gpkg(ab):
    for d in STATE_DIRS:
        if (d / f"{ab}.gpkg").exists():
            return d / f"{ab}.gpkg"
    raise FileNotFoundError(ab)


def best_candidate(ab):
    cands = []
    for d in RESULT_DIRS:
        for f in glob.glob(str(d / f"{ab}.json")) + glob.glob(str(d / f"{ab}_*.json")):
            f = Path(f)
            pk = f.with_name(f.stem + "_best.pkl")
            if pk.exists():
                r = json.loads(f.read_text())
                if "optimized" in r:
                    cands.append((r["optimized"]["obj"], f, pk, r["enacted"]["obj"]))
    return min(cands, key=lambda c: c[0]) if cands else None


def clean(geom, min_part=5e6, min_hole=2e7):
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    keep = [p for p in polys if p.area >= min_part] or [max(polys, key=lambda p: p.area)]
    out = [Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area >= min_hole]) for p in keep]
    return out[0] if len(out) == 1 else MultiPolygon(out)


def plan_table(g, col):
    ok = (g.D + g.R) > 0
    w = np.where(ok, g["pop"], 0.0)
    p = np.where(ok, g.D / (g.D + g.R).where(ok, 1), 0.0)
    g = g.assign(_w=w, _p=p)
    dis = g.dissolve(by=col, aggfunc={"pop": "sum", "D": "sum", "R": "sum"})
    rows = []
    for d, s in g.groupby(col):
        W = s["_w"].sum()
        P = (s["_w"] * s["_p"]).sum() / W
        den = 2 * W * P * (1 - P)
        rows.append({"k": d, "d_share": P,
                     "diss": (s["_w"] * (s["_p"] - P).abs()).sum() / den if den > 0 else 0.0,
                     "winner": "D" if dis.loc[d, "D"] > dis.loc[d, "R"] else "R"})
    t = pd.DataFrame(rows).set_index("k")
    dis = dis.join(t)
    dis["comp"] = 4 * np.pi * dis.geometry.area / dis.geometry.length ** 2
    return dis.reset_index().rename(columns={col: "plan_district"})


prec_parts, dist_parts, summary = [], [], []
for ab in states:
    t0 = time.time()
    g = gpd.read_file(find_gpkg(ab)).set_index("node", drop=False)
    miss = g["enacted"].isna()
    if miss.any():
        near = gpd.sjoin_nearest(g.loc[miss, ["geometry"]], g.loc[~miss, ["enacted", "geometry"]], how="left")
        g.loc[miss, "enacted"] = near[~near.index.duplicated()]["enacted"]
    g["enacted"] = g["enacted"].astype(int)
    cand = best_candidate(ab)
    if cand is None:
        g["best"], eobj, oobj = g["enacted"], np.nan, np.nan
    else:
        oobj, _, pk, eobj = cand
        g["best"] = pd.Series(pickle.load(open(pk, "rb"))).reindex(g.index).astype(int)
    enc, opt = plan_table(g, "enacted"), plan_table(g, "best")
    opt_label = {d: i + 1 for i, d in enumerate(sorted(opt.plan_district))}
    P_enc = g["enacted"].map(enc.set_index("plan_district")["d_share"])
    P_opt = g["best"].map(opt.set_index("plan_district")["d_share"])
    ok = (g.D + g.R) > 0
    p = (g.D / (g.D + g.R).where(ok, 1)).where(ok)
    pr = gpd.GeoDataFrame({
        "st": ab.upper(), "eno": g["enacted"].astype("int16"), "opn": g["best"].map(opt_label).astype("int16"),
        "pop": g["pop"].round(0).astype("int32"), "p": (p * 100).round().fillna(-1).astype("int16"),
        "ed": ((p - P_enc) * 100).round().fillna(0).astype("int16"),
        "od": ((p - P_opt) * 100).round().fillna(0).astype("int16"),
    }, geometry=g.geometry.simplify(40, preserve_topology=True).values, crs=5070)
    prec_parts.append(pr.to_crs(4326))
    for plan, tab in (("enacted", enc), ("optimized", opt)):
        d = tab.copy()
        d["plan"], d["st"] = plan, ab.upper()
        d["lab"] = d["plan_district"].astype(int) if plan == "enacted" else d["plan_district"].map(opt_label)
        d["geometry"] = d.geometry.apply(clean).simplify(200, preserve_topology=True)
        d["pop"] = d["pop"].round(0)
        d["ds"] = (d["d_share"] * 100).round(1)
        d["diss"] = d["diss"].round(3)
        d["comp"] = d["comp"].round(3)
        dist_parts.append(gpd.GeoDataFrame(d[["plan", "st", "lab", "pop", "ds", "diss", "comp", "winner", "geometry"]],
                                           geometry="geometry", crs=5070).to_crs(4326))
    summary.append({"st": ab.upper(), "k": len(opt), "enacted_diss": eobj, "opt_diss": oobj,
                    "enacted_D": int((enc.winner == "D").sum()), "opt_D": int((opt.winner == "D").sum()),
                    "pop": int(g["pop"].sum())})
    log(f"{ab.upper()}: {len(g):,} precincts, {len(opt)} districts ({time.time()-t0:.0f}s)")

precincts = pd.concat(prec_parts, ignore_index=True)
districts = pd.concat(dist_parts, ignore_index=True)
sm = pd.DataFrame(summary)
sm.to_csv(OUT / "summary.csv", index=False)
multi = sm[sm.k > 1]
stats = {"districts": int(sm.k.sum()), "enacted_D": int(sm.enacted_D.sum()), "opt_D": int(sm.opt_D.sum()),
         "enacted_diss": float(np.average(multi.enacted_diss, weights=multi.k)),
         "opt_diss": float(np.average(multi.opt_diss, weights=multi.k)), "states": len(sm),
         "built": time.strftime("%Y-%m-%d")}
(OUT / "stats.json").write_text(json.dumps(stats))
log("stats", json.dumps(stats))
(OUT / "states.json").write_text(sm.assign(enacted_diss=sm.enacted_diss.round(4), opt_diss=sm.opt_diss.round(4))
                                 .to_json(orient="records"))

for name, df, layer, lo, hi in (("districts", districts, "districts", 0, 9), ("precincts", precincts, "precincts", 6, 11)):
    path = OUT / f"{name}.pmtiles"
    if path.exists():
        path.unlink()
    t0 = time.time()
    pyogrio.write_dataframe(df, str(path), driver="PMTiles", layer=layer, MINZOOM=lo, MAXZOOM=hi,
                            MAX_SIZE=1000000, MAX_FEATURES=200000)
    log(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB, {len(df):,} features, zoom {lo}-{hi}) in {time.time()-t0:.0f}s")
