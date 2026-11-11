"""
download_usgs_lake_hypsometry.py

Great Salt Lake elevation-area-volume (hypsometry) tables from USGS.

Source
    Root, J.C., 2023, Half-meter topobathymetric elevation model and
    elevation-area-volume tables for Great Salt Lake, Utah, 2002-2016:
    U.S. Geological Survey data release, https://doi.org/10.5066/P9DGG75W

The tables give lake surface area and stored volume at 0.01 ft elevation
steps from 4,170 to 4,215 ft NAVD88 (about 4,166.5 to 4,211.5 ft NGVD29),
computed from 2002-2006 bathymetry merged with 2016 lidar.

Regions downloaded: total lake, south arm, north arm, Bear River Bay,
and Farmington Bay. The per-region tables support a multi-arm model.

Datum: the USGS lake-elevation gauge used in this project (10010000,
Saltair) reports feet above NGVD29, so processing uses the NGVD29 column.

Output
    raw_data/usgs_gsl_elevation_area_volume.csv
    (long format: Region, Elevation_ft_NGVD29, Elevation_ft_NAVD88,
     Area_acres, Volume_acre_ft)
"""

from io import StringIO
from pathlib import Path

import pandas as pd
import requests


# ------------------------------------------------------------
# 1. Settings and file locations
# ------------------------------------------------------------

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
RAW_DATA_FOLDER = PROJECT_FOLDER / "raw_data"
OUTPUT_FILE = RAW_DATA_FOLDER / "usgs_gsl_elevation_area_volume.csv"

SCIENCEBASE_ITEM = "6467b42fd34ec11ae4a8afb1"
SCIENCEBASE_URL = f"https://www.sciencebase.gov/catalog/item/{SCIENCEBASE_ITEM}"

# Region name used in the output -> file name in the data release
REGIONS = {
    "total": "Great_Salt_Lake_2023_ElevAreaVolume_total.csv",
    "south_arm": "Great_Salt_Lake_2023_ElevAreaVolume_south_arm.csv",
    "north_arm": "Great_Salt_Lake_2023_ElevAreaVolume_north_arm.csv",
    "bear_river_bay": "Great_Salt_Lake_2023_ElevAreaVolume_bear_river_bay.csv",
    "farmington_bay": "Great_Salt_Lake_2023_ElevAreaVolume_farmington_bay.csv",
}

COLUMNS = {
    "elev_ft_NGVD29": "Elevation_ft_NGVD29",
    "elev_ft_NAVD88": "Elevation_ft_NAVD88",
    "area_acre": "Area_acres",
    "volume_acreft": "Volume_acre_ft",
}


# ------------------------------------------------------------
# 2. Find download links (ScienceBase file URLs are content hashes)
# ------------------------------------------------------------

print("Reading USGS ScienceBase file list...")

with requests.Session() as session:
    session.headers.update({"User-Agent": "GreatSaltLakeResearch/1.0"})

    response = session.get(SCIENCEBASE_URL, params={"format": "json"}, timeout=60)
    response.raise_for_status()
    files = {item["name"]: item["downloadUri"] for item in response.json()["files"]}

    missing = [name for name in REGIONS.values() if name not in files]
    if missing:
        raise RuntimeError(f"Files not found in the USGS release: {missing}")


    # --------------------------------------------------------
    # 3. Download each region's table
    # --------------------------------------------------------

    tables = []

    for region, file_name in REGIONS.items():
        print(f"Downloading {region}...")
        response = session.get(files[file_name], timeout=120)
        response.raise_for_status()

        table = pd.read_csv(StringIO(response.text), usecols=list(COLUMNS))
        table = table.rename(columns=COLUMNS)
        table.insert(0, "Region", region)
        tables.append(table)


# ------------------------------------------------------------
# 4. Save
# ------------------------------------------------------------

hypsometry = pd.concat(tables, ignore_index=True)

RAW_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
hypsometry.to_csv(OUTPUT_FILE, index=False)

summary = hypsometry.groupby("Region").agg(
    Min_Elevation_ft_NGVD29=("Elevation_ft_NGVD29", "min"),
    Max_Elevation_ft_NGVD29=("Elevation_ft_NGVD29", "max"),
    Max_Area_acres=("Area_acres", "max"),
    Max_Volume_acre_ft=("Volume_acre_ft", "max"),
)

print("\n----------------------------------------")
print("USGS GSL elevation-area-volume tables saved")
print("----------------------------------------")
print(summary.round(1).to_string())
print(f"\nSaved to: {OUTPUT_FILE}")
