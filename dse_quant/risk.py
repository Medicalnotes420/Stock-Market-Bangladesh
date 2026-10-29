"""Hard risk limits. Every order passes through RiskGate.check; no caller can override LIMITS.

Values come from docs/PHASE1_SPEC.md section 6. Change them here, in code review, never at runtime.
"""
import math
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Limits:
    max_position_pct: float = 0.10   # of portfolio equity
    max_adtv_pct: float = 0.05       # of 20-day average daily traded value
    max_sector_pct: float = 0.30
    max_names: int = 12
    max_daily_loss: float = 0.02     # blocks new entries next session
    max_drawdown: float = 0.15       # kill switch
    max_missing_frac: float = 0.05   # of universe missing today's bar
    risk_per_atr: float = 0.005      # vol-target: equity fraction risked per 1 ATR


LIMITS = Limits()


@dataclass(frozen=True)
class Order:
    ticker: str
    qty: int
    price: float
    side: str

    def __post_init__(self):
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {self.side!r}")
        if self.qty < 0 or not self.price > 0:
            raise ValueError("qty must be >= 0 and price > 0")


@dataclass
class Portfolio:
    equity: float
    peak_equity: float
    day_start_equity: float
    positions: dict = field(default_factory=dict)  # ticker -> shares
    prices: dict = field(default_factory=dict)     # ticker -> last close
    sectors: dict = field(default_factory=dict)    # ticker -> sector

    def value(self, ticker):
        return self.positions.get(ticker, 0) * self.prices.get(ticker, 0.0)


def check_order(order, pf, adtv20, sector, limits=LIMITS):
    """Return (allowed_qty, reasons). Clips, never enlarges."""
    reasons = []
    if order.side == "SELL":
        held = pf.positions.get(order.ticker, 0)
        if order.qty > held:
            reasons.append("long_only")
        return min(order.qty, held), reasons

    if not adtv20 or adtv20 <= 0:
        return 0, ["no_adtv"]
    if order.ticker not in pf.positions and len(pf.positions) >= limits.max_names:
        return 0, ["max_names"]

    caps = {
        "max_position_pct": limits.max_position_pct * pf.equity - pf.value(order.ticker),
        "max_adtv_pct": limits.max_adtv_pct * adtv20 - pf.value(order.ticker),
        "max_sector_pct": limits.max_sector_pct * pf.equity
        - sum(pf.value(t) for t, s in pf.sectors.items() if s == sector),
    }
    qty = order.qty
    for name, room in caps.items():
        allowed = max(0, math.floor(room / order.price))
        if allowed < qty:
            qty = allowed
            reasons.append(name)
    return qty, reasons


class RiskGate:
    """Decides once per day whether new entries are allowed. Exits are always allowed."""

    def __init__(self, pf, latest_bar: date, expected: date, missing_frac: float,
                 has_index: bool, limits=LIMITS):
        self.pf, self.limits, self.reasons = pf, limits, []
        drawdown = 1 - pf.equity / pf.peak_equity
        day_loss = 1 - pf.equity / pf.day_start_equity
        self.kill = drawdown >= limits.max_drawdown
        if self.kill:
            self.reasons.append("max_drawdown")
        if day_loss >= limits.max_daily_loss:
            self.reasons.append("max_daily_loss")
        if latest_bar != expected:
            self.reasons.append("stale_data")
        if missing_frac > limits.max_missing_frac:
            self.reasons.append("missing_data")
        if not has_index:
            self.reasons.append("missing_index")
        self.allow_new_entries = not self.reasons

    def check(self, order, adtv20, sector):
        if order.side == "BUY" and not self.allow_new_entries:
            return 0, ["gate_closed"] + self.reasons
        return check_order(order, self.pf, adtv20, sector, self.limits)


def size_position(equity, atr, limits=LIMITS):
    """Shares such that a 1-ATR move costs risk_per_atr of equity. Caps are applied later by check_order."""
    if not atr or not math.isfinite(atr) or atr <= 0:
        return 0
    return math.floor(limits.risk_per_atr * equity / atr)


def exit_list(pf, adtv20, limits=LIMITS):
    """Kill-switch exit list, slowest-to-exit first, at max_adtv_pct daily participation."""
    rows = []
    for t, qty in pf.positions.items():
        value = pf.value(t)
        a = adtv20.get(t)
        days = math.ceil(value / (limits.max_adtv_pct * a)) if a else None
        rows.append({"ticker": t, "qty": qty, "value": value, "days_to_exit": days})
    return sorted(rows, key=lambda r: (r["days_to_exit"] is not None, -(r["days_to_exit"] or 0)))
