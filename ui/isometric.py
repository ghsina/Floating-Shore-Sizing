"""The island in isometric view: platform, hull, moorings and the sized equipment on the deck.

Footprints come from the model's deck-area inputs (m² per MW, per MWh or per kg) multiplied by the
sized capacities, so the drawing is to scale with the design. Heights are typical for the equipment
type and are only for the picture. The substation and the utility block (control room, helideck)
have fixed illustrative footprints because the model does not size them by area.
"""
from __future__ import annotations

import math

from .svgkit import label as _label
from .svgkit import (ANIM_CSS, BATT, H2, INK, INK2, MUTED, PAPER, POWER, SEA, STEEL, STEEL_LT, STORE, WHITE,
                     esc, page, turbine_side)

W, H = 820, 600
C30, S30 = math.cos(math.radians(30)), 0.5


FS = 1.38          # font scale: the drawing is shown narrower than its viewBox


def label(*a, **k):
    a = list(a)
    if len(a) > 3:
        a[3] = a[3] * FS
    return _label(*a, **k)


def _shade(hex_, f):
    hex_ = hex_.lstrip("#")
    r, g, b = (int(hex_[i:i + 2], 16) for i in (0, 2, 4))
    if f >= 1:
        r, g, b = (int(c + (255 - c) * (f - 1)) for c in (r, g, b))
    else:
        r, g, b = (int(c * f) for c in (r, g, b))
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


class Iso:
    def __init__(self, ox, oy, s):
        self.ox, self.oy, self.s = ox, oy, s

    def p(self, u, v, z=0.0):
        return (self.ox + (u - v) * C30 * self.s, self.oy + (u + v) * S30 * self.s - z * self.s)

    def poly(self, pts, fill, stroke=INK, sw=0.7, extra=""):
        d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + " Z"
        return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round" {extra}/>'

    def box(self, u, v, w, d, z0, h, color, stroke=INK, sw=0.7):
        """Visible faces of a box: top, the +u face and the +v face."""
        P = self.p
        top = [P(u, v, z0 + h), P(u + w, v, z0 + h), P(u + w, v + d, z0 + h), P(u, v + d, z0 + h)]
        fu = [P(u + w, v, z0), P(u + w, v + d, z0), P(u + w, v + d, z0 + h), P(u + w, v, z0 + h)]
        fv = [P(u, v + d, z0), P(u + w, v + d, z0), P(u + w, v + d, z0 + h), P(u, v + d, z0 + h)]
        return (self.poly(fu, _shade(color, 0.78), stroke, sw) + self.poly(fv, _shade(color, 0.62), stroke, sw)
                + self.poly(top, _shade(color, 1.18), stroke, sw))

    def cyl(self, u, v, r, z0, h, color, stroke=INK, sw=0.7, gid="cg"):
        X, Yb = self.p(u, v, z0)
        _, Yt = self.p(u, v, z0 + h)
        rx, ry = 1.2247 * r * self.s, 0.7071 * r * self.s
        side = (f'<path d="M{X - rx:.1f} {Yt:.1f} L{X - rx:.1f} {Yb:.1f} A{rx:.1f} {ry:.1f} 0 0 0 {X + rx:.1f} {Yb:.1f} '
                f'L{X + rx:.1f} {Yt:.1f} Z" fill="url(#{gid})" stroke="{stroke}" stroke-width="{sw}"/>')
        top = (f'<ellipse cx="{X:.1f}" cy="{Yt:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{_shade(color, 1.25)}" '
               f'stroke="{stroke}" stroke-width="{sw}"/>')
        return side + top


ASPECT = {"substation": 1.3, "electrolyser": 2.2, "desal": 1.6, "compressor": 1.4, "fuelcell": 1.5,
          "battery": 2.6, "tank": 1.0, "utility": 1.2}
HEIGHT = {"substation": 14, "electrolyser": 6, "desal": 4, "compressor": 5, "fuelcell": 4.5, "battery": 3,
          "tank": 14, "utility": 9}
COLOR = {"substation": POWER, "electrolyser": H2, "desal": "#5FA8C9", "compressor": "#3E8F8C", "fuelcell": "#C9822F",
         "battery": BATT, "tank": STORE, "utility": "#D8DDE0"}


