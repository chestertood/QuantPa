# Backtest Lab — SaaS Basket vs Buy-and-Hold — Design

## Purpose
The sidebar has a `backtest` / "Backtest-Lab" entry (`frontend/src/components/Sidebar.jsx:7`)
but `App.jsx` has no `view === "backtest"` branch, so selecting it renders an empty pane.

Goal: a quantitative-research view that tests whether a timing rule applied to a basket of
SaaS/cloud stocks beats buy-and-hold — measured against two separate benchmarks, presented
as a tearsheet with robustness checks and an explicit statement of the study's biases.

The research question, stated plainly: **does the timing rule add value (strategy vs basket
buy-and-hold), and does the sector bet add value (basket vs SPY buy-and-hold)?** Three equity
curves separate timing alpha from sector alpha. A single benchmark cannot.

## Non-goals
- Live/paper trading, order routing, or any write path to a broker.
- Intraday data. Daily bars only.
- Optimizing a strategy to find the "best" parameters. The sweep exists to show fragility,
  not to select a winner.

## Architecture

```
POST /api/backtest  {symbols, benchmark, rule, params, years, cost_bps}
  -> backtest.run_study(...)
       _panel(symbols + benchmark, years)      # adjusted-close DataFrame, cached
       -> equity curves:  bh_spy | bh_basket | strategy
       -> metrics(curve) for each              # curve-only, rule-agnostic
       -> sweep(rule, grid)                    # same engine, many params
       -> oos_split(curves)                    # 60/40 in/out of sample
  -> {curves, metrics, sweep, oos, turnover, caveats}
  -> Backtest.jsx renders (recharts)
```

New files: `backend/backtest.py`, `backend/test_backtest.py`,
`frontend/src/components/Backtest.jsx`.
Modified: `backend/main.py` (one route), `frontend/src/App.jsx` (one branch).
No new dependencies — pandas, numpy, scipy are installed backend-side; recharts frontend-side.

---

## 1. Data layer

### The adjusted-close problem
`market.get_history()` (`backend/market.py:296`) returns **raw close, rounded to 2 decimals**.
Both properties make it unfit for backtesting:

- **Raw close ignores splits.** A 2:1 split appears as a −50% single-day return. NVDA-style
  split history would destroy any strategy's measured performance.
- **Raw close ignores dividends.** Total return is understated for every dividend payer,
  which biases the SPY benchmark downward and flatters the (mostly non-paying) SaaS basket.
- **2dp rounding** is invisible on a chart and material over 2500 compounding days.

Yahoo's chart response already carries `indicators.adjclose[0].adjclose`, which `get_history`
discards.

**Do not change `get_history`.** Its callers (`/api/positions/{symbol}/history`, `PriceChart`)
want raw display prices, and the 2dp rounding is deliberate for that use. Instead
`backtest.py` calls the existing `market._fetch_chart(symbol, rng, interval)` — reusing the
session, browser impersonation, and symbol normalization — and reads `adjclose` unrounded.

### `_panel(symbols: tuple[str, ...], years: int) -> pd.DataFrame`
- One `_fetch_chart` call per symbol, `rng=f"{years}y"`, `interval="1d"`.
- Index: `DatetimeIndex` of dates. Columns: symbols. Values: unrounded adjusted close.
- **Inner join across symbols** so every series shares one calendar. A symbol that IPO'd
  mid-window would otherwise inject NaNs that silently propagate into returns.
- Note in the response how many rows survived the join and the effective start date —
  adding a young ticker (e.g. a 2020 IPO) truncates the whole study, and that must be
  visible rather than surprising.
- `@lru_cache(maxsize=8)` on `(symbols, years)`. The parameter sweep runs the engine ~15
  times; it must not re-hit Yahoo 15 times. Tuple args, not lists, so the key hashes.

### Universe
Default basket (editable in the UI as a comma-separated field):
`CRM, NOW, ADBE, SNOW, DDOG, TEAM, WDAY, ZS, HUBS, MDB`
Default benchmark: `SPY`. Default window: 5 years.

---

## 2. Strategy engine

All three curves derive from daily adjusted-close simple returns and are normalized to 1.0
on the first shared date, so they are directly comparable on one axis.

