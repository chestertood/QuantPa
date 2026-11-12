"""Fundamental metrics for one symbol, from Yahoo's quoteSummary endpoint.

Reuses market.py's session and crumb: same curl_cffi browser impersonation
(plain requests get 429'd), same per-thread crumb cache, same 401 re-handshake.

Values are passed through as Yahoo reports them. Yahoo's fundamentals are
uneven — fields go null per-symbol, and some are visibly wrong (BRK.B came
back with priceToBook 0.001) — so nothing here fills a gap with a guess or a
derived substitute. A missing number stays missing and renders as "—".
"""
import time

import market

# Fundamentals move on quarterly earnings, not by the second, so this cache is
# in hours where the quote cache is in seconds.
_TTL = 3600.0
_cache: dict[str, tuple[float, dict]] = {}

_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
_MODULES = "summaryDetail,defaultKeyStatistics,financialData"


def _raw(value):
    """Yahoo wraps numbers as {"raw": 1.23, "fmt": "1.23"}; some are bare."""
    if isinstance(value, dict):
        return value.get("raw")
    return value


def _flatten(payload):
    """Merge the requested modules into one flat {field: raw_value} map.

    Field names don't collide across these three modules in a way that matters
    (forwardPE and beta appear twice with the same value), so a flat namespace
    keeps the extraction below readable.
    """
    result = payload.get("quoteSummary", {}).get("result")
    if not result:
        return {}
    flat = {}
    for module in result[0].values():
        if isinstance(module, dict):
            for key, value in module.items():
                flat[key] = _raw(value)
    return flat


def shape(payload):
    """Turn a quoteSummary payload into the four metric groups the UI shows.

    Split out from the fetch so it can be tested against a captured payload
    without hitting the network.
    """
    f = _flatten(payload)
    if not f:
        return None

    return {
        "valuation": {
            "market_cap": f.get("marketCap"),
            "enterprise_value": f.get("enterpriseValue"),
            "pe_trailing": f.get("trailingPE"),
            "pe_forward": f.get("forwardPE"),
        },
        "profitability": {
            # Yahoo sends margins and growth as fractions (0.276 = 27.6%).
            # Kept as fractions here; the UI does the ×100 so the unit
            # conversion lives in one place.
            "roe": f.get("returnOnEquity"),
            "profit_margin": f.get("profitMargins"),
            "gross_margin": f.get("grossMargins"),
            "operating_margin": f.get("operatingMargins"),
            "revenue_growth": f.get("revenueGrowth"),
            "earnings_growth": f.get("earningsGrowth"),
        },
        "health": {
            "debt_to_equity": f.get("debtToEquity"),
            "current_ratio": f.get("currentRatio"),
            "quick_ratio": f.get("quickRatio"),
            "total_cash": f.get("totalCash"),
            "free_cashflow": f.get("freeCashflow"),
        },
        "trading": {
            "week52_low": f.get("fiftyTwoWeekLow"),
            "week52_high": f.get("fiftyTwoWeekHigh"),
            "beta": f.get("beta"),
            "dividend_yield": f.get("dividendYield"),
            "target_mean": f.get("targetMeanPrice"),
            "recommendation": f.get("recommendationKey"),
            "analyst_count": f.get("numberOfAnalystOpinions"),
        },
        "source": "Yahoo Finance",
    }


def _fetch(symbol):
    r = market._session().get(
        _URL.format(symbol=market._yahoo(symbol)),
        params={"modules": _MODULES, "crumb": market._crumb()},
        timeout=15,
    )
    if r.status_code in (401, 403):
        # Same expiry dance as market._batch_quotes: drop the crumb, retry once.
        market._local.crumb = None
        r = market._session().get(
            _URL.format(symbol=market._yahoo(symbol)),
            params={"modules": _MODULES, "crumb": market._crumb()},
            timeout=15,
        )
    if r.status_code == 404:
        return None  # Yahoo has no such symbol (e.g. the 688825 Shanghai line)
    r.raise_for_status()
    return r.json()


def get_fundamentals(symbol):
    """Metric groups for `symbol`, or None when Yahoo has no fundamentals."""
    now = time.time()
    cached = _cache.get(symbol)
    if cached and now - cached[0] < _TTL:
        return cached[1]

    payload = _fetch(symbol)
    data = shape(payload) if payload else None
    # Cached either way: a symbol Yahoo doesn't cover won't start being covered
    # within the hour, and re-asking on every chart open costs a round trip.
    _cache[symbol] = (now, data)
    return data


# GICS sector, e.g. "Technology", "Financial Services", "Real Estate" — changes
# essentially never, so this cache is a day long, not an hour.
_SECTOR_TTL = 86400.0
_sector_cache: dict[str, tuple[float, str | None]] = {}


def get_sector(symbol: str) -> str | None:
    """Yahoo's GICS sector for `symbol`, or None if unlisted/unknown."""
    now = time.time()
    cached = _sector_cache.get(symbol)
    if cached and now - cached[0] < _SECTOR_TTL:
        return cached[1]

    sector = None
    try:
        r = market._session().get(
            _URL.format(symbol=market._yahoo(symbol)),
            params={"modules": "assetProfile", "crumb": market._crumb()},
            timeout=15,
        )
        if r.status_code in (401, 403):
            market._local.crumb = None
            r = market._session().get(
                _URL.format(symbol=market._yahoo(symbol)),
                params={"modules": "assetProfile", "crumb": market._crumb()},
                timeout=15,
            )
        if r.status_code != 404:
            r.raise_for_status()
            result = r.json().get("quoteSummary", {}).get("result")
            sector = result[0]["assetProfile"].get("sector") if result else None
    except Exception:
        sector = None

    _sector_cache[symbol] = (now, sector)
    return sector
