"""Backtest engine — an equal-weight basket with a selectable timing rule,
scored against buy-and-hold benchmarks.

Deliberately reads *adjusted* close, unlike market.get_history(), which returns
raw close rounded to 2dp for display. Raw close turns a 2:1 split into a -50%
day and drops dividends entirely; neither is survivable in a backtest.
"""
from functools import lru_cache

import pandas as pd

import market

TRADING_DAYS = 252

# Selected in 2026, which is exactly the survivorship bias named in the caveats:
# the SaaS names that died are not here, so results are biased upward.
DEFAULT_BASKET = ("CRM", "NOW", "ADBE", "SNOW", "DDOG", "TEAM", "WDAY", "ZS", "HUBS", "MDB")


def _adj_closes(symbol: str, years: int) -> pd.Series:
    """Unrounded adjusted close for one symbol, indexed by date."""
    res = market._fetch_chart(market._yahoo(symbol), rng=f"{years}y", interval="1d")
    ind = res["indicators"]
    blocks = ind.get("adjclose") or []
    values = blocks[0].get("adjclose") if blocks else None
    if not values:
        # Some listings come back without an adjclose block. Raw close is wrong
        # across splits, so say so rather than silently backtesting bad data.
        raise ValueError(f"no adjusted close for {symbol}")
    idx = pd.to_datetime(res.get("timestamp", []), unit="s").normalize()
    s = pd.Series(values, index=idx, name=symbol, dtype="float64")
    return s[s.notna()]


@lru_cache(maxsize=8)
def _panel_cached(symbols: tuple[str, ...], years: int) -> pd.DataFrame:
    series = [_adj_closes(s, years) for s in symbols]
    df = pd.concat(series, axis=1, join="inner").sort_index()
    df = df.dropna()
    if len(df) < 2:
        raise ValueError("not enough overlapping history for these symbols")
    return df


def panel(symbols: tuple[str, ...], years: int) -> pd.DataFrame:
    """Date-aligned adjusted closes. Cached on (symbols, years) so a parameter
    sweep costs one set of Yahoo requests, not one per cell. Returns a copy —
    the cached frame must never be handed out where a caller could mutate it."""
    return _panel_cached(tuple(symbols), years).copy()


# Keep the cache reachable under the public name the tests and callers use.
panel.cache_clear = _panel_cached.cache_clear


def drawdown(equity: pd.Series) -> pd.Series:
    """Fractional distance below the running peak. 0 at a new high, -0.2 at 20% down."""
    return equity / equity.cummax() - 1.0


def monthly_returns(equity: pd.Series) -> dict:
    """{"YYYY-MM": fractional return} from month-end to month-end."""
    m = equity.resample("ME").last().pct_change().dropna()
    return {ts.strftime("%Y-%m"): float(v) for ts, v in m.items()}


def metrics(equity: pd.Series) -> dict:
    """Performance stats for one equity curve. Every rate is a fraction, not a
    percentage. Sharpe and Sortino assume a 0% risk-free rate — stated in the UI
    rather than buried here, because it flatters both."""
    eq = equity.dropna()
    r = eq.pct_change().dropna()
    # len(eq) - 1 periods of return, so 252 returns is exactly one year and the
    # closed-form CAGR test holds to machine precision.
    years = (len(eq) - 1) / TRADING_DAYS
    total = float(eq.iloc[-1] / eq.iloc[0]) - 1.0

    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else 0.0
    vol = float(r.std(ddof=0)) * (TRADING_DAYS ** 0.5)
    mean_ann = float(r.mean()) * TRADING_DAYS
    sharpe = mean_ann / vol if vol > 0 else 0.0

    downside = r[r < 0]
    dvol = float(downside.std(ddof=0)) * (TRADING_DAYS ** 0.5) if len(downside) else 0.0
    sortino = mean_ann / dvol if dvol > 0 else 0.0

    max_dd = float(drawdown(eq).min())
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    months = list(monthly_returns(eq).values())
    return {
        "total_return": total,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "calmar": calmar,
        "hit_rate": float((r > 0).mean()) if len(r) else 0.0,
        "best_month": max(months) if months else 0.0,
        "worst_month": min(months) if months else 0.0,
    }


