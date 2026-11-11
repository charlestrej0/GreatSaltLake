# -*- coding: utf-8 -*-
"""
Created on Tue Oct  6 08:11:58 2026

@author: charl
"""

import numpy as np
import pandas as pd
from pathlib import Path


# ============================================================
# 1. Set project folders
# ============================================================

# This assumes this script is located in:
# GreatSaltLake/scripts_python/aggregate_monthly_data.py

project_folder = Path(__file__).resolve().parent.parent

raw_data_folder = project_folder / "raw_data"
processed_data_folder = project_folder / "processed_data"

processed_data_folder.mkdir(parents=True, exist_ok=True)


# ============================================================
# 2. File locations
# ============================================================

lake_file = raw_data_folder / "usgs_lake_elevation.csv"
streamflow_file = raw_data_folder / "usgs_streamflow.csv"
precipitation_file = raw_data_folder / "noaa_historical_daily_precipitation_wide.csv"

# Weather sources. Any file that has not been downloaded yet is skipped.
noaa_weather_file = raw_data_folder / "noaa_historical_daily_weather.csv"
era5_file = raw_data_folder / "era5_land_monthly_weather.csv"
gridmet_file = raw_data_folder / "gridmet_daily_weather.csv"

# USGS elevation-area-volume tables (download_usgs_lake_hypsometry.py)
hypsometry_file = raw_data_folder / "usgs_gsl_elevation_area_volume.csv"

output_file = processed_data_folder / "gsl_monthly_master.csv"


# ============================================================
# Monthly aggregation rule for daily weather
# ============================================================
#
# - Columns ending in "_mm" are amounts (precipitation, ET): monthly SUM.
#   A sum over a half-missing month would look like a dry month, so sums
#   are left blank unless at least MIN_DAYS_FRACTION of days have data.
# - Everything else is a condition (temperature, humidity, wind,
#   radiation, pressure): monthly MEAN.

MIN_DAYS_FRACTION = 0.9


def aggregate_to_monthly(daily):
    """Aggregate a Date-indexed daily DataFrame to month-end rows."""
    monthly = daily.resample("ME").mean()

    sum_columns = [column for column in daily.columns if column.endswith("_mm")]

    if sum_columns:
        sums = daily[sum_columns].resample("ME").sum(min_count=1)
        days_reporting = daily[sum_columns].notna().resample("ME").sum()
        days_in_month = pd.Series(monthly.index.days_in_month, index=monthly.index)
        complete = days_reporting.div(days_in_month, axis=0) >= MIN_DAYS_FRACTION
        monthly[sum_columns] = sums.where(complete)

    return monthly


# ============================================================
# 3. Read the data
# ============================================================

print("Reading data...")

lake = pd.read_csv(lake_file)
streamflow = pd.read_csv(streamflow_file)
precipitation = pd.read_csv(precipitation_file)


# ============================================================
# 4. Convert dates
# ============================================================

lake["Date"] = pd.to_datetime(lake["Date"])
streamflow["Date"] = pd.to_datetime(streamflow["Date"])
precipitation["Date"] = pd.to_datetime(precipitation["Date"])


# ============================================================
# 5. Aggregate lake elevation
# ============================================================

print("Aggregating lake elevation...")

lake = lake.set_index("Date")

lake_monthly = lake.resample("ME").agg(
    Lake_Elevation_Mean_ft=("Lake_Elevation_ft", "mean"),
    Lake_Elevation_Month_End_ft=("Lake_Elevation_ft", "last"),
    Lake_Elevation_Obs_Count=("Lake_Elevation_ft", "count")
)

lake_monthly = lake_monthly.reset_index()


# ============================================================
# 6. Aggregate streamflow
# ============================================================

print("Aggregating streamflow...")

streamflow = streamflow.set_index("Date")

# Find the individual river/gauge columns.
streamflow_columns = []

for column in streamflow.columns:

    if column not in [
        "Total Inflow (ft^3/s)",
        "Number of Gauges Reporting"
    ]:
        streamflow_columns.append(column)


# Calculate monthly mean flow for each gauge.
streamflow_monthly = streamflow[
    streamflow_columns + [
        "Total Inflow (ft^3/s)"
    ]
].resample("ME").mean()

streamflow_monthly = streamflow_monthly.reset_index()


# ============================================================
# 7. Calculate monthly total inflow in MAF
# ============================================================

# Streamflow is measured in ft^3/s.
#
# Volume = flow rate × time
#
# 1 acre-foot = 43,560 ft^3
#
# 1 million acre-feet = 43,560 × 1,000,000 ft^3

seconds_per_day = 24 * 60 * 60

days_in_month = (
    streamflow_monthly["Date"]
    .dt.days_in_month
)

seconds_in_month = days_in_month * seconds_per_day

