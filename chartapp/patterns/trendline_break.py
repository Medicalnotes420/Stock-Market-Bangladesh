"""Close breaks the trendline through the last two zigzag pivots of one kind.

Bullish: the last two confirmed zigzag highs fall, and the close goes more than `min_break_pct` percent
above the line through them (a falling resistance line gives way). Bearish: the last two confirmed lows
rise, and the close goes that far below their line (a rising support line gives way).

Fires once per pair of pivots: on the first bar since the second pivot whose close is beyond their line.
A line that was already broken by the time its second pivot was confirmed never fires. Both pivots are
confirmed zigzag pivots, so the line is never drawn through a high or low that is still forming.
A later pivot that lands exactly on a broken line makes a new pair, and that pair can fire: price came
back, the line held once more, then gave way again.
If both lines break on one bar (past the point of a triangle), the bullish one is reported."""
from decimal import Decimal

from chartapp.geometry import crossed, line_through, value_at, zigzag
from chartapp.patterns import Detection, Point, Segment

NAME = "trendline_break"
VERSION = 1
# Two swings of one kind, with the move into the first, must fit: at 5% the index often needs most of a year.
# A longer window also costs signals, because the runner drops any window that holds a gap-flagged bar.
LOOKBACK = 250
DEFAULTS = {"reversal_pct": Decimal("5.0"), "min_break_pct": Decimal("0.5")}

_SIDES = (("high", "above", "bullish", "resistance"), ("low", "below", "bearish", "support"))
_PLACES = Decimal("0.0001")  # bars.py keeps prices to 4 places; the drawn end of the line gets the same


def check(cfg):
    """Config the type check cannot catch."""
    if cfg["reversal_pct"] <= 0:
        raise ValueError(f"reversal_pct must be positive, got {cfg['reversal_pct']}")
    # at 100 the lower edge of a line is zero, so no close could ever be below it
    if not 0 <= cfg["min_break_pct"] < 100:
        raise ValueError(f"min_break_pct must be at least 0 and under 100, got {cfg['min_break_pct']}")


def detect(bars, cfg):
    swings, last, tol = zigzag(bars, cfg["reversal_pct"]), len(bars) - 1, cfg["min_break_pct"]
    for kind, side, direction, role in _SIDES:
        two = [p for p in swings if p.kind == kind][-2:]
        if len(two) < 2:
            continue
        a, b = two
        # resistance must fall and support must rise; a flat line is a level, which swing_breakout covers
        if not (b.price < a.price if kind == "high" else b.price > a.price):
            continue
        # crossed() says "no" next to a non-positive close, which would hide an earlier break from the check below
        if any(x.close <= 0 for x in bars[b.idx:]):
            continue
        line = line_through(a, b)
        # first close beyond the line since its second pivot: a later crossing by the same pair is not a new event
        if crossed(line, bars, last, side, tol) and not any(crossed(line, bars, i, side, tol)
                                                            for i in range(b.idx + 1, last)):
            start = Point(bars[a.idx].date, a.price, role)
            # the line's price on the signal bar, cut to 4 places so it prints as a plain decimal
            end = Point(bars[last].date, value_at(line, last).quantize(_PLACES), role)
            return Detection(direction, segments=(Segment(start, end, role),),
                             points=(Point(bars[a.idx].date, a.price, f"{kind}_1"),
                                     Point(bars[b.idx].date, b.price, f"{kind}_2")))
    return None
