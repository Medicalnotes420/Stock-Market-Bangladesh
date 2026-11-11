"""Daily paper-trading run, after the DSE close. Produces an order file you would execute by hand
(always empty while no strategy has passed Phase 4) and appends one JSON line to the journal.

Order of work: data checks -> regime -> risk gate / kill switch -> orders -> journal. Any failure is
journaled as an alert and closes the gate; it never skips the journal."""
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from dse_quant import indicators as ind
from dse_quant.paper import book
from dse_quant.paper.book import _money
from dse_quant.strategies import make
from dse_quant.data.checks import data_status
from dse_quant.panels import build_panels, eligible_mask
from dse_quant.regime import classify, inputs as regime_inputs
from dse_quant.risk import Portfolio, RiskGate, exit_list

START_CASH = Decimal(10_000_000)  # Tk 1 crore paper account: assumption until you give capital size
HISTORY = 500     # sessions kept; >= 250 listing history + regime windows, and keeps a run under a minute
# paper-trackable rules: S67 was WEAK in docs/SECRETS_RESULTS.md, then rejected on fresh 2026 data
# (docs/SECRETS_FORECAST_RESULTS.md); off by default since 2026-11-05. Parameters are those chosen for held-out
STRATEGIES = {"S67": ("S67", {"filter96": True, "exit_rule": "cross"})}


def load_state(path):
    path = Path(path)
    if path.exists():
        s = json.loads(path.read_text())  # old files hold floats, new ones strings: both become Decimal
        for k in ("cash", "peak_equity", "day_start_equity", "equity"):
            if k in s:
                s[k] = _money(s[k])
        for lot in s.get("lots", {}).values():
            lot["basis"] = _money(lot["basis"])
        s["unsettled_cash"] = [[d, _money(a), lag] for d, a, lag in s.get("unsettled_cash", [])]
        return s
    return {"cash": START_CASH, "peak_equity": START_CASH, "day_start_equity": START_CASH, "positions": {}}


def author_flags(p, t):
    """Indicator values and the "My Secret Series" rule flags (docs/SECRETS_LEARNINGS.md) at the latest bar.
    The flags restate the author's rules; whether they work is what docs/SECRETS_RESULTS.md has the backtest results."""
    h, l, c = (x[t].ffill() for x in (p.high, p.low, p.close))
    v = p.value[t].fillna(0)
    r, (ml, ms), (bu, _, _, bw), a = ind.rsi(c), ind.macd(c), ind.bollinger(c), ind.aroon_up(h)
    dx, pdi, mdi = ind.adx(h, l, c)
    mf, s13, s19 = ind.mfi(h, l, c, v), ind.sma(c, 13), ind.sma(c, 19)
    now = lambda s: s.iloc[-1]
    crossed = lambda x, y: x.iloc[-1] > y.iloc[-1] and x.iloc[-2] <= y.iloc[-2]
    f = []
    if now(r) >= 97:
        f.append("#39 RSI 97+: author sells")
    elif now(r) >= 90:
        f.append("#1/#13 RSI 90+: author waits for a pullback to ~70")
    if r.iloc[-10:].max() >= 90 and 60 <= now(r) <= 72:
        f.append("#1 pulled back from RSI 90+ to ~70: author buys, sells at T+2")
    if crossed(ms, ml):
        f.append("#2 MACD line fell to its signal line: author sells")
    if now(a) < 90:
        f.append("#21 Aroon Up below 90: author exits a trend holding")
    if now(bw) <= bw.iloc[-120:].quantile(0.1):
        f.append("#25/#30 Bollinger squeeze: author's entry setup")
    if now(c) > now(bu) and now(r) > 75:
        f.append("#31 above upper Bollinger band with RSI 75+: author sells half")
    if crossed(s13, s19):
        f.append("#67 SMA13 crossed above SMA19: author's screener hit")
    if crossed(s19, s13):
        f.append("#3 moving average turned bearish: author sells")
    if (now(s13) > now(s19) and now(c) <= 1.1 * now(s19) and now(pdi) > now(mdi)
            and now(pdi) > pdi.iloc[-4] and now(mdi) < mdi.iloc[-4] and now(mf) > 60):
        f.append("#96 SMA + ADX + Money Flow checklist met")
    if now(v.rolling(20).mean()) < 0.1 * now(v.rolling(60).mean()):
        f.append("#38 turnover dried up: author says chart signals fail")
    num = lambda s: None if pd.isna(now(s)) else round(float(now(s)), 1)
    return {"rsi": num(r), "mfi": num(mf), "aroon_up": num(a), "adx": num(dx), "plus_di": num(pdi),
            "minus_di": num(mdi), "bb_width": num(bw * 100), "flags": f}


