"""Hybrid offshore-onshore capacity-expansion model (Pyomo LP/MILP).

Physics and cost structure follow the v9 model (AAU EVOLVE WP2). The time
axis is a ``TimeStructure``: the full hourly year, or the TDA blocks of
``tda.tpca`` (variable-length steps in calendar order).

Additions for the planner:
  * technology switches (any asset can be excluded);
  * sea area for wind and PV and deck area for island equipment, as two
    separate limits;
  * electricity revenue as PPA, merchant (hourly price) or two-sided CfD;
  * delivery as an annual volume, a firm hourly band, or an hourly profile;
  * shortfall slacks (used to verify a design on the full year);
  * per-component cost breakdown and hourly result extraction.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pyomo.environ as pyo

from .params import crf
from .timestructure import TimeStructure

CAP_VARS = ["C_wt", "C_pv", "C_ez_off", "C_ez_on", "C_cmp_off", "C_cmp_on", "C_fc_off",
            "C_fc_on", "C_cab", "E_bat_off", "P_bat_off", "E_bat_on", "P_bat_on",
            "E_tank_off", "E_tank_on"]
FLOWS = ["p_we", "p_cab_f", "p_cab_r", "p_curt_off", "bat_off_ch", "bat_off_dis",
         "h2_off", "h2_pipe", "h2fc_off", "tank_off_in", "tank_off_out", "p_pe", "p_grid",
         "bat_on_ch", "bat_on_dis", "h2_on", "h2fc_on", "h2_sell", "tank_on_in", "tank_on_out"]


N_SEG = 3        # piecewise-linear AC loss: equal segments of the installed rating


def set_cable_option(m, p: dict, v, n: float | None = None):
    """Make option v of p["cable_options"] the export link of model m.

    v = index of an option; v = "ideal" sets the lossless, cheapest-per-MW cable used for the lower bound;
    v = "none" builds no cable. With n given, the number of circuits (AC) or converter units (DC) is fixed."""
    CC = p.get("cable_options") or []
    m._cab_active = v
    big = p["cap_ub_mw"]
    if v == "none" or not CC:
        for prm in ("cab_inv_circuit", "cab_inv_mw", "cab_fixed", "cab_fee", "cab_noload", "cab_rho", "cab_plat",
                    "cab_capw"):
            getattr(m, prm).set_value(0.0)
        _set_segments(m, 0.0, big, False)
        m.cab_eff = 1.0
        m.cab_fac = 0.0
        m.cab_rating = 1.0
        m.n_cab.setlb(0)
        m.n_cab.setub(0)
        m.n_cab.fix(0)
        return
    if v == "ideal":
        m.cab_inv_circuit = 0.0
        m.cab_fixed = 0.0
        m.cab_fac = 1.0
        m.cab_inv_mw = min(c["full_use_eur_mw"] for c in CC)          # annual EUR/MW incl. fee and platform
        m.cab_fee = 0.0
        m.cab_noload = 0.0
        m.cab_rho = 0.0
        m.cab_eff = 1.0
        m.cab_capw = 0.0
        m.cab_plat = 0.0
        m.cab_rating = p["cap_ub_mw"]
        m.n_cab.setub(1)
        m.n_cab.fix(1)
        _set_segments(m, 0.0, big, False)
        return
    c = CC[v]
    m.cab_inv_circuit = c["inv_circuit"]
    m.cab_inv_mw = c["inv_mw"]
    m.cab_fixed = c["fixed_once"]
    m.cab_fac = c["fac"]
    m.cab_fee = c["fee"]
    m.cab_noload = c["annual_noload"]
    m.cab_rho = c["rho"]
    m.cab_eff = c["eff"]
    m.cab_capw = c["cap_from_n"]
    m.cab_plat = c["plat"]
    m.cab_rating = c["rating"]
    m.n_cab.unfix()
    m.n_cab.setlb(1)
    m.n_cab.setub(c["max_n"])
    if n is not None:
        m.n_cab.fix(n)
    # AC: quadratic loss as chords over N_SEG segments of the installed rating n * R (exact at the segment
    # ends, slightly above in between); DC: the full-load share applied linearly (secant)
    quad = c["cap_from_n"] > 0.5
    _set_segments(m, c["rho"], (c["rating"] * (n if n is not None else c["max_n"]) / N_SEG) if quad else big, quad)


def _set_segments(m, rho, seg_cap, quad):
    m.seg_cap = seg_cap
    for j in range(N_SEG):
        m.seg_slope[j] = rho * (2 * j + 1) / N_SEG if quad else rho


def build(ts: TimeStructure, p: dict, allow_shortfall: bool = False, relax_pipe: bool = False,
          relax_int: bool = False):
    R, L = ts.R, ts.L
    sw = ts.sw * ts.dt                      # hours represented by each step
    W = ts.weight_r()                       # occurrences of each period per year
    wt, pv = ts.reps["wind_cf"], ts.reps["pv_cf"]
    price = ts.reps.get("price")
    m = pyo.ConcreteModel()
    m.R = pyo.RangeSet(0, R - 1)
    m.H = pyo.RangeSet(0, L - 1)
    m.B = pyo.RangeSet(0, L)
    m.S = pyo.RangeSet(0, len(ts.slots) - 1)
    NN = pyo.NonNegativeReals
    ub, rub = p["cap_ub_mw"], p["cap_renewable_ub_mw"]
    Bt, Tk = p["batt"], p["tank"]
    on = lambda key: ub if p.get(key, True) else 0.0

    # ---- capacities -----------------------------------------------------------
    m.C_wt = pyo.Var(bounds=(0, rub))
    m.C_pv = pyo.Var(bounds=(0, rub if p["enable_pv"] else 0.0))
    m.C_ez_off = pyo.Var(bounds=(0, on("enable_ez_off")))
    m.C_ez_on = pyo.Var(bounds=(0, on("enable_ez_on")))
    m.C_cmp_off = pyo.Var(bounds=(0, ub if p["pipe_allowed"] else 0.0))
    m.C_cmp_on = pyo.Var(bounds=(0, on("enable_ez_on")))
    m.C_fc_off = pyo.Var(bounds=(0, on("enable_fc_off")))
    m.C_fc_on = pyo.Var(bounds=(0, on("enable_fc_on")))
    m.C_cab = pyo.Var(bounds=(0, ub if p["elec_export_allowed"] else 0.0))
    m.C_grid = pyo.Var(bounds=(0, max(p["grid_injection_cap_mw"], 0.0)))   # capacity injected into the grid
    m.E_bat_off = pyo.Var(bounds=(0, Bt["off"]["max_e"])); m.P_bat_off = pyo.Var(bounds=(0, Bt["off"]["max_p"]))
    m.E_bat_on = pyo.Var(bounds=(0, Bt["on"]["max_e"])); m.P_bat_on = pyo.Var(bounds=(0, Bt["on"]["max_p"]))
    m.E_tank_off = pyo.Var(bounds=(0, Tk["off"]["max_kg"])); m.E_tank_on = pyo.Var(bounds=(0, Tk["on"]["max_kg"]))
    m.K = pyo.Set(initialize=p["pipe_allowed"])
    m.y_pipe = pyo.Var(m.K, domain=pyo.UnitInterval if relax_pipe else pyo.Binary)
    if p["pipe_allowed"]:
        m.one_pipe = pyo.Constraint(expr=sum(m.y_pipe[k] for k in m.K) <= 1)

    # ---- operation --------------------------------------------------------------
    for n in FLOWS:
        setattr(m, n, pyo.Var(m.R, m.H, domain=NN))
    comp, fc, h2k = p["comp_mwh_per_kg"], p["fc_mwh_per_kg"], p["h2_kg_per_mwh"]
    gen = lambda r, h: m.C_wt * float(wt[r, h]) + m.C_pv * float(pv[r, h])

    # ---- export link: one catalogue option at a time (AC voltage/conductor/compensation, or HVDC) ----------
    # The option enters through mutable parameters so the selection search can swap options and re-solve
    # the same model warm (set_cable_option).
    CC = p.get("cable_options") or []
    mp = lambda v: pyo.Param(mutable=True, initialize=v)
    m.cab_inv_circuit = mp(0.0)  # EUR per circuit (AC) or per converter unit (DC)
    m.cab_inv_mw = mp(0.0)       # EUR per MW of capacity (DC)
    m.cab_fixed = mp(0.0)        # EUR once (mid-route compensation platform)
    m.cab_fac = mp(0.0)          # annuity factor + fixed O&M share
    m.cab_fee = mp(0.0)          # grid fee, EUR per MW per year
    m.cab_noload = mp(0.0)       # value of no-load losses, EUR per circuit per year
    m.cab_rho = mp(0.0)          # cable loss share at full loading of the installed rating
    m.cab_eff = mp(1.0)          # converter efficiency (DC), 1 for AC
    m.cab_capw = mp(0.0)         # 1: loss reference = circuits' rating (AC); 0: = capacity built (DC)
    m.cab_plat = mp(0.0)         # 1: island AC substation platform cost applies
    m.cab_rating = mp(1.0)       # MW per circuit / per converter unit
    m.n_cab = pyo.Var(domain=NN if relax_int else pyo.NonNegativeIntegers, bounds=(0, 0))
    m.cab_circ = pyo.Constraint(expr=m.C_cab <= m.cab_rating * m.n_cab)
    m._cab_active = None
    # Cable losses. Island -> shore: the flow is split into N_SEG segments of the installed rating, each with
    # the chord slope of rho * f^2 / Cap (piecewise-linear losses; the cheapest segments fill first). Shore ->
    # island flows are small (power for island equipment in calm hours) and use the full-load share rho.
    m.SEG = pyo.RangeSet(0, N_SEG - 1)
    m.seg_cap = pyo.Param(mutable=True, initialize=p["cap_ub_mw"])
    m.seg_slope = pyo.Param(m.SEG, mutable=True, initialize=0.0)
    m.pf_seg = pyo.Var(m.SEG, m.R, m.H, domain=NN, bounds=lambda mm, j, r, h: (0, mm.seg_cap))
    m.seg_sum = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.p_cab_f[r, h] == sum(mm.pf_seg[j, r, h] for j in mm.SEG))
    if CC:
        set_cable_option(m, p, p.get("cable_option_index", p.get("cable_preview_index", 0)),
                         p.get("cable_option_n"))
    else:
        set_cable_option(m, p, "none")
    loss_f = lambda mm, r, h: sum(mm.seg_slope[j] * mm.pf_seg[j, r, h] for j in mm.SEG)
    m._loss_f = loss_f
    recv_f = lambda mm, r, h: mm.cab_eff * mm.p_cab_f[r, h] - loss_f(mm, r, h)
    recv_r = lambda mm, r, h: (mm.cab_eff - mm.cab_rho) * mm.p_cab_r[r, h]

    m.off_bal = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        gen(r, h) + recv_r(mm, r, h) + fc * mm.h2fc_off[r, h] + mm.bat_off_dis[r, h]
        == mm.p_we[r, h] + comp * mm.h2_pipe[r, h] + mm.p_cab_f[r, h] + mm.p_curt_off[r, h] + mm.bat_off_ch[r, h])
    m.on_bal = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        recv_f(mm, r, h) + fc * mm.h2fc_on[r, h] + mm.bat_on_dis[r, h]
        == mm.p_pe[r, h] + comp * mm.h2_on[r, h] + mm.p_cab_r[r, h] + mm.p_grid[r, h] + mm.bat_on_ch[r, h])
    m.off_h2 = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        mm.h2_off[r, h] + mm.tank_off_out[r, h] == mm.h2_pipe[r, h] + mm.h2fc_off[r, h] + mm.tank_off_in[r, h])
    m.on_h2 = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        mm.h2_on[r, h] + p["pipeline_efficiency"] * mm.h2_pipe[r, h] + mm.tank_on_out[r, h]
        == mm.h2_sell[r, h] + mm.h2fc_on[r, h] + mm.tank_on_in[r, h])
    # turbine-level electrolysis avoids the array and AC/DC conversion losses of a central plant
    h2k_off = h2k * (1.0 + (p["turbine_ez_eff_gain"] if p.get("turbine_level") else 0.0))
    m.off_prod = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.h2_off[r, h] == h2k_off * mm.p_we[r, h])
    m.on_prod = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.h2_on[r, h] == h2k * mm.p_pe[r, h])
    lim = [("p_we", "C_ez_off", 1.0), ("p_pe", "C_ez_on", 1.0), ("h2_pipe", "C_cmp_off", comp),
           ("h2_on", "C_cmp_on", comp), ("h2fc_off", "C_fc_off", fc), ("h2fc_on", "C_fc_on", fc),
           ("p_cab_f", "C_cab", 1.0), ("p_cab_r", "C_cab", 1.0), ("bat_off_ch", "P_bat_off", 1.0),
           ("bat_off_dis", "P_bat_off", 1.0), ("bat_on_ch", "P_bat_on", 1.0), ("bat_on_dis", "P_bat_on", 1.0)]
    for i, (v, c, f) in enumerate(lim):
        setattr(m, f"lim_{i}", pyo.Constraint(m.R, m.H, rule=lambda mm, r, h, v=v, c=c, f=f:
                f * getattr(mm, v)[r, h] <= getattr(mm, c)))
    if comp <= 0:      # no compression needed: pipe flow still limited by the pipe only
        pass
    m.lim_pipe = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
        mm.h2_pipe[r, h] <= sum(p["pipe_classes"][k]["cap_kgh"] * mm.y_pipe[k] for k in mm.K))
    if p.get("h2_connection_used") == "tiein":            # spare capacity of the existing pipeline (0 = none)
        m.lim_tiein = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.h2_pipe[r, h] <= p["pipe_spare_kgh"])
    m.lim_grid = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.p_grid[r, h] <= mm.C_grid)
    m.lim_curt = pyo.Constraint(m.R, m.H, rule=lambda mm, r, h: mm.p_curt_off[r, h] <= gen(r, h))
    if p["config"] == "C_floating_decentralized":
        m.dec_ez = pyo.Constraint(expr=m.C_ez_off <= m.C_wt + m.C_pv)

    # ---- deliveries ----------------------------------------------------------------------
    hours = lambda r, h: float(W[r] * sw[h])
    annual = lambda var: sum(hours(r, h) * var[r, h] for r in m.R for h in m.H)
    if allow_shortfall:
        m.short_e = pyo.Var(m.R, m.H, domain=NN); m.short_h = pyo.Var(m.R, m.H, domain=NN)
        m.short_ey = pyo.Var(domain=NN); m.short_hy = pyo.Var(domain=NN)
    volume_free = p["elec_revenue"] in ("merchant", "cfd")

    def deliver(tag, var, D, mode, profile_key, sh_rh, sh_y):
        if mode == "profile" and profile_key in ts.reps:
            prof = ts.reps[profile_key]
            setattr(m, f"prof_{tag}", pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
                    var[r, h] + (sh_rh[r, h] if allow_shortfall else 0) == float(prof[r, h])))
        elif D <= 0:
            return
        elif mode == "firm":
            setattr(m, f"firm_{tag}", pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
                    var[r, h] + (sh_rh[r, h] if allow_shortfall else 0) == D / 8760.0))
        else:
            setattr(m, f"annual_{tag}", pyo.Constraint(expr=annual(var) + (sh_y if allow_shortfall else 0) == D))

    if not volume_free:
        deliver("e", m.p_grid, p["annual_demand_mwh"], p["elec_delivery"], "elec_demand",
                getattr(m, "short_e", None), getattr(m, "short_ey", None))
    deliver("h", m.h2_sell, p["annual_h2_demand_kg"], p["h2_delivery"], "h2_demand",
            getattr(m, "short_h", None), getattr(m, "short_hy", None))

    # ---- storage: Kotzur min/max bounds (exact for loss-free storage) ------------------------
    slots = ts.slots
    nS = len(slots)

    def storage(name, cap, inflow, outflow, eta_in, eta_out):
        start = pyo.Var(m.S, domain=NN); dev = pyo.Var(m.R, m.B, domain=pyo.Reals)
        dmin = pyo.Var(m.R, domain=pyo.Reals); dmax = pyo.Var(m.R, domain=pyo.Reals)
        for n, o in (("start", start), ("dev", dev), ("dmin", dmin), ("dmax", dmax)):
            setattr(m, f"{name}_{n}", o)
        setattr(m, f"{name}_d0", pyo.Constraint(m.R, rule=lambda mm, r: dev[r, 0] == 0))
        setattr(m, f"{name}_dyn", pyo.Constraint(m.R, m.H, rule=lambda mm, r, h:
                dev[r, h + 1] == dev[r, h] + float(sw[h]) * (eta_in * inflow[r, h] - outflow[r, h] / eta_out)))
        setattr(m, f"{name}_lo", pyo.Constraint(m.R, m.B, rule=lambda mm, r, b: dmin[r] <= dev[r, b]))
        setattr(m, f"{name}_hi", pyo.Constraint(m.R, m.B, rule=lambda mm, r, b: dev[r, b] <= dmax[r]))
        setattr(m, f"{name}_link", pyo.Constraint(m.S, rule=lambda mm, s:
                start[(s + 1) % nS] == start[s] + slots[s][1] * dev[slots[s][0], L]))
        cons = pyo.ConstraintList()
        setattr(m, f"{name}_bnd", cons)
        for s, (r, w, _) in enumerate(slots):
            k_last = max(int(math.ceil(w - 1e-9)) - 1, 0)
            for k in sorted({0, k_last}):
                cons.add(start[s] + k * dev[r, L] + dmin[r] >= 0)
                cons.add(start[s] + k * dev[r, L] + dmax[r] <= cap)

    storage("bat_off", m.E_bat_off, m.bat_off_ch, m.bat_off_dis, Bt["off"]["eta_ch"], Bt["off"]["eta_dis"])
    storage("bat_on", m.E_bat_on, m.bat_on_ch, m.bat_on_dis, Bt["on"]["eta_ch"], Bt["on"]["eta_dis"])
    storage("tank_off", m.E_tank_off, m.tank_off_in, m.tank_off_out, 1.0, 1.0)
    storage("tank_on", m.E_tank_on, m.tank_on_in, m.tank_on_out, 1.0, 1.0)

    # ---- space: sea area for generation, deck area for island equipment ---------------------
    m.sea_area = pyo.Constraint(expr=m.C_wt / p["wind_density_mw_km2"] + m.C_pv / p["pv_density_mw_km2"]
                                <= p["sea_area_km2"])
    m.deck_area = pyo.Constraint(expr=p["area_elec_m2_mw"] * m.C_ez_off + p["area_comp_m2_mw"] * m.C_cmp_off
        + p["area_fc_m2_mw"] * m.C_fc_off + p["area_batt_m2_mwh"] * m.E_bat_off
        + p["area_tank_m2_kg"] * m.E_tank_off <= p["deck_area_max_m2"])
    m.area_on = pyo.Constraint(expr=p["area_elec_m2_mw"] * m.C_ez_on + p["area_comp_m2_mw"] * m.C_cmp_on
        + p["area_fc_m2_mw"] * m.C_fc_on + p["area_batt_m2_mwh"] * m.E_bat_on
        + p["area_tank_m2_kg"] * m.E_tank_on <= p["area_onshore_max_m2"])

    # ---- costs -------------------------------------------------------------------------------
    op = p["offshore_premium"]
    tl = bool(p.get("turbine_level"))
    # island platform structure (version 0.10): k_esc k_inst [f_E c_E S_cab + f_H c_H S_H] (+ C_0), in EUR
    kk = 1e3 * p["platform_escalation"] * p["platform_install_factor"]
    s_h = (m.C_ez_off + p["platform_w_comp"] * m.C_cmp_off + p["platform_w_fc"] * m.C_fc_off
           + p["platform_w_bat"] * m.P_bat_off)
    plat_inv = kk * (p["platform_factor_e"] * p["platform_cable_coef"] * m.cab_plat * m.C_cab
                     + p["platform_factor_h"] * p["platform_elec_coef"] * s_h)
    if not tl and p["platform_fixed_eur"] > 0:
        plat_inv = plat_inv + p["platform_fixed_eur"]
    wind_capex = p["wind_capex_eur_mw"] - (p["array_cable_credit_eur_mw"] if tl else 0.0)
    ez_scale = p["turbine_ez_scale_factor"] if tl else 1.0
    cx = {
        "Offshore wind": (wind_capex * m.C_wt, p["wind_life"], p["wind_fom"]),
        "Floating PV": (p["pv_capex_eur_kw"] * 1e3 * m.C_pv, p["pv_life"], p["pv_fom"]),
        "Electrolyser (island)": (p["elec_capex_eur_kw"] * 1e3 * op * ez_scale * m.C_ez_off, p["elec_life"],
                                  p["elec_fom"]),
        "Electrolyser (onshore)": (p["elec_capex_eur_kw"] * 1e3 * m.C_ez_on, p["elec_life"], p["elec_fom"]),
        "Water treatment": (p["wt_capex_eur_mw"] * (m.C_ez_off + m.C_ez_on), p["wt_life"], p["wt_fom"]),
        "Compressors": (p["comp_capex_eur_mw"] * (op * m.C_cmp_off + m.C_cmp_on), p["comp_life"], p["comp_fom"]),
        "Fuel cells": (p["fc_capex_eur_kw"] * 1e3 * (op * m.C_fc_off + m.C_fc_on), p["fc_life"], p["fc_fom"]),
        "H2 pipeline": (sum((p["pipe_classes"][k]["capex_per_km"] * p["pipe_distance_km"] + p.get("pipe_fixed_eur", 0.0))
                            * m.y_pipe[k] for k in m.K),
                        p["pipeline_life"], p["pipeline_fom"]),
        "Island platform": (plat_inv, p["platform_life"], p["platform_fom_used"]),
    }
    if tl:   # configuration C: per-turbine integration and in-field hydrogen lines instead of a central platform
        cx["Turbine-level integration"] = (kk * p["turbine_integration_factor"] * p["platform_elec_coef"] * s_h,
                                           p["platform_life"], p["platform_fom"])
        cx["In-field H2 pipelines"] = (p["infield_pipe_eur_km"] * p["infield_km_per_turbine"] / p["turbine_mw"]
                                       * m.C_wt, p["pipeline_life"], p["infield_pipe_fom"])
    r_ = p["discount_rate"]
    m.cost_parts = {k: pyo.Expression(expr=e * (crf(r_, n) + f)) for k, (e, n, f) in cx.items()}
    # storage: island and onshore units keep their own fixed O&M (v9: 2.5 % offshore, 2.0 % onshore)
    st_capex = {
        "Batteries": [(Bt[s]["capex_e"] * getattr(m, f"E_bat_{s}") + Bt[s]["capex_p"] * getattr(m, f"P_bat_{s}"),
                       Bt[s]["life"], Bt[s]["fom"]) for s in ("off", "on")],
        "H2 tanks": [(Tk[s]["capex_kg"] * getattr(m, f"E_tank_{s}"), Tk[s]["life"], Tk[s]["fom"]) for s in ("off", "on")],
    }
    for k, parts in st_capex.items():
        m.cost_parts[k] = pyo.Expression(expr=sum(e * (crf(r_, n) + f) for e, n, f in parts) if parts else 0.0)
    m.cab_capex = pyo.Expression(expr=m.cab_inv_circuit * m.n_cab + m.cab_fixed + m.cab_inv_mw * m.C_cab)
    m.cost_parts["Export cable"] = pyo.Expression(expr=m.cab_fac * m.cab_capex + m.cab_noload * m.n_cab)
    capex_all = [e for e, _, _ in cx.values()] + [e for parts in st_capex.values() for e, _, _ in parts] + [m.cab_capex]
    for k, e in m.cost_parts.items():
        m.add_component("cp_" + "".join(ch for ch in k if ch.isalnum()), e)
    m.capex_total = pyo.Expression(expr=sum(capex_all))
    # hub access fee on the cable to the hub + TSO fee on the capacity injected into the existing grid
    m.tso = pyo.Expression(expr=m.cab_fee * m.C_cab + float(p.get("tso_grid_fee", 0.0)) * m.C_grid)
    m.ann_vom = pyo.Expression(expr=Bt["on"]["vom"] * (annual(m.bat_off_dis) + annual(m.bat_on_dis))
                               + Tk["on"]["vom"] * (annual(m.tank_off_in) + annual(m.tank_on_in)))
    if p["elec_revenue"] == "merchant":
        m.rev_e = pyo.Expression(expr=sum(hours(r, h) * float(price[r, h]) * m.p_grid[r, h] for r in m.R for h in m.H))
    elif p["elec_revenue"] == "cfd":
        strike = p["cfd_strike_eur_mwh"]
        m.rev_e = pyo.Expression(expr=sum(hours(r, h) * (strike if price[r, h] >= 0 else float(price[r, h]))
                                          * m.p_grid[r, h] for r in m.R for h in m.H))
    elif p["elec_revenue"] == "ppa":
        m.rev_e = pyo.Expression(expr=p["ppa_price_eur_mwh"] * annual(m.p_grid))
    else:
        m.rev_e = pyo.Expression(expr=0.0)
    m.rev_h = pyo.Expression(expr=p["h2_price_eur_kg"] * annual(m.h2_sell))
    pen = 0.0
    if allow_shortfall:
        pen = (p["shortfall_penalty_eur_mwh"] * (annual(m.short_e) + m.short_ey)
               + p["shortfall_penalty_eur_kg"] * (annual(m.short_h) + m.short_hy))
    m.penalty = pyo.Expression(expr=pen)
    m.total_cost = pyo.Expression(expr=sum(m.cost_parts.values()) + m.tso + m.ann_vom)
    m.net_cost = pyo.Expression(expr=m.total_cost - m.rev_e - m.rev_h + m.penalty)
    m.obj = pyo.Objective(expr=m.net_cost, sense=pyo.minimize)
    m._ts, m._p, m._hours = ts, p, np.outer(W, sw)
    return m


# ---------------------------------------------------------------------------
# solving
# ---------------------------------------------------------------------------

def _has_integers(m) -> bool:
    return any((v.is_integer() or v.is_binary()) and not v.fixed for v in m.component_data_objects(pyo.Var))


def _solver(name: str, ipm: bool, mip: bool = False):
    if name == "highs":
        from pyomo.contrib.appsi.solvers import Highs
        s = Highs()
        s.highs_options["presolve"] = "on"
        s.highs_options["threads"] = 1
        if mip:
            s.highs_options["mip_rel_gap"] = 1e-5
            s.highs_options["mip_abs_gap"] = 100.0          # EUR per year
            s.highs_options["time_limit"] = 3600.0
        elif ipm:
            s.highs_options["solver"] = "ipm"
            s.highs_options["run_crossover"] = "on"
        s.config.load_solution = False
        return s
    if name == "glpk":
        s = pyo.SolverFactory("glpk")
        s.options["tmlim"] = 3600
        if mip:
            s.options["mipgap"] = 1e-5
        return s
    raise ValueError(name)


def solve(m, solver: str = "highs") -> dict:
    t0 = time.time()
    mip = _has_integers(m)
    if solver == "highs":
        if mip:
            res = _solver("highs", False, mip=True).solve(m)
            ok = res.termination_condition.name == "optimal"
        else:
            res = _solver("highs", True).solve(m)
            ok = res.termination_condition.name == "optimal"
            if not ok:      # IPM can misreport badly scaled LPs; confirm with simplex
                res = _solver("highs", False).solve(m)
                ok = res.termination_condition.name == "optimal"
        status = res.termination_condition.name
        if ok:
            res.solution_loader.load_vars()
    else:
        res = _solver("glpk", False, mip=mip).solve(m)
        status = str(res.solver.termination_condition)
        ok = status == "optimal"
    if not ok:
        raise RuntimeError(f"The solver stopped without an optimal solution ({status}). "
                           "Check that the contracts can be met with the technologies allowed.")
    return {"solve_s": time.time() - t0, "status": status, "mip": mip}


def _annual_pipe(p, k):
    c = p["pipe_classes"][k]
    return (c["capex_per_km"] * p["pipe_distance_km"] + p.get("pipe_fixed_eur", 0.0)) * (
        crf(p["discount_rate"], p["pipeline_life"]) + p["pipeline_fom"])


def cable_min_mw(p, pipe_built: bool) -> float:
    """A cable capacity every feasible design needs. Electricity sold under contract can only arrive by cable
    unless onshore fuel cells make it from piped hydrogen; contracted hydrogen without a pipeline must be made
    onshore from electricity that crosses the cable."""
    e = 0.0
    if p["elec_revenue"] not in ("merchant", "cfd") and p["annual_demand_mwh"] > 0:
        if not (pipe_built and p.get("enable_fc_on", True)):
            e += p["annual_demand_mwh"]
    if p["annual_h2_demand_kg"] > 0 and not pipe_built:
        e += p["annual_h2_demand_kg"] / p["h2_kg_per_mwh"]
    return e / 8760.0


def pipe_required(p) -> bool:
    """Contracted hydrogen can only arrive by pipe when it cannot be made onshore from cable power."""
    return p["annual_h2_demand_kg"] > 0 and not (bool(p.get("cable_options")) and p.get("enable_ez_on", True))


def solve_sizing(ts, p, solver="highs"):
    """Exact sizing on a reduced year: the pipeline class, the export-link option and its whole number of
    circuits (AC) or converter units (DC), together with every continuous capacity and the operation.

    The problem is a mixed-integer programme: one pipeline class k or none (binary), one link option v from
    the catalogue (binary) and its integer number of circuits n. It is solved by an exact branch and bound
    that uses the structure of the problem:

    1. Pipe level. For each pipeline class k (and "none"), solve the LP with that pipe and an ideal cable:
       lossless, costing c0 per MW, the lowest annual cost per MW of any option at full use. Its cost Z_k
       is a lower bound on every design with pipe k. Pipes are explored in order of Z_k.
    2. Link level. For pipe k, G_k(P), the cost of everything except the cable with a lossless cable of
       capacity P, is convex in P (an LP value function in a right-hand side). Tangents at a few capacities,
       from reduced costs, bound it from below. For option v with n circuits, every design costs at least
           min over P in [P_min, n R_v] of  G_k_hat(P) + A_v(P, n),
       where A_v is the annual cost of the n circuits at capacity P (losses excluded, so it is a bound).
    3. Leaves. In order of these bounds, solve the LP with k, v and n fixed (its losses included) and keep
       the cheapest. Stop when the next bound cannot beat it.

    The result is the optimum of the mixed-integer programme up to the LP tolerance. Each LP re-solves the
    same model with a few parameters or bounds changed, warm-started by the dual simplex method."""
    t0 = time.time()
    CC = p.get("cable_options") or []
    pipes = list(p["pipe_allowed"])
    m = build(ts, p, relax_pipe=True, relax_int=True)       # the integers are fixed during the search
    persistent = solver == "highs"
    s = _solver("highs", True) if persistent else None
    n_lp = 0
    log = []
    last = {"res": None}
    if not persistent:
        m.rc = pyo.Suffix(direction=pyo.Suffix.IMPORT)

    def lp(first=False):
        nonlocal n_lp, s
        n_lp += 1
        t1 = time.time()
        if persistent:
            if not first:
                s.highs_options["solver"] = "simplex"
                s.highs_options["run_crossover"] = "on"
                s.highs_options["presolve"] = "off"
            r = s.solve(m)
            ok = r.termination_condition.name == "optimal"
            if not ok and first:          # IPM can misreport badly scaled LPs; confirm with simplex
                s = _solver("highs", False)
                r = s.solve(m)
                ok = r.termination_condition.name == "optimal"
            if ok:
                r.solution_loader.load_vars()
        else:
            r = _solver(solver, False).solve(m, load_solutions=False)
            ok = str(r.solver.termination_condition) == "optimal"
            if ok:
                m.solutions.load_from(r)
        f = float(pyo.value(m.obj)) if ok else math.inf
        _log(f"  LP {n_lp}: {f:,.0f} in {time.time() - t1:.1f}s")
        last["res"] = r if ok else None
        return f

    def reduced_cost(var):
        r = last["res"]
        if r is None:
            return 0.0
        if persistent:
            return float(r.solution_loader.get_reduced_costs([var]).get(var, 0.0))
        return float(m.rc.get(var, 0.0))

    def fix_pipe(k):
        for kk in pipes:
            m.y_pipe[kk].fix(1.0 if kk == k else 0.0)

    Pmax = p["cap_ub_mw"]
    c0 = min(c["full_use_eur_mw"] for c in CC) if CC else 0.0

    def ideal():
        set_cable_option(m, p, "ideal" if CC else "none")

    def annual_n(c, P, n):
        """Annual cost of option c with exactly n circuits/units carrying capacity P (losses excluded)."""
        return (c["fac"] * (c["inv_circuit"] * n + c["fixed_once"] + c["inv_mw"] * P) + c["annual_noload"] * n
                + (c["fee"] + c["plat"] * c["plat_mw"]) * P)

    # ---- 1. pipe level ----------------------------------------------------------------------------
    pipe_opts = ([None] if not (pipes and pipe_required(p)) else []) + pipes
    ideal()
    fix_pipe(pipe_opts[0])
    first_done = False
    Zk = {}
    for k in pipe_opts:
        fix_pipe(k)
        Zk[k] = lp(first=not first_done)
        first_done = True
    lb = min(Zk.values())
    if lb == math.inf:
        raise RuntimeError("The solver stopped without an optimal solution. "
                           "Check that the contracts can be met with the technologies allowed.")
    _log(f"lower bound {lb:,.0f}; pipe bounds " + ", ".join(f"{k}: {z:,.0f}" for k, z in Zk.items()))
    best, best_x, last_x = math.inf, None, None
    tol = lambda: max(1.0, 1e-6 * abs(best)) if best < math.inf else 0.0
    n_eval, n_bounds = 0, 0
    def make_leaves(k):
        """Tangents of G_k(P) and the bound of every (option, circuits) leaf under pipe k."""
        fix_pipe(k)
        Pmin = cable_min_mw(p, k is not None)
        cuts = []
        if CC:
            ideal()
            z = lp()
            P_star = _val(m.C_cab)
            cuts.append((P_star, z - c0 * P_star, -c0))          # tangent at the optimum of the bound LP
            m.cab_inv_mw = 0.0                                   # cable free: the objective is G_k(P)
            grid = sorted({round(x, 6) for x in (f * max(P_star, 1.0) for f in (0.1, 0.25, 0.5, 0.75, 1.25, 1.5, 2.0, 3.0))
                           if 1.05 * Pmin <= x <= Pmax})
            for P_i in grid:
                m.C_cab.setlb(P_i)
                m.C_cab.setub(P_i)
                g = lp()
                if g < math.inf:
                    cuts.append((P_i, g, reduced_cost(m.C_cab)))
            m.C_cab.setlb(0.0)
            m.C_cab.setub(Pmax)
        G_hat = lambda P: max(g + sl * (P - P_i) for P_i, g, sl in cuts)

        def bound(c, n):
            hi = min(Pmax, c["rating"] * n)
            lo = max(Pmin, 0.0)
            if lo > hi:
                return math.inf
            pts = {lo, hi}
            for i, (Pa, ga, sa) in enumerate(cuts):           # kinks of G_hat
                for Pb, gb, sb in cuts[i + 1:]:
                    if abs(sa - sb) > 1e-12:
                        x = (gb - sb * Pb - ga + sa * Pa) / (sa - sb)
                        if lo <= x <= hi:
                            pts.add(x)
            return min(G_hat(P) + annual_n(c, P, n) for P in pts)
        leaves = []
        for v, c in enumerate(CC):
            for n in range(1, (1 if c["key"] == "v9" else c["max_n"]) + 1):
                if c["rating"] * (n - 1) >= Pmax:
                    break
                b_ = bound(c, n)
                if b_ < math.inf:
                    leaves.append((b_, v, n))
        if not CC or Pmin <= 0:
            leaves.append(((G_hat(0.0) if cuts else Zk[k]), "none", 0))
        leaves.sort(key=lambda t: t[0])
        return leaves

    # Every other pipe k satisfies G_k(P) >= G_kmax(P) - A_kmax + A_k (a larger pipe can only lower the rest
    # of the cost), so the leaves of the largest pipe bound every pipe without new LPs.
    ann = {k: (_annual_pipe(p, k) if k is not None else 0.0) for k in pipe_opts}
    k_max = max(pipes, key=lambda k: p["pipe_classes"][k]["cap_kgh"]) if pipes else None
    leaves_max = make_leaves(k_max) if (pipes and len(pipe_opts) > 1 and Zk[k_max] < math.inf) else None
    min_leaf_max = leaves_max[0][0] if leaves_max else -math.inf
    for k in sorted(pipe_opts, key=lambda k: Zk[k]):
        if Zk[k] >= best - tol():
            continue
        if leaves_max is not None and min_leaf_max - ann[k_max] + ann[k] >= best - tol():
            continue
        leaves = leaves_max if (k == k_max and leaves_max is not None) else make_leaves(k)
        fix_pipe(k)
        n_bounds += len(leaves)
        leaves.sort(key=lambda t: t[0])
        # ---- 3. leaves -------------------------------------------------------------------------------
        for b_, v, n in leaves:
            if b_ >= best - tol():
                break
            set_cable_option(m, p, v, n if isinstance(v, int) else None)
            f = lp()
            n_eval += 1
            log.append(((CC[v]["name"] + f" x{n}") if isinstance(v, int) else "no export cable", k, b_, f))
            last_x = (v, n, k)
            if f < best:
                best, best_x = f, (v, n, k)
    if best_x is None:
        raise RuntimeError("No export-link option and pipeline class meets the contracts.")
    v, n, k = best_x
    f = best
    if last_x != best_x:                  # load the best design back into the model
        set_cable_option(m, p, v, n if isinstance(v, int) else None)
        fix_pipe(k)
        f = lp()
    m._search = {"lower_bound": lb, "leaves": n_bounds, "evaluated": n_eval, "log": log}
    return m, {"solve_s": time.time() - t0, "status": "optimal", "n_lp": n_lp, "lower_bound": lb,
               "objective": f, "options": len(CC), "leaves": n_bounds, "evaluated": n_eval, "log": log}


def _log(msg):
    import os
    if os.environ.get("EVOLVE_DEBUG"):
        print(msg, flush=True)


def design_of(m) -> dict:
    d = {v: max(float(pyo.value(getattr(m, v))), 0.0) for v in CAP_VARS}
    d["pipe"] = {k: int(round(pyo.value(m.y_pipe[k]))) for k in m.K}
    d["cable_class"] = m._cab_active
    d["cable_n"] = int(round(_val(m.n_cab)))
    return d


def cable_choice(m) -> dict:
    """The export link built: option, circuits or units, capacity, efficiency and cost."""
    from .cables import dc_voltage_label
    p = m._p
    CC = p.get("cable_options") or []
    v = m._cab_active
    P = _val(m.C_cab)
    if not CC or not isinstance(v, int) or P <= 1e-6:
        return {"cable_class": "none", "n_circuits": 0, "export_voltage_used": "none", "cable_tech": "none",
                "circuit_rating_mw": float("nan"), "cable_eff": 1.0, "cable_capex_eur_mw": 0.0,
                "link_mode": p.get("link_mode", "HVAC"), "cable_loss_mwh": 0.0}
    c = CC[v]
    n = _val(m.n_cab)
    hrs = m._hours
    sent = float((hrs * np.array([[_val(m.p_cab_f[r, h]) + _val(m.p_cab_r[r, h]) for h in m.H] for r in m.R])).sum())
    lost = float((hrs * np.array([[float(pyo.value(m._loss_f(m, r, h))) + c["rho"] * _val(m.p_cab_r[r, h])
                                   for h in m.H] for r in m.R])).sum())
    conv = (1 - c["eff"]) * sent
    out = {"cable_class": c["name"] if c["tech"] == "AC" else dc_voltage_label(P), "cable_tech": c["tech"],
           "n_circuits": int(math.ceil(n - 1e-6)), "export_voltage_used": (f"{c['kv']:.0f} kV AC" if c["tech"] == "AC"
                                                                       else dc_voltage_label(P)),
           "circuit_rating_mw": c["rating"] if c["tech"] == "AC" else P,
           "cable_capex_eur_mw": float(pyo.value(m.cab_capex)) / P,
           "link_mode": "HVDC" if c["tech"] == "DC" else "HVAC",
           "cable_conductor_mm2": c.get("mm2", 0), "cable_compensation": c.get("scheme", ""),
           "cable_loss_mwh": lost + conv + 8760.0 * c["noload_mw"] * math.ceil(n - 1e-6),
           "cable_noload_mw": c["noload_mw"] * math.ceil(n - 1e-6),
           "cable_utilisation": P / (c["rating"] * n) if n > 0 else 1.0,
           "cable_eff": 1.0 - (lost + conv) / sent if sent > 0 else c["eff"] * (1 - c["rho"]),
           "cable_reactive_mvar": c.get("q_mvar", 0.0) * math.ceil(n - 1e-6)}
    if c["key"] == "v9":
        out.update(cable_class=c["name"], export_voltage_used=c["name"], n_circuits=0,
                   circuit_rating_mw=float("nan"), cable_eff=c["eff"])
    return out


def _val(x):
    v = x.value
    return 0.0 if v is None else float(v)


def hourly(m) -> dict:
    """Hourly arrays (length = steps of the time structure, R=1)."""
    out = {n: np.array([_val(getattr(m, n)[0, h]) for h in m.H]) for n in FLOWS}
    ts = m._ts
    out["gen_wind"] = _val(m.C_wt) * ts.reps["wind_cf"][0]
    out["gen_pv"] = _val(m.C_pv) * ts.reps["pv_cf"][0]
    for name in ("tank_on", "tank_off", "bat_on", "bat_off"):
        start = _val(getattr(m, f"{name}_start")[0])
        dev = np.array([_val(getattr(m, f"{name}_dev")[0, b]) for b in range(ts.L + 1)])
        out[f"soc_{name}"] = start + dev[1:]
    if hasattr(m, "short_e"):
        out["short_e"] = np.array([_val(m.short_e[0, h]) for h in m.H])
        out["short_h"] = np.array([_val(m.short_h[0, h]) for h in m.H])
    if "price" in ts.reps:
        out["price"] = ts.reps["price"][0]
    return out


def summary(m) -> dict:
    v = pyo.value
    p = m._p
    hrs = m._hours
    d = design_of(m)
    out = {k: d[k] for k in CAP_VARS}
    out["pipe"] = next((k for k, x in d["pipe"].items() if x == 1), "none")
    out["C_grid"] = max(float(_val(m.C_grid)), 0.0)
    out["cost_parts"] = {k: float(v(e)) for k, e in m.cost_parts.items()}
    out["cost_parts"]["TSO fee"] = float(v(m.tso))
    out["cost_parts"]["Variable O&M"] = float(v(m.ann_vom))
    out["capex_total"] = float(v(m.capex_total))
    out["total_cost"] = float(v(m.total_cost))
    out["rev_e"], out["rev_h"] = float(v(m.rev_e)), float(v(m.rev_h))
    out["penalty"] = float(v(m.penalty))
    out["net_cost"] = float(v(m.net_cost))
    tot = lambda name: float((hrs * np.array([[_val(getattr(m, name)[r, h]) for h in m.H] for r in m.R])).sum())
    out["grid_mwh"], out["h2_kg"] = tot("p_grid"), tot("h2_sell")
    out["curt_mwh"] = tot("p_curt_off")
    wt, pv = m._ts.reps["wind_cf"], m._ts.reps["pv_cf"]
    out["gen_wind_mwh"] = float((hrs * wt).sum() * out["C_wt"])
    out["gen_pv_mwh"] = float((hrs * pv).sum() * out["C_pv"])
    out["short_e_mwh"] = out["short_h_kg"] = 0.0
    if hasattr(m, "short_e"):
        out["short_e_mwh"] = tot("short_e") + _val(m.short_ey)
        out["short_h_kg"] = tot("short_h") + _val(m.short_hy)
    for k in ("p_we", "p_pe", "p_cab_f", "h2_pipe", "h2fc_off", "h2fc_on", "bat_on_dis", "bat_off_dis"):
        out[f"sum_{k}"] = tot(k)
    out["config"], out["link_mode"] = p["config"], p["link_mode"]
    out.update(cable_choice(m))
    out["grid_distance_km"], out["pipe_distance_km"] = p["grid_distance_km"], p["pipe_distance_km"]
    # unit costs (v9 definitions, net of the other product's revenue)
    out["lcoe_net"] = (out["total_cost"] - out["rev_h"]) / out["grid_mwh"] if out["grid_mwh"] > 1 else float("nan")
    out["lcoh_net"] = (out["total_cost"] - out["rev_e"]) / out["h2_kg"] if out["h2_kg"] > 1 else float("nan")
    return out
