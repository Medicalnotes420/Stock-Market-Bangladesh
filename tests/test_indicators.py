import unittest

import numpy as np
import pandas as pd

from dse_quant.indicators import adx, aroon_up, bollinger, macd, mfi, rsi

idx = pd.bdate_range("2020-01-01", periods=60)
up = pd.Series(np.linspace(10, 20, 60), idx)
down = pd.Series(np.linspace(20, 10, 60), idx)
flat = pd.Series(10.0, idx)


class NewIndicators(unittest.TestCase):
    def test_stoch_cci_atr(self):
        from dse_quant.indicators import atr, cci, ema, stoch
        hi, lo = up + 0.5, up - 0.5
        k, d = stoch(hi, lo, up)
        self.assertAlmostEqual(k.iloc[-1], 100 * (13 * 10 / 59 + .5) / (13 * 10 / 59 + 1))  # close .5 under the 14-day high
        self.assertTrue(k.iloc[:13].isna().all())
        self.assertTrue(stoch(flat, flat, flat)[0].isna().all())  # no range -> undefined, not a divide error
        self.assertGreater(cci(hi, lo, up).iloc[-1], 0)
        self.assertLess(cci(down + .5, down - .5, down).iloc[-1], 0)
        self.assertAlmostEqual(atr(flat + 1, flat - 1, flat).iloc[-1], 2.0)
        self.assertAlmostEqual(ema(flat, 10).iloc[-1], 10.0)


class Indicators(unittest.TestCase):
    def test_rsi_extremes(self):
        self.assertAlmostEqual(rsi(up).iloc[-1], 100.0)
        self.assertAlmostEqual(rsi(down).iloc[-1], 0.0)

    def test_rsi_known_value(self):
        # alternating +1/-1 has equal average gain and loss -> 50 in the long run
        s = pd.Series(10 + np.tile([0.0, 1.0], 100), pd.bdate_range("2020-01-01", periods=200))
        self.assertAlmostEqual(rsi(s).iloc[-1], 50.0, delta=2.0)

    def test_macd_zero_on_flat(self):
        line, signal = macd(flat)
        self.assertAlmostEqual(line.iloc[-1], 0.0)
        self.assertAlmostEqual(signal.iloc[-1], 0.0)

    def test_macd_positive_in_uptrend(self):
        line, signal = macd(up)
        self.assertGreater(line.iloc[-1], 0)

    def test_bollinger_flat_has_zero_width(self):
        upper, mid, lower, width = bollinger(flat)
        self.assertAlmostEqual(width.iloc[-1], 0.0)
        self.assertAlmostEqual(mid.iloc[-1], 10.0)

    def test_aroon_up_is_100_at_new_high_and_drops_after(self):
        self.assertAlmostEqual(aroon_up(up).iloc[-1], 100.0)
        s = pd.concat([up, pd.Series(19.0, pd.bdate_range(idx[-1] + pd.offsets.BDay(), periods=5))])
        self.assertAlmostEqual(aroon_up(s).iloc[-1], 100 * (25 - 5) / 25)

    def test_adx_direction(self):
        hi, lo = up * 1.01, up * 0.99
        a, pdi, mdi = adx(hi, lo, up)
        self.assertGreater(pdi.iloc[-1], mdi.iloc[-1])
        self.assertGreater(a.iloc[-1], 25)

    def test_mfi_extremes(self):
        value = pd.Series(1e6, idx)
        self.assertAlmostEqual(mfi(up * 1.01, up * 0.99, up, value).iloc[-1], 100.0)
        self.assertAlmostEqual(mfi(down * 1.01, down * 0.99, down, value).iloc[-1], 0.0)

    def test_works_column_wise_on_panels(self):
        panel = pd.DataFrame({"A": up, "B": down})
        r = rsi(panel).iloc[-1]
        self.assertAlmostEqual(r["A"], 100.0)
        self.assertAlmostEqual(r["B"], 0.0)


if __name__ == "__main__":
    unittest.main()
