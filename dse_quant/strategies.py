"""Candidate strategies (docs/PHASE1_SPEC.md section 5, deviations in docs/PHASE4_PREREG.md).

A strategy nominates tickers (entries) and flags strategy-specific exits. Stops, sizing, caps, locks and
costs belong to the engine. All signals use rolling windows and shifts only, so day t sees data <= t."""
import math
from itertools import product

import numpy as np


class Base:
    stop_atr, trail, target_atr, max_hold, rebalance = None, False, None, 10 ** 9, None

    def __init__(self, **params):
        self.params = params
        for k, v in params.items():
            setattr(self, k, v)

    def prepare(self, p, elig=None):
        self.elig = (elig if elig is not None else p.close.notna()).values
        self._prep(p)

    def _rank(self, score, t, ascending=False):
        s = score[t]
        ok = np.flatnonzero(self.elig[t] & np.isfinite(s))
        return ok[np.argsort(s[ok] if ascending else -s[ok], kind="stable")].tolist()

    def is_reb(self, t):
        return t % self.rebalance == 0

    def exit(self, t, j, pos):
        return False


class Momentum(Base):
    """C1: 6-12 month return skipping the last month; monthly top_n; exit when it leaves the top 30%."""
    stop_atr, trail, rebalance, skip = 2.5, True, 21, 21

    def _prep(self, p):
        c = p.close.ffill()
        self.score = (c.shift(self.skip) / c.shift(self.lookback) - 1).values

    def entries(self, t):
        return self._rank(self.score, t)[:self.top_n] if self.is_reb(t) else []

    def exit(self, t, j, pos):
        if not self.is_reb(t):
            return False
        ranked = self._rank(self.score, t)
        return j not in ranked[:max(self.top_n, math.ceil(0.3 * len(ranked)))]


class Breakout(Base):
    """C2: close above the prior `window`-day high on traded value >= mult x its average."""
    stop_atr, max_hold = 2.0, 30

    def _prep(self, p):
        hh = p.high.shift(1).rolling(self.window, min_periods=self.window).max()
        vavg = p.value.shift(1).rolling(self.window, min_periods=self.window // 2).mean()
        surge = p.value / vavg
        sig = (p.close > hh) & (surge >= self.mult) & ~p.upper_lock
        self.score = surge.where(sig).values
        self.low20 = p.low.shift(1).rolling(20, min_periods=15).min().values
        self.close = p.close.values

    def entries(self, t):
        return self._rank(self.score, t)

    def exit(self, t, j, pos):
        return self.close[t, j] < self.low20[t, j]


class Reversal(Base):
    """C3: 5-day drop <= `drop` and <= -2 sigma of the stock's own 5-day returns; short hold."""
    stop_atr, target_atr = 1.5, 1.0

    def _prep(self, p):
        self.max_hold = self.hold
        c = p.close.ffill()
        r5 = c / c.shift(5) - 1
        z = (r5 - r5.rolling(250, min_periods=120).mean()) / r5.rolling(250, min_periods=120).std()
        sig = (r5 <= self.drop) & (z <= -2) & ~p.lower_lock & p.close.notna()
        self.score = z.where(sig).values

    def entries(self, t):
        return self._rank(self.score, t, ascending=True)


class LowVol(Base):
    """C4 (modified, no dividend data): quarterly, hold the top_n lowest-volatility eligible stocks."""
    rebalance = 63

    def _prep(self, p):
        r = p.close.ffill().pct_change(fill_method=None)
        self.score = r.rolling(self.window, min_periods=int(self.window * 0.8)).std().values

    def entries(self, t):
        return self._rank(self.score, t, ascending=True)[:self.top_n] if self.is_reb(t) else []

    def exit(self, t, j, pos):
        return self.is_reb(t) and j not in self._rank(self.score, t, ascending=True)[:2 * self.top_n]


CLASSES = {"C1": Momentum, "C2": Breakout, "C3": Reversal, "C4": LowVol}
GRIDS = {
    "C1": [dict(lookback=l, top_n=n) for l, n in product([126, 189, 252], [5, 8, 10])],
    "C2": [dict(window=w, mult=m) for w, m in product([40, 60, 90], [1.5, 2.0, 3.0])],
    "C3": [dict(drop=d, hold=h) for d, h in product([-0.08, -0.10, -0.12], [5, 7, 10])],
    "C4": [dict(window=w, top_n=n) for w, n in product([120, 250], [8, 10, 12])],
}


def make(name, params):
    return CLASSES[name](**params)
