"""One state, end to end: download -> precinct table -> neutral ensemble + dissimilarity optimizer.

    python pipeline.py --state il --ens-min 8 --opt-min 20

Inputs (all public):
  * VEST 2020 precinct shapefiles (Harvard Dataverse, doi:10.7910/DVN/K7760H): presidential votes
  * Census 2020 PL 94-171 block population (internal points) -> precinct population
  * Census TIGER 2024 119th-Congress districts -> the "enacted" plan
Objective minimized: population-weighted mean over districts of
    Diss_d = sum_i w_i |p_i - P_d| / (2 W_d P_d (1 - P_d)),   p_i = precinct 2-party D share (all residents)
"""
import argparse
import json
import pickle
import re
import shutil
import sys
import time
import traceback
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
RAW, STATES, OUT, LOGS = ROOT / "raw", ROOT / "states", ROOT / "out", ROOT / "logs"
for d in (RAW, STATES, OUT, LOGS):
    d.mkdir(exist_ok=True)

# abbr: (name for Census URL, FIPS, VEST 2020 Dataverse file id)
ST = {
    "al": ("Alabama", "01", 4751074), "ak": ("Alaska", "02", 11070062), "az": ("Arizona", "04", 4864722),
    "ar": ("Arkansas", "05", 4931787), "ca": ("California", "06", 5206371), "co": ("Colorado", "08", 4863166),
    "ct": ("Connecticut", "09", 4986646), "de": ("Delaware", "10", 4773531), "fl": ("Florida", "12", 12070362),
    "ga": ("Georgia", "13", 11070054), "hi": ("Hawaii", "15", 4750434), "id": ("Idaho", "16", 4789401),
    "il": ("Illinois", "17", 14304793), "in": ("Indiana", "18", 5143396), "ia": ("Iowa", "19", 14304797),
    "ks": ("Kansas", "20", 6696064), "ky": ("Kentucky", "21", 6550200), "la": ("Louisiana", "22", 5739918),
    "me": ("Maine", "23", 11070059), "md": ("Maryland", "24", 12070366), "ma": ("Massachusetts", "25", 5007849),
    "mi": ("Michigan", "26", 9865421), "mn": ("Minnesota", "27", 11595851), "ms": ("Mississippi", "28", 5706487),
    "mo": ("Missouri", "29", 5007850), "mt": ("Montana", "30", 4773527), "ne": ("Nebraska", "31", 5739922),
    "nv": ("Nevada", "32", 11595850), "nh": ("New_Hampshire", "33", 11070060), "nj": ("New_Jersey", "34", 12070367),
    "nm": ("New_Mexico", "35", 5425599), "ny": ("New_York", "36", 5259468), "nc": ("North_Carolina", "37", 11595848),
    "nd": ("North_Dakota", "38", 5342900), "oh": ("Ohio", "39", 14304791), "ok": ("Oklahoma", "40", 5790364),
    "or": ("Oregon", "41", 5194704), "pa": ("Pennsylvania", "42", 14304796), "ri": ("Rhode_Island", "44", 11070053),
    "sc": ("South_Carolina", "45", 11070057), "sd": ("South_Dakota", "46", 6082788), "tn": ("Tennessee", "47", 11070058),
    "tx": ("Texas", "48", 12070365), "ut": ("Utah", "49", 11595849), "vt": ("Vermont", "50", 14304794),
    "va": ("Virginia", "51", 11070061), "wa": ("Washington", "53", 11070055), "wv": ("West_Virginia", "54", 6418344),
    "wi": ("Wisconsin", "55", 14304795), "wy": ("Wyoming", "56", 4789404),
}
PL_URL = ("https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/"
          "{name}/{ab}2020.pl.zip")
CD_URL = "https://www2.census.gov/geo/tiger/TIGER2024/CD/tl_2024_{fips}_cd119.zip"
VEST_URL = "https://dataverse.harvard.edu/api/access/datafile/{fid}"
CRS = 5070


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fetch(url, dest, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research script)"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            return
        except Exception as e:
            log(f"download retry {i+1} for {url}: {e}")
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"could not download {url}")


