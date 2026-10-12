"""All user-editable inputs of the planner, with defaults, units and help text.

One flat dictionary holds every input. ``SPEC`` describes each entry for the
interface and the Excel workbook; ``derive`` turns the flat inputs into the
quantities the optimisation model uses (configuration, export technology,
compression work, nested storage/pipeline tables, ...).

Default values are the v9 techno-economic set (Step 2 validation). Entries
marked ``step3=True`` are placeholders that Step 3 replaces with referenced
values; the interface flags them.
"""
from __future__ import annotations

import copy
import math
import numpy as np
from dataclasses import dataclass, field


@dataclass
class P:
    key: str
    group: str
    label: str
    unit: str
    default: object
    kind: str = "float"            # float | int | bool | choice | text
    options: tuple = ()
    help: str = ""
    step3: bool = False
    advanced: bool = False
    min: float | None = None
    max: float | None = None
    source: str = ""               # where the default value comes from (shown in the app and the handbook)


SPEC: list[P] = [
    # ------------------------------------------------------------------ use case
    P("use_case", "Use case", "What the island supplies", "-", "Hybrid", "choice",
      ("Power-led", "Hydrogen-led", "Hybrid"),
      "Power-led: electricity to the grid, hydrogen only as internal storage. Hydrogen-led: hydrogen to an "
      "offtaker, electricity optional. Hybrid: both contracts."),
    P("annual_demand_mwh", "Use case", "Electricity to deliver per year", "MWh/yr", 200_000.0, min=0.0,
      help="Contracted electricity at the grid point. Ignored in merchant and CfD modes, where volume is free."),
    P("annual_h2_demand_kg", "Use case", "Hydrogen to deliver per year", "kg/yr", 2.0e6, min=0.0),
    P("elec_delivery", "Use case", "Electricity delivery profile", "-", "annual", "choice",
      ("annual", "firm", "profile"),
      "annual: only the yearly volume counts. firm: the same power every hour. profile: follow the hourly "
      "profile uploaded with the time series (column elec_demand_mw)."),
    P("h2_delivery", "Use case", "Hydrogen delivery profile", "-", "annual", "choice", ("annual", "firm", "profile"),
      "As for electricity; profile uses column h2_demand_kgh."),
    P("elec_revenue", "Use case", "Electricity revenue", "-", "ppa", "choice", ("ppa", "merchant", "cfd"),
      "ppa: fixed volume at the PPA price. merchant: every MWh sold at the hourly day-ahead price. cfd: two-sided "
      "contract for difference, strike price paid in hours with non-negative price (French offshore scheme)."),
    P("ppa_price_eur_mwh", "Use case", "PPA price", "EUR/MWh", 100.0, min=0.0),
    P("cfd_strike_eur_mwh", "Use case", "CfD strike price", "EUR/MWh", 86.45, min=0.0,
      help="Bretagne Sud 1 (Pennavel) award, 15 May 2024: EUR 86.45/MWh."),
    P("h2_price_eur_kg", "Use case", "Hydrogen sales price", "EUR/kg", 6.0, min=0.0),
    P("sell_surplus", "Use case", "Sell the other carrier as a by-product", "-", False, "bool",
      help="Power-led: sell hydrogen made from surplus power at the hydrogen price. Hydrogen-led: sell "
           "surplus electricity (merchant or CfD). Off: only the main product earns revenue."),
    P("grid_injection_cap_mw", "Use case", "Maximum grid injection", "MW", 100.0, min=0.0,
      help="Firm capacity of the grid connection."),
    # ------------------------------------------------------------------ site
    P("site_name", "Site", "Site name", "-", "My floating island", "text"),
    P("site_lat", "Site", "Island latitude", "deg", 47.38, min=-90.0, max=90.0),
    P("site_lon", "Site", "Island longitude", "deg", -3.55, min=-180.0, max=180.0),
    P("grid_name", "Site", "Grid connection point", "-", "Grid substation", "text"),
    P("grid_lat", "Site", "Grid point latitude", "deg", 47.64, min=-90.0, max=90.0),
    P("grid_lon", "Site", "Grid point longitude", "deg", -3.16, min=-180.0, max=180.0),
    P("h2_name", "Site", "Hydrogen offtake point", "-", "Hydrogen offtaker", "text"),
    P("h2_lat", "Site", "Hydrogen offtake latitude", "deg", 47.27, min=-90.0, max=90.0),
    P("h2_lon", "Site", "Hydrogen offtake longitude", "deg", -2.20, min=-180.0, max=180.0),
    P("route_method", "Site", "How route lengths are found", "-", "sea route", "choice",
      ("sea route", "straight line"),
      "sea route: shortest path through the sea on the bundled 1 km coastline (around islands and headlands) "
      "from the island to the coast nearest the onshore point, plus a straight onshore leg. straight line: "
      "great-circle distance x routing factor. An entered route length below always wins."),
    P("routing_factor", "Site", "Routing factor (route / straight line)", "-", 1.2, min=1.0, max=3.0,
      help="Used with the straight-line method. Cables and pipes rarely run straight; 1.1-1.3 is typical."),
    P("link_distance_override_km", "Site", "Export cable route length (0 = computed)", "km", 0.0, min=0.0,
      help="Routed length of the island's own cable to the grid point, from a cable route study if you have "
           "it; it replaces the computed length. A cable to a nearby hub is always measured from the map."),
    P("pipe_distance_override_km", "Site", "Pipeline route length (0 = computed)", "km", 0.0, min=0.0,
      help="Routed length of the island's own pipeline to the offtake point, if known. A spur to a pipeline "
           "tie-in is always measured from the map."),
    P("avg_water_depth_m", "Site", "Water depth at the island", "m", 75.0, min=0.0,
      help="Up to the fixed/floating threshold the island is bottom-fixed; deeper it floats."),
    P("fixed_floating_depth_m", "Site", "Fixed/floating threshold depth", "m", 60.0, min=0.0, advanced=True),
    P("decentralized_h2", "Site", "Turbine-level electrolysis (no power cable)", "-", False, "bool",
      help="Floating, decentralised concept (Dolphyn type): hydrogen made in each turbine, pipeline export only."),
    P("existing_pipeline_available", "Site", "Existing gas pipeline on the route can be repurposed", "-", False, "bool"),
    P("sea_area_km2", "Site", "Usable sea area", "km2", 38.0, min=0.0,
      help="Polygon available for turbines and floating PV."),
    P("wind_density_mw_km2", "Site", "Wind power density", "MW/km2", 6.3, min=0.1,
      help="Bretagne Sud: 250 MW on 40 km2 and 500 MW on 75 km2 (State brochure, 2026)."),
    P("pv_density_mw_km2", "Site", "Floating PV density", "MW/km2", 60.0, min=0.1, step3=True),
    P("deck_area_max_m2", "Site", "Island deck area available", "m2", 200_000.0, min=0.0,
      help="Area for electrolysers, compressors, fuel cells, batteries and tanks on the island."),
    P("area_onshore_max_m2", "Site", "Onshore plot area", "m2", 1_000_000.0, min=0.0),
    # ------------------------------------------------------------------ connections to existing infrastructure
    P("elec_connection", "Connections", "Electricity connection", "-", "direct", "choice",
      options=("direct", "hub", "choose"),
      help="Direct: own export cable to the onshore grid point. Hub: short cable to a nearby offshore substation "
           "or cable with spare capacity (its owner carries the power to shore for an access fee). Choose: the "
           "model sizes both and keeps the cheaper."),
    P("hub_name", "Connections", "Nearby offshore substation or cable", "-", "Nearby offshore substation", "text"),
    P("hub_lat", "Connections", "Hub latitude", "deg", 47.42, min=-90.0, max=90.0),
    P("hub_lon", "Connections", "Hub longitude", "deg", -3.45, min=-180.0, max=180.0),
    P("hub_spare_mw", "Connections", "Spare capacity at the hub", "MW", 100.0, min=0.0,
      help="Capacity the hub owner can offer; it caps the power the island can export through the hub."),
    P("hub_voltage_kv", "Connections", "Hub voltage", "kV", 225.0, min=1.0,
      help="AC voltage of the hub; sets the rating of the cable from the island."),
    P("hub_access_fee_eur_mw_yr", "Connections", "Hub access fee", "EUR/MW/yr", 42_000.0, min=0.0, step3=True,
      help="Annual charge per MW of connection for using the hub and its link to shore."),
    P("export_voltage", "Connections", "Export link", "-", "auto", "choice",
      options=("auto", "66 kV", "132 kV", "220 kV", "275 kV", "HVDC"),
      help="Auto: the model chooses AC or DC, the voltage, the conductor, the compensation, the number of circuits "
           "and the capacity. A fixed choice restricts it to that AC voltage or to HVDC."),
    P("h2_connection", "Connections", "Hydrogen connection", "-", "direct", "choice",
      options=("direct", "tiein", "choose"),
      help="Direct: own pipeline to the offtake point. Tie-in: short pipeline to a nearby pipeline with spare "
           "capacity. Choose: the model sizes both and keeps the cheaper."),
    P("tiein_name", "Connections", "Nearby pipeline tie-in point", "-", "Nearby pipeline", "text"),
    P("tiein_lat", "Connections", "Tie-in latitude", "deg", 47.45, min=-90.0, max=90.0),
    P("tiein_lon", "Connections", "Tie-in longitude", "deg", -3.30, min=-180.0, max=180.0),
    P("tiein_spare_kgh", "Connections", "Spare capacity in the pipeline", "kg/h", 20_000.0, min=0.0),
    P("tiein_pressure_bar", "Connections", "Pipeline operating pressure", "bar", 70.0, min=1.0,
      help="Pressure of the existing pipeline at the tie-in. Compressors deliver this pressure plus the spur's "
           "pressure-drop margin (Hydrogen pipeline tab)."),
    P("tiein_fee_eur", "Connections", "Tie-in cost (hot tap, metering)", "EUR", 5.0e6, min=0.0, step3=True),
    # ------------------------------------------------------------------ technology switches
    P("enable_pv", "Technologies", "Floating PV", "-", True, "bool"),
    P("enable_ez_off", "Technologies", "Electrolyser on the island", "-", True, "bool"),
    P("enable_ez_on", "Technologies", "Electrolyser onshore", "-", True, "bool"),
    P("enable_fc_off", "Technologies", "Fuel cell on the island", "-", True, "bool"),
    P("enable_fc_on", "Technologies", "Fuel cell onshore", "-", True, "bool"),
    P("enable_batt_off", "Technologies", "Battery on the island", "-", True, "bool"),
    P("enable_batt_on", "Technologies", "Battery onshore", "-", True, "bool"),
    P("enable_tank_off", "Technologies", "Hydrogen tank on the island", "-", True, "bool"),
    P("enable_tank_on", "Technologies", "Hydrogen tank onshore", "-", True, "bool"),
    P("enable_cable", "Technologies", "Electricity export cable", "-", True, "bool"),
    P("enable_pipe", "Technologies", "Hydrogen export pipeline", "-", True, "bool"),
    # ------------------------------------------------------------------ finance
    P("discount_rate", "Finance", "Discount rate (real WACC)", "fraction", 0.07, min=0.0, max=0.3),
    P("offshore_premium", "Finance", "Offshore cost premium on island equipment", "x", 1.10, min=1.0, step3=True),
    P("offshore_fom_adder", "Finance", "Extra fixed O&M for batteries and tanks on the island", "fraction/yr", 0.005,
      min=0.0, help="Added to the battery and tank fixed O&M on the island (v9: 2.5 % offshore, 2.0 % onshore)."),
    # ------------------------------------------------------------------ wind
    P("wind_capex_eur_mw", "Offshore wind", "CAPEX, bottom-fixed", "EUR/MW", 2_540_000.0, min=0.0, step3=True),
    P("wind_capex_floating_eur_mw", "Offshore wind", "CAPEX, floating", "EUR/MW", 3_429_000.0, min=0.0, step3=True,
      help="1.35 x the bottom-fixed CAPEX. Floating wind costs 1.33 x bottom-fixed in Lanni et al. (2025, Table 3), "
           "1.36 x in NREL's 2024 cost review and 1.56-1.70 x in the BVG Associates guides; test 3.30-4.32 MEUR/MW. "
           "The AAU workbook (v9) used 2.54 MEUR/MW for both.",
      source="1.35 x bottom-fixed: Lanni et al. 2025; NREL Cost of Wind Energy Review 2024; BVG Associates 2024"),
    P("wind_life", "Offshore wind", "Lifetime", "yr", 25, "int", min=1),
    P("wind_fom", "Offshore wind", "Fixed O&M, bottom-fixed", "fraction/yr", 0.025, min=0.0),
    P("wind_fom_floating", "Offshore wind", "Fixed O&M, floating", "fraction/yr", 0.03, min=0.0),
    P("turbine_mw", "Offshore wind", "Turbine rating (for the drawing)", "MW", 15.0, min=1.0, advanced=True),
    # ------------------------------------------------------------------ PV
    P("pv_capex_eur_kw", "Floating PV", "CAPEX", "EUR/kW", 1500.0, min=0.0, step3=True),
    P("pv_life", "Floating PV", "Lifetime", "yr", 25, "int", min=1),
    P("pv_fom", "Floating PV", "Fixed O&M", "fraction/yr", 0.02, min=0.0),
    # ------------------------------------------------------------------ electrolysis
    P("elec_capex_eur_kw", "Electrolysis", "CAPEX (stack + balance of plant)", "EUR/kW", 2000.0, min=0.0, step3=True),
    P("electrolyzer_efficiency", "Electrolysis", "Efficiency (LHV)", "fraction", 0.75, min=0.3, max=1.0),
    P("elec_life", "Electrolysis", "Lifetime (stack replacement)", "yr", 15, "int", min=1),
    P("elec_fom", "Electrolysis", "Fixed O&M", "fraction/yr", 0.015, min=0.0),
    P("area_elec_m2_mw", "Electrolysis", "Deck area", "m2/MW", 200.0, min=0.0, advanced=True),
    P("wt_capex_eur_mw", "Electrolysis", "Water treatment CAPEX", "EUR/MW", 20_750.0, min=0.0, advanced=True),
    P("wt_life", "Electrolysis", "Water treatment lifetime", "yr", 20, "int", advanced=True),
    P("wt_fom", "Electrolysis", "Water treatment O&M", "fraction/yr", 0.10, advanced=True),
    # ------------------------------------------------------------------ compression
    P("comp_p_in_bar", "Compression", "Inlet pressure", "bar", 30.0, min=1.0),
    P("comp_p_out_bar", "Compression", "Outlet pressure", "bar", 70.0, min=1.0),
    P("comp_isentropic_eff", "Compression", "Isentropic efficiency", "fraction", 0.75, min=0.3, max=1.0),
    P("comp_stages", "Compression", "Stages", "-", 2, "int", min=1, advanced=True),
    P("comp_inlet_temp_k", "Compression", "Inlet temperature", "K", 313.0, advanced=True),
    P("comp_z", "Compression", "Compressibility factor", "-", 1.05, advanced=True),
    P("comp_gamma", "Compression", "Heat capacity ratio of hydrogen", "-", 1.41, min=1.01, max=1.67,
      advanced=True),
    P("comp_capex_eur_mw", "Compression", "CAPEX", "EUR/MW", 5.08e6, min=0.0,
      source="ACER 2026 UIC median, compression stations 10-50 MW (gas and H2 blending), 5.08 MEUR/MW"),
    P("comp_life", "Compression", "Lifetime", "yr", 20, "int", min=1),
    P("comp_fom", "Compression", "Fixed O&M", "fraction/yr", 0.03, min=0.0),
    P("area_comp_m2_mw", "Compression", "Deck area", "m2/MW", 100.0, advanced=True),
    # ------------------------------------------------------------------ fuel cell
    P("fc_efficiency_lhv", "Fuel cell", "Efficiency (LHV)", "fraction", 0.50, min=0.1, max=1.0),
    P("fc_capex_eur_kw", "Fuel cell", "CAPEX", "EUR/kW", 1170.0, min=0.0),
    P("fc_life", "Fuel cell", "Lifetime", "yr", 15, "int", min=1),
    P("fc_fom", "Fuel cell", "Fixed O&M", "fraction/yr", 0.03, min=0.0),
    P("area_fc_m2_mw", "Fuel cell", "Deck area", "m2/MW", 120.0, advanced=True),
    # ------------------------------------------------------------------ batteries
    P("batt_capex_e_eur_mwh", "Battery", "Energy CAPEX", "EUR/MWh", 160_000.0, min=0.0),
    P("batt_capex_p_eur_mw", "Battery", "Power CAPEX", "EUR/MW", 100_000.0, min=0.0, step3=True,
      help="Power conversion system and grid interface. With 160 EUR/kWh for energy, a 4-hour system costs "
           "740 EUR/kW (185 EUR/kWh), slightly above BNEF's 2025 European turnkey average (177 USD/kWh).",
      source="Assumption checked against BNEF 2025 turnkey BESS prices (Europe 177 USD/kWh); the v9 value "
             "5.34 MEUR/MW made a 4-hour battery about nine times the market price"),
    P("batt_eta", "Battery", "Charge and discharge efficiency (each way)", "fraction", 0.95, min=0.5, max=1.0),
    P("batt_life", "Battery", "Lifetime", "yr", 15, "int", min=1),
    P("batt_fom", "Battery", "Fixed O&M", "fraction/yr", 0.02, min=0.0),
    P("batt_vom", "Battery", "Variable O&M", "EUR/MWh", 1.19, min=0.0),
    P("area_batt_m2_mwh", "Battery", "Deck area", "m2/MWh", 25.0, advanced=True),
    P("batt_max_mwh", "Battery", "Largest battery allowed, energy (each site)", "MWh", 1.0e5, min=0.0,
      advanced=True),
    P("batt_max_mw", "Battery", "Largest battery allowed, power (each site)", "MW", 2.0e4, min=0.0, advanced=True),
    # ------------------------------------------------------------------ tanks
    P("tank_capex_eur_kg", "Hydrogen tank", "CAPEX", "EUR/kg", 650.0, min=0.0),
    P("tank_life", "Hydrogen tank", "Lifetime", "yr", 20, "int", min=1),
    P("tank_fom", "Hydrogen tank", "Fixed O&M", "fraction/yr", 0.02, min=0.0),
    P("tank_vom", "Hydrogen tank", "Variable O&M", "EUR/kg", 0.01, min=0.0),
    P("area_tank_m2_kg", "Hydrogen tank", "Deck area", "m2/kg", 1.5, advanced=True),
    P("tank_max_kg", "Hydrogen tank", "Largest tank allowed (each site)", "kg", 5.0e6, min=0.0, advanced=True),
    # ------------------------------------------------------------------ export cable
    P("cable_cost_model", "Export cable", "Cable cost model", "-", "catalogue", "choice", ("catalogue", "v9 linear"),
      help="catalogue: every AC voltage and conductor size with reactors at both ends or also mid-route, and a "
           "VSC HVDC link; the model chooses the option, the circuits and the capacity exactly. v9 linear: the "
           "earlier project model (cost per MW, HVAC up to a distance limit), kept for comparison."),
    # AC cables
    P("ac_install_eur_km", "Export cable", "AC cable installation per circuit-km", "EUR/km", 910_000.0, min=0.0,
      help="Laying and burial of one AC circuit, added to the cable supply cost.",
      source="ENTSO-E installation 0.91 MEUR/km (reviewed in Hartel et al. 2017); with ORBIT supply it "
             "reproduces ACER 2026's AC submarine cable median 2.30 MEUR/km at 220 kV 1000 mm2"),
    P("ac_supply_factor", "Export cable", "AC cable supply cost factor", "x", 1.0, min=0.0, advanced=True,
      help="Multiplies the NREL ORBIT supply prices (sensitivity)."),
    P("usd_eur", "Export cable", "EUR per USD for ORBIT prices", "EUR/USD", 0.924, min=0.0, advanced=True,
      source="ECB reference rate, 2024 average 1.082 USD per EUR"),
    P("grid_power_factor", "Export cable", "Power factor at the grid connection", "-", 0.95, min=0.5, max=1.0,
      advanced=True, help="Reactive power the AC link must carry at full output (grid-code capability).",
      source="assumption (typical grid-code requirement)"),
    P("cable_loss_factor", "Export cable", "AC loss factor for screen and armour", "x", 1.5, min=1.0, advanced=True,
      help="Multiplies the conductor resistance for screen and armour losses.",
      source="Perez-Rua, Lumbreras, Ramos & Cutululis, Wind Energy 25 (2022)"),
    P("cable_tan_delta", "Export cable", "XLPE dielectric loss factor tan(delta)", "-", 0.001, min=0.0, advanced=True,
      source="IEC 60287-1-1 typical value for XLPE"),
    P("reactor_eur_mvar", "Export cable", "Shunt reactor cost per MVAr", "EUR/MVAr", 20_000.0, min=0.0,
      help="Charging power of each AC circuit is fully compensated by reactors at both ends (and mid-route).",
      source="10-30 kEUR/MVAr in the literature: ORBIT 10-14 kUSD/MVAr, Dicorato-type functions "
             "10.5-15.8 kEUR/MVAr, NSCOGI 2011 2.8-3.0 MEUR per 100 MVAr"),
    P("reactor_fixed_eur", "Export cable", "Shunt reactor fixed cost per site and circuit", "EUR", 1_000_000.0,
      min=0.0, source="0.8-1.2 MEUR fixed term of Dicorato-type functions, rounded up"),
    P("allow_midroute", "Export cable", "Allow a mid-route compensation platform", "-", True, "bool"),
    P("midroute_platform_eur", "Export cable", "Mid-route compensation platform", "EUR", 50_000_000.0, min=0.0,
      step3=True, help="Structure for a reactor halfway along an AC route (e.g. Hornsea One). No public cost "
                       "exists; test 12-80 MEUR.", source="assumption: small AC offshore platform (NSCOGI 2011 "
                       "300 MW AC platform about 32-48 MEUR in 2011, escalated)"),
    P("loss_value_eur_mwh", "Export cable", "Value of no-load cable losses", "EUR/MWh", 50.0, min=0.0,
      help="Charging-current and dielectric losses run all year whatever the load; they are costed at this price.",
      source="40-50 EUR/MWh as in Van Eeckhout et al. 2010, Elliott et al. 2016, Xiang et al. 2021"),
    P("cable_max_circuits", "Export cable", "Largest number of circuits or converter units", "-", 12, "int", min=1,
      advanced=True),
    # HVDC
    P("vh_np_eur_mw", "Export cable", "HVDC converter, per MW (each end)", "EUR/MW", 112_990.0, min=0.0,
      source="Vrana & Hartel, EPSR 160 (2018), Table 6"),
    P("vh_n0_eur", "Export cable", "HVDC converter, fixed per unit (each end)", "EUR", 23_500_000.0, min=0.0,
      source="Vrana & Hartel 2018, Table 6"),
    P("vh_sp_eur_mw", "Export cable", "HVDC offshore station, per MW", "EUR/MW", 723_420.0, min=0.0,
      source="Vrana & Hartel 2018, Table 6"),
    P("vh_s0_eur", "Export cable", "HVDC offshore station, fixed per unit", "EUR", 57_320_000.0, min=0.0,
      source="Vrana & Hartel 2018, Table 6"),
    P("vh_blp_eur_mw_km", "Export cable", "HVDC cable, per MW and km", "EUR/MW/km", 980.0, min=0.0,
      source="Vrana & Hartel 2018, Table 6"),
    P("vh_bl_eur_km", "Export cable", "HVDC cable, per km", "EUR/km", 270_000.0, min=0.0,
      source="Vrana & Hartel 2018, Table 6"),
    P("vh_b0_eur", "Export cable", "HVDC cable, fixed per unit", "EUR", 3_630_000.0, min=0.0,
      source="Vrana & Hartel 2018, Table 6"),
    P("hvdc_unit_mw", "Export cable", "Largest HVDC unit", "MW", 2000.0, min=1.0, advanced=True,
      source="Vrana & Hartel 2018 (2 GW); TenneT 2 GW standard"),
    P("hvdc_cost_factor", "Export cable", "HVDC cost escalation factor", "x", 1.0, min=0.0,
      help="Multiplies all HVDC costs. At 1.0 the converter stations and platform of a 2 GW link cost "
           "EUR 2.0 bn, within about 6 % of TenneT's 2 GW programme (about EUR 2.1 bn per system) and at the "
           "upper end of ENTSO-E ONDP 2024 converter costs.",
      source="checked against TenneT 2023 and ENTSO-E ONDP 2024"),
    P("hvdc_converter_loss", "Export cable", "HVDC converter losses (both stations)", "fraction", 0.02, min=0.0,
      source="1 % per station: PyPSA technology data; EVOLVE v9"),
    P("hvdc_cable_loss_per_100km", "Export cable", "HVDC cable loss per 100 km at full load", "fraction", 0.0045,
      min=0.0, advanced=True, source="2 I^2 R at rated current, ORBIT 320 kV/2000 mm2 (0.61 %) and 525 kV/2500 mm2 "
                                     "(0.30 %) at 70 C; mid value"),
    P("hvdc_float_premium", "Export cable", "Floating offshore-station premium (floating island)", "x", 1.5, min=1.0,
      step3=True, help="Multiplies the HVDC offshore-station cost when the island floats and makes its own power "
                       "(concept B)."),
    # grid fee, O&M
    P("tso_fee_eur_mw_yr", "Export cable", "TSO grid fee (per MW injected into the grid)", "EUR/MW/yr", 42_000.0, min=0.0, step3=True,
      help="Annual charge per MW of capacity injected into the existing grid (the largest hourly injection), "
           "paid only when the island connects to the grid with its own cable. Power used onshore by the "
           "electrolysers without entering the grid pays no fee. With a hub, the hub access fee replaces it."),
    P("cable_fom_hvac", "Export cable", "Fixed O&M, HVAC link", "fraction/yr", 0.005, min=0.0),
    P("cable_fom_hvdc", "Export cable", "Fixed O&M, HVDC link", "fraction/yr", 0.01, min=0.0),
    # v9 linear model (comparison)
    P("hvac_hvdc_threshold_km", "Export cable", "v9 linear model: HVAC up to", "km", 60.0, min=0.0, advanced=True),
    P("hvac_var_eur_mw_km", "Export cable", "v9 linear model: HVAC cost per MW per km", "EUR/MW/km", 1360.0,
      advanced=True),
    P("hvac_fix_eur_km", "Export cable", "v9 linear model: HVAC fixed cost per km", "EUR/km", 206_130.0, advanced=True),
    P("hvac_loss_per_km", "Export cable", "v9 linear model: HVAC loss per km", "fraction/km", 6.7e-5, advanced=True),
    P("hvdc_cable_eur_mw_km", "Export cable", "v9 linear model: HVDC cable per MW per km", "EUR/MW/km", 1000.0,
      advanced=True),
    P("hvdc_cable_loss_per_km", "Export cable", "v9 linear model: HVDC cable loss per km", "fraction/km", 3.5e-5,
      advanced=True),
    P("v9_converter_pair_eur_mw", "Export cable", "v9 linear model: HVDC converter pair", "EUR/MW", 300_000.0,
      advanced=True),
    P("tso_fee_hvdc_eur_mw_yr", "Export cable", "v9 linear model: TSO grid fee, HVDC", "EUR/MW/yr", 0.0, min=0.0,
      advanced=True),
    P("cable_life", "Export cable", "Lifetime", "yr", 30, "int", min=1),
    # ------------------------------------------------------------------ pipeline
    P("pipe_cost_fixed_eur_km", "Hydrogen pipeline", "New pipeline cost, fixed part", "EUR/km", 1_550_000.0, min=0.0,
      help="Cost per km of a new pipeline = fixed part + part per inch of diameter.",
      source="Line through ACER 2026 UIC medians of H2-ready gas pipelines: 2.08 MEUR/km at 12-16 in, 3.14 at 36-48 in"),
    P("pipe_cost_per_inch_eur_km", "Hydrogen pipeline", "New pipeline cost, per inch of diameter", "EUR/km/inch",
      37_857.0, min=0.0, source="Same ACER 2026 line (slope)"),
    P("pipe_repurposed_capex_eur_km", "Hydrogen pipeline", "Repurposed 36-inch: cost", "EUR/km", 1_180_000.0,
      min=0.0, source="ACER 2026 UIC median, hydrogen pipelines (all repurposed), 1.18 MEUR/km"),
    P("pipe_offshore_factor", "Hydrogen pipeline", "Subsea cost factor", "x", 1.7, min=0.1,
      help="Multiplies new and repurposed pipeline costs for the subsea route. ACER's indicators do not separate "
           "subsea from onshore pipelines; the European Hydrogen Backbone prices offshore pipelines at 1.7 times "
           "onshore.", source="European Hydrogen Backbone 2022 (offshore = 1.7 x onshore)"),
    P("pipe_p_out_bar", "Hydrogen pipeline", "Delivery pressure at the end of the pipeline", "bar", 30.0, min=1.0,
      help="Lowest pressure in the pipeline; the gas velocity limit is checked here.", source="assumption"),
    P("tiein_dp_bar", "Hydrogen pipeline", "Pressure drop allowed in a tie-in spur", "bar", 5.0, min=0.1,
      advanced=True, help="With a tie-in, compressors deliver the tie-in pressure plus this margin."),
    P("pipe_max_velocity_ms", "Hydrogen pipeline", "Design gas velocity", "m/s", 20.0, min=1.0,
      help="Largest gas velocity at the pipeline outlet. The erosional limit below is also respected.",
      source="Danish Energy Agency, Technology Brief on hydrogen transport (2025): capacities at 20 m/s"),
    P("pipe_velocity_fraction", "Hydrogen pipeline", "Gas velocity limit, share of erosional velocity", "fraction",
      0.5, min=0.05, max=1.0, advanced=True, source="Menon (2011), as used by Singlitico et al. (2021)"),
    P("pipe_erosional_c", "Hydrogen pipeline", "Erosional velocity constant (SI)", "(kg/m3)^0.5 m/s", 122.0,
      min=1.0, advanced=True, source="API RP 14E, c = 100 in US units"),
    P("pipe_roughness_mm", "Hydrogen pipeline", "Wall roughness", "mm", 0.05, min=0.0, advanced=True,
      source="Singlitico et al. (2021)"),
    P("pipe_gas_temp_k", "Hydrogen pipeline", "Gas temperature in the pipeline", "K", 288.0, min=200.0,
      advanced=True),
    P("pipe_id_4in", "Hydrogen pipeline", "4-inch: inner diameter", "m", 0.1023, min=0.01, advanced=True,
      source="ASME B36.10 outside diameter minus a typical wall"),
    P("pipe_id_6in", "Hydrogen pipeline", "6-inch: inner diameter", "m", 0.1541, min=0.01, advanced=True,
      source="ASME B36.10 outside diameter minus a typical wall"),
    P("pipe_id_8in", "Hydrogen pipeline", "8-inch: inner diameter", "m", 0.2027, min=0.01, advanced=True,
      source="ASME B36.10 outside diameter minus a typical wall"),
    P("pipe_id_12in", "Hydrogen pipeline", "12-inch: inner diameter", "m", 0.3049, min=0.01, advanced=True,
      source="ASME B36.10 outside diameter minus a typical wall"),
    P("pipe_id_16in", "Hydrogen pipeline", "16-inch: inner diameter", "m", 0.3842, min=0.01, advanced=True,
      source="ASME B36.10 outside diameter minus a typical wall"),
    P("pipe_id_20in", "Hydrogen pipeline", "20-inch: inner diameter", "m", 0.4826, min=0.01, advanced=True,
      source="ASME B36.10 outside diameter minus a typical wall"),
    P("pipe_id_24in", "Hydrogen pipeline", "24-inch: inner diameter", "m", 0.5814, min=0.01, advanced=True,
      source="ASME B36.10 outside diameter minus a typical wall"),
    P("pipe_id_36in", "Hydrogen pipeline", "36-inch: inner diameter", "m", 0.8758, min=0.01, advanced=True,
      source="ASME B36.10 outside diameter minus a typical wall"),
    P("pipeline_efficiency", "Hydrogen pipeline", "Delivery efficiency", "fraction", 0.99),
    P("pipeline_life", "Hydrogen pipeline", "Lifetime", "yr", 40, "int"),
    P("pipeline_fom", "Hydrogen pipeline", "Fixed O&M", "fraction/yr", 0.009),
    # ------------------------------------------------------------------ platform
    # Structure cost of the island platform (version 0.10). Core, on the DNV GL (2018) basis of a jacket in 30 m:
    #   C = k_esc k_inst [ f_E c_E S_cab + f_H c_H (S_ez + w_c S_cmp + w_f S_fc + w_b S_bat) ] + C_0
    # A bottom-fixed:  f = (1 - s) + s (d / d_ref)^alpha         (depth acts on the jacket share s only)
    # B floating:      f = (1 - s) u + s r                        (hull and moorings replace the jacket)
    # C turbine-level: no central platform; per-turbine integration f_C k_esc k_inst c_H S, in-field pipelines,
    #                  an electrolyser scale penalty and a credit for the array cables it does not need.
    P("platform_cable_coef", "Island platform", "Electrical platform structure, per MW of export capacity (c_E)",
      "kEUR/MW", 84.651, step3=True,
      help="Topside and jacket for the export electrical equipment, sized on export capacity, 30 m water. Not the "
           "cable itself. Close to DNV GL's HVDC converter-platform costs (77-89 kEUR/MW); price year 2018 assumed.",
      source="DNV GL 2018 (P2H IJmuiden Ver) via Bouma 2023, Eq. 3.3"),
    P("platform_elec_coef", "Island platform", "Process platform structure, per MW of island equipment (c_H)",
      "kEUR/MW", 139.281, step3=True,
      help="Topside and jacket for electrolysis, 30 m water, excluding the electrolysers themselves (priced under "
           "Electrolysis). Reproduces DNV GL's electrolysis-platform costs to 0.05 %; price year 2018 assumed.",
      source="DNV GL 2018 (P2H IJmuiden Ver) via Bouma 2023, Eq. 3.3"),
    P("platform_install_factor", "Island platform", "Installation, engineering and contingency factor (k_inst)",
      "x", 1.5, min=1.0,
      help="1.15 for installation (DNV GL: about 15 % of fabrication and supply) x 1.30 for engineering, owner's "
           "cost and contingency (stated assumption, after Ekhar 2021). Test 1.15-1.6.",
      source="Bouma 2023 (value); DNV GL 2018 and Ekhar 2021 (decomposition, stated)"),
    P("platform_escalation", "Island platform", "Price escalation of the platform coefficients (k_esc)", "x", 1.0,
      min=0.0, help="Multiplies c_E and c_H to bring 2018 EUR to the model's price year. 1.0 keeps 2018 prices.",
      source="Assumption: 2018 EUR basis kept"),
    P("platform_fixed_eur", "Island platform", "Fixed platform cost (C_0)", "EUR", 0.0, min=0.0, advanced=True,
      help="Cost of a platform independent of its size; matters for islands below about 100 MW. Added as a "
           "constant to the platform of configurations A and B (0 = off).",
      source="Assumption (ORBIT: 285 t of fixed topside mass)"),
    P("platform_w_comp", "Island platform", "Weight of compressor MW on the process platform", "-", 1.0, min=0.0,
      advanced=True, help="Bouma's coefficient covers electrolyser MW only; 1 counts compressors like "
                          "electrolysers, 0 leaves them out. Test 0-1.", source="Assumption"),
    P("platform_w_fc", "Island platform", "Weight of fuel-cell MW on the process platform", "-", 1.0, min=0.0,
      advanced=True, help="As for compressors. Test 0-1.", source="Assumption"),
    P("platform_w_bat", "Island platform", "Weight of battery MW on the process platform", "-", 1.0, min=0.0,
      advanced=True, help="As for compressors. Test 0-1.", source="Assumption"),
    P("platform_ref_depth_m", "Island platform", "Reference depth of the coefficients", "m", 30.0, min=1.0,
      advanced=True, source="DNV GL 2018: jacket in 30 m"),
    P("platform_jacket_share_h", "Island platform", "Jacket share of the process platform (s_H)", "fraction", 0.28,
      min=0.0, max=1.0, source="DNV GL 2018 electrolysis-platform tables (0.27-0.28)"),
    P("platform_jacket_share_e", "Island platform", "Jacket share of the electrical platform (s_E)", "fraction", 0.22,
      min=0.0, max=1.0, source="DNV GL 2018 HVDC-platform tables"),
    P("platform_depth_exponent", "Island platform", "Jacket cost exponent on depth (alpha)", "-", 1.0, min=0.0,
      help="Bottom-fixed: the jacket share scales with (depth / reference depth)^alpha. 1.0 from Ekhar's jacket "
           "mass per metre of depth; 1.56 from BVG's substation foundation at 50 and 100 m.",
      source="Ekhar 2021 (1.0); BVG Associates 2024 guides (1.56)"),
    P("platform_float_topside_uplift", "Island platform", "Floating: topside uplift (u)", "x", 1.1, min=1.0,
      help="Motion-tolerant topside on a floating hull (Dolphyn barge trial: output varying with motion, sloshing). "
           "Test 1.0-1.2.", source="Assumption, after DESNZ 2024 (ERM Dolphyn)"),
    P("platform_float_hull_ratio", "Island platform", "Floating: hull and moorings vs jacket (r)", "x", 3.0, min=1.0,
      help="Cost of the floating hull with moorings relative to the jacket it replaces. BVG: semi-submersible with "
           "moorings 3.9 x a monopile; Myhr et al.: manufacturing factor 2.0. Test 2.0-3.9. Resulting floating "
           "factor about 1.6 (process) and 1.5 (electrical) instead of the earlier 2.0, for which no source exists.",
      source="BVG Associates 2024 guides; Myhr et al. (via Frontiers 2026 review)"),
    P("platform_life", "Island platform", "Lifetime", "yr", 25, "int"),
    P("platform_fom", "Island platform", "Fixed O&M, bottom-fixed and turbine-level", "fraction/yr", 0.02,
      source="Bouma 2023"),
    P("platform_fom_floating", "Island platform", "Fixed O&M, floating central platform", "fraction/yr", 0.03,
      min=0.0, help="Floating hubs need more inspection and are manned more often; published values span 1-7 %/yr.",
      source="Assumption within Travaglini et al. 2025 (1 %), Bouma 2023 (2 %), Lanni et al. 2025 (7 %)"),
    P("dyn_cable_km", "Island platform", "Floating: dynamic section of each export circuit", "km", 0.5, min=0.0,
      help="Length of the export cable between the floating platform and the seabed (lazy wave), priced with the "
           "dynamic premium. A few times the water depth.", source="Assumption"),
    P("dyn_cable_premium", "Island platform", "Floating: dynamic cable premium", "fraction", 0.75, min=0.0,
      help="Extra cost per km of dynamic over static cable: +30-50 % up to 33 kV, +60-90 % up to 66 kV "
           "(Collin et al., cited by Ibrahim et al. 2022). No data above 66 kV.",
      source="Collin et al. via Ibrahim et al. 2022"),
    P("dyn_cable_max_kv", "Island platform", "Floating: highest qualified dynamic export voltage", "kV", 66.0,
      min=0.0, help="Dynamic export cables are commercially qualified up to 66 kV (DNV 2021; BVG 2024). A floating "
                    "central platform with a higher export voltage is reported as a warning, or excluded if the "
                    "next input is on.", source="DNV 2021; BVG Associates 2024"),
    P("dyn_cable_restrict", "Island platform", "Floating: allow only qualified dynamic voltages", "-", False, "bool",
      help="On: AC options above the qualified dynamic voltage are not offered to a floating central platform."),
    # turbine-level electrolysis (configuration C)
    P("turbine_integration_factor", "Island platform", "Turbine-level: integration factor (f_C)", "-", 0.5, min=0.0,
      help="Cost of enlarging each turbine floater for its electrolyser, desalination, buffer and standby power, as "
           "a share of the process-platform cost per MW (f_C x k_esc x k_inst x c_H). No published value exists: "
           "0 in Lanni et al. 2025 and Travaglini et al. 2025, 1 in the earlier model. Test 0-1.",
      source="Assumption bracketed by Lanni et al. 2025 (0) and EVOLVE 0.9 (1)"),
    P("turbine_ez_scale_factor", "Island platform", "Turbine-level: electrolyser scale penalty (k_scale)", "x", 1.3,
      min=1.0, help="Electrolysers of one turbine's size cost more per kW than a central plant: 1.30 (Singlitico et "
                    "al. 2021, 15 MW against 100 MW and more), 1.24 (DNV GL 2018 balance-of-plant scaling), 3-4 "
                    "(Travaglini et al. 2025). Test 1.0-3.7.",
      source="Singlitico et al. 2021; DNV GL 2018 with Ekhar 2021"),
    P("infield_pipe_eur_km", "Island platform", "Turbine-level: in-field hydrogen pipeline", "EUR/km", 550_000.0,
      min=0.0, help="Small-diameter flowlines from each turbine to the export pipeline. 0.2-0.9 MEUR/km.",
      source="Travaglini et al. 2025 (2030+)"),
    P("infield_km_per_turbine", "Island platform", "Turbine-level: in-field pipeline per turbine", "km", 1.0,
      min=0.0, help="About the turbine spacing (Dolphyn layout: about 1 km).", source="ERM 2019 (Dolphyn)"),
    P("infield_pipe_fom", "Island platform", "Turbine-level: in-field pipeline O&M", "fraction/yr", 0.005, min=0.0,
      source="Travaglini et al. 2025"),
    P("infield_manifold_eur", "Island platform", "Turbine-level: collection manifold", "EUR", 50_000.0, min=0.0,
      advanced=True, help="Hub joining the in-field lines to the export pipeline; probably low.",
      source="Lanni et al. 2025"),
    P("array_cable_credit_eur_mw", "Island platform", "Turbine-level: array cables not needed", "EUR/MW", 145_000.0,
      min=0.0, help="Turbine-level electrolysis needs no electrical array cables. The floating wind CAPEX includes "
                    "them (Lanni et al. 2025: 0.145 MEUR/MW floating, 0.053 bottom-fixed), so they are deducted.",
      source="Lanni et al. 2025, Table 3"),
    P("turbine_ez_eff_gain", "Island platform", "Turbine-level: avoided electrical losses", "fraction", 0.005,
      min=0.0, help="Extra hydrogen per MWh because the array and AC/DC chain losses are avoided (0.5 % intra-array "
                    "loss in Lanni et al. 2025). Test 0-1 %.", source="Lanni et al. 2025"),
    # ------------------------------------------------------------------ penalties
    P("shortfall_penalty_eur_mwh", "Solver", "Penalty for undelivered electricity", "EUR/MWh", 3000.0, advanced=True),
    P("shortfall_penalty_eur_kg", "Solver", "Penalty for undelivered hydrogen", "EUR/kg", 100.0, advanced=True),
    P("lhv_h2_kwh_kg", "Solver", "Hydrogen LHV", "kWh/kg", 33.3, advanced=True),
    P("cap_ub_mw", "Solver", "Upper bound on any converter or cable capacity", "MW", 5000.0, advanced=True),
    P("cap_renewable_ub_mw", "Solver", "Upper bound on wind and PV capacity", "MW", 10_000.0, advanced=True,
      help="The usable sea area and power densities normally limit wind and PV first."),
]

