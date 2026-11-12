# DSE EOD chart app — design

Status: design only, nothing built. Written 2026-11-11.

A local, read-only web app: pick a DSE ticker, see its end-of-day candles, and see where pattern
plugins fired. FastAPI backend, Lightweight Charts frontend, pure-Python pattern plugins.
No LLM or network calls at run time. No orders, no money path.

## 1. Constraints this design is built around

| Constraint | Where it is enforced |
|---|---|
| Prices are `Decimal` everywhere in Python; `float` only in the chart layer | `bars.py` parses CSV text straight to `Decimal`; the no-float-in-JSON test is the real guard, an AST scan of `chartapp/` is a cheap second one; one JS function converts for the chart |
| JSON prices are decimal strings | Pydantic response models; a test parses every response with `json.loads(parse_float=<raise>)` |
| Plugins see only bars up to and including the signal bar | The runner passes a truncated slice; the future is never in the plugin's arguments |
| Labels use only bars strictly after the signal bar | `labels.py` takes `bars[i+1:]` only; nothing in the serving path may import it |
| `dse_quant/` costs and float usage untouched | New top-level package `chartapp/`; it imports only `dse_quant.sessions` (calendar, no prices) |
| No LLM at run time | An AST test bans `anthropic` and network modules in `chartapp/` |

`async_risk_guard.py` and `dse_paper_harness.py` are not touched, so the CLAUDE.md verification gate
does not apply to this work.

## 2. Canonical data source

**`data/clean/prices.csv.gz` is canonical.** `dse_quant/data/` is not a data directory: it is the Python
package (`load.py`, `adjust.py`, `checks.py`) that `scripts/build_clean.py` uses to produce `data/clean/`.
The app reads the output and never imports that package.

Facts about the file as of 2026-11-09 (checked, not assumed):

- 1,199,844 rows, 533 tickers, 2012-10-01 to 2026-11-09, sorted by ticker then date.
- Columns: `date, ticker, open, high, low, close, volume, value, source, gap_flag, close_raw, adj_factor,
  prev_close, limit, lower_lock, upper_lock, type`.
- `open/high/low/close` are **back-adjusted** for inferred bonus/split actions. `close_raw` is the traded
  close. `adj_factor` links them.
- `type` is one of Equity, MutualFund, Index, Bond, Sukuk, TreasuryBill, Unknown.
- No-trade days have no row. OHLC-inconsistent rows were removed to `quarantine.csv`.
- `data/` is gitignored, so the file exists only on this machine.

Not used: `data/watch/*.csv` (short per-ticker fetches for the daily watcher), `data/raw/` (inputs to the
build), `data/clean/market.csv` (DSEX is already in the price file as ticker `00DSEX`).

Five properties of the file that the design has to respect:

1. **It was written from floats.** Adjusted prices look like `7.573440000000005`. The app cannot make them
   more exact than their source; it only avoids adding float error. `Decimal(text)` is used, then any value
   with more than 4 decimal places is quantized to 4 (`ROUND_HALF_EVEN`). Tick-priced values (`56.2`) pass
   through unchanged. Rounding is monotonic, so `high >= close >= low` survives.
2. **It is today's reconstruction, not a point-in-time snapshot.** Back-adjustment multiplies all history
   before an action by a constant, and an action is only accepted 10 sessions after its ex-date
   (`infer_actions(hold=10)`). A plugin working on these prices therefore sees a scale that depends on
   later events. Section 5.4 removes this by requiring scale-invariant plugins.
3. **Actions stop before the data does.** The last accepted action in `actions.csv` is 2025-10-27 (1,556
   in all). The Mendeley A2 set that actions are inferred from ends 2026-01-22, and an ex-date in its last
   10 rows can never be accepted. A later bonus shows up as a raw price gap with `gap_flag = True`, not as
   an adjustment. 1,683 rows carry the flag, 35 of them after 2026-01-22.
4. **The flag columns are computed on adjusted prices.** `lower_lock`, `upper_lock` and `limit` come from
   `lock_flags`, which runs after adjustment: the limit tier is picked from the adjusted previous close
   and compared with an absolute tick. A later action can therefore change them, and they do not rescale
   with price. `gap_flag` depends on which actions were accepted, which needs 10 later sessions. None of
   these columns is point-in-time safe, so none is given to plugins (section 5.1).
