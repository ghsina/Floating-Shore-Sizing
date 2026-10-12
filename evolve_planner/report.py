"""Results workbook: everything a partner needs to check or reuse a design."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

from .levelized import levelized
from .params import SPEC

CAP_ROWS = [("C_wt", "Offshore wind", "MW"), ("C_pv", "Floating PV", "MW"),
            ("C_ez_off", "Electrolyser on the island", "MW"), ("C_ez_on", "Electrolyser onshore", "MW"),
            ("C_cmp_off", "Compressor on the island", "MW"), ("C_cmp_on", "Compressor onshore", "MW"),
            ("C_fc_off", "Fuel cell on the island", "MW"), ("C_fc_on", "Fuel cell onshore", "MW"),
            ("C_cab", "Export cable", "MW"), ("E_bat_off", "Battery on the island, energy", "MWh"),
            ("P_bat_off", "Battery on the island, power", "MW"), ("E_bat_on", "Battery onshore, energy", "MWh"),
            ("P_bat_on", "Battery onshore, power", "MW"), ("E_tank_off", "Hydrogen tank on the island", "kg"),
            ("E_tank_on", "Hydrogen tank onshore", "kg")]

HOURLY_COLS = [("gen_wind", "wind generation MW"), ("gen_pv", "PV generation MW"),
               ("p_curt_off", "curtailed MW"), ("p_we", "island electrolyser MW"),
               ("p_cab_f", "cable to shore MW"), ("p_cab_r", "cable to island MW"), ("p_grid", "to grid MW"),
               ("p_pe", "onshore electrolyser MW"), ("bat_off_ch", "island battery charge MW"),
               ("bat_off_dis", "island battery discharge MW"), ("bat_on_ch", "onshore battery charge MW"),
               ("bat_on_dis", "onshore battery discharge MW"), ("h2_off", "H2 made on island kg/h"),
               ("h2_on", "H2 made onshore kg/h"), ("h2_pipe", "H2 in pipeline kg/h"),
               ("h2_sell", "H2 delivered kg/h"), ("h2fc_off", "H2 to island fuel cell kg/h"),
               ("h2fc_on", "H2 to onshore fuel cell kg/h"), ("soc_bat_off", "island battery level MWh"),
               ("soc_bat_on", "onshore battery level MWh"), ("soc_tank_off", "island tank level kg"),
               ("soc_tank_on", "onshore tank level kg"), ("short_e", "electricity shortfall MW"),
               ("short_h", "hydrogen shortfall kg/h"), ("price", "price EUR/MWh")]


def kpi_rows(res: dict) -> list[tuple[str, float, str]]:
    f, r = res["final"], res["reduced"]
    lv = res.get("levelized") or levelized(f)
    d = res.get("derived", {})
    return [
        ("LCOE, levelized cost of electricity delivered (energy allocation)", lv["lcoe"], "EUR/MWh"),
        ("LCOH, levelized cost of hydrogen delivered (energy allocation)", lv["lcoh"], "EUR/kg"),
        ("LCOH in energy terms (LHV)", lv["lcoh_eur_mwh"], "EUR/MWh H2"),
        ("Cost of generation (wind + PV) per MWh generated", lv["lcoe_generation"], "EUR/MWh"),
        ("Share of shared costs allocated to hydrogen", lv["share_h2"], "fraction"),
        ("Electricity connection", d.get("elec_connection_used", "direct"), ""),
        ("Export voltage", d.get("export_voltage_used", ""), ""),
        ("Rating per circuit", d.get("circuit_rating_mw", float("nan")), "MW"),
        ("Export link built", f.get("cable_class", ""), ""),
        ("Circuits built (AC) or converter units (DC)", f.get("n_circuits", 0), ""),
        ("Link losses", f.get("cable_loss_mwh", float("nan")), "MWh/yr"),
        ("Reactive compensation", f.get("cable_reactive_mvar", 0.0), "MVAr"),
        ("Cable investment per MW used", f.get("cable_capex_eur_mw", float("nan")), "EUR/MW"),
        ("Cable efficiency over the route", f.get("cable_eff", float("nan")), ""),
        ("Hydrogen connection", d.get("h2_connection_used", "direct"), ""),
        ("Net annual cost (cost minus revenue)", f["net_cost"], "EUR/yr"),
        ("Total annual cost", f["total_cost"], "EUR/yr"),
        ("Electricity revenue", f["rev_e"], "EUR/yr"),
        ("Hydrogen revenue", f["rev_h"], "EUR/yr"),
        ("Investment (CAPEX, total)", f["capex_total"], "EUR"),
        ("Electricity delivered to the grid", f["grid_mwh"], "MWh/yr"),
        ("Hydrogen delivered", f["h2_kg"], "kg/yr"),
        ("Curtailed electricity", f["curt_mwh"], "MWh/yr"),
        ("Undelivered electricity", f["short_e_mwh"], "MWh/yr"),
        ("Undelivered hydrogen", f["short_h_kg"], "kg/yr"),
        ("Net cost of electricity (cost minus H2 revenue, per MWh)", f["lcoe_net"], "EUR/MWh"),
        ("Net cost of hydrogen (cost minus electricity revenue, per kg)", f["lcoh_net"], "EUR/kg"),
        ("Configuration", f["config"], ""), ("Export link", f["link_mode"], ""), ("Pipeline", f["pipe"], ""),
        ("Cable route length", f["grid_distance_km"], "km"),
        ("Cable route found by", d.get("grid_route_how", ""), ""),
        ("Pipeline route length", f["pipe_distance_km"], "km"),
        ("Pipeline route found by", d.get("pipe_route_how", ""), ""),
        ("TDA blocks", res["tda"]["blocks"], ""), ("TDA chord error (share of range)", res["tda"]["eps"], ""),
        ("Net cost on the TDA year (before full-year check)", r["net_cost"], "EUR/yr"),
        ("Repair factor, generation", res["scale"].get("generation", 1.0), "x"),
        ("Repair factor, conversion", res["scale"].get("conversion", 1.0), "x"),
        ("Repair factor, storage", res["scale"].get("storage", 1.0), "x"),
        ("Run time", res["timing"]["total_s"], "s"), ("Solver", res["solver"], ""),
    ]


def results_xlsx(res: dict) -> bytes:
    f = res["final"]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(kpi_rows(res), columns=["item", "value", "unit"]).to_excel(xw, sheet_name="Summary", index=False)
        pd.DataFrame([(lab, f[k], u) for k, lab, u in CAP_ROWS], columns=["component", "size", "unit"]) \
            .to_excel(xw, sheet_name="Capacities", index=False)
        pd.DataFrame([(k, v) for k, v in f["cost_parts"].items()], columns=["component", "EUR per year"]) \
            .to_excel(xw, sheet_name="Annual costs", index=False)
        lv = res.get("levelized") or levelized(f)
        pd.DataFrame([{"component": x["component"], "allocation rule": x["rule"], "annual cost EUR": x["annual_cost"],
                       "to electricity EUR": x["to_electricity"], "to hydrogen EUR": x["to_hydrogen"],
                       "EUR per MWh delivered": x["eur_per_mwh"], "EUR per kg delivered": x["eur_per_kg"]}
                      for x in lv["rows"]]).to_excel(xw, sheet_name="Levelized costs", index=False)
        opts = res.get("connection_options") or []
        if opts:
            pd.DataFrame(opts).to_excel(xw, sheet_name="Connection options", index=False)
        h = res["hourly"]
        df = pd.DataFrame({"hour": np.arange(1, 8761)})
        for k, lab in HOURLY_COLS:
            if h.get(k) is not None:
                df[lab] = np.round(np.asarray(h[k], float)[:8760], 4)
        df.to_excel(xw, sheet_name="Hourly (full year)", index=False)
        d = res["tda"]["diag"]
        pd.DataFrame({"block": np.arange(1, len(d["block_len"]) + 1), "hours": d["block_len"],
                      "ends at hour": d["block_ends"] + 1}).to_excel(xw, sheet_name="TDA blocks", index=False)
        by = {s.key: s for s in SPEC}
        inp = res["inputs"]
        pd.DataFrame([(s.group, s.key, s.label, inp.get(s.key, s.default), s.unit,
                       "placeholder" if s.step3 else "", "" if inp.get(s.key, s.default) == s.default else "changed",
                       s.source)
                      for s in SPEC], columns=["group", "key", "label", "value", "unit", "status", "vs default",
                                               "source of the default"]) \
            .to_excel(xw, sheet_name="Inputs used", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col[:40])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    return buf.getvalue()
