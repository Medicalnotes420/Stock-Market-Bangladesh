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

from dse_quant.indicators import adx, atr, bollinger, cci, ema, macd, rsi, sma, stoch
from dse_quant.paper.harness import author_flags
from dse_quant.universe import UniverseRules

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


def _payload(html):
    """A dse.com.bd page is a Next.js app that carries its data as JSON strings in self.__next_f.push([1,"..."])
    scripts; there is no documented API. Returns those strings joined."""
    return "".join(json.loads(m) for m in re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html))


def parse_news(html):
    """Company news items embedded in a dse.com.bd company page, newest first: dicts of id, type (Notice, Dividend,
    Financials, Rating), date ('02 Nov 2026'), summary, body."""
    text = _payload(html)
    dec, items = json.JSONDecoder(), []
    for m in re.finditer(r'\{"id":"\d+","type":"', text):
        o = dec.raw_decode(text, m.start())[0]
        if o["body"].startswith("$"):  # shortcut: long bodies sit in a separate payload row; summary only for those
            o["body"] = ""
        items.append(o)
    return items


def parse_company(html):
    """The company record in a dse.com.bd company page (code, sector, marketCap, multiYearFinancials,
    interimFinancials, dividendHistory, sharePattern, loanStatus, ...), or None. Missing values arrive as "$undefined"."""
    text, dec = _payload(html), json.JSONDecoder()
    for m in re.finditer(r'\{"code":"[^"]+","name":', text):
        o = dec.raw_decode(text, m.start())[0]
        if "multiYearFinancials" in o:
            return o
    return None


