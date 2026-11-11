import unittest
from decimal import Decimal

import pandas as pd

from dse_quant.plan import plan, replay


def frame(rows):
    """rows: (open, high, low, close)."""
    idx = pd.bdate_range("2025-01-01", periods=len(rows))
    return pd.DataFrame(rows, idx, columns=["open", "high", "low", "close"]).assign(volume=1_000_000.0)


FLAT = [(100, 101, 99, 100)] * 20  # 20-day low 99 -> stop 99, risk 1, 2R target 102


class TestReplay(unittest.TestCase):
    def test_target_first(self):
        out = replay(frame(FLAT + [(100, 102.5, 99.5, 102)]), horizon=1)
        self.assertEqual(out[-1], ("target", 2.0, 2.0))

    def test_stop_checked_first_and_gap_fills_at_open(self):
        both = replay(frame(FLAT + [(100, 103, 98, 100)]), horizon=1)
        self.assertEqual(both[-1][:2], ("stop", -1.0))
        gap = replay(frame(FLAT + [(96, 97, 95, 96)]), horizon=1)
        self.assertEqual(gap[-1][:2], ("stop", -4.0))

    def test_open_at_horizon_and_cost(self):
        out = replay(frame(FLAT + [(100, 100.5, 99.5, 100.5)]), horizon=1, cost=0.002)
        self.assertEqual(out[-1][:2], ("open", 0.5))
        self.assertAlmostEqual(out[-1][2], 0.5 - 2 * 0.002 * 100 / 1)

    def test_stop_too_tight_for_costs_skipped(self):
        self.assertEqual(replay(frame(FLAT + [(100, 102.5, 99.5, 102)]), horizon=1, cost=0.005), [])

    def test_gap_flag_skips(self):
        df = frame(FLAT + [(100, 102.5, 99.5, 102)]).assign(gap_flag=False)
        df.iloc[-1, df.columns.get_loc("gap_flag")] = True
        self.assertEqual(replay(df, horizon=1), [])


class TestPlan(unittest.TestCase):
    WIDE = [(100, 103, 97, 100)] * 80  # stop 97, risk 3, 2R target 106

    def test_size_capped_by_position_limit(self):
        p = plan(frame(self.WIDE), "X", equity=100_000, max_loss=6_000)
        self.assertAlmostEqual(p["stop"], 97)
        self.assertAlmostEqual(p["target"], 106)
        self.assertEqual(p["wanted"], 2_000)
        self.assertEqual(p["shares"], 100)  # 10% of 100,000 at Tk 100
        self.assertIn("max_position_pct", p["capped_by"])

    def test_outputs_are_tick_validated_decimals(self):
        p = plan(frame(self.WIDE), "X", equity=100_000, entry=100.04, stop=96.96, max_loss=6_000)
        self.assertEqual((p["entry"], p["stop"]), (Decimal("100.1"), Decimal("96.9")))
        for k in ("entry", "stop", "target", "value", "loss_at_stop", "max_loss"):
            self.assertIsInstance(p[k], Decimal)
        for k in ("entry", "stop", "target"):
            self.assertEqual(p[k] % Decimal("0.1"), 0)

    def test_bad_stops_rejected(self):
        for stop in (101, 99.5):  # above the entry; too close for ~0.57% costs each way
            with self.assertRaises(ValueError):
                plan(frame(self.WIDE), "X", equity=100_000, stop=stop)


if __name__ == "__main__":
    unittest.main()
