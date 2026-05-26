"""Пополнение счёта (зарплата → бот)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from bot.config import Config
from bot.data.moex_iss import OhlcBar
from bot.portfolio.core_portfolio import rebalance_core_portfolio
from bot.portfolio.rebalancer import rebalance_portfolio
from bot.portfolio.state import PortfolioState

logger = logging.getLogger(__name__)


def apply_monthly_deposit(
    state: PortfolioState, config: Config, *, total_equity: float | None = None
) -> float:
    if total_equity is not None and total_equity < config.satellite_min_equity_rub:
        state.core.cash_rub += config.monthly_deposit_rub
        core_part = config.monthly_deposit_rub
        sat_part = 0.0
    else:
        core_part = config.monthly_deposit_rub * config.core_weight
        sat_part = config.monthly_deposit_rub * config.satellite_weight
        state.core.cash_rub += core_part
        state.satellite.cash_rub += sat_part
    logger.info(
        "Deposit +%.0f RUB (core %.0f | satellite %.0f)",
        config.monthly_deposit_rub,
        core_part,
        sat_part,
    )
    return config.monthly_deposit_rub


def process_new_month(
    state: PortfolioState,
    prices: dict[str, float],
    histories: dict[str, dict[date, OhlcBar]],
    as_of: date,
    config: Config,
    month_key: str,
) -> tuple[float, float, int]:
    """Пополнение → ребаланс core-портфеля → 80/20."""
    eq = state.core.equity(prices) + state.satellite.equity(prices)
    apply_monthly_deposit(state, config, total_equity=eq)
    trades, fees = rebalance_core_portfolio(
        state,
        prices,
        histories,
        as_of,
        config,
        extra_cash=0,
        tag="MONTHLY",
    )
    rebalance_portfolio(state, prices, config)
    state.month_key = month_key
    state.satellite_month_start_equity = state.satellite.equity(prices)
    return config.monthly_deposit_rub, fees, trades


def current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")
