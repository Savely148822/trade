"""Пополнение счёта (зарплата → core 100%)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from bot.config import Config
from bot.data.moex_iss import OhlcBar
from bot.portfolio.core_portfolio import rebalance_core_portfolio
from bot.portfolio.state import PortfolioState

logger = logging.getLogger(__name__)


def apply_monthly_deposit(state: PortfolioState, config: Config) -> float:
    state.core.cash_rub += config.monthly_deposit_rub
    state.total_deposits_rub += config.monthly_deposit_rub
    logger.info("Deposit +%.0f RUB → core", config.monthly_deposit_rub)
    return config.monthly_deposit_rub


def process_new_month(
    state: PortfolioState,
    prices: dict[str, float],
    histories: dict[str, dict[date, OhlcBar]],
    as_of: date,
    config: Config,
    month_key: str,
    *,
    universe: list[str] | None = None,
) -> tuple[float, float, int]:
    apply_monthly_deposit(state, config)
    trades, fees = rebalance_core_portfolio(
        state,
        prices,
        histories,
        as_of,
        config,
        universe=universe,
        tag="MONTHLY",
    )
    state.month_key = month_key
    return config.monthly_deposit_rub, fees, trades


def current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")
