"""Quant research: annual return by S&P 500 GICS sector, proxied by SPDR
sector ETFs. Standalone script, run directly — not a FastAPI endpoint.

    .venv/Scripts/python -m research.sector_returns
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from market import get_history

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}


def _price_series(symbol: str, period: str) -> pd.Series:
    rows = get_history(symbol, period=period, interval="1d")
    s = pd.Series(
        {row["date"]: row["close"] for row in rows},
        dtype=float,
    )
    s.index = pd.to_datetime(s.index)
    return s


def annual_returns(symbol: str, period: str = "10y") -> pd.Series:
    """Year -> price return, % (close-to-close, last trading day of each year)."""
    year_end = _price_series(symbol, period).resample("YE").last()
    return year_end.pct_change().dropna() * 100


def monthly_returns(symbol: str, period: str = "10y") -> pd.Series:
    """Month -> price return, % (close-to-close, last trading day of each month)."""
    month_end = _price_series(symbol, period).resample("ME").last()
    r = month_end.pct_change().dropna() * 100
    return r.set_axis(r.index.strftime("%Y-%m"))


@dataclass
class Drawdown:
    pct: float  # deepest peak-to-trough decline, % (always <= 0)
    peak: object  # index label where the run-up preceding the drawdown topped out
    trough: object  # index label of the deepest point


def max_drawdown(pct_returns: pd.Series) -> Drawdown:
    cum = (1 + pct_returns / 100).cumprod()
    running_peak = cum.cummax()
    drawdown = (cum - running_peak) / running_peak
    trough = drawdown.idxmin()
    peak = cum.loc[:trough].idxmax()
    return Drawdown(pct=drawdown.min() * 100, peak=peak, trough=trough)


def downside_deviation(pct_returns: pd.Series, mar: float = 0.0) -> float:
    """Annualized std of returns that fall below MAR (minimum acceptable
    return, % per period). Upside swings don't count against it."""
    shortfall = pct_returns.clip(upper=mar) - mar  # 0 where return >= mar
    monthly_dd = (shortfall ** 2).mean() ** 0.5
    return monthly_dd * (12 ** 0.5)


def beta(pct_returns: pd.Series, market_returns: pd.Series) -> float:
    """Regression slope of sector return on market return: how many % the
    sector moves per 1% the market moves. 1.0 = moves with market."""
    aligned = pd.concat([pct_returns, market_returns], axis=1, join="inner").dropna()
    cov = aligned.cov().iloc[0, 1]
    market_var = aligned.iloc[:, 1].var()
    return cov / market_var


@dataclass
class TTestResult:
    mean_excess_pct: float  # avg (sector - market) return per year, %
    t_stat: float
    p_value: float
    n: int


def paired_ttest(sector_annual: pd.Series, market_annual: pd.Series) -> TTestResult:
    """H0: sector's mean annual excess return over the market is 0.
    One-sample t-test on the per-year (sector - market) differences —
    'paired' because each year is its own before/after pair, controlling
    for whatever the market did that year."""
    aligned = pd.concat([sector_annual, market_annual], axis=1, join="inner").dropna()
    excess = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    t_stat, p_value = stats.ttest_1samp(excess, popmean=0)
    return TTestResult(mean_excess_pct=excess.mean(), t_stat=t_stat, p_value=p_value, n=len(excess))


def main() -> None:
    annual, monthly = {}, {}
    for symbol, name in SECTOR_ETFS.items():
        label = f"{name} ({symbol})"
        try:
            r = annual_returns(symbol)
            annual[label] = r.set_axis(r.index.year)
            monthly[label] = monthly_returns(symbol)
        except Exception as e:
            print(f"skip {symbol}: {e}")

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)

    df = pd.DataFrame(annual).round(1)
    print(df.T)  # sector rows, year columns

    print("\nMean annual return, ranked:")
    print(df.mean().sort_values(ascending=False).round(1))

    m = pd.DataFrame(monthly)
    spy_monthly = monthly_returns("SPY")
    ann_mean = m.mean() * 12
    ann_vol = m.std() * (12 ** 0.5)
    # ponytail: rf=0 (no T-bill fetch). Shifts absolute Sharpe values but not
    # the ranking, since it's a constant subtracted from every sector alike.
    dd = {label: max_drawdown(m[label].dropna()) for label in m.columns}
    max_dd = pd.Series({label: d.pct for label, d in dd.items()})
    downside_vol = pd.Series({label: downside_deviation(m[label].dropna()) for label in m.columns})
    beta_vs_spy = pd.Series({label: beta(m[label], spy_monthly) for label in m.columns})
    summary = pd.DataFrame({
        "annualized_return_%": ann_mean,
        "annualized_vol_%": ann_vol,
        "beta_vs_spy": beta_vs_spy,
        "sharpe": ann_mean / ann_vol,
        "sortino": ann_mean / downside_vol,
        "max_drawdown_%": max_dd,
        "dd_peak": pd.Series({label: d.peak for label, d in dd.items()}),
        "dd_trough": pd.Series({label: d.trough for label, d in dd.items()}),
        "calmar": ann_mean / max_dd.abs(),
    }).round(2)
    print("\nAnnualized return / vol / Sharpe / max DD (peak->trough) / Calmar, ranked by Sharpe:")
    print(summary.sort_values("sharpe", ascending=False))

    spy_annual = annual_returns("SPY")
    spy_annual = spy_annual.set_axis(spy_annual.index.year)
    ttests = {label: paired_ttest(df[label], spy_annual) for label in df.columns}
    ttest_df = pd.DataFrame({
        "mean_excess_return_%_per_yr": {l: r.mean_excess_pct for l, r in ttests.items()},
        "t_stat": {l: r.t_stat for l, r in ttests.items()},
        "p_value": {l: r.p_value for l, r in ttests.items()},
        "n_years": {l: r.n for l, r in ttests.items()},
    }).round(3)
    print("\nPaired t-test vs SPY (H0: mean annual excess return = 0), ranked by t_stat:")
    print(ttest_df.sort_values("t_stat", ascending=False))


if __name__ == "__main__":
    main()
