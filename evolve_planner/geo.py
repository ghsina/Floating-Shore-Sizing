"""Coastline, distance from shore and sea routes from a 1 km global land mask.

The mask (assets/landmask_120.npz, 1.5 MB) is the GLOBE 30-arc-second land/water grid as packaged by
the `global-land-mask` project (MIT licence; GLOBE data are public domain), stored bit-packed. One
cell is 1/120 degree (about 0.9 km). Everything here is for drawing: routes are the shortest path
through sea cells, not engineered cable routes.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np

MASK = Path(__file__).resolve().parents[1] / "assets" / "landmask_120.npz"
MAX_CELLS = 220_000      # larger windows are coarsened so a drawing or route stays fast
RES = 120  # cells per degree
KM_PER_DEG = 111.32


@lru_cache(maxsize=1)
def _packed():
    if not MASK.exists():
        return None
    return np.load(MASK)["mask"]          # (21600, 5400) uint8 bit-packed, True = water, rows from 90N


def land_window(lat_s, lat_n, lon_w, lon_e):
    """Boolean land grid for a box, rows from north to south, and the cell-centre coordinates."""
    pk = _packed()
    i0 = max(int(math.floor((90 - lat_n) * RES)), 0)
    i1 = min(int(math.ceil((90 - lat_s) * RES)), 21600)
    j0 = max(int(math.floor((lon_w + 180) * RES)), 0)
    j1 = min(int(math.ceil((lon_e + 180) * RES)), 43200)
    lats = 90 - (np.arange(i0, i1) + 0.5) / RES
    lons = -180 + (np.arange(j0, j1) + 0.5) / RES
    if pk is None:
        return np.zeros((i1 - i0, j1 - j0), bool), lats, lons, False
    b0, b1 = j0 // 8, (j1 + 7) // 8
    bits = np.unpackbits(pk[i0:i1, b0:b1], axis=1)
    off = j0 - b0 * 8
    ocean = bits[:, off:off + (j1 - j0)].astype(bool)        # the stored grid marks water
    return ~ocean, lats, lons, True


def _res(lats):
    return 1.0 / abs(lats[0] - lats[1]) if len(lats) > 1 else RES


def _cell_km(lat, res=RES):
    return KM_PER_DEG / res, KM_PER_DEG * math.cos(math.radians(lat)) / res     # dy, dx


def coarsen(land, lats, lons, max_cells=MAX_CELLS):
    """Block-reduce a land grid so it has at most `max_cells` cells (a block is land if most of it is)."""
    s = int(math.ceil(math.sqrt(land.size / max_cells))) if land.size > max_cells else 1
    if s <= 1:
        return land, lats, lons
    ny, nx = (land.shape[0] // s) * s, (land.shape[1] // s) * s
    blk = land[:ny, :nx].reshape(ny // s, s, nx // s, s).mean(axis=(1, 3)) >= 0.5
    return blk, lats[:ny].reshape(-1, s).mean(axis=1), lons[:nx].reshape(-1, s).mean(axis=1)


def distance_from_land_km(land, lat_mid, res=RES):
    from scipy.ndimage import distance_transform_edt
    dy, dx = _cell_km(lat_mid, res)
    if not land.any():
        return np.full(land.shape, 99.0)
    return distance_transform_edt(~land, sampling=(dy, dx))


def smooth_field(land, sigma=0.8):
    from scipy.ndimage import gaussian_filter
    return gaussian_filter(land.astype(float), sigma)


def contours(field, lats, lons, level):
    """Line contours of a field as lists of (lat, lon) arrays."""
    import contourpy
    lat_up = lats[::-1]
    z = field[::-1, :]
    cg = contourpy.contour_generator(x=lons, y=lat_up, z=z, line_type=contourpy.LineType.Separate)
    return [np.c_[ln[:, 1], ln[:, 0]] for ln in cg.lines(level) if len(ln) > 2]


def filled(field, lats, lons, lo, hi):
    """Filled contour polygons (each a list of rings of (lat, lon)) between lo and hi."""
    import contourpy
    lat_up = lats[::-1]
    z = field[::-1, :]
    cg = contourpy.contour_generator(x=lons, y=lat_up, z=z, fill_type=contourpy.FillType.OuterOffset)
    pts_list, offs_list = cg.filled(lo, hi)
    out = []
    for pts, offs in zip(pts_list, offs_list):
        rings = [np.c_[pts[a:b, 1], pts[a:b, 0]] for a, b in zip(offs[:-1], offs[1:])]
        out.append(rings)
    return out


def sea_route(land, lats, lons, start, end, shore_km=1.5):
    """Shortest sea path from start to the sea cell nearest to end, then on to end.

    Returns (list of (lat, lon), landfall (lat, lon), offshore length km). Cells within `shore_km`
    of land cost more, so routes keep off the coast until the landfall.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    ny, nx = land.shape
    lat_mid = float(np.mean(lats))
    res = _res(lats)
    dy, dx = _cell_km(lat_mid, res)

    def cell(p):
        i = int(np.clip(round((lats[0] - p[0]) * res), 0, ny - 1))
        j = int(np.clip(round((p[1] - lons[0]) * res), 0, nx - 1))
        return i, j

    sea = ~land
    if sea.sum() < 4:
        return [start, end], end, _gc_km(start, end)
    dist = distance_from_land_km(land, lat_mid, res)
    from scipy.ndimage import label as _label
    comp, ncomp = _label(sea, structure=np.ones((3, 3), int))
    si, sj = cell(start)
    if not sea[si, sj]:
        si, sj = _nearest(sea, si, sj)
    if ncomp > 1:
        sizes = np.bincount(comp.ravel())
        if sizes[comp[si, sj]] < 0.02 * sizes[1:].sum():
            # the start sits in a lake or a pocket the grid cannot see out of: use the open sea nearby
            si, sj = _nearest(comp == sizes[1:].argmax() + 1, si, sj)
    sea = comp == comp[si, sj]                 # route only through water connected to the start
    land = ~sea
    ei, ej = cell(end)
    li, lj = (ei, ej) if sea[ei, ej] else _nearest(sea, ei, ej)
    idx = -np.ones(land.shape, int)
    ii, jj = np.nonzero(sea)
    idx[ii, jj] = np.arange(len(ii))
    pen = 1.0 + 3.0 * np.clip(1 - dist / shore_km, 0, 1)
    rows, cols, w = [], [], []
    for di, dj in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a_i, a_j = ii, jj
        b_i, b_j = ii + di, jj + dj
        ok = (b_i < ny) & (b_j >= 0) & (b_j < nx)
        a_i, a_j, b_i, b_j = a_i[ok], a_j[ok], b_i[ok], b_j[ok]
        ok2 = sea[b_i, b_j]
        a_i, a_j, b_i, b_j = a_i[ok2], a_j[ok2], b_i[ok2], b_j[ok2]
        step = math.hypot(di * dy, dj * dx)
        cost = step * 0.5 * (pen[a_i, a_j] + pen[b_i, b_j])
        rows.append(idx[a_i, a_j]); cols.append(idx[b_i, b_j]); w.append(cost)
    rows, cols, w = np.concatenate(rows), np.concatenate(cols), np.concatenate(w)
    g = coo_matrix((np.r_[w, w], (np.r_[rows, cols], np.r_[cols, rows])), shape=(len(ii), len(ii))).tocsr()
    s, t = idx[si, sj], idx[li, lj]
    _, pred = dijkstra(g, indices=s, return_predecessors=True)
    if pred[t] < 0 and t != s:
        return [start, end], end, _gc_km(start, end)
    chain = [t]
    while chain[-1] != s:
        chain.append(pred[chain[-1]])
    chain = chain[::-1]
    pts = [(float(lats[ii[k]]), float(lons[jj[k]])) for k in chain]
    pts[0] = start if not land[cell(start)] else pts[0]
    pts = _rdp(pts, 1.2 / geo_km_per_deg())
    pts = _chaikin(pts, 3)
    landfall = (float(lats[li]), float(lons[lj]))
    off_km = sum(_gc_km(pts[k], pts[k + 1]) for k in range(len(pts) - 1))
    return pts + ([end] if (li, lj) != (ei, ej) else []), landfall, off_km


