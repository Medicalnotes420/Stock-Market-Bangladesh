"""Per-side trading cost as a fraction of order value (docs/PHASE4_PREREG.md)."""
import math

BASE = 0.0047  # commission 0.40% + tax 0.05% + misc 0.02%: assumption until the broker's schedule arrives


def cost_rate(order_value, adtv, mult=1.0, k=0.5, floor=0.001):
    # unknown liquidity is priced as if the order were a full day's turnover
    impact = k * math.sqrt(order_value / adtv) if adtv and adtv > 0 else k
    return mult * (BASE + max(floor, impact))
