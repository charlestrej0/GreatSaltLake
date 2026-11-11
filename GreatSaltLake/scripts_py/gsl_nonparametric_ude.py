"""Great Salt Lake nonparametric ODE-inspired prototype.
Uses monthly elevation, streamflow, and precipitation from gsl_monthly_master.csv.

Important: predicts lake ELEVATION, not volume. The learned spline captures
unresolved net effects; it is not evaporation alone. A physical volume model
needs an elevation-volume/area relationship and better-defined flux terms.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import least_squares
from sklearn.preprocessing import SplineTransformer
from sklearn.metrics import mean_absolute_error, mean_squared_error

# Edit this path if your CSV is stored elsewhere.
DATA_FILE = Path(r"C:\Users\charl\GreatSaltLake\processed_data\gsl_monthly_master.csv")
OUTPUT_DIR = DATA_FILE.parent / "nonparametric_model_output"
TRAIN_FRACTION = 0.80
N_KNOTS = 5                 # fewer knots = simpler learned function
SMOOTHNESS_PENALTY = 2.0    # larger = smoother spline

# 1. Load and clean data
if not DATA_FILE.exists():
    raise FileNotFoundError(f"CSV not found: {DATA_FILE}\nEdit DATA_FILE at the top.")
df = pd.read_csv(DATA_FILE)
df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
columns = ["Date", "Lake_Elevation_Mean_ft", "Total_Inflow_Mean_ft3_s", "NOAA_Station_Mean_Precip_in"]
missing = [c for c in columns if c not in df.columns]
if missing:
    raise ValueError(f"Missing columns: {missing}")
data = df[columns].copy().dropna(subset=["Date"])
for c in columns[1:]:
    data[c] = pd.to_numeric(data[c], errors="coerce")
data = data.dropna(subset=columns[1:]).sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
if len(data) < 60:
    raise ValueError(f"Only {len(data)} complete rows. Need more monthly data.")

def standardize(series):
    mean, std = series.mean(), series.std()
    if std == 0:
        raise ValueError(f"{series.name} has zero standard deviation.")
    return (series - mean) / std, mean, std

data["Inflow_z"], inflow_mean, inflow_std = standardize(data["Total_Inflow_Mean_ft3_s"])
data["Precip_z"], precip_mean, precip_std = standardize(data["NOAA_Station_Mean_Precip_in"])
data["Elevation_z"], elevation_mean, elevation_std = standardize(data["Lake_Elevation_Mean_ft"])
month = data["Date"].dt.month.to_numpy()
data["Season_sin"] = np.sin(2 * np.pi * month / 12)
data["Season_cos"] = np.cos(2 * np.pi * month / 12)

# Chronological split: the final 20% of months are held out for testing.
split = int(len(data) * TRAIN_FRACTION)
if split < 36 or len(data) - split < 12:
    raise ValueError("Train/test split too small; adjust TRAIN_FRACTION.")
train = data.iloc[:split].reset_index(drop=True)
test = data.iloc[split:].reset_index(drop=True)
spline = SplineTransformer(n_knots=N_KNOTS, degree=3, knots="quantile", include_bias=False, extrapolation="linear")
spline.fit(train[["Elevation_z"]])
n_spline = spline.transform(train[["Elevation_z"]]).shape[1]
n_linear = 5

# Monthly ODE approximation:
# change in elevation (ft/month) = linear input effects + seasonal terms + spline(elevation).
# The spline represents unresolved state-dependent net effects, not evaporation alone.
def change_ft(elevation_ft, row, parameters):
    elevation_z = (elevation_ft - elevation_mean) / elevation_std
    basis = spline.transform(np.array([[elevation_z]]))[0]
    return (parameters[0] + parameters[1] * row["Inflow_z"]
            + parameters[2] * row["Precip_z"] + parameters[3] * row["Season_sin"]
            + parameters[4] * row["Season_cos"] + np.dot(basis, parameters[n_linear:]))

def rollout(rows, start_elevation_ft, parameters, advance_first_row=False):
    predicted = np.zeros(len(rows))
    current = float(start_elevation_ft)
    for i in range(len(rows)):
        # Training predictions are aligned to observed rows: row 0 is the
        # known starting elevation, then each later row advances the model.
        # Test predictions advance immediately from the last training value.
        if i > 0 or advance_first_row:
            current += change_ft(current, rows.iloc[i], parameters)
        predicted[i] = current
    return predicted

observed_train = train["Lake_Elevation_Mean_ft"].to_numpy()
start_train = observed_train[0]

def objective(parameters):
    predicted = np.zeros(len(train))
    predicted[0] = start_train
    for i in range(1, len(train)):
        predicted[i] = predicted[i - 1] + change_ft(predicted[i - 1], train.iloc[i], parameters)
    trajectory_error = predicted[1:] - observed_train[1:]
    spline_coefficients = parameters[n_linear:]
    if len(spline_coefficients) >= 3:
        smooth_error = np.sqrt(SMOOTHNESS_PENALTY) * np.diff(spline_coefficients, n=2)
    else:
        smooth_error = np.array([])
    return np.concatenate([trajectory_error, smooth_error])

print("Fitting model. This may take a minute...")
fit = least_squares(objective, np.zeros(n_linear + n_spline), max_nfev=3000, verbose=1)
parameters = fit.x
if not fit.success:
    print("Optimizer warning:", fit.message)
train_pred = rollout(train, start_train, parameters)
# Test rollout starts from the last observed training value; test data do not fit parameters.
test_pred = rollout(test, train["Lake_Elevation_Mean_ft"].iloc[-1], parameters, advance_first_row=True)
train_actual = train["Lake_Elevation_Mean_ft"].to_numpy()
test_actual = test["Lake_Elevation_Mean_ft"].to_numpy()
print("\n--- Performance (feet) ---")
print(f"Training MAE:  {mean_absolute_error(train_actual, train_pred):.3f}")
print(f"Testing MAE:   {mean_absolute_error(test_actual, test_pred):.3f}")
print(f"Training RMSE: {np.sqrt(mean_squared_error(train_actual, train_pred)):.3f}")
print(f"Testing RMSE:  {np.sqrt(mean_squared_error(test_actual, test_pred)):.3f}")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
results = data[["Date", "Lake_Elevation_Mean_ft"]].copy()
results["Split"] = ["Train" if i < split else "Test" for i in range(len(results))]
results["Predicted_Elevation_ft"] = np.nan
results.loc[:split - 1, "Predicted_Elevation_ft"] = train_pred
results.loc[split:, "Predicted_Elevation_ft"] = test_pred
results["Residual_ft"] = results["Lake_Elevation_Mean_ft"] - results["Predicted_Elevation_ft"]
results.to_csv(OUTPUT_DIR / "predictions.csv", index=False)
names = ["intercept_ft_per_month", "inflow_effect", "precip_effect", "season_sin_effect", "season_cos_effect"]
names += [f"spline_coefficient_{i+1}" for i in range(n_spline)]
pd.DataFrame({"Parameter": names, "Estimate": parameters}).to_csv(OUTPUT_DIR / "parameters.csv", index=False)

plt.figure(figsize=(12, 6))
plt.plot(train["Date"], train_actual, label="Observed (training)")
plt.plot(train["Date"], train_pred, label="Predicted (training)")
plt.plot(test["Date"], test_actual, label="Observed (test)")
plt.plot(test["Date"], test_pred, label="Predicted (test)")
plt.axvline(test["Date"].iloc[0], linestyle="--", label="Train/test boundary")
plt.xlabel("Date"); plt.ylabel("Mean lake elevation (ft)")
plt.title("Great Salt Lake: Nonparametric Monthly Model")
plt.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
plt.grid(True, alpha=0.25); plt.tight_layout()
plt.savefig(OUTPUT_DIR / "observed_vs_predicted.png", dpi=200); plt.show()

elevation_grid_z = np.linspace(train["Elevation_z"].min(), train["Elevation_z"].max(), 200)
basis_grid = spline.transform(elevation_grid_z.reshape(-1, 1))
spline_effect = basis_grid @ parameters[n_linear:]
elevation_grid_ft = elevation_grid_z * elevation_std + elevation_mean
plt.figure(figsize=(9, 5)); plt.plot(elevation_grid_ft, spline_effect)
plt.xlabel("Lake elevation (ft)"); plt.ylabel("Spline contribution to change (ft/month)")
plt.title("Learned State-Dependent Component"); plt.grid(True, alpha=0.25); plt.tight_layout()
plt.savefig(OUTPUT_DIR / "learned_spline.png", dpi=200); plt.show()
print(f"\nSaved output files in: {OUTPUT_DIR}")
