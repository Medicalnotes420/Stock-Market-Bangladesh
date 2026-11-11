"""Paper book for an enabled strategy (S67, docs/SECRETS_RESULTS.md). Same fill rules as the backtest engine:
orders decided at close t fill at the next session's typical price with costs, no sell before settlement (T+2,
T+3 for Cat Z), no sell on a lower-lock day, no buy on an upper-lock day. Sale proceeds stay in unsettled_cash
until they clear; buys spend settled cash only. Sizing and caps go through dse_quant.risk. State is a plain dict
saved in data/paper/state.json (money as Decimal; the harness writes strings and reads old floats too)."""
import math
from decimal import Decimal

import numpy as np

from async_risk_guard import ShareCategory
from dse_quant.backtest.costs import buy_fill, cost_amount
from dse_quant.backtest.metrics import sharpe
from dse_quant.limits import snap
from dse_quant.risk import LIMITS, Order, Portfolio, check_order, size_position

STOP_AFTER = 60     # live sessions before the performance stop can fire
STALE_STOP = 3      # stale-data sessions in a row while holding
_money = lambda v: Decimal(str(v))  # state value (old float or new string) -> Decimal
_D = lambda x: Decimal(str(float(x))) if math.isfinite(x) else Decimal(0)  # panel float -> Decimal; no price counts as 0


def settle_lag(category):
    """T+3 for Cat Z, T+2 otherwise. A missing or unknown category counts as Z: the safe side."""
    try:
        return 3 if ShareCategory(category) is ShareCategory.Z else 2
    except ValueError:
        return 3


def new_book(cash):
    # "cash" is SETTLED cash; unsettled_cash holds [sale_date, amount, lag] until the sale clears
    return {"cash": _money(cash), "unsettled_cash": [], "positions": {}, "lots": {}, "pending_buys": {},
            "pending_sells": [], "exit_attempts": [], "returns": [], "stale_days": 0, "stopped": None}


def _held_sessions(p, entry_date, t):
    d = p.dates
    return int(((d > entry_date) & (d <= d[t])).sum())


def unsettled_shares(book, p, t):
    """Shares that cannot be sold at the session after t (lot not matured yet), ticker -> shares."""
    lots = book.get("lots", {})  # absent in no-strategy mode: those positions count as matured
    return {tk: q for tk, q in book["positions"].items()
            if tk in lots and _held_sessions(p, lots[tk]["entry_date"], t) + 1 < lots[tk].get("lag", 3)}


def fill_pending(book, p, t, mult=1.0, categories=None):
    """Fill yesterday's orders at session t. Returns fill records for the journal."""
    d, fills, prev, categories = p.dates[t], [], max(t - 1, 0), categories or {}
    waiting = []
    for sale_date, amount, lag in book["unsettled_cash"]:
        if _held_sessions(p, sale_date, t) >= lag:
            book["cash"] += amount
        else:
            waiting.append([sale_date, amount, lag])
    book["unsettled_cash"] = waiting
    for tk in list(book["pending_sells"]):
        qty = book["positions"].get(tk, 0)
        if qty <= 0 or tk not in p.close.columns:
            book["pending_sells"].remove(tk)
            continue
        c = p.close.at[d, tk]
        lot = book["lots"][tk]
        lag = lot.get("lag", 3)  # stored at buy time; old state files predate it, so assume Cat Z (safe side)
        if math.isnan(c) or _held_sessions(p, lot["entry_date"], t) < lag:
            continue  # stays pending until matured, never dropped
        if p.lower_lock.at[d, tk]:
            book["exit_attempts"].append(1)
            continue
        book["exit_attempts"].append(0)
        px = snap((p.open.at[d, tk] + p.high.at[d, tk] + p.low.at[d, tk] + c) / 4, False)
        gross = qty * px
        proceeds = gross - cost_amount(gross, p.adtv[tk].iloc[prev], p.vol[tk].iloc[prev], mult)
        book["unsettled_cash"].append([str(d.date()), proceeds, lag])
        fills.append({"side": "SELL", "ticker": tk, "qty": qty, "price": px, "pnl": proceeds - lot["basis"]})
        del book["positions"][tk], book["lots"][tk]
        book["pending_sells"].remove(tk)
    for tk, q in book["pending_buys"].items():
        c = p.close.at[d, tk] if tk in p.close.columns else float("nan")
        if math.isnan(c) or p.upper_lock.at[d, tk]:
            continue
        px = snap((p.open.at[d, tk] + p.high.at[d, tk] + p.low.at[d, tk] + c) / 4, True)
        q, cost = buy_fill(q, px, p.adtv[tk].iloc[prev], p.vol[tk].iloc[prev], mult, book["cash"])
        if q <= 0:
            continue
        book["cash"] -= cost
        book["positions"][tk] = q
        book["lots"][tk] = {"entry_date": str(d.date()), "basis": cost, "lag": settle_lag(categories.get(tk))}
        fills.append({"side": "BUY", "ticker": tk, "qty": q, "price": px})
    book["pending_buys"] = {}
    return fills


def equity(book, p, t):
    last = p.close.ffill().iloc[t]
    return (book["cash"] + sum((a for _, a, _ in book["unsettled_cash"]), Decimal(0))
            + sum((q * _D(last.get(tk, 0.0)) for tk, q in book["positions"].items()), Decimal(0)))


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
    risk_mult = Decimal("0.5") if base == "NEUTRAL" else Decimal(1)
    last = p.close.ffill().iloc[t]
    pf = Portfolio(equity=eq, peak_equity=eq, day_start_equity=eq, positions=dict(book["positions"]),
                   prices={tk: _D(last[tk]) for tk in book["positions"]}, unsettled=unsettled_shares(book, p, t))
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
        q, _ = check_order(Order(tk, want, snap(p.close.iloc[t, j], True), "BUY"), pf, adtv[j], sector=tk)
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