5. **`00DSEX` after 2026-01-22 has open = high = low = close and zero volume** (only the index close is
   copied from DSE). The chart draws these bars as a close line (section 8).

One known bad value: MONNOCERA 2018-09-20 has `low = 0.0` with a close near 233.8. It passes the build's
OHLC check. Geometry and plugins divide by prices, so they must treat a non-positive price as "no signal",
not crash.

Staleness: `/api/meta` reports the last bar date and compares it with
`dse_quant.sessions.expected_session(today)`. The UI shows a "data is N sessions old" badge.

## 3. Folder structure

```
chartapp/
  __init__.py
  bars.py          Bar dataclass; reads data/clean/prices.csv.gz as text -> Decimal
  geometry.py      pivots, zigzag, trendlines (Decimal, bar-index space)
  runner.py        plugin discovery, config, walk-forward driver, contract checks, cache
  api.py           FastAPI app, response models, static file mount
  labels.py        forward-outcome labels. Tests and offline evaluation only.
  patterns/
    __init__.py
    swing_breakout.py      first plugin
    trendline_break.py     second plugin (after v1)
  web/
    index.html
    app.js                 ticker search, fetch, detection table
    chart.js               the only file that turns price strings into numbers
    vendor/lightweight-charts.standalone.production.js   pinned, served locally
config/
  patterns.toml    plugin on/off and parameters
tests/
  test_chart_bars.py  test_chart_geometry.py  test_chart_runner.py
  test_chart_patterns.py  test_chart_labels.py  test_chart_api.py
  test_chart_static.py            AST rules: no float, no network or LLM imports
  fixtures/chart/labeled.toml     hand-labeled historical examples (dates only, no prices)
docs/design/eod-chart-app.md
```

Tests stay flat in `tests/` like the existing ones. `config/patterns.toml` is a new file; the existing
`config/workflow.toml` is not edited.

New dependencies: `fastapi`, `uvicorn` (neither is installed today), and `httpx` for FastAPI's test client.
Pin them in `requirements.txt` when building. No Node, no bundler: the frontend is three static files.

Run: `python -m uvicorn chartapp.api:app --host 127.0.0.1 --port 8000`. Bound to loopback, GET only,
no auth.

## 4. Backend

### 4.1 Bars

Two types, so that what a plugin can see is a matter of fields, not discipline:

```python
@dataclass(frozen=True, slots=True)
class Bar:               # what plugins and geometry.py get
    date: datetime.date
    open: Decimal        # back-adjusted
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int          # shares, adjusted inversely to price

@dataclass(frozen=True, slots=True)
class Row(Bar):          # API and labels.py only
    value: Decimal       # BDT traded value, unadjusted
    close_raw: Decimal   # traded close
    adj_factor: Decimal
    gap_flag: bool
    lower_lock: bool     # as in the file: computed on adjusted prices, display only
    upper_lock: bool
```

`adj_factor` and `close_raw` are kept from plugins because `adj_factor` is the product of all actions
*after* the bar: a value other than 1 on the signal bar says a bonus or split is coming. 351 tickers have
such bars. The runner builds plain `Bar`s from `Row`s before calling a plugin.

Loading: `pandas.read_csv(..., dtype=str, na_filter=False, usecols=[...])` once at startup, grouped by
ticker. pandas is used only as a string-table reader. `na_filter=False` matters: without it empty cells
become NaN, which is a float. Conversion to `tuple[Row, ...]` is lazy per ticker behind
`functools.lru_cache(maxsize=64)`. A cell must be plain digits with an optional fraction; signs,
exponents, `nan` and spaces are rejected, so `str()` of a parsed value is always a plain decimal. Volume is stored as `"3163.0"`, so it is parsed as `int(Decimal(text))` after
asserting the value is whole. `prev_close` and `limit` are not loaded.

- `shortcut: whole file held in memory as strings and loaded at startup (about 9 s measured, accepted
  2026-11-11); if memory hurts or startup grows well past that, split into per-ticker files in a build step.`
- The file is read once. After `build_clean.py` runs, restart the server. `build_clean.py` does not write
  atomically, so a truncated gzip at startup must fail loudly, not serve a partial table.

### 4.2 JSON API

All routes are `GET`. Dates are `YYYY-MM-DD`. Every price, level, score and BDT value is a JSON string
holding a decimal. Share counts and bar counts are JSON integers. No JSON floats appear anywhere.

