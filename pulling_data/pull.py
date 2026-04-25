import math
import requests
import numpy as np
import pandas as pd
import pyeto.fao as fao
import getpass
import json
import sys

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
def return_data():
    pass


def parse_input(raw_json: str) -> tuple[list[dict], str, list[float]]:
    """Return (coordinates, crop_name, kc_list) from frontend JSON.

    Expected format:
        {"coordinates":[{"lat":41.7,"lng":21.5}, ...],
         "crop_type": {"Cabbage": [0.7, 1.05, 0.95]}}

    kc_list indices: 0 = ini, 1 = mid, 2 = end
    The correct Kc is selected after GROWTH_STAGE is derived from NDVI.
    """
    data = json.loads(raw_json)
    coords = data["coordinates"]
    crop_type = data.get("crop_type", {"Unknown": [1.0, 1.0, 1.0]})
    crop_name = list(crop_type.keys())[0]
    kc_list   = [float(v) for v in list(crop_type.values())[0]]
    return coords, crop_name, kc_list

def bbox_from_coordinates(coords: list[dict]) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) from a list of {lat, lng} dicts."""
    lats = [c["lat"] for c in coords]
    lngs = [c["lng"] for c in coords]
    return min(lngs), min(lats), max(lngs), max(lats)

# Resolve coordinate source
# Coordinates MUST come from frontend (CLI or stdin)

try:
    if len(sys.argv) > 1:
        coordinates, CROP_NAME, KC_LIST = parse_input(sys.argv[1])

    elif not sys.stdin.isatty():
        coordinates, CROP_NAME, KC_LIST = parse_input(sys.stdin.read())

    else:
        raise ValueError("No input received from frontend.")

except Exception as e:
    print("\nERROR: Input is required from the frontend.")
    print("Expected JSON format:")
    print('{"coordinates":[{"lat":41.7,"lng":21.5}, ...], "crop_type":{"Cabbage":[0.7,1.05,0.95]}}')
    sys.exit(1)
west, south, east, north = bbox_from_coordinates(coordinates)

date_target = None   # None = today, or "2026-04-24"

# ── CROP SETTINGS ────────────────────────────
# crop_type from the frontend: {"CropName": [Kc_ini, Kc_mid, Kc_end]}
# GROWTH_STAGE is derived automatically from the 60-day NDVI time series (see below).
# The matching Kc is selected from KC_LIST after GROWTH_STAGE is known.
GROWTH_STAGE = "mid"   # placeholder; overwritten by NDVI time-series logic below

STAGE_TO_IDX = {"ini": 0, "dev": 0, "mid": 1, "late": 2, "end": 2}

# ── SOIL SETTINGS ─────────────────────────────
# SOIL_TYPE and TAW are derived automatically from SoilGrids API (see below).
SOIL_TYPE = "loam"        # placeholder; overwritten by SoilGrids query below

TAW_TABLE = {
    "sandy": 100.0,
    "loam":  150.0,
    "clay":  200.0,
}

# DR_PREV is computed automatically from Sentinel-1 soil moisture below.
# Fallback (no S1 data): assume field capacity (zero depletion).
DR_PREV = 0.0   # overwritten when SM_SOURCE == "Sentinel-1"

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

        NDVI_2d = np.clip((B08 - B04) / (B08 + B04 + 1e-9), -1, 1)   # 2D — kept for per-pixel pipeline
        NDVI_mean = np.nanmean(NDVI_2d)

        # Liang (2001) broadband albedo for Sentinel-2
        alpha_2d = np.clip(
            0.356 * B02 +
            0.130 * B04 +
            0.373 * B08 +
            0.085 * B11 +
            0.072 * B12 -
            0.0018,
            0, 1
        )                                                                  # 2D — kept for per-pixel pipeline
        alpha_mean = np.nanmean(alpha_2d)

    except Exception as e:
        print(f"[S2] No data, using defaults. ({e})")

# ─────────────────────────────────────────────
# GROWTH STAGE — derived from 60-day NDVI time series (Sentinel-2)
# Logic: find peak NDVI; compare today's value to classify stage.
# ─────────────────────────────────────────────

if config.sh_client_id and config.sh_client_secret:

    evalscript_ndvi_ts = """
    //VERSION=3
    function setup() {
      return {
        input: [{bands:["B04","B08"],units:"REFLECTANCE"}],
        output:{bands:1,sampleType:"FLOAT32"},
        mosaicking: "ORBIT"
      };
    }
    function evaluatePixel(samples){
      var total = 0, count = 0;
      for (var i = 0; i < samples.length; i++) {
        var b4 = samples[i].B04, b8 = samples[i].B08;
        if (b8 + b4 > 0) { total += (b8 - b4) / (b8 + b4); count++; }
      }
      return [count > 0 ? total / count : 0];
    }
    """

    ts_start = (target_date - timedelta(days=60)).strftime("%Y-%m-%d")
    ts_end   = DATE_TARGET

    try:
        from sentinelhub import SentinelHubStatistical, Geometry
        import shapely.geometry

        geo = shapely.geometry.box(west, south, east, north)
        geometry = Geometry(geo, CRS.WGS84)

        stat_request = SentinelHubStatistical(
            aggregation=SentinelHubStatistical.aggregation(
                evalscript=evalscript_ndvi_ts,
                time_interval=(ts_start, ts_end),
                aggregation_interval="P5D",
                size=size
            ),
            input_data=[
                SentinelHubStatistical.input_data(
                    SENTINEL2_CDSE,
                    maxcc=0.3
                )
            ],
            geometry=geometry,
            config=config
        )

        ts_data = stat_request.get_data()[0]
        ndvi_series = []
        for interval in ts_data.get("data", []):
            val = interval.get("outputs", {}).get("default", {}).get("bands", {}).get("B0", {}).get("stats", {}).get("mean")
            if val is not None and not math.isnan(val):
                ndvi_series.append(val)

        if len(ndvi_series) >= 3:
            peak_ndvi = max(ndvi_series)
            peak_idx  = ndvi_series.index(peak_ndvi)
            last_ndvi = ndvi_series[-1]
            frac      = last_ndvi / (peak_ndvi + 1e-9)

            if peak_idx >= len(ndvi_series) - 2:
                # Still rising toward peak
                if frac < 0.5:
                    GROWTH_STAGE = "ini"
                else:
                    GROWTH_STAGE = "dev"
            else:
                # Past peak
                if frac >= 0.90:
                    GROWTH_STAGE = "mid"
                else:
                    GROWTH_STAGE = "late"
        else:
            GROWTH_STAGE = "mid"   # insufficient data; keep default

    except Exception as e:
        print(f"[S2-TS] NDVI time series failed, using default growth stage. ({e})")

# ─────────────────────────────────────────────
# SOIL TYPE + TAW — SoilGrids REST API (ISRIC)
# Queries sand/clay % at 0–30 cm depth for LAT/LON.
# ─────────────────────────────────────────────

TAW_TABLE = {
    "sandy": 100.0,
    "loam":  150.0,
    "clay":  200.0,
}

try:
    sg_resp = requests.get(
        "https://rest.isric.org/soilgrids/v2.0/properties/query",
        params={
            "lon":        LON,
            "lat":        LAT,
            "property":   ["clay", "sand"],
            "depth":      ["0-5cm", "5-15cm", "15-30cm"],
            "value":      "mean",
        },
        timeout=20
    )
    sg_data = sg_resp.json()

    def _sg_mean(prop_name):
        for layer in sg_data["properties"]["layers"]:
            if layer["name"] == prop_name:
                vals = [
                    d["values"].get("mean")
                    for d in layer["depths"]
                    if d["values"].get("mean") is not None
                ]
                if vals:
                    # SoilGrids returns g/kg (‰); divide by 10 to get %
                    return np.mean(vals) / 10.0
        return None

    clay_pct = _sg_mean("clay")
    sand_pct = _sg_mean("sand")

    if clay_pct is not None and sand_pct is not None:
        if sand_pct >= 70:
            SOIL_TYPE = "sandy"
        elif clay_pct >= 40:
            SOIL_TYPE = "clay"
        else:
            SOIL_TYPE = "loam"
    # else keep placeholder "loam"

except Exception as e:
    print(f"[SoilGrids] API error, using default soil type. ({e})")

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
        VV_dry  = 0.01   # ~−20 dB linear
        VV_sat  = 0.32   # ~−5  dB linear
        SM_2d       = np.clip((VV - VV_dry) / (VV_sat - VV_dry), 0, 1)   # 2D — kept for per-pixel pipeline
        SM_FRACTION = float(np.nanmean(SM_2d))                            # scalar for summary output
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

Kc  = KC_LIST[STAGE_TO_IDX.get(GROWTH_STAGE, 1)]   # select from [ini, mid, end] via NDVI-derived stage
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

# ── Scalar path (summary output) ─────────────────────────────────────────────
# Override Dr,i-1 with Sentinel-1 observation when available
if SM_SOURCE == "Sentinel-1":
    DR_PREV = TAW * (1.0 - SM_FRACTION)

P_eff = RAINFALL_MM   # simplified: P_eff = P − RO ≈ P for small events

Dr_today = float(np.clip(DR_PREV - P_eff + ETc, 0, TAW))
IRRIGATION_MM   = max(0.0, Dr_today)
IRRIGATION_L_M2 = IRRIGATION_MM   # mm ≡ L/m²

# ── Per-pixel 2D path (heatmap output) ───────────────────────────────────────
# ET₀ is spatially uniform (weather is field-scale); spatial variation comes
# from per-pixel albedo (→ Rns), NDVI (→ G), and soil moisture (→ DR_PREV_2d).

# 2D Rns and G using pixel-level albedo and NDVI (fall back to scalars if S2 unavailable)
try:
    Rns_2d = (1.0 - alpha_2d) * Rs
    G_2d   = 0.1 * (Rns_2d - Rnl) * (
        (LST_K - 273.15) *
        (0.0038 + 0.0074 * alpha_2d) *
        (1 - 0.98 * NDVI_2d ** 4)
    )
    Rn_2d  = Rns_2d - Rnl
    ET0_2d = fao.fao56_penman_monteith(
        net_rad=Rn_2d, t=T + 273.15, ws=u2,
        svp=es, avp=ea, delta_svp=Delta, psy=gamma, shf=G_2d
    )
except NameError:
    # alpha_2d / NDVI_2d not available (S2 fallback) — broadcast scalars
    ET0_2d = np.full(size[::-1], ET0)   # size is (width, height); numpy is row-major

ETc_2d = ET0_2d * Kc

# 2D DR_PREV from per-pixel soil moisture (fall back to scalar if S1 unavailable)
try:
    DR_PREV_2d = TAW * (1.0 - SM_2d)
except NameError:
    DR_PREV_2d = np.full_like(ETc_2d, DR_PREV)

Dr_today_2d      = np.clip(DR_PREV_2d - P_eff + ETc_2d, 0, TAW)
IRRIGATION_2d    = np.maximum(0.0, Dr_today_2d)   # L/m² per pixel (mm ≡ L/m²)

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
print(f"  Crop               : {CROP_NAME}")
print(f"  Growth stage       : {GROWTH_STAGE}  (derived from 60-day NDVI trend)")
print(f"  Kc                 : {Kc:.2f}  (Kc_ini={KC_LIST[0]:.2f}, Kc_mid={KC_LIST[1]:.2f}, Kc_end={KC_LIST[2]:.2f})")
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
# HEATMAP ARRAY OUTPUT
# ─────────────────────────────────────────────
# Emit a JSON object the frontend can use to colour each pixel.
# Shape: rows (north→south) × cols (west→east), values in L/m².
# Includes bbox so the frontend can geo-register the grid.

heatmap_payload = {
    "bbox": {"west": west, "south": south, "east": east, "north": north},
    "resolution_m": RESOLUTION,
    "rows": int(IRRIGATION_2d.shape[0]),
    "cols": int(IRRIGATION_2d.shape[1]),
    "unit": "L/m2",
    "irrigation_grid": [
        [round(float(v), 2) for v in row]
        for row in IRRIGATION_2d
    ]
}

print("\n" + "=" * 60)
print("HEATMAP — Per-pixel irrigation need (L/m²)")
print("=" * 60)
print(f"  Grid size : {heatmap_payload['rows']} rows × {heatmap_payload['cols']} cols")
print(f"  Min       : {float(IRRIGATION_2d.min()):.2f} L/m²")
print(f"  Max       : {float(IRRIGATION_2d.max()):.2f} L/m²")
print(f"  Mean      : {float(IRRIGATION_2d.mean()):.2f} L/m²  (≈ scalar result above)")
print("\nHEATMAP_JSON_START")
print(json.dumps(heatmap_payload, separators=(',', ':')))
print("HEATMAP_JSON_END\n")

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
    {"Stage": 2, "Parameter": "Crop name",                       "Value": CROP_NAME,        "Unit": "—"},
    {"Stage": 2, "Parameter": "Growth stage (NDVI-derived)",     "Value": GROWTH_STAGE,     "Unit": "—"},
    {"Stage": 2, "Parameter": "Kc (selected)",                   "Value": f"{Kc:.2f}",      "Unit": "—"},
    {"Stage": 2, "Parameter": "ETc (crop demand)",               "Value": f"{ETc:.2f}",    "Unit": "mm/day"},
    # Stage 3
    {"Stage": 3, "Parameter": "TAW",                            "Value": f"{TAW:.0f}",    "Unit": "mm"},
    {"Stage": 3, "Parameter": "SM fraction (Sentinel-1)",       "Value": f"{SM_FRACTION:.2f}", "Unit": "0–1"},
    {"Stage": 3, "Parameter": "Dr,i-1 (previous depletion)",   "Value": f"{DR_PREV:.2f}","Unit": "mm"},
    {"Stage": 3, "Parameter": "Effective rainfall",             "Value": f"{P_eff:.2f}",  "Unit": "mm"},
    {"Stage": 3, "Parameter": "Dr,i (today's depletion)",      "Value": f"{Dr_today:.2f}","Unit": "mm"},
    {"Stage": 3, "Parameter": "Irrigation needed",             "Value": f"{IRRIGATION_L_M2:.1f}", "Unit": "L/m²"},
])

print(df.to_string(index=False))