def watch_row(p, elig, t):
    """What the status page shows for one watched stock, at its latest bar (raw traded prices)."""
    c = p.close_raw[t].dropna()
    d = c.index[-1]
    adtv = p.adtv[t].iloc[-1]
    return {"last_bar": str(d.date()), "close": float(c.iloc[-1]),
            "change": float(c.iloc[-1] / c.iloc[-2] - 1) if len(c) > 1 else None,
            "lower_lock": bool(p.lower_lock.at[d, t]), "upper_lock": bool(p.upper_lock.at[d, t]),
            "adtv20": None if pd.isna(adtv) else float(adtv), "eligible": bool(elig[t].iloc[-1]),
            "gap_20d": bool(p.gap_flag[t].iloc[-20:].any()), **author_flags(p, t)}


def daily_run(prices, market, types, asof, state_path, journal_path, orders_dir, strategy=None, watch=(), categories=None):
    asof = pd.Timestamp(asof)
    entry = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "asof": str(asof.date()),
             "strategy": strategy or "none", "alerts": [], "orders": [], "exit_list": [], "regime": "UNKNOWN",
             "watchlist": {}}
    status, last_close, adtv = None, {}, {}
    try:
        hist = prices[prices.date <= asof]
        keep = sorted(hist.date.unique())[-HISTORY:]
        hist = hist[hist.date >= keep[0]]
        entry["inputs_hash"] = str(pd.util.hash_pandas_object(hist, index=False).sum())
        p = build_panels(hist)
        elig = eligible_mask(p, types)
        prior = elig.iloc[-2] if p.dates[-1] == asof and len(p.dates) > 1 else elig.iloc[-1]
        status = data_status(hist, asof, list(prior.index[prior]))
        last_close = p.close.ffill().iloc[-1].dropna().to_dict()
        adtv = p.adtv.iloc[-1].dropna().to_dict()
        if p.dates[-1] == asof:
            m, above, lock_frac = regime_inputs(p, elig, types, market)
            entry["regime"] = str(classify(m, above, lock_frac).iloc[-1])
            if pd.isna(market["n"].get(asof)):  # DSE market-summary day: breadth is unknown, so no RISK_ON
                entry["regime"] += " (no breadth data)"
        entry["data_status"] = {k: str(v) for k, v in status.items()}
        for t in watch:
            if t in p.close.columns and p.close_raw[t].notna().any():
                entry["watchlist"][t] = watch_row(p, elig, t)
            else:
                entry["alerts"].append(f"watchlist: {t} not in data")
    except Exception as e:  # corrupt or missing input: journal it, trade nothing
        entry["alerts"].append(f"input error: {type(e).__name__}: {e}")

    state_ok = False
    try:
        state = load_state(state_path)
        last = state.get("asof")
        if last and asof < pd.Timestamp(last):
            raise ValueError(f"asof {asof.date()} is before the last run {last}; use a fresh state file to replay")
        new_day = last != str(asof.date())
        bar_today = status is not None and p.dates[-1] == asof
        # a stale run (bar not loaded yet) marks the day seen but not its bar: the rerun with the bar must still
        # fill and decide. Old state files have no bar_asof: defaulting to asof means a processed day is never
        # filled twice; the cost is one missed fill if the old file's last run was stale.
        new_bar = bar_today and state.get("bar_asof", last) != str(asof.date())
        weekend = asof.dayofweek in (4, 5) and not bar_today
        if strategy:
            for k, v in book.new_book(state["cash"]).items():
                state.setdefault(k, v)
            for t, q in state["positions"].items():  # hand-entered (no-strategy) positions have no lot: matured, valued today
                state["lots"].setdefault(t, {"entry_date": "1900-01-01", "lag": book.settle_lag((categories or {}).get(t)),
                                             "basis": q * Decimal(str(last_close.get(t, 0.0)))})
            if new_bar:  # fill yesterday's orders once per session; a rerun keeps them
                entry["fills"] = book.fill_pending(state, p, len(p.dates) - 1, categories=categories)
        # baseline = equity at the previous day's close; a rerun of the same day keeps that day's baseline
        day_start = state["day_start_equity"] if last == str(asof.date()) else state.get("equity", state["day_start_equity"])
        pos = {t: q for t, q in state["positions"].items() if q > 0}
        prices_now = {t: Decimal(str(last_close.get(t, 0.0))) for t in pos}
        if status is not None:  # a held share with no price is valued at 0: say so, it can latch the kill switch
            entry["alerts"] += [f"no price for held share {t}: valued at 0" for t in pos if t not in last_close]
        receivable = sum((a for _, a, _ in state.get("unsettled_cash", [])), Decimal(0))
        equity = state["cash"] + receivable + sum(q * prices_now[t] for t, q in pos.items())
        # no-strategy mode has no lots, so positions count as matured; without data no lot can be proven matured
        unsettled = (book.unsettled_shares(state, p, len(p.dates) - 1) if status is not None
                     else {t: q for t, q in pos.items() if t in state.get("lots", {})})
        pf = Portfolio(equity=equity, peak_equity=max(state["peak_equity"], equity),
                       day_start_equity=day_start, positions=pos, prices=prices_now, unsettled=unsettled)
        if status is None:
            entry.update(gate_open=False, gate_reasons=["input_error"], kill=False)
        else:
            gate = RiskGate(pf, **status)
            entry.update(gate_open=gate.allow_new_entries, gate_reasons=gate.reasons, kill=gate.kill)
            if weekend:  # DSE trades Sunday-Thursday: a Friday/Saturday without prices is not stale data
                entry.update(gate_open=False, gate_reasons=[r for r in gate.reasons if r not in
                             ("stale_data", "missing_data", "missing_index")] + ["dse_weekend"])
            if gate.kill:
                entry["exit_list"] = exit_list(pf, adtv)
        if entry["regime"] == "STRESS" and pos:
            entry["exit_list"] = entry["exit_list"] or exit_list(pf, adtv)
        entry["equity"] = equity
        if strategy and (new_day or new_bar):
            if state.get("equity") and new_bar:
                state["returns"].append(float(equity / state["equity"] - 1))
            stale = not weekend and (status is None or status["latest_bar"] != status["expected"])
            book.stop_checks(state, stale=stale, kill=entry["kill"])
            if new_bar:
                name, params = STRATEGIES[strategy]
                strat = make(name, params)
                strat.prepare(p, elig)
                book.decide(state, strat, p, len(p.dates) - 1, regime=entry["regime"], gate_open=entry["gate_open"])
        if strategy:
            reason = f"stopped: {state['stopped']}" if state["stopped"] else f"{strategy} exit"
            entry["orders"] = ([{"ticker": t, "side": "SELL", "qty": state["positions"][t] - unsettled.get(t, 0),
                                 "reason": reason}
                                for t in state["pending_sells"] if state["positions"][t] > unsettled.get(t, 0)]
                               + [{"ticker": t, "side": "BUY", "qty": q, "reason": f"{strategy} entry"}
                                  for t, q in state["pending_buys"].items()])
            entry["book"] = {k: state[k] for k in ("cash", "positions", "stopped")}
        state_ok = True
    except Exception as e:  # corrupt or impossible state (e.g. zero equity): journal it, trade nothing
        entry["alerts"].append(f"state error: {type(e).__name__}: {e}")
        entry["gate_open"] = False
        entry.setdefault("gate_reasons", []).append("state_error")
        entry.setdefault("kill", False)
        entry.setdefault("equity", None)

    Path(orders_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(orders_dir) / f"orders_{asof.date()}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "side", "qty", "limit_price", "reason"])
        for r in entry["orders"]:
            w.writerow([r["ticker"], r["side"], r["qty"], "", r["reason"]])
        if not strategy:  # with a strategy, the book already turns kill/STRESS into sell orders
            for r in entry["exit_list"]:
                w.writerow([r["ticker"], "SELL", r["qty"], "", "kill_switch" if entry["kill"] else "stress"])
    Path(journal_path).parent.mkdir(parents=True, exist_ok=True)
    with open(journal_path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    # never overwrite a state file we could not use, or save equity valued without prices
    if state_ok and status is not None:
        state.update(asof=str(asof.date()), day_start_equity=day_start)
        if bar_today or new_day:  # a same-day stale rerun is valued at the previous close: keep the bar's equity
            state.update(equity=equity, peak_equity=pf.peak_equity)
        if bar_today:
            state["bar_asof"] = str(asof.date())
        Path(state_path).write_text(json.dumps(state, default=str))  # Decimal -> string; default= keeps it from raising
    return entry
