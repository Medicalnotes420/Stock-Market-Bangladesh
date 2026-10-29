"""Per-side trading cost as a fraction of order value (docs/PHASE4_PREREG.md, change 4)."""
import math

BASE = 0.0047  # commission 0.40% + tax 0.05% + misc 0.02%: assumption until the broker's schedule arrives
# shortcut: a 10% haircut stands in for working a large order over several days; model a multi-day exit if
# results depend on exits bigger than a day's turnover
MAX_IMPACT = 0.10


def cost_rate(order_value, adtv, sigma, mult=1.0, k=1.0, floor=0.001):
    """Square-root impact: k * daily volatility * sqrt(order / ADTV), floored at 0.10% (spread)."""
    if not (adtv and adtv > 0) or not math.isfinite(sigma):
        impact = MAX_IMPACT  # no recent turnover or no volatility history: priced at the cap
    else:
        impact = k * sigma * math.sqrt(order_value / adtv)
    return mult * (BASE + min(MAX_IMPACT, max(floor, impact)))
