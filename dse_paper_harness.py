"""
dse_paper_harness.py
Async WebSocket paper-trading execution harness wrapping async_risk_guard.py
with non-blocking asyncio.Queue JSONL audit logging.
"""

from __future__ import annotations

import asyncio
import json
import queue as thread_queue
import threading
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


def _append_line(fp, line: str) -> None:
    fp.write(line)
    fp.flush()


def _resolve(fut: "asyncio.Future[None]", outcome: Optional[BaseException]) -> None:
    if fut.done():  # already timed out or cancelled by the caller
        return
    if outcome is None:
        fut.set_result(None)
    else:
        fut.set_exception(outcome)


class _Pending:
    """One submitted row. The writer thread sets finished and error before the loop hears about it."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.future: "asyncio.Future[None]" = loop.create_future()
        self.finished = threading.Event()
        self.error: Optional[BaseException] = None


class _DiskWriter:
    """Owns the log file on a daemon thread.

    The event loop never touches the file, so a stalled write cannot freeze the loop
    (audit finding 1). A daemon thread cannot block interpreter exit (finding 3).
    """

    def __init__(self, log_path: Path, loop: asyncio.AbstractEventLoop) -> None:
        # Opened here, in start(): an unwritable path fails the session before any fill (audit L2)
        self._fp = log_path.open("a", encoding="utf-8")
        self._loop = loop
        self._requests: thread_queue.Queue = thread_queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="audit-disk-writer")
        self._thread.start()

    def _run(self) -> None:
        fp = self._fp
        while True:
            req = self._requests.get()
            if req is None:
                break
            line, pend = req
            outcome: Optional[BaseException] = None
            try:
                _append_line(fp, line)
            except BaseException as exc:
                outcome = exc
            pend.error = outcome
            pend.finished.set()
            try:
                self._loop.call_soon_threadsafe(_resolve, pend.future, outcome)
            except RuntimeError:
                pass  # the loop has closed; nobody is waiting on this row any more
        fp.close()

    def submit(self, line: str) -> _Pending:
        pend = _Pending(self._loop)
        self._requests.put((line, pend))
        return pend

    def close(self) -> None:
        """Non-blocking: the writer thread closes the file after draining what it has."""
        self._requests.put(None)


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

    def __init__(
        self,
        log_path: Path = Path("dse_paper_audit.jsonl"),
        write_timeout_s: float = 1.0,  # shortcut: fills can run for up to this long during a stuck write; upgrade by refusing fills while a write is in flight
    ) -> None:
        self.queue: asyncio.Queue[Optional[AuditEvent]] = asyncio.Queue(maxsize=10_000)
        self.log_path = log_path
        self.write_timeout_s = write_timeout_s
        self._worker: Optional[asyncio.Task[None]] = None
        self._writer: Optional[_DiskWriter] = None
        self.events_written: int = 0
        # Set in the same step that a write raises or times out, so no fill can run unseen (audit M1)
        self.failure: Optional[BaseException] = None

    def start(self) -> None:
        self._writer = _DiskWriter(self.log_path, asyncio.get_running_loop())
        self._worker = asyncio.create_task(self._drain_loop())
        # Release the file however the worker ends, including cancellation before its first step
        self._worker.add_done_callback(lambda _task: self._writer.close())

    async def put(self, item: Optional[AuditEvent]) -> None:
        """Enqueue without blocking on a dead drain worker (audit M1, M2)."""
        if self.failure is not None:
            raise self.failure
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
        """Raise if a write has failed or the drain worker has ended, so fills do not pile up unseen."""
        if self.failure is not None:
            raise self.failure
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
        assert self._writer is not None
        try:
            while True:
                ev = await self.queue.get()
                if ev is None:
                    self.queue.task_done()
                    break
                try:
                    # A write that stalls past the timeout is a failure, not a silent hang (audit M2)
                    pending = self._writer.submit(json.dumps(asdict(ev)) + "\n")
                    try:
                        await asyncio.wait_for(pending.future, timeout=self.write_timeout_s)
                    except asyncio.TimeoutError:
                        # A blocked loop can let the timer expire after the write finished: trust the writer
                        if not pending.finished.is_set():
                            raise
                        if pending.error is not None:
                            raise pending.error
                except BaseException as exc:
                    if isinstance(exc, asyncio.CancelledError):
                        self.failure = RuntimeError("audit drain cancelled mid-write")  # finding 4
                    else:
                        self.failure = exc
                    raise
                self.events_written += 1
                self.queue.task_done()
        finally:
            self._writer.close()


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


async def _send_parked(portfolio: AsyncPortfolioState, logger: AsyncAuditLogger) -> None:
    """Queue parked audit rows, waiting while the queue is full. Raises if the writer has died."""
    while portfolio.has_unsent_audit():
        logger.check_alive()
        portfolio.flush_unsent_audit()
        if portfolio.has_unsent_audit():
            await asyncio.sleep(0.001)


async def run_paper_session(log_path: Path = Path("dse_paper_audit.jsonl")) -> AsyncPortfolioState:
    # The log is append-only: a rerun adds rows rather than erasing the previous session's audit trail
    logger = AsyncAuditLogger(log_path=log_path)
    logger.start()

    portfolio = AsyncPortfolioState(
        initial_cash=Decimal("500000.00"),
        max_position_pct=Decimal("0.30"),
        max_drawdown_pct=Decimal("0.10"),
        audit_queue=logger.queue,
        audit_guard=logger.check_alive,
    )

    staged: Dict[str, List[StagedOrder]] = {}
    try:
        await _run_ticks(portfolio, logger, staged)
    finally:
        try:
            await _send_parked(portfolio, logger)  # rows parked by the decorator path must reach the log
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
        await _send_parked(portfolio, logger)
        # 1. Execute previously staged orders once the latency window has elapsed
        pending = staged.get(tick.symbol, [])
        still_waiting: List[StagedOrder] = []
        for order in pending:
            if tick.exchange_ts_ms < order.signal_ts_ms + MIN_NETWORK_LATENCY_MS:
                still_waiting.append(order)  # retry on a later tick of this symbol
                continue
            logger.check_alive()  # per order: no fill may commit on a writer that has already died
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
