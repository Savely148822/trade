"""Симуляция стратегии на исторических данных MOEX."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from bot.config import Config
from bot.data.moex_iss import (
    OhlcBar,
    closes_before,
    fetch_history,
    fetch_index_history,
    ohlc_before,
    prices_on,
)
from bot.portfolio.executor import apply_core_signal, apply_satellite_signal
from bot.portfolio.rebalancer import (
    rebalance_portfolio,
    rebalance_satellite_profit_trim,
    should_rebalance_satellite_profit,
)
from bot.portfolio.state import PortfolioState, SleeveState
from bot.risk.manager import check_risk
from bot.strategies.core_momentum import CoreAction, evaluate_core
from bot.strategies.satellite_breakout import SatelliteAction, evaluate_satellite

logger = logging.getLogger(__name__)


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
    trades: int
    monthly_snapshots: list[tuple[str, float, float]] = field(default_factory=list)


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
    logger.info("Loading MOEX history %s … %s for %d tickers", start, end, len(tickers) + 1)

    histories: dict[str, dict[date, OhlcBar]] = {}
    for t in tickers:
        histories[t] = fetch_history(t, start, end)
        logger.info("  %s: %d days", t, len(histories[t]))

    index = fetch_index_history(config.market_index, start, end)
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

    trades = 0
    total_deposits = 0.0
    max_dd = 0.0
    prev_month = trading_days[0].strftime("%Y-%m")
    monthly_snapshots: list[tuple[str, float, float]] = []

    for day in trading_days:
        prices = prices_on(histories, tickers, day)
        if not prices:
            continue

        month = day.strftime("%Y-%m")
        if month != prev_month:
            state.core.cash_rub += monthly_deposit * config.core_weight
            state.satellite.cash_rub += monthly_deposit * config.satellite_weight
            total_deposits += monthly_deposit
            prev_month = month
            prices = prices_on(histories, tickers, day)
            rebalance_portfolio(
                state, prices, config.core_weight, config.satellite_weight
            )

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
            rebalance_satellite_profit_trim(state, prices, config.satellite_weight)
            prices = prices_on(histories, tickers, day)

        risk = check_risk(
            state,
            prices,
            config.max_drawdown_pct,
            config.satellite_monthly_loss_cap_pct,
        )

        core_signals = []
        for ticker in config.core_universe:
            series = histories.get(ticker, {})
            need = config.core_ma_slow + 30
            closes = closes_before(series, day, need)
            if len(closes) < config.core_ma_slow + 2:
                continue
            sig = evaluate_core(
                ticker,
                closes,
                config.core_ma_fast,
                config.core_ma_slow,
                config.core_momentum_months,
            )
            if sig:
                core_signals.append(sig)
                if sig.action in (CoreAction.SELL, CoreAction.TRIM):
                    if apply_core_signal(state, sig):
                        trades += 1

        buy_candidates = [s for s in core_signals if s.action == CoreAction.BUY]
        if buy_candidates:
            best = max(buy_candidates, key=lambda s: s.score)
            if apply_core_signal(state, best):
                trades += 1

        allow_sat = risk.allow_satellite and _index_regime_ok(
            index, day, config.satellite_index_sma_period
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
                    if apply_satellite_signal(state, sig):
                        trades += 1

        prices = prices_on(histories, tickers, day)
        equity = state.total_equity(prices)
        monthly_snapshots.append((month, equity, total_deposits))

    prices = prices_on(histories, tickers, trading_days[-1])
    final = state.total_equity(prices)
    contributed = initial_capital + total_deposits
    profit = final - contributed

    # dedupe monthly last per month
    by_month: dict[str, tuple[float, float]] = {}
    for m, eq, dep in monthly_snapshots:
        by_month[m] = (eq, dep)
    snaps = [(m, eq, dep) for m, (eq, dep) in sorted(by_month.items())]

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
        trades=trades,
        monthly_snapshots=snaps,
    )


def print_report(result: BacktestResult) -> None:
    print("\n" + "=" * 60)
    print("BACKTEST REPORT (MOEX ISS, paper rules)")
    print("=" * 60)
    print(f"Period:        {result.start} → {result.end}")
    print(f"Start capital: {result.initial_capital:,.0f} RUB")
    print(f"Deposits:      {result.total_deposits:,.0f} RUB (monthly top-ups)")
    print(f"Contributed:   {result.total_contributed:,.0f} RUB")
    print(f"Final equity:  {result.final_equity:,.0f} RUB")
    print(f"Profit:        {result.profit_rub:+,.0f} RUB")
    print(f"Return:        {result.return_on_contributed_pct:+.2f}% on contributed")
    print(f"Max drawdown:  {result.max_drawdown_pct:.1f}%")
    print(f"Trades:        {result.trades}")
    print("\nEnd of month:")
    for month, eq, dep in result.monthly_snapshots:
        print(f"  {month}  equity={eq:,.0f} RUB  (deposits so far {dep:,.0f})")
    print("=" * 60 + "\n")
