"""
download_era5_land_monthly.py

Great Salt Lake ERA5-Land monthly evaporation drivers (1950 to last full year).

Uses the ERA5-Land MONTHLY MEANS product, which (unlike the daily-statistics
product) includes accumulated variables: radiation, precipitation, and
evaporation. Output is monthly, matching processed_data/gsl_monthly_master.csv.

Variables downloaded
- Air: 2 m temperature, 2 m dewpoint, surface pressure, 10 m u/v wind
- Surface: skin temperature
- Radiation: downward shortwave and longwave, net shortwave and longwave
- Water: total precipitation, total evaporation, potential evaporation

Derived
- Saturation and actual vapor pressure, vapor pressure deficit, relative
  humidity (FAO-56 equations, from monthly mean T and Td)
- Net radiation, wind speed

Known limitations (read before modeling)
- Wind speed is computed from the MEAN u and v components, so it is a
  vector-mean speed and is biased low compared with averaged station
  wind speeds. Treat it as an index or calibrate it against GHCNh stations.
- Monthly means have no daily Tmax/Tmin, so vapor pressure deficit uses
  mean temperature (FAO-56 prefers averaging es(Tmax) and es(Tmin)).
- ERA5-Land is a land model with a simple freshwater lake scheme. It does
  not represent a hypersaline lake with a changing shoreline, so its own
  evaporation fields are a comparison, not ground truth.
- potential_evaporation in ERA5-Land is known to run high.

Spatial averaging
- A box around the lake (AREA) is downloaded at 0.1 degree resolution.
- Only grid cells whose long-term mean surface pressure is at least
  MIN_SURFACE_PRESSURE_HPA are averaged. This drops mountain cells
  (Wasatch, Oquirrh) and keeps cells near lake level (~1,280 m, ~870 hPa).

Setup
1. CDS account, with the ERA5-Land monthly licence accepted:
   https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-monthly-means
2. API key in ~/.cdsapirc: https://cds.climate.copernicus.eu/how-to-api
3. pip install cdsapi xarray netcdf4 pandas numpy

Downloads are cached in raw_data/era5_cache/ in multi-year chunks, so a
failed or interrupted run resumes where it stopped.

Output
    raw_data/era5_land_monthly_weather.csv
"""

import shutil
import zipfile
from datetime import date
from pathlib import Path

import cdsapi
import numpy as np
import pandas as pd
import xarray as xr


# ------------------------------------------------------------
# 1. Settings and file locations
# ------------------------------------------------------------

START_YEAR = 1950  # first year of ERA5-Land
END_YEAR = date.today().year - 1  # last complete year
CHUNK_YEARS = 5  # years per CDS request

# CDS order: North, West, South, East. Covers the lake and its shore.
AREA = [41.75, -113.15, 40.60, -111.85]

# Keep grid cells at or below roughly 1,450 m elevation.
MIN_SURFACE_PRESSURE_HPA = 850.0

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
RAW_DATA_FOLDER = PROJECT_FOLDER / "raw_data"
CACHE_FOLDER = RAW_DATA_FOLDER / "era5_cache"
OUTPUT_FILE = RAW_DATA_FOLDER / "era5_land_monthly_weather.csv"

DATASET = "reanalysis-era5-land-monthly-means"

# CDS request name -> short name used inside the NetCDF files
VARIABLES = {
    "2m_temperature": "t2m",
    "2m_dewpoint_temperature": "d2m",
    "surface_pressure": "sp",
    "10m_u_component_of_wind": "u10",
    "10m_v_component_of_wind": "v10",
    "skin_temperature": "skt",
    "surface_solar_radiation_downwards": "ssrd",
    "surface_thermal_radiation_downwards": "strd",
    "surface_net_solar_radiation": "ssr",
    "surface_net_thermal_radiation": "str",
    "total_precipitation": "tp",
    "total_evaporation": "e",
    "potential_evaporation": "pev",
}

SECONDS_PER_DAY = 86_400


# ------------------------------------------------------------
# 2. Download helpers (cached, resumable)
# ------------------------------------------------------------

