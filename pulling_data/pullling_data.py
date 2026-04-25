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

# CONFIGURATION

# NOT LOGGED-IN

# config = SHConfig()
# config.sh_client_id = getpass.getpass("Enter your SentinelHub client id")
# config.sh_client_secret = getpass.getpass("Enter your SentinelHub client secret")
# config.sh_token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
# config.sh_base_url = "https://sh.dataspace.copernicus.eu"
# config.save("cdse")

# ALREADY LOGGED-IN
config = SHConfig()

SENTINEL2_CDSE = DataCollection.SENTINEL2_L2A.define_from(
    "SENTINEL2_L2A_CDSE",
    service_url="https://sh.dataspace.copernicus.eu"
)

SENTINEL3_CDSE = DataCollection.SENTINEL3_SLSTR.define_from(
    "SENTINEL3_SLSTR_CDSE",
    service_url="https://sh.dataspace.copernicus.eu"
)

# CUSTOM INPUT AREA + DATE

west = 21.705
south = 42.118
east = 21.715
north = 42.126

date_target = None   # None = today, or "2026-04-24"

# AUTO DATE HANDLING

if date_target is None:
    target_date = date.today()
else:
    target_date = datetime.strptime(date_target, "%Y-%m-%d").date()

DATE_TARGET = target_date.strftime("%Y-%m-%d")

TIME_INTERVAL = (
    (target_date - timedelta(days=10)).strftime("%Y-%m-%d"),
    DATE_TARGET
)

DOY = target_date.timetuple().tm_yday

# AREA HANDLING

BBOX = BBox(bbox=[west, south, east, north], crs=CRS.WGS84)

LAT = (south + north) / 2
LON = (west + east) / 2

ELEVATION_M = 280.0
RESOLUTION = 10

size = bbox_to_dimensions(BBOX, resolution=RESOLUTION)

# DEFAULT VALUES (IN CASE OF NO DATA)

alpha_mean = 0.19
NDVI_mean = 0.65
LST_K = 300.15

# SENTINEL-2 (NDVI + ALBEDO)

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
            responses=[
                SentinelHubRequest.output_response(
                    "default", MimeType.TIFF
                )
            ],
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

        alpha = (
            0.356 * B02 +
            0.130 * B04 +
            0.373 * B08 +
            0.085 * B11 +
            0.072 * B12 -
            0.0018
        )

        alpha_mean = np.nanmean(np.clip(alpha, 0, 1))

    except:
        pass

# SENTINEL-3 (LAND SURFACE TEMPERATURE)

if config.sh_client_id and config.sh_client_secret:

    evalscript_s3 = """
    //VERSION=3
    function setup() {
      return {
        input: [{
          bands:["LST"],
          units:"KELVIN"
        }],
        output:{bands:1,sampleType:"FLOAT32"}
      };
    }

    function evaluatePixel(s){
      return [s.LST];
    }
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
            responses=[
                SentinelHubRequest.output_response(
                    "default", MimeType.TIFF
                )
            ],
            bbox=BBOX,
            size=(50, 50),
            config=config
        )

        data = request.get_data()[0]
        LST_K = np.nanmean(data[:, :, 0])

    except:
        pass

# OPEN-METEO WEATHER

today = date.today()

if target_date <= today:
    api_url = "https://archive-api.open-meteo.com/v1/archive"
else:
    api_url = "https://api.open-meteo.com/v1/forecast"

try:
    response = requests.get(
        api_url,
        params={
            "latitude": LAT,
            "longitude": LON,
            "hourly":
                "temperature_2m,"
                "relative_humidity_2m,"
                "windspeed_10m,"
                "surface_pressure,"
                "shortwave_radiation",
            "start_date": DATE_TARGET,
            "end_date": DATE_TARGET,
            "timezone": "auto"
        },
        timeout=30
    )

    weather = response.json()["hourly"]

    T = np.mean(weather["temperature_2m"])
    RH = np.mean(weather["relative_humidity_2m"])
    Td = T - (100 - RH) / 5

    u10 = np.mean(weather["windspeed_10m"]) / 3.6
    P = np.mean(weather["surface_pressure"]) / 10
    Rs = np.sum(weather["shortwave_radiation"]) * 3600 / 1e6

except:
    T = 28.5
    Td = 14.5
    u10 = 2.0
    P = 97.5
    Rs = 26.0

# CALCULATIONS

es = fao.svp_from_t(T)
ea = fao.avp_from_tdew(Td)
VPD = es - ea

u2 = u10 * 4.87 / math.log(67.8 * 10 - 5.42)

Delta = fao.delta_svp(T)
gamma = fao.psy_const(P)

lat_rad = math.radians(LAT)

dr = fao.inv_rel_dist_earth_sun(DOY)
sd = fao.sol_dec(DOY)
sha = fao.sunset_hour_angle(lat_rad, sd)

Ra = fao.et_rad(lat_rad, sd, sha, dr)

Rs0 = (0.75 + 2e-5 * ELEVATION_M) * Ra

Rns = (1 - alpha_mean) * Rs

Rnl = fao.net_out_lw_rad(
    T + 273.15,
    T + 273.15,
    ea,
    Rs,
    Rs0
)

Rn = Rns - Rnl

G = Rn * (
    (LST_K - 273.15) *
    (0.0038 + 0.0074 * alpha_mean) *
    (1 - 0.98 * NDVI_mean ** 4)
)

G = 0.1 * G

# ET0

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

# OUTPUT

params = {
    "T (Mean daily air temperature)": f"{T:.2f} °C",
    "Rn (Net radiation)": f"{Rn:.2f} MJ/m²/day",
    "G (Soil heat flux)": f"{G:.2f} MJ/m²/day",
    "es (Saturation vapor pressure)": f"{es:.4f} kPa",
    "ea (Actual vapor pressure)": f"{ea:.4f} kPa",
    "(es - ea) Vapor pressure deficit": f"{VPD:.4f} kPa",
    "u₂ (Wind speed at 2 m)": f"{u2:.2f} m/s",
    "Δ (Slope of SVP curve)": f"{Delta:.4f} kPa/°C",
    "γ (Psychrometric constant)": f"{gamma:.5f} kPa/°C"
}

for name, value in params.items():
    print(f"{name:35} {value}")

print(f"\nET₀ (Reference evapotranspiration): {ET0:.2f} mm/day")

df = pd.DataFrame([
    {"Parameter": "T (Mean daily air temperature)", "Value": f"{T:.2f}", "Unit": "°C"},
    {"Parameter": "Rn (Net radiation)", "Value": f"{Rn:.2f}", "Unit": "MJ/m²/day"},
    {"Parameter": "G (Soil heat flux)", "Value": f"{G:.2f}", "Unit": "MJ/m²/day"},
    {"Parameter": "es (Saturation vapor pressure)", "Value": f"{es:.4f}", "Unit": "kPa"},
    {"Parameter": "ea (Actual vapor pressure)", "Value": f"{ea:.4f}", "Unit": "kPa"},
    {"Parameter": "(es - ea) Vapor pressure deficit", "Value": f"{VPD:.4f}", "Unit": "kPa"},
    {"Parameter": "u₂ (Wind speed at 2 m)", "Value": f"{u2:.2f}", "Unit": "m/s"},
    {"Parameter": "Δ (Slope of SVP curve)", "Value": f"{Delta:.4f}", "Unit": "kPa/°C"},
    {"Parameter": "γ (Psychrometric constant)", "Value": f"{gamma:.5f}", "Unit": "kPa/°C"},
    {"Parameter": "ET₀ (Reference ET)", "Value": f"{ET0:.2f}", "Unit": "mm/day"},
])