import math
import requests
import numpy as np
import pyeto.fao as fao
import json

from datetime import datetime, timedelta, date
from PIL import Image as _Image

from sentinelhub import (
    SHConfig, BBox, CRS, DataCollection,
    SentinelHubRequest, MimeType, bbox_to_dimensions
)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

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
# CROP CALENDARS  (DOY upper boundary per stage)
# [ini_end, dev_end, mid_end, late_end]
# FAO-56 Table 11 Northern-Hemisphere defaults.
# ─────────────────────────────────────────────
CROP_CALENDARS = {
    "Cabbage":   [30,  75,  130, 160],
    "Wheat":     [30,  85,  165, 210],
    "Maize":     [25,  75,  145, 185],
    "Tomato":    [35,  80,  145, 175],
    "Cotton":    [30,  90,  185, 230],
    "Potato":    [25,  60,  105, 130],
    "Sunflower": [25,  65,  130, 160],
    "Soybean":   [20,  60,  120, 155],
    "Default":   [30,  80,  140, 180],
}

# Root zone depth (m) per crop — FAO-56 Table 22
ROOT_DEPTH_TABLE = {
    "Cabbage":   0.5,
    "Wheat":     1.0,
    "Maize":     1.0,
    "Tomato":    0.7,
    "Cotton":    1.0,
    "Potato":    0.4,
    "Sunflower": 0.8,
    "Soybean":   0.6,
    "Default":   0.7,
}

# Field capacity and wilting point (m³/m³) by soil class
# TAW = (FC - WP) * root_depth * 1000  [mm]
SOIL_PARAMS = {
    "sandy": {"FC": 0.18, "WP": 0.08},
    "loam":  {"FC": 0.31, "WP": 0.14},
    "clay":  {"FC": 0.40, "WP": 0.22},
}

_WARN  = "\033[93m"
_ERR   = "\033[91m"
_RESET = "\033[0m"


# ─────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────

