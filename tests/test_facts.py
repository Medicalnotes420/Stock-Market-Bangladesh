import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from dse_quant.watch import facts_for, quarter_label

spec = importlib.util.spec_from_file_location("run_health", Path(__file__).resolve().parents[1] / "scripts" / "run_health.py")
rh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rh)


class QuarterLabelTest(unittest.TestCase):
    def test_june_year_end(self):
        self.assertEqual(quarter_label("June", "202609"), "Q1 (Jul-Sep 2026)")  # Crown's July-September is Q1
        self.assertEqual(quarter_label("June", "202603"), "Q3 (Jan-Mar 2026)")  # and Jan-Mar is Q3
        self.assertEqual(quarter_label("June", "202606"), "Q4 (Apr-Jun 2026)")

    def test_december_year_end_and_bad_input(self):
        self.assertEqual(quarter_label("December", "202603"), "Q1 (Jan-Mar 2026)")
        self.assertIsNone(quarter_label(None, "202609"))


class FactsTest(unittest.TestCase):
    def test_turnover_dividend_and_quarter(self):
        idx = pd.bdate_range("2026-01-01", periods=80)
        df = pd.DataFrame({"close": np.full(80, 50.0), "volume": np.full(80, 10_000.0)}, index=idx)
        a = {"date": "2026-04-20", "close": 50.0, "trend": "down", "rsi": 31.24, "change": {"5d": -0.0312},
             "forecast": {5: {"low": 45.123, "mid": 50.0, "high": 55.0}},
             "alerts": [{"rule": "A", "fired": True}, {"rule": "B", "fired": False}],
             "news": [{"type": "Notice", "date": "01 Apr 2026", "summary": "x"},
                      {"type": "Financials", "date": "30 Apr 2026", "summary": "Q3 EPS Tk 0.91 vs 2.03"}],
             "dividend": {"pct": 22.5, "tk": 2.25, "record": pd.Timestamp("2026-05-01"), "sessions": 7, "drop": 0.04},
             "fund": {"year_end": "June", "eps": 4.52, "eps_when": "FY2025", "nav": 65.7, "nav_when": "FY2026",
                      "pe": 11.0, "pb": 0.8, "interim": {"ends": {"q1": "202609"}, "rows": [
                          {"metric": "Earnings Per Share (EPS) Basic", "q1": 0.34}]}}}
        f = facts_for(df, a)
        self.assertEqual(f["median_turnover_60d_mn"], 0.5)
        self.assertEqual((f["trend"], f["rsi"], f["moves_pct"], f["alerts_fired"]), ("down", 31.2, {"5d": -3.1}, ["A"]))
        self.assertEqual(f["ranges_80pct"], {"5_sessions": {"low": 45.12, "mid": 50.0, "high": 55.0}})
        self.assertEqual(f["dividend_ahead"]["record_date"], "2026-05-01")
        self.assertEqual(f["dividend_ahead"]["range_lowered_pct"], 4.0)
        self.assertEqual(f["latest_quarter"]["fiscal_quarter"], "Q1 (Jul-Sep 2026)")
        self.assertEqual(f["eps_period"], "FY2025")
        self.assertEqual(f["recent_results_filings"],
                         [{"date": "30 Apr 2026", "summary": "Q3 EPS Tk 0.91 vs 2.03", "detail": ""}])


class DeclaredEpsTest(unittest.TestCase):
    BODY = ("The Board of Directors has recommended 22.50% Cash Dividend for the year ended June 30, 2026. The Company "
            "has also reported EPS of Tk. 5.08, NAV per share of Tk. 65.73 for the year ended June 30, 2026 as against "
            "EPS of Tk. 4.52, NAV per share of Tk. 62.66 for the year ended June 30, 2025.")

    def test_declared_eps_beats_the_lagging_table(self):
        from dse_quant.watch import fundamentals
        co = {"faceValue": 10, "paidUpCapital": 1e8, "multiYearFinancials": [{"year": 2025, "epsBasic": 4.52, "nav": 62.66}],
              "dividendHistory": [{"year": 2025, "cash": 20, "stock": 0}], "interimFinancials": "$undefined",
              "sharePattern": "$undefined", "loanStatus": {"shortTerm": 1.0, "longTerm": 0.0}}
        f = fundamentals(co, 56.2, [{"type": "Dividend", "body": self.BODY}])
        self.assertEqual((f["eps"], f["eps_when"]), (5.08, "FY2026 (dividend declaration)"))
        self.assertAlmostEqual(f["pe"], 56.2 / 5.08)

    def test_table_eps_kept_without_a_newer_declaration(self):
        from dse_quant.watch import fundamentals
        co = {"faceValue": 10, "paidUpCapital": 1e8, "multiYearFinancials": [{"year": 2025, "epsBasic": 4.52, "nav": 62.66}],
              "dividendHistory": [], "interimFinancials": "$undefined", "sharePattern": "$undefined", "loanStatus": {}}
        self.assertEqual(fundamentals(co, 56.2, [])["eps"], 4.52)


class RunHealthTest(unittest.TestCase):
    TASK = "Last Run Time:  09-Nov-26 9:56:40 AM\nLast Result:  -2147020576\nStatus:  Ready\nPower Management: No Start On Batteries"
    BLOCK = "==== 09-Nov-26 19:38:00 (session 2026-11-08)\nfetching 2026-11-05 to 2026-11-08\n2026-11-08 regime RISK_OFF gate CLOSED"

    def test_nonzero_result_is_a_problem_first(self):
        lines, ok = rh.summarise(rh.parse_schtasks(self.TASK), rh.last_block("old\n" + self.BLOCK))
        self.assertFalse(ok)
        self.assertIn("-2147020576 (0x800710E0)", lines[0])
        self.assertTrue(any("regime RISK_OFF" in ln for ln in lines))

    def test_parse_events(self):
        txt = ("Event[0]:\n  Log Name: x\n  Date: 2026-11-09T09:56:40\n  Event ID: 201\n  Description:\n"
               "Task Scheduler failed action \"x\"\n\nEvent[1]:\n  Date: 2026-11-09T08:00:00\n  Event ID: 101\n"
               "  Description:\nTask failed to start\n")
        out = rh.parse_events(txt)
        self.assertEqual(len(out), 2)
        self.assertIn("id 201", out[0])
        self.assertIn("Task failed to start", out[1])
        self.assertEqual(rh.parse_events(""), [])

    def test_clean_run_and_failed_block(self):
        ok_task = {"Last Result": "0"}
        self.assertTrue(rh.summarise(ok_task, rh.last_block(self.BLOCK))[1])
        bad = "==== x\nDATA PIPELINE FAILED, see above"
        self.assertFalse(rh.summarise(ok_task, rh.last_block(bad))[1])
        self.assertFalse(rh.summarise(ok_task, "")[1])


if __name__ == "__main__":
    unittest.main()
