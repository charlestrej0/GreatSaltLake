"""Reusable continuous-time SINDy tools and a Great Salt Lake example."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pysindy as ps
from scipy.integrate import solve_ivp
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass
class SparseRegressionConfig:
    """Settings for the continuous-time SINDy feature library and optimizer."""

    thresholds: tuple = field(
        default_factory=lambda: tuple(np.logspace(-3, -0.5, 24))
    )
    polynomial_degree: int = 2
    ridge_alpha: float = 0.05
    max_cv_splits: int = 5
    max_iterations: int = 100
    n_jobs: Optional[int] = -1


class DynamicsIntegrationError(RuntimeError):
    """Raised when a candidate SINDy equation cannot be numerically integrated."""


class ControlledSINDyRegressor(BaseEstimator, RegressorMixin):
    """PySINDy estimator for one continuous state with measured forcing inputs."""

    def __init__(
        self,
        state_name: str = "state",
        control_names: Optional[Sequence[str]] = None,
        threshold: float = 0.1,
        polynomial_degree: int = 2,
        alpha: float = 0.05,
        max_iterations: int = 100,
    ):
        self.state_name = state_name
        self.control_names = control_names
        self.threshold = threshold
        self.polynomial_degree = polynomial_degree
        self.alpha = alpha
        self.max_iterations = max_iterations

    def fit(self, X, y):
        """Fit dx/dt = f(x, u), where the first feature is the state."""
        if self.threshold <= 0:
            raise ValueError("threshold must be positive.")
        if self.polynomial_degree < 1:
            raise ValueError("polynomial_degree must be at least 1.")

        values = np.asarray(X, dtype=float)
        derivative = np.asarray(y, dtype=float).reshape(-1, 1)
        if values.ndim != 2 or values.shape[1] < 2:
            raise ValueError("X must contain one state column and at least one control.")
        if len(values) != len(derivative):
            raise ValueError("X and y must contain the same number of rows.")

        controls = values[:, 1:]
        control_names = (
            list(self.control_names)
            if self.control_names is not None
            else [f"control_{index}" for index in range(controls.shape[1])]
        )
        if len(control_names) != controls.shape[1]:
            raise ValueError("control_names must match the number of control columns.")

        self.model_ = ps.SINDy(
            feature_library=ps.PolynomialLibrary(
                degree=self.polynomial_degree,
                include_bias=True,
            ),
            optimizer=ps.STLSQ(
                threshold=self.threshold,
                alpha=self.alpha,
                max_iter=self.max_iterations,
                normalize_columns=False,
            ),
        )
        self.model_.fit(
            x=values[:, :1],
            t=1.0,
            x_dot=derivative,
            u=controls,
            feature_names=[self.state_name, *control_names],
        )
        self.n_features_in_ = values.shape[1]
        self.feature_names_in_ = np.asarray(
            [self.state_name, *control_names], dtype=object
        )
        return self

    def predict(self, X):
        """Evaluate the learned state derivative for state and control values."""
        values = np.asarray(X, dtype=float)
        if values.ndim != 2 or values.shape[1] != self.n_features_in_:
            raise ValueError(
                f"X must have {self.n_features_in_} state/control columns."
            )
        prediction = self.model_.predict(
            x=values[:, :1],
            u=values[:, 1:],
        )
        return np.asarray(prediction).reshape(-1)


def prepare_dynamics_data(
    data: pd.DataFrame,
    state_column: str,
    control_columns: Sequence[str],
    time_column: str = "Date",
    max_gap_days: int = 62,
):
    """Estimate state derivatives from consecutive observations and average controls.

    Derivatives use finite differences over each observed interval. Intervals
    longer than max_gap_days or containing missing state/forcing values are
    excluded rather than interpolated.
    """
    required = [time_column, state_column, *control_columns]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"Required dynamics columns not found: {missing}")
    if not control_columns:
        raise ValueError("At least one measured forcing/control is required.")
    if max_gap_days <= 0:
        raise ValueError("max_gap_days must be positive.")

    observations = data[required].copy()
    observations[time_column] = pd.to_datetime(
        observations[time_column], errors="raise"
    )
    observations = observations.sort_values(time_column).dropna(subset=required)
    for column in [state_column, *control_columns]:
        observations[column] = pd.to_numeric(observations[column], errors="raise")

    current = observations.iloc[:-1].reset_index(drop=True)
    following = observations.iloc[1:].reset_index(drop=True)
    elapsed_days = (
        following[time_column] - current[time_column]
    ).dt.total_seconds() / 86400
    valid_intervals = (elapsed_days > 0) & (elapsed_days <= max_gap_days)
    current = current.loc[valid_intervals].reset_index(drop=True)
    following = following.loc[valid_intervals].reset_index(drop=True)
    elapsed_years = elapsed_days.loc[valid_intervals].to_numpy() / 365.2425
    if not len(elapsed_years):
        raise ValueError(
            "No valid consecutive state/control observations; check coverage "
            "and max_gap_days."
        )

    result = pd.DataFrame(
        {
            "time_start": current[time_column].to_numpy(),
            "time_end": following[time_column].to_numpy(),
            "duration_years": elapsed_years,
            "state_start": current[state_column].to_numpy(),
            "state_end": following[state_column].to_numpy(),
        }
    )
    result["state_mid"] = (result["state_start"] + result["state_end"]) / 2
    result["state_derivative"] = (
        result["state_end"] - result["state_start"]
    ) / result["duration_years"]
    for column in control_columns:
        result[column] = (current[column].to_numpy() + following[column].to_numpy()) / 2
    return result


def build_dynamics_pipeline(
    config: SparseRegressionConfig,
    state_column: str,
    control_columns: Sequence[str],
    threshold: float,
):
    """Build a preprocessing and controlled-SINDy pipeline for one threshold."""
    if not config.thresholds or any(value <= 0 for value in config.thresholds):
        raise ValueError("SINDy thresholds must be a non-empty set of positive values.")
    if config.polynomial_degree < 1:
        raise ValueError("polynomial_degree must be at least 1.")
    if config.ridge_alpha < 0:
        raise ValueError("ridge_alpha cannot be negative.")
    if config.max_iterations < 1:
        raise ValueError("max_iterations must be positive.")
    if not control_columns:
        raise ValueError("At least one forcing/control column is required.")

    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                ControlledSINDyRegressor(
                    state_name=f"z({state_column})",
                    control_names=[f"z({column})" for column in control_columns],
                    threshold=threshold,
                    polynomial_degree=config.polynomial_degree,
                    alpha=config.ridge_alpha,
                    max_iterations=config.max_iterations,
                ),
            ),
        ]
    )


def fit_dynamics_model(
    intervals: pd.DataFrame,
    state_column: str,
    control_columns: Sequence[str],
    config: Optional[SparseRegressionConfig] = None,
):
    """Select the sparsity threshold by time-ordered derivative CV, then refit."""
    if config is None:
        config = SparseRegressionConfig()
    if len(intervals) < 4:
        raise ValueError("At least four valid intervals are required for fitting.")
    if config.max_cv_splits < 2:
        raise ValueError("max_cv_splits must be at least 2.")
    if not config.thresholds or any(value <= 0 for value in config.thresholds):
        raise ValueError("SINDy thresholds must be a non-empty set of positive values.")

    input_columns = ["state_mid", *control_columns]
    X = intervals[input_columns]
    derivative = intervals["state_derivative"]
    cv = TimeSeriesSplit(n_splits=min(config.max_cv_splits, len(intervals) - 1))
    search = GridSearchCV(
        estimator=build_dynamics_pipeline(
            config, state_column, control_columns, config.thresholds[0]
        ),
        param_grid={"model__threshold": config.thresholds},
        scoring="neg_mean_squared_error",
        cv=cv,
        n_jobs=config.n_jobs,
        error_score="raise",
    )
    search.fit(X, derivative)
    return search, input_columns


def predict_derivative(model, intervals: pd.DataFrame, input_columns: Sequence[str]):
    """Predict dx/dt for each interval midpoint and its measured forcing."""
    X = intervals[["state_mid", *input_columns[1:]]].copy()
    X.columns = list(input_columns)
    estimator = getattr(model, "best_estimator_", model)
    return estimator.predict(X)


def simulate_dynamics(
    model,
    intervals: pd.DataFrame,
    input_columns: Sequence[str],
):
    """Integrate the learned state equation using interpolated forcing inputs.

    The interval-mean controls are linearly interpolated between interval
    midpoints. The first interval starts from its measured initial state; later
    states are propagated from the model trajectory.
    """
    if intervals.empty:
        raise ValueError("At least one interval is required for integration.")

    durations = intervals["duration_years"].to_numpy(dtype=float)
    elapsed_edges = np.concatenate(([0.0], np.cumsum(durations)))
    control_values = intervals[list(input_columns[1:])].to_numpy(dtype=float)
    control_midpoints = elapsed_edges[:-1] + durations / 2
    pipeline = getattr(model, "best_estimator_", model)

    def state_derivative(time, state_value):
        controls = [
            np.interp(time, control_midpoints, control_values[:, index])
            for index in range(control_values.shape[1])
        ]
        input_values = pd.DataFrame(
            [[state_value[0], *controls]], columns=input_columns
        )
        return [float(pipeline.predict(input_values)[0])]

    solution = solve_ivp(
        state_derivative,
        (0.0, float(elapsed_edges[-1])),
        [float(intervals.iloc[0]["state_start"])],
        t_eval=elapsed_edges[1:],
        max_step=float(np.median(durations)),
        rtol=1e-6,
        atol=1e-8,
    )
    if not solution.success:
        raise DynamicsIntegrationError(
            f"Dynamics integration failed: {solution.message}"
        )
    predictions = solution.y[0]
    if not np.all(np.isfinite(predictions)):
        raise DynamicsIntegrationError(
            "Dynamics integration produced a non-finite state."
        )
    return predictions


def evaluate_predictions(observed, predicted):
    """Return standard regression metrics for predictions."""
    return {
        "mae": mean_absolute_error(observed, predicted),
        "rmse": np.sqrt(mean_squared_error(observed, predicted)),
        "r_squared": r2_score(observed, predicted),
    }


def get_dynamics_equation(model):
    """Return the fitted sparse equation's terms and coefficients."""
    sindy = model.best_estimator_.named_steps["model"].model_
    coefficients = sindy.coefficients().reshape(-1)
    names = sindy.get_feature_names()
    return pd.Series(coefficients, index=names)[lambda values: values != 0].sort_values(
        key=np.abs, ascending=False
    )


