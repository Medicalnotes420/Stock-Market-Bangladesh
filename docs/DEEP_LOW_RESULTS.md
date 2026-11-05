# Does a deep fall predict a big rise? Results

Run 2026-11-05 as pre-registered in docs/DEEP_LOW_PREREG.md (`python -W ignore scripts/deep_low.py`, output
results/deep_low_years.csv, results/deep_low_episodes.csv). Signal: index 30%+ below its highest level so far.

## Answer in one line
**LEANS UP, not a signal.** After deep falls the next stretch was better on average, but only half the time,
and the yearly result could be luck. It can't tell you when a rally starts.

## A. Yearly, 1997–2025
| | Years | Next-year average | Rose |
|---|---|---|---|
| Index 30%+ below its high | 18 | +15.4% | 9 of 18 |
| Other years | 11 | −5.5% | |

Difference +21 points, p 0.16 (shuffle test): not significant. The average leans on two huge years, 2004
(+109%) and 2007 (+126%); without them, deep years averaged +2.7%.

A weakness of this design, seen only after running: after the 1996 bubble the index stayed 30%+ below its
1996 high until 2008, so "deep" covers whole depressed decades, not just fresh crashes. Not re-tuned; noted.

## B. Daily DSEX, 2012–2026 (two episodes)
| Episode | Days 30%+ below | Deepest | Next 120 sessions | Next 240 sessions |
|---|---|---|---|---|
| Dec 2019 – Aug 2020 | 65 | −43% | +31% | +57% |
| Jun 2024 – Apr 2026 | 122 | −37% | +9% | +13% |
| Other days | | | +1.0% | +2.5% |

Both episodes were followed by gains, the 2020 one helped by the floor price and the 2021 rally. Two cases.

## What it means
- Buying when DSEX is far below its high has, on average, done better than buying at other times. But in half
  the deep years the market still fell the next year, sometimes for several years running (1998–99, 2001–02,
  2012–13), so a deep low can get deeper.
- It says nothing about the day or month the turn comes. The rises table (results/dsex_rises.csv) shows that
  short bounces of 18–22% (Jan 2020, Jun 2024, May 2025) started from the same kind of lows as the big rallies.
- Not investment advice; history, not a forecast.