| Route | Returns |
|---|---|
| `/api/meta` | data status |
| `/api/tickers?q=` | ticker list, optional prefix filter |
| `/api/bars/{ticker}?from=&to=` | bars for one ticker |
| `/api/patterns` | installed plugins and their effective config (after v1) |
| `/api/detections/{ticker}?pattern=&from=&to=` | signals for one ticker |
| `/` | the static frontend |

`from` and `to` only filter the output. The runner always walks the ticker's full history, so a signal
never depends on the query window.

`/api/meta`
```json
{"last_bar": "2026-11-09", "expected_session": "2026-11-11", "sessions_behind": 2,
 "rows": 1199844, "tickers": 533, "file_mtime": "2026-11-09T19:39:00"}
```

`/api/tickers`
```json
[{"ticker": "CROWNCEMNT", "type": "Equity", "first": "2012-10-01", "last": "2026-11-08", "bars": 3175}]
```

`/api/bars/CROWNCEMNT?from=2026-11-01`
```json
{"ticker": "CROWNCEMNT", "type": "Equity", "adjusted": true,
 "bars": [{"t": "2026-11-08", "o": "56.2", "h": "57.8", "l": "52.1", "c": "56.2",
           "v": 7245, "value": "407169.0", "c_raw": "56.2", "adj": "1.0",
           "flags": []}]}
```
`flags` holds any of `"gap"`, `"lower_lock"`, `"upper_lock"`.

`/api/patterns`
```json
[{"name": "swing_breakout", "version": 1, "lookback": 120, "enabled": true,
  "config": {"left": 5, "right": 5, "min_break_pct": "0.5"}, "config_hash": "9c1f03ab"}]
```

`/api/detections/CROWNCEMNT`
```json
[{"pattern": "swing_breakout", "version": 1, "config_hash": "9c1f03ab",
  "ticker": "CROWNCEMNT", "signal_date": "2026-10-14", "direction": "bullish",
  "points": [{"t": "2026-09-22", "p": "55.9", "role": "swing_high"}],
  "segments": [],
  "levels": {"breakout": "55.9"},
  "score": null, "note": ""}]
```
(Values above are illustrative, not real detections.)

A segment is `{"start": {"t", "p", "role"}, "end": {"t", "p", "role"}, "role": "support"}`. Signals come back
oldest first. With no `pattern`, every enabled plugin is run; an unknown or disabled `pattern` is 404.
Signals are computed on first request (about 2.5 s for a full history) and cached per ticker and plugin for
the life of the process. Startup needs `actions.csv` beside the price file and a valid `config/patterns.toml`.

Errors: unknown ticker or pattern is 404; bad dates are FastAPI's 422. The ticker is checked against the
loaded set and is never used to build a file path.

Serialization: response models are Pydantic v2 models with `Decimal` fields, which serialize to strings in
JSON mode. The test that parses responses with a `parse_float` hook that raises is the guard, so the rule
does not depend on remembering Pydantic's default. `file_mtime` is formatted from `st_mtime_ns`, an
integer.

## 5. Pattern plugins

### 5.1 Interface

A plugin is one module in `chartapp/patterns/`. No base class, no registry call: the runner imports every
module in the package with `pkgutil.iter_modules`.

```python
# chartapp/patterns/swing_breakout.py
NAME = "swing_breakout"
VERSION = 1                 # bump when detection logic changes
LOOKBACK = 120              # the most bars the plugin needs; the runner never passes more
DEFAULTS = {"left": 5, "right": 5, "min_break_pct": Decimal("0.5")}

def detect(bars: Sequence[Bar], cfg: Mapping[str, object]) -> Detection | None:
    """Does a signal fire on bars[-1]? bars[-1] is the signal bar. Nothing after it exists here."""
```

**Inputs.** `bars` is a tuple of at most `LOOKBACK` consecutive `Bar`s of one ticker, oldest first, ending
at the signal bar. All prices are `Decimal`. A `Bar` carries date, OHLC and volume only: no adjustment
factor, raw close or flag columns (section 2, point 4 and section 4.1). `cfg` is `DEFAULTS` overlaid with
the plugin's section of `config/patterns.toml`. The plugin gets no ticker name, no file access and no
clock.

**Output.** `None`, or:

