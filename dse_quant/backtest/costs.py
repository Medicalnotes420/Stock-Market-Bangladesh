"""Per-side trading cost as a fraction of order value (docs/PHASE4_PREREG.md, change 4)."""
import math
from decimal import ROUND_CEILING, Decimal

from async_risk_guard import DSE_COMMISSION_RATE

# shortcut: a 10% haircut stands in for working a large order over several days; model a multi-day exit if
# results depend on exits bigger than a day's turnover
MAX_IMPACT = Decimal("0.10")


def cost_rate(order_value, adtv, sigma, mult=1.0, k=1.0, floor=Decimal("0.001")):
    """Square-root impact: k * daily volatility * sqrt(order / ADTV), floored at 0.10% (spread). Returns an
    unquantized Decimal; callers round the Tk amount. cost_mult scales the commission too (stress-test knob)."""
    mult, k, floor = (x if isinstance(x, Decimal) else Decimal(str(x)) for x in (mult, k, floor))
    if not (adtv and adtv > 0) or not math.isfinite(sigma):
        impact = MAX_IMPACT  # no recent turnover or no volatility history: priced at the cap
    else:
        impact = k * Decimal(str(float(sigma) * math.sqrt(float(order_value) / float(adtv))))
    return mult * (DSE_COMMISSION_RATE + min(MAX_IMPACT, max(floor, impact)))


def cost_amount(gross, adtv, sigma, mult=1.0):
    """Tk cost of one side, rounded up to the paisa like async_risk_guard (buy total = gross + cost, sell net =
    gross - cost). The rate itself is never quantized."""
    return (gross * cost_rate(gross, adtv, sigma, mult)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def buy_fill(q, px, adtv, sigma, mult, cash):
    """Largest quantity <= q whose total (gross + rounded cost) fits in settled cash, and that total.
    (0, 0) if none fits; raises rather than ever return a total above cash."""
    total = lambda n: n * px + cost_amount(n * px, adtv, sigma, mult)
    q = min(q, math.floor(cash / (px * (1 + cost_rate(q * px, adtv, sigma, mult)))))
    while q > 0 and total(q) > cash:  # the rounded-up cost can still tip it over
        q -= 1
    if q <= 0:
        return 0, Decimal(0)
    if total(q) > cash:
        raise RuntimeError(f"buy total {total(q)} exceeds settled cash {cash}")
    return q, total(q)