def report_dynamics(
    model,
    state_column: str,
    control_columns: Sequence[str],
    intervals: pd.DataFrame,
    derivative_metrics,
    trajectory_metrics,
):
    """Print the continuous-time equation and held-out model scores."""
    pipeline = model.best_estimator_
    scaler = pipeline.named_steps["scaler"]
    input_columns = ["state_mid", *control_columns]
    coefficients = get_dynamics_equation(model)
    print(f"Best sparsity threshold: {model.best_params_['model__threshold']:.6g}")
    print(f"Training/test intervals: {len(intervals)}")
    print(
        "Derivative test metrics "
        f"(ft/year): MAE={derivative_metrics['mae']:.4f}, "
        f"RMSE={derivative_metrics['rmse']:.4f}, "
        f"R-squared={derivative_metrics['r_squared']:.4f}"
    )
    print(
        "Integrated elevation test metrics "
        f"(ft): MAE={trajectory_metrics['mae']:.4f}, "
        f"RMSE={trajectory_metrics['rmse']:.4f}, "
        f"R-squared={trajectory_metrics['r_squared']:.4f}"
    )
    equation = " + ".join(
        f"({coefficient:.6g}) * {term}"
        for term, coefficient in coefficients.items()
    ) or "0"
    print(f"d({state_column})/dt [ft/year] = {equation}")
    print("Standardized equation inputs: z(column) = (column - mean) / scale")
    for column, mean, scale in zip(input_columns, scaler.mean_, scaler.scale_):
        original_name = state_column if column == "state_mid" else column
        print(f"  z({original_name}) = ({original_name} - {mean:.6g}) / {scale:.6g}")
    print(
        "Training interval: "
        f"{intervals['time_start'].min().date()} to "
        f"{intervals['time_end'].max().date()}"
    )


