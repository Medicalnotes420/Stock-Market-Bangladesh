import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dse_long_run import build  # noqa: E402


class TestBuild(unittest.TestCase):
    def test_dollar_return_to_taka_and_real(self):
        raw = {"sp_usd_pct": pd.Series({2000: 0.0, 2001: 10.0}),
               "bdt_per_usd": pd.Series({2000: 50.0, 2001: 55.0}),  # taka weakens 10%
               "inflation_pct": pd.Series({2000: 5.0, 2001: 21.0})}
        t = build(raw)
        self.assertAlmostEqual(t.return_bdt_pct[2001], 21.0)  # 1.1 x 1.1 - 1
        self.assertAlmostEqual(t.real_return_pct[2001], 0.0)  # all of it eaten by 21% inflation
        self.assertTrue(pd.isna(t.return_bdt_pct[2000]))  # no earlier rate to compare


if __name__ == "__main__":
    unittest.main()
