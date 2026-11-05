# What the tests found: the dse-watch agent's reference

One place for every tested finding, with its verdict and where the full write-up is. The `dse-watch` agent reads
only the section a question needs. Numbers here are from the dated runs named; for today's values, read the
files (the watch page, the logs, `results/`). Not investment advice: present each finding with its verdict.

## 1. Price range forecast (the watch page)
Built by `dse_quant.watch.forecast`: 10%/50%/90% of the share's own past 5- and 20-session moves (last 250).
- **Shifted down** 1% (5 sessions) and 3% (20 sessions) since 2026-11-05, because unshifted ranges missed low
  twice as often as high (`docs/RANGE_SKEW_RESULTS.md`, pre-registered). Shifted, on DSE 2014–2026 the range held
  76–83% of the time, misses about even. Falling years (2018, 2024): only 66–75%, misses still mostly low; in a
  RISK_OFF market warn that the low end may be too high.
- **Widened 1.3×** on days when turnover is 2×+ its 20-day average (`docs/VOLUME_RANGE_RESULTS.md`).
- **Lowered for a coming cash dividend** (since 2026-11-05): if a dividend record date from the DSE news falls
  inside a horizon, that range drops by the dividend (cash % × Tk 10 face value ÷ price). The page says so under
  the table. It is arithmetic, not a forecast: the price normally drops by the dividend when trading resumes, and
  holders get the cash. Stock (bonus) dividends are not handled here.
- **Live track record:** each morning the watchlist run saves its ranges to `data/watch/forecast_log.csv` and,
  once 5 or 20 sessions have passed, scores them; the page shows "Track record of this page's ranges: X of N
  inside". This is the best evidence of whether to trust the ranges. Quote it when it has entries; until then say
  none has come due yet. One-off checks (`--symbols`) keep their own log, `data/watch/one_off_forecast_log.csv`,
  scored the next time that share is checked (since 2026-11-05).
- **Less tested here** (since 2026-11-05): the 76–83% was measured only on shares passing the universe screen
  (250+ sessions, median turnover ≥ Tk 2 crore over 60 sessions, price ≥ Tk 10; `scripts/forecast_check.py`). The
  page names any of these a share fails. Say so whenever it shows: the range may hold less often for that share.
  Turnover is close × volume, so it can read low. Both watched shares are under Tk 2 crore.
- Never give a single-price prediction, a direction call, or a range beyond 20 sessions. "Up in past moves" is
  history, not a prediction. The middle is the typical outcome, not a target.

## 2. My Secret Series teachings (rule flags)
Sources: `docs/SECRETS_LEARNINGS.md`, `docs/SECRETS_RESULTS.md`, `docs/SECRETS_FORECAST_RESULTS.md` (pre-registered).

| Teaching | What it says | Verdict |
|---|---|---|
| #1/#13 | RSI 90 → buy the pullback to ~70 | REJECTED: no forecast power, lost money |
| #7/#32 | Turnover surge after a flat base | REJECTED |
| #23 | MFI rising while price is flat ("90% success") | REJECTED: worst of all |
| #25/#30 | Bollinger squeeze entry | REJECTED (2026's good run has no support in earlier years) |
| #67 | SMA13 crosses above SMA19 | REJECTED |
| #96 | #67 + ADX/DI + MFI checklist | REJECTED: lost 4.3% on fresh 2026 data while DSEX gained 5.3% |
| #98 | Lazy-range buy low / sell high | REJECTED (too few trades) |
| **#2** | MACD line falls through its signal line: sell | **SMALL EDGE:** lags the market ~0.3% over 5 days, every period. A caution flag; not tradable (no short selling) |
| #3 | SMA13 crosses below SMA19: sell | no reliable forecast power |
| #21 | Aroon Up below 90: exit | no reliable forecast power (fires often) |
| **#31** | Above upper Bollinger band with RSI > 75: sell half | **OPPOSITE:** these beat the market 1.2–2.8% over 5 days (post-hoc) |
| #39 | RSI 97+: sell | only 7 cases since 2014; prices kept rising |
| #62/#64 | "Top side flash": no new high for 2 days | FALSE: held 14% of the time |
| #38 | Signals fail when turnover dries up | a filter, not tested alone |

