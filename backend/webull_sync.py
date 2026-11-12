"""Webull portfolio sync — Phase 2 (official Webull OpenAPI).

Reads live positions from a Webull brokerage account via the official
OpenAPI and maps them to the same raw shape the CSV loader produces:
[{symbol, quantity, avg_cost}].

Auth uses an App Key + App Secret (HMAC-signed requests) — no email/MFA.
Get them by applying for API access at https://developer.webull.com
(Individual Application, ~1-2 business days), then generating the key pair
in the developer portal.

Config (backend/.env):
    WEBULL_APP_KEY, WEBULL_APP_SECRET   required
    WEBULL_REGION_ID                    e.g. us, hk, jp, sg, th  (default: us)
    WEBULL_ACCOUNT_ID                   optional — auto-picks first account
    WEBULL_API_ENDPOINT                 optional host override

Credentials stay server-side only, never sent to the frontend. Positions
are read-only — no orders are ever placed.
"""
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# SDK is optional — only needed when PORTFOLIO_SOURCE=webull.
try:
    from webull.core.client import ApiClient  # type: ignore
    from webull.trade.trade_client import TradeClient  # type: ignore
    from webull.data.data_client import DataClient  # type: ignore
except ImportError:  # pragma: no cover - import guard
    ApiClient = None
    TradeClient = None
    DataClient = None

# Env vars are read lazily (at call time), not at import, so main.py can
# import this module before calling load_dotenv() without losing the config.
def _env():
    return {
        "app_key": os.getenv("WEBULL_APP_KEY"),
        "app_secret": os.getenv("WEBULL_APP_SECRET"),
        "region_id": os.getenv("WEBULL_REGION_ID", "us"),
        "account_id": os.getenv("WEBULL_ACCOUNT_ID"),
        "api_endpoint": os.getenv("WEBULL_API_ENDPOINT"),
    }


class WebullError(RuntimeError):
    """Raised for any Webull config/API failure with a user-facing message."""


def configured() -> bool:
    """True when App Key + Secret are present (SDK ready to try a call)."""
    e = _env()
    return bool(ApiClient and e["app_key"] and e["app_secret"])


def _require(e):
    if ApiClient is None:
        raise WebullError(
            "webull-openapi-python-sdk not installed. Run: pip install -r requirements.txt"
        )
    if not e["app_key"] or not e["app_secret"]:
        raise WebullError(
            "Set WEBULL_APP_KEY / WEBULL_APP_SECRET in backend/.env"
        )


_LOG_DIR = Path(__file__).parent / "log"


def _configure_sdk_logger(client, filename: str) -> None:
    """Point the SDK's own logging at backend/log/ instead of the cwd.

    TradeClient/DataClient each set up a default file logger on first use
    (see their _init_logger) — but only if none is set yet. Pre-setting one
    here (same format the SDK uses) makes it skip that default and write
    into our log dir instead.
    """
    _LOG_DIR.mkdir(exist_ok=True)
    log_format = "%(thread)d %(asctime)s %(name)s %(levelname)s %(message)s"
    client.set_stream_logger(stream=sys.stdout, format_string=log_format)
    client.set_file_logger(
        path=str(_LOG_DIR / filename), log_level=logging.INFO, format_string=log_format
    )


def _api_client(log_filename: str):
    e = _env()
    _require(e)
    client = ApiClient(e["app_key"], e["app_secret"], e["region_id"])
    if e["api_endpoint"]:
        client.add_endpoint(e["region_id"], e["api_endpoint"])
    _configure_sdk_logger(client, log_filename)
    return client


def _make_client(cls, log_filename: str):
    """Build an SDK client. Its constructor does the token handshake, which
    raises SDK exceptions (429, VERIFY_FAILURE_EXCEED_LIMIT, ...) — wrap them
    so callers' `except WebullError` yields a JSON 502 instead of a bare 500."""
    try:
        return cls(_api_client(log_filename))
    except WebullError:
        raise
    except Exception as e:
        raise WebullError(
            f"Webull auth failed — check Webull authentication: approve the "
            f"login/verification on your phone in the Webull app, then retry. ({e})"
        )


def _trade_client():
    return _make_client(TradeClient, "webull_trade_sdk.log")


def _data_client():
    return _make_client(DataClient, "webull_data_sdk.log")


def _check(res, what: str):
    """Validate an SDK http response, returning its parsed JSON."""
    code = getattr(res, "status_code", None)
    if code != 200:
        body = getattr(res, "text", "") or ""
        raise WebullError(f"Webull {what} failed: HTTP {code} {body}".strip())
    return res.json()


