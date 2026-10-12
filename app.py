"""EVOLVE Planner: lowest-cost design of a floating energy island and its onshore plant.

Run locally:   streamlit run app.py
"""
from __future__ import annotations

import json
import math
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

from evolve_planner import __version__, params as P, report, weather, workbook, workflow
from evolve_planner.levelized import levelized
from evolve_planner.params import SPEC
from ui import charts, theme
from ui import drawings, livemap
from evolve_planner import geo

ROOT = Path(__file__).parent
EX = ROOT / "examples" / "belle_ile"
BY = {s.key: s for s in SPEC}
STEPS = ["Site", "Use case", "Data", "Technologies", "Run", "Results"]
REPO_URL = "https://github.com/YOUR-ACCOUNT/EVOLVE-Floating-Shore"     # edit after you create the repository

NAMES = {
    ("use_case", "Power-led"): "Electricity", ("use_case", "Hydrogen-led"): "Hydrogen",
    ("use_case", "Hybrid"): "Electricity and hydrogen",
    ("elec_delivery", "annual"): "Annual volume, any hour", ("elec_delivery", "firm"): "Constant power every hour",
    ("elec_delivery", "profile"): "Follow my hourly profile",
    ("h2_delivery", "annual"): "Annual volume, any hour", ("h2_delivery", "firm"): "Constant flow every hour",
    ("h2_delivery", "profile"): "Follow my hourly profile",
    ("elec_revenue", "ppa"): "PPA: fixed price for the contracted volume",
    ("elec_revenue", "merchant"): "Merchant: sell at the day-ahead price",
    ("elec_revenue", "cfd"): "Contract for difference (strike price)",
    ("elec_connection", "direct"): "Own export cable to the onshore grid point",
    ("elec_connection", "hub"): "Short cable to a nearby offshore substation or cable",
    ("elec_connection", "choose"): "Let the model choose the cheaper",
    ("h2_connection", "direct"): "Own pipeline to the offtake point",
    ("h2_connection", "tiein"): "Short pipeline to a nearby pipeline",
    ("h2_connection", "choose"): "Let the model choose the cheaper",
    ("export_voltage", "auto"): "Auto: the model chooses AC or DC, voltage and circuits",
    ("export_voltage", "HVDC"): "HVDC only",
    ("cable_cost_model", "catalogue"): "Catalogue (AC options and HVDC, exact choice)",
    ("cable_cost_model", "v9 linear"): "v9 linear (earlier project model)",
}
ZONES = ["FR", "DE-LU", "NL", "BE", "DK1", "DK2", "NO2", "SE4", "PL", "AT", "CH", "CZ", "IT-North"]

st.set_page_config(page_title="EVOLVE Planner", page_icon=":material/waves:", layout="wide",
                   initial_sidebar_state="expanded")
theme.apply()
ss = st.session_state


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def init():
    ss.setdefault("user", P.defaults())
    ss.setdefault("series", {})
    ss.setdefault("series_src", {})
    ss.setdefault("notes", [])
    ss.setdefault("started", False)
    ss.setdefault("nav", STEPS[0])
    ss.setdefault("result", None)


init()
U = ss.user


def reset_widgets():
    for k in [k for k in ss.keys() if str(k).startswith(("w_", "ed_"))]:
        del ss[k]


def go(step):
    ss.nav = step
    ss.started = True


def load_preset(name: str):
    pre = json.loads((EX / "presets.json").read_text())[name]
    user = P.defaults()
    user.update({k: v for k, v in pre.items() if not k.startswith("_")})
    ss.user = user
    load_example_year(pre.get("_year", 2019))
    ss.result = None
    reset_widgets()
    go("Site")


def load_example_year(year: int):
    df = pd.read_csv(EX / f"timeseries_{year}.csv")
    ss.series = {"wind_cf": df.wind_cf.to_numpy(), "pv_cf": df.pv_cf.to_numpy(),
                 "price": df.price_eur_mwh.to_numpy()}
    src = f"Belle-Ile example, {year} (ERA5 + IEA 15 MW curve, pvlib, Energy-Charts FR prices)"
    ss.series_src = {"wind_cf": src, "pv_cf": src, "price": src}


def new_design():
    ss.user = P.defaults()
    ss.series, ss.series_src, ss.result = {}, {}, None
    reset_widgets()
    go("Site")


# ---------------------------------------------------------------------------
# input widgets bound to the user dict
# ---------------------------------------------------------------------------

def _decimals(x, cap=6):
    for k in range(cap + 1):
        if abs(round(x, k) - x) <= 1e-9 * max(abs(x), 1.0):
            return k
    return cap


def _step_fmt(s, scale=1.0):
    """A +/- step of about a tenth of the default's order of magnitude, and a format that shows it.

    Both depend only on the parameter (not on the current value), so the widget keeps its identity
    while the user clicks. Without an explicit step Streamlit steps by 0.01, which a "%.0f" field
    cannot show, so the buttons looked dead."""
    if s.unit == "deg":
        return 0.01, "%.4f"
    ref = abs(float(s.default)) * scale
    if ref == 0:
        ref = 0.1 if s.unit.startswith("fraction") else (10_000.0 if "EUR" in s.unit else 10.0)
    e = math.floor(math.log10(ref))
    e -= 2 if ref / 10.0 ** e < 1.5 else 1          # 1.05 -> 0.01, 6.3 -> 0.1, 2.54e6 -> 1e5
    step = 10.0 ** e
    dec = min(max(0, -e, _decimals(float(s.default) * scale)), 6)
    return (round(step, 6) if step < 1 else step), f"%.{dec}f"


def w(key, label=None, help=None, scale=1.0, unit=None, disabled=False, fmt=None):
    """Render the input for `key`; the value is kept in ss.user. `scale` shows e.g. MWh as GWh."""
    s = BY[key]
    wk = "w_" + key
    u = ss.user
    unit = unit if unit is not None else s.unit
    lab = (label or s.label) + (f" ({unit})" if unit not in ("-", "", None) else "")
    hp = help if help is not None else (s.help or None)
    if s.source:
        hp = (hp + " " if hp else "") + f"Source: {s.source}."
    if s.step3:
        hp = (hp + " " if hp else "") + "No ACER 2026 indicator exists for this value; it is a placeholder until Step 3."
    if s.kind == "bool":
        ss.setdefault(wk, bool(u[key]))
        v = st.toggle(lab, key=wk, help=hp, disabled=disabled)
    elif s.kind == "choice":
        ss.setdefault(wk, u[key] if u[key] in s.options else s.options[0])
        v = st.selectbox(lab, s.options, key=wk, help=hp, disabled=disabled,
                         format_func=lambda o: NAMES.get((key, o), o))
    elif s.kind == "text":
        ss.setdefault(wk, str(u[key]))
        v = st.text_input(lab, key=wk, help=hp, disabled=disabled)
    elif s.kind == "int":
        ss.setdefault(wk, int(u[key]))
        v = st.number_input(lab, key=wk, step=1, min_value=0, help=hp, disabled=disabled)
    else:
        shown = float(u[key]) * scale
        ss.setdefault(wk, shown)
        step, f0 = _step_fmt(s, scale)
        v = st.number_input(lab, key=wk, format=fmt or f0, step=step, help=hp, disabled=disabled,
                            min_value=None if s.min is None else s.min * scale,
                            max_value=None if s.max is None else s.max * scale)
        v = float(v) / scale
    u[key] = v
    return v


@st.cache_data(show_spinner=False, max_entries=64)
def _drawing(kind: str, user_json: str, design_json: str, final_json: str, animate: bool):
    user = json.loads(user_json)
    design = json.loads(design_json) if design_json else None
    final = json.loads(final_json) if final_json else None
    if kind == "atlas":
        return drawings.atlas_html(user, design, final, title=user.get("_title", "Connection atlas"), animate=animate)
    fn = {"island": drawings.island_html, "section": drawings.section_html}[kind]
    return fn(user, design, final, animate=animate)


def drawing(kind, user, design=None, final=None, animate=True, title=None):
    keep = {k: v for k, v in user.items() if isinstance(v, (int, float, str, bool))}
    if title:
        keep["_title"] = title
    fin = ({k: final[k] for k in ("grid_mwh", "h2_kg", "link_mode", "elec_connection_used", "h2_connection_used",
                                  "export_voltage_used", "n_circuits", "circuit_rating_mw", "cable_class")
            if k in final} if final else None)
    return _drawing(kind, json.dumps(keep, sort_keys=True), json.dumps(design, sort_keys=True) if design else "",
                    json.dumps(fin, sort_keys=True) if fin else "", animate)


