"""Симуляция core-only: ежемесячный скан MOEX + портфель top-N."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date

from bot.analytics.monthly_scan import scan_promising_stocks
from bot.config import Config
from bot.data.moex_dividends import load_dividends_by_day
from bot.data.moex_iss import (
    OhlcBar,
    fetch_history,
    fetch_index_history,
    prices_on,
)
from bot.data.moex_market import fetch_tqbr_market_snapshot
from bot.data.macro import build_macro_snapshot
from bot.portfolio.core_portfolio import rebalance_core_portfolio
from bot.portfolio.dividends import apply_daily_dividends
from bot.portfolio.forecast_exits import apply_forecast_exits
from bot.portfolio.state import PortfolioState, SleeveState

logger = logging.getLogger(__name__)

from pathlib import Path

REPORT_CSV = Path("data/backtest_report.csv")


@dataclass
class MonthlySnapshot:
    month: str
    total_equity: float
    universe: str
    contributed_cumulative: float
    trading_pnl: float


@dataclass
class BacktestResult:
    start: date
    end: date
    initial_capital: float
    total_deposits: float
    total_contributed: float
    final_equity: float
    profit_rub: float
    return_on_contributed_pct: float
    max_drawdown_pct: float
    core_rebalance_trades: int
    forecast_exit_trades: int
    total_commissions: float
    total_dividends_net: float
    inflation_drag_rub: float
    real_profit_rub: float
    avg_core_cash_pct: float
    monthly: list[MonthlySnapshot] = field(default_factory=list)


def _preload_histories(
    tickers: list[str], start: date, end: date
) -> dict[str, dict[date, OhlcBar]]:
    histories: dict[str, dict[date, OhlcBar]] = {}
    for t in tickers:
        h = fetch_history(t, start, end)
        if len(h) > 60:
            histories[t] = h
    return histories


def run_backtest(
    config: Config,
    start: date,
    end: date,
    initial_capital: float,
    monthly_deposit: float,
) -> BacktestResult:
    # Кандидаты для walk-forward: текущий ликвидный список + core_universe
    try:
        snap = fetch_tqbr_market_snapshot()
        liquid = sorted(snap, key=lambda s: s.valtoday_rub, reverse=True)
        scan_candidates = [s.ticker for s in liquid[: config.scan_liquid_pool]]
    except Exception:
        scan_candidates = list(config.core_universe)

    all_tickers = list(set(scan_candidates + config.core_universe))
    logger.info("Preloading history for %d tickers…", len(all_tickers))
    histories = _preload_histories(all_tickers, start, end)

    index = fetch_index_history(config.market_index, start, end)
    trading_days = sorted(set().union(index.keys(), *[h.keys() for h in histories.values()]))
    trading_days = [d for d in trading_days if start <= d <= end]
    if not trading_days:
        raise RuntimeError("No trading days in range")

    state = PortfolioState(
        core=SleeveState(cash_rub=initial_capital),
        satellite=SleeveState(cash_rub=0.0),
        initial_equity=initial_capital,
        peak_equity=initial_capital,
        equity_at_last_rebalance=initial_capital,
        last_rebalance_at="",
        last_scheduled_rebalance_at="",
        satellite_month_start_equity=0.0,
        satellite_baseline_equity=0.0,
        month_key=trading_days[0].strftime("%Y-%m"),
    )

    core_trades = 0
    exit_trades = 0
    total_deposits = 0.0
    total_commissions = 0.0
    total_dividends = 0.0
    max_dd = 0.0
    first_month = trading_days[0].strftime("%Y-%m")
    prev_month = first_month
    active_universe = list(config.core_universe)
    monthly_rows: list[MonthlySnapshot] = []
    core_cash_pcts: list[float] = []

    dividends_by_day = (
        load_dividends_by_day(all_tickers, start, end) if config.include_dividends else {}
    )

    for day in trading_days:
        prices = prices_on(histories, all_tickers, day)
        if not prices:
            continue

        total_dividends += apply_daily_dividends(state, dividends_by_day.get(day, []), config)

        if state.core.positions and config.exit_on_negative_forecast:
            et, ef = apply_forecast_exits(
                state,
                prices,
                histories,
                config,
                day,
                index_series=index,
                macro=build_macro_snapshot(day, config.market_index),
            )
            exit_trades += et
            total_commissions += ef

        month = day.strftime("%Y-%m")
        if month != prev_month:
            report = scan_promising_stocks(config, day, histories=histories)
            if report.picks:
                active_universe = [p.ticker for p in report.picks]
                logger.info("Universe %s: %s", month, ",".join(active_universe))

            if month != first_month:
                state.core.cash_rub += monthly_deposit
                total_deposits += monthly_deposit

            ct, cf = rebalance_core_portfolio(
                state,
                prices,
                histories,
                day,
                config,
                universe=active_universe,
                tag="MONTHLY" if month != first_month else "INIT",
            )
            core_trades += ct
            total_commissions += cf
            prev_month = month

        equity = state.core.equity(prices)
        if equity > state.peak_equity:
            state.peak_equity = equity
        dd = (state.peak_equity - equity) / state.peak_equity * 100 if state.peak_equity else 0
        max_dd = max(max_dd, dd)
        if equity > 0:
            core_cash_pcts.append(state.core.cash_rub / equity * 100)

        contributed = initial_capital + total_deposits
        monthly_rows.append(
            MonthlySnapshot(
                month=month,
                total_equity=equity,
                universe=",".join(active_universe[:5]) + ("…" if len(active_universe) > 5 else ""),
                contributed_cumulative=contributed,
                trading_pnl=equity - contributed,
            )
        )

    prices = prices_on(histories, all_tickers, trading_days[-1])
    final = state.core.equity(prices)
    contributed = initial_capital + total_deposits
    profit = final - contributed

    years = max((trading_days[-1] - trading_days[0]).days / 365.25, 0.01)
    infl_mult = (1 + config.inflation_annual_pct / 100) ** years
    inflation_drag = contributed * (infl_mult - 1)
    real_profit = profit - total_commissions - inflation_drag

    by_month: dict[str, MonthlySnapshot] = {}
    for row in monthly_rows:
        by_month[row.month] = row

    return BacktestResult(
        start=trading_days[0],
        end=trading_days[-1],
        initial_capital=initial_capital,
        total_deposits=total_deposits,
        total_contributed=contributed,
        final_equity=final,
        profit_rub=profit,
        return_on_contributed_pct=(profit / contributed * 100) if contributed else 0,
        max_drawdown_pct=max_dd,
        core_rebalance_trades=core_trades,
        forecast_exit_trades=exit_trades,
        total_commissions=total_commissions,
        total_dividends_net=total_dividends,
        inflation_drag_rub=inflation_drag,
        real_profit_rub=real_profit,
        avg_core_cash_pct=(sum(core_cash_pcts) / len(core_cash_pcts)) if core_cash_pcts else 0,
        monthly=list(by_month.values()),
    )


def print_report(result: BacktestResult, config: Config) -> None:
    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "equity", "universe_sample", "contributed", "pnl"])
        for row in result.monthly:
            w.writerow(
                [
                    row.month,
                    round(row.total_equity, 2),
                    row.universe,
                    round(row.contributed_cumulative, 2),
                    round(row.trading_pnl, 2),
                ]
            )

    print("\n" + "=" * 72)
    print("BACKTEST — core 100%, monthly MOEX scan → top 20, hold top 5")
    print("=" * 72)
    print(f"Period:     {result.start} → {result.end}")
    print(f"Holdings:   top {config.core_top_n} from scan top {config.scan_top_n}")
    print(f"Dividends:  {'on' if config.include_dividends else 'off'} (tax {config.dividend_tax_pct:.0f}%)")
    print(f"Contributed:{result.total_contributed:,.0f} RUB → Final {result.final_equity:,.0f} RUB")
    print(f"Profit:     {result.profit_rub:+,.0f} RUB ({result.return_on_contributed_pct:+.2f}%)")
    print(f"Dividends:  +{result.total_dividends_net:,.0f} | Fees −{result.total_commissions:,.0f}")
    print(f"Real (est): {result.real_profit_rub:+,.0f} RUB | Max DD {result.max_drawdown_pct:.1f}%")
    print(f"Idle cash:  avg {result.avg_core_cash_pct:.1f}%")
    print(
        f"Trades:     rebalance {result.core_rebalance_trades}"
        f" | forecast exits {result.forecast_exit_trades}"
    )
    print(f"CSV:        {REPORT_CSV}")
    print("=" * 72 + "\n")
