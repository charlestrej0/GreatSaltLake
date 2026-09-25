# -*- coding: utf-8 -*-
"""
Created on Fri Sep 25 08:44:27 2026

@author: charl
"""

# download_noaa_precipitation.py
#
# Great Salt Lake NOAA Historical Daily Precipitation
#
# This script:
# 1. Finds GHCN stations near the Great Salt Lake
# 2. Checks precipitation record history
# 3. Selects historical candidate stations
# 4. Downloads daily precipitation data
# 5. Calculates data coverage
# 6. Saves station, coverage, and precipitation data
#


import requests
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import date


# =========================================================
# USER SETTINGS
# =========================================================

# Great Salt Lake station search area
MIN_LATITUDE = 40.3
MAX_LATITUDE = 41.8

MIN_LONGITUDE = -113.5
MAX_LONGITUDE = -111.3

# Only download stations whose precipitation records
# begin on or before this year
MAX_FIRST_YEAR = 1910


# =========================================================
# FILE LOCATIONS
# =========================================================

# Find the GreatSaltLake project folder
project_folder = Path(__file__).resolve().parent.parent

# Find the raw_data folder
raw_data_folder = project_folder / "raw_data"

# Create raw_data folder if necessary
raw_data_folder.mkdir(exist_ok=True)


# =========================================================
# NOAA URLS
# =========================================================

station_url = (
    "https://www.ncei.noaa.gov/pub/data/ghcn/daily/"
    "ghcnd-stations.txt"
)

inventory_url = (
    "https://www.ncei.noaa.gov/pub/data/ghcn/daily/"
    "ghcnd-inventory.txt"
)


# =========================================================
# 1. DOWNLOAD NOAA STATION INVENTORY
# =========================================================

print("\n========================================")
print("DOWNLOADING NOAA STATION INVENTORY")
print("========================================\n")

response = requests.get(station_url)

response.raise_for_status()

stations_raw = response.text.splitlines()

print("Downloaded", len(stations_raw), "stations.")


# =========================================================
# 2. PARSE STATION INVENTORY
# =========================================================

print("\nParsing station information...")

station_data = []

for line in stations_raw:

    # Make sure the line is long enough
    if len(line) < 71:
        continue

    station_id = line[0:11].strip()

    latitude = pd.to_numeric(
        line[12:20].strip(),
        errors="coerce"
    )

    longitude = pd.to_numeric(
        line[21:30].strip(),
        errors="coerce"
    )

    elevation = pd.to_numeric(
        line[31:37].strip(),
        errors="coerce"
    )

    state = line[38:40].strip()

    name = line[41:71].strip()

    station_data.append(
        {
            "ID": station_id,
            "Latitude": latitude,
            "Longitude": longitude,
            "Elevation_m": elevation,
            "State": state,
            "Name": name
        }
    )


stations = pd.DataFrame(station_data)


# =========================================================
# 3. FIND STATIONS NEAR THE GREAT SALT LAKE
# =========================================================

print("\nFinding stations near the Great Salt Lake...")

gsl_stations = stations[
    (stations["State"] == "UT") &
    (stations["Latitude"] >= MIN_LATITUDE) &
    (stations["Latitude"] <= MAX_LATITUDE) &
    (stations["Longitude"] >= MIN_LONGITUDE) &
    (stations["Longitude"] <= MAX_LONGITUDE)
].copy()


gsl_stations = gsl_stations.sort_values("Name")


print(
    "Found",
    len(gsl_stations),
    "stations near the Great Salt Lake."
)


print("\nGSL stations:")
print(gsl_stations.to_string(index=False))


# =========================================================
# 4. SAVE GSL STATION LIST
# =========================================================

stations_file = (
    raw_data_folder /
    "noaa_gsl_stations.csv"
)

gsl_stations.to_csv(
    stations_file,
    index=False
)

print("\nSaved station list to:")
print(stations_file)


