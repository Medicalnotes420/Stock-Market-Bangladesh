import random
import unittest
from datetime import date, timedelta
from decimal import Decimal

from chartapp.bars import Bar
from chartapp.geometry import Line, Pivot, crossed, fit, line_through, pivots, touches, value_at, zigzag


def make(pairs):
    """Bars from (high, low) pairs; open and close sit on the low and high."""
    d0 = date(2026, 1, 1)
    return tuple(Bar(d0 + timedelta(days=i), Decimal(lo), Decimal(hi), Decimal(lo), Decimal(hi), 100)
                 for i, (hi, lo) in enumerate(pairs))


# a W: down to 10, up to 15, down to 11, up to 18
W = make([("20", "19"), ("17", "16"), ("11", "10"), ("13", "12"), ("15", "14"), ("13", "12"), ("12", "11"),
          ("14", "13"), ("16", "15"), ("18", "17"), ("17", "16")])


class Pivots(unittest.TestCase):
    def test_w_shape(self):
        self.assertEqual(pivots(W, 2, 2), [
            Pivot(2, 4, "low", Decimal("10")),
            Pivot(4, 6, "high", Decimal("15")),
            Pivot(6, 8, "low", Decimal("11")),
        ])  # the high at 9 has one bar after it, so it is not confirmed yet

    def test_pivot_appears_exactly_when_confirmed(self):
        idx, right = 4, 2
        highs = lambda bs: [p.idx for p in pivots(bs, 2, right) if p.kind == "high"]  # noqa: E731
        self.assertNotIn(idx, highs(W[:idx + right]))
        self.assertIn(idx, highs(W[:idx + right + 1]))

    def test_prefix_never_knows_more(self):
        rng = random.Random(7)
        pairs, lo = [], 100
        for _ in range(300):
            lo = max(1, lo + rng.randint(-5, 5))
            pairs.append((str(lo + rng.randint(0, 4)), str(lo)))
        bars = make(pairs)
        for left, right in ((1, 1), (3, 2), (5, 5), (3, 1)):
            full = pivots(bars, left, right)
            self.assertGreater(len(full), 10)
            self.assertTrue(all(p.confirmed_idx == p.idx + right for p in full))
            for k in range(len(bars) + 1):
                self.assertEqual(pivots(bars[:k], left, right), [p for p in full if p.confirmed_idx <= k - 1])
            # the runner slides a window: it must see the same pivots, minus those too close to its left edge
            for s, e in ((0, 300), (1, 40), (37, 120), (150, 151), (200, 300), (299, 300)):
                want = [Pivot(p.idx - s, p.confirmed_idx - s, p.kind, p.price) for p in full
                        if p.idx >= s + left and p.confirmed_idx <= e - 1]
                self.assertEqual(pivots(bars[s:e], left, right), want, (left, right, s, e))

    def test_equal_highs_further_apart_than_the_window_are_both_pivots(self):
        bars = make([("10", "9"), ("11", "9"), ("15", "9"), ("12", "9"), ("13", "9"), ("15", "9"), ("12", "9"),
                     ("11", "9"), ("10", "9")])
        self.assertEqual([p.idx for p in pivots(bars, 2, 2) if p.kind == "high"], [2, 5])
        # with a look-back that reaches the first 15, the second is no longer a pivot
        longer = make([("9", "9")]) + tuple(bars)  # one more bar so index 3 has three bars before it
        self.assertEqual([p.price for p in pivots(longer, 3, 2) if p.kind == "high"], [Decimal("15")])

    def test_equal_highs_earliest_wins(self):
        bars = make([("10", "9"), ("11", "9"), ("15", "9"), ("12", "9"), ("15", "9"), ("12", "9"), ("11", "9")])
        self.assertEqual([p.idx for p in pivots(bars, 2, 2) if p.kind == "high"], [2])

    def test_equal_lows_earliest_wins(self):
        bars = make([("20", "12"), ("20", "11"), ("20", "8"), ("20", "10"), ("20", "8"), ("20", "10"), ("20", "11")])
        self.assertEqual([p.idx for p in pivots(bars, 2, 2) if p.kind == "low"], [2])

    def test_outside_bar_is_both(self):
        bars = make([("10", "8"), ("11", "7"), ("15", "3"), ("11", "7"), ("10", "8")])
        self.assertEqual([(p.idx, p.kind) for p in pivots(bars, 2, 2)], [(2, "high"), (2, "low")])

    def test_zero_price_is_never_a_pivot(self):
        bars = make([("20", "12"), ("20", "11"), ("20", "0.0"), ("20", "10"), ("20", "11")])
        self.assertEqual(pivots(bars, 2, 2), [])

    def test_too_few_bars(self):
        self.assertEqual(pivots((), 2, 2), [])
        self.assertEqual(pivots(W[:4], 2, 2), [])

    def test_window_sizes(self):
        for left, right in ((0, 2), (2, 0), (-1, 2), (2, 3)):  # (2, 3): look-back shorter than look-ahead
            with self.assertRaises(ValueError):
                pivots(W, left, right)

    def test_prices_stay_decimal(self):
        self.assertTrue(all(type(p.price) is Decimal for p in pivots(W, 2, 2)))


