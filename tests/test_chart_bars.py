import gzip
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from chartapp import bars as B

HEAD = ("date,ticker,open,high,low,close,volume,value,source,gap_flag,close_raw,adj_factor,prev_close,limit,"
        "lower_lock,upper_lock,type")
GOOD = [  # first row has empty prev_close/limit, as the first row of every ticker does in the real file
    "2026-11-05,AAA,7.573440000000005,8.330784000000007,7.573440000000005,8.141448000000006,3578.0,"
    "202514.8,a2,False,8.6,0.9466800000000006,,,False,False,Equity",
    "2026-11-08,AAA,56.2,57.8,52.1,56.2,7245.0,16153703895.000002,dse,True,56.2,1.0,56.6,0.1,False,True,Equity",
    "2026-11-08,BBB,10.0,10.0,10.0,10.0,0.0,0.0,dse,False,10.0,1.0,,,False,False,Index",
]


class Parse(unittest.TestCase):
    def test_tick_price_is_exact(self):
        self.assertEqual(str(B.dec("56.2")), "56.2")

    def test_float_noise_is_cut_to_4dp(self):
        self.assertEqual(str(B.dec("7.573440000000005")), "7.5734")
        self.assertEqual(str(B.dec("16153703895.000002")), "16153703895.0000")

    def test_rejects_anything_but_plain_digits(self):
        for bad in ("", "nan", "inf", "-inf", "1e+16", "1E-7", "-1.0", "1_000", " 5.5 ", "5.", ".5", "5.5\n"):
            with self.assertRaises(ValueError, msg=bad):
                B.dec(bad)

    def test_volume(self):
        self.assertEqual(B.whole("3163.0"), 3163)
        self.assertIs(type(B.whole("3163.0")), int)
        for bad in ("1.5", "nan", "1e3"):
            with self.assertRaises(ValueError):
                B.whole(bad)


class Load(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, lines, name="p.csv.gz"):
        p = Path(self.dir.name) / name
        with gzip.open(p, "wt", newline="") as f:
            f.write("\n".join([HEAD, *lines]) + "\n")
        return p

    def test_every_loaded_cell_is_a_string(self):
        t = B.table(self.write(GOOD))
        self.assertEqual(sorted(t), ["AAA", "BBB"])
        for g in t.values():
            self.assertTrue(g.map(lambda v: type(v) is str).all().all())

    def test_rows_are_typed_and_ordered(self):
        rs = B.rows("AAA", self.write(GOOD))
        self.assertEqual([r.date for r in rs], [date(2026, 11, 5), date(2026, 11, 8)])
        self.assertEqual(rs[0].open, Decimal("7.5734"))
        self.assertEqual(rs[0].adj_factor, Decimal("0.9467"))
        self.assertEqual(str(rs[1].close), "56.2")
        self.assertEqual(rs[1].volume, 7245)
        self.assertEqual((rs[1].gap_flag, rs[1].lower_lock, rs[1].upper_lock), (True, False, True))
        allowed = {date, Decimal, int, bool}
        for r in rs:
            self.assertTrue({type(getattr(r, f)) for f in B.Row.__dataclass_fields__} <= allowed)

    def test_plugin_view_has_no_hindsight_fields(self):
        b = B.bars(B.rows("AAA", self.write(GOOD)))[0]
        self.assertIs(type(b), B.Bar)
        self.assertEqual(set(B.Bar.__dataclass_fields__), {"date", "open", "high", "low", "close", "volume"})
        for leaked in ("adj_factor", "close_raw", "gap_flag", "lower_lock", "upper_lock", "value"):
            self.assertFalse(hasattr(b, leaked))

    def test_unknown_ticker(self):
        with self.assertRaises(KeyError):
            B.rows("NOPE", self.write(GOOD))

    def test_empty_cell_fails_loudly(self):
        bad = GOOD[1].replace(",56.2,57.8,", ",,57.8,", 1)  # empty open
        p = self.write([bad])
        self.assertEqual(B.table(p)["AAA"].open.iloc[0], "")  # still a str, not NaN
        with self.assertRaises(ValueError):
            B.rows("AAA", p)

    def test_default_path_is_read_once(self):
        p = self.write(GOOD)
        self.assertIs(B.table(p), B.table(path=p))
        self.assertIs(B.rows("AAA", p), B.rows("AAA", path=p))

    def test_unsorted_or_duplicate_dates_fail(self):
        for name, lines in (("rev.csv.gz", [GOOD[1], GOOD[0]]), ("dup.csv.gz", [GOOD[1], GOOD[1]])):
            with self.assertRaises(ValueError):
                B.rows("AAA", self.write(lines, name))

    def test_truncated_gzip_fails(self):
        p = self.write(GOOD * 200)
        data = p.read_bytes()
        cut = Path(self.dir.name) / "cut.csv.gz"
        cut.write_bytes(data[: len(data) // 2])
        with self.assertRaises(EOFError):
            B.table(cut)


@unittest.skipUnless(B.PRICES.exists(), "data/clean is local only")
class RealFile(unittest.TestCase):
    def test_one_ticker(self):
        rs = B.rows("CROWNCEMNT")
        self.assertGreater(len(rs), 3000)
        self.assertTrue(all(r.high >= r.close >= r.low and r.high >= r.open >= r.low for r in rs))
        self.assertTrue(all(r.close.as_tuple().exponent >= -4 for r in rs))

    def test_no_empty_cells_in_loaded_columns(self):
        for g in B.table().values():
            self.assertFalse((g == "").any().any())


if __name__ == "__main__":
    unittest.main()
