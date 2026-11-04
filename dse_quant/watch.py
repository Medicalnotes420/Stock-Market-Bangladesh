"""Single-share price watcher: daily OHLCV in (stocknow fetch or an uploaded CSV), one HTML page out.

Descriptive only: trend, indicators and rule alerts on the data given. Not investment advice."""
import json
import re
import urllib.request
from html import escape
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from dse_quant.indicators import bollinger, macd, rsi, sma
from dse_quant.paper.harness import author_flags

# What the backtest found for each "My Secret Series" flag (docs/SECRETS_RESULTS.md); key = flag's first word
VERDICT = {"#1/#13": "REJECTED: lost money out of sample (S1)", "#1": "REJECTED: lost money out of sample (S1)",
           "#25/#30": "REJECTED: lost money out of sample (S25)",
           "#67": "REJECTED on its own (S67 without the #96 filter)",
           "#96": "WEAK: only passed with the market regime filter on (S67 + #96); not good enough to trade",
           "#2": "exit used by the WEAK S67 rule", "#3": "exit used by the WEAK S67 rule",
           "#21": "not tested on its own", "#31": "not tested on its own", "#39": "not tested on its own",
           "#38": "not tested on its own (filter)"}

EXPORT_URL = "https://stocknow.com.bd/api/v1/eod/export"  # undocumented; found from the site's own download button
COLS = ["open", "high", "low", "close", "volume"]
ALIASES = {"date": "date", "date_ymd": "date", "tradingdate": "date", "open": "open", "openprice": "open",
           "high": "high", "highprice": "high", "low": "low", "lowprice": "low", "close": "close",
           "closingprice": "close", "closeprice": "close", "ltp": "close", "volume": "volume", "vol": "volume",
           "ticker": "symbol", "symbol": "symbol", "tradingcode": "symbol"}
MIN_ROWS = 30


def _clean(df, source):
    """Validate and normalise rows from any source. Raises ValueError naming the problem; never fills gaps."""
    missing = [c for c in ["date"] + COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{source}: missing column(s) {', '.join(missing)}")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"].astype(str), errors="coerce", format="mixed")
    for c in COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad = df[df[["date"] + COLS].isna().any(axis=1)]
    if len(bad):
        raise ValueError(f"{source}: non-numeric or missing value in row {bad.index[0] + 2}")
    if (df.high < df.low).any():
        raise ValueError(f"{source}: high below low on {df.loc[df.high < df.low, 'date'].iloc[0]:%Y-%m-%d}")
    df = df.drop_duplicates("date", keep="last").sort_values("date").set_index("date")[COLS]
    if len(df) < MIN_ROWS:
        raise ValueError(f"{source}: only {len(df)} rows, need at least {MIN_ROWS}")
    return df


def load_csv(path):
    """Read an uploaded daily OHLCV CSV. Headers are matched ignoring case, spaces and underscores; accepted
    aliases: Date/Date_YMD/Trading Date, Close/Closing Price/LTP, Vol, Open Price, High Price, Low Price.
    A Ticker/Symbol column is allowed but the file must hold one share only."""
    df = pd.read_csv(path)
    df.columns = [ALIASES.get(re.sub(r"[\s_]", "", c.lower()), c) for c in df.columns]
    if "symbol" in df.columns and df.symbol.nunique() > 1:
        raise ValueError(f"{path}: holds {df.symbol.nunique()} shares, upload one share per file")
    return _clean(df, str(path))


INSTRUMENTS_URL = "https://stocknow.com.bd/api/v1/instruments"