def closes(values):
    """Bars with the given closes. Highs and lows are wild on purpose: zigzag must read closes only."""
    d0 = date(2026, 1, 1)
    return tuple(Bar(d0 + timedelta(days=i), c, c * 3, Decimal(0), c, 100) for i, c in enumerate(map(Decimal, values)))


def walk(n, seed):
    rng, c, out = random.Random(seed), 100, []
    for _ in range(n):
        c = max(20, c + rng.randint(-6, 6))
        out.append(c)
    return closes(out)


def scan(bars, pct):
    """The textbook zigzag, written a different way from geometry.zigzag: one pass from the first bar,
    tracking the running extreme. Its first pivot is measured from the series' edge, so it is not trusted."""
    g, x, out = 1 + Decimal(pct) / 100, [b.close for b in bars], []
    hi = lo = 0  # index of the running high and low; direction unknown until the first reversal
    direction = None
    for i in range(1, len(x)):
        if direction != "down" and x[i] > x[hi]:
            hi = i
        if direction != "up" and x[i] < x[lo]:
            lo = i
        if direction != "down" and x[i] * g <= x[hi]:
            out.append(Pivot(hi, i, "high", x[hi]))
            direction, lo = "down", i
        elif direction != "up" and x[i] >= x[lo] * g:
            out.append(Pivot(lo, i, "low", x[lo]))
            direction, hi = "up", i
    return out


def evidence(bars, p, pct):
    """Index of the nearest earlier close a full reversal away from pivot p: the bar a window must hold."""
    g = 1 + Decimal(pct) / 100
    for a in range(p.idx - 1, -1, -1):
        c = bars[a].close
        if (c * g <= p.price) if p.kind == "high" else (c >= p.price * g):
            return a
    raise AssertionError(f"{p} has no backward reversal")


