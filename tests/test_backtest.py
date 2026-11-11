import math
import unittest

import numpy as np
import pandas as pd

from decimal import Decimal

from dse_quant.backtest.costs import buy_fill, cost_amount, cost_rate
from dse_quant.backtest.engine import Config, run
from dse_quant.backtest.metrics import deflated_sharpe, first_breach, max_drawdown, sharpe, trade_stats
from dse_quant.backtest.walkforward import stitch, switch_cost
from dse_quant.limits import lock_flags
from dse_quant.panels import build_panels, eligible_mask
from dse_quant.universe import UniverseRules, eligible
from tests.helpers import bars
from tests.test_universe import RULES, TYPES, market


def clean(df):
    return lock_flags(df.assign(close_raw=df.close, gap_flag=False))


class Costs(unittest.TestCase):
    def test_floor_slippage(self):
        self.assertAlmostEqual(float(cost_rate(1_000, 1e12, 0.02)), 0.0030 + 0.001)

    def test_impact_scales_with_vol_and_sqrt(self):
        # Tk 10 lakh vs Tk 5 crore ADTV, 2.5% daily vol -> 0.025 * sqrt(0.02) = 0.354%
        self.assertAlmostEqual(float(cost_rate(1e6, 5e7, 0.025)), 0.0030 + 0.025 * math.sqrt(0.02))

    def test_impact_capped_so_a_sale_never_costs_more_than_it_raises(self):
        self.assertAlmostEqual(float(cost_rate(1e6, 5e4, 0.05)), 0.0030 + 0.10)         # 20x ADTV, 5% vol
        self.assertAlmostEqual(float(cost_rate(1e6, 0, 0.02)), 0.0030 + 0.10)           # no turnover after a suspension
        self.assertAlmostEqual(float(cost_rate(1e6, 5e7, float("nan"))), 0.0030 + 0.10)  # no vol history
        self.assertLess(float(cost_rate(1e9, 1, 1.0, mult=2.0)), 1.0)

    def test_multiplier(self):
        self.assertAlmostEqual(float(cost_rate(1_000, 1e12, 0.02, mult=2)), 2 * (0.0030 + 0.001))

    def test_cost_is_rounded_up_to_the_paisa(self):
        self.assertEqual(cost_amount(Decimal("1001"), 1e12, 0.0), Decimal("4.01"))  # 0.4% of 1001 = 4.004

    def test_buy_never_exceeds_settled_cash(self):
        q, total = buy_fill(1000, Decimal("10.1"), 1e12, 0.0, 1.0, Decimal("1014.00"))
        self.assertEqual((q, total), (99, Decimal("1003.90")))  # 100 shares would cost 1014.04


class Metrics(unittest.TestCase):
    def test_sharpe(self):
        r = pd.Series([0.01, -0.01] * 50 + [0.0])
        self.assertAlmostEqual(sharpe(r), r.mean() / r.std() * math.sqrt(240))

    def test_max_drawdown(self):
        self.assertAlmostEqual(max_drawdown(pd.Series([100, 120, 90, 130, 65])), 0.5)

    def test_first_breach_of_kill_level(self):
        eq = pd.Series([100, 110, 95, 93, 120, 90], index=pd.bdate_range("2020-01-01", periods=6))
        self.assertEqual(first_breach(eq, 0.15), eq.index[3])     # 93/110 = -15.45%
        self.assertIsNone(first_breach(eq, 0.30))

    def test_trade_stats(self):
        s = trade_stats(pd.Series([10.0, -5.0, 20.0, -5.0]))
        self.assertEqual(s, {"trades": 4, "win_rate": 0.5, "profit_factor": 3.0})

    def test_deflated_sharpe_bounds(self):
        rng = np.random.default_rng(1)
        strong = pd.Series(rng.normal(0.002, 0.01, 1500))
        noise = pd.Series(rng.normal(0.0, 0.01, 1500))
        self.assertGreater(deflated_sharpe(strong, n_trials=1, sr_var=0.0), 0.99)
        self.assertLess(deflated_sharpe(noise, n_trials=132, sr_var=0.02 ** 2), 0.5)
        self.assertLess(deflated_sharpe(strong, n_trials=132, sr_var=0.05 ** 2),
                        deflated_sharpe(strong, n_trials=1, sr_var=0.0))


class WalkForward(unittest.TestCase):
    def setUp(self):
        self.yr = {y: pd.Series([0.01, 0.01], index=pd.to_datetime([f"{y}-01-02", f"{y}-01-03"]))
                   for y in (2017, 2018)}

    def test_switch_charged_on_first_day_of_new_year(self):
        out, n = stitch(self.yr, {2017: 0, 2018: 1}, cost=0.02)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(out.iloc[2], 1.01 * 0.98 - 1)
        self.assertEqual(out.iloc[0], 0.01)
        self.assertEqual(out.iloc[3], 0.01)

    def test_same_choice_costs_nothing(self):
        out, n = stitch(self.yr, {2017: 0, 2018: 0}, cost=0.02)
        self.assertEqual(n, 0)
        self.assertTrue((out == 0.01).all())

    def test_switch_cost_scales(self):
        self.assertAlmostEqual(switch_cost(1.5), 2 * 1.5 * (0.0030 + 0.001))


