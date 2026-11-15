"""Forward-outcome labels for a signal (docs/design/eod-chart-app.md 7.4). Tests and offline evaluation only:
nothing that serves charts or detects patterns may import this module (tests/test_chart_static.py checks).

A label reads only bars strictly after the signal bar. That is by construction: the caller passes
rows[i + 1:], and the signal bar and everything before it are not arguments.

Outcomes are for a long position, gross of costs, and assume the entry filled. Whether a buy on a
limit-locked open would have filled is not decided here.

Do not label windows that reach past the last accepted corporate action's reach: no action is inferred
after the Mendeley A2 set ends (2026-01-22) or in its last 10 sessions. A later bonus that stays inside the
daily limit carries no gap_flag and reads as a plain fall, which can fire a stop that never happened.
Cash dividends are not adjusted anywhere, so an ex-dividend drop is in every label as a price fall."""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from chartapp.bars import Row

_ROUNDING = Decimal("0.0002")  # two steps of the 4 dp quantize in bars.dec: one on the entry, one on the bar

@dataclass(frozen=True, slots=True)
class Outcome:
    entry: Decimal        # open of the first bar after the signal; every percentage is measured from it
    ret_pct: Decimal      # close of the last bar of the horizon against the entry
    mfe_pct: Decimal      # highest high in the horizon against the entry (most in favour)
    mae_pct: Decimal      # lowest low in the horizon against the entry (most against; zero or negative)
    # A touch is a price reaching the level, not a fill: on a gap down or a lower-lock day the loss can be
    # larger than stop_pct, or the sale may not happen at all. mae_pct bounds the loss.
    first_touch: Literal["target", "stop"] | None
    touch_bar: int | None  # index into `future` of that touch


def forward_outcome(future: Sequence[Row], horizon: int, target_pct: Decimal, stop_pct: Decimal,
                    min_hold: int = 2) -> Outcome | None:
    """Outcome over future[:horizon], where future = rows[i + 1:] for signal bar i, so future[0] is the entry
    bar, T. An EOD signal is known only after the close of bar i, hence the entry at the next open.

    Target and stop touches count from future[min_hold]: shares bought at T cannot be sold before T+2
    (T+3 for category Z; the file has no category, so the caller chooses). Bars are days the share traded:
    after a no-trade day future[2] is later than T+2, so the wait is never too short, only sometimes too long.
    A bar that touches both counts as the stop.

    None, never a partial label, when: fewer than `horizon` bars exist; a bar in the horizon carries
    gap_flag (an unadjusted bonus would read as a crash); or a price in the horizon is not positive.
    A flag on the entry bar also gives None. That one is stricter than needed, since the entry open is
    already after the jump, but a flagged bar is not one to start a label on."""
    if horizon < 1 or min_hold < 0 or target_pct <= 0 or stop_pct <= 0:
        raise ValueError(f"need horizon >= 1, min_hold >= 0 and positive target_pct and stop_pct, got "
                         f"{horizon}, {min_hold}, {target_pct}, {stop_pct}")
    window = future[:horizon]
    if len(window) < horizon or any(r.gap_flag or r.low <= 0 or r.open <= 0 for r in window):
        return None
    entry = window[0].open

    def pct(price):
        return (price / entry - 1) * 100

    # Adjusted prices are cut to 4 dp on load, so an exact touch (entry 100, high 110) can miss by a rounding
    # step once a later bonus rescales both. _ROUNDING absorbs that; ticks are far wider, so nothing else moves.
    target, stop = entry * (1 + target_pct / 100) - _ROUNDING, entry * (1 - stop_pct / 100) + _ROUNDING
    touch = bar = None
    for j in range(min_hold, horizon):
        if window[j].low <= stop:  # checked first: both in one bar counts as the stop
            touch, bar = "stop", j
        elif window[j].high >= target:
            touch, bar = "target", j
        if touch:
            break
    return Outcome(entry, pct(window[-1].close), pct(max(r.high for r in window)), pct(min(r.low for r in window)),
                   touch, bar)
