"""Зачисление дивидендов в paper/backtest."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from bot.config import Config
from bot.data.moex_dividends import DividendEvent, fetch_dividends
from bot.portfolio.state import PortfolioState, SleeveState

logger = logging.getLogger(__name__)


def dividend_event_key(event: DividendEvent) -> str:
    return f"{event.ticker}:{event.registry_close.isoformat()}"


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
    return total


def process_dividends_through(
    state: PortfolioState,
    as_of: date,
    config: Config,
    *,
    lookback_days: int = 14,
) -> float:
    """
    Начисляет дивиденды по отсечкам от last_dividend_date до as_of.
    Дубликаты отсекаются по paid_dividend_keys.
    """
    if not config.include_dividends:
        return 0.0

    tickers = list(state.core.positions.keys())
    if not tickers:
        state.last_dividend_date = as_of.isoformat()
        return 0.0

    start = date.fromisoformat(state.last_dividend_date) if state.last_dividend_date else (
        as_of - timedelta(days=lookback_days)
    )
    if start > as_of:
        start = as_of - timedelta(days=lookback_days)

    fetch_start = start - timedelta(days=1)
    total = 0.0
    paid = set(state.paid_dividend_keys)

    for ticker in tickers:
        pos = state.core.positions.get(ticker)
        if not pos or pos.qty <= 0:
            continue
        for ev in fetch_dividends(ticker, fetch_start, as_of):
            if ev.registry_close < start or ev.registry_close > as_of:
                continue
            key = dividend_event_key(ev)
            if key in paid:
                continue
            net = apply_dividend(state.core, "core", ev, config)
            if net > 0:
                paid.add(key)
                state.paid_dividend_keys.append(key)
                state.total_dividends_net_rub += net
                total += net

    state.last_dividend_date = as_of.isoformat()
    return total
