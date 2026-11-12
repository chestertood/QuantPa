# Backtest Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Backtest-Lab view — an equal-weight SaaS basket with a selectable timing rule, scored against two buy-and-hold benchmarks and presented as a quantitative-research tearsheet with robustness checks.

**Architecture:** A single backend module `backend/backtest.py` holds the whole engine: it fetches unrounded **adjusted** closes through the existing `market._fetch_chart`, builds a date-aligned price panel, converts strategy rules into target-weight rows, and runs one shared simulator that drifts holdings, charges turnover costs, and applies a one-day signal shift. Metrics take an equity curve and nothing else, so all three curves are scored by identical code. `POST /api/backtest` returns one JSON study; `frontend/src/components/Backtest.jsx` renders it with recharts.

**Tech Stack:** Python 3.12, FastAPI, pandas 2.2.3, numpy, pydantic v2 (all installed). React 18 + recharts 2.13 (installed). **No new dependencies are added by this plan.**

## Global Constraints

- **No new dependencies**, backend or frontend. pandas/numpy/scipy and recharts are already present; use them.
- **Never modify `market.get_history()`.** Its callers (`/api/positions/{symbol}/history`, `PriceChart.jsx`) depend on raw, 2dp-rounded close for display. The backtest reads adjusted close through `market._fetch_chart` instead.
- **Adjusted close only, unrounded**, everywhere in the backtest. Raw close makes a 2:1 split look like a −50% day.
- **Signals are shifted one day** before they earn returns. Decide on close *t*, hold from *t+1*.
- **Tests make no network calls.** Every test builds synthetic price data. Follow the repo convention in `backend/test_market.py`: plain `def test_*()` functions with bare `assert`, plus an `if __name__ == "__main__":` block that calls each test and prints `ok`. Runnable as `python test_backtest.py` and under `pytest`.
- **Trading-day constant is 252.** Month ≈ 21 trading days where a trading-day offset is needed.
- Follow existing FastAPI style in `backend/main.py`: `HTTPException` with `status_code=502` for upstream failures, `400` for bad input, `404` for empty results.
- Frontend follows existing conventions: `panel` / `card` / `muted-text` / `up` / `down` classes from `styles.css`, dark recharts styling (`stroke="#2a2f3a"` grid, `background: "#1a1d24"` tooltip) as in `PriceChart.jsx`, number formatting via `format.js` (`fracPct` for fractions, `ratio` for plain ratios).
- Run all backend commands from the `backend/` directory using the venv interpreter: `.venv\Scripts\python.exe`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/backtest.py` (create) | Data panel, simulator, rules, metrics, sweep, OOS split, `run_study` entry point |
| `backend/test_backtest.py` (create) | Synthetic-data self-check for every piece of the engine |
| `backend/main.py` (modify) | One `POST /api/backtest` route + pydantic request model |
| `frontend/src/api.js` (modify) | One `runBacktest(body)` client function |
| `frontend/src/components/Backtest.jsx` (create) | Controls, equity chart, underwater plot, metrics table, heatmap, sweep, caveats |
| `frontend/src/App.jsx` (modify) | `view === "backtest"` branch |

---

### Task 1: Price panel on adjusted close

**Files:**
- Create: `backend/backtest.py`
- Create: `backend/test_backtest.py`

**Interfaces:**
- Consumes: `market._fetch_chart(symbol, rng, interval)` and `market._yahoo(symbol)` from the existing `backend/market.py`.
- Produces:
  - `TRADING_DAYS: int = 252`
  - `DEFAULT_BASKET: tuple[str, ...]`
  - `_adj_closes(symbol: str, years: int) -> pd.Series` — unrounded adjusted close, DatetimeIndex, named `symbol`
  - `panel(symbols: tuple[str, ...], years: int) -> pd.DataFrame` — inner-joined, sorted, NaN-free, safe to mutate

- [ ] **Step 1: Write the failing tests**

Create `backend/test_backtest.py`:

```python
"""Self-check for backtest.py — the price panel, simulator, rules and metrics.
Every test builds synthetic prices, so it makes no network calls.
Run: python test_backtest.py
"""
import pandas as pd

import backtest


def _chart(dates, adj):
    """A Yahoo chart payload with an adjclose block, as _fetch_chart returns it."""
    ts = [int(pd.Timestamp(d).timestamp()) for d in dates]
    return {
        "timestamp": ts,
        "indicators": {
            "quote": [{"close": [round(a, 2) for a in adj]}],
            "adjclose": [{"adjclose": adj}],
        },
    }


def _stub_charts(mapping):
    """Point backtest at canned charts. mapping: {symbol: (dates, adj_closes)}."""
    def fake(symbol, rng, interval):
        dates, adj = mapping[symbol]
        return _chart(dates, adj)
    backtest.market._fetch_chart = fake
    backtest.panel.cache_clear()


def test_panel_uses_adjusted_close_not_rounded_close():
    # adjclose carries three decimals; a raw-close reader would round them away.
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    _stub_charts({"AAA": (dates, [100.125, 101.375, 102.625])})
    df = backtest.panel(("AAA",), 1)
    assert list(df.columns) == ["AAA"], df.columns
    assert df["AAA"].iloc[0] == 100.125, df["AAA"].iloc[0]
    assert len(df) == 3, len(df)


