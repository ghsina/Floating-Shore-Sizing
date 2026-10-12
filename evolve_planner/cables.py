"""Export-link catalogue: every candidate AC and DC option, with its physics and cost on a given route.

Each option is one complete link type. For a route of L km the function `options` returns, per option:

    rating       usable active power of one circuit (AC) or of one converter unit (DC), MW
    inv_circuit  investment per circuit / unit that does not scale with the MW used, EUR
    inv_mw       investment per MW of capacity used, EUR/MW
    plat         1 if the island's AC substation platform cost applies (AC), 0 if the offshore converter
                 station is costed in inv_circuit / inv_mw (DC)
    rho          share of the power lost in the cable at full loading of the installed rating (-)
    eff          converter efficiency, both stations (DC), 1 for AC
    cap_from_n   1 if the loss reference is the installed circuits' rating (AC), 0 if it is the MW built (DC)
    noload_mw    losses per energised circuit that do not depend on the load (charging current, dielectric), MW
    fom, fee     fixed O&M share and grid fee

AC physics (one three-core XLPE copper circuit, 50 Hz):
    charging current        i_c = omega C' U / sqrt(3)                                   [A/km]
    usable rating           P = sqrt(3) U pf sqrt(I_r^2 - (i_c L / m)^2)                  [MW]
                            m = 2 with shunt reactors at both ends, 4 with an extra mid-route reactor
    reactive power          Q = omega C' U^2 L, fully compensated, split over the reactor sites   [MVAr]
    load losses             3 I^2 R_ac,90 k_loss L, with I = P / (sqrt(3) U pf)
    no-load losses          R_ac,90 k_loss i_c^2 L^3 / m^2  +  omega C' U^2 tan(delta) L
Sources: ABB "XLPE Submarine Cable Systems" user's guide (C', ampacity); IEC 60287 method for R_ac at 90 C;
Colla et al. (2009) for the derating with compensation; Perez-Rua et al. (2022) for the loss factor 1.5.

DC cost (Vrana & Hartel 2018, EPSR 160, Table 6, "QQEF" set; two converter nodes, one offshore station):
    cable      B_lp l p + ceil(p / 2 GW) (B_l l + B_0)
    converter  2 x (N_p p + ceil(p / 2 GW) N_0)
    offshore   S_p p + ceil(p / 2 GW) S_0           (x floating premium on a floating island, concept B)
"""
from __future__ import annotations

import math

OMEGA = 2 * math.pi * 50.0

# ABB XLPE submarine cable systems guide, three-core copper: capacitance uF/km by voltage and cross-section,
# continuous current rating (A) by cross-section (IEC 60287, seabed 20 C, burial 1 m, 1.0 K m/W, 90 C).
ABB_C_UF_KM = {
    66: {500: 0.29, 630: 0.32, 800: 0.35, 1000: 0.38},
    132: {500: 0.20, 630: 0.21, 800: 0.23, 1000: 0.25},
    220: {500: 0.14, 630: 0.16, 800: 0.17, 1000: 0.19},
    275: {500: 0.14, 630: 0.16, 800: 0.17, 1000: 0.18},
}
ABB_AMPACITY_A = {500: 655, 630: 715, 800: 775, 1000: 825}
# AC resistance at 90 C (IEC 60287-1-1 method, round compacted copper), ohm/km
R_AC90_OHM_KM = {500: 0.047, 630: 0.038, 800: 0.032, 1000: 0.027}
# NREL ORBIT cable library, supply cost per km of one cable, 2024 USD. Missing sizes are filled with the
# ECN cable cost function's ratio to the nearest ORBIT entry of the same voltage (see supply_usd_km).
ORBIT_SUPPLY_USD_KM = {
    (66, 630): 650_000.0,
    (132, 500): 528_487.0,
    (220, 500): 799_459.0, (220, 630): 853_557.0, (220, 800): 932_902.0, (220, 1000): 1_500_902.0,
    (275, 1200): 1_374_065.0,
}
AC_KV = (66, 132, 220, 275)
AC_MM2 = (500, 630, 800, 1000)


def _ecn(mm2: float, kv: float) -> float:
    """ECN AC cable cost function (Bedon 2017, as reported by Ramirez Gonzalez 2018), kEUR/km: shape only."""
    return 0.2625 * mm2 + 4.985 * kv - 28.7


def supply_usd_km(kv: int, mm2: int) -> tuple[float, str]:
    if (kv, mm2) in ORBIT_SUPPLY_USD_KM:
        return ORBIT_SUPPLY_USD_KM[(kv, mm2)], "ORBIT 2024"
    anchors = [(m, c) for (v, m), c in ORBIT_SUPPLY_USD_KM.items() if v == kv]
    m0, c0 = min(anchors, key=lambda t: abs(t[0] - mm2))
    return c0 * _ecn(mm2, kv) / _ecn(m0, kv), f"ORBIT 2024 {kv} kV {m0} mm2 x ECN size ratio"


def transformer_eur(mva: float) -> float:
    """One power transformer, Lakshmanan et al. (2015) via Ramirez Gonzalez (2018): 1.15(105 S^0.447 - 122.4) kEUR."""
    return 1e3 * 1.15 * (105.0 * mva ** 0.447 - 122.4)


