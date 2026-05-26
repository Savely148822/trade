"""Сводная доходность: цена + дивиденды (нетто после налога)."""

from __future__ import annotations

from datetime import date, timedelta

from bot.config import Config
from bot.data.moex_dividends import DividendEvent, fetch_dividends


def net_dividend_per_share(value_per_share: float, config: Config) -> float:
    return value_per_share * (1.0 - config.dividend_tax_pct / 100.0)


def dividend_return_decimal(
    events: list[DividendEvent],
    registry_from: date,
    registry_to: date,
    price: float,
    config: Config,
) -> float:
    """Доля от цены: сумма дивидендов с отсечкой в (from, to], нетто."""
    if price <= 0 or not config.include_dividends:
        return 0.0
    gross = sum(
        ev.value_per_share
        for ev in events
        if registry_from < ev.registry_close <= registry_to
        and ev.currency.upper() in ("RUB", "SUR")
        and ev.value_per_share > 0
    )
    if gross <= 0:
        return 0.0
    return net_dividend_per_share(gross, config) / price


def expected_dividend_pct_1m(
    ticker: str,
    price: float,
    as_of: date,
    config: Config,
    *,
    horizon_days: int = 21,
    events: list[DividendEvent] | None = None,
) -> float:
    """Ожидаемая дивидендная доходность за горизонт, % от цены (нетто)."""
    if price <= 0 or not config.include_dividends:
        return 0.0
    if events is None:
        end = as_of + timedelta(days=horizon_days + 30)
        start = as_of - timedelta(days=30)
        events = fetch_dividends(ticker, start, end)
    ret = dividend_return_decimal(
        events,
        as_of,
        as_of + timedelta(days=horizon_days),
        price,
        config,
    )
    return ret * 100.0


def total_return_pct(price_return_pct: float, dividend_pct: float) -> float:
    return price_return_pct + dividend_pct


def preload_dividends(
    tickers: list[str],
    start: date,
    end: date,
) -> dict[str, list[DividendEvent]]:
    return {t: fetch_dividends(t, start, end) for t in tickers}
