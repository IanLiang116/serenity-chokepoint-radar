from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DOCS_DIR = APP_DIR / "docs"
SIGNAL_FILE = DATA_DIR / "momentum_strategy_signals.csv"
REPORT_FILE = DOCS_DIR / "momentum_strategy_report.md"

HEADERS = {"User-Agent": "Mozilla/5.0 SerenityRadar/3.0"}
RISK_ASSETS = ("QQQ", "SPY")
DEFENSIVE_ASSET = "SHY"
DEFAULT_SYMBOLS = (*RISK_ASSETS, DEFENSIVE_ASSET)


@dataclass(frozen=True)
class StrategyStats:
    name: str
    cagr: float
    volatility: float
    sharpe: float
    max_drawdown: float
    growth_multiple: float


def yahoo_adjusted_close(
    symbol: str,
    start: date = date(2007, 1, 1),
    end: date | None = None,
) -> pd.Series:
    if end is None:
        end = datetime.now(timezone.utc).date()
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    period2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    response = requests.get(url, params=params, headers=HEADERS, timeout=20)
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    if not adjusted:
        adjusted = result["indicators"]["quote"][0]["close"]
    series = pd.Series(adjusted, index=pd.to_datetime(timestamps, unit="s"), name=symbol)
    return series.dropna().sort_index()


def load_price_history(symbols: Iterable[str] = DEFAULT_SYMBOLS) -> pd.DataFrame:
    prices = {symbol: yahoo_adjusted_close(symbol) for symbol in symbols}
    return pd.DataFrame(prices).dropna()


def completed_monthly_prices(daily_prices: pd.DataFrame, as_of: date | None = None) -> pd.DataFrame:
    if as_of is None:
        as_of = datetime.now(timezone.utc).date()
    monthly = daily_prices.resample("ME").last().dropna()
    current_month_start = pd.Timestamp(as_of.replace(day=1))
    return monthly[monthly.index < current_month_start]


def monthly_signal(monthly_prices: pd.DataFrame) -> pd.DataFrame:
    returns_12m = monthly_prices.pct_change(12)
    rows = []
    for idx in range(12, len(monthly_prices) - 1):
        signal_date = monthly_prices.index[idx]
        next_month = monthly_prices.index[idx + 1]
        momentum = returns_12m.iloc[idx]
        ranked = momentum[list(RISK_ASSETS)].sort_values(ascending=False)
        best_risk_asset = str(ranked.index[0])
        use_risk = momentum[best_risk_asset] > momentum[DEFENSIVE_ASSET] and momentum[best_risk_asset] > 0
        holding = best_risk_asset if use_risk else DEFENSIVE_ASSET
        period_return = monthly_prices[holding].pct_change().loc[next_month]
        rows.append(
            {
                "signal_date": signal_date.date().isoformat(),
                "holding_month": next_month.date().isoformat(),
                "holding": holding,
                "qqq_12m_return": float(momentum["QQQ"]),
                "spy_12m_return": float(momentum["SPY"]),
                "shy_12m_return": float(momentum["SHY"]),
                "strategy_return": float(period_return),
            }
        )
    return pd.DataFrame(rows)


def current_signal(monthly_prices: pd.DataFrame) -> dict[str, object]:
    if len(monthly_prices) < 13:
        raise ValueError("Need at least 13 completed monthly prices to produce a 12-month signal.")
    returns_12m = monthly_prices.pct_change(12).iloc[-1]
    ranked = returns_12m[list(RISK_ASSETS)].sort_values(ascending=False)
    best_risk_asset = str(ranked.index[0])
    use_risk = returns_12m[best_risk_asset] > returns_12m[DEFENSIVE_ASSET] and returns_12m[best_risk_asset] > 0
    holding = best_risk_asset if use_risk else DEFENSIVE_ASSET
    return {
        "signal_date": monthly_prices.index[-1].date().isoformat(),
        "recommended_holding": holding,
        "best_risk_asset": best_risk_asset,
        "qqq_12m_return": float(returns_12m["QQQ"]),
        "spy_12m_return": float(returns_12m["SPY"]),
        "shy_12m_return": float(returns_12m["SHY"]),
    }


def performance_stats(name: str, returns: pd.Series) -> StrategyStats:
    returns = returns.dropna().astype(float)
    equity = (1 + returns).cumprod()
    years = (returns.index[-1] - returns.index[0]).days / 365.25
    cagr = equity.iloc[-1] ** (1 / years) - 1
    volatility = returns.std() * math.sqrt(12)
    sharpe = (returns.mean() * 12) / volatility if volatility else float("nan")
    drawdown = equity / equity.cummax() - 1
    return StrategyStats(
        name=name,
        cagr=float(cagr),
        volatility=float(volatility),
        sharpe=float(sharpe),
        max_drawdown=float(drawdown.min()),
        growth_multiple=float(equity.iloc[-1]),
    )


