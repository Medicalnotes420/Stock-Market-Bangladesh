"""
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

    async def stop(self) -> None:
        if self._worker is not None:
            await self.queue.put(None)
            await self._worker

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
    if log_path.exists():
        log_path.unlink()

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
                await logger.queue.put(
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
