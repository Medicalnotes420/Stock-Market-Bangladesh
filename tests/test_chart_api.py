import gzip
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from chartapp.api import WEB, create_app, sessions_behind
from tests.test_chart_bars import GOOD, HEAD


def no_floats(resp):
    """Parse a response body; any JSON float anywhere fails the test."""
    def boom(text):
        raise AssertionError(f"JSON float {text} in {resp.url}")
    return json.loads(resp.text, parse_float=boom, parse_constant=boom)  # parse_constant: NaN and Infinity


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.dir.cleanup)
        cls.path = Path(cls.dir.name) / "p.csv.gz"
        with gzip.open(cls.path, "wt", newline="") as f:
            f.write("\n".join([HEAD, *GOOD]) + "\n")
        cls.client = cls.enterClassContext(TestClient(create_app(cls.path)))

    def test_meta(self):
        m = no_floats(self.client.get("/api/meta"))
        self.assertEqual((m["last_bar"], m["rows"], m["tickers"]), ("2026-11-08", 3, 2))
        self.assertEqual(m["sessions_behind"],
                         sessions_behind(date(2026, 11, 8), date.fromisoformat(m["expected_session"])))
        self.assertRegex(m["file_mtime"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")

    def test_tickers(self):
        ts = no_floats(self.client.get("/api/tickers"))
        self.assertEqual(ts, [
            {"ticker": "AAA", "type": "Equity", "first": "2026-11-05", "last": "2026-11-08", "bars": 2},
            {"ticker": "BBB", "type": "Index", "first": "2026-11-08", "last": "2026-11-08", "bars": 1}])
        self.assertEqual([t["ticker"] for t in no_floats(self.client.get("/api/tickers?q=b"))], ["BBB"])
        self.assertEqual(no_floats(self.client.get("/api/tickers?q=zz")), [])

    def test_bars_are_decimal_strings(self):
        b = no_floats(self.client.get("/api/bars/AAA"))
        self.assertEqual((b["ticker"], b["type"], b["adjusted"], len(b["bars"])), ("AAA", "Equity", True, 2))
        self.assertEqual(b["bars"][0], {
            "t": "2026-11-05", "o": "7.5734", "h": "8.3308", "l": "7.5734", "c": "8.1414", "v": 3578,
            "value": "202514.8", "c_raw": "8.6", "adj": "0.9467", "flags": []})
        self.assertEqual(b["bars"][1]["c"], "56.2")
        self.assertEqual(b["bars"][1]["flags"], ["gap", "upper_lock"])

    def test_from_and_to_filter(self):
        get = lambda q: [x["t"] for x in no_floats(self.client.get("/api/bars/AAA" + q))["bars"]]  # noqa: E731
        self.assertEqual(get("?from=2026-11-06"), ["2026-11-08"])
        self.assertEqual(get("?to=2026-11-05"), ["2026-11-05"])
        self.assertEqual(get("?from=2026-11-05&to=2026-11-08"), ["2026-11-05", "2026-11-08"])
        self.assertEqual(get("?from=2027-01-01"), [])

    def test_errors(self):
        r = self.client.get("/api/bars/NOPE")
        self.assertEqual((r.status_code, "unknown ticker" in r.text), (404, True))
        self.assertEqual(self.client.get("/api/bars/..%2Fsecret").status_code, 404)
        for bad in ("yesterday", "0", "1762560000", "2026-11-08T00:00:00", "20261108", "2026-13-40"):
            for key in ("from", "to"):
                r = self.client.get(f"/api/bars/AAA?{key}={bad}")
                self.assertEqual(r.status_code, 422, (key, bad))
                no_floats(r)
        self.assertEqual(self.client.get("/docs").status_code, 404)

    def test_odd_ticker_names_round_trip(self):
        lines = [GOOD[2].replace(",BBB,", f",{t},") for t in ("KAY&QUE", "AMCL(PRAN)", "AL-HAJTEX")]
        p = Path(self.dir.name) / "odd.csv.gz"
        with gzip.open(p, "wt", newline="") as f:
            f.write("\n".join([HEAD, *lines]) + "\n")
        with TestClient(create_app(p)) as c:
            for t in ("KAY&QUE", "AMCL(PRAN)", "AL-HAJTEX"):
                r = c.get("/api/bars/" + quote(t, safe=""))
                self.assertEqual((r.status_code, no_floats(r)["ticker"]), (200, t))

    def test_writes_are_refused(self):
        self.assertEqual(self.client.post("/api/bars/AAA").status_code, 405)
        self.assertEqual(self.client.post("/").status_code, 405)

    def test_page_and_scripts_are_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('src="app.js"', r.text)
        for f in ("app.js", "chart.js", "vendor/lightweight-charts.standalone.production.js"):
            r = self.client.get("/" + f)
            self.assertEqual((r.status_code, r.headers["content-type"].split(";")[0]), (200, "text/javascript"), f)
        # encoded, or httpx folds the ".." away before the request is sent
        for path in ("/vendor/%2e%2e/%2e%2e/api.py", "/..%5capi.py", "/%2e%2e/api.py"):
            self.assertEqual(self.client.get(path).status_code, 404, path)


class Frontend(unittest.TestCase):
    def test_only_chart_js_makes_numbers_from_prices(self):
        app_js = (WEB / "app.js").read_text(encoding="utf-8")
        for word in ("Number(", "parseFloat", "parseInt", "innerHTML"):
            self.assertNotIn(word, app_js)
        self.assertIn("Number(", (WEB / "chart.js").read_text(encoding="utf-8"))

    def test_page_loads_nothing_from_the_network(self):
        for f in ("index.html", "app.js", "chart.js"):
            self.assertNotIn("://", (WEB / f).read_text(encoding="utf-8"), f)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_close_only_bars_become_a_line(self):
        js = """
        import assert from 'node:assert/strict';
        import {split} from './chart.js';
        const bar = (t, o, h, l, c, v) => ({t, o, h, l, c, v});
        const d = split([
          bar('2026-01-20', '10.0', '11.0', '9.0', '10.5', 100),
          bar('2026-01-21', '10.5', '12.0', '10.0', '11.5', 200),
          bar('2026-01-25', '12.0', '12.0', '12.0', '12.0', 0),    // close only
          bar('2026-01-26', '12.5', '12.5000', '12.5', '12.50', 0), // close only, spelled three ways
          bar('2026-01-27', '13.0', '13.0', '13.0', '13.0', 50),   // one price all day, but it traded
        ]);
        assert.deepEqual(d.candles, [
          {time: '2026-01-20', open: 10, high: 11, low: 9, close: 10.5},
          {time: '2026-01-21', open: 10.5, high: 12, low: 10, close: 11.5},
          {time: '2026-01-25'}, {time: '2026-01-26'},
          {time: '2026-01-27', open: 13, high: 13, low: 13, close: 13}]);
        assert.deepEqual(d.line, [
          {time: '2026-01-20'},
          {time: '2026-01-21', value: 11.5},                       // joins the line to the last candle
          {time: '2026-01-25', value: 12}, {time: '2026-01-26', value: 12.5},
          {time: '2026-01-27'}]);
        assert.deepEqual(d.volume.map(x => x.value), [100, 200, undefined, undefined, 50]);
        """
        r = subprocess.run(["node", "--input-type=module", "-e", js], cwd=WEB, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class Startup(unittest.TestCase):
    def test_header_only_file_stops_startup(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.csv.gz"
            with gzip.open(p, "wt", newline="") as f:
                f.write(HEAD + "\n")
            with self.assertRaises(ValueError):
                with TestClient(create_app(p)):
                    pass

    def test_missing_file_stops_startup(self):
        with self.assertRaises(FileNotFoundError):
            with TestClient(create_app(Path(tempfile.gettempdir()) / "no-such-prices.csv.gz")):
                pass


class Sessions(unittest.TestCase):
    def test_counts_sessions_not_days(self):
        thu, sun = date(2026, 11, 5), date(2026, 11, 8)  # Friday and Saturday are the DSE weekend
        self.assertEqual(sessions_behind(thu, sun), 1)
        self.assertEqual(sessions_behind(sun, sun), 0)
        self.assertEqual(sessions_behind(sun, thu), 0)


if __name__ == "__main__":
    unittest.main()
