"""Monitoring summary over the paper journal, plus the automatic alerts and a local status page."""
import json
from collections import Counter
from html import escape
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


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>DSE Paper Status</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--mute:#666;--line:#ddd;--ok:#1a7f37;--bad:#c62828}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8e8e8;--mute:#999;--line:#333;--ok:#4caf6a;--bad:#ef6b6b}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:960px;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}}.mute{{color:var(--mute)}}.ok{{color:var(--ok)}}.bad{{color:var(--bad)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:16px 0}}
.card{{border:1px solid var(--line);border-radius:8px;padding:10px}}.card b{{display:block;font-size:18px}}
.wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--line);padding:6px;text-align:left;white-space:nowrap}}
</style></head><body><h1>DSE paper trading status</h1><p class="mute">Journal: {runs} runs, {first} to {last}. Strategy: none enabled.</p>
<div class="cards">{cards}</div>{alerts}{watch}<h2>Last {n} runs</h2><div class="wrap"><table>
<tr><th>As of</th><th>Gate</th><th>Reasons</th><th>Regime</th><th>Equity (Tk)</th><th>Alerts</th></tr>{rows}</table></div></body></html>"""


def status_page(journal_path, out_path, last_n=30):
    """Write a self-contained HTML status page. Journal text is escaped: it is data, not markup."""
    rows = [json.loads(l) for l in Path(journal_path).read_text().splitlines() if l.strip()]
    s, r = summarize(journal_path), rows[-1]
    gate = '<span class="ok">OPEN</span>' if r.get("gate_open") else '<span class="bad">CLOSED</span>'
    eq = lambda v: "n/a" if v is None else f"{v:,.0f}"
    cards = "".join(f'<div class="card"><span class="mute">{k}</span><b>{v}</b></div>' for k, v in [
        ("Latest run", escape(r["asof"])), ("Gate", gate), ("Regime", escape(str(r.get("regime")))),
        ("Equity", eq(r.get("equity"))), ("Max drawdown", f"{s['max_drawdown']:.1%}"),
        ("Kill switch", '<span class="bad">FIRED</span>' if r.get("kill") else "off")])
    alerts = "".join(f'<p class="bad">⚠ {escape(a)}</p>' for a in s["alerts"] + r.get("alerts", []))
    bk = r.get("book")
    if bk:  # paper-tracked strategy: positions, today's fills, orders for tomorrow
        alerts += (f'<h2>Paper strategy: {escape(r.get("strategy", ""))}</h2><p class="mute">Tracked on paper only '
                   '(WEAK in docs/SECRETS_RESULTS.md). Orders are what the rule would do next session; not advice.</p>'
                   + (f'<p class="bad">STOPPED: {escape(bk["stopped"])}. Exits only.</p>' if bk["stopped"] else "")
                   + f'<p>Cash Tk {bk["cash"]:,.0f} · Positions: '
                   + (escape(", ".join(f"{t} {q:,}" for t, q in bk["positions"].items())) or "none")
                   + "<br>Fills today: " + (escape("; ".join(f"{f['side']} {f['ticker']} {f['qty']:,} @ {f['price']}"
                                                         for f in r.get("fills", []))) or "none")
                   + "<br>Orders for next session: " + (escape("; ".join(f"{o['side']} {o['ticker']} {o['qty']:,} ({o['reason']})"
                                                                     for o in r.get("orders", []))) or "none")
                   + "</p>")
    yes = lambda b, bad=True: f'<span class="{"bad" if bad else "ok"}">yes</span>' if b else "no"
    w = r.get("watchlist") or {}
    watch = "" if not w else (
        '<h2>Watchlist</h2><div class="wrap"><table><tr><th>Stock</th><th>Last bar</th><th>Close (Tk)</th>'
        '<th>Change</th><th>Lower lock</th><th>Upper lock</th><th>20-day value (Tk)</th><th>Eligible</th>'
        '<th>Unexplained gap (20d)</th></tr>' + "".join(
            f"<tr><td>{escape(t)}</td><td>{escape(v['last_bar'])}</td><td>{v['close']:,.2f}</td>"
            f"<td>{'n/a' if v['change'] is None else format(v['change'], '+.2%')}</td>"
            f"<td>{yes(v['lower_lock'])}</td><td>{yes(v['upper_lock'], bad=False)}</td><td>{eq(v['adtv20'])}</td>"
            f"<td>{'yes' if v['eligible'] else '<span class=\"mute\">no (below liquidity floor or filter)</span>'}</td>"
            f"<td>{yes(v['gap_20d'])}</td></tr>" for t, v in w.items()) + "</table></div>"
        + '<h2>Author\'s indicators and rule flags</h2><p class="mute">From "My Secret Series" '
          '(docs/SECRETS_LEARNINGS.md). The rules are the author\'s; how they did in backtests is in '
          'docs/SECRETS_RESULTS.md. Not advice.</p><div class="wrap"><table><tr><th>Stock</th><th>RSI</th>'
          '<th>Money Flow</th><th>Aroon Up</th><th>ADX (+DI / −DI)</th><th>Bollinger width %</th>'
          '<th>Flags</th></tr>' + "".join(
            f"<tr><td>{escape(t)}</td><td>{v.get('rsi', 'n/a')}</td><td>{v.get('mfi', 'n/a')}</td>"
            f"<td>{v.get('aroon_up', 'n/a')}</td><td>{v.get('adx', 'n/a')} ({v.get('plus_di', 'n/a')} / "
            f"{v.get('minus_di', 'n/a')})</td><td>{v.get('bb_width', 'n/a')}</td>"
            f"<td style=\"white-space:normal\">{'<br>'.join(escape(x) for x in v.get('flags', [])) or 'none'}</td></tr>"
            for t, v in w.items()) + "</table></div>")
    body = "".join(
        f"<tr><td>{escape(x['asof'])}</td><td>{'OPEN' if x.get('gate_open') else 'CLOSED'}</td>"
        f"<td>{escape(', '.join(x.get('gate_reasons', [])))}</td><td>{escape(str(x.get('regime')))}</td>"
        f"<td>{eq(x.get('equity'))}</td><td>{escape('; '.join(x.get('alerts', [])))}</td></tr>"
        for x in reversed(rows[-last_n:]))
    Path(out_path).write_text(PAGE.format(runs=s["runs"], first=escape(str(s["first"])), last=escape(str(s["last"])),
                                          cards=cards, alerts=alerts, watch=watch, n=min(last_n, len(rows)), rows=body),
                              encoding="utf-8")