def safe_drawing(kind, *args, **kw):
    """A drawing that fails must never stop the page: show a short note instead."""
    try:
        svg_block(drawing(kind, *args, **kw))
    except Exception as e:  # noqa: BLE001
        st.caption(f"This drawing could not be produced ({type(e).__name__}: {e}). The results are not affected.")


def svg_block(html):
    """The drawing in its own frame, sized to its content (CSS animations need a real document)."""
    if hasattr(st, "iframe"):
        st.iframe(html, height="content")
    else:                                            # Streamlit before st.iframe
        components.html(html, height=560)


def badge(text, kind="n"):
    return f'<span class="badge {kind}">{text}</span>'


def eur(x, unit=""):
    a = abs(x)
    if a >= 1e9:
        s = f"€{x / 1e9:,.2f} bn"
    elif a >= 1e6:
        s = f"€{x / 1e6:,.1f} M"
    elif a >= 1e3:
        s = f"€{x / 1e3:,.0f} k"
    else:
        s = f"€{x:,.0f}"
    return s + unit


def derived():
    try:
        return P.derive(P.apply_profiles(ss.user, ss.get("series")))
    except Exception:          # noqa: BLE001  (half-typed inputs)
        return None


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

def sidebar():
    with st.sidebar:
        st.markdown("### EVOLVE Planner")
        st.caption(f"Floating energy islands, sized on one year of hours. Version {__version__}.")
        if ss.started:
            d = derived()
            uc = NAMES[("use_case", U["use_case"])]
            st.markdown(f"**{U['site_name']}**  \n{uc}")
            lines = []
            if d:
                lines.append(f"{'Floating' if d['floating'] else 'Bottom-fixed'}, {U['avg_water_depth_m']:.0f} m deep")
                lines.append(f"{d['link_mode']} export, {d['grid_distance_km']:.0f} km")
            have = [k for k in ("wind_cf", "pv_cf", "price", "elec_demand", "h2_demand") if ss.series.get(k) is not None]
            lines.append(f"Hourly data: {', '.join(have) if have else 'not loaded yet'}")
            if ss.result:
                f = ss.result["final"]
                lines.append(f"Last result: {'surplus' if f['net_cost'] < 0 else 'net cost'} "
                             f"{eur(abs(f['net_cost']), '/yr')}")
            st.markdown("  \n".join(lines))
            st.divider()
        st.markdown("**Inputs workbook**")
        st.download_button("Save all inputs (Excel)", workbook.to_bytes(U, ss.series, ss.notes),
                           file_name=f"EVOLVE_inputs_{U['site_name'][:30].replace(' ', '_')}.xlsx",
                           width="stretch")
        up = st.file_uploader("Open an inputs workbook", type=["xlsx"], key="wb_upload",
                              help="A workbook saved from this app or filled from the template. "
                                   "Restores every input and the hourly series.")
        if up is not None and ss.get("wb_id") != up.file_id:
            ss.wb_id = up.file_id
            try:
                user, series, notes = workbook.from_file(up)
                ss.user, ss.notes, ss.result = user, notes, None
                if series:
                    ss.series = series
                    ss.series_src = {k: f"workbook {up.name}" for k in series}
                reset_widgets()
                go("Site")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"The workbook could not be read: {e}")
        guide = ROOT / "examples" / "EVOLVE_data_guide.xlsx"
        if guide.exists():
            st.download_button("Data guide: what to upload, where to get it (Excel)", guide.read_bytes(), guide.name,
                               width="stretch")
        st.divider()
        if st.button("Open the Belle-Île example", width="stretch"):
            load_preset("hybrid_ppa"); st.rerun()
        if st.button("Start a new design", width="stretch"):
            new_design(); st.rerun()
        st.caption(f"[Method and source code]({REPO_URL})")


# ---------------------------------------------------------------------------
# landing
# ---------------------------------------------------------------------------

def landing():
    demo = P.defaults()
    demo.update({k: v for k, v in json.loads((EX / "presets.json").read_text())["hybrid_ppa"].items()
                 if not k.startswith("_")})
    left, right = st.columns([5, 7], gap="large")
    with left:
        st.markdown('<p class="hero-kicker">EVOLVE · offshore energy islands</p>', unsafe_allow_html=True)
        st.markdown("# Plan a floating energy island, hour by hour")
        st.markdown(
            '<p class="lede">Size offshore wind, floating PV, electrolysers, batteries, hydrogen storage, the export '
            'cable and the pipeline, on the island and onshore, at the lowest cost: for electricity, hydrogen or '
            'both. One year of hourly data is reduced with topological data analysis, so every surplus and lull '
            'that matters stays in, and the design is checked on all 8,760 hours.</p>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.button("Open Belle-Île example", type="primary", on_click=load_preset, args=("hybrid_ppa",),
                  width="stretch")
        c2.button("Start a new design", on_click=new_design, width="stretch")
        st.markdown("**Describe the project.** Coordinates, depth, sea area, grid and hydrogen offtake points, and "
                    "what you deliver.  \n**Add one year of hours.** Upload capacity factors and prices, or "
                    "download them by coordinates.  \n**Get the design.** Capacities, costs, hourly operation and "
                    "drawings of the island, the route and the onshore plant.")
    with right:
        safe_drawing("island", demo)
    safe_drawing("atlas", demo, title="Belle-Île example · connection atlas")
    st.caption("Drawn from the Belle-Île inputs before any run; every design draws its own island, route section "
               "and atlas.")


# ---------------------------------------------------------------------------
# step 1: site
# ---------------------------------------------------------------------------

def site_map(user, d, final=None, hourly=None, height=500):
    """Interactive map: candidates before a run, the built design after it (ui/livemap.py)."""
    if d is None:
        st.caption("The map appears when every input on this step is a valid number.")
        return
    try:
        deck, legend, links = livemap.build(user, d, final, hourly)
    except Exception as e:  # noqa: BLE001
        st.caption(f"The interactive map could not be built ({type(e).__name__}: {e}).")
        return
    st.pydeck_chart(deck, height=height)
    sw = "".join(f'<span class="lg"><i style="background:rgb({c[0]},{c[1]},{c[2]})"></i>{t}</span>'
                 for t, c in legend)
    st.markdown(f'<div class="maplegend">{sw}</div>', unsafe_allow_html=True)
    if links:
        st.dataframe(pd.DataFrame(links), hide_index=True, width="stretch")
    st.caption(("What was built: line widths follow the cable MW and the pipeline's peak flow; hover any element "
                "for its numbers." if final is not None else
                "What the model will assume: candidate links with the lengths it measures; with \"let the model "
                "choose\" both options are drawn.") + " Routes are the shortest paths through the sea on a 1 km "
               "coastline; the basemap needs internet in your browser.")


def _set_point(prefix, lat, lon):
    ss.user[prefix + "_lat"], ss.user[prefix + "_lon"] = round(lat, 4), round(lon, 4)
    for k in (prefix + "_lat", prefix + "_lon"):
        ss.pop("w_" + k, None)


