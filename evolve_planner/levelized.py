"""Levelized cost of electricity (LCOE) and of hydrogen (LCOH) for a solved design.

The island produces two products from shared assets, so the annual cost has to be split between them.
The split used here (energy allocation) is transparent and standard:

* costs that serve only hydrogen (electrolysers, water treatment, compressors, hydrogen tanks, the
  hydrogen pipeline and, with turbine-level electrolysis, the floater integration and in-field lines) go to
  hydrogen;
* fuel cells turn hydrogen back into power for the grid, and the TSO fee is paid on power injected into
  the grid, so both go to electricity;
* every shared cost (wind, PV, export cable, platform, batteries, variable O&M) is split in
  proportion to the electricity each product uses: power delivered to the grid versus power fed to
  the electrolysers.

LCOE = electricity share of the annual cost / MWh delivered to the grid.
LCOH = hydrogen share of the annual cost / kg of hydrogen delivered.
Annual cost = annualised investment (capital recovery factor at the discount rate over each lifetime)
+ fixed O&M + variable O&M + TSO fee. Revenues and shortfall penalties are not part of it.
"""
from __future__ import annotations

import math

H2_ONLY = ("Electrolyser (island)", "Electrolyser (onshore)", "Water treatment", "Compressors", "H2 pipeline",
           "H2 tanks", "Turbine-level integration", "In-field H2 pipelines")
POWER_ONLY = ("Fuel cells", "TSO fee")   # the TSO fee is paid on power injected into the grid


def levelized(f: dict, lhv_kwh_kg: float = 33.3) -> dict:
    grid = float(f.get("grid_mwh") or 0.0)
    h2 = float(f.get("h2_kg") or 0.0)
    e_h2 = float(f.get("sum_p_we") or 0.0) + float(f.get("sum_p_pe") or 0.0)
    gen = float(f.get("gen_wind_mwh") or 0.0) + float(f.get("gen_pv_mwh") or 0.0)
    curt = float(f.get("curt_mwh") or 0.0)
    if h2 <= 1.0:
        share_h = 0.0                       # no hydrogen product: everything serves electricity
    elif grid <= 1.0:
        share_h = 1.0                       # no electricity product
    else:
        share_h = e_h2 / (e_h2 + grid) if (e_h2 + grid) > 0 else 0.0
    rows = []
    for name, cost in f.get("cost_parts", {}).items():
        cost = float(cost)
        if abs(cost) < 1.0:
            continue
        if name in H2_ONLY and h2 > 1.0:
            to_e, to_h, rule = 0.0, cost, "hydrogen only"
        elif name in POWER_ONLY and grid > 1.0:
            to_e, to_h, rule = cost, 0.0, "electricity only"
        else:
            to_e, to_h, rule = cost * (1 - share_h), cost * share_h, "shared by energy"
        rows.append({"component": name, "annual_cost": cost, "to_electricity": to_e, "to_hydrogen": to_h,
                     "rule": rule,
                     "eur_per_mwh": to_e / grid if grid > 1 else 0.0,
                     "eur_per_kg": to_h / h2 if h2 > 1 else 0.0})
    cost_e = sum(r["to_electricity"] for r in rows)
    cost_h = sum(r["to_hydrogen"] for r in rows)
    lcoe = cost_e / grid if grid > 1 else math.nan
    lcoh = cost_h / h2 if h2 > 1 else math.nan
    gen_cost = float(f.get("cost_parts", {}).get("Offshore wind", 0.0)) + \
        float(f.get("cost_parts", {}).get("Floating PV", 0.0))
    return {
        "lcoe": lcoe, "lcoh": lcoh,
        "lcoh_eur_mwh": lcoh * 1000.0 / lhv_kwh_kg if h2 > 1 else math.nan,
        "share_h2": share_h, "cost_to_electricity": cost_e, "cost_to_hydrogen": cost_h,
        "electricity_to_h2_mwh": e_h2, "grid_mwh": grid, "h2_kg": h2,
        "lcoe_generation": gen_cost / gen if gen > 1 else math.nan,
        "lcoe_generation_used": gen_cost / (gen - curt) if gen - curt > 1 else math.nan,
        "rows": rows,
    }
