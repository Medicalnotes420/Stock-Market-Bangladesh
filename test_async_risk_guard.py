"""
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