def route_panel(d):
    """What the model measures, where the numbers come from, and help to find real connection points."""
    shore = None
    try:
        shore = geo.nearest_shore(round(U["site_lat"], 3), round(U["site_lon"], 3))
        on_land = geo.is_land(U["site_lat"], U["site_lon"])
    except Exception:  # noqa: BLE001
        on_land = None
    rows = []
    if d["elec_export_allowed"]:
        to = U["hub_name"] if d.get("elec_connection_used") == "hub" else U["grid_name"]
        rows.append({"link": f"Export cable to {to}", "length used, km": round(d["grid_distance_km"], 1),
                     "found by": d.get("grid_route_how", ""), "straight line, km": round(d.get("straight_grid_km", 0), 1)
                     if d.get("elec_connection_used") != "hub" else float("nan")})
    if d["pipe_allowed"]:
        to = U["tiein_name"] if d.get("h2_connection_used") == "tiein" else U["h2_name"]
        rows.append({"link": f"Hydrogen pipeline to {to}", "length used, km": round(d["pipe_distance_km"], 1),
                     "found by": d.get("pipe_route_how", ""),
                     "straight line, km": round(P.haversine_km(U["site_lat"], U["site_lon"], U["h2_lat"], U["h2_lon"]), 1)
                     if d.get("h2_connection_used") != "tiein" else float("nan")})
    left, right = st.columns([3, 2], gap="large")
    with left:
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if on_land:
            st.warning("The island coordinates fall on land on the coastline map. Check the latitude and longitude "
                       "(decimal degrees, west and south negative).")
        far = [(n, k) for n, k in ((U["grid_name"], d["grid_distance_km"]), (U["h2_name"], d["pipe_distance_km"]))
               if k > 300]
        if far:
            st.warning("Long route: " + ", ".join(f"{n} is {k:,.0f} km away" for n, k in far) + ". If you moved the "
                       "island, move the onshore points too, or use the nearest coast below.")
    with right:
        st.markdown("**Find real connection points**")
        lat, lon = U["site_lat"], U["site_lon"]
        st.markdown(
            f"- [Substations, power lines and pipelines near the island (OpenInfraMap)]"
            f"(https://openinframap.org/#8/{lat:.3f}/{lon:.3f})\n"
            "- [Offshore cables and pipelines (EMODnet Human Activities map)](https://emodnet.ec.europa.eu/en/human-activities)\n"
            "- [Transmission grid map (ENTSO-E)](https://www.entsoe.eu/data/map/)")
        if shore:
            st.caption(f"No substation yet? Put a point on the coast nearest the island "
                       f"({shore[1]:.3f}, {shore[2]:.3f}, {shore[0]:,.0f} km away) as a first guess:")
            st.button("Move the grid point there", on_click=_set_point, args=("grid", shore[1], shore[2]),
                      width="stretch", key="near_grid")
            st.button("Move the hydrogen offtake there", on_click=_set_point, args=("h2", shore[1], shore[2]),
                      width="stretch", key="near_h2")


def step_site():
    st.markdown("## Where is the island?")
    a, b, c = st.columns([2, 1, 1])
    with a: w("site_name")
    with b: w("site_lat", label="Island latitude", unit="°")
    with c: w("site_lon", label="Island longitude", unit="°")
    a, b, c = st.columns([2, 1, 1])
    with a: w("grid_name")
    with b: w("grid_lat", label="Grid point latitude", unit="°")
    with c: w("grid_lon", label="Grid point longitude", unit="°")
    a, b, c = st.columns([2, 1, 1])
    with a: w("h2_name")
    with b: w("h2_lat", label="Offtake latitude", unit="°")
    with c: w("h2_lon", label="Offtake longitude", unit="°")
    a, b, c, e = st.columns(4)
    with a: w("avg_water_depth_m")
    with b: w("sea_area_km2")
    with c: w("deck_area_max_m2", "Island deck area")
    with e: w("area_onshore_max_m2", "Onshore plot area")
    st.markdown("#### Route lengths")
    a, b, c, e = st.columns(4)
    with a: w("route_method")
    with b: w("routing_factor", "Routing factor", disabled=U["route_method"] != "straight line")
    with c: w("link_distance_override_km", "Cable length, if known")
    with e: w("pipe_distance_override_km", "Pipeline length, if known")
    d = derived()
    if d:
        route_panel(d)
    with st.expander("Densities and foundations"):
        a, b, c = st.columns(3)
        with a:
            w("wind_density_mw_km2")
            w("pv_density_mw_km2")
        with b:
            w("fixed_floating_depth_m")
            w("turbine_mw")
        with c:
            w("decentralized_h2")
            w("existing_pipeline_available")
    st.markdown("#### Connections to existing infrastructure")
    st.caption("Is there an offshore substation, an export cable or a pipeline nearby with spare capacity? The "
               "island can connect to it instead of building its own link to shore, or the model can compare both. "
               "Comparing doubles the sizing time for each option compared.")
    ce, ch = st.columns(2, gap="large")
    with ce:
        w("elec_connection")
        if U["elec_connection"] != "direct":
            w("hub_name")
            a1, a2 = st.columns(2)
            with a1: w("hub_lat", unit="°")
            with a2: w("hub_lon", unit="°")
            a1, a2, a3 = st.columns(3)
            with a1: w("hub_spare_mw", "Spare capacity")
            with a2: w("hub_voltage_kv", "Voltage")
            with a3: w("hub_access_fee_eur_mw_yr", "Access fee")
        if U["elec_connection"] != "hub":
            a1, a2 = st.columns(2)
            with a1: w("export_voltage", "Export link of the island's own connection")
            with a2: w("tso_fee_eur_mw_yr", "TSO grid fee")
    with ch:
        w("h2_connection")
        if U["h2_connection"] != "direct":
            w("tiein_name")
            a1, a2 = st.columns(2)
            with a1: w("tiein_lat", unit="°")
            with a2: w("tiein_lon", unit="°")
            a1, a2, a3 = st.columns(3)
            with a1: w("tiein_spare_kgh", "Spare capacity")
            with a2: w("tiein_pressure_bar", "Pressure")
            with a3: w("tiein_fee_eur", "Tie-in cost")
        if not U["enable_pipe"]:
            st.caption("The hydrogen pipeline is switched off under Technologies; switch it on to use this.")
    d = derived()
    if d:
        fnd = (f"Floating foundations ({U['avg_water_depth_m']:.0f} m is deeper than "
               f"{U['fixed_floating_depth_m']:.0f} m)" if d["floating"]
               else f"Bottom-fixed foundations ({U['avg_water_depth_m']:.0f} m)")
        to = f"to {U['hub_name']}" if d.get("elec_connection_used") == "hub" else "to the grid point"
        ncls = len(d.get("cable_classes") or [])
        cab_txt = (f"{d['export_voltage_used']} cable {to}, {d['grid_distance_km']:.0f} km, "
                   f"{d['circuit_rating_mw']:,.0f} MW per circuit" if ncls == 1 else
                   f"Export link {to}, {d['grid_distance_km']:.0f} km: the model chooses among {ncls} AC and DC "
                   f"options (cheapest at the grid limit, before load losses: {d.get('cable_preview', '')})" if ncls > 1 else
                   f"No export cable")
        html = (badge(fnd) + badge(cab_txt, "p")
                + badge(f"Pipeline route {d['pipe_distance_km']:.0f} km", "h")
                + badge(f"Wind up to {U['sea_area_km2'] * U['wind_density_mw_km2']:,.0f} MW in the sea area"))
        st.markdown(html, unsafe_allow_html=True)
        if d["config"].startswith("C"):
            st.caption("Turbine-level electrolysis: no power cable is built; energy leaves as hydrogen.")
    t_atlas, t_map = st.tabs(["Connection atlas", "Interactive map"])
    with t_atlas:
        with st.spinner("Drawing the coastline and routes"):
            safe_drawing("atlas", U, animate=False)
        st.caption("The atlas is redrawn from your coordinates. The run chooses the export link (AC voltage, "
                   "conductor and compensation, or HVDC) and its number of circuits from the route length; costs "
                   "and cable data are under Technologies, Export cable.")
    with t_map:
        site_map(U, d)
    nav_buttons("Site")


# ---------------------------------------------------------------------------
# step 2: use case
# ---------------------------------------------------------------------------

def profile_note(key, mode, what, col):
    """Under profile delivery the uploaded hourly series is the contract; say what it amounts to."""
    if mode != "profile":
        return
    x = (ss.get("series") or {}).get(key)
    if x is None:
        st.caption(f"Upload the hourly {what} profile on the Data step (column {col}). Until then the annual "
                   "volume above is shown but not used.")
        return
    x = np.asarray(x, float)
    if key == "elec_demand":
        st.caption(f"Uploaded profile: {np.nansum(x) / 1e3:,.1f} GWh/yr, {np.nanmean(x):,.1f} MW on average, peak "
                   f"{np.nanmax(x):,.1f} MW. It replaces the annual volume above and must be met every hour.")
    else:
        st.caption(f"Uploaded profile: {np.nansum(x) / 1e3:,.0f} t/yr, {np.nanmean(x):,.0f} kg/h on average, peak "
                   f"{np.nanmax(x):,.0f} kg/h. It replaces the annual volume above and must be met every hour.")