# =========================================================
# 5. DOWNLOAD NOAA INVENTORY
# =========================================================

print("\n========================================")
print("DOWNLOADING NOAA DATA INVENTORY")
print("========================================\n")

response = requests.get(inventory_url)

response.raise_for_status()

inventory_raw = response.text.splitlines()

print(
    "Downloaded",
    len(inventory_raw),
    "inventory records."
)


# =========================================================
# 6. PARSE NOAA INVENTORY
# =========================================================

inventory_data = []

for line in inventory_raw:

    if len(line) < 45:
        continue

    station_id = line[0:11].strip()

    latitude = pd.to_numeric(
        line[12:20].strip(),
        errors="coerce"
    )

    longitude = pd.to_numeric(
        line[21:30].strip(),
        errors="coerce"
    )

    element = line[31:35].strip()

    first_year = pd.to_numeric(
        line[36:40].strip(),
        errors="coerce"
    )

    last_year = pd.to_numeric(
        line[41:45].strip(),
        errors="coerce"
    )

    inventory_data.append(
        {
            "ID": station_id,
            "Latitude": latitude,
            "Longitude": longitude,
            "Element": element,
            "First_Year": first_year,
            "Last_Year": last_year
        }
    )


inventory = pd.DataFrame(inventory_data)


# =========================================================
# 7. FIND PRECIPITATION HISTORY
# =========================================================

print("\nFinding precipitation records...")

gsl_station_ids = gsl_stations["ID"].tolist()


precip_history = inventory[
    (inventory["ID"].isin(gsl_station_ids)) &
    (inventory["Element"] == "PRCP")
].copy()


# Add station information
precip_history = pd.merge(
    gsl_stations[
        [
            "ID",
            "Name",
            "Latitude",
            "Longitude",
            "Elevation_m",
            "State"
        ]
    ],
    precip_history[
        [
            "ID",
            "Element",
            "First_Year",
            "Last_Year"
        ]
    ],
    on="ID",
    how="left"
)


# Remove stations with no precipitation history
precip_history = precip_history[
    precip_history["First_Year"].notna()
].copy()


precip_history = precip_history.sort_values(
    "First_Year"
)


# =========================================================
# 8. DISPLAY HISTORICAL PRECIPITATION STATIONS
# =========================================================

print("\n========================================")
print("HISTORICAL PRECIPITATION STATIONS")
print("========================================\n")

print(
    precip_history[
        [
            "ID",
            "Name",
            "Latitude",
            "Longitude",
            "Elevation_m",
            "First_Year",
            "Last_Year"
        ]
    ].to_string(index=False)
)


# =========================================================
# 9. FIND STATIONS BEGINNING BEFORE 1900
# =========================================================

print("\n========================================")
print("STATIONS WITH PRCP BEFORE 1900")
print("========================================\n")


old_stations = precip_history[
    precip_history["First_Year"] < 1900
].copy()


old_stations = old_stations.sort_values(
    "First_Year"
)


if len(old_stations) == 0:

    print("No stations found with precipitation records before 1900.")

else:

    print(
        old_stations[
            [
                "ID",
                "Name",
                "First_Year",
                "Last_Year"
            ]
        ].to_string(index=False)
    )


# =========================================================
# 10. SAVE PRECIPITATION STATION HISTORY
# =========================================================

history_file = (
    raw_data_folder /
    "noaa_precipitation_station_history.csv"
)


precip_history.to_csv(
    history_file,
    index=False
)


print("\nSaved precipitation history to:")
print(history_file)


# =========================================================
# 11. SELECT HISTORICAL CANDIDATE STATIONS
# =========================================================

print("\n========================================")
print("SELECTING CANDIDATE STATIONS")
print("========================================\n")


candidate_stations = precip_history[
    precip_history["First_Year"] <= MAX_FIRST_YEAR
].copy()


candidate_stations = candidate_stations.sort_values(
    "First_Year"
)