def backtest(monthly_prices: pd.DataFrame) -> tuple[pd.DataFrame, list[StrategyStats]]:
    signals = monthly_signal(monthly_prices)
    strategy_returns = pd.Series(
        signals["strategy_return"].to_list(),
        index=pd.to_datetime(signals["holding_month"]),
        name="QQQ_SPY_momentum",
    )
    monthly_returns = monthly_prices.pct_change().dropna().loc[strategy_returns.index]
    stats = [
        performance_stats("QQQ/SPY 12M momentum", strategy_returns),
        performance_stats("SPY buy and hold", monthly_returns["SPY"]),
        performance_stats("QQQ buy and hold", monthly_returns["QQQ"]),
        performance_stats("60/40 SPY/SHY monthly", 0.6 * monthly_returns["SPY"] + 0.4 * monthly_returns["SHY"]),
    ]
    return signals, stats


def pct(value: float) -> str:
    return f"{value:.2%}"


def write_report(signals: pd.DataFrame, stats: list[StrategyStats], signal: dict[str, object]) -> None:
    REPORT_FILE.parent.mkdir(exist_ok=True)
    stats_rows = "\n".join(
        f"| {item.name} | {pct(item.cagr)} | {pct(item.volatility)} | "
        f"{item.sharpe:.2f} | {pct(item.max_drawdown)} | {item.growth_multiple:.2f}x |"
        for item in stats
    )
    latest_rows = "\n".join(
        f"| {row.signal_date} | {row.holding_month} | {row.holding} | {pct(row.strategy_return)} |"
        for row in signals.tail(12).itertuples(index=False)
    )
    text = f"""# Momentum Strategy Report

Updated: {datetime.now(timezone.utc).date().isoformat()}

## Objective

Build a repeatable stock-market strategy that targets long-term 10%+ annualized returns and attempts to beat the broad U.S. market without relying on daily prediction or discretionary stock picking.

## Selected strategy

Use a monthly dual-momentum rule across `QQQ`, `SPY`, and `SHY`.

1. On the final completed month, calculate 12-month total return for `QQQ`, `SPY`, and `SHY`.
2. If the stronger of `QQQ` and `SPY` has positive 12-month return and beats `SHY`, hold that stronger risk asset for the next month.
3. Otherwise hold `SHY`.
4. Rebalance once per month only.

## Latest completed-month signal

- Signal date: `{signal["signal_date"]}`
- Recommended holding: `{signal["recommended_holding"]}`
- Best risk asset: `{signal["best_risk_asset"]}`
- QQQ 12-month return: {pct(float(signal["qqq_12m_return"]))}
- SPY 12-month return: {pct(float(signal["spy_12m_return"]))}
- SHY 12-month return: {pct(float(signal["shy_12m_return"]))}

## Backtest summary

The backtest uses Yahoo adjusted daily closes, converts them to completed month-end prices, and applies the signal to the following month.

| Strategy | CAGR | Volatility | Sharpe | Max drawdown | Growth of $1 |
|---|---:|---:|---:|---:|---:|
{stats_rows}

## Last 12 monthly holdings

| Signal date | Holding month | Holding | Monthly return |
|---|---:|---:|---:|
{latest_rows}

## Risk controls

- This is not a guarantee of profit. The edge can decay, especially because `QQQ` has benefited from a strong technology regime.
- The strategy should be reviewed monthly, not daily.
- A practical starting allocation is 50%-70% of investable capital, with the rest in cash or short-duration bonds.
- Stop using the strategy for new capital if the live drawdown exceeds the historical max drawdown by a large margin, for example worse than -25% to -30%, until the rules are reviewed.
- Do not mix this signal with impulsive single-stock trades. Individual stock ideas from the Serenity scanner should be treated as a separate satellite sleeve.

## How to rerun

```powershell
python strategy.py --write
```
"""
    REPORT_FILE.write_text(text, encoding="utf-8")


def run(write: bool = False) -> tuple[pd.DataFrame, list[StrategyStats], dict[str, object]]:
    daily = load_price_history()
    monthly = completed_monthly_prices(daily)
    signals, stats = backtest(monthly)
    signal = current_signal(monthly)
    if write:
        DATA_DIR.mkdir(exist_ok=True)
        signals.to_csv(SIGNAL_FILE, index=False)
        write_report(signals, stats, signal)
    return signals, stats, signal


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the QQQ/SPY monthly momentum strategy backtest.")
    parser.add_argument("--write", action="store_true", help="Write CSV signals and Markdown report.")
    args = parser.parse_args()
    _, stats, signal = run(write=args.write)
    print(f"Signal date: {signal['signal_date']}")
    print(f"Recommended holding: {signal['recommended_holding']}")
    for item in stats:
        print(
            f"{item.name}: CAGR={pct(item.cagr)}, Vol={pct(item.volatility)}, "
            f"Sharpe={item.sharpe:.2f}, MaxDD={pct(item.max_drawdown)}, Growth={item.growth_multiple:.2f}x"
        )
    if args.write:
        print(f"Wrote {SIGNAL_FILE}")
        print(f"Wrote {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
