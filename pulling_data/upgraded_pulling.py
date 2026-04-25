import math
import requests
import numpy as np
import pandas as pd
import pyeto.fao as fao
import getpass

from datetime import datetime, timedelta, date

from sentinelhub import (
    SHConfig, BBox, CRS, DataCollection,
    SentinelHubRequest, MimeType, bbox_to_dimensions
)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

# NOT LOGGED-IN
# config = SHConfig()
# config.sh_client_id = getpass.getpass("Enter your SentinelHub client id")
# config.sh_client_secret = getpass.getpass("Enter your SentinelHub client secret")
# config.sh_token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
# config.sh_base_url = "https://sh.dataspace.copernicus.eu"
# config.save("cdse")

# ALREADY LOGGED-IN
config = SHConfig()

SENTINEL1_CDSE = DataCollection.SENTINEL1_IW.define_from(
    "SENTINEL1_IW_CDSE",
    service_url="https://sh.dataspace.copernicus.eu"
)

SENTINEL2_CDSE = DataCollection.SENTINEL2_L2A.define_from(
    "SENTINEL2_L2A_CDSE",
    service_url="https://sh.dataspace.copernicus.eu"
)

SENTINEL3_CDSE = DataCollection.SENTINEL3_SLSTR.define_from(
    "SENTINEL3_SLSTR_CDSE",
    service_url="https://sh.dataspace.copernicus.eu"
)

# ─────────────────────────────────────────────
# CUSTOM INPUT AREA + DATE
# ─────────────────────────────────────────────

west  = 21.705
south = 42.118
east  = 21.715
north = 42.126

date_target = None   # None = today, or "2026-04-24"

# ── CROP SETTINGS ────────────────────────────
# Set your crop type and growth stage for Kc lookup.
# Kc values from FAO-56 Table 12.
CROP_TYPE   = "tomato"    # e.g. "tomato", "wheat", "maize", "cotton", "potato", "bare_soil"
GROWTH_STAGE = "mid"      # "ini" (initial), "dev" (development), "mid" (mid-season), "late"

# Kc table: {crop: {stage: Kc}}
KC_TABLE = {
    "tomato":     {"ini": 0.40, "dev": 0.80, "mid": 1.15, "late": 0.70},
    "wheat":      {"ini": 0.30, "dev": 0.70, "mid": 1.15, "late": 0.25},
    "maize":      {"ini": 0.30, "dev": 0.70, "mid": 1.20, "late": 0.35},
    "cotton":     {"ini": 0.35, "dev": 0.75, "mid": 1.15, "late": 0.50},
    "potato":     {"ini": 0.50, "dev": 0.75, "mid": 1.15, "late": 0.75},
    "bare_soil":  {"ini": 0.30, "dev": 0.30, "mid": 0.30, "late": 0.30},
}

# ── SOIL SETTINGS ─────────────────────────────
# Total Available Water (TAW) depends on soil texture.
# sandy ~100 mm, loam ~150 mm, clay ~200 mm
SOIL_TYPE = "loam"        # "sandy", "loam", "clay"

TAW_TABLE = {
    "sandy": 100.0,
    "loam":  150.0,
    "clay":  200.0,
}

# Previous day's root zone depletion (mm).
# On first run set to 0 (full field capacity) or load from your daily log.
DR_PREV = 0.0             # Dr,i-1 in FAO-56 Eq. 85

# ─────────────────────────────────────────────
# AUTO DATE HANDLING
# ─────────────────────────────────────────────

if date_target is None:
    target_date = date.today()
else:
    target_date = datetime.strptime(date_target, "%Y-%m-%d").date()

DATE_TARGET  = target_date.strftime("%Y-%m-%d")
TIME_INTERVAL = (
    (target_date - timedelta(days=10)).strftime("%Y-%m-%d"),
    DATE_TARGET
)

DOY = target_date.timetuple().tm_yday

# ─────────────────────────────────────────────
# AREA HANDLING
# ─────────────────────────────────────────────

