"""Paper book for an enabled strategy (S67, docs/SECRETS_RESULTS.md). Same fill rules as the backtest engine:
orders decided at close t fill at the next session's typical price with costs, no sell before T+2, no sell on a
lower-lock day, no buy on an upper-lock day. Sizing and caps go through dse_quant.risk. State is a plain dict
saved in data/paper/state.json."""
import math

import numpy as np

from dse_quant.backtest.costs import cost_rate
from dse_quant.backtest.metrics import sharpe
from dse_quant.risk import LIMITS, Order, Portfolio, check_order, size_position

STOP_AFTER = 60     # live sessions before the performance stop can fire
STALE_STOP = 3      # stale-data sessions in a row while holding


def new_book(cash):
    return {"cash": cash, "positions": {}, "lots": {}, "pending_buys": {}, "pending_sells": [],
            "exit_attempts": [], "returns": [], "stale_days": 0, "stopped": None}


def _held_sessions(p, entry_date, t):
    d = p.dates
    return int(((d > entry_date) & (d <= d[t])).sum())


def fill_pending(book, p, t, mult=1.0):
    """Fill yesterday's orders at session t. Returns fill records for the journal."""
    d, fills, prev = p.dates[t], [], max(t - 1, 0)
    for tk in list(book["pending_sells"]):
        qty = book["positions"].get(tk, 0)
        if qty <= 0 or tk not in p.close.columns:
            book["pending_sells"].remove(tk)
            continue
        c = p.close.at[d, tk]
        if math.isnan(c) or _held_sessions(p, book["lots"][tk]["entry_date"], t) < 2:
            continue
        if p.lower_lock.at[d, tk]:
            book["exit_attempts"].append(1)
            continue
        book["exit_attempts"].append(0)
        tp = (p.open.at[d, tk] + p.high.at[d, tk] + p.low.at[d, tk] + c) / 4
        proceeds = qty * tp * (1 - cost_rate(qty * tp, p.adtv[tk].iloc[prev], p.vol[tk].iloc[prev], mult))
        book["cash"] += proceeds
        fills.append({"side": "SELL", "ticker": tk, "qty": qty, "price": round(tp, 2),
                      "pnl": round(proceeds - book["lots"][tk]["basis"], 2)})
        del book["positions"][tk], book["lots"][tk]
        book["pending_sells"].remove(tk)
    for tk, q in book["pending_buys"].items():
        c = p.close.at[d, tk] if tk in p.close.columns else float("nan")
        if math.isnan(c) or p.upper_lock.at[d, tk]:
            continue
        tp = (p.open.at[d, tk] + p.high.at[d, tk] + p.low.at[d, tk] + c) / 4
        rate = cost_rate(q * tp, p.adtv[tk].iloc[prev], p.vol[tk].iloc[prev], mult)
        q = min(q, math.floor(book["cash"] / (tp * (1 + rate))))
        if q <= 0:
            continue
        cost = q * tp * (1 + rate)
        book["cash"] -= cost
        book["positions"][tk] = q
        book["lots"][tk] = {"entry_date": str(d.date()), "basis": cost}
        fills.append({"side": "BUY", "ticker": tk, "qty": q, "price": round(tp, 2)})
    book["pending_buys"] = {}
    return fills


def equity(book, p, t):
    last = p.close.ffill().iloc[t]
    return book["cash"] + sum(q * last.get(tk, 0.0) for tk, q in book["positions"].items())


def decide(book, strat, p, t, regime, gate_open):
    """Queue exits and entries at the close of session t (to fill next session)."""
    held = list(book["positions"])
    base = regime.split()[0]
    if book["stopped"] or base == "STRESS":
        book["pending_sells"] = held
        book["pending_buys"] = {}
        return
    for tk in held:
        j = p.tickers.index(tk) if tk in p.tickers else None
        if j is not None and not math.isnan(p.close.iloc[t, j]) and strat.exit(t, j, {}) \
                and tk not in book["pending_sells"]:
            book["pending_sells"].append(tk)
    if not gate_open or base not in ("RISK_ON", "NEUTRAL"):
        return
    eq = equity(book, p, t)
    risk_mult = 0.5 if base == "NEUTRAL" else 1.0
    last = p.close.ffill().iloc[t]
    pf = Portfolio(equity=eq, peak_equity=eq, day_start_equity=eq, positions=dict(book["positions"]),
                   prices={tk: last[tk] for tk in book["positions"]})
    elig = getattr(strat, "elig", None)
    adtv = p.adtv.iloc[t].values
    thr = (np.nanpercentile(adtv[elig[t]], 200 / 3) if base == "NEUTRAL" and elig is not None and elig[t].any()
           else -np.inf)  # same NEUTRAL rule as the engine: top liquidity tercile only
    names = len(book["positions"]) + len(book["pending_buys"])
    for j in strat.entries(t):
        tk = p.tickers[j]
        if names >= LIMITS.max_names:
            break
        if tk in book["positions"] or tk in book["pending_buys"] or not adtv[j] >= thr:
            continue
        want = size_position(eq * risk_mult, p.atr.iloc[t, j])
        if want <= 0:
            continue
        q, _ = check_order(Order(tk, want, p.close.iloc[t, j], "BUY"), pf, adtv[j], sector=tk)
        if q > 0:
            book["pending_buys"][tk] = q
            names += 1


def stop_checks(book, stale, kill):
    """Automatic stops (docs/PHASE5_HARNESS.md). Once stopped, the book only exits."""
    book["stale_days"] = book["stale_days"] + 1 if stale and book["positions"] else 0
    if book["stopped"]:
        return
    attempts = book["exit_attempts"][-20:]
    if kill:
        book["stopped"] = "kill switch: 15% drawdown from peak"
    elif book["stale_days"] >= STALE_STOP:
        book["stopped"] = f"stale data {book['stale_days']} sessions while holding positions"
    elif len(attempts) >= 5 and np.mean(attempts) > 0.2:
        book["stopped"] = "over 20% of recent exits blocked by lower-limit locks"
    elif len(book["returns"]) >= STOP_AFTER and sharpe(book["returns"]) < 0:
        # shortcut: live Sharpe < 0 after 60 sessions (backtest OOS was 0.54); use a bootstrap band once a year of live data exists
        book["stopped"] = f"live Sharpe below 0 after {len(book['returns'])} sessions"