def company_page(symbol, timeout=60):
    """One fetch of a share's dse.com.bd page: (company record or None, news items). Raises if there is no news,
    which means the page layout changed or the code is wrong."""
    req = urllib.request.Request(NEWS_URL.format(urllib.parse.quote(symbol)), headers={"User-Agent": "dse-watch/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8")
    items = parse_news(html)
    if not items:
        raise ValueError(f"dse.com.bd: no news found on the {symbol} page (layout may have changed)")
    return parse_company(html), items


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


# "recommended 10% Cash and 5% Stock Dividend for the year ended June 30, 2026" / "recommended No Dividend ..."
DECL_RE = re.compile(r"recommended\s+(.{0,80}?dividend).{0,80}?(?<![Hh]alf[ -])year ended\s+\w+\s+\d+,\s+(\d{4})", re.I | re.S)
CASH_RE, STOCK_RE = re.compile(r"([\d.]+)%\s+cash", re.I), re.compile(r"([\d.]+)%\s+stock", re.I)
NAV_RE = re.compile(r"NAV per share of Tk\.?\s*(\(?)([\d.]+)\)?", re.I)


def _declared(news, after_year):
    """Newest year-end dividend declaration in dse.com.bd news for a year after `after_year`:
    {"year", "cash", "stock", "nav"} (nav None if not stated; "(x)" means negative), or None."""
    for x in news or []:
        m = DECL_RE.search(x.get("body", "")) if x.get("type") == "Dividend" else None
        if m:
            if int(m[2]) <= after_year:
                return None
            ca, st, nv = CASH_RE.search(m[1]), STOCK_RE.search(m[1]), NAV_RE.search(x["body"])
            return {"year": int(m[2]), "cash": float(ca[1]) if ca else 0.0, "stock": float(st[1]) if st else 0.0,
                    "nav": (-1 if nv[1] else 1) * float(nv[2]) if nv else None}
    return None


def fundamentals(c, price, news=()):
    """Valuation and balance-sheet figures from a parse_company record at `price` (Tk). Money in Tk mn as DSE
    reports it. DSE fills its multi-year table late, so newer figures win: EPS from the interim table's annual
    column, NAV and dividend from the year-end declaration in `news` (parse_news items)."""
    # DSE sends "$undefined" for a missing table or value: keep only the dicts we expect
    rows_of = lambda x: [r for r in x if isinstance(r, dict)] if isinstance(x, list) else []
    dict_of = lambda x: x if isinstance(x, dict) else {}
    years = sorted((y for y in rows_of(c.get("multiYearFinancials")) if _num(y.get("year"))), key=lambda y: y["year"])
    last = years[-1] if years else {}
    eps, eps_when = _num(last.get("epsBasic")), f"FY{last.get('year', '?')}"
    inter = dict_of(c.get("interimFinancials"))
    ends = dict_of(inter.get("periodEnds"))
    inter_rows = rows_of(inter.get("rows"))
    eps_row = next((r for r in inter_rows if str(r.get("metric", "")).startswith("Earnings Per Share (EPS) Basic")), {})
    annual = str(ends.get("annual") or "")
    if len(annual) == 6 and _num(eps_row.get("annual")) is not None and int(annual[:4]) > (last.get("year") or 0):
        eps, eps_when = float(eps_row["annual"]), f"year to {annual[4:]}/{annual[:4]} (interim report)"
    nav, nav_when = _num(last.get("nav")), f"FY{last.get('year', '?')}"
    face = _num(c.get("faceValue")) or 10.0
    paid = _num(c.get("paidUpCapital"))
    shares = paid / face if paid else None
    divs = sorted((d for d in rows_of(c.get("dividendHistory")) if _num(d.get("year"))), key=lambda d: d["year"])
    dv = divs[-1] if divs else {}
    dec = _declared(news, max([last.get("year") or 0] + [d["year"] for d in divs]))
    if dec:
        dv = {"year": f'{dec["year"]} (declared)', "cash": dec["cash"], "stock": dec["stock"]}
        if dec["nav"] is not None:
            nav, nav_when = dec["nav"], f"FY{dec['year']} (dividend declaration)"
    div_tk = (_num(dv.get("cash")) or 0) / 100 * face if dv else None
    loans = c.get("loanStatus") if isinstance(c.get("loanStatus"), dict) else {}
    debt = sum(v for v in (_num(loans.get("shortTerm")), _num(loans.get("longTerm"))) if v is not None) if loans else None
    equity = nav * shares / 1e6 if nav and shares else None
    pos = lambda v: v is not None and v > 0
    return {
        "name": c.get("name"), "sector": c.get("sector"), "category": c.get("category"), "board": c.get("board"),
        "listing_year": c.get("listingYear"), "year_end": c.get("yearEnd"), "agm": c.get("agmDate"),
        "as_of": c.get("asOfDate"), "market_cap_mn": (_num(c.get("marketCap")) or 0) / 1e6 or None,
        "free_float_pct": _num(c.get("freeFloat")), "shares": shares, "face": face,
        "paid_up_mn": paid / 1e6 if paid else None, "authorized_mn": _num(c.get("authorizedCapital")),
        "reserve_mn": _num(c.get("reserveWithoutOci")),
        "eps": eps, "eps_when": eps_when, "nav": nav, "nav_when": nav_when,
        "pe": price / eps if pos(eps) else None, "pb": price / nav if pos(nav) else None,
        "roe": eps / nav if eps is not None and pos(nav) else None,
        "div_year": dv.get("year"), "div_cash_pct": _num(dv.get("cash")), "div_stock_pct": _num(dv.get("stock")),
        "div_tk": div_tk, "div_yield": div_tk / price if div_tk is not None and price else None,
        "payout": div_tk / eps if div_tk is not None and pos(eps) else None,
        "debt_mn": debt, "loans": {k: _num(v) for k, v in loans.items()},
        "debt_equity": debt / equity if debt is not None and pos(equity) else None,
        "years": [{"year": y["year"], "eps": _num(y.get("epsBasic")), "nav": _num(y.get("nav")),
                   "profit_mn": _num(y.get("profit")), "pe": _num(y.get("pe")),
                   "div": next((f'{_num(d.get("cash")) or 0:g}% cash' + (f' + {_num(d.get("stock")):g}% stock'
                                if _num(d.get("stock")) else "") for d in divs if d["year"] == y["year"]), "")}
                  for y in years[-6:]],
        "interim": {"ends": ends, "rows": [r for r in inter_rows if any(_num(r.get(k)) is not None for k in ends)]},
        "holders": [h for h in rows_of(c.get("sharePattern")) if isinstance(h.get("pattern"), dict)],
    }


MA_N = (5, 10, 20, 50, 100, 200)


def _side(x):
    return "n/a" if pd.isna(x) else "Bullish" if x > 0 else "Bearish" if x < 0 else "Neutral"


def _band(x, lo, hi, mid):
    return "n/a" if pd.isna(x) else "Oversold" if x < lo else "Overbought" if x > hi else _side(x - mid)


def _tally(rows):
    """Counts of Bullish / Bearish / Neutral (Overbought and Oversold count as Neutral) and a one-word reading."""
    sig = [r["signal"] for r in rows if r["signal"] not in ("n/a", "info")]
    b, s = sig.count("Bullish"), sig.count("Bearish")
    score = (b - s) / len(sig) if sig else 0
    word = ("Strongly bullish" if score >= .5 else "Bullish" if score >= .15 else "Strongly bearish" if score <= -.5
            else "Bearish" if score <= -.15 else "Neutral")
    return {"bullish": b, "bearish": s, "neutral": len(sig) - b - s, "reading": word if sig else "n/a"}


def tech_summary(df):
    """investing.com-style technical table: moving averages (close above = Bullish), oscillators with the usual
    textbook thresholds, and classic pivot points from the last session. Descriptive: docs/FINDINGS.md §2 found
    the RSI/MACD/SMA rules tested on DSE had no forecast power."""
    h, l, c = df.high, df.low, df.close
    last = c.iloc[-1]
    mas = [{"name": f"MA{n}", "kind": kind, "value": float(v), "signal": _side(last - v)}
           for n in MA_N for kind, v in (("Simple", sma(c, n).iloc[-1]), ("Exponential", ema(c, n).iloc[-1]))]
    k, d = stoch(h, l, c)
    ml, ms = macd(c)
    ax, pdi, mdi = adx(h, l, c)
    r, cc, roc, at = rsi(c).iloc[-1], cci(h, l, c).iloc[-1], (c.pct_change(12) * 100).iloc[-1], atr(h, l, c).iloc[-1]
    if c.iloc[-15:].nunique() == 1:  # no move in 14 sessions (e.g. stuck at the floor price): rsi() reports 100
        r = np.nan
    macd_sig = _side(ml.iloc[-1] - ms.iloc[-1]) if len(c) >= 35 else "n/a"  # macd() has no warm-up; 26 + 9 sessions
    kk, dd = k.iloc[-1], d.iloc[-1]
    osc = [{"name": "RSI(14)", "value": r, "signal": _band(r, 30, 70, 50)},
           {"name": "Stochastic %K(14,3)", "value": kk,
            "signal": "n/a" if pd.isna(kk) else "Oversold" if kk < 20 else "Overbought" if kk > 80 else _side(kk - dd)},
           {"name": "MACD(12,26)", "value": ml.iloc[-1], "signal": macd_sig},
           {"name": "ADX(14)", "value": ax.iloc[-1],
            "signal": "n/a" if pd.isna(ax.iloc[-1]) else "Neutral" if ax.iloc[-1] < 20 else _side(pdi.iloc[-1] - mdi.iloc[-1])},
           {"name": "Williams %R(14)", "value": kk - 100, "signal": _band(kk - 100, -80, -20, -50)},
           {"name": "CCI(14)", "value": cc, "signal": _band(cc, -100, 100, 0)},
           {"name": "ROC(12)", "value": roc, "signal": _side(roc)},
           {"name": "ATR(14)", "value": at, "signal": "info"}]
    H, L, C = h.iloc[-1], l.iloc[-1], last
    P = (H + L + C) / 3
    piv = {"S3": L - 2 * (H - P), "S2": P - (H - L), "S1": 2 * P - H, "Pivot": P,
           "R1": 2 * P - L, "R2": P + (H - L), "R3": H + 2 * (P - L)}
    return {"ma": mas, "osc": osc, "pivots": {k_: float(v) for k_, v in piv.items()},
            "ma_tally": _tally(mas), "osc_tally": _tally(osc), "overall": _tally(mas + osc)}


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


def data_warnings(df, rules=UniverseRules()):
    """Ways this share falls outside the shares the range's hit rate was measured on (scripts/forecast_check.py
    checks only universe-eligible shares). Empty list if none.
    shortcut: the 90%-of-sessions-traded rule is not checked (needs the DSE session calendar); add it if a share
    with long trading gaps shows up."""
    c, out = df.close, []
    if len(c) < rules.min_history:
        out.append(f"only {len(c)} sessions of prices (tested shares had at least {rules.min_history})")
    med = float((c * df.volume).iloc[-rules.lookback:].median())  # close x volume, as elsewhere on this page
    if med < rules.min_median_value:
        out.append(f"median daily turnover of about Tk {med / 1e6:,.1f} million over the last {rules.lookback} "
                   f"sessions (tested shares traded at least Tk {rules.min_median_value / 1e6:,.0f} million)")
    if c.iloc[-1] < rules.min_price:
        out.append(f"a price below Tk {rules.min_price:g} (tested shares were at Tk {rules.min_price:g} or more)")
    return out


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
    chg = {f"{n}d": float(last / c.iloc[-1 - n] - 1) for n in (1, 5, 20, 60, 120, 240) if len(c) > n}
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
            "rsi": float(r.iloc[-1]), "alerts": alerts, "data_warnings": data_warnings(df), "tech": tech_summary(df),
            "high52": float(df.high.iloc[-240:].max()), "low52": float(df.low.iloc[-240:].min()),
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
             if a.get("turnover_ratio", 0) >= WIDEN_AT else '') + _div_note(a) + '</p>' + _warn_note(a)
          + _score_note(a)) if fc else ""
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
            + (f' ({a["volume"] / a["vol_avg20"]:.1f}x)' if a["vol_avg20"] > 0 else '')
            + (f'<br>52-week range Tk {a["low52"]:,.2f} &ndash; {a["high52"]:,.2f}' if "high52" in a else '') + '</p>'
            + _fund(a) +
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
            + _tech(a) + f'<h3>Rule alerts</h3><div class="wrap"><table><tr><th>Rule</th><th>Fired</th><th>Value</th><th>Date</th></tr>{rows}'
            f'</table></div>{fc}{sec}{_news(a)}</section>')


