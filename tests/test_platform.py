"""Island platform cost model (version 0.10): configuration factors and the turbine-level cost block."""
import sys
from pathlib import Path

import pandas as pd
import pyomo.environ as pyo
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evolve_planner import model as M, params, tda, workflow  # noqa: E402

EX = ROOT / "examples" / "belle_ile"


def _derive(**kw):
    u = params.defaults()
    u.update(kw)
    return params.derive(u)


def test_bottom_fixed_factor_grows_with_depth():
    d30 = _derive(avg_water_depth_m=30.0)
    assert d30["config"] == "A_fixed"
    assert d30["platform_factor_h"] == pytest.approx(1.0) and d30["platform_factor_e"] == pytest.approx(1.0)
    d60 = _derive(avg_water_depth_m=60.0, fixed_floating_depth_m=70.0)
    assert d60["platform_factor_h"] == pytest.approx(0.72 + 0.28 * 2.0)
    assert d60["platform_factor_e"] == pytest.approx(0.78 + 0.22 * 2.0)
    d60b = _derive(avg_water_depth_m=60.0, fixed_floating_depth_m=70.0, platform_depth_exponent=1.56)
    assert d60b["platform_factor_h"] == pytest.approx(0.72 + 0.28 * 2.0 ** 1.56)
    assert d30["platform_fom_used"] == 0.02


def test_floating_central_factor():
    d = _derive(avg_water_depth_m=75.0, decentralized_h2=False)
    assert d["config"] == "B_floating_centralized"
    assert d["platform_factor_h"] == pytest.approx(0.72 * 1.1 + 0.28 * 3.0)   # 1.632
    assert d["platform_factor_e"] == pytest.approx(0.78 * 1.1 + 0.22 * 3.0)   # 1.518
    assert d["platform_fom_used"] == 0.03
    assert d["wind_capex_eur_mw"] == pytest.approx(3_429_000.0)


def test_dynamic_cable_section_is_priced_on_floating_islands_only():
    kw = dict(link_distance_override_km=55.0, decentralized_h2=False)
    fix = _derive(avg_water_depth_m=30.0, **kw)
    flo = _derive(avg_water_depth_m=75.0, **kw)
    a = next(c for c in fix["cable_options"] if c["key"] == "ac132_500_2")
    b = next(c for c in flo["cable_options"] if c["key"] == "ac132_500_2")
    assert a["parts"]["dynamic section"] == 0.0
    assert b["parts"]["dynamic section"] == pytest.approx(0.75 * a["parts"]["cable"] / 55.0 * 0.5)
    restricted = _derive(avg_water_depth_m=75.0, dyn_cable_restrict=True, **kw)
    assert {c["kv"] for c in restricted["cable_options"] if c["tech"] == "AC"} == {66.0}


def test_turbine_level_block():
    d = _derive(avg_water_depth_m=75.0, decentralized_h2=True, enable_pipe=True)
    assert d["config"] == "C_floating_decentralized" and d["turbine_level"]
    assert d["platform_factor_h"] == 0.0 and d["pipe_fixed_eur"] == pytest.approx(50_000.0)
    df = pd.read_csv(EX / "timeseries_2019.csv")
    series = {"wind_cf": df.wind_cf.to_numpy(), "pv_cf": df.pv_cf.to_numpy()}
    ts = tda.uniform(workflow._data(series), 73)
    m = M.build(ts, d)
    for v, x in (("C_wt", 30.0), ("C_ez_off", 20.0), ("C_cmp_off", 0.2), ("C_pv", 0.0), ("C_fc_off", 0.0),
                 ("P_bat_off", 0.0), ("C_cab", 0.0)):
        getattr(m, v).fix(x)
    val = lambda k: pyo.value(m.cost_parts[k], exception=False)
    ann = lambda n, f: params.crf(d["discount_rate"], n) + f
    kk = 1e3 * d["platform_escalation"] * d["platform_install_factor"]
    assert val("Island platform") == pytest.approx(0.0)
    integ = kk * 0.5 * d["platform_elec_coef"] * (20.0 + 0.2) * ann(d["platform_life"], d["platform_fom"])
    assert val("Turbine-level integration") == pytest.approx(integ)
    pipes = 550_000.0 * 1.0 / d["turbine_mw"] * 30.0 * ann(d["pipeline_life"], d["infield_pipe_fom"])
    assert val("In-field H2 pipelines") == pytest.approx(pipes)
    ez = d["elec_capex_eur_kw"] * 1e3 * d["offshore_premium"] * 1.3 * 20.0 * ann(d["elec_life"], d["elec_fom"])
    assert val("Electrolyser (island)") == pytest.approx(ez)
    wind = (d["wind_capex_eur_mw"] - 145_000.0) * 30.0 * ann(d["wind_life"], d["wind_fom"])
    assert val("Offshore wind") == pytest.approx(wind)


def test_central_platform_cost_uses_factors():
    d = _derive(avg_water_depth_m=75.0, decentralized_h2=False, enable_pipe=True)
    df = pd.read_csv(EX / "timeseries_2019.csv")
    ts = tda.uniform(workflow._data({"wind_cf": df.wind_cf.to_numpy(), "pv_cf": df.pv_cf.to_numpy()}), 73)
    m = M.build(ts, d)
    for v, x in (("C_ez_off", 10.0), ("C_cmp_off", 0.0), ("C_fc_off", 0.0), ("P_bat_off", 0.0), ("C_cab", 0.0)):
        getattr(m, v).fix(x)
    inv = 1e3 * 1.5 * d["platform_factor_h"] * d["platform_elec_coef"] * 10.0
    ann = params.crf(d["discount_rate"], d["platform_life"]) + 0.03
    assert pyo.value(m.cost_parts["Island platform"], exception=False) == pytest.approx(inv * ann)
    assert "Turbine-level integration" not in m.cost_parts
