"""Зачисление дивидендов в paper/backtest."""

from __future__ import annotations

import logging

from bot.config import Config
from bot.data.moex_dividends import DividendEvent
from bot.portfolio.state import PortfolioState, SleeveState

logger = logging.getLogger(__name__)


def apply_dividend(
    sleeve: SleeveState,
    sleeve_name: str,
    event: DividendEvent,
    config: Config,
) -> float:
    """Начисляет дивиденд в кэш рукава. Возвращает сумму после налога."""
    if not config.include_dividends:
        return 0.0
    if event.currency.upper() not in ("RUB", "SUR"):
        logger.debug("Skip dividend %s: currency %s", event.ticker, event.currency)
        return 0.0

    pos = sleeve.positions.get(event.ticker)
    if not pos or pos.qty <= 0:
        return 0.0

    gross = event.value_per_share * pos.qty
    net = gross * (1 - config.dividend_tax_pct / 100)
    sleeve.cash_rub += net
    logger.info(
        "DIV %s %s | %s %.4f sh × %.2f = %.0f gross, net %.0f RUB (tax %.0f%%)",
        event.ticker,
        event.registry_close,
        sleeve_name,
        pos.qty,
        event.value_per_share,
        gross,
        net,
        config.dividend_tax_pct,
    )
    return net


def apply_daily_dividends(
    state: PortfolioState,
    events: list[DividendEvent],
    config: Config,
) -> float:
    total = 0.0
    for ev in events:
        total += apply_dividend(state.core, "core", ev, config)
        total += apply_dividend(state.satellite, "satellite", ev, config)
    return total
