"""Hourly input series: uploads, ERA5 download (Open-Meteo) and day-ahead prices.

Every series is one calendar year of 8,760 hours (UTC, 29 February removed).

Wind: ERA5 100 m wind speed -> hub height (power law) -> IEA 15 MW reference
turbine curve, smoothed to farm level (sigma = 0.6 + 0.2 v) -> losses.
PV: ERA5 global and diffuse irradiance -> pvlib (tilted floating array,
Faiman cell temperature with water cooling, PVWatts) -> losses.
The same method produced the validated Belle-Ile test series (Step 2).
"""
from __future__ import annotations

import io
import time

import numpy as np
import pandas as pd

# IEA 15 MW reference turbine (IEAWindTask37/IEA-15-240-RWT, Rotor Performance table)
IEA15_WS = [3.0, 3.55, 4.068, 4.554, 5.006, 5.424, 5.807, 6.153, 6.462, 6.733, 6.965, 7.159, 7.313, 7.427,
            7.501, 7.535, 7.541, 7.588, 7.676, 7.803, 7.97, 8.177, 8.422, 8.706, 9.027, 9.386, 9.78, 10.21,
            10.659, 25.0]
IEA15_PU = [0.0029, 0.0195, 0.0405, 0.0653, 0.0934, 0.1239, 0.1558, 0.1883, 0.2203, 0.2507, 0.2787, 0.3028,
            0.3227, 0.3381, 0.3483, 0.353, 0.3539, 0.3606, 0.3732, 0.3921, 0.4178, 0.4511, 0.493, 0.5445,
            0.6071, 0.6823, 0.7719, 0.8782, 1.0, 1.0]

COLUMNS = {
    "wind_cf": ["wind_cf", "wt_cp", "wind", "wind cf"],
    "pv_cf": ["pv_cf", "pv_cp", "pv", "solar", "solar_cf", "pv cf"],
    "price": ["price", "price_eur_mwh", "el_price", "day_ahead", "dayahead"],
    "elec_demand": ["elec_demand", "elec_demand_mw", "demand_mw", "load_mw"],
    "h2_demand": ["h2_demand", "h2_demand_kgh", "h2_kgh"],
}


# ---------------------------------------------------------------------------
# uploads
# ---------------------------------------------------------------------------

def read_table(file) -> pd.DataFrame:
    name = getattr(file, "name", str(file)).lower()
    if name.endswith((".xlsx", ".xls")):
        xl = pd.ExcelFile(file)
        sheet = "TimeSeries" if "TimeSeries" in xl.sheet_names else xl.sheet_names[0]
        return xl.parse(sheet)
    return pd.read_csv(file, sep=None, engine="python")


def series_from_table(df: pd.DataFrame) -> tuple[dict, list[str]]:
    """Map recognised columns to series. Returns (series, notes)."""
    cols = {c.lower().strip(): c for c in df.columns}
    out, notes = {}, []
    for key, names in COLUMNS.items():
        hit = next((cols[n] for n in names if n in cols), None)
        if hit is None:
            continue
        x = pd.to_numeric(df[hit], errors="coerce").to_numpy(float)
        if np.isnan(x).all():
            continue                                  # empty column
        x, msg = to_hourly_year(x)
        if msg:
            notes.append(f"{key}: {msg}")
        if len(x) != 8760:
            notes.append(f"{key}: found {len(x)} rows, 8,760 needed; column ignored.")
            continue
        if np.isnan(x).any():
            n = int(np.isnan(x).sum())
            x = pd.Series(x).interpolate(limit_direction="both").to_numpy()
            notes.append(f"{key}: {n} missing values filled by interpolation.")
        if key in ("wind_cf", "pv_cf"):
            if x.max() > 1.0 + 1e-9 and x.max() <= 100.0:
                x = x / 100.0
                notes.append(f"{key}: values looked like percent and were divided by 100.")
            x = np.clip(x, 0.0, 1.0)
        out[key] = x
    return out, notes


STEPS_PER_HOUR = {1: "hourly", 2: "30-minute", 4: "15-minute", 6: "10-minute", 12: "5-minute"}


def to_hourly_year(x):
    """Bring one calendar year at any of 60/30/15/10/5-minute resolution to 8,760 hourly values.

    Leap years lose 29 February; sub-hourly values are averaged within each hour (right for power,
    capacity factors and prices). Returns (array, note or '')."""
    n = len(x)
    for k, name in STEPS_PER_HOUR.items():
        for hours, leap in ((8760, False), (8784, True)):
            if n == hours * k:
                notes = []
                if leap:
                    x = np.r_[x[:1416 * k], x[1440 * k:]]
                    notes.append("leap year, 29 February removed")
                if k > 1:
                    x = np.nanmean(np.asarray(x, float).reshape(8760, k), axis=1)
                    notes.append(f"{name} values averaged to hourly")
                return np.asarray(x, float), "; ".join(notes)
    return np.asarray(x, float), ""


def template_csv() -> bytes:
    h = np.arange(1, 8761)
    df = pd.DataFrame({"hour": h, "wind_cf": "", "pv_cf": "", "price_eur_mwh": "", "elec_demand_mw": "",
                       "h2_demand_kgh": ""})
    return df.to_csv(index=False).encode()


# ---------------------------------------------------------------------------
# conversion
# ---------------------------------------------------------------------------