streamflow_monthly["Total_Inflow_MAF"] = (
    streamflow_monthly["Total Inflow (ft^3/s)"]
    * seconds_in_month
    / 43560
    / 1_000_000
)


# Rename the total inflow column.
streamflow_monthly = streamflow_monthly.rename(
    columns={
        "Total Inflow (ft^3/s)": "Total_Inflow_Mean_ft3_s"
    }
)


# ============================================================
# 8. Calculate streamflow reporting information
# ============================================================

streamflow_reporting = (
    streamflow["Total Inflow (ft^3/s)"]
    .resample("ME")
    .count()
    .reset_index()
)

streamflow_reporting = streamflow_reporting.rename(
    columns={
        "Total Inflow (ft^3/s)": "Streamflow_Days_Reporting"
    }
)


streamflow_monthly = streamflow_monthly.merge(
    streamflow_reporting,
    on="Date",
    how="left"
)


# ============================================================
# 9. Aggregate NOAA precipitation
# ============================================================

print("Aggregating NOAA precipitation...")

precipitation = precipitation.set_index("Date")


# Every column except Date is a NOAA station.
station_columns = list(precipitation.columns)


# Monthly precipitation total for every station.
precipitation_monthly = (
    precipitation[station_columns]
    .resample("ME")
    .sum(min_count=1)
)

precipitation_monthly = precipitation_monthly.reset_index()


# ============================================================
# 10. Calculate NOAA station-average precipitation
# ============================================================

precipitation_monthly["NOAA_Station_Mean_Precip_mm"] = (
    precipitation_monthly[station_columns]
    .mean(axis=1, skipna=True)
)


# Count how many stations reported during each month.
precipitation_monthly["NOAA_Stations_Reporting"] = (
    precipitation_monthly[station_columns]
    .notna()
    .sum(axis=1)
)


# Rename individual station columns.
new_names = {}

for column in station_columns:
    new_names[column] = (
        "NOAA_"
        + column
        + "_Monthly_Precip_mm"
    )

precipitation_monthly = precipitation_monthly.rename(
    columns=new_names
)


# ============================================================
# 11. Aggregate NOAA station weather (GHCNh)
# ============================================================
#
# The station file has one column per station and variable, for example
# Temperature_USW00024127_C. Collapse these to one regional mean per
# variable so the master table does not get 100+ sparse columns.
# Caution: stations sit at different elevations, so the regional mean can
# shift when stations start or stop reporting. Check
# NOAA_Weather_Stations_Reporting before trusting long-term trends.

weather_sources = []

if noaa_weather_file.exists():

    print("Aggregating NOAA station weather...")

    noaa_weather = pd.read_csv(noaa_weather_file, parse_dates=["Date"])
    noaa_weather = noaa_weather.set_index("Date").sort_index()

    noaa_variables = {
        "Temperature": "C",
        "Humidity": "percent",
        "Pressure": "hPa",
        "Wind": "m_s",
        "DewPoint": "C",
    }

    noaa_daily = pd.DataFrame(index=noaa_weather.index)

    for prefix, unit in noaa_variables.items():
        columns = [
            column for column in noaa_weather.columns
            if column.startswith(prefix + "_")
        ]
        noaa_daily[f"NOAA_Station_Mean_{prefix}_{unit}"] = (
            noaa_weather[columns].mean(axis=1, skipna=True)
        )

        if prefix == "Temperature":
            noaa_daily["NOAA_Weather_Stations_Reporting"] = (
                noaa_weather[columns].notna().sum(axis=1)
            )

    weather_sources.append(aggregate_to_monthly(noaa_daily).reset_index())

else:
    print("Skipping NOAA station weather (file not found).")


# ============================================================
# 12. ERA5-Land weather (already monthly)
# ============================================================

if era5_file.exists():

    print("Adding ERA5-Land monthly weather...")

    era5_monthly = pd.read_csv(era5_file, parse_dates=["Date"])

    # Align to month-end in case of any date-format differences.
    era5_monthly["Date"] = era5_monthly["Date"] + pd.offsets.MonthEnd(0)

    weather_sources.append(era5_monthly)

else:
    print("Skipping ERA5-Land weather (file not found).")


# ============================================================
# 13. Aggregate gridMET daily weather
# ============================================================

if gridmet_file.exists():

    print("Aggregating gridMET daily weather...")

    gridmet = pd.read_csv(gridmet_file, parse_dates=["Date"])
    gridmet = gridmet.set_index("Date").sort_index()

    gridmet_monthly = aggregate_to_monthly(gridmet)

    # Days with data each month (flags the partial current month).
    gridmet_monthly["GRIDMET_Days_Reporting"] = (
        gridmet["GRIDMET_Tmax_C"].resample("ME").count()
    )

    weather_sources.append(gridmet_monthly.reset_index())

else:
    print("Skipping gridMET weather (file not found).")


