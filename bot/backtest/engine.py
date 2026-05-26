"""Walk-forward replay: та же логика, что paper, на истории MOEX."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

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

REPORT_CSV = Path("data/paper_replay_report.csv")


@dataclass
class MonthlySnapshot:
    month: str
    total_equity: float
    universe: str
    contributed_cumulative: float
    trading_pnl: float
    fill_tier: str = ""


@dataclass
class ReplayResult:
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
    imoex_final_equity: float
    imoex_return_pct: float
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


def _imoex_dca_equity(
    index: dict[date, float],
    month_starts: list[date],
    initial: float,
    monthly_deposit: float,
) -> float:
    """DCA в индекс: покупка на close первого торгового дня каждого месяца."""
    cash = initial
    qty = 0.0
    for i, day in enumerate(month_starts):
        if i > 0:
            cash += monthly_deposit
        px = index.get(day)
        if px is None:
            prior = sorted(d for d in index if d <= day)
            px = index[prior[-1]] if prior else None
        if not px or px <= 0:
            continue
        qty += cash / px
        cash = 0.0
    last = month_starts[-1]
    prior = sorted(d for d in index if d <= last)
    last_px = index[prior[-1]] if prior else 0.0
    return qty * last_px


def run_paper_replay(
    config: Config,
    start: date,
    end: date,
    initial_capital: float,
    monthly_deposit: float,
) -> ReplayResult:
    preload_start = start - timedelta(days=config.forecast_train_days + 150)
    try:
        snap = fetch_tqbr_market_snapshot()
        liquid = sorted(snap, key=lambda s: s.valtoday_rub, reverse=True)
        scan_candidates = [s.ticker for s in liquid[: config.scan_liquid_pool]]
    except Exception:
        scan_candidates = list(config.core_universe)

    all_tickers = list(set(scan_candidates + config.core_universe))
    logger.info("Preloading %d tickers (%s → %s)…", len(all_tickers), preload_start, end)
    histories = _preload_histories(all_tickers, preload_start, end)

    index = fetch_index_history(config.market_index, preload_start, end)
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
        total_deposits_rub=0.0,
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
    last_fill_tier = ""
    monthly_rows: list[MonthlySnapshot] = []
    core_cash_pcts: list[float] = []
    month_start_days: list[date] = []

    dividends_by_day = (
        load_dividends_by_day(all_tickers, preload_start, end) if config.include_dividends else {}
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
            month_start_days.append(day)
            report = scan_promising_stocks(config, day, histories=histories)
            last_fill_tier = report.fill_tier
            if report.picks:
                active_universe = [p.ticker for p in report.picks]
                logger.info(
                    "Universe %s [%s]: %d names — %s",
                    month,
                    last_fill_tier,
                    len(active_universe),
                    ",".join(active_universe[:8]) + ("…" if len(active_universe) > 8 else ""),
                )

            if month != first_month:
                state.core.cash_rub += monthly_deposit
                state.total_deposits_rub += monthly_deposit
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
                fill_tier=last_fill_tier,
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

    imoex_final = _imoex_dca_equity(
        index, month_start_days or [trading_days[0]], initial_capital, monthly_deposit
    )
    imoex_ret = (imoex_final - contributed) / contributed * 100 if contributed else 0

    by_month: dict[str, MonthlySnapshot] = {}
    for row in monthly_rows:
        by_month[row.month] = row

    return ReplayResult(
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
        imoex_final_equity=imoex_final,
        imoex_return_pct=imoex_ret,
        monthly=list(by_month.values()),
    )


# alias for backtest entrypoint
run_backtest = run_paper_replay
BacktestResult = ReplayResult


def print_report(result: ReplayResult, config: Config) -> None:
    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "equity", "universe_sample", "contributed", "pnl", "fill_tier"])
        for row in result.monthly:
            w.writerow(
                [
                    row.month,
                    round(row.total_equity, 2),
                    row.universe,
                    round(row.contributed_cumulative, 2),
                    round(row.trading_pnl, 2),
                    row.fill_tier,
                ]
            )

    alpha = result.return_on_contributed_pct - result.imoex_return_pct
    print("\n" + "=" * 72)
    print("PAPER REPLAY — walk-forward на истории MOEX (логика = paper-бот)")
    print("=" * 72)
    print(f"Period:     {result.start} → {result.end}")
    print(
        f"Config:     scan top-{config.scan_top_n} / hold top-{config.core_top_n} | "
        f"adaptive={config.scan_adaptive_fill} min_universe={config.scan_min_universe}"
    )
    print(f"Contributed:{result.total_contributed:,.0f} RUB → Final {result.final_equity:,.0f} RUB")
    print(f"Profit:     {result.profit_rub:+,.0f} RUB ({result.return_on_contributed_pct:+.2f}%)")
    print(
        f"IMOEX DCA:  {result.imoex_final_equity:,.0f} RUB ({result.imoex_return_pct:+.2f}%) | "
        f"alpha {alpha:+.2f} pp"
    )
    print(f"Dividends:  +{result.total_dividends_net:,.0f} | Fees −{result.total_commissions:,.0f}")
    print(f"Real (est): {result.real_profit_rub:+,.0f} RUB | Max DD {result.max_drawdown_pct:.1f}%")
    print(f"Idle cash:  avg {result.avg_core_cash_pct:.1f}%")
    print(
        f"Trades:     rebalance {result.core_rebalance_trades}"
        f" | forecast exits {result.forecast_exit_trades}"
    )
    print(f"CSV:        {REPORT_CSV}")
    print("=" * 72 + "\n")
