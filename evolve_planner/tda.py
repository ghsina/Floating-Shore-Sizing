"""Topology-preserving chronological aggregation (TPCA) of one year of data.

The planner's time reduction. One year of hourly data (8,760 steps) is cut
into N variable-length blocks that follow the calendar; each block carries
the mean of every attribute and its duration. The model then runs on the N
blocks in their true order, so storage dynamics stay chronological.

Where blocks are cut is decided by topological data analysis of the
cumulative energy balance of each attribute,

    S_a(t) = sum_{tau <= t} ( x_a(tau) - mean(x_a) ).

Troughs and peaks of S_a are deficit and surplus episodes; their 0-dimensional
sublevel/superlevel-set persistence is the energy a store must shift between
them. Because block means preserve energy, the reduced balance S~_a equals
S_a at every block boundary and is the straight chord in between. Hence

    || S_a - S~_a ||_inf  =  largest chord error over all blocks  =:  e_a,

and by the stability theorem of persistence diagrams (Cohen-Steiner,
Edelsbrunner & Harer 2007) the bottleneck distance between the diagrams of
S_a and S~_a is at most e_a. The same holds for any net balance
c_w S_wind + c_pv S_pv - D t of a design with flat demand D, with bound
c_w e_wind + c_pv e_pv, because chords are linear and a flat demand is exact.

Algorithm
---------
1. Persistent critical points of every S_a (persistence >= tau) become fixed
   block boundaries: no deficit or surplus episode that matters is merged away.
2. Starting from hourly blocks, adjacent blocks are merged in Ward order
   (smallest increase in within-block variance of the standardised
   attributes, which keeps hourly power levels and the duration curves),
   but only while the chord error of every S_a stays below epsilon.
3. If N blocks are not reached, epsilon is relaxed geometrically.
The result reports the achieved epsilon (the guarantee) and the measured
bottleneck distances.
"""
from __future__ import annotations

import heapq
import time

import numpy as np

from . import timestructure as tsm


# ---------------------------------------------------------------------------
# 1-D persistence
# ---------------------------------------------------------------------------

def persistence_pairs(f: np.ndarray):
    """0-dim sublevel-set persistence of a signal on a path graph.

    Returns rows (birth value, death value, birth index, death index); the
    essential class (global minimum) is returned with death = max(f).
    """
    f = np.asarray(f, float)
    n = len(f)
    order = np.argsort(f, kind="stable")
    parent = np.full(n, -1, dtype=np.int64)
    bmin = np.empty(n, dtype=np.int64)          # index of the minimum that created the component
    out = []

    def find(i):
        r = i
        while parent[r] != r:
            r = parent[r]
        while parent[i] != r:
            parent[i], i = r, parent[i]
        return r

    for i in order:
        parent[i] = i
        bmin[i] = i
        for j in (i - 1, i + 1):
            if 0 <= j < n and parent[j] >= 0:
                ri, rj = find(i), find(j)
                if ri == rj:
                    continue
                if f[bmin[ri]] > f[bmin[rj]] or (f[bmin[ri]] == f[bmin[rj]] and bmin[ri] > bmin[rj]):
                    young, old = ri, rj
                else:
                    young, old = rj, ri
                if f[i] > f[bmin[young]]:
                    out.append((f[bmin[young]], f[i], bmin[young], i))
                parent[young] = old
    g = int(np.argmin(f))
    out.append((f[g], float(f.max()), g, int(np.argmax(f))))
    return np.array(out, dtype=float)


def diagrams(S: np.ndarray):
    """(sublevel, superlevel) diagrams as (birth, death) arrays."""
    lo = persistence_pairs(S)[:, :2]
    hi = -persistence_pairs(-S)[:, :2]
    return lo, hi


def critical_points(S: np.ndarray, tau: float) -> set:
    """Extrema of S (minima and maxima) whose persistence is at least tau."""
    pts = set()
    for sign in (1.0, -1.0):
        P = persistence_pairs(sign * S)
        keep = (P[:, 1] - P[:, 0]) >= tau
        pts.update(P[keep, 2].astype(int).tolist())     # births = extrema
        pts.update(P[keep, 3].astype(int).tolist())     # deaths = the opposite extrema
    return pts


def bottleneck(S1: np.ndarray, S2: np.ndarray) -> float:
    """Max bottleneck distance over sub- and superlevel diagrams (gudhi)."""
    import gudhi
    a, b = diagrams(S1), diagrams(S2)
    return max(gudhi.bottleneck_distance(a[0], b[0]), gudhi.bottleneck_distance(-a[1], -b[1]))


# ---------------------------------------------------------------------------
# Topology-preserving chronological aggregation
# ---------------------------------------------------------------------------

def _chord_error(S: np.ndarray, s: int, e: int) -> float:
    """Max |S - chord| over hours s..e, chord from S[s-1] (0 before t=0) to S[e]."""
    left = S[s - 1] if s > 0 else 0.0
    right = S[e]
    n = e - s + 1
    t = np.arange(1, n + 1)
    chord = left + (right - left) * t / n
    return float(np.max(np.abs(S[s:e + 1] - chord)))