def chunk_folder(first_year, last_year):
    return CACHE_FOLDER / f"era5_land_monthly_{first_year}_{last_year}"


def download_chunk(client, first_year, last_year):
    """Download one multi-year chunk into its cache folder, unless already there."""
    folder = chunk_folder(first_year, last_year)
    if folder.exists() and any(folder.glob("*.nc")):
        print(f"  Cached: {first_year}-{last_year}")
        return folder

    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": list(VARIABLES),
        "year": [str(year) for year in range(first_year, last_year + 1)],
        "month": [f"{month:02d}" for month in range(1, 13)],
        "time": ["00:00"],
        "area": AREA,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }

    CACHE_FOLDER.mkdir(parents=True, exist_ok=True)
    part_file = CACHE_FOLDER / f"{folder.name}.part"
    print(f"  Requesting {first_year}-{last_year} from CDS (may queue)...")
    client.retrieve(DATASET, request).download(str(part_file))

    # Write into a temporary folder, then rename, so a crash never leaves a
    # half-finished chunk that looks cached.
    staging = CACHE_FOLDER / f"{folder.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    # CDS returns a ZIP when instantaneous and accumulated variables are
    # split into separate NetCDF files, even with "unarchived".
    if zipfile.is_zipfile(part_file):
        with zipfile.ZipFile(part_file) as archive:
            for member in archive.namelist():
                if member.lower().endswith(".nc"):
                    (staging / Path(member).name).write_bytes(archive.read(member))
        part_file.unlink()
    else:
        part_file.replace(staging / f"{folder.name}.nc")

    staging.replace(folder)
    return folder


def open_chunk(folder):
    """Open and merge every NetCDF in a chunk folder into one Dataset."""
    datasets = []
    for path in sorted(folder.glob("*.nc")):
        with xr.open_dataset(path) as dataset:
            dataset = dataset.load()
        if "valid_time" in dataset.dims:
            dataset = dataset.rename({"valid_time": "time"})
        # Drop bookkeeping coordinates (number, expver) that block merging.
        extra = [name for name in dataset.coords if name not in dataset.dims]
        datasets.append(dataset.drop_vars(extra))
    return xr.merge(datasets, compat="override", join="outer")


# ------------------------------------------------------------
# 3. Download all chunks
# ------------------------------------------------------------

client = cdsapi.Client()
chunk_datasets = []

print(f"ERA5-Land monthly means, {START_YEAR}-{END_YEAR}")
for first_year in range(START_YEAR, END_YEAR + 1, CHUNK_YEARS):
    last_year = min(first_year + CHUNK_YEARS - 1, END_YEAR)
    folder = download_chunk(client, first_year, last_year)
    chunk_datasets.append(open_chunk(folder))

era5 = xr.concat(chunk_datasets, dim="time").sortby("time")
era5 = era5.sel(time=~era5.get_index("time").duplicated())

missing = [short for short in VARIABLES.values() if short not in era5]
if missing:
    raise RuntimeError(f"Variables missing from the CDS files: {missing}")


# ------------------------------------------------------------
# 4. Select lake-level grid cells and average them
# ------------------------------------------------------------

mean_pressure_hpa = era5["sp"].mean("time") / 100.0
has_data = era5["t2m"].notnull().any("time")
lake_level = has_data & (mean_pressure_hpa >= MIN_SURFACE_PRESSURE_HPA)

cells_total = int(has_data.size)
cells_with_data = int(has_data.sum())
cells_used = int(lake_level.sum())
print(
    f"\nGrid cells: {cells_total} in box, {cells_with_data} with data, "
    f"{cells_used} at lake level (>= {MIN_SURFACE_PRESSURE_HPA:.0f} hPa)"
)
if cells_used == 0:
    raise RuntimeError("No grid cells passed the elevation mask; check AREA.")

regional = era5[list(VARIABLES.values())].where(lake_level).mean(
    dim=["latitude", "longitude"], skipna=True
)
frame = regional.to_dataframe().reset_index()


# ------------------------------------------------------------
# 5. Convert units and derive evaporation drivers
# ------------------------------------------------------------

