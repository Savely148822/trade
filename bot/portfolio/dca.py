"""Ежемесячное вложение пополнения в core (DCA по БПИФ)."""

from __future__ import annotations

import logging

from bot.config import Config
from bot.portfolio.executor import buy_with_rules
from bot.portfolio.state import PortfolioState

logger = logging.getLogger(__name__)


def apply_core_monthly_dca(
    state: PortfolioState,
    prices: dict[str, float],
    rub_from_deposit: float,
    config: Config,
) -> tuple[int, float]:
    """Покупка core-БПИФ на сумму пополнения (доля core). Возвращает (сделки, комиссии)."""
    if not config.core_dca_enabled or rub_from_deposit <= 0:
        return 0, 0.0

    tickers = [t for t in config.core_dca_universe if t in prices and prices[t] > 0]
    if not tickers:
        logger.warning("DCA: no prices on this day for %s", config.core_dca_universe)
        return 0, 0.0

    per_ticker = rub_from_deposit / len(tickers)
    trades = 0
    commissions = 0.0

    for ticker in tickers:
        px = prices[ticker]
        result = buy_with_rules(
            state.core,
            "core",
            ticker,
            px,
            per_ticker,
            config,
            min_trade_override=config.dca_min_trade_rub,
            tag="DCA",
        )
        if result:
            trades += 1
            commissions += result.commission_rub

    if trades:
        logger.info(
            "DCA invested %.0f RUB across %d tickers (%s)",
            rub_from_deposit,
            trades,
            ",".join(tickers),
        )
    return trades, commissions
