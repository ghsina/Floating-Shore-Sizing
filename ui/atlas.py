"""Connection atlas: a plan-view chart of the island, the wind farm, the export routes and the onshore ends.

Drawn from the real coastline (1 km land mask), with waterlines at fixed distances from the shore,
shortest sea routes around islands and headlands, a graticule, a scale bar and a legend. Depths are
not drawn: no bathymetry is bundled, and the island's depth is printed as entered.
"""
from __future__ import annotations

import math

import numpy as np

from evolve_planner import geo
from .svgkit import (ANIM_CSS, COAST, H2, INK, INK2, LAND, LAND_DARK, MUTED, PAPER, POWER, SEA, STEEL,
                     WHITE, chevrons, esc, label, page, path_d, point_at, poly_length, smooth_d)

W, H = 1000, 640
M = 30                      # frame margin
MX0, MY0, MX1, MY1 = M, M, W - M, H - M


def _nice(x):
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= x:
            return m * e
    return 10 * e


def _dms(v, pos, neg):
    h = pos if v >= 0 else neg
    v = abs(v)
    d = int(v)
    m = round((v - d) * 60)
    if m == 60:
        d, m = d + 1, 0
    return f"{d}°{m:02d}′{h}"


def _bbox(points):
    lat_c = float(np.mean([p[0] for p in points]))
    kx = geo.KM_PER_DEG * math.cos(math.radians(lat_c))
    ys = [p[0] * geo.KM_PER_DEG for p in points]
    xs = [p[1] * kx for p in points]
    w_km = max(max(xs) - min(xs), 1.0)
    h_km = max(max(ys) - min(ys), 1.0)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    w_km, h_km = w_km * 1.55 + 14, h_km * 1.55 + 14
    aspect = (MX1 - MX0) / (MY1 - MY0)
    if w_km / h_km < aspect:
        w_km = h_km * aspect
    else:
        h_km = w_km / aspect
    w_km, h_km = max(w_km, 40 * aspect), max(h_km, 40)
    if w_km / h_km < aspect:
        w_km = h_km * aspect
    else:
        h_km = w_km / aspect
    return ((cy - h_km / 2) / geo.KM_PER_DEG, (cy + h_km / 2) / geo.KM_PER_DEG,
            (cx - w_km / 2) / kx, (cx + w_km / 2) / kx, w_km)


def _turbine_plan(x, y, s=4.2, color=INK):
    arms = "".join(f'<line x1="0" y1="0" x2="{s * math.cos(math.radians(a)):.2f}" '
                   f'y2="{s * math.sin(math.radians(a)):.2f}"/>' for a in (-90, 30, 150))
    return (f'<g transform="translate({x:.1f},{y:.1f})" stroke="{color}" stroke-width="1.1" '
            f'stroke-linecap="round">{arms}<circle r="1.3" fill="{WHITE}"/></g>')


def _island_glyph(x, y, s=1.0, floating=True):
    """Small isometric platform seen from above-left, with its shadow on the water."""
    w, h = 16 * s, 8 * s
    deck = f"M{x - w} {y} L{x} {y - h} L{x + w} {y} L{x} {y + h} Z"
    cols = "".join(f'<rect x="{x + dx - 2 * s:.1f}" y="{y + dy:.1f}" width="{4 * s:.1f}" height="{6 * s:.1f}" '
                   f'fill="{STEEL}"/>' for dx, dy in ((-w + 3 * s, 0), (w - 3 * s, 0), (0, h - 2 * s)))
    blocks = (f'<path d="M{x - 6 * s} {y - 1 * s} l6 {-3 * s} l6 {3 * s} l-6 {3 * s} Z" fill="{H2}"/>'
              f'<path d="M{x - 6 * s} {y - 1 * s} v{-4 * s} l6 {-3 * s} v{4 * s} Z" fill="#0E7577"/>'
              f'<path d="M{x} {y - 4 * s} v{-4 * s} l6 {3 * s} v{4 * s} Z" fill="#45B3B2"/>'
              f'<circle cx="{x + 9 * s:.1f}" cy="{y + 1 * s:.1f}" r="{2.6 * s:.1f}" fill="none" stroke="{WHITE}" '
              f'stroke-width="0.9"/>')
    shadow = f'<ellipse cx="{x + 4 * s:.1f}" cy="{y + 9 * s:.1f}" rx="{w * 1.05:.1f}" ry="{h * 0.7:.1f}" ' \
             f'fill="#2A5566" opacity="0.25"/>'
    return (shadow + (cols if floating else "") +
            f'<path d="{deck}" fill="#E9EDEF" stroke="{INK}" stroke-width="0.9"/>' + blocks)