```python
@dataclass(frozen=True)
class Point:
    date: datetime.date
    price: Decimal
    role: str                       # "swing_high", "trough_1", ...

@dataclass(frozen=True)
class Segment:
    start: Point
    end: Point
    role: str                       # "support", "resistance", "neckline"

@dataclass(frozen=True)
class Detection:
    direction: Literal["bullish", "bearish", "neutral"]
    points: tuple[Point, ...] = ()
    segments: tuple[Segment, ...] = ()
    levels: Mapping[str, Decimal] = field(default_factory=dict)   # "breakout", "invalidation"
    score: Decimal | None = None    # 0 to 1, plugin-defined shape quality. Not a probability.
    note: str = ""
```

The runner adds `pattern`, `version`, `config_hash`, `ticker` and `signal_date = bars[-1].date` to make
the `Signal` the API returns.

### 5.2 Plugin contract

1. **Event, not state.** Return a detection only on the bar where the condition first becomes true (for a
   breakout: `close[-1]` above the level and `close[-2]` not). Otherwise one pattern prints a marker on
   every following bar.
2. **Pure.** Same `(bars, cfg)` gives the same result. No module-level caches, no I/O, no randomness.
3. **Decimal only.** No `float`, no `math.sqrt` on prices, no numpy or pandas. `dse_quant/indicators.py` is
   float-based and must not be imported; a plugin that needs an average computes it in `Decimal`.
4. **Scale-invariant.** Thresholds are ratios, percentages or multiples of a range. Never an absolute BDT
   amount or a tick count. See 5.4.
5. **Geometry stays inside the window.** Every `Point` and `Segment` date must be a date in `bars`. The
   runner checks this and raises `PluginContractError`; a drawn line cannot reach past the signal bar.

### 5.3 Config format

`config/patterns.toml`, one table per plugin:

```toml
[swing_breakout]
enabled = true
left = 5
right = 5
min_break_pct = 0.5
```

Read with `tomllib.loads(text, parse_float=Decimal)`, so `0.5` arrives as `Decimal("0.5")` and never as a
float. At startup the runner rejects unknown plugin names, unknown keys, and values whose type differs
from the default's type. The check is `type(value) is type(default)`, because `bool` is a subclass of
`int` and `left = true` would otherwise pass. A missing table means defaults with `enabled = true`.
`config_hash` is the first 8 hex characters of a SHA-256 over `repr(sorted(cfg.items()))`; with `VERSION`
it identifies exactly which rule produced a signal. Config changes need a restart.

### 5.4 No lookahead

The rule is enforced by construction, then checked by tests.

- **Construction.** For signal bar index `i` the runner calls
  `detect(bars[max(0, i + 1 - LOOKBACK) : i + 1], cfg)`. Bars after `i` are not reachable from the plugin.
  A swing pivot at bar `j` that needs `right` bars after it can only appear once bar `j + right` is in the
  slice, so confirmation delay falls out of the slicing with no extra rule.
- **Scale leak.** The remaining leak is the back-adjusted scale (section 2, point 2). Inside a window
  whose newest action is at least 10 sessions old, the file's series and the series as this pipeline would
  have produced it on the signal date differ only by a constant factor. A scale-invariant plugin gives the
  same signals on both. This is tested: multiply every price in a window by `Decimal("0.5")` and the
  signal dates must not change.
- **Blocked windows.** The runner, not the plugin, drops a signal when either holds:
  - an ex-date from `data/clean/actions.csv` lies in the last 10 bars of the window. In those sessions
    the action was not yet accepted, so a same-day run would have seen a raw gap where the file shows a
    smooth series. A window that starts after the ex-date is not blocked: adjustment only rescales bars
    before the ex-date, so that window is the same in both views;
  - any bar in the window has `gap_flag`. This keeps limit-breaking moves that no accepted action explains,
    including every bonus after October 2025, from being read as breakdowns.

  Both rules only remove signals. The plugin still never sees the flag or the action list.

Cost: one ticker is at most 3,353 bars (median 3,008), each call sees at most `LOOKBACK` bars. Results are cached per
`(ticker, pattern, config_hash)` for the life of the process.
`shortcut: every bar re-runs detect on its own slice, fine for one ticker on demand; a market-wide scanner
needs an incremental driver, and that driver must pass the prefix test in 7.2 before it replaces this one.`

## 6. Shared pivot and trendline utilities (`geometry.py`)

All functions take `Sequence[Bar]` and return indices into that sequence plus `Decimal` prices. The x axis
is the **bar index**, not the calendar date: DSE has Friday/Saturday weekends, holidays and no-trade days,
and a line drawn over calendar days would bend at every gap.

