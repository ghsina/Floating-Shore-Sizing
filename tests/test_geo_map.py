"""Coastline routes, route-length options and the interactive map."""
import pytest
import time

import numpy as np

from evolve_planner import geo, params
from ui import drawings, livemap


def test_sea_route_belle_ile():
    tot, off, on, _, _ = geo.route_km(47.38, -3.55, 47.64, -3.16)
    straight = params.haversine_km(47.38, -3.55, 47.64, -3.16)
    assert straight < tot < 1.4 * straight
    assert off > on >= 0


def test_far_points_are_fast_and_go_round_capes():
    t = time.time()
    tot = geo.route_km(56.6, 6.4, 47.64, -3.16)[0]        # North Sea to Lorient: round Brittany
    assert time.time() - t < 15
    assert tot > 1.15 * params.haversine_km(56.6, 6.4, 47.64, -3.16)


def test_route_methods():
    u = params.defaults()
    d = params.derive(u)
    assert d["grid_route_how"] == "sea route"
    u["route_method"] = "straight line"
    d2 = params.derive(u)
    assert d2["grid_route_how"] == "straight line x factor"
    assert abs(d2["grid_distance_km"] - 1.2 * d2["straight_grid_km"]) < 1e-6
    u["link_distance_override_km"] = 55.0
    assert params.derive(u)["grid_distance_km"] == 55.0
    u.update(elec_connection="hub", route_method="sea route")      # the entered length is for the own cable only
    d3 = params.derive(u)
    assert d3["grid_distance_km"] < 20 and d3["tso_fee"] == u["hub_access_fee_eur_mw_yr"]


def test_exposed_constants_are_used():
    u = params.defaults()
    u.update(cable_fom_hvac=0.02, tso_fee_eur_mw_yr=1234.0, platform_float_hull_ratio=4.0, batt_max_mwh=7.0,
             comp_gamma=1.30)
    d = params.derive(u)
    assert d["cable_fom"] == 0.02 and d["tso_fee"] == 1234.0
    assert d["platform_factor_h"] == pytest.approx(0.72 * 1.1 + 0.28 * 4.0) and d["batt"]["on"]["max_e"] == 7.0
    assert d["comp_mwh_per_kg"] < params.derive(params.defaults())["comp_mwh_per_kg"]


def test_nearest_shore_and_land():
    km, lat, lon = geo.nearest_shore(47.38, -3.55)
    assert 5 < km < 40
    assert geo.is_land(48.1, -1.7) and not geo.is_land(47.38, -3.55)


def test_atlas_for_moved_site():
    for kw in (dict(site_lat=56.6, site_lon=6.4), dict(site_lat=5.0), dict(site_lat=89.0)):
        u = params.defaults()
        u.update(kw)
        t = time.time()
        assert "<svg" in drawings.atlas_html(u, animate=False)
        assert time.time() - t < 20


def test_livemap_plan_and_result():
    u = params.defaults()
    u.update(elec_connection="choose", h2_connection="choose")
    deck, legend, links = livemap.build(u, params.derive(u))
    assert len(links) == 6 and deck.to_json()
    final = {"C_cab": 66.8, "pipe": "new_12in", "C_wt": 79.0, "C_pv": 5.0, "C_ez_off": 10.0, "E_bat_off": 0.0,
             "C_ez_on": 3.0, "E_bat_on": 0.0, "grid_mwh": 2e5, "h2_kg": 2e6}
    d = params.derive(u, "hub", "direct")
    deck, legend, links = livemap.build(u, d, final, {"h2_pipe": np.full(8760, 300.0)})
    assert [x["status"] for x in links] == ["built", "existing", "built"]