V9_SRC = "EVOLVE v9 model (OffShore-Onshore_Setting.py)"
_SOURCES = {
    # values carried over from the v9 model; ACER 2026 has no indicator for these technologies
    **{k: V9_SRC for k in (
        "discount_rate", "offshore_premium", "wind_capex_eur_mw", "wind_life", "wind_fom", "wind_fom_floating",
        "pv_capex_eur_kw", "pv_life", "pv_fom", "elec_capex_eur_kw", "electrolyzer_efficiency", "elec_life",
        "elec_fom", "area_elec_m2_mw", "wt_capex_eur_mw", "wt_life", "wt_fom", "comp_p_in_bar", "comp_p_out_bar",
        "comp_isentropic_eff", "comp_stages", "comp_inlet_temp_k", "comp_z", "comp_life", "comp_fom",
        "area_comp_m2_mw", "fc_efficiency_lhv", "fc_capex_eur_kw", "fc_life", "fc_fom", "area_fc_m2_mw",
        "batt_capex_e_eur_mwh", "batt_capex_p_eur_mw", "batt_eta", "batt_life", "batt_fom", "batt_vom",
        "area_batt_m2_mwh", "batt_max_mwh", "batt_max_mw", "tank_capex_eur_kg", "tank_life", "tank_fom", "tank_vom",
        "area_tank_m2_kg", "tank_max_kg", "cable_fom_hvac", "cable_fom_hvdc", "hvdc_float_premium", "cable_life",
        "tso_fee_eur_mw_yr", "hvac_hvdc_threshold_km", "hvac_var_eur_mw_km", "hvac_fix_eur_km", "hvac_loss_per_km",
        "hvdc_cable_eur_mw_km", "hvdc_cable_loss_per_km", "v9_converter_pair_eur_mw", "tso_fee_hvdc_eur_mw_yr",
        "pipeline_efficiency", "pipeline_life", "pipeline_fom", "platform_life",
        "shortfall_penalty_eur_mwh", "shortfall_penalty_eur_kg", "lhv_h2_kwh_kg", "cap_ub_mw", "cap_renewable_ub_mw",
        "fixed_floating_depth_m", "deck_area_max_m2", "area_onshore_max_m2", "hub_access_fee_eur_mw_yr")},
    "offshore_fom_adder": "v9: island batteries and tanks 2.5 % against 2.0 % onshore",
    "turbine_mw": "IEA 15 MW reference turbine (Gaertner et al. 2020); drawings only",
    "pv_density_mw_km2": "Assumption (floating PV at about 60 MW/km2)",
    "wind_density_mw_km2": "Belle-Ile site data (EVOLVE)",
    "tiein_fee_eur": "Assumption (hot tap and metering station); no ACER indicator",
    "tiein_dp_bar": "Assumption: margin above the host pipeline pressure",
    "pipe_gas_temp_k": "Assumption: seabed gas temperature",
    "pipe_offshore_factor": "European Hydrogen Backbone 2022 (offshore = 1.7 x onshore)",
    "comp_gamma": "Hydrogen heat capacity ratio (v9 used 1.41)",
    "cable_max_circuits": "Model limit",
    "cable_cost_model": "catalogue: this handbook, chapter Cost model; v9 linear: EVOLVE v9 model",
}
for _s in SPEC:
    if not _s.source and _s.key in _SOURCES:
        _s.source = _SOURCES[_s.key]
