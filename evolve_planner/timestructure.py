"""Time structure shared by the full-chronology model and every reduced model.

One representation covers all cases:

* ``reps``   : representative profiles, dict attr -> array (R, L)
* ``slots``  : the chronology as a list of (rep index, repetitions, year index).
               The model walks the slots in order; storage inventories are
               carried from slot to slot and closed cyclically at the end.

Examples
--------
full chronology, Y years     R = Y, L = 8760, slots = [(y, 1, y) for y]
v9 seasonal weeks            R = 12, L = 168, slots = [(p, 730/168, 0) ...]
clustered weeks (Kotzur)     R = K, L = 168, slots = one per calendar week,
                             each pointing at its cluster's representative
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

HOURS = 8760


@dataclass
class TimeStructure:
    reps: dict                 # attr -> (R, L) float array
    slots: list                # [(r, w, y)]
    n_years: int
    label: str = ""
    meta: dict = field(default_factory=dict)
    dt: float = 1.0            # hours per time step (1 except for down-sampled chronologies)
    step_w: np.ndarray | None = None   # relative length of each step within a period
                                       # (variable-length blocks of the TDA aggregation)

    @property
    def sw(self) -> np.ndarray:
        return np.ones(self.L) if self.step_w is None else np.asarray(self.step_w, float)

    @property
    def R(self) -> int:
        return next(iter(self.reps.values())).shape[0]

    @property
    def L(self) -> int:
        return next(iter(self.reps.values())).shape[1]

    def weight_ry(self) -> np.ndarray:
        """W[r, y]: hours represented by one time step of rep r in year y
        (occurrences x step length)."""
        W = np.zeros((self.R, self.n_years))
        for r, w, y in self.slots:
            W[r, y] += w * self.dt
        return W

    def weight_r(self) -> np.ndarray:
        """Average occurrences of rep r per year."""
        return self.weight_ry().sum(axis=1) / self.n_years

    def check(self):
        tot = self.weight_ry().sum(axis=0) * self.sw.sum()
        if not np.allclose(tot, HOURS, rtol=1e-6):
            raise ValueError(f"[{self.label}] hours per year {tot} != {HOURS}")

    def expand(self, attr: str) -> np.ndarray:
        """Rebuild the (Y, 8760) series this structure implies (for diagnostics)."""
        out = [[] for _ in range(self.n_years)]
        prof = self.reps[attr]
        for r, w, y in self.slots:
            n_full = int(np.floor(w + 1e-9))
            frac = w - n_full
            for _ in range(n_full):
                out[y].append(prof[r])
            if frac > 1e-9:
                out[y].append(prof[r][: int(round(frac * self.L))])
        return np.array([np.concatenate(o)[:HOURS] for o in out])


def full(data: dict) -> TimeStructure:
    """Full chronology. data: attr -> (Y, 8760)."""
    Y = next(iter(data.values())).shape[0]
    ts = TimeStructure(reps={k: np.asarray(v, float) for k, v in data.items()},
                       slots=[(y, 1.0, y) for y in range(Y)], n_years=Y, label="FULL")
    ts.check()
    return ts


def week_slots(Y: int, L: int = 168):
    """Calendar periods per year: full periods + one partial tail period."""
    n_full = HOURS // L
    tail = HOURS - n_full * L
    per_year = [(i * L, L) for i in range(n_full)]
    if tail:
        per_year.append((n_full * L, tail))
    return n_full, tail, per_year


def period_matrix(data: dict, L: int = 168):
    """Stack all FULL calendar periods of all years: returns
    X[attr] -> (Y * n_full, L), and the index list [(y, i)]."""
    Y = next(iter(data.values())).shape[0]
    n_full, _, _ = week_slots(Y, L)
    idx = [(y, i) for y in range(Y) for i in range(n_full)]
    X = {k: np.stack([v[y, i * L:(i + 1) * L] for (y, i) in idx]) for k, v in data.items()}
    return X, idx


def from_assignment(data: dict, labels: np.ndarray, rep_profiles: dict, L: int = 168,
                    label: str = "", merge: bool = True, meta: dict | None = None) -> TimeStructure:
    """Chronology where each calendar period points at its representative.

    labels: rep index of every full period, in period_matrix order (Y * n_full).
    The partial tail period of each year (24 h for weeks) uses the rep of the
    last full period, with fractional repetition tail / L.
    """
    Y = next(iter(data.values())).shape[0]
    n_full, tail, _ = week_slots(Y, L)
    labels = np.asarray(labels, int).reshape(Y, n_full)
    slots = []
    for y in range(Y):
        seq = [(int(labels[y, i]), 1.0) for i in range(n_full)]
        if tail:
            seq.append((int(labels[y, -1]), tail / L))
        for r, w in seq:
            if merge and slots and slots[-1][0] == r and slots[-1][2] == y:
                slots[-1] = (r, slots[-1][1] + w, y)
            else:
                slots.append((r, w, y))
    ts = TimeStructure(reps={k: np.asarray(v, float) for k, v in rep_profiles.items()},
                       slots=slots, n_years=Y, label=label, meta=meta or {})
    ts.check()
    return ts


def from_segments(rep_profiles: dict, seg_hours: np.ndarray, L: int = 168, label: str = "",
                  meta: dict | None = None) -> TimeStructure:
    """v9-style: one representative per chronological segment of one year."""
    R = next(iter(rep_profiles.values())).shape[0]
    slots = [(r, float(seg_hours[r]) / L, 0) for r in range(R)]
    ts = TimeStructure(reps=rep_profiles, slots=slots, n_years=1, label=label, meta=meta or {})
    ts.check()
    return ts


def downsample(data: dict, k: int) -> TimeStructure:
    """Full chronology at k-hour resolution (block means). Keeps the true order
    of every hour, so storage dynamics stay chronological."""
    if 8760 % k:
        raise ValueError("k must divide 8760")
    reps = {a: v.reshape(v.shape[0], 8760 // k, k).mean(axis=2) for a, v in data.items()}
    Y = next(iter(data.values())).shape[0]
    ts = TimeStructure(reps=reps, slots=[(y, 1.0, y) for y in range(Y)], n_years=Y,
                       label=f"downsample_{k}h", meta={"method": f"downsample_{k}h", "K": 8760 // k}, dt=float(k))
    ts.check()
    return ts
