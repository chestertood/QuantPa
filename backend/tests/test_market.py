"""Self-check for market.get_quotes: the CNBC -> Yahoo -> chart source chain,
staleness detection, and caching. Stubs every source, so it makes no network
calls. Run: python test_market.py
"""
import time

import market


def _chart(price, closes, ts=None):
    meta = {"regularMarketPrice": price}
    if ts is not None:
        meta["regularMarketTime"] = ts
    return {"meta": meta, "indicators": {"quote": [{"close": closes}]}}


def _px(q):
    """Just the price fields, for asserting against the freshness keys too."""
    return {"price": q["price"], "prev_close": q["prev_close"]}


def _explode(symbols, _retry=True):
    """A dead quote source — forces the next step of the chain."""
    raise RuntimeError("source down")


def _quiet_sources():
    """Silence both batch sources so a test can't touch the network."""
    market._cnbc_quotes = _explode
    market._batch_quotes = _explode


class _FakeSession:
    """Stands in for the requests session so _cnbc_quotes' own parsing can be
    tested without a network call."""

    def __init__(self, payload):
        self.payload = payload

    def get(self, url, params=None, timeout=None):
        return self

    def raise_for_status(self):
        pass

    def json(self):
        return {"QuickQuoteResult": {"QuickQuote": self.payload}}


def _with_cnbc_payload(payload, fn):
    """Run fn() with _cnbc_quotes' HTTP layer stubbed, then put it back."""
    real = market._session
    market._session = lambda: _FakeSession(payload)
    try:
        return fn()
    finally:
        market._session = real


def test_batch_is_one_request_and_chart_covers_the_rest():
    market._quote_cache.clear()
    market._cnbc_quotes = _explode
    batched = []
    charted = []

    def fake_batch(symbols, _retry=True):
        batched.append(list(symbols))
        # "GHOST" is unknown to Yahoo: absent from the response, not an error.
        return {
            s: {"price": 10.0, "prev_close": 8.0} for s in symbols if s != "GHOST"
        }

    def fake_chart(symbol, rng, interval):
        charted.append(symbol)
        return _chart(11.0, [7.0, 9.0])

    market._batch_quotes = fake_batch
    market._fetch_chart = fake_chart

    out = market.get_quotes(["AAPL", "BRK B", "GHOST"])

    assert batched == [["AAPL", "BRK-B", "GHOST"]], f"one batched request, got {batched}"
    assert _px(out["BRK B"]) == {"price": 10.0, "prev_close": 8.0}, out.get("BRK B")
    assert charted == ["GHOST"], f"only the unbatched symbol hits the chart API: {charted}"
    assert _px(out["GHOST"]) == {"price": 11.0, "prev_close": 7.0}, out.get("GHOST")


def test_parallel_and_cache():
    market._quote_cache.clear()
    _quiet_sources()
    calls = []

    def fake(symbol, rng, interval):
        calls.append(symbol)
        time.sleep(0.05)  # any serial loop over 8 symbols would take >0.4s
        if symbol == "BAD":
            raise ValueError("no chart data")
        return _chart(10.0, [8.0, 9.0])

    market._fetch_chart = fake

    syms = ["A", "B", "C", "D", "E", "F", "G", "BAD"]
    start = time.time()
    out = market.get_quotes(syms)
    elapsed = time.time() - start

    assert set(out) == set(syms) - {"BAD"}, f"BAD should be omitted, got {list(out)}"
    # closes[-1] is today; prev_close must be the prior trading day, 8.0.
    assert _px(out["A"]) == {"price": 10.0, "prev_close": 8.0}, out["A"]
    assert elapsed < 0.3, f"fetches ran serially: {elapsed:.2f}s"
    assert len(calls) == 8, calls

    # Second call inside the TTL refetches nothing but BAD — failures aren't
    # cached, so a symbol that errored retries rather than staying dead for 60s.
    calls.clear()
    again = market.get_quotes(syms)
    assert calls == ["BAD"], f"expected only BAD refetched, got {calls}"
    assert again["A"] == out["A"]


