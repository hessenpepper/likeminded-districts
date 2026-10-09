"""Overnight run: continue every multi-district state from its best saved plan until it stalls, plus fresh
random-start chains for the biggest states. Stall = < 0.1% improvement over 20,000 steps (after >= 50,000 steps)."""
import argparse, ctypes, json, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent
STALL = ["--stall-steps", "20000", "--stall-gain", "0.001", "--min-steps", "50000", "--max-opt-min", "90"]
BIG = ["ca", "tx", "fl", "ny", "il", "pa", "oh"]          # also get a fresh random-start chain
BELOW_NORMAL = 0x00004000


def precincts(ab):
    return json.loads((ROOT / "states" / f"{ab}_meta.json").read_text())["precincts"]


def run(job):
    ab, kind = job.split(":")
    if kind == "warm":
        extra = ["--start", "best", "--warm-file", str(ROOT / "warm" / f"{ab}_warm.pkl"), "--tag", "_warm", "--seed", "7"]
    else:
        extra = ["--start", "random", "--ens-min", "0.2", "--tag", "_rand", "--seed", "101"]
    t0 = time.time()
    with open(ROOT / "logs" / f"{ab}_{kind}.log", "w") as fh:
        rc = subprocess.call([sys.executable, str(ROOT / "pipeline.py"), "--state", ab, *extra, *STALL],
                             stdout=fh, stderr=subprocess.STDOUT, creationflags=BELOW_NORMAL)
    print(f"{time.strftime('%H:%M:%S')} {job} rc={rc} {(time.time()-t0)/60:.0f} min", flush=True)
    return job, rc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "out").mkdir(exist_ok=True)
    states = sorted((p.name[:-len("_warm.pkl")] for p in (ROOT / "warm").glob("*_warm.pkl")), key=precincts, reverse=True)
    jobs = []
    for ab in states:
        jobs.append(f"{ab}:warm")
        if ab in BIG:
            jobs.append(f"{ab}:rand")
    # long jobs first: the big states' random chains are the slowest
    jobs.sort(key=lambda j: (-(precincts(j.split(':')[0]) * (1.5 if j.endswith('rand') else 1))))
    done = lambda j: (ROOT / "out" / f"{j.split(':')[0]}_{'warm' if j.endswith('warm') else 'rand'}.json").exists()
    todo = [j for j in jobs if not done(j)]
    print(f"{len(todo)} jobs, {a.jobs} at a time: {','.join(todo)}", flush=True)
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(run, todo))
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    print("ALL DONE; failed:", [j for j, rc in res if rc], flush=True)
