"""Volume vs future price test, exactly as docs/VOLUME_FORECAST_PREREG.md.
Run from the repo root: python -W ignore scripts/volume_forecast.py
Output: results/volume_forecast.csv and a printed table."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.data.load import load_a2_types  # noqa: E402
from dse_quant.panels import build_panels, eligible_mask  # noqa: E402

PERIODS = {"A": ("2014-01-01", "2022-12-31"), "B": ("2023-01-01", "2026-01-22"), "C": ("2026-01-25", "2099-12-31")}
T_DIR, T_MAG, COST = 2.64, 2.24, 0.011
OUT = Path("results")

df = pd.read_csv("data/clean/prices.csv.gz", parse_dates=["date"])
types = {**json.load(open("data/clean/report.json"))["dead_tickers_from_a1"], **load_a2_types()}
p = build_panels(df)
E = eligible_mask(p, types)
c = p.close.ffill()
val = p.value.where(p.value > 0)
base20 = val.fillna(0).shift(1).rolling(20, min_periods=20).mean()  # sessions t-20..t-1, no-trade days count as 0
R = (val / base20).where(base20 > 0)
day = c / c.shift() - 1
inC = p.dates >= PERIODS["C"][0]
print("panels", p.close.shape, "last date", p.dates[-1].date(), "| R known on",
      f"{R.where(E).notna().values[inC].sum() / E.values[inC].sum():.0%} of eligible stock-days in C")
gap = p.gap_flag.astype(float)


def fwd_excess(hz):
    fwd = c.shift(-hz) / c - 1
    fwd = fwd.where(p.close.shift(-hz).notna())
    fwd = fwd.where(gap[::-1].rolling(hz, min_periods=1).max()[::-1].shift(-1).fillna(0) == 0)  # no gap in t+1..t+h
    base = fwd.where(E)
    return fwd, base, fwd - base.mean(axis=1).values[:, None]


def daily_ic(x, y):
    """Spearman across stocks per day (needs >= 20 stocks that day)."""
    ok = x.notna() & y.notna()
    xr, yr = x.where(ok).rank(axis=1), y.where(ok).rank(axis=1)
    return xr.corrwith(yr, axis=1).where(ok.sum(axis=1) >= 20).dropna()


def tstat(s):
    return s.mean() / (s.std(ddof=1) / np.sqrt(len(s))) if len(s) > 2 else np.nan


rows = []
for hz in (5, 20):
    fwd, base, exc = fwd_excess(hz)
    events = {f"VU{hz}": ((R >= 2) & (day > 0), +1), f"VD{hz}": ((R >= 2) & (day < 0), -1)}
    for name, (fire, d) in events.items():
        ev = fire & E & exc.notna()
        x = exc * d
        for per, (a, b) in PERIODS.items():
            m = (p.dates >= a) & (p.dates <= b)
            e, xx, f, bs = ev[m], x[m], fwd[m], base[m]
            per_date = xx.where(e).mean(axis=1).dropna()
            n = int(e.values.sum())
            rows.append({"test": name, "kind": "event", "predicts": "up" if d > 0 else "down", "h": hz, "period": per,
                         "n": n, "mean": float(xx.where(e).stack().mean()) if n else np.nan, "t": float(tstat(per_date)),
                         "hit_rate": float(((f.where(e) * d) > 0).sum().sum() / n) if n else np.nan,
                         "base_hit_rate": float(((bs * d) > 0).sum().sum() / bs.notna().sum().sum())})
    sig = (np.log(R) * np.sign(day)).where(E)
    for name, xs, ys in ((f"IC{hz}", sig, exc.where(E)), (f"MAG{hz}", np.log(R).where(E), exc.abs().where(E))):
        ic = daily_ic(xs, ys)
        for per, (a, b) in PERIODS.items():
            s = ic[(ic.index >= a) & (ic.index <= b)]
            rows.append({"test": name, "kind": "ic", "predicts": "size" if name.startswith("MAG") else "up", "h": hz,
                         "period": per, "n": len(s), "mean": float(s.mean()), "t": float(tstat(s)),
                         "hit_rate": float((s > 0).mean()), "base_hit_rate": np.nan})
res = pd.DataFrame(rows)


def verdict(g):
    g = g.set_index("period")
    mag = g["predicts"].iat[0] == "size"
    tmin = T_MAG if mag else T_DIR
    a_ok = g.at["A", "mean"] > 0 and g.at["A", "t"] >= tmin
    rest = all(g.at[k, "mean"] > 0 for k in "BC" if g.at[k, "n"] > 0) and g.at["C", "n"] > 0
    cost_ok = not (g["kind"].iat[0] == "event" and g["predicts"].iat[0] == "up") or g.at["A", "mean"] >= COST
    if a_ok and rest and cost_ok:
        return "LARGER MOVES" if mag else "FORECASTS"
    return "WEAK" if a_ok else "NO"


v = res.groupby("test", sort=False).apply(verdict, include_groups=False).rename("verdict")
res = res.merge(v, left_on="test", right_index=True)
OUT.mkdir(exist_ok=True)
res.to_csv(OUT / "volume_forecast.csv", index=False)
pd.set_option("display.width", 250)
print(res.pivot_table(index=["test", "predicts", "verdict"], columns="period",
                      values=["n", "mean", "t", "hit_rate", "base_hit_rate"], sort=False).round(4).to_string())
