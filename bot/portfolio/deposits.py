"""Пополнение счёта (зарплата → бот)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bot.config import Config
from bot.portfolio.dca import apply_core_monthly_dca
from bot.portfolio.rebalancer import rebalance_portfolio
from bot.portfolio.state import PortfolioState

logger = logging.getLogger(__name__)


def apply_monthly_deposit(state: PortfolioState, config: Config) -> float:
    """Зачисляет MONTHLY_DEPOSIT_RUB на core/satellite по весам."""
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
    config: Config,
    month_key: str,
) -> tuple[float, float, int]:
    """Пополнение → DCA в core → ребаланс 80/20. Возвращает (deposit, dca_commission, dca_trades)."""
    apply_monthly_deposit(state, config)
    dca_rub = config.monthly_deposit_rub * config.core_weight
    dca_trades, dca_fees = apply_core_monthly_dca(state, prices, dca_rub, config)
    rebalance_portfolio(state, prices, config)
    state.month_key = month_key
    state.satellite_month_start_equity = state.satellite.equity(prices)
    return config.monthly_deposit_rub, dca_fees, dca_trades


def current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")
