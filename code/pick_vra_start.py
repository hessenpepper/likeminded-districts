"""For each multi-district state: the enacted plan's majority-Black / majority-Hispanic district counts (the VRA floor),
and which saved plans already respect it. Writes C:\\gerry-compute\\vra\\warm\\<st>_warm.pkl for the best compliant plan and
C:\\gerry-compute\\vra\\vra_manifest.csv (states with no compliant plan are started from the enacted plan instead)."""
import glob
import json
import pickle
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio

BASE = Path(r"C:\gerry-compute")
STATE_DIRS = [BASE / "states", BASE / "laptop-data" / "states"]
RESULT_DIRS = [BASE / "out", BASE / "out_laptop", BASE / "seedcheck" / "out", BASE / "seedcheck_enacted" / "out",
               BASE / "overnight" / "out"]
STATES = ("al az ar ca co ct fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc oh ok or pa ri sc "
          "tn tx ut va wa wv wi").split()
OUT = BASE / "vra"
(OUT / "warm").mkdir(parents=True, exist_ok=True)


def counts(assign, vv, bv, hv):
    parts = np.asarray(assign, dtype=np.int64)
    K = int(parts.max()) + 1
    V, B, H = (np.bincount(parts, x, K) for x in (vv, bv, hv))
    live = V > 0
    return int((B[live] / V[live] > 0.5).sum()), int((H[live] / V[live] > 0.5).sum())


rows = []
for ab in STATES:
    gp = next(d / f"{ab}.gpkg" for d in STATE_DIRS if (d / f"{ab}.gpkg").exists())
    enc = pyogrio.read_dataframe(gp, columns=["node", "enacted"], read_geometry=False).set_index("node")["enacted"]
    race = pd.read_csv(BASE / "race" / f"{ab}.csv").set_index("node").reindex(enc.index).fillna(0)
    vv, bv, hv = (race[c].to_numpy(float) for c in ("vap", "bvap", "hvap"))
    e = enc.fillna(enc.mode().iloc[0]).astype(int).to_numpy()
    need_b, need_h = counts(e, vv, bv, hv)
    cands = []
    for d in RESULT_DIRS:
        for f in glob.glob(str(d / f"{ab}.json")) + glob.glob(str(d / f"{ab}_*.json")):
            f = Path(f)
            pk = f.with_name(f.stem + "_best.pkl")
            if not pk.exists():
                continue
            r = json.loads(f.read_text())
            if "optimized" not in r:
                continue
            plan = pickle.load(open(pk, "rb"))
            a = pd.Series(plan).reindex(enc.index).astype(int).to_numpy()
            nb, nh = counts(a, vv, bv, hv)
            cands.append({"obj": r["optimized"]["obj"], "pk": pk, "name": f"{d.name}/{f.stem}", "nb": nb, "nh": nh,
                          "ok": nb >= need_b and nh >= need_h})
    ok = [c for c in cands if c["ok"]]
    best_all = min(c["obj"] for c in cands)
    chosen = min(ok, key=lambda c: c["obj"]) if ok else None
    if chosen:
        shutil.copy(chosen["pk"], OUT / "warm" / f"{ab}_warm.pkl")
    rows.append({"state": ab.upper(), "need_black": need_b, "need_hisp": need_h, "candidates": len(cands),
                 "compliant": len(ok), "best_obj_any": round(best_all, 4),
                 "best_obj_compliant": round(chosen["obj"], 4) if chosen else None,
                 "chosen": chosen["name"] if chosen else "enacted (repaired) start",
                 "best_any_counts": next(f"{c['nb']}/{c['nh']}" for c in cands if c["obj"] == best_all)})
df = pd.DataFrame(rows)
df.to_csv(OUT / "vra_manifest.csv", index=False)
pd.set_option("display.width", 200)
print(df.to_string(index=False))
has = df[(df.need_black > 0) | (df.need_hisp > 0)]
print(f"\nstates where the enacted plan has majority-minority districts: {len(has)} of {len(df)}")
print(f"  of those, best plan already compliant: {int((has.compliant > 0).sum())}; needs a constrained search: {int((has.compliant == 0).sum())}")
print(f"  states with no floor (no majority-minority districts): {len(df) - len(has)}")
