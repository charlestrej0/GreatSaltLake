# download_noaa_weather_hourly.py
#
# Great Salt Lake NOAA GHCNh Weather Data
#
# Python version of scripts_r/download_noaa_weather_hourly.R.
#
# This script:
# 1. Reads the GSL-region station list (raw_data/noaa_gsl_stations.csv)
# 2. Keeps only stations that exist in NOAA GHCNh (hourly)
# 3. Downloads one GHCNh file per station per year
# 4. Averages hourly observations into daily (UTC) values
# 5. Saves one column per station and variable, plus a download report
#
# Variables: temperature, relative humidity, station-level pressure,
# wind speed, and dew point temperature.
#
# Output:
#   raw_data/noaa_historical_daily_weather.csv
#   raw_data/noaa_weather_download_report.csv

import time
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import requests


# 1. Settings and file locations
START_YEAR = 1948
END_YEAR = date.today().year
REQUEST_DELAY_SECONDS = 0.25
REQUEST_TIMEOUT_SECONDS = 120

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
RAW_DATA_FOLDER = PROJECT_FOLDER / "raw_data"
STATION_FILE = RAW_DATA_FOLDER / "noaa_gsl_stations.csv"
OUTPUT_FILE = RAW_DATA_FOLDER / "noaa_historical_daily_weather.csv"
REPORT_FILE = RAW_DATA_FOLDER / "noaa_weather_download_report.csv"

GHCNH_URL = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly"
GHCNH_STATION_LIST_URL = f"{GHCNH_URL}/doc/ghcnh-station-list.csv"

# NOAA GHCNh column -> output column prefix
VARIABLES = {
    "temperature": "Temperature",
    "relative_humidity": "Humidity",
    "station_level_pressure": "Pressure",
    "wind_speed": "Wind",
    "dew_point_temperature": "DewPoint",
}

# Units appended to each output column, matching the R script's names
# (for example Temperature_USW00024127_C).
UNITS = {
    "Temperature": "C",
    "Humidity": "percent",
    "Pressure": "hPa",
    "Wind": "m_s",
    "DewPoint": "C",
}


# 2. Read station list and keep stations that GHCNh covers
stations = pd.read_csv(STATION_FILE)
print(f"Number of GSL-region stations: {len(stations)}")

# Most GSL stations are daily-only (co-op, CoCoRaHS) and have no hourly
# file, so filter first instead of requesting ~27 missing files each.
ghcnh_stations = pd.read_csv(GHCNH_STATION_LIST_URL, usecols=["GHCN_ID"])
station_ids = [
    station_id
    for station_id in stations["ID"]
    if station_id in set(ghcnh_stations["GHCN_ID"])
]
print(f"Stations available in GHCNh: {len(station_ids)}")

if not station_ids:
    raise RuntimeError("None of the GSL-region stations are in the GHCNh station list.")


