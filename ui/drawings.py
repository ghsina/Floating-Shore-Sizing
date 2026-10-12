"""Inputs for the three illustrations, from the user's inputs (preview) or from a solved design."""
from __future__ import annotations

import math

from evolve_planner import params as P

from .atlas import atlas_page
from .isometric import island_iso_page
from .section import section_page

AREA_KEYS = ("area_elec_m2_mw", "area_comp_m2_mw", "area_fc_m2_mw", "area_batt_m2_mwh", "area_tank_m2_kg",
             "deck_area_max_m2")
CAPS = ("C_wt", "C_pv", "C_ez_off", "C_ez_on", "C_cmp_off", "C_cmp_on", "C_fc_off", "C_fc_on", "C_cab", "E_bat_off",
        "P_bat_off", "E_bat_on", "P_bat_on", "E_tank_off", "E_tank_on")


def _derived(user, final=None):
    try:
        ec = (final or {}).get("elec_connection_used")
        hc = (final or {}).get("h2_connection_used")
        return P.derive(user, elec=ec, h2=hc)
    except Exception:  # noqa: BLE001
        return None


def preview_design(user: dict) -> dict:
    """Illustrative sizes for every technology the user allows (no model run yet)."""
    on = lambda k: bool(user.get(k))
    wind = min(user.get("sea_area_km2", 40) * user.get("wind_density_mw_km2", 6.3), 600)
    h2_case = user.get("use_case") != "Power-led"
    d = dict(C_wt=wind, C_pv=0.15 * wind if on("enable_pv") else 0,
             C_ez_off=0.2 * wind if (on("enable_ez_off") and h2_case) else 0,
             C_ez_on=0.15 * wind if (on("enable_ez_on") and h2_case) else 0,
             C_fc_off=0.04 * wind if on("enable_fc_off") else 0, C_fc_on=0.06 * wind if on("enable_fc_on") else 0,
             E_bat_off=0.2 * wind if on("enable_batt_off") else 0, P_bat_off=0.05 * wind if on("enable_batt_off") else 0,
             E_bat_on=0.4 * wind if on("enable_batt_on") else 0, P_bat_on=0.1 * wind if on("enable_batt_on") else 0,
             E_tank_off=60 * wind if (on("enable_tank_off") and h2_case) else 0,
             E_tank_on=400 * wind if (on("enable_tank_on") and h2_case) else 0,
             C_cab=0.9 * wind if on("enable_cable") else 0)
    d["C_cmp_off"] = 0.02 * d["C_ez_off"] if on("enable_pipe") else 0
    d["C_cmp_on"] = 0.01 * d["C_ez_on"]
    d["pipe"] = "new_12in" if (on("enable_pipe") and h2_case) else "none"
    return d


def _common(user, der, design, final=None):
    tmw = float(user.get("turbine_mw") or 15)
    return dict(
        floating=der["floating"] if der else True, depth_m=float(user.get("avg_water_depth_m") or 0),
        link_mode=(final or {}).get("link_mode") or (der or {}).get("link_mode", "HVAC"),
        grid_km=(der or {}).get("grid_distance_km", 0.0), pipe_km=(der or {}).get("pipe_distance_km", 0.0),
        n_turbines=int(math.ceil(design.get("C_wt", 0) / tmw)) if design.get("C_wt", 0) > 0.5 else 0,
        **{k: float(design.get(k) or 0) for k in CAPS}, pipe=design.get("pipe", "none"),
        **{k: float(user.get(k) or 0) for k in AREA_KEYS},
        grid_gwh=(final or {}).get("grid_mwh", 0) / 1000, h2_t=(final or {}).get("h2_kg", 0) / 1000,
        volt=(final or {}).get("export_voltage_used") or (der or {}).get("cable_preview"),
        circuits=(int((final or {}).get("n_circuits") or 0) if (final or {}).get("n_circuits") is not None else
                  (math.ceil(float(design.get("C_cab") or 0) / max((der or {}).get("circuit_rating_mw", 1e9), 1e-9) - 1e-6)
                   if float(design.get("C_cab") or 0) > 1e-3 else 0)),
        hub_name=(user.get("hub_name") if (der or {}).get("elec_connection_used") == "hub" else None),
        tiein_name=(user.get("tiein_name") if (der or {}).get("h2_connection_used") == "tiein" else None))


def atlas_html(user, design=None, final=None, title="Connection atlas", animate=True):
    der = _derived(user, final)
    design = design or preview_design(user)
    c = _common(user, der, design, final)
    show_h2 = user.get("use_case") != "Power-led" or c["pipe"] != "none"
    a = dict(site_lat=user["site_lat"], site_lon=user["site_lon"], site_name=user.get("site_name", "Island"),
             grid_lat=user["grid_lat"], grid_lon=user["grid_lon"], grid_name=user.get("grid_name", "Grid point"),
             h2_lat=user["h2_lat"], h2_lon=user["h2_lon"], h2_name=user.get("h2_name", "Hydrogen offtake"),
             show_h2=show_h2 and (final is None or (final.get("h2_kg", 0) > 1)),
             sea_area_km2=user.get("sea_area_km2", 0), n_turbines=c["n_turbines"], floating=c["floating"],
             depth_m=c["depth_m"], title=title,
             cable=(dict(mw=c["C_cab"], mode=c["link_mode"], km=c["grid_km"], volt=c.get("volt"))
                    if c["C_cab"] > 1e-3 else None),
             hub=(dict(lat=user["hub_lat"], lon=user["hub_lon"], name=user.get("hub_name", "Offshore hub"),
                       spare=user.get("hub_spare_mw", 0), kv=user.get("hub_voltage_kv", 0),
                       used=(der or {}).get("elec_connection_used") == "hub" and c["C_cab"] > 1e-3)
                  if user.get("elec_connection", "direct") != "direct" else None),
             tiein=(dict(lat=user["tiein_lat"], lon=user["tiein_lon"], name=user.get("tiein_name", "Pipeline tie-in"),
                         spare=user.get("tiein_spare_kgh", 0), bar=user.get("tiein_pressure_bar", 0),
                         used=(der or {}).get("h2_connection_used") == "tiein" and c["pipe"] not in ("none", None))
                    if (user.get("h2_connection", "direct") != "direct" and user.get("enable_pipe")) else None),
             pipe=(dict(label=str(c["pipe"]).replace("_", " "), km=c["pipe_km"]) if c["pipe"] not in ("none", None)
                   else None))
    return atlas_page(a, animate)


def island_html(user, design=None, final=None, animate=True):
    der = _derived(user, final)
    design = design or preview_design(user)
    return island_iso_page(_common(user, der, design, final), animate)


def section_html(user, design=None, final=None, animate=True):
    der = _derived(user, final)
    design = design or preview_design(user)
    return section_page(_common(user, der, design, final), animate)


def design_from_final(final: dict) -> dict:
    d = {k: float(final.get(k) or 0) for k in CAPS}
    d["pipe"] = final.get("pipe", "none")
    return d
