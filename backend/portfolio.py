"""Load portfolio from CSV and enrich with live market data."""
import os
import pandas as pd

from market import get_quotes

REQUIRED_COLS = {"symbol", "quantity", "avg_cost"}


def load_positions_csv(csv_path: str) -> list[dict]:
    """Read the raw portfolio CSV. Returns list of {symbol, quantity, avg_cost}."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Portfolio CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    missing = REQUIRED_COLS - set(c.lower() for c in df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}. Need {REQUIRED_COLS}")

    df.columns = [c.lower() for c in df.columns]
    df["symbol"] = df["symbol"].str.strip().str.upper()
    df = df.groupby("symbol", as_index=False).agg(
        quantity=("quantity", "sum"),
        avg_cost=("avg_cost", "mean"),  # simple mean; refine if you track lots
    )
    return df.to_dict("records")


def build_portfolio(csv_path: str) -> dict:
    """Enrich raw CSV positions with quotes and compute P/L + weights."""
    return build_portfolio_from_positions(load_positions_csv(csv_path))


def build_portfolio_from_positions(raw: list[dict]) -> dict:
    """Enrich raw positions (any source) with quotes and compute P/L + weights.

    `raw` is a list of {symbol, quantity, avg_cost} — same shape the CSV
    loader and the Webull sync both produce.
    """
    symbols = [r["symbol"] for r in raw]
    quotes = get_quotes(symbols)

    positions = []
    total_mv = 0.0
    for r in raw:
        sym = r["symbol"]
        q = quotes.get(sym)
        price = q["price"] if q else r["avg_cost"]  # fallback: assume flat if no quote
        prev = q["prev_close"] if q else price
        qty = float(r["quantity"])
        avg = float(r["avg_cost"])

        market_value = price * qty
        cost_basis = avg * qty
        unrealized = market_value - cost_basis
        day_change = (price - prev) * qty
        total_mv += market_value

        positions.append({
            "symbol": sym,
            "quantity": qty,
            "avg_cost": round(avg, 2),
            "current_price": round(price, 2),
            "prev_close": round(prev, 2),
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_pl": round(unrealized, 2),
            "unrealized_pl_pct": round(unrealized / cost_basis * 100, 2) if cost_basis else 0.0,
            "day_change": round(day_change, 2),
            "day_change_pct": round((price - prev) / prev * 100, 2) if prev else 0.0,
            "weight": 0.0,  # filled below once total known
            # Stale means "don't trust this price": either no quote at all
            # (falling back to avg_cost) or a frozen feed during open hours.
            "_stale": q is None or q["stale"],
            "quote_age_s": q["age_s"] if q else None,
        })

    # weights
    for p in positions:
        p["weight"] = round(p["market_value"] / total_mv * 100, 2) if total_mv else 0.0

    total_cost = sum(p["cost_basis"] for p in positions)
    total_unreal = sum(p["unrealized_pl"] for p in positions)
    total_day = sum(p["day_change"] for p in positions)
    prev_total = total_mv - total_day

    summary = {
        "total_market_value": round(total_mv, 2),
        "total_cost_basis": round(total_cost, 2),
        "total_unrealized_pl": round(total_unreal, 2),
        "total_unrealized_pl_pct": round(total_unreal / total_cost * 100, 2) if total_cost else 0.0,
        "total_day_change": round(total_day, 2),
        "total_day_change_pct": round(total_day / prev_total * 100, 2) if prev_total else 0.0,
        "position_count": len(positions),
    }
    return {"summary": summary, "positions": positions}
