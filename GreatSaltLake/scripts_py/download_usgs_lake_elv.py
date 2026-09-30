# -*- coding: utf-8 -*-
"""
Created on Wed Sep 30 08:03:24 2026

@author: charl
"""

# ============================================================
# Download USGS Great Salt Lake Elevation Data
# ============================================================
#
# Downloads daily Great Salt Lake water-surface elevation
# from the USGS Water Data API.
#
# Station:
#   10010000 - Great Salt Lake at Saltair Boat Harbor, UT
#
# Parameter:
#   62614 - Lake/reservoir water-surface elevation
#
# Units:
#   feet above NGVD 1929
#
# Output:
#   raw_data/usgs_lake_elevation.csv
# ============================================================


import requests
import pandas as pd
from pathlib import Path


# ------------------------------------------------------------
# 1. Project folders
# ------------------------------------------------------------

project_folder = Path(__file__).resolve().parent.parent

raw_data_folder = project_folder / "raw_data"

output_file = raw_data_folder / "usgs_lake_elevation.csv"


# ------------------------------------------------------------
# 2. USGS station information
# ------------------------------------------------------------

site_no = "10010000"

parameter = "62614"

start_date = "1847-10-18"

end_date = pd.Timestamp.today().strftime("%Y-%m-%d")


# ------------------------------------------------------------
# 3. USGS Water Data API
# ------------------------------------------------------------

url = "https://waterservices.usgs.gov/nwis/dv/"


params = {
    "format": "json",
    "sites": site_no,
    "parameterCd": parameter,
    "startDT": start_date,
    "endDT": end_date,
    "siteStatus": "all"
}


# ------------------------------------------------------------
# 4. Download data
# ------------------------------------------------------------

print("Downloading USGS Great Salt Lake elevation data...")

response = requests.get(url, params=params, timeout=60)

response.raise_for_status()

data = response.json()


# ------------------------------------------------------------
# 5. Extract observations
# ------------------------------------------------------------

time_series = data["value"]["timeSeries"][0]

observations = time_series["values"][0]["value"]


# ------------------------------------------------------------
# 6. Convert to DataFrame
# ------------------------------------------------------------

records = []

for observation in observations:

    date = observation["dateTime"]

    value = observation["value"]

    records.append({
        "Date": date,
        "Lake_Elevation_ft": value
    })


lake_elevation = pd.DataFrame(records)


# ------------------------------------------------------------
# 7. Clean data
# ------------------------------------------------------------

lake_elevation["Date"] = pd.to_datetime(
    lake_elevation["Date"]
)

lake_elevation["Lake_Elevation_ft"] = pd.to_numeric(
    lake_elevation["Lake_Elevation_ft"],
    errors="coerce"
)


# ------------------------------------------------------------
# 8. Sort by date
# ------------------------------------------------------------

lake_elevation = lake_elevation.sort_values(
    "Date"
).reset_index(drop=True)


# ------------------------------------------------------------
# 9. Save data
# ------------------------------------------------------------

raw_data_folder.mkdir(
    parents=True,
    exist_ok=True
)

lake_elevation.to_csv(
    output_file,
    index=False
)


# ------------------------------------------------------------
# 10. Print summary
# ------------------------------------------------------------

print()
print("Download complete.")
print()

print("Station:")
print("10010000 - Great Salt Lake at Saltair Boat Harbor, UT")

print()
print("Parameter:")
print("62614 - Lake/reservoir water-surface elevation")

print()
print("Number of observations:")
print(len(lake_elevation))

print()
print("First date:")
print(lake_elevation["Date"].min())

print()
print("Last date:")
print(lake_elevation["Date"].max())

print()
print("Missing values:")
print(lake_elevation["Lake_Elevation_ft"].isna().sum())

print()
print("Output file:")
print(output_file)