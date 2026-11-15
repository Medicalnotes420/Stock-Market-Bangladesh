"""Corporate-action adjustment.

No clean corporate-action file exists in the approved data, so an action is accepted only when two signals
agree: the vendor's adjusted/raw factor makes a step that persists, and the raw price falls that day.
Cash dividends are not adjusted (see docs/PHASE3_DATA.md). Returns are therefore price-only."""
import numpy as np
import pandas as pd


def infer_actions(raw, adj, min_step=0.01, hold=10):
    """Return DataFrame[ticker, date, ratio]: date is the ex-date, ratio = pre/post price multiple (2.0 = 1:1 bonus)."""
    m = raw[["ticker", "date", "close"]].merge(
        adj[["ticker", "date", "close"]].rename(columns={"close": "close_adj"}), on=["ticker", "date"])
    m = m[(m.close > 0) & (m.close_adj > 0)].sort_values(["ticker", "date"])
    m["k"] = m.close_adj / m.close
    g = m.groupby("ticker")
    m["ratio"] = m.k / g.k.shift()
    m["ret"] = g.close.pct_change()
    # persistence: k stays within min_step of its ex-date level for the next `hold` rows
    fwd_max = g.k.transform(lambda s: s[::-1].rolling(hold + 1, min_periods=hold + 1).max()[::-1])
    fwd_min = g.k.transform(lambda s: s[::-1].rolling(hold + 1, min_periods=hold + 1).min()[::-1])
    stable = (fwd_max / m.k - 1 <= min_step) & (1 - fwd_min / m.k <= min_step)
    ok = (m.ratio > 1 + min_step) & stable & (m.ret < 0)
    return m.loc[ok, ["ticker", "date", "ratio"]].reset_index(drop=True)


def apply_actions(prices, actions):
    """Back-adjust prices (and inverse-adjust volume) so the series is continuous through each action.
    `value` and `close_raw` keep the unadjusted traded amounts. Input frame is not modified."""
    out = prices.sort_values(["ticker", "date"]).merge(actions, on=["ticker", "date"], how="left")
    inv = 1 / out.ratio.fillna(1.0)
    # factor(t) = product of 1/ratio over actions strictly after t
    after = inv.groupby(out.ticker).transform(lambda s: s[::-1].cumprod()[::-1]) / inv
    out["close_raw"] = out.close
    for c in ["open", "high", "low", "close"]:
        out[c] = out[c] * after
    out["volume"] = np.round(out.volume / after)
    out["adj_factor"] = after
    return out.drop(columns="ratio").reset_index(drop=True)