def _farm_curve(sig_a=0.6, sig_b=0.2):
    g = np.arange(0.0, 40.0001, 0.05)
    single = np.interp(g, np.r_[2.999, IEA15_WS, 25.0001], np.r_[0.0, IEA15_PU, 0.0], left=0.0, right=0.0)
    out = np.empty_like(g)
    for i, v in enumerate(g):
        s = sig_a + sig_b * v
        w = np.exp(-0.5 * ((g - v) / s) ** 2)
        out[i] = (w * single).sum() / w.sum()
    return g, out


_FARM = None


def wind_cf_from_speed(ws100, hub_height=150.0, alpha=0.11, losses=0.125, scale=1.0):
    global _FARM
    if _FARM is None:
        _FARM = _farm_curve()
    g, pc = _FARM
    ws = np.asarray(ws100, float) * (hub_height / 100.0) ** alpha * scale
    return np.clip(np.interp(ws, g, pc) * (1.0 - losses), 0.0, 1.0)


def pv_cf_from_irradiance(times, lat, lon, ghi, dhi, t_air, wind10=None, tilt=10.0, azimuth=180.0, losses=0.14):
    import pvlib
    tmid = pd.DatetimeIndex(times) - pd.Timedelta(minutes=30)
    sp = pvlib.solarposition.get_solarposition(tmid, lat, lon)
    ghi = np.asarray(ghi, float)
    dhi = np.minimum(np.asarray(dhi, float), ghi)
    cosz = np.cos(np.radians(sp["apparent_zenith"].to_numpy()))
    dni = np.clip(np.where(cosz > 0.05, (ghi - dhi) / np.maximum(cosz, 0.05), 0.0), 0, 1100)
    poa = pvlib.irradiance.get_total_irradiance(tilt, azimuth if lat >= 0 else 0.0, sp["apparent_zenith"],
                                                sp["azimuth"], dni=dni, ghi=ghi, dhi=dhi, albedo=0.06)
    g = np.nan_to_num(poa["poa_global"].to_numpy(), nan=0.0)
    ws = np.zeros_like(g) if wind10 is None else np.asarray(wind10, float)
    tc = pvlib.temperature.faiman(g, np.asarray(t_air, float), ws, u0=35.0, u1=8.0)
    pdc = pvlib.pvsystem.pvwatts_dc(g, tc, pdc0=1.0, gamma_pdc=-0.0035)
    return np.clip(np.nan_to_num(np.asarray(pdc) * (1.0 - losses)), 0.0, 1.0)


def _drop_feb29(df):
    idx = pd.DatetimeIndex(df["time"])
    return df[~((idx.month == 2) & (idx.day == 29))].reset_index(drop=True)


# ---------------------------------------------------------------------------
# downloads (need internet; the hosted app has it)
# ---------------------------------------------------------------------------

def fetch_era5(lat: float, lon: float, year: int, timeout: int = 60) -> tuple[dict, dict]:
    """Wind and PV capacity factors for one year from ERA5 (Open-Meteo archive API, no key)."""
    import requests
    url = "https://archive-api.open-meteo.com/v1/archive"
    q = {"latitude": lat, "longitude": lon, "start_date": f"{year}-01-01", "end_date": f"{year}-12-31",
         "hourly": "wind_speed_100m,wind_speed_10m,shortwave_radiation,diffuse_radiation,temperature_2m",
         "models": "era5", "wind_speed_unit": "ms", "timezone": "GMT"}
    r = requests.get(url, params=q, timeout=timeout)
    r.raise_for_status()
    j = r.json()["hourly"]
    df = _drop_feb29(pd.DataFrame(j).assign(time=lambda d: pd.to_datetime(d["time"])))
    wind = wind_cf_from_speed(df["wind_speed_100m"].to_numpy())
    pv = pv_cf_from_irradiance(df["time"], lat, lon, df["shortwave_radiation"], df["diffuse_radiation"],
                               df["temperature_2m"], df["wind_speed_10m"])
    meta = {"source": "ERA5 via Open-Meteo archive API", "lat": lat, "lon": lon, "year": year,
            "mean_ws100": float(df["wind_speed_100m"].mean())}
    return {"wind_cf": wind[:8760], "pv_cf": pv[:8760]}, meta


def fetch_prices(zone: str, year: int, timeout: int = 60, retries: int = 4) -> tuple[np.ndarray, dict]:
    """Hourly day-ahead prices (EUR/MWh, UTC) from the Energy-Charts API (Fraunhofer ISE)."""
    import requests
    url = "https://api.energy-charts.info/price"
    for attempt in range(retries):
        r = requests.get(url, params={"bzn": zone, "start": f"{year}-01-01", "end": f"{year}-12-31"},
                         timeout=timeout)
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        j = r.json()
        s = pd.Series(np.asarray(j["price"], float),
                      index=pd.to_datetime(np.asarray(j["unix_seconds"]), unit="s", utc=True))
        s = s.resample("1h").mean().tz_convert(None)
        full = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
        s = s.reindex(full).interpolate(limit_direction="both")
        s = s[~((s.index.month == 2) & (s.index.day == 29))]
        return s.to_numpy()[:8760], {"source": "Energy-Charts API (SMARD data, CC BY 4.0)", "zone": zone,
                                     "year": year, "mean": float(s.mean())}
    raise RuntimeError("The price service is busy (rate limit). Try again in a minute or upload prices.")
