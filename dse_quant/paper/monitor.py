"""Monitoring summary over the paper journal, plus the automatic alerts."""
import json
from collections import Counter
from pathlib import Path

STALE_ALERT_DAYS = 3


def summarize(journal_path):
    rows = [json.loads(l) for l in Path(journal_path).read_text().splitlines() if l.strip()]
    eq = [r["equity"] for r in rows if r.get("equity") is not None]  # state-error runs log no equity
    peak, mdd = 0.0, 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = max(mdd, 1 - e / peak if peak else 0.0)
    run = best = 0
    for r in rows:
        run = run + 1 if "stale_data" in r.get("gate_reasons", []) else 0
        best = max(best, run)
    reasons = Counter(x for r in rows for x in r.get("gate_reasons", []))
    kills = [r["asof"] for r in rows if r.get("kill")]
    alerts = []
    if best >= STALE_ALERT_DAYS:
        alerts.append(f"data feed broken: {best} consecutive stale days")
    if kills:
        alerts.append(f"kill switch fired on {kills[0]}: exit list written, no new signals")
    errors = sum(bool(r.get("alerts")) for r in rows)
    if errors:
        alerts.append(f"{errors} runs had input errors")
    return {"runs": len(rows), "first": rows[0]["asof"] if rows else None, "last": rows[-1]["asof"] if rows else None,
            "gate_open_days": sum(bool(r.get("gate_open")) for r in rows), "gate_reasons": dict(reasons),
            "regimes": dict(Counter(r.get("regime") for r in rows)), "equity_last": eq[-1] if eq else None,
            "max_drawdown": mdd, "max_consecutive_stale": best, "alerts": alerts}