BBOX = BBox(bbox=[west, south, east, north], crs=CRS.WGS84)
LAT  = (south + north) / 2
LON  = (west  + east)  / 2

ELEVATION_M = 280.0
RESOLUTION  = 10

size = bbox_to_dimensions(BBOX, resolution=RESOLUTION)

# ─────────────────────────────────────────────
# DEFAULT VALUES (fallbacks when satellite data unavailable)
# ─────────────────────────────────────────────

alpha_mean = 0.19
NDVI_mean  = 0.65
LST_K      = 300.15

# Stage 3 defaults
SM_FRACTION   = 0.50    # Sentinel-1 soil moisture (fraction of field capacity, 0–1)
SM_SOURCE     = "default"
RAINFALL_MM   = 0.0     # From weather API for the target date

# ─────────────────────────────────────────────
# STAGE 1 INPUTS — SENTINEL-2 (NDVI + ALBEDO)
# ─────────────────────────────────────────────

if config.sh_client_id and config.sh_client_secret:

    evalscript_s2 = """
    //VERSION=3
    function setup() {
      return {
        input: [{
          bands:["B02","B04","B08","B11","B12"],
          units:"REFLECTANCE"
        }],
        output:{bands:5,sampleType:"FLOAT32"}
      };
    }
    function evaluatePixel(s){
      return [s.B02,s.B04,s.B08,s.B11,s.B12];
    }
    """

    try:
        request = SentinelHubRequest(
            evalscript=evalscript_s2,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=SENTINEL2_CDSE,
                    time_interval=TIME_INTERVAL,
                    maxcc=0.3,
                    mosaicking_order="leastCC"
                )
            ],
            responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
            bbox=BBOX,
            size=size,
            config=config
        )

        data = request.get_data()[0]

        B02 = data[:, :, 0]
        B04 = data[:, :, 1]
        B08 = data[:, :, 2]
        B11 = data[:, :, 3]
        B12 = data[:, :, 4]

        NDVI = (B08 - B04) / (B08 + B04 + 1e-9)
        NDVI_mean = np.nanmean(np.clip(NDVI, -1, 1))

        # Liang (2001) broadband albedo for Sentinel-2
        alpha = (
            0.356 * B02 +
            0.130 * B04 +
            0.373 * B08 +
            0.085 * B11 +
            0.072 * B12 -
            0.0018
        )
        alpha_mean = np.nanmean(np.clip(alpha, 0, 1))

    except Exception as e:
        print(f"[S2] No data, using defaults. ({e})")

# ─────────────────────────────────────────────
# STAGE 1 INPUTS — SENTINEL-3 (LST)
# ─────────────────────────────────────────────

if config.sh_client_id and config.sh_client_secret:

    evalscript_s3 = """
    //VERSION=3
    function setup() {
      return {
        input: [{bands:["LST"],units:"KELVIN"}],
        output:{bands:1,sampleType:"FLOAT32"}
      };
    }
    function evaluatePixel(s){ return [s.LST]; }
    """

    try:
        request = SentinelHubRequest(
            evalscript=evalscript_s3,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=SENTINEL3_CDSE,
                    time_interval=TIME_INTERVAL
                )
            ],
            responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
            bbox=BBOX,
            size=(50, 50),
            config=config
        )
        data = request.get_data()[0]
        LST_K = np.nanmean(data[:, :, 0])

    except Exception as e:
        print(f"[S3] No LST data, using default. ({e})")

# ─────────────────────────────────────────────
# STAGE 3 INPUTS — SENTINEL-1 (SOIL MOISTURE)
# Sentinel-1 SAR C-band VV/VH backscatter → soil moisture fraction
# ─────────────────────────────────────────────

