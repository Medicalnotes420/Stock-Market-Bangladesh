"""Shared shape utilities for pattern plugins (docs/design/eod-chart-app.md 6). Decimal only.
Positions are bar indices into the sequence given, not dates: DSE weekends, holidays and no-trade days
would bend anything measured in calendar days."""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
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


def _reversal(values, p: Decimal, g: Decimal, high: bool, ties: bool):
    """Index of the first value a full reversal (ratio g) away from p. None if a value beyond p comes first
    (or one equal to it, when ties is False), or a non-positive one, or the values run out."""
    for i, v in values:
        if v <= 0:
            return None
        lo, hi = (v, p) if high else (p, v)
        if lo < hi and lo * g <= hi:  # lo < hi: a ratio so small that it rounds to 1 must not make equals a reversal
            return i
        if hi < lo or (hi == lo and not ties):
            return None
    return None


def zigzag(bars: Sequence[Bar], reversal_pct: Decimal) -> list[Pivot]:
    """Swing points of the closes, oldest first, alternating high and low, each leg at least reversal_pct
    measured from its low end (high >= low * (1 + reversal_pct / 100), for rises and falls alike).

    A close is a high when, going forward, a close a full reversal below it comes before any higher close,
    and going back, a close a full reversal below it comes before any close as high or higher (lows
    mirrored; of equal closes the earliest is the pivot). confirmed_idx is that forward bar.

    This is a rule about the bars around the pivot, not a scan from the first bar, so it has the same
    property as pivots(): a prefix returns exactly the pivots confirmed inside it, and a sliding window
    returns the full-series pivots minus those whose backward reversal lies left of the window. The
    window's edges are never taken as evidence, so the first and the unfinished last leg are not returned.
    A non-positive close is never a pivot and never evidence. Across one, neither promise holds: two highs
    can follow each other, and a high and a low either side of it can be any distance apart."""
    if reversal_pct <= 0:
        raise ValueError(f"reversal_pct must be positive, got {reversal_pct}")
    g = 1 + reversal_pct / 100
    closes = [b.close for b in bars]
    out = []
    for j in range(1, len(closes) - 1):
        p, prev, nxt = closes[j], closes[j - 1], closes[j + 1]
        # the two neighbours settle most bars: a high is above the close before it and not below the one after
        # (so no bar is both a high and a low). Only the survivors pay for the two scans.
        high = prev < p
        if p <= 0 or prev == p or (nxt > p if high else nxt < p):
            continue
        confirmed = _reversal(((i, closes[i]) for i in range(j + 1, len(closes))), p, g, high, ties=True)
        before = ((i, closes[i]) for i in range(j - 1, -1, -1))
        if confirmed is not None and _reversal(before, p, g, high, ties=False) is not None:
            out.append(Pivot(j, confirmed, "high" if high else "low", p))
    return out


@dataclass(frozen=True, slots=True)
class Line:
    x0: int
    y0: Decimal
    slope: Decimal  # price per bar


# Slopes are kept to more digits than a value is rounded to, so a line through (0, 100) and (3, 101) gives
# exactly 102 at bar 6, not 101.99...98: a close sitting on a line must not look like a cross, and the
# answer must not depend on the price scale.
_WIDE = 40


def line_through(a: Pivot, b: Pivot) -> Line:
    if a.idx == b.idx:
        raise ValueError(f"two points on the same bar ({a.idx}) do not make a line")
    with localcontext(prec=_WIDE):
        return Line(a.idx, a.price, (b.price - a.price) / (b.idx - a.idx))


def value_at(line: Line, idx: int) -> Decimal:
    with localcontext(prec=_WIDE):
        y = line.y0 + line.slope * (idx - line.x0)
    return +y  # rounds to the normal 28 digits


def fit(points: Sequence[Pivot]) -> Line:
    """Least-squares line through the points' (idx, price). x is measured from the first point, so the
    line does not depend on where the window starts."""
    x0 = points[0].idx if points else 0
    xs, ys, n = [p.idx - x0 for p in points], [p.price for p in points], len(points)
    with localcontext(prec=_WIDE):
        sx, sy, sxx, sxy = sum(xs), sum(ys), sum(x * x for x in xs), sum(x * y for x, y in zip(xs, ys))
        den = n * sxx - sx * sx
        if den == 0:
            raise ValueError("a fit needs points on at least two different bars")
        return Line(x0, (sy * sxx - sx * sxy) / den, (n * sxy - sx * sy) / den)


def _edges(line: Line, idx: int, tol_pct: Decimal):
    """The line's price at idx less and plus tol_pct percent of it. None where the line is not positive:
    a percentage of a zero or negative price means nothing."""
    if tol_pct < 0:
        raise ValueError(f"tol_pct must not be negative, got {tol_pct}")
    with localcontext(prec=_WIDE):  # from the unrounded line value: the edge can be a short decimal when it is not
        v = line.y0 + line.slope * (idx - line.x0)
        low, high = v * (1 - tol_pct / 100), v * (1 + tol_pct / 100)
    return (+low, +high) if v > 0 else None


def touches(line: Line, pivots: Sequence[Pivot], tol_pct: Decimal) -> list[Pivot]:
    """The pivots whose price is within tol_pct percent of the line's price at their bar."""
    out = []
    for p in pivots:
        edges = _edges(line, p.idx, tol_pct)
        if edges and edges[0] <= p.price <= edges[1]:
            out.append(p)
    return out


def crossed(line: Line, bars: Sequence[Bar], idx: int, side: Literal["above", "below"], tol_pct: Decimal) -> bool:
    """The close at idx is beyond the line by more than tol_pct percent of the line's price there, and the
    close at idx - 1 was not. Reads bars[idx - 1] and bars[idx] only. False at idx 0 (no bar before it) and
    wherever a close or the line is not positive."""
    if side not in ("above", "below"):
        raise ValueError(f"side must be 'above' or 'below', got {side!r}")
    if not 0 <= idx < len(bars):
        raise IndexError(f"bar {idx} is not in a sequence of {len(bars)}")

    def beyond(i):
        edges, close = _edges(line, i, tol_pct), bars[i].close
        if edges is None or close <= 0:
            return None
        return close > edges[1] if side == "above" else close < edges[0]

    return idx > 0 and beyond(idx) is True and beyond(idx - 1) is False
