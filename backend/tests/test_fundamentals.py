"""Tests the payload -> metric-groups transform against captured Yahoo
responses, so they don't depend on the network or on live market values.

testdata/quotesummary_AAPL.json  — a symbol Yahoo covers fully
testdata/quotesummary_SPCX.json  — a symbol with real gaps (no beta, no ROE)
"""
import json
import os

import pytest

import fundamentals

HERE = os.path.dirname(__file__)


def load(name):
    with open(os.path.join(HERE, "testdata", f"quotesummary_{name}.json"), encoding="utf-8") as f:
        return json.load(f)


aapl = fundamentals.shape(load("AAPL"))
spcx = fundamentals.shape(load("SPCX"))


def test_all_four_groups_present():
    assert set(aapl) == {"valuation", "profitability", "health", "trading", "source"}


def test_unwraps_yahoo_raw_values():
    """Yahoo sends {"raw": 4537070911488, "fmt": "4.54T"} — the raw number is
    what must come through, not the dict or the pre-formatted string."""
    assert isinstance(aapl["valuation"]["market_cap"], (int, float))
    assert aapl["valuation"]["market_cap"] > 1e12


def test_pe_present_for_covered_symbol():
    assert aapl["valuation"]["pe_trailing"] > 0
    assert aapl["valuation"]["pe_forward"] > 0


def test_margins_stay_fractions():
    """Conversion to percent belongs in the UI, in one place — the API must not
    pre-multiply or the frontend would double it."""
    assert 0 < aapl["profitability"]["profit_margin"] < 1
    assert 0 < aapl["profitability"]["gross_margin"] < 1


def test_dropped_metrics_absent():
    """P/B and price-to-sales were cut: P/B because Yahoo's value is unreliable
    (BRK.B reported 0.001), price-to-sales because it came back null for every
    symbol tested."""
    flat = {k for group in ("valuation", "profitability", "health", "trading")
            for k in aapl[group]}
    assert not any("book" in k or "sales" in k for k in flat)


def test_missing_fields_are_none_not_invented():
    """SPCX genuinely has no beta or ROE in Yahoo's data. Those must surface as
    None so the UI can render "—", never as 0 or a derived stand-in."""
    assert spcx["trading"]["beta"] is None
    assert spcx["profitability"]["roe"] is None


def test_partial_symbol_still_returns_all_groups():
    assert set(spcx) == set(aapl)
    assert spcx["valuation"]["market_cap"] is not None


def test_source_is_attributed():
    assert aapl["source"] == "Yahoo Finance"


def test_empty_payload_returns_none():
    assert fundamentals.shape({"quoteSummary": {"result": None}}) is None
    assert fundamentals.shape({}) is None


@pytest.mark.parametrize("group,key", [
    ("valuation", "enterprise_value"),
    ("profitability", "revenue_growth"),
    ("health", "debt_to_equity"),
    ("health", "free_cashflow"),
    ("trading", "week52_low"),
    ("trading", "week52_high"),
    ("trading", "target_mean"),
    ("trading", "recommendation"),
])
def test_expected_metric_is_populated_for_aapl(group, key):
    assert aapl[group][key] is not None
