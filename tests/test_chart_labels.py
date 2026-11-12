import inspect
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from chartapp import bars as B, runner as R
from chartapp.bars import Row
from chartapp.labels import Outcome, forward_outcome
from tests.test_chart_runner import make

D = Decimal
D0 = date(2026, 1, 1)


def rows(*ohlc, gap_at=None):
    """Rows from (open, high, low, close) strings, one a day."""
    return [Row(D0 + timedelta(days=i), D(o), D(h), D(lo), D(c), 100, D(1000), D(c), D("1.0"), i == gap_at,
                False, False) for i, (o, h, lo, c) in enumerate(ohlc)]


# entry 100: target at +10% is 110, stop at -5% is 95
FLAT = ("100", "101", "99", "100")
UP = ("100", "111", "99", "110")      # touches the target
DOWN = ("100", "101", "94", "95")     # touches the stop
BOTH = ("100", "111", "94", "100")    # touches both


def outcome(*ohlc, horizon=None, min_hold=2, gap_at=None):
    future = rows(*ohlc, gap_at=gap_at)
    return forward_outcome(future, horizon or len(future), D("10"), D("5"), min_hold)


class Values(unittest.TestCase):
    def test_measured_from_the_next_open(self):
        o = outcome(("100", "104", "98", "102"), ("102", "108", "101", "107"), ("107", "109", "96", "105"))
        self.assertEqual(o, Outcome(D("100"), D("5"), D("9"), D("-4"), None, None))
        self.assertTrue(all(type(v) is Decimal for v in (o.entry, o.ret_pct, o.mfe_pct, o.mae_pct)))

    def test_horizon_one_is_the_entry_bar_alone(self):
        self.assertEqual(outcome(("50", "55", "45", "52"), FLAT, horizon=1, min_hold=0),
                         Outcome(D("50"), D("4"), D("10"), D("-10"), "stop", 0))

    def test_horizon_cuts_the_window(self):
        o = outcome(FLAT, FLAT, FLAT, ("100", "300", "1", "200"), horizon=3)
        self.assertEqual((o.ret_pct, o.mfe_pct, o.mae_pct, o.first_touch), (D("0"), D("1"), D("-1"), None))


class Touches(unittest.TestCase):
    def test_target_first(self):
        o = outcome(FLAT, FLAT, UP, DOWN)
        self.assertEqual((o.first_touch, o.touch_bar), ("target", 2))

    def test_stop_first(self):
        o = outcome(FLAT, FLAT, DOWN, UP)
        self.assertEqual((o.first_touch, o.touch_bar), ("stop", 2))

    def test_both_in_one_bar_is_the_stop(self):
        o = outcome(FLAT, FLAT, BOTH)
        self.assertEqual((o.first_touch, o.touch_bar), ("stop", 2))

    def test_exactly_on_the_level_counts(self):
        self.assertEqual(outcome(FLAT, FLAT, ("100", "110", "99", "100")).first_touch, "target")
        self.assertEqual(outcome(FLAT, FLAT, ("100", "101", "95", "100")).first_touch, "stop")
        self.assertIsNone(outcome(FLAT, FLAT, ("100", "109.99", "95.01", "100")).first_touch)

    def test_a_later_bonus_does_not_lose_an_exact_touch(self):
        # entry 100, high exactly 110 and low exactly 95, as the file holds them after a bonus rescales history
        # and bars.dec cuts each price to 4 dp. Without the rounding allowance about half of these are lost.
        for k in range(1, 200):
            f = 1 / (1 + D(k) / 100)
            def px(v):
                return str(B.dec(str(D(v) * f)))
            flat, up, down = [tuple(px(v) for v in bar) for bar in (FLAT, ("100", "110", "99", "100"),
                                                                    ("100", "101", "95", "100"))]
            self.assertEqual(outcome(flat, flat, up).first_touch, "target", k)
            self.assertEqual(outcome(flat, flat, down).first_touch, "stop", k)
            near = tuple(px(v) for v in ("100", "109.9", "95.1", "100"))  # one tick short of both levels
            self.assertIsNone(outcome(flat, flat, near).first_touch, k)

    def test_touches_before_the_shares_settle_do_not_count(self):
        o = outcome(UP, DOWN, FLAT, FLAT)  # both levels hit on T and T+1, when the shares cannot be sold
        self.assertEqual((o.first_touch, o.touch_bar), (None, None))
        self.assertEqual((o.mfe_pct, o.mae_pct), (D("11"), D("-6")))  # the excursions still record them
        self.assertEqual(outcome(UP, DOWN, FLAT, UP).touch_bar, 3)
        self.assertEqual(outcome(FLAT, DOWN, FLAT, min_hold=1).touch_bar, 1)
        self.assertEqual(outcome(FLAT, FLAT, FLAT, DOWN, UP, min_hold=3).touch_bar, 3)  # category Z: T+3

    def test_min_hold_beyond_the_horizon_means_no_touch(self):
        self.assertIsNone(outcome(UP, UP, min_hold=2).first_touch)