class PanelUniverseMatchesReference(unittest.TestCase):
    def test_vectorised_equals_reference(self):
        df = clean(market(80).drop(columns=["prev_close", "limit", "lower_lock", "upper_lock"]))
        p = build_panels(df)
        mask = eligible_mask(p, TYPES, RULES)
        for d in p.dates[40:]:
            got = sorted(mask.columns[mask.loc[d]])
            self.assertEqual(got, eligible(df, d, TYPES, RULES), d)

    def test_min_price_uses_raw_close(self):
        df = clean(market(80).drop(columns=["prev_close", "limit", "lower_lock", "upper_lock"]))
        df.loc[df.ticker == "GOOD", "close"] /= 3          # back-adjusted below Tk10, raw still ~20
        self.assertIn("GOOD", eligible(df, df.date.max(), TYPES, RULES))


class AlwaysBuy:
    """Test strategy: wants ticker 0 every day, exits only by max_hold."""
    name, stop_atr, trail, target_atr, max_hold = "test", None, False, None, 3

    def prepare(self, p, elig=None):
        pass

    def entries(self, t):
        return [0]

    def exit(self, t, j, pos):
        return False


def one_stock(closes, **kw):
    df = clean(bars("S", closes, volume=1e9, **kw))
    p = build_panels(df)
    p.adtv.iloc[:, :] = 1e10   # fixtures are shorter than the 20-session ADTV and vol windows
    p.vol.iloc[:, :] = 0.0
    return p, pd.DataFrame(True, index=p.dates, columns=p.tickers)


