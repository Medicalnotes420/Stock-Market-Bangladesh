"""Even out the price range's low-side misses, exactly as docs/RANGE_SKEW_PREREG.md.
Run from the repo root: python -W ignore scripts/range_skew.py  -> results/range_skew.csv"""
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
SHIFTS = np.round(np.arange(0, 0.1001, 0.005), 3)

df = pd.read_csv("data/clean/prices.csv.gz", parse_dates=["date"])
types = {**json.load(open("data/clean/report.json"))["dead_tickers_from_a1"], **load_a2_types()}
p = build_panels(df[df.date >= "2013-01-01"])
E = eligible_mask(p, types)
lc = np.log(p.close.ffill())
gap = p.gap_flag.astype(float)
per = pd.Series("", index=p.dates)
for k, (a, b) in PERIODS.items():
    per[(p.dates >= a) & (p.dates <= b)] = k


def flat(x):
    return x.to_numpy().ravel()


def score(f, lo, hi):
    return {"inside": ((f >= lo) & (f <= hi)).mean(), "below": (f < lo).mean(), "above": (f > hi).mean()}


rows, sfit = [], {}
for h in HORIZONS:
    r = (lc - lc.shift(h)).where(gap.rolling(h, min_periods=1).max() == 0)
    q = {b: r.rolling(WINDOW, min_periods=WINDOW // 2).quantile(b) for b in BAND}
    fut = r.shift(-h)
    m = flat(E & fut.notna() & q[BAND[0]].notna())
    lo, mid, hi, f = (flat(x)[m] for x in (q[BAND[0]], q[BAND[1]], q[BAND[2]], fut))
    pr = np.repeat(per.to_numpy()[:, None], lc.shape[1], axis=1).ravel()[m]
    A = pr == "A"
    skew = {s: abs(np.subtract(*[score(f[A], lo[A] - s, hi[A] - s)[k] for k in ("below", "above")])) for s in SHIFTS}
    sfit[h] = min(skew, key=skew.get)
    variants = {"D0": (lo, hi), "D1": (lo - mid, hi - mid), "D2": (lo - sfit[h], hi - sfit[h])}
    for v, (l2, h2) in variants.items():
        for pname in PERIODS:
            sel = pr == pname
            rows.append({"h": h, "variant": v, "period": pname, "n": int(sel.sum()),
                         "shift": sfit[h] if v == "D2" else 0.0, **score(f[sel], l2[sel], h2[sel])})

res = pd.DataFrame(rows)
res["gap"] = (res.below - res.above).abs()


def passes(h, v):
    g = res[res.h == h].set_index(["variant", "period"])
    return all(g.gap[v, k] < g.gap["D0", k] and 0.75 <= g.inside[v, k] <= 0.85
               and g.inside[v, k] >= g.inside["D0", k] - 0.02 for k in "BC")


Path("results").mkdir(exist_ok=True)
res.to_csv("results/range_skew.csv", index=False)
pd.set_option("display.width", 200)
print(res.pivot_table(index=["h", "variant"], columns="period", values=["inside", "below", "above"],
                      sort=False).round(3).to_string())
for h in HORIZONS:
    d1, d2 = passes(h, "D1"), passes(h, "D2")
    print(f"h={h}: D2 shift fitted on A = {sfit[h]}  D1 passes {d1}, D2 passes {d2} -> "
          + ("ADOPT D1" if d1 else "ADOPT D2" if d2 else "NOT ADOPTED"))
