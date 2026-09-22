# ============================================================
# Download NOAA GHCNh Weather Data
# ============================================================
#
# Collects historical hourly weather observations for NOAA
# stations in the Great Salt Lake study region.
#
# Variables:
#   - Temperature
#   - Relative Humidity
#   - Station-Level Pressure
#   - Wind Speed
#   - Dew Point Temperature
#
# Data source:
# NOAA Global Historical Climatology Network hourly (GHCNh)
#
# Output:
# raw_data/noaa_historical_daily_weather.csv
# ============================================================


# ------------------------------------------------------------
# 1. Load packages
# ------------------------------------------------------------

library(tidyverse)
library(lubridate)
library(here)


# ------------------------------------------------------------
# 2. File paths
# ------------------------------------------------------------

station_file <- here(
  "raw_data",
  "noaa_gsl_stations.csv"
)

output_file <- here(
  "raw_data",
  "noaa_historical_daily_weather.csv"
)


# ------------------------------------------------------------
# 3. Read NOAA station list
# ------------------------------------------------------------

stations <- read_csv(
  station_file,
  show_col_types = FALSE
)

cat("Number of GSL-region stations:", nrow(stations), "\n")


# ------------------------------------------------------------
# 4. GHCNh base URL
# ------------------------------------------------------------

base_url <- paste0(
  "https://www.ncei.noaa.gov/",
  "oa/global-historical-climatology-network/",
  "hourly/access/by-station/"
)


# ------------------------------------------------------------
# 5. Function to download one station
# ------------------------------------------------------------

download_station <- function(station_id) {
  
  file_name <- paste0(
    "GHCNh_",
    station_id,
    "_por.psv"
  )
  
  url <- paste0(
    base_url,
    file_name
  )
  
  temp_file <- tempfile(
    fileext = ".psv"
  )
  
  cat("\nDownloading:", station_id, "\n")
  
  success <- tryCatch(
    {
      download.file(
        url,
        temp_file,
        mode = "wb",
        quiet = TRUE
      )
      
      TRUE
    },
    error = function(e) {
      FALSE
    }
  )
  
  
  # Stop if download failed
  if (!success) {
    cat(
      "No GHCNh data found for:",
      station_id,
      "\n"
    )
    
    return(NULL)
  }
  
  
  # Read GHCNh PSV file
  data <- tryCatch(
    {
      read_delim(
        temp_file,
        delim = "|",
        show_col_types = FALSE,
        na = c(
          "",
          "NA",
          "-9999",
          "-999.9"
        )
      )
    },
    error = function(e) {
      NULL
    }
  )
  
  
  # Delete temporary file
  unlink(temp_file)
  
  
  if (is.null(data)) {
    return(NULL)
  }
  
  
  # ----------------------------------------------------------
  # Keep only variables needed for the project
  # ----------------------------------------------------------
  
  required_columns <- c(
    "DATE",
    "temperature",
    "relative_humidity",
    "station_level_pressure",
    "wind_speed",
    "dew_point_temperature"
  )
  
  
  available_columns <- intersect(
    required_columns,
    names(data)
  )
  
  
  if (!"DATE" %in% available_columns) {
    cat(
      "DATE column missing for:",
      station_id,
      "\n"
    )
    
    return(NULL)
  }
  
  
  data <- data %>%
    select(
      all_of(available_columns)
    )
  
  
  # ----------------------------------------------------------
  # Convert date/time
  # ----------------------------------------------------------
  
  data <- data %>%
    mutate(
      DATE = ymd_hms(
        DATE,
        quiet = TRUE,
        tz = "UTC"
      )
    )
  
  
  # ----------------------------------------------------------
  # Add station ID
  # ----------------------------------------------------------
  
  data <- data %>%
    mutate(
      ID = station_id
    )
  
  
  return(data)
}


# ------------------------------------------------------------
# 6. Download all stations
# ------------------------------------------------------------

station_ids <- stations$ID


weather_data <- list()


for (i in seq_along(station_ids)) {
  
  station_id <- station_ids[i]
  
  result <- download_station(
    station_id
  )
  
  if (!is.null(result)) {
    weather_data[[length(weather_data) + 1]] <- result
  }
  
}


