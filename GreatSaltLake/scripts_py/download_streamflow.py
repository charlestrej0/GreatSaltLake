# -*- coding: utf-8 -*-
"""
Created on Fri Sep 25 07:52:15 2026

@author: charl
"""

# download_streamflow.py
# Downloads daily USGS streamflow for multiple rivers

import requests
import pandas as pd
from pathlib import Path


# USER INPUT
#-----------

sites = [
    "10126000",    # Bear River
    "10141000",    # Weber River
    "10141200",    # North Fork Weber River
    "10141100",    # South Fork Weber River
    "10141410",    # Howard Slough
    "10141450",    # Kays Creek
    "10142000",    # Farmington CR Abv Div
    "10172625",    # Salt Lake City Sewage Canal
    "10172600",    # Jordan River
    "10172630",    # Goggin Drain
    "10172640"     # Lee Creek
]

river_names = [
    "Bear (ft^3/s)",
    "Weber (ft^3/s)",
    "N-Fork Weber (ft^3/s)",
    "S-Fork Weber (ft^3/s)",
    "Howard Slough (ft^3/s)",
    "Kays Creek (ft^3/s)",
    "Farmington CR Abv Div (ft^3/s)",
    "Salt Lake City Sewage Canal (ft^3/s)",
    "Jordan (ft^3/s)",
    "Goggin Drain (ft^3/s)",
    "Lee Creek (ft^3/s)"
]

parameter = "00060"        # Discharge (cfs)

start_date = "1900-01-01"
end_date = pd.Timestamp.today().strftime("%Y-%m-%d")


# Download each river
#--------------------

master = None

for i in range(len(sites)):

    print("Downloading", river_names[i], "...")

    url = "https://waterservices.usgs.gov/nwis/dv/"

    params = {
        "format": "json",
        "sites": sites[i],
        "startDT": start_date,
        "endDT": end_date,
        "parameterCd": parameter,
        "siteStatus": "all"
    }

    response = requests.get(url, params=params)

    response.raise_for_status()

    data = response.json()


    # Get the daily values
    time_series = data["value"]["timeSeries"]

    if len(time_series) == 0:
        print("No data found for", river_names[i])
        continue

    values = time_series[0]["values"][0]["value"]

    temp = pd.DataFrame(values)


    # Convert dates
    temp["Date"] = pd.to_datetime(temp["dateTime"]).dt.date


    # Convert discharge to numbers
    temp[river_names[i]] = pd.to_numeric(
        temp["value"],
        errors="coerce"
    )


    # Keep only the columns we need
    temp = temp[["Date", river_names[i]]]


    # Add this river to the master dataset
    if master is None:

        master = temp

    else:

        master = pd.merge(
            master,
            temp,
            on="Date",
            how="outer"
        )


# Sort by date
#-------------

master = master.sort_values("Date")


# Add total inflow and reporting count
#-------------------------------------

master["Total Inflow (ft^3/s)"] = master[river_names].sum(
    axis=1,
    skipna=True
)

master["Number of Gauges Reporting"] = master[river_names].notna().sum(
    axis=1
)


# Save
#-----

# Find the GreatSaltLake project folder
project_folder = Path(__file__).resolve().parent.parent

# Find the raw_data folder
raw_data_folder = project_folder / "raw_data"

# Create raw_data folder if it doesn't already exist
raw_data_folder.mkdir(exist_ok=True)

# Create the output file path
output_file = raw_data_folder / "usgs_streamflow_py.csv"

# Save the data
master.to_csv(
    output_file,
    index=False
)

print("\nFinished downloading streamflow data!")
print("Saved to:", output_file)

print(master.head())