class Zigzag(unittest.TestCase):
    #          0      1     2     3     4     5     6     7     8      9      10    11
    SHAPE = ["100", "95", "90", "93", "88", "92", "99", "97", "105", "100", "94", "96"]

    def test_hand_built(self):
        # 10%: the low is 88 (bar 4), first closed 10% above at bar 6 (99 >= 96.8), and 100 at bar 0 is
        # the fall into it. The high is 105 (bar 8), first closed 10% below at bar 10 (94 * 1.1 = 103.4).
        # Bar 0 is 10% above bar 2 but nothing shows the rise into it; bar 10 has not reversed yet.
        self.assertEqual(zigzag(closes(self.SHAPE), Decimal("10")),
                         [Pivot(4, 6, "low", Decimal("88")), Pivot(8, 10, "high", Decimal("105"))])

    def test_smaller_moves_are_ignored_and_larger_thresholds_find_less(self):
        self.assertEqual([p.idx for p in zigzag(closes(self.SHAPE), Decimal("4"))], [4, 8])  # 90->93 is 3.3%
        self.assertEqual([p.idx for p in zigzag(closes(self.SHAPE), Decimal("3"))], [2, 3, 4, 8])
        self.assertEqual(zigzag(closes(self.SHAPE), Decimal("15")), [])

    def test_pivot_appears_exactly_when_confirmed(self):
        bars = closes(self.SHAPE)
        self.assertEqual(zigzag(bars[:6], Decimal("10")), [])
        self.assertEqual(zigzag(bars[:7], Decimal("10")), [Pivot(4, 6, "low", Decimal("88"))])
        self.assertEqual(len(zigzag(bars[:10], Decimal("10"))), 1)
        self.assertEqual(len(zigzag(bars[:11], Decimal("10"))), 2)

    def test_exact_reversal_counts(self):
        self.assertEqual(zigzag(closes(["110", "100", "110"]), Decimal("10")), [Pivot(1, 2, "low", Decimal("100"))])
        self.assertEqual(zigzag(closes(["110", "100", "109.99"]), Decimal("10")), [])

    def test_equal_closes_earliest_wins(self):
        self.assertEqual(zigzag(closes(["80", "100", "95", "100", "80"]), Decimal("20")),
                         [Pivot(1, 4, "high", Decimal("100"))])
        self.assertEqual(zigzag(closes(["100", "80", "85", "80", "100"]), Decimal("20")),
                         [Pivot(1, 4, "low", Decimal("80"))])

    def test_matches_a_one_pass_scan(self):
        for seed in range(12):
            bars = walk(400, seed)
            for pct in ("3", "8", "15"):
                got, ref = zigzag(bars, Decimal(pct)), scan(bars, pct)
                self.assertGreater(len(got), 2, (seed, pct))
                # the scan's first pivot is only sometimes real; everything after it must agree exactly
                self.assertIn(got, (ref, ref[1:]), (seed, pct))

    def test_alternates_and_every_leg_is_big_enough(self):
        bars, g = walk(600, 5), Decimal("1.08")
        zz = zigzag(bars, Decimal("8"))
        self.assertGreater(len(zz), 10)
        for a, b in zip(zz, zz[1:]):
            self.assertNotEqual(a.kind, b.kind)
            self.assertLess(a.idx, b.idx)
            self.assertLessEqual(a.confirmed_idx, b.idx)  # a pivot is confirmed before the next one forms
            low, high = sorted((a.price, b.price))
            self.assertGreaterEqual(high, low * g)
        self.assertTrue(all(p.idx < p.confirmed_idx and p.price == bars[p.idx].close for p in zz))

    def test_prefix_never_knows_more_and_a_window_never_changes_an_answer(self):
        bars = walk(300, 11)
        for pct in ("4", "9"):
            full = zigzag(bars, Decimal(pct))
            self.assertGreater(len(full), 8)
            for k in range(len(bars) + 1):
                self.assertEqual(zigzag(bars[:k], Decimal(pct)), [p for p in full if p.confirmed_idx <= k - 1])
            dropped = 0
            for s in range(0, 300, 7):
                for e in (s + 1, s + 30, s + 120, 300):
                    e = min(e, 300)
                    want = [Pivot(p.idx - s, p.confirmed_idx - s, p.kind, p.price) for p in full
                            if evidence(bars, p, pct) >= s and p.confirmed_idx <= e - 1]
                    dropped += sum(1 for p in full if s <= p.idx and p.confirmed_idx <= e - 1) - len(want)
                    self.assertEqual(zigzag(bars[s:e], Decimal(pct)), want, (pct, s, e))
            self.assertGreater(dropped, 0)  # some windows did cut a pivot off from its evidence

    def test_non_positive_close_is_not_a_pivot_and_not_evidence(self):
        # without the guard bar 2 would be a low and would also count as "the fall" behind bar 3
        self.assertEqual(zigzag(closes(["100", "80", "0", "100", "80"]), Decimal("20")), [])
        # 70 at bar 3 would be a low (100 at bar 0 behind it, 100 at bar 4 ahead) but the bad bar is in the way.
        # Bar 4 is still a high: its evidence, bar 3, is on its own side of the bad bar.
        self.assertEqual(zigzag(closes(["100", "80", "0.0", "70", "100", "80", "100"]), Decimal("20")),
                         [Pivot(4, 5, "high", Decimal("100")), Pivot(5, 6, "low", Decimal("80"))])
        self.assertEqual([p.idx for p in zigzag(closes(["100", "80", "75", "70", "100", "80", "100"]), Decimal("20"))],
                         [3, 4, 5])

    def test_reads_closes_only(self):
        bars = closes(self.SHAPE)
        calm = tuple(Bar(b.date, b.close, b.close, b.close, b.close, 1) for b in bars)
        self.assertEqual(zigzag(bars, Decimal("10")), zigzag(calm, Decimal("10")))

    def test_scale_does_not_move_pivots(self):
        bars = walk(300, 2)
        base = zigzag(bars, Decimal("7"))
        for k in ("0.5", "3", "0.0137"):
            got = zigzag(closes([b.close * Decimal(k) for b in bars]), Decimal("7"))
            self.assertEqual([(p.idx, p.confirmed_idx, p.kind) for p in got],
                             [(p.idx, p.confirmed_idx, p.kind) for p in base])

    def test_bad_threshold_and_short_input(self):
        for pct in ("0", "-5"):
            with self.assertRaises(ValueError):
                zigzag(closes(self.SHAPE), Decimal(pct))
        self.assertEqual(zigzag((), Decimal("5")), [])
        # a threshold so small that 1 + pct/100 rounds to 1: equal closes are still not a reversal
        self.assertEqual(zigzag(closes(["5", "5", "5"]), Decimal("1e-26")), [])
        self.assertEqual(zigzag(closes(["100", "50"]), Decimal("5")), [])


