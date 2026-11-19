# Great Salt Lake Mathematical Modeling

Reproducible Python (and legacy R) scripts that collect, update, and combine
historical Great Salt Lake (GSL) hydrologic and climate data into one monthly
dataset for modeling lake volume.

## What we are trying to do

Great Salt Lake has no outlet: its volume rises and falls with the balance
between water coming in and water evaporating. Our research team is building an
interpretable mathematical model, a system of differential equations, to
explain historical lake-volume changes and how the drivers interact.

The core water balance is

```
dV/dt = Q_in(t) + A(h) * [P(t) - E(t)] + Q_other(t)
```

| Term | Meaning | Data used |
|---|---|---|
| `V` | Lake volume (acre-ft) | Lake elevation converted with USGS area–volume tables |
| `h` | Lake surface elevation (ft) | USGS gauge 10010000, Saltair |
| `A(h)` | Lake surface area at elevation `h` (acres) | USGS elevation–area–volume tables |
| `Q_in` | River and canal inflow | 11 USGS streamflow gauges |
| `P` | Precipitation falling directly on the lake | gridMET, ERA5-Land, NOAA stations |
| `E` | Evaporation from the lake surface | Estimated from radiation, wind, humidity, temperature (gridMET, ERA5-Land, NOAA) |
| `Q_other` | Unmeasured terms: groundwater, ungauged inflow, withdrawals | Estimated as the water-balance residual |

Research approach:

1. Collect and standardize historical hydrologic and climate data
2. Convert lake elevation to surface area and volume
3. Analyze patterns and relationships among the drivers
4. Build the water-balance differential-equation model
5. Evaluate it against historical lake-volume changes

Planned extensions:

- **Salinity correction for evaporation.** Salty water evaporates more slowly,
  and salinity rises as the lake shrinks (salt mass ÷ volume). This adds a
  second equation for salt mass, following Mohammed & Tarboton (2012).
  Candidate data: UGS brine chemistry database and the Dunn et al. HydroShare
  salinity compilation.
- **Two-arm model.** The railroad causeway splits the lake into a north arm
  and a south arm with different levels and salinity. The USGS tables include
  separate area–volume curves for each arm.
- **Not yet collected:** PRISM gridded precipitation and SNOTEL snowpack.

## Repository layout

```
GreatSaltLake/
├── raw_data/          Downloaded source data, in each source's native units (mostly metric)
├── processed_data/    gsl_monthly_master.csv (imperial units) and data_status.json
├── scripts_py/        Python download, processing, and update scripts
├── scripts_r/         Earlier R versions of some download scripts (kept for reference)
└── logs/              Update logs (not committed)
```

Download caches (`raw_data/*_cache/`) and logs are git-ignored; they make
re-runs fast and are rebuilt automatically if deleted.

## Data sources

| Source | Script | Output (`raw_data/`) | Period | What it provides |
|---|---|---|---|---|
| USGS lake elevation, gauge 10010000 (Saltair Boat Harbor) | `download_usgs_lake_elv.py` | `usgs_lake_elevation.csv` | 1847–present | Daily lake surface elevation, ft above NGVD29. Measures the **south arm**. |
| USGS streamflow, 11 gauges | `download_streamflow.py` | `usgs_streamflow.csv` | 1907–present | Daily discharge (ft³/s) for the Bear, Weber (main, N. Fork, S. Fork), Jordan, Howard Slough, Kays Creek, Farmington Creek, SLC Sewage Canal, Goggin Drain, and Lee Creek, plus total inflow |
| NOAA GHCN-Daily precipitation | `download_noaa_precipitation.py` | `noaa_historical_daily_precipitation_wide.csv` | 1893–present | Daily precipitation (mm) at 28 long-record stations near the lake (records starting by 1910). Also writes the station list used by the weather script. |
| NOAA GHCNh hourly weather | `download_noaa_weather_hourly.py` | `noaa_historical_daily_weather.csv` | 1948–present | Daily means of temperature, humidity, station pressure, wind speed, and dew point at 9 stations (mostly airports, incl. Salt Lake City and Ogden) |
| ERA5-Land monthly means (Copernicus) | `download_era5_land_monthly.py` | `era5_land_monthly_weather.csv` | 1950–last full year | Air and skin temperature, dew point, pressure, wind, **solar and longwave radiation (incoming and net)**, precipitation, evaporation, and potential evaporation, averaged over lake-level grid cells. Needs a free CDS API key. |
| gridMET daily (Abatzoglou 2013) | `download_gridmet_daily.py` | `gridmet_daily_weather.csv` | 1979–present | Daily Tmax/Tmin, RH max/min, specific humidity, vapor pressure deficit, **solar radiation**, wind speed, precipitation, and grass/alfalfa reference ET, averaged over lake-level 4 km cells |
| USGS GSL elevation–area–volume tables (Root 2023) | `download_usgs_lake_hypsometry.py` | `usgs_gsl_elevation_area_volume.csv` | Static (2002–2016 survey) | Area and volume vs. elevation (0.01 ft steps) for the total lake, south arm, north arm, Bear River Bay, and Farmington Bay |

