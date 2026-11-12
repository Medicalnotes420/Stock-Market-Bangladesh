import random
import unittest
from datetime import date, timedelta
from decimal import Decimal

from chartapp.bars import Bar
from chartapp.geometry import Pivot, pivots


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


if __name__ == "__main__":
    unittest.main()