def _resolve_account_id(tc) -> str:
    account_id = os.getenv("WEBULL_ACCOUNT_ID")
    if account_id:
        return account_id
    data = _check(tc.account_v2.get_account_list(), "account list")
    accounts = data if isinstance(data, list) else (
        data.get("data") or data.get("accounts") or []
    )
    if not accounts:
        raise WebullError("No Webull accounts returned. Check region / API access.")
    first = accounts[0]
    aid = first.get("account_id") or first.get("accountId") or first.get("id")
    if not aid:
        raise WebullError("Could not read account_id from Webull account list.")
    return aid


def _map_positions(data) -> list[dict]:
    """Map an OpenAPI positions response to {symbol, quantity, avg_cost}.

    The response nests holdings in a `holdings`/`positions` list; each entry
    may carry an `items` array of lots. We flatten and aggregate by symbol
    (sum quantity, quantity-weighted average cost) to match the CSV loader.
    """
    if isinstance(data, dict):
        groups = data.get("holdings") or data.get("positions") or data.get("data") or []
    elif isinstance(data, list):
        groups = data
    else:
        groups = []

    agg: dict[str, dict] = {}
    for g in groups:
        if not isinstance(g, dict):
            continue
        items = g.get("items") if isinstance(g.get("items"), list) else [g]
        for it in items:
            if not isinstance(it, dict):
                continue
            sym = it.get("symbol") or it.get("ticker")
            qty = it.get("quantity")
            cost = it.get("cost_price") or it.get("costPrice")
            if not sym or qty is None or cost is None:
                continue
            try:
                qty_f = float(qty)
                cost_f = float(cost)
            except (TypeError, ValueError):
                continue
            sym = str(sym).strip().upper()
            a = agg.setdefault(sym, {"symbol": sym, "quantity": 0.0, "_cost_qty": 0.0})
            a["quantity"] += qty_f
            a["_cost_qty"] += cost_f * qty_f

    raw = []
    for a in agg.values():
        qty = a["quantity"]
        avg = a["_cost_qty"] / qty if qty else 0.0
        raw.append({"symbol": a["symbol"], "quantity": qty, "avg_cost": avg})
    return raw


def get_webull_positions() -> list[dict]:
    """Return live Webull holdings as [{symbol, quantity, avg_cost}].

    Raises WebullError with an actionable message on any failure.
    """
    tc = _trade_client()
    aid = _resolve_account_id(tc)
    try:
        res = tc.account_v2.get_account_position(aid)
    except Exception as e:
        raise WebullError(f"Webull positions request errored: {e}")
    raw = _map_positions(_check(res, "positions"))
    if not raw:
        raise WebullError("Webull returned no positions.")
    return raw


def _as_list(data, *keys) -> list:
    """Pull a list out of an OpenAPI response that may be raw or wrapped."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def get_webull_watchlists() -> list[dict]:
    """Return the user's Webull watchlists as [{id, name, symbols: [...]}].

    Watchlists live in the market-data API (DataClient), separate from the
    trade API used for positions — so this can fail with a 403 if the
    account lacks market-data API access even when positions work.
    """
    if DataClient is None:
        raise WebullError(
            "webull-openapi-python-sdk not installed. Run: pip install -r requirements.txt"
        )
    dc = _data_client()
    lists = _as_list(_check(dc.watchlist.get_watchlist(), "watchlists"), "data", "watchlists")

    heads = []
    for wl in lists:
        if not isinstance(wl, dict):
            continue
        wid = wl.get("watchlist_id") or wl.get("watchlistId") or wl.get("id")
        if wid:
            heads.append((str(wid), wl.get("name") or "Watchlist"))

    def symbols_of(wid: str) -> list[str]:
        items = _as_list(
            _check(dc.watchlist.get_instruments(wid), "watchlist instruments"),
            "instruments", "data",
        )
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            sym = it.get("symbol") or it.get("ticker")
            if sym:
                out.append(str(sym).strip().upper())
        return out

    if not heads:
        return []

    # One get_instruments call per watchlist. Serially, 10 lists took ~8.7s
    # before anything rendered; fetch them together instead.
    # ponytail: 8-way pool, same as market.get_quotes. Lower it if Webull
    # starts rate-limiting.
    with ThreadPoolExecutor(max_workers=8) as pool:
        symbol_lists = list(pool.map(lambda h: symbols_of(h[0]), heads))

    return [
        {"id": wid, "name": name, "symbols": syms}
        for (wid, name), syms in zip(heads, symbol_lists)
    ]
