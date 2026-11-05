# Does a deep fall predict a big rise? (pre-registration)

Fixed on 2026-11-05, before the test was run. Every big DSEX rally since 2012 started at the low after a big
fall, but so did short bounces. Question: when the market is far below its high, has the next stretch been
better than usual?

**Signal ("deep low"):** the index is **30% or more below its highest level so far**.

## A. Yearly, 1997–2025 (main test: the most separate cases)
Index built by compounding the World Bank taka returns (`results/dse_long_run.csv`, `return_bdt_pct`), starting
at 100 at the end of 1996. A year t is a signal year if, at the end of year t−1, the index was ≥ 30% below
its highest year-end so far. Compare next-year return (year t) for signal years vs all other years.
- Statistic: difference in mean; p-value from 10,000 seeded shuffles of the signal labels (two-sided).
- Also: share of signal years that rose.

## B. Daily DSEX, Oct 2012 – Nov 2026 (check)
For each day, how far DSEX is below its highest close so far. On signal days, the DSEX change over the next
120 and 240 sessions vs the same on all other days. Reported per episode (signal days more than 240 sessions
apart start a new episode), because neighbouring days are nearly the same case.

## Verdict
- **SIGNAL** if in A the difference is > 0 with p < 0.05, **and** in B both the 120- and 240-session
  differences are > 0.
- **LEANS UP** if A's difference and both B differences are > 0 but A's p ≥ 0.05.
- **NO** otherwise.
Even SIGNAL would mean "rises were more likely after deep falls", not when the low comes.

## Known limits
- A has only ~28 years and maybe 8–10 signal years, several of them back to back, so they overlap.
- B has about two episodes (2019–20, 2024–25), and the 2020 one runs into the floor-price period, which held
  prices up. B can confirm the direction, not the size.
- Before 2013 the yearly returns are the S&P index in dollars converted to taka (yearly average rate).
