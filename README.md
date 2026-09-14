# Great Salt Lake Mathematical Modeling

This repository contains reproducible R and Python scripts for collecting, processing, and analyzing historical Great Salt Lake hydrologic and environmental data.

The project investigates the factors contributing to historical fluctuations in Great Salt Lake water volume. Data from sources including USGS, NOAA, PRISM, and SNOTEL are used to examine precipitation, streamflow, evaporation, snowpack, lake level, and other environmental variables.

The primary research goal is to develop and evaluate an interpretable mathematical model, potentially using a system of differential equations, to explain historical Great Salt Lake volume dynamics and the interactions among major hydrologic drivers.

## Project Structure

- `raw_data/` — Collected and processed datasets
- `scripts_r/` — R scripts for data collection and processing
- `scripts_python/` — Python scripts for analysis and mathematical modeling

## Data Sources

- **USGS** — Streamflow and hydrologic data
- **NOAA** — Historical weather and precipitation data
- **PRISM** — Spatial precipitation data
- **SNOTEL** — Snowpack and related hydrologic data
- **Great Salt Lake monitoring data** — Historical lake elevation and water-level data

## Research Approach

1. Collect historical environmental and hydrologic data
2. Process and standardize datasets
3. Analyze temporal patterns and relationships
4. Convert lake elevation measurements to volume
5. Develop a water-balance-based mathematical model
6. Evaluate the model against historical lake-volume fluctuations
