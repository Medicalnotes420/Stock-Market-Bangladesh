"""Daily-bar long-only backtest. Signals at close t, fills at t+1 typical price (docs/PHASE4_PREREG.md).

Strategies only nominate tickers; sizing and every cap go through dse_quant.risk."""
import math
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from dse_quant.backtest.costs import buy_fill, cost_amount
from dse_quant.limits import snap
from dse_quant.risk import LIMITS, Order, Portfolio, check_order, daily_loss_breached, size_position


@dataclass(frozen=True)
class Config:
    cost_mult: float = 1.0
    use_regime: bool = True
    gap_exclusion: bool = True
    start_equity: Decimal = Decimal(10_000_000)  # Tk 1 crore: assumption until you give capital size (floats are converted)
    writeoff_after: int = 60        # sessions without a bar -> assume delisted, value 0
    gap_days: int = 20
    # shortcut: T+2 for all shares and sale proceeds; Cat Z is T+3 but no category history exists. Upgrade with one.
    settle_lag: int = 2


@dataclass
class Result:
    equity: pd.Series
    cash: pd.Series
    positions: pd.DataFrame
    trades: pd.DataFrame


_D = lambda x: x if isinstance(x, Decimal) else Decimal(str(float(x)))  # panel float -> Decimal, only at the fill/sizing call site


