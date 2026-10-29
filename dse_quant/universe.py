"""Point-in-time tradable universe (docs/PHASE1_SPEC.md section 4). Uses only rows dated <= asof.

Not enforced yet, because the approved data lacks it: DSE category (A/B/N/Z) history, suspension and
SME-board flags. See docs/PHASE3_DATA.md."""
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class UniverseRules:
    min_median_value: float = 2e7   # Tk 2 crore median daily traded value
    lookback: int = 60              # sessions
    min_trade_frac: float = 0.9
    min_history: int = 250          # sessions since first trade
    min_price: float = 10.0
    no_lower_lock_days: int = 3


def eligible(prices, asof, types, rules=UniverseRules()):
    """`prices` must already carry lower_lock from limits.lock_flags. Returns sorted tickers."""
    asof = pd.Timestamp(asof)
    h = prices[prices.date <= asof]
    sessions = pd.Index(sorted(h.date.unique()))
    if len(sessions) < rules.lookback:
        return []
    window = h[h.date >= sessions[-rules.lookback]]
    recent = h[h.date >= sessions[-rules.no_lower_lock_days]]
    w = window.groupby("ticker").agg(n=("date", "size"), med=("value", "median"))
    hist = h.groupby("ticker").date.size()
    # min price applies to the traded (raw) price; back-adjusted history understates it
    today = h[h.date == asof].set_index("ticker")["close_raw" if "close_raw" in h else "close"]
    locked = set(recent.loc[recent.lower_lock.fillna(False).astype(bool), "ticker"])
    ok = (w.n >= rules.min_trade_frac * rules.lookback) & (w.med >= rules.min_median_value)
    keep = [t for t in w.index[ok]
            if types.get(t) == "Equity" and hist[t] >= rules.min_history
            and today.get(t, 0) >= rules.min_price and t not in locked]
    return sorted(keep)
