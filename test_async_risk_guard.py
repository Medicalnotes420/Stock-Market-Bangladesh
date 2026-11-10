"""
test_async_risk_guard.py
Pytest-asyncio concurrency suite for the decorator buy path: atomic cash reservation,
double-spend prevention, rollback on broker failure, and the shared tick pre-checks.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from async_risk_guard import (
    AsyncPortfolioState,
    CircuitBreakerLiquidityError,
    MarketTick,
    MaxDrawdownCircuitBreakerError,
    PositionLimitExceededError,
    SettlementViolationError,
    ShareCategory,
    TemporalLeakageError,
    async_risk_guard,
)


def make_tick(
    ts: int = 1_000,
    ask: str = "100.00",
    category: ShareCategory = ShareCategory.A,
    symbol: str = "GP",
    ask_volume: int = 1_000,
) -> MarketTick:
    a = Decimal(ask)
    return MarketTick(
        symbol=symbol,
        category=category,
        exchange_ts_ms=ts,
        bid=a - Decimal("0.10"),
        ask=a,
        ask_volume=ask_volume,
    )


@pytest.mark.asyncio
async def test_concurrent_ticks_prevent_double_spending():
    """
    10 simultaneous broker orders for 100 GP at a 200.00 tick ask (cost 20,060.00 BDT with
    0.30% commission). With 25,000 BDT cash only one can succeed.
    """
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("25000.00"),
        max_position_pct=Decimal("1.00"),
        max_drawdown_pct=Decimal("0.20"),
    )
    tick = make_tick(ts=1_000, ask="200.00")

    @async_risk_guard(portfolio)
    async def execute_buy(symbol: str, qty: int, price: Decimal) -> str:
        await asyncio.sleep(0.01)  # Simulate network round-trip
        return f"FILLED:{symbol}:{qty}@{price}"

    results = await asyncio.gather(
        *(execute_buy(tick, 100, 900) for _ in range(10)), return_exceptions=True
    )

    fills = [r for r in results if isinstance(r, str)]
    rejections = [r for r in results if isinstance(r, SettlementViolationError)]
    assert len(fills) == 1
    assert len(rejections) == 9
    assert portfolio.settled_cash == Decimal("4940.00")
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_atomic_rollback_restores_cash_on_broker_exception():
    """If the downstream broker coroutine raises, reserved cash rolls back."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def failing_broker_order(symbol: str, qty: int, price: Decimal) -> None:
        await asyncio.sleep(0.005)
        raise ConnectionResetError("DSE FIX gateway timeout")

    with pytest.raises(ConnectionResetError):
        await failing_broker_order(make_tick(ts=1_000, ask="150.00", symbol="BXPHARMA"), 100, 900)

    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")
    assert portfolio.unsettled_share_lots == []
    assert portfolio.pending_qty == {}


@pytest.mark.asyncio
async def test_position_size_and_drawdown_circuit_breakers():
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"),
        max_position_pct=Decimal("0.20"),  # Max 20,000 BDT per ticker
        max_drawdown_pct=Decimal("0.10"),  # Max 10% drawdown
    )

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    # 1. 150 x 150 = 22,500 BDT > 20% of 100,000 -> position limit
    with pytest.raises(PositionLimitExceededError):
        await place_order(make_tick(ts=1_000, ask="150.00", symbol="SQURPHARMA"), 150, 900)

    # 2. Simulate 12% portfolio drawdown -> drawdown breaker on the next ordered tick
    portfolio.settled_cash = Decimal("88000.00")
    with pytest.raises(MaxDrawdownCircuitBreakerError):
        await place_order(make_tick(ts=2_000, ask="150.00", symbol="SQURPHARMA"), 10, 1_900)


@pytest.mark.asyncio
async def test_float_price_is_rejected_when_the_tick_is_built():
    """A float price cannot reach the decorator: MarketTick refuses it first."""
    with pytest.raises(TypeError):
        MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=1,
                   bid=100.0, ask=Decimal("100.10"))


@pytest.mark.asyncio
async def test_decorator_rejects_negative_qty_without_moving_cash():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    with pytest.raises(ValueError):
        await place_order(make_tick(ts=1_000), -100, 900)
    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_unknown_category_cannot_reach_the_decorator():
    """Category is taken from the tick, so an unknown value fails when the tick is built."""
    with pytest.raises(ValueError):
        MarketTick(symbol="GP", category="z", exchange_ts_ms=1,
                   bid=Decimal("99.90"), ask=Decimal("100.00"))


