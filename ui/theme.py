"""Visual identity: sea-chart palette and waterline backgrounds, Archivo + IBM Plex Sans + Source Serif 4."""
import streamlit as st

from ._bg import PAGE_BG, SIDEBAR_BG

PALETTE = {
    "abyss": "#0E2A3B",     # deep water: headings, hero
    "tide": "#1F6F8B",      # primary actions
    "chart": "#EEF3F5",     # page background (sea-chart paper)
    "ink": "#13232E",       # text
    "power": "#E3A72F",     # electricity
    "h2": "#3FC1C9",        # hydrogen
    "h2_ink": "#1E8C93",    # hydrogen as text
    "store": "#8E7CC3",     # storage
    "muted": "#9AA8B0",
    "warn": "#C8553D",
}

CSS = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@87,500;87,600;87,700&family=IBM+Plex+Sans:wght@400;500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"], .stMarkdown, .stText, p, li, label, input, textarea {{
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
}}
h1, h2, h3, h4 {{ font-family: 'Archivo', 'IBM Plex Sans', sans-serif !important; font-stretch: 87%;
  color: {PALETTE['abyss']}; letter-spacing: -0.01em; }}
h1 {{ font-weight: 700 !important; }}
.block-container {{ padding-top: 4.6rem; padding-bottom: 4rem; max-width: 1380px; }}
.stApp {{ background-color: {PALETTE['chart']}; background-image: url("{PAGE_BG}"); background-size: 640px 640px; }}
header[data-testid="stHeader"] {{ background: rgba(238,243,245,0.82); backdrop-filter: blur(6px); }}
[data-testid="stSidebar"] > div:first-child {{ background-image: url("{SIDEBAR_BG}"); background-size: 520px 520px; }}
.hero-kicker {{ font-family: 'Source Serif 4', Georgia, serif; font-style: italic; font-size: 1.05rem; color: {PALETTE['tide']}; }}
h1 {{ font-size: 2.7rem !important; line-height: 1.08 !important; }}
iframe {{ border-radius: 6px; }}
div[data-testid="stSegmentedControl"] button {{ font-weight: 500; }}
[data-testid="stSidebar"] {{ background: {PALETTE['abyss']}; }}
[data-testid="stSidebar"] * {{ color: #DCE8EE !important; }}
[data-testid="stSidebar"] .stButton button, [data-testid="stSidebar"] .stDownloadButton button {{
  background: transparent; border: 1px solid #3F6577; color: #DCE8EE !important; }}
.stButton button[kind="primary"] {{ background: {PALETTE['tide']}; border: 0; }}
.stButton button[kind="primary"]:hover {{ background: {PALETTE['abyss']}; }}
div[data-testid="stMetricValue"] {{ font-family: 'Archivo', sans-serif; font-stretch: 87%;
  font-variant-numeric: tabular-nums; color: {PALETTE['abyss']}; }}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{ background: #163A4F; border: 1px dashed #3F6577; }}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {{ background: transparent; border: 1px solid #5B8396; }}
.schematic svg {{ width: 100%; height: auto; display: block; border-radius: 6px; }}
.lede {{ font-size: 1.05rem; color: #3A4A54; max-width: 62ch; }}
.stepper {{ display: flex; gap: 0; margin: 0.4rem 0 1.2rem 0; border-bottom: 1px solid #C9D6DD; }}
.stepper .s {{ padding: 0.5rem 1rem 0.6rem 0; margin-right: 1.4rem; color: #6B7B85; font-weight: 500;
  border-bottom: 3px solid transparent; white-space: nowrap; }}
.stepper .s.on {{ color: {PALETTE['abyss']}; border-bottom-color: {PALETTE['tide']}; }}
.stepper .s.done {{ color: {PALETTE['tide']}; }}
.stepper .n {{ font-family: 'Archivo', sans-serif; margin-right: 0.35rem; }}
.badge {{ display: inline-block; padding: 0.15rem 0.55rem; border-radius: 4px; font-size: 0.85rem;
  font-weight: 600; margin-right: 0.4rem; border: 1px solid; }}
.badge.p {{ color: #8A5A00; border-color: {PALETTE['power']}; background: #FBF1DD; }}
.badge.h {{ color: {PALETTE['h2_ink']}; border-color: {PALETTE['h2']}; background: #E2F5F6; }}
.badge.n {{ color: {PALETTE['abyss']}; border-color: #9FB6C2; background: #F2F6F8; }}
.maplegend {{ display: flex; flex-wrap: wrap; gap: 0.3rem 1.1rem; font-size: 0.85rem; color: #3A4A54; margin: 0.2rem 0 0.5rem; }}
.maplegend .lg i {{ display: inline-block; width: 18px; height: 5px; border-radius: 3px; margin-right: 0.4rem; vertical-align: middle; }}
.badge.w {{ color: #7A2E0E; border-color: #D9804F; background: #FCEBE1; }}
.note {{ color: #4B5B65; font-size: 0.9rem; }}
.card {{ border: 1px solid #C9D6DD; border-radius: 6px; padding: 0.8rem 1rem; background: #FFFFFF; }}
.card.sel {{ border: 2px solid {PALETTE['tide']}; }}
.kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 0.6rem; }}
.kpi {{ background: #FFFFFF; border: 1px solid #D3DEE4; border-radius: 6px; padding: 0.6rem 0.8rem; }}
.kpi .v {{ font-family: 'Archivo', sans-serif; font-stretch: 87%; font-size: 1.55rem; font-weight: 600;
  color: {PALETTE['abyss']}; font-variant-numeric: tabular-nums; }}
.kpi .v .u {{ font-family: 'IBM Plex Sans', sans-serif; font-size: 0.85rem; font-weight: 500; color: #52626C;
  margin-left: 0.2rem; }}
.kpi .l {{ font-size: 0.82rem; color: #52626C; }}
.kpi.p {{ border-top: 3px solid {PALETTE['power']}; }}
.kpi.h {{ border-top: 3px solid {PALETTE['h2']}; }}
.kpi.s {{ border-top: 3px solid {PALETTE['store']}; }}
.kpi.n {{ border-top: 3px solid {PALETTE['tide']}; }}
.check-ok {{ color: #2F7D4F; }} .check-bad {{ color: {PALETTE['warn']}; }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; transition: none !important; }} }}
</style>
"""


def apply():
    st.markdown(CSS, unsafe_allow_html=True)


def kpis(items):
    """items: list of (label, value, kind) with kind in p|h|s|n."""
    html = '<div class="kpi-row">' + "".join(
        f'<div class="kpi {k}"><div class="v">{v}</div><div class="l">{l}</div></div>' for l, v, k in items) + "</div>"
    st.markdown(html, unsafe_allow_html=True)
