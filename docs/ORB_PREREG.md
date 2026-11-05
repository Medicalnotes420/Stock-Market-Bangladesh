# Opening-range breakout: does it make money? (pre-registration)

Fixed on 2026-11-05, before the test was run. The day-trader agent's skills (trader-scanner, trader-entry,
trader-exit) recommend this setup on US stocks; the skill pack's own example came out "close to a coin flip".
Nothing below is tuned after seeing results.

## Question
Taken exactly as the skills trade it, does a 15-minute opening-range breakout on US stocks earn more than it
costs, on average, over the last ~60 sessions?

## Data
Yahoo 5-minute bars, `range=60d` (the most Yahoo gives), fetched once with trader-timemachine's own
`fetch_chart`/`parse_bars`; full sessions only (78 bars, 9:30–16:00 New York), so half days are left out.

## Stocks
1. The US common-stock list from `trader-scanner/scan.py universe` (Nasdaq Trader files of 2026-11-05: 5,935 names).
2. A random sample of 400, `random.Random(20261105).sample(sorted(symbols), 400)`.
3. Keep those a day trader could trade: median close ≥ $5 and mean traded value (Σ close × volume per session)
   ≥ $20M a day over the window. The sample and who passed are saved with the results.

## The trade (trader-timemachine's `history_replay`, unchanged)
- Opening range = high/low of the first three 5-minute bars (9:30–9:45).
- Entry: the close of the first later bar that closes above the range high. Long only, one trade per stock-day.
  Entries after 15:30 are dropped (trader-risk's default window).
- Stop: range midpoint, rounded down to the cent (trader-exit default).
- Target: entry + 2 × risk (trader-exit default). Primary test.
- Exit: stop or target, whichever a bar touches first (stop first if both in one bar); else the 15:55 close.
- Result in R (risk units). **Cost:** 0.05% of price each side (spread + slippage; Alpaca charges no commission),
  so net R = R − 0.001 × entry / risk.

## Tests (2, Bonferroni: t ≥ 2.24)
| Id | Target | Role |
|---|---|---|
| ORB2R | 2R | primary (skill default) |
| ORB1R | 1R | secondary (the skill pack's worked example) |

Statistic: each session's mean net R across the trades that day, then t of those daily means (days, not
trades, because stocks on the same day move together). Halves: first and second half of the sessions by date.

## Verdict
- **WORKS:** mean net R > 0, t ≥ 2.24, and mean > 0 in both halves.
- **WEAK:** mean net R > 0 in all three (whole, both halves) but t < 2.24.
- **NO:** otherwise.

Also reported, as description only: trades, % target first, % stop first, % open at the close, mean gross R.

## Known limits
- ~59 sessions is a short window (one market mood: a sharp move into the US midterms). A NO is fairly
  convincing; a WORKS needs the forward record before anyone trusts it.
- 5-minute bars, not ticks: fills at the bar close, and a stop inside a bar is taken at the stop price
  (gaps through it would be worse).
- The liquidity filter uses the same window's volume, a mild look-ahead in which stocks are chosen, not in
  any trade's outcome.