def geo_km_per_deg():
    return KM_PER_DEG


def _nearest(mask, i, j):
    ii, jj = np.nonzero(mask)
    k = int(np.argmin((ii - i) ** 2 + (jj - j) ** 2))
    return int(ii[k]), int(jj[k])


def _gc_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _rdp(pts, eps):
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0]), np.array(pts[-1])
    ab = b - a
    n = np.linalg.norm(ab)
    arr = np.array(pts)
    rel = arr - a
    # 2-D cross product written out (np.cross on 2-D vectors is removed in recent NumPy)
    d = (np.abs(ab[0] * rel[:, 1] - ab[1] * rel[:, 0]) / n) if n > 0 else np.linalg.norm(rel, axis=1)
    k = int(np.argmax(d))
    if d[k] > eps:
        return _rdp(pts[:k + 1], eps)[:-1] + _rdp(pts[k:], eps)
    return [pts[0], pts[-1]]


def _chaikin(pts, it):
    for _ in range(it):
        if len(pts) < 3:
            return pts
        out = [pts[0]]
        for p, q in zip(pts[:-1], pts[1:]):
            out += [(0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]),
                    (0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1])]
        out.append(pts[-1])
        pts = out
    return pts


def window_for(points, pad_deg=0.35):
    """Land grid around the points, padded by a quarter of the span so routes can round capes outside it."""
    lat = [p[0] for p in points]
    lon = [p[1] for p in points]
    pad = max(pad_deg, 0.25 * max(max(lat) - min(lat), max(lon) - min(lon)))
    return land_window(max(min(lat) - pad, -89.9), min(max(lat) + pad, 89.9), max(min(lon) - pad, -180.0),
                       min(max(lon) + pad, 180.0))


