# Rules
- Done = `python -m unittest discover -s tests` shows no new failures (6 errors pre-exist: `dse_quant/data` is untracked). Report pass/fail in one line.
- Don't restate your reasoning in the reply; give the result and the diff summary.
- Reuse helpers in `dse_quant/` and `scripts/` before writing new ones.
- Backtest changes: state the Sharpe/drawdown before and after on the same data.
- Don't change `results/` or `watchlist.txt` unless asked.
- Lookups and quick edits: use a Sonnet/Haiku subagent. Opus for backtest logic.
- Keep model, effort and this file fixed within a session (prompt cache).
- Read `TASKS.md` first in a new session.
