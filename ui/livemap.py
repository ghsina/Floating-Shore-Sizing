"""Interactive map (pydeck) of a planned or optimised island and its links.

Before a run it shows what the model will assume: the island, the usable sea area, every candidate
link with the route the model measures, and the onshore and offshore end points. After a run it shows
what was built: turbines placed in the sea area, the export cable and pipeline drawn with a width
proportional to their capacity, the voltage and number of circuits, and the existing links of a hub
or a pipeline tie-in. Every element has a tooltip with its numbers.

Routes come from evolve_planner.geo.route_path (shortest sea path on the 1 km coastline), so the map
shows the same lengths the model uses when the route method is "sea route".
"""
from __future__ import annotations

import math

import numpy as np
import pydeck as pdk

from evolve_planner import geo

POWER = [221, 107, 30]
H2 = [19, 151, 154]
NAVY = [14, 42, 59]
GREY = [112, 124, 132]
ZONE = [31, 111, 139]


def _circle(lat, lon, r_km, n=72):
    kx = geo.KM_PER_DEG * math.cos(math.radians(lat))
    return [[lon + r_km * math.cos(t) / kx, lat + r_km * math.sin(t) / geo.KM_PER_DEG]
            for t in np.linspace(0, 2 * math.pi, n)]


def _turbines(lat, lon, r_km, n):
    """n positions on a staggered grid inside the circle, nearest the centre first."""
    if n <= 0:
        return []
    sp = max(r_km * math.sqrt(math.pi / n) * 0.95, 0.4)
    kx = geo.KM_PER_DEG * math.cos(math.radians(lat))
    cand = []
    k = int(r_km / sp) + 2
    for i in range(-k, k + 1):
        for j in range(-k, k + 1):
            x, y = (j + (0.5 if i % 2 else 0)) * sp, i * sp * 0.866
            if math.hypot(x, y) <= r_km * 0.97:
                cand.append((math.hypot(x, y), x, y))
    cand.sort()
    return [[lon + x / kx, lat + y / geo.KM_PER_DEG] for _, x, y in cand[:n]]


def _coast(lat_s, lat_n, lon_w, lon_e, max_cells=90_000):
    """Land polygons from the bundled coastline, so the map reads even when the basemap cannot load."""
    try:
        land, lats, lons, ok = geo.land_window(max(lat_s, -89.0), min(lat_n, 89.0), max(lon_w, -180.0),
                                               min(lon_e, 180.0))
        if not ok or not land.any():
            return []
        land, lats, lons = geo.coarsen(land, lats, lons, max_cells)
        out = []
        for rings in geo.filled(geo.smooth_field(land, 0.7), lats, lons, 0.5, 2.0):
            out.append({"rings": [[[round(float(lo), 4), round(float(la), 4)] for la, lo in r[::2]] for r in rings
                                  if len(r) > 6]})
        return [o for o in out if o["rings"]]
    except Exception:  # noqa: BLE001
        return []


def _route(a, b, method):
    """(offshore path, onshore path, total km) as [lon, lat] lists."""
    if method == "sea route":
        try:
            pts, lf, tot, off = geo.route_path(a[0], a[1], b[0], b[1])
            pts = [[p[1], p[0]] for p in pts]
            k = min(range(len(pts)), key=lambda i: (pts[i][0] - lf[1]) ** 2 + (pts[i][1] - lf[0]) ** 2)
            return pts[:k + 1], (pts[k:] if tot - off > 0.2 else []), tot
        except Exception:  # noqa: BLE001
            pass
    return [[a[1], a[0]], [b[1], b[0]]], [], geo._gc_km(a, b)