@lru_cache(maxsize=256)
def route_path(a_lat, a_lon, b_lat, b_lon):
    """Shortest sea route from a to the coast nearest b, then straight on to b.

    Returns (tuple of (lat, lon) points, landfall (lat, lon), total km, offshore km). Windows larger than
    MAX_CELLS are coarsened, so a route across a whole sea basin still takes about a second."""
    a, b = (a_lat, a_lon), (b_lat, b_lon)
    land, lats, lons, ok = window_for([a, b])
    if not ok or land.size == 0:
        d = _gc_km(a, b)
        return (a, b), b, d, d
    land, lats, lons = coarsen(land, lats, lons)
    pts, lf, off = sea_route(land, lats, lons, a, b)
    on = _gc_km(lf, b) if pts[-1] == b and tuple(lf) != tuple(b) else 0.0
    return tuple(pts), lf, off + on, off


def route_km(a_lat, a_lon, b_lat, b_lon):
    """(total km, offshore km, onshore km, landfall lat, landfall lon) of `route_path`."""
    _, lf, tot, off = route_path(a_lat, a_lon, b_lat, b_lon)
    return tot, off, tot - off, lf[0], lf[1]


def sea_km(a_lat, a_lon, b_lat, b_lon):
    return route_path(a_lat, a_lon, b_lat, b_lon)[2]


@lru_cache(maxsize=256)
def nearest_shore(lat, lon, search_deg=1.5):
    """Nearest coast cell to a sea point: (distance km, lat, lon), or None if no land within ~5 degrees."""
    land, lats, lons, ok = land_window(lat - search_deg, lat + search_deg, lon - search_deg * 1.5,
                                       lon + search_deg * 1.5)
    if not ok:
        return None
    if not land.any():
        return nearest_shore(lat, lon, 5.0) if search_deg < 5.0 else None
    land, lats, lons = coarsen(land, lats, lons, 400_000)
    ii, jj = np.nonzero(land)
    kx = math.cos(math.radians(lat))
    d2 = ((lats[ii] - lat) ** 2 + ((lons[jj] - lon) * kx) ** 2)
    k = int(np.argmin(d2))
    p = (float(lats[ii[k]]), float(lons[jj[k]]))
    return _gc_km((lat, lon), p), p[0], p[1]


def is_land(lat, lon):
    """True if the 1 km cell at (lat, lon) is land; None if the coastline file is missing."""
    land, _, _, ok = land_window(lat - 0.004, lat + 0.004, lon - 0.004, lon + 0.004)
    if not ok or land.size == 0:
        return None
    return bool(land[land.shape[0] // 2, land.shape[1] // 2])
