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
RESULT_DIRS = [BASE / "vra" / "out"]       # rook-contiguous plans optimized under the VRA floor (majority-minority count)
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


def mm_counts(parts, vv, bv, hv):
    """(# majority-Black, # majority-Hispanic) districts by voting-age population."""
    parts = np.asarray(parts, dtype=np.int64)
    K = int(parts.max()) + 1
    V, B, H = (np.bincount(parts, x, K) for x in (vv, bv, hv))
    live = V > 0
    return int((B[live] / V[live] > 0.5).sum()), int((H[live] / V[live] > 0.5).sum())


def best_candidate(ab, index, need, vv, bv, hv):
    """Lowest-dissimilarity saved plan that keeps at least the enacted count of majority-Black and majority-Hispanic
    districts. Returns None when no saved plan qualifies (the site then shows the enacted plan as the optimized one)."""
    cands = []
    for d in RESULT_DIRS:
        for f in glob.glob(str(d / f"{ab}_*.json")):
            f = Path(f)
            pk = f.with_name(f.stem + "_best.pkl")
            if pk.exists():
                r = json.loads(f.read_text())
                if "optimized" in r:
                    plan = pd.Series(pickle.load(open(pk, "rb"))).reindex(index).astype(int).to_numpy()
                    nb, nh = mm_counts(plan, vv, bv, hv)
                    if nb >= need[0] and nh >= need[1]:
                        cands.append((r["optimized"]["obj"], f, pk, r["enacted"]["obj"], (nb, nh)))
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
    dis = g.dissolve(by=col, aggfunc={"pop": "sum", "D": "sum", "R": "sum", "vap": "sum", "bvap": "sum", "hvap": "sum"})
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
    race = pd.read_csv(BASE / "race" / f"{ab}.csv").set_index("node").reindex(g.index).fillna(0)
    for c in ("vap", "bvap", "hvap"):
        g[c] = race[c].to_numpy(float)
    miss = g["enacted"].isna()
    if miss.any():
        near = gpd.sjoin_nearest(g.loc[miss, ["geometry"]], g.loc[~miss, ["enacted", "geometry"]], how="left")
        g.loc[miss, "enacted"] = near[~near.index.duplicated()]["enacted"]
    g["enacted"] = g["enacted"].astype(int)
    vv, bv, hv = (g[c].to_numpy() for c in ("vap", "bvap", "hvap"))
    need = mm_counts(g["enacted"].to_numpy(), vv, bv, hv)
    cand = best_candidate(ab, g.index, need, vv, bv, hv)
    if cand is None:
        g["best"], eobj, oobj, got = g["enacted"], np.nan, np.nan, need
    else:
        oobj, _, pk, eobj, got = cand
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
        d["bp"] = (100 * d["bvap"] / d["vap"].where(d["vap"] > 0, 1)).round(1)     # Black alone, % of voting-age pop
        d["hp"] = (100 * d["hvap"] / d["vap"].where(d["vap"] > 0, 1)).round(1)     # Hispanic, % of voting-age pop
        dist_parts.append(gpd.GeoDataFrame(d[["plan", "st", "lab", "pop", "ds", "diss", "comp", "bp", "hp", "winner", "geometry"]],
                                           geometry="geometry", crs=5070).to_crs(4326))
    summary.append({"st": ab.upper(), "k": len(opt), "enacted_diss": eobj, "opt_diss": oobj,
                    "enacted_D": int((enc.winner == "D").sum()), "opt_D": int((opt.winner == "D").sum()),
                    "mm_enacted_black": need[0], "mm_enacted_hisp": need[1], "mm_opt_black": int(got[0]),
                    "mm_opt_hisp": int(got[1]), "vra_ok": bool(got[0] >= need[0] and got[1] >= need[1]), "pop": int(g["pop"].sum())})
    log(f"{ab.upper()}: {len(g):,} precincts, {len(opt)} districts ({time.time()-t0:.0f}s)")

precincts = pd.concat(prec_parts, ignore_index=True)
districts = pd.concat(dist_parts, ignore_index=True)
sm = pd.DataFrame(summary)
sm.to_csv(OUT / "summary.csv", index=False)
multi = sm[sm.k > 1]
stats = {"districts": int(sm.k.sum()), "enacted_D": int(sm.enacted_D.sum()), "opt_D": int(sm.opt_D.sum()),
         "enacted_diss": float(np.average(multi.enacted_diss, weights=multi.k)),
         "opt_diss": float(np.average(multi.opt_diss, weights=multi.k)), "states": len(sm),
         "mm_enacted": int(sm.mm_enacted_black.sum() + sm.mm_enacted_hisp.sum()),
         "mm_opt": int(sm.mm_opt_black.sum() + sm.mm_opt_hisp.sum()),
         "vra_ok_states": int(sm.vra_ok.sum()),
         "built": time.strftime("%Y-%m-%d")}
(OUT / "stats.json").write_text(json.dumps(stats))
log("stats", json.dumps(stats))
(OUT / "states.json").write_text(sm.assign(enacted_diss=sm.enacted_diss.round(4), opt_diss=sm.opt_diss.round(4))
                                 .to_json(orient="records"))

def write_tiles(path, df, layer, lo, hi):
    path = Path(path)
    if path.exists():
        path.unlink()
    t0 = time.time()
    pyogrio.write_dataframe(df, str(path), driver="PMTiles", layer=layer, MINZOOM=lo, MAXZOOM=hi,
                            MAX_SIZE=1000000, MAX_FEATURES=200000)
    log(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB, {len(df):,} features, zoom {lo}-{hi}) in {time.time()-t0:.0f}s")


write_tiles(OUT / "districts.pmtiles", districts, "districts", 0, 9)

# precincts: split by state into N_FILES files of roughly equal feature count (largest states first, greedy)
N_FILES = 4
counts = precincts.groupby("st").size().sort_values(ascending=False)
bins = [[] for _ in range(N_FILES)]
load = [0] * N_FILES
for st, n in counts.items():
    i = int(np.argmin(load))
    bins[i].append(st)
    load[i] += int(n)
for i, group in enumerate(bins, 1):
    write_tiles(OUT / f"precincts-{i}.pmtiles", precincts[precincts.st.isin(group)], "precincts", 6, 11)
(OUT / "precincts.json").write_text(json.dumps({str(i): g for i, g in enumerate(bins, 1)}))
