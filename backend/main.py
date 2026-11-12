"""QuantPa backend — Phase 1: portfolio dashboard + market data."""
import os
import re
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import backtest
import cashflow
import chat
import demo
import ff_calendar
import fundamentals
import news
import tax_summary
from market import get_history, get_quotes
from portfolio import build_portfolio, build_portfolio_from_positions
import webull_sync

load_dotenv()

# Portfolio CSV path — override with PORTFOLIO_CSV in .env
CSV_PATH = os.getenv("PORTFOLIO_CSV", os.path.join(os.path.dirname(__file__), "sample_portfolio.csv"))

# Where positions come from: "csv" (default) or "webull" (Phase 2 sync).
PORTFOLIO_SOURCE = os.getenv("PORTFOLIO_SOURCE", "csv").lower()

# DEMO=1: no real account data anywhere — sample CSV positions, made-up
# cashflow/tax/watchlists (demo.py). For screenshots and recordings.
DEMO = os.getenv("DEMO") == "1"
if DEMO:
    PORTFOLIO_SOURCE = "csv"
    CSV_PATH = os.path.join(os.path.dirname(__file__), "sample_portfolio.csv")

app = FastAPI(title="QuantPa", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "source": PORTFOLIO_SOURCE, "csv": os.path.basename(CSV_PATH)}


@app.get("/api/source")
def source():
    """Report the active portfolio source and Webull auth status."""
    return {
        "source": "demo" if DEMO else PORTFOLIO_SOURCE,
        "csv": os.path.basename(CSV_PATH),
        "webull_authed": webull_sync.configured(),
    }


# Webull holdings only change when you trade, but prices change constantly, so
# the frontend now polls every 10s. Cache the slow, stable half (the Webull
# round-trip, ~1-3s) and let get_quotes re-price the cached holdings on every
# request — that's what makes fast polling affordable. A fill shows up within
# one bucket; lower this if you trade while watching the dashboard.
_POSITIONS_TTL = int(os.getenv("WEBULL_POSITIONS_TTL", "60"))  # seconds


@lru_cache(maxsize=1)
def _positions_cached(_bucket: int):
    """Webull holdings for one TTL bucket. Exceptions aren't cached, so a
    failed sync retries on the next request instead of sticking."""
    return webull_sync.get_webull_positions()


