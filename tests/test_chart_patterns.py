import random
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from chartapp import bars as B, runner as R
from chartapp.bars import Bar
from chartapp.patterns import swing_breakout, trendline_break
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
        self.assertIn("trendline_break", CONFIG)

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
                # the market scan's shortcut: the same plugin on a tail of the history, recent bars only
                since = found[len(found) // 2].signal_date
                tail = B.tail(ticker, since, PLUGINS[name].LOOKBACK - 1)
                self.assertLess(len(tail), len(B.rows(ticker)), (ticker, name))
                self.assertEqual(R.run(PLUGINS[name], cfg, ticker, tail, R.ex_dates(R.ACTIONS).get(ticker, ()), since),
                                 [s for s in found if s.signal_date >= since], (ticker, name))


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


class TrendlineBreak(unittest.TestCase):
    CFG = {"reversal_pct": Decimal("10"), "min_break_pct": Decimal("1.0")}
    # Zigzag at 10%: high 120 at bar 1 (confirmed at 2), low 100 at bar 2, high 112 at bar 3 (confirmed at 4).
    # The line through the two highs falls 4 a bar: 108 at bar 4, 104, 100, 96 at bar 7, 92, 88.
    DOWN = ["100", "120", "100", "112", "100"]
    # Mirror: low 100 at bar 1, high 120 at bar 2, low 108 at bar 3 (confirmed at 4: 120 >= 118.8).
    # The line through the two lows rises 4 a bar: 112 at bar 4, 116, 120, 124 at bar 7.
    UP = ["120", "100", "120", "108", "120"]

    def fires(self, closes):
        """Indices at which detect fires when the series is revealed one bar at a time."""
        bars = series(closes)
        return [i for i in range(len(bars)) if trendline_break.detect(bars[:i + 1], self.CFG)]

    def test_bullish_break_of_falling_highs(self):
        # bar 5: 101 under the line (104). bar 6: 100.5 is over the line (100) but inside the 1% margin (101).
        # bar 7: 98 is over 96 * 1.01 = 96.96
        closes = self.DOWN + ["101", "100.5", "98"]
        bars = series(closes)
        self.assertEqual(self.fires(closes), [7])
        d = trendline_break.detect(bars, self.CFG)
        self.assertEqual(d.direction, "bullish")
        self.assertEqual([(p.date, p.price, p.role) for p in d.points],
                         [(bars[1].date, Decimal("120"), "high_1"), (bars[3].date, Decimal("112"), "high_2")])
        (seg,) = d.segments
        self.assertEqual((seg.role, seg.start.date, seg.start.price), ("resistance", bars[1].date, Decimal("120")))
        # the line ends on the signal bar, at the line's own price there, not at the close
        self.assertEqual((seg.end.date, seg.end.price, str(seg.end.price)), (bars[7].date, Decimal("96"), "96.0000"))
        self.assertEqual(dict(d.levels), {})

    def test_bearish_break_of_rising_lows(self):
        # bar 6: 119.5 is under the line (120) but inside the margin (118.8). bar 7: 122 is under 124 * 0.99 = 122.76
        closes = self.UP + ["119", "119.5", "122"]
        bars = series(closes)
        self.assertEqual(self.fires(closes), [7])
        d = trendline_break.detect(bars, self.CFG)
        self.assertEqual(d.direction, "bearish")
        self.assertEqual([(p.date, p.price, p.role) for p in d.points],
                         [(bars[1].date, Decimal("100"), "low_1"), (bars[3].date, Decimal("108"), "low_2")])
        (seg,) = d.segments
        self.assertEqual((seg.role, seg.start.date, seg.end.date, seg.end.price),
                         ("support", bars[1].date, bars[7].date, Decimal("124")))

    def test_needs_the_full_margin(self):
        self.assertEqual(self.fires(self.DOWN + ["101", "100.5", "96.96"]), [])   # exactly on the edge
        self.assertEqual(self.fires(self.DOWN + ["101", "100.5", "96.97"]), [7])
        self.assertEqual(self.fires(self.UP + ["119", "119.5", "122.76"]), [])
        self.assertEqual(self.fires(self.UP + ["119", "119.5", "122.75"]), [7])

    def test_does_not_fire_again_for_the_same_line(self):
        # breaks at 7, back under the line at 8 (90 < 92), over it again at 9 (95 > 88)
        self.assertEqual(self.fires(self.DOWN + ["101", "100.5", "98", "90", "95"]), [7])

    def test_a_line_broken_before_its_second_pivot_was_confirmed_never_fires(self):
        # bar 4: 110 is already over the line (108 * 1.01 = 109.08) but the high at 3 is only confirmed at bar 5.
        # bar 6: 103 is over the line (100) with bar 5 under it: a cross, but not the first since the pivot
        self.assertEqual(self.fires(["100", "120", "100", "112", "110", "100", "103"]), [])

    def test_the_line_must_slope_the_right_way(self):
        # highs 112 then 120 rise and the lows are both 100: neither a falling resistance nor a rising support
        self.assertEqual(self.fires(["100", "112", "100", "120", "100", "130"]), [])
        # highs 120 and 120: flat. 130 is far above that level, which is swing_breakout's business
        self.assertEqual(self.fires(["100", "120", "100", "120", "100", "130"]), [])
        # lows 100 then 90 fall (their line is at 75 on bar 6, and 70 is under it); the highs are both 120
        self.assertEqual(self.fires(["120", "100", "120", "90", "120", "100", "70"]), [])

    def test_only_closes_since_the_second_pivot_count(self):
        # highs 120 (bar 1) and 112 (bar 5), line falling 2 a bar. Bar 3 closed at 118, over the line (116)
        # between the two pivots: that is before the line existed. Bar 7: 110 > 108 * 1.01 = 109.08
        self.assertEqual(self.fires(["100", "120", "108", "118", "100", "112", "100", "110"]), [7])

    def test_uses_the_last_two_pivots_and_a_new_pivot_on_the_line_makes_a_new_pair(self):
        # line through 120 (bar 1) and 112 (bar 3) is 104 at bar 5: 106 breaks it. Price falls back and makes
        # a third high, 92 at bar 8, exactly on that line. The pair (112, 92) is new and breaks at bar 10
        # (line 84, edge 84.84, close 86)
        closes = ["100", "120", "100", "112", "100", "106", "94", "80", "92", "80", "86"]
        bars = series(closes)
        self.assertEqual(self.fires(closes), [5, 10])
        self.assertEqual([(p.date, p.price) for p in trendline_break.detect(bars, self.CFG).points],
                         [(bars[3].date, Decimal("112")), (bars[8].date, Decimal("92"))])

    def test_bullish_is_reported_when_both_lines_break_on_one_bar(self):
        # Lows 100 (bar 1) and 110 (bar 3): support rises 5 a bar, 120 at bar 5, edge 118.8.
        # Highs 200 (bar 2) and 130 (bar 4): resistance falls 35 a bar, 95 at bar 5, edge 95.95.
        # The lines have crossed, so 118 at bar 5 (which also confirms the high at 4) is beyond both.
        closes = ["150", "100", "200", "110", "130", "118"]
        self.assertEqual(self.fires(closes), [5])
        self.assertEqual(trendline_break.detect(series(closes), self.CFG).direction, "bullish")
        # the bearish break is real too: with the order of the sides swapped, the same bar reports it
        with mock.patch.object(trendline_break, "_SIDES", trendline_break._SIDES[::-1]):
            self.assertEqual(self.fires(closes), [5])
            self.assertEqual(trendline_break.detect(series(closes), self.CFG).direction, "bearish")

    def test_no_signal_before_the_second_pivot_is_confirmed(self):
        # 113 is far over where the line would be, but the high at bar 3 has not reversed yet
        self.assertEqual(self.fires(["100", "120", "100", "112", "111", "113"]), [])

    def test_a_non_positive_close_since_the_second_pivot_means_no_signal(self):
        # bar 6 (105) is over the line; crossed() cannot see that next to the zero at bar 5, so without the
        # plugin's own guard bar 8 would look like the first cross
        self.assertEqual(self.fires(self.DOWN + ["0", "105", "96.5", "95"]), [])
        self.assertEqual(self.fires(self.DOWN + ["101", "105", "96.5", "95"]), [6])

    def test_short_or_empty_history(self):
        self.assertIsNone(trendline_break.detect((), self.CFG))
        self.assertIsNone(trendline_break.detect(series(["10"]), self.CFG))

    def test_drawn_line_passes_the_runner_and_stays_plain_at_a_small_scale(self):
        closes = [str(Decimal(c) * Decimal("0.0137")) for c in self.DOWN + ["101", "100.5", "98"]]
        rows = [B.Row(b.date, b.open, b.high, b.low, b.close, 100, b.close, b.close, Decimal("1.0"), False, False,
                      False) for b in series(closes)]
        (signal,) = R.run(trendline_break, self.CFG, "T", rows)   # run() checks every returned value
        end = signal.detection.segments[0].end
        self.assertEqual((signal.signal_date, end.date, str(end.price)), (rows[7].date, rows[7].date, "1.3152"))

    def test_config_that_cannot_work_is_refused(self):
        ok = dict(trendline_break.DEFAULTS)
        trendline_break.check(ok)
        trendline_break.check(CONFIG["trendline_break"])  # what config/patterns.toml actually loads
        trendline_break.check({**ok, "min_break_pct": Decimal("99.9")})
        for change in ({"reversal_pct": Decimal("0")}, {"reversal_pct": Decimal("-5")},
                       {"min_break_pct": Decimal("-0.1")}, {"min_break_pct": Decimal("100")}):
            with self.assertRaises(ValueError, msg=change):
                trendline_break.check({**ok, **change})


if __name__ == "__main__":
    unittest.main()
