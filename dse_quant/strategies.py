"""Candidate strategies (docs/PHASE1_SPEC.md section 5, deviations in docs/PHASE4_PREREG.md).

A strategy nominates tickers (entries) and flags strategy-specific exits. Stops, sizing, caps, locks and
costs belong to the engine. All signals use rolling windows and shifts only, so day t sees data <= t."""
import math
from itertools import product

import numpy as np

from dse_quant import indicators as ind


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


class Secret(Base):
    """Shared inputs for the "My Secret Series" rules (docs/SECRETS_PREREG.md), incl. the #38 dry filter."""

    def _prep(self, p):
        self.h, self.l, self.c = (x.ffill() for x in (p.high, p.low, p.close))
        self.v = p.value.fillna(0)
        self.dry = self.v.rolling(20).mean() < 0.1 * self.v.rolling(60).mean()
        self.has = p.close.notna()
        self._signal(p)

    def _score(self, sig, score):
        self.score = score.where(sig & ~self.dry & self.has).values

    def entries(self, t):
        return self._rank(self.score, t)


class RsiPullback(Secret):
    """S1 (#1, #13): RSI was 90+ within L sessions, now back to 60-72; sell after `hold`."""

    def _signal(self, p):
        self.max_hold = self.hold
        r = ind.rsi(self.c)
        self._score((r.rolling(self.L).max() >= 90) & (r >= 60) & (r <= 72), r.rolling(self.L).max())


class TurnoverSurge(Secret):
    """S7 (#7, #32): value surge with a +2..6% day after a flat 15-session base; sell after `hold`."""

    def _signal(self, p):
        self.max_hold = self.hold
        c, v = self.c, self.v
        base = c.shift(1).rolling(15).max() / c.shift(1).rolling(15).min() - 1
        ratio = v / v.shift(1).rolling(15).mean()
        ret = c / c.shift() - 1
        self._score((base <= self.rng) & (ratio >= self.mult) & (ret >= 0.02) & (ret <= 0.06), ratio)


class Squeeze(Secret):
    """S25 (#25, #30): Bollinger squeeze, tight 15-session range, MFI 50-80 and rising; sell after `hold`."""

    def _signal(self, p):
        self.max_hold = self.hold
        _, _, _, bw = ind.bollinger(self.c)
        low_bw = bw <= bw.shift(1).rolling(120, min_periods=60).quantile(self.q)
        rng = self.c.rolling(15).max() / self.c.rolling(15).min() - 1
        m = ind.mfi(self.h, self.l, self.c, self.v)
        self._score(low_bw & (rng <= self.rng) & (m >= 50) & (m <= 80) & (m > m.shift(3)), -bw)


class MfiRising(Secret):
    """S23 (#23): price flat over 10 sessions while MFI rose X points; sell after `hold`."""

    def _signal(self, p):
        self.max_hold = self.hold
        m = ind.mfi(self.h, self.l, self.c, self.v)
        dm = m - m.shift(10)
        self._score(((self.c / self.c.shift(10) - 1).abs() <= self.flat) & (dm >= self.X), dm)


class SmaCross(Secret):
    """S67 (#67, optional #96 filter); exit #3 cross-down, #21 Aroon Up < 90, or #2 MACD cross-down."""

    def _signal(self, p):
        s13, s19 = ind.sma(self.c, 13), ind.sma(self.c, 19)
        sig = (s13 > s19) & (s13.shift() <= s19.shift())
        if self.filter96:
            _, pdi, mdi = ind.adx(self.h, self.l, self.c)
            m = ind.mfi(self.h, self.l, self.c, self.v)
            sig &= (pdi > mdi) & (pdi > pdi.shift(3)) & (mdi < mdi.shift(3)) & (m > 60) & (self.c <= 1.1 * s19)
        self._score(sig, s13 / s19)
        if self.exit_rule == "cross":
            out = (s13 < s19) & (s13.shift() >= s19.shift())
        elif self.exit_rule == "aroon":
            out = ind.aroon_up(self.h) < 90
        else:
            line, signal = ind.macd(self.c)
            out = (line < signal) & (line.shift() >= signal.shift())
        self.out = out.values

    def exit(self, t, j, pos):
        return bool(self.out[t, j])


class LazyRange(Secret):
    """S98 (#98): stock stuck in a range <= R over n sessions; buy bottom 20%, sell top 20%."""

    def _signal(self, p):
        hi, lo = self.c.rolling(self.n).max(), self.c.rolling(self.n).min()
        pos = (self.c - lo) / (hi - lo)
        rng = hi / lo - 1
        self._score((rng <= self.R) & (pos <= 0.2), -rng)
        self.top = (pos >= 0.8).values

    def exit(self, t, j, pos):
        return bool(self.top[t, j])


CLASSES = {"C1": Momentum, "C2": Breakout, "C3": Reversal, "C4": LowVol,
           "S1": RsiPullback, "S7": TurnoverSurge, "S25": Squeeze, "S23": MfiRising, "S67": SmaCross,
           "S98": LazyRange}
GRIDS = {
    "C1": [dict(lookback=l, top_n=n) for l, n in product([126, 189, 252], [5, 8, 10])],
    "C2": [dict(window=w, mult=m) for w, m in product([40, 60, 90], [1.5, 2.0, 3.0])],
    "C3": [dict(drop=d, hold=h) for d, h in product([-0.08, -0.10, -0.12], [5, 7, 10])],
    "C4": [dict(window=w, top_n=n) for w, n in product([120, 250], [8, 10, 12])],
    # docs/SECRETS_PREREG.md
    "S1": [dict(L=L, hold=h) for L, h in product([5, 10, 15], [2, 3, 5])],
    "S7": [dict(mult=m, rng=r, hold=h) for m, r, h in product([2, 3], [0.05, 0.08], [3, 5])],
    "S25": [dict(q=q, rng=r, hold=h) for q, r, h in product([0.1, 0.2], [0.03, 0.05], [6, 7])],
    "S23": [dict(X=x, flat=f, hold=h) for x, f, h in product([10, 20], [0.02, 0.04], [6, 7])],
    "S67": [dict(filter96=f, exit_rule=e) for f, e in product([False, True], ["cross", "aroon", "macd"])],
    "S98": [dict(R=r, n=n) for r, n in product([0.12, 0.15, 0.20], [120, 250])],
}
PHASE4 = ["C1", "C2", "C3", "C4"]
SECRETS = ["S1", "S7", "S25", "S23", "S67", "S98"]


def make(name, params):
    return CLASSES[name](**params)
