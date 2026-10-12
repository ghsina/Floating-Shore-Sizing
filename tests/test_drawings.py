"""The three illustrations render for typical and edge-case designs, and sub-hourly uploads are averaged."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evolve_planner import params  # noqa: E402
from evolve_planner.weather import to_hourly_year  # noqa: E402
from ui import drawings, geo  # noqa: E402


def _user(**kw):
    u = params.defaults()
    u.update(dict(site_lat=47.38, site_lon=-3.55, grid_lat=47.64, grid_lon=-3.16, h2_lat=47.73, h2_lon=-3.37))
    u.update(kw)
    return u


def test_land_mask_knows_belle_ile():
    land, lats, lons, ok = geo.land_window(47.25, 47.45, -3.30, -3.05)
    assert ok and land.any() and (~land).any()


def test_drawings_render_preview_and_empty_design():
    u = _user()
    for fn in (drawings.atlas_html, drawings.island_html, drawings.section_html):
        assert "<svg" in fn(u)
    empty = {k: 0.0 for k in drawings.CAPS}
    empty["pipe"] = "none"
    for fn in (drawings.atlas_html, drawings.island_html, drawings.section_html):
        assert "<svg" in fn(u, empty, {"grid_mwh": 0, "h2_kg": 0})


def test_fixed_hvdc_far_site():
    u = _user(avg_water_depth_m=30, site_lat=56.6, site_lon=6.4, grid_lat=55.55, grid_lon=8.13, h2_lat=56.25,
              h2_lon=8.12, enable_pipe=True)
    assert "<svg" in drawings.atlas_html(u)


def test_sub_hourly_upload_is_averaged():
    x, note = to_hourly_year(np.ones(35136))
    assert len(x) == 8760 and "15-minute" in note and "leap" in note
    x, note = to_hourly_year(np.arange(17520, dtype=float))
    assert len(x) == 8760 and x[0] == 0.5