# --------------------------------------------------------------------------- prep
def prep(ab):
    import geopandas as gpd

    name, fips, fid = ST[ab]
    gp = STATES / f"{ab}.gpkg"
    meta_path = STATES / f"{ab}_meta.json"
    if gp.exists() and meta_path.exists():
        log("prep cached")
        return json.loads(meta_path.read_text())
    work = RAW / ab
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    t0 = time.time()

    log("downloading VEST precincts")
    fetch(VEST_URL.format(fid=fid), work / "vest.zip")
    with zipfile.ZipFile(work / "vest.zip") as z:
        z.extractall(work / "vest")
    shp = sorted((work / "vest").rglob("*.shp"))[0]
    prec = gpd.read_file(shp)
    dcol = [c for c in prec.columns if re.match(r"^G20PRED", c)]
    rcol = [c for c in prec.columns if re.match(r"^G20PRER", c)]
    assert len(dcol) == 1 and len(rcol) == 1, f"presidential columns not found: {list(prec.columns)}"
    prec = prec.to_crs(CRS)
    bad = ~prec.geometry.is_valid
    if bad.any():
        prec.loc[bad, "geometry"] = prec.loc[bad, "geometry"].buffer(0)
    prec = prec[~prec.geometry.is_empty].reset_index(drop=True)
    prec["node"] = prec.index
    prec["D"] = prec[dcol[0]].astype(float)
    prec["R"] = prec[rcol[0]].astype(float)
    log(f"{len(prec):,} precincts; presidential D={prec.D.sum():,.0f} R={prec.R.sum():,.0f}")

    log("downloading congressional districts")
    fetch(CD_URL.format(fips=fips), work / "cd.zip")
    with zipfile.ZipFile(work / "cd.zip") as z:
        z.extractall(work / "cd")
    cd = gpd.read_file(sorted((work / "cd").rglob("*.shp"))[0]).to_crs(CRS)
    cd = cd[~cd["GEOID"].str.endswith("ZZ")].copy()
    cd["district"] = cd["GEOID"].str[2:].astype(int)
    k = cd["district"].nunique()

    log("downloading census PL 94-171")
    fetch(PL_URL.format(name=name, ab=ab), work / "pl.zip")
    with zipfile.ZipFile(work / "pl.zip") as z:
        z.extractall(work / "pl")
    plf = {f.name[len(ab):][:7]: f for f in (work / "pl").glob("*.pl")}  # '000012020', 'geo2020' ...
    geo_f = next(f for f in (work / "pl").glob(f"{ab}geo2020.pl"))
    f1_f = next((work / "pl").glob(f"{ab}000012020.pl"))
    f2_f = next((work / "pl").glob(f"{ab}000022020.pl"))
    with open(geo_f, encoding="latin-1") as fh:
        ncol = len(fh.readline().split("|"))
    geo = pd.read_csv(geo_f, sep="|", header=None, dtype=str, encoding="latin-1",
                      usecols=[2, 7, ncol - 5, ncol - 4], names=["sumlev", "logrecno", "lat", "lon"])
    geo = geo[geo["sumlev"] == "750"]
    f1 = pd.read_csv(f1_f, sep="|", header=None, dtype=str, encoding="latin-1", usecols=[4, 5],
                     names=["logrecno", "pop"])
    f2 = pd.read_csv(f2_f, sep="|", header=None, dtype=str, encoding="latin-1", usecols=[4, 5],
                     names=["logrecno", "vap"])
    blk = geo.merge(f1, on="logrecno").merge(f2, on="logrecno")
    blk[["pop", "vap"]] = blk[["pop", "vap"]].astype(int)
    pts = gpd.GeoDataFrame(blk[["pop", "vap"]],
                           geometry=gpd.points_from_xy(blk["lon"].astype(float), blk["lat"].astype(float)),
                           crs=4269).to_crs(CRS)
    del geo, f1, f2, blk
    total_pop = int(pts["pop"].sum())
    log(f"{len(pts):,} blocks, population {total_pop:,}")

    # blocks -> precinct (nearest polygon for points that miss every polygon), blocks -> district
    j = gpd.sjoin(pts, prec[["node", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    miss = j["node"].isna()
    lost = int(j.loc[miss, "pop"].sum())
    if miss.any():
        nn = gpd.sjoin_nearest(pts.loc[miss[miss].index], prec[["node", "geometry"]], how="left")
        nn = nn[~nn.index.duplicated(keep="first")]
        j.loc[nn.index, "node"] = nn["node"]
    j = j.drop(columns="index_right")
    jd = gpd.sjoin(j, cd[["district", "geometry"]], how="left", predicate="within")
    jd = jd[~jd.index.duplicated(keep="first")]
    miss = jd["district"].isna()
    if miss.any():
        nn = gpd.sjoin_nearest(j.loc[miss[miss].index], cd[["district", "geometry"]], how="left")
        nn = nn[~nn.index.duplicated(keep="first")]
        jd.loc[nn.index, "district"] = nn["district"]
    jd["node"] = jd["node"].astype(int)
    jd["district"] = jd["district"].astype(int)

    tot = jd.groupby("node")[["pop", "vap"]].sum()
    by = jd.groupby(["node", "district"])["pop"].sum().reset_index().sort_values("pop", ascending=False)
    home = by.drop_duplicates("node").set_index("node")["district"]
    out = prec[["node", "D", "R", "geometry"]].copy()
    out["pop"] = tot["pop"].reindex(out["node"]).fillna(0).to_numpy()
    out["vap"] = tot["vap"].reindex(out["node"]).fillna(0).to_numpy()
    out["enacted"] = home.reindex(out["node"]).to_numpy()
    out.to_file(gp, driver="GPKG")
    meta = {"state": ab, "k": int(k), "precincts": int(len(prec)), "total_pop": total_pop,
            "pop_outside_precinct_polygons": lost, "split_precincts": int((by.groupby("node").size() > 1).sum()),
            "votes_per_vap": float((out.D.sum() + out.R.sum()) / out.vap.sum()),
            "prep_seconds": round(time.time() - t0, 1)}
    meta_path.write_text(json.dumps(meta))
    shutil.rmtree(work, ignore_errors=True)
    log("prep done", json.dumps(meta))
    return meta


# --------------------------------------------------------------------------- optimize
def optimize(ab, meta, a):
    import geopandas as gpd
    import networkx as nx
    from gerrychain import Graph, MarkovChain, Partition, accept, constraints, updaters
    from gerrychain.optimization import SingleMetricOptimizer
    from gerrychain.proposals import ReCom
    from shapely.strtree import STRtree

    gdf = gpd.read_file(STATES / f"{ab}.gpkg")
    import shapely
    from shapely.geometry import box as _box
    nullg = gdf.geometry.isna() | gdf.geometry.is_empty
    if nullg.any():     # a precinct with no usable outline (no residents mapped): park a 1 m square at the state's edge
        x0, y0, x1, y1 = gdf.geometry[~nullg].total_bounds
        gdf.loc[nullg, "geometry"] = [_box(x0, y0, x0 + 1, y0 + 1)] * int(nullg.sum())
        log(f"{int(nullg.sum())} precinct(s) without geometry given a placeholder outline")
    bad = ~gdf.geometry.is_valid
    if bad.any():      # self-intersecting source polygons: make_valid, keep the polygonal part
        fixed = []
        for geom in gdf.geometry[bad]:
            m = shapely.make_valid(geom)
            if m.geom_type not in ("Polygon", "MultiPolygon"):
                parts = [p for p in shapely.get_parts(m) if p.geom_type in ("Polygon", "MultiPolygon")]
                m = shapely.union_all(parts) if parts else geom.buffer(0)
            fixed.append(m)
        gdf.loc[bad, "geometry"] = fixed
        log(f"repaired {int(bad.sum())} invalid precinct geometries")
    k = meta["k"]
    graph = Graph.from_geodataframe(gdf, adjacency=a.adjacency, cols_to_add=["pop", "D", "R", "enacted"])
    if a.land_only:
        # Water polygons (zero residents, mostly outside the Census shoreline) must not connect land: cut their edges
        # down to one, so they hang off the graph as leaves and a district can't use open water as a corridor.
        import shapely
        shore = gpd.read_file(a.shoreline).set_index("STUSPS").to_crs(gdf.crs).loc[ab.upper(), "geometry"]
        zero = np.where(gdf["pop"].to_numpy() == 0)[0]
        water = set()
        if len(zero):
            gz = gdf.geometry.to_numpy()[zero]
            frac = shapely.area(shapely.intersection(gz, shore)) / np.maximum(shapely.area(gz), 1.0)
            water = {int(zero[i]) for i in np.where(frac < 0.5)[0]}
        cut = 0
        for w_ in water:
            nb_ = list(graph.neighbors(w_))
            keep = next((m for m in nb_ if m not in water), None)
            for m in nb_:
                if m != keep:
                    graph.remove_edge(w_, m)
                    cut += 1
        log(f"land-only adjacency: {len(water)} water precincts made leaves ({cut} edges removed)")
    nodes = list(graph.nodes)
    N = len(nodes)

    # join disconnected pieces (islands) to their nearest neighbor so spanning trees exist
    geoms = gdf.geometry.to_numpy()
    comps = [set(c) for c in nx.connected_components(graph)]
    bridges = 0
    while len(comps) > 1:
        comps.sort(key=len)
        small = comps[0]
        rest = [n for c in comps[1:] for n in c]
        tree = STRtree([geoms[n] for n in rest])
        best = None
        for n in small:
            i = int(tree.nearest(geoms[n]))
            d = geoms[n].distance(geoms[rest[i]])
            if best is None or d < best[0]:
                best = (d, n, rest[i])
        graph.add_edge(best[1], best[2])
        bridges += 1
        comps = [set(c) for c in nx.connected_components(graph)]
    if bridges:
        log(f"added {bridges} bridge edges to connect islands")

    enacted = {n: graph.node_data(n)["enacted"] for n in nodes}
    for _ in range(50):  # precincts with no residents have no district: copy from neighbors
        todo = [n for n in nodes if enacted[n] is None or enacted[n] != enacted[n]]
        if not todo:
            break
        for n in todo:
            neigh = [enacted[m] for m in graph.neighbors(n) if enacted[m] == enacted[m] and enacted[m] is not None]
            if neigh:
                enacted[n] = max(set(neigh), key=neigh.count)
    for n in nodes:
        graph.node_data(n)["enacted"] = int(enacted[n])

    pop = np.array([graph.node_data(n)["pop"] for n in nodes], dtype=float)
    D = np.array([graph.node_data(n)["D"] for n in nodes], dtype=float)
    R = np.array([graph.node_data(n)["R"] for n in nodes], dtype=float)
    nv = D + R
    ok = nv > 0
    p = np.where(ok, D / np.where(ok, nv, 1), 0.0)
    w = np.where(ok, pop, 0.0)
    ideal = pop.sum() / k
    kmax = 64

    def parts_array(part):
        asg = part.assignment
        return np.fromiter((asg[n] for n in nodes), dtype=np.int64, count=N)

    def summarize(parts):
        K = int(parts.max()) + 1
        W = np.bincount(parts, w, K)
        live = W > 0
        P = np.zeros(K)
        P[live] = np.bincount(parts, w * p, K)[live] / W[live]
        mad = np.bincount(parts, w * np.abs(p - P[parts]), K)
        den = 2 * W * P * (1 - P)
        diss = np.zeros(K)
        good = live & (den > 0)
        diss[good] = mad[good] / den[good]
        Dv, Rv = np.bincount(parts, D, K), np.bincount(parts, R, K)
        popd = np.bincount(parts, pop, K)
        tv = (Dv + Rv)[live]
        wasteD = np.where(Dv > Rv, Dv - (Dv + Rv) / 2, Dv)[live]
        wasteR = np.where(Rv > Dv, Rv - (Dv + Rv) / 2, Rv)[live]
        return {
            "obj": float((W[live] * diss[live]).sum() / W[live].sum()),
            "mad": float(mad[live].sum() / (2 * W[live].sum())),
            "d_seats": int((Dv[live] > Rv[live]).sum()),
            "competitive": int((np.abs(P[live] - 0.5) < 0.05).sum()),
            "eff_gap": float((wasteD.sum() - wasteR.sum()) / tv.sum()),  # + = D wastes more (favors R)
            "max_pop_dev": float(np.abs(popd[live] / ideal - 1).max()),
            "d_share_by_district": sorted(P[live].round(3).tolist()),
        }

    def obj_fn(part):
        return summarize(parts_array(part))["obj"]

    res = {"state": ab, "k": k, "nodes": N, "meta": meta, "bridges": bridges, "adjacency": a.adjacency,
           "d_share_votes": float(D.sum() / nv.sum()), "d_share_pop": float((w * p).sum() / w.sum())}
    e_parts = np.array([graph.node_data(n)["enacted"] for n in nodes], dtype=np.int64)
    res["enacted"] = summarize(e_parts)
    log("ENACTED", json.dumps({x: v for x, v in res["enacted"].items() if x != "d_share_by_district"}))
    if k == 1:
        res["note"] = "single at-large district: nothing to optimize"
        return res, None

    upd = {"population": updaters.Tally("pop", alias="population")}
    BIG = 10 ** 9
    if a.start in ("enacted", "warm"):
        # start from the enacted plan (--start warm: a saved plan carried onto new precincts). Whole-precinct plans rarely sit well inside +-eps, and ReCom needs slack
        # to re-split district pairs, so first move boundary precincts from over- to under-populated districts
        # (keeping every district's contiguity no worse than before) until all are within eps/2.
        import networkx as nx
        t0 = time.time()
        eps_used = a.eps
        nbrs = {n: list(graph.neighbors(n)) for n in nodes}
        G = nx.Graph()
        G.add_nodes_from(nodes)
        G.add_edges_from((n, m) for n in nodes for m in nbrs[n] if n < m)
        idx = {n: i for i, n in enumerate(nodes)}

        def balance_repair(assign, target, max_iter=200000):
            """Move boundary precincts from higher- to lower-population neighbors while that lowers the sum of squared
            deviations (any move of weight x between districts with deviations dA > dB helps iff x < dA - dB), never
            leaving the source district more fragmented than before."""
            assign = dict(assign)
            members = {}
            for n, d in assign.items():
                members.setdefault(d, set()).add(n)
            dpop = {d: float(sum(pop[idx[n]] for n in s_)) for d, s_ in members.items()}
            ncomp = {d: nx.number_connected_components(G.subgraph(s_)) for d, s_ in members.items()}
            bnd = {n for n in nodes if any(assign[m] != assign[n] for m in nbrs[n])}
            moves = 0
            for _ in range(max_iter):
                dev = {d: dpop[d] / ideal - 1 for d in dpop}
                if max(abs(v) for v in dev.values()) <= target:
                    break
                cands = []
                for n in bnd:
                    x = pop[idx[n]] / ideal
                    if x <= 0:
                        continue
                    A = assign[n]
                    for B in {assign[m] for m in nbrs[n]}:
                        if B == A:
                            continue
                        gain = 2 * x * (dev[A] - dev[B]) - 2 * x * x
                        if gain > 1e-12:
                            cands.append((gain, n, A, B))
                if not cands:
                    break
                cands.sort(reverse=True)
                moved = False
                for gain, n, A, B in cands[:30]:
                    rest = members[A] - {n}
                    if not rest:
                        continue
                    if nx.number_connected_components(G.subgraph(rest)) <= ncomp[A]:
                        members[A].remove(n)
                        members[B].add(n)
                        assign[n] = B
                        dpop[A] -= pop[idx[n]]
                        dpop[B] += pop[idx[n]]
                        ncomp[A] = nx.number_connected_components(G.subgraph(members[A]))
                        ncomp[B] = nx.number_connected_components(G.subgraph(members[B]))
                        for q in [n] + nbrs[n]:
                            if any(assign[m] != assign[q] for m in nbrs[q]):
                                bnd.add(q)
                            else:
                                bnd.discard(q)
                        moves += 1
                        moved = True
                        break
                if not moved:
                    break
            return assign, moves, max(abs(v / ideal - 1) for v in dpop.values())

        def bridge_fragments(assign):
            """Connect each district's separated pieces to its largest piece by the nearest pair of precincts (adds
            graph edges). Used for the enacted plan, whose districts legitimately cross water or other gaps."""
            from shapely.strtree import STRtree
            members = {}
            for n, d in assign.items():
                members.setdefault(d, set()).add(n)
            added = 0
            for d, s_ in members.items():
                comps = sorted(nx.connected_components(G.subgraph(s_)), key=len, reverse=True)
                main = set(comps[0])
                for comp in comps[1:]:
                    main_nodes = list(main)
                    tree = STRtree([geoms[n] for n in main_nodes])
                    best = None
                    for n in comp:
                        i = int(tree.nearest(geoms[n]))
                        dist = geoms[n].distance(geoms[main_nodes[i]])
                        if best is None or dist < best[0]:
                            best = (dist, n, main_nodes[i])
                    _, u, v = best
                    graph.add_edge(u, v)
                    G.add_edge(u, v)
                    nbrs[u].append(v)
                    nbrs[v].append(u)
                    main |= comp
                    added += 1
            return added

        def fix_contiguity(assign):
            """Whole-precinct enacted plans can have stray pieces (a precinct goes to the district holding most of
            its residents). Give each non-largest piece to the neighboring district it touches most."""
            assign = dict(assign)
            fixed_nodes, fixed_pop = 0, 0.0
            for _ in range(30):
                members = {}
                for n, d in assign.items():
                    members.setdefault(d, set()).add(n)
                changed = False
                for d, s_ in members.items():
                    comps = sorted(nx.connected_components(G.subgraph(s_)),
                                   key=lambda c: sum(pop[idx[n]] for n in c), reverse=True)
                    for frag in comps[1:]:
                        cnt = {}
                        for n in frag:
                            for m in nbrs[n]:
                                if assign[m] != d:
                                    cnt[assign[m]] = cnt.get(assign[m], 0) + 1
                        if cnt:
                            e = max(cnt, key=cnt.get)
                            for n in frag:
                                assign[n] = e
                            fixed_nodes += len(frag)
                            fixed_pop += sum(pop[idx[n]] for n in frag)
                            changed = True
                if not changed:
                    break
            return assign, fixed_nodes, fixed_pop

        if a.start == "warm":
            with open(a.warm_file, "rb") as fh:
                saved = pickle.load(fh)
            assign = {n: int(saved[n]) for n in nodes}
            raw = summarize(np.array([assign[n] for n in nodes], dtype=np.int64))
            res["warm_raw_obj"], res["warm_raw_max_pop_dev"] = raw["obj"], raw["max_pop_dev"]
            log(f"carried plan before repair: obj {raw['obj']:.4f}, max population deviation {raw['max_pop_dev']*100:.2f}%")
            if a.bridge_warm:       # continuing a saved plan whose districts use water crossings / gaps (bridge edges)
                nb = bridge_fragments(assign)
                if nb:
                    log(f"added {nb} bridge edges so the carried plan's districts are connected")
                    res["district_bridges"] = nb
        else:
            assign = {n: int(graph.node_data(n)["enacted"]) for n in nodes}
            nb = bridge_fragments(assign)
            if nb:
                log(f"added {nb} bridge edges so the enacted districts are connected (water crossings and gaps)")
                res["district_bridges"] = nb
        assign, fixed_nodes, fixed_pop = fix_contiguity(assign)
        if fixed_nodes:
            log(f"contiguity: reattached {fixed_nodes} stray precincts ({fixed_pop:,.0f} people) to neighboring districts")
        dev0 = res["enacted"]["max_pop_dev"]
        assign, moves, devr = balance_repair(assign, a.eps * 0.5)
        if devr > a.eps:
            if devr > 0.05:
                raise RuntimeError(f"could not rebalance the start plan below 5% (got {devr:.4f})")
            eps_used = float(devr * 1.02)
            log(f"population tolerance for this state loosened to +-{eps_used*100:.2f}% (the start plan reached {devr*100:.2f}%)")
        start = Partition(graph, assignment=assign, updaters=upd)
        res.update({"eps_used": eps_used, "start": a.start, "rebalance_moves": moves,
                    "contiguity_fixed_nodes": fixed_nodes, "contiguity_fixed_pop": fixed_pop,
                    "start_max_dev_before": dev0, "start_max_dev_after": devr,
                    "start_seconds": round(time.time() - t0, 1)})
        log(f"rebalanced enacted plan: max deviation {dev0*100:.2f}% -> {devr*100:.2f}% with {moves} precinct moves")
        log(f"start plan ({a.start}, rebalanced) obj {obj_fn(start):.4f} vs enacted {res['enacted']['obj']:.4f}")
        proposal = ReCom.district_pairs_mst(pop_col="pop", pop_target=ideal, epsilon=eps_used)
        cons = [constraints.within_percent_of_ideal_population(start, eps_used, pop_key="population")]
        res["ensemble"], res["ensemble_steps"], res["ensemble_seconds"] = [], 0, 0.0
        last = start
    elif a.start == "best":
        # continue from a saved plan (a pickled {precinct: district} assignment); same tolerance as the other runs
        t0 = time.time()
        with open(a.warm_file, "rb") as fh:
            saved = pickle.load(fh)
        start = Partition(graph, assignment={n: int(saved[n]) for n in nodes}, updaters=upd)
        eps_used = a.eps
        res.update({"eps_used": eps_used, "start": "best", "warm_file": str(a.warm_file),
                    "start_seconds": round(time.time() - t0, 1)})
        log(f"start plan (saved best, {a.warm_file}) obj {obj_fn(start):.4f}, enacted {res['enacted']['obj']:.4f}")
        proposal = ReCom.district_pairs_mst(pop_col="pop", pop_target=ideal, epsilon=eps_used)
        cons = [constraints.within_percent_of_ideal_population(start, eps_used, pop_key="population")]
        res["ensemble"], res["ensemble_steps"], res["ensemble_seconds"] = [], 0, 0.0
        last = start
    else:
        t0 = time.time()
        eps_ladder = [a.eps, 0.01, 0.02, 0.05]
        start, eps_used, start_type = None, None, None
        for eps in eps_ladder:
            try:
                start = Partition.from_random_assignment(graph, n_parts=k, epsilon=eps, pop_col="pop",
                                                         updaters=upd, rng=a.seed)
                eps_used, start_type = eps, "random"
                break
            except Exception as e:
                log(f"random start failed at eps={eps}: {type(e).__name__}: {str(e)[:120]}")
        if start is None:  # fall back to the enacted plan with its own deviation as tolerance
            eps_used = float(max(res["enacted"]["max_pop_dev"] * 1.05, a.eps))
            start = Partition(graph, assignment="enacted", updaters=upd)
            start_type = "enacted"
        res.update({"eps_used": eps_used, "start": start_type, "start_seconds": round(time.time() - t0, 1)})
        log(f"start plan ({start_type}, eps={eps_used}) in {time.time()-t0:.0f}s, obj {obj_fn(start):.4f}")

        proposal = ReCom.district_pairs_mst(pop_col="pop", pop_target=ideal, epsilon=eps_used)
        cons = [constraints.within_percent_of_ideal_population(start, eps_used, pop_key="population")]

        # ---- neutral ensemble (time-boxed) ----
        t0 = time.time()
        rows, last, steps = [], start, 0
        for i, part in enumerate(MarkovChain(proposal, cons, accept.always_accept, start, BIG, rng=a.seed + 1)):
            last, steps = part, i + 1
            if i >= a.burn and (i - a.burn) % a.thin == 0:
                rows.append(summarize(parts_array(part)))
            if time.time() - t0 > a.ens_min * 60 and len(rows) >= 20:
                break
            if time.time() - t0 > 3 * a.ens_min * 60:
                break
        res["ensemble"] = rows
        res["ensemble_steps"] = steps
        res["ensemble_seconds"] = round(time.time() - t0, 1)
        objs = np.array([r["obj"] for r in rows])
        seats = np.array([r["d_seats"] for r in rows])
        log(f"ENSEMBLE {len(rows)} plans / {steps} steps: obj mean {objs.mean():.4f}, D seats mean {seats.mean():.2f} "
            f"range {seats.min()}-{seats.max()} ({res['ensemble_seconds']:.0f}s)")


    res["start_obj"] = float(obj_fn(last))
    vra_info = None
    if a.vra:
        if a.start == "random":
            raise RuntimeError("--vra needs --start enacted or --start best (a random plan cannot meet the VRA floor)")
        race = pd.read_csv(Path(a.race_dir) / f"{ab}.csv").set_index("node").reindex(nodes).fillna(0)
        bv, hv, vv = (race[c].to_numpy(float) for c in ("bvap", "hvap", "vap"))

        def vra_counts(parts):
            """(# majority-Black, # majority-Hispanic) districts, by share of voting-age population."""
            K = int(parts.max()) + 1
            V, B, H = (np.bincount(parts, x, K) for x in (vv, bv, hv))
            live = V > 0
            return int((B[live] / V[live] > 0.5).sum()), int((H[live] / V[live] > 0.5).sum())

        need_b, need_h = vra_counts(e_parts)                    # the enacted plan's own counts
        s_b, s_h = vra_counts(parts_array(last))                # the starting plan's counts
        relaxed = s_b < need_b or s_h < need_h
        if relaxed and a.restore_floor:
            def deficit(parts):
                """How far the (need)th most-minority districts are from a 50% majority, summed over both groups."""
                K = int(parts.max()) + 1
                V, B, H = (np.bincount(parts, x, K) for x in (vv, bv, hv))
                live = V > 0
                tot = 0.0
                for X, need in ((B, need_b), (H, need_h)):
                    if need > 0:
                        sh = np.sort(X[live] / V[live])[::-1][:need]
                        tot += float(np.clip(0.5001 - sh, 0, None).sum())
                return tot

            log(f"VRA: starting plan has {s_b} Black / {s_h} Hispanic majority districts, fewer than the enacted "
                f"{need_b} / {need_h}; restoring the floor first (up to {a.restore_min:.0f} min)")
            t_r = time.time()
            r_score = lambda part: 100.0 * deficit(parts_array(part)) + float(obj_fn(part))
            r_best, r_best_score, r_cur, r_steps, r_retries, got = last, r_score(last), last, 0, 0, None
            while got is None and time.time() - t_r < a.restore_min * 60 and r_retries <= 10:
                r_opt = SingleMetricOptimizer(proposal, cons, r_cur, r_score, maximize=False,
                                              rng=a.seed + 7 + 1000 * r_retries)
                try:
                    for part in r_opt.short_bursts(a.burst_len, BIG):
                        r_steps += 1
                        c = vra_counts(parts_array(part))
                        if c[0] >= need_b and c[1] >= need_h:
                            got = part
                            break
                        if r_steps % 200 == 0:
                            if r_opt.best_score is not None and float(r_opt.best_score) < r_best_score:
                                r_best, r_best_score = r_opt.best_part, float(r_opt.best_score)
                            if time.time() - t_r > a.restore_min * 60:
                                break
                except RuntimeError as e:
                    if r_opt.best_score is not None and float(r_opt.best_score) < r_best_score:
                        r_best, r_best_score = r_opt.best_part, float(r_opt.best_score)
                    r_retries += 1
                    r_cur = r_best
                    log(f"  restore: ReCom failure ({str(e)[:60]}); restart #{r_retries}")
            res["restore_floor"] = {"before": [s_b, s_h], "needed": [need_b, need_h], "steps": r_steps,
                                    "minutes": round((time.time() - t_r) / 60, 1), "ok": got is not None}
            if got is not None:
                last = got
                res["start_obj_before_restore"] = res["start_obj"]
                res["start_obj"] = float(obj_fn(last))
                s_b, s_h = vra_counts(parts_array(last))
                relaxed = False
                log(f"VRA: floor restored after {r_steps:,} steps ({res['restore_floor']['minutes']} min): "
                    f"{s_b} Black / {s_h} Hispanic; obj {res['start_obj_before_restore']:.4f} -> {res['start_obj']:.4f}")
            else:
                log(f"VRA: could not restore the floor in {a.restore_min:.0f} min; falling back to the start's counts")
        if relaxed:
            log(f"VRA: starting plan has {s_b} Black / {s_h} Hispanic majority districts, fewer than the enacted "
                f"{need_b} / {need_h}; floor lowered to the start's counts")
            need_b, need_h = min(need_b, s_b), min(need_h, s_h)
        cons = list(cons) + [lambda part: all(c >= n for c, n in zip(vra_counts(parts_array(part)), (need_b, need_h)))]
        vra_info = {"enacted": list(vra_counts(e_parts)), "start": [s_b, s_h], "floor": [need_b, need_h],
                    "relaxed": bool(relaxed)}
        log(f"VRA floor: at least {need_b} majority-Black and {need_h} majority-Hispanic districts "
            f"(enacted {vra_info['enacted']}, start {vra_info['start']})")

    # ---- optimizer: time-boxed, or in rounds until a round gains < min_gain, or until a stall ----
    t0 = time.time()
    trace, nsteps, rounds, retries, stop_reason = [], 0, [], 0, "unknown"
    round_start_best = float(obj_fn(last))  # best_score is unset until the first step
    best, best_score, cur_start, last_logged = last, round_start_best, last, round_start_best
    cap = (a.max_opt_min if (a.round_bursts or a.stall_steps) else a.opt_min) * 60
    while True:
        opt = SingleMetricOptimizer(proposal, cons, cur_start, obj_fn, maximize=False,
                                    rng=a.seed + 2 + 1000 * retries)
        try:
            for i, part in enumerate(opt.short_bursts(a.burst_len, BIG)):
                nsteps += 1
                if i % a.burst_len == 0:
                    if float(opt.best_score) < best_score:
                        best, best_score = opt.best_part, float(opt.best_score)
                        if best_score < last_logged * (1 - 0.0005):
                            log(f"  step {nsteps:,}: best {best_score:.4f}")
                            last_logged = best_score
                    trace.append(best_score)
                    b = len(trace)
                    if a.stall_steps:
                        W = max(1, a.stall_steps // a.burst_len)
                        if len(trace) > W and nsteps >= a.min_steps:
                            past = trace[-W - 1]
                            if (past - best_score) / past < a.stall_gain:
                                stop_reason = "stall"
                                break
                    if a.round_bursts and b % a.round_bursts == 0:
                        gain = (round_start_best - best_score) / round_start_best
                        rounds.append({"round": b // a.round_bursts, "best": best_score, "gain": gain,
                                       "minutes": round((time.time() - t0) / 60, 1)})
                        log(f"  round {b // a.round_bursts}: best {best_score:.4f}, gain {gain*100:.2f}%")
                        if gain < a.min_gain:
                            stop_reason = "round gain"
                            break
                        round_start_best = best_score
                    if time.time() - t0 > cap:
                        stop_reason = "time cap"
                        break
            break
        except RuntimeError as e:   # ReCom could not split some district pair: restart from the best plan
            if opt.best_score is not None and float(opt.best_score) < best_score:
                best, best_score = opt.best_part, float(opt.best_score)
            retries += 1
            log(f"  ReCom failure ({str(e)[:70]}); restart #{retries} from best plan")
            if retries > 25:
                raise
            cur_start = best
    res["opt_retries"] = retries
    if vra_info:
        vra_info["optimized"] = list(vra_counts(parts_array(best)))
        res["vra"] = vra_info
        log(f"VRA: optimized plan has {vra_info['optimized'][0]} Black / {vra_info['optimized'][1]} Hispanic majority districts")
    res["stop_reason"] = stop_reason
    log(f"stopped: {stop_reason} after {nsteps:,} steps, {(time.time()-t0)/60:.0f} min; best {best_score:.4f}")
    res["optimized"] = summarize(parts_array(best))
    res["opt_trace"] = trace
    res["opt_rounds"] = rounds
    res["seed"] = a.seed
    res["opt_steps"] = nsteps
    res["opt_seconds"] = round(time.time() - t0, 1)
    log("OPTIMIZED", json.dumps({x: v for x, v in res["optimized"].items() if x != "d_share_by_district"}),
        f"({nsteps} steps)")
    asg = {n: int(best.assignment[n]) for n in nodes}
    return res, asg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--eps", type=float, default=0.005)
    ap.add_argument("--burn", type=int, default=100)
    ap.add_argument("--thin", type=int, default=5)
    ap.add_argument("--burst-len", type=int, default=25)
    ap.add_argument("--ens-min", type=float, default=8.0)
    ap.add_argument("--opt-min", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--start", default="random", choices=["random", "enacted", "best", "warm"])
    ap.add_argument("--warm-file", default="", help="with --start best: pickle of {precinct: district}")
    ap.add_argument("--adjacency", default="rook", choices=["rook", "queen"],
                    help="rook = districts must connect through shared boundary, not just a corner")
    ap.add_argument("--vra", action="store_true", help="keep at least the enacted count of majority-Black and majority-Hispanic districts")
    ap.add_argument("--bridge-warm", action="store_true",
                    help="with --start warm: connect the saved plan's separated pieces with nearest-pair bridge edges "
                         "instead of reassigning them (use to continue a plan that already relies on such bridges)")
    ap.add_argument("--land-only", action="store_true",
                    help="water precincts (no residents, mostly off the shoreline) cannot connect land: districts "
                         "must be contiguous over populated precincts, except across the sanctioned island bridges")
    ap.add_argument("--shoreline", default=r"C:\gerry-compute\shoreline\cb_2024_us_state_500k.shp",
                    help="Census cartographic state boundaries (shoreline-clipped), used by --land-only")
    ap.add_argument("--restore-floor", action="store_true",
                    help="with --vra: if the start plan has fewer majority-minority districts than the enacted plan, "
                         "first optimize toward restoring them (instead of lowering the floor)")
    ap.add_argument("--restore-min", type=float, default=40.0, help="time cap for --restore-floor, minutes")
    ap.add_argument("--race-dir", default=r"C:\gerry-compute\race", help="folder with <st>.csv from add_race.py")
    ap.add_argument("--stall-steps", type=int, default=0, help="stall window in steps (0 = off)")
    ap.add_argument("--stall-gain", type=float, default=0.001, help="stall if best improved by less than this")
    ap.add_argument("--min-steps", type=int, default=0, help="never declare a stall before this many steps")
    ap.add_argument("--tag", default="", help="suffix for output file names, e.g. _s11")
    ap.add_argument("--round-bursts", type=int, default=0, help="if >0, optimize in rounds of this many bursts")
    ap.add_argument("--min-gain", type=float, default=0.01, help="stop when a round improves the best score by less")
    ap.add_argument("--max-opt-min", type=float, default=120.0, help="safety cap on optimizer minutes (round mode)")
    a = ap.parse_args()
    ab = a.state.lower()
    t_all = time.time()
    try:
        meta = prep(ab)
        res, asg = optimize(ab, meta, a)
        res["total_seconds"] = round(time.time() - t_all, 1)
        (OUT / f"{ab}{a.tag}.json").write_text(json.dumps(res))
        if asg is not None:
            with open(OUT / f"{ab}{a.tag}_best.pkl", "wb") as fh:
                pickle.dump(asg, fh)
        log(f"{ab} done in {res['total_seconds']:.0f}s")
    except Exception:
        err = traceback.format_exc()
        log(err)
        (OUT / f"{ab}{a.tag}.error.txt").write_text(err)
        sys.exit(1)
