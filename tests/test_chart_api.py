import gzip
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from decimal import Decimal
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
        cls.path.with_name("actions.csv").write_text("ticker,date,ratio\n")
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
        self.node(js)

    def node(self, js):
        r = subprocess.run(["node", "--input-type=module", "-e", js], cwd=WEB, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_markers_and_selected_signal_overlay(self):
        self.node("""
        import assert from 'node:assert/strict';
        import {markers, overlay} from './chart.js';
        const bar = (t, h, l, flags = []) => ({t, o: l, h, l, c: h, v: 10, flags});
        const bars = [bar('2026-01-01', '11.0', '10.0'), bar('2026-01-02', '12.0', '11.0', ['gap']),
                      bar('2026-01-05', '13.0', '12.0', ['upper_lock']), bar('2026-01-06', '12.5', '11.5', ['lower_lock']),
                      bar('2026-01-07', '14.0', '13.0')];
        const sig = (signal_date, direction, extra = {}) =>
          ({signal_date, direction, points: [], segments: [], levels: {}, ...extra});
        const m = markers(bars, [sig('2026-01-07', 'bullish'), sig('2026-01-01', 'bearish'),
                                 sig('2026-01-05', 'neutral'), sig('2030-01-01', 'bullish')]);
        assert.deepEqual(m.map(x => [x.time, x.shape, x.position, x.price, x.text ?? '']), [
          ['2026-01-01', 'arrowDown', 'atPriceTop', 11, ''],
          ['2026-01-02', 'square', 'atPriceTop', 12, 'gap'],
          ['2026-01-05', 'circle', 'atPriceTop', 13, ''],       // upper lock
          ['2026-01-05', 'circle', 'atPriceTop', 13, ''],       // neutral signal on the same bar
          ['2026-01-06', 'circle', 'atPriceBottom', 11.5, ''],  // lower lock
          ['2026-01-07', 'arrowUp', 'atPriceBottom', 13, '']]); // the 2030 signal has no bar and is dropped
        assert.deepEqual(markers(bars, []).map(x => x.time), ['2026-01-02', '2026-01-05', '2026-01-06']);

        const p = (t, price, role) => ({t, p: price, role});
        const o = overlay(sig('2026-01-06', 'bullish', {
          points: [p('2026-01-02', '12.0', 'swing_high')],
          segments: [{start: p('2026-01-05', '13.0', 'b'), end: p('2026-01-01', '11.0', 'a'), role: 'support'},
                     {start: p('2026-01-05', '13.0', 'x'), end: p('2026-01-05', '12.0', 'y'), role: 'degenerate'}],
          levels: {breakout: '12.06'}}), bars);
        assert.equal(o.index, 3);
        assert.deepEqual(o.points.map(x => [x.time, x.price, x.text]), [['2026-01-02', 12, 'swing_high']]);
        assert.deepEqual(o.lines, [
          {data: [{time: '2026-01-01', value: 11}, {time: '2026-01-05', value: 13}], dashed: false},  // put in order
          {data: [{time: '2026-01-02', value: 12.06}, {time: '2026-01-06', value: 12.06}], dashed: true}]);
        // nothing is drawn after the signal bar
        assert.ok(o.lines.every(l => l.data.every(d => d.time <= '2026-01-06')));
        // no points: the level starts 20 bars back, or at the first bar; a signal on the first bar draws none
        assert.deepEqual(overlay(sig('2026-01-07', 'bullish', {levels: {a: '1'}}), bars).lines[0].data.map(d => d.time),
                         ['2026-01-01', '2026-01-07']);
        assert.deepEqual(overlay(sig('2026-01-01', 'bullish', {levels: {a: '1'}}), bars).lines, []);
        assert.deepEqual(overlay(sig('2030-01-01', 'bullish', {levels: {a: '1'}}), bars).lines, []);
        """)


def lines(ticker, closes, gap_at=None):
    """Price-file rows: one bar a day from 2026-01-01, high and low a tenth either side of the close."""
    out = []
    for i, c in enumerate(map(Decimal, closes)):
        hi, lo = c + Decimal("0.1"), c - Decimal("0.1")
        out.append(f"{date(2026, 1, 1 + i)},{ticker},{c},{hi},{lo},{c},100.0,1000.0,dse,{i == gap_at},{c},1.0,,,"
                   "False,False,Equity")
    return out


class Detections(unittest.TestCase):
    # swing high 15.1 on 2026-01-04, confirmed two bars later; 15.3 on 2026-01-08 is the first close above 15.251
    CLOSES = ["10", "12", "13", "15", "13", "12", "14", "15.3", "16"]

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.dir.cleanup)
        d = Path(cls.dir.name)
        with gzip.open(d / "p.csv.gz", "wt", newline="") as f:
            rows = lines("SIG", cls.CLOSES) + lines("EXD", cls.CLOSES) + lines("GAP", cls.CLOSES, gap_at=5)
            f.write("\n".join([HEAD, *rows]) + "\n")
        (d / "actions.csv").write_text("ticker,date,ratio\nEXD,2026-01-06,2.0\n")
        (d / "patterns.toml").write_text("[swing_breakout]\nleft = 2\nright = 2\nmin_break_pct = 1.0\n")
        cls.client = cls.enterClassContext(TestClient(create_app(d / "p.csv.gz", d / "patterns.toml")))

    def get(self, path):
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200, r.text)
        return no_floats(r)

    def test_signal_shape(self):
        (s,) = self.get("/api/detections/SIG")
        self.assertRegex(s.pop("config_hash"), r"^[0-9a-f]{8}$")
        level = s["levels"].pop("breakout")
        self.assertIs(type(level), str)
        self.assertEqual(Decimal(level), Decimal("15.251"))
        self.assertEqual(s, {
            "pattern": "swing_breakout", "version": 1, "ticker": "SIG", "signal_date": "2026-01-08",
            "direction": "bullish", "points": [{"t": "2026-01-04", "p": "15.1", "role": "swing_high"}],
            "segments": [], "levels": {}, "score": None, "note": ""})

    def test_pattern_filter(self):
        self.assertEqual(self.get("/api/detections/SIG?pattern=swing_breakout"), self.get("/api/detections/SIG"))
        r = self.client.get("/api/detections/SIG?pattern=nope")
        self.assertEqual((r.status_code, "unknown or disabled pattern" in r.text), (404, True))

    def test_dates_only_filter_the_answer(self):
        self.assertEqual(self.get("/api/detections/SIG?from=2026-01-09"), [])
        self.assertEqual(self.get("/api/detections/SIG?to=2026-01-07"), [])
        # asking from the signal date onward still finds it: the swing high before `from` was still used
        self.assertEqual(len(self.get("/api/detections/SIG?from=2026-01-08&to=2026-01-08")), 1)

    def test_blocked_windows_give_no_signal(self):
        self.assertEqual(self.get("/api/detections/EXD"), [])  # ex-date two bars before the breakout
        self.assertEqual(self.get("/api/detections/GAP"), [])  # flagged gap inside the window
        self.assertEqual(len(self.get("/api/bars/EXD")["bars"]), len(self.CLOSES))  # the bars are still served

    def test_errors(self):
        r = self.client.get("/api/detections/NOPE")
        self.assertEqual((r.status_code, "unknown ticker" in r.text), (404, True))
        self.assertEqual(self.client.get("/api/detections/SIG?from=0").status_code, 422)
        self.assertEqual(self.client.post("/api/detections/SIG").status_code, 405)

    def test_a_plugin_that_breaks_the_contract_is_named(self):
        from chartapp.patterns import Detection, swing_breakout
        self.addCleanup(setattr, swing_breakout, "detect", swing_breakout.detect)
        swing_breakout.detect = lambda bars, cfg: Detection("up")
        d = Path(self.dir.name)
        with TestClient(create_app(d / "p.csv.gz", d / "patterns.toml"), raise_server_exceptions=False) as c:
            r = c.get("/api/detections/SIG")
            self.assertEqual(r.status_code, 500)
            self.assertIn("swing_breakout", no_floats(r)["detail"])

    def test_startup_needs_actions_and_a_valid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "p.csv.gz"
            shutil.copy(Path(self.dir.name) / "p.csv.gz", p)
            with self.assertRaises(FileNotFoundError):  # no actions.csv beside the prices
                with TestClient(create_app(p)):
                    pass
            p.with_name("actions.csv").write_text("ticker,date,ratio\n")
            bad = Path(tmp) / "patterns.toml"
            for text in ("[no_such_plugin]\n", "[swing_breakout]\nleft = 2\nright = 3\n"):
                bad.write_text(text)
                with self.assertRaises(ValueError, msg=text):
                    with TestClient(create_app(p, bad)):
                        pass


class Startup(unittest.TestCase):
    def test_header_only_file_stops_startup(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.csv.gz"
            with gzip.open(p, "wt", newline="") as f:
                f.write(HEAD + "\n")
            p.with_name("actions.csv").write_text("ticker,date,ratio\n")
            with self.assertRaisesRegex(ValueError, "no rows"):
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
