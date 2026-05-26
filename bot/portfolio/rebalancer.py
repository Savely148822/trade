"""Периодический пересчёт капитала и деление core / satellite."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.portfolio.executor import _sell
from bot.portfolio.state import PortfolioState

logger = logging.getLogger(__name__)

TOLERANCE_PCT = 1.5  # не трогаем, если отклонение меньше %


@dataclass
class RebalanceReport:
    total_equity: float
    equity_at_last_rebalance: float
    pnl_rub: float
    pnl_pct: float
    core_equity_before: float
    satellite_equity_before: float
    core_equity_after: float
    satellite_equity_after: float
    target_core: float
    target_satellite: float
    cash_moved_to_core: float
    satellite_sold_rub: float
    message: str


def should_rebalance(state: PortfolioState, interval_sec: int) -> bool:
    if not state.last_rebalance_at:
        return True
    try:
        last = datetime.fromisoformat(state.last_rebalance_at)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= interval_sec


def rebalance_portfolio(
    state: PortfolioState,
    prices: dict[str, float],
    core_weight: float,
    satellite_weight: float,
) -> RebalanceReport:
    total = state.total_equity(prices)
    equity_at_last = state.equity_at_last_rebalance or state.initial_equity
    pnl_rub = total - equity_at_last
    pnl_pct = (pnl_rub / equity_at_last * 100) if equity_at_last else 0.0

    core_before = state.core.equity(prices)
    sat_before = state.satellite.equity(prices)
    target_core = total * core_weight
    target_sat = total * satellite_weight

    cash_moved_to_core = 0.0
    satellite_sold_rub = 0.0

    core_pct = (core_before / total * 100) if total else 0
    sat_pct = (sat_before / total * 100) if total else 0
    target_core_pct = core_weight * 100
    target_sat_pct = satellite_weight * 100

    logger.info(
        "REBALANCE report | total=%.0f RUB | PnL since last: %+.0f RUB (%+.2f%%)",
        total,
        pnl_rub,
        pnl_pct,
    )
    logger.info(
        "  Before: core=%.0f (%.1f%%) | satellite=%.0f (%.1f%%)",
        core_before,
        core_pct,
        sat_before,
        sat_pct,
    )
    logger.info(
        "  Target: core=%.0f (%.0f%%) | satellite=%.0f (%.0f%%)",
        target_core,
        target_core_pct,
        target_sat,
        target_sat_pct,
    )

    # 1) Satellite перевес — продаём позиции, переводим кэш в core
    sat_eq = state.satellite.equity(prices)
    if total > 0 and sat_eq > target_sat * (1 + TOLERANCE_PCT / 100):
        excess = sat_eq - target_sat
        satellite_sold_rub = _reduce_satellite_positions(state, prices, excess)
        sat_eq = state.satellite.equity(prices)

    # 2) Перевод кэша: satellite → core
    if sat_eq > target_sat and state.satellite.cash_rub > 0:
        transfer = min(sat_eq - target_sat, state.satellite.cash_rub)
        state.satellite.cash_rub -= transfer
        state.core.cash_rub += transfer
        cash_moved_to_core += transfer

    # 3) Перевод кэша: core → satellite (если satellite недовес)
    sat_eq = state.satellite.equity(prices)
    core_eq = state.core.equity(prices)
    if sat_eq < target_sat * (1 - TOLERANCE_PCT / 100):
        need = target_sat - sat_eq
        transfer = min(need, state.core.cash_rub)
        if transfer > 0:
            state.core.cash_rub -= transfer
            state.satellite.cash_rub += transfer
            cash_moved_to_core -= transfer

    core_after = state.core.equity(prices)
    sat_after = state.satellite.equity(prices)

    state.equity_at_last_rebalance = total
    state.last_rebalance_at = datetime.now(timezone.utc).isoformat()

    msg = (
        f"After: core={core_after:.0f} ({core_after/total*100:.1f}%), "
        f"sat={sat_after:.0f} ({sat_after/total*100:.1f}%)"
        if total
        else "empty portfolio"
    )
    logger.info("  %s", msg)
    if cash_moved_to_core:
        logger.info("  Cash to core: %+.0f RUB", cash_moved_to_core)
    if satellite_sold_rub:
        logger.info("  Sold from satellite: %.0f RUB", satellite_sold_rub)

    return RebalanceReport(
        total_equity=total,
        equity_at_last_rebalance=equity_at_last,
        pnl_rub=pnl_rub,
        pnl_pct=pnl_pct,
        core_equity_before=core_before,
        satellite_equity_before=sat_before,
        core_equity_after=core_after,
        satellite_equity_after=sat_after,
        target_core=target_core,
        target_satellite=target_sat,
        cash_moved_to_core=cash_moved_to_core,
        satellite_sold_rub=satellite_sold_rub,
        message=msg,
    )


def _reduce_satellite_positions(
    state: PortfolioState,
    prices: dict[str, float],
    rub_target: float,
) -> float:
    """Продаёт satellite-позиции на сумму до rub_target."""
    sold = 0.0
    for ticker in sorted(
        state.satellite.positions.keys(),
        key=lambda t: state.satellite.positions[t].qty * prices.get(t, 0),
        reverse=True,
    ):
        if sold >= rub_target:
            break
        px = prices.get(ticker)
        if not px:
            continue
        pos = state.satellite.positions[ticker]
        value = pos.qty * px
        need = rub_target - sold
        fraction = min(1.0, need / value) if value > 0 else 1.0
        result = _sell(state.satellite, "satellite", ticker, px, fraction)
        if result:
            sold += result.rub
    if sold > 0:
        transfer = min(sold, state.satellite.cash_rub)
        state.satellite.cash_rub -= transfer
        state.core.cash_rub += transfer
    return sold
