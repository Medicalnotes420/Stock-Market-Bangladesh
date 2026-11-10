#!/usr/bin/env python3
"""
bootstrap_dse_quant_repo.py
Regenerated from the current sources. Writes the four core DSE quant files
into the current directory. Generated: do not hand-edit; regenerate instead.
Claude Code agent and hook files are managed in git and are not written here.
"""

from pathlib import Path

FILES: dict[str, str] = {}

# ===========================================================================
# async_risk_guard.py
# ===========================================================================
FILES['async_risk_guard.py'] = r'''"""
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
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
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
        # Commission rounds up: a cost to us is never under-reserved
        commission = (gross * self.commission_rate).quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
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

    def _require_audit_capacity(self) -> None:
        """Fail closed: refuse to fill when the audit queue cannot take the row (audit F10)."""
        if self.audit_queue is not None and self.audit_queue.full():
            raise RuntimeError("audit queue full: refusing to fill without an audit row")

    def _emit_audit_unlocked(self, event: AuditEvent) -> None:
        if self.audit_queue is not None:
            self.audit_queue.put_nowait(event)  # capacity guaranteed by _require_audit_capacity

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
            if exec_price > tick.upper_circuit:  # a penalised fill above the circuit cannot print
                raise CircuitBreakerLiquidityError(
                    f"{tick.symbol} penalised fill {exec_price} above upper circuit {tick.upper_circuit}."
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
            self._require_audit_capacity()
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

            # Depth penalty mirrors the buy side: a sweep past L1 bid volume fills 25 bps worse,
            # rounded down to the tick (conservative for proceeds)
            sell_px = tick.bid
            if qty > tick.bid_volume:
                sell_px = (tick.bid * Decimal("0.9975") / DSE_TICK_SIZE).to_integral_value(
                    rounding=ROUND_FLOOR
                ) * DSE_TICK_SIZE

            if sell_px < tick.lower_circuit:  # a penalised fill below the circuit cannot print
                raise CircuitBreakerLiquidityError(
                    f"{tick.symbol} penalised fill {sell_px} below lower circuit {tick.lower_circuit}."
                )

            # Compute every amount before mutating anything
            gross = sell_px * Decimal(qty)
            # Commission rounds up: it reduces proceeds, so rounding up is conservative
            commission = (gross * self.commission_rate).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
            net_proceeds = gross - commission

            # All checks passed: commit the fill
            self._require_audit_capacity()
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
                    exec_price=str(sell_px),
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
'''