# ------------------------------------------------------------
# 7. Combine stations
# ------------------------------------------------------------

if (length(weather_data) == 0) {
  
  stop(
    "No GHCNh station data were successfully downloaded."
  )
  
}


weather_data <- bind_rows(
  weather_data
)


# ------------------------------------------------------------
# 8. Create daily averages
# ------------------------------------------------------------

weather_daily <- weather_data %>%
  mutate(
    Date = as.Date(DATE)
  ) %>%
  group_by(
    ID,
    Date
  ) %>%
  summarise(
    
    Temperature_C =
      mean(
        temperature,
        na.rm = TRUE
      ),
    
    Relative_Humidity_percent =
      mean(
        relative_humidity,
        na.rm = TRUE
      ),
    
    Station_Pressure_hPa =
      mean(
        station_level_pressure,
        na.rm = TRUE
      ),
    
    Wind_Speed_m_s =
      mean(
        wind_speed,
        na.rm = TRUE
      ),
    
    Dew_Point_C =
      mean(
        dew_point_temperature,
        na.rm = TRUE
      ),
    
    .groups = "drop"
  )


# ------------------------------------------------------------
# 9. Replace invalid NaN values with NA
# ------------------------------------------------------------

weather_daily <- weather_daily %>%
  mutate(
    across(
      where(is.numeric),
      ~ ifelse(
        is.nan(.x),
        NA,
        .x
      )
    )
  )


# ------------------------------------------------------------
# 10. Create separate columns for each station
# ------------------------------------------------------------

temperature_wide <- weather_daily %>%
  select(
    ID,
    Date,
    Temperature_C
  ) %>%
  pivot_wider(
    names_from = ID,
    values_from = Temperature_C,
    names_glue = "Temperature_{ID}_C"
  )


humidity_wide <- weather_daily %>%
  select(
    ID,
    Date,
    Relative_Humidity_percent
  ) %>%
  pivot_wider(
    names_from = ID,
    values_from = Relative_Humidity_percent,
    names_glue = "Humidity_{ID}_percent"
  )


pressure_wide <- weather_daily %>%
  select(
    ID,
    Date,
    Station_Pressure_hPa
  ) %>%
  pivot_wider(
    names_from = ID,
    values_from = Station_Pressure_hPa,
    names_glue = "Pressure_{ID}_hPa"
  )


wind_wide <- weather_daily %>%
  select(
    ID,
    Date,
    Wind_Speed_m_s
  ) %>%
  pivot_wider(
    names_from = ID,
    values_from = Wind_Speed_m_s,
    names_glue = "Wind_{ID}_m_s"
  )


dew_point_wide <- weather_daily %>%
  select(
    ID,
    Date,
    Dew_Point_C
  ) %>%
  pivot_wider(
    names_from = ID,
    values_from = Dew_Point_C,
    names_glue = "DewPoint_{ID}_C"
  )


# ------------------------------------------------------------
# 11. Combine all variables
# ------------------------------------------------------------

weather_wide <- temperature_wide %>%
  full_join(
    humidity_wide,
    by = "Date"
  ) %>%
  full_join(
    pressure_wide,
    by = "Date"
  ) %>%
  full_join(
    wind_wide,
    by = "Date"
  ) %>%
  full_join(
    dew_point_wide,
    by = "Date"
  ) %>%
  arrange(Date)


# ------------------------------------------------------------
# 12. Save data
# ------------------------------------------------------------

write_csv(
  weather_wide,
  output_file
)


# ------------------------------------------------------------
# 13. Report results
# ------------------------------------------------------------

cat("\n----------------------------------------\n")
cat("GHCNh weather download complete\n")
cat("----------------------------------------\n")

cat(
  "Stations requested:",
  length(station_ids),
  "\n"
)

cat(
  "Stations successfully downloaded:",
  length(weather_data),
  "\n"
)

cat(
  "Date range:",
  min(weather_wide$Date, na.rm = TRUE),
  "to",
  max(weather_wide$Date, na.rm = TRUE),
  "\n"
)

cat(
  "Saved to:",
  output_file,
  "\n"
)