def test_share_class_symbol_is_translated_for_yahoo():
    market._quote_cache.clear()
    _quiet_sources()
    seen = []

    def fake(symbol, rng, interval):
        seen.append(symbol)
        return _chart(10.0, [8.0, 9.0])

    market._fetch_chart = fake
    assert "BRK B" in market.get_quotes(["BRK B"]), "share-class symbol must price"
    assert seen == ["BRK-B"], f"Yahoo needs a dash, requested {seen}"

    seen.clear()
    market.get_history("BRK B")
    assert seen == ["BRK-B"], f"get_history must translate too, requested {seen}"


def test_prev_close_falls_back_to_prior_close():
    market._quote_cache.clear()
    _quiet_sources()
    # previousClose present but null — the case that inflated day change.
    market._fetch_chart = lambda symbol, rng, interval: {
        "meta": {"regularMarketPrice": 10.0, "previousClose": None},
        "indicators": {"quote": [{"close": [7.0, 8.0, 9.0]}]},
    }
    assert market.get_quotes(["X"])["X"]["prev_close"] == 8.0


def test_frozen_feed_during_open_market_is_flagged_stale():
    """The 2026-07-24 case: Yahoo served MU's 10:35 ET price for 2.5h with
    marketState REGULAR, so -6.70% looked live while it was really -5.7%."""
    frozen = time.time() - 9000  # 2.5h ago
    quotes = {
        "FROZEN": {"price": 923.86, "prev_close": 990.21, "ts": frozen, "state": "REGULAR"},
        "LIVE": {"price": 933.90, "prev_close": 990.21, "ts": time.time(), "state": "REGULAR"},
        # Same 2.5h age, but the market is shut — that price is correct, not stale.
        "CLOSED": {"price": 923.86, "prev_close": 990.21, "ts": frozen, "state": "CLOSED"},
    }

    market._quote_cache.clear()
    market._batch_quotes = _explode
    market._cnbc_quotes = lambda symbols: {s: quotes[s] for s in symbols}
    out = market.get_quotes(list(quotes))

    assert out["FROZEN"]["stale"] is True, "a frozen open-market quote must flag"
    assert out["FROZEN"]["age_s"] > 8000, out["FROZEN"]["age_s"]
    assert out["LIVE"]["stale"] is False, out["LIVE"]
    assert out["CLOSED"]["stale"] is False, "closed markets are legitimately old"

    # A cache hit must report the print's real age, not the cache's age — the
    # whole point is that the number ages while we keep serving it.
    time.sleep(0.05)
    again = market.get_quotes(["LIVE"])
    assert again["LIVE"]["age_s"] is not None


def test_cnbc_is_primary_and_yahoo_only_sees_what_it_missed():
    """CNBC first: on 2026-07-24 Yahoo froze for hours while CNBC stayed live.
    Yahoo must still catch the symbols CNBC doesn't carry."""
    market._quote_cache.clear()
    asked_cnbc = []
    asked_yahoo = []

    def fake_cnbc(symbols):
        asked_cnbc.append(list(symbols))
        return {
            s: {"price": 933.90, "prev_close": 990.21, "ts": time.time(), "state": "REGULAR"}
            for s in symbols
            if s != "ODD"
        }

    def fake_yahoo(symbols, _retry=True):
        asked_yahoo.append(list(symbols))
        return {
            s: {"price": 5.0, "prev_close": 4.0, "ts": time.time(), "state": "REGULAR"}
            for s in symbols
        }

    market._cnbc_quotes = fake_cnbc
    market._batch_quotes = fake_yahoo
    out = market.get_quotes(["MU", "BRK B", "ODD"])

    assert asked_cnbc == [["MU", "BRK.B", "ODD"]], f"CNBC spelling/first: {asked_cnbc}"
    assert asked_yahoo == [["ODD"]], f"Yahoo only gets the leftovers: {asked_yahoo}"
    assert out["BRK B"]["price"] == 933.90, out["BRK B"]
    assert out["ODD"]["price"] == 5.0, out["ODD"]