def P(idx, price, kind="low"):
    return Pivot(idx, idx, kind, Decimal(price))


class Lines(unittest.TestCase):
    def test_line_through_and_value_at(self):
        line = line_through(P(2, "10"), P(6, "12"))
        self.assertEqual(line, Line(2, Decimal("10"), Decimal("0.5")))
        self.assertEqual([value_at(line, i) for i in (0, 2, 6, 10)], [Decimal(v) for v in ("9", "10", "12", "14")])
        self.assertEqual(value_at(line_through(P(6, "12"), P(2, "10")), 10), Decimal("14"))  # order is free
        self.assertIs(type(value_at(line, 3)), Decimal)

    def test_a_slope_that_does_not_terminate_still_lands_on_the_points(self):
        # 1/3 per bar
        line = line_through(P(0, "100"), P(3, "101"))
        self.assertEqual(value_at(line, 3), Decimal("101"))
        self.assertEqual(value_at(line, 6), Decimal("102"))
        self.assertEqual(value_at(line_through(P(0, "50"), P(3, "50.5")), 6), Decimal("51"))  # same line, half scale
        self.assertEqual(value_at(line_through(P(0, "1.37"), P(7, "1.3837")), 14), Decimal("1.3974"))
        # slope 8192.37 / 177 over 1770 bars is exactly 81923.7. Plain 28-digit arithmetic gives 83517.3799...9
        a, b = P(675, "1593.68"), P(852, "9786.05")
        self.assertEqual(value_at(line_through(a, b), 2445), Decimal("83517.38"))
        self.assertEqual(value_at(fit([a, b]), 2445), Decimal("83517.38"))

    def test_a_close_exactly_on_the_edge_is_on_it_at_any_scale(self):
        # the line is 9998/99 at bar 1, which does not terminate, but 1% under it is exactly 99.98
        for k in map(Decimal, ("1", "0.5", "3", "0.0137", "7")):
            line = line_through(P(0, 101 * k), P(99, 100 * k))
            on = P(1, Decimal("99.98") * k)
            self.assertEqual(touches(line, [on], Decimal("1")), [on], k)
            self.assertFalse(crossed(line, closes([110 * k, on.price]), 1, "below", Decimal("1")), k)
            self.assertTrue(crossed(line, closes([110 * k, on.price - k / 10000]), 1, "below", Decimal("1")), k)
            # and from the other side: the line is 20000/101 at bar 1, and 1% over it is exactly 200
            line = line_through(P(-1, 0), P(100, 10000 * k))
            self.assertFalse(crossed(line, closes([k, 200 * k]), 1, "above", Decimal("1")), k)
            self.assertTrue(crossed(line, closes([k, 200 * k + k / 10000]), 1, "above", Decimal("1")), k)

    def test_same_bar_is_not_a_line(self):
        with self.assertRaises(ValueError):
            line_through(P(4, "10"), P(4, "12"))

    def test_fit(self):
        # (0,1) (1,3) (2,2): mean x 1, mean y 2, Sxy = 1, Sxx = 2, so slope 0.5 and 1.5 at bar 0
        line = fit([P(0, "1"), P(1, "3"), P(2, "2")])
        self.assertEqual((line.x0, line.y0, line.slope), (0, Decimal("1.5"), Decimal("0.5")))
        self.assertEqual(value_at(line, 4), Decimal("3.5"))
        # uneven spacing, (0,2) (1,3) (5,10): mean x 2, mean y 5, Sxy = 6 + 2 + 15 = 23, Sxx = 4 + 1 + 9 = 14,
        # so slope 23/14, and 5 - 2 * 23/14 = 12/7 at bar 0, 12/7 + 5 * 23/14 = 139/14 at bar 5
        pts = [P(0, "2"), P(1, "3"), P(5, "10")]
        self.assertLess(abs(value_at(fit(pts), 0) * 7 - 12), Decimal("1e-20"))
        self.assertLess(abs(value_at(fit(pts), 5) * 14 - 139), Decimal("1e-20"))

    def test_fit_of_two_points_is_the_line_through_them(self):
        a, b = P(3, "20"), P(10, "27")
        self.assertEqual([value_at(fit([a, b]), i) for i in (0, 3, 10, 14)],
                         [value_at(line_through(a, b), i) for i in (0, 3, 10, 14)])

    def test_fit_does_not_depend_on_where_the_window_starts(self):
        pts = [P(0, "2"), P(1, "3"), P(5, "10"), P(9, "11")]
        here, there = fit(pts), fit([P(p.idx + 37, p.price) for p in pts])
        self.assertEqual((there.x0, there.y0, there.slope), (37, here.y0, here.slope))

    def test_fit_needs_two_bars(self):
        for pts in ([], [P(1, "5")], [P(1, "5"), P(1, "6")]):
            with self.assertRaises(ValueError):
                fit(pts)

    def test_touches(self):
        flat = Line(0, Decimal("100"), Decimal("0"))
        pts = [P(1, "100.4"), P(2, "100.5"), P(3, "100.6"), P(4, "99.5"), P(5, "99.4"), P(6, "100")]
        self.assertEqual([p.idx for p in touches(flat, pts, Decimal("0.5"))], [1, 2, 4, 6])
        self.assertEqual([p.idx for p in touches(flat, pts, Decimal("0"))], [6])

    def test_tolerance_is_a_percentage_of_the_line_at_that_bar(self):
        rising = line_through(P(0, "100"), P(10, "200"))
        # both pivots are 1.5 BDT off the line: 1.5% of 100, but only 0.75% of 200
        self.assertEqual([p.idx for p in touches(rising, [P(0, "101.5"), P(10, "201.5")], Decimal("1"))], [10])
        half = line_through(P(0, "50"), P(10, "100"))
        self.assertEqual([p.idx for p in touches(half, [P(0, "50.75"), P(10, "100.75")], Decimal("1"))], [10])

    def test_touches_where_the_line_is_not_positive(self):
        falling = line_through(P(0, "10"), P(10, "0"))
        self.assertEqual(touches(falling, [P(10, "0"), P(12, "-2"), P(5, "5")], Decimal("1")), [P(5, "5")])

    def test_negative_tolerance(self):
        flat = Line(0, Decimal("100"), Decimal("0"))
        with self.assertRaises(ValueError):
            touches(flat, [P(1, "100")], Decimal("-1"))
        with self.assertRaises(ValueError):
            crossed(flat, closes(["100", "102"]), 1, "above", Decimal("-1"))


