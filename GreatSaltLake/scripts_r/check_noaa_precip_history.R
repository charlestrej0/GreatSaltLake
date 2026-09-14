# check_noaa_precip_history.R
#
# Check historical precipitation records for GSL stations
# =======================================================

library(tidyverse)
library(here)


# 1. Load GSL station list
# =============================

stations_file <- here(
  "raw_data",
  "noaa_gsl_stations.csv"
)

stations <- read_csv(
  stations_file,
  show_col_types = FALSE
)


# 2. Download NOAA GHCN station inventory
# =======================================

inventory_url <- paste0(
  "https://www.ncei.noaa.gov/pub/data/ghcn/daily/",
  "ghcnd-inventory.txt"
)

inventory_lines <- read_lines(inventory_url)


# ----------------------------------
# 3. Parse the fixed-width inventory
#
# GHCN inventory format:
# ID          = columns 1-11
# Latitude    = columns 13-20
# Longitude   = columns 22-30
# Element     = columns 32-35
# First year  = columns 37-40
# Last year   = columns 42-45
# ----------------------------------

inventory <- tibble(
  ID = str_trim(str_sub(inventory_lines, 1, 11)),
  Latitude = as.numeric(str_sub(inventory_lines, 13, 20)),
  Longitude = as.numeric(str_sub(inventory_lines, 22, 30)),
  Element = str_trim(str_sub(inventory_lines, 32, 35)),
  First_Year = as.integer(str_sub(inventory_lines, 37, 40)),
  Last_Year = as.integer(str_sub(inventory_lines, 42, 45))
)


# 4. Keep only precipitation records
# ==================================

precip_history <- inventory %>%
  filter(
    ID %in% stations$ID,
    Element == "PRCP"
  )


# 5. Attach station names
# =======================

precip_history <- stations %>%
  select(
    ID,
    Name,
    Latitude,
    Longitude,
    Elevation_m,
    State
  ) %>%
  left_join(
    precip_history %>%
      select(
        ID,
        Element,
        First_Year,
        Last_Year
      ),
    by = "ID"
  ) %>%
  filter(!is.na(First_Year)) %>%
  arrange(First_Year)


# 6. Display oldest precipitation stations
# ========================================

print(
  precip_history %>%
    select(
      ID,
      Name,
      Latitude,
      Longitude,
      Elevation_m,
      First_Year,
      Last_Year
    ),
  n = 50
)


# 7. Show stations with records beginning before 1900
# ===================================================

cat("\n========================================\n")
cat("Stations with PRCP beginning before 1900\n")
cat("========================================\n\n")

old_stations <- precip_history %>%
  filter(First_Year < 1900) %>%
  arrange(First_Year)

print(old_stations, n = 100)


# 8. Save results
# ===============

output_file <- here(
  "raw_data",
  "noaa_precipitation_station_history.csv"
)

write_csv(
  precip_history,
  output_file
)

cat("\nSaved to:", output_file, "\n")