# ===========================================================================
# test_async_risk_guard.py
# ===========================================================================
FILES['test_async_risk_guard.py'] = r'''"""
test_async_risk_guard.py
Pytest-asyncio concurrency suite verifying atomic cash reservation, double-spend
prevention under simultaneous WebSocket ticks, and automatic rollback on broker failure.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import pytest

from async_risk_guard import (
    AsyncPortfolioState,
    InsufficientSettledCashError,
    MaxDrawdownCircuitBreakerError,
    PositionLimitExceededError,
    ShareCategory,
    async_risk_guard,
)


@pytest.mark.asyncio
async def test_concurrent_ticks_prevent_double_spending():
    """
    10 simultaneous WebSocket coroutines attempt to buy 100 shares of GP @ 200.00 BDT
    (Cost = 20,060.00 BDT each with 0.30% DSE commission).
    With 25,000 BDT cash and 100% position limit, ONLY 1 order can succeed.
    """
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("25000.00"),
        max_position_pct=Decimal("1.00"),
        max_drawdown_pct=Decimal("0.20"),
    )

    @async_risk_guard(portfolio)
    async def execute_buy(symbol: str, qty: int, price: Decimal) -> str:
        await asyncio.sleep(0.01)  # Simulate network round-trip
        return f"FILLED:{symbol}:{qty}@{price}"

    tasks = [
        execute_buy("GP", 100, Decimal("200.00"), category=ShareCategory.A)
        for _ in range(10)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    fills = [r for r in results if isinstance(r, str)]
    rejections = [r for r in results if isinstance(r, InsufficientSettledCashError)]

    assert len(fills) == 1
    assert len(rejections) == 9
    # 25,000.00 - (100 * 200.00 * 1.0030 = 20,060.00) = 4,940.00 BDT
    assert portfolio.settled_cash == Decimal("4940.00")
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_atomic_rollback_restores_cash_on_broker_exception():
    """If the downstream broker coroutine raises an exception, reserved cash rolls back."""
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"),
        max_position_pct=Decimal("0.50"),
    )

    @async_risk_guard(portfolio)
    async def failing_broker_order(symbol: str, qty: int, price: Decimal) -> None:
        await asyncio.sleep(0.005)
        raise ConnectionResetError("DSE FIX gateway timeout")

    with pytest.raises(ConnectionResetError):
        await failing_broker_order("BXPHARMA", 100, Decimal("150.00"), category=ShareCategory.A)

    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")
    assert len(portfolio.unsettled_share_lots) == 0
    assert portfolio.pending_qty == {}  # in-flight quantity released on broker failure


@pytest.mark.asyncio
async def test_position_size_and_drawdown_circuit_breakers():
    """Verifies max_position_pct and max_drawdown_pct gates."""
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"),
        max_position_pct=Decimal("0.20"),  # Max 20,000 BDT per ticker
        max_drawdown_pct=Decimal("0.10"),  # Max 10% drawdown
    )

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    # 1. Breach 20% position limit (150 * 150 = 22,500 BDT > 20,000 BDT)
    with pytest.raises(PositionLimitExceededError):
        await place_order("SQURPHARMA", 150, Decimal("150.00"), category=ShareCategory.A)

    # 2. Simulate 12% portfolio drawdown -> triggers circuit breaker
    portfolio.settled_cash = Decimal("88000.00")
    with pytest.raises(MaxDrawdownCircuitBreakerError):
        await place_order("SQURPHARMA", 10, Decimal("150.00"), category=ShareCategory.A)


@pytest.mark.asyncio
async def test_decorator_rejects_negative_qty_and_float_price():
    """Negative qty conjured cash in the audit; float price bypasses Decimal reservation."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    with pytest.raises(ValueError):
        await place_order("GP", -100, Decimal("100.00"), category=ShareCategory.A)
    with pytest.raises(TypeError):
        await place_order("GP", 10, 100.0, category=ShareCategory.A)
    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_decorator_requires_explicit_category():
    """A silent default would settle Category Z lots at T+2."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    with pytest.raises(TypeError):
        await place_order("Z_JUTE", 10, Decimal("45.00"))  # no category


@pytest.mark.asyncio
async def test_cancelled_broker_call_releases_reserved_cash():
    """A cancelled (e.g. wait_for timeout) broker call must not strand reserved cash."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def slow_broker_order(symbol: str, qty: int, price: Decimal) -> None:
        await asyncio.sleep(10)

    task = asyncio.create_task(slow_broker_order("BXPHARMA", 100, Decimal("150.00"), category=ShareCategory.A))
    await asyncio.sleep(0.01)
    assert portfolio.reserved_cash > 0
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")
    assert portfolio.pending_qty == {}  # in-flight quantity released on cancellation


@pytest.mark.asyncio
async def test_category_z_lot_through_decorator_matures_at_t3():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    await buy("Z_JUTE", 10, Decimal("45.00"), category=ShareCategory.Z)
    await portfolio.advance_trading_day(days=2)
    assert portfolio.matured_positions.get("Z_JUTE", 0) == 0  # still unsettled on T+2
    await portfolio.advance_trading_day(days=1)
    assert portfolio.matured_positions["Z_JUTE"] == 10  # matured on T+3


@pytest.mark.asyncio
async def test_rejected_decorator_order_does_not_overwrite_mark():
    """Audit N2: a caller-supplied price on a rejected order must not inflate equity."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))
    portfolio.last_prices["GP"] = Decimal("100.00")

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    with pytest.raises(InsufficientSettledCashError):
        await place_order("GP", 100, Decimal("9999.00"), category=ShareCategory.A)
    assert portfolio.last_prices["GP"] == Decimal("100.00")


@pytest.mark.asyncio
async def test_decorator_rejects_zero_price_and_unknown_category():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    with pytest.raises(ValueError):
        await place_order("GP", 1, Decimal("0"), category=ShareCategory.A)
    with pytest.raises(ValueError):
        await place_order("GP", 1, Decimal("100.00"), category="z")
    assert portfolio.settled_cash == Decimal("100000.00")


@pytest.mark.asyncio
async def test_concurrent_orders_cannot_exceed_position_limit():
    """Audit F1: in-flight orders must count toward exposure, or four buys all fill."""
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"),
        max_position_pct=Decimal("0.25"),
        max_drawdown_pct=Decimal("0.50"),
    )

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> str:
        await asyncio.sleep(0.01)  # broker round-trip: every order is in flight at once
        return "FILLED"

    results = await asyncio.gather(
        *(buy("GP", 200, Decimal("100.00"), category=ShareCategory.A) for _ in range(4)),
        return_exceptions=True,
    )
    fills = [r for r in results if r == "FILLED"]
    limits = [r for r in results if isinstance(r, PositionLimitExceededError)]
    assert len(fills) == 1
    assert len(limits) == 3
    assert portfolio.pending_qty == {}  # every in-flight reservation released
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_failed_broker_call_leaves_caller_price_unmarked():
    """Audit F3: a failed order at a caller-supplied price must not inflate equity."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))
    portfolio.last_prices["GP"] = Decimal("100.00")

    @async_risk_guard(portfolio)
    async def failing_order(symbol: str, qty: int, price: Decimal) -> None:
        raise ConnectionResetError("gateway timeout")

    with pytest.raises(ConnectionResetError):
        await failing_order("GP", 1, Decimal("900.00"), category=ShareCategory.A)
    assert portfolio.last_prices["GP"] == Decimal("100.00")
    assert portfolio.settled_cash == Decimal("100000.00")
'''

