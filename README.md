# EVOLVE-Floating-Shore (EVOLVE Planner)

Lowest-cost design of a floating (or bottom-fixed) offshore energy island and its onshore plant, for
electricity, hydrogen or both, on one year of hourly data reduced with topological data analysis (TDA).

**What it sizes:** offshore wind, floating PV, electrolysers (island and onshore), desalination, compressors,
fuel cells, batteries, hydrogen tanks, the export link (AC voltage, conductor, reactive compensation and circuits, or HVDC, chosen exactly) and the
hydrogen pipeline (new or repurposed classes).
**What it delivers:** capacities, annualised costs, revenues, the levelized cost of electricity (LCOE) and of
hydrogen (LCOH) with a component breakdown, the 8,760-hour operation, and three drawings generated from every
design:

- **Route section** – side view from the island down the export cable and pipeline, through the landfall,
  to the onshore plant (only what was built is drawn).
- **Island** – isometric view of the platform with the sized equipment laid out on the deck to scale, and
  the deck area used.
- **Connection atlas** – a chart of the site drawn from the real coastline (1 km GLOBE land mask in
  `assets/landmask_120.npz`), with the wind-farm zone, sea routes around islands and headlands, the grid
  and hydrogen points, waterlines, graticule, scale bar and legend.

## Handbook

`docs/EVOLVE_Planner_handbook.pdf` documents the full optimisation model, the TDA reduction, how to use the app,
how to prepare and import data, and a worked Belle-Île example.

## Connections to existing infrastructure

The island can export power through its own cable to the onshore grid point, or through a short cable to a
nearby offshore substation or cable with spare capacity (MW), a voltage (kV) and an access fee; hydrogen can
leave through its own pipeline or tie into a nearby pipeline with spare capacity (kg/h) and an operating
pressure. With "let the model choose" every combination is sized on the reduced year and the cheapest is
checked on the full year. The island's own link is chosen from 32 AC options (66, 132, 220 or 275 kV;
500–1000 mm² copper; shunt reactors at both ends or also mid-route) and an HVDC option; the user can restrict
it to one AC voltage or to HVDC.

## Route lengths and connection points

The island, grid point, hydrogen offtake, hub and tie-in are coordinates you enter; the app does not look up
substations or pipelines in a database. From those coordinates it measures each route in one of three ways
(Site step, "How route lengths are found"):

1. **Sea route** (default): shortest path through the sea on the bundled 1 km coastline, around islands and
   headlands, to the coast nearest the onshore point, plus a straight onshore leg. Large areas are coarsened so a
   route across a whole sea takes about a second.
2. **Straight line × routing factor** (1.1–1.3 typical).
3. **Entered length**: a cable or pipeline length from a route study replaces both.

The Site step shows the length used and how it was found, the nearest coast to the island (with buttons to put
the grid point or offtake there as a first guess), and links to OpenInfraMap, EMODnet Human Activities and the
ENTSO-E grid map to find real substations, cables and pipelines. The usable AC ratings, the reactive
compensation, the link costs and losses follow from the length; the optimiser then chooses AC or HVDC.

## Interactive map

Before a run the map shows what the model will assume: the island and sea area, every candidate link with the
length it measures, and hub or tie-in points. After a run it shows what was built: turbines in the sea area, the
export cable and pipeline with widths proportional to MW and peak kg/h, voltage and circuits, and the existing
links of a hub or pipeline, with tooltips. The coastline is drawn from the bundled mask, so the map reads even if
the basemap cannot load.

## LCOE and LCOH

Annual cost (annualised investment + O&M + fees) is split between the two products: hydrogen-only equipment
to hydrogen, fuel cells to electricity, and shared assets (wind, PV, cable, platform, batteries, fees) in
proportion to the electricity each product uses (power to the grid vs power to the electrolysers).
LCOE = electricity share / MWh delivered; LCOH = hydrogen share / kg delivered.

## How a run works

1. **Reduce.** The cumulative surplus-and-deficit curve of each hourly series is analysed with 0-dimensional
   persistent homology. Persistent extrema (deep lulls, long surpluses) become fixed cuts; neighbouring hours are
   merged where the curve stays within a chord error. Default: 1,460 variable-length blocks.
2. **Size.** A Pyomo capacity-expansion model is solved on the blocks, with storage tracked across the whole
   year (min/max-bounded state of charge). The export link is one option of the catalogue in whole circuits (AC) or
   2 GW units (HVDC), and the pipeline one of eight sizes (4 to 36 inch, or a repurposed line). An exact branch
   and bound finds the cheapest combination: LPs with an ideal cable bound each pipe choice, tangents of the
   convex cost-versus-capacity curve bound every (option, circuits) leaf, and leaves are solved in order of their
   bound (warm-started dual simplex) until no bound can beat the best design.
3. **Check.** The design is operated on all 8,760 hours. Three group factors (generation, conversion and export,
   storage) between 1 and 3 may enlarge the design; one LP chooses them and the hourly operation at the lowest net
   cost, with undelivered energy heavily penalised and reported.

In the Step 2 tests (Belle-Île, 2019 and 2024, three cases) the cost stayed within 0.3 % of the full-year
optimum and every contract was delivered.

## Run it on your computer

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

GLPK is optional (`packages.txt` installs it on Streamlit Cloud; locally `apt install glpk-utils` or
`conda install glpk`). HiGHS is installed with `highspy` and is the default.

## Inputs

