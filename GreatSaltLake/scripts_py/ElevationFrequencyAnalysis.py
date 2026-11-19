"""Analyze elevation cycles and track changes in their seasonal period."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FrequencyAnalysisConfig:
    """Settings for the elevation frequency and seasonal-drift analysis."""

    input_path: Optional[Path] = None
    date_column: str = "Date"
    value_column: str = "Lake_Elevation_ft"
    rolling_window_years: int = 20
    rolling_step_years: int = 1
    spectrum_min_period_months: float = 2.0
    spectrum_max_period_months: float = 60.0
    seasonal_period_min_months: float = 8.0
    seasonal_period_max_months: float = 18.0
    drift_threshold_months: float = 0.5
    spectrum_output_path: Optional[Path] = None
    rolling_output_path: Optional[Path] = None


def prepare_monthly_elevation(
    input_path: Path,
    date_column: str,
    value_column: str,
) -> pd.Series:
    """Load elevation observations and aggregate them to monthly means."""
    data = pd.read_csv(input_path)
    missing_columns = [
        column for column in (date_column, value_column) if column not in data.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Required columns not found: {missing_columns}. "
            f"Available columns: {list(data.columns)}"
        )

    observations = data[[date_column, value_column]].copy()
    observations[date_column] = pd.to_datetime(
        observations[date_column], errors="raise"
    )
    observations[value_column] = pd.to_numeric(
        observations[value_column], errors="coerce"
    )
    observations = observations.dropna(subset=[value_column])
    observations = observations.groupby(date_column)[value_column].mean().sort_index()
    monthly = observations.resample("ME").mean().astype(float)
    monthly.name = value_column

    if monthly.notna().sum() < 24:
        raise ValueError("At least 24 valid monthly observations are required.")
    return monthly


def calculate_spectrum(
    monthly: pd.Series,
    minimum_period_months: float = 2.0,
    maximum_period_months: float = 240.0,
    oversampling: int = 8,
) -> pd.DataFrame:
    """Calculate a one-sided FFT spectrum from the longest complete monthly run."""
    if minimum_period_months <= 0 or maximum_period_months <= minimum_period_months:
        raise ValueError("The FFT period range must be positive and increasing.")
    segment = _longest_contiguous_segment(monthly)
    values = segment.to_numpy(dtype=float)
    if oversampling < 1:
        raise ValueError("oversampling must be at least 1.")
    if len(values) < 3:
        raise ValueError("At least three continuous monthly observations are required.")

    time = np.arange(len(values), dtype=float)
    trend = np.column_stack((np.ones(len(time)), time - time.mean()))
    detrended = values - trend @ np.linalg.lstsq(trend, values, rcond=None)[0]
    tapered = detrended * np.hanning(len(values))
    fft_length = len(values) * oversampling
    transformed = np.fft.rfft(tapered, n=fft_length)
    frequencies = np.fft.rfftfreq(fft_length, d=1.0)
    power = np.abs(transformed) ** 2

    positive = frequencies > 0
    frequencies = frequencies[positive]
    power = power[positive]
    periods = 1 / frequencies
    in_range = (periods >= minimum_period_months) & (
        periods <= maximum_period_months
    )
    frequencies = frequencies[in_range]
    power = power[in_range]
    periods = periods[in_range]
    if not len(periods):
        raise ValueError("The FFT has no frequencies in the requested period range.")

    peak_candidates = np.flatnonzero(
        (power[1:-1] >= power[:-2]) & (power[1:-1] > power[2:])
    ) + 1
    if not len(peak_candidates):
        peak_candidates = np.array([int(np.argmax(power))])
    peak_candidates = peak_candidates[np.argsort(power[peak_candidates])[::-1]][:10]
    peak_ranks = np.full(len(power), np.nan)
    peak_ranks[peak_candidates] = np.arange(1, len(peak_candidates) + 1)
    normalized_power = power / power.sum() if power.sum() else power
    return pd.DataFrame(
        {
            "peak_rank": peak_ranks,
            "frequency_cycles_per_month": frequencies,
            "period_months": periods,
            "period_years": periods / 12,
            "normalized_power": normalized_power,
        }
    )


def _longest_contiguous_segment(monthly: pd.Series) -> pd.Series:
    """Return the longest run of consecutive months with observed values."""
    valid = monthly.notna().to_numpy()
    starts = np.flatnonzero(valid & np.r_[True, ~valid[:-1]])
    ends = np.flatnonzero(valid & np.r_[~valid[1:], True])
    if not len(starts):
        raise ValueError("No valid monthly observations are available.")
    longest = int(np.argmax(ends - starts))
    return monthly.iloc[starts[longest] : ends[longest] + 1]


def estimate_fft_period(
    values: np.ndarray,
    minimum_period_months: float,
    maximum_period_months: float,
    oversampling: int = 8,
) -> tuple[float, float]:
    """Return the strongest FFT period in a band and its share of band power."""
    if not np.isfinite(values).all():
        raise ValueError("FFT input must contain a complete run of monthly values.")
    if oversampling < 1:
        raise ValueError("oversampling must be at least 1.")

    time = np.arange(len(values), dtype=float)
    trend = np.column_stack((np.ones(len(time)), time - time.mean()))
    detrended = values - trend @ np.linalg.lstsq(trend, values, rcond=None)[0]
    transformed = np.fft.rfft(
        detrended * np.hanning(len(values)),
        n=len(values) * oversampling,
    )
    frequencies = np.fft.rfftfreq(len(values) * oversampling, d=1.0)
    power = np.abs(transformed) ** 2
    periods = np.full_like(frequencies, np.inf)
    positive = frequencies > 0
    periods[positive] = 1 / frequencies[positive]
    in_band = (
        positive
        & (periods >= minimum_period_months)
        & (periods <= maximum_period_months)
    )
    if not np.any(in_band):
        raise ValueError("The FFT has no frequencies in the seasonal period range.")

    band_indices = np.flatnonzero(in_band)
    peak_index = band_indices[np.argmax(power[in_band])]
    band_power = float(power[band_indices].sum())
    relative_power = float(power[peak_index] / band_power) if band_power else 0.0
    return float(periods[peak_index]), relative_power


def calculate_rolling_periods(
    monthly: pd.Series,
    config: FrequencyAnalysisConfig,
) -> pd.DataFrame:
    """Track the strongest seasonal FFT period in complete monthly windows."""
    window_months = config.rolling_window_years * 12
    step_months = config.rolling_step_years * 12
    if window_months < 24 or step_months < 1:
        raise ValueError("Rolling window and step must be positive and at least 2 years.")
    if config.seasonal_period_min_months >= config.seasonal_period_max_months:
        raise ValueError("The minimum seasonal period must be below the maximum.")

    results: list[dict[str, float | int | pd.Timestamp]] = []
    for start in range(0, len(monthly) - window_months + 1, step_months):
        window = monthly.iloc[start : start + window_months]
        if window.isna().any():
            continue

        period, relative_power = estimate_fft_period(
            window.to_numpy(dtype=float),
            config.seasonal_period_min_months,
            config.seasonal_period_max_months,
        )
        midpoint = window.index[len(window) // 2]
        results.append(
            {
                "window_start": window.index[0],
                "window_end": window.index[-1],
                "window_midpoint": midpoint,
                "valid_months": window_months,
                "coverage": 1.0,
                "dominant_period_months": period,
                "fft_peak_relative_power": relative_power,
            }
        )

    if not results:
        raise ValueError(
            "No rolling windows have complete monthly observations. "
            "FFT requires a regular series; try a shorter window."
        )
    return pd.DataFrame(results)


def summarize_period_drift(
    rolling: pd.DataFrame,
    threshold_months: float,
) -> tuple[float, float, str]:
    """Fit a linear period trend and classify drift using the configured threshold."""
    if threshold_months < 0:
        raise ValueError("drift_threshold_months must be zero or greater.")
    dates = pd.to_datetime(rolling["window_midpoint"])
    years = (dates - dates.iloc[0]).dt.total_seconds().to_numpy() / (
        365.2425 * 24 * 60 * 60
    )
    periods = rolling["dominant_period_months"].to_numpy(dtype=float)
    if len(periods) < 2:
        return float("nan"), float("nan"), "insufficient windows to assess drift"

    slope = float(np.polyfit(years, periods, 1)[0])
    total_change = slope * float(years[-1] - years[0])
    classification = (
        "drifting"
        if abs(total_change) > threshold_months
        else "stable within the configured threshold"
    )
    return slope, total_change, classification


def plot_frequency_analysis(
    monthly: pd.Series,
    spectrum: pd.DataFrame,
    rolling: pd.DataFrame,
    config: FrequencyAnalysisConfig,
) -> None:
    """Show the full-record spectrum and period estimates from rolling windows."""
    figure, (spectrum_axis, period_axis) = plt.subplots(
        2, 1, figsize=(13, 9), constrained_layout=True
    )
    spectrum_curve = spectrum.loc[
        (spectrum["period_months"] >= config.spectrum_min_period_months)
        & (spectrum["period_months"] <= config.spectrum_max_period_months)
    ].sort_values("period_months")
    spectrum_axis.plot(
        spectrum_curve["period_months"],
        spectrum_curve["normalized_power"],
        color="tab:blue",
        linewidth=1,
    )
    spectrum_axis.set_xlim(
        config.spectrum_min_period_months,
        config.spectrum_max_period_months,
    )
    spectrum_axis.set_title(
        "Elevation FFT Spectrum (up to "
        f"{config.spectrum_max_period_months / 12:g} years)"
    )
    spectrum_axis.set_xlabel("Period (months)")
    spectrum_axis.set_ylabel("Share of FFT power")
    spectrum_axis.grid(True, alpha=0.3)
    spectrum_axis.legend()

    tolerance = config.drift_threshold_months
    period_axis.axhspan(
        12 - tolerance,
        12 + tolerance,
        color="tab:green",
        alpha=0.12,
        label=f"Within +/- {tolerance:g} months of 12",
    )
    period_axis.plot(
        rolling["window_midpoint"],
        rolling["dominant_period_months"],
        marker="o",
        markersize=4,
        linewidth=1.2,
        color="tab:purple",
        label=f"{config.rolling_window_years}-year window FFT",
    )
    period_axis.axhline(12, color="tab:red", linestyle="--", label="12 months")
    period_axis.set_ylim(
        config.seasonal_period_min_months,
        config.seasonal_period_max_months,
    )
    period_axis.set_title("Seasonal cycle length over time")
    period_axis.set_xlabel("Center date of each window")
    period_axis.set_ylabel("Strongest cycle length (months)")
    period_axis.grid(True, alpha=0.3)
    period_axis.legend()
    period_axis.text(
        0.01,
        0.02,
        "Each dot is the strongest "
        f"{config.seasonal_period_min_months:g}-"
        f"{config.seasonal_period_max_months:g} month FFT cycle in one complete "
        f"{config.rolling_window_years}-year window.",
        transform=period_axis.transAxes,
        fontsize=9,
        va="bottom",
    )
    segment = _longest_contiguous_segment(monthly)
    figure.suptitle(
        "FFT uses the longest uninterrupted monthly record "
        f"({segment.index[0]:%Y-%m} to {segment.index[-1]:%Y-%m})"
    )
    plt.show()
    plt.close(figure)


def main() -> None:
    """Run the configurable elevation frequency analysis."""
    config = FrequencyAnalysisConfig()
    project_folder = Path(__file__).resolve().parent.parent
    input_path = (
        config.input_path
        or project_folder / "raw_data" / "usgs_lake_elevation.csv"
    )
    spectrum_output = (
        config.spectrum_output_path
        or project_folder / "processed_data" / "elevation_frequency_peaks.csv"
    )
    rolling_output = (
        config.rolling_output_path
        or project_folder / "processed_data" / "elevation_rolling_periods.csv"
    )

    monthly = prepare_monthly_elevation(
        input_path, config.date_column, config.value_column
    )
    spectrum = calculate_spectrum(
        monthly,
        config.spectrum_min_period_months,
        config.spectrum_max_period_months,
    )
    rolling = calculate_rolling_periods(monthly, config)
    slope, total_change, classification = summarize_period_drift(
        rolling, config.drift_threshold_months
    )

    spectrum_output.parent.mkdir(parents=True, exist_ok=True)
    rolling_output.parent.mkdir(parents=True, exist_ok=True)
    spectrum.to_csv(spectrum_output, index=False)
    rolling.to_csv(rolling_output, index=False)
    plot_frequency_analysis(monthly, spectrum, rolling, config)

    print(f"Monthly observations: {monthly.notna().sum()} of {len(monthly)}")
    segment = _longest_contiguous_segment(monthly)
    print(
        "FFT segment: "
        f"{segment.index[0].date()} to {segment.index[-1].date()} "
        f"({len(segment)} consecutive months)"
    )
    print("Strongest FFT peaks (period in months):")
    peaks = spectrum.dropna(subset=["peak_rank"]).sort_values("peak_rank")
    print(peaks.head(5).to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"Rolling window: {config.rolling_window_years} years")
    print(f"Valid rolling windows: {len(rolling)}")
    print(
        "Median rolling seasonal period: "
        f"{rolling['dominant_period_months'].median():.3f} months"
    )
    print(f"Estimated period change: {total_change:.3f} months")
    print(f"Estimated period trend: {slope:.4f} months/year")
    print(
        f"Seasonal period assessment: {classification} "
        f"(drift threshold: {config.drift_threshold_months:.2f} months)"
    )
    print(f"Wrote spectral peaks to: {spectrum_output}")
    print(f"Wrote rolling estimates to: {rolling_output}")


if __name__ == "__main__":
    main()