# FIXED: removed `async` — all I/O uses synchronous requests; async keyword was misleading
# FIXED: added dr_prev parameter so callers maintain a running root-zone depletion balance
# FIXED: added crop_name parameter needed for calendar-based growth stage and root depth
def return_data(
    coordinates: list[dict],
    crop_values: list[float],
    crop_name: str = "Default",
    dr_prev: float = 0.0,
    date_target: str | None = None,
) -> dict:
    """
    Parameters
    ----------
    coordinates : list of {lat, lng}
    crop_values : [Kc_ini, Kc_mid, Kc_end]
    crop_name   : key into CROP_CALENDARS / ROOT_DEPTH_TABLE
    dr_prev     : root-zone depletion carried forward from previous day [mm]
    date_target : ISO date string or None (= today)

    Returns
    -------
    {
        "ETo":             float,
        "irrigation_avg":  float,
        "irrigation_grid": list[list[float]],
        "data_quality":    dict          # source flags and warnings for every input
    }
    """
    KC_LIST = [float(v) for v in crop_values]
    west, south, east, north = bbox_from_coordinates(coordinates)

    STAGE_TO_IDX = {"ini": 0, "dev": 0, "mid": 1, "late": 2, "end": 2}
    GROWTH_STAGE = "mid"
    SOIL_TYPE    = "loam"

    # FIXED: DR_PREV now initialised from parameter instead of always being 0
    DR_PREV = float(dr_prev)

    # FIXED: alpha default changed 0.19 → 0.23 (FAO-56 eq.38 reference grass surface)
    alpha_mean  = 0.23
    NDVI_mean   = 0.65
    LST_K       = 300.15
    SM_FRACTION = 0.50
    SM_SOURCE   = "default"
    RAINFALL_MM = 0.0
    ELEVATION_M = None

    # FIXED: data_quality dict surfaces every source and every fallback to the caller
    data_quality = {
        "alpha_source":        "default_0.23",
        "ndvi_source":         "default_0.65",
        "lst_source":          "default_300.15K",
        "sm_source":           "default_0.50",
        "growth_stage_source": "default_mid",
        "soil_type_source":    "default_loam",
        "elevation_source":    "pending",
        "weather_source":      "default_hardcoded",
        "warnings":            [],
    }

    if date_target is None:
        target_date = date.today()
    else:
        target_date = datetime.strptime(date_target, "%Y-%m-%d").date()

    DATE_TARGET   = target_date.strftime("%Y-%m-%d")
    TIME_INTERVAL = (
        (target_date - timedelta(days=10)).strftime("%Y-%m-%d"),
        DATE_TARGET,
    )
    DOY = target_date.timetuple().tm_yday

    BBOX = BBox(bbox=[west, south, east, north], crs=CRS.WGS84)
    LAT  = (south + north) / 2
    LON  = (west  + east)  / 2
    RESOLUTION = 10
    size = bbox_to_dimensions(BBOX, resolution=RESOLUTION)
    # size = (width, height); numpy arrays are row-major: shape = (height, width)

    # ── SENTINEL-2 (NDVI + ALBEDO) ────────────
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
                        mosaicking_order="leastCC",
                    )
                ],
                responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
                bbox=BBOX, size=size, config=config,
            )
            s2_data = req.get_data()[0]
            B02 = s2_data[:, :, 0]; B04 = s2_data[:, :, 1]
            B08 = s2_data[:, :, 2]; B11 = s2_data[:, :, 3]; B12 = s2_data[:, :, 4]

            NDVI_2d   = np.clip((B08 - B04) / (B08 + B04 + 1e-9), -1, 1)
            NDVI_mean = float(np.nanmean(NDVI_2d))

            alpha_2d   = np.clip(
                0.356*B02 + 0.130*B04 + 0.373*B08 + 0.085*B11 + 0.072*B12 - 0.0018,
                0, 1,
            )
            alpha_mean = float(np.nanmean(alpha_2d))

            data_quality["alpha_source"] = "Sentinel-2"
            data_quality["ndvi_source"]  = "Sentinel-2"
        except Exception as e:
            print(f"{_WARN}[WARNING][S2] No data — alpha and NDVI using defaults. ({e}){_RESET}")
            data_quality["warnings"].append(
                f"S2 unavailable — alpha defaulting to 0.23, NDVI to 0.65: {e}"
            )

    # ── GROWTH STAGE ──────────────────────────
    # FIXED: DOY-based crop calendar replaces pure NDVI heuristic as primary source,
    #        resolving misclassification for multi-cropping systems.
    calendar = CROP_CALENDARS.get(crop_name, CROP_CALENDARS["Default"])
    if DOY <= calendar[0]:
        GROWTH_STAGE = "ini"
    elif DOY <= calendar[1]:
        GROWTH_STAGE = "dev"
    elif DOY <= calendar[2]:
        GROWTH_STAGE = "mid"
    elif DOY <= calendar[3]:
        GROWTH_STAGE = "late"
    else:
        GROWTH_STAGE = "end"
    data_quality["growth_stage_source"] = f"crop_calendar:{crop_name}:DOY{DOY}"

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
            geo      = shapely.geometry.box(west, south, east, north)
            geometry = Geometry(geo, CRS.WGS84)
            stat_req = SentinelHubStatistical(
                aggregation=SentinelHubStatistical.aggregation(
                    evalscript=evalscript_ndvi_ts,
                    time_interval=(ts_start, DATE_TARGET),
                    aggregation_interval="P5D",
                    size=size,
                ),
                input_data=[SentinelHubStatistical.input_data(SENTINEL2_CDSE, maxcc=0.3)],
                geometry=geometry, config=config,
            )
            ts_data = stat_req.get_data()[0]
            ndvi_series = []
            for interval in ts_data.get("data", []):
                val = (interval
                       .get("outputs", {})
                       .get("default", {})
                       .get("bands", {})
                       .get("B0", {})
                       .get("stats", {})
                       .get("mean"))
                if val is not None and not math.isnan(val):
                    ndvi_series.append(val)

            if len(ndvi_series) >= 3:
                peak_ndvi = max(ndvi_series)
                peak_idx  = ndvi_series.index(peak_ndvi)
                last_ndvi = ndvi_series[-1]
                frac      = last_ndvi / (peak_ndvi + 1e-9)
                if peak_idx >= len(ndvi_series) - 2:
                    ndvi_stage = "ini" if frac < 0.5 else "dev"
                else:
                    ndvi_stage = "mid" if frac >= 0.90 else "late"

                # FIXED: NDVI time-series only overrides the calendar stage when the
                #        two agree within one adjacent stage, preventing large jumps
                #        caused by disease events or multi-crop confusion.
                stage_order = ["ini", "dev", "mid", "late", "end"]
                cal_idx     = stage_order.index(GROWTH_STAGE)
                ndvi_idx    = stage_order.index(ndvi_stage)
                if abs(cal_idx - ndvi_idx) <= 1:
                    GROWTH_STAGE = ndvi_stage
                    data_quality["growth_stage_source"] = (
                        f"ndvi_ts_refined:{crop_name}:DOY{DOY}"
                    )
                else:
                    data_quality["warnings"].append(
                        f"NDVI stage '{ndvi_stage}' disagreed with calendar "
                        f"stage '{GROWTH_STAGE}' by >1 step — calendar kept."
                    )
        except Exception as e:
            print(f"{_WARN}[WARNING][S2-TS] NDVI time series failed — using calendar stage. ({e}){_RESET}")
            data_quality["warnings"].append(
                f"S2 NDVI time-series unavailable — growth stage from crop calendar: {e}"
            )

    # ── SOIL TYPE (SoilGrids) ─────────────────
    try:
        sg_resp = requests.get(
            "https://rest.isric.org/soilgrids/v2.0/properties/query",
            params={
                "lon": LON, "lat": LAT,
                "property": ["clay", "sand"],
                "depth": ["0-5cm", "5-15cm", "15-30cm"],
                "value": "mean",
            },
            timeout=20,
        )
        sg_data = sg_resp.json()

        def _sg_mean(prop_name: str) -> float | None:
            for layer in sg_data["properties"]["layers"]:
                if layer["name"] == prop_name:
                    vals = [
                        d["values"].get("mean")
                        for d in layer["depths"]
                        if d["values"].get("mean") is not None
                    ]
                    return float(np.mean(vals)) / 10.0 if vals else None
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
            data_quality["soil_type_source"] = (
                f"SoilGrids:clay={clay_pct:.1f}%:sand={sand_pct:.1f}%"
            )
    except Exception as e:
        print(f"{_WARN}[WARNING][SoilGrids] API error — defaulting to loam. ({e}){_RESET}")
        data_quality["warnings"].append(
            f"SoilGrids unavailable — soil type defaulting to loam: {e}"
        )

    # ── SENTINEL-3 (LST) ──────────────────────
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
                    data_collection=SENTINEL3_CDSE,
                    time_interval=TIME_INTERVAL,
                )],
                responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
                bbox=BBOX, size=(50, 50), config=config,
            )
            LST_K = float(np.nanmean(req.get_data()[0][:, :, 0]))
            data_quality["lst_source"] = "Sentinel-3"
        except Exception as e:
            print(f"{_WARN}[WARNING][S3] No LST data — using default 300.15 K. ({e}){_RESET}")
            data_quality["warnings"].append(
                f"S3 LST unavailable — using default 300.15 K: {e}"
            )

    # ── SENTINEL-1 (SOIL MOISTURE) ────────────
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
                    data_collection=SENTINEL1_CDSE,
                    time_interval=TIME_INTERVAL,
                )],
                responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
                # FIXED: S1 fetched at same bbox size as S2 — eliminates resolution mismatch
                bbox=BBOX, size=size, config=config,
            )
            s1_data = req.get_data()[0]
            VV = s1_data[:, :, 0]

            # FIXED: VV_dry and VV_sat derived from scene percentiles instead of hardcoded
            #        constants; 5th/95th percentile of positive backscatter values gives
            #        scene-relative dry/saturated anchors without site calibration.
            VV_valid = VV[VV > 0].ravel()
            if len(VV_valid) >= 10:
                VV_dry = float(np.percentile(VV_valid, 5))
                VV_sat = float(np.percentile(VV_valid, 95))
                data_quality["sm_source"] = (
                    f"Sentinel-1:VV_dry={VV_dry:.4f}:VV_sat={VV_sat:.4f}"
                )
            else:
                VV_dry, VV_sat = 0.01, 0.32
                print(f"{_WARN}[WARNING][S1] VV scene too sparse — using hardcoded dry/sat. {_RESET}")
                data_quality["warnings"].append(
                    "S1 VV scene had <10 valid pixels — hardcoded VV_dry=0.01 VV_sat=0.32"
                )
                data_quality["sm_source"] = "Sentinel-1:hardcoded_thresholds"

            SM_2d       = np.clip((VV - VV_dry) / (VV_sat - VV_dry + 1e-9), 0, 1)
            SM_FRACTION = float(np.nanmean(SM_2d))
            SM_SOURCE   = "Sentinel-1"
        except Exception as e:
            print(f"{_WARN}[WARNING][S1] No soil moisture data — DR_PREV carried from caller. ({e}){_RESET}")
            data_quality["warnings"].append(
                f"S1 unavailable — SM fraction defaulting to 0.50; "
                f"DR_PREV carried from caller ({dr_prev:.2f} mm): {e}"
            )

    # ── WEATHER (OPEN-METEO) ──────────────────
    today_date = date.today()
    api_url = (
        "https://archive-api.open-meteo.com/v1/archive"
        if target_date <= today_date
        else "https://api.open-meteo.com/v1/forecast"
    )
    try:
        response = requests.get(
            api_url,
            params={
                "latitude":  LAT,
                "longitude": LON,
                "hourly": (
                    "temperature_2m,relative_humidity_2m,windspeed_10m,"
                    "surface_pressure,shortwave_radiation,precipitation"
                ),
                "start_date": DATE_TARGET,
                "end_date":   DATE_TARGET,
                "timezone":   "auto",
            },
            timeout=30,
        )
        resp_json = response.json()
        weather   = resp_json["hourly"]

        # FIXED: elevation extracted from Open-Meteo response — no DEM call needed
        if "elevation" in resp_json:
            ELEVATION_M = float(resp_json["elevation"])
            data_quality["elevation_source"] = f"Open-Meteo:{ELEVATION_M:.0f}m"
        else:
            data_quality["warnings"].append(
                "Open-Meteo response missing 'elevation' field"
            )

        T           = float(np.mean(weather["temperature_2m"]))
        RH          = float(np.mean(weather["relative_humidity_2m"]))
        Td          = T - (100 - RH) / 5
        u10         = float(np.mean(weather["windspeed_10m"])) / 3.6
        P_atm       = float(np.mean(weather["surface_pressure"])) / 10
        Rs          = float(np.sum(weather["shortwave_radiation"])) * 3600 / 1e6
        RAINFALL_MM = float(np.sum(weather["precipitation"]))
        data_quality["weather_source"] = "Open-Meteo"
    except Exception as e:
        print(f"{_ERR}[WARNING][Weather] API error — using hardcoded Mediterranean defaults. ({e}){_RESET}")
        data_quality["warnings"].append(
            f"Open-Meteo unavailable — hardcoded fallback weather applied "
            f"(unreliable outside Mediterranean climate): {e}"
        )
        T = 28.5; Td = 14.5; u10 = 2.0; P_atm = 97.5; Rs = 26.0; RAINFALL_MM = 0.0

    if ELEVATION_M is None:
        ELEVATION_M = 280.0
        data_quality["elevation_source"] = "hardcoded_280m"
        data_quality["warnings"].append(
            "Elevation unavailable from all sources — hardcoded to 280 m; "
            "Rs0 and P_atm will be inaccurate at other altitudes."
        )

    # ── ET₀ (FAO-56 Penman-Monteith) ─────────
    es    = fao.svp_from_t(T)
    ea    = fao.avp_from_tdew(Td)
    # u2: Open-Meteo always delivers windspeed_10m, so z=10 is fixed and correct here.
    # FAO-56 eq.47: u2 = uz * 4.87 / ln(67.8*z - 5.42), z=10 → denominator ≈ 6.51
    u2    = u10 * 4.87 / math.log(67.8 * 10 - 5.42)
    Delta = fao.delta_svp(T)
    gamma = fao.psy_const(P_atm)

    lat_rad = math.radians(LAT)
    dr  = fao.inv_rel_dist_earth_sun(DOY)
    sd  = fao.sol_dec(DOY)
    sha = fao.sunset_hour_angle(lat_rad, sd)
    Ra  = fao.et_rad(lat_rad, sd, sha, dr)
    Rs0 = (0.75 + 2e-5 * ELEVATION_M) * Ra

    # FIXED: alpha_mean default is now 0.23 (FAO-56 reference surface)
    Rns = (1 - alpha_mean) * Rs
    # FIXED: pyeto net_out_lw_rad expects Kelvin — T+273.15 confirmed correct
    Rnl = fao.net_out_lw_rad(T + 273.15, T + 273.15, ea, Rs, Rs0)
    Rn  = Rns - Rnl

    # FIXED: G=0 for daily ET₀ per FAO-56 sect.4 (daily soil heat flux is negligible).
    #        Previous SEBAL/METRIC formula mixed instantaneous thermal flux with daily
    #        aggregated radiation — incompatible timescales, now removed.
    G = 0.0

    # FIXED: fao56_penman_monteith expects t in Kelvin — T+273.15 confirmed correct
    ET0 = fao.fao56_penman_monteith(
        net_rad=Rn, t=T + 273.15, ws=u2,
        svp=es, avp=ea, delta_svp=Delta, psy=gamma, shf=G,
    )

    # ── ETc ───────────────────────────────────
    Kc  = KC_LIST[STAGE_TO_IDX.get(GROWTH_STAGE, 1)]
    ETc = ET0 * Kc

    # FIXED: TAW now computed dynamically from soil FC/WP and crop root depth
    #        instead of three hardcoded constants that assumed a fixed 1 m root zone.
    root_depth = ROOT_DEPTH_TABLE.get(crop_name, ROOT_DEPTH_TABLE["Default"])
    sp         = SOIL_PARAMS.get(SOIL_TYPE, SOIL_PARAMS["loam"])
    TAW        = (sp["FC"] - sp["WP"]) * root_depth * 1000  # mm

    if SM_SOURCE == "Sentinel-1":
        DR_PREV = TAW * (1.0 - SM_FRACTION)

    P_eff    = RAINFALL_MM
    Dr_today = float(np.clip(DR_PREV - P_eff + ETc, 0, TAW))
    IRRIGATION_L_M2 = max(0.0, Dr_today)

    # ── Per-pixel 2D irrigation (heatmap) ─────
    if alpha_2d is not None and NDVI_2d is not None:
        Rns_2d = (1.0 - alpha_2d) * Rs
        Rn_2d  = Rns_2d - Rnl
        ET0_2d = fao.fao56_penman_monteith(
            net_rad=Rn_2d, t=T + 273.15, ws=u2,
            svp=es, avp=ea, delta_svp=Delta, psy=gamma, shf=0.0,
        )

        # FIXED: per-pixel Kc derived from NDVI using Allen et al. (2011) METRIC linear
        #        relationship. Previously NDVI_2d was fetched but never used after G=0
        #        removed the only SEBAL formula that referenced it, leaving a scalar Kc
        #        applied uniformly — the primary cause of a flat irrigation grid.
        #        Bare soil (NDVI≈0.15) → Kc_ini; full canopy (NDVI≈0.80) → Kc_mid.
        NDVI_soil = 0.15
        NDVI_full = 0.80
        Kc_ini_val = KC_LIST[0]
        Kc_mid_val = KC_LIST[1]
        Kc_2d = Kc_ini_val + (Kc_mid_val - Kc_ini_val) * np.clip(
            (NDVI_2d - NDVI_soil) / (NDVI_full - NDVI_soil), 0.0, 1.0
        )
    else:
        # FIXED: explicit (height, width) shape derived from size to avoid ambiguity
        #        size = (width, height) from bbox_to_dimensions → numpy shape is reversed
        ET0_2d = np.full((size[1], size[0]), ET0, dtype=np.float32)
        Kc_2d  = np.full((size[1], size[0]), Kc,  dtype=np.float32)
        data_quality["warnings"].append(
            "S2 unavailable — per-pixel Kc cannot be computed; "
            "scalar Kc applied uniformly, irrigation grid will have no canopy-cover variation."
        )

    ETc_2d = ET0_2d * Kc_2d

    if SM_2d is not None:
        # FIXED: S1 now fetched at the same `size` as S2 — reshape is no longer needed
        #        in the normal path. Defensive resize retained for any edge-case mismatch.
        if SM_2d.shape != ETc_2d.shape:
            print(f"{_WARN}[WARNING] SM_2d shape {SM_2d.shape} != ETc_2d shape "
                  f"{ETc_2d.shape} — bilinear resize applied.{_RESET}")
            data_quality["warnings"].append(
                f"SM shape mismatch {SM_2d.shape} vs {ETc_2d.shape} "
                f"— bilinear resize applied"
            )
            _sm_img = _Image.fromarray(SM_2d.astype(np.float32))
            _sm_rsz = _sm_img.resize(
                (ETc_2d.shape[1], ETc_2d.shape[0]), _Image.BILINEAR
            )
            SM_2d = np.array(_sm_rsz)
        DR_PREV_2d = TAW * (1.0 - SM_2d)
    else:
        DR_PREV_2d = np.full_like(ETc_2d, DR_PREV)

    Dr_today_2d   = np.clip(DR_PREV_2d - P_eff + ETc_2d, 0, TAW)
    IRRIGATION_2d = np.maximum(0.0, Dr_today_2d)

    # ── MASK GRID TO ORIGINAL IRREGULAR FIELD ──
    polygon = [(p["lng"], p["lat"]) for p in coordinates]

    rows = IRRIGATION_2d.shape[0]
    cols = IRRIGATION_2d.shape[1]

    masked_grid = []

    for r in range(rows):
        row_data = []

        for c in range(cols):
            lng = west + (c + 0.5) / cols * (east - west)
            lat = north - (r + 0.5) / rows * (north - south)

            if point_in_polygon(lng, lat, polygon):
                row_data.append(round(float(IRRIGATION_2d[r][c]), 2))
            else:
                row_data.append(None)

        masked_grid.append(row_data)

    return {
        "ETo": round(float(ET0), 4),
        "irrigation_avg": round(float(IRRIGATION_L_M2), 4),
        "irrigation_grid": masked_grid,
        "data_quality": data_quality,
    }


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def parse_input(raw_json: str) -> tuple[list[dict], str, list[float]]:
    """Return (coordinates, crop_name, kc_list) from frontend JSON.

    Expected format:
        {"coordinates":[{"lat":41.7,"lng":21.5}, ...],
         "crop_type": {"Cabbage": [0.7, 1.05, 0.95]}}
    """
    data      = json.loads(raw_json)
    coords    = data["coordinates"]
    crop_type = data.get("crop_type", {"Default": [1.0, 1.0, 1.0]})
    crop_name = list(crop_type.keys())[0]
    kc_list   = [float(v) for v in list(crop_type.values())[0]]
    return coords, crop_name, kc_list


def bbox_from_coordinates(coords: list[dict]) -> tuple[float, float, float, float]:
    lats = [c["lat"] for c in coords]
    lngs = [c["lng"] for c in coords]
    return min(lngs), min(lats), max(lngs), max(lats)


# ADD THIS NEW FUNCTION
def point_in_polygon(x: float, y: float, polygon: list[tuple]) -> bool:
    inside = False
    j = len(polygon) - 1

    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)):
            cross = (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
            if x < cross:
                inside = not inside

        j = i

    return inside