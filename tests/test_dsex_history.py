import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dsex_history import drawdowns, rises  # noqa: E402


class TestDrawdowns(unittest.TestCase):
    def test_finds_recovered_and_open_falls(self):
        v = [100, 110, 80, 90, 111, 120, 100, 90, 95]  # -27% recovered, then -25% still open
        s = pd.Series(v, pd.bdate_range("2020-01-01", periods=len(v)), dtype=float)
        d = drawdowns(s)
        self.assertEqual(len(d), 2)
        self.assertEqual((d.peak[0], d.trough[0]), (110, 80))
        self.assertEqual(d.recovered[0], s.index[4])
        self.assertAlmostEqual(d.depth[1], 0.25)
        self.assertTrue(pd.isna(d.recovered[1]))

    def test_rises_between_turning_points(self):
        v = [100, 80, 90, 120, 100, 95, 110]  # low 80 -> high 120 (+50%), then low 95 -> 110 still running
        s = pd.Series(v, pd.bdate_range("2020-01-01", periods=len(v)), dtype=float)
        r = rises(s)
        self.assertEqual(list(zip(r.low, r.high)), [(80, 120), (95, 110)])
        self.assertAlmostEqual(r.rise[0], 0.5)
        self.assertEqual(list(r.running), [False, True])

    def test_small_dips_ignored(self):
        s = pd.Series([100, 90, 101, 95, 102], pd.bdate_range("2020-01-01", periods=5), dtype=float)
        self.assertTrue(drawdowns(s).empty)


if __name__ == "__main__":
    unittest.main()
