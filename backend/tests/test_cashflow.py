"""Checks against the real statement PDFs in deposit_history/.

Expected figures come from the printed statements themselves (the Total(THB)
row of each month's withdrawal table, and the deposit rows above it).
"""
import pytest

import cashflow

data = cashflow.load_cashflow()
records = data["records"]
monthly = {m["month"]: m for m in data["monthly"]}


def test_parses_every_record():
    assert len(records) == 40


def test_records_are_newest_first():
    assert records == sorted(records, key=lambda r: r["date"], reverse=True)


def test_amounts_are_unsigned():
    assert all(r["amount"] > 0 for r in records)


def test_dates_are_iso():
    assert all(len(r["date"]) == 10 and r["date"][4] == "-" for r in records)


def test_total_row_is_not_a_record():
    """Each month's withdrawal table ends in a Total(THB) row — a summary, not a
    transaction. Counting it would double every month's outflow."""
    assert not any(r["remarks"] == "Total(THB)" for r in records)
    assert monthly["2026-01"]["withdrawal"] == pytest.approx(12000.01)


@pytest.mark.parametrize("month,deposit,withdrawal", [
    ("2026-01", 150000.00, 12000.01),
    ("2026-02", 0.0, 10700.00),
    ("2026-03", 0.0, 25226.05),
    ("2026-04", 0.0, 13531.48),
    ("2026-05", 0.0, 5253.45),
    ("2026-06", 90000.00, 39656.15),
])
def test_monthly_totals(month, deposit, withdrawal):
    m = monthly.get(month, {"deposit": 0.0, "withdrawal": 0.0})
    assert m["deposit"] == pytest.approx(deposit)
    assert m["withdrawal"] == pytest.approx(withdrawal)


def test_months_are_chronological():
    assert [m["month"] for m in data["monthly"]] == sorted(monthly)


def test_summary_matches_records():
    s = data["summary"]
    assert s["total_deposit"] == pytest.approx(240000.00)
    assert s["total_withdrawal"] == pytest.approx(106367.14)
    assert s["net"] == pytest.approx(s["total_deposit"] - s["total_withdrawal"])
    assert s["record_count"] == len(records)


def test_fingerprint_changes_with_folder(tmp_path):
    assert cashflow.statement_fingerprint(str(tmp_path)) == (0, 0.0)
    before = cashflow.statement_fingerprint()
    assert before[0] == 6 and before[1] > 0