def ac_physics(kv: int, mm2: int, L: float, m: int, pf: float, k_loss: float, tan_delta: float) -> dict:
    C = ABB_C_UF_KM[kv][mm2] * 1e-6                                # F/km
    U = kv * 1e3
    ic = OMEGA * C * U / math.sqrt(3.0)                            # A/km
    Ir = ABB_AMPACITY_A[mm2]
    Ia2 = Ir ** 2 - (ic * L / m) ** 2
    rating = math.sqrt(3.0) * U * pf * math.sqrt(Ia2) / 1e6 if Ia2 > 0 else 0.0     # MW
    R = R_AC90_OHM_KM[mm2] * k_loss                                # effective ohm/km incl. screen and armour
    q_mvar = OMEGA * C * U ** 2 * L / 1e6                          # total charging MVAr of one circuit
    rho = (R * L * rating / (kv ** 2 * pf ** 2)) if rating > 0 else 1.0        # loss share at full rating
    noload = (R * (ic / 1e3) ** 2 * L ** 3 / m ** 2) + (q_mvar * tan_delta)     # MW
    return {"rating": rating, "q_mvar": q_mvar, "rho": rho, "noload_mw": noload, "ic_a_km": ic,
            "rating0": math.sqrt(3.0) * U * pf * Ir / 1e6, "s_mva": math.sqrt(3.0) * U * Ir / 1e6}


def dc_voltage_label(mw: float) -> str:
    """Typical VSC voltage class for a link of this size (industry practice; reporting only)."""
    if mw <= 600:
        return "HVDC, +/-150 to 200 kV class"
    if mw <= 1250:
        return "HVDC, +/-320 kV class"
    return "HVDC, +/-525 kV class"


