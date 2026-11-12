"""Dump the statement deposit/withdrawal history to one CSV.

The dashboard reads the same data live over /api/cashflow; this is for when you
want the records in a spreadsheet. Parsing lives in cashflow.py.

    .venv/Scripts/python scripts/export_cashflow.py
"""
import sys
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import cashflow  # noqa: E402  (needs backend/ on sys.path first)

OUT = BACKEND / "deposit_withdrawal_all.csv"

if __name__ == "__main__":
    data = cashflow.load_cashflow()
    df = pd.DataFrame(data["records"], columns=["date", "type", "amount", "currency", "remarks"])
    df.to_csv(OUT, index=False)
    print(f"Saved {len(df)} records -> {OUT}")