@app.get("/api/portfolio")
def portfolio():
    try:
        if PORTFOLIO_SOURCE == "webull":
            positions = _positions_cached(int(time.time() // _POSITIONS_TTL))
            data = build_portfolio_from_positions(positions)
        else:
            data = build_portfolio(CSV_PATH)
    except webull_sync.WebullError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    data["as_of"] = datetime.now(timezone.utc).isoformat()
    data["source"] = "demo" if DEMO else PORTFOLIO_SOURCE
    # Positions price in USD; the dashboard displays in baht, so hand it the
    # live rate. Reuses get_quotes' existing cache/fallback chain — no new
    # fetch path needed for one more "symbol".
    fx = get_quotes(["THB=X"]).get("THB=X")
    data["usd_thb_rate"] = fx["price"] if fx else None
    return data


_WATCHLIST_TTL = 600  # seconds

# Serialises the cold build below. React StrictMode double-invokes effects in
# dev, so mounting Markets fires two /api/watchlists at once; both missed the
# empty cache and did every Webull + Yahoo call twice, which contended badly
# enough to take 14s each vs 5.7s for one. The second caller now waits for the
# first and reads its cache.
# ponytail: one global lock — a single expensive endpoint doesn't need per-key
# locks. Revisit if a second slow endpoint wants the same treatment.
_watchlists_lock = threading.Lock()


@lru_cache(maxsize=1)
def _watchlists_cached(_bucket: int):
    """Webull watchlists for one TTL bucket — the slowest part of /api/watchlists
    (~3s for 10 lists) and the least volatile, since membership only changes when
    you edit a list in Webull. Prices are not cached here; get_quotes keeps its
    own 60s TTL, so quotes stay fresh even on a watchlist cache hit.
    Raised exceptions aren't cached, so failures retry immediately.
    """
    return webull_sync.get_webull_watchlists()


@app.get("/api/watchlists")
def watchlists():
    """Return the user's pinned Webull watchlists, each symbol enriched with a
    live quote (price + day change %). Requires PORTFOLIO_SOURCE=webull."""
    with _watchlists_lock:
        try:
            lists = demo.get_watchlists() if DEMO else _watchlists_cached(int(time.time() // _WATCHLIST_TTL))
        except webull_sync.WebullError as e:
            raise HTTPException(status_code=502, detail=str(e))

        all_syms = sorted({s for wl in lists for s in wl["symbols"]})
        quotes = get_quotes(all_syms) if all_syms else {}

    out = []
    for wl in lists:
        # An empty watchlist renders as a panel with nothing in it, pushing the
        # real lists (and the chart) down the page. Drop them.
        if not wl["symbols"]:
            continue
        items = []
        for sym in wl["symbols"]:
            q = quotes.get(sym)
            if q:
                prev = q["prev_close"]
                day_pct = (q["price"] - prev) / prev * 100 if prev else 0.0
                items.append({
                    "symbol": sym,
                    "price": q["price"],
                    "day_change_pct": day_pct,
                    "stale": q["stale"],
                    "quote_age_s": q["age_s"],
                })
            else:
                items.append({
                    "symbol": sym,
                    "price": None,
                    "day_change_pct": None,
                    "stale": True,
                    "quote_age_s": None,
                })
        out.append({"id": wl["id"], "name": wl["name"], "items": items})

    return {
        "watchlists": out,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


@lru_cache(maxsize=1)
def _cashflow_cached(_fingerprint):
    """Statement PDFs for one folder state. Keyed on (file count, newest mtime)
    rather than a clock bucket: the source only changes when you drop in a new
    statement, and re-parsing all six costs ~3.7s."""
    return cashflow.load_cashflow()


@app.get("/api/cashflow")
def get_cashflow():
    """Deposit / withdrawal history from the Webull monthly statement PDFs."""
    try:
        data = demo.load_cashflow() if DEMO else _cashflow_cached(cashflow.statement_fingerprint())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"statement parse error: {e}")
    return {**data, "as_of": datetime.now(timezone.utc).isoformat()}


@lru_cache(maxsize=1)
def _tax_summary_cached(_fingerprint):
    """Same fingerprint scheme as _cashflow_cached — re-parses only when a
    statement PDF is added or replaced."""
    return tax_summary.load_tax_summary()


@app.get("/api/tax-summary")
def get_tax_summary():
    """Raw figures for an accountant: realized trading P/L (FIFO-matched from
    the statement PDFs), dividends, interest, fees, and cash withdrawn to
    Thailand — grouped by year. Does not compute tax owed; see the `note`
    field returned with the data."""
    try:
        data = demo.load_tax_summary() if DEMO else _tax_summary_cached(cashflow.statement_fingerprint())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"statement parse error: {e}")
    return {**data, "as_of": datetime.now(timezone.utc).isoformat()}


@app.get("/api/news")
def get_news():
    """Econ/market headlines, ranked by relevance to the current portfolio."""
    try:
        if PORTFOLIO_SOURCE == "webull":
            positions = _positions_cached(int(time.time() // _POSITIONS_TTL))
            data = build_portfolio_from_positions(positions)
        else:
            data = build_portfolio(CSV_PATH)
    except Exception:
        data = {"positions": []}  # news still useful with no portfolio context

    holdings_by_sector: dict[str, list[dict]] = {}
    for p in data["positions"]:
        sector = fundamentals.get_sector(p["symbol"])
        if sector:
            holdings_by_sector.setdefault(sector, []).append(
                {"symbol": p["symbol"], "weight_pct": p["weight"]}
            )

    return {
        "items": news.get_news(holdings_by_sector),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


_ECON_TTL = 300  # seconds — short enough that Actual shows up soon after a release prints


@lru_cache(maxsize=1)
def _econ_calendar_cached(_bucket: int):
    return ff_calendar.fetch_calendar("thisweek")


@app.get("/api/econ-calendar")
def econ_calendar():
    """This week's red-folder (high-impact) econ events, for next to the chart."""
    try:
        events = _econ_calendar_cached(int(time.time() // _ECON_TTL))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    rows = [ff_calendar.as_row(e) for e in ff_calendar.high_impact(events)]
    return {"events": rows, "as_of": datetime.now(timezone.utc).isoformat()}


@app.get("/api/fundamentals/{symbol}")
def get_fundamentals(symbol: str):
    """Valuation / profitability / financial-health / trading metrics for one
    symbol. 404s when Yahoo has no fundamentals for it (some foreign listings)."""
    try:
        data = fundamentals.get_fundamentals(symbol.upper())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"fundamentals error: {e}")
    if data is None:
        raise HTTPException(status_code=404, detail=f"no fundamentals for {symbol}")
    return {**data, "symbol": symbol.upper()}


@app.get("/api/positions/{symbol}/history")
def history(symbol: str, period: str = "6mo"):
    try:
        points = get_history(symbol.upper(), period=period)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"market data error: {e}")
    if not points:
        raise HTTPException(status_code=404, detail=f"no history for {symbol}")
    return {"symbol": symbol.upper(), "period": period, "points": points}


# Symbols are interpolated into an outbound Yahoo URL, so the character set is
# constrained here rather than trusted from the client.
_SYMBOL_OK = re.compile(r"^[A-Za-z0-9.\- ]{1,12}$")


class BacktestRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: list(backtest.DEFAULT_BASKET), max_length=20)
    benchmark: str = "SPY"
    rule: Literal["sma", "momentum"] = "sma"
    params: dict = Field(default_factory=dict)
    years: int = Field(default=5, ge=1, le=20)
    cost_bps: float = Field(default=5.0, ge=0, le=100)


@app.post("/api/backtest")
def run_backtest(req: BacktestRequest):
    """Run one backtest study: strategy vs basket buy-and-hold vs benchmark
    buy-and-hold, with a parameter sweep and an in/out-of-sample split.

    POST rather than GET: the body is a nested object and the response is a
    computed study, not a cacheable resource.
    """
    symbols = [s.strip().upper() for s in req.symbols if s.strip()]
    if not symbols:
        raise HTTPException(status_code=400, detail="no symbols given")
    for s in [*symbols, req.benchmark]:
        if not _SYMBOL_OK.match(s):
            raise HTTPException(status_code=400, detail=f"bad symbol: {s}")

    try:
        return backtest.run_study(
            symbols=tuple(symbols),
            benchmark=req.benchmark.strip().upper(),
            rule=req.rule,
            params=req.params,
            years=req.years,
            cost_bps=req.cost_bps,
        )
    except ValueError as e:
        # No overlapping history, no adjusted close, unknown rule — all caller error.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"backtest data error: {e}")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


@app.post("/api/chat")
async def chat_turn(body: ChatIn):
    """One assistant turn via the local Claude Code login (see chat.py)."""
    try:
        return await chat.ask(body.message, body.session_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"chat error: {e}")