def saturation_vapor_pressure_kpa(temperature_c):
    """FAO-56 equation 11."""
    return 0.6108 * np.exp(17.27 * temperature_c / (temperature_c + 237.3))


# Monthly means are reported at the first of the month; the master table
# uses month-end dates.
month_start = pd.to_datetime(frame["time"]).dt.to_period("M").dt.to_timestamp()
days = month_start.dt.days_in_month

weather = pd.DataFrame({"Date": month_start + pd.offsets.MonthEnd(0)})

weather["ERA5_Temperature_C"] = frame["t2m"] - 273.15
weather["ERA5_Dew_Point_C"] = frame["d2m"] - 273.15
weather["ERA5_Skin_Temperature_C"] = frame["skt"] - 273.15
weather["ERA5_Surface_Pressure_hPa"] = frame["sp"] / 100.0

saturation = saturation_vapor_pressure_kpa(weather["ERA5_Temperature_C"])
actual = saturation_vapor_pressure_kpa(weather["ERA5_Dew_Point_C"])
weather["ERA5_Saturation_Vapor_Pressure_kPa"] = saturation
weather["ERA5_Actual_Vapor_Pressure_kPa"] = actual
weather["ERA5_Vapor_Pressure_Deficit_kPa"] = (saturation - actual).clip(lower=0)
weather["ERA5_Relative_Humidity_percent"] = (100.0 * actual / saturation).clip(0, 100)

weather["ERA5_Wind_U_m_s"] = frame["u10"]
weather["ERA5_Wind_V_m_s"] = frame["v10"]
# Vector-mean speed: biased low (see module docstring).
weather["ERA5_Wind_Vector_Speed_m_s"] = np.sqrt(frame["u10"] ** 2 + frame["v10"] ** 2)

# Radiation: monthly means of daily accumulations (J/m^2 per day) -> mean W/m^2.
weather["ERA5_Shortwave_Down_W_m2"] = frame["ssrd"] / SECONDS_PER_DAY
weather["ERA5_Longwave_Down_W_m2"] = frame["strd"] / SECONDS_PER_DAY
weather["ERA5_Net_Shortwave_W_m2"] = frame["ssr"] / SECONDS_PER_DAY
weather["ERA5_Net_Longwave_W_m2"] = frame["str"] / SECONDS_PER_DAY
weather["ERA5_Net_Radiation_W_m2"] = (
    weather["ERA5_Net_Shortwave_W_m2"] + weather["ERA5_Net_Longwave_W_m2"]
)

# Water: monthly means of daily accumulations (m per day) -> monthly total mm.
# ECMWF counts evaporation as negative (upward flux), so flip the sign to
# make evaporation positive.
meters_per_day_to_mm_per_month = 1000.0 * days
weather["ERA5_Precipitation_mm"] = frame["tp"] * meters_per_day_to_mm_per_month
weather["ERA5_Evaporation_mm"] = -frame["e"] * meters_per_day_to_mm_per_month
weather["ERA5_Potential_Evaporation_mm"] = -frame["pev"] * meters_per_day_to_mm_per_month

weather = weather.sort_values("Date").reset_index(drop=True)


# ------------------------------------------------------------
# 6. Save and report
# ------------------------------------------------------------

RAW_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
weather.to_csv(OUTPUT_FILE, index=False, date_format="%Y-%m-%d")

annual = weather.set_index("Date").resample("YE").agg({
    "ERA5_Temperature_C": "mean",
    "ERA5_Shortwave_Down_W_m2": "mean",
    "ERA5_Precipitation_mm": "sum",
    "ERA5_Evaporation_mm": "sum",
    "ERA5_Potential_Evaporation_mm": "sum",
})

print("\n----------------------------------------")
print("ERA5-Land monthly download complete")
print("----------------------------------------")
print(f"Monthly rows: {len(weather)}")
print(f"Date range: {weather['Date'].min():%Y-%m} to {weather['Date'].max():%Y-%m}")
print("\nLong-term annual means (sanity check):")
print(annual.mean().round(1).to_string())
print(f"\nSaved to: {OUTPUT_FILE}")