BY_KEY = {s.key: s for s in SPEC}
GROUP_ORDER = []
for s in SPEC:
    if s.group not in GROUP_ORDER:
        GROUP_ORDER.append(s.group)


def defaults() -> dict:
    return {s.key: copy.deepcopy(s.default) for s in SPEC}


def platform_factors(p: dict, floating: bool) -> dict:
    """Configuration factors f_E, f_H of the island platform (version 0.10) and its fixed O&M.

    Bottom-fixed: depth acts on the jacket share only, f = (1 - s) + s (d / d_ref)^alpha.
    Floating central platform: the jacket is replaced by a hull with moorings, f = (1 - s) u + s r.
    Turbine-level electrolysis has no central platform; its costs are set in the model (factor 0 here)."""
    sH, sE = p["platform_jacket_share_h"], p["platform_jacket_share_e"]
    if not floating:
        x = (max(p["avg_water_depth_m"], 0.0) / p["platform_ref_depth_m"]) ** p["platform_depth_exponent"]
        fH, fE, fom = (1 - sH) + sH * x, (1 - sE) + sE * x, p["platform_fom"]
    elif not p["decentralized_h2"]:
        u, r = p["platform_float_topside_uplift"], p["platform_float_hull_ratio"]
        fH, fE, fom = (1 - sH) * u + sH * r, (1 - sE) * u + sE * r, p["platform_fom_floating"]
    else:
        fH, fE, fom = 0.0, 0.0, p["platform_fom"]
    return {"platform_factor_h": fH, "platform_factor_e": fE, "platform_fom_used": fom}