Notes on the sources:

- **Lake-level cells only.** ERA5-Land and gridMET are averaged over grid cells
  near lake elevation; mountain cells are excluded so temperature and pressure
  reflect the lake, not the Wasatch.
- **Direct precipitation.** For the `P` term, use gridMET or ERA5-Land. The NOAA
  station average includes mountain stations, whose rain already reaches the lake
  through streamflow, so using it would count that water twice.
- **Wind.** ERA5-Land wind speed is computed from averaged wind components and
  runs low (labeled `Wind_Vector_Speed`). Prefer gridMET or NOAA station wind.
- **ERA5-Land evaporation** comes from a freshwater lake/land model and is a
  comparison, not a measurement of hypersaline-lake evaporation.
- **Single-gauge volume.** Total-lake area and volume are computed from the
  south-arm gauge, so they are approximate when the arms' levels differ.

## The monthly master table

`processed_data/gsl_monthly_master.csv` combines every source by month
(month-end dates), in **imperial units**:

| Group | Example columns |
|---|---|
| Lake | `Lake_Elevation_Mean_ft`, `Lake_Area_Mean_acres`, `Lake_Volume_Mean_acre_ft`, `Delta_Lake_Volume_acre_ft` (the dV/dt term) |
| Inflow | One column per gauge (ft³/s), `Total_Inflow_Mean_ft3_s`, `Total_Inflow_MAF` |
| Precipitation | `GRIDMET_Precipitation_in`, `ERA5_Precipitation_in`, `NOAA_Station_Mean_Precip_in`, per-station NOAA columns |
| Evaporation drivers | Temperature (°F), humidity (%), vapor pressure deficit (inHg), wind (mph), radiation (BTU/ft²/hr), reference ET and potential evaporation (in) |
| Data coverage | `NOAA_Stations_Reporting`, `NOAA_Weather_Stations_Reporting`, `GRIDMET_Days_Reporting`, `Streamflow_Days_Reporting` |

Monthly aggregation rules: amounts (precipitation, ET, evaporation) are monthly
**sums**, left blank when fewer than 90% of days have data; conditions
(temperature, humidity, wind, radiation, pressure) are monthly **means**.

`processed_data/data_status.json` records when each source was last updated
and the latest date it covers (for the project website).

## Updating the data

Everything is refreshed with one command, run from the `GreatSaltLake` folder:

```bash
.venv/Scripts/python.exe scripts_py/update_all_data.py
```

It runs each download script in order, retries a failed step once (keeping the
previous data if it still fails), rebuilds the master table, writes a log to
`logs/`, and updates `data_status.json`. A full run takes about 15 minutes.

Useful options:

```bash
.venv/Scripts/python.exe scripts_py/update_all_data.py --only streamflow lake_elevation
.venv/Scripts/python.exe scripts_py/update_all_data.py --skip era5
.venv/Scripts/python.exe scripts_py/update_all_data.py --no-process
```

Things to know:

- Close `gsl_monthly_master.csv` in Excel first; the update stops if the file is locked.
- Don't switch git branches while an update is running.
- ERA5-Land requires a Copernicus CDS account and API key in `~/.cdsapirc`
  (see https://cds.climate.copernicus.eu/how-to-api).

### Weekly automatic update

On the maintainer's computer, a Windows Task Scheduler task named
**"Great Salt Lake weekly data update"** runs the update every Monday at
7:00 AM (or as soon as possible if the computer was off). It only runs when
the repository is on the `R-Python` branch and does not commit anything; each
run adds a line to `logs/run_history.log`. Review and commit the refreshed
files when convenient.

## Branches

| Branch | Contents |
|---|---|
| `main` | Stable data pipeline and datasets |
| `R-Python` | Active development of the data pipeline |
| `QGIS-(Mapping)` | QGIS map of the USGS gauges (`GreatSaltLake/qgis/`) |
| `nonparametric-model` | Exploratory nonparametric (spline) lake-level model |

## References

- Abatzoglou, J.T., 2013, Development of gridded surface meteorological data for
  ecological applications and modelling: International Journal of Climatology,
  https://doi.org/10.1002/joc.3413
- Mohammed, I.N., and Tarboton, D.G., 2012, An examination of the sensitivity of
  the Great Salt Lake to changes in inputs: Water Resources Research,
  https://doi.org/10.1029/2012WR011908
- Muñoz-Sabater, J., et al., 2021, ERA5-Land: a state-of-the-art global
  reanalysis dataset for land applications: Earth System Science Data,
  https://doi.org/10.5194/essd-13-4349-2021
- Root, J.C., 2023, Half-meter topobathymetric elevation model and
  elevation-area-volume tables for Great Salt Lake, Utah, 2002–2016: U.S.
  Geological Survey data release, https://doi.org/10.5066/P9DGG75W
- NOAA National Centers for Environmental Information: Global Historical
  Climatology Network daily (GHCN-Daily) and hourly (GHCNh)
- U.S. Geological Survey, National Water Information System,
  https://waterdata.usgs.gov/nwis