def _pylon(x, y, s=1.0, color=POWER):
    return (f'<g transform="translate({x:.1f},{y:.1f}) scale({s})" fill="none" stroke="{INK}" stroke-width="1.1" '
            f'stroke-linejoin="round"><path d="M-6 9 L-1.6 -10 L1.6 -10 L6 9 M-4.2 1 L4.2 1 M-3 -4 L3 -4 '
            f'M-8 -6 L8 -6 M-4.2 1 L1.6 -10 M4.2 1 L-1.6 -10"/>'
            f'<circle cx="0" cy="12.5" r="3" fill="{color}" stroke="{WHITE}" stroke-width="1.2"/></g>')


def _tanks(x, y, s=1.0, color=H2):
    return (f'<g transform="translate({x:.1f},{y:.1f}) scale({s})" stroke="{INK}" stroke-width="0.9">'
            f'<rect x="-9" y="-8" width="7" height="14" rx="3.5" fill="{WHITE}"/>'
            f'<rect x="1" y="-11" width="8" height="17" rx="4" fill="{WHITE}"/>'
            f'<path d="M-9 0 h7 M1 0 h8" stroke="{color}" stroke-width="2"/>'
            f'<circle cx="0" cy="12" r="3" fill="{color}" stroke="{WHITE}" stroke-width="1.2"/></g>')


def _hub_glyph(x, y, used=True):
    col = POWER if used else MUTED
    return (f'<g transform="translate({x:.1f},{y:.1f})"><rect x="-8" y="-8" width="16" height="12" fill="{WHITE}" '
            f'stroke="{col}" stroke-width="1.8"/><path d="M-1 -6 L-4 -1 L0 -1 L-2 3" fill="none" stroke="{col}" '
            f'stroke-width="1.4"/><path d="M-6 4 v6 M6 4 v6" stroke="{INK}" stroke-width="1.2"/></g>')


def _tiein_glyph(x, y, used=True):
    col = H2 if used else MUTED
    return (f'<g transform="translate({x:.1f},{y:.1f})"><path d="M-8 -6 L8 6 L8 -6 L-8 6 Z" fill="{WHITE}" '
            f'stroke="{col}" stroke-width="1.8" stroke-linejoin="round"/><path d="M0 0 V-11 M-4 -11 H4" '
            f'stroke="{INK}" stroke-width="1.3"/></g>')