def step_use():
    st.markdown("## What should the island deliver?")
    s = BY["use_case"]
    ss.setdefault("w_use_case", U["use_case"])
    uc = st.radio("Main product", s.options, key="w_use_case", horizontal=True,
                  format_func=lambda o: NAMES[("use_case", o)],
                  captions=["Power to the grid; hydrogen only as a buffer or by-product",
                            "Hydrogen to an offtaker; the cable only if it pays",
                            "A set amount of each"])
    U["use_case"] = uc
    e_col, h_col = st.columns(2, gap="large")
    if uc != "Hydrogen-led":
        with e_col:
            st.markdown("#### Electricity")
            rev = w("elec_revenue")
            if rev == "ppa":
                w("annual_demand_mwh", "Electricity to deliver per year", scale=1e-3, unit="GWh/yr")
                w("elec_delivery")
                profile_note("elec_demand", U["elec_delivery"], "electricity", "elec_demand_mw")
                w("ppa_price_eur_mwh")
            elif rev == "cfd":
                w("cfd_strike_eur_mwh")
                st.caption("The strike price is paid in hours with a non-negative day-ahead price, the market price "
                           "otherwise. The optimiser chooses how much to sell.")
            else:
                st.caption("Every MWh earns the hourly day-ahead price. The optimiser chooses how much to sell.")
            w("grid_injection_cap_mw")
    if uc != "Power-led":
        with h_col if uc == "Hybrid" else e_col:
            st.markdown("#### Hydrogen")
            w("annual_h2_demand_kg", "Hydrogen to deliver per year", scale=1e-3, unit="t/yr")
            w("h2_delivery")
            profile_note("h2_demand", U["h2_delivery"], "hydrogen", "h2_demand_kgh")
            w("h2_price_eur_kg")
    with h_col if uc != "Hybrid" else st.container():
        if uc == "Power-led":
            st.markdown("#### Hydrogen as a by-product")
            w("sell_surplus", "Sell hydrogen made from surplus power")
            if U["sell_surplus"]:
                w("h2_price_eur_kg")
        elif uc == "Hydrogen-led":
            st.markdown("#### Electricity as a by-product")
            w("sell_surplus", "Sell surplus electricity")
            if U["sell_surplus"]:
                w("elec_revenue", "How surplus electricity is sold")
                if U["elec_revenue"] == "cfd":
                    w("cfd_strike_eur_mwh")
                w("grid_injection_cap_mw")
                if U["elec_revenue"] == "ppa":
                    st.caption("A PPA needs a contracted volume; choose merchant or CfD for surplus sales.")
    if uc == "Hybrid":
        e_gwh = U["annual_demand_mwh"] / 1e3 if U["elec_revenue"] == "ppa" else 0.0
        h_gwh = U["annual_h2_demand_kg"] * U["lhv_h2_kwh_kg"] / U["electrolyzer_efficiency"] / 1e6
        tot = e_gwh + h_gwh
        if tot > 0:
            pe = 100 * e_gwh / tot
            st.markdown(
                f'<div style="margin-top:.6rem"><div class="note">Split of the contracted energy (before '
                f'losses): {e_gwh:,.0f} GWh to the grid and {h_gwh:,.0f} GWh of electricity for hydrogen</div>'
                f'<div style="display:flex;height:14px;border-radius:3px;overflow:hidden;margin-top:.3rem">'
                f'<div style="width:{pe:.1f}%;background:{theme.PALETTE["power"]}"></div>'
                f'<div style="width:{100 - pe:.1f}%;background:{theme.PALETTE["h2"]}"></div></div></div>',
                unsafe_allow_html=True)
    nav_buttons("Use case")


# ---------------------------------------------------------------------------
# step 3: data
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=20, ttl=24 * 3600)
def _era5(lat, lon, year):
    return weather.fetch_era5(lat, lon, year)


@st.cache_data(show_spinner=False, max_entries=20, ttl=24 * 3600)
def _prices(zone, year):
    return weather.fetch_prices(zone, year)


