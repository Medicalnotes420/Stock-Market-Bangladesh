"""Daily paper-trading run, after the DSE close. Produces an order file you would execute by hand
(always empty while no strategy has passed Phase 4) and appends one JSON line to the journal.

Order of work: data checks -> regime -> risk gate / kill switch -> orders -> journal. Any failure is
journaled as an alert and closes the gate; it never skips the journal."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dse_quant.data.checks import data_status
from dse_quant.panels import build_panels, eligible_mask
from dse_quant.regime import classify, inputs as regime_inputs
from dse_quant.risk import Portfolio, RiskGate, exit_list

START_CASH = 1e7  # Tk 1 crore paper account: assumption until you give capital size
HISTORY = 500     # sessions kept; >= 250 listing history + regime windows, and keeps a run under a minute


def load_state(path):
    path = Path(path)
    if path.exists():
        return json.loads(path.read_text())
    return {"cash": START_CASH, "peak_equity": START_CASH, "day_start_equity": START_CASH, "positions": {}}


def watch_row(p, elig, t):
    """What the status page shows for one watched stock, at its latest bar (raw traded prices)."""
    c = p.close_raw[t].dropna()
    d = c.index[-1]
    adtv = p.adtv[t].iloc[-1]
    return {"last_bar": str(d.date()), "close": float(c.iloc[-1]),
            "change": float(c.iloc[-1] / c.iloc[-2] - 1) if len(c) > 1 else None,
            "lower_lock": bool(p.lower_lock.at[d, t]), "upper_lock": bool(p.upper_lock.at[d, t]),
            "adtv20": None if pd.isna(adtv) else float(adtv), "eligible": bool(elig[t].iloc[-1]),
            "gap_20d": bool(p.gap_flag[t].iloc[-20:].any())}


def daily_run(prices, market, types, asof, state_path, journal_path, orders_dir, strategy=None, watch=()):
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
        # baseline = equity at the previous day's close; a rerun of the same day keeps that day's baseline
        day_start = state["day_start_equity"] if last == str(asof.date()) else state.get("equity", state["day_start_equity"])
        pos = {t: q for t, q in state["positions"].items() if q > 0}
        prices_now = {t: last_close.get(t, 0.0) for t in pos}
        equity = state["cash"] + sum(q * prices_now[t] for t, q in pos.items())
        pf = Portfolio(equity=equity, peak_equity=max(state["peak_equity"], equity),
                       day_start_equity=day_start, positions=pos, prices=prices_now)
        if status is None:
            entry.update(gate_open=False, gate_reasons=["input_error"], kill=False)
        else:
            gate = RiskGate(pf, **status)
            entry.update(gate_open=gate.allow_new_entries, gate_reasons=gate.reasons, kill=gate.kill)
            if gate.kill:
                entry["exit_list"] = exit_list(pf, adtv)
        if entry["regime"] == "STRESS" and pos:
            entry["exit_list"] = entry["exit_list"] or exit_list(pf, adtv)
        # no strategy enabled: nothing passed Phase 4, so orders stay empty by construction
        entry["equity"] = equity
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
        for r in entry["exit_list"]:
            w.writerow([r["ticker"], "SELL", r["qty"], "", "kill_switch" if entry["kill"] else "stress"])
    Path(journal_path).parent.mkdir(parents=True, exist_ok=True)
    with open(journal_path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    # never overwrite a state file we could not use, or save equity valued without prices
    if state_ok and status is not None:
        state.update(asof=str(asof.date()), equity=equity, day_start_equity=day_start, peak_equity=pf.peak_equity)
        Path(state_path).write_text(json.dumps(state))
    return entry
