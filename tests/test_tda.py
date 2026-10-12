"""Checks that the TDA reduction does what its documentation claims."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from evolve_planner import tda  # noqa: E402

TS = ROOT / "examples" / "belle_ile" / "timeseries_2019.csv"


def brute_force_pairs(f):
    """Reference 0-dim sublevel persistence by sweeping thresholds on a path."""
    vals = np.unique(f)
    births = {}
    pairs = []
    comp_prev = []
    for v in vals:
        mask = f <= v
        comps, cur = [], []
        for i, m in enumerate(mask):
            if m:
                cur.append(i)
            elif cur:
                comps.append(cur); cur = []
        if cur:
            comps.append(cur)
        # each component is identified by its minimum index (elder = lower min)
        new = []
        for c in comps:
            mins = [k for k in births if k in c]
            if not mins:
                k = c[int(np.argmin(f[c]))]
                births[k] = f[k]
                new.append(k)
            elif len(mins) > 1:
                mins.sort(key=lambda k: (births[k], k))
                for k in mins[1:]:
                    pairs.append((births[k], v))
                    del births[k]
        comp_prev = comps
    return sorted(p[1] - p[0] for p in pairs if p[1] > p[0])


def test_persistence_matches_brute_force():
    rng = np.random.default_rng(3)
    for _ in range(5):
        f = np.cumsum(rng.normal(size=120)) + rng.normal(scale=1e-9, size=120)
        P = tda.persistence_pairs(f)[:-1]                       # drop the essential class
        ours = sorted((P[:, 1] - P[:, 0])[P[:, 1] > P[:, 0]])
        assert np.allclose(ours, brute_force_pairs(f), atol=1e-9)


@pytest.fixture(scope="module")
def year():
    df = pd.read_csv(TS)
    return {"wind_cf": df.wind_cf.to_numpy().reshape(1, -1), "pv_cf": df.pv_cf.to_numpy().reshape(1, -1),
            "price": df.price_eur_mwh.to_numpy().reshape(1, -1)}


@pytest.mark.parametrize("N", [730, 1460])
def test_tpca_size_energy_and_bound(year, N):
    attrs = ["wind_cf", "pv_cf", "price"]
    ts = tda.tpca(year, N, attrs)
    assert ts.L == N
    assert ts.sw.sum() == pytest.approx(8760)
    for a in attrs:                                              # block means preserve energy exactly
        assert (ts.reps[a][0] * ts.sw).sum() == pytest.approx(year[a][0].sum(), rel=1e-9)
    for a, b in ts.meta["bottleneck_norm"].items():              # stability: d_B <= sup-norm error
        assert b <= ts.meta["eps_achieved"] + 1e-12


def test_fixed_cuts_are_block_boundaries(year):
    ts = tda.tpca(year, 1460, ["wind_cf", "pv_cf"])
    ends = np.cumsum(ts.sw).astype(int) - 1
    X = np.stack([year[a][0] for a in ("wind_cf", "pv_cf")], axis=1)
    S = np.cumsum(X - X.mean(axis=0), axis=0)
    scale = S.max(axis=0) - S.min(axis=0)
    for k in range(2):
        for t in tda.critical_points(S[:, k], 0.02 * scale[k]):
            assert t in set(ends)                                # every persistent extremum ends a block