Everything can be typed in the app (every number has − and + buttons; the Technologies step lists every
cost and performance input, and the Run step lists every input of the run with what the model derives) or loaded from one Excel workbook (sidebar, "Open an inputs workbook").
The workbook has an `Inputs` sheet (one row per parameter, edit the `value` column) and a `TimeSeries` sheet
with one calendar year: `wind_cf`, `pv_cf` (0–1), `price_eur_mwh`, `elec_demand_mw`, `h2_demand_kgh` (the last
two only for profile delivery, in MW and kg/h per hour; `examples/belle_ile/EVOLVE_hourly_demand_profiles_2019.xlsx` is a synthetic example). Hourly files have 8,760 rows; 30, 15, 10 and 5-minute files are averaged to
hours, and a leap year loses 29 February.

`examples/EVOLVE_data_guide.xlsx` (also downloadable from the app's sidebar) lists every series and input,
the file format and resolution, and where to get the data.

Without files, the app can download wind and solar capacity factors from ERA5 (Open-Meteo archive API) and
day-ahead prices from Energy-Charts (Fraunhofer ISE) for the island coordinates.

## Costs

AC cables use ABB XLPE data for capacitance and current rating (so the usable rating falls with length),
NREL ORBIT supply prices plus installation calibrated to ACER's AC submarine-cable median, transformer and
shunt-reactor costs, and load and no-load losses. HVDC uses the cost function that Vrana & Härtel (EPSR 2018)
fitted to 21 VSC projects, checked against recent projects and TenneT's 2 GW programme. No distance rule decides
between AC and HVDC. Hydrogen pipelines and compressors use the ACER unit investment cost indicators of 24 April
2026 (medians), with a 1.7 subsea factor (European Hydrogen Backbone) and pipe capacities from a 20 m/s design
velocity (Danish Energy Agency) and the pressure drop. Technologies that ACER does not cover (wind, PV, electrolysers, fuel
cells, batteries, tanks) keep the v9 values and are flagged "placeholder" until Step 3. Every input
shows its source in the app, in the inputs workbook and in the data guide; the handbook (`docs/`) has a chapter
"Cost model" with every formula, value, source and the comparison with ACER.

Changes in 0.9.1: the TSO grid fee is charged per MW of capacity injected into the existing grid (the largest
hourly injection, by the island's cable or an onshore fuel cell), not per MW of cable, so power used onshore by
the electrolysers pays no fee; with a hub the hub access fee on the cable replaces it. The battery power cost is
100 kEUR/MW (power conversion and grid interface): with 160 EUR/kWh for energy a 4-hour battery costs
185 EUR/kWh, close to BNEF's 2025 European turnkey average (the v9 value of 5.34 MEUR/MW priced it about nine
times above the market).

Changes in 0.10.0 (island platform): the platform cost follows the DNV GL (2018) model as used by Bouma (2023),
C = k_esc k_inst [f_E c_E S_cable + f_H c_H (S_ez + w_c S_comp + w_f S_fc + w_b S_bat)] + C_0, with
c_E = 84.651 and c_H = 139.281 kEUR/MW and k_inst = 1.5 (1.15 installation x 1.30 engineering and
contingency). The single "floating factor" of 2 is replaced by factors built from the substructure share:
bottom-fixed (A) f = (1 - s) + s (d/30 m) (jacket share s = 0.28 process, 0.22 electrical); floating central (B)
f = 1.1 (1 - s) + 3 s, i.e. about 1.63 and 1.52, with 3 %/yr platform O&M and a 0.5 km dynamic export section at
+75 % (warning above 66 kV, optional restriction). Turbine-level electrolysis (C, Dolphyn type) has no central
platform: it pays an integration cost of 0.5 c_H per MW, a 1.3 scale factor on the electrolyser, 1 km of in-field
pipeline per turbine at 0.55 MEUR/km plus a 50 kEUR manifold, saves 145 kEUR/MW of array cable and gains 0.5 % in
hydrogen yield. Floating wind CAPEX is 3.429 MEUR/MW (1.35 x bottom-fixed, Lanni et al. 2025 and NREL 2024)
instead of the bottom-fixed value. Workbooks with the old key platform_float_factor still open; the key is ignored
with a note. The handbook chapter "Cost model" gives every formula, value and source.

## Repository layout

```
app.py                      Streamlit app (wizard: Site, Use case, Data, Technologies, Run, Results)
evolve_planner/
  params.py                 every input: label, unit, default, help; derived quantities
  tda.py                    topology-preserving chronological aggregation (TPCA)
  timestructure.py          variable-length time steps
  model.py                  Pyomo capacity-expansion model
  workflow.py               reduce -> size -> check on the full year
  weather.py                uploads, ERA5 and price downloads, CF conversion
  workbook.py, report.py    input and results workbooks
  geo.py                    coastline, sea routes, nearest shore (1 km land mask)
ui/                         theme, Plotly charts, interactive map (livemap.py), drawings (atlas, isometric, section)
assets/landmask_120.npz     1 km land/water grid for the atlas (GLOBE via global-land-mask, bit-packed)
examples/                   data guide, blank inputs workbook; belle_ile/ has 2019 and 2024 series and presets
tests/                      TDA properties and an end-to-end check
```

## Tests

```bash
pip install pytest
pytest -q                 # about one minute
```

## Hosting

Streamlit Community Cloud: connect the GitHub repository, main file `app.py`, Python 3.12. The free tier
has limited memory; the app runs one solve at a time and queues the next. For heavier use, the `Dockerfile`
runs the same app on any server: `docker build -t evolve-planner . && docker run -p 8501:8501 evolve-planner`.