def _items(d):
    g = lambda k: float(d.get(k) or 0.0)
    it = []
    hvdc = d.get("link_mode") == "HVDC"
    if g("C_cab") > 1e-3:
        it.append(dict(kind="substation", name="HVDC converter" if hvdc else "Offshore substation",
                       value=f"{d.get('volt') or ('HVDC' if hvdc else 'HVAC')} · {int(g('circuits'))} × circuit · {g('C_cab'):,.0f} MW",
                       area=max(g("C_cab") * 8, 400),
                       sized=False))
    if g("C_ez_off") > 1e-3:
        a = g("C_ez_off") * g("area_elec_m2_mw")
        it.append(dict(kind="electrolyser", name="Electrolysers", value=f"{g('C_ez_off'):,.1f} MW", area=a, sized=True))
        it.append(dict(kind="desal", name="Desalination", value="seawater to electrolysis", area=max(0.08 * a, 60),
                       sized=False))
    if g("C_cmp_off") > 1e-3:
        it.append(dict(kind="compressor", name="Compressors", value=f"{g('C_cmp_off'):,.2f} MW",
                       area=max(g("C_cmp_off") * g("area_comp_m2_mw"), 60), sized=True))
    if g("C_fc_off") > 1e-3:
        it.append(dict(kind="fuelcell", name="Fuel cells", value=f"{g('C_fc_off'):,.1f} MW",
                       area=g("C_fc_off") * g("area_fc_m2_mw"), sized=True))
    if g("E_bat_off") > 1e-3:
        it.append(dict(kind="battery", name="Battery", value=f"{g('E_bat_off'):,.0f} MWh · {g('P_bat_off'):,.0f} MW",
                       area=g("E_bat_off") * g("area_batt_m2_mwh"), sized=True))
    if g("E_tank_off") > 1.0:
        it.append(dict(kind="tank", name="Hydrogen storage", value=f"{g('E_tank_off') / 1000:,.1f} t",
                       area=g("E_tank_off") * g("area_tank_m2_kg"), sized=True))
    it.append(dict(kind="utility", name="Control room and helideck", value="", area=500, sized=False))
    return it


def _pack(items, L, gap):
    """Shelf packing along u, rows stacked along v. Returns True if everything fits in L x L."""
    u = v = gap
    row_h = 0.0
    for it in sorted(items, key=lambda x: -x["area"]):
        a = ASPECT[it["kind"]]
        w = math.sqrt(it["area"] * a)
        dpt = it["area"] / w
        w, dpt = min(w, L - 2 * gap), None if False else dpt
        dpt = it["area"] / w
        if u + w > L - gap + 1e-6:
            u, v = gap, v + row_h + gap
            row_h = 0.0
        it["u"], it["v"], it["w"], it["d"] = u, v, w, dpt
        u += w + gap
        row_h = max(row_h, dpt)
    return v + row_h <= L - gap + 1e-6


