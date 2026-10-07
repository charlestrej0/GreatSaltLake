# -*- coding: utf-8 -*-
"""
Created on Tue Oct  6 08:11:58 2026

@author: charl
"""

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

output_file = processed_data_folder / "gsl_monthly_master.csv"


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
# 11. Combine all datasets
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


# Sort chronologically.
master = master.sort_values("Date")

master = master.reset_index(drop=True)


# ============================================================
# 12. Calculate change in lake elevation
# ============================================================

master["Delta_Lake_Elevation_ft"] = (
    master["Lake_Elevation_Month_End_ft"].diff()
)


# ============================================================
# 13. Save the master dataset
# ============================================================

master.to_csv(
    output_file,
    index=False
)


# ============================================================
# 14. Print summary
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