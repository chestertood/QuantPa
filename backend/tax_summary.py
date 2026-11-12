"""Raw figures for a Thai accountant, pulled from the Webull statement PDFs.

This module does NOT compute Thai tax owed. Personal income tax on foreign-
sourced income depends on your total income, deductions, and residency rules
that live entirely outside a brokerage statement (Revenue Code section 41,
amended by Por.161/2566) — a portfolio app cannot know any of that. What it
CAN do reliably is turn statement PDFs into the numbers an accountant asks
for: realized trading gains, dividends, interest, fees, and cash repatriated
to Thailand.
"""
import glob
import os
from collections import defaultdict, deque
from datetime import datetime

import pdfplumber

from cashflow import STATEMENT_DIR, load_cashflow

_TRADE_HEADER = [
    "Symbol & Name", "Trade Date", "Time", "Settlement Date", "Buy/Sell",
    "Quantity", "Traded Price", "Gross Amount", "Net Amount",
    "Comm/Fee/Tax", "VAT", "Exchange", "Remarks", "Status",
]
_CASH_SUMMARY_ROWS = {"Dividends", "Interest", "Interest WHT", "Comm/Fee/Tax", "VAT"}


def _num(raw):
    return float(raw.replace(",", "").strip())


def _symbol(cell):
    """'CLS  \nCELESTICA INC' -> 'CLS'. The ticker is always the first line."""
    return cell.split("\n")[0].strip()


def _trade_rows(pdf_path):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if table[0] == _TRADE_HEADER:
                    rows.extend(dict(zip(_TRADE_HEADER, r)) for r in table[1:])
    return rows


def _cash_summary_row(pdf_path):
    """Dividends / Interest / Interest WHT / Comm/Fee/Tax / VAT, THB-converted
    (the statement's Total(THB) column), for one month."""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if table[0][0] == "" and "HKD" in table[0]:
                    return {r[0]: _num(r[-1]) for r in table[1:] if r[0] in _CASH_SUMMARY_ROWS}
    return {}


def _realized_pl_by_symbol(trades):
    """FIFO-match buys against sells, per symbol, in trade-date order.

    Net Amount already has commission/VAT baked in (it's what you actually
    paid or received), so gain = matched sell proceeds - matched buy cost,
    scaled to the quantity being matched. Unmatched buy quantity is an open
    position — not realized, and deliberately excluded.
    """
    for t in trades:
        t["_symbol"] = _symbol(t["Symbol & Name"])
        t["_date"] = datetime.strptime(t["Trade Date"].split(",")[0].strip(), "%d/%m/%Y")
        t["_qty"] = float(t["Quantity"])  # fractional shares happen (e.g. DRIP)
        t["_net"] = _num(t["Net Amount"])

    by_symbol = defaultdict(list)
    for t in sorted(trades, key=lambda t: t["_date"]):
        by_symbol[t["_symbol"]].append(t)

    realized = []  # [{symbol, date (sell), quantity, pl}]
    for symbol, lots in by_symbol.items():
        buys = deque()  # (remaining_qty, cost_per_share)
        for t in lots:
            per_share = t["_net"] / t["_qty"]
            if t["Buy/Sell"] == "BUY":
                buys.append([t["_qty"], per_share])
            else:
                remaining = t["_qty"]
                proceeds_per_share = per_share
                pl = 0.0
                matched = 0.0
                while remaining > 0 and buys:
                    lot_qty, lot_cost = buys[0]
                    take = min(remaining, lot_qty)
                    pl += take * (proceeds_per_share - lot_cost)
                    matched += take
                    remaining -= take
                    lot_qty -= take
                    if lot_qty == 0:
                        buys.popleft()
                    else:
                        buys[0][0] = lot_qty
                if matched:
                    realized.append({
                        "symbol": symbol,
                        "date": t["_date"].strftime("%Y-%m-%d"),
                        "quantity": matched,
                        "pl": round(pl, 2),
                    })
                # `remaining` > 0 here would mean a sell with no matching buy in
                # this statement window (e.g. a position opened before the
                # earliest PDF on hand) — left unmatched rather than guessed at.
    return realized


def load_tax_summary(statement_dir=STATEMENT_DIR):
    pdf_files = sorted(glob.glob(os.path.join(statement_dir, "*.pdf")))

    all_trades = []
    cash_by_year = defaultdict(lambda: {"dividend": 0.0, "interest": 0.0, "interest_wht": 0.0, "fee": 0.0, "vat": 0.0})
    for pdf_file in pdf_files:
        month = os.path.splitext(os.path.basename(pdf_file))[0]  # "2026-01"
        year = month[:4]
        all_trades.extend(_trade_rows(pdf_file))

        row = _cash_summary_row(pdf_file)
        cash_by_year[year]["dividend"] += row.get("Dividends", 0.0)
        cash_by_year[year]["interest"] += row.get("Interest", 0.0)
        cash_by_year[year]["interest_wht"] += row.get("Interest WHT", 0.0)
        cash_by_year[year]["fee"] += abs(row.get("Comm/Fee/Tax", 0.0))
        cash_by_year[year]["vat"] += abs(row.get("VAT", 0.0))

    realized = _realized_pl_by_symbol(all_trades)
    realized_by_year = defaultdict(float)
    for r in realized:
        realized_by_year[r["date"][:4]] += r["pl"]

    withdrawals_by_year = defaultdict(float)
    for rec in load_cashflow(statement_dir)["records"]:
        if rec["type"] == "withdrawal":
            withdrawals_by_year[rec["date"][:4]] += rec["amount"]

    years = sorted(set(cash_by_year) | set(realized_by_year) | set(withdrawals_by_year))
    yearly = []
    for y in years:
        c = cash_by_year[y]
        yearly.append({
            "year": y,
            "realized_pl_usd": round(realized_by_year.get(y, 0.0), 2),
            "dividend_thb": round(c["dividend"], 2),
            "interest_thb": round(c["interest"], 2),
            "interest_wht_thb": round(c["interest_wht"], 2),
            "fee_thb": round(c["fee"] + c["vat"], 2),
            "withdrawn_to_thailand_thb": round(withdrawals_by_year.get(y, 0.0), 2),
        })

    return {
        "yearly": yearly,
        "realized_trades": sorted(realized, key=lambda r: r["date"], reverse=True),
        "note": (
            "ตัวเลขดิบจากใบแจ้งยอด ไม่ใช่การคำนวณภาษี — ภาษีเงินได้จริงขึ้นกับรายได้รวม "
            "ค่าลดหย่อน และกฎเงินได้ต่างประเทศที่ใช้บังคับ ปรึกษานักบัญชีก่อนยื่นจริง"
        ),
    }
