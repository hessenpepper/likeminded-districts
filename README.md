# Like-Minded Districts

An interactive map comparing the **enacted U.S. congressional districts** with **computer-optimized districts** that group
"like-minded" precincts. Use the **year switch** to choose between two elections: **2020** (optimized from scratch on
VEST precincts) and **2024** (the 2020 optimized maps, adjusted on New York Times 2024 precincts). Zoom in for
precinct-level detail.

**Live map:** see the repository's GitHub Pages site (`index.html`).

## What "like-minded" means here

For each district, `p_i` is the Democratic share of the two-party presidential vote in precinct *i*, `P` is the district's
population-weighted share, and `w_i` is the precinct's 2020 census population (non-voters are assumed to vote like the
voters in their own precinct). The district's **dissimilarity** is

```
D = sum_i w_i * |p_i - P| / (2 * W * P * (1 - P))        W = sum_i w_i
```

`D = 0` means every precinct matches the district as a whole; larger values mean the district stitches together
precincts that lean very differently. A state's score is the population-weighted mean over its districts.

## How the optimized plans were made

* **2020 maps:** units are 2020 VEST precincts (175k+ nationwide), joined to 2020 census block populations (PL 94-171).
  This is the "first generation" map: it is built from scratch (random starting maps are among the starting points),
  because the enacted maps are themselves products of line-drawing. For every state the plan with the lowest
  dissimilarity that satisfies the rules below was used, whatever its starting point.
* **2024 maps:** units are the New York Times 2024 precinct results and boundaries. The final 2020 optimized plan is carried
  onto the 2024 precincts through census blocks, rebalanced to equal population, and re-optimized from there
  ("adjusted"), so later maps change little from the previous one. No 2024 map is drawn from scratch. Alaska has no usable
  2024 precinct data and is not shown for 2024.
* Search: [GerryChain](https://github.com/mggg/GerryChain) ReCom Markov chain with a short-burst optimizer, keeping every
  district contiguous and within ±0.5% of equal population, minimizing the dissimilarity above.
* **Contiguity is rook:** a district must be connected across shared boundaries, not only at a corner. Islands and
  other water crossings that the enacted map itself uses are connected by nearest-pair links. Large water polygons
  (zero residents, mostly off the Census shoreline, such as Lake Michigan and Lake Erie) are leaves in the graph, so a
  district cannot use open water as a corridor (`--land-only`). Precinct and district shapes are clipped to the Census
  cartographic shoreline for display only; attributes are unchanged.
* **Voting Rights Act floor:** every optimized plan keeps at least as many majority-Black and as many majority-Hispanic
  districts (more than 50% of voting-age population, 2020 census) as the enacted plan in that state. The rule is a hard
  constraint inside the search, so plans that fall below it are never accepted. This is a count-based check, not a legal
  VRA analysis: it does not test whether minority voters can elect candidates of their choice or racially polarized
  voting. **Known exception (2024):** California's carried 2020 plan has 16 majority-Hispanic districts on the 2024
  precincts against 18 in the enacted plan, and the 2024 adjusted plan keeps that count of 16.
* Searches are time-boxed by CPU time or stopped on a stall rule (less than 0.1% gain over 20,000 steps). Some states hit
  the time cap while still improving slowly, so longer runs could do a bit better; seed-to-seed spread in testing was
  about 1.5% of the score.

## Caveats, please read

* **Not proposals and not legal maps.** The optimized plans keep the enacted number of majority-Black and
  majority-Hispanic districts but are not a Voting Rights Act analysis, and they ignore county and city boundaries,
  communities of interest and compactness rules. District numbers in optimized plans are arbitrary.
* **Enacted plans are approximations.** The "enacted" layer is the 2024-era 119th-Congress map rebuilt from whole 2020
  precincts (each precinct goes to the district holding most of its residents), so district populations are roughly
  ±1% from equal and a few split precincts are reassigned. Several states have redrawn maps since 2024; those changes are
  not reflected.
* **One election per year.** Each year uses that year's presidential race (2020: Biden/Trump; 2024: Harris/Trump).
  "Biden-won" and "Harris-won" counts are not House results.
* Population-weighting assumes non-voters (including children and non-citizens) vote like their precinct, a strong assumption.
* Dissimilarity rewards grouping similar voters and is not a measure of fairness. It says nothing about competitiveness,
  representation or legality.

## Data sources and credit

* **2020 precinct results and boundaries:** Voting and Election Science Team (VEST), *2020 Precinct-Level Election Results*,
  Harvard Dataverse, <https://doi.org/10.7910/DVN/K7760H>, licensed **CC BY 4.0**. The vector tiles in `data/2020/` are
  derived from it and carry the same attribution requirement.
* **2024 precinct results and boundaries:** *2024 Precinct-Level Election Results*, The New York Times
  (<https://www.nytimes.com/interactive/2025/us/elections/2024-election-precinct-map.html>), used under the NYT
  Computational Use of Data Agreement, **for non-commercial use only**. Credit is required in any public display, and
  the terms must be passed on to recipients: see `data/2024/LICENSE-NYT.txt` and `data/2024/NYT-README.md`.
* **Population and districts:** U.S. Census Bureau, 2020 PL 94-171 redistricting data, TIGER/Line 2024 congressional districts
  and the 2024 cartographic state boundaries (shoreline clipping), all public domain.
* **Basemap:** [OpenFreeMap](https://openfreemap.org), © OpenMapTiles, data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
* **Libraries:** [MapLibre GL JS](https://maplibre.org), [PMTiles](https://github.com/protomaps/PMTiles).

## Files

* `index.html`: the whole viewer (static; loads tiles with HTTP range requests).
  Districts can be shaded by Democratic share or by dissimilarity (one fixed scale for all states: 0.10 to 0.50+).
  Zoomed out, each state is shaded and labeled by the average dissimilarity of its districts (population-weighted, same scale);
  the side panel shows seat shares as percentages next to Biden's share of the two-party vote, nationally or for a chosen state.
* `data/2020/` and `data/2024/`: one folder per year, loaded on demand by the year switch. Each has
  `states.geojson` (state outlines with seat counts, dissimilarity and vote share), `states.json`, `stats.json`
  (the state list and headline numbers), `districts.pmtiles` and `precincts-1..4.pmtiles` (the precinct tiles are split
  into four files by state group). `data/2024/` also carries the NYT license and data notes.
* `code/`: the scripts that produced the results (`pipeline.py` per-state download and optimization with rook contiguity,
  the VRA floor and warm starts; `driver*.py` and `rook_orchestrator.py` batch runners; `build_tiles.py` tile builder;
  `state_votes.py` / `make_states_layer.py` state-level numbers; `aggregate.py` cross-state comparison).

## License

* **Code** (`index.html` and everything in `code/`): [MIT License](LICENSE).
* **Data, 2020** (`data/2020/`): derived from VEST precinct data, so it is **CC BY 4.0**; credit VEST and the Census
  Bureau as listed above.
* **Data, 2024** (`data/2024/`): derived from New York Times precinct data, so it is available **for non-commercial use
  only** under the NYT Computational Use of Data Agreement (`data/2024/LICENSE-NYT.txt`); credit the New York Times as
  listed above and pass these terms on. It is not CC BY.
* The MIT license covers the code only, not the data.
