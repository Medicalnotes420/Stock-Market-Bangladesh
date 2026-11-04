"""Does dse_quant.watch.forecast's 80% range contain the real price 80% of the time? Walk-forward on DSE history:
at each check date only past data is used, then the price h sessions later is compared with the range.
Run from the repo root: python -W ignore scripts/forecast_check.py  -> results/forecast_check.csv"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.data.load import load_a2_types  # noqa: E402
from dse_quant.panels import build_panels, eligible_mask  # noqa: E402
from dse_quant.watch import BAND, HORIZONS, WINDOW  # noqa: E402

STEP = 10  # check every 10th session per stock
df = pd.read_csv("data/clean/prices.csv.gz", parse_dates=["date"])
types = {**json.load(open("data/clean/report.json"))["dead_tickers_from_a1"], **load_a2_types()}
p = build_panels(df[df.date >= "2013-01-01"])
E = eligible_mask(p, types)
lc = np.log(p.close.ffill())
gap = p.gap_flag.astype(float)
rows = []
for h in HORIZONS:
    r = lc - lc.shift(h)
    r = r.where(gap.rolling(h, min_periods=1).max() == 0)  # drop moves that span an unexplained jump
    q = {b: r.rolling(WINDOW, min_periods=WINDOW // 2).quantile(b) for b in BAND}
    fut = r.shift(-h)  # realised move over the next h sessions
    for t in range(WINDOW, len(p.dates) - h, STEP):
        ok = E.iloc[t].values & fut.iloc[t].notna().values & q[BAND[0]].iloc[t].notna().values
        if not ok.any():
            continue
        f, lo, mid, hi = (x.iloc[t].values[ok] for x in (fut, q[BAND[0]], q[BAND[1]], q[BAND[2]]))
        for v, a, m, b in zip(f, lo, mid, hi):
            rows.append((h, p.dates[t].year, a <= v <= b, v < a, v > b, abs(v - m)))
res = pd.DataFrame(rows, columns=["h", "year", "inside", "below", "above", "abs_err_mid"])
summ = res.groupby(["h", "year"]).agg(checks=("inside", "size"), inside=("inside", "mean"), below=("below", "mean"),
                                      above=("above", "mean")).reset_index()
tot = res.groupby("h").agg(checks=("inside", "size"), inside=("inside", "mean"), below=("below", "mean"),
                           above=("above", "mean")).reset_index().assign(year="all")
out = pd.concat([summ, tot], ignore_index=True)
Path("results").mkdir(exist_ok=True)
out.to_csv("results/forecast_check.csv", index=False)
print(out.round(3).to_string())