if config.sh_client_id and config.sh_client_secret:

    evalscript_s1 = """
    //VERSION=3
    function setup() {
      return {
        input: [{bands:["VV","VH"],units:"LINEAR"}],
        output:{bands:2,sampleType:"FLOAT32"}
      };
    }
    function evaluatePixel(s){ return [s.VV, s.VH]; }
    """

    try:
        request = SentinelHubRequest(
            evalscript=evalscript_s1,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=SENTINEL1_CDSE,
                    time_interval=TIME_INTERVAL,
                )
            ],
            responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
            bbox=BBOX,
            size=(50, 50),
            config=config
        )
        data = request.get_data()[0]
        VV = data[:, :, 0]
        VH = data[:, :, 1]

        # Simple empirical linear scaling of VV to volumetric soil moisture (m³/m³).
        # Dry bare soil ≈ −20 dB (VV_lin ≈ 0.01), saturated ≈ −5 dB (VV_lin ≈ 0.32).
        # Scale to [0, 1] fraction of field capacity.
        VV_mean = np.nanmean(VV)
        VV_dry  = 0.01   # ~−20 dB linear
        VV_sat  = 0.32   # ~−5  dB linear
        SM_FRACTION = float(np.clip((VV_mean - VV_dry) / (VV_sat - VV_dry), 0, 1))
        SM_SOURCE = "Sentinel-1"

    except Exception as e:
        print(f"[S1] No soil moisture data, using default. ({e})")

# ─────────────────────────────────────────────
# WEATHER — OPEN-METEO
# ─────────────────────────────────────────────

today = date.today()

if target_date <= today:
    api_url = "https://archive-api.open-meteo.com/v1/archive"
else:
    api_url = "https://api.open-meteo.com/v1/forecast"

try:
    response = requests.get(
        api_url,
        params={
            "latitude":   LAT,
            "longitude":  LON,
            "hourly":
                "temperature_2m,"
                "relative_humidity_2m,"
                "windspeed_10m,"
                "surface_pressure,"
                "shortwave_radiation,"
                "precipitation",
            "start_date": DATE_TARGET,
            "end_date":   DATE_TARGET,
            "timezone":   "auto"
        },
        timeout=30
    )

    weather = response.json()["hourly"]

    T  = np.mean(weather["temperature_2m"])
    RH = np.mean(weather["relative_humidity_2m"])
    Td = T - (100 - RH) / 5

    u10  = np.mean(weather["windspeed_10m"]) / 3.6
    P    = np.mean(weather["surface_pressure"]) / 10
    Rs   = np.sum(weather["shortwave_radiation"]) * 3600 / 1e6
    RAINFALL_MM = float(np.sum(weather["precipitation"]))

except Exception as e:
    print(f"[Weather] API error, using defaults. ({e})")
    T    = 28.5
    Td   = 14.5
    u10  = 2.0
    P    = 97.5
    Rs   = 26.0
    RAINFALL_MM = 0.0

# ─────────────────────────────────────────────
# STAGE 1 — REFERENCE ET₀ (FAO-56 Penman-Monteith)
# α (albedo) from Sentinel-2 feeds Rn → more accurate ET₀.
# ─────────────────────────────────────────────

es    = fao.svp_from_t(T)
ea    = fao.avp_from_tdew(Td)
VPD   = es - ea

u2    = u10 * 4.87 / math.log(67.8 * 10 - 5.42)

Delta = fao.delta_svp(T)
gamma = fao.psy_const(P)

lat_rad = math.radians(LAT)

dr  = fao.inv_rel_dist_earth_sun(DOY)
sd  = fao.sol_dec(DOY)
sha = fao.sunset_hour_angle(lat_rad, sd)

Ra  = fao.et_rad(lat_rad, sd, sha, dr)
Rs0 = (0.75 + 2e-5 * ELEVATION_M) * Ra

Rns = (1 - alpha_mean) * Rs
Rnl = fao.net_out_lw_rad(T + 273.15, T + 273.15, ea, Rs, Rs0)
Rn  = Rns - Rnl

G = Rn * (
    (LST_K - 273.15) *
    (0.0038 + 0.0074 * alpha_mean) *
    (1 - 0.98 * NDVI_mean ** 4)
)
G = 0.1 * G