# ===========================================================================
# test_quant_verifier_dse.py
# ===========================================================================
FILES['test_quant_verifier_dse.py'] = r'''"""
test_quant_verifier_dse.py
Red-team audit test suite for DSE T+2/T+3 settlement constraints, 0.30% commission
+ L1 depth slippage, and strict temporal causality.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import pytest

from async_risk_guard import (
    AsyncPortfolioState,
    CircuitBreakerLiquidityError,
    MarketTick,
    ShareCategory,
    SettlementViolationError,
    TemporalLeakageError,
)


@pytest.mark.asyncio
async def test_t2_and_cat_z_t3_settlement_blocks_premature_selling():
    state = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"),
        max_position_pct=Decimal("0.50"),
        current_trading_day=1,
    )

    tick_buy = MarketTick(
        symbol="BXPHARMA",
        category=ShareCategory.A,
        exchange_ts_ms=1_000,
        bid=Decimal("150.00"),
        ask=Decimal("150.10"),
        ask_volume=500,
        upper_circuit=Decimal("165.00"),
        lower_circuit=Decimal("135.00"),
    )
    await state.ingest_tick_and_buy(tick_buy, qty=100, signal_generated_ts_ms=980)

    # Intraday sell on Day 1 must fail (T+2 short-sale ban)
    tick_sell = MarketTick(
        symbol="BXPHARMA",
        category=ShareCategory.A,
        exchange_ts_ms=1_050,
        bid=Decimal("152.00"),
        ask=Decimal("152.20"),
        ask_volume=500,
        upper_circuit=Decimal("165.00"),
        lower_circuit=Decimal("135.00"),
    )
    with pytest.raises(SettlementViolationError, match="Short-Sale Ban"):
        await state.sell_matured_shares(tick_sell, qty=100, signal_generated_ts_ms=1_000)

    # Day 2 (T+1): still unsettled
    await state.advance_trading_day(days=1)
    assert state.matured_positions.get("BXPHARMA", 0) == 0

    # Day 3 (T+2): matured and eligible for sale
    await state.advance_trading_day(days=1)
    assert state.matured_positions["BXPHARMA"] == 100


@pytest.mark.asyncio
async def test_concurrent_sell_coroutines_cannot_double_spend_matured_shares():
    state = AsyncPortfolioState(initial_cash=Decimal("50000.00"), current_trading_day=1)
    state.matured_positions["GP"] = 200

    async def attempt_sell(idx: int):
        tick = MarketTick(
            symbol="GP",
            category=ShareCategory.A,
            exchange_ts_ms=2_000 + idx,
            bid=Decimal("286.60"),
            ask=Decimal("287.00"),
        )
        return await state.sell_matured_shares(tick, qty=200, signal_generated_ts_ms=1_000)

    results = await asyncio.gather(*(attempt_sell(i) for i in range(5)), return_exceptions=True)
    successes = [r for r in results if isinstance(r, Decimal)]
    failures = [r for r in results if isinstance(r, SettlementViolationError)]

    assert len(successes) == 1
    assert len(failures) == 4
    assert state.matured_positions["GP"] == 0


@pytest.mark.asyncio
async def test_dse_commission_and_depth_slippage_reservation():
    # Exact cash for 100 @ 100.00 + 0.30% = 10,030.00 BDT
    state = AsyncPortfolioState(
        initial_cash=Decimal("10030.00"),
        max_position_pct=Decimal("1.00"),
        current_trading_day=1,
    )

    thin_book_tick = MarketTick(
        symbol="SQURPHARMA",
        category=ShareCategory.A,
        exchange_ts_ms=5_000,
        bid=Decimal("99.80"),
        ask=Decimal("100.00"),
        ask_volume=50,  # Order of 100 sweeps L1 -> +25 bps slippage -> 100.30 BDT
    )
    with pytest.raises(SettlementViolationError, match="Insufficient settled cash"):
        await state.ingest_tick_and_buy(thin_book_tick, qty=100, signal_generated_ts_ms=4_900)


@pytest.mark.asyncio
async def test_temporal_leakage_rejects_same_tick_fill_and_out_of_order_packets():
    state = AsyncPortfolioState(
        initial_cash=Decimal("500000.00"),
        max_position_pct=Decimal("0.50"),
    )

    tick_t1 = MarketTick(
        symbol="BRACBANK",
        category=ShareCategory.A,
        exchange_ts_ms=10_000,
        bid=Decimal("38.40"),
        ask=Decimal("38.50"),
    )
    with pytest.raises(TemporalLeakageError, match="Look-ahead fill rejected"):
        await state.ingest_tick_and_buy(tick_t1, qty=100, signal_generated_ts_ms=10_000)

    tick_t2 = MarketTick(
        symbol="BRACBANK",
        category=ShareCategory.A,
        exchange_ts_ms=10_020,
        bid=Decimal("38.40"),
        ask=Decimal("38.50"),
    )
    await state.ingest_tick_and_buy(tick_t2, qty=100, signal_generated_ts_ms=10_000)

    stale_tick = MarketTick(
        symbol="BRACBANK",
        category=ShareCategory.A,
        exchange_ts_ms=10_010,
        bid=Decimal("38.30"),
        ask=Decimal("38.40"),
    )
    with pytest.raises(TemporalLeakageError, match="Out-of-order tick"):
        await state.ingest_tick_and_buy(stale_tick, qty=100, signal_generated_ts_ms=9_900)


@pytest.mark.asyncio
async def test_sell_latency_gate_rejects_same_tick_fill():
    state = AsyncPortfolioState(initial_cash=Decimal("50000.00"))
    state.matured_positions["GP"] = 100
    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=10_000,
                      bid=Decimal("286.60"), ask=Decimal("287.00"))
    with pytest.raises(TemporalLeakageError, match="Look-ahead sell rejected"):
        await state.sell_matured_shares(tick, qty=100, signal_generated_ts_ms=10_000)
    assert state.matured_positions["GP"] == 100  # nothing moved


@pytest.mark.asyncio
async def test_rejected_sell_marks_ordered_tick_bid():
    state = AsyncPortfolioState(initial_cash=Decimal("50000.00"))
    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=20_000,
                      bid=Decimal("290.00"), ask=Decimal("291.00"))
    with pytest.raises(SettlementViolationError):
        await state.sell_matured_shares(tick, qty=100, signal_generated_ts_ms=1_000)
    assert state.last_exchange_ts_ms == 20_000  # a valid ordered tick, even though the order failed
    assert state.last_prices["GP"] == Decimal("290.00")  # market data marks the book (audit F2)


@pytest.mark.asyncio
async def test_mark_follows_market_down_so_drawdown_breaker_sees_it():
    """Audit F2: a rejected order on a falling tick must still mark the book down."""
    state = AsyncPortfolioState(initial_cash=Decimal("50000.00"), max_drawdown_pct=Decimal("0.10"))
    state.matured_positions["GP"] = 500
    state.last_prices["GP"] = Decimal("100.00")  # bought at 100: equity 100,000 on 50,000 cash
    crash = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=5_000,
                       bid=Decimal("50.00"), ask=Decimal("50.10"))
    with pytest.raises(SettlementViolationError):  # over-sell, rejected
        await state.sell_matured_shares(crash, qty=1000, signal_generated_ts_ms=1_000)
    assert state.last_prices["GP"] == Decimal("50.00")
    # equity now 50,000 + 500*50 = 75,000 vs initial 50,000 -> the drawdown check sees the move
    assert state.total_equity_unlocked() == Decimal("75000.00")


@pytest.mark.asyncio
async def test_latency_rejected_newer_tick_still_blocks_older_tick():
    """Audit F4: a latency-blocked newer tick must still advance the watermark."""
    state = AsyncPortfolioState(initial_cash=Decimal("500000.00"))
    newer = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=200,
                       bid=Decimal("99.90"), ask=Decimal("100.00"))
    with pytest.raises(TemporalLeakageError, match="Look-ahead fill rejected"):
        await state.ingest_tick_and_buy(newer, qty=1, signal_generated_ts_ms=190)
    older = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=150,
                       bid=Decimal("99.90"), ask=Decimal("100.00"))
    with pytest.raises(TemporalLeakageError, match="Out-of-order tick"):
        await state.ingest_tick_and_buy(older, qty=1, signal_generated_ts_ms=100)
    assert state.unsettled_share_lots == []


@pytest.mark.asyncio
async def test_older_tick_cannot_fill_after_rejected_newer_tick():
    """Audit N1: a rejected newer tick must still block an older tick from filling."""
    state = AsyncPortfolioState(initial_cash=Decimal("100.00"), max_position_pct=Decimal("1.00"))
    newer = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=200,
                       bid=Decimal("99.90"), ask=Decimal("100.00"))
    with pytest.raises(SettlementViolationError, match="Insufficient settled cash"):
        await state.ingest_tick_and_buy(newer, qty=100, signal_generated_ts_ms=100)
    older = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=150,
                       bid=Decimal("99.90"), ask=Decimal("100.00"))
    with pytest.raises(TemporalLeakageError, match="Out-of-order tick"):
        await state.ingest_tick_and_buy(older, qty=1, signal_generated_ts_ms=100)
    assert state.unsettled_share_lots == []


@pytest.mark.asyncio
async def test_rejected_buy_marks_bid_never_the_order_ask():
    """Audit N2: the caller's order ask must not set the mark; only the tick's bid does."""
    state = AsyncPortfolioState(initial_cash=Decimal("100000.00"))
    state.last_prices["GP"] = Decimal("100.00")
    locked = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=1_000,
                        bid=Decimal("499.00"), ask=Decimal("500.00"),
                        upper_circuit=Decimal("500.00"))
    with pytest.raises(CircuitBreakerLiquidityError):
        await state.ingest_tick_and_buy(locked, qty=1, signal_generated_ts_ms=0)
    assert state.last_prices["GP"] == Decimal("499.00")  # tick bid, not the 500.00 ask


@pytest.mark.asyncio
async def test_zero_latency_window_is_rejected():
    state = AsyncPortfolioState(initial_cash=Decimal("100000.00"))
    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=1_000,
                      bid=Decimal("99.90"), ask=Decimal("100.00"))
    with pytest.raises(ValueError):
        await state.ingest_tick_and_buy(tick, qty=1, signal_generated_ts_ms=1_000,
                                        min_network_latency_ms=0)


def test_bad_market_data_is_rejected():
    base = dict(symbol="GP", category=ShareCategory.A, exchange_ts_ms=1,
                bid=Decimal("99.90"), ask=Decimal("100.00"))
    with pytest.raises(ValueError):  # unknown category must not silently become T+2
        MarketTick(**{**base, "category": "Q"})
    with pytest.raises(ValueError):  # non-finite prices
        MarketTick(**{**base, "ask": Decimal("Infinity")})
    with pytest.raises(ValueError):  # crossed book
        MarketTick(**{**base, "bid": Decimal("101.00")})


def test_portfolio_parameters_are_validated():
    with pytest.raises(ValueError):
        AsyncPortfolioState(initial_cash=Decimal("100.00"), max_drawdown_pct=Decimal("5"))
    with pytest.raises(ValueError):
        AsyncPortfolioState(initial_cash=Decimal("100.00"), max_position_pct=Decimal("-1"))


@pytest.mark.asyncio
async def test_advance_zero_days_is_rejected():
    state = AsyncPortfolioState(initial_cash=Decimal("100.00"))
    with pytest.raises(ValueError):
        await state.advance_trading_day(days=0)


@pytest.mark.asyncio
async def test_negative_or_zero_qty_cannot_mint_cash_or_shares():
    state = AsyncPortfolioState(initial_cash=Decimal("100000.00"), current_trading_day=1)
    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=30_000,
                      bid=Decimal("99.90"), ask=Decimal("100.00"))
    with pytest.raises(ValueError):
        await state.ingest_tick_and_buy(tick, qty=0, signal_generated_ts_ms=20_000)
    with pytest.raises(ValueError):
        await state.ingest_tick_and_buy(tick, qty=-100, signal_generated_ts_ms=20_000)
    with pytest.raises(ValueError):
        await state.sell_matured_shares(tick, qty=-100, signal_generated_ts_ms=20_000)
    assert state.settled_cash == Decimal("100000.00")
    assert state.matured_positions == {}


def test_float_prices_and_cash_are_rejected():
    with pytest.raises(TypeError):
        MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=1,
                   bid=100.0, ask=Decimal("100.10"))
    with pytest.raises(TypeError):
        AsyncPortfolioState(initial_cash=100000.0)


@pytest.mark.asyncio
async def test_harness_run_logs_t2_rejection_and_closes_log(tmp_path):
    import dse_paper_harness

    log = tmp_path / "audit.jsonl"
    final = await dse_paper_harness.run_paper_session(log_path=log)
    text = log.read_text(encoding="utf-8")
    assert "Short-Sale Ban" in text       # the staged intraday sell is rejected and logged
    assert final.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_harness_retries_staged_order_until_latency_elapses(tmp_path, monkeypatch):
    """Audit F7: ticks 5 ms apart must hold a staged buy until the 15 ms window has passed."""
    import dse_paper_harness
    import json

    async def fast_stream(num_ticks: int = 0):
        for i in range(5):
            yield MarketTick(symbol="BXPHARMA", category=ShareCategory.A,
                             exchange_ts_ms=1_000 + 5 * i, bid=Decimal("149.90"),
                             ask=Decimal("150.00"), ask_volume=500, bid_volume=500)
            await asyncio.sleep(0)

    monkeypatch.setattr(dse_paper_harness, "simulated_dse_stream", fast_stream)
    log = tmp_path / "audit.jsonl"
    await dse_paper_harness.run_paper_session(log_path=log)
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    # The first buy (signal 1000) must fill on the first tick at or after 1015, not be dropped or
    # executed early. Its fill is the only ORDER_FILLED at exchange_ts_ms 1015.
    assert any(e["event_type"] == "ORDER_FILLED" and e["exchange_ts_ms"] == 1_015 for e in events)
    assert not any("Look-ahead" in e["reason"] for e in events)


@pytest.mark.asyncio
async def test_sell_sweeping_past_bid_volume_fills_25bps_worse_on_tick():
    state = AsyncPortfolioState(initial_cash=Decimal("0.01"))
    state.matured_positions["GP"] = 1_000
    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=5_000,
                      bid=Decimal("100.00"), ask=Decimal("100.10"), bid_volume=500)
    # 1000 > 500 L1 -> 100.00 * 0.9975 = 99.75, floored to the 0.10 tick = 99.70
    # gross 99,700.00, commission ceiling 0.3% = 299.10, net 99,400.90
    net = await state.sell_matured_shares(tick, qty=1_000, signal_generated_ts_ms=1_000)
    assert net == Decimal("99400.90")


@pytest.mark.asyncio
async def test_audit_queue_full_fails_closed_without_moving_cash():
    """Audit F10: no fill may commit if its audit row cannot be queued."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait(None)  # fill the queue
    state = AsyncPortfolioState(initial_cash=Decimal("100000.00"), audit_queue=queue)
    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=5_000,
                      bid=Decimal("99.90"), ask=Decimal("100.00"))
    with pytest.raises(RuntimeError, match="audit queue full"):
        await state.ingest_tick_and_buy(tick, qty=10, signal_generated_ts_ms=1_000)
    assert state.settled_cash == Decimal("100000.00")
    assert state.unsettled_share_lots == []


@pytest.mark.asyncio
async def test_penalised_sell_below_lower_circuit_is_rejected():
    """Audit M2: 135.10 x 0.9975 floors to 134.70, below the 135.00 circuit. Must not print."""
    state = AsyncPortfolioState(initial_cash=Decimal("0.01"))
    state.matured_positions["SQURPHARMA"] = 1_000
    tick = MarketTick(symbol="SQURPHARMA", category=ShareCategory.A, exchange_ts_ms=5_000,
                      bid=Decimal("135.10"), ask=Decimal("135.20"), bid_volume=500,
                      lower_circuit=Decimal("135.00"))
    with pytest.raises(CircuitBreakerLiquidityError, match="below lower circuit"):
        await state.sell_matured_shares(tick, qty=1_000, signal_generated_ts_ms=1_000)
    assert state.matured_positions["SQURPHARMA"] == 1_000  # nothing moved


@pytest.mark.asyncio
async def test_penalised_buy_above_upper_circuit_is_rejected():
    """Audit M2: ask 100.00 plus the 25 bps sweep penalty rounds to 100.30, above a 100.20 circuit."""
    state = AsyncPortfolioState(initial_cash=Decimal("500000.00"))
    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=5_000,
                      bid=Decimal("99.90"), ask=Decimal("100.00"), ask_volume=50,
                      upper_circuit=Decimal("100.20"))
    with pytest.raises(CircuitBreakerLiquidityError, match="above upper circuit"):
        await state.ingest_tick_and_buy(tick, qty=100, signal_generated_ts_ms=1_000)
    assert state.settled_cash == Decimal("500000.00")
    assert state.unsettled_share_lots == []


@pytest.mark.asyncio
async def test_sell_commission_rounds_up_on_fractional_cent():
    """L3: 7 x 150.10 = 1050.70; 0.3% = 3.1521 -> 3.16 on the sell side (half-up gives 3.15)."""
    state = AsyncPortfolioState(initial_cash=Decimal("0.01"))
    state.matured_positions["GP"] = 7
    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=5_000,
                      bid=Decimal("150.10"), ask=Decimal("150.20"), bid_volume=1_000)
    net = await state.sell_matured_shares(tick, qty=7, signal_generated_ts_ms=1_000)
    assert net == Decimal("1047.54")


@pytest.mark.asyncio
async def test_logger_stop_does_not_hang_when_drain_worker_died(tmp_path):
    """Audit L1: stop() must surface a dead drain worker, not block on a put with no consumer."""
    from dse_paper_harness import AsyncAuditLogger

    logger = AsyncAuditLogger(log_path=tmp_path / "a.jsonl")

    async def dead() -> None:
        raise OSError("disk gone")

    logger._worker = asyncio.create_task(dead())
    await asyncio.sleep(0)
    with pytest.raises(OSError, match="disk gone"):
        await asyncio.wait_for(logger.stop(), timeout=1)


@pytest.mark.asyncio
async def test_stop_surfaces_worker_death_while_queue_is_full(tmp_path):
    """Audit M1: a worker that dies while the queue is full must not hang stop()."""
    from dse_paper_harness import AsyncAuditLogger

    logger = AsyncAuditLogger(log_path=tmp_path / "a.jsonl")
    logger.queue = asyncio.Queue(maxsize=1)
    logger.queue.put_nowait(None)  # full, and nothing is consuming it

    async def dies_later() -> None:
        await asyncio.sleep(0.05)
        raise OSError("disk gone")

    logger._worker = asyncio.create_task(dies_later())
    with pytest.raises(OSError, match="disk gone"):
        await asyncio.wait_for(logger.stop(), timeout=1)


@pytest.mark.asyncio
async def test_put_surfaces_worker_death_instead_of_blocking(tmp_path):
    """Audit M2: a risk-rejection row on a full queue with a dead worker must raise, not hang."""
    from dse_paper_harness import AsyncAuditLogger

    logger = AsyncAuditLogger(log_path=tmp_path / "a.jsonl")
    logger.queue = asyncio.Queue(maxsize=1)
    logger.queue.put_nowait(None)

    async def dies_later() -> None:
        await asyncio.sleep(0.05)
        raise OSError("disk gone")

    logger._worker = asyncio.create_task(dies_later())
    with pytest.raises(OSError, match="disk gone"):
        await asyncio.wait_for(logger.put(None), timeout=1)


@pytest.mark.asyncio
async def test_cancelled_put_leaves_no_ghost_task(tmp_path):
    """Audit M1: cancelling a put() on a full queue must not leave an orphan put task."""
    from dse_paper_harness import AsyncAuditLogger

    logger = AsyncAuditLogger(log_path=tmp_path / "a.jsonl")
    logger.queue = asyncio.Queue(maxsize=1)
    logger.queue.put_nowait(None)  # full
    logger._worker = asyncio.create_task(asyncio.sleep(10))  # alive, but not consuming
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(logger.put(None), timeout=0.05)
    await asyncio.sleep(0)
    orphans = [t for t in asyncio.all_tasks()
               if t is not asyncio.current_task() and t is not logger._worker and not t.done()]
    assert orphans == []
    logger._worker.cancel()


@pytest.mark.asyncio
async def test_check_alive_raises_once_worker_has_ended(tmp_path):
    """Audit M2: the per-tick liveness check must surface a dead writer."""
    from dse_paper_harness import AsyncAuditLogger

    logger = AsyncAuditLogger(log_path=tmp_path / "a.jsonl")

    async def dead() -> None:
        raise OSError("disk gone")

    logger._worker = asyncio.create_task(dead())
    await asyncio.sleep(0)
    with pytest.raises(OSError, match="disk gone"):
        logger.check_alive()


@pytest.mark.asyncio
async def test_cancelled_worker_is_reported_as_runtime_error_not_cancellation(tmp_path):
    """Audit L1: a cancelled drain worker must not raise CancelledError into an uncancelled caller."""
    from dse_paper_harness import AsyncAuditLogger

    logger = AsyncAuditLogger(log_path=tmp_path / "a.jsonl")
    logger._worker = asyncio.create_task(asyncio.sleep(10))
    await asyncio.sleep(0)
    logger._worker.cancel()
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="cancelled"):
        await asyncio.wait_for(logger.stop(), timeout=1)


def test_commission_rounds_up_not_to_nearest():
    state = AsyncPortfolioState(initial_cash=Decimal("100000.00"))
    # 7 x 150.10 = 1050.70; 0.3% = 3.1521 -> ceiling 3.16 (half-up would give 3.15)
    _, commission, _ = state.calculate_buy_cost(Decimal("150.10"), 7)
    assert commission == Decimal("3.16")
'''