No teaching came near the claimed "90% success" (win rates 23–45%). Mindset notes (think in %, avoid margin,
don't spread thin) are behaviour advice, not forecasts. The author's "1–2 stocks only" conflicts with the user's
10%-per-position limit; don't change limits without asking. Rule flags don't change the range; you may add the
two measured tilts (#2 about −0.3% vs market over 5 days; #31 about +1.6%) as information.

## 3. Volume (`docs/VOLUME_FORECAST_RESULTS.md`, pre-registered)
Volume does not forecast direction. One small exception: a fall on 2×+ volume trailed the market ~0.6–0.9% over 20
sessions (a caution flag). Volume does forecast size: 2×+ volume is followed by bigger moves either way (hence
the widening in section 1).

## 4. Trade plan (`python scripts/trade_plan.py CODE --equity TK`, `dse_quant/plan.py`)
Needs the user's whole portfolio in taka; ask, never guess. Options `--entry`, `--stop`, `--target-r` (2),
`--max-loss` (default 0.5% of equity), `--held`. Stop = 20-session low, target = 2× risk; shares cut by
`dse_quant/risk.py` limits (10% of equity per share, 5% of 20-day turnover); say which limit cut it. History
since 2012 of the same rule: % target first / stop first / neither, average result before and after costs
(~0.47% fees + impact each way); stops too close for costs are refused. When the after-costs average is ≤ 0, say
the rule has not paid on this share. It's history, not a forecast; a stop can fill lower after a gap or a
lower-limit lock. DSE settles T+2: a days-to-weeks plan, never same-day.

## 5. DSEX over the years
- Daily DSEX from Oct 2012: `python scripts/dsex_history.py` (yearly table, falls of 20%+, rises of 15%+ in
  `results/dsex_rises.csv`). Yearly back to 1993: `python scripts/dse_long_run.py` (World Bank; S&P Bangladesh
  yearly change from 1997 in dollars, converted to taka with the average rate; matches DSEX 2013–2025 at
  correlation 0.95). Nothing for 1990–92; no free daily index before 2012 (DSE archive gone, dsestocks.com
  blocks downloads). Market value % of GDP and listed-company counts have breaks (2001–02, 2011, 2025).
- DSEX is prices only (no dividends); figures nominal taka. Floor prices (2020-03-19 to 2021-04-07,
  2022-07-28 to 2024-01-21) held prices up, so those years look calmer. ~70 days a year in 2023–25 lack a DSEX value.
- **Months** (`docs/CALENDAR_EVENTS_RESULTS.md`, pre-registered): March and October weak almost every year
  (PATTERN); June leans up (HINT); last year's return doesn't predict this year's. Likely reason for
  March/October: dividend record dates (untested); never present it as a chance to sell and buy back.
  Elections and pay scales: too few to call; quote the table as what happened.
- **Deep lows** (`docs/DEEP_LOW_RESULTS.md`, pre-registered): LEANS UP only. 30%+ below the high was followed by a
  better year on average, but only half those years rose (p 0.16); it can't time the turn. Never say a rally is
  coming.
- Market-level patterns (`docs/DSEX_PATTERNS_RESULTS.md`): momentum, breadth, Sunday weakness are real but far
  too small to trade.

## 6. Interest rates and DSEX
- **Bonds vs shares** (`docs/RATES_VS_INDEX.md`, IMF data, descriptive): since 2011 government bonds far
  outdid the share index even with 3–4% dividends; over 2006–2025 roughly even with dividends.
- **Rising bond yields → weaker DSEX** (`docs/RATES_SIGNAL_RESULTS.md`, pre-registered): **WEAK**. Negative in
  every slice, p 0.063, mostly from 2020 on.
- **Deposit rates** (`docs/DEPOSIT_RATES_RESULTS.md`, pre-registered): **WEAK** for both "move together" and
  "predicts", but negative in every cut (both eras, without floor, without 2020–21); shares don't move rates
  first; most of it is the rate cycle shared with bond yields. The IMF "deposit rate" tracks fixed-deposit rates,
  not Bangladesh Bank's weighted average (~6.3% in 2025).
- The watch page's top line shows the latest bond and deposit rates and their 6-month change (from
  `results/rates_monthly.csv`, refreshed by the daily run when over 30 days old; the IMF publishes months late).
  Describe it as "a modest, consistent link, a caution flag for the whole market", never as a forecast.
- **Yearly re-check:** Windows task "DSE Rates Check" (1 Aug 09:00) runs `scripts\rates_yearly.cmd` into
  `data/rates/rates_check.log`. The verdicts there are fixed; only the "Fresh months after 2026-06" tally can
  confirm or undo the link, and only if it keeps agreeing over several years.

## 7. The report page
"DSE Market History 1993–2026": https://claude.ai/artifact/2Rw2JVeZWhmqayx26C4FrZ. Its data files come from
`python -W ignore scripts/report_data.py` (into `data/report/`); a Claude scheduled task ("Monthly DSE report
refresh", the 2nd of each month, 10:00) uploads them. It's private unless the user shared it.

## 8. Fundamentals and the technical summary (watch page, added 2026-11-05)
**Fundamentals** come from the share's public dse.com.bd company page (`dse_quant.watch.fundamentals`): sector,
category, market cap, EPS, P/E, NAV, Price/NAV, ROE (EPS / NAV), last dividend and yield, payout, loans (Tk mn)
and loans/equity (equity = NAV × shares, approximate), reserves, a year-by-year EPS/NAV/profit/dividend table,
the latest interim quarters, and shareholding. DSE fills its yearly table late, so the newest figures win: EPS
from the interim table's annual column, NAV and dividend from the year-end dividend declaration in the news.
Not tested as a price forecast; context only. No sector comparison yet (it would need every peer's page).

**Technical summary** is an investing.com-style tally: price above each simple/exponential MA (5–200) reads
bullish; oscillators use textbook thresholds (RSI 30/70, Stochastic 20/80, Williams %R −80/−20, CCI ±100, ADX
< 20 = no trend, ROC sign, MACD vs signal); classic pivots from the last session. It is a description of the
chart, not a forecast: the RSI, MACD and moving-average rules tested in §2 had no forecast power on DSE.
