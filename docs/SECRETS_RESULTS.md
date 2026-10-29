# "My Secret Series" rules: Results

Status: for your decision · 2026-10-29 · Rules fixed in docs/SECRETS_PREREG.md (commit ed879c8) before this run.
Command: `python -W ignore scripts/run_phase4.py secrets` (571 s). Output: results/secrets_*.csv/json, results/secrets.log.
Check first: `python scripts/run_phase4.py` reproduced the committed Phase 4 table exactly, so the script changes altered nothing old.

## Comparison table (walk-forward out-of-sample 2017–2022, 1× costs, gap exclusion on)
| Rule | Tips | Regime filter | OOS Sharpe | Max DD | Trades | Sharpe 1.5× / 2× cost | Held-out 2023–26 | Criteria | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| S1 RSI 90 → 70 pullback, sell T+2 | #1, #13 | on / off | −0.53 / −0.59 | 5% / 8% | 20 / 34 | −0.70 / −0.80 (off: −0.80 / −0.97) | −0.57 / −0.47 | nnnnYnn | REJECT |
| S7 turnover surge after flat base | #7, #32 | on / off | −0.72 / −2.22 | 14% / 44% | 112 / 269 | −1.13 / −2.86 | −0.96 / −2.60 | ≤1 of 7 | REJECT |
| S25 Bollinger squeeze checklist | #25, #30 | on / off | −0.26 / −1.59 | 8% / 37% | 54 / 312 | −0.65 / −2.32 | −1.81 / −1.76 | ≤1 of 7 | REJECT |
| S23 MFI rising, price flat | #23 | on / off | −1.54 / −2.81 | 36% / 90% | 253 / 1317 | −2.01 / −3.49 | −1.05 / −2.60 | 0 of 7 | REJECT |
| **S67 SMA13×19 cross + #96 filter** | #67, #96, #3, #2 | **on** | **0.54** | **9%** | **115** | **0.32 / 0.11** | **0.16** | **YYnnYYY** | **WEAK** |
| S67 (same) | | off | −0.69 | 53% | 540 | −1.15 | −1.62 | 0 of 7 | REJECT |
| S98 lazy range buy-low/sell-high | #98 | on / off | −0.45 / −0.73 | 1% / 3% | 0 closed | — | −0.50 / −0.93 | 1 of 7 | REJECT |
| DSEX buy-and-hold | — | — | 0.32 | 43% | — | — | −0.38 | — | benchmark |

Chance correction: n_trials = 222 (132 earlier + 90 new). The deflated Sharpe probability is 0.00 for every row.

## The one WEAK result: S67 with the #96 filter, regime on
- **Rule:** SMA13 crosses above SMA19, *and* the author's #96 checklist holds: +DI above −DI, +DI rising, −DI falling, Money Flow > 60, price within 10% of SMA19. Walk-forward picked the #3 cross-down exit in 4 of 6 years and the #2 MACD exit in 2.
- **Passes:**
  1. Out-of-sample Sharpe 0.54 with 115 trades.
  2. Still positive at 1.5× costs (0.32).
  5. The 15% kill switch never fired (max drawdown 9%).
  6. Positive without the floor-price periods (0.72).
  7. Held-out positive (0.16, 15 trades). It beat DSEX there (−0.38) and over 2017–22 on risk (DSEX 0.32 with a 43% drawdown).
- **Fails:**
  3. **Neighbourhood:** only 2 of 6 grid points were positive in training. Without the #96 filter, all three exits lose (−0.06 to −1.03). The edge exists only in one narrow corner of the rule.
  4. **Chance correction:** after 222 tries, a Sharpe of 0.54 is entirely consistent with luck (deflated Sharpe probability 0.00).
- **Other facts:**
  - Return is about 3% a year (2017–22), because it mostly sits in cash. The regime filter stops entries most days.
  - With the regime filter **off**, the same rule loses badly (−0.69, 53% drawdown). Whatever works comes from the market filter as much as from the author's rule.

Verdict per the pre-registration: **WEAK**, labelled post-hoc data / pre-registered rule. Not good enough to trade. The fair next step is to track it forward on paper, with its own kill rule.

## Claim check: #62/#64 "top side flash"
Flash day: traded value ≥ 3× the 20-session mean and close ≥ +5%. Eligible stocks, 2014–2022: **1,458 flash days**.
- **Claim:** "the next 2 sessions do not trade above the flash day's high." It held **14.3%** of the time. **False in 86% of cases.**
- **Close 3 sessions later above the flash close:** **49.4%**, a coin flip.

## What this says about the "90% success" claims
- **No rule achieved anything near 90%.** Win rates were 23–45%, and five of the six rules lost money out of sample.
- **The highest-claimed rules failed hardest:** #23 (MFI rising, "90%") lost the most (−2.8 Sharpe, 90% drawdown).
- **Close to random:** #7 (turnover surge, "90%") and #1 (RSI pullback, "90%") were roughly random before costs and negative after.
- **The tested claim was wrong:** #62 held 14% of the time, against "always".

Limits of this test:
- Daily data only, with no tick data, so the author's screen-reading judgement is absent.
- Category and dividend data are missing.
- Some numbers in the rules are my reading of the author's words (pre-registered, so not tuned).
- The same 2012–2026 data was used before, and held-out has now been seen twice.