def crf(r: float, n: float) -> float:
    return r * (1 + r) ** n / ((1 + r) ** n - 1) if r > 0 else 1.0 / n


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def route_length(p: dict, a, b, override_km=0.0, sea=False) -> tuple[float, str]:
    """Route length from a to b and how it was found.

    Entered length > sea route on the coastline (to the coast nearest b, then straight onshore; for an
    offshore end point such as a hub, `sea` keeps the whole route at sea) > straight line x routing factor."""
    if override_km and override_km > 0:
        return float(override_km), "entered"
    straight = haversine_km(a[0], a[1], b[0], b[1])
    if p.get("route_method", "sea route") == "sea route" and straight > 0.5:
        try:
            from . import geo
            km = geo.sea_km(a[0], a[1], b[0], b[1]) if sea else geo.route_km(a[0], a[1], b[0], b[1])[0]
            if km and math.isfinite(km):
                return float(max(km, straight)), "sea route"
        except Exception:      # no coastline file or an odd window: fall back to the straight line
            pass
    return straight * p["routing_factor"], "straight line x factor"


def apply_profiles(user: dict, series: dict | None) -> dict:
    """With profile delivery, the uploaded hourly profile is the contract: its sum replaces the annual volume
    (electricity in MWh from elec_demand_mw, hydrogen in kg from h2_demand_kgh)."""
    u = dict(user)
    series = series or {}
    e, h = series.get("elec_demand"), series.get("h2_demand")
    if u.get("elec_delivery") == "profile" and e is not None and len(e) == 8760:
        u["annual_demand_mwh"] = float(np.nansum(e))
    if u.get("h2_delivery") == "profile" and h is not None and len(h) == 8760:
        u["annual_h2_demand_kg"] = float(np.nansum(h))
    return u