class Crossed(unittest.TestCase):
    FLAT = Line(0, Decimal("100"), Decimal("0"))
    #               0      1        2      3        4      5     6
    BARS = closes(["100", "100.9", "101", "101.1", "102", "99", "98.9"])

    def at(self, side, line=None, bars=None):
        bars = self.BARS if bars is None else bars
        return [i for i in range(len(bars)) if crossed(line or self.FLAT, bars, i, side, Decimal("1"))]

    def test_first_close_beyond_the_margin(self):
        self.assertEqual(self.at("above"), [3])   # 101 is on the edge, 101.1 is past it; bar 4 is not the first
        self.assertEqual(self.at("below"), [6])   # 99 is on the edge

    def test_uses_the_line_price_at_each_bar(self):
        rising = line_through(P(0, "100"), P(4, "104"))   # 100 101 102 103 104 105 106
        bars = closes(["100", "101", "103.5", "104.5", "104", "104", "104"])
        self.assertEqual(self.at("above", rising, bars), [2])      # 103.5 > 102 * 1.01 = 103.02
        self.assertEqual(self.at("below", rising, bars), [6])      # 104 < 106 * 0.99 = 104.94; bar 5: 104 > 103.95
        falling = line_through(P(0, "106"), P(6, "100"))  # 106 105 104 103 102 101 100
        self.assertEqual(self.at("above", falling, bars), [3])     # bar 2: 103.5 < 105.04; bar 3: 104.5 > 104.03

    def test_does_not_read_past_idx(self):
        for i in range(len(self.BARS)):
            for side in ("above", "below"):
                self.assertEqual(crossed(self.FLAT, self.BARS[:i + 1], i, side, Decimal("1")),
                                 crossed(self.FLAT, self.BARS, i, side, Decimal("1")))

    def test_first_bar_has_no_before(self):
        self.assertFalse(crossed(self.FLAT, closes(["150"]), 0, "above", Decimal("1")))

    def test_non_positive_prices_give_no_cross(self):
        self.assertEqual(self.at("above", bars=closes(["0", "102", "100", "0", "102"])), [])
        self.assertEqual(self.at("below", bars=closes(["100", "0", "100", "0"])), [])
        sinking = line_through(P(0, "2"), P(2, "0"))      # 2 1 0 -1
        self.assertEqual(self.at("above", sinking, closes(["2", "1", "5", "5"])), [])

    def test_scale(self):
        half = closes([b.close / 2 for b in self.BARS])
        self.assertEqual(self.at("above", Line(0, Decimal("50"), Decimal("0")), half), [3])
        self.assertEqual(self.at("below", Line(0, Decimal("50"), Decimal("0")), half), [6])

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            crossed(self.FLAT, self.BARS, 3, "up", Decimal("1"))
        for idx in (-1, len(self.BARS)):
            with self.assertRaises(IndexError):
                crossed(self.FLAT, self.BARS, idx, "above", Decimal("1"))


if __name__ == "__main__":
    unittest.main()
