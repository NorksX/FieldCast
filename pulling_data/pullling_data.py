import math
import requests
import numpy as np
import pandas as pd

import pyeto.fao as fao

from sentinelhub import (
    SHConfig, BBox, CRS, DataCollection,
    SentinelHubRequest, MimeType, bbox_to_dimensions,
)

# ══════════════════════════════════════════════════════════════
# 0.  CONFIGURATION
# ══════════════════════════════════════════════════════════════

config = SHConfig()

SENTINEL2_CDSE = DataCollection.SENTINEL2_L2A.define_from(
    "SENTINEL2_L2A_CDSE",
    service_url="https://sh.dataspace.copernicus.eu"
)

coordinates = []

# Area of interest (Kumanovo, North Macedonia)
BBOX = BBox(bbox=[21.705, 42.118, 21.715, 42.126], crs=CRS.WGS84)
RESOLUTION = 10
TIME_INTERVAL = ("2024-07-01", "2024-07-20")
DATE_TARGET = "2024-07-12"

# Location parameters
LAT = 42.122
LON = 21.710
ELEVATION_M = 280.0
DOY = 193  # Day of year for July 12

def celsius_to_kelvin(temp_c):
    return temp_c + 273.15

def wind_speed_2m(u10):
    return u10 * 4.87 / math.log(67.8 * 10 - 5.42)

def penman_monteith_et0(Rn, T, u2, es, ea, Delta, gamma, G):
    # Convert temperature to Kelvin for some calculations if needed
    T_K = celsius_to_kelvin(T)

    # Latent heat of vaporization (lambda) - FAO-56 eq. 3-1
    # lambda = 2.45 MJ/kg at 20°C, but temperature dependent:
    lambda_v = 2.501 - 0.002361 * T  # MJ/kg

    # Penman-Monteith equation (FAO-56 eq. 6)
    # ET0 = [0.408 * Delta * (Rn - G) + gamma * (900/(T+273)) * u2 * (es - ea)] /
    #       [Delta + gamma * (1 + 0.34 * u2)]

    numerator = (0.408 * Delta * (Rn - G) +
                 gamma * (900 / (T + 273)) * u2 * (es - ea))
    denominator = Delta + gamma * (1 + 0.34 * u2)

    ET0 = numerator / denominator
    return max(0, ET0)  # Ensure non-negative

size = bbox_to_dimensions(BBOX, resolution=RESOLUTION)
print(f"AOI: {size[0]} × {size[1]} px @ {RESOLUTION} m")
print(f"Target date: {DATE_TARGET}\n")

# ══════════════════════════════════════════════════════════════
# 1.  SENTINEL-2 DATA (for albedo and NDVI)
# ══════════════════════════════════════════════════════════════

alpha_mean = 0.19  # Default albedo for agricultural land
NDVI_mean = 0.65   # Default NDVI

if config.sh_client_id and config.sh_client_secret:
    EVALSCRIPT = """
    //VERSION=3
    function setup() {
        return {
            input: [{
                bands: ["B02", "B03", "B04", "B08", "B11", "B12"],
                units: "REFLECTANCE"
            }],
            output: { bands: 6, sampleType: "FLOAT32" }
        };
    }
    function evaluatePixel(s) {
        return [s.B02, s.B03, s.B04, s.B08, s.B11, s.B12];
    }
    """

    try:
        print("Fetching Sentinel-2 data...")
        request = SentinelHubRequest(
            evalscript=EVALSCRIPT,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=SENTINEL2_CDSE,
                    time_interval=TIME_INTERVAL,
                    maxcc=0.3,
                    mosaicking_order="leastCC",
                )
            ],
            responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
            bbox=BBOX,
            size=size,
            config=config,
        )

        data = request.get_data()[0]

        if data is not None and len(data.shape) == 3:
            B02, B03, B04 = data[:,:,0], data[:,:,1], data[:,:,2]
            B08, B11, B12 = data[:,:,3], data[:,:,4], data[:,:,5]

            # NDVI
            NDVI = np.clip((B08 - B04) / (B08 + B04 + 1e-9), -1, 1)
            NDVI_mean = np.nanmean(NDVI)

            # Broadband albedo (Liang, 2001)
            alpha = (0.356*B02 + 0.130*B04 + 0.373*B08 +
                    0.085*B11 + 0.072*B12 - 0.0018)
            alpha = np.clip(alpha, 0.0, 1.0)
            alpha_mean = np.nanmean(alpha)

            print(f"✓ NDVI: {NDVI_mean:.3f} | Albedo: {alpha_mean:.3f}")
    except Exception as e:
        print(f"⚠ Using default values (Sentinel-2 error: {e})")

# ══════════════════════════════════════════════════════════════
# 2.  OPEN-METEO WEATHER DATA
# ══════════════════════════════════════════════════════════════

