"""My Secret Series forecast test + fresh-2026 test, exactly as docs/SECRETS_FORECAST_PREREG.md.
Run from the repo root: python -W ignore scripts/secrets_forecast.py
Output: results/secrets_forecast.csv, results/secrets_fresh.csv, printed tables."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant import indicators as ind  # noqa: E402
from dse_quant.backtest.engine import Config, run  # noqa: E402
from dse_quant.backtest.metrics import max_drawdown, sharpe  # noqa: E402
from dse_quant.data.load import load_a2_types  # noqa: E402
from dse_quant.panels import build_panels, eligible_mask  # noqa: E402
from dse_quant.regime import classify, inputs as regime_inputs  # noqa: E402
from dse_quant.strategies import make  # noqa: E402

PERIODS = {"A": ("2014-01-01", "2022-12-31"), "B": ("2023-01-01", "2026-01-22"), "C": ("2026-01-25", "2099-12-31")}
T_MIN, COST = 2.87, 0.011
OUT = Path("results")

df = pd.read_csv("data/clean/prices.csv.gz", parse_dates=["date"])
types = {**json.load(open("data/clean/report.json"))["dead_tickers_from_a1"], **load_a2_types()}
p = build_panels(df)
E = eligible_mask(p, types)
held = pd.read_csv(OUT / "secrets_table.csv")
hp = {(r.strategy, r.regime): json.loads(r.held_params) for r in held.itertuples()}
print("panels", p.close.shape, "last date", p.dates[-1].date())

# --- signals (bool date x ticker), direction, horizon
def entry(name, params):
    s = make(name, params)
    s.prepare(p, E)
    return pd.DataFrame(np.isfinite(s.score), index=p.dates, columns=p.tickers)


c, h, l = p.close.ffill(), p.high.ffill(), p.low.ffill()
s13, s19 = ind.sma(c, 13), ind.sma(c, 19)
line, sig = ind.macd(c)
r = ind.rsi(c)
up_band, _, _, _ = ind.bollinger(c)
ar = ind.aroon_up(h)
cross = lambda a, b: (a < b) & (a.shift() >= b.shift())
S = {"S1": (entry("S1", hp["S1", True]), +1, 2), "S7": (entry("S7", hp["S7", True]), +1, 5),
     "S25": (entry("S25", hp["S25", True]), +1, 7), "S23": (entry("S23", hp["S23", True]), +1, 7),
     "S67": (entry("S67", {"filter96": False, "exit_rule": "cross"}), +1, 10),
     "S67+96": (entry("S67", hp["S67", True]), +1, 10), "S98": (entry("S98", hp["S98", True]), +1, 20),
     "X2": (cross(line, sig), -1, 5), "X3": (cross(s13, s19), -1, 5), "X21": ((ar < 90) & (ar.shift() >= 90), -1, 5),
     "X31": ((c > up_band) & (r > 75), -1, 5), "X39": (r >= 97, -1, 5)}

gap = p.gap_flag.astype(float)
rows = []
for name, (fire, d, hz) in S.items():
    fwd = c.shift(-hz) / c - 1
    fwd = fwd.where(p.close.shift(-hz).notna())
    fwd = fwd.where(gap[::-1].rolling(hz, min_periods=1).max()[::-1].shift(-1).fillna(0) == 0)  # no gap in t+1..t+h
    base = fwd.where(E)
    exc = (fwd - base.mean(axis=1).values[:, None]) * d
    ev = fire & E & fwd.notna()
    for per, (a, b) in PERIODS.items():
        m = (p.dates >= a) & (p.dates <= b)
        e, x, f, bs = ev[m], exc[m], fwd[m], base[m]
        per_date = x.where(e).mean(axis=1).dropna()
        n_ev = int(e.values.sum())
        t = per_date.mean() / (per_date.std(ddof=1) / np.sqrt(len(per_date))) if len(per_date) > 2 else np.nan
        hit = float(((f.where(e) * d) > 0).sum().sum() / n_ev) if n_ev else np.nan
        base_hit = float(((bs * d) > 0).sum().sum() / bs.notna().sum().sum())
        rows.append({"signal": name, "predicts": "up" if d > 0 else "down", "h": hz, "period": per, "events": n_ev,
                     "dates": len(per_date), "mean_excess": float(x.where(e).stack().mean()) if n_ev else np.nan,
                     "t_dates": float(t), "hit_rate": hit, "base_hit_rate": base_hit})
fc = pd.DataFrame(rows)


def verdict(g):
    g = g.set_index("period")
    a_ok = g.at["A", "mean_excess"] > 0 and g.at["A", "t_dates"] >= T_MIN
    rest = all(g.at[k, "mean_excess"] > 0 for k in "BC" if g.at[k, "events"] > 0) and g.at["C", "events"] > 0
    cost_ok = g.at["A", "predicts"] == "down" or g.at["A", "mean_excess"] >= COST
    return "FORECASTS" if a_ok and rest and cost_ok else "WEAK" if a_ok else "NO"


v = fc.groupby("signal", sort=False).apply(verdict, include_groups=False).rename("verdict")
fc = fc.merge(v, left_on="signal", right_index=True)
OUT.mkdir(exist_ok=True)
fc.to_csv(OUT / "secrets_forecast.csv", index=False)
wide = fc.pivot_table(index=["signal", "predicts", "h", "verdict"], columns="period",
                      values=["events", "mean_excess", "t_dates", "hit_rate", "base_hit_rate"], sort=False)
pd.set_option("display.width", 250)
print(wide.round(4).to_string())

# --- test 2: rules traded, fresh slice
m = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date").reindex(p.dates)
mm, above, lock_frac = regime_inputs(p, E, types, m)
regime = classify(mm, above, lock_frac)
a, b = PERIODS["C"]
sl = lambda s: s[(s.index >= a) & (s.index <= b)]
dsex = sl(mm.dsex)
fr = []
for (name, rg), params in hp.items():
    res = run(p, make(name, params), Config(use_regime=rg, gap_exclusion=True), E, regime)
    ret = sl(res.equity.pct_change().fillna(0))
    tr = res.trades[res.trades.exit_date >= pd.Timestamp(a)] if len(res.trades) else res.trades
    fr.append({"rule": name, "regime_filter": rg, "params": json.dumps(params), "sharpe_C": sharpe(ret),
               "return_C": float((1 + ret).prod() - 1), "mdd_C": max_drawdown((1 + ret).cumprod()),
               "trades_C": len(tr), "win_rate_C": float((tr.pnl > 0).mean()) if len(tr) else np.nan})
fresh = pd.DataFrame(fr)
fresh.to_csv(OUT / "secrets_fresh.csv", index=False)
print(fresh.round(3).to_string())
print(f"DSEX {dsex.index[0].date()}..{dsex.index[-1].date()}: return {dsex.iloc[-1] / dsex.iloc[0] - 1:+.2%}, "
      f"sharpe {sharpe(dsex.pct_change().dropna()):.2f}")
print("regime days in C:", sl(regime).value_counts().to_dict())