def atlas_svg(a: dict, animate: bool = True) -> str:
    """a: site_lat/lon/name, grid_lat/lon/name, h2_lat/lon/name, show_h2 (bool), sea_area_km2,
    n_turbines, floating, depth_m, cable (dict mw, mode, km or None), pipe (dict label, km or None),
    title (str)."""
    site = (float(a["site_lat"]), float(a["site_lon"]))
    grid = (float(a["grid_lat"]), float(a["grid_lon"]))
    hpt = (float(a["h2_lat"]), float(a["h2_lon"]))
    show_h2 = bool(a.get("show_h2"))
    hub = a.get("hub")
    tie = a.get("tiein")
    pts = [site, grid] + ([hpt] if show_h2 else [])
    pts += [(hub["lat"], hub["lon"])] if hub else []
    pts += [(tie["lat"], tie["lon"])] if tie else []
    lat_s, lat_n, lon_w, lon_e, w_km = _bbox(pts)
    land, lats, lons, have_coast = geo.land_window(lat_s - 0.05, lat_n + 0.05, lon_w - 0.08, lon_e + 0.08)
    land, lats, lons = geo.coarsen(land, lats, lons)
    res = geo._res(lats)
    sx = (MX1 - MX0) / (lon_e - lon_w)
    sy = (MY1 - MY0) / (lat_n - lat_s)
    P = lambda la, lo: (MX0 + (lo - lon_w) * sx, MY0 + (lat_n - la) * sy)
    km_px = (MX1 - MX0) / w_km
    out = []
    coast_xy = []
    cid = "mapclip"
    out.append(f'<defs><clipPath id="{cid}"><rect x="{MX0}" y="{MY0}" width="{MX1 - MX0}" height="{MY1 - MY0}"/>'
               f'</clipPath>'
               f'<pattern id="landtex" width="7" height="7" patternUnits="userSpaceOnUse">'
               f'<circle cx="1.5" cy="2" r="0.55" fill="{LAND_DARK}"/><circle cx="5" cy="5.5" r="0.45" '
               f'fill="{LAND_DARK}"/></pattern>'
               f'<pattern id="zonehatch" width="6" height="6" patternUnits="userSpaceOnUse" '
               f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="{WHITE}" '
               f'stroke-width="1" opacity="0.55"/></pattern></defs>')
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{PAPER}"/>')
    g = [f'<g clip-path="url(#{cid})">', f'<rect x="{MX0}" y="{MY0}" width="{MX1 - MX0}" height="{MY1 - MY0}" '
                                          f'fill="{SEA[-1]}"/>']

    def ring_path(rings):
        d = ""
        for r in rings:
            xy = [P(la, lo) for la, lo in r]
            d += path_d(xy, close=True) + " "
        return d

    if have_coast and land.any():
        from scipy.ndimage import gaussian_filter
        lat_mid = float(np.mean(lats))
        dist = gaussian_filter(geo.distance_from_land_km(land, lat_mid, res), 1.0)
        for (lo_, hi_), col in zip(((-1, 3), (3, 8), (8, 16), (16, 30)), SEA[:4]):
            for rings in geo.filled(dist, lats, lons, lo_, hi_):
                g.append(f'<path d="{ring_path(rings)}" fill="{col}" fill-rule="evenodd"/>')
        for k, (lev, op) in enumerate(((0.55, 0.9), (1.2, 0.7), (2.0, 0.5), (3.0, 0.32), (4.3, 0.2))):
            for ln in geo.contours(dist, lats, lons, lev):
                xy = [P(la, lo) for la, lo in ln]
                g.append(f'<path d="{path_d(xy)}" fill="none" stroke="{WHITE}" stroke-width="0.8" opacity="{op}"/>')
        sm = geo.smooth_field(land, 0.8)
        for rings in geo.filled(sm, lats, lons, 0.5, 2.0):
            d = ring_path(rings)
            g.append(f'<path d="{d}" fill="{LAND}" fill-rule="evenodd"/>'
                     f'<path d="{d}" fill="url(#landtex)" fill-rule="evenodd" opacity="0.8"/>')
        for ln in geo.contours(sm, lats, lons, 0.5):
            xy = [P(la, lo) for la, lo in ln]
            coast_xy.extend(xy[::3])
            g.append(f'<path d="{path_d(xy)}" fill="none" stroke="{COAST}" stroke-width="0.9" '
                     f'stroke-linejoin="round"/>')
    # graticule
    span = lat_n - lat_s
    step = next((s for s in (1 / 12, 1 / 6, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0) if span / s <= 6), 45.0)
    lat_ticks = np.arange(math.ceil(lat_s / step) * step, lat_n, step)
    lon_ticks = np.arange(math.ceil(lon_w / step) * step, lon_e, step)
    for la in lat_ticks:
        y = P(la, lon_w)[1]
        g.append(f'<line x1="{MX0}" x2="{MX1}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK2}" stroke-width="0.5" '
                 f'opacity="0.35"/>')
    for lo in lon_ticks:
        x = P(lat_n, lo)[0]
        g.append(f'<line y1="{MY0}" y2="{MY1}" x1="{x:.1f}" x2="{x:.1f}" stroke="{INK2}" stroke-width="0.5" '
                 f'opacity="0.35"/>')
    # wind farm zone and turbines
    sx_, sy_ = P(*site)
    r_px = math.sqrt(max(float(a.get("sea_area_km2") or 0), 0.5) / math.pi) * km_px
    g.append(f'<circle cx="{sx_:.1f}" cy="{sy_:.1f}" r="{r_px:.1f}" fill="url(#zonehatch)" stroke="{INK}" '
             f'stroke-width="1" stroke-dasharray="5 3"/>')
    n = int(min(max(a.get("n_turbines") or 0, 0), 80))
    if n:
        sp = max(r_px * math.sqrt(math.pi / max(n, 1)) * 0.95, 7)
        cand = []
        for i in range(-30, 31):
            for j in range(-30, 31):
                x = (j + (0.5 if i % 2 else 0)) * sp
                y = i * sp * 0.866
                if math.hypot(x, y) <= r_px - 3:
                    cand.append((math.hypot(x, y), x, y))
        cand.sort()
        for _, x, y in cand[1:n + 1] if len(cand) > n else cand[1:]:
            g.append(_turbine_plan(sx_ + x, sy_ + y))
    # routes
    legend = []
    lab = []
    cab = a.get("cable")
    pip = a.get("pipe")
    route_pts = {}
    def route(p0, p1):
        if have_coast:
            return geo.sea_route(land, lats, lons, p0, p1)
        return [p0, p1], p1, geo._gc_km(p0, p1)

    hub_pt = (hub["lat"], hub["lon"]) if hub else None
    tie_pt = (tie["lat"], tie["lon"]) if tie else None
    route_pts["cable"] = route(site, hub_pt if (hub and hub.get("used")) else grid)
    if hub and hub.get("used"):
        route_pts["hub_on"] = route(hub_pt, grid)
    if pip or show_h2:
        route_pts["pipe"] = route(site, tie_pt if (tie and tie.get("used") and pip) else hpt)
    if tie and tie.get("used") and pip:
        route_pts["tie_on"] = route(tie_pt, hpt)

    def draw_route(key, color, text, dashed_on=True):
        r, lf, km = route_pts[key]
        xy = [P(la, lo) for la, lo in r]
        lfx, lfy = P(*lf)
        # offshore part and onshore part (after the landfall)
        k_lf = min(range(len(xy)), key=lambda k: (xy[k][0] - lfx) ** 2 + (xy[k][1] - lfy) ** 2)
        off, on = xy[:k_lf + 1], xy[k_lf:]
        d_off = smooth_d(off)
        g.append(f'<path d="{d_off}" fill="none" stroke="{WHITE}" stroke-width="6.5" stroke-linecap="round" '
                 f'opacity="0.9"/>')
        g.append(f'<path d="{d_off}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round"/>')
        if animate:
            g.append(f'<path d="{d_off}" fill="none" stroke="{WHITE}" stroke-width="1.2" stroke-dasharray="2 12" '
                     f'class="flow" opacity="0.9"/>')
        g.append(chevrons(off, color, spacing=90))
        if len(on) > 1 and dashed_on:
            g.append(f'<path d="{path_d(on)}" fill="none" stroke="{color}" stroke-width="2.2" '
                     f'stroke-dasharray="5 4" stroke-linecap="round"/>')
        g.append(f'<circle cx="{lfx:.1f}" cy="{lfy:.1f}" r="3.4" fill="{WHITE}" stroke="{color}" stroke-width="1.6"/>')
        # label along the route, reading left to right
        if text and len(off) > 1 and poly_length(off) > 80:
            simp = [tuple(p) for p in geo._rdp([tuple(p) for p in off], 6.0)]
            segs = sorted(((math.dist(simp[k], simp[k + 1]), k) for k in range(len(simp) - 1)), reverse=True)
            seg_len, k = segs[0]
            pid = f"lp_{key}"
            if seg_len >= len(text) * 6.2 + 20:
                p0, p1 = simp[k], simp[k + 1]
                if p1[0] < p0[0]:
                    p0, p1 = p1, p0
                out.insert(1, f'<defs><path id="{pid}" d="M{p0[0]:.1f} {p0[1]:.1f} L{p1[0]:.1f} {p1[1]:.1f}"/></defs>')
            else:
                lp = off if off[-1][0] >= off[0][0] else off[::-1]
                mx, my, _ = point_at(lp, 0.5)
                (x0, y0), (x1, y1) = lp[0], lp[-1]
                cx, cy = 2 * mx - (x0 + x1) / 2, 2 * my - (y0 + y1) / 2
                out.insert(1, f'<defs><path id="{pid}" d="M{x0:.1f} {y0:.1f} Q{cx:.1f} {cy:.1f} {x1:.1f} {y1:.1f}"/></defs>')
            lab.append(f'<text style="font-family:\'Archivo\',Arial,sans-serif;font-size:11.5px;font-weight:600;'
                       f'font-stretch:87%" fill="{color}" stroke="{PAPER}" stroke-width="3.4" paint-order="stroke" '
                       f'stroke-linejoin="round" dy="-8"><textPath href="#{pid}" startOffset="50%" '
                       f'text-anchor="middle">{esc(text)}</textPath></text>')
        return km

    for key, col, text in (("hub_on", POWER, "Existing link to shore (hub owner)"),
                           ("tie_on", H2, "Existing pipeline onwards")):
        if key in route_pts:
            xy = [P(la, lo) for la, lo in route_pts[key][0]]
            g.append(f'<path d="{smooth_d(xy)}" fill="none" stroke="{col}" stroke-width="2" opacity="0.75" '
                     f'stroke-dasharray="7 4" stroke-linecap="round"/>')
            legend.append(("dash", col, text))
    if cab:
        km_drawn = draw_route("cable", POWER, f"{cab.get('volt') or cab.get('mode', 'HVAC')} · "
                                              f"{cab.get('mw', 0):,.0f} MW · {cab.get('km', 0):,.0f} km")
        legend.append(("line", POWER, "Electricity export cable"))
    if pip:
        draw_route("pipe", H2, f"H2 pipeline · {pip.get('label', '')} · {pip.get('km', 0):,.0f} km")
        legend.append(("line", H2, "Hydrogen pipeline"))
    elif show_h2:
        r, lf, km = route_pts["pipe"]
        gx, gy = P(*grid)
        hx, hy = P(*hpt)
        g.append(f'<path d="M{gx:.1f} {gy:.1f} Q{(gx + hx) / 2:.1f} {min(gy, hy) - 30:.1f} {hx:.1f} {hy:.1f}" '
                 f'fill="none" stroke="{H2}" stroke-width="1.6" stroke-dasharray="2 4" stroke-linecap="round"/>')
        legend.append(("dots", H2, "Hydrogen to offtaker (transport not costed)"))
    if cab or pip:
        legend.append(("dash", INK2, "Onshore section beyond the landfall"))
    g.append("</g>")
    out += g
    # symbols on top of the clip so they never get cut
    sx_, sy_ = P(*site)
    out.append(_island_glyph(sx_, sy_, 1.4, bool(a.get("floating", True))))
    gx, gy = P(*grid)
    out.append(_pylon(gx, gy - 12, 1.0))
    if show_h2 or pip:
        hx, hy = P(*hpt)
        out.append(_tanks(hx, hy - 12, 1.0))
    if hub:
        hx_, hy_ = P(*hub_pt)
        out.append(_hub_glyph(hx_, hy_, bool(hub.get("used"))))
    if tie:
        tx_, ty_ = P(*tie_pt)
        out.append(_tiein_glyph(tx_, ty_, bool(tie.get("used"))))
    out += lab
    # place-name labels: names in serif, facts in Archivo
    depth = a.get("depth_m")

    def name_tag(x, y, name, sub, side="right"):
        anc = "start" if side == "right" else "end"
        dx = 16 if side == "right" else -16
        return (label(x + dx, y - 2, name, 14, 600, INK, anc, serif=True, halo_w=4) +
                (label(x + dx, y + 13, sub, 11, 500, INK2, anc, halo_w=3.5) if sub else ""))

    sub = (f"{'Floating' if a.get('floating', True) else 'Bottom-fixed'} · "
           f"{depth:,.0f} m deep · {float(a.get('sea_area_km2') or 0):,.0f} km² zone" if depth else "")
    gx0, _ = P(*grid)
    side = "left" if gx0 > sx_ else "right"
    if side == "left" and sx_ - r_px - 260 < MX0:
        side = "right"
    if side == "right" and sx_ + r_px + 260 > MX1:
        side = "left"
    out.append(name_tag(sx_ + (r_px * 0.7 if side == "right" else -r_px * 0.7), sy_ + r_px * 0.75 + 10,
                        a.get("site_name", "Island"), sub, side))
    if hub:
        sd = "right" if hx_ < MX1 - 240 else "left"
        out.append(name_tag(hx_, hy_ - 6, hub.get("name", "Offshore hub") + ("" if hub.get("used") else " (option)"),
                            f"{hub.get('kv', 0):,.0f} kV · {hub.get('spare', 0):,.0f} MW spare", sd))
    if tie:
        sd = "right" if tx_ < MX1 - 240 else "left"
        if hub and math.dist((tx_, ty_), (hx_, hy_)) < 140:
            sd = "left" if sd == "right" else "right"
        out.append(name_tag(tx_, ty_ - 6, tie.get("name", "Pipeline tie-in") + ("" if tie.get("used") else " (option)"),
                            f"{tie.get('bar', 0):,.0f} bar · {tie.get('spare', 0) / 1000:,.1f} t/h spare", sd))
    side_g = "right" if gx < MX1 - 220 else "left"
    out.append(name_tag(gx, gy - 4, a.get("grid_name", "Grid point"), "Grid connection", side_g))
    if show_h2 or pip:
        side_h = "right" if hx < MX1 - 220 else "left"
        out.append(name_tag(hx, hy - 4, a.get("h2_name", "Hydrogen offtake"), "Hydrogen offtake", side_h))
    # title cartouche
    out.append(f'<g transform="translate({MX0 + 14},{MY0 + 14})">'
               f'<rect width="300" height="54" rx="3" fill="{PAPER}" opacity="0.93" stroke="{INK}" stroke-width="0.8"/>'
               + label(12, 23, a.get("title", "Connection atlas"), 18, 600, INK, serif=True, halo=None)
               + label(12, 41, "Coastline from a 1 km land mask · routes are schematic", 11, 400, INK2, halo=None)
               + "</g>")
    # north arrow
    nx_, ny_ = MX1 - 34, MY0 + 46
    out.append(f'<g transform="translate({nx_},{ny_})"><path d="M0 -20 L7 8 L0 3 L-7 8 Z" fill="{INK}"/>'
               f'<path d="M0 -20 L0 3 L-7 8 Z" fill="{PAPER}" stroke="{INK}" stroke-width="0.8"/>'
               + label(0, 24, "N", 12, 700, INK, "middle", serif=True, halo=None) + "</g>")
    # legend
    items = [("zone", None, "Wind farm zone (sea area)"), ("turb", None, "Wind turbine"),
             ("isl", None, "Energy island"), ("pyl", None, "Grid connection")]
    if show_h2 or pip:
        items.append(("tank", None, "Hydrogen offtake"))
    if hub:
        items.append(("hub", None, "Offshore substation or cable hub"))
    if tie:
        items.append(("tie", None, "Pipeline tie-in point"))
    items += legend + [("water", None, "Waterlines: 0.5 to 4 km from shore")]
    lw = int(max(len(t) for _, _, t in items) * 6.0 + 64)
    lh = 19 * len(items) + 30
    keypts = [P(*site), P(*grid)] + ([P(*hpt)] if (show_h2 or pip) else [])
    for key in route_pts:
        r = route_pts[key][0]
        keypts += [P(*r[int(len(r) * f)]) for f in (0.25, 0.5, 0.75)] if len(r) > 3 else []

    def crowd(x, y, w, h):
        pts_in = sum(1 for (px, py) in keypts if x - 30 <= px <= x + w + 30 and y - 30 <= py <= y + h + 30)
        coast_in = sum(1 for (px, py) in coast_xy if x <= px <= x + w and y <= py <= y + h)
        return pts_in * 50 + coast_in

    corners = {"bl": (MX0 + 14, MY1 - 14 - lh), "br": (MX1 - 14 - lw, MY1 - 14 - lh),
               "tr": (MX1 - 14 - lw, MY0 + 80), "tl": (MX0 + 14, MY0 + 84)}
    best = min(corners, key=lambda k: (crowd(*corners[k], lw, lh), ["bl", "br", "tr", "tl"].index(k)))
    lx, ly = corners[best]
    out.append(f'<g transform="translate({lx},{ly})"><rect width="{lw}" height="{19 * len(items) + 30}" rx="3" '
               f'fill="{PAPER}" opacity="0.94" stroke="{INK}" stroke-width="0.8"/>'
               + label(12, 19, "Legend", 12.5, 600, INK, serif=True, halo=None))
    for k, (kind, col, text) in enumerate(items):
        y = 38 + 19 * k
        sym = ""
        if kind == "line":
            sym = (f'<line x1="12" x2="40" y1="{y - 4}" y2="{y - 4}" stroke="{WHITE}" stroke-width="6"/>'
                   f'<line x1="12" x2="40" y1="{y - 4}" y2="{y - 4}" stroke="{col}" stroke-width="3"/>')
        elif kind == "dash":
            sym = f'<line x1="12" x2="40" y1="{y - 4}" y2="{y - 4}" stroke="{col}" stroke-width="2" stroke-dasharray="5 4"/>'
        elif kind == "dots":
            sym = (f'<line x1="12" x2="40" y1="{y - 4}" y2="{y - 4}" stroke="{col}" stroke-width="1.8" '
                   f'stroke-dasharray="2 4" stroke-linecap="round"/>')
        elif kind == "zone":
            sym = f'<rect x="14" y="{y - 11}" width="24" height="13" fill="{SEA[2]}" stroke="{INK}" stroke-dasharray="4 2"/>'
        elif kind == "turb":
            sym = _turbine_plan(26, y - 4, 4.5)
        elif kind == "isl":
            sym = _island_glyph(26, y - 5, 0.62)
        elif kind == "pyl":
            sym = _pylon(26, y - 9, 0.55)
        elif kind == "tank":
            sym = _tanks(26, y - 9, 0.6)
        elif kind == "hub":
            sym = _hub_glyph(26, y - 6)
        elif kind == "tie":
            sym = _tiein_glyph(26, y - 4)
        elif kind == "water":
            sym = (f'<rect x="12" y="{y - 12}" width="28" height="15" fill="{SEA[1]}"/>'
                   + "".join(f'<path d="M12 {y - 9 + 3.5 * i} q7 -2 14 0 t14 0" fill="none" stroke="{WHITE}" '
                             f'stroke-width="0.8"/>' for i in range(3)))
        out[-1] += sym + label(50, y, text, 11.5, 500, INK, halo=None)
    out[-1] += "</g>"
    # scale bar
    L = _nice(w_km / 6)
    Lpx = L * km_px
    bx, by = (MX0 + 40, MY1 - 26) if best == "br" else (MX1 - 30 - Lpx, MY1 - 26)
    seg = "".join(f'<rect x="{bx + k * Lpx / 4:.1f}" y="{by:.1f}" width="{Lpx / 4:.1f}" height="5" '
                  f'fill="{INK if k % 2 == 0 else PAPER}" stroke="{INK}" stroke-width="0.7"/>' for k in range(4))
    out.append(f'<rect x="{bx - 12:.1f}" y="{by - 22:.1f}" width="{Lpx + 46:.1f}" height="40" rx="3" fill="{PAPER}" '
               f'opacity="0.9"/>' + seg + label(bx, by - 6, "0", 10.5, 500, INK, "middle", halo=None)
               + label(bx + Lpx, by - 6, f"{L:g} km", 10.5, 500, INK, "middle", halo=None))
    # neatline frame with alternating bands and coordinate labels
    fr = [f'<rect x="{MX0}" y="{MY0}" width="{MX1 - MX0}" height="{MY1 - MY0}" fill="none" stroke="{INK}" '
          f'stroke-width="1.2"/>',
          f'<rect x="{MX0 - 5}" y="{MY0 - 5}" width="{MX1 - MX0 + 10}" height="{MY1 - MY0 + 10}" fill="none" '
          f'stroke="{INK}" stroke-width="0.8"/>']
    sub_step = step / 4
    for k, la in enumerate(np.arange(math.floor(lat_s / sub_step) * sub_step, lat_n, sub_step)):
        y0 = P(la, lon_w)[1]
        y1 = P(la + sub_step, lon_w)[1]
        top, bot = max(min(y0, y1), MY0), min(max(y0, y1), MY1)
        if bot > top and int(round(la / sub_step)) % 2 == 0:
            for xx in (MX0 - 5, MX1):
                fr.append(f'<rect x="{xx}" y="{top:.1f}" width="5" height="{bot - top:.1f}" fill="{INK}"/>')
    for k, lo in enumerate(np.arange(math.floor(lon_w / sub_step) * sub_step, lon_e, sub_step)):
        x0 = P(lat_n, lo)[0]
        x1 = P(lat_n, lo + sub_step)[0]
        lft, rgt = max(min(x0, x1), MX0), min(max(x0, x1), MX1)
        if rgt > lft and int(round(lo / sub_step)) % 2 == 0:
            for yy in (MY0 - 5, MY1):
                fr.append(f'<rect x="{lft:.1f}" y="{yy}" width="{rgt - lft:.1f}" height="5" fill="{INK}"/>')
    for la in lat_ticks:
        y = P(la, lon_w)[1]
        fr.append(label(MX0 - 11, y, _dms(la, "N", "S"), 9.5, 500, INK2, "middle", halo=None,
                        extra=f'transform="rotate(-90 {MX0 - 11} {y:.1f})"'))
        fr.append(label(MX1 + 11, y, _dms(la, "N", "S"), 9.5, 500, INK2, "middle", halo=None,
                        extra=f'transform="rotate(90 {MX1 + 11} {y:.1f})"'))
    for lo in lon_ticks:
        x = P(lat_n, lo)[0]
        fr.append(label(x, MY0 - 10, _dms(lo, "E", "W"), 9.5, 500, INK2, "middle", halo=None))
        fr.append(label(x, MY1 + 18, _dms(lo, "E", "W"), 9.5, 500, INK2, "middle", halo=None))
    out += fr
    svg = (f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="Connection atlas: island, wind farm, export routes and onshore connection points">'
           + "".join(out) + "</svg>")
    return svg


def atlas_page(a: dict, animate=True) -> str:
    return page(atlas_svg(a, animate), ANIM_CSS)