```python
@dataclass(frozen=True)
class Pivot:
    idx: int               # bar that is the high or low
    confirmed_idx: int     # first bar at which this pivot is knowable
    kind: Literal["high", "low"]
    price: Decimal

def pivots(bars, left: int, right: int) -> list[Pivot]
    # Fractal swing: bars[idx].high is above the highs of `left` bars before and not below the highs
    # of `right` bars after (lows mirrored), so of equal highs the earliest bar is the pivot.
    # confirmed_idx = idx + right. Only pivots with confirmed_idx <= len(bars) - 1 are returned.
    # Needs 1 <= right <= left: with a shorter look-back two equal highs could both be pivots.
    # A bar with a non-positive price is never a pivot.
    # On a sliding window the result is the full-series pivots minus those within `left` bars of the
    # window's left edge; a bar's pivot status never changes because the window moved.

def zigzag(bars, reversal_pct: Decimal) -> list[Pivot]
    # Alternating highs and lows separated by at least reversal_pct. confirmed_idx is the bar whose
    # close first completes the reversal. The unfinished last leg is not returned.

@dataclass(frozen=True)
class Line:
    x0: int
    y0: Decimal
    slope: Decimal         # price per bar

def line_through(a: Pivot, b: Pivot) -> Line
def value_at(line: Line, idx: int) -> Decimal
def fit(points: Sequence[Pivot]) -> Line                     # least squares, Decimal arithmetic
def touches(line, pivots, tol_pct: Decimal) -> list[Pivot]   # pivots within tol_pct of the line
def crossed(line, bars, idx: int, side: Literal["above", "below"], tol_pct: Decimal) -> bool
    # close at idx is beyond the line by tol_pct and the close at idx - 1 was not
```

Rules that keep these safe to share:

- Tolerances are percentages of the line's price at that bar. No absolute amounts.
- A plugin may only use a pivot with `confirmed_idx <= len(bars) - 1`. `pivots` and `zigzag` already
  return nothing else, so a plugin cannot get an unconfirmed pivot by accident.
- Lines are linear in price. Log-scale lines are left out until a pattern needs them.
- Indices are relative to the window the plugin was given. Plugins convert to dates
  (`bars[idx].date`) before returning `Point`s, so indices never leave the plugin.

## 7. Test strategy

### 7.1 Two kinds of label, kept apart

| | Shape label | Outcome label |
|---|---|---|
| Question | Is the pattern there on this date? | What happened next? |
| Source | A person, looking at the chart | `labels.py`, computed |
| Uses bars | Up to and including the signal bar; labeled from a chart cut off at that bar | Strictly after the signal bar |
| Stored | `tests/fixtures/chart/labeled.toml` | Never stored by hand; recomputed |

Outcomes are never typed in by a person. That is what stops "it worked" from deciding which examples
count as the pattern.

### 7.2 Tests that need no market data (run in CI)

Synthetic bar sequences are built in the test code.

"Run in CI" means "able to": today `.github/workflows` runs only the two root risk-guard tests and
installs only pytest. Running `tests/test_chart_*.py` there needs a workflow change, which is not part of
this design.

- **Bars**: text to `Decimal` with no float step; quantization of long adjusted values; a truncated gzip
  raises.
- **Geometry**: a hand-built W gives the expected pivots; a pivot is absent from `bars[:idx + right]` and
  present in `bars[:idx + right + 1]`; equal highs resolve to the earliest; `fit` and `value_at` against
  hand-computed values.
- **Prefix test (runner)**: for a sequence `S` and every `k`, signals from running on `S` with
  `signal_date <= S[k].date` equal the signals from running on `S[:k + 1]`. True by construction today;
  the test exists so a faster driver cannot break it later.
- **Scale test (every plugin)**: prices times `Decimal("0.5")` give the same signal dates, with levels
  scaled.
- **Purity test (every plugin)**: calling `detect` on windows in shuffled order gives the same results.
- **Contract test**: a fake plugin returning a `Point` dated outside its window raises
  `PluginContractError`.
- **API**: every response is parsed with a `parse_float` hook that raises; unknown ticker is 404.
- **Blocked windows (runner)**: a fake always-firing plugin gives no signal in the 10 bars after an
  ex-date or in a window holding a `gap_flag` bar.