def step_data():
    st.markdown("## One year of hourly data")
    st.markdown('<p class="lede">The planner works on one calendar year at hourly resolution: wind and solar '
                'capacity factors (0 to 1), and day-ahead prices for merchant or CfD revenue. Demand profiles are '
                'needed only for "follow my hourly profile" delivery. Files at 30, 15, 10 or 5-minute resolution are '
                'averaged to hours, and a leap year loses 29 February. The data guide in the sidebar lists where to '
                'get every series.</p>', unsafe_allow_html=True)
    t_up, t_api, t_ex = st.tabs(["Upload a file", "Download by coordinates", "Belle-Île example"])
    with t_up:
        a, b = st.columns([3, 2])
        with a:
            f = st.file_uploader("CSV or Excel file with one row per hour", type=["csv", "xlsx"], key="ts_upload",
                                 help="Recognised columns: wind_cf, pv_cf, price_eur_mwh, elec_demand_mw, h2_demand_kgh. "
                                      "One row per time step of one year: 8,760 hourly rows, or 17,520 / 35,040 / "
                                      "52,560 / 105,120 rows at 30 / 15 / 10 / 5 minutes (leap years accepted).")
            if f is not None and ss.get("ts_id") != f.file_id:
                ss.ts_id = f.file_id
                try:
                    new, notes = weather.series_from_table(weather.read_table(f))
                    if not new:
                        st.error("No recognised column was found. Use the column names of the template.")
                    else:
                        ss.series.update(new)
                        ss.series_src.update({k: f"upload {f.name}" for k in new})
                        ss.notes = notes
                        ss.result = None
                except Exception as e:  # noqa: BLE001
                    st.error(f"The file could not be read: {e}")
            for n in ss.notes:
                st.caption(n)
        with b:
            st.markdown("**Templates**")
            st.download_button("Hourly template (CSV)", weather.template_csv(), "EVOLVE_timeseries_template.csv",
                               width="stretch")
            st.download_button("Full inputs workbook (Excel)", workbook.to_bytes(U, ss.series, ss.notes),
                               "EVOLVE_inputs.xlsx", width="stretch")
    with t_api:
        st.caption(f"Island at {U['site_lat']:.3f}°, {U['site_lon']:.3f}°. Wind: ERA5 100 m wind → 150 m hub → "
                   "IEA 15 MW reference curve, farm-smoothed, 12.5 % losses. Solar: ERA5 irradiance → pvlib, 10° "
                   "tilt, water-cooled modules, 14 % losses.")
        a, b, c = st.columns([1, 1, 2])
        year = a.selectbox("Weather year", list(range(2024, 1999, -1)), key="api_year")
        zone = b.selectbox("Price zone", ZONES, key="api_zone")
        with c:
            st.write("")
            st.write("")
            col1, col2 = st.columns(2)
            get_w = col1.button("Get wind and solar", width="stretch")
            get_p = col2.button("Get prices", width="stretch")
        if get_w:
            with st.spinner("Downloading ERA5 from the Open-Meteo archive"):
                try:
                    s, meta = _era5(round(U["site_lat"], 3), round(U["site_lon"], 3), int(year))
                    ss.series.update(s)
                    src = f"ERA5 {year} at {meta['lat']:.2f}°, {meta['lon']:.2f}° (Open-Meteo)"
                    ss.series_src.update({"wind_cf": src, "pv_cf": src})
                    ss.result = None
                    st.success(f"Wind and solar loaded. Mean wind speed at 100 m: {meta['mean_ws100']:.1f} m/s.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"The weather service did not answer ({type(e).__name__}). Try again, or upload "
                             "wind_cf and pv_cf in a file.")
        if get_p:
            with st.spinner("Downloading day-ahead prices from Energy-Charts"):
                try:
                    pr, meta = _prices(zone, int(year))
                    ss.series["price"] = pr
                    ss.series_src["price"] = f"Day-ahead {zone} {year} (Energy-Charts, Fraunhofer ISE)"
                    ss.result = None
                    st.success(f"Prices loaded. Mean {meta['mean']:.1f} EUR/MWh.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"The price service did not answer ({e}). Try again, or upload a price_eur_mwh column.")
        st.caption("Wind and solar series derived here are first estimates. For a project, upload your own "
                   "measured or modelled capacity factors.")
    with t_ex:
        st.markdown("Bretagne Sud floating wind zone, south of Belle-Île (47.38° N, 3.55° W), 75 m deep. "
                    "Wind 42 % and solar 14.6 % capacity factor in 2019; French day-ahead prices.")
        a, b, _ = st.columns([1, 1, 2])
        yr = a.selectbox("Year", [2019, 2024], key="ex_year")
        if b.button("Use this year's data", width="stretch"):
            load_example_year(int(yr))
            ss.result = None
            st.success(f"Belle-Île {yr} loaded.")
        presets = json.loads((EX / "presets.json").read_text())
        a, b, _ = st.columns([2, 1, 1])
        pick = a.selectbox("Or load a complete Belle-Île scenario (replaces every input)", list(presets),
                           format_func=lambda k: presets[k]["_title"], key="ex_preset")
        with b:
            st.write("")
            st.write("")
            st.button("Load scenario", on_click=load_preset, args=(pick,), width="stretch")
    # ---- what is loaded --------------------------------------------------------------------
    st.markdown("#### Loaded series")
    rows = []
    labels = {"wind_cf": ("Wind capacity factor", "%", 100), "pv_cf": ("Solar capacity factor", "%", 100),
              "price": ("Day-ahead price", "EUR/MWh", 1), "elec_demand": ("Electricity demand", "MW", 1),
              "h2_demand": ("Hydrogen demand", "kg/h", 1)}
    for k, (lab, unit, sc) in labels.items():
        x = ss.series.get(k)
        rows.append({"series": lab, "status": "loaded" if x is not None else "missing",
                     "mean": f"{np.mean(x) * sc:,.1f} {unit}" if x is not None else "",
                     "source": ss.series_src.get(k, "")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    d = derived()
    if d:
        probs = workflow.check_series(ss.series, d)
        if probs:
            for m in probs:
                st.markdown(f'<span class="check-bad">To fix before running: {m}</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="check-ok">The series match the use case. Ready to run.</span>',
                        unsafe_allow_html=True)
        if ss.series.get("wind_cf") is not None:
            a, b = st.columns(2)
            a.plotly_chart(charts.monthly_cf(ss.series), width="stretch")
            b.plotly_chart(charts.duration(ss.series), width="stretch")
        if ss.series.get("price") is not None:
            st.plotly_chart(charts.price_profile(ss.series["price"]), width="stretch")
    nav_buttons("Data")


# ---------------------------------------------------------------------------
# step 4: technologies
# ---------------------------------------------------------------------------

EDIT_GROUPS = ["Finance", "Offshore wind", "Floating PV", "Electrolysis", "Compression", "Fuel cell", "Battery",
               "Hydrogen tank", "Export cable", "Connections", "Hydrogen pipeline", "Island platform", "Solver"]
GROUP_NOTES = {
    "Export cable": "The model chooses the export link exactly from a catalogue: AC at 66, 132, 220 or 275 kV with "
                    "500 to 1000 mm2 conductors and shunt reactors at both ends (or also mid-route), or a VSC HVDC "
                    "link. AC ratings fall with route length because of the charging current; HVDC costs follow "
                    "Vrana & Hartel (2018). The TSO grid fee is charged per MW every year; with a hub connection the "
                    "hub access fee (Connections) replaces it. 'v9 linear' restores the earlier cost for comparison.",
    "Hydrogen pipeline": "Eight new pipe sizes from 4 to 36 inch, plus a repurposed 36-inch line if an existing pipeline "
                         "is available. Cost per km follows the ACER 2026 medians times a subsea factor; the capacity of "
                         "each size comes from the design gas velocity and the pressure drop over the route.",
    "Connections": "Nearby offshore substations, cables and pipelines. The same inputs are on the Site step.",
    "Island platform": "Structure cost of the island (version 0.10): k_esc x k_inst x [f_E x c_E x export MW + f_H x "
                       "c_H x island equipment MW], on DNV GL's 2018 basis of a jacket in 30 m. Bottom-fixed: the "
                       "jacket share grows with depth. Floating central platform: a hull with moorings replaces the "
                       "jacket (factor about 1.6). Turbine-level electrolysis: no central platform; each floater is "
                       "enlarged (f_C), in-field hydrogen lines are added, small electrolysers carry a scale penalty "
                       "and the electrical array cables are credited.",
    "Solver": "Model limits. Raise the bounds only if a result sits exactly on one of them.",
}


def _reset_group(g):
    for s_ in SPEC:
        if s_.group == g:
            ss.user[s_.key] = s_.default
            ss.pop("w_" + s_.key, None)


def param_grid(specs, ncol=3):
    cols = st.columns(ncol, gap="medium")
    for i, s_ in enumerate(specs):
        with cols[i % ncol]:
            w(s_.key)


def step_tech():
    st.markdown("## Which technologies may the optimiser use?")
    st.markdown('<p class="lede">Offshore wind is always available. Switch off anything that is not an option '
                'for your project; the optimiser sizes the rest, and may size an allowed technology at zero.</p>',
                unsafe_allow_html=True)
    a, b, c = st.columns(3, gap="large")
    with a:
        st.markdown("#### On the island")
        for k in ("enable_pv", "enable_ez_off", "enable_fc_off", "enable_batt_off", "enable_tank_off"):
            w(k, BY[k].label.replace(" on the island", ""))
    with b:
        st.markdown("#### Onshore")
        for k in ("enable_ez_on", "enable_fc_on", "enable_batt_on", "enable_tank_on"):
            w(k, BY[k].label.replace(" onshore", ""))
    with c:
        st.markdown("#### Links to shore")
        w("enable_cable")
        w("enable_pipe")
        if U["enable_pipe"] and not U["existing_pipeline_available"]:
            st.caption("Only new pipelines are considered. Tick 'existing gas pipeline' on the Site step to allow "
                       "a repurposed one.")
    safe_drawing("section", U, animate=False)
    pa, pb = st.columns([7, 5], gap="large")
    with pa:
        safe_drawing("island", U, animate=False)
    with pb:
        st.markdown("#### What the preview shows")
        st.markdown("The route section and the island show every technology you allow, at illustrative sizes "
                    "scaled to your sea area. Equipment footprints on the deck use the area inputs (m² per MW, "
                    "per MWh or per kg) under *Costs and performance*, so you can see early whether the deck you "
                    "entered is large enough.")
    st.caption("Preview with illustrative sizes for every technology you allow; the run sizes them for real. "
               "Switched-off technologies disappear from the drawings.")
    st.markdown("#### Costs and performance")
    st.caption("Every number the model uses is here: type a value or use − and +. Hover the ? icon for what a value "
               "means and where it comes from. Cables, converters, reactors, pipelines and compressors follow "
               "manufacturer data, published cost functions and the ACER 2026 unit investment cost indicators; "
               "values marked as placeholders have no referenced value yet and will be replaced in Step 3. The Run step lists every input of the run with its source.")
    tabs = st.tabs(EDIT_GROUPS)
    for g, tab in zip(EDIT_GROUPS, tabs):
        with tab:
            if g in GROUP_NOTES:
                st.caption(GROUP_NOTES[g])
            specs = [s_ for s_ in SPEC if s_.group == g and s_.kind != "text"]
            main = [s_ for s_ in specs if not s_.advanced]
            more = [s_ for s_ in specs if s_.advanced]
            param_grid(main)
            if more:
                st.markdown("**Further parameters**")
                param_grid(more)
            changed = [s_.label for s_ in specs if U.get(s_.key) != s_.default]
            if changed:
                st.button(f"Reset {g.lower()} to defaults ({len(changed)} changed)", key=f"reset_{g}",
                          on_click=_reset_group, args=(g,))
    nav_buttons("Technologies")


# ---------------------------------------------------------------------------
# step 5: run
# ---------------------------------------------------------------------------

@st.cache_resource
def _run_lock():
    return threading.Lock()


DERIVED_ROWS = [
    ("config", "Island concept", ""), ("floating", "Floating", ""), ("link_mode", "Export technology", ""),
    ("export_voltage_used", "Export voltage", ""), ("circuit_rating_mw", "Rating per circuit", "MW"),
    ("n_circuits", "Circuits built", ""),
    ("grid_distance_km", "Cable route length", "km"), ("grid_route_how", "Cable route found by", ""),
    ("pipe_distance_km", "Pipeline route length", "km"), ("pipe_route_how", "Pipeline route found by", ""),
    ("cable_capex_eur_mw", "Cable cost per MW (incl. converters)", "EUR/MW"), ("cable_eff", "Cable efficiency", ""),
    ("cable_fom", "Cable fixed O&M", "fraction/yr"), ("tso_fee", "Grid or hub fee applied", "EUR/MW/yr"),
    ("grid_injection_cap_mw", "Grid injection limit applied", "MW"),
    ("wind_capex_eur_mw", "Wind CAPEX applied", "EUR/MW"), ("wind_fom", "Wind fixed O&M applied", "fraction/yr"),
    ("platform_factor_e", "Platform factor applied, electrical part (f_E)", "x"),
    ("platform_factor_h", "Platform factor applied, process part (f_H)", "x"),
    ("platform_fom_used", "Platform fixed O&M applied", "fraction/yr"),
    ("hvdc_float_premium", "HVDC converter factor applied", "x"),
    ("h2_kg_per_mwh", "Hydrogen per MWh of electrolysis", "kg/MWh"),
    ("comp_mwh_per_kg", "Compression work", "MWh/kg"), ("fc_mwh_per_kg", "Fuel cell output", "MWh/kg"),
    ("pipe_allowed", "Pipeline classes allowed", ""), ("elec_revenue", "Electricity revenue applied", ""),
    ("annual_demand_mwh", "Electricity contract applied", "MWh/yr"),
    ("annual_h2_demand_kg", "Hydrogen contract applied", "kg/yr")]


def _show(v, sig=6):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:,.{sig}g}" if abs(v) < 1e4 else f"{v:,.0f}"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x).replace("_", " ") for x in v) or "none"
    return str(NAMES.get((None, v), v))


def inputs_review(d):
    groups = ["All"] + list(dict.fromkeys(s_.group for s_ in SPEC))
    a, b = st.columns([2, 1])
    g = a.selectbox("Group", groups, key="rev_group", label_visibility="collapsed")
    only = b.toggle("Only values changed from the defaults", key="rev_changed")
    rows = [{"group": s_.group, "input": s_.label, "value": _show(U.get(s_.key, s_.default)), "unit": s_.unit,
             "default": _show(s_.default), "source": s_.source, "note": ("placeholder" if s_.step3 else "")
             + (" · changed" if U.get(s_.key) != s_.default else "")}
            for s_ in SPEC if (g == "All" or s_.group == g) and (not only or U.get(s_.key) != s_.default)]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=360)
    st.markdown("**Derived by the model from these inputs**")
    preview = len(d.get("cable_classes") or []) > 1 and "n_circuits" not in d
    pv_keys = {"link_mode", "export_voltage_used", "circuit_rating_mw", "cable_capex_eur_mw", "cable_eff", "cable_fom"}
    rows = [{"quantity": lab + (" (preview: option cheapest at the grid limit)" if preview and k in pv_keys else ""),
             "value": _show(d.get("cable_preview") if (preview and k == "export_voltage_used") else d[k], 4),
             "unit": unit} for k, lab, unit in DERIVED_ROWS if k in d]
    if preview:
        n_ac = sum(1 for c in d["cable_classes"] if c.get("tech") == "AC")
        n_dc = len(d["cable_classes"]) - n_ac
        rows.insert(3, {"quantity": "Export-link options the run chooses from",
                        "value": f"{n_ac} AC and {n_dc} HVDC", "unit": ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def step_run():
    st.markdown("## Find the lowest-cost design")
    d = derived()
    if d is None:
        st.error("Some inputs are not valid numbers. Check the previous steps.")
        return
    probs = workflow.check_series(ss.series, d)
    uc = NAMES[("use_case", U["use_case"])]
    want = []
    if d["annual_demand_mwh"] > 0 and d["elec_revenue"] == "ppa":
        want.append(f"{d['annual_demand_mwh'] / 1e3:,.0f} GWh of electricity a year")
    if d["annual_h2_demand_kg"] > 0:
        want.append(f"{d['annual_h2_demand_kg'] / 1e3:,.0f} t of hydrogen a year")
    st.markdown(
        f"**{U['site_name']}**: {uc.lower()}"
        + (f", {' and '.join(want)}" if want else ", volume chosen by the optimiser")
        + f". {'Floating' if d['floating'] else 'Bottom-fixed'} wind at {U['avg_water_depth_m']:.0f} m, "
          + (f"export link over {d['grid_distance_km']:.0f} km, option and circuits chosen by the run."
             if len(d.get("cable_classes") or []) > 1 else
             f"{d['link_mode']} export over {d['grid_distance_km']:.0f} km."))
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("The run has three stages:")
        st.markdown(
            "1. **Reduce.** The cumulative surplus-and-deficit curves of "
            + " and ".join({"wind_cf": "wind", "pv_cf": "solar", "price": "price", "elec_demand": "electricity demand",
                            "h2_demand": "hydrogen demand"}[k] for k in workflow._cut_attrs(ss.series, d))
            + " are analysed with persistent homology. Every long surplus or deficit episode becomes a fixed cut, "
              "and neighbouring hours are merged only where the curve stays within a small error.\n"
            "2. **Size.** The capacity-expansion model is solved on the reduced year, with storage carried "
            "across the whole year.\n"
            "3. **Check.** The design is operated on all 8,760 hours. Generation, conversion and storage may each be "
            "scaled up (by up to 3 times) where that lowers the net cost, with undelivered energy heavily "
            "penalised, so short hours are fixed by the cheapest enlargement.")
    with right:
        n = st.select_slider("Detail of the reduced year", options=[730, 1460, 2190], value=1460, key="n_blocks",
                             format_func=lambda v: {730: "Quick (730 blocks)", 1460: "Standard (1,460 blocks)",
                                                    2190: "Fine (2,190 blocks)"}[v])
        solvers = ["highs"] + (["glpk"] if shutil.which("glpsol") else [])
        solver = st.radio("Solver", solvers, horizontal=True, key="solver",
                          format_func=lambda s: {"highs": "HiGHS", "glpk": "GLPK (slower)"}[s])
        st.caption("Standard detail kept the cost within 0.3 % of the full-year optimum in the Step 2 tests. "
                   "With HiGHS a run takes about two to five minutes; GLPK is much slower on the full-year "
                   "check (often ten minutes or more on the free server).")
    with st.expander("Every input of this run, and what the model derives from it"):
        inputs_review(d)
    if probs:
        for m in probs:
            st.markdown(f'<span class="check-bad">{m}</span>', unsafe_allow_html=True)
        st.button("Go to the data step", on_click=go, args=("Data",))
        return
    if st.button("Find the lowest-cost design", type="primary"):
        lock = _run_lock()
        with st.status("Solving", expanded=True) as status:
            if not lock.acquire(blocking=False):
                status.write("Another design is being solved on this server. Yours starts as soon as it finishes.")
                lock.acquire()
            t0 = time.time()
            try:
                res = workflow.plan(dict(U), dict(ss.series), n_blocks=int(n), solver=solver,
                                    progress=lambda stage, text: status.write(f"{text} ({time.time() - t0:.0f} s)"))
                ss.result = res
                status.update(label=f"Design found in {res['timing']['total_s']:.0f} s", state="complete")
            except Exception as e:  # noqa: BLE001
                status.update(label="The run stopped", state="error")
                st.error(f"{e}")
                return
            finally:
                lock.release()
        ss._goto = "Results"          # the step selector is already drawn in this run
        st.rerun()


# ---------------------------------------------------------------------------
# step 6: results
# ---------------------------------------------------------------------------

CAP_ISLAND = [("C_wt", "Offshore wind", "MW"), ("C_pv", "Floating PV", "MW"), ("C_ez_off", "Electrolyser", "MW"),
              ("C_cmp_off", "Compressor", "MW"), ("C_fc_off", "Fuel cell", "MW"), ("P_bat_off", "Battery power", "MW"),
              ("E_bat_off", "Battery energy", "MWh"), ("E_tank_off", "Hydrogen tank", "t")]
CAP_SHORE = [("C_cab", "Export cable", "MW"), ("C_ez_on", "Electrolyser", "MW"), ("C_cmp_on", "Compressor", "MW"),
             ("C_fc_on", "Fuel cell", "MW"), ("P_bat_on", "Battery power", "MW"), ("E_bat_on", "Battery energy", "MWh"),
             ("E_tank_on", "Hydrogen tank", "t")]


def cap_table(f, rows):
    out = []
    for k, lab, unit in rows:
        v = f[k] / 1000 if unit == "t" else f[k]
        if v > 1e-3:
            out.append({"component": lab, "size": f"{v:,.1f} {unit}"})
    return pd.DataFrame(out) if out else pd.DataFrame({"component": ["Nothing built"], "size": [""]})


def connection_table(res, f):
    d, inp, h = res["derived"], res["inputs"], res["hourly"]
    rows = []
    if f["C_cab"] > 1e-3:
        hub = d.get("elec_connection_used") == "hub"
        rating = float(f.get("circuit_rating_mw") or d.get("circuit_rating_mw") or 0)
        n = int(f["n_circuits"]) if f.get("n_circuits") is not None else (
            math.ceil(f["C_cab"] / rating - 1e-6) if rating == rating and rating > 0 else 0)
        rows += [("Electricity route", f"Cable to {inp.get('hub_name')}" if hub else "Own cable to the grid point"),
                 ("Export voltage", f"{f.get('export_voltage_used', d.get('export_voltage_used', ''))} "
                                    f"({f.get('link_mode', d.get('link_mode', ''))})"),
                 ("Cable capacity used", f"{f['C_cab']:,.1f} MW"),
                 ("Link built", f.get("cable_class", "")),
                 ("Circuits built" if f.get("cable_tech") != "DC" else "Converter units",
                  (f"{n} × {rating:,.0f} MW usable at this length" if f.get("cable_tech") != "DC" else f"{n}")
                  if n else "per-MW cost (v9 linear)"),
                 ("Cable investment per MW used", f"€{f.get('cable_capex_eur_mw', 0):,.0f}/MW"),
                 ("Energy delivered / sent (year)", f"{100 * f.get('cable_eff', 1.0):,.2f} %"),
                 ("Link losses (year)", f"{f.get('cable_loss_mwh', 0) / 1e3:,.1f} GWh, of which "
                                        f"{8.76 * f.get('cable_noload_mw', 0):,.1f} GWh at no load"),
                 ("Reactive compensation", f"{f.get('cable_reactive_mvar', 0):,.0f} MVAr of shunt reactors"
                  if f.get("cable_tech") == "AC" else "none (HVDC)"),
                 ("Cable length", f"{f['grid_distance_km']:,.0f} km ({d.get('grid_route_how', 'straight line x factor')})"),
                 ("Grid or hub fee", f"€{d.get('tso_fee', 0):,.0f}/MW/yr")]
        if hub:
            rows.append(("Hub spare capacity used", f"{100 * np.max(h['p_grid']) / max(inp.get('hub_spare_mw', 1), 1e-9):,.0f} % "
                                                    f"(peak {np.max(h['p_grid']):,.0f} of {inp.get('hub_spare_mw', 0):,.0f} MW)"))
    if f["pipe"] != "none":
        tie = d.get("h2_connection_used") == "tiein"
        rows += [("Hydrogen route", f"Pipeline to {inp.get('tiein_name')}" if tie else "Own pipeline to the offtake"),
                 ("Pipeline", f"{f['pipe'].replace('_', ' ')}, {f['pipe_distance_km']:,.0f} km "
                              f"({d.get('pipe_route_how', 'straight line x factor')})")]
        pc = (d.get("pipe_class_table") or {}).get(f["pipe"])
        if pc:
            pk = float(np.max(h["h2_pipe"]))
            rows += [("Pipeline capacity", f"{pc['cap_kgh']:,.0f} kg/h (limited by {pc['limit']}); peak flow {pk:,.0f} kg/h"),
                     ("Pipeline cost", f"€{pc['capex_per_km'] / 1e6:,.2f} million per km")]
        if tie:
            pk = float(np.max(h["h2_pipe"]))
            rows.append(("Pipeline spare capacity used", f"{100 * pk / max(inp.get('tiein_spare_kgh', 1), 1e-9):,.0f} % "
                                                         f"(peak {pk:,.0f} of {inp.get('tiein_spare_kgh', 0):,.0f} kg/h)"))
    if not rows:
        rows = [("Links", "No export cable or pipeline built")]
    return pd.DataFrame(rows, columns=["item", "value"])


def levelized_tab(lv, inp, d):
    u = lambda s: f'<span class="u">{s}</span>'
    items = []
    if not math.isnan(lv["lcoe"]):
        items.append(("LCOE, electricity delivered to the grid", f"€{lv['lcoe']:,.1f}" + u("/MWh"), "p"))
    if not math.isnan(lv["lcoh"]):
        items += [("LCOH, hydrogen delivered", f"€{lv['lcoh']:,.2f}" + u("/kg"), "h"),
                  ("LCOH in energy terms (LHV)", f"€{lv['lcoh_eur_mwh']:,.0f}" + u("/MWh H2"), "h")]
    if not math.isnan(lv["lcoe_generation"]):
        items.append(("Cost of generation (wind + PV)", f"€{lv['lcoe_generation']:,.1f}" + u("/MWh"), "n"))
    if lv["h2_kg"] > 1 and lv["grid_mwh"] > 1:
        items.append(("Share of shared costs carried by hydrogen", f"{100 * lv['share_h2']:,.1f}" + u("%"), "s"))
    theme.kpis(items)
    ref_e = {"ppa": inp.get("ppa_price_eur_mwh"), "cfd": inp.get("cfd_strike_eur_mwh")}.get(d.get("elec_revenue"))
    a, b = st.columns(2)
    if not math.isnan(lv["lcoe"]):
        a.plotly_chart(charts.levelized(lv, "e", ref_e, "PPA price" if d.get("elec_revenue") == "ppa" else "Strike"),
                       width="stretch")
    if not math.isnan(lv["lcoh"]):
        b.plotly_chart(charts.levelized(lv, "h", inp.get("h2_price_eur_kg"), "Hydrogen price"), width="stretch")
    st.markdown(
        "**How these are calculated.** Annual cost = annualised investment (capital recovery factor at the discount "
        "rate over each lifetime) + fixed and variable O&M + TSO or hub fee; revenues and penalties are not "
        "included. Costs used only for hydrogen (electrolysers, water treatment, compressors, hydrogen tanks, "
        "pipeline) go to hydrogen; fuel cells go to electricity; every shared cost (wind, PV, export cable, "
        "platform, batteries, fees) is split by the electricity each product uses: "
        f"{lv['grid_mwh'] / 1e3:,.0f} GWh delivered to the grid and {lv['electricity_to_h2_mwh'] / 1e3:,.0f} GWh fed "
        "to the electrolysers. LCOE = electricity share / MWh delivered; LCOH = hydrogen share / kg delivered. "
        "Cost of generation = wind and PV cost / MWh generated. The net costs in the results workbook credit the "
        "other product's revenue instead of splitting costs.")
    st.dataframe(pd.DataFrame([{
        "component": r["component"], "rule": r["rule"], "annual cost, M EUR": round(r["annual_cost"] / 1e6, 3),
        "to electricity, M EUR": round(r["to_electricity"] / 1e6, 3),
        "to hydrogen, M EUR": round(r["to_hydrogen"] / 1e6, 3),
        "EUR/MWh": round(r["eur_per_mwh"], 2), "EUR/kg": round(r["eur_per_kg"], 3)} for r in lv["rows"]]),
        hide_index=True, width="stretch")


def step_results():
    res = ss.result
    if not res:
        st.markdown("## Results")
        st.info("No design yet. Set up the project and run it on the Run step.")
        st.button("Go to the run step", on_click=go, args=("Run",))
        return
    f, r, d = res["final"], res["reduced"], res["derived"]
    inp = res["inputs"]
    lv = res.get("levelized") or levelized(f, inp.get("lhv_h2_kwh_kg", 33.3))
    f = {**f, "elec_connection_used": d.get("elec_connection_used", "direct"),
         "h2_connection_used": d.get("h2_connection_used", "direct")}
    st.markdown(f"## {inp['site_name']}: lowest-cost design")
    st.caption(f"{NAMES[('use_case', inp['use_case'])]}. Sized on {res['tda']['blocks']:,} TDA blocks, checked on "
               f"8,760 hours, {res['timing']['total_s']:.0f} s with "
               f"{'HiGHS' if res['solver'] == 'highs' else 'GLPK'}.")
    built_any = f["C_wt"] + f["C_pv"] > 1e-3
    if not built_any:
        st.warning("Nothing is built: with these costs and revenues every MWh would cost more than it earns, and no "
                   "volume is contracted. Lower the costs, raise the price, or contract a volume under a PPA.")
    gen = f["gen_wind_mwh"] + f["gen_pv_mwh"]
    u = lambda s: f'<span class="u">{s}</span>'
    net = f["net_cost"]
    items = [("Net annual surplus (revenue − cost)" if net < 0 else "Net annual cost (cost − revenue)",
              eur(abs(net)) + u("/yr"), "n"),
             ("Investment", eur(f["capex_total"]), "n")]
    if f["grid_mwh"] > 1:
        items += [("Electricity to the grid", f"{f['grid_mwh'] / 1e3:,.0f}" + u("GWh/yr"), "p"),
                  ("LCOE, levelized cost of electricity", f"€{lv['lcoe']:,.1f}" + u("/MWh"), "p")]
    if f["h2_kg"] > 1:
        items += [("Hydrogen delivered", f"{f['h2_kg'] / 1e3:,.0f}" + u("t/yr"), "h"),
                  ("LCOH, levelized cost of hydrogen", f"€{lv['lcoh']:,.2f}" + u("/kg"), "h")]
    if gen > 1:
        items.append(("Generation curtailed", f"{100 * f['curt_mwh'] / gen:,.1f}" + u("%"), "s"))
    theme.kpis(items)
    for msg in res.get("warnings", []):
        st.warning(msg)
    if f["short_e_mwh"] > 1 or f["short_h_kg"] > 1:
        st.warning(f"Not delivered after the full-year check: {f['short_e_mwh']:,.0f} MWh of electricity and "
                   f"{f['short_h_kg'] / 1e3:,.1f} t of hydrogen. Usually the sea area, deck area or grid capacity "
                   "limits the design; relax one of them and run again.")
    design = drawings.design_from_final(f)
    safe_drawing("section", inp, design, f)
    a, b = st.columns([7, 5], gap="large")
    with a:
        safe_drawing("island", inp, design, f)
    with b:
        st.markdown("#### On the island")
        st.dataframe(cap_table(f, CAP_ISLAND), hide_index=True, width="stretch")
        st.markdown("#### Links and onshore")
        st.dataframe(cap_table(f, CAP_SHORE), hide_index=True, width="stretch")
        if f["pipe"] != "none":
            st.caption(f"Hydrogen pipeline: {f['pipe'].replace('_', ' ')}, {f['pipe_distance_km']:.0f} km.")
        st.markdown("#### Connections")
        st.dataframe(connection_table(res, f), hide_index=True, width="stretch")
    opts = res.get("connection_options") or []
    if len(opts) > 1:
        best = min(o["objective"] for o in opts)
        st.markdown("#### Connection options compared")
        st.dataframe(pd.DataFrame([{
            "electricity": NAMES[("elec_connection", o["electricity"])],
            "hydrogen": NAMES[("h2_connection", o["hydrogen"])],
            "annual cost vs best, M EUR/yr": f"{(o['objective'] - best) / 1e6:+,.2f}",
            "chosen": "yes" if o["chosen"] else ""} for o in opts]), hide_index=True, width="stretch")
        st.caption("Each option was sized on the same reduced year; the cheapest was then checked on all 8,760 hours.")
    safe_drawing("atlas", inp, design, f)
    tabs = st.tabs(["Levelized costs", "Energy flows", "Hour by hour", "Storage", "Costs and revenues", "TDA check",
                    "Map of the design", "Download"])
    h = res["hourly"]
    with tabs[0]:
        levelized_tab(lv, inp, d)
    tabs = tabs[1:]
    with tabs[0]:
        st.plotly_chart(charts.sankey(f, {**d, "cable_eff": d.get("cable_eff") or P.derive(inp)["cable_eff"]}),
                        width="stretch")
    with tabs[1]:
        day = st.slider("First day of the week shown", 1, 359, 15, key="week_day")
        st.plotly_chart(charts.week(h, day - 1), width="stretch")
        a, b = st.columns(2)
        a.plotly_chart(charts.carpet(h, "p_grid", "Power to the grid", "MW", theme.PALETTE["power"]),
                       width="stretch")
        h2 = {"h2": np.asarray(h["h2_off"]) + np.asarray(h["h2_on"])}
        b.plotly_chart(charts.carpet(h2, "h2", "Hydrogen production", "kg/h", theme.PALETTE["h2_ink"]),
                       width="stretch")
    with tabs[2]:
        st.plotly_chart(charts.storage(h), width="stretch")
    with tabs[3]:
        st.plotly_chart(charts.costs(f), width="stretch")
        rows = [("Total annual cost", f["total_cost"]), ("Electricity revenue", -f["rev_e"]),
                ("Hydrogen revenue", -f["rev_h"]), ("Penalty for undelivered energy", f["penalty"]),
                ("Net annual cost", f["net_cost"])]
        st.dataframe(pd.DataFrame([(k, f"{v / 1e6:,.2f}") for k, v in rows], columns=["item", "M EUR per year"]),
                     hide_index=True, width="stretch")
        st.caption("Investment is annualised with the capital recovery factor of each component's lifetime at the "
                   "discount rate, plus fixed O&M. Revenues are shown negative.")
    with tabs[4]:
        t = res["tda"]
        diff = 100 * (f["net_cost"] - r["net_cost"]) / max(abs(r["total_cost"]), 1.0)
        theme.kpis([("Time steps in the reduced year", f"{t['blocks']:,} blocks", "n"),
                    ("Shape error of the energy balance", f"{100 * t['eps']:.2f} %", "n"),
                    ("Persistent episodes kept exactly", f"{t['n_fixed']:,}", "n"),
                    ("Cost change in the full-year check", f"{diff:+.2f}" + '<span class="u">%</span>', "n")])
        a, b = st.columns(2)
        a.plotly_chart(charts.tda_balance(t["diag"]), width="stretch")
        b.plotly_chart(charts.tda_diagram(t["diag"]), width="stretch")
        sc = res["scale"]
        st.caption(
            f"Series used to place the cuts: {', '.join(t['attrs'])}. Repair factors applied on the full year: "
            f"generation ×{sc['generation']:.3f}, conversion ×{sc['conversion']:.3f}, storage ×{sc['storage']:.3f}. "
            "The persistence diagram lists every deficit episode of the wind balance: a point far from the diagonal "
            "is a long, deep lull. Points of the reduced year sit on those of the full year, so the storage need is "
            "preserved.")
    with tabs[5]:
        site_map(inp, d, f, h)
    with tabs[6]:
        st.download_button("Results workbook (Excel)", report.results_xlsx(res),
                           f"EVOLVE_results_{inp['site_name'][:30].replace(' ', '_')}.xlsx", type="primary")
        st.download_button("Inputs workbook of this run (Excel)", workbook.to_bytes(inp, ss.series, ss.notes),
                           f"EVOLVE_inputs_{inp['site_name'][:30].replace(' ', '_')}.xlsx")
        for kind, name in (("section", "Route section"), ("island", "Island"), ("atlas", "Connection atlas")):
            st.download_button(f"{name} drawing (HTML, opens in any browser)",
                               drawing(kind, inp, design, f, animate=False),
                               f"EVOLVE_{kind}.html", mime="text/html", key=f"dl_{kind}")
        st.caption("The results workbook holds the summary, capacities, annual costs, the 8,760-hour operation, the "
                   "TDA blocks and every input used.")


# ---------------------------------------------------------------------------
# navigation
# ---------------------------------------------------------------------------

def nav_buttons(step):
    i = STEPS.index(step)
    st.write("")
    a, b, _ = st.columns([1, 1, 5])
    if i > 0:
        a.button("Back", on_click=go, args=(STEPS[i - 1],), key=f"back_{step}", width="stretch")
    if i < len(STEPS) - 1:
        b.button(f"Next: {STEPS[i + 1].lower()}", on_click=go, args=(STEPS[i + 1],), type="primary",
                 key=f"next_{step}", width="stretch")


def _keep_nav():
    if not ss.nav:                     # clicking the selected step again would clear it
        ss.nav = ss.get("_last_nav", STEPS[0])


def main():
    sidebar()
    if not ss.started:
        landing()
        return
    if ss.get("_goto"):
        ss.nav = ss.pop("_goto")
    st.segmented_control("Step", STEPS, key="nav", label_visibility="collapsed", on_change=_keep_nav)
    ss._last_nav = ss.nav
    {"Site": step_site, "Use case": step_use, "Data": step_data, "Technologies": step_tech, "Run": step_run,
     "Results": step_results}[ss.nav]()


main()
