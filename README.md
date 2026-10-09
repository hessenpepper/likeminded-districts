# Like-Minded Districts

An interactive map comparing the **enacted U.S. congressional districts** with **computer-optimized districts** that group
"like-minded" precincts, using 2020 presidential results. Zoom in for precinct-level detail.

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

* Units: 2020 VEST precincts (175k+ nationwide), joined to 2020 census block populations (PL 94-171).
* Search: [GerryChain](https://github.com/mggg/GerryChain) ReCom Markov chain with a short-burst optimizer, keeping every
  district contiguous and within ±0.5% of equal population, minimizing the dissimilarity above.
* The map shows the lowest-dissimilarity plan found for each state across several runs (random starts, different seeds,
  and starts from the enacted map). Searches were time-boxed or stopped on a stall rule, so a longer search could do a bit
  better; seed-to-seed spread in testing was about 1.5% of the score.
* "Neutral" comparison ensembles (population + contiguity only) were also run per state and are discussed in the project
  notes, not shown on the map.

## Caveats, please read

* **Not proposals and not legal maps.** The optimized plans ignore the Voting Rights Act, county and city boundaries,
  communities of interest and compactness rules. District numbers in optimized plans are arbitrary.
* **Enacted plans are approximations.** The "enacted" layer is the 2024-era 119th-Congress map rebuilt from whole 2020
  precincts (each precinct goes to the district holding most of its residents), so district populations are roughly
  ±1% from equal and a few split precincts are reassigned. Several states have redrawn maps since 2024; those changes are
  not reflected.
* **One election.** Everything uses the 2020 presidential race. "Biden-won" counts are not House results.
* Population-weighting assumes non-voters (including children and non-citizens) vote like their precinct, a strong assumption.
* Dissimilarity rewards grouping similar voters and is not a measure of fairness. It says nothing about competitiveness,
  representation or legality.

## Data sources and credit

* **Precinct results and boundaries:** Voting and Election Science Team (VEST), *2020 Precinct-Level Election Results*,
  Harvard Dataverse, <https://doi.org/10.7910/DVN/K7760H>, licensed **CC BY 4.0**. The vector tiles in `data/` are derived
  from it and carry the same attribution requirement.
* **Population and districts:** U.S. Census Bureau, 2020 PL 94-171 redistricting data and TIGER/Line 2024 congressional districts (public domain).
* **Basemap:** [OpenFreeMap](https://openfreemap.org), © OpenMapTiles, data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
* **Libraries:** [MapLibre GL JS](https://maplibre.org), [PMTiles](https://github.com/protomaps/PMTiles).

## Files

* `index.html`: the whole viewer (static; loads tiles with HTTP range requests).
* `data/districts.pmtiles`, `data/precincts.pmtiles`: vector tiles. `data/states.json`, `data/stats.json`: the state list and headline numbers.
* `code/`: the scripts that produced the results (`pipeline.py` per-state download and optimization, `driver*.py` batch
  runners, `build_tiles.py` tile builder, `aggregate.py` cross-state comparison).

## License

* **Code** (`index.html` and everything in `code/`): [MIT License](LICENSE).
* **Data** (`data/*.pmtiles` and the JSON files): derived from VEST precinct data, so they are **CC BY 4.0**; credit VEST
  and the Census Bureau as listed above. The MIT license does not cover the data.
