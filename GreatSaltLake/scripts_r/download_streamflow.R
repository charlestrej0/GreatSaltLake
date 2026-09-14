# download_streamflow.R
# Downloads daily USGS streamflow for multiple rivers

library(dataRetrieval)
library(dplyr)
library(readr)
library(here)


# USER INPUT
#-----------

sites <- c(
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
)

river_names <- c(
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
)

parameter <- "00060"        # Discharge (cfs)

start_date <- "1900-01-01"
end_date   <- Sys.Date()


# Download each river
#--------------------

master <- NULL

for(i in seq_along(sites)) {
  
  cat("Downloading", river_names[i], "...\n")
  
  temp <- readNWISdv(
    siteNumbers = sites[i],
    parameterCd = parameter,
    startDate = start_date,
    endDate = end_date
  )
  
  # Find the discharge column automatically
  flow_col <- grep("^X_00060", names(temp), value = TRUE)[1]
  
  temp <- temp |>
    select(Date, all_of(flow_col)) |>
    rename(!!river_names[i] := all_of(flow_col))
  
  if (is.null(master)) {
    
    master <- temp
    
  } else {
    
    master <- full_join(master, temp, by = "Date")
    
  }
}


# Sort by date
#-------------

master <- master |>
  arrange(Date)



# Add total inflow and reporting count
#-------------------------------------

river_cols <- river_names

master <- master |>
  mutate(
    `Total Inflow (ft^3/s)` =
      rowSums(select(., all_of(river_cols)), na.rm = TRUE),
    
    `Number of Gauges Reporting` =
      rowSums(!is.na(select(., all_of(river_cols))))
  )


# Save
#-----

write_csv(
  master,
  "C:/Users/charl/OneDrive/Documents/MathResearchThings/GreatSaltLake/raw_data/usgs_streamflow.csv"
)

cat("\nFinished downloading streamflow data!\n")
print(head(master))
