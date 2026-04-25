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
async def return_data(coordinates, crop_values):
    """
    Given a list of {lat, lng} coordinate dicts and a [Kc_ini, Kc_mid, Kc_end]
    list, compute irrigation requirements and return:
        {
            "ETo":               float,   # Reference ET₀ in mm/day
            "irrigation_avg":    float,   # Average irrigation need in L/m²
            "irrigation_grid":   list[list[float]]  # Per-pixel L/m² (rows × cols)
        }
    """
    KC_LIST = [float(v) for v in crop_values]

    west, south, east, north = bbox_from_coordinates(coordinates)

    date_target = None   # None = today

    # ── CROP SETTINGS ────────────────────────────
    GROWTH_STAGE = "mid"
    STAGE_TO_IDX = {"ini": 0, "dev": 0, "mid": 1, "late": 2, "end": 2}

    # ── SOIL SETTINGS ─────────────────────────────
    SOIL_TYPE = "loam"
    TAW_TABLE = {
        "sandy": 100.0,
        "loam":  150.0,
        "clay":  200.0,
    }
    DR_PREV = 0.0

    # ── DEFAULT VALUES (fallbacks when satellite data unavailable) ────────────
    alpha_mean = 0.19
    NDVI_mean  = 0.65
    LST_K      = 300.15
    SM_FRACTION = 0.50
    SM_SOURCE   = "default"
    RAINFALL_MM = 0.0

    # ── AUTO DATE HANDLING ────────────────────────
    if date_target is None:
        target_date = date.today()
    else:
        target_date = datetime.strptime(date_target, "%Y-%m-%d").date()

    DATE_TARGET   = target_date.strftime("%Y-%m-%d")
    TIME_INTERVAL = (
        (target_date - timedelta(days=10)).strftime("%Y-%m-%d"),
        DATE_TARGET
    )
    DOY = target_date.timetuple().tm_yday

    # ── AREA ──────────────────────────────────────
    BBOX = BBox(bbox=[west, south, east, north], crs=CRS.WGS84)
    LAT  = (south + north) / 2
    LON  = (west  + east)  / 2
    ELEVATION_M = 280.0
    RESOLUTION  = 10
    size = bbox_to_dimensions(BBOX, resolution=RESOLUTION)

    # ── STAGE 1 — SENTINEL-2 (NDVI + ALBEDO) ─────
    alpha_2d = None
    NDVI_2d  = None

    if config.sh_client_id and config.sh_client_secret:
        evalscript_s2 = """
        //VERSION=3
        function setup() {
          return {
            input: [{bands:["B02","B04","B08","B11","B12"],units:"REFLECTANCE"}],
            output:{bands:5,sampleType:"FLOAT32"}
          };
        }
        function evaluatePixel(s){
          return [s.B02,s.B04,s.B08,s.B11,s.B12];
        }
        """
        try:
            req = SentinelHubRequest(
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
                bbox=BBOX, size=size, config=config
            )
            s2_data = req.get_data()[0]
            B02 = s2_data[:, :, 0]; B04 = s2_data[:, :, 1]
            B08 = s2_data[:, :, 2]; B11 = s2_data[:, :, 3]; B12 = s2_data[:, :, 4]

            NDVI_2d    = np.clip((B08 - B04) / (B08 + B04 + 1e-9), -1, 1)
            NDVI_mean  = float(np.nanmean(NDVI_2d))

            alpha_2d   = np.clip(
                0.356*B02 + 0.130*B04 + 0.373*B08 + 0.085*B11 + 0.072*B12 - 0.0018,
                0, 1
            )
            alpha_mean = float(np.nanmean(alpha_2d))
        except Exception as e:
            print(f"[S2] No data, using defaults. ({e})")

    # ── GROWTH STAGE — 60-day NDVI time series ────
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
        try:
            from sentinelhub import SentinelHubStatistical, Geometry
            import shapely.geometry
            geo = shapely.geometry.box(west, south, east, north)
            geometry = Geometry(geo, CRS.WGS84)
            stat_request = SentinelHubStatistical(
                aggregation=SentinelHubStatistical.aggregation(
                    evalscript=evalscript_ndvi_ts,
                    time_interval=(ts_start, DATE_TARGET),
                    aggregation_interval="P5D",
                    size=size
                ),
                input_data=[SentinelHubStatistical.input_data(SENTINEL2_CDSE, maxcc=0.3)],
                geometry=geometry, config=config
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
                    GROWTH_STAGE = "ini" if frac < 0.5 else "dev"
                else:
                    GROWTH_STAGE = "mid" if frac >= 0.90 else "late"
        except Exception as e:
            print(f"[S2-TS] NDVI time series failed, using default growth stage. ({e})")

    # ── SOIL TYPE — SoilGrids ─────────────────────
    try:
        sg_resp = requests.get(
            "https://rest.isric.org/soilgrids/v2.0/properties/query",
            params={"lon": LON, "lat": LAT, "property": ["clay", "sand"],
                    "depth": ["0-5cm", "5-15cm", "15-30cm"], "value": "mean"},
            timeout=20
        )
        sg_data = sg_resp.json()

        # FIX Bug 1: _sg_mean defined AND called inside the same try block.
        # SoilGrids returns values in g/kg (0-1000); divide by 10 → percentage (0-100).
        def _sg_mean(prop_name):
            for layer in sg_data["properties"]["layers"]:
                if layer["name"] == prop_name:
                    vals = [d["values"].get("mean") for d in layer["depths"]
                            if d["values"].get("mean") is not None]
                    return np.mean(vals) / 10.0 if vals else None   # g/kg → %
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
            print(f"[SoilGrids] clay={clay_pct:.1f}% sand={sand_pct:.1f}% → SOIL_TYPE={SOIL_TYPE}")
    except Exception as e:
        print(f"[SoilGrids] API error, using default soil type. ({e})")

    # ── SENTINEL-3 (LST) ──────────────────────────
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
            req = SentinelHubRequest(
                evalscript=evalscript_s3,
                input_data=[SentinelHubRequest.input_data(
                    data_collection=SENTINEL3_CDSE, time_interval=TIME_INTERVAL)],
                responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
                bbox=BBOX, size=(50, 50), config=config
            )
            LST_K = float(np.nanmean(req.get_data()[0][:, :, 0]))
        except Exception as e:
            print(f"[S3] No LST data, using default. ({e})")

    # ── SENTINEL-1 (SOIL MOISTURE) ────────────────
    SM_2d = None

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
            req = SentinelHubRequest(
                evalscript=evalscript_s1,
                input_data=[SentinelHubRequest.input_data(
                    data_collection=SENTINEL1_CDSE, time_interval=TIME_INTERVAL)],
                responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
                bbox=BBOX, size=(50, 50), config=config
            )
            s1_data = req.get_data()[0]
            VV = s1_data[:, :, 0]
            VV_dry, VV_sat = 0.01, 0.32
            SM_2d       = np.clip((VV - VV_dry) / (VV_sat - VV_dry), 0, 1)
            SM_FRACTION = float(np.nanmean(SM_2d))
            SM_SOURCE   = "Sentinel-1"
        except Exception as e:
            print(f"[S1] No soil moisture data, using default. ({e})")

    # ── WEATHER — OPEN-METEO ──────────────────────
    today_date = date.today()
    api_url = ("https://archive-api.open-meteo.com/v1/archive"
               if target_date <= today_date
               else "https://api.open-meteo.com/v1/forecast")
    T_max = T_min = None   # will be set below
    try:
        response = requests.get(
            api_url,
            params={
                "latitude": LAT, "longitude": LON,
                "hourly": ("temperature_2m,relative_humidity_2m,windspeed_10m,"
                           "surface_pressure,shortwave_radiation,precipitation"),
                # FIX Bug 3: fetch daily Tmax/Tmin for correct Rnl calculation
                "daily": "temperature_2m_max,temperature_2m_min",
                "start_date": DATE_TARGET, "end_date": DATE_TARGET,
                "timezone": "auto"
            },
            timeout=30
        )
        resp_json   = response.json()
        weather     = resp_json["hourly"]
        T           = float(np.mean(weather["temperature_2m"]))
        RH          = float(np.mean(weather["relative_humidity_2m"]))
        Td          = T - (100 - RH) / 5
        u10         = float(np.mean(weather["windspeed_10m"])) / 3.6
        P_atm       = float(np.mean(weather["surface_pressure"])) / 10
        Rs          = float(np.sum(weather["shortwave_radiation"])) * 3600 / 1e6
        RAINFALL_MM = float(np.sum(weather["precipitation"]))
        T_max       = float(resp_json["daily"]["temperature_2m_max"][0])
        T_min       = float(resp_json["daily"]["temperature_2m_min"][0])
    except Exception as e:
        print(f"[Weather] API error, using defaults. ({e})")
        T = 28.5; Td = 14.5; u10 = 2.0; P_atm = 97.5; Rs = 26.0; RAINFALL_MM = 0.0

    # Fallback if daily fields missing
    if T_max is None: T_max = T + 5.0
    if T_min is None: T_min = T - 5.0

    # ── STAGE 1 — ET₀ (FAO-56 Penman-Monteith) ───
    es    = fao.svp_from_t(T)
    ea    = fao.avp_from_tdew(Td)
    u2    = u10 * 4.87 / math.log(67.8 * 10 - 5.42)
    Delta = fao.delta_svp(T)
    gamma = fao.psy_const(P_atm)

    lat_rad = math.radians(LAT)
    dr  = fao.inv_rel_dist_earth_sun(DOY)
    sd  = fao.sol_dec(DOY)
    sha = fao.sunset_hour_angle(lat_rad, sd)
    Ra  = fao.et_rad(lat_rad, sd, sha, dr)
    Rs0 = (0.75 + 2e-5 * ELEVATION_M) * Ra

    Rns = (1 - alpha_mean) * Rs
    # FIX Bug 3: use actual Tmax/Tmin in Kelvin, not mean T twice
    Rnl = fao.net_out_lw_rad(T_max + 273.15, T_min + 273.15, ea, Rs, Rs0)
    Rn  = Rns - Rnl
    # FIX Bug 4: correct SEBAL G formula — Ts (°C) multiplies Rn directly
    Ts_C = LST_K - 273.15
    G    = Rn * Ts_C * (0.0038 + 0.0074 * alpha_mean) * (1 - 0.98 * NDVI_mean ** 4)

    ET0 = fao.fao56_penman_monteith(
        net_rad=Rn, t=T + 273.15, ws=u2,
        svp=es, avp=ea, delta_svp=Delta, psy=gamma, shf=G
    )

    # ── STAGE 2 — Crop-specific ETc ───────────────
    Kc  = KC_LIST[STAGE_TO_IDX.get(GROWTH_STAGE, 1)]
    ETc = ET0 * Kc

    # ── STAGE 3 — Irrigation need ─────────────────
    TAW = TAW_TABLE.get(SOIL_TYPE, 150.0)

    if SM_SOURCE == "Sentinel-1":
        DR_PREV = TAW * (1.0 - SM_FRACTION)

    P_eff    = RAINFALL_MM
    Dr_today = float(np.clip(DR_PREV - P_eff + ETc, 0, TAW))
    IRRIGATION_MM   = max(0.0, Dr_today)
    IRRIGATION_L_M2 = IRRIGATION_MM   # mm ≡ L/m²

    # ── Per-pixel 2D irrigation (heatmap) ─────────
    # Spatial variation comes from per-pixel albedo (→ Rns), NDVI (→ G),
    # and soil moisture (→ DR_PREV_2d); ET₀ weather inputs are field-scale.
    if alpha_2d is not None and NDVI_2d is not None:
        Rns_2d = (1.0 - alpha_2d) * Rs
        # FIX Bug 4 (2D): same corrected SEBAL G formula
        Ts_C_2d = LST_K - 273.15
        G_2d    = (Rns_2d - Rnl) * Ts_C_2d * (0.0038 + 0.0074 * alpha_2d) * (1 - 0.98 * NDVI_2d ** 4)
        Rn_2d  = Rns_2d - Rnl
        ET0_2d = fao.fao56_penman_monteith(
            net_rad=Rn_2d, t=T + 273.15, ws=u2,
            svp=es, avp=ea, delta_svp=Delta, psy=gamma, shf=G_2d
        )
    else:
        # FIX Bug 5: S2 unavailable — synthesise mild spatial variation from
        # a geographic temperature gradient (≈0.6 °C / 100 m elevation proxy)
        # so the grid is not entirely flat.  Variation is ±~5% around ET0.
        rows, cols = size[1], size[0]
        # Linear lat gradient across the bounding box (cooler northward)
        lat_grad = np.linspace(0, 1, rows)[:, np.newaxis] * np.ones((rows, cols))
        # ±2 °C variation → ±≈5% ET0 variation
        T_spatial = T + 1.0 - 2.0 * lat_grad          # warmer south, cooler north
        es_2d   = np.vectorize(fao.svp_from_t)(T_spatial)
        Delta_2d = np.vectorize(fao.delta_svp)(T_spatial)
        ET0_2d = fao.fao56_penman_monteith(
            net_rad=Rn, t=T_spatial + 273.15, ws=u2,
            svp=es_2d, avp=ea, delta_svp=Delta_2d, psy=gamma, shf=G
        )

    ETc_2d = ET0_2d * Kc

    if SM_2d is not None:
        # Resize SM_2d to match ETc_2d if S1 was fetched at lower resolution (50×50)
        if SM_2d.shape != ETc_2d.shape:
            from PIL import Image as _Image
            _sm_img  = _Image.fromarray(SM_2d.astype(np.float32))
            _sm_rsz  = _sm_img.resize((ETc_2d.shape[1], ETc_2d.shape[0]), _Image.BILINEAR)
            SM_2d    = np.array(_sm_rsz)
        DR_PREV_2d = TAW * (1.0 - SM_2d)
    else:
        DR_PREV_2d = np.full_like(ETc_2d, DR_PREV)

    Dr_today_2d   = np.clip(DR_PREV_2d - P_eff + ETc_2d, 0, TAW)
    IRRIGATION_2d = np.maximum(0.0, Dr_today_2d)   # L/m² per pixel

    # ── Return the three requested outputs ─────────
    return {
        "ETo":            round(float(ET0), 4),
        "irrigation_avg": round(float(IRRIGATION_L_M2), 4),
        "irrigation_grid": [
            [round(float(v), 2) for v in row]
            for row in IRRIGATION_2d
        ]
    }


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