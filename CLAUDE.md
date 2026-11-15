## Model routing
- Consult the Opus 5.5 advisor before a plan locks, after the same error twice, and before a task is marked done.
- Use Haiku 5.5 for orchestration and simple edits (<30 lines). Once the plan locks, delegate complex implementations to the Sonnet 5.5 `coder` subagent.
- Use `search`, `grep` and `docs` (Haiku, read-only) for lookups. Run `quant-verifier` before deploying quant changes.

## DSE Quantitative Risk & Execution Invariants (Mandatory)
- **Currency & Math**: Strictly `decimal.Decimal` for all BDT prices, commissions (`0.0030` = 0.30%), and tick sizes (`0.10 BDT` rounded via `ROUND_CEILING` on buy reservations). `float` is forbidden.
- **Settlement Law**: Segregate `settled_cash` from `unsettled_cash` and `matured_positions` from `unsettled_shares` (T+2 for Cat A/B/G/N; T+3 for Cat Z). Intraday shorting or selling unsettled shares must raise `SettlementViolationError`.
- **Temporal & Lock Law**: Enforce `tick.exchange_ts_ms >= last_exchange_ts_ms` and `fill_ts >= signal_ts + 15ms`. Never perform file/network I/O inside `async with self._lock:`—emit `AuditEvent` objects via `asyncio.Queue.put_nowait`.
- **Verification Gate**: Every change to `async_risk_guard.py` or `dse_paper_harness.py` must be audited by `@quant-verifier` and pass `pytest test_async_risk_guard.py test_quant_verifier_dse.py --asyncio-mode=strict`.
- **`dse_quant/` status (since 560c238, 2026-11-11)**: the money path (cash, costs, fill prices, basis, settlement) is `Decimal` at 0.30%, taken from `async_risk_guard.DSE_COMMISSION_RATE`. One `float` still feeds money: the square-root impact term in `backtest/costs.py` is computed in `float`, then converted, and sets the cost, the buy quantity and the cash spent in the backtest and the paper book. The backtest's stop and target exits also compare `float` entry prices. Elsewhere `float` is statistics and reporting (indicators, panels, metrics, `watch.py`, `fundamentals.py`). The backtest uses T+2 for every share (no category history). `docs/PHASE1_SPEC.md` and `docs/PHASE4_PREREG.md` still say 0.40% commission and 0.47% per side with tax and misc; the code charges 0.30% plus impact only. Do not change any of this unasked.
