import unittest

import pandas as pd

from dse_quant.data.adjust import apply_actions, infer_actions
from tests.helpers import bars


def bonus_case():
    """100% bonus (1:1) on day 5: raw price halves, vendor 'adjusted' series is continuous."""
    # 15 sessions after the ex-date so the 10-session persistence check can confirm it
    raw = bars("X", [100, 101, 102, 103, 104] + [52 + i for i in range(15)], volume=1000)
    adj = raw.copy()
    adj.loc[:4, ["open", "high", "low", "close"]] /= 2
    return raw, adj


class Infer(unittest.TestCase):
    def test_confirmed_bonus_found(self):
        raw, adj = bonus_case()
        acts = infer_actions(raw, adj)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts.date.iloc[0], raw.date.iloc[5])
        self.assertAlmostEqual(acts.ratio.iloc[0], 2.0)

    def test_reverting_vendor_step_rejected(self):
        raw = bars("X", [100.0] * 30)
        adj = raw.copy()
        adj.loc[10:12, "close"] = 50.0                   # step that reverts 3 days later
        self.assertEqual(len(infer_actions(raw, adj)), 0)

    def test_step_without_raw_drop_rejected(self):
        raw = bars("X", [100.0] * 30)
        adj = raw.copy()
        adj.loc[:9, "close"] = 50.0                      # vendor claims action, raw price didn't fall
        self.assertEqual(len(infer_actions(raw, adj)), 0)


class Apply(unittest.TestCase):
    def test_series_continuous_and_volume_scaled(self):
        raw, adj = bonus_case()
        out = apply_actions(raw, infer_actions(raw, adj))
        self.assertAlmostEqual(out.close.iloc[4], 52.0)
        self.assertAlmostEqual(out.close.iloc[5], 52.0)
        self.assertEqual(out.volume.iloc[0], 2000)
        self.assertEqual(out.volume.iloc[5], 1000)

    def test_value_and_raw_close_untouched(self):
        raw, adj = bonus_case()
        out = apply_actions(raw, infer_actions(raw, adj))
        self.assertEqual(out.value.tolist(), raw.value.tolist())
        self.assertEqual(out.close_raw.tolist(), raw.close.tolist())

    def test_input_not_modified(self):
        raw, adj = bonus_case()
        before = raw.copy()
        apply_actions(raw, infer_actions(raw, adj))
        pd.testing.assert_frame_equal(raw, before)

    def test_no_actions_is_identity(self):
        raw, _ = bonus_case()
        out = apply_actions(raw, infer_actions(raw, raw))
        self.assertEqual(out.close.tolist(), raw.close.tolist())


if __name__ == "__main__":
    unittest.main()
