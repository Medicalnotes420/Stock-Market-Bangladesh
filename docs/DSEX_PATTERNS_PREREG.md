# DSEX market-level patterns (pre-registration)

Fixed on 2026-11-05, before `scripts/dsex_patterns.py` was run. Periods, Bonferroni style and cost bar follow
docs/VOLUME_FORECAST_PREREG.md. Thresholds are round numbers picked once; nothing is tuned.

## Honesty note: these patterns were found on the same data
An exploratory pass on 2026-11-05 ran about 20 checks on the whole DSEX history (2012-10 to 2026-11-04,
including period C) and picked the four below because they held in both halves. So A, B and C are **not blind**:
passing here means "survives a stricter, pre-fixed restatement", not "confirmed". The only blind data is
**period D, sessions after 2026-11-04**. The script reports D automatically as days are added. A pattern is
treated as confirmed only once D has ≥ 120 sessions and the mean has the predicted sign there.

## Data
`data/clean/market.csv`: DSEX close, adv/dec counts, by date. **r_t** = ln(DSEX_t / DSEX_t-1). r_t is dropped when
either close is missing or the dates are more than 7 calendar days apart (the 2020 closure). Days inside the floor-
price periods (2020-03-19..2021-04-07, 2022-07-28..2024-01-21, as in scripts/run_phase4.py) are dropped from every
test, because frozen prices make the index sticky. Breadth **b_t** = (adv - dec) / (adv + dec); days with no counts
are dropped from BR only.

Periods: A = 2014-01-01..2022-12-31, B = 2023-01-01..2026-01-22, C = 2026-01-25..2026-11-04, D = after 2026-11-04.

## Tests (4, two-sided Bonferroni: t ≥ 2.50)
The unit is one session. t = mean / (sd / √n) over sessions.

| Id | Signal at close t | Measured value x | Predicts |
|---|---|---|---|
| MOM1 | sign of today's return | sign(r_t) × r_t+1 | x > 0: tomorrow continues today's direction |
| DOWN3 | three down days in a row (r_t-2, r_t-1, r_t < 0) | r_t+1 on those days | x < 0: a fourth down day |
| BR1 | sign of today's breadth | sign(b_t) × r_t+1 | x > 0: tomorrow follows today's breadth |
| SUN | the session is the first of the DSE week (Sunday) | r_t on Sundays − mean r_t on other days in that period | x < 0 |

## Verdict
- **HOLDS**: predicted sign with |t| ≥ 2.50 in A, and the predicted sign in B and in C.
- **WEAK**: A passes, B or C does not.
- **NO**: A fails.
- **TRADABLE** (separate column): |mean x| in A ≥ 1.1%, the round-trip cost in SECRETS_FORECAST_PREREG.md. The index
  itself cannot be bought; a basket that tracks it would pay at least that.

## Known limits
- Non-synchronous trading: illiquid DSEX members that do not trade today show yesterday's price, so part of MOM1 and
  BR1 can be stale prices catching up rather than anything a trader could capture. This test cannot separate the two.
- DOWN3 is not independent of MOM1; it is included because the author of "My Secret Series" and many traders reason
  in streaks.
- SUN compares Sunday to other days, so one Sunday's return also moves the "other days" mean slightly; ignored.

## Addendum: tradable backtest (fixed 2026-11-05, before `scripts/dsex_backtest.py` was run)
The index cannot be bought, so each pattern trades a **basket**: an equal-weight basket of the 30 eligible stocks
(eligible_mask) with the highest 20-session traded value as of the previous close. Membership is updated daily.

Fills follow docs/PHASE4_PREREG.md: the signal is read at close t, and the fill is at session t+1's typical price
(O+H+L+C)/4. A position can be sold no earlier than two sessions after it was bought (T+2). Each switch in or out
pays cost_rate() per basket name for a Tk 1 crore order split evenly over the 30 names. The basket is forced flat
during the floor-price periods.

| Id | In the market when (at close t) | Out when |
|---|---|---|
| BH | always (benchmark: buy and hold the basket) | never |
| S_MOM1 | DSEX rose today | DSEX fell today |
| S_BR1 | breadth b_t > 0 | b_t < 0 (no breadth data: keep the current position) |
| S_DOWN3 | by default | after 3 DSEX down days; back in after the next up day |
| S_SUN | from Sunday's close until Wednesday's close | Wednesday's close signal → sold Thursday, back Sunday |

Changing `S_SUN` to sit out exactly over the weekend is not possible: a Sunday close signal fills on Monday.
The rule above is out of the market for Thursday → Sunday, which is where the measured weakness sits.

**Verdict per strategy:** BEATS BUY-AND-HOLD if its annualised net return is above BH's in A, B and C, and its
Sharpe is above BH's in A. Otherwise DOES NOT BEAT. Nothing is tuned; there is one rule per pattern.