def test_panel_inner_joins_to_the_shorter_series():
    # BBB starts a day late — the panel must start late too, not carry a NaN.
    _stub_charts({
        "AAA": (["2024-01-02", "2024-01-03", "2024-01-04"], [10.0, 11.0, 12.0]),
        "BBB": (["2024-01-03", "2024-01-04"], [20.0, 21.0]),
    })
    df = backtest.panel(("AAA", "BBB"), 1)
    assert len(df) == 2, len(df)
    assert str(df.index[0].date()) == "2024-01-03", df.index[0]
    assert not df.isna().any().any(), df


def test_panel_result_is_safe_to_mutate():
    # panel() is cached; handing out the cached frame would let one caller
    # corrupt the next caller's data.
    dates = ["2024-01-02", "2024-01-03"]
    _stub_charts({"AAA": (dates, [10.0, 11.0])})
    first = backtest.panel(("AAA",), 1)
    first.iloc[0, 0] = -999.0
    second = backtest.panel(("AAA",), 1)
    assert second.iloc[0, 0] == 10.0, second.iloc[0, 0]


if __name__ == "__main__":
    test_panel_uses_adjusted_close_not_rounded_close()
    test_panel_inner_joins_to_the_shorter_series()
    test_panel_result_is_safe_to_mutate()
    print("ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`:
```
.venv\Scripts\python.exe test_backtest.py
```
Expected: `ModuleNotFoundError: No module named 'backtest'`

- [ ] **Step 3: Write the implementation**

Create `backend/backtest.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `backend/`:
```
.venv\Scripts\python.exe test_backtest.py
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/backtest.py backend/test_backtest.py
git commit -m "Add backtest price panel on adjusted close"
```

---

### Task 2: Metrics from an equity curve

**Files:**
- Modify: `backend/backtest.py` (append)
- Modify: `backend/test_backtest.py` (append)

**Interfaces:**
- Consumes: `TRADING_DAYS` from Task 1.
- Produces:
  - `metrics(equity: pd.Series) -> dict` with keys `cagr, vol, sharpe, sortino, max_dd, calmar, hit_rate, best_month, worst_month, total_return` (all plain floats, all as fractions — `0.12` means 12%)
  - `monthly_returns(equity: pd.Series) -> dict[str, float]` keyed `"YYYY-MM"`
  - `drawdown(equity: pd.Series) -> pd.Series`
  - `relative(strategy: pd.Series, benchmark: pd.Series) -> dict` with keys `alpha, beta, tracking_error, information_ratio`

Metrics take an equity curve and nothing else — no rule, no weights, no params — so all three curves in the study are scored by identical code.

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_backtest.py`, above the `__main__` block:

```python
def _curve(returns, start="2024-01-02"):
    """An equity curve starting at 1.0, then compounding `returns`."""
    idx = pd.bdate_range(start=start, periods=len(returns) + 1)
    eq = [1.0]
    for r in returns:
        eq.append(eq[-1] * (1 + r))
    return pd.Series(eq, index=idx)


def test_metrics_on_constant_drift_match_closed_form():
    eq = _curve([0.001] * 252)
    m = backtest.metrics(eq)
    # 252 returns over 252 trading days is exactly one year.
    assert abs(m["cagr"] - (1.001 ** 252 - 1)) < 1e-9, m["cagr"]
    assert abs(m["vol"]) < 1e-12, m["vol"]        # no dispersion at all
    assert abs(m["max_dd"]) < 1e-12, m["max_dd"]  # never below a prior peak
    assert abs(m["hit_rate"] - 1.0) < 1e-12, m["hit_rate"]


def test_max_drawdown_is_peak_to_trough():
    # 1.00 -> 1.10 -> 0.88 -> 0.968: worst is 0.88 against the 1.10 peak = -20%.
    eq = _curve([0.10, -0.20, 0.10])
    m = backtest.metrics(eq)
    assert abs(m["max_dd"] - (-0.20)) < 1e-12, m["max_dd"]
    assert abs(m["total_return"] - (1.1 * 0.8 * 1.1 - 1)) < 1e-12, m["total_return"]


def test_monthly_returns_are_keyed_by_month():
    idx = pd.to_datetime(["2024-01-30", "2024-01-31", "2024-02-29"])
    eq = pd.Series([1.0, 1.10, 1.32], index=idx)
    mr = backtest.monthly_returns(eq)
    # February compounds off January's close: 1.32 / 1.10 - 1 = 0.20
    assert abs(mr["2024-02"] - 0.20) < 1e-12, mr


def test_beta_of_a_curve_against_itself_is_one():
    eq = _curve([0.01, -0.02, 0.03, 0.005])
    rel = backtest.relative(eq, eq)
    assert abs(rel["beta"] - 1.0) < 1e-9, rel["beta"]
    assert abs(rel["alpha"]) < 1e-9, rel["alpha"]
    assert abs(rel["tracking_error"]) < 1e-12, rel["tracking_error"]
```

And add to the `__main__` block:
```python
    test_metrics_on_constant_drift_match_closed_form()
    test_max_drawdown_is_peak_to_trough()
    test_monthly_returns_are_keyed_by_month()
    test_beta_of_a_curve_against_itself_is_one()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`:
```
.venv\Scripts\python.exe test_backtest.py
```
Expected: `AttributeError: module 'backtest' has no attribute 'metrics'`

- [ ] **Step 3: Write the implementation**

Append to `backend/backtest.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `backend/`:
```
.venv\Scripts\python.exe test_backtest.py
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/backtest.py backend/test_backtest.py
git commit -m "Add backtest performance metrics"
```

---

### Task 3: The simulator — drift, costs, and the one-day shift

**Files:**
- Modify: `backend/backtest.py` (append)
- Modify: `backend/test_backtest.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks beyond the module itself.
- Produces:
  - `simulate(prices: pd.DataFrame, targets: pd.DataFrame, cost_bps: float, shift: int = 1) -> tuple[pd.Series, pd.Series]` returning `(equity, turnover)`, both indexed like `prices`

`targets` is a DataFrame with the same columns as `prices`, containing a weight row **only on rebalance dates** and NaN elsewhere. A row of zeros means "hold cash". `shift` exists so the test suite can prove the engine is not reading the future; production code never passes anything but the default.

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_backtest.py`, above the `__main__` block:

```python
def _prices(series_map, start="2024-01-02"):
    """A price DataFrame from {symbol: [prices...]}."""
    n = len(next(iter(series_map.values())))
    idx = pd.bdate_range(start=start, periods=n)
    return pd.DataFrame(series_map, index=idx)


def _targets_like(prices, rows):
    """A target-weight frame: {row_position: {symbol: weight}}, NaN elsewhere."""
    t = pd.DataFrame(index=prices.index, columns=prices.columns, dtype="float64")
    for pos, weights in rows.items():
        for sym, w in weights.items():
            t.iloc[pos, t.columns.get_loc(sym)] = w
    return t


def test_full_allocation_tracks_the_asset_exactly():
    px = _prices({"AAA": [10.0, 11.0, 12.1]})
    eq, _ = backtest.simulate(px, _targets_like(px, {0: {"AAA": 1.0}}), cost_bps=0)
    # Bought on day 0's signal, so returns accrue from day 1: +10%, +10%.
    assert abs(eq.iloc[-1] - 1.21) < 1e-12, eq.iloc[-1]


def test_zero_weights_are_cash_and_never_move():
    px = _prices({"AAA": [10.0, 5.0, 2.5]})
    eq, _ = backtest.simulate(px, _targets_like(px, {0: {"AAA": 0.0}}), cost_bps=0)
    assert abs(eq.iloc[-1] - 1.0) < 1e-12, eq.iloc[-1]


def test_costs_reduce_terminal_equity_and_show_up_as_turnover():
    px = _prices({"AAA": [10.0, 11.0, 12.0, 13.0]})
    targets = _targets_like(px, {0: {"AAA": 1.0}, 1: {"AAA": 0.0}, 2: {"AAA": 1.0}})
    free, turn_free = backtest.simulate(px, targets, cost_bps=0)
    charged, turn_charged = backtest.simulate(px, targets, cost_bps=100)
    assert charged.iloc[-1] < free.iloc[-1], (charged.iloc[-1], free.iloc[-1])
    assert turn_charged.sum() > 0, turn_charged.sum()
    # Turnover is the same trades either way; only the charge differs.
    assert abs(turn_free.sum() - turn_charged.sum()) < 1e-12


def test_engine_does_not_read_the_future():
    # A rise then a crash. Acting on the same day's close (shift=0) is peeking,
    # and peeking MUST look better. If it doesn't, the shift is wired backwards
    # and the production path is reading tomorrow's price.
    px = _prices({"AAA": [10.0, 11.0, 12.0, 6.0, 6.5]})
    # Exit on the row before the crash prints.
    targets = _targets_like(px, {0: {"AAA": 1.0}, 2: {"AAA": 0.0}})
    honest, _ = backtest.simulate(px, targets, cost_bps=0, shift=1)
    peeking, _ = backtest.simulate(px, targets, cost_bps=0, shift=0)
    assert peeking.iloc[-1] > honest.iloc[-1], (peeking.iloc[-1], honest.iloc[-1])


def test_holdings_drift_between_rebalances():
    # Equal weight on day 0; AAA doubles while BBB is flat. With no further
    # target rows the position must drift to 2/3 AAA, not snap back to 50/50.
    px = _prices({"AAA": [10.0, 20.0, 40.0], "BBB": [10.0, 10.0, 10.0]})
    eq, _ = backtest.simulate(
        px, _targets_like(px, {0: {"AAA": 0.5, "BBB": 0.5}}), cost_bps=0
    )
    # Day 1: 0.5*2 + 0.5*1 = 1.5. Day 2: AAA is now 2/3 of the book and doubles
    # again -> 1.5 * (2/3*2 + 1/3*1) = 2.5.
    assert abs(eq.iloc[-1] - 2.5) < 1e-12, eq.iloc[-1]
```

And add to the `__main__` block:
```python
    test_full_allocation_tracks_the_asset_exactly()
    test_zero_weights_are_cash_and_never_move()
    test_costs_reduce_terminal_equity_and_show_up_as_turnover()
    test_engine_does_not_read_the_future()
    test_holdings_drift_between_rebalances()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`:
```
.venv\Scripts\python.exe test_backtest.py
```
Expected: `AttributeError: module 'backtest' has no attribute 'simulate'`

- [ ] **Step 3: Write the implementation**

Append to `backend/backtest.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `backend/`:
```
.venv\Scripts\python.exe test_backtest.py
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/backtest.py backend/test_backtest.py
git commit -m "Add backtest simulator with drift, costs and lookahead guard"
```

---

### Task 4: Strategy rules and the study entry point

**Files:**
- Modify: `backend/backtest.py` (append)
- Modify: `backend/test_backtest.py` (append)

**Interfaces:**
- Consumes: `panel`, `simulate`, `metrics`, `relative`, `monthly_returns`, `drawdown`, `TRADING_DAYS`, `DEFAULT_BASKET`.
- Produces:
  - `month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex` — last trading day of each month
  - `basket_index(prices: pd.DataFrame) -> pd.Series` — equal-weight signal index
  - `targets_bh_single(prices, symbol) -> pd.DataFrame`
  - `targets_bh_basket(prices, basket) -> pd.DataFrame`
  - `targets_sma(prices, basket, window: int) -> pd.DataFrame`
  - `targets_momentum(prices, basket, n: int, lookback: int) -> pd.DataFrame`
  - `build_targets(prices, basket, rule: str, params: dict) -> pd.DataFrame` — dispatch; raises `ValueError` on an unknown rule
  - `run_study(symbols, benchmark, rule, params, years, cost_bps) -> dict` — the full JSON-ready study

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_backtest.py`, above the `__main__` block:

```python
def test_sma_rule_sits_out_the_crash():
    # 120 days climbing, then a slide. A 20-day filter must be in cash for most
    # of the fall, so its drawdown beats buy-and-hold's.
    up = [10.0 * (1.01 ** i) for i in range(120)]
    down = [up[-1] * (0.97 ** i) for i in range(1, 61)]
    px = _prices({"AAA": up + down})
    basket = ("AAA",)

    filtered = backtest.targets_sma(px, basket, window=20)
    held = backtest.targets_bh_basket(px, basket)
    eq_f, _ = backtest.simulate(px, filtered, cost_bps=0)
    eq_h, _ = backtest.simulate(px, held, cost_bps=0)

    assert backtest.metrics(eq_f)["max_dd"] > backtest.metrics(eq_h)["max_dd"], (
        backtest.metrics(eq_f)["max_dd"], backtest.metrics(eq_h)["max_dd"]
    )
    assert eq_f.iloc[-1] > eq_h.iloc[-1], (eq_f.iloc[-1], eq_h.iloc[-1])


def test_momentum_holds_only_the_top_n():
    # AAA compounds fastest, CCC slowest. Top-1 must hold AAA alone.
    n = 400
    px = _prices({
        "AAA": [10.0 * (1.004 ** i) for i in range(n)],
        "BBB": [10.0 * (1.002 ** i) for i in range(n)],
        "CCC": [10.0 * (0.999 ** i) for i in range(n)],
    })
    t = backtest.targets_momentum(px, ("AAA", "BBB", "CCC"), n=1, lookback=6)
    rows = t.dropna(how="all")
    assert len(rows) > 0, "no rebalance rows emitted"
    last = rows.iloc[-1].fillna(0.0)
    assert abs(last["AAA"] - 1.0) < 1e-12, last.to_dict()
    assert abs(last["CCC"]) < 1e-12, last.to_dict()


def test_momentum_never_ranks_a_symbol_with_short_history():
    # DDD only has data for the tail. Ranking it on a partial window would let
    # it enter on no information; it must be excluded until the window fills.
    n = 400
    px = _prices({
        "AAA": [10.0 * (1.001 ** i) for i in range(n)],
        "DDD": [float("nan")] * (n - 30) + [10.0 * (1.05 ** i) for i in range(30)],
    })
    t = backtest.targets_momentum(px, ("AAA", "DDD"), n=1, lookback=6)
    first = t.dropna(how="all").iloc[0].fillna(0.0)
    assert abs(first["DDD"]) < 1e-12, first.to_dict()


def test_month_ends_are_the_last_trading_day():
    idx = pd.bdate_range("2024-01-01", "2024-03-15")
    me = backtest.month_ends(idx)
    assert str(me[0].date()) == "2024-01-31", me[0]
    assert str(me[1].date()) == "2024-02-29", me[1]


def test_build_targets_rejects_an_unknown_rule():
    px = _prices({"AAA": [10.0, 11.0]})
    try:
        backtest.build_targets(px, ("AAA",), "wishful", {})
    except ValueError as e:
        assert "wishful" in str(e), str(e)
    else:
        assert False, "unknown rule was accepted"


def test_run_study_returns_three_aligned_curves():
    n = 300
    _stub_charts({
        "AAA": (list(pd.bdate_range("2023-01-02", periods=n).strftime("%Y-%m-%d")),
                [10.0 * (1.002 ** i) for i in range(n)]),
        "SPY": (list(pd.bdate_range("2023-01-02", periods=n).strftime("%Y-%m-%d")),
                [50.0 * (1.001 ** i) for i in range(n)]),
    })
    study = backtest.run_study(
        symbols=("AAA",), benchmark="SPY", rule="sma",
        params={"window": 50}, years=2, cost_bps=5,
    )
    c = study["curves"]
    assert len(c["dates"]) == len(c["strategy"]) == len(c["bh_basket"]) == len(c["bh_spy"])
    assert c["strategy"][0] == 1.0 and c["bh_spy"][0] == 1.0, (c["strategy"][0], c["bh_spy"][0])
    for key in ("strategy", "bh_basket", "bh_spy", "vs_basket", "vs_spy"):
        assert key in study["metrics"], study["metrics"].keys()
    assert study["caveats"], "caveats must never be empty"
    assert study["start_date"] == c["dates"][0], study["start_date"]
```

And add to the `__main__` block:
```python
    test_sma_rule_sits_out_the_crash()
    test_momentum_holds_only_the_top_n()
    test_momentum_never_ranks_a_symbol_with_short_history()
    test_month_ends_are_the_last_trading_day()
    test_build_targets_rejects_an_unknown_rule()
    test_run_study_returns_three_aligned_curves()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`:
```
.venv\Scripts\python.exe test_backtest.py
```
Expected: `AttributeError: module 'backtest' has no attribute 'targets_sma'`

- [ ] **Step 3: Write the implementation**

Append to `backend/backtest.py`:

```python
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
        "symbols": list(basket),
        "benchmark": benchmark,
        "rule": rule,
        "params": params,
        "start_date": dates[0],
        "end_date": dates[-1],
        "n_days": len(dates),
        "caveats": CAVEATS,
    }