class Engine(unittest.TestCase):
    def cfg(self, **kw):
        base = dict(cost_mult=0.0, use_regime=False, gap_exclusion=False, start_equity=1e6)
        base.update(kw)
        return Config(**base)

    def test_hand_computed_round_trip_no_costs(self):
        closes = [10.0, 10.0, 11.0, 12.0, 13.0, 14.0]
        p, elig = one_stock(closes)
        p.atr.iloc[:, :] = 1.0                   # qty = 0.005*1e6/1 = 5000 -> 10% cap = 100k/10 = 10000; 5000 wins
        res = run(p, AlwaysBuy(), self.cfg(), elig=elig)
        # signal t0 close -> buy t1 @10 (5000 sh); held 3 sessions -> exit signal t4 close -> sell t5 @14
        first = res.trades.iloc[0]
        self.assertEqual(first.qty, 5000)
        self.assertAlmostEqual(first.pnl, 5000 * (14 - 10))
        self.assertAlmostEqual(res.equity.iloc[-1], 1e6 + 20000)

    def test_sale_proceeds_stay_unsettled_but_count_in_equity(self):
        p, elig = one_stock([10.0, 10.0, 11.0, 12.0, 13.0, 14.0])
        p.atr.iloc[:, :] = 1.0
        res = run(p, AlwaysBuy(), self.cfg(), elig=elig)         # sells t5; proceeds clear at t7, after the run
        self.assertAlmostEqual(res.cash.iloc[-1], 1e6 - 5000 * 10)
        self.assertAlmostEqual(res.equity.iloc[-1], 1e6 + 20000)

    def test_fills_snap_to_tick_buy_up_sell_down(self):
        p, elig = one_stock([10.05] * 7)
        p.atr.iloc[:, :] = 1.0
        res = run(p, AlwaysBuy(), self.cfg(), elig=elig)
        self.assertAlmostEqual(res.trades.iloc[0].pnl, 5000 * (10.0 - 10.1))

    def test_costs_charged_both_sides(self):
        closes = [10.0] * 7
        p, elig = one_stock(closes)
        p.atr.iloc[:, :] = 1.0
        res = run(p, AlwaysBuy(), self.cfg(cost_mult=1.0), elig=elig)
        rate = float(cost_rate(50_000, 1e10, 0.0))      # flat prices -> zero volatility -> spread floor
        t = res.trades.iloc[0]
        self.assertAlmostEqual(t.pnl, 5000 * 10 * (1 - rate) - 5000 * 10 * (1 + rate), places=6)

    def test_no_sell_on_lower_lock(self):
        closes = [10.0, 10.0, 10.0, 10.0, 9.0, 8.1, 8.1, 8.1]   # t4, t5 locked down
        p, elig = one_stock(closes)
        p.atr.iloc[:, :] = 1.0
        res = run(p, AlwaysBuy(), self.cfg(), elig=elig)
        exit_day = res.trades.iloc[0].exit_date
        self.assertEqual(exit_day, p.dates[6])    # exit wanted t4 close -> fill t5 blocked -> t6

    def test_long_only_never_negative(self):
        p, elig = one_stock([10.0 + (i % 3) for i in range(40)])
        p.atr.iloc[:, :] = 0.5
        res = run(p, AlwaysBuy(), self.cfg(cost_mult=1.0), elig=elig)
        self.assertTrue((res.positions >= 0).all().all())
        self.assertTrue((res.cash >= -1e-6).all())

    def held_strategy(self, **attrs):
        class S(AlwaysBuy):
            max_hold = 10_000

            def entries(self, t):
                return [0] if t == 0 else []
        for k, v in attrs.items():
            setattr(S, k, v)
        return S()

    def run_path(self, closes, strat, regime=None, **cfg):
        p, elig = one_stock(closes)
        p.atr.iloc[:, :] = 1.0
        return p, run(p, strat, self.cfg(**cfg), elig=elig, regime=regime)

    def test_fixed_stop_exits(self):
        # entry t1 @10, stop 10 - 1.5 = 8.5; close 8.4 at t5 -> sell t6
        p, res = self.run_path([10, 10, 10, 9.6, 9.0, 8.4, 8.4, 8.4], self.held_strategy(stop_atr=1.5))
        self.assertEqual(res.trades.iloc[0].exit_date, p.dates[6])

    def test_no_stop_exit_above_level(self):
        _, res = self.run_path([10, 10, 10, 9.6, 9.0, 8.6, 8.6, 8.6], self.held_strategy(stop_atr=1.5))
        self.assertEqual(len(res.trades), 0)

    def test_trailing_stop_follows_peak(self):
        # peak 12 -> trail level 10.5; close 10.4 at t6 -> sell t7 (a fixed stop at 8.5 would not fire)
        p, res = self.run_path([10, 10, 11, 12, 11.4, 10.8, 10.4, 10.4, 10.4],
                               self.held_strategy(stop_atr=1.5, trail=True))
        self.assertEqual(res.trades.iloc[0].exit_date, p.dates[7])

    def test_profit_target(self):
        # target 10 + 1 = 11; close 11.0 at t3 -> sell t4
        p, res = self.run_path([10, 10, 10.5, 11.0, 11.2, 11.2], self.held_strategy(target_atr=1.0))
        self.assertEqual(res.trades.iloc[0].exit_date, p.dates[4])

    def test_risk_off_blocks_entries(self):
        closes = [10.0] * 8
        reg = pd.Series("RISK_OFF", index=pd.bdate_range("2020-01-01", periods=8))
        _, res = self.run_path(closes, AlwaysBuy(), regime=reg, use_regime=True)
        self.assertEqual(res.positions.values.sum(), 0)

    def test_neutral_halves_size(self):
        closes = [10.0] * 8
        reg = pd.Series("NEUTRAL", index=pd.bdate_range("2020-01-01", periods=8))
        _, res = self.run_path(closes, self.held_strategy(), regime=reg, use_regime=True)
        self.assertEqual(res.positions.iloc[-1].max(), 2500)   # 0.5 * 0.005 * 1e6 / ATR 1

    def test_stress_sells_everything(self):
        closes = [10.0] * 8
        reg = pd.Series("RISK_ON", index=pd.bdate_range("2020-01-01", periods=8))
        reg.iloc[4] = "STRESS"
        p, res = self.run_path(closes, self.held_strategy(), regime=reg, use_regime=True)
        self.assertEqual(res.trades.iloc[0].exit_date, p.dates[5])

    def test_trade_counts_gap_days_while_held(self):
        p, elig = one_stock([10.0] * 8)
        p.atr.iloc[:, :] = 1.0
        p.gap_flag.iloc[3, 0] = True            # unexplained gap while the position is held
        res = run(p, AlwaysBuy(), self.cfg(), elig=elig)
        self.assertEqual(res.trades.iloc[0].gap_days, 1)

    def test_delisted_written_off(self):
        df = clean(pd.concat([bars("S", [10.0] * 5, volume=1e9), bars("Z", [1.0] * 80, volume=1e9)]))
        p = build_panels(df)
        p.atr.iloc[:, :] = 1.0
        p.adtv.iloc[:, :] = 1e10
        elig = pd.DataFrame(True, index=p.dates, columns=p.tickers)

        class BuyOnceHold(AlwaysBuy):
            max_hold = 10_000
            def entries(self, t):
                return [0] if t == 0 else []

        res = run(p, BuyOnceHold(), self.cfg(), elig=elig)
        self.assertAlmostEqual(res.equity.iloc[-1], 1e6 - 5000 * 10)


if __name__ == "__main__":
    unittest.main()
