"""Shared shape utilities for pattern plugins (docs/design/eod-chart-app.md 6). Decimal only.
Positions are bar indices into the sequence given, not dates: DSE weekends, holidays and no-trade days
would bend anything measured in calendar days."""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from chartapp.bars import Bar


@dataclass(frozen=True, slots=True)
class Pivot:
    idx: int             # the bar that is the high or low
    confirmed_idx: int   # the first bar at which this pivot is knowable
    kind: Literal["high", "low"]
    price: Decimal


def pivots(bars: Sequence[Bar], left: int, right: int) -> list[Pivot]:
    """Fractal swing points, oldest first. A swing high is above the highs of the `left` bars before it and
    not below the highs of the `right` bars after it (lows mirrored), so of equal highs the earliest wins.

    A pivot needs `right` later bars to exist, so it is only returned once bar idx + right is in `bars`:
    calling this on a prefix can never return a pivot that the prefix could not have known."""
    # left >= right: with a shorter look-back, two equal highs between `left` and `right` bars apart would
    # both be pivots, and "the earliest wins" would be false
    if not 1 <= right <= left:
        raise ValueError(f"need 1 <= right <= left, got left={left} right={right}")
    out = []
    for i in range(left, len(bars) - right):
        before, after, b = bars[i - left:i], bars[i + 1:i + 1 + right], bars[i]
        # price > 0: the file has a bar with low 0.0 (MONNOCERA 2018-09-20); callers divide by pivot prices
        if b.high > 0 and all(b.high > x.high for x in before) and all(b.high >= x.high for x in after):
            out.append(Pivot(i, i + right, "high", b.high))
        if b.low > 0 and all(b.low < x.low for x in before) and all(b.low <= x.low for x in after):
            out.append(Pivot(i, i + right, "low", b.low))
    return out