def relative(strategy: pd.Series, benchmark: pd.Series) -> dict:
    """Strategy measured against one benchmark, on their shared dates."""
    a = strategy.pct_change().dropna()
    b = benchmark.pct_change().dropna()
    a, b = a.align(b, join="inner")
    if len(a) < 2:
        return {"alpha": 0.0, "beta": 0.0, "tracking_error": 0.0, "information_ratio": 0.0}

    var_b = float(b.var(ddof=0))
    beta = float(a.cov(b, ddof=0) / var_b) if var_b > 0 else 0.0
    alpha = (float(a.mean()) - beta * float(b.mean())) * TRADING_DAYS

    active = a - b
    te = float(active.std(ddof=0)) * (TRADING_DAYS ** 0.5)
    ir = (float(active.mean()) * TRADING_DAYS) / te if te > 0 else 0.0
    return {"alpha": alpha, "beta": beta, "tracking_error": te, "information_ratio": ir}


def simulate(prices, targets, cost_bps: float, shift: int = 1):
    """Walk the price panel day by day, holding `targets` where they appear and
    letting positions drift in between. Returns (equity, turnover).

    `targets` carries a weight row only on rebalance dates, NaN elsewhere. A row
    of zeros is cash, which earns nothing and cannot lose anything.

    `shift` is the lookahead guard: a target decided from close t is applied to
    returns from t+1 onward. It is a parameter only so the test suite can run
    shift=0 and prove that peeking scores better — production never overrides it.

    ponytail: a plain O(days x assets) python loop. ~1300 days x 11 names is
    microseconds, and the vectorized version of drift-plus-turnover is the kind
    of code nobody can verify at 3am. Vectorize only if a sweep gets slow.
    """
    rets = prices.pct_change().fillna(0.0)
    applied = targets.shift(shift) if shift else targets

    weights = pd.Series(0.0, index=prices.columns)
    equity = 1.0
    curve, turns = [], []

    for date in prices.index:
        row = applied.loc[date]
        turnover = 0.0
        if not row.isna().all():
            target = row.fillna(0.0)
            turnover = float((target - weights).abs().sum()) / 2.0
            weights = target

        day = float((weights * rets.loc[date]).sum()) - turnover * cost_bps / 1e4
        equity *= 1 + day

        # Positions drift with prices until the next rebalance: a name that
        # doubled is now a bigger share of the book, and pretending otherwise
        # silently rebalances daily for free.
        grown = weights * (1 + rets.loc[date])
        total = float(grown.sum())
        weights = grown / total if total > 0 else grown

        curve.append(equity)
        turns.append(turnover)

    return (
        pd.Series(curve, index=prices.index),
        pd.Series(turns, index=prices.index),
    )


MONTH_DAYS = 21  # trading days per month, for momentum lookback offsets

CAVEATS = [
    "Survivorship bias, and it is the largest error in this study. The basket is "
    "picked in 2026 knowing which SaaS companies survived. Names that collapsed, "
    "delisted, or were acquired at a loss are absent, so every return here is "
    "biased upward — and not slightly. Removing this needs point-in-time index "
    "constituents, which this study does not have.",
    "Costs are a flat charge on turnover. No slippage, no market impact, no bid/ask spread.",
    "No taxes. Momentum rotation realises short-term gains; a taxable account keeps less.",
    "Dividends are handled through adjusted close, which assumes frictionless reinvestment.",
    "One sample, one market regime. The window is a single non-overlapping draw from history.",
    "Sharpe and Sortino assume a 0% risk-free rate, which flatters both.",
]


