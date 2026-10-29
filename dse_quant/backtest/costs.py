"""Per-side trading cost as a fraction of order value (docs/PHASE4_PREREG.md)."""
import math

BASE = 0.0047  # commission 0.40% + tax 0.05% + misc 0.02%: assumption until the broker's schedule arrives


# shortcut: a 10% haircut stands in for working a large order over several days; model a multi-day exit if
# results depend on exits bigger than a day's turnover
MAX_IMPACT = 0.10


def cost_rate(order_value, adtv, mult=1.0, k=0.5, floor=0.001):
    # no recent turnover is priced at the cap
    impact = k * math.sqrt(order_value / adtv) if adtv and adtv > 0 else MAX_IMPACT
    return mult * (BASE + min(MAX_IMPACT, max(floor, impact)))