# 3. Function to download and summarize one station-year
def download_station_year(session, station_id, year, temp_folder):
    """Download one GHCNh station-year and return (daily DataFrame or None, status)."""
    file_name = f"GHCNh_{station_id}_{year}.psv"
    url = f"{GHCNH_URL}/access/by-year/{year}/psv/{file_name}"
    temp_file = Path(temp_folder) / file_name

    try:
        response = session.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return None, "No file"
        response.raise_for_status()

        with open(temp_file, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                file.write(chunk)

        wanted_columns = {"DATE"} | set(VARIABLES)
        data = pd.read_csv(
            temp_file,
            sep="|",
            usecols=lambda column: column in wanted_columns,
            low_memory=False,
        )

        if "DATE" not in data.columns or data.empty:
            return None, "No DATE column or no rows"

        data["DATE"] = pd.to_datetime(data["DATE"], errors="coerce", utc=True)
        data = data.dropna(subset=["DATE"])

        for variable_name in VARIABLES:
            if variable_name not in data.columns:
                data[variable_name] = float("nan")
            data[variable_name] = pd.to_numeric(data[variable_name], errors="coerce")
            # NOAA missing-value codes (-9999, 9999, -999.9).
            missing = (data[variable_name].abs() >= 9999) | (data[variable_name] == -999.9)
            data.loc[missing, variable_name] = float("nan")

        if data[list(VARIABLES)].isna().all().all():
            return None, "No usable values"

        # Use the UTC calendar date consistently.
        data["Date"] = data["DATE"].dt.strftime("%Y-%m-%d")
        daily = data.groupby("Date", as_index=False)[list(VARIABLES)].mean()
        daily["ID"] = station_id
        daily = daily.rename(columns=VARIABLES)
        return daily[["Date", "ID"] + list(VARIABLES.values())], "Data found"

    except requests.RequestException as error:
        print(f"  Download failed: {station_id}, {year}: {error}")
        return None, f"Request error: {type(error).__name__}"
    except (ValueError, OSError, pd.errors.ParserError) as error:
        print(f"  Could not process {station_id}, {year}: {error}")
        return None, f"Processing error: {type(error).__name__}"
    finally:
        # Delete each downloaded file after processing to save disk space.
        if temp_file.exists():
            temp_file.unlink()



# 4. Download and aggregate data immediately
daily_results = []
download_report = []

with requests.Session() as session:
    session.headers.update({"User-Agent": "GreatSaltLakeResearch/1.0"})

    with TemporaryDirectory(prefix="gsl_noaa_") as temp_folder:
        for station_number, station_id in enumerate(station_ids, start=1):
            print(f"\nStation {station_number}/{len(station_ids)}: {station_id}")
            station_days = 0
            successful_years = 0
            year_statuses = []

            for year in range(START_YEAR, END_YEAR + 1):
                daily, status = download_station_year(
                    session, station_id, year, temp_folder
                )
                year_statuses.append(f"{year}: {status}")

                if daily is not None and not daily.empty:
                    daily_results.append(daily)
                    station_days += len(daily)
                    successful_years += 1

                time.sleep(REQUEST_DELAY_SECONDS)

            download_report.append({
                "ID": station_id,
                "Start_Year_Requested": START_YEAR,
                "End_Year_Requested": END_YEAR,
                "Years_With_Data": successful_years,
                "Daily_Records": station_days,
                "Year_Statuses": "; ".join(year_statuses),
                "Download_Status": (
                    "Data found" if successful_years > 0 else "No usable data found"
                ),
            })
            print(f"  Years with data: {successful_years}; daily records: {station_days}")


# 5. Save report, including per-year reasons if downloads fail
RAW_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
report = pd.DataFrame(download_report)
report.to_csv(REPORT_FILE, index=False)

if not daily_results:
    print(f"\nNo usable weather data were downloaded. See: {REPORT_FILE}")
    raise RuntimeError(
        "No usable NOAA weather data were downloaded. Check the report's "
        "Year_Statuses column, station IDs, URL, and NOAA column names."
    )


# 6. Combine station data and reconcile duplicate dates
weather_daily = pd.concat(daily_results, ignore_index=True)
weather_daily["Date"] = pd.to_datetime(weather_daily["Date"])
weather_daily = weather_daily.groupby(["Date", "ID"], as_index=False)[
    list(VARIABLES.values())
].mean()


# 7. Make one column per station and variable
wide_parts = []
for variable in VARIABLES.values():
    wide = weather_daily.pivot(index="Date", columns="ID", values=variable)
    wide.columns = [
        f"{variable}_{station_id}_{UNITS[variable]}" for station_id in wide.columns
    ]
    wide_parts.append(wide)

weather_wide = pd.concat(wide_parts, axis=1).sort_index()
weather_wide.index.name = "Date"
weather_wide = weather_wide.reset_index()
weather_wide.to_csv(OUTPUT_FILE, index=False)


# 8. Report results
print("\n----------------------------------------")
print("NOAA GHCNh weather processing complete")
print("----------------------------------------")
print(f"Stations requested: {len(station_ids)}")
print(f"Stations with data: {(report['Years_With_Data'] > 0).sum()}")
print(f"Daily rows: {len(weather_wide)}")
print(f"Date range: {weather_wide['Date'].min()} to {weather_wide['Date'].max()}")
print(f"Weather data saved to: {OUTPUT_FILE}")
print(f"Download report saved to: {REPORT_FILE}")