def _f(v, fmt="{:,.2f}", na="n/a"):
    return na if v is None or (isinstance(v, float) and np.isnan(v)) else fmt.format(v)


def _sig(s):
    cls = {"Bullish": "ok", "Strongly bullish": "ok", "Bearish": "bad", "Strongly bearish": "bad"}.get(s, "mute")
    return f'<span class="{cls}">{escape(s)}</span>'


def _tech(a):
    t = a.get("tech")
    if not t:
        return ""
    tl = lambda x: (f'{_sig(x["reading"])} <span class="mute">({x["bullish"]} bullish, {x["bearish"]} bearish, '
                    f'{x["neutral"]} neutral)</span>')
    ma = "".join(f'<tr><td>{s["name"]}</td><td>{_f(s["value"])} {_sig(s["signal"])}</td>'
                 f'<td>{_f(e["value"])} {_sig(e["signal"])}</td></tr>'
                 for s, e in zip(t["ma"][::2], t["ma"][1::2]))  # rows alternate Simple, Exponential
    osc = "".join(f'<tr><td>{escape(o["name"])}</td><td>{_f(o["value"])}</td><td>{_sig(o["signal"])}</td></tr>'
                  for o in t["osc"])
    pv = "".join(f'<th>{k}</th>' for k in t["pivots"]), "".join(f'<td>{v:,.2f}</td>' for v in t["pivots"].values())
    return (f'<h3>Technical summary</h3><p>Overall: {tl(t["overall"])}<br>Moving averages: {tl(t["ma_tally"])}<br>'
            f'Oscillators: {tl(t["osc_tally"])}</p>'
            f'<div class="wrap"><table><tr><th>Moving average</th><th>Simple</th><th>Exponential</th></tr>{ma}</table></div>'
            f'<div class="wrap"><table><tr><th>Oscillator</th><th>Value</th><th>Reading</th></tr>{osc}</table></div>'
            f'<p class="mute">Classic pivot points from the last session (Tk):</p>'
            f'<div class="wrap"><table><tr>{pv[0]}</tr><tr>{pv[1]}</tr></table></div>'
            '<p class="mute">A mechanical tally like investing.com\'s: price above an average reads bullish; oscillators '
            'use textbook thresholds (RSI 30/70, Stochastic 20/80, Williams %R &minus;80/&minus;20, CCI &plusmn;100, ADX '
            'below 20 = no trend). It describes the chart, it is not a forecast or a buy/sell call: the RSI, MACD and '
            'moving-average rules tested on DSE 2014&ndash;2026 had no forecast power (docs/FINDINGS.md &sect;2).</p>')