ET0 = fao.fao56_penman_monteith(
    net_rad=Rn,
    t=T + 273.15,
    ws=u2,
    svp=es,
    avp=ea,
    delta_svp=Delta,
    psy=gamma,
    shf=G
)

# ─────────────────────────────────────────────
# STAGE 2 — CROP-SPECIFIC ETc
# ETc = ET₀ × Kc
# ─────────────────────────────────────────────

Kc  = KC_TABLE.get(CROP_TYPE, KC_TABLE["bare_soil"]).get(GROWTH_STAGE, 1.0)
ETc = ET0 * Kc      # mm/day, crop water demand

# ─────────────────────────────────────────────
# STAGE 3 — ACTUAL IRRIGATION NEED (FAO-56 Ch.8 Eq.85)
#
#   Dr,i = Dr,i-1 − (P − RO) − I − CR + ETc + DP
#
# Simplified (hackathon-ready):
#   • RO (runoff)         = 0  (flat field assumption)
#   • I  (irrigation)     = 0  (unknown; farmer logs it)
#   • CR (capillary rise) = 0  (water table > 1 m)
#   • DP (deep perc.)     = 0  (not over-irrigated)
#
# Sentinel-1 replaces the running water balance for Dr,i-1:
#   Dr,i-1 = TAW × (1 − SM_FRACTION)
# This resets accumulated error every 5-6 days when a new S-1 pass arrives.
# ─────────────────────────────────────────────

TAW      = TAW_TABLE.get(SOIL_TYPE, 150.0)

# Override Dr,i-1 with Sentinel-1 observation when available
if SM_SOURCE == "Sentinel-1":
    DR_PREV = TAW * (1.0 - SM_FRACTION)

# Effective rainfall (precipitation that enters the root zone; ignore runoff)
P_eff = RAINFALL_MM   # simplified: P_eff = P − RO ≈ P for small events

# FAO-56 Eq. 85 (I = CR = DP = 0)
Dr_today = DR_PREV - P_eff + ETc

# Clamp: depletion cannot exceed TAW (saturate upward) or go negative (overfill)
Dr_today = float(np.clip(Dr_today, 0, TAW))

# Irrigation need = how much to refill to field capacity
# Only apply if positive; negative means soil already has enough
IRRIGATION_MM = max(0.0, Dr_today)

# Convert mm → L/m²  (1 mm = 1 L/m²)
IRRIGATION_L_M2 = IRRIGATION_MM   # mm ≡ L/m²

# ─────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────

print("=" * 60)
print("STAGE 1 — Reference evapotranspiration (crop-agnostic)")
print("=" * 60)
stage1 = {
    "T  (Mean daily air temperature)":   f"{T:.2f} °C",
    "Rn (Net radiation)":                f"{Rn:.2f} MJ/m²/day",
    "G  (Soil heat flux)":               f"{G:.2f} MJ/m²/day",
    "es (Saturation vapor pressure)":    f"{es:.4f} kPa",
    "ea (Actual vapor pressure)":        f"{ea:.4f} kPa",
    "VPD (Vapor pressure deficit)":      f"{VPD:.4f} kPa",
    "u₂ (Wind speed at 2 m)":           f"{u2:.2f} m/s",
    "Δ  (Slope of SVP curve)":           f"{Delta:.4f} kPa/°C",
    "γ  (Psychrometric constant)":       f"{gamma:.5f} kPa/°C",
    "α  (Albedo, from Sentinel-2)":      f"{alpha_mean:.4f}",
    "NDVI (from Sentinel-2)":            f"{NDVI_mean:.4f}",
}
for k, v in stage1.items():
    print(f"  {k:42} {v}")
print(f"\n  ET₀ = {ET0:.2f} mm/day\n")

print("=" * 60)
print("STAGE 2 — Crop-specific evapotranspiration")
print("=" * 60)
print(f"  Crop type     : {CROP_TYPE}")
print(f"  Growth stage  : {GROWTH_STAGE}")
print(f"  Kc            : {Kc:.2f}")
print(f"  ETc = ET₀ × Kc = {ET0:.2f} × {Kc:.2f} = {ETc:.2f} mm/day\n")

