# ============================================================
# analyze_noaa_stations.R
#
# Identify NOAA GHCN stations around the Great Salt Lake
# that have long historical precipitation records.
# ============================================================

library(dplyr)
library(readr)
library(stringr)


# ============================================================
# 1. READ STATION INVENTORY
# ============================================================

station_file <- paste0(
  "C:/Users/charl/OneDrive/Documents/",
  "MathResearchThings/GreatSaltLake/",
  "raw_data/noaa_gsl_stations.csv"
)

stations <- read_csv(
  station_file,
  show_col_types = FALSE
)


# Look at the columns
print(names(stations))


# ============================================================
# 2. DISPLAY THE OLDEST-LOOKING STATIONS
# ============================================================

print(
  stations,
  n = 100
)