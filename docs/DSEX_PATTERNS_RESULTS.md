# DSEX market-level patterns: results

Run 2026-11-05 as pre-registered in docs/DSEX_PATTERNS_PREREG.md (`python -W ignore scripts/dsex_patterns.py`,
output results/dsex_patterns.csv). Floor-price days are excluded, which leaves B with only ~170–240 sessions.

## Answer in one line
All four patterns pass the pre-fixed bar, but each is worth 0.1–0.4% a day, far below the 1.1% round-trip cost,
and they were found on this same data. They describe how the index moves; they are not trades.

| Test | What it says | Mean A / B / C | t in A / B / C | Verdict |
|---|---|---|---|---|
| MOM1 | tomorrow tends to follow today's direction | +0.16% / +0.21% / +0.12% | 8.9 / 3.6 / 1.7 | HOLDS, not tradable |
| DOWN3 | after 3 down days, a 4th down day is likelier | −0.20% / −0.23% / −0.005% | −3.9 / −1.9 / −0.0 | HOLDS on paper; **flat in C** |
| BR1 | tomorrow follows today's breadth (advancers vs decliners) | +0.14% / +0.24% / +0.11% | 8.0 / 5.1 / 1.5 | HOLDS, not tradable |
| SUN | Sunday, the first DSE session of the week, is weaker than other days | −0.25% / −0.28% / −0.44% | −5.3 / −2.3 / −2.1 | HOLDS, not tradable |

Bar: |t| ≥ 2.50 in A, predicted sign in B and C. Tradable needs |mean| ≥ 1.1% in A; none comes close.

## How to read it
- **SUN** is the cleanest: same sign and t ≥ 2 in every period, and stale prices cannot explain a weekday effect.
  The index has on average closed Sunday about a quarter of a percent lower than on other days. That is a calendar
  fact about the past, not a strategy.
- **MOM1 and BR1** are probably partly stale prices: illiquid stocks that skip a day catch up the next one. They are
  still useful as context ("a strong-breadth day usually doesn't reverse at once"), not as a forecast you can buy.
- **DOWN3** passes only because −0.005% is technically below zero in C. Treat it as not holding on 2026 data.
- None of this is blind. The patterns were picked by looking at the full history first. Period D (sessions after
  2026-11-04) is the real test; the script marks `confirmed_on_D` once D has 120 sessions with the predicted sign.

## Tradable backtest
Run 2026-11-05 as fixed in the addendum of DSEX_PATTERNS_PREREG.md (`python -W ignore scripts/dsex_backtest.py`,
output results/dsex_backtest.csv). The basket is the 30 eligible stocks with the most traded value, equal weight.
Fills are at the next session's typical price, with T+2 and about 0.66% cost per side (median). Floor periods are flat.

**Answer: none of the four beats buy-and-hold.** Costs make every timing rule far worse than doing nothing.

| Strategy | Net annual return A / B / C | Before costs A / B / C | Switches A / B / C | Verdict |
|---|---|---|---|---|
| BH (buy and hold the basket) | −12% / −28% / −6% | same | 1 / 1 / 1 | benchmark |
| S_MOM1 | −47% / −32% / −56% | −9% / −9% / −19% | 627 / 84 / 73 | DOES NOT BEAT |
| S_BR1 | −49% / −54% / −58% | −10% / −16% / −24% | 647 / 176 / 70 | DOES NOT BEAT |
| S_DOWN3 | −27% / −34% / −29% | −11% / −22% / −13% | 225 / 49 / 23 | DOES NOT BEAT |
| S_SUN | −50% / −61% / −34% | −8% / −26% / +14% | 723 / 186 / 65 | DOES NOT BEAT |

"Before costs" is a diagnostic added after the pre-registration, not part of the verdict.

How to read it:
- **The basket itself lost money.** The 30 most-traded DSE names fell about 12% a year in A, while DSEX was roughly
  flat. An equal-weight basket of all eligible stocks did about −7% a year over 2014–19. Turnover leaders lagging the
  market is consistent with docs/VOLUME_FORECAST_RESULTS.md. These are price returns: dividends are not included,
  for the basket or for DSEX.
- **Before costs, momentum and Sunday timing did help a little** (MOM1 beat BH in A and B, SUN in A and C). The
  patterns are partly real in tradable stocks, not only an index artefact. But each rule switches 70–720 times a
  period, and at about 1.3% a round trip the cost is many times the gain.
- **Neither T+2 nor next-session fills can be avoided on the DSE.** A one-day pattern cannot be held for one day,
  and the close that produced the signal is already gone when the order can be placed.
- Shortcut in the script: daily changes in basket membership are not charged. Charging them would make every row
  worse. BH is in the market longest, so it would be hit hardest; the gaps above (25–45 points a year in A) are
  far larger than that cost is likely to be, but this was not run.
