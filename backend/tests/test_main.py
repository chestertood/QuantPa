"""Self-check for main's Webull positions cache — the thing that lets the
frontend poll every 10s without one Webull round-trip per poll.
Stubs the sync, so it makes no network calls. Run: python test_main.py
"""
from fastapi.testclient import TestClient

import main
import webull_sync


def test_positions_cached_per_bucket():
    main._positions_cached.cache_clear()
    calls = []

    def fake():
        calls.append(1)
        return [{"symbol": "AAPL", "quantity": 1.0, "avg_cost": 100.0}]

    webull_sync.get_webull_positions = fake

    main._positions_cached(1)
    main._positions_cached(1)
    assert len(calls) == 1, f"same bucket must reuse the cache, got {len(calls)} calls"

    main._positions_cached(2)
    assert len(calls) == 2, "a new TTL bucket must re-sync"


def test_failed_sync_is_not_cached():
    main._positions_cached.cache_clear()
    calls = []

    def boom():
        calls.append(1)
        raise webull_sync.WebullError("down")

    webull_sync.get_webull_positions = boom

    for _ in range(2):
        try:
            main._positions_cached(1)
        except webull_sync.WebullError:
            pass
    assert len(calls) == 2, "an error must retry next request, not stick for a whole TTL"


client = TestClient(main.app)


def test_backtest_rejects_a_bad_symbol():
    """Symbols reach an outbound URL, so anything outside [A-Za-z0-9.- ] is
    refused before a request is ever built."""
    r = client.post("/api/backtest", json={"symbols": ["AA;rm -rf"], "benchmark": "SPY"})
    assert r.status_code == 400, (r.status_code, r.text)


def test_backtest_rejects_an_unknown_rule():
    r = client.post("/api/backtest", json={"symbols": ["AAA"], "rule": "wishful"})
    assert r.status_code == 422, (r.status_code, r.text)


def test_backtest_caps_the_symbol_count():
    r = client.post("/api/backtest", json={"symbols": [f"S{i}" for i in range(25)]})
    assert r.status_code == 422, (r.status_code, r.text)


if __name__ == "__main__":
    test_positions_cached_per_bucket()
    test_failed_sync_is_not_cached()
    test_backtest_rejects_a_bad_symbol()
    test_backtest_rejects_an_unknown_rule()
    test_backtest_caps_the_symbol_count()
    print("ok")