def plot_dynamics_fit(
    intervals: pd.DataFrame,
    predicted_elevation,
    state_column: str,
):
    """Plot measured and integrated test elevations and a parity plot."""
    observed = intervals["state_end"].to_numpy()
    predicted = np.asarray(predicted_elevation)
    dates = intervals["time_end"]

    figure, (time_axis, parity_axis) = plt.subplots(1, 2, figsize=(13, 5))
    time_axis.plot(dates, observed, label="Observed", linewidth=1.5)
    time_axis.plot(
        dates,
        predicted,
        label="SINDy integrated trajectory",
        linestyle="--",
        linewidth=1.5,
    )
    time_axis.set_title(f"{state_column}: continuous-time model")
    time_axis.set_xlabel("Date")
    time_axis.set_ylabel("Elevation (ft)")
    time_axis.legend()
    time_axis.grid(True, alpha=0.3)

    parity_axis.scatter(
        observed,
        predicted,
        alpha=0.65,
        label="One dot per held-out month",
    )
    limits = [
        min(observed.min(), predicted.min()),
        max(observed.max(), predicted.max()),
    ]
    parity_axis.plot(
        limits,
        limits,
        color="black",
        linestyle=":",
        label="Exact match (predicted = observed)",
    )
    parity_axis.set_title("How close are the model estimates?")
    parity_axis.set_xlabel(f"Measured {state_column} at month end (ft)")
    parity_axis.set_ylabel(f"SINDy-predicted {state_column} at month end (ft)")
    parity_axis.text(
        0.03,
        0.97,
        "Above line: overprediction\nBelow line: underprediction",
        transform=parity_axis.transAxes,
        va="top",
        fontsize=9,
    )
    parity_axis.set_xlim(limits)
    parity_axis.set_ylim(limits)
    parity_axis.set_aspect("equal", adjustable="box")
    parity_axis.legend()
    parity_axis.grid(True, alpha=0.3)
    figure.tight_layout()
    plt.show()
    return figure, (time_axis, parity_axis)