```

- [ ] **Step 4: Write the sweep and out-of-sample blocks**

`run_study` above calls `sweep` and `oos_split`. Append them to `backend/backtest.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run from `backend/`:
```
.venv\Scripts\python.exe test_backtest.py
```
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add backend/backtest.py backend/test_backtest.py
git commit -m "Add backtest rules, parameter sweep and out-of-sample split"
```

---

### Task 5: The API route

**Files:**
- Modify: `backend/main.py` (add import near the existing `import cashflow` block; add route at end of file)
- Modify: `backend/test_main.py` (append)

**Interfaces:**
- Consumes: `backtest.run_study`, `backtest.DEFAULT_BASKET`.
- Produces: `POST /api/backtest` returning the `run_study` dict.

- [ ] **Step 1: Write the failing test**

First read the top of `backend/test_main.py` to match its existing client setup, then append:

```python
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
```

Add these to `test_main.py`'s `__main__` block if it has one, matching the file's existing style.

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`:
```
.venv\Scripts\python.exe test_main.py
```
Expected: failures reporting 404 (route does not exist yet).

- [ ] **Step 3: Add the route**

Add to the import block at the top of `backend/main.py`, after `import cashflow`:

```python
import backtest
```

Add to the imports from fastapi/pydantic at the top:

```python
from pydantic import BaseModel, Field
```

