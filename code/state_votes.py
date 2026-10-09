"""Two-party presidential vote totals per state (plan-independent), for the map's seat-vs-vote comparison."""
import json
from pathlib import Path
import pyogrio

BASE = Path(r"C:\gerry-compute")
DIRS = [BASE / "states", BASE / "laptop-data" / "states"]
ALL = ("al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok "
       "or pa ri sc sd tn tx ut vt va wa wv wi wy").split()
out = {}
for ab in ALL:
    p = next(d / f"{ab}.gpkg" for d in DIRS if (d / f"{ab}.gpkg").exists())
    df = pyogrio.read_dataframe(p, columns=["D", "R"], read_geometry=False)
    out[ab.upper()] = [float(df["D"].sum()), float(df["R"].sum())]
(BASE / "state_votes.json").write_text(json.dumps(out))
D = sum(v[0] for v in out.values()); R = sum(v[1] for v in out.values())
print(len(out), "states; national two-party D share %.4f (D %.0f, R %.0f)" % (D / (D + R), D, R))
