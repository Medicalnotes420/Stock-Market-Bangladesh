"""
test_async_risk_guard.py
Pytest-asyncio suite for the decorator buy path: priced from a tick, shared pre-checks,
the broker contract (filled quantity, rejection, unknown outcome), and audit rows.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from async_risk_guard import (
    AsyncPortfolioState,
    BrokerRejectedError,
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
    async def execute_buy(symbol: str, qty: int, price: Decimal) -> int:
        await asyncio.sleep(0.01)  # Simulate network round-trip
        return qty

    results = await asyncio.gather(
        *(execute_buy(tick, 100, 900) for _ in range(10)), return_exceptions=True
    )

    fills = [r for r in results if r == 100]
    rejections = [r for r in results if isinstance(r, SettlementViolationError)]
    assert len(fills) == 1
    assert len(rejections) == 9
    assert portfolio.settled_cash == Decimal("4940.00")
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_broker_rejection_releases_cash():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def rejected_order(symbol: str, qty: int, price: Decimal) -> int:
        raise BrokerRejectedError("DSE rejected: price outside band")

    with pytest.raises(BrokerRejectedError):
        await rejected_order(make_tick(ts=1_000, ask="150.00", symbol="BXPHARMA"), 100, 900)

    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")
    assert portfolio.unsettled_share_lots == []
    assert portfolio.pending_qty == {}
    assert portfolio.unknown_orders == []


@pytest.mark.asyncio
async def test_connection_loss_holds_cash_as_unknown_until_resolved():
    """A dropped connection may still have filled at the exchange, so cash stays reserved."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def failing_broker_order(symbol: str, qty: int, price: Decimal) -> int:
        await asyncio.sleep(0.005)
        raise ConnectionResetError("DSE FIX gateway timeout")

    with pytest.raises(ConnectionResetError):
        await failing_broker_order(make_tick(ts=1_000, ask="150.00", symbol="BXPHARMA"), 100, 900)

    assert len(portfolio.unknown_orders) == 1
    assert portfolio.reserved_cash == Decimal("15045.00")  # 100 x 150.00 + 0.30% commission
    assert portfolio.pending_qty == {"BXPHARMA": 100}  # still counts toward exposure

    await portfolio.resolve_unknown(portfolio.unknown_orders[0].order_id, 0)  # broker query: not filled
    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")
    assert portfolio.pending_qty == {}


@pytest.mark.asyncio
async def test_resolve_unknown_records_a_fill_the_broker_confirms():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def slow_broker_order(symbol: str, qty: int, price: Decimal) -> int:
        await asyncio.sleep(10)
        return qty

    task = asyncio.create_task(slow_broker_order(make_tick(ts=1_000, ask="150.00", symbol="BXPHARMA"), 100, 900))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(portfolio.unknown_orders) == 1
    await portfolio.resolve_unknown(portfolio.unknown_orders[0].order_id, 100)  # broker confirms 100
    assert portfolio.unknown_orders == []
    assert portfolio.unsettled_share_lots[0].qty == 100
    assert portfolio.reserved_cash == Decimal("0.00")
    assert portfolio.pending_qty == {}


@pytest.mark.asyncio
async def test_partial_fill_records_filled_shares_and_releases_the_rest():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))

    @async_risk_guard(portfolio)
    async def partial(symbol: str, qty: int, price: Decimal) -> int:
        return 60  # of 100 ordered

    await partial(make_tick(ts=1_000, ask="100.00"), 100, 900)

    assert portfolio.unsettled_share_lots[0].qty == 60
    # reserved 10,030.00 for 100; 60 filled costs 6,018.00; 4,012.00 released
    assert portfolio.settled_cash == Decimal("93982.00")
    assert portfolio.reserved_cash == Decimal("0.00")
    assert portfolio.pending_qty == {}


@pytest.mark.asyncio
async def test_invalid_broker_answer_is_treated_as_unknown():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))

    @async_risk_guard(portfolio)
    async def bad_answer(symbol: str, qty: int, price: Decimal) -> str:
        return "FILLED"

    with pytest.raises(ValueError, match="filled quantity"):
        await bad_answer(make_tick(ts=1_000, ask="100.00"), 10, 900)
    assert len(portfolio.unknown_orders) == 1


@pytest.mark.asyncio
async def test_successful_fill_writes_an_audit_row():
    queue: asyncio.Queue = asyncio.Queue()
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"), audit_queue=queue
    )

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> int:
        return qty

    await buy(make_tick(ts=1_000, ask="100.00"), 10, 900)
    event = queue.get_nowait()
    assert event.event_type == "ORDER_FILLED"
    assert event.qty == 10
    assert event.symbol == "GP"
    assert event.order_id > 0


