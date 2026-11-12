import random
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from chartapp import bars as B, runner as R
from chartapp.bars import Bar
from chartapp.patterns import swing_breakout
from tests.test_chart_runner import make

D0 = date(2026, 1, 1)
PLUGINS = R.discover()
CONFIG = R.configure(PLUGINS, R.CONFIG)


def series(closes):
    """Bars with the given closes; high and low sit one tenth either side."""
    tenth = Decimal("0.1")
    return tuple(Bar(D0 + timedelta(days=i), c, c + tenth, c - tenth, c, 100)
                 for i, c in enumerate(map(Decimal, closes)))


def scaled(rows, k):
    return [replace(r, open=r.open * k, high=r.high * k, low=r.low * k, close=r.close * k, close_raw=r.close_raw * k)
            for r in rows]


class EveryPlugin(unittest.TestCase):
    """Design 7.2: these hold for any plugin, so they run over whatever is installed."""

    def test_there_is_something_to_test(self):
        self.assertIn("swing_breakout", CONFIG)

    def test_scale_does_not_change_the_signals(self):
        rows = make(600)
        for name, cfg in CONFIG.items():
            base = R.run(PLUGINS[name], cfg, "T", rows)
            self.assertGreater(len(base), 3, name)
            for k in (Decimal("0.5"), Decimal("3"), Decimal("0.0137")):
                got = R.run(PLUGINS[name], cfg, "T", scaled(rows, k))
                self.assertEqual([s.signal_date for s in got], [s.signal_date for s in base], (name, k))
                for a, b in zip(base, got):
                    self.assertEqual([p.price * k for p in a.detection.points], [p.price for p in b.detection.points])
                    self.assertEqual({n: v * k for n, v in a.detection.levels.items()}, dict(b.detection.levels))

    def test_same_window_same_answer_in_any_order(self):
        view = B.bars(tuple(make(400)))
        for name, cfg in CONFIG.items():
            p = PLUGINS[name]
            windows = [view[max(0, i + 1 - p.LOOKBACK):i + 1] for i in range(len(view))]
            in_order = [p.detect(w, cfg) for w in windows]
            self.assertTrue(any(in_order), name)
            order = list(range(len(windows)))
            random.Random(1).shuffle(order)
            shuffled = {i: p.detect(windows[i], cfg) for i in order}
            self.assertEqual([shuffled[i] for i in range(len(windows))], in_order, name)

    def test_a_shorter_history_gives_the_same_signals(self):
        rows = make(300)
        for name, cfg in CONFIG.items():
            full = R.run(PLUGINS[name], cfg, "T", rows)
            for k in range(0, len(rows) + 1, 7):
                want = [s for s in full if s.signal_date <= rows[k - 1].date] if k else []
                self.assertEqual(R.run(PLUGINS[name], cfg, "T", rows[:k]), want, (name, k))

    @unittest.skipUnless(B.PRICES.exists() and R.ACTIONS.exists(), "data/clean is local only")
    def test_real_tickers_keep_the_contract(self):
        for ticker in ("CROWNCEMNT", "MONNOCERA", "00DSEX"):  # MONNOCERA has a bar with low 0.0
            for name, cfg in CONFIG.items():
                found = R.run(PLUGINS[name], cfg, ticker, B.rows(ticker), R.ex_dates(R.ACTIONS).get(ticker, ()))
                self.assertGreater(len(found), 0, (ticker, name))  # run() raises on any contract breach


class SwingBreakout(unittest.TestCase):
    CFG = {"left": 2, "right": 2, "min_break_pct": Decimal("1.0")}
    # swing high 15 at index 3 (high 15.1), confirmed at index 5; breakout level 15.1 * 1.01 = 15.251
    BASE = ["10", "12", "13", "15", "13", "12"]

    def fires(self, closes):
        """Indices at which detect fires when the series is revealed one bar at a time."""
        bars = series(closes)
        return [i for i in range(len(bars)) if swing_breakout.detect(bars[:i + 1], self.CFG)]

    def test_fires_on_the_first_close_above_the_level(self):
        bars = series(self.BASE + ["14", "15.3", "16"])
        self.assertEqual(self.fires(self.BASE + ["14", "15.3", "16"]), [7])
        d = swing_breakout.detect(bars[:8], self.CFG)
        self.assertEqual(d.direction, "bullish")
        self.assertEqual([(p.date, p.price, p.role) for p in d.points], [(bars[3].date, Decimal("15.1"), "swing_high")])
        self.assertEqual(dict(d.levels), {"breakout": Decimal("15.251")})

    def test_needs_the_full_margin(self):
        self.assertEqual(self.fires(self.BASE + ["15.2", "15.25"]), [])   # above the high, inside the margin
        self.assertEqual(self.fires(self.BASE + ["15.251"]), [])          # exactly on the level
        self.assertEqual(self.fires(self.BASE + ["15.2511"]), [6])

    def test_does_not_fire_again_for_the_same_high(self):
        # breaks out at 6, dips under the level at 7, crosses again at 8. Bar 8 is higher than bar 6, so bar 6
        # never becomes a swing high: the second crossing is measured against the same high and must not fire
        self.assertEqual(self.fires(self.BASE + ["15.3", "15.2", "15.35"]), [6])

    def test_no_signal_before_the_high_is_confirmed(self):
        self.assertEqual(self.fires(["10", "12", "13", "15", "13"]), [])  # one bar after the high: not confirmed
        self.assertEqual(self.fires(["10", "11", "12", "13", "14", "15", "16"]), [])  # no swing high at all

    def test_breaks_the_most_recent_swing_high_not_an_older_one(self):
        # highs at 3 (15.1) and 8 (13.1); 13.5 clears the newer one only
        closes = self.BASE + ["11", "12", "13", "12", "11", "13.5"]
        bars = series(closes)
        self.assertEqual(self.fires(closes), [11])
        self.assertEqual(swing_breakout.detect(bars, self.CFG).points[0].date, bars[8].date)

    def test_short_or_empty_history(self):
        self.assertIsNone(swing_breakout.detect((), self.CFG))
        self.assertIsNone(swing_breakout.detect(series(["10"]), self.CFG))

    def test_config_that_cannot_work_is_refused(self):
        ok = dict(swing_breakout.DEFAULTS)
        swing_breakout.check(ok)
        swing_breakout.check(CONFIG["swing_breakout"])  # what config/patterns.toml actually loads
        swing_breakout.check({**ok, "left": 59, "right": 59})  # the largest that still fits LOOKBACK
        for change in ({"left": 2, "right": 3}, {"right": 0}, {"left": 60, "right": 59},
                       {"min_break_pct": Decimal("-0.1")}):
            with self.assertRaises(ValueError, msg=change):
                swing_breakout.check({**ok, **change})

    def test_largest_allowed_windows_can_still_fire(self):
        closes = [str(100 + i) for i in range(59)] + ["200"] + [str(150 - i) for i in range(59)] + ["300"]
        bars = series(closes)
        self.assertEqual(len(bars), swing_breakout.LOOKBACK)
        cfg = {"left": 59, "right": 59, "min_break_pct": Decimal("0.5")}
        self.assertEqual(swing_breakout.detect(bars, cfg).points[0].date, bars[59].date)


if __name__ == "__main__":
    unittest.main()
