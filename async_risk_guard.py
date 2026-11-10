"""
async_risk_guard.py
Asynchronous, concurrency-safe risk-management and DSE settlement state engine.
Enforces:
  - 0.30% DSE commission + 0.10 BDT tick ceiling
  - T+2 (Category A/B/G/N) and T+3 (Category Z) settlement maturation queues
  - Atomic cash & matured-share reservation with automatic exception rollback
  - Max position size & max portfolio drawdown circuit breakers
  - Monotonic exchange timestamp watermarks & execution latency gates
"""

from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

DSE_COMMISSION_RATE = Decimal("0.0030")  # 0.30% DSE commission
DSE_TICK_SIZE = Decimal("0.10")          # 0.10 BDT tick increment
MIN_NETWORK_LATENCY_MS = 15              # shared default; the harness imports this


def _require_decimal(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value}")
    return value


def _require_int(name: str, value: object, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an int >= {minimum}, got {value!r}")
    return value


def _require_qty(qty: object) -> int:
    return _require_int("qty", qty, 1)


class ShareCategory(str, Enum):
    A = "A"  # T+2 settlement
    B = "B"  # T+2 settlement
    G = "G"  # T+2 settlement
    N = "N"  # T+2 settlement
    Z = "Z"  # T+3 settlement, no netting


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class RiskViolationError(RuntimeError):
    """Base exception for risk guard rejections."""


class InsufficientSettledCashError(RiskViolationError):
    """Raised when settled cash cannot cover gross cost + 0.30% commission + slippage."""


class PositionLimitExceededError(RiskViolationError):
    """Raised when an order breaches maximum single-ticker exposure."""


class MaxDrawdownCircuitBreakerError(RiskViolationError):
    """Raised when portfolio equity drops below the maximum allowed drawdown."""


class SettlementViolationError(RiskViolationError):
    """Raised on T+2/T+3 short-sale bans or premature unsettled share liquidation."""


class TemporalLeakageError(RiskViolationError):
    """Raised on out-of-order WebSocket ticks or zero-latency look-ahead fills."""


class CircuitBreakerLiquidityError(RiskViolationError):
    """Raised when price is pinned at DSE daily circuit limits or L1 volume is zero."""


@dataclass(frozen=True)
class MarketTick:
    symbol: str
    category: ShareCategory
    exchange_ts_ms: int
    bid: Decimal
    ask: Decimal
    ask_volume: int = 1_000
    bid_volume: int = 1_000
    upper_circuit: Decimal = Decimal("999999.00")
    lower_circuit: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        # Unknown categories raise ValueError here rather than silently becoming T+2
        object.__setattr__(self, "category", ShareCategory(self.category))
        _require_int("exchange_ts_ms", self.exchange_ts_ms, 0)
        _require_int("ask_volume", self.ask_volume, 0)
        _require_int("bid_volume", self.bid_volume, 0)
        for name in ("bid", "ask", "upper_circuit", "lower_circuit"):
            _require_decimal(name, getattr(self, name))
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("bid and ask must be positive")
        if self.bid > self.ask:
            raise ValueError("crossed book: bid > ask")


@dataclass
class SettlementLot:
    symbol: str
    qty: int
    clears_at_day: int


@dataclass
class CashReceivable:
    amount: Decimal
    category: ShareCategory
    clears_at_day: int


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    exchange_ts_ms: int
    symbol: str
    side: str
    qty: int
    exec_price: str
    commission_bdt: str
    settled_cash_after_bdt: str
    reason: str = "OK"


class AsyncPortfolioState:
    """
    Concurrency-safe portfolio state protected by an asyncio.Lock.
    Supports both decorator-driven atomic cash reservations (with automatic rollback)
    and full DSE T+2/T+3 tick execution.
    """

    def __init__(
        self,
        initial_cash: Decimal,
        max_position_pct: Decimal = Decimal("0.25"),
        max_drawdown_pct: Decimal = Decimal("0.10"),
        commission_rate: Decimal = DSE_COMMISSION_RATE,
        current_trading_day: int = 1,
        audit_queue: Optional[asyncio.Queue[Optional[AuditEvent]]] = None,
    ) -> None:
        self._lock = asyncio.Lock()
        _require_decimal("initial_cash", initial_cash)
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.initial_equity: Decimal = initial_cash
        self.settled_cash: Decimal = initial_cash
        self.reserved_cash: Decimal = Decimal("0.00")
        self.max_position_pct: Decimal = _require_decimal("max_position_pct", max_position_pct)
        self.max_drawdown_pct: Decimal = _require_decimal("max_drawdown_pct", max_drawdown_pct)
        self.commission_rate: Decimal = _require_decimal("commission_rate", commission_rate)
        if not (Decimal("0") < self.max_position_pct <= Decimal("1")):
            raise ValueError("max_position_pct must be in (0, 1]")
        if not (Decimal("0") < self.max_drawdown_pct <= Decimal("1")):
            raise ValueError("max_drawdown_pct must be in (0, 1]")
        if self.commission_rate < 0:
            raise ValueError("commission_rate must be >= 0")

        self.current_day: int = _require_int("current_trading_day", current_trading_day, 1)
        self.last_exchange_ts_ms: int = 0

        self.matured_positions: Dict[str, int] = {}
        self.unsettled_share_lots: List[SettlementLot] = []
        self.unsettled_cash: List[CashReceivable] = []
        self.last_prices: Dict[str, Decimal] = {}
        # Quantity reserved by decorator orders still awaiting the broker; counts toward exposure
        self.pending_qty: Dict[str, int] = {}
        self.audit_queue = audit_queue

    @property
    def available_cash(self) -> Decimal:
        return self.settled_cash

    @staticmethod
    def round_to_dse_tick(price: Decimal) -> Decimal:
        """Rounds up to the nearest 0.10 BDT tick for conservative buy reservation."""
        return (price / DSE_TICK_SIZE).to_integral_value(rounding=ROUND_CEILING) * DSE_TICK_SIZE

    def calculate_buy_cost(
        self, ask_price: Decimal, qty: int, slippage_bps: Decimal = Decimal("0")
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Returns (exec_price, commission, total_cost_with_commission)."""
        slipped = ask_price * (Decimal("1") + slippage_bps / Decimal("10000"))
        exec_price = self.round_to_dse_tick(slipped)
        gross = exec_price * Decimal(qty)
        commission = (gross * self.commission_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return exec_price, commission, gross + commission

    def total_equity_unlocked(self, price_overrides: Optional[Dict[str, Decimal]] = None) -> Decimal:
        """Mark-to-market equity. Overrides let a pre-trade check mark a price without committing it."""
        prices = {**self.last_prices, **(price_overrides or {})}
        receivables = sum((r.amount for r in self.unsettled_cash), Decimal("0.00"))
        inventory = Decimal("0.00")
        for sym, qty in self.matured_positions.items():
            inventory += prices.get(sym, Decimal("0.00")) * Decimal(qty)
        for lot in self.unsettled_share_lots:
            inventory += prices.get(lot.symbol, Decimal("0.00")) * Decimal(lot.qty)
        return self.settled_cash + self.reserved_cash + receivables + inventory

    def _emit_audit_unlocked(self, event: AuditEvent) -> None:
        if self.audit_queue is not None:
            try:
                self.audit_queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # known gap: dropped audit row (see audit F10)

    async def ingest_tick_and_buy(
        self,
        tick: MarketTick,
        qty: int,
        signal_generated_ts_ms: int,
        min_network_latency_ms: int = MIN_NETWORK_LATENCY_MS,
    ) -> Decimal:
        """Executes a DSE buy order under full temporal, slippage, and T+2/T+3 guards."""
        _require_qty(qty)
        _require_int("signal_generated_ts_ms", signal_generated_ts_ms, 0)
        _require_int("min_network_latency_ms", min_network_latency_ms, 1)
        async with self._lock:
            if tick.exchange_ts_ms < self.last_exchange_ts_ms:
                raise TemporalLeakageError(
                    f"Out-of-order tick: {tick.exchange_ts_ms} < watermark {self.last_exchange_ts_ms}"
                )
            # The tick is ordered, so it is valid market data whatever happens to this order.
            # Commit watermark and mark now, so a rejected or latency-blocked tick still
            # blocks older ticks and marks the book (see audit N1, F2, F4).
            self.last_exchange_ts_ms = tick.exchange_ts_ms
            self.last_prices[tick.symbol] = tick.bid  # conservative mark for longs

            if tick.exchange_ts_ms < signal_generated_ts_ms + min_network_latency_ms:
                raise TemporalLeakageError(
                    f"Look-ahead fill rejected: tick_ts={tick.exchange_ts_ms} "
                    f"< signal_ts ({signal_generated_ts_ms}) + latency ({min_network_latency_ms})"
                )

            if tick.ask >= tick.upper_circuit or tick.ask_volume <= 0:
                raise CircuitBreakerLiquidityError(
                    f"{tick.symbol} locked at upper circuit ({tick.upper_circuit}) or zero ask depth."
                )

            equity = self.total_equity_unlocked()
            drawdown = (self.initial_equity - equity) / self.initial_equity
            if drawdown >= self.max_drawdown_pct:
                raise MaxDrawdownCircuitBreakerError(
                    f"Portfolio drawdown {drawdown:.2%} >= limit {self.max_drawdown_pct:.2%}"
                )

            slippage_bps = Decimal("0") if qty <= tick.ask_volume else Decimal("25")
            exec_price, commission, required_cash = self.calculate_buy_cost(
                tick.ask, qty, slippage_bps=slippage_bps
            )

            if required_cash > self.settled_cash:
                raise SettlementViolationError(
                    f"Insufficient settled cash: need {required_cash}, have {self.settled_cash}"
                )

            existing_qty = (
                self.matured_positions.get(tick.symbol, 0)
                + self.pending_qty.get(tick.symbol, 0)
                + sum(lot.qty for lot in self.unsettled_share_lots if lot.symbol == tick.symbol)
            )
            new_exposure = (Decimal(existing_qty + qty) * exec_price) / equity
            if new_exposure > self.max_position_pct:
                raise PositionLimitExceededError(
                    f"Position exposure {new_exposure:.2%} exceeds max {self.max_position_pct:.2%}"
                )

            # All checks passed: commit the fill
            self.settled_cash -= required_cash
            lag = 3 if tick.category == ShareCategory.Z else 2
            self.unsettled_share_lots.append(
                SettlementLot(
                    symbol=tick.symbol,
                    qty=qty,
                    clears_at_day=self.current_day + lag,
                )
            )
            self._emit_audit_unlocked(
                AuditEvent(
                    event_type="ORDER_FILLED",
                    exchange_ts_ms=tick.exchange_ts_ms,
                    symbol=tick.symbol,
                    side=OrderSide.BUY.value,
                    qty=qty,
                    exec_price=str(exec_price),
                    commission_bdt=str(commission),
                    settled_cash_after_bdt=str(self.settled_cash),
                    reason=f"T+{lag}_LOT_CREATED",
                )
            )
            return required_cash

    async def sell_matured_shares(
        self,
        tick: MarketTick,
        qty: int,
        signal_generated_ts_ms: int,
        min_network_latency_ms: int = MIN_NETWORK_LATENCY_MS,
    ) -> Decimal:
        """Executes a DSE sell order strictly against matured T+2/T+3 shares."""
        _require_qty(qty)
        _require_int("signal_generated_ts_ms", signal_generated_ts_ms, 0)
        _require_int("min_network_latency_ms", min_network_latency_ms, 1)
        async with self._lock:
            if tick.exchange_ts_ms < self.last_exchange_ts_ms:
                raise TemporalLeakageError("Out-of-order tick on sell execution.")
            # Ordered tick: commit watermark and mark (see the buy path)
            self.last_exchange_ts_ms = tick.exchange_ts_ms
            self.last_prices[tick.symbol] = tick.bid

            if tick.exchange_ts_ms < signal_generated_ts_ms + min_network_latency_ms:
                raise TemporalLeakageError(
                    f"Look-ahead sell rejected: tick_ts={tick.exchange_ts_ms} "
                    f"< signal_ts ({signal_generated_ts_ms}) + latency ({min_network_latency_ms})"
                )

            if tick.bid <= tick.lower_circuit or tick.bid_volume <= 0:
                raise CircuitBreakerLiquidityError(
                    f"{tick.symbol} locked at lower circuit ({tick.lower_circuit})."
                )

            available = self.matured_positions.get(tick.symbol, 0)
            if qty > available:
                raise SettlementViolationError(
                    f"T+2/T+3 Short-Sale Ban: Attempted to sell {qty} of {tick.symbol}, "
                    f"but only {available} matured shares exist."
                )

            # Compute every amount before mutating anything
            gross = tick.bid * Decimal(qty)
            commission = (gross * self.commission_rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            net_proceeds = gross - commission

            # All checks passed: commit the fill
            self.matured_positions[tick.symbol] = available - qty
            lag = 3 if tick.category == ShareCategory.Z else 2
            self.unsettled_cash.append(
                CashReceivable(
                    amount=net_proceeds,
                    category=tick.category,
                    clears_at_day=self.current_day + lag,
                )
            )
            self._emit_audit_unlocked(
                AuditEvent(
                    event_type="ORDER_FILLED",
                    exchange_ts_ms=tick.exchange_ts_ms,
                    symbol=tick.symbol,
                    side=OrderSide.SELL.value,
                    qty=qty,
                    exec_price=str(tick.bid),
                    commission_bdt=str(commission),
                    settled_cash_after_bdt=str(self.settled_cash),
                    reason=f"T+{lag}_RECEIVABLE_QUEUED",
                )
            )
            return net_proceeds

    async def advance_trading_day(self, days: int = 1) -> None:
        """Rolls the DSE settlement calendar forward and matures eligible lots and cash."""
        _require_int("days", days, 1)
        async with self._lock:
            self.current_day += days
            remaining_lots: List[SettlementLot] = []
            for lot in self.unsettled_share_lots:
                if lot.clears_at_day <= self.current_day:
                    self.matured_positions[lot.symbol] = (
                        self.matured_positions.get(lot.symbol, 0) + lot.qty
                    )
                else:
                    remaining_lots.append(lot)
            self.unsettled_share_lots = remaining_lots

            remaining_cash: List[CashReceivable] = []
            for rec in self.unsettled_cash:
                if rec.clears_at_day <= self.current_day:
                    self.settled_cash += rec.amount
                else:
                    remaining_cash.append(rec)
            self.unsettled_cash = remaining_cash


def async_risk_guard(
    portfolio: AsyncPortfolioState,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """
    Decorator that atomically validates drawdown, position limits, and reserves
    settled cash (including 0.30% DSE commission + 0.10 BDT tick rounding) BEFORE
    executing an async broker order coroutine, rolling back automatically on failure.

    Note: this path takes no tick, so it has no watermark, latency or L1-depth checks.
    It is a second buy path; do not expose it to live flow without adding them.
    """
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def wrapper(
            symbol: str,
            qty: int,
            price: Decimal,
            *args: Any,
            category: ShareCategory,  # required: a silent default would mis-settle Z lots as T+2
            **kwargs: Any,
        ) -> Any:
            _require_qty(qty)
            _require_decimal("price", price)
            if price <= 0:
                raise ValueError("price must be positive")
            category = ShareCategory(category)  # unknown values raise ValueError
            lag = 3 if category == ShareCategory.Z else 2

            # Step 1: Atomic Pre-Trade Risk Check & Cash Reservation
            async with portfolio._lock:
                equity = portfolio.total_equity_unlocked({symbol: price})  # override only, not committed
                drawdown = (portfolio.initial_equity - equity) / portfolio.initial_equity
                if drawdown >= portfolio.max_drawdown_pct:
                    raise MaxDrawdownCircuitBreakerError(
                        f"Drawdown {drawdown:.2%} breached limit {portfolio.max_drawdown_pct:.2%}"
                    )

                exec_price, _, total_cost = portfolio.calculate_buy_cost(price, qty)
                if total_cost > portfolio.settled_cash:
                    raise InsufficientSettledCashError(
                        f"Need {total_cost} BDT (incl. 0.30% fee), available: {portfolio.settled_cash} BDT"
                    )

                existing_qty = (
                    portfolio.matured_positions.get(symbol, 0)
                    + portfolio.pending_qty.get(symbol, 0)
                    + sum(lot.qty for lot in portfolio.unsettled_share_lots if lot.symbol == symbol)
                )
                exposure = (Decimal(existing_qty + qty) * exec_price) / equity
                if exposure > portfolio.max_position_pct:
                    raise PositionLimitExceededError(
                        f"Exposure {exposure:.2%} exceeds limit {portfolio.max_position_pct:.2%}"
                    )

                # Reserve cash before awaiting broker I/O
                portfolio.settled_cash -= total_cost
                portfolio.reserved_cash += total_cost
                portfolio.pending_qty[symbol] = portfolio.pending_qty.get(symbol, 0) + qty
                clears_at_day = portfolio.current_day + lag  # fixed at order time

            # Finalisation is synchronous: it mutates state with no await, so it cannot be
            # interrupted by cancellation and cannot leave reserved cash half-released.
            def _finalize(filled: bool) -> None:
                portfolio.reserved_cash -= total_cost
                remaining = portfolio.pending_qty.get(symbol, 0) - qty
                if remaining:
                    portfolio.pending_qty[symbol] = remaining
                else:
                    portfolio.pending_qty.pop(symbol, None)
                if filled:
                    portfolio.last_prices[symbol] = price  # mark only on a confirmed fill
                    portfolio.unsettled_share_lots.append(
                        SettlementLot(symbol=symbol, qty=qty, clears_at_day=clears_at_day)
                    )
                else:
                    portfolio.settled_cash += total_cost

            # Step 2: broker call outside the lock; roll back on any exit (incl. cancellation)
            try:
                result = await func(symbol, qty, exec_price, *args, **kwargs)
            except BaseException:
                _finalize(filled=False)
                raise
            _finalize(filled=True)
            return result

        return wrapper
    return decorator