def derive(user: dict, elec=None, h2=None) -> dict:
    """Flat user inputs -> everything the model needs. `elec`/`h2` force a connection option."""
    p = defaults()
    p.update({k: v for k, v in user.items() if v is not None})
    if elec:
        p["elec_connection"] = elec
    if h2:
        p["h2_connection"] = h2
    d = dict(p)
    # use case
    if p["use_case"] == "Power-led":
        d["annual_h2_demand_kg"] = 0.0
        if not p.get("sell_surplus", False):
            d["h2_price_eur_kg"] = 0.0
        if p["h2_delivery"] == "profile":
            d["h2_delivery"] = "annual"
    elif p["use_case"] == "Hydrogen-led":
        d["annual_demand_mwh"] = 0.0
        if p["elec_delivery"] == "profile":
            d["elec_delivery"] = "annual"
        if p["elec_revenue"] == "ppa" or not p.get("sell_surplus", False):
            d["elec_revenue"] = "none"
    # distances
    site = (p["site_lat"], p["site_lon"])
    d["straight_grid_km"] = haversine_km(*site, p["grid_lat"], p["grid_lon"])
    d["grid_distance_km"], d["grid_route_how"] = route_length(p, site, (p["grid_lat"], p["grid_lon"]),
                                                              p["link_distance_override_km"])
    d["h2_distance_km"], d["h2_route_how"] = route_length(p, site, (p["h2_lat"], p["h2_lon"]),
                                                          p["pipe_distance_override_km"])
    d["link_distance_km"] = d["grid_distance_km"]
    # configuration (v9 rule)
    floating = p["avg_water_depth_m"] > p["fixed_floating_depth_m"]
    d.update(platform_factors(p, floating))
    if not floating:
        d.update(config="A_fixed", hvdc_float_premium=1.0, elec_export_allowed=True)
    elif not p["decentralized_h2"]:
        d.update(config="B_floating_centralized", hvdc_float_premium=p["hvdc_float_premium"], elec_export_allowed=True)
    else:
        d.update(config="C_floating_decentralized", hvdc_float_premium=1.0, elec_export_allowed=False)
    d["turbine_level"] = d["config"] == "C_floating_decentralized"
    d["floating"] = floating
    if floating:
        d["wind_capex_eur_mw"] = p["wind_capex_floating_eur_mw"]
        d["wind_fom"] = p["wind_fom_floating"]
    if not p["enable_cable"]:
        d["elec_export_allowed"] = False
    # conversion constants
    d["h2_kg_per_mwh"] = 1000.0 * p["electrolyzer_efficiency"] / p["lhv_h2_kwh_kg"]
    d["fc_mwh_per_kg"] = p["fc_efficiency_lhv"] * p["lhv_h2_kwh_kg"] / 1000.0
    k, n = float(p["comp_gamma"]), int(p["comp_stages"])
    ratio = (p["comp_p_out_bar"] / p["comp_p_in_bar"]) ** ((k - 1.0) / (n * k))
    w = (p["comp_z"] * 8.314 * p["comp_inlet_temp_k"] / (p["comp_isentropic_eff"] * 2.016e-3)
         * n * (k / (k - 1.0)) * (ratio - 1.0))
    d["comp_mwh_per_kg"] = max(w, 0.0) / 3.6e6 / 1000.0
    # export link: direct to shore or to a nearby hub; candidate cable classes (voltage, AC/DC)
    ec = p.get("elec_connection", "direct")
    ec = "direct" if ec == "choose" else ec
    d["elec_connection_used"] = ec
    # TSO fee: charged per MW of capacity injected into the existing grid, by the island's cable or by an
    # onshore fuel cell (with a hub, its access fee on the cable replaces it)
    d["tso_grid_fee"] = p["tso_fee_eur_mw_yr"] if ec == "direct" else 0.0
    if ec == "hub":
        km, how = route_length(p, site, (p["hub_lat"], p["hub_lon"]), 0.0, sea=True)
        d["grid_distance_km"] = d["link_distance_km"] = km
        d["grid_route_how"] = how
        d["grid_injection_cap_mw"] = min(p["grid_injection_cap_mw"], p["hub_spare_mw"])
    from . import cables
    d["cable_options"] = d["cable_classes"] = cables.options(p, d, ec)
    d["cable_mode"] = p.get("cable_cost_model", "catalogue")
    opts = d["cable_options"]
    techs = sorted({c["tech"] for c in opts})
    d["export_voltage_used"] = ("none" if not opts else opts[0]["name"] if len(opts) == 1 else
                                f"chosen by the model ({len(opts)} options: " + " and ".join(techs) + ")")
    # a preview before a run: the option cheapest for the grid injection limit (losses not counted)
    if opts:
        pmw = max(min(d.get("grid_injection_cap_mw", p["grid_injection_cap_mw"]), 5000.0), 1.0)
        prev = min(opts, key=lambda c: c["annual"](pmw))
        d["cable_preview"] = prev["name"] if prev["tech"] == "AC" else cables.dc_voltage_label(pmw)
        d["cable_preview_index"] = opts.index(prev)
        d["link_mode"] = "HVDC" if prev["tech"] == "DC" else "HVAC"
        n = max(math.ceil(pmw / prev["rating"] - 1e-9), 1)
        d["circuit_rating_mw"] = prev["rating"] if prev["tech"] == "AC" else pmw
        d["cable_eff"] = prev["eff"] * (1.0 - prev["rho"] * pmw / (prev["rating"] * n if prev["cap_from_n"] else pmw))
        d["cable_capex_eur_mw"] = (prev["inv_circuit"] * n + prev["fixed_once"] + prev["inv_mw"] * pmw) / pmw
        d["cable_fom"] = prev["fom"]
        d["tso_fee"] = prev["fee"] if ec == "hub" else d["tso_grid_fee"]
    else:
        d.update(cable_preview="none", link_mode="HVAC", circuit_rating_mw=float("nan"), cable_eff=1.0,
                 cable_capex_eur_mw=0.0, cable_fom=0.0, tso_fee=0.0)
    # nested tables used by the model
    op = p["offshore_premium"]
    big_e, big_p, big_kg = p["batt_max_mwh"], p["batt_max_mw"], p["tank_max_kg"]
    d["batt"] = {
        "on": {"capex_e": p["batt_capex_e_eur_mwh"], "capex_p": p["batt_capex_p_eur_mw"], "life": p["batt_life"],
               "max_e": big_e if p["enable_batt_on"] else 0.0, "max_p": big_p if p["enable_batt_on"] else 0.0,
               "eta_ch": p["batt_eta"], "eta_dis": p["batt_eta"], "lam": 0.0, "fom": p["batt_fom"],
               "vom": p["batt_vom"]},
        "off": {"capex_e": p["batt_capex_e_eur_mwh"] * op, "capex_p": p["batt_capex_p_eur_mw"] * op,
                "life": p["batt_life"], "max_e": big_e if p["enable_batt_off"] else 0.0,
                "max_p": big_p if p["enable_batt_off"] else 0.0, "eta_ch": p["batt_eta"],
                "eta_dis": p["batt_eta"], "lam": 0.0, "fom": p["batt_fom"] + p["offshore_fom_adder"], "vom": p["batt_vom"]},
    }
    d["tank"] = {
        "on": {"capex_kg": p["tank_capex_eur_kg"], "life": p["tank_life"], "fom": p["tank_fom"], "lam": 0.0,
               "max_kg": big_kg if p["enable_tank_on"] else 0.0, "vom": p["tank_vom"]},
        "off": {"capex_kg": p["tank_capex_eur_kg"] * op, "life": p["tank_life"], "fom": p["tank_fom"] + p["offshore_fom_adder"],
                "lam": 0.0, "max_kg": big_kg if p["enable_tank_off"] else 0.0, "vom": p["tank_vom"]},
    }
    hc = p.get("h2_connection", "direct")
    hc = "direct" if hc == "choose" else hc
    d["h2_connection_used"] = hc
    if hc == "tiein":
        d["pipe_distance_km"], d["pipe_route_how"] = route_length(
            p, site, (p["tiein_lat"], p["tiein_lon"]), 0.0, sea=True)
        d["pipe_spare_kgh"] = p["tiein_spare_kgh"]
        d["pipe_fixed_eur"] = p["tiein_fee_eur"]
        d["pipe_p_in_bar"] = p["tiein_pressure_bar"] + p["tiein_dp_bar"]
        d["pipe_p_end_bar"] = p["tiein_pressure_bar"]
        ratio_t = (d["pipe_p_in_bar"] / p["comp_p_in_bar"]) ** ((k - 1.0) / (n * k))
        w_t = (p["comp_z"] * 8.314 * p["comp_inlet_temp_k"] / (p["comp_isentropic_eff"] * 2.016e-3)
               * n * (k / (k - 1.0)) * (ratio_t - 1.0))
        d["comp_mwh_per_kg"] = max(w_t, 0.0) / 3.6e6 / 1000.0
    else:
        d["pipe_distance_km"] = d["h2_distance_km"]
        d["pipe_route_how"] = d["h2_route_how"]
        d["pipe_spare_kgh"] = 0.0
        d["pipe_fixed_eur"] = 0.0
        d["pipe_p_in_bar"] = p["comp_p_out_bar"]
        d["pipe_p_end_bar"] = min(p["pipe_p_out_bar"], p["comp_p_out_bar"])
    if d["turbine_level"]:
        d["pipe_fixed_eur"] += p["infield_manifold_eur"]
    classes = pipe_classes(p, d["pipe_distance_km"], d["pipe_p_in_bar"], d["pipe_p_end_bar"])
    d["pipe_classes"] = classes
    d["pipe_allowed"] = [] if not p["enable_pipe"] else [
        kk for kk, c in classes.items() if not c.get("repurposed") or p["existing_pipeline_available"]]
    return d


