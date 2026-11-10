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
async def test_failed_write_is_visible_before_any_fill(tmp_path, monkeypatch):
    """Audit M1/M3: a write that raises in the thread must block the next fill, not just the worker."""
    import dse_paper_harness
    from async_risk_guard import AuditEvent

    def disk_full(fp, line):
        raise OSError("disk full")

    monkeypatch.setattr(dse_paper_harness, "_append_line", disk_full)
    logger = dse_paper_harness.AsyncAuditLogger(log_path=tmp_path / "a.jsonl")
    logger.start()
    await logger.put(AuditEvent(event_type="X", exchange_ts_ms=1, symbol="GP", side="BUY",
                                qty=1, exec_price="1", commission_bdt="0",
                                settled_cash_after_bdt="0"))
    await asyncio.wait({logger._worker}, timeout=2)  # deterministic: wait for the writer to fail
    with pytest.raises(OSError, match="disk full"):
        logger.check_alive()
    with pytest.raises(OSError, match="disk full"):
        await logger.put(None)
    with pytest.raises(OSError, match="disk full"):
        await asyncio.wait_for(logger.stop(), timeout=1)


@pytest.mark.asyncio
async def test_stalled_write_times_out_and_blocks_further_work(tmp_path, monkeypatch):
    """Audit M2/M3: a write that never returns must surface as a timeout, not a silent hang."""
    import dse_paper_harness
    import threading
    from async_risk_guard import AuditEvent

    gate = threading.Event()

    def stall(fp, line):
        gate.wait(5)

    monkeypatch.setattr(dse_paper_harness, "_append_line", stall)
    logger = dse_paper_harness.AsyncAuditLogger(log_path=tmp_path / "a.jsonl", write_timeout_s=0.05)
    logger.start()
    try:
        await logger.put(AuditEvent(event_type="X", exchange_ts_ms=1, symbol="GP", side="BUY",
                                    qty=1, exec_price="1", commission_bdt="0",
                                    settled_cash_after_bdt="0"))
        await asyncio.wait({logger._worker}, timeout=2)  # deterministic: wait for the timeout
        with pytest.raises(TimeoutError):
            logger.check_alive()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(logger.stop(), timeout=1)
    finally:
        gate.set()


def test_unwritable_log_path_fails_at_start_not_at_first_row(tmp_path):
    """Audit L2: a bad log path must stop the session before any fill can commit."""
    from dse_paper_harness import AsyncAuditLogger

    logger = AsyncAuditLogger(log_path=tmp_path / "missing_dir" / "a.jsonl")

    async def run() -> None:
        with pytest.raises(FileNotFoundError):
            logger.start()
        assert logger._writer is None and logger._worker is None  # nothing half-started

    asyncio.run(run())


@pytest.mark.asyncio
async def test_cancelled_before_first_step_still_releases_the_file(tmp_path):
    """Audit low: cancelling the worker before its first step must not leak the thread or handle."""
    from dse_paper_harness import AsyncAuditLogger

    logger = AsyncAuditLogger(log_path=tmp_path / "a.jsonl")
    logger.start()
    writer = logger._writer
    logger._worker.cancel()
    with pytest.raises(RuntimeError, match="cancelled"):
        await asyncio.wait_for(logger.stop(), timeout=2)
    writer._thread.join(timeout=2)
    assert not writer._thread.is_alive()
    assert writer._fp.closed


@pytest.mark.asyncio
async def test_session_with_failing_disk_raises_and_does_not_hang(tmp_path, monkeypatch):
    """Audit finding 2: a session whose every log write fails must raise promptly, not hang."""
    import dse_paper_harness

    def disk_full(fp, line):
        raise OSError("disk full")

    monkeypatch.setattr(dse_paper_harness, "_append_line", disk_full)
    with pytest.raises(OSError, match="disk full"):
        await asyncio.wait_for(
            dse_paper_harness.run_paper_session(log_path=tmp_path / "s.jsonl"), timeout=10
        )


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
