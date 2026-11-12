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
    # Exit on the crash row itself. shift=0 acts on the crash day's own close and
    # so escapes the -50%; shift=1 can only sell the day after, and eats it. Put
    # the exit any earlier and both paths dodge the crash, which proves nothing.
    targets = _targets_like(px, {0: {"AAA": 1.0}, 3: {"AAA": 0.0}})
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


def test_count_entries_counts_flat_to_invested_transitions():
    px = _prices({"AAA": [10.0] * 6})
    # flat -> in (row 0) -> out (row 2) -> in (row 4): two entries, not three rows.
    targets = _targets_like(px, {0: {"AAA": 1.0}, 2: {"AAA": 0.0}, 4: {"AAA": 1.0}})
    assert backtest.count_entries(targets) == 2, backtest.count_entries(targets)


def test_count_entries_ignores_resizes_while_already_invested():
    px = _prices({"AAA": [10.0] * 4, "BBB": [10.0] * 4})
    # Already invested at row 0; row 2 just reweights, it's not a fresh entry.
    targets = _targets_like(px, {0: {"AAA": 1.0, "BBB": 0.0}, 2: {"AAA": 0.5, "BBB": 0.5}})
    assert backtest.count_entries(targets) == 1, backtest.count_entries(targets)


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


if __name__ == "__main__":
    test_panel_uses_adjusted_close_not_rounded_close()
    test_panel_inner_joins_to_the_shorter_series()
    test_panel_result_is_safe_to_mutate()
    test_metrics_on_constant_drift_match_closed_form()
    test_max_drawdown_is_peak_to_trough()
    test_monthly_returns_are_keyed_by_month()
    test_beta_of_a_curve_against_itself_is_one()
    test_full_allocation_tracks_the_asset_exactly()
    test_zero_weights_are_cash_and_never_move()
    test_costs_reduce_terminal_equity_and_show_up_as_turnover()
    test_engine_does_not_read_the_future()
    test_holdings_drift_between_rebalances()
    test_sma_rule_sits_out_the_crash()
    test_momentum_holds_only_the_top_n()
    test_momentum_never_ranks_a_symbol_with_short_history()
    test_month_ends_are_the_last_trading_day()
    test_count_entries_counts_flat_to_invested_transitions()
    test_count_entries_ignores_resizes_while_already_invested()
    test_build_targets_rejects_an_unknown_rule()
    test_run_study_returns_three_aligned_curves()
    print("ok")
