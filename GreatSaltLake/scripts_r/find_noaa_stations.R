# ============================================================
# find_noaa_stations.R
#
# Find GHCN stations around the Great Salt Lake
# ============================================================

library(readr)
library(dplyr)
library(stringr)


# NOAA station inventory
url <- paste0(
  "https://www.ncei.noaa.gov/pub/data/ghcn/daily/",
  "ghcnd-stations.txt"
)


# Download station inventory
stations_raw <- read_lines(url)


# Parse the fixed-width station file
stations <- tibble(
  ID = str_sub(stations_raw, 1, 11),
  Latitude = as.numeric(str_sub(stations_raw, 13, 20)),
  Longitude = as.numeric(str_sub(stations_raw, 22, 30)),
  Elevation_m = as.numeric(str_sub(stations_raw, 32, 37)),
  State = str_trim(str_sub(stations_raw, 39, 40)),
  Name = str_trim(str_sub(stations_raw, 42, 71))
)


# ============================================================
# Find Utah stations
# ============================================================

utah_stations <- stations %>%
  filter(State == "UT")


# Look for stations near the Great Salt Lake
gsl_stations <- utah_stations %>%
  filter(
    Latitude >= 40.3,
    Latitude <= 41.8,
    Longitude >= -113.5,
    Longitude <= -111.3
  ) %>%
  arrange(Name)


# Print results
print(gsl_stations, n = 200)


# Save the station list
write_csv(
  gsl_stations,
  "C:/Users/charl/OneDrive/Documents/MathResearchThings/GreatSaltLake/raw_data/noaa_gsl_stations.csv"
)


cat("\nFinished!\n")
cat("Found", nrow(gsl_stations), "stations.\n")