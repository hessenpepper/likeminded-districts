"""Combine out/<state>.json from both machines into one table, charts and a map-free summary."""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
OUT = ROOT / "out"
rows = []
for f in sorted(OUT.glob("*.json")):
    r = json.loads(f.read_text())
    ab, k = r["state"], r["k"]
    vs = r["d_share_votes"]
    e = r["enacted"]
    row = {"state": ab.upper(), "districts": k, "precincts": r["nodes"], "d_vote_share": vs,
           "d_pop_share": r["d_share_pop"], "enacted_seats": e["d_seats"], "enacted_diss": e["obj"],
           "enacted_eg": e["eff_gap"], "enacted_competitive": e["competitive"],
           "proportional_seats": vs * k}
    if "ensemble" in r:
        ens = r["ensemble"]
        objs = np.array([x["obj"] for x in ens])
        seats = np.array([x["d_seats"] for x in ens])
        o = r["optimized"]
        row.update({
            "ens_plans": len(ens), "ens_steps": r["ensemble_steps"],
            "ens_seats_mean": seats.mean(), "ens_seats_min": seats.min(), "ens_seats_max": seats.max(),
            "ens_diss_mean": objs.mean(),
            "pct_neutral_more_uniform": (objs < e["obj"]).mean() * 100,
            "pct_neutral_ge_enacted_seats": (seats >= e["d_seats"]).mean() * 100,
            "pct_neutral_le_enacted_seats": (seats <= e["d_seats"]).mean() * 100,
            "opt_seats": o["d_seats"], "opt_diss": o["obj"], "opt_competitive": o["competitive"],
            "opt_eg": o["eff_gap"], "diss_reduction_pct": (1 - o["obj"] / e["obj"]) * 100,
            "opt_steps": r["opt_steps"], "eps_used": r["eps_used"], "start": r["start"],
            "max_pop_dev_opt": o["max_pop_dev"], "seconds": r.get("total_seconds"),
        })
    rows.append(row)
df = pd.DataFrame(rows).set_index("state")
df["enacted_seat_bonus"] = df["enacted_seats"] / df["districts"] - df["d_vote_share"]
df["ens_seat_bonus"] = df["ens_seats_mean"] / df["districts"] - df["d_vote_share"]
df["unexplained_seats"] = df["enacted_seats"] - df["ens_seats_mean"]  # + favors D, - favors R
df.to_csv(ROOT / "all_states.csv")
errs = sorted(p.stem.replace(".error", "") for p in OUT.glob("*.error.txt"))
print(f"{len(df)} states with results; errors: {errs}")

pd.set_option("display.width", 220)
m = df[df.districts > 1]
cols = ["districts", "d_vote_share", "enacted_seats", "proportional_seats", "ens_seats_mean", "ens_seats_min",
        "ens_seats_max", "unexplained_seats", "pct_neutral_ge_enacted_seats", "pct_neutral_le_enacted_seats",
        "enacted_diss", "ens_diss_mean", "opt_diss", "diss_reduction_pct", "enacted_eg"]
print(m.sort_values("unexplained_seats")[cols].round(3).to_string())
tot_e = m["enacted_seats"].sum()
print(f"\nMulti-district states: enacted D seats {tot_e} of {m.districts.sum()}; neutral-plan average "
      f"{m.ens_seats_mean.sum():.1f}; proportional {m.proportional_seats.sum():.1f}; optimized {m.opt_seats.sum()}")
print(f"Mean dissimilarity (pop-weighted by state size): enacted {np.average(m.enacted_diss, weights=m.districts):.3f}, "
      f"neutral {np.average(m.ens_diss_mean, weights=m.districts):.3f}, optimized {np.average(m.opt_diss, weights=m.districts):.3f}")

# ---- charts ----
fig, ax = plt.subplots(1, 2, figsize=(15, 7))
s = m.sort_values("unexplained_seats")
colors = ["#b2182b" if v < 0 else "#2166ac" for v in s["unexplained_seats"]]
ax[0].barh(s.index, s["unexplained_seats"], color=colors)
ax[0].axvline(0, color="k", lw=0.8)
ax[0].set(title="Enacted D seats minus neutral-plan average (2020 presidential)\nblue = more D seats than neutral maps give",
          xlabel="seats")
ax[0].tick_params(axis="y", labelsize=7)
ax[1].scatter(m["enacted_diss"], m["opt_diss"], s=m["districts"] * 6, alpha=.7)
for st, r in m.iterrows():
    ax[1].annotate(st, (r["enacted_diss"], r["opt_diss"]), fontsize=7)
lim = [0, max(m.enacted_diss.max(), m.opt_diss.max()) * 1.05]
ax[1].plot(lim, lim, "k--", lw=.8)
ax[1].set(title="Dissimilarity: enacted vs optimized (lower = more like-minded)", xlabel="enacted", ylabel="optimized")
fig.tight_layout()
fig.savefig(ROOT / "all_states_summary.png", dpi=130)
print("wrote all_states.csv and all_states_summary.png")
