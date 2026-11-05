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
