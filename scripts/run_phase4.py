"""Phase 4: run every pre-registered variant, walk-forward selection, cost sensitivity, held-out check.
Rules are fixed in docs/PHASE4_PREREG.md. Run from the repo root: python scripts/run_phase4.py
`python scripts/run_phase4.py secrets` runs the My Secret Series rules instead (docs/SECRETS_PREREG.md).
Writes results/<tag>_*.csv/json."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dse_quant.backtest.engine import Config, run  # noqa: E402
from dse_quant.backtest.metrics import deflated_sharpe, first_breach, max_drawdown, sharpe, trade_stats  # noqa: E402
from dse_quant.backtest.walkforward import stitch, switch_cost  # noqa: E402
from dse_quant.risk import LIMITS  # noqa: E402
from dse_quant.data.load import load_a2_types  # noqa: E402
from dse_quant.panels import build_panels, eligible_mask  # noqa: E402
from dse_quant.regime import classify, inputs as regime_inputs, proxy_returns  # noqa: E402
from dse_quant.strategies import GRIDS, PHASE4, SECRETS, make  # noqa: E402

OUT = Path("results")
TRAIN = ("2014-01-01", "2022-12-31")
OOS_YEARS = range(2017, 2023)
HELD = ("2023-01-01", "2026-12-31")
FLOOR = [("2020-03-19", "2021-04-07"), ("2022-07-28", "2024-01-21")]
SECRET_RUN = sys.argv[1:] == ["secrets"]
TAG, NAMES = ("secrets", SECRETS) if SECRET_RUN else ("phase4", PHASE4)
SETTINGS = [(rg, gp) for rg in (True, False) for gp in ((True,) if SECRET_RUN else (True, False))]
t0 = time.time()
log = lambda *a: print(f"[{time.time() - t0:6.0f}s]", *a, flush=True)

df = pd.read_csv("data/clean/prices.csv.gz", parse_dates=["date"])
# full-market data only: later DSE copies cover just the watchlist (breadth n is NaN there)
mk = pd.read_csv("data/clean/market.csv", parse_dates=["date"])
df = df[df.date <= mk.date[mk.n.notna()].max()]
types = {**json.load(open("data/clean/report.json"))["dead_tickers_from_a1"], **load_a2_types()}
p = build_panels(df)
E = eligible_mask(p, types)
log("panels built")

# --- market inputs and regime
m = pd.read_csv("data/clean/market.csv", parse_dates=["date"]).set_index("date").reindex(p.dates)
prox = proxy_returns(p, types)
dsex_r = m.dsex.pct_change(fill_method=None)
both = dsex_r.notna() & prox.notna() & m.dsex.shift().notna()
proxy_check = {"overlap_days": int(both.sum()), "corr_daily": round(float(dsex_r[both].corr(prox[both])), 3),
               "dsex_missing_filled": int(m.dsex.isna().sum())}
m, above, lock_frac = regime_inputs(p, E, types, m)
regime = classify(m, above, lock_frac)
reg_counts = regime.groupby(regime.index.year).value_counts().unstack(fill_value=0)
log("regime done", proxy_check)

# --- all variants at 1x
period = lambda s, a, b: s[(s.index >= a) & (s.index <= b)]
runs, rets = {}, {}
for name in NAMES:
    grid = GRIDS[name]
    for gi, params in enumerate(grid):
        for rg, gp in SETTINGS:
            res = run(p, make(name, params), Config(use_regime=rg, gap_exclusion=gp), E, regime)
            key = (name, gi, rg, gp)
            runs[key] = res.trades
            rets[key] = res.equity.pct_change().fillna(0)
    log(name, "grid done")
n_trials = len(rets)
sr_pp = pd.Series({k: sharpe(period(r, *TRAIN)) / np.sqrt(240) for k, r in rets.items()})
if SECRET_RUN:  # count every variant ever tried on this data
    prior = pd.read_csv(OUT / "phase4_variants.csv").train_sharpe_2014_2022 / np.sqrt(240)
    sr_pp, n_trials = pd.concat([sr_pp, prior], ignore_index=True), n_trials + len(prior)
sr_var = float(sr_pp.var())

# --- walk-forward per strategy x setting
def wf(chosen, store, mult=1.0):
    yr = {y: period(store[(n, chosen[y], rg, gp)], f"{y}-01-01", f"{y}-12-31") for y in OOS_YEARS}
    return stitch(yr, chosen, switch_cost(mult))

def trades_in(keys_by_year, store_trades):
    pn = []
    for y, k in keys_by_year.items():
        t = store_trades[k]
        pn.append(t[(t.exit_date >= f"{y}-01-01") & (t.exit_date <= f"{y}-12-31")])
    return pd.concat(pn)

def ex_floor(r):
    keep = np.ones(len(r), bool)
    for a, b in FLOOR:
        keep &= ~((r.index >= a) & (r.index <= b))
    return r[keep]

rows, variants = [], []
for name in NAMES:
    grid = GRIDS[name]
    for rg, gp in SETTINGS:
        tr_sh = {gi: sharpe(period(rets[(name, gi, rg, gp)], *TRAIN)) for gi in range(len(grid))}
        for gi, s in tr_sh.items():
            variants.append({"strategy": name, "params": json.dumps(grid[gi]), "regime": rg, "gap_excl": gp,
                             "train_sharpe_2014_2022": round(s, 3)})
        chosen = {}
        for y in list(OOS_YEARS) + [2023]:
            win = {gi: sharpe(period(rets[(name, gi, rg, gp)], f"{y - 3}-01-01", f"{y - 1}-12-31"))
                   for gi in range(len(grid))}
            chosen[y] = max(win, key=win.get)
        n = name
        oos, n_switch = wf(chosen, rets)
        oos_trades = trades_in({y: (n, chosen[y], rg, gp) for y in OOS_YEARS}, runs)
        oos_tr = trade_stats(oos_trades.pnl)
        # cost sensitivity: rerun the selected parameter sets at higher cost
        cost_sh = {}
        for mult in (1.5, 2.0):
            store = {}
            for gi in set(chosen[y] for y in OOS_YEARS):
                res = run(p, make(n, grid[gi]), Config(cost_mult=mult, use_regime=rg, gap_exclusion=gp), E, regime)
                store[(n, gi, rg, gp)] = res.equity.pct_change().fillna(0)
            cost_sh[mult] = sharpe(wf(chosen, store, mult)[0])
        held_key = (n, chosen[2023], rg, gp)
        held = period(rets[held_key], *HELD).copy()
        if chosen[2023] != chosen[2022] and len(held):
            held.iloc[0] = (1 + held.iloc[0]) * (1 - switch_cost()) - 1
        oos_kill = first_breach((1 + oos).cumprod(), LIMITS.max_drawdown)
        held_kill = first_breach((1 + held).cumprod(), LIMITS.max_drawdown)
        ht = runs[held_key]
        held_tr = trade_stats(ht[ht.exit_date >= HELD[0]].pnl)
        row = {
            "strategy": n, "regime": rg, "gap_excl": gp,
            "oos_sharpe": sharpe(oos), "oos_mdd": max_drawdown((1 + oos).cumprod()),
            "oos_cagr": float((1 + oos).prod() ** (240 / len(oos)) - 1),
            "oos_trades": oos_tr["trades"], "oos_win_rate": oos_tr["win_rate"], "oos_pf": oos_tr["profit_factor"],
            "oos_sharpe_1_5x": cost_sh[1.5], "oos_sharpe_2x": cost_sh[2.0], "oos_switches": n_switch,
            "oos_trades_through_gap": float((oos_trades.gap_days > 0).mean()) if len(oos_trades) else 0.0,
            "oos_kill_date": oos_kill.date() if oos_kill is not None else None,
            "held_kill_date": held_kill.date() if held_kill is not None else None,
            "neighbourhood_pos": float(np.mean([s > 0 for s in tr_sh.values()])),
            "dsr": deflated_sharpe(oos, n_trials, sr_var),
            "oos_sharpe_ex_floor": sharpe(ex_floor(oos)),
            "held_sharpe": sharpe(held), "held_mdd": max_drawdown((1 + held).cumprod()),
            "held_trades": held_tr["trades"], "held_params": json.dumps(grid[chosen[2023]]),
            "params_by_year": json.dumps({y: grid[chosen[y]] for y in OOS_YEARS}),
        }
        c1 = row["oos_sharpe"] >= 0.5 and row["oos_trades"] >= 30
        c5 = oos_kill is None  # changed from mdd <= 25%: see "Changes after registration"
        crit = [c1, row["oos_sharpe_1_5x"] > 0, row["neighbourhood_pos"] >= 2 / 3, row["dsr"] >= 0.9, c5,
                row["oos_sharpe_ex_floor"] > 0, row["held_sharpe"] > 0]
        row["criteria_passed"] = "".join("Y" if x else "n" for x in crit)
        row["verdict"] = "SURVIVES" if all(crit) else ("WEAK" if c1 and c5 else "REJECT")
        rows.append(row)
    log(name, "walk-forward done")

# --- benchmark: DSEX (proxy-filled) buy and hold
bench = m.dsex.pct_change(fill_method=None).fillna(0)
boos = pd.concat([period(bench, f"{y}-01-01", f"{y}-12-31") for y in OOS_YEARS])
bheld = period(bench, *HELD)
benchmark = {"oos_sharpe": sharpe(boos), "oos_mdd": max_drawdown((1 + boos).cumprod()),
             "held_sharpe": sharpe(bheld), "held_mdd": max_drawdown((1 + bheld).cumprod())}

OUT.mkdir(exist_ok=True)
table = pd.DataFrame(rows)
table.to_csv(OUT / f"{TAG}_table.csv", index=False)
pd.DataFrame(variants).to_csv(OUT / f"{TAG}_variants.csv", index=False)
reg_counts.to_csv(OUT / f"{TAG}_regime_counts.csv")
(OUT / f"{TAG}_meta.json").write_text(json.dumps(
    {"n_trials": n_trials, "sr_var_per_period": sr_var, "proxy_check": proxy_check, "benchmark_dsex": benchmark,
     "runtime_s": round(time.time() - t0)}, indent=1))
pd.set_option("display.width", 250)
print(table[["strategy", "regime", "gap_excl", "oos_sharpe", "oos_mdd", "oos_trades", "oos_win_rate", "oos_pf",
             "oos_sharpe_1_5x", "oos_sharpe_2x", "oos_switches", "oos_trades_through_gap", "oos_kill_date", "neighbourhood_pos", "dsr",
             "oos_sharpe_ex_floor", "held_sharpe", "held_kill_date", "criteria_passed", "verdict"]].round(3).to_string())
print(json.dumps({"benchmark_dsex": benchmark, "proxy_check": proxy_check, "n_trials": n_trials}, indent=1))
if SECRET_RUN:  # #62/#64 "top side flash" claim check, descriptive (docs/SECRETS_PREREG.md)
    v, c, h = p.value, p.close, p.high
    flash = (v >= 3 * v.shift(1).rolling(20, min_periods=15).mean()) & (c / c.ffill().shift() - 1 >= 0.05) & E
    flash = flash[(flash.index >= TRAIN[0]) & (flash.index <= TRAIN[1])].reindex(p.dates, fill_value=False)
    next2 = pd.concat([h.shift(-1), h.shift(-2)]).groupby(level=0).max()
    held = (next2 <= h)[flash & next2.notna()].stack()
    up3 = (c.shift(-3) > c)[flash & c.shift(-3).notna()].stack()
    claim = {"flash_days": int(flash.values.sum()), "next2_high_not_above_flash_high": round(float(held.mean()), 3),
             "close_3_sessions_later_above_flash_close": round(float(up3.mean()), 3)}
    print("#62 top side flash:", claim)
    meta = json.loads((OUT / f"{TAG}_meta.json").read_text())
    (OUT / f"{TAG}_meta.json").write_text(json.dumps({**meta, "claim_62_top_side_flash": claim}, indent=1))
log("done")