PIPE_SIZES = [4, 6, 8, 12, 16, 20, 24, 36]


def pipe_capacity_kgh(d_inner_m: float, length_km: float, p_in_bar: float, p_out_bar: float, temp_k: float,
                      z: float, roughness_mm: float, velocity_fraction: float, erosional_c: float,
                      max_velocity: float = 20.0) -> dict:
    """Hydrogen a pipe can carry: the lower of a gas-velocity limit at the outlet and a pressure-drop limit.

    velocity: u <= f * C / sqrt(rho_out) (erosional velocity, API RP 14E), m = u * rho_out * A;
    pressure drop: isothermal flow, p_in^2 - p_out^2 = lambda * L / D * (Z R T / M) * (m / A)^2,
    lambda from the fully rough Colebrook limit 1/sqrt(lambda) = -2 log10(eps / (3.7 D))."""
    M, R = 2.016e-3, 8.314
    A = math.pi * d_inner_m ** 2 / 4.0
    rho_out = p_out_bar * 1e5 * M / (z * R * temp_k)
    u = min(velocity_fraction * erosional_c / math.sqrt(rho_out), max_velocity)
    m_vel = u * rho_out * A
    eps = max(roughness_mm, 1e-6) / 1000.0
    lam = (2.0 * math.log10(3.7 * d_inner_m / eps)) ** -2
    dp2 = max((p_in_bar * 1e5) ** 2 - (p_out_bar * 1e5) ** 2, 0.0)
    L = max(length_km, 0.1) * 1000.0
    m_dp = A * math.sqrt(dp2 * d_inner_m * M / (lam * L * z * R * temp_k))
    return {"cap_kgh": 3600.0 * min(m_vel, m_dp), "vel_kgh": 3600.0 * m_vel, "dp_kgh": 3600.0 * m_dp,
            "limit": "velocity" if m_vel <= m_dp else "pressure drop", "u_ms": u, "lambda": lam}


