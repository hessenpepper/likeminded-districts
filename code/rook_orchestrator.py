"""2020 'final' pass, unattended on the office PC. Replaces vra_orchestrator.py.

After the overnight run finishes, every multi-district state is re-optimized from its best saved plan under
  * rook contiguity (districts connected through shared boundary, not just a corner), and
  * the VRA floor (at least the enacted number of majority-Black / majority-Hispanic districts; trivial when that is 0).
The saved plans came from queen-adjacency runs, so --start warm first repairs them (stray pieces, population balance).
Outputs: C:\\gerry-compute\\vra\\out\\<st>_r2020.json / _r2020_best.pkl ; log vra\\orchestrator.log ; marker vra\\orchestrator.done"""
import csv
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(r"C:\gerry-compute")
VRA = BASE / "vra"
PY = sys.executable
BELOW_NORMAL = 0x00004000
STALL = ["--stall-steps", "20000", "--stall-gain", "0.001", "--min-steps", "50000", "--max-opt-min", "90"]


def log(*a):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(VRA / "orchestrator.log", "a") as fh:
        fh.write(line + "\n")


def overnight_done():
    f = BASE / "overnight" / "driver.out"
    return f.exists() and "ALL DONE" in f.read_text(errors="ignore")


def run_state(row):
    ab = row["state"].lower()
    if (VRA / "out" / f"{ab}_r2020.json").exists():
        return ab, "already done"
    warm = VRA / "warm" / f"{ab}_warm.pkl"
    start = ["--start", "warm", "--warm-file", str(warm)] if warm.exists() else ["--start", "enacted"]
    cmd = [PY, str(VRA / "pipeline.py"), "--state", ab, *start, "--vra", "--adjacency", "rook", "--tag", "_r2020",
           "--seed", "17", *STALL]
    t0 = time.time()
    with open(VRA / "logs" / f"{ab}_r2020.log", "w") as fh:
        rc = subprocess.call(cmd, cwd=str(VRA), stdout=fh, stderr=subprocess.STDOUT, creationflags=BELOW_NORMAL)
    return ab, f"rc={rc} {(time.time() - t0) / 60:.0f} min ({'warm' if warm.exists() else 'enacted'} start)"


if __name__ == "__main__":
    (VRA / "logs").mkdir(exist_ok=True)
    (VRA / "out").mkdir(exist_ok=True)
    log("rook orchestrator: waiting for the overnight run to finish...")
    waited = 0
    while not overnight_done() and waited < 36 * 3600:
        time.sleep(60)
        waited += 60
    log("overnight run finished (or wait limit reached); choosing start plans")
    subprocess.call([PY, str(BASE / "pick_vra_start.py")], cwd=str(BASE), stdout=open(VRA / "pick.log", "w"),
                    stderr=subprocess.STDOUT)
    rows = list(csv.DictReader(open(VRA / "vra_manifest.csv")))
    log(f"{len(rows)} multi-district states to re-optimize under rook + VRA floor")
    # states whose best plan is not compliant (need the enacted start) first: they take longest
    rows.sort(key=lambda r: r["compliant"] != "0")
    with ThreadPoolExecutor(6) as ex:
        for ab, msg in ex.map(run_state, rows):
            log(f"{ab.upper()}: {msg}")
    log("ALL DONE")
    (VRA / "orchestrator.done").write_text("done")
