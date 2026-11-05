"""Bangladesh government bond and T-bill yields vs the stock index. Descriptive: what happened, not a forecast.
Run from the repo root: python scripts/rates_vs_index.py   (--refresh re-downloads the IMF data;
--refresh-if-stale only when the copy is over 30 days old, as the daily run does)
Output: results/rates_monthly.csv, results/rates_yearly.csv and a printed summary.
Rates: IMF Monetary and Financial Statistics (MFS_IR), monthly, cached in data/raw/imf/. The IMF's recent
Bangladesh lending and deposit rates look mislabelled (lending below deposit), so they are not used."""
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw/imf/MFS_IR_BGD.xml")
URL = "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,MFS_IR/BGD..M?startPeriod=1990"
SERIES = {"S13BOND_RT_PT_A_PT": "bond_yield", "GSTBILY_RT_PT_A_PT": "tbill_yield",
          "MFS172_RT_PT_A_PT": "repo_rate",
          "MFS135_RT_PT_A_PT": "deposit_rate"}  # tracks fixed-deposit rates (docs/DEPOSIT_RATES_PREREG.md)


def parse(xml, series=SERIES):
    """IMF SDMX structure-specific XML -> monthly DataFrame of the `series` columns (percent a year)."""
    cols = {}
    for m in re.finditer(r"<Series ([^>]*)>(.*?)</Series>", xml, re.S):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        name = series.get(attrs.get("INDICATOR"))
        if not name or attrs.get("FREQUENCY") != "M":
            continue
        obs = {}
        for o in re.findall(r"<Obs ([^>]*)/?>", m.group(2)):
            a = dict(re.findall(r'(\w+)="([^"]*)"', o))
            if "TIME_PERIOD" in a and "OBS_VALUE" in a:
                obs[pd.Period(a["TIME_PERIOD"].replace("-M", "-"), "M")] = float(a["OBS_VALUE"])
        cols[name] = pd.Series(obs)
    missing = set(series.values()) - set(cols)
    if missing:
        raise ValueError(f"IMF reply is missing {sorted(missing)} for Bangladesh")
    return pd.DataFrame(cols).sort_index()


def yearly(rates, wb):
    """Yearly average yields beside the yearly taka index return, and Tk 100 grown in each from the first year."""
    y = rates.groupby(rates.index.year).mean().join(wb, how="inner").dropna(subset=["bond_yield", "return_bdt_pct"])
    y["bonds_tk100"] = 100 * (1 + y.bond_yield / 100).cumprod()
    y["shares_tk100"] = 100 * (1 + y.return_bdt_pct / 100).cumprod()
    return y


if __name__ == "__main__":
    stale = RAW.exists() and time.time() - RAW.stat().st_mtime > 30 * 86400
    if "--refresh" in sys.argv or not RAW.exists() or ("--refresh-if-stale" in sys.argv and stale):
        RAW.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=120) as r:
            RAW.write_bytes(r.read())
    rates = parse(RAW.read_text(encoding="utf-8"))
    s = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date").dsex.dropna()
    dsex_m = s.groupby(s.index.to_period("M")).last().rename("dsex")
    M = rates.join(dsex_m, how="outer")
    M["dsex_chg_pct"] = 100 * M.dsex.pct_change()
    M["bond_chg_pts"] = M.bond_yield.diff()
    wb = pd.read_csv("results/dse_long_run.csv").set_index("year")[["return_bdt_pct", "inflation_pct"]]
    Y = yearly(rates, wb)
    Path("results").mkdir(exist_ok=True)
    M.to_csv("results/rates_monthly.csv", index_label="month")
    Y.to_csv("results/rates_yearly.csv", index_label="year")

    both = M.dropna(subset=["dsex_chg_pct", "bond_chg_pts"])
    c0 = both.dsex_chg_pct.corr(both.bond_chg_pts)
    lead = {}
    for h in (6, 12):  # bond yield change over the past h months vs DSEX change over the next h months
        past = M.bond_yield - M.bond_yield.shift(h)
        nxt = 100 * (M.dsex.shift(-h) / M.dsex - 1)
        lead[h] = pd.concat([past, nxt], axis=1).dropna().corr().iloc[0, 1]
    lv = pd.concat([M.bond_yield, 100 * (M.dsex.shift(-12) / M.dsex - 1)], axis=1).dropna().corr().iloc[0, 1]
    pd.set_option("display.width", 200)
    print(Y.round(1).to_string())
    print(f"\n{Y.index.min()}-{Y.index.max()}: Tk 100 in government bonds -> Tk {Y.bonds_tk100.iloc[-1]:,.0f}; "
          f"in the share index (prices only) -> Tk {Y.shares_tk100.iloc[-1]:,.0f}; "
          f"bonds beat shares in {(Y.bond_yield > Y.return_bdt_pct).sum()} of {len(Y)} years")
    print(f"Monthly, {both.index.min()}-{both.index.max()}: DSEX change vs bond yield change, same month, "
          f"correlation {c0:+.2f}")
    print("Bond yield change over the past 6 / 12 months vs DSEX over the next 6 / 12: "
          f"{lead[6]:+.2f} / {lead[12]:+.2f}; bond yield level vs DSEX next 12 months: {lv:+.2f} "
          "(overlapping windows: far fewer independent cases than months)")
    print(f"Latest: bond {rates.bond_yield.dropna().iloc[-1]:.2f}% ({rates.bond_yield.dropna().index[-1]}), "
          f"T-bill {rates.tbill_yield.dropna().iloc[-1]:.2f}%, repo {rates.repo_rate.dropna().iloc[-1]:.2f}%")