@pytest.mark.asyncio
async def test_order_ids_are_unique_across_portfolios():
    queue_a: asyncio.Queue = asyncio.Queue()
    queue_b: asyncio.Queue = asyncio.Queue()
    ids = []
    for queue in (queue_a, queue_b):
        portfolio = AsyncPortfolioState(
            initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"), audit_queue=queue
        )

        @async_risk_guard(portfolio)
        async def buy(symbol: str, qty: int, price: Decimal) -> int:
            return qty

        await buy(make_tick(ts=1_000, ask="100.00"), 1, 900)
        ids.append(queue.get_nowait().order_id)
    assert ids[0] != ids[1]


@pytest.mark.asyncio
async def test_dead_audit_writer_blocks_decorator_reservation():
    def writer_died() -> None:
        raise RuntimeError("audit writer died")

    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"), audit_guard=writer_died
    )

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> int:
        return qty

    with pytest.raises(RuntimeError, match="audit writer died"):
        await buy(make_tick(ts=1_000, ask="100.00"), 10, 900)
    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_position_size_and_drawdown_circuit_breakers():
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"),
        max_position_pct=Decimal("0.20"),  # Max 20,000 BDT per ticker
        max_drawdown_pct=Decimal("0.10"),  # Max 10% drawdown
    )

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> int:
        return qty

    # 1. 150 x 150 = 22,500 BDT > 20% of 100,000 -> position limit
    with pytest.raises(PositionLimitExceededError):
        await place_order(make_tick(ts=1_000, ask="150.00", symbol="SQURPHARMA"), 150, 900)

    # 2. Simulate 12% portfolio drawdown -> drawdown breaker on the next ordered tick
    portfolio.settled_cash = Decimal("88000.00")
    with pytest.raises(MaxDrawdownCircuitBreakerError):
        await place_order(make_tick(ts=2_000, ask="150.00", symbol="SQURPHARMA"), 10, 1_900)


def test_float_price_is_rejected_when_the_tick_is_built():
    """A float price cannot reach the decorator: MarketTick refuses it first."""
    with pytest.raises(TypeError):
        MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=1,
                   bid=100.0, ask=Decimal("100.10"))


@pytest.mark.asyncio
async def test_decorator_rejects_negative_qty_without_moving_cash():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> int:
        return qty

    with pytest.raises(ValueError):
        await place_order(make_tick(ts=1_000), -100, 900)
    assert portfolio.settled_cash == Decimal("100000.00")
    assert portfolio.reserved_cash == Decimal("0.00")


def test_unknown_category_cannot_reach_the_decorator():
    """Category is taken from the tick, so an unknown value fails when the tick is built."""
    with pytest.raises(ValueError):
        MarketTick(symbol="GP", category="z", exchange_ts_ms=1,
                   bid=Decimal("99.90"), ask=Decimal("100.00"))


@pytest.mark.asyncio
async def test_decorator_rejects_look_ahead_order_using_the_tick_gate():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> int:
        return qty

    with pytest.raises(TemporalLeakageError, match="Look-ahead"):
        await place_order(make_tick(ts=1_000), 1, 1_000)
    assert portfolio.settled_cash == Decimal("100000.00")


@pytest.mark.asyncio
async def test_decorator_rejects_out_of_order_tick():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> int:
        return qty

    await place_order(make_tick(ts=2_000), 1, 1_000)
    with pytest.raises(TemporalLeakageError, match="Out-of-order"):
        await place_order(make_tick(ts=1_500), 1, 1_000)


@pytest.mark.asyncio
async def test_decorator_refuses_penalised_fill_above_upper_circuit():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("500000.00"))

    @async_risk_guard(portfolio)
    async def place_order(symbol: str, qty: int, price: Decimal) -> int:
        return qty

    tick = MarketTick(symbol="GP", category=ShareCategory.A, exchange_ts_ms=1_000,
                      bid=Decimal("99.90"), ask=Decimal("100.00"), ask_volume=50,
                      upper_circuit=Decimal("100.20"))
    with pytest.raises(CircuitBreakerLiquidityError, match="above upper circuit"):
        await place_order(tick, 100, 900)
    assert portfolio.settled_cash == Decimal("500000.00")