def options(p: dict, d: dict, ec: str) -> list[dict]:
    """All candidate export-link options on this route. Empty if no cable may be built."""
    if not d["elec_export_allowed"]:
        return []
    L = float(d["link_distance_km"])
    out = []
    usd = p["usd_eur"]
    op = p["offshore_premium"]
    if p.get("cable_cost_model", "catalogue") == "v9 linear":
        hvdc = ec != "hub" and (L > p["hvac_hvdc_threshold_km"] or p.get("export_voltage", "auto") == "HVDC")
        if hvdc:
            inv = p["v9_converter_pair_eur_mw"] * d["hvdc_float_premium"] + p["hvdc_cable_eur_mw_km"] * L
            eff, fee, fom, name = (1.0 - (p["hvdc_converter_loss"] + p["hvdc_cable_loss_per_km"] * L),
                                   0.0, p["cable_fom_hvdc"], "HVDC (v9 linear)")
        else:
            cap = max(d.get("grid_injection_cap_mw", p["grid_injection_cap_mw"]), 1.0)
            inv = (p["hvac_var_eur_mw_km"] + p["hvac_fix_eur_km"] / cap) * L
            fee = p["hub_access_fee_eur_mw_yr"] if ec == "hub" else 0.0   # own link: grid fee on injection
            eff, fom, name = 1.0 - p["hvac_loss_per_km"] * L, p["cable_fom_hvac"], "HVAC (v9 linear)"
        out.append(dict(key="v9", name=name, tech="DC" if hvdc else "AC", kv=float("nan"), mm2=0, scheme="",
                        rating=p["cap_ub_mw"], max_n=1, inv_circuit=0.0, inv_mw=inv, plat=1.0, rho=0.0, eff=eff,
                        cap_from_n=0.0, noload_mw=0.0, fom=fom, fee=fee, parts={}))
        return _finish(p, d, out)

    # An own link pays no fee on its own capacity: the TSO fee is charged on the capacity injected into the
    # existing grid (model variable C_grid). A hub's access fee is charged on the cable to the hub.
    fee_ac = p["hub_access_fee_eur_mw_yr"] if ec == "hub" else 0.0
    want = str(p.get("export_voltage", "auto"))
    if "DC" in want:                         # older workbooks: "320 kV DC", "525 kV DC"
        want = "HVDC"
    elif want != "auto":
        want = want.replace(" AC", "")
        if want not in ("66 kV", "132 kV", "220 kV", "275 kV"):
            want = "auto"
    # ---- AC options -------------------------------------------------------------------------
    if want != "HVDC":
        kvs = list(AC_KV)
        if ec == "hub":
            kvs = [min(AC_KV, key=lambda v: abs(v - p["hub_voltage_kv"]))]
        elif want != "auto":
            kvs = [int(want.split()[0])]
        schemes = [("ends", 2)] + ([("ends + mid-route", 4)] if p.get("allow_midroute", True) and ec != "hub" else [])
        inst = p["ac_install_eur_km"]
        floating_b = d.get("config") == "B_floating_centralized"
        dyn_km = p.get("dyn_cable_km", 0.0) if floating_b else 0.0
        if floating_b and p.get("dyn_cable_restrict", False):
            kvs = [v for v in kvs if v <= p.get("dyn_cable_max_kv", 66.0) + 1e-9] or kvs[:1]
        for kv in kvs:
            for mm2 in AC_MM2:
                sup_usd, sup_src = supply_usd_km(kv, mm2)
                cable_km = sup_usd * usd * p["ac_supply_factor"] + inst
                for sname, m in schemes:
                    ph = ac_physics(kv, mm2, L, m, p["grid_power_factor"], p["cable_loss_factor"], p["cable_tan_delta"])
                    if ph["rating"] <= 0.05 * ph["rating0"]:
                        continue          # the charging current uses up the cable: not a usable option
                    trafo = transformer_eur(ph["s_mva"]) * (1.0 + op)          # island end x offshore premium
                    sites = (0.5, 0.5) if m == 2 else (0.25, 0.5, 0.25)        # island, (mid), shore
                    react = sum(p["reactor_eur_mvar"] * ph["q_mvar"] * s + p["reactor_fixed_eur"] for s in sites)
                    react += p["reactor_eur_mvar"] * ph["q_mvar"] * sites[0] * (op - 1.0)   # island reactor premium
                    mid = p["midroute_platform_eur"] if m == 4 else 0.0
                    dyn = p.get("dyn_cable_premium", 0.0) * cable_km * min(dyn_km, L)   # floating: dynamic section
                    parts = {"cable": cable_km * L, "transformers": trafo, "reactors": react, "dynamic section": dyn}
                    out.append(dict(
                        key=f"ac{kv}_{mm2}_{m}", tech="AC", kv=float(kv), mm2=mm2, scheme=sname,
                        name=f"{kv} kV AC, 3x{mm2} mm2 Cu, reactors at {'both ends' if m == 2 else 'both ends and mid-route'}",
                        rating=ph["rating"], max_n=int(p["cable_max_circuits"]),
                        inv_circuit=cable_km * L + trafo + react + dyn, inv_mw=0.0, plat=1.0, rho=ph["rho"], eff=1.0,
                        cap_from_n=1.0, noload_mw=ph["noload_mw"], fom=p["cable_fom_hvac"], fee=fee_ac,
                        q_mvar=ph["q_mvar"], fixed_once=mid, parts=parts, supply_source=sup_src,
                        rating0=ph["rating0"]))
    # ---- DC option (Vrana & Hartel 2018) -------------------------------------------------------
    if ec != "hub" and want in ("auto", "HVDC"):
        e = p["hvdc_cost_factor"]
        prem = d["hvdc_float_premium"]
        unit = p["hvdc_unit_mw"]
        ld = (1.0 + p.get("dyn_cable_premium", 0.0) * min(p.get("dyn_cable_km", 0.0), L) / L
              if d.get("config") == "B_floating_centralized" and L > 0 else 1.0)       # dynamic section premium
        per_unit = e * (p["vh_bl_eur_km"] * L * ld + p["vh_b0_eur"] + 2 * p["vh_n0_eur"] + prem * p["vh_s0_eur"])
        per_mw = e * (p["vh_blp_eur_mw_km"] * L * ld + 2 * p["vh_np_eur_mw"] + prem * p["vh_sp_eur_mw"])
        out.append(dict(
            key="dc", tech="DC", kv=float("nan"), mm2=0, scheme="", name="HVDC VSC link",
            rating=unit, max_n=int(p["cable_max_circuits"]), inv_circuit=per_unit, inv_mw=per_mw, plat=0.0,
            rho=p["hvdc_cable_loss_per_100km"] * L / 100.0, eff=1.0 - p["hvdc_converter_loss"], cap_from_n=0.0,
            noload_mw=0.0, fom=p["cable_fom_hvdc"], fee=0.0, fixed_once=0.0,
            parts={"per unit": per_unit, "per MW": per_mw}))
    return _finish(p, d, out)


def _finish(p: dict, d: dict, out: list[dict]) -> list[dict]:
    from .params import crf
    a = crf(p["discount_rate"], p["cable_life"])
    # the island platform's part per MW of export capacity (electrical platform structure c_E), annualised
    plat_mw = (1e3 * p["platform_escalation"] * p["platform_install_factor"] * d["platform_factor_e"]
               * p["platform_cable_coef"] * (crf(p["discount_rate"], p["platform_life"]) + d["platform_fom_used"]))
    for c in out:
        c.setdefault("fixed_once", 0.0)
        c["fac"] = a + c["fom"]
        c["annual_noload"] = 8760.0 * c["noload_mw"] * p["loss_value_eur_mwh"]

        def annual(mw, c=c):
            """Annual cost of carrying `mw` with this option: whole circuits / units, no losses in the balance."""
            if mw <= 0:
                return 0.0
            n = math.ceil(mw / c["rating"] - 1e-9)
            if n > c["max_n"]:
                return math.inf
            return (c["fac"] * ((c["inv_circuit"]) * n + c["fixed_once"] + c["inv_mw"] * mw) + c["annual_noload"] * n
                    + c["fee"] * mw + c["plat"] * plat_mw * mw)
        c["annual"] = annual
        c["full_use_eur_mw"] = annual(c["rating"]) / c["rating"] if c["rating"] > 0 else math.inf
        c["plat_mw"] = plat_mw
    return out