def _get(url, body=None, timeout=120):
    req = urllib.request.Request(url, body and json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "dse-watch/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def export_rows(symbols, start, end, adjusted):
    """Raw stocknow export: DataFrame of symbol, date, open, high, low, close, volume (may be empty)."""
    data = _get(EXPORT_URL, {"symbols": list(symbols), "start_date": str(start), "end_date": str(end),
                             "adjusted": adjusted})
    if "rows" not in data:
        raise ValueError(f"stocknow: unexpected reply {str(data)[:200]}")
    return pd.DataFrame(data["rows"])


def instruments():
    """stocknow's instrument list with each one's latest session (code, category, close, value in Tk mn, updated_at)."""
    data = _get(INSTRUMENTS_URL)
    rows = list(data.values()) if isinstance(data, dict) else data
    if not rows or "code" not in rows[0]:
        raise ValueError(f"stocknow: unexpected instruments reply {str(data)[:200]}")
    return pd.DataFrame(rows)


def fetch(symbols, start, end, adjusted=True):
    """Daily bars for up to 1000 DSE symbols from stocknow, as {symbol: DataFrame}. Symbols with no rows are absent."""
    df = export_rows(symbols, start, end, adjusted)
    if df.empty:
        return {}
    return {s: _clean(g.reset_index(drop=True), f"stocknow {s}") for s, g in df.groupby("symbol")}


def _cross(a, b):
    """+1 if a crossed above b on the last bar, -1 if below, 0 otherwise."""
    d = (a - b).iloc[-2:]
    if d.isna().any():
        return 0
    return 1 if d.iloc[0] <= 0 < d.iloc[1] else -1 if d.iloc[0] >= 0 > d.iloc[1] else 0


def analyze(df, above=None, below=None):
    c = df.close
    s20, s50 = sma(c, 20), sma(c, 50)
    up, mid, lo, _ = bollinger(c)
    r = rsi(c)
    ml, ms = macd(c)
    last, day = c.iloc[-1], df.index[-1].strftime("%Y-%m-%d")
    chg = {f"{n}d": float(last / c.iloc[-1 - n] - 1) for n in (1, 5, 20, 60) if len(c) > n}
    if pd.notna(s50.iloc[-1]):
        trend = ("up" if last > s20.iloc[-1] > s50.iloc[-1] else
                 "down" if last < s20.iloc[-1] < s50.iloc[-1] else "sideways")
    else:
        trend = "up" if last > s20.iloc[-1] else "down" if last < s20.iloc[-1] else "sideways"
    vol = float(np.log(c).diff().iloc[-20:].std() * np.sqrt(240))  # DSE trades ~240 sessions a year
    alerts = []

    def rule(name, fired, value):
        alerts.append({"rule": name, "fired": bool(fired), "value": value, "date": day})

    for n, s in (("SMA20", s20), ("SMA50", s50)):
        x = _cross(c, s)
        rule(f"Close crosses above {n}", x == 1, f"{last:,.2f} vs {s.iloc[-1]:,.2f}" if pd.notna(s.iloc[-1]) else "n/a")
        rule(f"Close crosses below {n}", x == -1, f"{last:,.2f} vs {s.iloc[-1]:,.2f}" if pd.notna(s.iloc[-1]) else "n/a")
    rule("RSI(14) above 70 (overbought)", r.iloc[-1] > 70, f"{r.iloc[-1]:.1f}")
    rule("RSI(14) below 30 (oversold)", r.iloc[-1] < 30, f"{r.iloc[-1]:.1f}")
    x = _cross(ml, ms)
    rule("MACD crosses above signal", x == 1, f"{ml.iloc[-1]:.2f} vs {ms.iloc[-1]:.2f}")
    rule("MACD crosses below signal", x == -1, f"{ml.iloc[-1]:.2f} vs {ms.iloc[-1]:.2f}")
    if above is not None:
        rule(f"Close above {above:,.2f}", last > above, f"{last:,.2f}")
    if below is not None:
        rule(f"Close below {below:,.2f}", last < below, f"{last:,.2f}")
    # shortcut: turnover approximated as close x volume (stocknow gives no value column); only #38 uses it
    one = lambda col: col.to_frame("X")
    p = SimpleNamespace(high=one(df.high), low=one(df.low), close=one(c), value=one(c * df.volume))
    secrets = [{"flag": f, "verdict": VERDICT.get(f.split()[0], "not tested")} for f in author_flags(p, "X")["flags"]]
    return {"date": day, "close": float(last), "change": chg, "trend": trend, "volatility": vol, "secrets": secrets,
            "support": float(df.low.iloc[-20:].min()), "resistance": float(df.high.iloc[-20:].max()),
            "rsi": float(r.iloc[-1]), "alerts": alerts,
            "series": pd.DataFrame({"close": c, "sma20": s20, "sma50": s50, "bb_up": up, "bb_lo": lo,
                                    "rsi": r, "macd": ml, "signal": ms, "hist": ml - ms}).iloc[-250:]}


W, PAD = 900, 6


def _path(s, lo, hi, h):
    """SVG polyline points for series s scaled into [lo, hi] -> [h-PAD, PAD]; NaN breaks the line."""
    n, out, seg = len(s), [], []
    for i, v in enumerate(s.to_numpy()):
        if np.isnan(v):
            if seg:
                out.append(seg)
            seg = []
            continue
        x = PAD + i * (W - 2 * PAD) / max(n - 1, 1)
        seg.append(f"{x:.1f},{h - PAD - (v - lo) / (hi - lo or 1) * (h - 2 * PAD):.1f}")
    if seg:
        out.append(seg)
    return "".join(f'<polyline points="{" ".join(p)}"/>' for p in out)


def _svg(lines, h, lo=None, hi=None, guides=(), label=""):
    vals = pd.concat([s for s, _ in lines]).dropna()
    lo = vals.min() if lo is None else lo
    hi = vals.max() if hi is None else hi
    g = "".join(f'<line x1="0" x2="{W}" y1="{h - PAD - (y - lo) / (hi - lo or 1) * (h - 2 * PAD):.1f}" '
                f'y2="{h - PAD - (y - lo) / (hi - lo or 1) * (h - 2 * PAD):.1f}" class="guide"/>' for y in guides)
    body = "".join(f'<g class="{cls}">{_path(s, lo, hi, h)}</g>' for s, cls in lines)
    return (f'<svg viewBox="0 0 {W} {h}" preserveAspectRatio="none" role="img" aria-label="{escape(label)}">'
            f'{g}{body}</svg>')


def _section(sym, a):
    s = a["series"]
    pct = lambda v: f'<span class="{"ok" if v >= 0 else "bad"}">{v:+.1%}</span>'
    chg = " · ".join(f"{k}: {pct(v)}" for k, v in a["change"].items())
    hist = s["hist"].fillna(0)
    m = max(hist.abs().max(), 1e-9)
    bars = "".join(f'<rect x="{PAD + i * (W - 2 * PAD) / len(hist):.1f}" width="{(W - 2 * PAD) / len(hist) * .8:.1f}" '
                   f'y="{50 - max(v, 0) / m * 44:.1f}" height="{abs(v) / m * 44:.1f}" class="{"hp" if v >= 0 else "hn"}"/>'
                   for i, v in enumerate(hist))
    rows = "".join(f'<tr class="{"fired" if x["fired"] else ""}"><td>{escape(x["rule"])}</td>'
                   f'<td>{"<b class=bad>YES</b>" if x["fired"] else "no"}</td><td>{escape(x["value"])}</td>'
                   f'<td>{escape(x["date"])}</td></tr>' for x in a["alerts"])
    fired = sum(x["fired"] for x in a["alerts"])
    sec = "".join(f'<tr><td>{escape(x["flag"])}</td><td class="{"bad" if x["verdict"].startswith("REJECTED") else ""}">'
                  f'{escape(x["verdict"])}</td></tr>' for x in a["secrets"])
    sec = (f'<h3>My Secret Series rules active today</h3><div class="wrap"><table><tr><th>Author\'s rule</th>'
           f'<th>What the backtest found</th></tr>{sec}</table></div>') if sec else (
        '<p class="mute">My Secret Series: none of the author\'s rules are active today.</p>')
    return (f'<section><h2>{escape(sym)} <span class="mute">· {fired} alert(s)</span></h2>'
            f'<p>Last close <b>Tk {a["close"]:,.2f}</b> on {escape(a["date"])}. Trend: <b>{a["trend"]}</b> '
            f'(close vs 20- and 50-day averages).<br>{chg}<br>20-day volatility {a["volatility"]:.0%} a year · '
            f'Support (20-day low) Tk {a["support"]:,.2f} · Resistance (20-day high) Tk {a["resistance"]:,.2f}</p>'
            f'<p class="mute legend"><i class="k c"></i>Close <i class="k a"></i>SMA20 <i class="k b"></i>SMA50 '
            f'<i class="k bb"></i>Bollinger bands · last {len(s)} sessions</p>'
            + _svg([(s.bb_up, "bb"), (s.bb_lo, "bb"), (s.sma50, "b"), (s.sma20, "a"), (s.close, "c")], 260,
                   label=f"{sym} price chart")
            + f'<p class="mute">RSI(14): {a["rsi"]:.1f} (lines at 30 and 70)</p>'
            + _svg([(s.rsi, "a")], 90, 0, 100, (30, 70), f"{sym} RSI")
            + '<p class="mute legend">MACD <i class="k a"></i>line <i class="k b"></i>signal, bars = histogram</p>'
            + f'<svg viewBox="0 0 {W} 100" preserveAspectRatio="none" role="img" aria-label="{escape(sym)} MACD">'
            f'<g transform="translate(0,0)">{bars}</g></svg>'
            + _svg([(s.macd, "a"), (s.signal, "b")], 100, guides=(0,), label=f"{sym} MACD lines")
            + f'<div class="wrap"><table><tr><th>Rule</th><th>Fired</th><th>Value</th><th>Date</th></tr>{rows}'
            f'</table></div>{sec}</section>')


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>DSE Share Watch</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--mute:#666;--line:#ddd;--ok:#1a7f37;--bad:#c62828;--c:#1a1a1a;--a:#1f6feb;--b:#d97706;--bb:#999}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8e8e8;--mute:#999;--line:#333;--ok:#4caf6a;--bad:#ef6b6b;--c:#e8e8e8;--a:#58a6ff;--b:#f0a542;--bb:#666}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:960px;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:18px;margin:28px 0 4px}}h3{{font-size:15px;margin:16px 0 4px}}.mute{{color:var(--mute)}}.ok{{color:var(--ok)}}.bad{{color:var(--bad)}}
svg{{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:6px;margin:2px 0 6px}}
polyline{{fill:none;stroke-width:1.5;vector-effect:non-scaling-stroke}}.c polyline{{stroke:var(--c)}}.a polyline{{stroke:var(--a)}}
.b polyline{{stroke:var(--b)}}.bb polyline{{stroke:var(--bb);stroke-dasharray:3 3}}.guide{{stroke:var(--line);vector-effect:non-scaling-stroke}}
.hp{{fill:var(--ok)}}.hn{{fill:var(--bad)}}.k{{display:inline-block;width:14px;height:3px;margin:0 4px 3px 10px;vertical-align:middle}}
.k.c{{background:var(--c)}}.k.a{{background:var(--a)}}.k.b{{background:var(--b)}}.k.bb{{background:var(--bb)}}
.wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--line);padding:6px;text-align:left;white-space:nowrap}}
tr.fired td{{font-weight:600}}footer{{margin-top:32px;font-size:13px}}
</style></head><body><h1>DSE share watch</h1><p class="mute">{note}</p>{errors}{sections}
<h2>About the My Secret Series rules</h2><p class="mute">Flags restate the author's rules (docs/SECRETS_LEARNINGS.md).
Tested 2017&ndash;2026 (docs/SECRETS_RESULTS.md): none came near the claimed 90% success, five of six lost money, and the
only WEAK pass (S67 + #96) needs the market regime to be RISK_ON or NEUTRAL. {regime}</p>
<footer class="mute">Descriptive analysis of the uploaded data only. Not investment advice.</footer></body></html>"""


def latest_regime(journal="data/paper/journal.jsonl"):
    """Last market regime the paper run logged, as (asof, regime), or None. This page does not compute it."""
    try:
        r = json.loads(Path(journal).read_text().splitlines()[-1])
        return r["asof"], r["regime"]
    except (OSError, IndexError, KeyError, ValueError):
        return None


def render(results, out_path, note="", errors=(), regime=None):
    """results: {symbol: analyze() output}. errors: messages for shares that could not be analysed.
    regime: (asof, regime) from latest_regime(), shown next to the rule notes."""
    err = "".join(f'<p class="bad">⚠ {escape(e)}</p>' for e in errors)
    reg = (f"Last regime from the paper run: {escape(regime[1])} on {escape(regime[0])}." if regime else
           "No regime available: run scripts/paper_run.py to compute it.")
    html = PAGE.format(note=escape(note), errors=err, regime=reg,
                       sections="".join(_section(k, v) for k, v in results.items()))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(html, encoding="utf-8")
    return out_path