def pipe_classes(p: dict, length_km: float, p_in_bar: float, p_out_bar: float) -> dict:
    """Pipeline classes with cost per km and capacity for this route and these pressures."""
    out = {}
    f = p["pipe_offshore_factor"]
    for d_in in PIPE_SIZES:
        cap = pipe_capacity_kgh(p[f"pipe_id_{d_in}in"], length_km, p_in_bar, p_out_bar, p["pipe_gas_temp_k"],
                                p["comp_z"], p["pipe_roughness_mm"], p["pipe_velocity_fraction"], p["pipe_erosional_c"],
                                p["pipe_max_velocity_ms"])
        out[f"new_{d_in}in"] = {"capex_per_km": f * (p["pipe_cost_fixed_eur_km"] + p["pipe_cost_per_inch_eur_km"] * d_in),
                                "cap_kgh": cap["cap_kgh"], "inch": d_in, "limit": cap["limit"]}
    cap = pipe_capacity_kgh(p["pipe_id_36in"], length_km, p_in_bar, p_out_bar, p["pipe_gas_temp_k"], p["comp_z"],
                            p["pipe_roughness_mm"], p["pipe_velocity_fraction"], p["pipe_erosional_c"],
                            p["pipe_max_velocity_ms"])
    out["repurposed_36in"] = {"capex_per_km": f * p["pipe_repurposed_capex_eur_km"], "cap_kgh": cap["cap_kgh"],
                              "inch": 36, "limit": cap["limit"], "repurposed": True}
    return out


def connection_variants(user: dict) -> list[tuple[str, str]]:
    """The (electricity, hydrogen) connection options the model should compare."""
    p = defaults()
    p.update({k: v for k, v in user.items() if v is not None})
    ev = ["direct", "hub"] if (p.get("elec_connection") == "choose" and p["enable_cable"]) else [
        "direct" if p.get("elec_connection") == "choose" else p.get("elec_connection", "direct")]
    hv = ["direct", "tiein"] if (p.get("h2_connection") == "choose" and p["enable_pipe"]) else [
        "direct" if p.get("h2_connection") == "choose" else p.get("h2_connection", "direct")]
    return [(e, h) for e in ev for h in hv]
