"""
download_gridmet_daily.py

Great Salt Lake gridMET daily evaporation drivers (1979 to present).

gridMET (Abatzoglou 2013) is a 4 km daily dataset for the contiguous US.
For evaporation it fills the gaps in ERA5-Land monthly means:
- scalar 10 m wind speed (not a vector mean)
- daily maximum and minimum temperature and relative humidity
- shortwave radiation, vapor pressure deficit, specific humidity
- ASCE reference evapotranspiration (grass and alfalfa)

No account is needed. Data are subset on the server (THREDDS NCSS) to a box
around the lake, cached by variable in 5-year chunks, and averaged over
lake-level grid cells into one daily regional value per variable.

Lake-level cells
gridMET has no elevation file on its server, so mountain cells are removed
with a temperature proxy: a cell is kept when its long-term mean daily
maximum temperature is within MAX_COOLING_C of the warm lake-plain cells
(the 90th percentile in the box). 2 degrees C is roughly 300 m of climb.

Notes
- The most recent ~2 months are provisional and are re-downloaded each run.
- gridMET values over the lake are interpolated from land stations; they
  describe air over and around the lake, not lake-surface conditions.

Output
    raw_data/gridmet_daily_weather.csv
"""

import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
import xarray as xr


# ------------------------------------------------------------
# 1. Settings and file locations
# ------------------------------------------------------------

START_YEAR = 1979  # first year of gridMET
END_DATE = date.today() - timedelta(days=7)  # allow for gridMET's update lag
CHUNK_YEARS = 5

# Same box as the ERA5-Land script: North, West, South, East.
NORTH, WEST, SOUTH, EAST = 41.75, -113.15, 40.60, -111.85

MAX_COOLING_C = 2.0
WARM_REFERENCE_QUANTILE = 0.90

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
RAW_DATA_FOLDER = PROJECT_FOLDER / "raw_data"
CACHE_FOLDER = RAW_DATA_FOLDER / "gridmet_cache"
OUTPUT_FILE = RAW_DATA_FOLDER / "gridmet_daily_weather.csv"

NCSS_URL = "http://thredds.northwestknowledge.net:8080/thredds/ncss"
REQUEST_TIMEOUT_SECONDS = 300
MAX_ATTEMPTS = 3

# gridMET short name -> (variable name in the file, output column, conversion)
VARIABLES = {
    "tmmx": ("daily_maximum_temperature", "GRIDMET_Tmax_C", lambda x: x - 273.15),
    "tmmn": ("daily_minimum_temperature", "GRIDMET_Tmin_C", lambda x: x - 273.15),
    "rmax": ("daily_maximum_relative_humidity", "GRIDMET_RHmax_percent", None),
    "rmin": ("daily_minimum_relative_humidity", "GRIDMET_RHmin_percent", None),
    "sph": ("daily_mean_specific_humidity", "GRIDMET_Specific_Humidity_kg_kg", None),
    "vpd": ("daily_mean_vapor_pressure_deficit", "GRIDMET_VPD_kPa", None),
    "srad": ("daily_mean_shortwave_radiation_at_surface", "GRIDMET_Shortwave_Down_W_m2", None),
    "vs": ("daily_mean_wind_speed", "GRIDMET_Wind_Speed_m_s", None),
    "pr": ("precipitation_amount", "GRIDMET_Precipitation_mm", None),
    "pet": ("daily_mean_reference_evapotranspiration_grass", "GRIDMET_Reference_ET_Grass_mm", None),
    "etr": ("daily_mean_reference_evapotranspiration_alfalfa", "GRIDMET_Reference_ET_Alfalfa_mm", None),
}


# ------------------------------------------------------------
# 2. Download helpers (cached, resumable)
# ------------------------------------------------------------

def year_chunks():
    for first_year in range(START_YEAR, END_DATE.year + 1, CHUNK_YEARS):
        yield first_year, min(first_year + CHUNK_YEARS - 1, END_DATE.year)


