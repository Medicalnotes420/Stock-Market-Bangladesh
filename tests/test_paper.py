import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from dse_quant.limits import lock_flags
from dse_quant.paper.harness import daily_run, load_state
from dse_quant.paper.monitor import summarize
from tests.helpers import bars

TYPES = {f"T{k}": "Equity" for k in range(6)} | {"00DSEX": "Index"}


def world(n=320):
    rng = np.random.default_rng(3)
    frames = [bars("00DSEX", (5000 * np.cumprod(1 + rng.normal(0.0005, 0.008, n))).round(2), volume=1e9)]
    for k in range(6):
        b = bars(f"T{k}", (30 * np.cumprod(1 + rng.normal(0.0003, 0.015, n))).round(1), volume=2e6)
        b["high"], b["low"] = b.close * 1.01, b.close * 0.99
        frames.append(b)
    df = lock_flags(pd.concat(frames, ignore_index=True).assign(close_raw=lambda d: d.close, gap_flag=False))
    eq = df[df.ticker != "00DSEX"]
    eq = eq.assign(ret=eq.close / eq.groupby("ticker").close.shift() - 1)
    market = pd.DataFrame({
        "dsex": df[df.ticker == "00DSEX"].set_index("date").close,
        "turnover": eq.groupby("date").value.sum(),
        "adv": eq[eq.ret > 0].groupby("date").size(), "dec": eq[eq.ret < 0].groupby("date").size(),
        "n": eq.groupby("date").size()}).fillna(0)
    return df, market


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.paths = dict(state_path=self.tmp / "state.json", journal_path=self.tmp / "journal.jsonl",
                          orders_dir=self.tmp / "orders")
        self.df, self.m = world()
        self.last = self.df.date.max()

    def journal(self):
        return [json.loads(l) for l in (self.tmp / "journal.jsonl").read_text().splitlines()]

    def test_healthy_day_no_strategy_gives_cash_and_journals(self):
        e = daily_run(self.df, self.m, TYPES, self.last, **self.paths)
        self.assertTrue(e["gate_open"])
        self.assertEqual(e["orders"], [])
        self.assertIn(e["regime"], {"RISK_ON", "NEUTRAL", "RISK_OFF", "STRESS"})
        self.assertEqual(len(self.journal()), 1)
        self.assertTrue((self.tmp / "orders" / f"orders_{self.last.date()}.csv").exists())
        self.assertIn("inputs_hash", e)

    def test_stale_data_blocks_and_alerts(self):
        e = daily_run(self.df, self.m, TYPES, self.last + pd.offsets.BDay(3), **self.paths)
        self.assertFalse(e["gate_open"])
        self.assertIn("stale_data", e["gate_reasons"])
        self.assertEqual(e["orders"], [])

    def test_corrupt_input_never_raises_and_blocks(self):
        e = daily_run(self.df.drop(columns=["close"]), self.m, TYPES, self.last, **self.paths)
        self.assertFalse(e["gate_open"])
        self.assertTrue(e["alerts"])
        self.assertEqual(len(self.journal()), 1)

    def test_kill_switch_writes_exit_list(self):
        held = {"cash": 1e6, "peak_equity": 1e7, "day_start_equity": 1.2e6,
                "positions": {"T1": 1000, "T2": 500}}
        self.paths["state_path"].write_text(json.dumps(held))
        e = daily_run(self.df, self.m, TYPES, self.last, **self.paths)
        self.assertTrue(e["kill"])
        self.assertEqual({r["ticker"] for r in e["exit_list"]}, {"T1", "T2"})
        self.assertFalse(e["gate_open"])

    def check_bad_state(self, text):
        self.paths["state_path"].write_text(text)
        e = daily_run(self.df, self.m, TYPES, self.last, **self.paths)   # must not raise
        self.assertFalse(e["gate_open"])
        self.assertIn("state_error", e["gate_reasons"])
        self.assertTrue(any("state error" in a for a in e["alerts"]))
        self.assertEqual(len(self.journal()), 1)
        self.assertEqual(self.paths["state_path"].read_text(), text)       # left as found, for inspection
        s = summarize(self.paths["journal_path"])                          # monitor copes with no equity
        self.assertEqual(s["runs"], 1)

    def test_zero_equity_state_never_skips_journal(self):
        self.check_bad_state(json.dumps({"cash": 0, "peak_equity": 0, "day_start_equity": 0, "positions": {}}))

    def test_corrupt_state_file_never_skips_journal(self):
        self.check_bad_state("{not json")

    def test_rerun_same_day_keeps_daily_loss_baseline(self):
        prev = str(self.df.date.unique()[-2].date())
        self.paths["state_path"].write_text(json.dumps(
            {"asof": prev, "equity": 1e7, "day_start_equity": 1e7, "cash": 9.7e6, "peak_equity": 1e7, "positions": {}}))
        for _ in range(2):  # -3% vs yesterday's close, on both runs
            e = daily_run(self.df, self.m, TYPES, self.last, **self.paths)
            self.assertIn("max_daily_loss", e["gate_reasons"])

    def test_input_error_day_does_not_move_state(self):
        text = json.dumps({"asof": "2020-01-01", "equity": 1e7, "day_start_equity": 1e7, "cash": 1e6,
                           "peak_equity": 1e7, "positions": {"T1": 1000}})
        self.paths["state_path"].write_text(text)
        daily_run(self.df.drop(columns=["close"]), self.m, TYPES, self.last, **self.paths)
        self.assertEqual(self.paths["state_path"].read_text(), text)

    def test_run_older_than_last_is_refused(self):
        text = json.dumps({"asof": str(self.last.date()), "equity": 1e7, "day_start_equity": 1e7, "cash": 1e7,
                           "peak_equity": 1e7, "positions": {}})
        self.paths["state_path"].write_text(text)
        e = daily_run(self.df, self.m, TYPES, self.df.date.unique()[-5], **self.paths)
        self.assertIn("state_error", e["gate_reasons"])
        self.assertEqual(self.paths["state_path"].read_text(), text)

    def test_journal_is_append_only_and_state_persists(self):
        daily_run(self.df, self.m, TYPES, self.df.date.unique()[-2], **self.paths)
        daily_run(self.df, self.m, TYPES, self.last, **self.paths)
        self.assertEqual(len(self.journal()), 2)
        self.assertAlmostEqual(load_state(self.paths["state_path"])["cash"], 1e7)


class Monitor(unittest.TestCase):
    def test_summary_flags_broken_feed(self):
        tmp = Path(tempfile.mkdtemp())
        rows = [{"asof": f"2026-01-0{i}", "gate_open": False, "gate_reasons": ["stale_data"], "regime": "UNKNOWN",
                 "equity": 1e7, "kill": False, "alerts": []} for i in range(1, 5)]
        (tmp / "j.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        s = summarize(tmp / "j.jsonl")
        self.assertEqual(s["runs"], 4)
        self.assertEqual(s["max_consecutive_stale"], 4)
        self.assertIn("data feed broken", " ".join(s["alerts"]))
        self.assertEqual(s["max_drawdown"], 0.0)


if __name__ == "__main__":
    unittest.main()