Append to the end of `backend/main.py`:

```python
# Symbols are interpolated into an outbound Yahoo URL, so the character set is
# constrained here rather than trusted from the client.
_SYMBOL_OK = re.compile(r"^[A-Za-z0-9.\- ]{1,12}$")


class BacktestRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: list(backtest.DEFAULT_BASKET), max_length=20)
    benchmark: str = "SPY"
    rule: Literal["sma", "momentum"] = "sma"
    params: dict = Field(default_factory=dict)
    years: int = Field(default=5, ge=1, le=20)
    cost_bps: float = Field(default=5.0, ge=0, le=100)


@app.post("/api/backtest")
def run_backtest(req: BacktestRequest):
    """Run one backtest study: strategy vs basket buy-and-hold vs benchmark
    buy-and-hold, with a parameter sweep and an in/out-of-sample split.

    POST rather than GET: the body is a nested object and the response is a
    computed study, not a cacheable resource.
    """
    symbols = [s.strip().upper() for s in req.symbols if s.strip()]
    if not symbols:
        raise HTTPException(status_code=400, detail="no symbols given")
    for s in [*symbols, req.benchmark]:
        if not _SYMBOL_OK.match(s):
            raise HTTPException(status_code=400, detail=f"bad symbol: {s}")

    try:
        return backtest.run_study(
            symbols=tuple(symbols),
            benchmark=req.benchmark.strip().upper(),
            rule=req.rule,
            params=req.params,
            years=req.years,
            cost_bps=req.cost_bps,
        )
    except ValueError as e:
        # No overlapping history, no adjusted close, unknown rule — all caller error.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"backtest data error: {e}")
```

