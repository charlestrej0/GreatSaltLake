library(tidyverse)
library(lubridate)

# =========================================================
# GREAT SALT LAKE NOAA DAILY PRECIPITATION COVERAGE
# =========================================================

# ---------------------------------------------------------
# 1. Set project directory
# ---------------------------------------------------------

setwd("C:/Users/charl/OneDrive/Documents/MathResearchThings/GreatSaltLake")


# ---------------------------------------------------------
# 2. Load station history
# ---------------------------------------------------------

history_file <- "raw_data/noaa_precipitation_station_history.csv"

station_history <- read_csv(
  history_file,
  show_col_types = FALSE
)


# ---------------------------------------------------------
# 3. Select historical stations
#
# For now, look at stations beginning before 1910.
# We can change this later.
# ---------------------------------------------------------

candidate_stations <- station_history %>%
  filter(First_Year <= 1910) %>%
  arrange(First_Year)

print(candidate_stations, n = 100)


# ---------------------------------------------------------
# 4. Function to download and parse a NOAA .dly file
# ---------------------------------------------------------

read_noaa_dly <- function(station_id) {
  
  url <- paste0(
    "https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/",
    station_id,
    ".dly"
  )
  
  cat("\nDownloading:", station_id, "\n")
  
  # Download to temporary file
  temp_file <- tempfile(fileext = ".dly")
  
  tryCatch(
    {
      download.file(
        url,
        temp_file,
        mode = "wb",
        quiet = TRUE
      )
    },
    error = function(e) {
      cat("Download failed:", station_id, "\n")
      return(NULL)
    }
  )
  
  # Read fixed-width NOAA file
  lines <- readLines(
    temp_file,
    warn = FALSE
  )
  
  # Delete temporary file
  unlink(temp_file)
  
  if (length(lines) == 0) {
    return(NULL)
  }
  
  # -------------------------------------------------------
  # Parse station/year/month/element
  # -------------------------------------------------------
  
  station <- str_trim(str_sub(lines, 1, 11))
  
  year <- as.integer(
    str_sub(lines, 12, 15)
  )
  
  month <- as.integer(
    str_sub(lines, 16, 17)
  )
  
  element <- str_trim(
    str_sub(lines, 18, 21)
  )
  
  # We only need precipitation
  lines <- lines[element == "PRCP"]
  
  if (length(lines) == 0) {
    return(NULL)
  }
  
  year <- year[element == "PRCP"]
  month <- month[element == "PRCP"]
  station <- station[element == "PRCP"]
  
  # -------------------------------------------------------
  # Extract the 31 possible daily values
  # -------------------------------------------------------
  
  output <- vector("list", length(lines) * 31)
  
  counter <- 1
  
  for (i in seq_along(lines)) {
    
    # Number of days in this month
    days_in_month <- days_in_month(
      as.Date(
        paste0(
          year[i],
          "-",
          sprintf("%02d", month[i]),
          "-01"
        )
      )
    )
    
    for (day in seq_len(days_in_month)) {
      
      start <- 22 + (day - 1) * 8
      
      value <- as.numeric(
        str_sub(
          lines[i],
          start,
          start + 4
        )
      )
      
      # NOAA uses -9999 for missing data
      if (value == -9999) {
        value <- NA_real_
      }
      
      # PRCP is reported in tenths of mm
      value_mm <- value / 10
      
      date <- as.Date(
        paste0(
          year[i],
          "-",
          sprintf("%02d", month[i]),
          "-",
          sprintf("%02d", day)
        )
      )
      
      output[[counter]] <- tibble(
        ID = station[i],
        Date = date,
        Precipitation_mm = value_mm
      )
      
      counter <- counter + 1
    }
  }
  
  bind_rows(output)
}


# ---------------------------------------------------------
# 5. Calculate coverage statistics
# ---------------------------------------------------------