print(
    "Found",
    len(candidate_stations),
    "candidate stations."
)


print(
    candidate_stations[
        [
            "ID",
            "Name",
            "First_Year",
            "Last_Year"
        ]
    ].to_string(index=False)
)


# =========================================================
# 12. FUNCTION TO DOWNLOAD NOAA .DLY FILE
# =========================================================

def read_noaa_dly(station_id):

    url = (
        "https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/"
        + station_id
        + ".dly"
    )

    print("\nDownloading:", station_id)

    try:

        response = requests.get(url)

        response.raise_for_status()

    except requests.RequestException:

        print("Download failed:", station_id)

        return None


    lines = response.text.splitlines()


    if len(lines) == 0:

        print("No data found:", station_id)

        return None


    output = []


    # Each line represents one month and one element
    for line in lines:

        if len(line) < 22:
            continue


        station = line[0:11].strip()

        year = int(line[11:15])

        month = int(line[15:17])

        element = line[17:21].strip()


        # We only want precipitation
        if element != "PRCP":
            continue


        # Determine number of days in month
        first_day = pd.Timestamp(
            year=year,
            month=month,
            day=1
        )

        days_in_month = first_day.days_in_month


        # Extract daily precipitation
        for day in range(1, days_in_month + 1):

            start = 21 + (day - 1) * 8

            value_string = line[
                start:start + 5
            ]


            try:

                value = float(value_string)

            except ValueError:

                value = np.nan


            # NOAA uses -9999 for missing data
            if value == -9999:

                value = np.nan


            # NOAA PRCP is stored in tenths of millimeters
            if not pd.isna(value):

                precipitation_mm = value / 10

            else:

                precipitation_mm = np.nan


            observation_date = pd.Timestamp(
                year=year,
                month=month,
                day=day
            )


            output.append(
                {
                    "ID": station,
                    "Date": observation_date,
                    "Precipitation_mm": precipitation_mm
                }
            )


    if len(output) == 0:

        return None


    return pd.DataFrame(output)


# =========================================================
# 13. FUNCTION TO CALCULATE COVERAGE
# =========================================================

def calculate_coverage(data, station_id):

    if data is None:

        return pd.DataFrame(
            [
                {
                    "ID": station_id,
                    "First_Date": pd.NaT,
                    "Last_Date": pd.NaT,
                    "Days_Observed": 0,
                    "Days_Expected": np.nan,
                    "Coverage_Percent": np.nan,
                    "Longest_Gap_Days": np.nan
                }
            ]
        )


    observed = data[
        data["Precipitation_mm"].notna()
    ].copy()


    observed = observed.sort_values("Date")


    if len(observed) == 0:

        return pd.DataFrame(
            [
                {
                    "ID": station_id,
                    "First_Date": pd.NaT,
                    "Last_Date": pd.NaT,
                    "Days_Observed": 0,
                    "Days_Expected": np.nan,
                    "Coverage_Percent": np.nan,
                    "Longest_Gap_Days": np.nan
                }
            ]
        )


    first_date = observed["Date"].min()

    last_date = observed["Date"].max()


    expected_dates = pd.date_range(
        start=first_date,
        end=last_date,
        freq="D"
    )


    days_expected = len(expected_dates)

    days_observed = len(observed)


    coverage = (
        100 *
        days_observed /
        days_expected
    )


    # Find gaps between observations
    date_difference = (
        observed["Date"].diff()
        .dt.days
    )


    gaps = date_difference - 1

    gaps = gaps.dropna()


    if len(gaps) > 0:

        longest_gap = gaps.max()

    else:

        longest_gap = 0


    return pd.DataFrame(
        [
            {
                "ID": station_id,
                "First_Date": first_date,
                "Last_Date": last_date,
                "Days_Observed": days_observed,
                "Days_Expected": days_expected,
                "Coverage_Percent": coverage,
                "Longest_Gap_Days": longest_gap
            }
        ]
    )