# ===========================================================================
# dse_paper_harness.py
# ===========================================================================
FILES['dse_paper_harness.py'] = r'''"""
dse_paper_harness.py
Async WebSocket paper-trading execution harness wrapping async_risk_guard.py
with non-blocking asyncio.Queue JSONL audit logging.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from async_risk_guard import (
    MIN_NETWORK_LATENCY_MS,
    AsyncPortfolioState,
    AuditEvent,
    MarketTick,
    OrderSide,
    RiskViolationError,
    ShareCategory,
)


@dataclass(frozen=True)
class StagedOrder:
    order_id: str
    symbol: str
    category: ShareCategory
    side: OrderSide
    qty: int
    signal_ts_ms: int


class AsyncAuditLogger:
    """Drains AuditEvent items from an asyncio.Queue outside the portfolio lock."""

    def __init__(self, log_path: Path = Path("dse_paper_audit.jsonl")) -> None:
        self.queue: asyncio.Queue[Optional[AuditEvent]] = asyncio.Queue(maxsize=10_000)
        self.log_path = log_path
        self._worker: Optional[asyncio.Task[None]] = None
        self.events_written: int = 0

    def start(self) -> None:
        self._worker = asyncio.create_task(self._drain_loop())

    async def put(self, item: Optional[AuditEvent]) -> None:
        """Enqueue without blocking on a dead drain worker (audit M1, M2)."""
        if self._worker is None:
            raise RuntimeError("audit logger not started")
        if self._worker.done():
            self._raise_worker_end()
        put_task = asyncio.ensure_future(self.queue.put(item))
        try:
            done, _ = await asyncio.wait(
                {put_task, self._worker}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            if not put_task.done():  # caller cancelled, or the worker ended: never leave a ghost put
                put_task.cancel()
        if put_task in done:
            put_task.result()  # surface a failed put rather than reporting success (audit L1)
            return
        self._raise_worker_end()

    def check_alive(self) -> None:
        """Raise if the drain worker has ended, so fills do not pile up unseen (audit M2)."""
        if self._worker is not None and self._worker.done():
            self._raise_worker_end()

    def _raise_worker_end(self) -> None:
        assert self._worker is not None and self._worker.done()
        if self._worker.cancelled():
            raise RuntimeError("audit drain worker was cancelled")
        if self._worker.exception() is not None:
            raise self._worker.exception()
        raise RuntimeError("audit drain worker stopped before the session ended")

    async def stop(self) -> None:
        if self._worker is None:
            return
        if not self._worker.done():
            await self.put(None)
            await asyncio.wait({self._worker})
        if self._worker.cancelled():  # surface, rather than raising CancelledError into the caller
            raise RuntimeError("audit drain worker was cancelled")
        if self._worker.exception() is not None:
            raise self._worker.exception()

    async def _drain_loop(self) -> None:
        with self.log_path.open("a", encoding="utf-8") as fp:
            while True:
                ev = await self.queue.get()
                if ev is None:
                    self.queue.task_done()
                    break
                fp.write(json.dumps(asdict(ev)) + "\n")
                fp.flush()
                self.events_written += 1
                self.queue.task_done()


async def simulated_dse_stream(num_ticks: int = 12) -> AsyncIterator[MarketTick]:
    instruments = [
        ("BXPHARMA", ShareCategory.A, Decimal("150.00")),
        ("SQURPHARMA", ShareCategory.A, Decimal("210.00")),
        ("GP", ShareCategory.A, Decimal("286.60")),
        ("Z_JUTE", ShareCategory.Z, Decimal("45.00")),
    ]
    ts = 1_700_000_000_000
    for i in range(num_ticks):
        sym, cat, px = instruments[i % len(instruments)]
        ts += 20
        yield MarketTick(
            symbol=sym,
            category=cat,
            exchange_ts_ms=ts,
            bid=px - Decimal("0.10"),
            ask=px + Decimal("0.10"),
            ask_volume=500,
            bid_volume=500,
            upper_circuit=px * Decimal("1.10"),
            lower_circuit=px * Decimal("0.90"),
        )
        await asyncio.sleep(0.002)


async def run_paper_session(log_path: Path = Path("dse_paper_audit.jsonl")) -> AsyncPortfolioState:
    # The log is append-only: a rerun adds rows rather than erasing the previous session's audit trail
    logger = AsyncAuditLogger(log_path=log_path)
    logger.start()

    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("500000.00"),
        max_position_pct=Decimal("0.30"),
        max_drawdown_pct=Decimal("0.10"),
        audit_queue=logger.queue,
    )

    staged: Dict[str, List[StagedOrder]] = {}
    try:
        await _run_ticks(portfolio, logger, staged)
    finally:
        await logger.stop()  # always drain and close the audit file, even on error
    return portfolio


async def _run_ticks(
    portfolio: AsyncPortfolioState,
    logger: AsyncAuditLogger,
    staged: Dict[str, List[StagedOrder]],
) -> None:
    seq = 0
    async for tick in simulated_dse_stream(num_ticks=12):
        logger.check_alive()  # a dead writer must stop the session, not let fills pile up unlogged
        # 1. Execute previously staged orders once the latency window has elapsed
        pending = staged.get(tick.symbol, [])
        still_waiting: List[StagedOrder] = []
        for order in pending:
            if tick.exchange_ts_ms < order.signal_ts_ms + MIN_NETWORK_LATENCY_MS:
                still_waiting.append(order)  # retry on a later tick of this symbol
                continue
            try:
                if order.side == OrderSide.BUY:
                    await portfolio.ingest_tick_and_buy(
                        tick, qty=order.qty, signal_generated_ts_ms=order.signal_ts_ms
                    )
                else:
                    await portfolio.sell_matured_shares(
                        tick, qty=order.qty, signal_generated_ts_ms=order.signal_ts_ms
                    )
            except RiskViolationError as exc:
                # await put (not put_nowait) so a full queue back-pressures instead of dropping rows
                await logger.put(
                    AuditEvent(
                        event_type="RISK_REJECTED",
                        exchange_ts_ms=tick.exchange_ts_ms,
                        symbol=tick.symbol,
                        side=order.side.value,
                        qty=order.qty,
                        exec_price="0.00",
                        commission_bdt="0.00",
                        settled_cash_after_bdt=str(portfolio.settled_cash),
                        reason=str(exc),
                    )
                )
        staged[tick.symbol] = still_waiting

        # 2. Stage new orders for future ticks
        seq += 1
        if tick.symbol in ("BXPHARMA", "Z_JUTE") and seq <= 4:
            staged.setdefault(tick.symbol, []).append(
                StagedOrder(
                    order_id=f"ORD-{seq:03d}",
                    symbol=tick.symbol,
                    category=tick.category,
                    side=OrderSide.BUY,
                    qty=100,
                    signal_ts_ms=tick.exchange_ts_ms,
                )
            )
        elif tick.symbol == "BXPHARMA" and seq == 5:
            # Stage an intraday sell of unsettled Day-1 shares -> triggers T+2 rejection log
            staged.setdefault(tick.symbol, []).append(
                StagedOrder(
                    order_id=f"ORD-{seq:03d}",
                    symbol="BXPHARMA",
                    category=ShareCategory.A,
                    side=OrderSide.SELL,
                    qty=100,
                    signal_ts_ms=tick.exchange_ts_ms,
                )
            )


if __name__ == "__main__":
    final_state = asyncio.run(run_paper_session())
    print(f"Paper Session Complete | Settled Cash: {final_state.settled_cash:,.2f} BDT")
    print(f"Unsettled Lots: {final_state.unsettled_share_lots}")
'''


def main() -> None:
    for rel_path, content in FILES.items():
        path = Path(rel_path)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"[CREATED] {path}")


if __name__ == "__main__":
    main()
