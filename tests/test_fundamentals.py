import tempfile
import unittest
from pathlib import Path

from dse_quant.fundamentals import latest_snapshot, save_snapshot, screen, sector_view, table, trim
from dse_quant.watch import AUDIT_RE, ownership_flags


def rec(code, sector, price, eps, nav, cash=10, loans=50.0):
    return {"code": code, "name": code, "sector": sector, "price": price, "faceValue": 10, "paidUpCapital": 1e8,
            "loanStatus": {"shortTerm": loans, "longTerm": 0.0},
            "multiYearFinancials": [{"year": 2025, "epsBasic": eps, "nav": nav}],
            "dividendHistory": [{"year": 2025, "cash": cash, "stock": 0}], "interimFinancials": "$undefined",
            "sharePattern": "$undefined", "news": []}


RECS = {"A": rec("A", "Cement", 50, 5, 50),      # P/E 10, P/NAV 1.0, yield 2%
        "B": rec("B", "Cement", 30, 5, 60),      # P/E 6,  P/NAV 0.5, yield 3.3%
        "C": rec("C", "Cement", 40, -1, 20, 0),  # loss: no P/E
        "D": rec("D", "Bank", 10, 2, 20),
        "E": rec("E", "Cement", "$undefined", 1, 1)}  # no price: left out


class Fundamentals(unittest.TestCase):
    def test_eps_stale(self):
        from dse_quant.fundamentals import eps_stale
        self.assertTrue(eps_stale("FY2025", "June", "2026-11-06"))  # ended 30 Jun 2025, 494 days
        self.assertFalse(eps_stale("FY2025", "December", "2026-11-06"))  # ended 31 Dec 2025, 311 days
        self.assertFalse(eps_stale("year to 06/2026 (interim report)", "June", "2026-11-06"))
        self.assertFalse(eps_stale("FY2025", None, "2026-11-06"))

    def test_table_sector_and_screen(self):
        tab = table(RECS)
        self.assertEqual(sorted(tab.index), ["A", "B", "C", "D"])
        v = sector_view(tab, "A", "2026-11-05")
        self.assertEqual(v["members"], 3)
        self.assertEqual(v["metrics"]["pe"], {"share": 10.0, "median": 8.0, "rank": 2, "n": 2})  # C has no P/E
        self.assertEqual((v["metrics"]["pb"]["rank"], v["metrics"]["pb"]["n"]), (2, 3))  # B 0.5 < A 1.0 < C 2.0
        self.assertEqual(sector_view(tab, "B", "d")["metrics"]["div_yield"]["rank"], 1)
        self.assertIn("only 1", sector_view(tab, "D", "d"))
        self.assertIn("not in", sector_view(tab, "Z", "d"))
        self.assertEqual(list(screen(tab, max_pb=1.0).index), ["B", "A"])  # cheapest P/NAV first
        self.assertNotIn("D", screen(tab).index)  # banks left out by default
        self.assertIn("D", screen(tab, financials=True).index)
        self.assertEqual(list(screen(tab, max_pe=100).index), ["B", "A"])  # a loss fails a P/E limit
        self.assertEqual(list(screen(tab, sector="cement", min_yield=0.03).index), ["B"])
        self.assertEqual(list(screen(tab, sector="cement", min_yield=3).index), ["B"])  # 3 means 3%, not 300%

    def test_snapshot_roundtrip_and_trim(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(latest_snapshot(Path(d)))
            save_snapshot("2026-10-29", {"X": 1}, Path(d))
            save_snapshot("2026-11-05", {"Y": 2}, Path(d))
            self.assertEqual(latest_snapshot(Path(d)), ("2026-11-05", {"Y": 2}))
        t = trim({"code": "X", "companySecretary": "x", "price": 1},
                 [{"type": "Dividend", "body": "b"}, {"type": "Notice", "body": "n"}])
        self.assertNotIn("companySecretary", t)
        self.assertEqual(t["news"], [{"type": "Dividend", "body": "b"}])

    def test_ownership_flags(self):
        h = [{"date": "Jun 30, 2025", "pattern": {"sponsor": 30.65, "institution": 12.75, "foreign": 0}},
             {"date": "Oct 31, 2026", "pattern": {"sponsor": 30.65, "institution": 1.07, "foreign": 0.05}}]
        self.assertEqual(ownership_flags(h), ["Institutions down 11.7 pts (12.75% to 1.07%, Jun 30, 2025 to Oct 31, 2026)"])
        self.assertEqual(ownership_flags(h[:1]), [])

    def test_auditor_links_only_from_dse(self):
        body = ("see https://www.dsebd.org/Auditors_opinion/2025/AL-HAJTEX25.pdf and "
                "https://evil.example/Auditors_opinion/2025/x.pdf")
        self.assertEqual(AUDIT_RE.findall(body), ["https://www.dsebd.org/Auditors_opinion/2025/AL-HAJTEX25.pdf"])
