"""
update_all_data.py

Refresh every Great Salt Lake dataset and rebuild the monthly master table
with one command:

    python scripts_py/update_all_data.py

What it does
1. Runs each download script in order (see STEPS). A failed download is
   reported but does not stop the others; the previous CSV for that source
   is kept and still used.
2. Runs process_all_data.py to rebuild processed_data/gsl_monthly_master.csv.
3. Writes processed_data/data_status.json: when each source was last
   updated, its status, row count, and date range. A website can read this
   to show "data current through ...".
4. Saves the full console output to logs/update_<timestamp>.log.

Options
    --only lake_elevation streamflow   run just these steps (plus processing)
    --skip era5                        run everything except these
    --include-static                   also re-download static data
                                       (lake hypsometry tables)
    --no-process                       download only; do not rebuild master

Exit code is 1 if any step failed, so schedulers (Windows Task Scheduler,
cron) can flag a bad run.

Typical run time after the first full download: a few minutes. The NOAA
weather, ERA5 and gridMET scripts cache older data and only re-download
recent periods. ERA5 needs a CDS API key in ~/.cdsapirc.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd


# ------------------------------------------------------------
# 1. Steps, in run order
# ------------------------------------------------------------

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
SCRIPTS_FOLDER = PROJECT_FOLDER / "scripts_py"
RAW_DATA_FOLDER = PROJECT_FOLDER / "raw_data"
PROCESSED_DATA_FOLDER = PROJECT_FOLDER / "processed_data"
LOG_FOLDER = PROJECT_FOLDER / "logs"
STATUS_FILE = PROCESSED_DATA_FOLDER / "data_status.json"
RETRY_DELAY_SECONDS = 60

# name: (script, main output file, static?)
# noaa_precipitation must run before noaa_weather: it refreshes the
# station list that the weather script reads.
STEPS = {
    "lake_elevation": ("download_usgs_lake_elv.py", RAW_DATA_FOLDER / "usgs_lake_elevation.csv", False),
    "streamflow": ("download_streamflow.py", RAW_DATA_FOLDER / "usgs_streamflow.csv", False),
    "noaa_precipitation": ("download_noaa_precipitation.py", RAW_DATA_FOLDER / "noaa_historical_daily_precipitation_wide.csv", False),
    "noaa_weather": ("download_noaa_weather_hourly.py", RAW_DATA_FOLDER / "noaa_historical_daily_weather.csv", False),
    "era5": ("download_era5_land_monthly.py", RAW_DATA_FOLDER / "era5_land_monthly_weather.csv", False),
    "gridmet": ("download_gridmet_daily.py", RAW_DATA_FOLDER / "gridmet_daily_weather.csv", False),
    "lake_hypsometry": ("download_usgs_lake_hypsometry.py", RAW_DATA_FOLDER / "usgs_gsl_elevation_area_volume.csv", True),
}

PROCESS_STEP = ("process_all_data.py", PROCESSED_DATA_FOLDER / "gsl_monthly_master.csv")


# ------------------------------------------------------------
# 2. Helpers
# ------------------------------------------------------------

def run_script(script, log):
    """Run one script with this Python, echoing output to the console and log."""
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-u", str(SCRIPTS_FOLDER / script)],
        cwd=PROJECT_FOLDER,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    for line in process.stdout:
        print(line, end="")
        log.write(line)
    return process.wait()


def describe_output(path):
    """Row count and date range of a CSV output, for the status file."""
    if not path.exists():
        return {"output": str(path.relative_to(PROJECT_FOLDER)), "exists": False}

    info = {
        "output": str(path.relative_to(PROJECT_FOLDER)),
        "exists": True,
        "file_modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }
    try:
        header = pd.read_csv(path, nrows=0).columns
        if "Date" in header:
            table = pd.read_csv(path, low_memory=False)
            dates = pd.to_datetime(table["Date"], errors="coerce")
            # Some sources pad the current month with empty future rows, so
            # report the last date that actually has a value.
            has_data = table.drop(columns="Date").notna().any(axis=1)
            info.update(
                rows=int(len(dates)),
                first_date=str(dates.min().date()),
                last_date=str(dates[has_data].max().date()),
            )
        else:
            info["rows"] = int(sum(1 for _ in open(path, encoding="utf-8")) - 1)
    except (ValueError, OSError, pd.errors.ParserError) as error:
        info["note"] = f"Could not summarize: {error}"
    return info


def load_status():
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"steps": {}}


# ------------------------------------------------------------
# 3. Choose steps
# ------------------------------------------------------------

parser = argparse.ArgumentParser(description="Update all Great Salt Lake datasets.")
parser.add_argument("--only", nargs="+", choices=list(STEPS), help="run only these steps")
parser.add_argument("--skip", nargs="+", choices=list(STEPS), default=[], help="skip these steps")
parser.add_argument("--include-static", action="store_true", help="also re-download static data")
parser.add_argument("--no-process", action="store_true", help="do not rebuild the master table")
args = parser.parse_args()

selected = []
for name, (script, output, is_static) in STEPS.items():
    if args.only:
        if name in args.only:
            selected.append(name)
    elif name in args.skip:
        continue
    elif is_static and output.exists() and not args.include_static:
        continue  # static and already downloaded
    else:
        selected.append(name)


# ------------------------------------------------------------
# 4. Run
# ------------------------------------------------------------

# Excel locks CSVs it has open; catch that before spending time downloading.
if not args.no_process and PROCESS_STEP[1].exists():
    try:
        with open(PROCESS_STEP[1], "a"):
            pass
    except PermissionError:
        sys.exit(
            f"{PROCESS_STEP[1].name} is open in another program (often Excel). "
            "Close it and run the update again."
        )

LOG_FOLDER.mkdir(exist_ok=True)
run_started = datetime.now()
log_file = LOG_FOLDER / f"update_{run_started:%Y%m%d_%H%M%S}.log"
status = load_status()
results = []

with open(log_file, "w", encoding="utf-8") as log:

    for name in selected:
        script, output, _ = STEPS[name]
        banner = f"\n{'=' * 60}\n{name}: {script}\n{'=' * 60}\n"
        print(banner, end="")
        log.write(banner)

        started = time.time()
        return_code = run_script(script, log)

        # Retry once: most failures are brief network or server hiccups.
        if return_code != 0:
            note = f"\n{name} failed (exit {return_code}); retrying in {RETRY_DELAY_SECONDS} s...\n"
            print(note, end="")
            log.write(note)
            time.sleep(RETRY_DELAY_SECONDS)
            return_code = run_script(script, log)

        duration = time.time() - started

        step_status = "ok" if return_code == 0 else f"failed (exit {return_code})"
        results.append((name, step_status, duration))

        previous = status["steps"].get(name, {})
        entry = {"status": step_status, "last_attempt": datetime.now().isoformat(timespec="seconds")}
        entry["last_success"] = entry["last_attempt"] if return_code == 0 else previous.get("last_success")
        entry.update(describe_output(output))
        status["steps"][name] = entry

    if not args.no_process:
        script, output = PROCESS_STEP
        banner = f"\n{'=' * 60}\nprocess: {script}\n{'=' * 60}\n"
        print(banner, end="")
        log.write(banner)

        started = time.time()
        return_code = run_script(script, log)
        duration = time.time() - started

        step_status = "ok" if return_code == 0 else f"failed (exit {return_code})"
        results.append(("process", step_status, duration))
        status["master"] = {
            "status": step_status,
            "last_attempt": datetime.now().isoformat(timespec="seconds"),
            **describe_output(output),
        }


# ------------------------------------------------------------
# 5. Save status and print summary
# ------------------------------------------------------------

status["last_run"] = run_started.isoformat(timespec="seconds")
status["last_log"] = str(log_file.relative_to(PROJECT_FOLDER))
PROCESSED_DATA_FOLDER.mkdir(exist_ok=True)
STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")

print("\n" + "=" * 60)
print("UPDATE SUMMARY")
print("=" * 60)
for name, step_status, duration in results:
    info = status["steps"].get(name) or status.get("master", {})
    through = info.get("last_date", "")
    print(f"{name:20s} {step_status:20s} {duration / 60:6.1f} min   data through {through}")

failed = [name for name, step_status, _ in results if step_status != "ok"]
if failed:
    print(f"\nFailed: {', '.join(failed)}. Older data were kept for those sources.")
print(f"\nLog: {log_file}")
print(f"Status: {STATUS_FILE}")

sys.exit(1 if failed else 0)