def run(p, strat, cfg, elig, regime=None):
    T, J = len(p.dates), len(p.tickers)
    O, H, L, C = (x.values for x in (p.open, p.high, p.low, p.close))
    TP = (O + H + L + C) / 4
    has = ~np.isnan(C)
    LL, UL, GAP = p.lower_lock.values, p.upper_lock.values, p.gap_flag.values
    ATR, ADTV, VOL = p.atr.values, p.adtv.values, p.vol.values
    E = elig.reindex(index=p.dates, columns=p.tickers).fillna(False).values.astype(bool)
    if cfg.gap_exclusion:
        E &= ~(p.gap_flag.astype(float).rolling(cfg.gap_days, min_periods=1).max().values > 0)
    reg = regime.reindex(p.dates).fillna("NEUTRAL").values if cfg.use_regime and regime is not None else None
    strat.prepare(p, pd.DataFrame(E, index=p.dates, columns=p.tickers))

    qty = np.zeros(J, dtype=np.int64)
    entry_t = np.full(J, -1)
    entry_px, entry_atr, peak = np.zeros(J), np.zeros(J), np.zeros(J)  # entry_px/peak feed float stop signals
    basis = [Decimal(0)] * J
    last_px, missing = np.full(J, np.nan), np.zeros(J, dtype=int)
    cash = prev_equity = peak_eq = _D(cfg.start_equity)  # settled cash; sale proceeds wait in `unsettled`
    unsettled = []  # (clear_t, amount)
    pend_sell, pend_buy = set(), {}
    eq_hist, cash_hist, pos_hist, trades = np.zeros(T), np.zeros(T), np.zeros((T, J)), []

    def close_out(t, j, proceeds, reason):
        trades.append({"ticker": p.tickers[j], "entry_date": p.dates[entry_t[j]], "exit_date": p.dates[t],
                       "qty": int(qty[j]), "pnl": float(proceeds - basis[j]), "ret": float(proceeds / basis[j] - 1),
                       "reason": reason,
                       # unexplained gaps while held: P&L may include an unadjusted corporate action
                       "gap_days": int(GAP[entry_t[j] + 1:t + 1, j].sum())})
        qty[j], entry_t[j] = 0, -1
        pend_sell.discard(j)

    for t in range(T):
        # 1. sale proceeds that cleared, then fills for orders decided at the previous close
        cash += sum((a for c, a in unsettled if c <= t), Decimal(0))
        unsettled[:] = [(c, a) for c, a in unsettled if c > t]
        if t > 0:
            for j in sorted(pend_sell):
                if has[t, j] and not LL[t, j] and t - entry_t[j] >= cfg.settle_lag:
                    # shortcut: tick-snapping adjusted historical OHLC is approximate (adjusted prices are off-tick)
                    px = snap(TP[t, j], False)
                    gross = int(qty[j]) * px
                    proceeds = gross - cost_amount(gross, ADTV[t - 1, j], VOL[t - 1, j], cfg.cost_mult)
                    unsettled.append((t + cfg.settle_lag, proceeds))  # sales never fund buys until they clear
                    close_out(t, j, proceeds, "exit")
            for j, q in list(pend_buy.items()):
                del pend_buy[j]
                if not has[t, j] or UL[t, j]:
                    continue
                px = snap(TP[t, j], True)
                q, cost = buy_fill(q, px, ADTV[t - 1, j], VOL[t - 1, j], cfg.cost_mult, cash)
                if q <= 0:
                    continue
                cash -= cost
                qty[j], entry_t[j], entry_px[j], basis[j] = q, t, float(px), cost
                entry_atr[j], peak[j] = ATR[t - 1, j], C[t, j]

        # 2. mark to market; write off long-missing holdings
        last_px = np.where(has[t], C[t], last_px)
        missing = np.where(has[t], 0, missing + 1)
        for j in np.flatnonzero((qty > 0) & (missing >= cfg.writeoff_after)):
            close_out(t, j, Decimal(0), "writeoff")
        # equity counts sale receivables, otherwise every sale would look like a loss to the daily-loss/drawdown rules
        equity = cash + sum((a for _, a in unsettled), Decimal(0)) \
            + sum((int(qty[j]) * _D(last_px[j]) for j in np.flatnonzero(qty > 0)), Decimal(0))
        day_start, prev_equity, peak_eq = prev_equity, equity, max(peak_eq, equity)
        eq_hist[t], cash_hist[t], pos_hist[t] = float(equity), float(cash), qty  # floats are output only
        if t == T - 1:
            break

        # 3. decisions at close t
        allow = not (t > 0 and day_start > 0 and daily_loss_breached(equity, day_start))
        r = reg[t] if reg is not None else "RISK_ON"
        held = np.flatnonzero(qty > 0)
        if r == "STRESS":
            pend_sell.update(held.tolist())
        allow = allow and r in ("RISK_ON", "NEUTRAL")
        risk_mult = Decimal("0.5") if r == "NEUTRAL" else Decimal(1)

        for j in held:
            if j in pend_sell or not has[t, j]:
                continue
            peak[j] = max(peak[j], C[t, j])
            out = strat.exit(t, j, {"entry_t": entry_t[j], "entry_px": entry_px[j]})
            if strat.stop_atr:
                ref = peak[j] if strat.trail else entry_px[j]
                out |= C[t, j] <= ref - strat.stop_atr * entry_atr[j]
            if strat.target_atr:
                out |= C[t, j] >= entry_px[j] + strat.target_atr * entry_atr[j]
            out |= t - entry_t[j] >= strat.max_hold
            if out:
                pend_sell.add(j)

        if not allow:
            continue
        keep = [j for j in np.flatnonzero(qty > 0) if j not in pend_sell]
        pf = Portfolio(equity=equity, peak_equity=peak_eq, day_start_equity=equity,
                       positions={p.tickers[j]: int(qty[j]) for j in keep},
                       prices={p.tickers[j]: _D(last_px[j]) for j in keep},
                       unsettled={p.tickers[j]: int(qty[j]) for j in keep if t - entry_t[j] < cfg.settle_lag})
        names = len(keep) + len(pend_buy)
        thr = np.nanpercentile(ADTV[t][E[t]], 200 / 3) if r == "NEUTRAL" and E[t].any() else -np.inf
        for j in strat.entries(t):
            if names >= LIMITS.max_names:
                break
            if not E[t, j] or qty[j] > 0 or j in pend_buy or not ADTV[t, j] >= thr:
                continue
            want = size_position(equity * risk_mult, ATR[t, j])
            if want <= 0:
                continue
            q, _ = check_order(Order(p.tickers[j], want, snap(C[t, j], True), "BUY"), pf, ADTV[t, j], sector=p.tickers[j])
            if q > 0:
                pend_buy[j] = q
                names += 1

    idx = p.dates
    tr = pd.DataFrame(trades, columns=["ticker", "entry_date", "exit_date", "qty", "pnl", "ret", "reason",
                                       "gap_days"])
    return Result(pd.Series(eq_hist, idx), pd.Series(cash_hist, idx),
                  pd.DataFrame(pos_hist, idx, p.tickers), tr)
