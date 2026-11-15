"""Daily trade plan for one DSE share: stop, target, size within the hard limits, and how often the same rule
hit its target or its stop first on this share's own history. Numbers, not advice; the odds are history.

DSE has no intraday data here and shares settle T+2, so this is a days-to-weeks plan, never a day trade."""
import math
from decimal import Decimal

import numpy as np

from dse_quant.backtest.costs import cost_rate
from dse_quant.limits import snap
from dse_quant.risk import LIMITS, Order, Portfolio, check_order

LOOKBACK, HORIZON, TARGET_R = 20, 20, 2.0
MIN_RISK_COSTS = 4  # stop must be >= 4 x the per-side cost away, so the round trip eats at most half the risk


def replay(df, lookback=LOOKBACK, horizon=HORIZON, target_r=TARGET_R, cost=0.0):
    """The rule on every past session t: buy at close t, stop at the lowest low of sessions t-lookback+1..t,
    target = entry + target_r x risk; then walk the next `horizon` sessions. Stop is checked before target in
    a session (cautious); a gap below the stop fills at that day's open. Days flagged as gaps in df (bonus/split)
    are skipped as entries, and so are stops closer than MIN_RISK_COSTS x cost (plan() refuses those).
    Returns (outcome, gross R, R after `cost` per side, a fraction of price) per trade."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    gap = df["gap_flag"].to_numpy(bool) if "gap_flag" in df else np.zeros(len(df), bool)
    out = []
    for t in range(lookback - 1, len(df) - horizon):
        if gap[t:t + horizon + 1].any():
            continue
        e = c[t]
        s = float(snap(l[t - lookback + 1:t + 1].min(), False))
        risk = e - s
        if risk <= 0 or risk < MIN_RISK_COSTS * cost * e:
            continue
        tgt = e + target_r * risk
        R, outcome = (c[t + horizon] - e) / risk, "open"
        for d in range(t + 1, t + horizon + 1):
            if l[d] <= s:
                R, outcome = (min(s, o[d]) - e) / risk, "stop"
                break
            if h[d] >= tgt:
                R, outcome = (max(tgt, o[d]) - e) / risk, "target"
                break
        out.append((outcome, R, R - 2 * cost * e / risk))
    return out


def plan(df, symbol, equity, entry=None, stop=None, target_r=TARGET_R, max_loss=None, held_value=0.0):
    """df: daily OHLCV (+ optional gap_flag), oldest first. equity: the user's total portfolio in Tk.
    max_loss defaults to LIMITS.risk_per_atr of equity (the same 0.5% the paper strategy risks)."""
    if not equity or not math.isfinite(equity) or equity <= 0:
        raise ValueError("equity (your portfolio in Tk) must be > 0")
    equity = Decimal(str(equity))  # caller floats become Decimal here; prices are tick-snapped
    last = df.iloc[-1]
    entry = snap(last.close if entry is None else entry, True)
    stop = snap(df.low.iloc[-LOOKBACK:].min() if stop is None else stop, False)
    if stop >= entry:
        raise ValueError(f"stop {stop:,.2f} must be below the entry {entry:,.2f}")
    risk = entry - stop
    target = snap(entry + Decimal(str(target_r)) * risk, False)
    max_loss = LIMITS.risk_per_atr * equity if max_loss is None else Decimal(str(max_loss))
    value = df.close * df.volume
    adtv20 = float(value.iloc[-20:].mean())
    sigma = float(np.log(df.close).diff().iloc[-20:].std())
    want = math.floor(max_loss / risk)
    # held_value: Tk already in this share, so the 10% position cap counts it (1 share priced at that value)
    held_value = Decimal(str(held_value))
    pf = Portfolio(equity, equity, equity, positions={symbol: 1} if held_value else {},
                   prices={symbol: held_value} if held_value else {})
    qty, capped_by = check_order(Order(symbol, want, entry, "BUY"), pf, adtv20, sector="", limits=LIMITS)
    cost = cost_rate(qty * entry, adtv20, sigma)
    if risk < MIN_RISK_COSTS * cost * entry:
        raise ValueError(f"stop {stop:,.2f} is too close: costs (~{cost:.2%} each way) would eat over half the risk; "
                         f"put it at least Tk {MIN_RISK_COSTS * cost * entry:,.2f} below the entry")
    trades = replay(df, target_r=target_r, cost=float(cost))  # replay is statistics: float
    n = len(trades) or 1
    mean = lambda i: float(np.mean([x[i] for x in trades])) if trades else float("nan")
    return {
        "symbol": symbol, "date": f"{df.index[-1]:%Y-%m-%d}", "entry": entry, "stop": stop, "target": target,
        "risk_per_share": risk, "risk_pct": risk / entry, "max_loss": max_loss, "shares": qty, "wanted": want,
        "capped_by": capped_by, "value": qty * entry, "loss_at_stop": qty * risk, "gain_at_target": qty * (target - entry),
        "cost_per_side": cost, "horizon": HORIZON,
        "history": {"cases": len(trades), "from": f"{df.index[LOOKBACK - 1]:%Y-%m-%d}",
                    "target_pct": sum(x[0] == "target" for x in trades) / n,
                    "stop_pct": sum(x[0] == "stop" for x in trades) / n,
                    "open_pct": sum(x[0] == "open" for x in trades) / n,
                    "gross_R": mean(1), "avg_R": mean(2)},
    }
