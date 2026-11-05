# DSEX by month, around elections and pay scales: results

Run 2026-11-05 as pre-registered in docs/CALENDAR_EVENTS_PREREG.md (`python -W ignore scripts/calendar_events.py`,
output results/calendar_months.csv, results/calendar_events.csv). DSEX Oct 2012 to 4 Nov 2026, floor days out.
scipy isn't installed, so the t-test is computed directly and T2's p-value comes from 10,000 seeded shuffles.

## Answer in one line
Two months stand out: **March** and **October** have been weak almost every year. June leans up (a hint only).
Good years don't predict good years. Elections and pay scales are too few to say anything; what happened around
each is listed below.

## T1 Month of the year (bar: |t| ≥ 3.0 and same sign in 2012–19 and 2020–26)
| Month | Avg change | Up years | t | Verdict |
|---|---|---|---|---|
| March | −5.5% (median −4.5%) | 2 of 12 | −3.15 | **PATTERN** |
| October | −3.1% (median −2.3%) | 2 of 12 | −3.11 | **PATTERN** |
| June | +2.1% (median +1.6%) | 9 of 12 | +2.88 | HINT |
| others | between −2.3% and +2.4% | | \|t\| < 1.9 | NONE |

Checked after the verdict: March without the 2020 Covid crash is still −4.1% (t −3.7); 2026, data the
earlier years never saw, was −6.5% in March and −2.4% in October.

**Likely reason (not tested):** DSEX is a price index. On a record date a share's price drops by its dividend.
Companies with a December year end (banks, insurers, many multinationals) mostly hold record dates around
March–May; the many companies with a June year end mostly around October–November. If so, holders got much of
these "falls" back as dividends. Testing it needs dividend and record-date data this project doesn't have.

June is when the national budget is placed; the test can't separate the budget from the month.

## T2 Does a good year follow a good year?
1997–2025, 28 pairs: Spearman −0.01, p 0.97. **NO.** Last year's return says nothing about this year's.

## T3 Elections and pay scales (described only)
DSEX change over 60 sessions, with its percentile among all 60-session changes since 2012:

| Event | 60 sessions before | 60 sessions after |
|---|---|---|
| Election 5 Jan 2014 | +9.4% (84th) | +7.6% (79th) |
| Election 30 Dec 2018 | −1.4% (43rd) | +0.7% (54th) |
| Election 7 Jan 2024 | −0.3% (49th, floor prices) | −15.8% (1st: the floor was lifted 21 Jan) |
| Election 12 Feb 2026 | +11.0% (88th) | −6.9% (17th) |
| 8th pay scale 7 Sep 2015 | +5.5% (73rd) | −2.9% (36th) |
| 9th pay scale 31 Aug 2026 | +2.9% (64th) | not 60 sessions yet |

Election years in the yearly data (2001 −15%, 2008 +4%, 2014 +18%, 2018 −15%, 2024 −15%) averaged −4.7% vs
+10.0% in other years, but 2024's fall came from lifting the floor price, and five years can't carry a claim.
No consistent move around either event type.

## Caveats
- About 12 values per month. A real effect this size could still be partly luck; keep checking each year.
- A March/October weakness of 3–5% is bigger than the ~1.1% round-trip cost, but if it is mostly dividends,
  a holder doesn't lose it and someone who sells before and buys after gives up the dividend. Not a trade.