- **Static rules (AST scan of `chartapp/`)**: no `float` name or float literal, no `statistics` import;
  no import of `anthropic`, `requests`, `httpx`, `urllib.request` or `socket`; `labels` is imported by
  nothing in `api.py`, `runner.py`, `geometry.py` or `patterns/`. The scan cannot see every float (for
  example `/` between two ints), so it backs up the JSON test and does not replace it.

### 7.3 Labeled historical examples (run locally, skipped when `data/clean` is absent)

`tests/fixtures/chart/labeled.toml` stores references only, no prices, so no market data is committed:

```toml
[[example]]
pattern = "swing_breakout"
ticker = "SQURPHARMA"
signal_date = 2019-03-14     # illustrative
within = 2                   # sessions of tolerance either side
expect = "fire"
note = "clean break of the February swing high"

[[example]]
pattern = "swing_breakout"
ticker = "GP"
from = 2020-06-01            # illustrative
to = 2020-08-31
expect = "none"
note = "range-bound, three failed pokes above the high"
```

- `fire`: the plugin, run walk-forward through the runner, signals within `within` sessions of
  `signal_date`.
- `none`: no signal anywhere in `[from, to]`.
- The person labels from a chart that ends at the candidate signal bar (`/api/bars/{ticker}?to=<date>`),
  so they cannot see what happened next.
- Aim for about ten `fire` and ten `none` per pattern. Once the shape labels are fixed, run `labels.py`
  over the `fire` set; if every example went on to win, label more until failures are in the set. A
  plugin that only matches the winners has been tuned on hindsight.
- Examples are split by date. Thresholds are tuned on examples before a cutoff; later ones are a holdout
  that is run, not tuned on.
- A data rebuild can rescale history but does not move dates, and plugins are scale-invariant, so the
  examples survive rebuilds.

Because CI has no `data/`, these tests are a local gate. That is the price of not committing price data.

### 7.4 Outcome labels (`labels.py`)

```python
def forward_outcome(future: Sequence[Row], horizon: int, target_pct: Decimal, stop_pct: Decimal,
                    min_hold: int = 2) -> Outcome | None
```

The caller passes `future = bars[i + 1:]`. The signal bar and everything before it are not arguments, so
the label cannot read them.

- Entry reference is the **open of bar `i + 1`**: an EOD signal is known only after the close of bar `i`.
  All returns are measured from that open, not from the signal bar's close.
- `Outcome` holds: return at the close of bar `horizon`, maximum favourable and adverse excursion, which of
  target or stop was touched first.
- Whether the entry would have filled is **not** part of the label. An upper-limit lock on bar `i + 1`
  blocks a buy, but deciding that needs the signal bar's raw close, which a label may not read, and the
  file's `upper_lock` is computed on adjusted prices (section 2, point 4). Fill feasibility is left to a
  later evaluation step and is out of v1; until then outcomes assume the entry filled, and say so.
- `future[0]` is the entry bar, T. Target and stop touches count only from `future[min_hold]` onward.
  Shares bought at T cannot be sold before T+2 (T+3 for category Z). Bars are sessions the share traded
  in; a no-trade day has no row and is not counted, so after one `future[2]` is later than T+2. The wait is
  never too short, only sometimes longer than needed.
  The clean file has no category column, so `min_hold` is a parameter with default 2.
- Target and stop both inside one bar: counted as the stop.
- Fewer than `horizon` bars in `future`: returns `None`. No partial labels.
- Any bar within the horizon has `gap_flag`: returns `None`. An unadjusted bonus would read as a crash
  and trigger a false stop.
- Any price in the horizon is zero or negative: returns `None` (the file has such a bar, section 2).
- The window is `future[:horizon]`, so `horizon` counts the entry bar and the return is taken at the close
  of `future[horizon - 1]`. Excursions cover the whole window, including the bars before `min_hold`.
- Outcomes are for a long position. DSE has no shorting, so a bearish signal has no outcome label yet.
- A touch is a price reaching the level, not a fill. On a gap down or a lower-lock day the loss can be
  larger than `stop_pct`; `mae_pct` bounds it.
- Touch levels carry a 0.0002 allowance. Adjusted prices are cut to 4 decimal places on load, so without
  it an exact touch (entry 100, high 110) is lost about half the time once a later bonus rescales both,
  and the label would change when the data is rebuilt.
