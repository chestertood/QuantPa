"""Deposit / withdrawal history, parsed out of Webull monthly statement PDFs.

The statements land in deposit_history/ as one PDF per month. Each has a
"DEPOSIT & WITHDRAWAL RECORDS" section holding two tables; everything else in
the PDF (trades, portfolio, FX) is ignored here.
"""
import glob
import os
from datetime import datetime

import pdfplumber

STATEMENT_DIR = os.path.join(os.path.dirname(__file__), "deposit_history")

# Header rows identify the two tables we want. Matching on the header rather
# than a page/table index keeps this working when a month has no deposits (the
# table is absent entirely) or the layout shifts by a page.
_DEPOSIT_HEADER = ["Date", "Currency", "Remarks", "Amount"]
_WITHDRAWAL_HEADER = ["Date", "Bank Name", "Bank Account No.", "Currency", "Remarks", "Amount"]


def extract_deposit_withdrawal(pdf_path):
    """Return (deposit_rows, withdrawal_rows) as lists of dicts, header-keyed."""
    deposits, withdrawals = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                header = table[0]
                if header == _DEPOSIT_HEADER:
                    deposits = [dict(zip(header, r)) for r in table[1:]]
                elif header == _WITHDRAWAL_HEADER:
                    withdrawals = [dict(zip(header, r)) for r in table[1:]]
    return deposits, withdrawals


def _parse_amount(raw):
    """'-1,000.00' -> 1000.0. Sign is carried by the record's type, not here."""
    return abs(float(raw.replace(",", "").strip()))


def _parse_date(raw):
    """'19/01/2026' -> '2026-01-19', so records sort lexically."""
    return datetime.strptime(raw.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")


def _is_data_row(row):
    """Skip the trailing 'Total(THB)' summary row and any blank filler."""
    date = (row.get("Date") or "").strip()
    return bool(date) and date != "Total(THB)" and (row.get("Amount") or "").strip()


def _records(pdf_path):
    deposits, withdrawals = extract_deposit_withdrawal(pdf_path)
    out = []
    for kind, rows in (("deposit", deposits), ("withdrawal", withdrawals)):
        for row in rows:
            if not _is_data_row(row):
                continue
            out.append({
                "date": _parse_date(row["Date"]),
                "type": kind,
                "amount": _parse_amount(row["Amount"]),
                "currency": (row.get("Currency") or "").strip() or "THB",
                "remarks": (row.get("Remarks") or "").strip(),
            })
    return out


def _monthly(records):
    """Per-month deposit / withdrawal totals, oldest first — the chart's X axis.

    Months come from the transaction date, not the filename: a statement can
    carry a record dated in a neighbouring month, and it belongs to the month it
    happened in.
    """
    buckets = {}
    for r in records:
        b = buckets.setdefault(r["date"][:7], {"month": r["date"][:7], "deposit": 0.0, "withdrawal": 0.0})
        b[r["type"]] += r["amount"]
    for b in buckets.values():
        b["net"] = round(b["deposit"] - b["withdrawal"], 2)
        b["deposit"] = round(b["deposit"], 2)
        b["withdrawal"] = round(b["withdrawal"], 2)
    return [buckets[m] for m in sorted(buckets)]


def load_cashflow(statement_dir=STATEMENT_DIR):
    """Parse every statement PDF in `statement_dir` into records + aggregates.

    Returns {"records": [...newest first...], "monthly": [...], "summary": {...}}.
    """
    records = []
    for pdf_file in sorted(glob.glob(os.path.join(statement_dir, "*.pdf"))):
        records.extend(_records(pdf_file))

    records.sort(key=lambda r: r["date"], reverse=True)
    monthly = _monthly(records)

    total_dep = round(sum(r["amount"] for r in records if r["type"] == "deposit"), 2)
    total_wd = round(sum(r["amount"] for r in records if r["type"] == "withdrawal"), 2)

    return {
        "records": records,
        "monthly": monthly,
        "summary": {
            "total_deposit": total_dep,
            "total_withdrawal": total_wd,
            "net": round(total_dep - total_wd, 2),
            "record_count": len(records),
            "currency": "THB",
        },
    }


def statement_fingerprint(statement_dir=STATEMENT_DIR):
    """Cheap identity for the PDF folder: (file count, newest mtime).

    Parsing all six statements costs ~3.7s, far too slow to redo per request,
    but the answer only changes when a PDF is added or replaced. Caching on this
    means dropping in next month's statement shows up on the next refresh with
    no manual step, while an unchanged folder never re-parses.
    """
    files = glob.glob(os.path.join(statement_dir, "*.pdf"))
    newest = max((os.path.getmtime(f) for f in files), default=0.0)
    return len(files), newest
