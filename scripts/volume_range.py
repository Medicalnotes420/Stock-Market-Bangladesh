"""Price range coverage by volume, and a widened range on high-volume days, exactly as docs/VOLUME_RANGE_PREREG.md.
Run from the repo root: python -W ignore scripts/volume_range.py  -> results/volume_range.csv"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.data.load import load_a2_types  # noqa: E402
from dse_quant.panels import build_panels, eligible_mask  # noqa: E402
from dse_quant.watch import BAND, HORIZONS, WINDOW  # noqa: E402

PERIODS = {"A": ("2014-01-01", "2022-12-31"), "B": ("2023-01-01", "2026-01-22"), "C": ("2026-01-25", "2099-12-31")}
BUCKETS = [(0, 0.5, "<0.5"), (0.5, 1, "0.5-1"), (1, 2, "1-2"), (2, np.inf, ">=2")]
KS = np.round(np.arange(1.0, 3.01, 0.1), 1)

df = pd.read_csv("data/clean/prices.csv.gz", parse_dates=["date"])
types = {**json.load(open("data/clean/report.json"))["dead_tickers_from_a1"], **load_a2_types()}
p = build_panels(df[df.date >= "2013-01-01"])
E = eligible_mask(p, types)
lc = np.log(p.close.ffill())
gap = p.gap_flag.astype(float)
val = p.value.where(p.value > 0)
base20 = val.fillna(0).shift(1).rolling(20, min_periods=20).mean()
R = (val / base20).where(base20 > 0)
per = pd.Series("", index=p.dates)
for k, (a, b) in PERIODS.items():
    per[(p.dates >= a) & (p.dates <= b)] = k


def flat(x):
    return x.to_numpy().ravel()


rows, kfit = [], {}
for h in HORIZONS:
    r = (lc - lc.shift(h)).where(gap.rolling(h, min_periods=1).max() == 0)  # past moves, same as forecast_check
    q = {b: r.rolling(WINDOW, min_periods=WINDOW // 2).quantile(b) for b in BAND}
    fut = r.shift(-h)  # move over t..t+h, NaN if a gap falls in t+1..t+h
    ok = E & fut.notna() & q[BAND[0]].notna() & R.notna()
    m = flat(ok)
    lo, mid, hi, f, rr = (flat(x)[m] for x in (q[BAND[0]], q[BAND[1]], q[BAND[2]], fut, R))
    pr = np.repeat(per.to_numpy()[:, None], lc.shape[1], axis=1).ravel()[m]

    def cover(k, sel):
        l2, h2 = mid[sel] - k * (mid[sel] - lo[sel]), mid[sel] + k * (hi[sel] - mid[sel])
        return (f[sel] >= l2) & (f[sel] <= h2), f[sel] < l2, f[sel] > h2

    for pname in PERIODS:
        for blo, bhi, bname in BUCKETS:
            sel = (pr == pname) & (rr >= blo) & (rr < bhi)
            ins, below, above = cover(1.0, sel)
            rows.append({"h": h, "period": pname, "bucket": bname, "k": 1.0, "n": int(sel.sum()),
                         "inside": ins.mean(), "below": below.mean(), "above": above.mean()})
    hiA = (pr == "A") & (rr >= 2)
    kfit[h] = next((k for k in KS if cover(k, hiA)[0].mean() >= 0.80), np.nan)
    for pname in PERIODS:
        sel = (pr == pname) & (rr >= 2)
        ins, below, above = cover(kfit[h], sel)
        rows.append({"h": h, "period": pname, "bucket": ">=2 widened", "k": kfit[h], "n": int(sel.sum()),
                     "inside": ins.mean(), "below": below.mean(), "above": above.mean()})

res = pd.DataFrame(rows)


def verdict(h):
    g = res[res.h == h].set_index(["bucket", "period"]).inside
    base, wide = g[">=2"], g[">=2 widened"]
    c1 = base["A"] < 0.75
    c2 = all(0.75 <= wide[k] <= 0.85 for k in "BC")
    c3 = all(abs(wide[k] - 0.8) < abs(base[k] - 0.8) for k in "BC")
    return "ADOPT" if c1 and c2 and c3 else "NOT ADOPTED", (c1, c2, c3)


Path("results").mkdir(exist_ok=True)
res.to_csv("results/volume_range.csv", index=False)
pd.set_option("display.width", 200)
print(res.pivot_table(index=["h", "bucket"], columns="period", values=["n", "inside", "below", "above"],
                      sort=False).round(3).to_string())
for h in HORIZONS:
    v, cs = verdict(h)
    print(f"h={h}: k fitted on A = {kfit[h]}  -> {v}  (conditions 1-3: {cs})")
