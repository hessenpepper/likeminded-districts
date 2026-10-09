"""Run pipeline.py for a list of states, several at a time, at below-normal priority.

    python driver.py --states ca,tx,ny --jobs 8
Resumable: states that already have out/<st>.json are skipped.
"""
import argparse
import ctypes
import math
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent
# VEST zip sizes in MB (rough proxy for precinct count; Illinois = 15.5 MB = ~10k precincts)
SIZE = {"al": 18.8, "ak": 10.7, "az": 7.7, "ar": 12.9, "ca": 58.2, "co": 17.2, "ct": 2.6, "de": 1.6, "fl": 22.3,
        "ga": 19.1, "hi": 2.4, "id": 7.9, "il": 15.5, "in": 11.0, "ia": 5.2, "ks": 9.5, "ky": 6.6, "la": 16.6,
        "me": 3.6, "md": 21.6, "ma": 7.6, "mi": 7.9, "mn": 5.6, "ms": 13.8, "mo": 13.5, "mt": 7.2, "ne": 4.2,
        "nv": 6.9, "nh": 1.2, "nj": 8.0, "nm": 13.8, "ny": 25.2, "nc": 25.0, "nd": 2.3, "oh": 16.4, "ok": 13.4,
        "or": 13.6, "pa": 20.4, "ri": 1.4, "sc": 11.2, "sd": 4.3, "tn": 24.7, "tx": 41.1, "ut": 10.7, "vt": 0.7,
        "va": 22.5, "wa": 30.3, "wi": 24.1, "wv": 16.6, "wy": 4.2}
ONE_SEAT = {"ak", "de", "nd", "sd", "vt", "wy"}
BELOW_NORMAL = 0x00004000


def scale(ab):
    return min(1.8, max(0.6, math.sqrt(SIZE[ab] / 15.5)))


def cost(ab):
    return 1.0 if ab in ONE_SEAT else 28 * scale(ab) + 0.2 * SIZE[ab]


def run_one(ab, base_args):
    s = scale(ab)
    log = ROOT / "logs" / f"{ab}.log"
    cmd = [sys.executable, str(ROOT / "pipeline.py"), "--state", ab,
           "--ens-min", f"{8 * s:.1f}", "--opt-min", f"{20 * s:.1f}", *base_args]
    t0 = time.time()
    with open(log, "w") as fh:
        rc = subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT, creationflags=BELOW_NORMAL)
    print(f"{time.strftime('%H:%M:%S')} {ab} finished rc={rc} in {(time.time()-t0)/60:.1f} min", flush=True)
    return ab, rc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--extra", default="", help="extra args passed to pipeline.py")
    a = ap.parse_args()
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "out").mkdir(exist_ok=True)
    states = [s for s in a.states.split(",") if s]
    todo = [s for s in states if not (ROOT / "out" / f"{s}.json").exists()]
    todo.sort(key=cost, reverse=True)  # big states first so the tail is short
    print(f"{len(todo)} states to run with {a.jobs} jobs: {','.join(todo)}", flush=True)
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # keep the machine awake while running
    failed = []
    with ThreadPoolExecutor(a.jobs) as ex:
        for ab, rc in ex.map(lambda s: run_one(s, a.extra.split()), todo):
            if rc:
                failed.append(ab)
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    print("ALL DONE; failed:", failed, flush=True)
