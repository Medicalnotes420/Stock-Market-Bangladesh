"""Tradable backtest of the DSEX patterns, exactly as the addendum in docs/DSEX_PATTERNS_PREREG.md.
Run from the repo root: python -W ignore scripts/dsex_backtest.py
Output: results/dsex_backtest.csv and a printed table."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.backtest.costs import cost_rate  # noqa: E402
from dse_quant.backtest.metrics import max_drawdown, sharpe, PPY  # noqa: E402
from dse_quant.data.load import load_a2_types  # noqa: E402
from dse_quant.panels import build_panels, eligible_mask  # noqa: E402

PERIODS = {"A": ("2014-01-01", "2022-12-31"), "B": ("2023-01-01", "2026-01-22"),
           "C": ("2026-01-25", "2026-11-04"), "D": ("2026-11-05", "2099-12-31")}
FLOOR = [("2020-03-19", "2021-04-07"), ("2022-07-28", "2024-01-21")]
N_NAMES, ORDER, MIN_HOLD = 30, 1e7, 2


def simulate(want, g, cost, floor):
    """want: desired position read at close t (1, 0, NaN = keep). g[s]: basket return TP_s -> TP_s+1.
    cost[s]: per-side cost of a fill at TP_s. Returns (daily net returns, number of switches)."""
    T = len(g)
    ret, pos, entry, switches = np.zeros(T), 0, -10, 0
    for s in range(1, T):
        d = 0 if floor[s] else (pos if np.isnan(want[s - 1]) else int(want[s - 1]))
        if d != pos and (d == 1 or s - entry >= MIN_HOLD or floor[s]):
            ret[s] -= cost[s]
            pos, switches = d, switches + 1
            entry = s if d == 1 else entry
        ret[s] += pos * (g[s] if np.isfinite(g[s]) else 0.0)
    return ret, switches


# self-check: always-in = one entry; flip every day obeys T+2 and pays each switch
_g, _c, _f = np.full(10, 0.01), np.full(10, 0.005), np.zeros(10, bool)
_r, _n = simulate(np.ones(10), _g, _c, _f)
assert _n == 1 and np.isclose(_r.sum(), 9 * 0.01 - 0.005)
_r, _n = simulate(np.tile([1.0, 0.0], 5), _g, _c, _f)
assert _n == 5  # in at 1, out at 3 (held 2), in at 5, out at 7, in at 9

if __name__ == "__main__":
    df = pd.read_csv("data/clean/prices.csv.gz", parse_dates=["date"])
    types = {**json.load(open("data/clean/report.json"))["dead_tickers_from_a1"], **load_a2_types()}
    p = build_panels(df)
    E = eligible_mask(p, types).reindex(index=p.dates, columns=p.tickers).fillna(False)
    TP = (p.open + p.high + p.low + p.close) / 4
    step = (TP.shift(-1) / TP - 1).where(~p.gap_flag.shift(-1, fill_value=False).astype(bool))
    # members for the interval starting at TP_s: top-30 traded value among eligible names at close s-1
    adtv_prev = p.adtv.where(E).shift(1)
    member = adtv_prev.rank(axis=1, ascending=False, method="first") <= N_NAMES
    g = step.where(member).mean(axis=1).values
    # shortcut: daily membership changes are not charged; only switches in and out of the basket pay
    per = ORDER / N_NAMES
    a, v = p.adtv.shift(1).where(member), p.vol.shift(1).where(member)
    cost = np.array([np.nanmean([cost_rate(per, x, y) for x, y in zip(a.values[s], v.values[s])
                                 if np.isfinite(x)]) if member.values[s].any() else np.nan
                     for s in range(len(p.dates))])
    cost = np.nan_to_num(cost, nan=cost_rate(per, 0, np.nan))
    floor = np.zeros(len(p.dates), bool)
    for x, y in FLOOR:
        floor |= (p.dates >= x) & (p.dates <= y)

    m = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date").reindex(p.dates)
    r = m.dsex / m.dsex.shift() - 1
    b = (m.adv - m.dec) / (m.adv + m.dec)
    nan = pd.Series(np.nan, index=p.dates)
    down3 = (r < 0) & (r.shift(1) < 0) & (r.shift(2) < 0)
    wants = {"BH": pd.Series(1.0, index=p.dates),
             "S_MOM1": nan.mask(r > 0, 1.0).mask(r < 0, 0.0),
             "S_BR1": nan.mask(b > 0, 1.0).mask(b < 0, 0.0),
             "S_DOWN3": nan.mask(r > 0, 1.0).mask(down3, 0.0),
             "S_SUN": pd.Series(np.where(p.dates.dayofweek == 2, 0.0, 1.0), index=p.dates)}

    rows = []
    for name, w in wants.items():
        ret, _ = simulate(w.values, g, cost, floor)
        ret = pd.Series(ret, index=p.dates)
        # diagnostic beyond the pre-registration: same path with zero costs
        gross = pd.Series(simulate(w.values, g, np.zeros_like(cost), floor)[0], index=p.dates)
        for per_id, (x, y) in PERIODS.items():
            sel = (p.dates >= x) & (p.dates <= y) & ~floor
            rr = ret[sel]
            if len(rr) < 2:
                rows.append({"strategy": name, "period": per_id, "n": len(rr)})
                continue
            # switches inside the period, recounted on that slice of the path
            _, sw = simulate(w.values[sel], g[sel], cost[sel], floor[sel])
            rows.append({"strategy": name, "period": per_id, "n": len(rr),
                         "ann_ret": float((1 + rr).prod() ** (PPY / len(rr)) - 1), "sharpe": sharpe(rr),
                         "ann_ret_gross": float((1 + gross[sel]).prod() ** (PPY / len(rr)) - 1),
                         "max_dd": max_drawdown((1 + rr).cumprod()), "switches": sw,
                         "cost_paid": float(sw * cost[sel].mean())})
    res = pd.DataFrame(rows)
    bh = res[res.strategy == "BH"].set_index("period")

    def verdict(gr):
        name, gr = gr.name, gr.set_index("period")
        if name == "BH":
            return "benchmark"
        ok = all(gr.at[k, "ann_ret"] > bh.at[k, "ann_ret"] for k in "ABC") and gr.at["A", "sharpe"] > bh.at["A", "sharpe"]
        return "BEATS BUY-AND-HOLD" if ok else "DOES NOT BEAT"

    v = res.groupby("strategy", sort=False).apply(verdict).rename("verdict")
    res = res.merge(v, left_on="strategy", right_index=True)
    Path("results").mkdir(exist_ok=True)
    res.to_csv("results/dsex_backtest.csv", index=False)
    pd.set_option("display.width", 220)
    print("basket cost per side: median", f"{np.median(cost):.4f}")
    print(res.pivot_table(index=["strategy", "verdict"], columns="period",
                          values=["ann_ret", "ann_ret_gross", "sharpe", "max_dd", "switches"], sort=False).round(3).to_string())