- **Do not label windows that reach past about 2026-01-08** (the A2 end, 2026-01-22, less 10 sessions,
  holidays not checked). No
  corporate action is inferred after that. A later bonus inside the daily limit carries no `gap_flag`,
  reads as a plain fall, and can fire a stop that never happened. Cash dividends are not adjusted at all,
  so an ex-dividend drop is in every label as a price fall.
- Outcomes are gross. No costs are applied and nothing is imported from `dse_quant/backtest/`.

Tests: changing any bar at or before `i` leaves the outcome unchanged; changing a bar after `i` leaves the
detection unchanged; the same-bar and short-future cases above.

Outcome labels are for offline evaluation. Any claim that a pattern has an edge needs a pre-registration
document like the existing `docs/*_PREREG.md` files, and is outside this design.

## 8. Frontend

Three static files, no build step. Lightweight Charts is vendored and pinned (v5 line), so the app works
offline. Its API changed between v4 and v5 (series creation, markers, panes); check the docs for the
pinned version when building. The library is Apache-2.0 and asks for attribution; leave its attribution
logo on.

- Candlestick series, volume histogram underneath. Time values are the `YYYY-MM-DD` strings from the API,
  so missing sessions simply do not appear.
- Close-only bars are drawn as a line, not candles. A bar is close-only when its `o`, `h`, `l` and `c`
  are equal and `v` is 0. Today that is 261 bars: `00DSEX` from 2026-01-25 (183) and 78 scattered share
  bars, mostly from 2014. `chart.js` puts those bars
  in a line series that starts at the last real candle's close, so the two join. The rule is on the data,
  with no ticker name or date in the code. A share that traded at one price all day has volume and stays
  a candle.
- Signals are series markers on `signal_date`. Pressing a signal's date in the table selects it: only then
  are its `points` drawn as small markers, its `segments` as two-point line
  series, and its `levels` as short horizontal line series that end at `signal_date`. Drawing every
  signal's shape at once would bury the chart. The library's price
  lines span the whole chart, so they are not used. Nothing is drawn to the right of the signal bar.
- `gap` and lock flags are shown as small markers so an unadjusted gap is not mistaken for a crash.
- A table under the chart lists signals. It prints the API's strings as they came.

Float boundary: only `chart.js` calls `Number()` on price strings, and what it makes goes to the chart.
`app.js` and the table never do arithmetic on prices.

## 9. Minimum first version

In:

- `/api/meta`, `/api/tickers`, `/api/bars`, `/api/detections`.
- One page: ticker search, candles, volume, staleness badge, signal markers, signal table.
- `geometry.pivots`, the runner, `config/patterns.toml`, one plugin (`swing_breakout`).
- `labels.forward_outcome` and the labeled-example harness with a first set of examples.
- All tests in 7.2.

Out, named so they are not built by accident:

- Trendlines and `trendline_break` (`zigzag`, `Line`, `fit`, `touches`, `crossed`): first thing after v1.
- Market-wide scanner, as-of replay slider, indicator overlays, raw-price toggle, log scale.
- `/api/patterns`, a ticker type filter, per-request config overrides, hot reload of data or config.
- Outcome statistics pages or any edge claim.
- Writing anything to disk.

## 10. Build order

Each step ends with its tests passing.

1. `bars.py` and `test_chart_bars.py`, plus the AST static-rule test. Add `fastapi`, `uvicorn`, `httpx`
   pins.
2. `api.py` with `/api/meta`, `/api/tickers`, `/api/bars`, and the no-float-in-JSON test.
3. `web/`: candles, close-only line fallback, volume, ticker search, staleness badge. **First usable point: a chart viewer.**
4. `geometry.pivots` with synthetic tests.
5. `runner.py`: discovery, config validation, slicing, blocked windows, contract checks. Prefix,
   blocked-window and contract tests. `Point`, `Segment` and `Detection` live in `patterns/__init__.py`
   so plugins import them without importing the runner.
6. `patterns/swing_breakout.py` with scale and purity tests.
7. `/api/detections` with the per-`(ticker, pattern)` signal cache; markers and the signal table in `web/`.
8. `labels.py` with its tests.
9. `labeled.toml` harness. Needs a person to label the first examples.

After v1: trendline utilities and `trendline_break`, then decide on the scanner.

## 11. Decisions and open question

Decided 2026-11-11:

- A roughly 9-second startup is acceptable. No per-ticker split in v1.
- `00DSEX` falls back to a line where it has close only (section 8).

Open:

1. Who labels the first examples, and for which tickers? Needed at build step 9, not before.