### `bh_spy`
SPY buy-and-hold. `(1 + r_spy).cumprod()`.

### `bh_basket`
Equal-weight basket, rebalanced monthly. A literal never-rebalance basket drifts into a
concentrated bet on whichever name ran hardest and stops being a basket, which makes it a
dishonest control for an equal-weight strategy. Monthly rebalancing is the matched passive
baseline.

### `strategy` — basket + selected rule

**Rule A — `sma` (trend filter).**
Build the basket's equal-weight index. Hold the full basket on days when the index closed
above its `window`-day SMA (default 200) **as of the prior close**; otherwise hold cash at
0% return.

**Rule B — `momentum` (cross-sectional rotation).**
On the last trading day of each month, rank basket members by return over `t−lookback
months → t−1 month`. Hold the top `N` equal-weight for the following month.
The one-month gap is deliberate: including the most recent month picks up short-term
reversal and inflates measured momentum performance. Members without full lookback history
are excluded from the ranking — never treated as a zero return, which would rank them
mid-pack and quietly enter positions on no information.

### Lookahead prevention
Every signal is computed from data through close *t* and applied to returns from *t+1*
onward — one `.shift(1)` on the weights frame, applied in a single place inside `run()` so
no rule can forget it. This is the defect that makes a backtest look excellent and be
worthless; it is the primary target of the test suite (§5).

### Transaction costs
`cost_bps` (default 5) charged against turnover on each rebalance:
`turnover_t = 0.5 * Σ|w_t − w_{t−1}|`, cost subtracted from that day's return. Turnover is
reported per strategy. Monthly momentum rotation looks dramatically better at zero cost
than it trades in practice, so costs are on by default rather than an optional extra.

### Interface
```python
run(prices: pd.DataFrame, rule: str, params: dict, cost_bps: float)
    -> (equity: pd.Series, weights: pd.DataFrame, turnover: pd.Series)
```
Metrics never see the rule, the params, or the weights — they take an equity curve and
nothing else, so all three curves are scored by identical code.

---

## 3. Metrics and robustness

### `metrics(equity: pd.Series) -> dict`
CAGR, annualized volatility, Sharpe (risk-free = 0, stated in the UI), Sortino, max drawdown,
Calmar, hit rate (share of positive days), best month, worst month.
252 trading days/year.

### `relative(strategy: pd.Series, benchmark: pd.Series) -> dict`
Alpha (annualized), beta, tracking error, information ratio — computed for the strategy
against each of the two benchmarks.

### Robustness — what separates this from a demo

**Parameter sweep.** `sma`: window ∈ {50, 100, 150, 200, 250}. `momentum`: N ∈ {2, 3, 5} ×
lookback ∈ {3, 6, 12} months. Each cell reports CAGR / Sharpe / MaxDD. The point is
diagnostic: a rule that only works at exactly one parameter value is a curve fit, and a
table makes that visible immediately.

**In/out-of-sample split.** First 60% of the date range vs the last 40%, metrics reported
separately for each. A strategy whose edge appears only in the first segment has not been
validated by the second.

**Caveats — rendered in the UI, not left in a source comment.**
1. **Survivorship bias, and it is the largest error in this study.** The basket is selected
   in 2026 with full knowledge of which SaaS companies survived. Names that collapsed,
   delisted, or were acquired at a loss are absent. Every return reported here is biased
   upward, and the bias is not small. A point-in-time index constituent list would be
   required to remove it, and this study does not have one.
2. Costs are a flat bps charge on turnover — no slippage, no market impact, no bid/ask.
3. No taxes. Momentum rotation generates short-term gains; a taxable account keeps less.
4. Dividends are handled via adjusted close, which assumes frictionless reinvestment.
5. One sample, one market regime, non-overlapping. The window is a single draw from history.

---

## 4. API

`POST /api/backtest`

Request:
```json
{"symbols": ["CRM","NOW"], "benchmark": "SPY", "rule": "sma",
 "params": {"window": 200}, "years": 5, "cost_bps": 5}
```