calculate_coverage <- function(data, station_id) {
  
  if (is.null(data) || nrow(data) == 0) {
    return(
      tibble(
        ID = station_id,
        First_Date = as.Date(NA),
        Last_Date = as.Date(NA),
        Days_Observed = 0,
        Days_Expected = NA_real_,
        Coverage_Percent = NA_real_,
        Longest_Gap_Days = NA_real_
      )
    )
  }
  
  # Keep actual precipitation observations
  observed <- data %>%
    filter(!is.na(Precipitation_mm)) %>%
    arrange(Date)
  
  if (nrow(observed) == 0) {
    return(
      tibble(
        ID = station_id,
        First_Date = as.Date(NA),
        Last_Date = as.Date(NA),
        Days_Observed = 0,
        Days_Expected = NA_real_,
        Coverage_Percent = NA_real_,
        Longest_Gap_Days = NA_real_
      )
    )
  }
  
  first_date <- min(observed$Date)
  last_date <- max(observed$Date)
  
  expected_dates <- seq(
    first_date,
    last_date,
    by = "day"
  )
  
  days_expected <- length(expected_dates)
  days_observed <- nrow(observed)
  
  coverage <- 100 * days_observed / days_expected
  
  # Calculate gaps between observations
  gaps <- diff(observed$Date) - 1
  
  longest_gap <- ifelse(
    length(gaps) > 0,
    max(as.numeric(gaps)),
    0
  )
  
  tibble(
    ID = station_id,
    First_Date = first_date,
    Last_Date = last_date,
    Days_Observed = days_observed,
    Days_Expected = days_expected,
    Coverage_Percent = coverage,
    Longest_Gap_Days = longest_gap
  )
}


# ---------------------------------------------------------
# 6. Download all candidate stations
# ---------------------------------------------------------

all_station_data <- list()

coverage_results <- list()

for (i in seq_len(nrow(candidate_stations))) {
  
  station_id <- candidate_stations$ID[i]
  
  cat(
    "\n----------------------------------------\n"
  )
  
  cat(
    "Station",
    i,
    "of",
    nrow(candidate_stations),
    ":",
    station_id,
    "\n"
  )
  
  data <- read_noaa_dly(station_id)
  
  if (!is.null(data)) {
    
    all_station_data[[station_id]] <- data
    
    coverage_results[[station_id]] <-
      calculate_coverage(
        data,
        station_id
      )
  }
}


# ---------------------------------------------------------
# 7. Combine coverage results
# ---------------------------------------------------------

coverage <- bind_rows(
  coverage_results
)


# ---------------------------------------------------------
# 8. Add station information
# ---------------------------------------------------------

coverage <- coverage %>%
  left_join(
    station_history %>%
      select(
        ID,
        Name,
        Latitude,
        Longitude,
        Elevation_m,
        First_Year,
        Last_Year
      ),
    by = "ID"
  ) %>%
  arrange(desc(Coverage_Percent))


# ---------------------------------------------------------
# 9. Print results
# ---------------------------------------------------------

cat("\n\n========================================\n")
cat("NOAA DAILY PRECIPITATION COVERAGE\n")
cat("========================================\n\n")

print(
  coverage %>%
    select(
      ID,
      Name,
      First_Year,
      Last_Year,
      First_Date,
      Last_Date,
      Days_Observed,
      Coverage_Percent,
      Longest_Gap_Days
    ),
  n = 100
)


# ---------------------------------------------------------
# 10. Save results
# ---------------------------------------------------------

write_csv(
  coverage,
  "raw_data/noaa_daily_coverage.csv"
)


# ---------------------------------------------------------
# 11. Save the actual daily data
# ---------------------------------------------------------

daily_data <- bind_rows(all_station_data)

daily_data_wide <- daily_data %>%
  select(ID, Date, Precipitation_mm) %>%
  pivot_wider(
    names_from = ID,
    values_from = Precipitation_mm
  ) %>%
  arrange(Date)

write_csv(
  daily_data_wide,
  "raw_data/noaa_historical_daily_precipitation_wide.csv"
)

cat("\n\nFinished!\n")
cat("Coverage saved to:\n")
cat("raw_data/noaa_daily_coverage.csv\n\n")

cat("Daily precipitation saved to:\n")
cat("raw_data/noaa_historical_daily_precipitation.csv\n")
