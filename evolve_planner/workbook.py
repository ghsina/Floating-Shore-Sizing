"""Input workbook: one Excel file that holds every input of a planner run.

Sheets
  README      how to fill the file
  Inputs      one row per input: key | group | label | unit | value | default | step3 | help
  TimeSeries  8,760 rows: hour | wind_cf | pv_cf | price_eur_mwh | elec_demand_mw | h2_demand_kgh
The app reads the 'key' and 'value' columns and the TimeSeries columns; labels
can be edited freely. Download a filled copy from the app at any time and
upload it again to continue.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

from .params import SPEC, defaults

TS_COLS = [("wind_cf", "wind_cf"), ("pv_cf", "pv_cf"), ("price", "price_eur_mwh"),
           ("elec_demand", "elec_demand_mw"), ("h2_demand", "h2_demand_kgh")]


def to_bytes(user: dict, series: dict | None = None, notes: list[str] | None = None) -> bytes:
    rows = []
    for s in SPEC:
        v = user.get(s.key, s.default)
        rows.append({"key": s.key, "group": s.group, "label": s.label, "unit": s.unit, "value": v,
                     "default": s.default, "placeholder until Step 3": "yes" if s.step3 else "",
                     "options": ", ".join(s.options), "help": s.help, "source of the default": s.source})
    inputs = pd.DataFrame(rows)
    ts = pd.DataFrame({"hour": np.arange(1, 8761)})
    for k, col in TS_COLS:
        x = (series or {}).get(k)
        ts[col] = np.round(x, 5) if x is not None else np.nan
    readme = pd.DataFrame({"EVOLVE Planner input workbook": [
        "Inputs: change the 'value' column only. 'default' shows the starting value and 'source of the default' "
        "where it comes from (cables and converters: manufacturer data and published cost functions, checked "
        "against ACER 2026; pipelines and compressors: ACER 2026 unit investment cost indicators). 'placeholder "
        "until Step 3' marks costs with no referenced value yet, kept from the v9 model or assumed.",
        "TimeSeries: 8,760 hourly rows of one year (UTC, 29 February removed). wind_cf and pv_cf are capacity "
        "factors between 0 and 1. price_eur_mwh is needed for merchant and CfD revenue. elec_demand_mw and "
        "h2_demand_kgh are needed only for profile delivery. Leave unused columns empty.",
        "Open this file in the app's sidebar ('Open an inputs workbook') to restore every input and the hourly series.",
        *(notes or []),
    ]})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        readme.to_excel(xw, sheet_name="README", index=False)
        inputs.to_excel(xw, sheet_name="Inputs", index=False)
        ts.to_excel(xw, sheet_name="TimeSeries", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col[:60])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 70)
    return buf.getvalue()


def _cast(spec, v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v == "":
        return spec.default
    if spec.kind == "bool":
        return str(v).strip().lower() in ("true", "1", "yes", "y")
    if spec.kind == "int":
        return int(float(v))
    if spec.kind in ("choice", "text"):
        return str(v)
    return float(v)


def from_file(file) -> tuple[dict, dict, list[str]]:
    """Read a workbook written by `to_bytes` (or edited by a user)."""
    xl = pd.ExcelFile(file)
    user, notes = defaults(), []
    if "Inputs" in xl.sheet_names:
        df = xl.parse("Inputs")
        by = {s.key: s for s in SPEC}
        for _, r in df.iterrows():
            k = str(r.get("key", "")).strip()
            if k == "platform_float_factor":
                notes.append("Input 'platform_float_factor' is no longer used (version 0.10): the floating platform "
                             "factor now follows from the jacket share, topside uplift and hull ratio "
                             "(Island platform inputs).")
            if k in by:
                try:
                    user[k] = _cast(by[k], r.get("value"))
                except (TypeError, ValueError):
                    notes.append(f"Input '{k}': value '{r.get('value')}' not understood, default kept.")
    series = {}
    if "TimeSeries" in xl.sheet_names:
        from .weather import series_from_table
        series, n2 = series_from_table(xl.parse("TimeSeries"))
        notes += n2
    return user, series, notes
