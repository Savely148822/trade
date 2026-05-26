"""Сводная доходность: цена + дивиденды (MOEX + прокси по истории)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from bot.config import Config
from bot.data.moex_dividends import DividendEvent, fetch_dividends

DEFAULT_HORIZON_DAYS = 21


@dataclass(frozen=True)
class DividendForecast:
    """Ожидаемая дивидендная доходность за ~1 мес, % от цены (нетто)."""

    announced_pct: float
    proxy_pct: float
    total_pct: float
    source: str  # "moex" | "proxy" | "none"


def net_dividend_per_share(value_per_share: float, config: Config) -> float:
    return value_per_share * (1.0 - config.dividend_tax_pct / 100.0)


def _eligible_events(events: list[DividendEvent]) -> list[DividendEvent]:
    return [
        ev
        for ev in events
        if ev.currency.upper() in ("RUB", "SUR") and ev.value_per_share > 0
    ]


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
        for ev in _eligible_events(events)
        if registry_from < ev.registry_close <= registry_to
    )
    if gross <= 0:
        return 0.0
    return net_dividend_per_share(gross, config) / price


def announced_dividend_pct_1m(
    events: list[DividendEvent],
    as_of: date,
    price: float,
    config: Config,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> float:
    """Объявленные в MOEX дивиденды с отсечкой в ближайший горизонт."""
    ret = dividend_return_decimal(
        events,
        as_of,
        as_of + timedelta(days=horizon_days),
        price,
        config,
    )
    return ret * 100.0


def proxy_dividend_pct_1m(
    events: list[DividendEvent],
    as_of: date,
    price: float,
    config: Config,
) -> float:
    """
    Прокси: среднемесячная доходность из выплат за DIVIDEND_PROXY_MONTHS.
    trailing_net / price / months × 100
    """
    if price <= 0 or not config.include_dividends or not config.dividend_use_proxy:
        return 0.0

    months = max(config.dividend_proxy_months, 1)
    lookback_start = as_of - timedelta(days=months * 31)
    gross = sum(
        ev.value_per_share
        for ev in _eligible_events(events)
        if lookback_start <= ev.registry_close <= as_of
    )
    if gross <= 0:
        return 0.0

    trailing_net = net_dividend_per_share(gross, config)
    monthly = trailing_net / price / months
    return monthly * 100.0


def forecast_dividend_pct_1m(
    ticker: str,
    price: float,
    as_of: date,
    config: Config,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    events: list[DividendEvent] | None = None,
) -> DividendForecast:
    """
    1) Если в MOEX есть отсечка в ближайший месяц — берём её сумму.
    2) Иначе — прокси по средней выплате за последние N месяцев.
    """
    if price <= 0 or not config.include_dividends:
        return DividendForecast(0.0, 0.0, 0.0, "none")

    if events is None:
        months = max(config.dividend_proxy_months, 1)
        start = as_of - timedelta(days=months * 31 + 5)
        end = as_of + timedelta(days=horizon_days + 30)
        events = fetch_dividends(ticker, start, end)

    announced = announced_dividend_pct_1m(events, as_of, price, config, horizon_days=horizon_days)
    proxy = proxy_dividend_pct_1m(events, as_of, price, config)

    if announced > 0:
        return DividendForecast(
            announced_pct=round(announced, 3),
            proxy_pct=round(proxy, 3),
            total_pct=round(announced, 3),
            source="moex",
        )
    if proxy > 0:
        return DividendForecast(
            announced_pct=0.0,
            proxy_pct=round(proxy, 3),
            total_pct=round(proxy, 3),
            source="proxy",
        )
    return DividendForecast(0.0, 0.0, 0.0, "none")


def expected_dividend_pct_1m(
    ticker: str,
    price: float,
    as_of: date,
    config: Config,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    events: list[DividendEvent] | None = None,
) -> float:
    """Совместимость: только итоговый % для прогноза."""
    return forecast_dividend_pct_1m(
        ticker,
        price,
        as_of,
        config,
        horizon_days=horizon_days,
        events=events,
    ).total_pct


def total_return_pct(price_return_pct: float, dividend_pct: float) -> float:
    return price_return_pct + dividend_pct


def preload_dividends(
    tickers: list[str],
    start: date,
    end: date,
) -> dict[str, list[DividendEvent]]:
    return {t: fetch_dividends(t, start, end) for t in tickers}


def dividend_preload_range(as_of: date, config: Config, *, horizon_days: int = DEFAULT_HORIZON_DAYS) -> tuple[date, date]:
    months = max(config.dividend_proxy_months, 1)
    start = as_of - timedelta(days=months * 31 + 5)
    end = as_of + timedelta(days=horizon_days + 30)
    return start, end
