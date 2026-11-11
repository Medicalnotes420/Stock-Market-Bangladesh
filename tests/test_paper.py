import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from dse_quant.limits import lock_flags
from dse_quant.paper.harness import daily_run, load_state
from dse_quant.paper.monitor import status_page, summarize
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

    def test_regime_labelled_when_breadth_unknown(self):
        m = self.m.copy()
        m.loc[self.last, ["adv", "dec", "n"]] = float("nan")   # only DSE's market summary for this day
        e = daily_run(self.df, m, TYPES, self.last, **self.paths)
        self.assertTrue(e["regime"].endswith("(no breadth data)"))

    def test_dse_weekend_without_bar_is_not_stale(self):
        sat = self.last + pd.offsets.Week(weekday=5)               # next Saturday: DSE closed, no bar
        e = daily_run(self.df, self.m, TYPES, sat, **self.paths)
        self.assertFalse(e["gate_open"])
        self.assertIn("dse_weekend", e["gate_reasons"])
        self.assertNotIn("stale_data", e["gate_reasons"])

    def test_stale_data_blocks_and_alerts(self):
        e = daily_run(self.df, self.m, TYPES, self.last + pd.Timedelta(days=7), **self.paths)  # a Tuesday: a DSE session with no data
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

    def test_kill_exit_list_has_matured_shares_only(self):
        held = {"cash": "1000000", "peak_equity": "10000000", "day_start_equity": "1200000",
                "positions": {"T1": 1000, "T2": 500},
                "lots": {"T1": {"entry_date": str(self.last.date()), "basis": "30000.00", "lag": 3},
                         "T2": {"entry_date": "2020-01-02", "basis": "15000.00", "lag": 2}}}
        self.paths["state_path"].write_text(json.dumps(held))
        e = daily_run(self.df, self.m, TYPES, self.last, **self.paths)
        self.assertTrue(e["kill"])
        self.assertEqual({r["ticker"]: r["qty"] for r in e["exit_list"]}, {"T2": 500})

    def test_state_is_written_as_strings_and_reloads(self):
        days = self.df.date.unique()[-3:]
        for d in days:
            daily_run(self.df, self.m, TYPES, d, strategy="S67", **self.paths)
        raw = json.loads(self.paths["state_path"].read_text())
        self.assertIsInstance(raw["cash"], str)
        self.assertIsInstance(raw["equity"], str)
        self.assertIsInstance(load_state(self.paths["state_path"])["cash"], Decimal)
        e = daily_run(self.df, self.m, TYPES, days[-1], strategy="S67", **self.paths)   # same-day rerun on string state
        self.assertEqual(e["alerts"], [])
        self.assertEqual(summarize(self.paths["journal_path"])["runs"], 4)

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

    def test_watchlist_reports_each_stock_and_flags_unknown(self):
        e = daily_run(self.df, self.m, TYPES, self.last, watch=["T1", "NOPE"], **self.paths)
        w = e["watchlist"]["T1"]
        last = self.df[self.df.ticker == "T1"].sort_values("date")
        self.assertAlmostEqual(w["close"], last.close.iloc[-1])
        self.assertAlmostEqual(w["change"], last.close.iloc[-1] / last.close.iloc[-2] - 1)
        self.assertEqual(w["last_bar"], str(self.last.date()))
        for k in ("lower_lock", "upper_lock", "adtv20", "eligible", "gap_20d"):
            self.assertIn(k, w)
        self.assertNotIn("NOPE", e["watchlist"])
        self.assertTrue(any("NOPE" in a for a in e["alerts"]))

    def test_strategy_book_runs_and_journals(self):
        days = self.df.date.unique()[-5:]
        for d in days:
            e = daily_run(self.df, self.m, TYPES, d, strategy="S67", **self.paths)
            self.assertIn("book", e)
            self.assertIsNone(e["book"]["stopped"])
        state = json.loads(self.paths["state_path"].read_text())
        self.assertEqual(len(state["returns"]), 4)               # first day has no previous equity... then 4
        rows = (self.tmp / "orders" / f"orders_{pd.Timestamp(days[-1]).date()}.csv").read_text().splitlines()
        self.assertEqual(rows[0], "ticker,side,qty,limit_price,reason")
        self.assertEqual(len(rows) - 1, len(e["orders"]))

    def test_rerun_same_day_keeps_daily_loss_baseline(self):
        prev = str(self.df.date.unique()[-2].date())
        self.paths["state_path"].write_text(json.dumps(
            {"asof": prev, "equity": 1e7, "day_start_equity": 1e7, "cash": 9.7e6, "peak_equity": 1e7, "positions": {}}))
        for _ in range(2):  # -3% vs yesterday's close, on both runs
            e = daily_run(self.df, self.m, TYPES, self.last, **self.paths)
            self.assertIn("max_daily_loss", e["gate_reasons"])

    def test_strategy_run_sells_a_hand_entered_position_without_a_lot(self):
        prev = str(self.df.date.unique()[-2].date())
        self.paths["state_path"].write_text(json.dumps(
            {"asof": prev, "equity": 1e7, "day_start_equity": 1e7, "cash": 1e7 - 30_000, "peak_equity": 1e7,
             "positions": {"T1": 1000}, "pending_sells": ["T1"]}))    # no "lots": made in no-strategy mode
        e = daily_run(self.df, self.m, TYPES, self.last, strategy="S67", **self.paths)
        self.assertEqual(e["alerts"], [])
        self.assertIn(("SELL", "T1"), [(f["side"], f["ticker"]) for f in e["fills"]])

    def test_rerun_with_the_bar_fills_after_a_stale_first_run(self):
        prev = str(self.df.date.unique()[-2].date())
        self.paths["state_path"].write_text(json.dumps(
            {"asof": prev, "bar_asof": prev, "equity": 1e7, "day_start_equity": 1e7, "cash": 1e7,
             "peak_equity": 1e7, "positions": {}, "pending_buys": {"T2": 100}}))
        daily_run(self.df[self.df.date < self.last], self.m, TYPES, self.last, strategy="S67", **self.paths)
        self.assertEqual(json.loads(self.paths["state_path"].read_text())["positions"], {})   # bar not loaded: no fill
        e = daily_run(self.df, self.m, TYPES, self.last, strategy="S67", **self.paths)
        self.assertEqual([(f["side"], f["ticker"]) for f in e["fills"]], [("BUY", "T2")])
        self.assertEqual(json.loads(self.paths["state_path"].read_text())["bar_asof"], str(self.last.date()))

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