@pytest.mark.asyncio
async def test_decorator_rejects_look_ahead_order_using_the_tick_gate():
    """The decorator now runs the tick latency gate: a fill inside the 15 ms window is refused."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    with pytest.raises(TemporalLeakageError, match="Look-ahead"):
        await place_order(make_tick(ts=1_000), 1, 1_000)
    assert portfolio.settled_cash == Decimal("100000.00")


@pytest.mark.asyncio
async def test_decorator_rejects_out_of_order_tick():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    await place_order(make_tick(ts=2_000), 1, 1_000)
    with pytest.raises(TemporalLeakageError, match="Out-of-order"):
        await place_order(make_tick(ts=1_500), 1, 1_000)


@pytest.mark.asyncio
async def test_decorator_refuses_penalised_fill_above_upper_circuit():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("500000.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=1_000,
                      bid=Decimal("99.90"), ask=Decimal("100.00"), ask_volume=50,
                      upper_circuit=Decimal("100.20"))
    with pytest.raises(CircuitBreakerLiquidityError, match="above upper circuit"):
        await place_order(tick, 100, 900)
    assert portfolio.settled_cash == Decimal("500000.00")


@pytest.mark.asyncio
async def test_cancelled_broker_call_releases_reserved_cash():
    """A cancelled (e.g. wait_for timeout) broker call must not strand reserved cash."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def slow_broker_order(symbol: str, qty: int, price: Decimal) -> None:
        await asyncio.sleep(10)

    task = asyncio.create_task(slow_broker_order(make_tick(ts=1_000, ask="150.00", symbol="BXPHARMA"), 100, 900))
    await asyncio.sleep(0.01)
    assert portfolio.reserved_cash > 0
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")
    assert portfolio.pending_qty == {}


@pytest.mark.asyncio
async def test_category_z_lot_through_decorator_matures_at_t3():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    await buy(make_tick(ts=1_000, ask="45.00", category=ShareCategory.Z, symbol="Z_JUTE"), 10, 900)
    await portfolio.advance_trading_day(days=2)
    assert portfolio.matured_positions.get("Z_JUTE", 0) == 0  # still unsettled on T+2
    await portfolio.advance_trading_day(days=1)
    assert portfolio.matured_positions["Z_JUTE"] == 10  # matured on T+3


@pytest.mark.asyncio
async def test_rejected_decorator_order_marks_tick_bid_not_order_price():
    """Only market data sets the mark: a rejected order cannot inflate equity."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> str:
        return "OK"

    tick = make_tick(ts=1_000, ask="100.00")
    with pytest.raises(SettlementViolationError):
        await place_order(tick, 100_000, 900)  # far more than the cash allows
    assert portfolio.last_prices["GP"] == Decimal("99.90")  # the tick bid


@pytest.mark.asyncio
async def test_concurrent_orders_cannot_exceed_position_limit():
    """In-flight orders must count toward exposure, or four buys all fill."""
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"),
        max_position_pct=Decimal("0.25"),
        max_drawdown_pct=Decimal("0.50"),
    )

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> str:
        await asyncio.sleep(0.01)  # broker round-trip: every order is in flight at once
        return "FILLED"

    tick = make_tick(ts=1_000, ask="100.00")
    results = await asyncio.gather(
        *(buy(tick, 200, 900) for _ in range(4)),
        return_exceptions=True,
    )
    fills = [r for r in results if r == "FILLED"]
    limits = [r for r in results if isinstance(r, PositionLimitExceededError)]
    assert len(fills) == 1
    assert len(limits) == 3
    assert portfolio.pending_qty == {}
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_failed_broker_call_keeps_tick_mark_and_restores_cash():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))

    @async_risk_guard(portfolio)
    async def failing_order(symbol: str, qty: int, price: Decimal) -> None:
        raise ConnectionResetError("gateway timeout")

    with pytest.raises(ConnectionResetError):
        await failing_order(make_tick(ts=1_000, ask="100.00"), 1, 900)
    assert portfolio.last_prices["GP"] == Decimal("99.90")  # market data, not the caller's
    assert portfolio.settled_cash == Decimal("100000.00")