# =========================================================
# 14. DOWNLOAD ALL CANDIDATE STATIONS
# =========================================================

print("\n========================================")
print("DOWNLOADING DAILY PRECIPITATION")
print("========================================")


all_station_data = []

coverage_results = []


for i in range(len(candidate_stations)):

    station_id = candidate_stations.iloc[i]["ID"]

    print("\n----------------------------------------")

    print(
        "Station",
        i + 1,
        "of",
        len(candidate_stations),
        ":",
        station_id
    )


    data = read_noaa_dly(station_id)


    if data is not None:

        all_station_data.append(data)


        coverage_result = calculate_coverage(
            data,
            station_id
        )


        coverage_results.append(
            coverage_result
        )


# =========================================================
# 15. COMBINE COVERAGE RESULTS
# =========================================================

if len(coverage_results) > 0:

    coverage = pd.concat(
        coverage_results,
        ignore_index=True
    )

else:

    coverage = pd.DataFrame()


# =========================================================
# 16. ADD STATION INFORMATION
# =========================================================

if len(coverage) > 0:

    coverage = pd.merge(
        coverage,
        precip_history[
            [
                "ID",
                "Name",
                "Latitude",
                "Longitude",
                "Elevation_m",
                "First_Year",
                "Last_Year"
            ]
        ],
        on="ID",
        how="left"
    )


    coverage = coverage.sort_values(
        "Coverage_Percent",
        ascending=False
    )


# =========================================================
# 17. PRINT COVERAGE RESULTS
# =========================================================

print("\n\n========================================")
print("NOAA DAILY PRECIPITATION COVERAGE")
print("========================================\n")


if len(coverage) > 0:

    print(
        coverage[
            [
                "ID",
                "Name",
                "First_Year",
                "Last_Year",
                "First_Date",
                "Last_Date",
                "Days_Observed",
                "Coverage_Percent",
                "Longest_Gap_Days"
            ]
        ].to_string(index=False)
    )

else:

    print("No coverage data were downloaded.")


# =========================================================
# 18. SAVE COVERAGE RESULTS
# =========================================================

coverage_file = (
    raw_data_folder /
    "noaa_daily_coverage.csv"
)


coverage.to_csv(
    coverage_file,
    index=False
)


print("\nCoverage saved to:")
print(coverage_file)


# =========================================================
# 19. COMBINE DAILY PRECIPITATION DATA
# =========================================================

if len(all_station_data) > 0:

    daily_data = pd.concat(
        all_station_data,
        ignore_index=True
    )


    # Convert from long format to wide format
    daily_data_wide = daily_data.pivot(
        index="Date",
        columns="ID",
        values="Precipitation_mm"
    )


    # Turn Date back into a regular column
    daily_data_wide = daily_data_wide.reset_index()


    # Sort by date
    daily_data_wide = daily_data_wide.sort_values(
        "Date"
    )


else:

    daily_data_wide = pd.DataFrame()


# =========================================================
# 20. SAVE DAILY PRECIPITATION
# =========================================================

daily_file = (
    raw_data_folder /
    "noaa_historical_daily_precipitation_wide.csv"
)


daily_data_wide.to_csv(
    daily_file,
    index=False
)


print("\nDaily precipitation saved to:")
print(daily_file)


# =========================================================
# 21. FINISHED
# =========================================================

print("\n========================================")
print("FINISHED!")
print("========================================\n")

print(
    "GSL stations:",
    len(gsl_stations)
)

print(
    "Historical precipitation stations:",
    len(precip_history)
)

print(
    "Candidate stations downloaded:",
    len(all_station_data)
)

if len(daily_data_wide) > 0:

    print(
        "Date range:",
        daily_data_wide["Date"].min(),
        "to",
        daily_data_wide["Date"].max()
    )

print("\nFiles saved in:")
print(raw_data_folder)