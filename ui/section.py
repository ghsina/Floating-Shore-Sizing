"""Route section: a side view from the island, along the export route, to the onshore plant.

The water depth at the island is the user's input; the seabed between the island and the shore is a
smooth schematic profile (no bathymetry is bundled) and the vertical scale is exaggerated. Distances
along the route and every capacity come from the model.
"""
from __future__ import annotations

import math

from .svgkit import label as _label
from .svgkit import (ANIM_CSS, BATT, H2, INK, INK2, MUTED, PAPER, POWER, SEA, STEEL, STORE, WHITE, esc,
                     page, smooth_d, turbine_side)

W, H = 1320, 440
SEA_Y = 196
X_ISL = 210
X_LAND = 860
GROUND_Y = SEA_Y - 14


FS = 1.3          # font scale: the drawing is shown narrower than its viewBox


def label(*a, **k):
    a = list(a)
    if len(a) > 3:
        a[3] = a[3] * FS
    return _label(*a, **k)


def _nice_step(span, n=6):
    raw = span / n
    e = 10 ** math.floor(math.log10(max(raw, 1e-9)))
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= raw:
            return m * e
    return 10 * e


def section_svg(d: dict, animate: bool = True) -> str:
    g = lambda k: float(d.get(k) or 0.0)
    floating = bool(d.get("floating", True))
    depth = max(g("depth_m"), 5.0)
    zmax = max(depth * 1.25, 30.0)
    bed_bottom = H - 60
    mpx = (bed_bottom - 30 - SEA_Y) / zmax          # px per metre of depth

    def bed_y(x):
        if x <= X_ISL - 160:
            t = 0.0
        else:
            t = min(max((x - (X_ISL - 160)) / (X_LAND - (X_ISL - 160)), 0), 1)
        prof = depth * (1 - t ** 1.6) ** 1.15 + 1.2 * math.sin(x / 37.0) * (1 - t)
        return SEA_Y + max(prof, 0.0) * mpx

    cab = g("C_cab") > 1e-3
    pipe = d.get("pipe") not in (None, "", "none")
    out = ['<defs>'
           f'<linearGradient id="sky2" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F8F5EE"/>'
           f'<stop offset="1" stop-color="#E3ECEE"/></linearGradient>'
           f'<linearGradient id="water" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{SEA[2]}"/>'
           f'<stop offset="1" stop-color="#4E8496"/></linearGradient>'
           '<pattern id="sed" width="9" height="9" patternUnits="userSpaceOnUse">'
           '<circle cx="2" cy="2" r="0.9" fill="#9A8F6E"/><circle cx="6.5" cy="6" r="0.7" fill="#9A8F6E"/></pattern>'
           '<pattern id="soil" width="12" height="8" patternUnits="userSpaceOnUse">'
           '<path d="M0 6 h5 M7 2 h4" stroke="#A39673" stroke-width="0.8"/></pattern>'
           '</defs>']
    out.append(f'<rect width="{W}" height="{H}" fill="url(#sky2)"/>')
    # water body and seabed
    xs = list(range(0, X_LAND + 1, 6)) + [X_LAND]
    bed = [(x, bed_y(x)) for x in xs]
    water = [(0, SEA_Y)] + [(X_LAND, SEA_Y)] + [(x, y) for x, y in reversed(bed)]
    out.append(f'<path d="M{water[0][0]} {water[0][1]} L{X_LAND + 40} {SEA_Y} L{X_LAND + 40} {bed_y(X_LAND) + 2} '
               + " ".join(f"L{x:.1f} {y:.1f}" for x, y in reversed(bed)) + ' Z" fill="url(#water)"/>')
    # land profile: beach rising to the ground level, then flat
    beach = [(X_LAND - 30, bed_y(X_LAND - 30)), (X_LAND, SEA_Y + 2), (X_LAND + 26, SEA_Y - 4),
             (X_LAND + 60, GROUND_Y), (W, GROUND_Y)]
    ground = [(0, bed_bottom + 200)] + bed[:-6] + beach + [(W, H), (0, H)]
    gd = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in ground) + " Z"
    out.append(f'<path d="{gd}" fill="#CDBF98"/><path d="{gd}" fill="url(#sed)" opacity="0.8"/>')
    land_top = [(X_LAND + 60, GROUND_Y), (W, GROUND_Y), (W, GROUND_Y + 10), (X_LAND + 60, GROUND_Y + 10)]
    out.append(f'<rect x="{X_LAND + 40}" y="{GROUND_Y}" width="{W - X_LAND - 40}" height="{H - GROUND_Y}" '
               f'fill="#D9CDAA"/><rect x="{X_LAND + 40}" y="{GROUND_Y}" width="{W - X_LAND - 40}" '
               f'height="{H - GROUND_Y}" fill="url(#soil)" opacity="0.9"/>'
               f'<rect x="{X_LAND + 40}" y="{GROUND_Y - 3}" width="{W - X_LAND - 40}" height="4" fill="#9DB07E"/>')
    out.append(f'<path d="{smooth_d(bed[:-2] + beach[:3])}" fill="none" stroke="#6E6347" stroke-width="1.3"/>')
    # sea surface and waves
    out.append(f'<line x1="0" x2="{X_LAND + 6}" y1="{SEA_Y}" y2="{SEA_Y}" stroke="{WHITE}" stroke-width="1.4"/>')
    waves = "".join(f'<path d="M{x} {SEA_Y} q8 -4 16 0 t16 0" fill="none" stroke="{WHITE}" stroke-width="1.1" '
                    f'opacity="0.8"/>' for x in range(-40, X_LAND - 20, 32))
    out.append(f'<g class="drift">{waves}</g>')
    # background turbines (part of the wind farm around the island)
    for k, x in enumerate((44, 104, 352)):
        hub = 74 if k == 1 else 62
        rot = 30 if k == 1 else 25
        out.append(f'<g opacity="{0.95 if k == 1 else 0.72}">' + turbine_side(x, SEA_Y, hub, rot, spin_s=5 + k) + "</g>")
        if floating:
            out.append(f'<rect x="{x - 4}" y="{SEA_Y - 3}" width="8" height="22" rx="3" fill="{STEEL}" opacity="0.9"/>')
            for sgn in (-1, 1):
                ax = x + sgn * 46
                out.append(f'<path d="M{x + sgn * 3} {SEA_Y + 17} Q{x + sgn * 24} {bed_y(ax) - 10:.1f} {ax} '
                           f'{bed_y(ax):.1f}" fill="none" stroke="#2E4B57" stroke-width="0.7" opacity="0.5"/>')
        else:
            out.append(f'<rect x="{x - 2.2}" y="{SEA_Y}" width="4.4" height="{bed_y(x) - SEA_Y:.1f}" fill="{STEEL}" '
                       f'opacity="0.8"/>')
    # inter-array cable from the farm to the island (on the seabed)
    ia = [(x, bed_y(x) - 2) for x in range(44, X_ISL - 30, 8)]
    out.append(f'<path d="{smooth_d(ia)}" fill="none" stroke="{POWER}" stroke-width="1.6" stroke-dasharray="4 3" '
               f'opacity="0.85"/>')
    # the island (side elevation)
    deck_y = SEA_Y - 46
    iw = 132
    x0 = X_ISL - iw / 2
    isl = []
    if floating:
        for cx in (x0 + 18, x0 + iw - 18):
            isl.append(f'<rect x="{cx - 10}" y="{deck_y + 8}" width="20" height="{SEA_Y + 36 - deck_y - 8}" '
                       f'fill="{STEEL}" stroke="{INK}" stroke-width="0.7"/>')
        isl.append(f'<rect x="{x0 + 4}" y="{SEA_Y + 30}" width="{iw - 8}" height="11" rx="4" fill="#55666E" '
                   f'stroke="{INK}" stroke-width="0.7"/>')
        for sgn, cx in ((-1, x0 + 10), (1, x0 + iw - 10)):
            ax = X_ISL + sgn * 175
            isl.append(f'<path d="M{cx} {SEA_Y + 44} C{cx + sgn * 40} {SEA_Y + 70} {ax - sgn * 50} {bed_y(ax) - 4:.1f} '
                       f'{ax} {bed_y(ax):.1f}" fill="none" stroke="#2E4B57" stroke-width="1.2"/>'
                       f'<path d="M{ax - 6} {bed_y(ax) + 1:.1f} l6 -7 l6 7 Z" fill="#2E4B57"/>')
    else:
        by = bed_y(X_ISL)
        for cx in (x0 + 18, x0 + iw - 18):
            isl.append(f'<line x1="{cx}" y1="{deck_y + 8}" x2="{cx + (-12 if cx < X_ISL else 12)}" y2="{by:.1f}" '
                       f'stroke="{STEEL}" stroke-width="5"/>')
        n_b = 5
        for k in range(n_b):
            y1 = SEA_Y - 30 + k * (by - SEA_Y + 30) / n_b
            y2 = SEA_Y - 30 + (k + 1) * (by - SEA_Y + 30) / n_b
            isl.append(f'<path d="M{x0 + 18} {y1:.1f} L{x0 + iw - 18} {y2:.1f} M{x0 + iw - 18} {y1:.1f} L{x0 + 18} {y2:.1f}" '
                       f'stroke="{STEEL}" stroke-width="1.4"/>')
    isl.append(f'<rect x="{x0}" y="{deck_y}" width="{iw}" height="10" fill="#9AA6AC" stroke="{INK}" stroke-width="0.8"/>')
    # equipment silhouettes on the deck, left to right, sized by the design
    eq = []
    if cab:
        eq.append(("sub", 30, 30, POWER))
    if g("C_ez_off") > 1e-3:
        eq.append(("ez", 40, 14, H2))
    if g("E_tank_off") > 1:
        eq.append(("tank", 26, 22, STORE))
    if g("E_bat_off") > 1e-3:
        eq.append(("bat", 20, 10, BATT))
    if g("C_fc_off") > 1e-3:
        eq.append(("fc", 14, 12, "#C9822F"))
    eq.append(("util", 20, 22, "#D8DDE0"))
    tot = sum(w for _, w, _, _ in eq) + 4 * (len(eq) - 1)
    sc = min(1.0, (iw - 12) / tot)
    xx = x0 + 6
    for kind, w, h, col in eq:
        w, h = w * sc, h
        if kind == "tank":
            for k in range(2):
                isl.append(f'<rect x="{xx + k * w / 2 + 1:.1f}" y="{deck_y - h}" width="{w / 2 - 2:.1f}" height="{h}" '
                           f'rx="{w / 4 - 1:.1f}" fill="{col}" stroke="{INK}" stroke-width="0.6"/>')
        elif kind == "util":
            isl.append(f'<rect x="{xx:.1f}" y="{deck_y - h}" width="{w:.1f}" height="{h}" fill="{col}" stroke="{INK}" '
                       f'stroke-width="0.6"/><rect x="{xx - 4:.1f}" y="{deck_y - h - 3}" width="{w + 8:.1f}" height="3" '
                       f'fill="#3D4A50"/>')
        else:
            isl.append(f'<rect x="{xx:.1f}" y="{deck_y - h}" width="{w:.1f}" height="{h}" fill="{col}" stroke="{INK}" '
                       f'stroke-width="0.6"/>')
            if kind == "sub":
                isl.append("".join(f'<rect x="{xx + 4 + 8 * k:.1f}" y="{deck_y - h - 7}" width="3" height="7" '
                                   f'fill="#E9ECEE" stroke="{INK}" stroke-width="0.4"/>' for k in range(3)))
            if kind == "ez":
                isl.append("".join(f'<line x1="{xx + w * k / 4:.1f}" x2="{xx + w * k / 4:.1f}" y1="{deck_y - h}" '
                                   f'y2="{deck_y}" stroke="#0B6466" stroke-width="0.6"/>' for k in range(1, 4)))
        xx += w + 4 * sc
    out.append(f'<g class="bob">{"".join(isl)}</g>')
    # export cable: lazy-wave riser, then on the seabed to the landfall, then HDD under the beach
    t_x = X_ISL + 170
    land_x = X_LAND - 36
    hdd_end = X_LAND + 92
    hub_x = X_ISL + 330 if d.get("hub_name") else None
    if cab:
        rise = [(X_ISL + iw / 2 - 6, deck_y + 6), (X_ISL + iw / 2 + 8, SEA_Y + 10)]
        if floating:
            mid = (X_ISL + 120, SEA_Y + (bed_y(X_ISL + 120) - SEA_Y) * 0.45)
            rise += [(X_ISL + 95, SEA_Y + (bed_y(X_ISL + 95) - SEA_Y) * 0.65), mid,
                     (X_ISL + 145, SEA_Y + (bed_y(X_ISL + 145) - SEA_Y) * 0.6)]
        else:
            rise = [(X_ISL + iw / 2 - 20, deck_y + 6), (X_ISL + iw / 2 - 26, bed_y(X_ISL + 50) - 3)]
        hdd = [(land_x, bed_y(land_x) - 1), (X_LAND, bed_y(X_LAND) + 22), (X_LAND + 50, GROUND_Y + 30),
               (hdd_end, GROUND_Y + 14)]
        if hub_x:
            run = [(x, bed_y(x) - 2.5) for x in range(int(t_x), int(hub_x - 14), 10)]
            own = rise + run + [(hub_x - 10, bed_y(hub_x - 10) - 8), (hub_x - 8, SEA_Y - 40)]
            onward = [(hub_x + 8, SEA_Y - 40), (hub_x + 10, bed_y(hub_x + 10) - 8)] + \
                [(x, bed_y(x) - 2.5) for x in range(int(hub_x + 24), int(land_x), 10)] + hdd
            od = smooth_d(onward)
            out.append(f'<path d="{od}" fill="none" stroke="{POWER}" stroke-width="2" stroke-dasharray="7 4" '
                       f'opacity="0.8"/>')
            hb = bed_y(hub_x)
            out.append(f'<path d="M{hub_x - 16} {hb:.1f} L{hub_x - 10} {SEA_Y - 30} M{hub_x + 16} {hb:.1f} '
                       f'L{hub_x + 10} {SEA_Y - 30} M{hub_x - 13} {SEA_Y + 10} L{hub_x + 13} {hb - 10:.1f} '
                       f'M{hub_x + 13} {SEA_Y + 10} L{hub_x - 13} {hb - 10:.1f}" stroke="{STEEL}" stroke-width="2.4" '
                       f'fill="none"/><rect x="{hub_x - 22}" y="{SEA_Y - 34}" width="44" height="6" fill="#9AA6AC" '
                       f'stroke="{INK}" stroke-width="0.7"/><rect x="{hub_x - 16}" y="{SEA_Y - 56}" width="32" '
                       f'height="22" fill="{POWER}" stroke="{INK}" stroke-width="0.7"/>'
                       + "".join(f'<rect x="{hub_x - 12 + 9 * k}" y="{SEA_Y - 63}" width="3" height="7" fill="#E9ECEE" '
                                 f'stroke="{INK}" stroke-width="0.4"/>' for k in range(3)))
            cpath = smooth_d(own)
        else:
            run = [(x, bed_y(x) - 2.5) for x in range(int(t_x), int(land_x), 10)]
            cpath = smooth_d(rise + run + hdd)
        out.append(f'<path d="{cpath}" fill="none" stroke="{WHITE}" stroke-width="5.5" opacity="0.7" '
                   f'stroke-linecap="round"/><path d="{cpath}" fill="none" stroke="{POWER}" stroke-width="3" '
                   f'stroke-linecap="round"/>')
        if animate:
            out.append(f'<path d="{cpath}" fill="none" stroke="{WHITE}" stroke-width="1.1" stroke-dasharray="2 12" '
                       f'class="flow"/>')
        if floating:
            mx, my = mid
            out.append("".join(f'<ellipse cx="{mx - 12 + 6 * k:.1f}" cy="{my - 1 + abs(k - 2) * 1.2:.1f}" rx="2.6" '
                               f'ry="4" fill="#F2C230" stroke="{INK}" stroke-width="0.5"/>' for k in range(5)))
    if pipe:
        prise = [(X_ISL - iw / 2 + 26, deck_y + 6), (X_ISL - iw / 2 + 30, SEA_Y + 30),
                 (X_ISL + 40, bed_y(X_ISL + 40) - 6), (X_ISL + 110, bed_y(X_ISL + 110) - 1)]
        prun = [(x, bed_y(x) + 3) for x in range(int(X_ISL + 130), int(land_x - 10), 10)]
        phdd = [(land_x - 10, bed_y(land_x - 10) + 4), (X_LAND, bed_y(X_LAND) + 32), (X_LAND + 50, GROUND_Y + 40),
                (hdd_end, GROUND_Y + 26)]
        pd = smooth_d(prise + prun + phdd)
        out.append(f'<path d="{pd}" fill="none" stroke="{WHITE}" stroke-width="7" opacity="0.6"/>'
                   f'<path d="{pd}" fill="none" stroke="{H2}" stroke-width="4.2"/>')
    # joint bay
    if cab or pipe:
        out.append(f'<rect x="{hdd_end - 2}" y="{GROUND_Y + 6}" width="22" height="28" fill="#B8AE90" stroke="{INK}" '
                   f'stroke-width="0.7"/>')
    # onshore underground run to the plant
    plant_x0 = hdd_end + 34
    if cab:
        out.append(f'<path d="M{hdd_end + 20} {GROUND_Y + 14} L{plant_x0 + 20} {GROUND_Y + 14} L{plant_x0 + 20} '
                   f'{GROUND_Y}" fill="none" stroke="{POWER}" stroke-width="2.4" stroke-dasharray="5 4"/>')
    if pipe:
        out.append(f'<path d="M{hdd_end + 20} {GROUND_Y + 26} L{W - 40} {GROUND_Y + 26}" fill="none" stroke="{H2}" '
                   f'stroke-width="3" stroke-dasharray="6 4"/>')
    # onshore plant, side elevations, only what is built
    plant = []
    hvdc = d.get("link_mode") == "HVDC"
    if cab:
        plant.append(("sub", 92, "HVDC converter station" if hvdc else "Substation",
                      f"{'HVDC' if hvdc else 'HVAC'} {g('C_cab'):,.0f} MW"))
    if g("C_ez_on") > 1e-3:
        plant.append(("ez", 54 + 24 * math.sqrt(g("C_ez_on") / 10), "Electrolysers", f"{g('C_ez_on'):,.1f} MW"))
    if g("C_cmp_on") > 1e-3:
        plant.append(("cmp", 34, "Compressor", f"{g('C_cmp_on'):,.2f} MW"))
    if g("E_tank_on") > 1:
        plant.append(("tank", 46 + 10 * min(math.sqrt(g("E_tank_on") / 20000), 4), "Hydrogen storage",
                      f"{g('E_tank_on') / 1000:,.1f} t"))
    if g("E_bat_on") > 1e-3:
        plant.append(("bat", 52, "Battery", f"{g('E_bat_on'):,.0f} MWh · {g('P_bat_on'):,.0f} MW"))
    if g("C_fc_on") > 1e-3:
        plant.append(("fc", 34, "Fuel cells", f"{g('C_fc_on'):,.1f} MW"))
    avail = W - 70 - plant_x0
    tot = sum(p[1] for p in plant) + 22 * max(len(plant) - 1, 0)
    sc = min(1.0, avail / tot) if tot else 1
    x = plant_x0
    gy = GROUND_Y
    labs = []
    for kind, w, name, val in plant:
        w *= sc
        out.append(f'<g transform="translate(0,{gy}) scale(1,1.35) translate(0,{-gy})">')
        if kind == "sub":
            if hvdc:
                out.append(f'<path d="M{x} {gy} V{gy - 50} L{x + w * 0.35} {gy - 64} L{x + w * 0.7} {gy - 50} V{gy} Z" '
                           f'fill="#E7E3D8" stroke="{INK}" stroke-width="0.8"/>'
                           f'<rect x="{x + 6}" y="{gy - 40}" width="{w * 0.7 - 12:.1f}" height="5" fill="{POWER}"/>')
                tx = x + w * 0.74
            else:
                out.append(f'<path d="M{x + 4} {gy} V{gy - 46} H{x + w * 0.62} V{gy} M{x + 4} {gy - 40} H{x + w * 0.62}" '
                           f'fill="none" stroke="{STEEL}" stroke-width="2"/>')
                tx = x + 10
            out.append(f'<rect x="{tx:.1f}" y="{gy - 24}" width="{w * 0.3:.1f}" height="24" fill="{POWER}" stroke="{INK}" '
                       f'stroke-width="0.7"/>'
                       + "".join(f'<line x1="{tx + 3 + k * 3.2:.1f}" x2="{tx + 3 + k * 3.2:.1f}" y1="{gy - 21}" '
                                 f'y2="{gy - 3}" stroke="#8E3F0E" stroke-width="0.8"/>' for k in range(int(w * 0.3 / 3.2) - 1))
                       + "".join(f'<rect x="{tx + 4 + k * 7:.1f}" y="{gy - 32}" width="3" height="8" fill="#E9ECEE" '
                                 f'stroke="{INK}" stroke-width="0.4"/>' for k in range(3)))
            # pylon and line to the grid
            px = x + w * 0.88
            out.append(f'<path d="M{px - 9} {gy} L{px - 2} {gy - 78} L{px + 2} {gy - 78} L{px + 9} {gy} '
                       f'M{px - 6.5} {gy - 26} L{px + 6.5} {gy - 26} M{px - 4.5} {gy - 52} L{px + 4.5} {gy - 52} '
                       f'M{px - 14} {gy - 68} L{px + 14} {gy - 68} M{px - 6.5} {gy - 26} L{px + 4.5} {gy - 52} '
                       f'M{px + 6.5} {gy - 26} L{px - 4.5} {gy - 52}" fill="none" stroke="{INK}" stroke-width="1"/>'
                       f'<path d="M{px + 14} {gy - 68} Q{(px + W) / 2:.1f} {gy - 44} {W} {gy - 70}" fill="none" '
                       f'stroke="{INK2}" stroke-width="0.8"/>')
        elif kind == "ez":
            hgt = 34
            teeth = max(3, int(w / 16))
            roof = f"M{x} {gy - hgt} " + " ".join(
                f"L{x + w * (k + 0.7) / teeth:.1f} {gy - hgt - 9} L{x + w * (k + 1) / teeth:.1f} {gy - hgt}"
                for k in range(teeth))
            out.append(f'<path d="{roof} V{gy} H{x} Z" fill="#EEF2F0" stroke="{INK}" stroke-width="0.8"/>'
                       f'<rect x="{x}" y="{gy - hgt * 0.55:.1f}" width="{w:.1f}" height="6" fill="{H2}"/>'
                       + "".join(f'<rect x="{x + 6 + k * 12:.1f}" y="{gy - hgt + 6}" width="6" height="7" fill="#9FB6BD"/>'
                                 for k in range(int((w - 8) / 12))))
        elif kind == "cmp":
            out.append(f'<rect x="{x}" y="{gy - 20}" width="{w:.1f}" height="20" fill="#DCE7E6" stroke="{INK}" '
                       f'stroke-width="0.8"/><path d="M{x + 6} {gy - 20} v-10 h{w - 12:.1f} v10" fill="none" '
                       f'stroke="{H2}" stroke-width="2.2"/>')
        elif kind == "tank":
            n = max(1, min(4, int(round(g("E_tank_on") / 40000)) + 1))
            for k in range(n):
                ty = gy - 14 - k * 13
                out.append(f'<rect x="{x + 3}" y="{ty:.1f}" width="{w - 6:.1f}" height="12" rx="6" fill="{STORE}" '
                           f'stroke="{INK}" stroke-width="0.7"/>')
            out.append(f'<path d="M{x + 8} {gy} v-3 M{x + w - 8:.1f} {gy} v-3" stroke="{INK}" stroke-width="2"/>')
        elif kind == "bat":
            for k in range(2):
                out.append(f'<rect x="{x + k * (w / 2):.1f}" y="{gy - 16}" width="{w / 2 - 2:.1f}" height="16" fill="{BATT}" '
                           f'stroke="{INK}" stroke-width="0.7"/><line x1="{x + k * (w / 2) + w / 4:.1f}" '
                           f'x2="{x + k * (w / 2) + w / 4:.1f}" y1="{gy - 15}" y2="{gy - 1}" stroke="#7A93AE" '
                           f'stroke-width="0.6"/>')
        elif kind == "fc":
            out.append(f'<rect x="{x}" y="{gy - 18}" width="{w:.1f}" height="18" fill="#E7B271" stroke="{INK}" '
                       f'stroke-width="0.8"/><rect x="{x + 4}" y="{gy - 24}" width="5" height="6" fill="{STEEL}"/>')
        out.append('</g>')
        labs.append((x + w / 2, name, val, {'sub': 90, 'ez': 58, 'cmp': 42, 'tank': 64, 'bat': 24, 'fc': 34}[kind]))
        x += w + 22 * sc
    # onshore labels: greedy rows, nearest row first, so neighbours never collide
    rows = []
    for lx, name, val, top in sorted(labs, key=lambda t: t[0]):
        wlab = (max(len(name) * 7.3, len(val) * 6.3) + 14) * FS
        r = 0
        while True:
            if r >= len(rows):
                rows.append([])
            if all(abs(lx - ox) > (wlab + ow) / 2 for ox, ow in rows[r]):
                rows[r].append((lx, wlab))
                break
            r += 1
        ly = GROUND_Y + 78 + 44 * r
        out.append(f'<line x1="{lx:.1f}" x2="{lx:.1f}" y1="{GROUND_Y + 2}" y2="{ly - 20:.1f}" '
                   f'stroke="{INK}" stroke-width="0.7"/><circle cx="{lx:.1f}" cy="{GROUND_Y + 2}" r="2" fill="{INK}"/>')
        out.append(label(lx, ly, name, 12.5, 600, INK, "middle", halo="#E4DABF"))
        out.append(label(lx, ly + 17, val, 11, 500, INK2, "middle", halo="#E4DABF"))
    # offshore annotations
    cab_km, pipe_km = g("grid_km"), g("pipe_km")
    if cab:
        mx = (t_x + land_x) / 2
        circ = int(g("circuits"))
        to_hub = ""
        if hub_x:
            out.append(label(hub_x, SEA_Y - 74, d.get("hub_name"), 12, 600, INK, "middle", halo="#F5F3EC"))
            out.append(label((hub_x + land_x) / 2, bed_y((hub_x + land_x) / 2) - 12,
                             "Existing link to shore (hub owner, access fee)", 11, 500, POWER, "middle", halo="#CFE2E7"))
            mx = X_ISL + 250
        out.append(label(mx, bed_y(mx) - 14 if not hub_x else SEA_Y - 10,
                         f"{'Own cable' if hub_x else 'Export cable'} · {d.get('volt') or d.get('link_mode', 'HVAC')} · "
                                             f"{circ} circuit{'s' if circ != 1 else ''} · {g('C_cab'):,.0f} MW · "
                                             f"{cab_km:,.0f} km", 12, 600, POWER, "middle", halo="#CFE2E7"))
        if floating:
            out.append(label(X_ISL + 120, mid[1] + 34, "Dynamic cable, lazy wave", 11, 500, INK, "middle",
                             halo="#CFE2E7"))
    if pipe:
        mx = (t_x + land_x) / 2 + 60
        out.append(label(mx, bed_y(mx) + 24, f"Hydrogen pipeline{' to ' + d['tiein_name'] if d.get('tiein_name') else ''} · {str(d.get('pipe')).replace('_', ' ')} · "
                                             f"{pipe_km:,.0f} km", 12, 600, H2, "middle", halo="#C9B98F"))
    out.append(label(X_LAND - 20, SEA_Y + 118, "Landfall: drilled under the beach", 11, 500, INK,
                     "end", halo="#D2C49E")
               if (cab or pipe) else "")
    out.append(label(X_ISL, deck_y - 48, "Floating island" if floating else "Bottom-fixed island", 13, 600, INK, "middle",
                     serif=True, halo="#F5F3EC"))
    out.append(label(X_ISL, deck_y - 33, f"{depth:,.0f} m water depth", 11, 500, INK2, "middle", halo="#F5F3EC"))
    if floating:
        out.append(label(X_ISL - 92, SEA_Y + 74, "Moorings", 11, 500, INK, "middle", halo="#BFD6DD"))
    out.append(label(70, SEA_Y - 100, "Wind farm", 11.5, 600, INK2, "middle", halo="#F5F3EC"))
    # depth axis
    ax_x = 22
    step = _nice_step(zmax, 4)
    z = 0.0
    while z <= zmax + 1e-6:
        y = SEA_Y + z * mpx
        out.append(f'<line x1="{ax_x}" x2="{ax_x + 6}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK}" stroke-width="0.8"/>'
                   + label(ax_x + 9, y + 4, f"{-z:,.0f} m" if z else "0 m", 10, 500, INK, halo="#CFE2E7"))
        z += step
    out.append(f'<line x1="{ax_x}" x2="{ax_x}" y1="{SEA_Y}" y2="{SEA_Y + zmax * mpx:.1f}" stroke="{INK}" stroke-width="0.8"/>')
    # distance axis along the route
    ay = H - 30
    ax_end = hub_x if hub_x else land_x
    out.append(f'<line x1="{X_ISL}" x2="{ax_end}" y1="{ay}" y2="{ay}" stroke="{INK}" stroke-width="0.9"/>')
    if cab_km > 0:
        st = _nice_step(cab_km, 5)
        kk = 0.0
        while kk <= cab_km + 1e-6:
            x = X_ISL + (ax_end - X_ISL) * kk / cab_km
            out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{ay}" y2="{ay + 5}" stroke="{INK}" stroke-width="0.9"/>'
                       + label(x, ay + 18, f"{kk:,.0f}", 10.5, 500, INK, "middle", halo=None))
            kk += st
    out.append(label((X_ISL + ax_end) / 2, ay - 9, "Distance along the island's own cable, km", 11, 500, INK, "middle",
                     halo="#CDBF98"))
    out.append(label(X_LAND + 64, GROUND_Y + 48, "Onshore, not to scale", 10.5, 500, INK2, "start", halo=None))
    # title
    out.append(label(24, 32, "Route section", 18, 600, INK, serif=True, halo=None))
    out.append(label(24, 54, "Island to grid, side view · vertical scale exaggerated · seabed profile schematic",
                     11.5, 400, INK2, halo=None))
    tag = []
    if g("grid_gwh") > 0:
        tag.append(f"Grid {g('grid_gwh'):,.0f} GWh/yr")
    if g("h2_t") > 0:
        tag.append(f"Hydrogen {g('h2_t'):,.0f} t/yr")
    if tag:
        out.append(label(24, 80, " · ".join(tag), 12.5, 600, INK, halo=None))
    css = (".drift{animation:drift 8s linear infinite;}@keyframes drift{to{transform:translateX(32px);}}")
    return (f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-label="Side view of the export route from the island to the onshore plant">'
            f'<style>{css}</style>' + "".join(out) + "</svg>")


def section_page(d: dict, animate=True) -> str:
    return page(section_svg(d, animate), ANIM_CSS)
