# DSE Systematic Research & Paper-Trading System — Phase 1 Spec

Status: DRAFT for approval · Written 2026-10-29 · No code exists yet. Every performance number is "not run".

Verification labels used below:
- **[V]**: confirmed in a cited source dated 2026.
- **[S]**: cited source is older or secondary. Re-check against the primary DSE/BSEC circular before Phase 3.
- **[U]**: unverified. No source found. Treated as an assumption.

---

## 1. Venue facts

| Item | Finding | Label | Source |
|---|---|---|---|
| Trading days | Sunday–Thursday, except exchange-declared holidays | [S] | [Wikipedia: DSE](https://en.wikipedia.org/wiki/Dhaka_Stock_Exchange), [TradingHours.com](https://www.tradinghours.com/markets/dse) |
| Trading hours (current) | Continuous trading 10:00–14:00 BST, plus a short post-close session. Cut from 14:30 on 5 Apr 2026 because of the fuel crisis, "until further notice". Changed again on 17 Jun 2026: regular trading runs 10:00–14:00 uninterrupted, and the post-close session was extended (new times not published). No report found of a return to 14:30. | [V] | [TBS 4 Apr 2026](https://www.tbsnews.net/economy/stocks/dse-cuts-trading-hours-30-minutes-amid-fuel-crisis-1402316), [FE](https://today.thefinancialexpress.com.bd/stock-corporate/dse-cse-cut-trading-hours-by-30-minutes-1775317057), [Observer 16 Jun 2026](https://www.observerbd.com/news/579665) |
| Hours change often | Ramadan schedules and crisis cuts happen most years | [V] | [FE Feb 2026](https://today.thefinancialexpress.com.bd/print/dse-cse-cut-trading-hours-during-ramadan-1771264014) |
| Settlement | T+2 for A/B/G/N categories. T+3 for Z buys. Spot market: T+1 buy, T+0 sell. | [S] | [BRAC EPL settlement page](https://bracepl.com/brokerage/investors/settlementprocedure), [EFG Hermes market info](https://tg.efghermes.com/Market/GetById/1199), [FE Feb 2024](https://today.thefinancialexpress.com.bd/print/newly-labeled-z-stocks-plunge-on-dse-1708277625) |
| Sell before settlement | Bought shares can't be sold until they are credited to the BO account, so the minimum hold equals the settlement cycle | [U] | Confirm with broker |
| Daily price limits | Tiered by previous close: ≤Tk200 ±10%; Tk200–500 ±8.75%; Tk500–1,000 ±7.5%; Tk1,000–2,000 ±6.25%; Tk2,000–5,000 ±5%; >Tk5,000 ±3.75%. On 1 Jul 2026 BSEC gave the power to set these back to the exchanges, and existing limits stay until the DSE board changes them. The middle tiers are confirmed only in 2022 sources. One 2025 blog claims a flat 10%. | Top/bottom tiers [V], middle tiers [S] | [TBS 1 Jul 2026](https://www.tbsnews.net/node/1477436), [FE 2022](https://thefinancialexpress.com.bd/stock/bangladesh/bsec-sets-20pc-circuit-breaker-at-lower-end-1653533989), [EFG Hermes](https://tg.efghermes.com/Market/GetById/1199) |
| SME board limit | 10% (cut from 20%) | [S] | [TBS](https://www.tbsnews.net/economy/stocks/bsec-cuts-circuit-breaker-limit-sme-index-399394) |
| Floor prices | Imposed Jul 2022. Lifted for all but 35 stocks on 21 Jan 2024, and fully removed by Aug 2024. None in force now as far as found. **Regime risk:** BSEC has imposed floors twice (2020, 2022) during selloffs. | [S] | [TBS](https://www.tbsnews.net/node/777158?amp), [FE](https://thefinancialexpress.com.bd/stock/bangladesh/bsec-lifts-beximco-islami-bank-floor-price), [FE 2022](https://thefinancialexpress.com.bd/stock/bangladesh/bsec-imposes-floor-prices-again-1659063561) |
| Lot size | Believed to be 1 share for all listed securities since ~2021 | [U] | No source found. Confirm with broker. |
| Short selling | Not practically available. BSEC short-sale rules exist on paper (2019 draft, reportedly enacted 2021), but the DSE has not adopted implementing regulations (as of Jan 2026). **The system is long-only.** | [V] | [BSEC draft rule PDF](https://sec.gov.bd/storage/draft-rules/draft_rule_20260621153804_P8T2aqIRSpiHmWt689fgDQlK.pdf), [FE Jan 2026](https://today.thefinancialexpress.com.bd/print/bsec-urges-caution-as-dse-pushes-for-share-netting-1768234883) |
| Margin | Margin Loan Rules 2025: eligibility needs ≥Tk5 lakh average annual investment. Z stocks are cash-only. **The system uses no margin.** | [S] | [Daily Star](https://online-d11.thedailystar.net/business/news/stocks-sink-political-tension-new-rules-rattle-investors-4034421), [FE 2024](https://today.thefinancialexpress.com.bd/print/newly-labeled-z-stocks-plunge-on-dse-1708277625) |
| Brokerage commission | Broker-specific. Retail range seen: 0.25%–0.50% per side. | [S] | [nsave guide](https://www.nsave.com/bangladesh/stocks) (low authority). **Need your broker's schedule.** |
| Transaction tax | TDS 0.05% of transaction value on share trades (ITA 2023 s.137). PwC lists 0.03%. Usually deducted via the broker. | [S] conflicting | [Moore](https://www.moore-global.com/services/tax/international-corporate-tax/bangladesh/), [PwC](https://taxsummaries.pwc.com/bangladesh/corporate/withholding-taxes), [TBS: DSE wants 0.02%](https://www.tbsnews.net/economy/stocks/dhaka-stock-exchange-urges-govt-avoid-capital-gains-tax-individual-investors-862471) |
| Capital gains tax | Individuals: 15% on annual listed-share gains above Tk50 lakh (applied FY2024-25). FY2025-26/26-27 status not confirmed. | [S] | [Dhaka Tribune](https://www.dhakatribune.com/business/stock/364252/nbr-lowers-capital-gains-tax-on-share-sales) |
| CDBL / BO fees | BO annual fee ~Tk450. Per-trade CDBL charges exist; current tariff not found. | [S] | [TBS](https://www.tbsnews.net/economy/stocks/63-brokerage-firms-owe-tk11cr-maintenance-fees-cdbl-383035) |
| Automated order entry | The DSE offers a FIX/API link from **broker** OMS to the Nasdaq matching engine. 66 brokers were certified by Aug 2026. No source shows a retail-client order API, and nothing permits client algorithms. | [V] for broker API, [U] for client access | [FE Aug 2026](https://today.thefinancialexpress.com.bd/print/dse-grants-fix-certification-to-13-more-brokerage-houses-1756403345), [FE](https://thefinancialexpress.com.bd/stock/bangladesh/11-more-brokerage-firms-get-fix-certification-to-boost-trading-efficiency) |

**Design consequence:** no permitted client-side automated order entry has been confirmed. The system is therefore a **daily end-of-day signal generator that you execute by hand**. It never connects to a broker.

### Cost model used until your broker's schedule arrives (conservative)
- Commission 0.40% per side + TDS 0.05% per side + CDBL/misc 0.02% per side = **0.47% per side (~0.94% round trip) before slippage.** [assumption]
- Slippage/impact per side = `max(0.10%, k · sqrt(order_value / ADTV_20d))` with k = 0.5 to start. Phase 4 sweeps it.
- Cost sensitivity is reported at 1×, 1.5× and 2× this model. A strategy that dies at 1.5× is rejected.

---

## 2. Session schedule the system builds for

- Runs once per trading day **after close**. Data is pulled ~16:00 BST once the DSE publishes final prices.
- Output: the next session's order list, with limit prices and expected fill assumptions.
- Execution assumption in backtests: fill at **next day's open-to-VWAP proxy** (we have daily bars only, so use `(O+H+L+C)/4` and stress-test with worse-of open/close). Never fill at the signal bar's close.
- The trading calendar is data-driven (days with DSE prints), not hard-coded. Hour changes don't matter to daily bars, but the data-freshness check uses the published calendar.
- Lower-limit lock rule: if a stock closes at its lower circuit price (within one tick), and/or its high equals its low at the limit, **the sell is assumed unfilled that day** and carried forward.
- Upper-limit lock rule: a buy signal on a stock closing at its upper limit is skipped. Assume no fill.
- Minimum hold = settlement cycle (T+2, or T+3 for Z, though Z is excluded anyway).

---

## 3. Market regime definition

All inputs are known at the close of day t and act on day t+1.

| Input | Definition | Bullish | Bearish |
|---|---|---|---|
| Trend | DSEX close vs 100-day SMA; slope of 20-day SMA over 10 days | Close > SMA100 and slope > 0 | Close < SMA100 and slope < 0 |
| Volatility | 20-day realised vol of DSEX daily returns, as a percentile of its trailing 250-day history | < 80th pct | ≥ 90th pct |
| Turnover | DSE total traded value: 20-day mean / 120-day mean | ≥ 1.0 | < 0.7 |
| Breadth | 10-day mean of (adv − dec)/(adv + dec), and % of liquid universe above its 50-day SMA | > 0 and > 50% | < −0.2 or < 30% |
| Limit-lock stress | % of liquid universe closing at lower limit | — | > 15% on any day |
| Macro calendar | Hand-maintained CSV of event dates (see below) | — | Inside a blackout window |

Regimes and actions:

| Regime | Rule | Action |
|---|---|---|
| **RISK_ON** | Trend bullish, breadth bullish, turnover ≥ 1.0, vol < 80th pct | Trade. Full risk budget. |
| **NEUTRAL** | Anything not covered by another row | Trade at 50% risk budget, top liquidity tercile only |
| **RISK_OFF** | Trend bearish, or breadth bearish on both measures, or vol ≥ 90th pct, or turnover < 0.7 | **No new entries.** Existing positions keep their stops. |
| **STRESS** | Limit-lock stress > 15%, or regulator intervention flag (floor price reinstated, trading halt, emergency circular), set by hand in the calendar CSV | **Cash. Kill switch fires** and an exit list is written. |

Macro calendar blackouts (no new entries, existing stops still active):
- National budget speech (usually early June): −2 / +3 trading days.
- Bangladesh Bank Monetary Policy Statement / policy-rate decision: −1 / +2 days.
- National election: −10 / +10 days. Parliamentary elections took place in Feb 2026, so the next is not near, but local polls and hartals go in the CSV.
- IMF review / tranche decision dates: −1 / +2 days.
- Major regulatory announcements (BSEC chair change, margin rule change, circuit-breaker change): flagged by hand, −0 / +3 days.

Phase 4 tests whether the regime filter adds value versus always-on. If it doesn't, it is dropped. It does not get to stay because it sounds sensible.

---

## 4. Universe and liquidity filter (evaluated daily, point-in-time)

Include a stock on day t only if all of these hold:
1. Listed on the DSE main board. Exclude SME board, ATB and OTC.
2. Category A, B or N as of day t. **Exclude Z and G.** Z is cash-only, T+3 and dominated by manipulation. Mutual funds and bonds are excluded.
3. 60-day median daily traded value ≥ **Tk 2 crore** [assumption, swept in Phase 4: Tk 1 / 2 / 5 crore].
4. Traded on ≥ 90% of the last 60 sessions.
5. Not suspended, not under a "trading halt / record date" spot-only window, not on a floor price.
6. Did not close at its lower limit in any of the last 3 sessions.
7. Listed ≥ 250 sessions. This excludes IPO price-discovery runs.
8. Price ≥ Tk 10.

Delisted and merged stocks stay in the historical universe up to their last trading day. That requires a data source with dead tickers (see the Phase 3 question).

---

## 5. Candidate strategies (to be tested in Phase 4; no results yet)

All are long-only, use daily bars, enter at the next session, and keep signals separate from execution.

### C1. Cross-sectional medium-term momentum
- **Edge:** DSE prices underreact to slow-diffusing fundamental news (sparse analyst coverage, a retail-dominated market). Stocks with strong 6–12 month returns keep outperforming for a few months.
- **Other side:** retail profit-takers and the disposition effect. Holders sell winners early.
- **Entry:** monthly, rank the universe by 126-day return skipping the last 21 days. Buy the top decile (min 5, max 10 names), equal-risk weighted.
- **Exit:** monthly rebalance out of the top 30%, or a 2.5 × ATR(20) trailing stop.
- **Hold / frequency:** ~1–3 months. ~5–10 trades/month.
- **Why it might persist:** behavioural, plus limits to arbitrage (no shorting, high costs). Known risk: momentum crashes after regime turns, which the regime filter is meant to address.

### C2. Turnover-confirmed breakout
- **Edge:** a close above the 60-day high on turnover ≥ 2× its 60-day average marks new information arriving.
- **Other side:** anchored holders selling at their old highs.
- **Entry:** next session after the signal, if the gap ≤ 3% and the stock is not at its upper limit.
- **Exit:** close below the 20-day low, or 2 × ATR stop, or 30-session time stop.
- **Hold / frequency:** ~2–6 weeks. ~3–8 trades/month.
- **Main threat:** DSE pump-and-dump schemes look exactly like this. Reject if returns concentrate in low-free-float or recently-investigated names.

### C3. Short-term overreaction reversal (liquid names only)
- **Edge:** retail panic selling in liquid A-category stocks, with no company news, overshoots, and it partially reverses within ~5 sessions.
- **Other side:** forced and margin-call sellers, and panicking retail.
- **Entry:** 5-day return ≤ −10% and ≤ −2σ versus its own history, DSEX not in RISK_OFF, no lower-limit close on the signal day. Buy the next session.
- **Exit:** +1 × ATR target, or 7-session time stop, or a stop at 1.5 × ATR below entry.
- **Hold / frequency:** 3–7 sessions (minimum 2 because of T+2). ~4–10 trades/month.
- **Main threat:** costs. A ~1% round trip eats short-horizon edges. Lower-limit lockups trap exits. This is the candidate most likely to die.

### C4. Low-volatility / quality tilt
- **Edge:** retail lottery preference bids up volatile junk, so low-volatility profitable A-category stocks earn better risk-adjusted returns.
- **Other side:** lottery-seeking retail.
- **Entry:** quarterly, take the lowest-quintile 250-day volatility among A-category stocks that paid a cash dividend in each of the last 2 years. Buy the top 10 by dividend yield.
- **Exit:** quarterly rebalance, or the stock drops from A category.
- **Hold / frequency:** 3+ months. ~2–4 trades/month.
- **Why it might persist:** structural (benchmark-free retail, no leverage for institutions). Low turnover makes it cost-robust.

### C5. Post-dividend-declaration drift
- **Edge:** the market underreacts to board dividend declarations that beat the prior year's payout.
- **Other side:** retail who ignore the disclosures and sellers after the record date.
- **Entry:** the session after a DSE news disclosure of a cash dividend ≥ 1.2× last year's, if the stock is not at its upper limit.
- **Exit:** 2 sessions before the record date (to avoid the spot-only window and the ex-date drop), or a 2 × ATR stop.
- **Data need:** time-stamped DSE disclosures. **Feasibility depends on the data source.** It is dropped if timestamps can't be trusted.

Total pre-registered variants: 5 strategies. The Phase 4 parameter grids get counted, and that count is reported so the results can be judged against chance (deflated Sharpe).

---

## 6. Hard risk limits (enforced in code; no signal can override)

| Limit | Value (initial) | Action on breach |
|---|---|---|
| Max position | 10% of portfolio equity | Order clipped |
| Max position vs liquidity | ≤ 5% of the stock's 20-day ADTV, so the exit fits in ~1 day at 5% participation | Order clipped |
| Max names | 12 | Lowest-ranked signal dropped |
| Max sector | 30% (banks, textiles, pharma, etc.) | Order clipped |
| Max daily loss | −2% of equity, marked to the close | No new entries next session |
| Max drawdown | −15% from the equity peak | **Kill switch:** stops all new signals and writes an exit list ordered by liquidity |
| Stale data | Latest bar ≠ expected latest trading day, or > 5% of universe missing, or DSEX missing | No signals that day. Alert. |
| Price sanity | |1-day return| > applicable circuit limit + 0.5% with no corporate action | Ticker quarantined |
| Long-only | Negative quantities rejected at the order layer | Hard error |
| Sizing | Volatility targeting: position risk = 0.5% of equity per 1 × ATR(20). Kelly is not used (estimates too noisy). | — |

Every decision gets logged as a JSON line: inputs hash, regime, signal, sizing, limit checks, final order, and later the paper fill and P&L.

---

## 7. Validation protocol (detailed in Phases 3–4)

- Prices adjusted for cash dividends, bonus (stock) dividends and rights issues, using point-in-time corporate actions.
- Split by time: **train 2012–2019, validation 2020–2022 (contains COVID and the floor-price era, kept for stress), held-out 2023–2026** [assumption, depends on data history]. The held-out set is opened once.
- Walk-forward: 3-year train / 1-year test, rolled annually.
- Floor-price periods (Mar 2020–Apr 2021 and Jul 2022–Jan 2024): reported separately. Strategies are not allowed to depend on them, since prices were artificially pinned and trading was illiquid.
- Reported for every variant: Sharpe, max drawdown, win rate, profit factor, trade count, cost sensitivity at 1×/1.5×/2×, and parameter-neighbourhood stability.

---

## 8. Open questions for you (blocking)

1. **Repo location.** You said "the project repo I point you to", but none was given. This spec sits in a temporary folder.
2. **Your broker.** I need its commission schedule, its order types and whether it offers any client API, plus its rule on selling before settlement.
3. **Capital size.** It determines whether the liquidity caps bind. At Tk 10 lakh they rarely bind. At Tk 5 crore they will.
4. **Data source.** Options and their terms go to you before Phase 3, as you asked. Nothing has been downloaded.

---

## HOW COULD THIS SYSTEM FAIL? (ranked)

1. **Weakest assumption: the DSE price series reflects tradable prices.** Floor-price years, frequent manipulation probes, thin books and limit lockups mean historical closes may not have been reachable at size. The backtest could be fiction for anything below the top ~100 names.
2. **Costs.** At ~1% round trip before slippage, C3 (reversal) and probably C2 (breakout) are fragile. C1 and C4 have low turnover and are the most likely survivors. If the broker commission is closer to 0.5%, everything short-horizon dies.
3. **Regulatory regime shifts.** BSEC has re-imposed floors and changed circuit limits and trading hours repeatedly. The exchanges now control the limits again (Jul 2026), so the rules may change mid-test. A floor-price reinstatement freezes exits for months, and only the STRESS kill switch plus small sizing protects against it.
4. **Already arbitraged?** It's unlikely that institutions have arbitraged momentum or low-vol away on the DSE (no shorting, few quant funds). The bigger risk is the opposite: the patterns may be manipulation artefacts that won't repeat.
5. **Data feed breaks.** Manual execution means a missed or stale update produces no signals rather than wrong trades. Stale-data checks block signal generation. The real danger is *silently wrong* data, such as unadjusted bonus shares that look like a −50% crash. Mitigation: the price-sanity quarantine plus cross-checking against a second source.
6. **Survivorship bias.** If the chosen data source lacks delisted and Z-relegated stocks, every result is inflated. This is a hard requirement for the data choice.