def month_ends(index) -> pd.DatetimeIndex:
    """The last trading day present in each calendar month."""
    s = index.to_series()
    return pd.DatetimeIndex(s.groupby([s.dt.year, s.dt.month]).max().sort_values())


def _empty_targets(prices) -> pd.DataFrame:
    return pd.DataFrame(index=prices.index, columns=prices.columns, dtype="float64")


def basket_index(prices: pd.DataFrame) -> pd.Series:
    """An equal-weight index of the basket, used ONLY to generate the SMA signal.
    Daily-rebalanced for simplicity — it never books a return, so its rebalancing
    convention cannot leak into the reported performance."""
    return (1 + prices.pct_change().fillna(0.0).mean(axis=1)).cumprod()


def targets_bh_single(prices, symbol) -> pd.DataFrame:
    """Buy the benchmark on day one and never trade again."""
    t = _empty_targets(prices)
    t.loc[prices.index[0], symbol] = 1.0
    return t


def targets_bh_basket(prices, basket) -> pd.DataFrame:
    """Equal weight, rebalanced monthly. A literal never-rebalance basket drifts
    into whichever name ran hardest and stops being a basket, which makes it a
    dishonest control for an equal-weight strategy."""
    t = _empty_targets(prices)
    w = 1.0 / len(basket)
    for date in [prices.index[0], *month_ends(prices.index)]:
        t.loc[date, list(basket)] = w
    return t


def targets_sma(prices, basket, window: int) -> pd.DataFrame:
    """Hold the basket while its equal-weight index is above its `window`-day SMA,
    else sit in cash. Rebalances monthly while invested, and on every day the
    signal flips."""
    members = list(basket)
    idx = basket_index(prices[members])
    on = idx > idx.rolling(window).mean()
    on = on.fillna(False)

    flips = on.ne(on.shift(1))
    dates = sorted(set(month_ends(prices.index)) | set(prices.index[flips]))

    t = _empty_targets(prices)
    w = 1.0 / len(members)
    for date in dates:
        t.loc[date, members] = w if bool(on.loc[date]) else 0.0
    return t


def targets_momentum(prices, basket, n: int, lookback: int) -> pd.DataFrame:
    """Monthly: rank members by return over t-lookback months to t-1 month, hold
    the top n equal-weight.

    The one-month gap is deliberate. Including the most recent month picks up
    short-term reversal and makes momentum look better than it trades.
    """
    members = list(basket)
    px = prices[members]
    skip = MONTH_DAYS
    span = MONTH_DAYS * lookback

    # NaN wherever either endpoint is missing, so a symbol without full history
    # drops out of the ranking instead of being scored on a partial window.
    past = px.shift(span)
    recent = px.shift(skip)
    score = recent / past - 1

    t = _empty_targets(prices)
    for date in month_ends(prices.index):
        row = score.loc[date].dropna()
        if row.empty:
            continue
        winners = list(row.sort_values(ascending=False).head(n).index)
        t.loc[date, members] = 0.0
        t.loc[date, winners] = 1.0 / len(winners)
    return t


def count_entries(targets: pd.DataFrame) -> int:
    """How many times the strategy moves from flat (all-cash) into a position.
    Targets only carry a row on rebalance dates; forward-filling gives the
    invested state on every day, so a drift day between rebalances (weights
    still nonzero) is correctly not counted as a fresh entry."""
    filled = targets.ffill().fillna(0.0)
    invested = filled.sum(axis=1) > 1e-9
    prev = invested.shift(1, fill_value=False)
    return int((invested & ~prev).sum())


def build_targets(prices, basket, rule: str, params: dict) -> pd.DataFrame:
    if rule == "sma":
        return targets_sma(prices, basket, window=int(params.get("window", 200)))
    if rule == "momentum":
        return targets_momentum(
            prices, basket,
            n=int(params.get("n", 3)),
            lookback=int(params.get("lookback", 12)),
        )
    raise ValueError(f"unknown rule: {rule}")


