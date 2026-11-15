"""Close breaks above the most recent confirmed swing high.

Fires once per swing high: on the first bar whose close is more than `min_break_pct` percent above it.
Two separate swing highs at the same price each get their own signal.
The swing high must already be confirmed (`right` bars after it), so the break is never read off a high
that is still forming."""
from decimal import Decimal

from chartapp.geometry import pivots
from chartapp.patterns import Detection, Point

NAME = "swing_breakout"
VERSION = 1
LOOKBACK = 120
DEFAULTS = {"left": 5, "right": 5, "min_break_pct": Decimal("0.5")}


def check(cfg):
    """Config the type check cannot catch: these would fail on every bar, or never fire, without a word."""
    left, right = cfg["left"], cfg["right"]
    if not 1 <= right <= left:
        raise ValueError(f"need 1 <= right <= left, got left={left} right={right}")
    if left + right + 2 > LOOKBACK:
        raise ValueError(f"left + right must stay under {LOOKBACK - 1}: no swing high plus a later bar fits")
    if cfg["min_break_pct"] < 0:
        raise ValueError(f"min_break_pct must not be negative, got {cfg['min_break_pct']}")


def detect(bars, cfg):
    highs = [p for p in pivots(bars, cfg["left"], cfg["right"]) if p.kind == "high"]
    if not highs:
        return None
    swing = highs[-1]
    level = swing.price * (1 + cfg["min_break_pct"] / 100)  # a ratio of the price, so it scales with it
    # first close above the level since the swing high: a second crossing of the same high is not a new event
    if bars[-1].close > level and all(b.close <= level for b in bars[swing.idx + 1:-1]):
        return Detection("bullish", points=(Point(bars[swing.idx].date, swing.price, "swing_high"),),
                         levels={"breakout": level})
    return None