# ============================================================
# 14. Combine all datasets
# ============================================================

print("Combining datasets...")

master = lake_monthly.merge(
    streamflow_monthly,
    on="Date",
    how="outer"
)

master = master.merge(
    precipitation_monthly,
    on="Date",
    how="outer"
)

for weather_monthly in weather_sources:
    master = master.merge(
        weather_monthly,
        on="Date",
        how="outer"
    )


# Sort chronologically.
master = master.sort_values("Date")

master = master.reset_index(drop=True)


# ============================================================
# 15. Calculate change in lake elevation
# ============================================================

master["Delta_Lake_Elevation_ft"] = (
    master["Lake_Elevation_Month_End_ft"].diff()
)


# ============================================================
# 15b. Convert lake elevation to surface area and volume
# ============================================================
#
# Uses the USGS total-lake elevation-area-volume table (NGVD29 column,
# matching the Saltair gauge). Elevations outside the table's range are
# left blank rather than extrapolated.
#
# Caution: the Saltair gauge measures the SOUTH arm. The north arm usually
# sits lower, so total-lake area/volume from one elevation is approximate.
# The per-arm tables in the raw file support a two-arm model.

if hypsometry_file.exists():

    print("Converting lake elevation to area and volume...")

    hypsometry = pd.read_csv(hypsometry_file)
    total_lake = hypsometry[hypsometry["Region"] == "total"].sort_values(
        "Elevation_ft_NGVD29"
    )

    table_elevation = total_lake["Elevation_ft_NGVD29"].to_numpy()

    def lake_lookup(elevation_ft, table_column):
        """Interpolate a hypsometry column at the given elevations."""
        values = np.interp(
            elevation_ft, table_elevation, total_lake[table_column].to_numpy()
        )
        in_range = (
            (elevation_ft >= table_elevation.min())
            & (elevation_ft <= table_elevation.max())
        )
        return pd.Series(values, index=elevation_ft.index).where(in_range)

    master["Lake_Area_Mean_acres"] = lake_lookup(
        master["Lake_Elevation_Mean_ft"], "Area_acres"
    )
    master["Lake_Volume_Mean_acre_ft"] = lake_lookup(
        master["Lake_Elevation_Mean_ft"], "Volume_acre_ft"
    )
    master["Lake_Volume_Month_End_acre_ft"] = lake_lookup(
        master["Lake_Elevation_Month_End_ft"], "Volume_acre_ft"
    )

    # Change in stored volume: the dV/dt term of the water balance.
    master["Delta_Lake_Volume_acre_ft"] = (
        master["Lake_Volume_Month_End_acre_ft"].diff()
    )

    outside = (
        master["Lake_Elevation_Mean_ft"].notna()
        & master["Lake_Volume_Mean_acre_ft"].isna()
    ).sum()
    print(f"  Months above/below the USGS table range: {outside}")

else:
    print("Skipping lake area/volume (hypsometry file not found).")


# ============================================================
# 16. Convert metric columns to imperial units
# ============================================================
#
# Raw data keep their source (metric) units; only the processed master
# table is converted. This runs after monthly aggregation because the
# sum-vs-mean rule above relies on the "_mm" suffix.
#
# Column suffix -> (new suffix, conversion)
IMPERIAL_CONVERSIONS = {
    "_C": ("_F", lambda c: c * 9 / 5 + 32),
    "_mm": ("_in", lambda mm: mm / 25.4),
    "_m_s": ("_mph", lambda m_s: m_s * 2.236936),
    "_hPa": ("_inHg", lambda hpa: hpa * 0.02952998),
    "_kPa": ("_inHg", lambda kpa: kpa * 0.2952998),
    "_W_m2": ("_BTU_ft2_hr", lambda w_m2: w_m2 * 0.3169983),
}

renamed_columns = {}

for column in master.columns:
    for suffix, (new_suffix, convert) in IMPERIAL_CONVERSIONS.items():
        if column.endswith(suffix):
            master[column] = convert(master[column])
            renamed_columns[column] = column[: -len(suffix)] + new_suffix
            break

master = master.rename(columns=renamed_columns)

print(f"Converted {len(renamed_columns)} metric columns to imperial units.")


# ============================================================
# 17. Save the master dataset
# ============================================================

master.to_csv(
    output_file,
    index=False
)


# ============================================================
# 18. Print summary
# ============================================================

print()
print("==============================================")
print("Monthly master dataset created")
print("==============================================")

print(
    "File:",
    output_file
)

print(
    "Number of months:",
    len(master)
)

print(
    "Number of columns:",
    len(master.columns)
)

print(
    "First month:",
    master["Date"].min()
)

print(
    "Last month:",
    master["Date"].max()
)

print()
print("Columns:")
print(master.columns.tolist())

print()
print("Done!")