Add `import re` and `from typing import Literal` to the top-of-file imports in `backend/main.py` if not already present.

- [ ] **Step 4: Run the tests to verify they pass**

Run from `backend/`:
```
.venv\Scripts\python.exe test_main.py
```
Expected: `ok`

- [ ] **Step 5: Verify the route against live data**

Start the backend from `backend/`:
```
.venv\Scripts\python.exe -m uvicorn main:app --port 8000 --reload
```
Then in a second shell:
```
curl -s -X POST http://localhost:8000/api/backtest -H "Content-Type: application/json" -d "{\"symbols\":[\"CRM\",\"NOW\",\"ADBE\"],\"rule\":\"sma\",\"params\":{\"window\":200},\"years\":3}"
```
Expected: JSON with `curves`, `metrics`, `sweep`, `oos`, `caveats`. Confirm `curves.strategy[0] == 1.0` and that `metrics.bh_spy.cagr` is a plausible SPY number for the window (roughly 0.10–0.20 for recent 3-year windows) — a wildly wrong benchmark means adjusted close is not being read.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/test_main.py
git commit -m "Add POST /api/backtest route"
```

---

### Task 6: The Backtest Lab view

**Files:**
- Modify: `frontend/src/api.js` (append)
- Create: `frontend/src/components/Backtest.jsx`
- Modify: `frontend/src/App.jsx` (import + one view branch)

**Interfaces:**
- Consumes: `POST /api/backtest` response from Task 5; `fracPct`, `ratio` from `format.js`.
- Produces: `runBacktest(body)` in `api.js`; default-exported `Backtest` component.

- [ ] **Step 1: Add the API client function**

Append to `frontend/src/api.js`:

```javascript
export async function runBacktest(body) {
  const r = await fetch(`${BASE}/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json()).detail || "backtest failed");
  return r.json();
}
```

- [ ] **Step 2: Write the component**

Create `frontend/src/components/Backtest.jsx`:

```javascript
import { useState } from "react";
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, CartesianGrid,
} from "recharts";
import { runBacktest } from "../api";
import { fracPct, ratio } from "../format";

const DEFAULT_BASKET = "CRM, NOW, ADBE, SNOW, DDOG, TEAM, WDAY, ZS, HUBS, MDB";

// The strategy is the subject, the benchmarks are context — so the strategy is
// the only bright series. Dash patterns carry the distinction too, because the
// app's red/green is not colorblind-safe on its own.
const SERIES = [
  { key: "strategy", name: "Strategy", stroke: "#4ea1ff", dash: null, width: 2.5 },
  { key: "bh_basket", name: "Basket B&H", stroke: "#9aa4b2", dash: "6 3", width: 1.5 },
  { key: "bh_spy", name: "SPY B&H", stroke: "#6b7280", dash: "2 3", width: 1.5 },
];

export default function Backtest() {
  const [symbols, setSymbols] = useState(DEFAULT_BASKET);
  const [rule, setRule] = useState("sma");
  const [window, setWindow] = useState(200);
  const [topN, setTopN] = useState(3);
  const [lookback, setLookback] = useState(12);
  const [years, setYears] = useState(5);
  const [costBps, setCostBps] = useState(5);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      const params = rule === "sma" ? { window: +window } : { n: +topN, lookback: +lookback };
      setData(await runBacktest({
        symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
        benchmark: "SPY",
        rule,
        params,
        years: +years,
        cost_bps: +costBps,
      }));
    } catch (e) {
      setErr(e.message);
      setData(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header>
        <h1>Backtest Lab</h1>
        {data && (
          <span className="asof">
            {data.start_date} → {data.end_date} · {data.n_days} days
          </span>
        )}
      </header>

      <section>
        <div className="panel">
          <h2>Study</h2>
          <div className="bt-controls">
            <label>
              Basket
              <input value={symbols} onChange={(e) => setSymbols(e.target.value)} />
            </label>
            <label>
              Rule
              <select value={rule} onChange={(e) => setRule(e.target.value)}>
                <option value="sma">SMA filter</option>
                <option value="momentum">Momentum top-N</option>
              </select>
            </label>
            {rule === "sma" ? (
              <label>
                SMA window
                <input type="number" value={window} onChange={(e) => setWindow(e.target.value)} />
              </label>
            ) : (
              <>
                <label>
                  Top N
                  <input type="number" value={topN} onChange={(e) => setTopN(e.target.value)} />
                </label>
                <label>
                  Lookback (mo)
                  <input type="number" value={lookback} onChange={(e) => setLookback(e.target.value)} />
                </label>
              </>
            )}
            <label>
              Years
              <input type="number" value={years} onChange={(e) => setYears(e.target.value)} />
            </label>
            <label>
              Cost (bps)
              <input type="number" value={costBps} onChange={(e) => setCostBps(e.target.value)} />
            </label>
            <button onClick={run} disabled={busy}>
              {busy ? "Running…" : "Run backtest"}
            </button>
          </div>
          <p className="muted-text">
            Runs on demand — a study fetches {symbols.split(",").length + 1} price
            histories and re-runs the engine once per sweep cell.
          </p>
        </div>
      </section>

      {err && <div className="error">backtest: {err}</div>}
      {data && <Report data={data} />}
    </>
  );
}

function Report({ data }) {
  const rows = data.curves.dates.map((d, i) => ({
    date: d,
    strategy: data.curves.strategy[i],
    bh_basket: data.curves.bh_basket[i],
    bh_spy: data.curves.bh_spy[i],
    strategy_dd: data.curves.strategy_dd[i],
  }));

  return (
    <>
      <section style={{ marginTop: 16 }}>
        <div className="panel">
          <h2>Growth of $1 (log scale)</h2>
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} />
              {/* Log scale: on a 5-year compounding chart a linear axis squashes
                  the early years into an unreadable flat line. */}
              <YAxis scale="log" domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={56} />
              <Tooltip
                contentStyle={{ background: "#1a1d24", border: "1px solid #2a2f3a" }}
                labelStyle={{ color: "#aaa" }}
                formatter={(v) => v.toFixed(3)}
              />
              <Legend />
              {SERIES.map((s) => (
                <Line
                  key={s.key} type="monotone" dataKey={s.key} name={s.name}
                  stroke={s.stroke} strokeDasharray={s.dash} strokeWidth={s.width} dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section style={{ marginTop: 16 }}>
        <div className="panel">
          <h2>Strategy drawdown</h2>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} />
              <YAxis tick={{ fontSize: 11 }} width={56} tickFormatter={fracPct} />
              <Tooltip
                contentStyle={{ background: "#1a1d24", border: "1px solid #2a2f3a" }}
                labelStyle={{ color: "#aaa" }}
                formatter={(v) => fracPct(v)}
              />
              <Area type="monotone" dataKey="strategy_dd" stroke="#ef4444" fill="#ef444433" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      <MetricsTable m={data.metrics} turnover={data.turnover} />
      <Heatmap monthly={data.monthly.strategy} />
      <SweepTable sweep={data.sweep} active={data.params} />
      <OosBlock oos={data.oos} />
      <Caveats items={data.caveats} />
    </>
  );
}

const ROWS = [
  ["CAGR", "cagr", fracPct],
  ["Volatility", "vol", fracPct],
  ["Sharpe", "sharpe", ratio],
  ["Sortino", "sortino", ratio],
  ["Max drawdown", "max_dd", fracPct],
  ["Calmar", "calmar", ratio],
  ["Hit rate", "hit_rate", fracPct],
  ["Best month", "best_month", fracPct],
  ["Worst month", "worst_month", fracPct],
];

function MetricsTable({ m, turnover }) {
  return (
    <section style={{ marginTop: 16 }}>
      <div className="panel">
        <h2>Performance</h2>
        <table>
          <thead>
            <tr><th>Metric</th><th>Strategy</th><th>Basket B&amp;H</th><th>SPY B&amp;H</th></tr>
          </thead>
          <tbody>
            {ROWS.map(([label, key, fmt]) => (
              <tr key={key}>
                <td>{label}</td>
                <td>{fmt(m.strategy[key])}</td>
                <td>{fmt(m.bh_basket[key])}</td>
                <td>{fmt(m.bh_spy[key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h2 style={{ marginTop: 16 }}>Strategy vs benchmark</h2>
        <table>
          <thead>
            <tr><th>Metric</th><th>vs Basket B&amp;H</th><th>vs SPY B&amp;H</th></tr>
          </thead>
          <tbody>
            <tr><td>Alpha (ann.)</td><td>{fracPct(m.vs_basket.alpha)}</td><td>{fracPct(m.vs_spy.alpha)}</td></tr>
            <tr><td>Beta</td><td>{ratio(m.vs_basket.beta)}</td><td>{ratio(m.vs_spy.beta)}</td></tr>
            <tr><td>Tracking error</td><td>{fracPct(m.vs_basket.tracking_error)}</td><td>{fracPct(m.vs_spy.tracking_error)}</td></tr>
            <tr><td>Information ratio</td><td>{ratio(m.vs_basket.information_ratio)}</td><td>{ratio(m.vs_spy.information_ratio)}</td></tr>
          </tbody>
        </table>
        <p className="muted-text">
          Annual turnover: {ratio(turnover.annual)}× · Sharpe and Sortino assume a 0% risk-free rate.
        </p>
      </div>
    </section>
  );
}

const MONTHS = ["01","02","03","04","05","06","07","08","09","10","11","12"];

function Heatmap({ monthly }) {
  const years = [...new Set(Object.keys(monthly).map((k) => k.slice(0, 4)))].sort();
  const scale = Math.max(...Object.values(monthly).map((v) => Math.abs(v)), 0.01);

  return (
    <section style={{ marginTop: 16 }}>
      <div className="panel">
        <h2>Monthly returns — strategy</h2>
        <div className="bt-heatmap" style={{ gridTemplateColumns: `48px repeat(12, 1fr)` }}>
          <div />
          {MONTHS.map((mo) => <div key={mo} className="bt-hm-head">{mo}</div>)}
          {years.map((y) => (
            <Row key={y} year={y} monthly={monthly} scale={scale} />
          ))}
        </div>
      </div>
    </section>
  );
}

function Row({ year, monthly, scale }) {
  return (
    <>
      <div className="bt-hm-head">{year}</div>
      {MONTHS.map((mo) => {
        const v = monthly[`${year}-${mo}`];
        const alpha = v == null ? 0 : Math.min(Math.abs(v) / scale, 1) * 0.75;
        const bg = v == null ? "transparent"
          : v >= 0 ? `rgba(34,197,94,${alpha})` : `rgba(239,68,68,${alpha})`;
        return (
          <div key={mo} className="bt-hm-cell" style={{ background: bg }}
               title={v == null ? "" : `${year}-${mo}: ${fracPct(v)}`}>
            {v == null ? "" : (v * 100).toFixed(1)}
          </div>
        );
      })}
    </>
  );
}

function SweepTable({ sweep, active }) {
  const isActive = (p) => JSON.stringify(p) === JSON.stringify(active);
  return (
    <section style={{ marginTop: 16 }}>
      <div className="panel">
        <h2>Parameter sweep</h2>
        <p className="muted-text">
          Not a search for the best setting. A rule that only works at one parameter
          value is a curve fit — this table is how you see that.
        </p>
        <table>
          <thead><tr><th>Params</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th></tr></thead>
          <tbody>
            {sweep.map((row, i) => (
              <tr key={i} className={isActive(row.params) ? "bt-active" : ""}>
                <td>{Object.entries(row.params).map(([k, v]) => `${k}=${v}`).join(" ")}</td>
                <td>{fracPct(row.cagr)}</td>
                <td>{ratio(row.sharpe)}</td>
                <td>{fracPct(row.max_dd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function OosBlock({ oos }) {
  if (!oos.in_sample) {
    return (
      <section style={{ marginTop: 16 }}>
        <div className="panel">
          <h2>In / out of sample</h2>
          <p className="muted-text">Window too short to split.</p>
        </div>
      </section>
    );
  }
  return (
    <section style={{ marginTop: 16 }}>
      <div className="panel">
        <h2>In / out of sample</h2>
        <p className="muted-text">
          Split at {oos.split_date}. An edge that appears only in-sample has not
          been validated out-of-sample.
        </p>
        <table>
          <thead><tr><th>Metric</th><th>In-sample (60%)</th><th>Out-of-sample (40%)</th></tr></thead>
          <tbody>
            {ROWS.map(([label, key, fmt]) => (
              <tr key={key}>
                <td>{label}</td>
                <td>{fmt(oos.in_sample[key])}</td>
                <td>{fmt(oos.out_sample[key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Caveats({ items }) {
  return (
    <section style={{ marginTop: 16 }}>
      <div className="panel">
        <h2>What this study does not prove</h2>
        <ul className="muted-text">
          {items.map((c, i) => <li key={i} style={{ marginBottom: 8 }}>{c}</li>)}
        </ul>
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Add the styles**

Append to `frontend/src/styles.css`:

```css
.bt-controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.bt-controls label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #9aa4b2; }
.bt-controls input, .bt-controls select {
  background: #12151b; border: 1px solid #2a2f3a; color: #e6e6e6;
  padding: 6px 8px; border-radius: 4px; font-size: 13px;
}
.bt-controls input[type="number"] { width: 90px; }
.bt-controls label:first-child { flex: 1 1 320px; }
.bt-controls label:first-child input { width: 100%; }
.bt-controls button {
  background: #2563eb; border: 0; color: #fff; padding: 8px 16px;
  border-radius: 4px; cursor: pointer; font-size: 13px;
}
.bt-controls button:disabled { background: #374151; cursor: default; }

.bt-heatmap { display: grid; gap: 2px; font-size: 11px; }
.bt-hm-head { color: #9aa4b2; text-align: center; padding: 2px; }
.bt-hm-cell { text-align: center; padding: 4px 2px; border-radius: 2px; }
tr.bt-active td { outline: 1px solid #4ea1ff; }
```

- [ ] **Step 4: Wire it into App.jsx**

Add the import alongside the other component imports at the top of `frontend/src/App.jsx`:

```javascript
import Backtest from "./components/Backtest.jsx";
```

Add the branch inside `<main className="main">`, after the `news` line:

```javascript
        {view === "backtest" && <Backtest />}
```

- [ ] **Step 5: Verify in the browser**

The sidebar's Backtest-Lab entry currently opens a blank pane; this step confirms it no longer does.

Run the dev server (hot reload, so edits appear on save) from `frontend/`:
```
npm run dev
```
Open http://localhost:5173, select **Backtest-Lab**, press **Run backtest**.

Confirm:
- Three curves render, all starting at 1.0, on a log axis.
- The drawdown area sits below zero and returns to zero at new highs.
- The metrics table has no `NaN` or `—` in the strategy column.
- The sweep table highlights the row matching the controls.
- The caveats block is visible without expanding anything.

Note: `start.bat` serves the **production build** from `dist/`, so changes will not appear there until `npm run build` runs. Use `npm run dev` while iterating.

- [ ] **Step 6: Verify the production build compiles**

Run from `frontend/`:
```
npm run build
```
Expected: build succeeds with no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api.js frontend/src/components/Backtest.jsx frontend/src/App.jsx frontend/src/styles.css
git commit -m "Add Backtest Lab view"
```

---

## Self-Review

**Spec coverage:** Data layer (adjusted close, inner join, cache) → Task 1. Metrics + relative → Task 2. Simulator, costs, lookahead shift → Task 3. Both rules, bh_basket monthly rebalance, bh_spy, sweep, OOS, caveats → Task 4. API with validation and error codes → Task 5. All eight UI blocks, log axis, colorblind-safe series → Task 6.

**Deviation from the spec, deliberate:** the spec listed six test cases; this plan has fourteen, because the simulator needed drift and cash-handling coverage that the spec's list did not name. The spec's test 3 (lookahead guard) is `test_engine_does_not_read_the_future` and remains the most important test in the file.

**Type consistency:** `panel()` is the public accessor everywhere (with `_panel_cached` behind it and `panel.cache_clear` aliased for the tests). `simulate()` returns `(equity, turnover)` at every call site. Metric keys in `ROWS` on the frontend match the dict `metrics()` returns. `params` keys are `window` for sma, `n`/`lookback` for momentum, consistently across `build_targets`, `SWEEP_GRID`, and the UI.