def build(user: dict, d: dict, final: dict | None = None, hourly: dict | None = None, height=480):
    """Returns (deck, legend rows, link rows). `d` is params.derive(user) or the derived dict of a result."""
    u = user
    built = final is not None
    method = u.get("route_method", "sea route")
    site = (float(u["site_lat"]), float(u["site_lon"]))
    grid = (float(u["grid_lat"]), float(u["grid_lon"]))
    hpt = (float(u["h2_lat"]), float(u["h2_lon"]))
    hub = (float(u["hub_lat"]), float(u["hub_lon"]))
    tie = (float(u["tiein_lat"]), float(u["tiein_lon"]))
    ec = d.get("elec_connection_used", "direct")
    hc = d.get("h2_connection_used", "direct")
    if not built:          # before a run "choose" shows both candidates
        ec_show = {"direct": ["direct"], "hub": ["hub"], "choose": ["direct", "hub"]}[u.get("elec_connection", "direct")]
        hc_show = {"direct": ["direct"], "tiein": ["tiein"], "choose": ["direct", "tiein"]}[u.get("h2_connection", "direct")]
    else:
        ec_show, hc_show = [ec], [hc]

    cab_mw = float(final["C_cab"]) if built else None
    pipe = final.get("pipe", "none") if built else None
    peak_kgh = float(np.max(hourly["h2_pipe"])) if (built and hourly is not None and pipe != "none") else 0.0
    want_cable = bool(u.get("enable_cable", True)) and d.get("elec_export_allowed", True)
    want_pipe = (bool(u.get("enable_pipe", True)) and bool(d.get("pipe_allowed", True))
                 and (u.get("use_case") != "Power-led" or bool(u.get("sell_surplus"))))
    multi = len(d.get("cable_classes") or []) > 1
    volt = ((final or {}).get("export_voltage_used") if built else None) or (
        f"voltage chosen by the run (cheapest at the grid limit: {d.get('cable_preview', '')})" if multi
        else d.get("export_voltage_used", ""))
    rating = float(((final or {}).get("circuit_rating_mw") if built else None) or d.get("circuit_rating_mw") or 0)
    if rating != rating:        # NaN: per-MW cable cost, no circuits
        rating = 0.0

    paths, points, links = [], [], []

    def add_path(path, color, width, name, info, alpha=235):
        if len(path) >= 2:
            paths.append(dict(path=path, color=color + [alpha], width=width, name=name, info=info))

    # ---- electricity -------------------------------------------------------------------------
    if want_cable and (not built or cab_mw > 1e-3):
        for opt in ec_show:
            end = hub if opt == "hub" else grid
            off, on, km = _route(site, end, method)
            if built:
                n = int(final["n_circuits"]) if final.get("n_circuits") else (
                    math.ceil(cab_mw / rating - 1e-6) if rating > 0 else 1)
                width = float(np.clip(3 + cab_mw / 40, 3, 16))
                info = (f"{cab_mw:,.0f} MW · {volt} · {n} × {rating:,.0f} MW circuit{'s' if n > 1 else ''} · "
                        f"{d['grid_distance_km']:,.0f} km ({d.get('grid_route_how', method)})")
                km_show = d["grid_distance_km"]
            else:
                width = 4
                dd = d if opt == ec else None
                info = (f"candidate · {volt if dd else 'own cable'} · "
                        f"{(dd['grid_distance_km'] if dd else km):,.0f} km measured by {d.get('grid_route_how', method)}")
                km_show = dd["grid_distance_km"] if dd else km
            name = f"Export cable to {u['hub_name'] if opt == 'hub' else u['grid_name']}"
            add_path(off, POWER, width, name, info, 235 if built else 200)
            add_path(on, POWER, max(width * 0.6, 2), name + " (onshore)", "onshore section after the landfall", 150)
            links.append({"link": name, "status": "built" if built else "candidate",
                          "length km": round(km_show, 1),
                          "capacity": f"{cab_mw:,.0f} MW" if built else "sized by the run",
                          "voltage": volt if (built or opt == ec) else "",
                          "length from": d.get("grid_route_how", method) if (built or opt == ec) else method})
            if opt == "hub":
                off2, on2, km2 = _route(hub, grid, method)
                add_path(off2 + on2[1:], GREY, 2.5, f"Existing link: {u['hub_name']} to shore",
                         f"owned by the hub operator · {u['hub_spare_mw']:,.0f} MW spare · "
                         f"{u['hub_voltage_kv']:,.0f} kV · access fee €{u['hub_access_fee_eur_mw_yr']:,.0f}/MW/yr",
                         170)
                links.append({"link": f"{u['hub_name']} to {u['grid_name']}", "status": "existing",
                              "length km": round(km2, 1), "capacity": f"{u['hub_spare_mw']:,.0f} MW spare",
                              "voltage": f"{u['hub_voltage_kv']:,.0f} kV", "length from": "not costed"})
    # ---- hydrogen ----------------------------------------------------------------------------
    if want_pipe and (not built or pipe != "none"):
        for opt in hc_show:
            end = tie if opt == "tiein" else hpt
            off, on, km = _route(site, end, method)
            if built:
                width = float(np.clip(3 + peak_kgh / 2500, 3, 16))
                info = (f"{pipe.replace('_', ' ')} · peak {peak_kgh:,.0f} kg/h · {d['pipe_distance_km']:,.0f} km "
                        f"({d.get('pipe_route_how', method)})")
                km_show = d["pipe_distance_km"]
            else:
                width = 4
                km_show = d["pipe_distance_km"] if opt == hc else km
                info = f"candidate · {km_show:,.0f} km measured by {d.get('pipe_route_how', method) if opt == hc else method}"
            name = f"Hydrogen pipeline to {u['tiein_name'] if opt == 'tiein' else u['h2_name']}"
            add_path(off, H2, width, name, info, 235 if built else 200)
            add_path(on, H2, max(width * 0.6, 2), name + " (onshore)", "onshore section after the landfall", 150)
            links.append({"link": name, "status": "built" if built else "candidate", "length km": round(km_show, 1),
                          "capacity": f"peak {peak_kgh:,.0f} kg/h" if built else "sized by the run",
                          "voltage": "", "length from": d.get("pipe_route_how", method) if (built or opt == hc)
                          else method})
            if opt == "tiein":
                off2, on2, km2 = _route(tie, hpt, method)
                add_path(off2 + on2[1:], GREY, 2.5, f"Existing pipeline: {u['tiein_name']}",
                         f"{u['tiein_spare_kgh']:,.0f} kg/h spare at {u['tiein_pressure_bar']:,.0f} bar", 170)
                links.append({"link": f"{u['tiein_name']} to {u['h2_name']}", "status": "existing",
                              "length km": round(km2, 1), "capacity": f"{u['tiein_spare_kgh']:,.0f} kg/h spare",
                              "voltage": f"{u['tiein_pressure_bar']:,.0f} bar", "length from": "not costed"})

    # ---- points --------------------------------------------------------------------------------
    fl = "floating" if d.get("floating") else "bottom-fixed"
    if built:
        isl = (f"{final['C_wt']:,.0f} MW wind · {final['C_pv']:,.0f} MW PV · "
               f"{final['C_ez_off']:,.0f} MW electrolyser · {final['E_bat_off']:,.0f} MWh battery · {fl}")
    else:
        isl = f"{fl}, {u['avg_water_depth_m']:,.0f} m deep · {u['sea_area_km2']:,.0f} km² usable sea area"
    points.append(dict(pos=[site[1], site[0]], color=NAVY + [255], r=11, name=u["site_name"], info=isl))
    show_grid = want_cable and (not built or cab_mw > 1e-3)
    if show_grid:
        on = (f"onshore: {final['C_ez_on']:,.0f} MW electrolyser · {final['E_bat_on']:,.0f} MWh battery · "
              f"{final['grid_mwh'] / 1e3:,.0f} GWh/yr to the grid" if built else
              f"grid connection point · up to {u['grid_injection_cap_mw']:,.0f} MW injection")
        points.append(dict(pos=[grid[1], grid[0]], color=POWER + [255], r=8, name=u["grid_name"], info=on))
    if want_pipe and (not built or pipe != "none"):
        info = (f"{final['h2_kg'] / 1e3:,.0f} t/yr of hydrogen delivered" if built else "hydrogen offtake point")
        points.append(dict(pos=[hpt[1], hpt[0]], color=H2 + [255], r=8, name=u["h2_name"], info=info))
    if "hub" in ec_show and show_grid:
        points.append(dict(pos=[hub[1], hub[0]], color=[255, 255, 255, 255], r=8, name=u["hub_name"],
                           info=f"offshore substation or cable · {u['hub_spare_mw']:,.0f} MW spare · "
                                f"{u['hub_voltage_kv']:,.0f} kV", line=POWER))
    if "tiein" in hc_show and want_pipe and (not built or pipe != "none"):
        points.append(dict(pos=[tie[1], tie[0]], color=[255, 255, 255, 255], r=8, name=u["tiein_name"],
                           info=f"pipeline tie-in · {u['tiein_spare_kgh']:,.0f} kg/h spare at "
                                f"{u['tiein_pressure_bar']:,.0f} bar", line=H2))
    for p in points:
        p.setdefault("line", [255, 255, 255])

    # ---- sea area and turbines ------------------------------------------------------------------
    r_km = math.sqrt(max(float(u.get("sea_area_km2") or 0), 0.05) / math.pi)
    zone = [dict(poly=_circle(site[0], site[1], r_km), name="Usable sea area",
                 info=f"{u['sea_area_km2']:,.0f} km² · up to {u['sea_area_km2'] * u['wind_density_mw_km2']:,.0f} MW "
                      f"of wind at {u['wind_density_mw_km2']:,.1f} MW/km²")]
    tmw = float(u.get("turbine_mw") or 15)
    n_t = int(round(final["C_wt"] / tmw)) if built else int(u["sea_area_km2"] * u["wind_density_mw_km2"] / tmw)
    turb = [dict(pos=p, name=f"Wind turbine, {tmw:,.0f} MW", info="built" if built else "possible position")
            for p in _turbines(site[0], site[1], r_km, min(n_t, 400))]

    layers = [
        pdk.Layer("PolygonLayer", data=zone, get_polygon="poly", get_fill_color=ZONE + [38],
                  get_line_color=ZONE + [200], line_width_min_pixels=1.5, stroked=True, pickable=True),
        pdk.Layer("ScatterplotLayer", data=turb, get_position="pos", get_radius=2.5, radius_units="'pixels'",
                  get_fill_color=NAVY + [230 if built else 90], pickable=True),
        pdk.Layer("PathLayer", data=paths, get_path="path", get_color="color", get_width="width",
                  width_units="'pixels'", cap_rounded=True, joint_rounded=True, pickable=True),
        pdk.Layer("ScatterplotLayer", data=points, get_position="pos", get_fill_color="color", get_radius="r",
                  radius_units="'pixels'", stroked=True, get_line_color="line", line_width_min_pixels=2.5,
                  pickable=True),
        pdk.Layer("TextLayer", data=points, get_position="pos", get_text="name", get_size=14,
                  get_color=[19, 35, 46], get_pixel_offset=[0, -24], character_set=pdk.types.String("auto"),
                  font_family=pdk.types.String("Georgia, 'Times New Roman', serif"), font_weight=600, outline_width=3,
                  outline_color=[255, 255, 255, 230], font_settings={"sdf": True}),
    ]
    # view that fits everything drawn
    xs = [p["pos"][0] for p in points] + [q[0] for pa in paths for q in pa["path"]]
    ys = [p["pos"][1] for p in points] + [q[1] for pa in paths for q in pa["path"]]
    lat_c = (max(ys) + min(ys)) / 2
    span_y = max(max(ys) - min(ys), 2 * r_km / geo.KM_PER_DEG, 0.05)
    span_x = max((max(xs) - min(xs)) * math.cos(math.radians(lat_c)), 0.05)
    span = max(span_y * 1.6, span_x)          # the map is wider than tall
    zoom = float(np.clip(math.log2(360 / span) - 1.2, 2, 12))
    # cover the whole initial view (about 1,300 x 500 px) and some panning room
    deg_px = 360.0 / (512.0 * 2 ** zoom)
    lon_c = (max(xs) + min(xs)) / 2
    half_x, half_y = 3.0 * 650 * deg_px, 3.0 * 250 * deg_px * math.cos(math.radians(lat_c))
    coast = _coast(lat_c - half_y, lat_c + half_y, lon_c - half_x, lon_c + half_x)
    if coast:
        layers.insert(0, pdk.Layer("PolygonLayer", data=coast, get_polygon="rings", get_fill_color=[236, 228, 207, 150],
                                   get_line_color=[52, 68, 76, 190], line_width_min_pixels=0.8, stroked=True,
                                   pickable=False))
    view = pdk.ViewState(latitude=lat_c, longitude=(max(xs) + min(xs)) / 2, zoom=zoom)
    deck = pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto", map_style="light",
                    tooltip={"html": "<b>{name}</b><br/>{info}",
                             "style": {"backgroundColor": "#13232E", "color": "white", "fontSize": "12px",
                                       "fontFamily": "Archivo, Helvetica, sans-serif", "maxWidth": "320px"}})
    legend = [("Island", NAVY), ("Usable sea area" + (" and turbines built" if built else ""), ZONE),
              ("Export cable" + (", width ∝ MW" if built else ""), POWER),
              ("Hydrogen pipeline" + (", width ∝ kg/h" if built else ""), H2),
              ("Existing link of a hub or pipeline", GREY)]
    return deck, legend, links