class NoLabel(unittest.TestCase):
    def test_short_future(self):
        self.assertIsNone(forward_outcome([], 1, D("10"), D("5")))
        self.assertIsNone(outcome(FLAT, FLAT, horizon=3))
        self.assertIsNotNone(outcome(FLAT, FLAT, horizon=2))

    def test_gap_in_the_horizon(self):
        self.assertIsNone(outcome(FLAT, FLAT, FLAT, gap_at=1))
        self.assertIsNone(outcome(FLAT, FLAT, FLAT, gap_at=2))
        self.assertIsNotNone(outcome(FLAT, FLAT, FLAT, FLAT, horizon=3, gap_at=3))  # after the horizon: ignored

    def test_non_positive_price(self):
        self.assertIsNone(outcome(("0.0", "101", "0.0", "100"), FLAT))       # entry open of zero
        self.assertIsNone(outcome(FLAT, ("100", "101", "0.0", "100")))       # MONNOCERA 2018-09-20 style low

    def test_bad_arguments(self):
        future = rows(FLAT, FLAT, FLAT)
        for horizon, target, stop, hold in ((0, "10", "5", 2), (3, "0", "5", 2), (3, "10", "0", 2),
                                            (3, "-1", "5", 2), (3, "10", "5", -1)):
            with self.assertRaises(ValueError):
                forward_outcome(future, horizon, D(target), D(stop), hold)


class StrictlyAfter(unittest.TestCase):
    def test_the_signal_bar_is_not_an_argument(self):
        self.assertEqual(list(inspect.signature(forward_outcome).parameters),
                         ["future", "horizon", "target_pct", "stop_pct", "min_hold"])

    def test_bars_after_the_horizon_do_not_change_the_label(self):
        history = make(120)
        want = forward_outcome(history[11:], 20, D("10"), D("5"))
        wrecked = history[:31] + [replace(r, close=r.close * 5, gap_flag=True) for r in history[31:]]
        self.assertEqual(forward_outcome(wrecked[11:], 20, D("10"), D("5")), want)

    def test_bars_after_the_signal_do_not_change_the_detection(self):
        plugins = R.discover()
        configs = R.configure(plugins, R.CONFIG)
        history = make(300)
        for name, cfg in configs.items():
            full = R.run(plugins[name], cfg, "T", history)
            self.assertGreater(len(full), 1, name)
            cut = (full[len(full) // 2].signal_date - D0).days  # index of a signal bar
            wrecked = history[:cut + 1] + [replace(r, close=r.close * 5, high=r.high * 9) for r in history[cut + 1:]]
            self.assertEqual([s for s in R.run(plugins[name], cfg, "T", wrecked) if s.signal_date <= history[cut].date],
                             [s for s in full if s.signal_date <= history[cut].date], name)

    @unittest.skipUnless(B.PRICES.exists() and R.ACTIONS.exists(), "data/clean is local only")
    def test_real_signals_get_labels(self):
        plugins = R.discover()
        configs = R.configure(plugins, R.CONFIG)
        history = B.rows("CROWNCEMNT")
        at = {r.date: i for i, r in enumerate(history)}
        for name, cfg in configs.items():
            signals = R.run(plugins[name], cfg, "CROWNCEMNT", history, R.ex_dates(R.ACTIONS).get("CROWNCEMNT", ()))
            got = [forward_outcome(history[at[s.signal_date] + 1:], 20, D("10"), D("5")) for s in signals]
            labeled = [o for o in got if o]
            self.assertGreater(len(labeled), len(got) // 2, name)
            self.assertTrue(all(o.mae_pct <= o.ret_pct <= o.mfe_pct and o.mae_pct <= 0 <= o.mfe_pct for o in labeled))


if __name__ == "__main__":
    unittest.main()