@pytest.mark.asyncio
async def test_category_z_lot_through_decorator_matures_at_t3():
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("0.50"))

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> int:
        return qty

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
    async def place_order(symbol: str, qty: int, price: Decimal) -> int:
        return qty

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
    async def buy(symbol: str, qty: int, price: Decimal) -> int:
        await asyncio.sleep(0.01)  # broker round-trip: every order is in flight at once
        return qty

    tick = make_tick(ts=1_000, ask="100.00")
    results = await asyncio.gather(
        *(buy(tick, 200, 900) for _ in range(4)),
        return_exceptions=True,
    )
    fills = [r for r in results if r == 200]
    limits = [r for r in results if isinstance(r, PositionLimitExceededError)]
    assert len(fills) == 1
    assert len(limits) == 3
    assert portfolio.pending_qty == {}
    assert portfolio.reserved_cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_fill_during_full_audit_queue_is_recorded_and_next_fill_fails_closed():
    """Audit M1: a fill whose audit row cannot be queued still returns normally; the next fill refuses."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"), audit_queue=queue
    )

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> int:
        queue.put_nowait("other producer")  # the queue fills during the broker call
        return qty

    assert await buy(make_tick(ts=1_000, ask="100.00"), 10, 900) == 10
    assert portfolio.unsettled_share_lots[0].qty == 10
    with pytest.raises(RuntimeError, match="audit queue full"):
        await buy(make_tick(ts=2_000, ask="100.00"), 1, 1_900)


@pytest.mark.asyncio
async def test_resolve_unknown_settles_only_the_named_order():
    """Audit M2: resolution is by order id, so a stale or repeated call cannot settle another order."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))

    @async_risk_guard(portfolio)
    async def lost(symbol: str, qty: int, price: Decimal) -> int:
        raise ConnectionResetError("lost")

    tick = make_tick(ts=1_000, ask="100.00")
    for _ in range(2):
        with pytest.raises(ConnectionResetError):
            await lost(tick, 10, 900)

    first, second = [o.order_id for o in portfolio.unknown_orders]
    await portfolio.resolve_unknown(second, 5)
    assert [o.order_id for o in portfolio.unknown_orders] == [first]
    with pytest.raises(KeyError):
        await portfolio.resolve_unknown(second, 5)  # already settled
    with pytest.raises(KeyError):
        await portfolio.resolve_unknown(999, 0)  # unknown id


@pytest.mark.asyncio
async def test_parked_audit_row_is_sent_by_flush_audit():
    """Audit F1: a parked row must reach the log through flush_audit, not sit in memory."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"), audit_queue=queue
    )

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> int:
        queue.put_nowait("other producer")
        return qty

    await buy(make_tick(ts=1_000, ask="100.00"), 10, 900)  # the row is parked
    queue.get_nowait()  # the writer drains the queue
    portfolio.flush_unsent_audit()
    assert not portfolio.has_unsent_audit()
    assert queue.get_nowait().event_type == "ORDER_FILLED"


@pytest.mark.asyncio
async def test_shut_down_queue_parks_the_row_and_refuses_the_next_fill():
    """Audit F2: put_nowait on a shut-down queue must park the row, not lose it or raise after the fill."""
    if not hasattr(asyncio.Queue, "shutdown"):
        pytest.skip("asyncio.Queue.shutdown needs Python 3.13+")
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    queue.shutdown()
    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"), audit_queue=queue
    )

    @async_risk_guard(portfolio)
    async def buy(symbol: str, qty: int, price: Decimal) -> int:
        return qty

    assert await buy(make_tick(ts=1_000, ask="100.00"), 10, 900) == 10
    assert len(portfolio._unsent_audit) == 1
    with pytest.raises(RuntimeError, match="audit queue full"):
        await buy(make_tick(ts=2_000, ask="100.00"), 1, 1_900)


@pytest.mark.asyncio
async def test_partial_resolve_releases_only_the_unfilled_cash_and_leaves_other_orders():
    """Audit F3: 10 shares at 100.00 reserve 1,003.00; filling 5 releases 501.50 of it."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))

    @async_risk_guard(portfolio)
    async def lost(symbol: str, qty: int, price: Decimal) -> int:
        raise ConnectionResetError("lost")

    tick = make_tick(ts=1_000, ask="100.00")
    for _ in range(2):
        with pytest.raises(ConnectionResetError):
            await lost(tick, 10, 900)

    _, second = [o.order_id for o in portfolio.unknown_orders]
    await portfolio.resolve_unknown(second, 5)
    assert portfolio.settled_cash == Decimal("98495.50")  # 100,000 - 2 x 1,003.00 + 501.50 refund
    assert portfolio.reserved_cash == Decimal("1003.00")  # the other order is still held
    assert portfolio.pending_qty == {"GP": 10}
    assert portfolio.unsettled_share_lots[0].qty == 5


@pytest.mark.asyncio
async def test_resolve_unknown_rejects_a_boolean_id():
    """Audit F4: True equals 1 in Python; a boolean must not select order 1."""
    portfolio = AsyncPortfolioState(initial_cash=Decimal("100000.00"), max_position_pct=Decimal("1.00"))

    @async_risk_guard(portfolio)
    async def lost(symbol: str, qty: int, price: Decimal) -> int:
        raise ConnectionResetError("lost")

    with pytest.raises(ConnectionResetError):
        await lost(make_tick(ts=1_000, ask="100.00"), 10, 900)
    with pytest.raises(ValueError):
        await portfolio.resolve_unknown(True, 0)
    assert len(portfolio.unknown_orders) == 1
