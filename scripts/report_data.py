"""Rebuild every data file behind the "DSE Market History 1993–2026" report page into data/report/.
Run from the repo root: python -W ignore scripts/report_data.py
It re-runs the history, deep-low, calendar and rates scripts first, so the files match the repo's results.
Each file's name is what the report's dataset expects (see REPORT_DATASETS in this file)."""
import subprocess
import sys
from pathlib import Path

import pandas as pd

OUT = Path("data/report")
# dataset id on the report page -> file written here
REPORT_DATASETS = {"dsex_daily": "dsex_daily.csv", "dsex_years": "dsex_years.csv", "dsex_big_falls": "dsex_big_falls.csv",
                   "wb": "dse_world_bank_years.csv", "months": "dsex_by_month.csv", "events": "dsex_events.csv",
                   "rises": "dsex_rises.csv", "deep_low": "deep_low_years.csv", "bonds": "bonds_vs_shares.csv",
                   "yields": "yields_monthly.csv"}
STEPS = ["dsex_history.py", "dse_long_run.py", "calendar_events.py", "deep_low.py", "rates_vs_index.py"]


def build():
    m = pd.read_csv("data/clean/market.csv", parse_dates=["date"])
    m = m[m.dsex.notna()]
    files = {"dsex_daily.csv": pd.DataFrame({"date": m.date.dt.strftime("%Y-%m-%d"), "dsex": m.dsex.round(2),
                                             "turnover_cr": (m.turnover / 1e7).round(1)})}
    y = pd.read_csv("results/dsex_years.csv")
    y = y.assign(**{c: (y[c] * 100).round(1) for c in ("return", "max_fall", "volatility")})
    files["dsex_years.csv"] = y.round({"start": 0, "end": 0, "high": 0, "low": 0, "turnover_cr": 0}).rename(
        columns={"return": "return_pct", "max_fall": "max_fall_pct", "volatility": "volatility_pct"})
    d = pd.read_csv("results/dsex_drawdowns.csv")
    files["dsex_big_falls.csv"] = d.assign(depth_pct=(d.depth * 100).round(1), peak=d.peak.round(0),
                                           trough=d.trough.round(0), recovered=d.recovered.fillna("not yet")
                                           ).drop(columns="depth")
    files["dse_world_bank_years.csv"] = pd.read_csv("results/dse_long_run.csv").round(1)
    files["dsex_by_month.csv"] = pd.read_csv("results/calendar_months.csv").round(2)
    files["dsex_events.csv"] = pd.read_csv("results/calendar_events.csv").round(1)
    r = pd.read_csv("results/dsex_rises.csv")
    files["dsex_rises.csv"] = r.assign(rise_pct=(r.rise * 100).round(1)).drop(columns="rise").round(0)
    dl = pd.read_csv("results/deep_low_years.csv")
    files["deep_low_years.csv"] = dl.assign(below_prev_end=(dl.below_prev_end * 100).round(1)).round(2)
    ry = pd.read_csv("results/rates_yearly.csv").round(2)
    files["bonds_vs_shares.csv"] = ry[["year", "bond_yield", "tbill_yield", "repo_rate", "return_bdt_pct",
                                       "bonds_tk100", "shares_tk100"]]
    rm = pd.read_csv("results/rates_monthly.csv")
    files["yields_monthly.csv"] = rm[rm.month >= "2006-07"][["month", "bond_yield", "tbill_yield", "repo_rate"]].dropna(
        how="all", subset=["bond_yield", "tbill_yield", "repo_rate"]).round(2)
    return files


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    for s in STEPS:
        subprocess.run([sys.executable, "-W", "ignore", str(here / s)], check=True, capture_output=True)
    files = build()
    assert set(files) == set(REPORT_DATASETS.values())
    OUT.mkdir(parents=True, exist_ok=True)
    for name, df in files.items():
        df.to_csv(OUT / name, index=False)
        print(f"{name}: {len(df)} rows")
    print("DSEX data to", files["dsex_daily.csv"].date.iloc[-1])
