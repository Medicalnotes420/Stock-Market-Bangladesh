"""
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
