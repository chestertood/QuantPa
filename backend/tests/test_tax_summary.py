"""Checks against the real statement PDFs — figures hand-verified from the
printed statement tables (see conversation history / PDF pages themselves).
"""
import pytest

import tax_summary

data = tax_summary.load_tax_summary()
yearly = {y["year"]: y for y in data["yearly"]}


def test_only_year_present():
    assert list(yearly) == ["2026"]


def test_realized_pl_matches_hand_fifo():
    """Jan trades hand-matched FIFO: CLS +175.99, EOSE -276.48, STX +601.62,
    OPEN +35.13, ONDS +406.69, SOFI +50.27, RIO +146.65 = 1139.87. Checked
    against January's slice specifically — the yearly total also includes
    Feb-Jun round-trips and won't match this on its own."""
    jan_pl = sum(r["pl"] for r in data["realized_trades"] if r["date"].startswith("2026-01"))
    assert jan_pl == pytest.approx(1139.87)


def test_open_positions_are_not_realized_within_the_holding_month():
    """January's Portfolio Summary lists SLVR (64 sh) and CLS (1 sh, bought
    01/28) as still-open positions as of end of January — neither may show up
    as a realized (matched) trade dated in January. They're both sold the
    following month (SLVR on 02/02), which is fine and expected."""
    jan_realized = [r for r in data["realized_trades"] if r["date"].startswith("2026-01")]
    assert not any(r["symbol"] == "SLVR" for r in jan_realized)
    assert not any(r["symbol"] == "CLS" and r["quantity"] == 1 for r in jan_realized)


def test_dividends_seen_in_april():
    assert yearly["2026"]["dividend_thb"] == pytest.approx(235.11)


def test_interest_and_wht_accumulate_across_months():
    # Feb 33.23/-4.97, Mar 4.59/-0.66, Apr 6.55/-0.98, May 28.93/-4.23
    assert yearly["2026"]["interest_thb"] == pytest.approx(33.23 + 4.59 + 6.55 + 28.93)
    assert yearly["2026"]["interest_wht_thb"] == pytest.approx(-(4.97 + 0.66 + 0.98 + 4.23))


def test_withdrawn_matches_cashflow_total():
    import cashflow
    total = sum(r["amount"] for r in cashflow.load_cashflow()["records"] if r["type"] == "withdrawal")
    assert yearly["2026"]["withdrawn_to_thailand_thb"] == pytest.approx(total)


def test_fee_total_is_positive():
    assert yearly["2026"]["fee_thb"] > 0


def test_realized_trades_sorted_newest_first():
    dates = [r["date"] for r in data["realized_trades"]]
    assert dates == sorted(dates, reverse=True)


def test_note_present():
    assert "ไม่ใช่การคำนวณภาษี" in data["note"]
