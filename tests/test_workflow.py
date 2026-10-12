"""End-to-end check on the Belle-Ile example: the design delivers every contract on the full year."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evolve_planner import params, report, workbook, workflow  # noqa: E402

EX = ROOT / "examples" / "belle_ile"


def _case(name):
    pre = json.loads((EX / "presets.json").read_text())[name]
    user = params.defaults()
    user.update({k: v for k, v in pre.items() if not k.startswith("_")})
    df = pd.read_csv(EX / "timeseries_2019.csv")
    return user, {"wind_cf": df.wind_cf.to_numpy(), "pv_cf": df.pv_cf.to_numpy(), "price": df.price_eur_mwh.to_numpy()}


@pytest.mark.slow
def test_hybrid_delivers_contracts():
    user, series = _case("hybrid_ppa")
    res = workflow.plan(user, series, n_blocks=730)
    f = res["final"]
    assert f["grid_mwh"] == pytest.approx(user["annual_demand_mwh"], rel=1e-4)
    assert f["h2_kg"] == pytest.approx(user["annual_h2_demand_kg"], rel=1e-4)
    assert f["short_e_mwh"] < 1 and f["short_h_kg"] < 1
    assert f["n_circuits"] >= 1 and f["C_cab"] <= f["n_circuits"] * f["circuit_rating_mw"] + 1e-6
    assert len(report.results_xlsx(res)) > 10_000


def test_workbook_round_trip(tmp_path):
    user, series = _case("hybrid_ppa")
    p = tmp_path / "w.xlsx"
    p.write_bytes(workbook.to_bytes(user, series))
    u2, s2, _ = workbook.from_file(p)
    assert u2["site_name"] == user["site_name"] and u2["sea_area_km2"] == user["sea_area_km2"]
    assert abs(s2["wind_cf"].mean() - series["wind_cf"].mean()) < 1e-5


def test_series_check_names_missing_price():
    user, series = _case("power_cfd")
    series.pop("price")
    msgs = workflow.check_series(series, params.derive(user))
    assert any("price" in m for m in msgs)


def test_levelized_costs_add_up():
    from evolve_planner.levelized import levelized
    f = {"grid_mwh": 200000.0, "h2_kg": 2e6, "sum_p_we": 0.0, "sum_p_pe": 90000.0, "gen_wind_mwh": 300000.0,
         "gen_pv_mwh": 0.0, "curt_mwh": 1000.0,
         "cost_parts": {"Offshore wind": 2.3e7, "Electrolyser (onshore)": 3e6, "Export cable": 1e6, "Fuel cells": 0.0}}
    lv = levelized(f)
    total = sum(f["cost_parts"].values())
    assert abs(lv["cost_to_electricity"] + lv["cost_to_hydrogen"] - total) < 1e-6
    assert lv["lcoe"] > 0 and lv["lcoh"] > 0 and 0 < lv["share_h2"] < 1


def test_connection_variants_and_hub_derivation():
    u = params.defaults()
    u.update(elec_connection="choose", h2_connection="choose", enable_pipe=True)
    assert len(params.connection_variants(u)) == 4
    d = params.derive(u, elec="hub", h2="tiein")
    assert d["elec_connection_used"] == "hub" and d["grid_injection_cap_mw"] <= u["hub_spare_mw"]
    assert d["pipe_spare_kgh"] == u["tiein_spare_kgh"] and d["pipe_fixed_eur"] == u["tiein_fee_eur"]


def test_profiles_replace_annual_volumes():
    user, series = _case("hybrid_ppa")
    user = dict(user, elec_delivery="profile", h2_delivery="profile")
    from evolve_planner import weather
    s, _ = weather.series_from_table(weather.read_table(Path(__file__).resolve().parents[1] / "examples/belle_ile/EVOLVE_hourly_demand_profiles_2019.xlsx"))
    series = {**series, **s}
    u = params.apply_profiles(user, series)
    assert abs(u["annual_demand_mwh"] - series["elec_demand"].sum()) < 1e-6
    assert abs(u["annual_h2_demand_kg"] - series["h2_demand"].sum()) < 1e-6
    assert workflow.check_series(series, params.derive(u)) == []
    low = dict(u, grid_injection_cap_mw=20.0)
    assert any("grid injection limit" in m for m in workflow.check_series(series, params.derive(low)))
