# DSEX by month, around elections and pay scales (pre-registration)

Fixed on 2026-11-05, before the test was run. Question from the user: does DSEX show a pattern by month of the
year or over the years, and does it move around general elections or new national pay scales?

## Data
- Daily DSEX from `data/clean/market.csv` (real values only, Oct 2012 to 4 Nov 2026). Floor-price days
  (2020-03-19 to 2021-04-07, 2022-07-28 to 2024-01-21) are left out, as in docs/DSEX_PATTERNS_PREREG.md.
- Yearly taka returns 1997–2025 from `results/dse_long_run.csv` (World Bank).
- Event dates (public): general elections 2001-10-01, 2008-12-29, 2014-01-05, 2018-12-30, 2024-01-07,
  2026-02-12; national pay scales approved by cabinet 2009-11 (7th), 2015-09-07 (8th), 2026-08-31 (9th).

## T1 Month of the year (the only real test)
Each calendar month's DSEX change (sum of daily log changes in that month; a month is dropped if over half
its sessions are floor days or missing). For each of the 12 months: t-test of that month's changes against
all other months' (Welch). Bonferroni for 12: **|t| ≥ 3.0**. Halves: 2012–2019 and 2020–2026.
**PATTERN** if |t| ≥ 3.0 and the month's mean minus the others' mean has the same sign in both halves;
**HINT** if the sign holds in both halves and |t| ≥ 2; otherwise **NONE**. Costs (~1.1% round trip) are
reported beside any PATTERN.

## T2 Does a good year follow a good year?
Spearman correlation of each year's taka return with the next year's, 1997–2025. **YES** if p < 0.05.

## T3 Elections and pay scales (described, not tested)
Too few events to test (4 elections and 2 pay scales in the daily data). For each: DSEX change over the 60
sessions before and the 60 after the date, and where that sits among all 60-session changes (percentile).
Election years in the yearly data (2001, 2008, 2014, 2018, 2024) vs other years: means only.
Reported as what happened, never as a pattern.

## Known limits
- 13–14 values per month: only a large, steady effect can pass T1.
- June holds the national budget most years; a June result can't separate budget from the month.
- Eid moves through the calendar, so it spreads across months rather than showing as one.
