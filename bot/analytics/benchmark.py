"""Бенчмарк: те же взносы, равные веса по всему core-universe (buy & rebalance monthly)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bot.config import Config
from bot.data.moex_iss import OhlcBar, fetch_history, fetch_index_history, prices_on
from bot.portfolio.executor import buy_with_rules, sell_with_rules
from bot.portfolio.state import PortfolioState, SleeveState


@dataclass
class BenchmarkResult:
    final_equity: float
    contributed: float
    profit_rub: float
    return_pct: float


def run_equal_weight_benchmark(
    config: Config,
    start: date,
    end: date,
    initial_capital: float,
    monthly_deposit: float,
) -> BenchmarkResult:
    tickers = list(config.core_universe)
    histories: dict[str, dict[date, OhlcBar]] = {
        t: fetch_history(t, start, end) for t in tickers
    }
    index = fetch_index_history(config.market_index, start, end)
    days = sorted(
        d for d in set().union(index.keys(), *[h.keys() for h in histories.values()])
        if start <= d <= end
    )
    if not days:
        raise RuntimeError("No trading days for benchmark")

    core_cash = initial_capital * config.core_weight
    state = PortfolioState(
        core=SleeveState(cash_rub=core_cash),
        satellite=SleeveState(cash_rub=initial_capital * config.satellite_weight),
        initial_equity=initial_capital,
        peak_equity=initial_capital,
        equity_at_last_rebalance=initial_capital,
        last_rebalance_at="",
        last_scheduled_rebalance_at="",
        satellite_month_start_equity=0.0,
        satellite_baseline_equity=0.0,
        month_key=days[0].strftime("%Y-%m"),
    )
    total_deposits = 0.0
    prev_month = days[0].strftime("%Y-%m")
    first_month = prev_month

    def _rebalance_equal(day: date) -> None:
        prices = prices_on(histories, tickers, day)
        if not prices:
            return
        n = len([t for t in tickers if t in prices])
        if n == 0:
            return
        w = 1.0 / n
        eq = state.core.equity(prices)
        for t in list(state.core.positions.keys()):
            if t not in tickers:
                px = prices.get(t)
                if px:
                    sell_with_rules(state.core, "core", t, px, config, 1.0, min_trade_override=0)
        for t in tickers:
            px = prices.get(t)
            if not px:
                continue
            target = eq * w
            pos = state.core.positions.get(t)
            cur = pos.qty * px if pos else 0.0
            delta = target - cur
            if delta > config.min_trade_rub:
                buy_with_rules(
                    state.core, "core", t, px, min(delta, state.core.cash_rub * 0.99), config
                )
            elif delta < -config.min_trade_rub and pos:
                frac = min(1.0, abs(delta) / cur) if cur > 0 else 1.0
                sell_with_rules(state.core, "core", t, px, config, frac, min_trade_override=0)

    _rebalance_equal(days[0])

    for day in days:
        month = day.strftime("%Y-%m")
        if month != prev_month:
            if month != first_month:
                state.core.cash_rub += monthly_deposit * config.core_weight
                state.satellite.cash_rub += monthly_deposit * config.satellite_weight
                total_deposits += monthly_deposit
                _rebalance_equal(day)
            prev_month = month

    prices = prices_on(histories, tickers, days[-1])
    final = state.core.equity(prices) + state.satellite.equity(prices)
    contributed = initial_capital + total_deposits
    profit = final - contributed
    return BenchmarkResult(
        final_equity=final,
        contributed=contributed,
        profit_rub=profit,
        return_pct=(profit / contributed * 100) if contributed else 0.0,
    )