def _fund(a):
    if "fund" not in a:
        return ""
    f = a["fund"]
    if isinstance(f, str):  # fetch or parse error message
        return f'<h3>Fundamentals</h3><p class="bad">⚠ {escape(f)}</p>'
    pct = lambda v: _f(v, "{:.1%}")
    eps_cls = "bad" if f["eps"] is not None and f["eps"] < 0 else ""
    key = [("Sector", escape(str(f["sector"] or "n/a"))), ("Category", escape(str(f["category"] or "n/a"))),
           ("Market cap", f'Tk {_f(f["market_cap_mn"], "{:,.0f}")} mn'),
           ("EPS", f'<span class="{eps_cls}">Tk {_f(f["eps"])}</span> <span class="mute">{escape(f["eps_when"])}</span>'),
           ("P/E", _f(f["pe"], "{:.1f}", "n/a (loss)" if f["eps"] is not None and f["eps"] <= 0 else "n/a")),
           ("NAV per share", f'Tk {_f(f["nav"])} <span class="mute">{escape(f["nav_when"])}</span>'),
           ("Price / NAV", _f(f["pb"], "{:.2f}")), ("Return on equity (EPS / NAV)", pct(f["roe"])),
           ("Last dividend", (f'{_f(f["div_cash_pct"], "{:g}")}% cash' + (f' + {f["div_stock_pct"]:g}% stock'
                              if f["div_stock_pct"] else '') + f' for {escape(str(f["div_year"]))} '
                              f'(Tk {_f(f["div_tk"])} a share)') if f["div_year"] else "n/a"),
           ("Dividend yield", pct(f["div_yield"])), ("Payout (dividend / EPS)", pct(f["payout"])),
           ("Loans", f'Tk {_f(f["debt_mn"], "{:,.1f}")} mn' + (
               f' <span class="mute">(short {_f(f["loans"].get("shortTerm"), "{:,.1f}")}, long '
               f'{_f(f["loans"].get("longTerm"), "{:,.1f}")})</span>' if f["loans"] else '')),
           ("Loans / equity", _f(f["debt_equity"], "{:.2f}")),
           ("Free float", _f(f["free_float_pct"], "{:.1f}%")), ("Shares", _f(f["shares"], "{:,.0f}")),
           ("Paid-up / authorised capital", f'Tk {_f(f["paid_up_mn"], "{:,.1f}")} / {_f(f["authorized_mn"], "{:,.0f}")} mn'),
           ("Reserves", f'Tk {_f(f["reserve_mn"], "{:,.1f}")} mn'),
           ("Year end · AGM · Listed", escape(f'{f["year_end"] or "n/a"} · {f["agm"] or "n/a"} · {f["listing_year"] or "n/a"}'))]
    rows = "".join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in key)
    yrs = "".join(f'<tr><td>{y["year"]}</td><td>{_f(y["eps"])}</td><td>{_f(y["nav"])}</td><td>{_f(y["profit_mn"], "{:,.1f}")}</td>'
                  f'<td>{_f(y["pe"], "{:.1f}")}</td><td>{escape(y["div"]) or "&ndash;"}</td></tr>' for y in reversed(f["years"]))
    ends = f["interim"]["ends"]
    cols = [k for k in ("q1", "q2", "half", "q3", "nine", "annual") if k in ends]
    inter = "".join(f'<tr><td style="white-space:normal">{escape(str(r.get("metric", "")))}</td>'
                    + "".join(f'<td>{_f(_num(r.get(k)))}</td>' for k in cols) + '</tr>' for r in f["interim"]["rows"])
    inter = (f'<h3>Latest interim results (Tk per share)</h3><div class="wrap"><table><tr><th></th>'
             + "".join(f'<th>{k} <span class="mute">{escape(str(ends[k]))}</span></th>' for k in cols)
             + f'</tr>{inter}</table></div>') if inter else ""
    names = ("sponsor", "government", "institution", "foreign", "public")
    hold = "".join(f'<tr><td>{escape(str(h.get("date", "")))}</td>'
                   + "".join(f'<td>{_f(_num(h["pattern"].get(n)), "{:.2f}%")}</td>' for n in names) + '</tr>'
                   for h in f["holders"])
    hold = ('<h3>Shareholding</h3><div class="wrap"><table><tr><th>As of</th>'
            + "".join(f'<th>{n.title()}</th>' for n in names) + f'</tr>{hold}</table></div>') if hold else ""
    return (f'<h3>Fundamentals <span class="mute">· {escape(str(f["name"] or ""))}</span></h3>'
            f'<div class="wrap"><table>{rows}</table></div>'
            f'<h3>Year by year</h3><div class="wrap"><table><tr><th>Year</th><th>EPS</th><th>NAV</th>'
            f'<th>Profit (Tk mn)</th><th>P/E then</th><th>Dividend</th></tr>{yrs}</table></div>{inter}{hold}'
            f'<p class="mute">From the dse.com.bd company page, as of {escape(str(f["as_of"]))}. P/E, Price/NAV and '
            'yield use the last close above. Money in Tk mn as DSE reports it. Loans / equity is approximate (equity = '
            'NAV &times; shares). Context only: fundamentals were not tested as a price forecast here.</p>')


