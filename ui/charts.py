"""Plotly figures with the planner's palette (electricity amber, hydrogen cyan, storage violet)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .theme import PALETTE as C

LHV_GWH_PER_T = 33.3 / 1000.0          # 1 t H2 = 0.0333 GWh (LHV)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_month_of_hour = np.repeat(np.arange(12), [d * 24 for d in (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)])


def _style(fig, h=320, legend=True):
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=36, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(family="IBM Plex Sans, sans-serif", size=12,
                                                               color=C["ink"]),
                      showlegend=legend, legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)"),
                      hoverlabel=dict(font_family="IBM Plex Sans"))
    fig.update_xaxes(gridcolor="#DCE5EA", zerolinecolor="#B9C7CF")
    fig.update_yaxes(gridcolor="#DCE5EA", zerolinecolor="#B9C7CF")
    return fig


def monthly_cf(series: dict):
    fig = go.Figure()
    for k, name, col in (("wind_cf", "Wind", C["tide"]), ("pv_cf", "Floating PV", C["power"])):
        if series.get(k) is not None:
            m = pd.Series(series[k]).groupby(_month_of_hour).mean() * 100
            fig.add_bar(x=MONTHS, y=m.values, name=f"{name} (year {np.mean(series[k]) * 100:.1f} %)",
                        marker_color=col, hovertemplate="%{x}: %{y:.1f} %<extra>" + name + "</extra>")
    fig.update_layout(barmode="group", title=dict(text="Monthly capacity factor, %", font_size=14))
    return _style(fig)


def duration(series: dict):
    fig = go.Figure()
    x = np.linspace(0, 100, 8760)
    for k, name, col in (("wind_cf", "Wind", C["tide"]), ("pv_cf", "Floating PV", C["power"])):
        if series.get(k) is not None:
            fig.add_scatter(x=x, y=np.sort(series[k])[::-1] * 100, name=name, line=dict(color=col, width=2),
                            hovertemplate="%{y:.0f} % or more for %{x:.0f} % of the year<extra>" + name + "</extra>")
    fig.update_layout(title=dict(text="Duration curve: share of the year above each output", font_size=14),
                      xaxis_title="% of hours", yaxis_title="capacity factor, %")
    return _style(fig)


def price_profile(price):
    s = pd.Series(price)
    fig = go.Figure()
    fig.add_bar(x=MONTHS, y=s.groupby(_month_of_hour).mean().values, marker_color=C["abyss"],
                name="monthly mean", hovertemplate="%{x}: %{y:.1f} EUR/MWh<extra></extra>")
    fig.update_layout(title=dict(text=f"Day-ahead price, EUR/MWh (mean {s.mean():.1f}, "
                                      f"{int((s < 0).sum())} negative hours)", font_size=14))
    return _style(fig, legend=False)


def sankey(f: dict, d: dict):
    """Annual energy flows in GWh (hydrogen at its lower heating value)."""
    gw, gp = f["gen_wind_mwh"] / 1e3, f["gen_pv_mwh"] / 1e3
    ez_off, ez_on = f["sum_p_we"] / 1e3, f["sum_p_pe"] / 1e3
    cab = f["sum_p_cab_f"] / 1e3
    curt = f["curt_mwh"] / 1e3
    grid = f["grid_mwh"] / 1e3
    h2_kg = f["h2_kg"]
    h2k = d["h2_kg_per_mwh"]
    h2_off_gwh = ez_off * h2k * LHV_GWH_PER_T          # kg -> t -> GWh
    h2_on_gwh = ez_on * h2k * LHV_GWH_PER_T
    pipe_gwh = f["sum_h2_pipe"] / 1000 * LHV_GWH_PER_T
    fc_gwh = (f["sum_h2fc_off"] + f["sum_h2fc_on"]) / 1000 * d["fc_mwh_per_kg"] * 1000 / 1000
    sold_gwh = h2_kg / 1000 * LHV_GWH_PER_T
    labels = ["Wind", "Floating PV", "Island power", "Curtailed", "Island electrolyser", "Export cable",
              "Onshore power", "Grid", "Onshore electrolyser", "Hydrogen", "Hydrogen sold", "Losses and own use"]
    colors = [C["tide"], C["power"], C["power"], C["muted"], C["h2"], C["power"], C["power"], C["power"],
              C["h2"], C["h2"], C["h2"], C["muted"]]
    links = []
    add = lambda a, b, v, col: links.append((a, b, max(v, 0.0), col)) if v > 0.05 else None
    add(0, 2, gw, "rgba(31,111,139,0.35)")
    add(1, 2, gp, "rgba(227,167,47,0.35)")
    add(2, 3, curt, "rgba(154,168,176,0.45)")
    add(2, 4, ez_off, "rgba(63,193,201,0.35)")
    add(2, 5, cab, "rgba(227,167,47,0.35)")
    add(5, 6, cab * d.get("cable_eff", 1.0), "rgba(227,167,47,0.35)")
    add(5, 11, cab * (1 - d.get("cable_eff", 1.0)), "rgba(154,168,176,0.45)")
    add(6, 7, grid, "rgba(227,167,47,0.45)")
    add(6, 8, ez_on, "rgba(63,193,201,0.35)")
    add(4, 9, h2_off_gwh, "rgba(63,193,201,0.45)")
    add(4, 11, max(ez_off - h2_off_gwh, 0), "rgba(154,168,176,0.45)")
    add(8, 9, h2_on_gwh, "rgba(63,193,201,0.45)")
    add(8, 11, max(ez_on - h2_on_gwh, 0), "rgba(154,168,176,0.45)")
    add(9, 10, sold_gwh, "rgba(63,193,201,0.55)")
    add(9, 11, max(h2_off_gwh + h2_on_gwh - sold_gwh, 0), "rgba(154,168,176,0.45)")
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, color=colors, pad=14, thickness=14, line=dict(width=0)),
        link=dict(source=[l[0] for l in links], target=[l[1] for l in links], value=[l[2] for l in links],
                  color=[l[3] for l in links], hovertemplate="%{source.label} to %{target.label}: %{value:.1f} GWh"
                                                              "<extra></extra>")))
    fig.update_layout(title=dict(text="Annual energy flows, GWh (hydrogen at lower heating value)", font_size=14))
    return _style(fig, h=380, legend=False)


def week(hourly: dict, start_day: int):
    s, e = start_day * 24, start_day * 24 + 168
    t = np.arange(s, e)
    fig = go.Figure()
    uses = [("p_grid", "To grid", C["power"]), ("p_we", "Island electrolyser", C["h2"]),
            ("p_pe", "Onshore electrolyser", "#2A9DA4"), ("bat_off_ch", "Battery charging", C["store"]),
            ("bat_on_ch", "Battery charging (onshore)", "#B4A7DA"), ("p_curt_off", "Curtailed", C["muted"])]
    for k, name, col in uses:
        y = hourly.get(k)
        if y is not None and y[s:e].max() > 1e-3:
            fig.add_scatter(x=t, y=y[s:e], name=name, stackgroup="u", line=dict(width=0.5, color=col),
                            fillcolor=col, hovertemplate="%{y:.1f} MW<extra>" + name + "</extra>")
    gen = hourly["gen_wind"][s:e] + hourly["gen_pv"][s:e]
    fig.add_scatter(x=t, y=gen, name="Generation", line=dict(color=C["abyss"], width=1.6),
                    hovertemplate="%{y:.1f} MW<extra>Generation</extra>")
    fig.update_layout(title=dict(text=f"One week, hour by hour (days {start_day + 1}-{start_day + 7}), MW",
                                 font_size=14), xaxis_title="hour of the year")
    return _style(fig, h=360)


def carpet(hourly: dict, key: str, label: str, unit: str, color: str):
    z = np.asarray(hourly[key][:8760]).reshape(365, 24).T
    fig = go.Figure(go.Heatmap(z=z, x=np.arange(1, 366), y=np.arange(24),
                               colorscale=[[0, "#F2F6F8"], [1, color]],
                               hovertemplate="day %{x}, hour %{y}: %{z:.1f} " + unit + "<extra></extra>",
                               colorbar=dict(title=unit, thickness=10)))
    fig.update_layout(title=dict(text=f"{label} through the year (day x hour)", font_size=14),
                      xaxis_title="day of the year", yaxis_title="hour")
    return _style(fig, h=300, legend=False)


def storage(hourly: dict):
    fig = go.Figure()
    for k, name, col, scale, unit in (("soc_tank_on", "Onshore H2 tank", C["store"], 1e-3, "t"),
                                      ("soc_tank_off", "Island H2 tank", "#B4A7DA", 1e-3, "t")):
        y = hourly.get(k)
        if y is not None and y.max() > 1:
            fig.add_scatter(y=y * scale, name=f"{name}, {unit}", line=dict(color=col, width=1.6),
                            hovertemplate="hour %{x}: %{y:.1f} " + unit + "<extra>" + name + "</extra>")
    for k, name, col in (("soc_bat_on", "Onshore battery, MWh", C["power"]), ("soc_bat_off", "Island battery, MWh", "#C99A3A")):
        y = hourly.get(k)
        if y is not None and y.max() > 0.1:
            fig.add_scatter(y=y, name=name, line=dict(color=col, width=1), yaxis="y2",
                            hovertemplate="hour %{x}: %{y:.1f} MWh<extra></extra>")
    fig.update_layout(title=dict(text="Storage level over the year", font_size=14), xaxis_title="hour of the year",
                      yaxis=dict(title="hydrogen, t"), yaxis2=dict(title="battery, MWh", overlaying="y", side="right",
                                                                     showgrid=False))
    if not fig.data:
        fig.add_annotation(text="No storage was built in this design", showarrow=False, x=0.5, y=0.5,
                           xref="paper", yref="paper")
    return _style(fig, h=320)


def costs(f: dict):
    parts = {k: v for k, v in f["cost_parts"].items() if abs(v) > 1.0}
    s = pd.Series(parts).sort_values()
    fig = go.Figure(go.Bar(x=s.values / 1e6, y=s.index, orientation="h", marker_color=C["tide"],
                           hovertemplate="%{y}: %{x:.2f} M EUR/yr<extra></extra>",
                           text=[f"{v / 1e6:.2f}" for v in s.values], textposition="outside"))
    fig.update_layout(title=dict(text=f"Annual cost by component, M EUR/yr (total {f['total_cost'] / 1e6:.1f})",
                                 font_size=14), xaxis_title="M EUR per year (annualised investment + O&M)")
    return _style(fig, h=max(260, 28 * len(s) + 80), legend=False)


def tda_balance(diag: dict):
    S, Sr = diag["S"], diag["S_reduced"]
    idx = np.arange(0, 8760, 3)
    fig = go.Figure()
    fig.add_scatter(x=idx, y=S[idx], name="Full year (8,760 h)", line=dict(color=C["muted"], width=3))
    fig.add_scatter(x=idx, y=Sr[idx], name="TDA blocks", line=dict(color=C["tide"], width=1.4))
    fig.update_layout(title=dict(text="Cumulative wind energy balance: full year and TDA blocks", font_size=14),
                      xaxis_title="hour of the year", yaxis_title="cumulative balance, CF·h")
    return _style(fig, h=320)


def tda_diagram(diag: dict):
    def top(D, n=40):                                   # the most persistent episodes; the rest is noise
        return D[np.argsort(-(D[:, 1] - D[:, 0]))[:n]]
    a, b = top(diag["dgm_full"]), top(diag["dgm_reduced"])
    lo = float(min(a.min(), b.min())); hi = float(max(a.max(), b.max()))
    fig = go.Figure()
    fig.add_scatter(x=[lo, hi], y=[lo, hi], mode="lines", line=dict(color="#B9C7CF", dash="dot"),
                    showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=a[:, 0], y=a[:, 1], mode="markers", name="Full year",
                    marker=dict(color=C["muted"], size=9, opacity=0.6),
                    hovertemplate="trough %{x:.1f}, refilled at %{y:.1f}<extra>Full year</extra>")
    fig.add_scatter(x=b[:, 0], y=b[:, 1], mode="markers", name="TDA blocks",
                    marker=dict(color=C["tide"], size=5),
                    hovertemplate="trough %{x:.1f}, refilled at %{y:.1f}<extra>TDA blocks</extra>")
    fig.update_layout(title=dict(text="Persistence diagram: the 40 deepest lulls", font_size=14),
                      xaxis_title="depth of the trough (birth)", yaxis_title="level where it is refilled (death)")
    return _style(fig, h=320)


def levelized(lv: dict, which: str, ref: float | None = None, ref_label: str = ""):
    """Breakdown of LCOE (which='e', EUR/MWh) or LCOH (which='h', EUR/kg) by component."""
    key = "eur_per_mwh" if which == "e" else "eur_per_kg"
    total = lv["lcoe"] if which == "e" else lv["lcoh"]
    unit = "EUR/MWh" if which == "e" else "EUR/kg"
    rows = sorted([r for r in lv["rows"] if r[key] > 1e-6], key=lambda r: r[key])
    col = C["power"] if which == "e" else C["h2_ink"]
    fig = go.Figure(go.Bar(x=[r[key] for r in rows], y=[r["component"] for r in rows], orientation="h",
                           marker_color=col, text=[f"{r[key]:,.2f}" for r in rows], textposition="outside",
                           customdata=[r["rule"] for r in rows],
                           hovertemplate="%{y}: %{x:.2f} " + unit + " (%{customdata})<extra></extra>"))
    name = "LCOE" if which == "e" else "LCOH"
    fig.update_layout(title=dict(text=f"{name} {total:,.2f} {unit}, by component", font_size=14),
                      xaxis_title=unit)
    if ref:
        fig.add_vline(x=ref, line_dash="dash", line_color=C["abyss"],
                      annotation_text=f"{ref_label} {ref:,.2f}", annotation_position="top")
    return _style(fig, h=max(240, 30 * len(rows) + 90), legend=False)