print("=" * 60)
print("STAGE 3 — Irrigation need (FAO-56 Eq. 85 water balance)")
print("=" * 60)
print(f"  Soil type              : {SOIL_TYPE}")
print(f"  TAW                    : {TAW:.0f} mm")
print(f"  Soil moisture source   : {SM_SOURCE}")
print(f"  SM fraction            : {SM_FRACTION:.2f}  (fraction of field capacity)")
print(f"  Dr,i-1 (prev depletion): {DR_PREV:.2f} mm")
print(f"  Effective rainfall     : {P_eff:.2f} mm")
print(f"  ETc (crop demand)      : {ETc:.2f} mm/day")
print(f"  Dr,i (today's depletion): {Dr_today:.2f} mm")
print(f"\n  ▶  Irrigation needed   : {IRRIGATION_MM:.1f} mm  =  {IRRIGATION_L_M2:.1f} L/m²\n")

# ─────────────────────────────────────────────
# DATAFRAME OUTPUT
# ─────────────────────────────────────────────

df = pd.DataFrame([
    # Stage 1
    {"Stage": 1, "Parameter": "T (Mean daily air temperature)", "Value": f"{T:.2f}",      "Unit": "°C"},
    {"Stage": 1, "Parameter": "Rn (Net radiation)",             "Value": f"{Rn:.2f}",     "Unit": "MJ/m²/day"},
    {"Stage": 1, "Parameter": "G (Soil heat flux)",             "Value": f"{G:.2f}",      "Unit": "MJ/m²/day"},
    {"Stage": 1, "Parameter": "es (Saturation VP)",             "Value": f"{es:.4f}",     "Unit": "kPa"},
    {"Stage": 1, "Parameter": "ea (Actual VP)",                 "Value": f"{ea:.4f}",     "Unit": "kPa"},
    {"Stage": 1, "Parameter": "VPD",                            "Value": f"{VPD:.4f}",    "Unit": "kPa"},
    {"Stage": 1, "Parameter": "u₂ (Wind at 2 m)",               "Value": f"{u2:.2f}",     "Unit": "m/s"},
    {"Stage": 1, "Parameter": "α (Albedo)",                     "Value": f"{alpha_mean:.4f}", "Unit": "—"},
    {"Stage": 1, "Parameter": "NDVI",                           "Value": f"{NDVI_mean:.4f}", "Unit": "—"},
    {"Stage": 1, "Parameter": "ET₀",                            "Value": f"{ET0:.2f}",    "Unit": "mm/day"},
    # Stage 2
    {"Stage": 2, "Parameter": "Kc",                             "Value": f"{Kc:.2f}",     "Unit": "—"},
    {"Stage": 2, "Parameter": "ETc (crop demand)",              "Value": f"{ETc:.2f}",    "Unit": "mm/day"},
    # Stage 3
    {"Stage": 3, "Parameter": "TAW",                            "Value": f"{TAW:.0f}",    "Unit": "mm"},
    {"Stage": 3, "Parameter": "SM fraction (Sentinel-1)",       "Value": f"{SM_FRACTION:.2f}", "Unit": "0–1"},
    {"Stage": 3, "Parameter": "Dr,i-1 (previous depletion)",   "Value": f"{DR_PREV:.2f}","Unit": "mm"},
    {"Stage": 3, "Parameter": "Effective rainfall",             "Value": f"{P_eff:.2f}",  "Unit": "mm"},
    {"Stage": 3, "Parameter": "Dr,i (today's depletion)",      "Value": f"{Dr_today:.2f}","Unit": "mm"},
    {"Stage": 3, "Parameter": "Irrigation needed",             "Value": f"{IRRIGATION_L_M2:.1f}", "Unit": "L/m²"},
])

print(df.to_string(index=False))