def main():
    """Configure and run the Great Salt Lake elevation dynamics example."""
    data_file = (
        Path(__file__).resolve().parent.parent
        / "processed_data"
        / "gsl_monthly_master.csv"
    )
    state_column = "Lake_Elevation_Month_End_ft"
    control_columns = [
        "Total_Inflow_MAF",
        "NOAA_Station_Mean_Precip_mm",
        "Seasonal_Sin",
        "Seasonal_Cos",
    ]
    max_gap_days = 62
    test_fraction = 0.2

    if not data_file.exists():
        raise FileNotFoundError(
            f"Monthly master dataset not found: {data_file}\n"
            "Run process_all_data.py first."
        )
    data = pd.read_csv(data_file, parse_dates=["Date"])
    annual_phase = 2 * np.pi * (data["Date"].dt.dayofyear - 1) / 365.2425
    data["Seasonal_Sin"] = np.sin(annual_phase)
    data["Seasonal_Cos"] = np.cos(annual_phase)
    intervals = prepare_dynamics_data(
        data,
        state_column,
        control_columns,
        time_column="Date",
        max_gap_days=max_gap_days,
    )
    split_index = int(len(intervals) * (1 - test_fraction))
    if split_index < 4 or split_index >= len(intervals):
        raise ValueError("Not enough valid intervals for the configured time split.")
    train_intervals = intervals.iloc[:split_index].reset_index(drop=True)
    test_intervals = intervals.iloc[split_index:].reset_index(drop=True)

    config = SparseRegressionConfig()
    model, input_columns = fit_dynamics_model(
        train_intervals,
        state_column,
        control_columns,
        config=config,
    )
    derivative_predictions = predict_derivative(
        model, test_intervals, input_columns
    )
    derivative_metrics = evaluate_predictions(
        test_intervals["state_derivative"], derivative_predictions
    )
    elevation_predictions = simulate_dynamics(
        model, test_intervals, input_columns
    )
    trajectory_metrics = evaluate_predictions(
        test_intervals["state_end"], elevation_predictions
    )

    print(f"State: {state_column}")
    print(f"Forcing inputs: {', '.join(control_columns)}")
    print(f"Usable intervals: {len(intervals)}")
    print(
        f"Train/test intervals: {len(train_intervals)}/{len(test_intervals)}"
    )
    report_dynamics(
        model,
        state_column,
        control_columns,
        train_intervals,
        derivative_metrics,
        trajectory_metrics,
    )
    plot_dynamics_fit(test_intervals, elevation_predictions, state_column)


if __name__ == "__main__":
    main()
