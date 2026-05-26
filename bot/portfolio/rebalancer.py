"""Периодический пересчёт капитала и деление core / satellite."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.config import Config
from bot.portfolio.executor import sell_with_rules
from bot.portfolio.state import PortfolioState, SleeveState

logger = logging.getLogger(__name__)

TOLERANCE_PCT = 1.5

# 30 суток — плановый ребаланс раз в месяц
MONTHLY_REBALANCE_SEC = 30 * 24 * 3600


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
    core_sold_rub: float
    trigger: str
    message: str


def should_rebalance_scheduled(state: PortfolioState, interval_sec: int) -> bool:
    last_at = state.last_scheduled_rebalance_at or state.last_rebalance_at
    if not last_at:
        return True
    try:
        last = datetime.fromisoformat(last_at)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= interval_sec


def should_rebalance_satellite_profit(
    state: PortfolioState,
    prices: dict[str, float],
    profit_pct: float,
) -> tuple[bool, str]:
    if profit_pct <= 0:
        return False, ""
    baseline = state.satellite_baseline_equity
    if baseline <= 0:
        return False, ""
    sat_eq = state.satellite.equity(prices)
    gain_pct = (sat_eq - baseline) / baseline * 100
    if gain_pct >= profit_pct:
        return (
            True,
            f"satellite +{gain_pct:.1f}% (baseline {baseline:.0f} → {sat_eq:.0f} RUB), "
            f"target {profit_pct:.0f}%",
        )
    return False, ""


def _reduce_sleeve_positions(
    sleeve: SleeveState,
    sleeve_name: str,
    prices: dict[str, float],
    rub_target: float,
    config: Config,
) -> float:
    sold = 0.0
    for ticker in sorted(
        sleeve.positions.keys(),
        key=lambda t: sleeve.positions[t].qty * prices.get(t, 0),
        reverse=True,
    ):
        if sold >= rub_target:
            break
        px = prices.get(ticker)
        if not px:
            continue
        pos = sleeve.positions[ticker]
        value = pos.qty * px
        need = rub_target - sold
        fraction = min(1.0, need / value) if value > 0 else 1.0
        result = sell_with_rules(
            sleeve,
            sleeve_name,
            ticker,
            px,
            config,
            fraction,
            tag="REBAL",
            min_trade_override=0,
        )
        if result:
            sold += result.rub
    return sold


def rebalance_satellite_profit_trim(
    state: PortfolioState,
    prices: dict[str, float],
    config: Config,
) -> RebalanceReport:
    satellite_weight = config.satellite_weight
    """Сливки с satellite до целевых 20% от total. Core-позиции не трогаем."""
    total = state.total_equity(prices)
    core_before = state.core.equity(prices)
    sat_before = state.satellite.equity(prices)
    target_sat = total * satellite_weight
    target_core = total * (1 - satellite_weight)

    cash_moved_to_core = 0.0
    satellite_sold_rub = 0.0

    logger.info(
        "REBALANCE [satellite_profit_trim] | total=%.0f | sat %.0f → target %.0f (%.0f%%)",
        total,
        sat_before,
        target_sat,
        satellite_weight * 100,
    )

    sat_eq = sat_before
    if sat_eq > target_sat * (1 + TOLERANCE_PCT / 100):
        excess = sat_eq - target_sat
        logger.info("  Trim satellite excess: %.0f RUB (positions stay in market)", excess)
        satellite_sold_rub = _reduce_sleeve_positions(
            state.satellite, "satellite", prices, excess, config
        )
        sat_eq = state.satellite.equity(prices)

    if sat_eq > target_sat and state.satellite.cash_rub > 0:
        transfer = min(sat_eq - target_sat, state.satellite.cash_rub)
        state.satellite.cash_rub -= transfer
        state.core.cash_rub += transfer
        cash_moved_to_core += transfer
        logger.info("  Cash to core: +%.0f RUB", transfer)

    sat_after = state.satellite.equity(prices)
    state.satellite_baseline_equity = sat_after

    core_after = state.core.equity(prices)
    msg = (
        f"Sat trim: {sat_before:.0f} → {sat_after:.0f} RUB "
        f"({sat_after/total*100:.1f}% of total), core untouched in stocks"
        if total
        else "empty"
    )
    logger.info("  %s", msg)
    logger.info("  New satellite baseline: %.0f RUB", state.satellite_baseline_equity)

    return RebalanceReport(
        total_equity=total,
        equity_at_last_rebalance=state.equity_at_last_rebalance,
        pnl_rub=0.0,
        pnl_pct=0.0,
        core_equity_before=core_before,
        satellite_equity_before=sat_before,
        core_equity_after=core_after,
        satellite_equity_after=sat_after,
        target_core=target_core,
        target_satellite=target_sat,
        cash_moved_to_core=cash_moved_to_core,
        satellite_sold_rub=satellite_sold_rub,
        core_sold_rub=0.0,
        trigger="satellite_profit_trim",
        message=msg,
    )


def rebalance_portfolio(
    state: PortfolioState,
    prices: dict[str, float],
    config: Config,
    *,
    trigger: str = "scheduled_monthly",
) -> RebalanceReport:
    core_weight = config.core_weight
    satellite_weight = config.satellite_weight
    """Плановый ребаланс 80/20: мягкая подгонка обоих рукавов, без полной ликвидации."""
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
    core_sold_rub = 0.0

    logger.info(
        "REBALANCE [%s] | total=%.0f RUB | PnL since last: %+.0f RUB (%+.2f%%)",
        trigger,
        total,
        pnl_rub,
        pnl_pct,
    )
    logger.info(
        "  Before: core=%.0f (%.1f%%) | satellite=%.0f (%.1f%%)",
        core_before,
        (core_before / total * 100) if total else 0,
        sat_before,
        (sat_before / total * 100) if total else 0,
    )
    logger.info(
        "  Target: core=%.0f (%.0f%%) | satellite=%.0f (%.0f%%)",
        target_core,
        core_weight * 100,
        target_sat,
        satellite_weight * 100,
    )

    # Satellite перевес — сливки в core
    sat_eq = sat_before
    if total > 0 and sat_eq > target_sat * (1 + TOLERANCE_PCT / 100):
        excess = sat_eq - target_sat
        satellite_sold_rub = _reduce_sleeve_positions(
            state.satellite, "satellite", prices, excess, config
        )
        sat_eq = state.satellite.equity(prices)

    if sat_eq > target_sat and state.satellite.cash_rub > 0:
        transfer = min(sat_eq - target_sat, state.satellite.cash_rub)
        state.satellite.cash_rub -= transfer
        state.core.cash_rub += transfer
        cash_moved_to_core += transfer

    # Core перевес — сливки в satellite (кэш)
    core_eq = state.core.equity(prices)
    if total > 0 and core_eq > target_core * (1 + TOLERANCE_PCT / 100):
        excess = core_eq - target_core
        core_sold_rub = _reduce_sleeve_positions(state.core, "core", prices, excess, config)
        transfer = min(excess, state.core.cash_rub)
        if transfer > 0:
            state.core.cash_rub -= transfer
            state.satellite.cash_rub += transfer
            cash_moved_to_core -= transfer

    # Satellite недовес — кэш из core
    sat_eq = state.satellite.equity(prices)
    if sat_eq < target_sat * (1 - TOLERANCE_PCT / 100):
        need = target_sat - sat_eq
        transfer = min(need, state.core.cash_rub)
        if transfer > 0:
            state.core.cash_rub -= transfer
            state.satellite.cash_rub += transfer
            cash_moved_to_core -= transfer

    core_after = state.core.equity(prices)
    sat_after = state.satellite.equity(prices)

    now = datetime.now(timezone.utc).isoformat()
    state.equity_at_last_rebalance = total
    state.last_scheduled_rebalance_at = now
    state.last_rebalance_at = now
    state.satellite_baseline_equity = sat_after
    state.satellite_month_start_equity = sat_after

    msg = (
        f"After: core={core_after:.0f} ({core_after/total*100:.1f}%), "
        f"sat={sat_after:.0f} ({sat_after/total*100:.1f}%)"
        if total
        else "empty portfolio"
    )
    logger.info("  %s", msg)

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
        core_sold_rub=core_sold_rub,
        trigger=trigger,
        message=msg,
    )
