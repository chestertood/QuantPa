"""Made-up data for DEMO=1 — screenshots and GIFs without real account numbers.

Positions come from sample_portfolio.csv (live Yahoo prices, fake holdings);
everything that would otherwise read the real statement PDFs or Webull comes
from here. Same response shapes as the real loaders.
"""

import cashflow

# (date, type, amount THB, remarks)
_CASH = [
    ("2026-01-05", "deposit", 50000, "Bank transfer"),
    ("2026-01-20", "deposit", 20000, "Bank transfer"),
    ("2026-02-03", "deposit", 30000, "Bank transfer"),
    ("2026-02-25", "withdrawal", 8000, "Withdraw to bank"),
    ("2026-03-10", "deposit", 25000, "Bank transfer"),
    ("2026-04-02", "deposit", 40000, "Bank transfer"),
    ("2026-04-28", "withdrawal", 15000, "Withdraw to bank"),
    ("2026-05-15", "deposit", 20000, "Bank transfer"),
    ("2026-06-06", "deposit", 35000, "Bank transfer"),
    ("2026-06-30", "withdrawal", 10000, "Withdraw to bank"),
]


def load_cashflow() -> dict:
    records = [
        {"date": d, "type": t, "amount": float(a), "currency": "THB", "remarks": r}
        for d, t, a, r in sorted(_CASH, reverse=True)
    ]
    dep = sum(r["amount"] for r in records if r["type"] == "deposit")
    wd = sum(r["amount"] for r in records if r["type"] == "withdrawal")
    return {
        "records": records,
        "monthly": cashflow._monthly(records),
        "summary": {
            "total_deposit": dep, "total_withdrawal": wd, "net": dep - wd,
            "record_count": len(records), "currency": "THB",
        },
    }


def load_tax_summary() -> dict:
    trades = [
        {"symbol": "NVDA", "date": "2026-06-12", "quantity": 4.0, "pl": 182.40},
        {"symbol": "TSLA", "date": "2026-05-20", "quantity": 2.0, "pl": -64.10},
        {"symbol": "AAPL", "date": "2026-04-08", "quantity": 5.0, "pl": 41.75},
        {"symbol": "MSFT", "date": "2026-02-17", "quantity": 1.0, "pl": 23.30},
    ]
    return {
        "yearly": [{
            "year": "2026",
            "realized_pl_usd": round(sum(t["pl"] for t in trades), 2),
            "dividend_thb": 1250.00, "interest_thb": 310.50, "interest_wht_thb": 46.58,
            "fee_thb": 420.00, "withdrawn_to_thailand_thb": 33000.00,
        }],
        "realized_trades": trades,
        "note": "DEMO — ตัวเลขสมมติ ไม่ใช่ข้อมูลจริง",
    }


def get_watchlists() -> list[dict]:
    return [
        {"id": "demo-tech", "name": "Tech", "symbols": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN"]},
        {"id": "demo-etf", "name": "ETF", "symbols": ["SPY", "QQQ", "VOO", "SCHD"]},
    ]