Response:
```json
{"curves": {"dates": [...], "strategy": [...], "bh_basket": [...], "bh_spy": [...]},
 "metrics": {"strategy": {...}, "bh_basket": {...}, "bh_spy": {...},
             "vs_basket": {...}, "vs_spy": {...}},
 "monthly": {"strategy": {"2024-01": 0.031, ...}},
 "sweep": [{"params": {...}, "cagr": ..., "sharpe": ..., "max_dd": ...}],
 "oos": {"in_sample": {...}, "out_sample": {...}, "split_date": "2024-02-01"},
 "turnover": {"annual": 3.2}, "start_date": "2021-08-04", "n_days": 1258,
 "caveats": [...]}
```

POST rather than GET: the body is a nested object, and the response is a computed study
rather than a cacheable resource. Validation via a pydantic model, consistent with the
existing FastAPI routes — symbol count capped (20), `years` capped (20), `cost_bps` bounded
[0, 100]. Symbols are passed to Yahoo, so they are constrained to `[A-Za-z0-9.\- ]` and
length-capped before any outbound request is built.

Errors: an unknown or delisted symbol yields a 400 naming the symbol, not a 500. Yahoo being
unreachable yields 502.

---

## 5. Frontend

`frontend/src/components/Backtest.jsx`, wired into `App.jsx` at `view === "backtest"`.

Layout, top to bottom:
1. **Controls** — symbols field, benchmark, rule dropdown (`SMA filter` / `Momentum top-N`),
   rule-specific params, years, cost bps, Run button. Runs on demand, not on mount: the
   study takes seconds and hits Yahoo N times.
2. **Equity curves** — recharts `LineChart`, **log y-axis** (a linear axis on a 5-year
   compounding chart makes early performance unreadable), three series, shared tooltip.
3. **Underwater plot** — `AreaChart` of drawdown beneath, same x-domain.
4. **Metrics table** — three columns (strategy, basket B&H, SPY B&H) plus the relative block.
5. **Monthly return heatmap** — CSS grid, years × months, diverging color scale.
6. **Sweep table** — selected cell marked.
7. **In/out-of-sample block.**
8. **Caveats block** — visible on the page, not collapsed by default.

Follows existing conventions: `panel` / `card` / `muted-text` classes from `styles.css`,
number formatting through `format.js` (`money`, `pct`, `cls`).

Chart color usage follows the project's existing chart styling; the strategy series is
visually dominant and the two benchmarks are muted, and the three series are distinguishable
without relying on color alone (dash patterns), since the up/down red-green already in use
is not colorblind-safe on its own.

---

## 6. Testing

`backend/test_backtest.py`, matching the existing `test_*.py` style. **Synthetic price series
with closed-form answers — no live Yahoo calls in tests**, so the suite is deterministic and
runs offline.

1. **Constant drift.** +0.1%/day for 252 days → CAGR matches `1.001**252 − 1`, max drawdown
   is exactly 0, vol is 0.
2. **Crash avoidance.** A series that rises 200 days then falls 40% → the SMA rule exits
   before the bottom; strategy max drawdown is strictly smaller than buy-and-hold's.
3. **Lookahead guard.** Re-run the engine with the signal shifted by −1 (deliberately
   peeking). Results must come out *better* than the correct +1 shift. If they do not, the
   shift is wired wrong and the engine is reading the future. This is the single most
   important test in the file.
4. **Costs bite.** Identical inputs at `cost_bps=0` vs `cost_bps=100` → terminal equity is
   strictly lower with costs, and turnover is > 0 for the momentum rule.
5. **Panel alignment.** A short series joined against a long one → the panel starts at the
   later date and the reported `start_date` reflects it.
6. **Metric independence.** `metrics()` on a hand-built curve with a known drawdown returns
   that drawdown.

---

## Implementation order
1. `backtest.py` — `_panel`, `run`, `metrics` + tests 1, 3, 5, 6.
2. Rules (`sma`, `momentum`) + costs + tests 2, 4.
3. Sweep, OOS split, monthly aggregation.
4. `POST /api/backtest` in `main.py` with validation.
5. `Backtest.jsx` + `App.jsx` branch.

Each step is independently runnable and testable before the next begins.