def test_cnbc_outage_falls_through_to_yahoo():
    market._quote_cache.clear()
    market._cnbc_quotes = _explode
    market._batch_quotes = lambda symbols, _retry=True: {
        s: {"price": 7.0, "prev_close": 6.0, "ts": time.time(), "state": "REGULAR"}
        for s in symbols
    }
    assert market.get_quotes(["MU"])["MU"]["price"] == 7.0


def test_chart_fallback_never_claims_stale():
    """Chart meta carries no marketState, so age is reported but staleness
    can't be asserted — guessing would flag every symbol overnight."""
    market._quote_cache.clear()
    _quiet_sources()
    market._fetch_chart = lambda symbol, rng, interval: _chart(
        10.0, [8.0, 9.0], ts=time.time() - 9000
    )
    q = market.get_quotes(["X"])["X"]
    assert q["stale"] is False, q
    assert q["age_s"] > 8000, q


def test_cnbc_prev_close_survives_the_overnight_rollover():
    """Once a session closes, CNBC rolls previous_day_closing forward so it
    equals `last` — both become the same close. Trusting that field makes the
    day change read 0.00% for every symbol from the closing bell until the next
    open. `change` still carries the real move, so the prior close is
    last - change (829.50 - 6.47 = 823.03, which is what Yahoo reports too)."""
    payload = {
        "symbol": "MU",
        "last": "829.50",
        "previous_day_closing": "829.50",  # rolled forward — not the prior session
        "change": "6.47",
        "curmktstatus": "PRE_MKT",
        "last_time_msec": "1785835733779",
    }
    q = _with_cnbc_payload(payload, lambda: market._cnbc_quotes(["MU"]))["MU"]
    assert q["price"] == 829.50, q
    assert q["prev_close"] == 823.03, q


def test_cnbc_prev_close_agrees_with_previous_day_closing_while_open():
    """During the regular session the two agree, so the derivation must not
    move the number: last - change == previous_day_closing."""
    payload = {
        "symbol": "MU",
        "last": "835.00",
        "previous_day_closing": "829.50",
        "change": "5.50",
        "curmktstatus": "REG_MKT",
        "last_time_msec": "1785835733779",
    }
    q = _with_cnbc_payload(payload, lambda: market._cnbc_quotes(["MU"]))["MU"]
    assert q["prev_close"] == 829.50, q
    assert q["state"] == "REGULAR", q


def test_cnbc_missing_change_falls_back_instead_of_guessing():
    """CNBC sends "UNCH" or nothing for change on thin names. Without a usable
    change there is nothing to derive from, so previous_day_closing is still the
    best available answer — and price is the last resort."""
    unch = {
        "symbol": "AAA",
        "last": "10.00",
        "previous_day_closing": "9.50",
        "change": "UNCH",
        "curmktstatus": "REG_MKT",
    }
    q = _with_cnbc_payload(unch, lambda: market._cnbc_quotes(["AAA"]))["AAA"]
    assert q["prev_close"] == 9.50, q

    bare = {"symbol": "BBB", "last": "10.00", "curmktstatus": "REG_MKT"}
    q = _with_cnbc_payload(bare, lambda: market._cnbc_quotes(["BBB"]))["BBB"]
    assert q["prev_close"] == 10.00, q


if __name__ == "__main__":
    test_cnbc_prev_close_survives_the_overnight_rollover()
    test_cnbc_prev_close_agrees_with_previous_day_closing_while_open()
    test_cnbc_missing_change_falls_back_instead_of_guessing()
    test_batch_is_one_request_and_chart_covers_the_rest()
    test_frozen_feed_during_open_market_is_flagged_stale()
    test_cnbc_is_primary_and_yahoo_only_sees_what_it_missed()
    test_cnbc_outage_falls_through_to_yahoo()
    test_chart_fallback_never_claims_stale()
    test_parallel_and_cache()
    test_share_class_symbol_is_translated_for_yahoo()
    test_prev_close_falls_back_to_prior_close()
    print("ok")
