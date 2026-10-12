"""Shared drawing vocabulary for the planner's illustrations (atlas, island, route section).

Cartographic conventions: water and place names in an italic serif, technical labels in Archivo,
labels sit on a paper-coloured halo instead of boxes, and colour always means a carrier:
electricity = orange, hydrogen = teal, storage = violet.
"""
from __future__ import annotations

import math
from html import escape

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@87,400;87,500;87,600;87,700&'
         'family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400;1,8..60,600&display=swap" '
         'rel="stylesheet">')

INK = "#22313A"
INK2 = "#4D5D66"
MUTED = "#8C9AA2"
PAPER = "#F6F2E8"
LAND = "#ECE4CF"
LAND_DARK = "#DCD2B6"
COAST = "#34444C"
SEA = ["#DDEBED", "#C9DFE4", "#B2D1D9", "#9AC2CE", "#86B3C2"]   # shore -> offshore
POWER = "#DD6B1E"       # electricity (cable, substation)
POWER_LT = "#F4B47E"
H2 = "#13979A"          # hydrogen (pipeline, electrolysers, tanks)
H2_LT = "#8FD3D2"
STORE = "#7462B0"       # storage
BATT = "#2E4866"        # battery containers
STEEL = "#6F7E86"
STEEL_LT = "#B9C4C9"
WHITE = "#FFFFFF"


def esc(s) -> str:
    return escape(str(s if s is not None else ""))


def fmt(x, unit="", nd=0):
    if x is None:
        return "–"
    s = f"{x:,.{nd}f}"
    return f"{s} {unit}".strip()


def label(x, y, text, size=12, weight=500, color=INK, anchor="start", italic=False, serif=False,
          halo=PAPER, halo_w=3.2, extra=""):
    """Text with a halo (cartographic) instead of a box."""
    fam = "'Source Serif 4', Georgia, serif" if serif else "'Archivo', 'Arial Narrow', Arial, sans-serif"
    style = (f"font-family:{fam};font-size:{size}px;font-weight:{weight};"
             f"{'font-style:italic;' if italic else ''}{'font-stretch:87%;' if not serif else ''}")
    h = (f' stroke="{halo}" stroke-width="{halo_w}" stroke-linejoin="round" paint-order="stroke"'
         if halo else "")
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="{color}" style="{style}"{h} {extra}>'
            f'{esc(text)}</text>')


def path_d(pts, close=False) -> str:
    if not pts:
        return ""
    s = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    return s + (" Z" if close else "")


def smooth_d(pts) -> str:
    """Catmull-Rom spline through points as cubic Beziers."""
    if len(pts) < 3:
        return path_d(pts)
    d = [f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}")
    return " ".join(d)


def poly_length(pts) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def point_at(pts, frac):
    """Point and direction (radians) at a fraction of the polyline length."""
    total = poly_length(pts)
    target, run = frac * total, 0.0
    for i in range(len(pts) - 1):
        seg = math.dist(pts[i], pts[i + 1])
        if run + seg >= target and seg > 0:
            t = (target - run) / seg
            x = pts[i][0] + t * (pts[i + 1][0] - pts[i][0])
            y = pts[i][1] + t * (pts[i + 1][1] - pts[i][1])
            return x, y, math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0])
        run += seg
    a = math.atan2(pts[-1][1] - pts[-2][1], pts[-1][0] - pts[-2][0]) if len(pts) > 1 else 0
    return pts[-1][0], pts[-1][1], a


def chevrons(pts, color, n=None, spacing=70, size=4.5):
    """Small direction chevrons along a route."""
    L = poly_length(pts)
    n = n or max(1, int(L // spacing))
    out = []
    for k in range(n):
        x, y, a = point_at(pts, (k + 0.5) / n)
        deg = math.degrees(a)
        out.append(f'<path d="M{-size} {-size} L0 0 L{-size} {size}" transform="translate({x:.1f},{y:.1f}) '
                   f'rotate({deg:.1f})" fill="none" stroke="{color}" stroke-width="1.6" '
                   f'stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(out)


def page(svg: str, css: str = "") -> str:
    """Wrap one SVG as a small HTML document for an iframe."""
    base = ("html,body{margin:0;padding:0;background:transparent;}"
            "svg{display:block;width:100%;height:auto;}"
            "@media (prefers-reduced-motion: reduce){*{animation:none!important;}}")
    return f'<meta charset="utf-8">{FONTS}<style>{base}{css}</style>{svg}'


def turbine_side(x, base_y, h, rotor, cls="rot", color=WHITE, stroke=STEEL, spin_s=6.0):
    """Side view of a three-bladed turbine: tower base at (x, base_y), hub height h px."""
    hub_y = base_y - h
    blades = "".join(
        f'<path d="M0 0 C {rotor * 0.08:.1f} {-rotor * 0.35:.1f}, {rotor * 0.05:.1f} {-rotor * 0.8:.1f}, 0 {-rotor:.1f} '
        f'C {-rotor * 0.04:.1f} {-rotor * 0.7:.1f}, {-rotor * 0.06:.1f} {-rotor * 0.3:.1f}, 0 0 Z" '
        f'transform="rotate({a})" fill="{color}" stroke="{stroke}" stroke-width="0.6"/>' for a in (0, 120, 240))
    return (f'<path d="M{x - 2.2:.1f} {base_y:.1f} L{x - 1.1:.1f} {hub_y:.1f} L{x + 1.1:.1f} {hub_y:.1f} '
            f'L{x + 2.2:.1f} {base_y:.1f} Z" fill="{color}" stroke="{stroke}" stroke-width="0.6"/>'
            f'<rect x="{x - 1:.1f}" y="{hub_y - 2.6:.1f}" width="{rotor * 0.16 + 4:.1f}" height="5.2" rx="2" '
            f'fill="{color}" stroke="{stroke}" stroke-width="0.6"/>'
            f'<g transform="translate({x:.1f},{hub_y:.1f})"><g class="{cls}" style="animation-duration:{spin_s:.1f}s">'
            f'{blades}<circle r="2" fill="{color}" stroke="{stroke}" stroke-width="0.6"/></g></g>')


ANIM_CSS = (".rot{animation:spin linear infinite;transform-origin:0 0;}"
            "@keyframes spin{to{transform:rotate(360deg);}}"
            ".flow{animation:flow 1.8s linear infinite;}"
            "@keyframes flow{to{stroke-dashoffset:-28;}}"
            ".bob{animation:bob 6s ease-in-out infinite;}"
            "@keyframes bob{50%{transform:translateY(1.6px);}}")
