"""Single-share price watcher: daily OHLCV in (stocknow fetch or an uploaded CSV), one HTML page out.

Descriptive only: trend, indicators and rule alerts on the data given. Not investment advice."""
import json
import re
import urllib.parse
import urllib.request
from html import escape
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from dse_quant.indicators import bollinger, macd, rsi, sma
from dse_quant.paper.harness import author_flags

# What the tests found for each "My Secret Series" flag (docs/SECRETS_RESULTS.md, docs/SECRETS_FORECAST_RESULTS.md);
# key = flag's first word. "Forecast" = the stock's next-days move vs the average stock, 2014 to Nov 2026.
VERDICT = {"#1/#13": "REJECTED: no forecast power, lost money traded (S1)",
           "#1": "REJECTED: no forecast power, lost money traded (S1)",
           "#25/#30": "REJECTED: no forecast power 2014-22, lost money traded (S25)",
           "#67": "REJECTED: no forecast power, lost money traded",
           "#96": "REJECTED: lost 4.3% on fresh 2026 data while DSEX gained 5.3% (S67 + #96)",
           "#2": "SMALL EDGE: stocks lagged the market by ~0.3% over the next 5 days (held 2014-2026)",
           "#3": "no reliable forecast power", "#21": "no reliable forecast power",
           "#31": "OPPOSITE: these stocks beat the market by ~1.6% over the next 5 days (post-hoc finding)",
           "#39": "only 7 cases since 2014; prices kept rising after",
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


NEWS_URL = "https://www.dse.com.bd/company/{}"


def parse_news(html):
    """Company news items embedded in a dse.com.bd company page, newest first: dicts of id, type (Notice, Dividend,
    Financials, Rating), date ('02 Nov 2026'), summary, body. The page is a Next.js app that carries its data as
    JSON strings in self.__next_f.push([1,"..."]) scripts; there is no documented API."""
    text = "".join(json.loads(m) for m in re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html))
    dec, items = json.JSONDecoder(), []
    for m in re.finditer(r'\{"id":"\d+","type":"', text):
        o = dec.raw_decode(text, m.start())[0]
        if o["body"].startswith("$"):  # shortcut: long bodies sit in a separate payload row; summary only for those
            o["body"] = ""
        items.append(o)
    return items


