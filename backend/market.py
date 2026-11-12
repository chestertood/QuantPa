"""Market data, cached briefly.

Quotes come from CNBC's public quote service, with Yahoo behind it as fallback.
Yahoo was primary until 2026-07-24, when it served every symbol's 10:34 ET price
for hours — marketState REGULAR, exchangeDataDelayedBy 0, no hint in the payload
except regularMarketTime. MU read -6.70% while it was really trading at -5.5%.
CNBC returned the live price throughout, timestamps its prints, needs no crumb
or cookie handshake, and covered every symbol in the watchlists.

History still comes from Yahoo's chart API — staleness doesn't matter there.
All of it goes through curl_cffi browser impersonation to avoid HTTP 429s.
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests

# Cache lifetime for a quote — the floor on how stale a price can be. Matches
# the frontend poll interval. The batch endpoint prices a whole watchlist in one
# request, so 5s costs ~0.2 requests/second no matter how many symbols.
# ponytail: knob kept anyway — raise QUOTE_TTL if Yahoo ever starts 429ing.
_QUOTE_TTL = float(os.getenv("QUOTE_TTL", "5"))  # seconds

# How old a quote may be, during an open market, before we call it stale. A
# feed can freeze — on 2026-07-24 Yahoo served every symbol's 10:34 ET price for
# ~2.5h with marketState REGULAR — and nothing in the price fields shows it,
# only the print timestamp. 30 min separates that from the honest case: thin
# ADRs (IBDRY, SIEGY, TOELY…) simply don't trade for ~19 min at a time, and
# flagging those would cry wolf on a third of the watchlist.
_STALE_AFTER = float(os.getenv("QUOTE_STALE_AFTER", "1800"))  # seconds
_quote_cache: dict[str, tuple[float, dict]] = {}

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Both quote sources are batch endpoints: every symbol in one request, vs one
# request per symbol for the chart API. That's what makes a 5s poll of a
# 200-symbol watchlist cheap instead of a wall of 429s.
_CNBC_URL = "https://quote.cnbc.com/quote-html-webservice/quote.htm"
_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
# ponytail: fixed chunk. The endpoint takes more, but a long query string is the
# other way to get blocked. Raise it if a watchlist ever outgrows one request.
_BATCH_SIZE = 50

# One impersonated session per thread. Yahoo blocks plain requests with 429,
# and a Session wraps a libcurl handle that must not be shared across threads.
_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = _local.session = requests.Session(impersonate="chrome")
    return s


def _fetch_chart(symbol: str, rng: str, interval: str) -> dict:
    r = _session().get(
        _CHART.format(symbol=symbol),
        params={"range": rng, "interval": interval},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"no chart data for {symbol}")
    return result[0]


def _yahoo(symbol: str) -> str:
    """Webull writes share classes with a space ("BRK A"); Yahoo wants "BRK-A"."""
    return symbol.replace(" ", "-")


def _cnbc(symbol: str) -> str:
    """CNBC spells the same share class "BRK.A"."""
    return symbol.replace(" ", ".")


def _num(v) -> float | None:
    """CNBC sends numbers as strings, and "UNCH"/"" when it has none."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cnbc_quotes(symbols: list[str]) -> dict[str, dict]:
    """Quote several CNBC-form symbols in one request. Same contract as
    _batch_quotes: unknown symbols are absent, transport failure raises."""
    r = _session().get(
        _CNBC_URL,
        params={
            "symbols": "|".join(symbols),
            "requestMethod": "quick",
            "exthrs": "1",
            "fund": "1",
            "output": "json",
        },
        timeout=15,
    )
    r.raise_for_status()
    res = r.json()["QuickQuoteResult"]["QuickQuote"]
    if isinstance(res, dict):  # a single symbol comes back unwrapped
        res = [res]

    out: dict[str, dict] = {}
    for q in res:
        sym = q.get("symbol")
        price = _num(q.get("last"))
        if not sym or price is None:
            continue
        # Derive the prior close from `change` rather than reading
        # previous_day_closing, which CNBC rolls forward the moment a session
        # closes: from the closing bell until the next open it equals `last`,
        # and trusting it makes the day change read 0.00% for every symbol all
        # night. `change` keeps pointing at the session `last` belongs to, so
        # last - change is the right prior close in every market state (and
        # matches Yahoo's regularMarketPreviousClose).
        change = _num(q.get("change"))
        prev = price - change if change is not None else _num(q.get("previous_day_closing"))
        ms = q.get("last_time_msec")
        out[sym] = {
            "price": price,
            "prev_close": round(prev, 4) if prev is not None else price,
            "ts": int(ms) / 1000 if ms else None,
            # REG_MKT means the regular session is open; pre/post and closed
            # states are left alone so _frozen doesn't flag a legitimately old
            # after-hours price.
            "state": "REGULAR" if str(q.get("curmktstatus", "")).startswith("REG_MKT") else None,
        }
    return out


def _crumb() -> str:
    """Session crumb required by the batch quote endpoint. Cached per thread
    alongside the session whose cookies it's bound to — a crumb from one cookie
    jar is rejected with another."""
    c = getattr(_local, "crumb", None)
    if c is None:
        s = _session()
        # 404s, but it's what sets the cookies getcrumb checks for.
        s.get("https://fc.yahoo.com", timeout=15)
        r = s.get(_CRUMB_URL, timeout=15)
        r.raise_for_status()
        c = r.text.strip()
        if not c or len(c) > 64:  # an HTML error page is not a crumb
            raise ValueError(f"bad crumb response: {c[:80]!r}")
        _local.crumb = c
    return c