def download_chunk(session, short_name, first_year, last_year):
    """Download one variable for a span of years, unless already cached."""
    file_variable = VARIABLES[short_name][0]
    target = CACHE_FOLDER / f"gridmet_{short_name}_{first_year}_{last_year}.nc"

    # Chunks that reach the current year hold provisional data; refresh them.
    is_final = last_year < END_DATE.year
    if target.exists() and is_final:
        return target

    end = min(date(last_year, 12, 31), END_DATE)
    params = {
        "var": file_variable,
        "north": NORTH,
        "west": WEST,
        "south": SOUTH,
        "east": EAST,
        "time_start": f"{first_year}-01-01T00:00:00Z",
        "time_end": f"{end:%Y-%m-%d}T00:00:00Z",
        "accept": "netcdf",
    }
    url = f"{NCSS_URL}/agg_met_{short_name}_1979_CurrentYear_CONUS.nc"

    CACHE_FOLDER.mkdir(parents=True, exist_ok=True)
    part_file = target.with_suffix(".part")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(f"  Downloading {short_name} {first_year}-{last_year}...")
            with session.get(url, params=params, stream=True,
                             timeout=REQUEST_TIMEOUT_SECONDS) as response:
                response.raise_for_status()
                with open(part_file, "wb") as file:
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        file.write(block)
            part_file.replace(target)
            return target
        except requests.RequestException as error:
            print(f"    Attempt {attempt} failed: {error}")
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(10 * attempt)


def load_variable(session, short_name):
    """Return one variable for the full period as a (day, lat, lon) DataArray."""
    file_variable, _, convert = VARIABLES[short_name]
    pieces = []
    for first_year, last_year in year_chunks():
        path = download_chunk(session, short_name, first_year, last_year)
        with xr.open_dataset(path) as dataset:
            pieces.append(dataset[file_variable].load())

    data = xr.concat(pieces, dim="day").sortby("day")
    data = data.sel(day=~data.get_index("day").duplicated())
    return convert(data) if convert else data


# ------------------------------------------------------------
# 3. Download, mask to lake-level cells, and average
# ------------------------------------------------------------

print(f"gridMET daily, {START_YEAR}-01-01 to {END_DATE}")
daily_columns = {}

with requests.Session() as session:
    session.headers.update({"User-Agent": "GreatSaltLakeResearch/1.0"})

    # Maximum temperature first: it defines the lake-level mask.
    tmax = load_variable(session, "tmmx")
    climatology = tmax.mean("day")
    warm_reference = float(climatology.quantile(WARM_REFERENCE_QUANTILE))
    lake_level = climatology >= warm_reference - MAX_COOLING_C

    print(
        f"\nGrid cells: {lake_level.size} in box, {int(lake_level.sum())} at lake "
        f"level (mean Tmax >= {warm_reference - MAX_COOLING_C:.1f} C)"
    )
    if int(lake_level.sum()) == 0:
        raise RuntimeError("No grid cells passed the lake-level mask.")

    for short_name, (_, column, _) in VARIABLES.items():
        data = tmax if short_name == "tmmx" else load_variable(session, short_name)
        regional = data.where(lake_level).mean(dim=["lat", "lon"], skipna=True)
        daily_columns[column] = regional.to_series()
        del data


# ------------------------------------------------------------
# 4. Combine, derive, and save
# ------------------------------------------------------------

weather = pd.DataFrame(daily_columns)
weather.index = pd.to_datetime(weather.index).normalize()
weather.index.name = "Date"
weather = weather.sort_index()

weather.insert(
    2, "GRIDMET_Tmean_C", (weather["GRIDMET_Tmax_C"] + weather["GRIDMET_Tmin_C"]) / 2
)

RAW_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
weather.reset_index().to_csv(OUTPUT_FILE, index=False, date_format="%Y-%m-%d")

annual = weather.resample("YE").agg({
    "GRIDMET_Tmean_C": "mean",
    "GRIDMET_Wind_Speed_m_s": "mean",
    "GRIDMET_Shortwave_Down_W_m2": "mean",
    "GRIDMET_Precipitation_mm": "sum",
    "GRIDMET_Reference_ET_Grass_mm": "sum",
})
complete_years = annual[weather.resample("YE").size() >= 365]

print("\n----------------------------------------")
print("gridMET daily download complete")
print("----------------------------------------")
print(f"Daily rows: {len(weather)}")
print(f"Date range: {weather.index.min():%Y-%m-%d} to {weather.index.max():%Y-%m-%d}")
print(f"Missing values: {int(weather.isna().sum().sum())}")
print("\nLong-term annual means (sanity check):")
print(complete_years.mean().round(1).to_string())
print(f"\nSaved to: {OUTPUT_FILE}")