def news(symbol, timeout=60):
    """Latest company news for one DSE share from its dse.com.bd page (see parse_news)."""
    req = urllib.request.Request(NEWS_URL.format(urllib.parse.quote(symbol)), headers={"User-Agent": "dse-watch/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        items = parse_news(r.read().decode("utf-8"))
    if not items:
        raise ValueError(f"dse.com.bd: no news found on the {symbol} page (layout may have changed)")
    return items


def fetch(symbols, start, end, adjusted=True):
    """Daily bars for up to 1000 DSE symbols from stocknow, as {symbol: DataFrame}. Symbols with no rows are absent."""
    df = export_rows(symbols, start, end, adjusted)
    if df.empty:
        return {}
    return {s: _clean(g.reset_index(drop=True), f"stocknow {s}") for s, g in df.groupby("symbol")}


HORIZONS, WINDOW, BAND = (5, 20), 250, (0.10, 0.50, 0.90)
# On days when turnover (close x volume) is >= 2x its prior 20-session average the plain range covered only ~70%;
# x1.3 (fitted on 2014-22) brought it back to 76-84% later (docs/VOLUME_RANGE_RESULTS.md)
WIDEN_AT, WIDEN = 2.0, 1.3
# Unshifted ranges missed below ~2x as often as above; a log shift fitted on 2014-22 evened the misses in 2023-26
# and lifted coverage (docs/RANGE_SKEW_RESULTS.md). Keys must match HORIZONS.
SKEW_SHIFT = {5: 0.01, 20: 0.03}


def forecast(close, horizons=HORIZONS, window=WINDOW, widen=1.0):
    """Price range in h sessions from the share's own past h-session moves (last `window` sessions, overlapping).
    No direction is assumed beyond what history shows: it's a spread of outcomes, not a prediction of up or down.
    `widen` stretches each side away from the middle (in log terms); see WIDEN.
    Coverage on DSE history: scripts/forecast_check.py -> results/forecast_check.csv."""
    lc = np.log(close.dropna().iloc[-window - max(horizons):])
    last, out = float(close.dropna().iloc[-1]), {}
    for h in horizons:
        r = (lc - lc.shift(h)).dropna().iloc[-window:]
        if len(r) < 60:
            continue
        ql, qm, qh = (float(r.quantile(q)) for q in BAND)
        s = SKEW_SHIFT.get(h, 0.0)
        lo, mid, hi = (last * float(np.exp(x - s)) for x in (qm - widen * (qm - ql), qm, qm + widen * (qh - qm)))
        out[h] = {"low": lo, "mid": mid, "high": hi, "p_up": float((r > 0).mean()), "p_flat": float((r == 0).mean()),
                  "n": len(r)}
    return out


FACE_VALUE = 10.0  # shortcut: DSE cash dividends are % of face value, Tk 10 for almost every share; read it per share if one isn't
DIV_RE = re.compile(r"recommended\s+([\d.]+)%\s+cash dividend", re.I)
REC_RE = re.compile(r"record date:?\s*(\d{1,2})(?:st|nd|rd|th)?[.\-/ ]+([A-Za-z]+|\d{1,2})[.\-/ ,]+(\d{4})", re.I)


def upcoming_dividend(items, after):
    """Newest cash-dividend declaration in dse.com.bd news whose record date is after `after` (a Timestamp):
    {"record": Timestamp, "pct": float, "tk": Tk per share} or None. Stock (bonus) dividends are left out: the
    adjusted prices already absorb them."""
    for x in items:
        if x.get("type") != "Dividend":
            continue
        text = f'{x.get("summary", "")} {x.get("body", "")}'
        d, r = DIV_RE.search(text), REC_RE.search(text)
        if not (d and r):
            continue
        day, mon, yr = r.groups()
        rec = pd.to_datetime(f"{day} {mon} {yr}", format="%d %m %Y" if mon.isdigit() else "mixed", dayfirst=True,
                             errors="coerce")
        if pd.notna(rec) and rec > after:
            pct = float(d.group(1))
            return {"record": rec, "pct": pct, "tk": pct / 100 * FACE_VALUE}
    return None


def sessions_until(start, end):
    """DSE sessions (Sun-Thu; holidays not known here) after `start` up to and including `end`."""
    days = pd.date_range(start + pd.Timedelta(days=1), end, freq="D")
    return int(sum(d.dayofweek not in (4, 5) for d in days))  # Friday, Saturday closed


def adjust_for_dividend(a, items):
    """Lower the range for any horizon that passes an upcoming cash-dividend record date: the price drops by about
    the dividend when trading resumes. Mutates a["forecast"]; records what was done in a["dividend"]."""
    div = upcoming_dividend(items, pd.Timestamp(a["date"])) if isinstance(items, list) else None
    if not div or not a.get("forecast"):
        return a
    n = sessions_until(pd.Timestamp(a["date"]), div["record"])
    drop = min(div["tk"] / a["close"], 0.5)
    hit = [h for h in a["forecast"] if n < h]  # trading resumes after the record date, inside the horizon
    for h in hit:
        a["forecast"][h] = {**a["forecast"][h], **{k: a["forecast"][h][k] * (1 - drop) for k in ("low", "mid", "high")}}
    a["dividend"] = {**div, "sessions": n, "drop": drop, "horizons": hit}
    return a


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
    tv = c * df.volume
    tv_ratio = float(tv.iloc[-1] / tv.iloc[-21:-1].mean()) if len(tv) > 20 and tv.iloc[-21:-1].mean() > 0 else np.nan
    return {"date": day, "close": float(last), "change": chg, "trend": trend, "volatility": vol, "secrets": secrets,
            "forecast": forecast(c, widen=WIDEN if tv_ratio >= WIDEN_AT else 1.0), "turnover_ratio": tv_ratio,
            # today's volume vs the 20 sessions before it (today left out so a spike doesn't dilute its own baseline)
            "volume": float(df.volume.iloc[-1]), "vol_avg20": float(df.volume.iloc[-21:-1].mean()),
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
    fc = "".join(f'<tr><td>{h} sessions</td><td>Tk {f["low"]:,.2f} &ndash; {f["high"]:,.2f}</td>'
                 f'<td>Tk {f["mid"]:,.2f}</td><td>{f["p_up"]:.0%}</td></tr>' for h, f in a.get("forecast", {}).items())
    fc = ('<h3>Price range forecast</h3><div class="wrap"><table><tr><th>In</th><th>80% range</th><th>Middle</th>'
          f'<th>Up in past moves</th></tr>{fc}</table></div><p class="mute">From this share\'s own moves over the last '
          f'{WINDOW} sessions, moved down {SKEW_SHIFT[5]:.0%} (5 sessions) and {SKEW_SHIFT[20]:.0%} (20 sessions) '
          'because unshifted ranges missed low twice as often as high. Shifted, on DSE history 2014&ndash;2026 the real '
          'price landed inside 76&ndash;83% of the time with misses about even, but in falling years (2018, 2024) only '
          '66&ndash;75%. A range of likely outcomes, not a prediction of direction.'
          + (f' <b>Widened {WIDEN}&times; today:</b> turnover was {a["turnover_ratio"]:.1f}&times; its 20-day average, '
             'and on such days the plain range held the price only ~70% of the time.'
             if a.get("turnover_ratio", 0) >= WIDEN_AT else '') + _div_note(a) + '</p>' + _score_note(a)) if fc else ""
    sec = "".join(f'<tr><td>{escape(x["flag"])}</td><td class="{"bad" if x["verdict"].startswith("REJECTED") else ""}">'
                  f'{escape(x["verdict"])}</td></tr>' for x in a["secrets"])
    sec = (f'<h3>My Secret Series rules active today</h3><div class="wrap"><table><tr><th>Author\'s rule</th>'
           f'<th>What the backtest found</th></tr>{sec}</table></div>') if sec else (
        '<p class="mute">My Secret Series: none of the author\'s rules are active today.</p>')
    return (f'<section><h2>{escape(sym)} <span class="mute">· {fired} alert(s)</span></h2>'
            f'<p>Last close <b>Tk {a["close"]:,.2f}</b> on {escape(a["date"])}. Trend: <b>{a["trend"]}</b> '
            f'(close vs 20- and 50-day averages).<br>{chg}<br>20-day volatility {a["volatility"]:.0%} a year · '
            f'Support (20-day low) Tk {a["support"]:,.2f} · Resistance (20-day high) Tk {a["resistance"]:,.2f}'
            f'<br>Volume {a["volume"]:,.0f} vs 20-day average {a["vol_avg20"]:,.0f}'
            + (f' ({a["volume"] / a["vol_avg20"]:.1f}x)' if a["vol_avg20"] > 0 else '') + '</p>'
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
            f'</table></div>{fc}{sec}{_news(a)}</section>')


def _div_note(a):
    d = a.get("dividend")
    if not d:
        return ""
    where = (f'so the {" and ".join(f"{h}-session" for h in d["horizons"])} range is lowered by {d["drop"]:.1%}'
             if d["horizons"] else "after both horizons, so the ranges are unchanged")
    return (f' <b>Dividend ahead:</b> {d["pct"]:g}% cash (about Tk {d["tk"]:,.2f} a share at Tk {FACE_VALUE:g} face '
            f'value), record date {d["record"]:%d %b %Y}, about {d["sessions"]} sessions away; the price usually drops '
            f'by the dividend when trading resumes, {where}. Holders receive the cash.')


def _score_note(a):
    sc = a.get("score")
    if sc is None:
        return ""
    if not any(v["checked"] for v in sc.values()):
        return ('<p class="mute">Track record: this page started saving its ranges on 2026-11-05; none has reached '
                'its end date yet.</p>')
    parts = [f'{h} sessions: {v["inside"]} of {v["checked"]} inside ({v["inside"] / v["checked"]:.0%}), '
             f'{v["below"]} below, {v["above"]} above' for h, v in sorted(sc.items()) if v["checked"]]
    return ('<p><b>Track record of this page\'s ranges</b> (saved each morning, checked when due): '
            + "; ".join(parts) + '. An 80% range should hold about 80%.</p>')


def _news(a, n=6):
    if "news" not in a:
        return ""
    if isinstance(a["news"], str):  # fetch error message
        return f'<h3>Company news</h3><p class="bad">⚠ {escape(a["news"])}</p>'
    rows = "".join(f'<tr><td>{escape(x["date"])}</td><td>{escape(x["type"])}</td><td style="white-space:normal">'
                   f'<b>{escape(x["summary"])}</b>{"<br>" + escape(x["body"][:400]) if x["body"] else ""}</td></tr>'
                   for x in a["news"][:n])
    return ('<h3>Company news</h3><div class="wrap"><table><tr><th>Date</th><th>Type</th><th>News</th></tr>'
            f'{rows}</table></div><p class="mute">Latest {n} items from dse.com.bd. Context only: news was not '
            'tested as a price forecast.</p>')


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
Tested on DSE data 2014 to Nov 2026 (docs/SECRETS_RESULTS.md, docs/SECRETS_FORECAST_RESULTS.md): no buy rule
forecast a rise, every rule lost money when traded on fresh 2026 data, one sell warning (#2) has a small edge and
#31 works in reverse. Use the flags as information, not forecasts. {regime}</p>
<footer class="mute">Descriptive analysis of the uploaded data only. Not investment advice.</footer></body></html>"""


def latest_regime(journal="data/paper/journal.jsonl"):
    """Last market regime the paper run logged, as (asof, regime), or None. This page does not compute it."""
    try:
        r = json.loads(Path(journal).read_text().splitlines()[-1])
        return r["asof"], r["regime"]
    except (OSError, IndexError, KeyError, ValueError):
        return None


LOG_COLS = ["made_on", "symbol", "h", "low", "mid", "high", "close"]


def log_forecasts(results, path="data/watch/forecast_log.csv"):
    """Append each share's ranges (one row per horizon), once per share and data date."""
    path = Path(path)
    old = pd.read_csv(path, dtype={"made_on": str}) if path.exists() else pd.DataFrame(columns=LOG_COLS)
    new = pd.DataFrame([{"made_on": a["date"], "symbol": s, "h": h, "low": f["low"], "mid": f["mid"],
                         "high": f["high"], "close": a["close"]}
                        for s, a in results.items() for h, f in a.get("forecast", {}).items()], columns=LOG_COLS)
    both = pd.concat([old, new], ignore_index=True).drop_duplicates(["made_on", "symbol", "h"], keep="first")
    path.parent.mkdir(parents=True, exist_ok=True)
    both.to_csv(path, index=False)
    return both


def score_forecasts(log, closes):
    """log: forecast_log rows; closes: {symbol: close Series indexed by date}. For each row whose horizon has
    passed, where the close h sessions later landed. Returns {symbol: {h: {checked, inside, below, above}}}."""
    out = {}
    for r in log.itertuples():
        c = closes.get(r.symbol)
        if c is None:
            continue
        i = c.index.searchsorted(pd.Timestamp(r.made_on), side="right") + int(r.h) - 1  # h sessions after made_on
        if i >= len(c) or c.index[c.index.searchsorted(pd.Timestamp(r.made_on))] != pd.Timestamp(r.made_on):
            continue
        v = c.iloc[i]
        s = out.setdefault(r.symbol, {}).setdefault(int(r.h), {"checked": 0, "inside": 0, "below": 0, "above": 0})
        s["checked"] += 1
        s["inside" if r.low <= v <= r.high else "below" if v < r.low else "above"] += 1
    return out


def rates_status(path="results/rates_monthly.csv", h=6):
    """Latest bond and deposit rates (IMF, monthly) and their change over h months, or None."""
    try:
        r = pd.read_csv(path)
    except OSError:
        return None
    out = {}
    for col in ("bond_yield", "deposit_rate"):
        if col not in r:
            continue
        x = r[["month", col]].dropna()
        if len(x) > h:
            out[col] = {"month": x.month.iloc[-1], "level": float(x[col].iloc[-1]),
                        "change": float(x[col].iloc[-1] - x[col].iloc[-1 - h])}
    return out or None


def _rates_line(rs):
    if not rs:
        return ""
    names = {"bond_yield": "government bond yield", "deposit_rate": "deposit rate"}
    parts = [f'{names[k]} {v["level"]:.2f}% ({"up" if v["change"] > 0 else "down" if v["change"] < 0 else "flat"} '
             f'{abs(v["change"]):.2f} pts in 6 months, to {escape(v["month"])})' for k, v in rs.items()]
    rising = any(v["change"] > 0 for v in rs.values())
    return ('<p><b>Interest rates</b> (IMF): ' + "; ".join(parts) + ". "
            + ('<span class="bad">Rates have been rising.</span> ' if rising else 'Rates have not been rising. ')
            + '<span class="mute">On DSE history, rising bond and deposit rates came before weaker DSEX, but the tests '
            'rated the link WEAK (docs/RATES_SIGNAL_RESULTS.md, docs/DEPOSIT_RATES_RESULTS.md): a caution flag for '
            'the whole market, not a forecast.</span></p>')


def render(results, out_path, note="", errors=(), regime=None, rates=None):
    """results: {symbol: analyze() output}. errors: messages for shares that could not be analysed.
    regime: (asof, regime) from latest_regime(), shown next to the rule notes."""
    err = "".join(f'<p class="bad">⚠ {escape(e)}</p>' for e in errors)
    reg = (f"Last regime from the paper run: {escape(regime[1])} on {escape(regime[0])}." if regime else
           "No regime available: run scripts/paper_run.py to compute it.")
    html = PAGE.format(note=escape(note), errors=err + _rates_line(rates), regime=reg,
                       sections="".join(_section(k, v) for k, v in results.items()))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(html, encoding="utf-8")
    return out_path
