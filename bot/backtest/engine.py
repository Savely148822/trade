"""Симуляция стратегии на исторических данных MOEX."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bot.analytics.benchmark import run_equal_weight_benchmark
from bot.config import Config
from bot.data.moex_dividends import load_dividends_by_day
from bot.data.moex_iss import (
    OhlcBar,
    closes_before,
    fetch_history,
    fetch_index_history,
    ohlc_before,
    prices_on,
)
from bot.portfolio.core_portfolio import rebalance_core_portfolio
from bot.portfolio.dividends import apply_daily_dividends
from bot.portfolio.executor import apply_satellite_signal
from bot.portfolio.rebalancer import (
    rebalance_portfolio,
    rebalance_satellite_profit_trim,
    should_rebalance_satellite_profit,
)
from bot.portfolio.state import PortfolioState, SleeveState
from bot.risk.manager import check_risk
from bot.strategies.satellite_breakout import SatelliteAction, evaluate_satellite

logger = logging.getLogger(__name__)

REPORT_CSV = Path("data/backtest_report.csv")


@dataclass
class MonthlySnapshot:
    month: str
    total_equity: float
    core_equity: float
    satellite_equity: float
    deposits_cumulative: float
    contributed_cumulative: float
    trading_pnl: float
    core_pct: float
    satellite_pct: float


@dataclass
class BacktestResult:
    start: date
    end: date
    initial_capital: float
    total_deposits: float
    total_contributed: float
    final_equity: float
    final_core: float
    final_satellite: float
    profit_rub: float
    core_profit_rub: float
    satellite_profit_rub: float
    return_on_contributed_pct: float
    max_drawdown_pct: float
    trades: int
    core_rebalance_trades: int
    satellite_trades: int
    total_commissions: float
    total_dividends_net: float
    inflation_drag_rub: float
    real_profit_rub: float
    benchmark_final: float
    benchmark_return_pct: float
    monthly: list[MonthlySnapshot] = field(default_factory=list)


def _index_regime_ok(index: dict[date, float], day: date, period: int) -> bool:
    closes = [index[d] for d in sorted(index) if d <= day]
    if len(closes) < period:
        return False
    sma = sum(closes[-period:]) / period
    return closes[-1] > sma


def _ticker_above_sma(series: dict[date, OhlcBar], day: date, period: int) -> bool:
    closes = closes_before(series, day, period + 1)
    if len(closes) < period:
        return False
    sma = sum(closes[-period:]) / period
    return closes[-1] > sma


def run_backtest(
    config: Config,
    start: date,
    end: date,
    initial_capital: float,
    monthly_deposit: float,
) -> BacktestResult:
    tickers = list(set(config.core_universe + config.satellite_universe))
    logger.info("Loading MOEX history %s … %s for %d tickers", start, end, len(tickers))

    histories: dict[str, dict[date, OhlcBar]] = {}
    for t in tickers:
        histories[t] = fetch_history(t, start, end)
        logger.info("  %s: %d days", t, len(histories[t]))

    index = fetch_index_history(config.market_index, start, end)
    dividends_by_day = (
        load_dividends_by_day(tickers, start, end) if config.include_dividends else {}
    )

    trading_days = sorted(set().union(index.keys(), *[h.keys() for h in histories.values()]))
    trading_days = [d for d in trading_days if start <= d <= end]
    if not trading_days:
        raise RuntimeError("No trading days in range")

    state = PortfolioState(
        core=SleeveState(cash_rub=initial_capital * config.core_weight),
        satellite=SleeveState(cash_rub=initial_capital * config.satellite_weight),
        initial_equity=initial_capital,
        peak_equity=initial_capital,
        equity_at_last_rebalance=initial_capital,
        last_rebalance_at="",
        last_scheduled_rebalance_at="",
        satellite_month_start_equity=initial_capital * config.satellite_weight,
        satellite_baseline_equity=initial_capital * config.satellite_weight,
        month_key=trading_days[0].strftime("%Y-%m"),
    )

    core_trades = sat_trades = 0
    total_deposits = 0.0
    total_commissions = 0.0
    total_dividends = 0.0
    max_dd = 0.0
    first_month = trading_days[0].strftime("%Y-%m")
    prev_month = first_month
    daily_monthly: list[tuple[str, float, float, float, float]] = []

    prices0 = prices_on(histories, tickers, trading_days[0])
    if prices0:
        ct, cf = rebalance_core_portfolio(
            state, prices0, histories, trading_days[0], config, tag="INIT"
        )
        core_trades += ct
        total_commissions += cf

    for day in trading_days:
        prices = prices_on(histories, tickers, day)
        if not prices:
            continue

        div_net = apply_daily_dividends(state, dividends_by_day.get(day, []), config)
        total_dividends += div_net

        month = day.strftime("%Y-%m")
        if month != prev_month:
            if month != first_month:
                state.core.cash_rub += monthly_deposit * config.core_weight
                state.satellite.cash_rub += monthly_deposit * config.satellite_weight
                total_deposits += monthly_deposit
                ct, cf = rebalance_core_portfolio(
                    state,
                    prices,
                    histories,
                    day,
                    config,
                    tag="MONTHLY",
                )
                core_trades += ct
                total_commissions += cf
                prices = prices_on(histories, tickers, day)
                rebalance_portfolio(state, prices, config)
            prev_month = month

        prices = prices_on(histories, tickers, day)
        equity = state.total_equity(prices)
        if equity > state.peak_equity:
            state.peak_equity = equity
        dd = (state.peak_equity - equity) / state.peak_equity * 100 if state.peak_equity else 0
        max_dd = max(max_dd, dd)

        profit_hit, _ = should_rebalance_satellite_profit(
            state, prices, config.satellite_profit_rebalance_pct
        )
        if profit_hit:
            rebalance_satellite_profit_trim(state, prices, config)
            prices = prices_on(histories, tickers, day)

        risk = check_risk(
            state,
            prices,
            config.max_drawdown_pct,
            config.satellite_monthly_loss_cap_pct,
        )

        allow_sat = (
            risk.allow_satellite
            and _index_regime_ok(index, day, config.satellite_index_sma_period)
            and equity >= config.satellite_min_equity_rub
        )
        if allow_sat:
            for ticker in config.satellite_universe:
                series = histories.get(ticker, {})
                if not _ticker_above_sma(series, day, config.satellite_ticker_sma_period):
                    continue
                bars = ohlc_before(
                    series,
                    day,
                    max(
                        config.satellite_breakout_bars + config.satellite_atr_period + 30,
                        config.satellite_ticker_sma_period + 10,
                    ),
                )
                if len(bars) < config.satellite_breakout_bars + 5:
                    continue
                sig = evaluate_satellite(
                    ticker,
                    [b.high for b in bars],
                    [b.low for b in bars],
                    [b.close for b in bars],
                    [b.volume for b in bars],
                    config.satellite_breakout_bars,
                    config.satellite_atr_period,
                    config.satellite_min_rvol,
                    config.satellite_require_close_confirm,
                )
                if sig and sig.action != SatelliteAction.HOLD:
                    r = apply_satellite_signal(state, sig, config)
                    if r:
                        sat_trades += 1
                        total_commissions += r.commission_rub

        prices = prices_on(histories, tickers, day)
        core_eq = state.core.equity(prices)
        sat_eq = state.satellite.equity(prices)
        equity = core_eq + sat_eq
        contributed_so_far = initial_capital + total_deposits
        daily_monthly.append((month, equity, core_eq, sat_eq, contributed_so_far))

    prices = prices_on(histories, tickers, trading_days[-1])
    final_core = state.core.equity(prices)
    final_sat = state.satellite.equity(prices)
    final = final_core + final_sat
    contributed = initial_capital + total_deposits
    profit = final - contributed

    core_contributed = initial_capital * config.core_weight + total_deposits * config.core_weight
    sat_contributed = initial_capital * config.satellite_weight + total_deposits * config.satellite_weight
    core_profit = final_core - core_contributed
    sat_profit = final_sat - sat_contributed

    years = max((trading_days[-1] - trading_days[0]).days / 365.25, 0.01)
    infl_mult = (1 + config.inflation_annual_pct / 100) ** years
    inflation_drag = contributed * (infl_mult - 1)
    real_profit = profit - total_commissions - inflation_drag

    by_month: dict[str, tuple[float, float, float, float]] = {}
    for m, eq, c, s, contrib in daily_monthly:
        by_month[m] = (eq, c, s, contrib)

    monthly: list[MonthlySnapshot] = []
    for m in sorted(by_month.keys()):
        eq, c, s, contrib = by_month[m]
        monthly.append(
            MonthlySnapshot(
                month=m,
                total_equity=eq,
                core_equity=c,
                satellite_equity=s,
                deposits_cumulative=contrib - initial_capital,
                contributed_cumulative=contrib,
                trading_pnl=eq - contrib,
                core_pct=(c / eq * 100) if eq else 0,
                satellite_pct=(s / eq * 100) if eq else 0,
            )
        )

    bench = run_equal_weight_benchmark(
        config, start, end, initial_capital, monthly_deposit
    )

    return BacktestResult(
        start=trading_days[0],
        end=trading_days[-1],
        initial_capital=initial_capital,
        total_deposits=total_deposits,
        total_contributed=contributed,
        final_equity=final,
        final_core=final_core,
        final_satellite=final_sat,
        profit_rub=profit,
        core_profit_rub=core_profit,
        satellite_profit_rub=sat_profit,
        return_on_contributed_pct=(profit / contributed * 100) if contributed else 0,
        max_drawdown_pct=max_dd,
        trades=core_trades + sat_trades,
        core_rebalance_trades=core_trades,
        satellite_trades=sat_trades,
        total_commissions=total_commissions,
        total_dividends_net=total_dividends,
        inflation_drag_rub=inflation_drag,
        real_profit_rub=real_profit,
        benchmark_final=bench.final_equity,
        benchmark_return_pct=bench.return_pct,
        monthly=monthly,
    )


def _ascii_bar(value: float, max_value: float, width: int = 36) -> str:
    if max_value <= 0:
        return ""
    filled = int(round(value / max_value * width))
    return "█" * filled + "░" * (width - filled)


def save_report_csv(result: BacktestResult, path: Path = REPORT_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "month",
                "total_rub",
                "core_rub",
                "satellite_rub",
                "core_pct",
                "satellite_pct",
                "deposits_cumulative",
                "contributed_cumulative",
                "trading_pnl",
            ]
        )
        for row in result.monthly:
            w.writerow(
                [
                    row.month,
                    round(row.total_equity, 2),
                    round(row.core_equity, 2),
                    round(row.satellite_equity, 2),
                    round(row.core_pct, 1),
                    round(row.satellite_pct, 1),
                    round(row.deposits_cumulative, 2),
                    round(row.contributed_cumulative, 2),
                    round(row.trading_pnl, 2),
                ]
            )


def print_report(result: BacktestResult, config: Config) -> None:
    save_report_csv(result)

    print("\n" + "=" * 72)
    print("BACKTEST REPORT (акции MOEX, cross-sectional core)")
    print("=" * 72)
    print(f"Period:        {result.start} → {result.end}")
    print(f"Core:          top {config.core_top_n} by {config.core_momentum_months}m momentum, 1/σ weights")
    print(f"Dividends:     {'да' if config.include_dividends else 'нет'} (налог {config.dividend_tax_pct:.0f}%)")
    print(f"Start capital: {result.initial_capital:,.0f} RUB")
    print(f"Deposits:      {result.total_deposits:,.0f} RUB")
    print(f"Contributed:   {result.total_contributed:,.0f} RUB")
    print(f"Final equity:  {result.final_equity:,.0f} RUB")
    print(f"  Core:        {result.final_core:,.0f} RUB")
    print(f"  Satellite:   {result.final_satellite:,.0f} RUB")
    print(f"Profit (nominal): {result.profit_rub:+,.0f} RUB ({result.return_on_contributed_pct:+.2f}%)")
    print(f"Dividends (net):  +{result.total_dividends_net:,.0f} RUB")
    print(f"Commissions:      −{result.total_commissions:,.0f} RUB")
    print(
        f"Benchmark (equal-weight core, same flows): "
        f"{result.benchmark_final:,.0f} RUB ({result.benchmark_return_pct:+.2f}%)"
    )
    alpha = result.return_on_contributed_pct - result.benchmark_return_pct
    print(f"vs benchmark:     {alpha:+.2f} pp")
    print(f"Inflation (~{config.inflation_annual_pct:.0f}%/y): −{result.inflation_drag_rub:,.0f} RUB (est.)")
    real_pct = (result.real_profit_rub / result.total_contributed * 100) if result.total_contributed else 0
    print(f"≈ Real result:    {result.real_profit_rub:+,.0f} RUB ({real_pct:+.2f}%)")
    print(f"Max drawdown:     {result.max_drawdown_pct:.1f}%")
    print(
        f"Trades:           {result.trades} "
        f"(core rebalance {result.core_rebalance_trades}, sat {result.satellite_trades})"
    )

    print("\n--- Monthly: total / core / satellite ---")
    print(f"{'Month':<8} {'Total':>10} {'Core':>10} {'Sat':>10} {'Trading PnL':>12}")
    print("-" * 60)
    for row in result.monthly:
        print(
            f"{row.month:<8} {row.total_equity:>10,.0f} {row.core_equity:>10,.0f} "
            f"{row.satellite_equity:>10,.0f} {row.trading_pnl:>+12,.0f}"
        )

    totals = [r.total_equity for r in result.monthly]
    max_eq = max(totals) if totals else 1
    print("\n--- Equity chart (end of month) ---")
    for row in result.monthly:
        bar = _ascii_bar(row.total_equity, max_eq)
        print(f"  {row.month}  {bar}  {row.total_equity:,.0f}")

    print(f"\nCSV: {REPORT_CSV}")
    print("=" * 72 + "\n")