SWEEP_GRID = {
    "sma": [{"window": w} for w in (50, 100, 150, 200, 250)],
    "momentum": [
        {"n": n, "lookback": lb}
        for n in (2, 3, 5)
        for lb in (3, 6, 12)
    ],
}


def sweep(prices, basket, rule: str, cost_bps: float) -> list:
    """The same engine across a parameter grid. This is a fragility check, not a
    search for the best setting: a rule that only works at one parameter value is
    a curve fit, and a table makes that obvious at a glance."""
    out = []
    for params in SWEEP_GRID.get(rule, []):
        eq, _ = simulate(prices, build_targets(prices, basket, rule, params), cost_bps)
        m = metrics(eq)
        out.append({
            "params": params,
            "cagr": m["cagr"],
            "sharpe": m["sharpe"],
            "max_dd": m["max_dd"],
        })
    return out


def oos_split(prices, basket, rule: str, params: dict, cost_bps: float) -> dict:
    """Metrics for the first 60% of the window and the last 40%, separately. An
    edge that shows up only in the first segment has not been validated by the
    second. Targets are built on the full panel and then sliced, so the
    out-of-sample segment keeps the indicator warm-up it would have had live."""
    targets = build_targets(prices, basket, rule, params)
    cut = int(len(prices) * 0.6)
    if cut < 2 or len(prices) - cut < 2:
        return {"in_sample": None, "out_sample": None, "split_date": None}

    in_eq, _ = simulate(prices.iloc[:cut], targets.iloc[:cut], cost_bps)
    out_eq, _ = simulate(prices.iloc[cut:], targets.iloc[cut:], cost_bps)
    return {
        "in_sample": metrics(in_eq),
        "out_sample": metrics(out_eq),
        "split_date": prices.index[cut].strftime("%Y-%m-%d"),
    }


def run_study(symbols, benchmark, rule, params, years, cost_bps) -> dict:
    """The whole study: three curves, their metrics, and the robustness blocks."""
    basket = tuple(symbols)
    prices = panel(basket + (benchmark,), years)

    strat_t = build_targets(prices, basket, rule, params)
    strategy, turnover = simulate(prices, strat_t, cost_bps)
    bh_basket, _ = simulate(prices, targets_bh_basket(prices, basket), cost_bps)
    bh_spy, _ = simulate(prices, targets_bh_single(prices, benchmark), cost_bps)

    dates = [d.strftime("%Y-%m-%d") for d in prices.index]
    years_run = (len(prices) - 1) / TRADING_DAYS

    return {
        "curves": {
            "dates": dates,
            "strategy": [round(v, 6) for v in strategy],
            "bh_basket": [round(v, 6) for v in bh_basket],
            "bh_spy": [round(v, 6) for v in bh_spy],
            "strategy_dd": [round(v, 6) for v in drawdown(strategy)],
            "bh_basket_dd": [round(v, 6) for v in drawdown(bh_basket)],
            "bh_spy_dd": [round(v, 6) for v in drawdown(bh_spy)],
        },
        "metrics": {
            "strategy": metrics(strategy),
            "bh_basket": metrics(bh_basket),
            "bh_spy": metrics(bh_spy),
            "vs_basket": relative(strategy, bh_basket),
            "vs_spy": relative(strategy, bh_spy),
        },
        "monthly": {
            "strategy": monthly_returns(strategy),
            "bh_basket": monthly_returns(bh_basket),
            "bh_spy": monthly_returns(bh_spy),
        },
        "sweep": sweep(prices, basket, rule, cost_bps),
        "oos": oos_split(prices, basket, rule, params, cost_bps),
        "turnover": {"annual": float(turnover.sum()) / years_run if years_run > 0 else 0.0},
        "trades": {"entries": count_entries(strat_t)},
        "symbols": list(basket),
        "benchmark": benchmark,
        "rule": rule,
        "params": params,
        "start_date": dates[0],
        "end_date": dates[-1],
        "n_days": len(dates),
        "caveats": CAVEATS,
    }
