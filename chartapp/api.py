"""FastAPI app: read-only JSON over chartapp.bars (docs/design/eod-chart-app.md 4.2).
Every price is a Decimal field, which Pydantic writes as a JSON string. No JSON floats anywhere.

Run: python -m uvicorn chartapp.api:app --host 127.0.0.1 --port 8000"""
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import mimetypes

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chartapp import bars as B
from dse_quant.sessions import closed_reason, expected_session

WEB = Path(__file__).parent / "web"
# Windows takes MIME types from the registry, where .js is sometimes text/plain; browsers refuse that for modules
mimetypes.add_type("text/javascript", ".js")


class Meta(BaseModel):
    last_bar: date
    expected_session: date
    sessions_behind: int
    rows: int
    tickers: int
    file_mtime: datetime


class TickerOut(BaseModel):
    ticker: str
    type: str
    first: date
    last: date
    bars: int


class BarOut(BaseModel):
    t: date
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741  short keys keep a 3,000-bar response small
    c: Decimal
    v: int
    value: Decimal
    c_raw: Decimal
    adj: Decimal
    flags: list[str]


class BarsOut(BaseModel):
    ticker: str
    type: str
    adjusted: bool = True
    bars: list[BarOut]


def sessions_behind(last: date, expected: date) -> int:
    """DSE sessions after `last` up to and including `expected`."""
    return sum(closed_reason(last + timedelta(days=n)) is None for n in range(1, (expected - last).days + 1))


def _bar(r: B.Row) -> BarOut:
    flags = [name for name, on in (("gap", r.gap_flag), ("lower_lock", r.lower_lock),
                                   ("upper_lock", r.upper_lock)) if on]
    return BarOut(t=r.date, o=r.open, h=r.high, l=r.low, c=r.close, v=r.volume, value=r.value,
                  c_raw=r.close_raw, adj=r.adj_factor, flags=flags)


_DAY = r"^\d{4}-\d\d-\d\d$"  # a plain `date` param would also accept numbers as Unix timestamps


def _day(text: str | None) -> date | None:
    try:
        return None if text is None else date.fromisoformat(text)
    except ValueError:
        raise HTTPException(422, f"not a date: {text!r}") from None


def create_app(path: Path = B.PRICES) -> FastAPI:
    index: dict[str, TickerOut] = {}

    @asynccontextmanager
    async def lifespan(_):
        # read the whole file before serving: a truncated or missing file must stop startup
        for t, g in sorted(B.table(path).items()):
            index[t] = TickerOut(ticker=t, type=g.type.iloc[0], first=g.date.min(), last=g.date.max(), bars=len(g))
        if not index:
            raise ValueError(f"{path}: no rows")
        yield

    # /docs and /redoc load their scripts from a CDN; this app makes no network calls
    app = FastAPI(title="DSE EOD charts", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/api/meta")
    def meta() -> Meta:
        last, expected = max(v.last for v in index.values()), expected_session(date.today())
        return Meta(last_bar=last, expected_session=expected, sessions_behind=sessions_behind(last, expected),
                    rows=sum(v.bars for v in index.values()), tickers=len(index),
                    file_mtime=datetime.fromtimestamp(path.stat().st_mtime_ns // 10**9))

    @app.get("/api/tickers")
    def tickers(q: str = "") -> list[TickerOut]:
        return [v for t, v in index.items() if t.startswith(q.upper())]

    @app.get("/api/bars/{ticker}")
    def bars(ticker: str, start: str | None = Query(None, alias="from", pattern=_DAY),
             to: str | None = Query(None, pattern=_DAY)) -> BarsOut:
        if ticker not in index:  # checked against the loaded set; never used to build a path
            raise HTTPException(404, f"unknown ticker {ticker!r}")
        start, to = _day(start), _day(to)
        rs = [r for r in B.rows(ticker, path) if (start is None or r.date >= start) and (to is None or r.date <= to)]
        return BarsOut(ticker=ticker, type=index[ticker].type, bars=[_bar(r) for r in rs])

    app.mount("/", StaticFiles(directory=WEB, html=True))  # last, so /api routes win
    return app


app = create_app()