try:
    resp = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": LAT,
            "longitude": LON,
            "hourly": "temperature_2m,relative_humidity_2m,windspeed_10m,"
                      "surface_pressure,shortwave_radiation",
            "start_date": DATE_TARGET,
            "end_date": DATE_TARGET,
            "timezone": "Europe/Skopje",
        },
        timeout=30,
    )
    resp.raise_for_status()
    om = resp.json()["hourly"]

    # Calculate daily values
    T_C = np.nanmean(om["temperature_2m"])
    RH = np.nanmean(om["relative_humidity_2m"])
    Td_C = T_C - (100 - RH) / 5.0  # Dewpoint approximation
    u10 = np.nanmean(om["windspeed_10m"]) / 3.6  # km/h to m/s
    P_hPa = np.nanmean(om["surface_pressure"])
    Rs_in = np.nansum(om["shortwave_radiation"]) * 3600 / 1e6

    print(f"Weather: {T_C:.1f}°C | RH: {RH:.0f}% | Wind: {u10:.1f} m/s | Rs: {Rs_in:.1f} MJ/m²")

except Exception as e:
    print(f"⚠ Using default weather values ({e})")
    T_C, Td_C, u10, P_hPa, Rs_in = 28.5, 14.5, 2.0, 975.0, 26.0

# ══════════════════════════════════════════════════════════════
# 3.  CALCULATE REQUIRED PARAMETERS
# ══════════════════════════════════════════════════════════════

# Calculate basic parameters
T = T_C  # Mean daily air temperature
es = fao.svp_from_t(T_C)  # Saturation vapor pressure (kPa)
ea = fao.avp_from_tdew(Td_C)  # Actual vapor pressure (kPa)
VPD = es - ea  # Vapor pressure deficit (kPa)
u2 = wind_speed_2m(u10)  # Wind speed at 2 m (m/s)
Delta = fao.delta_svp(T_C)  # Slope of SVP curve (kPa/°C)
P_atm = P_hPa / 10.0  # Atmospheric pressure (kPa)
gamma = fao.psy_const(P_atm)  # Psychrometric constant (kPa/°C)

# Calculate Net Radiation (Rn)
# Step 1: Extraterrestrial radiation (Ra)
lat_rad = math.radians(LAT)
dr = fao.inv_rel_dist_earth_sun(DOY)
sd = fao.sol_dec(DOY)
sha = fao.sunset_hour_angle(lat_rad, sd)
Ra = fao.et_rad(lat_rad, sd, sha, dr)  # MJ/m²/day

# Step 2: Clear-sky radiation (Rs0) - FAO-56 eq. 37
Rs0 = (0.75 + 2e-5 * ELEVATION_M) * Ra

# Step 3: Net shortwave radiation (Rns) - FAO-56 eq. 38
Rns = (1 - alpha_mean) * Rs_in

# Step 4: Net longwave radiation (Rnl) - FAO-56 eq. 39
sigma = 4.903e-9  # Stefan-Boltzmann constant (MJ/K⁴/m²/day)
T_kelvin = celsius_to_kelvin(T_C)

# Calculate the ratio Rs/Rs0 (limited to 0.3-1.0 as per FAO-56)
Rs_Rs0_ratio = Rs_in / Rs0 if Rs0 > 0 else 0.5
Rs_Rs0_ratio = max(0.3, min(1.0, Rs_Rs0_ratio))

# Rnl = σ * T⁴ * (0.34 - 0.14√ea) * (1.35 * Rs/Rs0 - 0.35)
Rnl = sigma * (T_kelvin**4) * (0.34 - 0.14 * math.sqrt(ea)) * (1.35 * Rs_Rs0_ratio - 0.35)
Rnl = max(0, Rnl)  # Ensure non-negative

# Step 5: Net radiation (Rn) - FAO-56 eq. 40
Rn = Rns - Rnl

# Soil heat flux (G) - Negligible for daily periods (FAO-56)
G = 0.0

# ══════════════════════════════════════════════════════════════
# 4.  DISPLAY RESULTS
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("REQUIRED ET₀ PARAMETERS")
print("=" * 60)

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

print("=" * 60)

# Calculate ET₀ using Penman-Monteith
ET0 = penman_monteith_et0(Rn, T_C, u2, es, ea, Delta, gamma, G)

print(f"\nET₀ (Reference evapotranspiration): {ET0:.2f} mm/day")
print("=" * 60)

# Save to CSV
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

df.to_csv("et0_parameters.csv", index=False)
print("\n✓ Parameters saved to: et0_parameters.csv")

# Display additional diagnostic info
print("\n" + "=" * 60)
print("DIAGNOSTIC INFORMATION")
print("=" * 60)
print(f"Extraterrestrial radiation (Ra):     {Ra:.2f} MJ/m²/day")
print(f"Clear-sky radiation (Rs0):           {Rs0:.2f} MJ/m²/day")
print(f"Rs/Rs0 ratio:                        {Rs_Rs0_ratio:.3f}")
print(f"Net shortwave (Rns):                 {Rns:.2f} MJ/m²/day")
print(f"Net longwave (Rnl):                  {Rnl:.2f} MJ/m²/day")
print(f"Surface albedo:                      {alpha_mean:.3f}")
print(f"NDVI:                                {NDVI_mean:.3f}")
print("=" * 60)

print("\n✅ ET₀ calculation completed successfully!")