"""Cost model: link catalogue (AC physics, HVDC cost function), pipeline capacities, exact selection."""
import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evolve_planner import cables, model as M, params, tda, workflow  # noqa: E402

EX = ROOT / "examples" / "belle_ile"


def _user(name="hybrid_ppa", **kw):
    pre = json.loads((EX / "presets.json").read_text())[name]
    u = params.defaults()
    u.update({k: v for k, v in pre.items() if not k.startswith("_")})
    u.update(kw)
    return u


def _opt(p, kv, mm2, m=2):
    return next(c for c in p["cable_options"] if c["key"] == f"ac{kv}_{mm2}_{m}")


def test_catalogue_and_ac_physics():
    p = params.derive(_user())
    opts = p["cable_options"]
    assert len(opts) == 4 * 4 * 2 + 1 and sum(c["tech"] == "DC" for c in opts) == 1
    # charging current and full rating of a 220 kV 1000 mm2 circuit (ABB data)
    ph0 = cables.ac_physics(220, 1000, 0.0, 2, 0.95, 1.5, 0.001)
    assert ph0["rating"] == pytest.approx(math.sqrt(3) * 220 * 0.825 * 0.95, rel=1e-6)
    assert cables.ac_physics(220, 1000, 1.0, 2, 1.0, 1.0, 0.0)["ic_a_km"] == pytest.approx(7.58, rel=0.01)
    # derating grows with length, and a mid-route reactor restores most of it
    r100 = cables.ac_physics(220, 1000, 100.0, 2, 0.95, 1.5, 0.001)["rating"]
    r100m = cables.ac_physics(220, 1000, 100.0, 4, 0.95, 1.5, 0.001)["rating"]
    assert 0.85 * ph0["rating"] < r100 < r100m < ph0["rating"]
    # installed AC cost at 220 kV 1000 mm2 reproduces ACER's AC submarine median (2.30 MEUR/km)
    c = _opt(p, 220, 1000)
    L = p["link_distance_km"]
    assert c["parts"]["cable"] / L == pytest.approx(2.30e6, rel=0.01)
    # a long route removes the AC options whose charging current uses up the conductor
    far = params.derive(_user(link_distance_override_km=400.0))
    assert not any(c["key"] == "ac275_500_2" for c in far["cable_options"])


def test_hvdc_cost_function_reproduces_vrana_hartel():
    u = _user(link_distance_override_km=150.0, avg_water_depth_m=30.0)      # bottom-fixed: no floating premium
    p = params.derive(u)
    dc = next(c for c in p["cable_options"] if c["tech"] == "DC")
    inv = dc["inv_circuit"] + dc["inv_mw"] * 2000.0
    assert inv == pytest.approx(2341.2e6, rel=1e-3)          # QQEF set, 2 GW over 150 km
    assert cables.dc_voltage_label(66) .startswith("HVDC, +/-150")
    assert cables.dc_voltage_label(2000).endswith("525 kV class")


def test_hub_offers_the_hub_voltage_only():
    p = params.derive(_user(elec_connection="hub"), elec="hub")
    assert {c["kv"] for c in p["cable_options"]} == {220.0}
    assert all(c["tech"] == "AC" for c in p["cable_options"])


def test_pipe_capacity_physics():
    p = params.derive(_user(enable_pipe=True))
    pc = p["pipe_classes"]
    caps = [pc[f"new_{d}in"]["cap_kgh"] for d in params.PIPE_SIZES]
    assert all(a < b for a, b in zip(caps, caps[1:]))
    f = p["pipe_offshore_factor"]
    assert pc["new_12in"]["capex_per_km"] == pytest.approx(f * (1.55e6 + 37857 * 12))
    assert 1.55e6 + 37857 * 14 == pytest.approx(2.08e6, rel=2e-3)        # ACER medians at 14 and 42 inch
    assert 1.55e6 + 37857 * 42 == pytest.approx(3.14e6, rel=2e-3)
    big = params.pipe_capacity_kgh(0.8758, 10, 70, 30, 288, 1.05, 0.05, 0.5, 122, 20.0)
    assert big["limit"] == "velocity" and big["u_ms"] == pytest.approx(20.0)


def _brute(ts, p):
    from pyomo.contrib.appsi.solvers import Highs
    m = M.build(ts, p, relax_pipe=True)
    sol = Highs()
    sol.config.load_solution = False
    best = math.inf
    CC, pipes = p["cable_options"], p["pipe_allowed"]
    for v in list(range(len(CC))) + ["none"]:
        for n in ([None] if v == "none" else range(1, 4)):
            for k in [None] + pipes:
                M.set_cable_option(m, p, v, n)
                for kk in pipes:
                    m.y_pipe[kk].fix(1.0 if kk == k else 0.0)
                r = sol.solve(m)
                if r.termination_condition.name == "optimal":
                    best = min(best, r.best_feasible_objective)
    return best


@pytest.mark.slow
@pytest.mark.parametrize("kw", [{}, {"enable_pipe": True, "enable_ez_on": False}, {"link_distance_override_km": 200.0}])
def test_selection_is_exact(kw):
    """The branch and bound returns the same cost as trying every option, circuit count and pipe."""
    u = _user(**kw)
    df = pd.read_csv(EX / "timeseries_2019.csv")
    series = {"wind_cf": df.wind_cf.to_numpy(), "pv_cf": df.pv_cf.to_numpy(), "price": df.price_eur_mwh.to_numpy()}
    p = params.derive(u)
    ts = tda.tpca(workflow._data(series), 24, workflow._cut_attrs(series, p))
    m, info = M.solve_sizing(ts, p)
    assert info["objective"] == pytest.approx(_brute(ts, p), rel=1e-6, abs=1.0)
    assert info["evaluated"] < 0.25 * info["leaves"]        # the bounds prune most of the catalogue