def _div_note(a):
    d = a.get("dividend")
    if not d:
        return ""
    where = (f'so the {" and ".join(f"{h}-session" for h in d["horizons"])} range is lowered by {d["drop"]:.1%}'
             if d["horizons"] else "after both horizons, so the ranges are unchanged")
    return (f' <b>Dividend ahead:</b> {d["pct"]:g}% cash (about Tk {d["tk"]:,.2f} a share at Tk {FACE_VALUE:g} face '
            f'value), record date {d["record"]:%d %b %Y}, about {d["sessions"]} sessions away; the price usually drops '
            f'by the dividend when trading resumes, {where}. Holders receive the cash.')


def _warn_note(a):
    w = a.get("data_warnings")
    if not w:
        return ""
    return ('<p class="bad"><b>Less tested here:</b> the 76&ndash;83% hit rate was measured only on shares with enough '
            'history and trading. This share has ' + escape("; ".join(w)) + '. Outside that group the range may hold less '
            'often, so trust it less and look at the track record.</p>')


def _score_note(a):
    sc = a.get("score")
    if sc is None:
        return ""
    one_off = a.get("score_src") == "one-off"
    if not any(v["checked"] for v in sc.values()):
        return ('<p class="mute">Track record: one-off checks save their ranges to data/watch/one_off_forecast_log.csv;'
                ' none for this share has reached its end date yet. Check it again after 5 sessions for a first score.'
                '</p>' if one_off else
                '<p class="mute">Track record: this page started saving its ranges on 2026-11-05; none has reached '
                'its end date yet.</p>')
    parts = [f'{h} sessions: {v["inside"]} of {v["checked"]} inside ({v["inside"] / v["checked"]:.0%}), '
             f'{v["below"]} below, {v["above"]} above' for h, v in sorted(sc.items()) if v["checked"]]
    how = "saved at each one-off check of this share" if one_off else "saved each morning"
    return (f'<p><b>Track record of this page\'s ranges</b> ({how}, checked when due): '
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