def island_iso_svg(d: dict, animate: bool = True) -> str:
    items = _items(d)
    used = sum(i["area"] for i in items)
    L = max(math.sqrt(used / 0.6), 45.0)
    for _ in range(60):
        gap = max(L * 0.035, 2.5)
        if _pack(items, L, gap):
            break
        L *= 1.06
    floating = bool(d.get("floating", True))
    elev0 = 22.0 if floating else 20.0
    ztop = elev0 + 4 + max(HEIGHT[i["kind"]] for i in items) + 22
    zbot = -18.0
    zone_top, zone_bot = 78, H - 104
    s = min(400 / (2 * L * C30), (zone_bot - zone_top) / (L + ztop - zbot))
    oy = zone_top + ztop * s + ((zone_bot - zone_top) - (L + ztop - zbot) * s) / 2
    iso = Iso(W * 0.5, oy, s)
    P = iso.p
    elev = elev0                               # deck elevation above the sea
    slab = 4.0
    out = []
    out.append('<defs>'
               '<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F7F4EC"/>'
               '<stop offset="1" stop-color="#E4ECEE"/></linearGradient>'
               f'<linearGradient id="sea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{SEA[1]}"/>'
               f'<stop offset="1" stop-color="{SEA[4]}"/></linearGradient>'
               f'<linearGradient id="cg" x1="0" x2="1"><stop offset="0" stop-color="{_shade(STORE, 1.35)}"/>'
               f'<stop offset="0.55" stop-color="{STORE}"/><stop offset="1" stop-color="{_shade(STORE, 0.6)}"/></linearGradient>'
               f'<linearGradient id="colg" x1="0" x2="1"><stop offset="0" stop-color="#C7D0D4"/>'
               f'<stop offset="0.5" stop-color="{STEEL}"/><stop offset="1" stop-color="#46545B"/></linearGradient>'
               f'<linearGradient id="tkw" x1="0" x2="1"><stop offset="0" stop-color="#FFFFFF"/>'
               f'<stop offset="1" stop-color="#AEBBC1"/></linearGradient>'
               '</defs>')
    out.append(f'<rect width="{W}" height="{H}" fill="url(#sea)"/>')
    # sea plane (large iso rhombus) and background turbines on the horizon line
    ext = L * 6
    sea_poly = [(0, 0), (W, 0), (W, H), (0, H)]
    for k in range(60):
        uu = -ext * 0.5 + (k * 37 % 100) / 100 * ext
        vv = -ext * 0.5 + (k * 61 % 100) / 100 * ext
        if -L * 0.4 < uu < L * 1.6 and -L * 0.4 < vv < L * 1.6:
            continue
        a, b = P(uu, vv, 0), P(uu + L * 0.18, vv, 0)
        if 0 < a[0] < W and 60 < a[1] < H:
            out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} L{b[0]:.1f} {b[1]:.1f}" stroke="{WHITE}" stroke-width="1" '
                       f'opacity="0.45" stroke-linecap="round"/>')
    # hull below the water line, then a translucent water veil
    col_r = L * 0.075
    cols = [(col_r * 1.3, col_r * 1.3), (L - col_r * 1.3, col_r * 1.3), (col_r * 1.3, L - col_r * 1.3),
            (L - col_r * 1.3, L - col_r * 1.3)]
    under = []
    if floating:
        for (cu, cv) in cols:
            for ang in (-0.6, 0.6):
                du = (cu - L / 2) / (L / 2)
                dv = (cv - L / 2) / (L / 2)
                tu, tv = cu + du * L * (1.4 + 0.2 * ang), cv + dv * L * (1.4 - 0.2 * ang)
                a, b = P(cu, cv, -14), P(tu, tv, -60)
                under.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} Q{(a[0] + b[0]) / 2:.1f} {max(a[1], b[1]) + 30:.1f} '
                             f'{b[0]:.1f} {b[1]:.1f}" fill="none" stroke="#3E5560" stroke-width="1" opacity="0.55"/>')
        pw = col_r * 1.2
        under.append(iso.box(cols[0][0], cols[0][1] - pw / 2, L - 2.6 * col_r, pw, -16, 5, "#55666E", sw=0.5))
        under.append(iso.box(cols[0][0] - pw / 2, cols[0][1], pw, L - 2.6 * col_r, -16, 5, "#55666E", sw=0.5))
        under.append(iso.box(cols[1][0] - pw / 2, cols[1][1], pw, L - 2.6 * col_r, -16, 5, "#55666E", sw=0.5))
        under.append(iso.box(cols[2][0], cols[2][1] - pw / 2, L - 2.6 * col_r, pw, -16, 5, "#55666E", sw=0.5))
        for (cu, cv) in cols:
            under.append(iso.cyl(cu, cv, col_r, -16, 16, STEEL, sw=0.5, gid="colg"))
    else:
        for (cu, cv) in cols:
            a, b = P(cu, cv, 0), P(cu + (cu - L / 2) * 0.25, cv + (cv - L / 2) * 0.25, -70)
            under.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{STEEL}" '
                         f'stroke-width="{max(2.5, col_r * s * 0.5):.1f}"/>')
    out += under
    out.append(f'<rect width="{W}" height="{H}" fill="{SEA[3]}" opacity="0.55"/>')
    # export cable and pipeline risers from the deck edge into the sea
    if float(d.get("C_cab") or 0) > 1e-3:
        a = P(L, L * 0.55, elev)
        b = P(L * 1.25, L * 0.75, 0)
        c = P(L * 2.2, L * 1.4, -30)
        out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} C{a[0] + 30:.1f} {a[1] + 10:.1f} {b[0]:.1f} {b[1] - 10:.1f} '
                   f'{b[0]:.1f} {b[1]:.1f} S{c[0] - 40:.1f} {c[1] - 30:.1f} {c[0]:.1f} {c[1]:.1f}" fill="none" '
                   f'stroke="{POWER}" stroke-width="3" stroke-linecap="round"/>')
        if animate:
            out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} C{a[0] + 30:.1f} {a[1] + 10:.1f} {b[0]:.1f} {b[1] - 10:.1f} '
                       f'{b[0]:.1f} {b[1]:.1f} S{c[0] - 40:.1f} {c[1] - 30:.1f} {c[0]:.1f} {c[1]:.1f}" fill="none" '
                       f'stroke="{WHITE}" stroke-width="1.1" stroke-dasharray="2 12" class="flow"/>')
    if d.get("pipe") not in (None, "", "none"):
        a = P(L * 0.55, L, elev)
        b = P(L * 0.8, L * 1.3, 0)
        c = P(L * 1.4, L * 2.3, -30)
        out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} C{a[0]:.1f} {a[1] + 20:.1f} {b[0] - 10:.1f} {b[1]:.1f} {b[0]:.1f} '
                   f'{b[1]:.1f} S{c[0] - 30:.1f} {c[1] - 30:.1f} {c[0]:.1f} {c[1]:.1f}" fill="none" stroke="{H2}" '
                   f'stroke-width="4" stroke-linecap="round"/>')
    # columns or jacket above water
    if floating:
        for (cu, cv) in cols:
            out.append(iso.cyl(cu, cv, col_r, 0, elev, STEEL, sw=0.6, gid="colg"))
            x, y = P(cu, cv, 0)
            out.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{1.2247 * col_r * s * 1.35:.1f}" '
                       f'ry="{0.7071 * col_r * s * 1.35:.1f}" fill="none" stroke="{WHITE}" stroke-width="1" opacity="0.8"/>')
    else:
        for (cu, cv) in cols:
            a, b = P(cu, cv, 0), P(cu, cv, elev)
            out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{STEEL}" '
                       f'stroke-width="{max(2.5, col_r * s * 0.6):.1f}"/>')
        for (c1, c2) in ((cols[0], cols[1]), (cols[0], cols[2])):
            a, b = P(c1[0], c1[1], 2), P(c2[0], c2[1], elev - 2)
            a2, b2 = P(c1[0], c1[1], elev - 2), P(c2[0], c2[1], 2)
            out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} L{b[0]:.1f} {b[1]:.1f} M{a2[0]:.1f} {a2[1]:.1f} '
                       f'L{b2[0]:.1f} {b2[1]:.1f}" stroke="{STEEL}" stroke-width="1.4"/>')
    # deck slab
    out.append(iso.box(0, 0, L, L, elev, slab, "#C4CCD0", sw=0.8))
    z = elev + slab
    # deck markings: walkway grid
    for k in range(1, 6):
        a, b = P(L * k / 6, 0, z), P(L * k / 6, L, z)
        out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#AEB8BD" '
                   f'stroke-width="0.5"/>')
        a, b = P(0, L * k / 6, z), P(L, L * k / 6, z)
        out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#AEB8BD" '
                   f'stroke-width="0.5"/>')
    # railing on the front edges
    for k in range(25):
        for (pu, pv) in ((L * k / 24, L), (L, L * k / 24)):
            a, b = P(pu, pv, z), P(pu, pv, z + 1.4)
            out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#7D8A90" '
                       f'stroke-width="0.6"/>')
    # equipment back to front
    anchors = []
    for it in sorted(items, key=lambda i: i["u"] + i["w"] / 2 + i["v"] + i["d"] / 2):
        k, u, v, w, dd = it["kind"], it["u"], it["v"], it["w"], it["d"]
        h = HEIGHT[k]
        col = COLOR[k]
        if k == "tank":
            n = max(1, min(30, int(round(it["area"] / 120))))
            nc = max(1, int(round(math.sqrt(n * w / dd))))
            nr = max(1, int(math.ceil(n / nc)))
            r = 0.42 * min(w / nc, dd / nr)
            cells = [(i, j) for j in range(nr) for i in range(nc)][:n]
            out.append(iso.box(u, v, w, dd, z, 0.6, "#9AA6AC", sw=0.4))
            for (i, j) in sorted(cells, key=lambda c: c[0] + c[1]):
                out.append(iso.cyl(u + (i + 0.5) * w / nc, v + (j + 0.5) * dd / nr, r, z + 0.6, h, STORE, sw=0.5))
        elif k == "utility":
            out.append(iso.box(u, v, w, dd, z, h, col))
            cx, cy = P(u + w / 2, v + dd / 2, z + h)
            rr = 0.36 * min(w, dd)
            out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{1.2247 * rr * s:.1f}" ry="{0.7071 * rr * s:.1f}" '
                       f'fill="#3D4A50" stroke="#F2C230" stroke-width="1.2"/>')
            out.append(f'<text x="{cx:.1f}" y="{cy + 3:.1f}" text-anchor="middle" fill="{WHITE}" '
                       f'style="font:700 {max(7, rr * s * 0.7):.0f}px Archivo, Arial">H</text>')
            for wk in range(1, 4):
                a, b = P(u + w, v + dd * wk / 4 - dd * 0.08, z + h * 0.55), P(u + w, v + dd * wk / 4 + dd * 0.08, z + h * 0.55)
                out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#6E8794" '
                           f'stroke-width="2"/>')
            # crane
            a = P(u + w * 0.15, v + dd * 0.15, z + h)
            b = P(u - L * 0.12, v + dd * 0.2, z + h + 18)
            out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} L{b[0]:.1f} {b[1]:.1f}" stroke="#E0A419" stroke-width="2.2"/>'
                       f'<path d="M{b[0]:.1f} {b[1]:.1f} v{12 * s:.1f}" stroke="{INK2}" stroke-width="0.7"/>')
        else:
            out.append(iso.box(u, v, w, dd, z, h, col))
            if k in ("electrolyser", "battery"):
                n = max(1, int(w / 12.2))
                for c in range(1, n):
                    a, b = P(u + w * c / n, v + dd, z), P(u + w * c / n, v + dd, z + h)
                    t1, t2 = P(u + w * c / n, v, z + h), P(u + w * c / n, v + dd, z + h)
                    out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} L{b[0]:.1f} {b[1]:.1f} L{t2[0]:.1f} {t2[1]:.1f} '
                               f'L{t1[0]:.1f} {t1[1]:.1f}" fill="none" stroke="{_shade(col, 0.5)}" stroke-width="0.6"/>')
                if k == "electrolyser":
                    for c in range(n):
                        x, y = P(u + w * (c + 0.5) / n, v + dd * 0.5, z + h)
                        out.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{2.2 * s + 1:.1f}" ry="{1.3 * s + 0.6:.1f}" '
                                   f'fill="{_shade(col, 0.55)}"/>')
            if k == "substation":
                for c in range(3):
                    out.append(iso.cyl(u + w * (0.25 + 0.25 * c), v + dd * 0.4, min(w, dd) * 0.05, z + h, 4, "#E9ECEE",
                                       sw=0.4, gid="tkw"))
                for c in range(1, 8):
                    a, b = P(u + w, v + dd * c / 8, z + 1), P(u + w, v + dd * c / 8, z + h - 2)
                    out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                               f'stroke="{_shade(col, 0.5)}" stroke-width="0.8"/>')
            if k == "compressor":
                a, b = P(u + w * 0.2, v + dd, z + h * 0.6), P(u + w * 0.2, v + dd + 6, z + 0.5)
                out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f} L{b[0]:.1f} {b[1]:.1f}" stroke="{H2}" stroke-width="2"/>')
            if k == "desal":
                for c in range(2):
                    out.append(iso.cyl(u + w * (0.3 + 0.4 * c), v + dd * 0.5, min(w, dd) * 0.18, z + h, 3, "#8CC3DA",
                                       sw=0.4, gid="tkw"))
        if k != "utility" or True:
            ax, ay = P(u + w / 2, v + dd / 2, z + h + (4 if k in ("tank", "substation") else 0))
            anchors.append((ax, ay, it))
    # leader-line labels in two columns
    cx_mid = W * 0.47
    left = sorted([a for a in anchors if a[0] < cx_mid], key=lambda a: a[1])
    right = sorted([a for a in anchors if a[0] >= cx_mid], key=lambda a: a[1])

    def column(group, x_text, anchor):
        ys, y_prev = [], 40
        for ax, ay, it in group:
            y = max(min(ay - 10, H - 160), y_prev + 48, 92)
            ys.append(y)
            y_prev = y
        res = []
        for (ax, ay, it), y in zip(group, ys):
            col = COLOR[it["kind"]]
            xe = x_text + (8 if anchor == "start" else -8)
            res.append(f'<path d="M{ax:.1f} {ay:.1f} L{xe:.1f} {y + 4:.1f}" fill="none" '
                       f'stroke="{INK}" stroke-width="0.8"/><circle cx="{ax:.1f}" cy="{ay:.1f}" r="2.4" fill="{col}" '
                       f'stroke="{WHITE}" stroke-width="1"/>')
            tx = x_text + (14 if anchor == "start" else -14)
            res.append(label(tx, y + 1, it["name"], 13, 600, INK, anchor, halo="#F2F1EA"))
            if it["value"]:
                res.append(label(tx, y + 20, it["value"], 11.5, 500, INK2, anchor, halo="#F2F1EA"))
        return "".join(res)

    out.append(column(left, 22, "start"))
    out.append(column(right, W - 22, "end"))
    # title and deck-use bar
    cfg = "Floating island" if floating else "Bottom-fixed island"
    out.append(label(24, 30, cfg, 18, 600, INK, serif=True, halo=None))
    out.append(label(24, 54, "Deck drawn to scale from the sized equipment", 11.5, 400, INK2, halo=None))
    avail = float(d.get("deck_area_max_m2") or 0)
    sized = [i for i in items if i["sized"]]
    tot_sized = sum(i["area"] for i in sized)
    bx, by, bw = 18, H - 40, W - 36
    out.append(f'<rect x="{bx}" y="{by - 40}" width="{bw}" height="66" rx="4" fill="{PAPER}" opacity="0.92" '
               f'stroke="#CFC8B5"/>')
    if avail > 0 and sized:
        out.append(label(bx + 12, by - 17, f"Deck used: {tot_sized:,.0f} m² of {avail:,.0f} m² "
                                           f"({100 * tot_sized / avail:,.1f} %)", 12, 600, INK, halo=None))
        x = bx + 12
        out.append(f'<rect x="{x}" y="{by - 4}" width="{bw - 24}" height="12" fill="#E7E2D3" stroke="#CFC8B5"/>')
        for i in sized:
            wpx = (bw - 24) * min(i["area"] / avail, 1.0)
            if wpx > 0.3:
                out.append(f'<rect x="{x:.1f}" y="{by - 4}" width="{wpx:.1f}" height="12" fill="{COLOR[i["kind"]]}"/>')
                x += wpx
    if not sized:
        out.append(label(bx + 12, by - 10, "No sized equipment on the island: it carries the export link only.", 12,
                         500, INK2, halo=None))
    built = {i["kind"] for i in items}
    missing = [n for k, n in (("electrolyser", "electrolysers"), ("compressor", "compressors"),
                              ("fuelcell", "fuel cells"), ("battery", "battery"), ("tank", "hydrogen storage"))
               if k not in built]
    if missing:
        out.append(label(W - 30, by + 21, "Not on the island: " + ", ".join(missing), 10, 400, INK2, "end",
                         halo=None))
    return (f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-label="Isometric view of the energy island and its equipment">' + "".join(out) + "</svg>")


def island_iso_page(d: dict, animate=True) -> str:
    return page(island_iso_svg(d, animate), ANIM_CSS)