class AuthorFlags(unittest.TestCase):
    def test_runaway_stock_gets_rsi_97_flag_and_indicator_values(self):
        from dse_quant.panels import build_panels
        from dse_quant.paper.harness import watch_row
        b = bars("UP", [10 * 1.01 ** i for i in range(80)])
        b["high"], b["low"] = b.close * 1.01, b.close * 0.99
        p = build_panels(lock_flags(b.assign(close_raw=b.close, gap_flag=False)))
        w = watch_row(p, pd.DataFrame(False, p.dates, p.tickers), "UP")
        self.assertGreaterEqual(w["rsi"], 97)
        self.assertTrue(any(f.startswith("#39") for f in w["flags"]))
        for k in ("mfi", "aroon_up", "adx", "bb_width"):
            self.assertIn(k, w)


class StatusPage(unittest.TestCase):
    def test_page_shows_latest_run_and_escapes_text(self):
        tmp = Path(tempfile.mkdtemp())
        rows = [{"asof": "2026-01-21", "gate_open": True, "gate_reasons": [], "regime": "RISK_OFF",
                 "equity": 1e7, "kill": False, "alerts": []},
                {"asof": "2026-01-22", "gate_open": False, "gate_reasons": ["stale_data"], "regime": "UNKNOWN",
                 "equity": None, "kill": False, "alerts": ["input error: <script>x</script>"],
                 "watchlist": {"AL-HAJTEX": {"last_bar": "2026-01-22", "close": 125.1, "change": -0.012,
                                             "lower_lock": False, "upper_lock": False, "adtv20": 1.8e7,
                                             "eligible": False, "gap_20d": False, "rsi": 31.2,
                                             "flags": ["#21 Aroon Up below 90 <x>"]}}}]
        (tmp / "j.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        status_page(tmp / "j.jsonl", tmp / "status.html")
        page = (tmp / "status.html").read_text(encoding="utf-8")
        self.assertIn("2026-01-22", page)
        self.assertIn("CLOSED", page)
        self.assertIn("stale_data", page)
        self.assertNotIn("<script>x", page)          # journal text is data, never markup
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("AL-HAJTEX", page)
        self.assertIn("125.1", page)
        self.assertIn("31.2", page)
        self.assertIn("#21 Aroon Up below 90 &lt;x&gt;", page)


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