def _batch_quotes(symbols: list[str], _retry: bool = True) -> dict[str, dict]:
    """Quote several Yahoo-form symbols in one request.

    Returns {yahoo_symbol: {"price", "prev_close"}}; symbols Yahoo doesn't know
    are simply absent from the response. Raises on transport/crumb failure —
    get_quotes treats that as "fall back to the chart API".
    """
    r = _session().get(
        _QUOTE_URL,
        params={"symbols": ",".join(symbols), "crumb": _crumb()},
        timeout=15,
    )
    if r.status_code in (401, 403) and _retry:
        # Crumbs expire. Drop it and re-handshake once before giving up.
        _local.crumb = None
        return _batch_quotes(symbols, _retry=False)
    r.raise_for_status()


    out: dict[str, dict] = {}
    for q in r.json().get("quoteResponse", {}).get("result", []):
        sym = q.get("symbol")
        price = q.get("regularMarketPrice")
        if not sym or price is None:
            continue
        # Unlike the chart API's meta, this prev close is reliably the prior
        # trading day, so no second-to-last-close reconstruction is needed.
        prev = q.get("regularMarketPreviousClose")
        out[sym] = {
            "price": float(price),
            "prev_close": float(prev if prev is not None else price),
            "ts": q.get("regularMarketTime"),
            "state": q.get("marketState"),
        }
    return out


def _frozen(q: dict, now: float) -> bool:
    """True when a quote is too old to be a live price.

    Outside regular trading the last price is *supposed* to be hours old, so a
    quote can only be frozen while its market is open — otherwise every symbol
    would flag overnight and on weekends. The chart fallback reports no market
    state, so it never trips this.
    """
    ts = q.get("ts")
    return bool(ts and now - ts > _STALE_AFTER and q.get("state") == "REGULAR")


def _freshness(q: dict, now: float) -> dict:
    """Public quote shape: price, prev_close, plus how old the print is."""
    ts = q.get("ts")
    return {
        "price": q["price"],
        "prev_close": q["prev_close"],
        # Clamped: a source clock a second ahead of ours shouldn't render as
        # "-1s old".
        "age_s": max(0, round(now - ts)) if ts else None,
        "stale": _frozen(q, now),
    }


def _quote(symbol: str) -> dict | None:
    """One symbol's quote, or None if it can't be fetched (caller falls back)."""
    try:
        res = _fetch_chart(_yahoo(symbol), rng="5d", interval="1d")
        meta = res["meta"]
        # Prev close must be the PRIOR trading day. meta.previousClose is
        # often null and meta.chartPreviousClose is the close before the
        # whole 5d window (a ~week-old price) — using it inflates the day
        # change. Take the second-to-last daily close from the series.
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        price = meta.get("regularMarketPrice")
        if price is None:
            price = closes[-1]
        prev = meta.get("previousClose")
        if prev is None:
            prev = closes[-2] if len(closes) >= 2 else price
        # No marketState in chart meta, so this path can report age but never
        # claims staleness — see _freshness.
        return {
            "price": float(price),
            "prev_close": float(prev),
            "ts": meta.get("regularMarketTime"),
            "state": None,
        }
    except Exception:
        return None


def get_quotes(symbols: list[str]) -> dict[str, dict]:
    """Return {symbol: {"price", "prev_close", "age_s", "stale"}}.

    Uses a QUOTE_TTL cache. A symbol that fails to fetch is omitted. `age_s` is
    how old the source's own print is (not how long we cached it) and `stale`
    warns that a supposedly-open market handed us a frozen price.

    Uncached symbols walk the source chain: CNBC batch, then Yahoo batch for
    whatever CNBC didn't return, then Yahoo's per-symbol chart API for the
    stragglers — that last one in parallel, since serially a 25-symbol watchlist
    took ~10s to render. Each step only sees what the one before it missed.
    """
    now = time.time()
    fetched: dict[str, dict] = {}
    uncached: list[str] = []

    for sym in symbols:
        cached = _quote_cache.get(sym)
        if cached and now - cached[0] < _QUOTE_TTL:
            fetched[sym] = cached[1]
        else:
            uncached.append(sym)

    def keep(sym: str, q: dict) -> None:
        _quote_cache[sym] = (now, q)
        fetched[sym] = q

    if uncached:
        missing = list(uncached)
        for translate, fetch in ((_cnbc, _cnbc_quotes), (_yahoo, _batch_quotes)):
            if not missing:
                break
            # Each source answers in its own symbol spelling, so map back to
            # what the caller asked for ("BRK.B" -> "BRK B").
            smap = {translate(s): s for s in missing}
            keys = list(smap)
            for i in range(0, len(keys), _BATCH_SIZE):
                try:
                    for key, q in fetch(keys[i:i + _BATCH_SIZE]).items():
                        if key in smap:
                            keep(smap[key], q)
                except Exception:
                    break  # source down; the next one covers it
            missing = [s for s in missing if s not in fetched]

        if missing:
            # ponytail: fixed 8-way pool. Raise it if Yahoo tolerates more,
            # lower it if the 429s come back.
            with ThreadPoolExecutor(max_workers=8) as pool:
                for sym, q in zip(missing, pool.map(_quote, missing)):
                    if q:
                        keep(sym, q)

    # Age is recomputed per call, so a cache hit still reports the true age of
    # the underlying print.
    return {sym: _freshness(q, now) for sym, q in fetched.items()}


def get_history(symbol: str, period: str = "6mo", interval: str = "1d") -> list[dict]:
    """Return [{"date": "YYYY-MM-DD", "close": float}, ...] for one symbol."""
    res = _fetch_chart(_yahoo(symbol), rng=period, interval=interval)
    timestamps = res.get("timestamp", [])
    closes = res["indicators"]["quote"][0]["close"]
    points = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        date = time.strftime("%Y-%m-%d", time.gmtime(ts))
        points.append({"date": date, "close": round(float(close), 2)})
    return points