def tpca(data: dict, N: int, attrs, tau_frac: float = 0.02, eps_frac: float = 0.002,
         relax: float = 1.5, label: str | None = None, protect=None) -> tsm.TimeStructure:
    """Reduce one year (data[a] shape (1, 8760)) to N chronological blocks.

    tau_frac : persistence threshold for fixed boundaries, as a fraction of the
               range of each cumulative balance.
    eps_frac : starting chord-error budget, same normalisation.
    """
    t0 = time.time()
    if data[attrs[0]].shape[0] != 1:
        raise ValueError("TPCA works on one year")
    T = data[attrs[0]].shape[1]
    X = np.stack([data[a][0] for a in attrs], axis=1)                  # (T, A)
    mu, sd = X.mean(axis=0), np.maximum(X.std(axis=0), 1e-12)
    Z = (X - mu) / sd
    S = np.cumsum(X - mu, axis=0)                                       # (T, A)
    scale = np.maximum(S.max(axis=0) - S.min(axis=0), 1e-12)

    # 1. fixed boundaries at persistent extrema of every cumulative balance
    fixed = set()
    for a in range(len(attrs)):
        fixed |= critical_points(S[:, a], tau_frac * scale[a])
    # a boundary "after hour t" forbids merging hour t with hour t+1
    cut_after = np.zeros(T, bool)
    for t in fixed:
        if t - 1 >= 0:
            cut_after[t - 1] = True          # extremum starts its own block ...
        cut_after[t] = True                  # ... and ends it
    # hours flagged by the verification step stay single-hour blocks
    for t in (protect or ()):
        t = int(t)
        if t - 1 >= 0:
            cut_after[t - 1] = True
        cut_after[t] = True
    # blocks: doubly linked list
    start = np.arange(T); end = np.arange(T)
    nxt = np.arange(1, T + 1); prv = np.arange(-1, T - 1)
    cnt = np.ones(T); ssum = Z.copy()
    alive = np.ones(T, bool)
    version = np.zeros(T, np.int64)
    n_blocks = T

    def ward(i, j):
        return cnt[i] * cnt[j] / (cnt[i] + cnt[j]) * float(((ssum[i] / cnt[i] - ssum[j] / cnt[j]) ** 2).sum())

    def chord(i, j):
        s, e = start[i], end[j]
        return max(_chord_error(S[:, a], s, e) / scale[a] for a in range(len(attrs)))

    eps = eps_frac
    blocked = []                                                       # merges that broke eps
    heap = []

    def push(i):
        j = nxt[i]
        if j >= T or not alive[i] or not alive[j] or cut_after[end[i]]:
            return
        heapq.heappush(heap, (ward(i, j), i, j, version[i], version[j]))

    for i in range(T - 1):
        push(i)
    n_relax = 0
    while n_blocks > N:
        if not heap:
            if not blocked:
                break                                                   # only fixed cuts remain
            eps *= relax
            n_relax += 1
            for item in blocked:
                heapq.heappush(heap, item)
            blocked = []
            continue
        w, i, j, vi, vj = heapq.heappop(heap)
        if not (alive[i] and alive[j]) or version[i] != vi or version[j] != vj or nxt[i] != j:
            continue
        if chord(i, j) > eps:
            blocked.append((w, i, j, vi, vj))
            continue
        # merge j into i
        end[i] = end[j]; cnt[i] += cnt[j]; ssum[i] += ssum[j]
        alive[j] = False
        nxt[i] = nxt[j]
        if nxt[j] < T:
            prv[nxt[j]] = i
        version[i] += 1
        n_blocks -= 1
        if prv[i] >= 0:
            version[prv[i]] += 0          # neighbour's pair is re-pushed below
            push(prv[i])
        push(i)
    blocks = [(int(start[i]), int(end[i])) for i in range(T) if alive[i]]
    lengths = np.array([e - s + 1 for s, e in blocks], float)
    reps = {}
    for a, v in data.items():
        reps[a] = np.array([[float(v[0, s:e + 1].mean()) for s, e in blocks]])
    # achieved guarantee and measured bottleneck distances
    eps_achieved = 0.0
    bott = {}
    for k, a in enumerate(attrs):
        Sr = np.repeat(np.cumsum(reps[a][0] * lengths - mu[k] * lengths), 1)   # S at block ends
        ends = np.array([e for _, e in blocks])
        Sfull_interp = np.interp(np.arange(T), np.r_[-1, ends], np.r_[0.0, Sr])
        err = float(np.max(np.abs(S[:, k] - Sfull_interp))) / scale[k]
        eps_achieved = max(eps_achieved, err)
        bott[a] = bottleneck(S[:, k], Sfull_interp) / scale[k]
    meta = {"method": "tpca", "K": len(blocks), "n_fixed": len(fixed), "n_protected": len(protect or ()), "eps_start": eps_frac,
            "eps_achieved": eps_achieved, "n_relax": n_relax, "bottleneck_norm": bott,
            "tau_frac": tau_frac, "select_s": time.time() - t0,
            "min_block_h": int(lengths.min()), "max_block_h": int(lengths.max())}
    ts = tsm.TimeStructure(reps=reps, slots=[(0, 1.0, 0)], n_years=1, label=label or f"tpca_N{len(blocks)}",
                           meta=meta, dt=1.0, step_w=lengths)
    ts.check()
    return ts


def uniform(data: dict, N: int) -> tsm.TimeStructure:
    """Same-size baseline without topology: equal-length chronological blocks."""
    T = next(iter(data.values())).shape[1]
    edges = np.rint(np.linspace(0, T, N + 1)).astype(int)
    lengths = np.diff(edges).astype(float)
    reps = {a: np.array([[float(v[0, edges[i]:edges[i + 1]].mean()) for i in range(N)]]) for a, v in data.items()}
    ts = tsm.TimeStructure(reps=reps, slots=[(0, 1.0, 0)], n_years=1, label=f"uniform_N{N}",
                           meta={"method": "uniform", "K": N}, dt=1.0, step_w=lengths)
    ts.check()
    return ts
