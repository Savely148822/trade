"""Сводная доходность: цена + дивиденды (MOEX + прокси с учётом редких выплат)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from bot.config import Config
from bot.data.moex_dividends import DividendEvent, fetch_dividends

DEFAULT_HORIZON_DAYS = 21


@dataclass(frozen=True)
class DividendHistoryStats:
    payment_count: int
    cycle_days: float | None
    last_payment: date | None
    sparse: bool  # редкие выплаты (раз в 2+ года или одна запись)


@dataclass(frozen=True)
class DividendForecast:
    """Ожидаемая дивидендная доходность за горизонт, % от цены (нетто)."""

    announced_pct: float
    proxy_pct: float
    total_pct: float
    source: str  # "moex" | "proxy" | "none"
    payment_count: int = 0
    cycle_days: float | None = None
    sparse: bool = False
    info_discount: float = 1.0


def net_dividend_per_share(value_per_share: float, config: Config) -> float:
    return value_per_share * (1.0 - config.dividend_tax_pct / 100.0)


def _eligible_events(events: list[DividendEvent]) -> list[DividendEvent]:
    return [
        ev
        for ev in events
        if ev.currency.upper() in ("RUB", "SUR") and ev.value_per_share > 0
    ]


def history_lookback_days(config: Config) -> int:
    months = max(config.dividend_history_months, config.dividend_proxy_months, 1)
    return months * 31 + 5


def dividend_preload_range(
    as_of: date,
    config: Config,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> tuple[date, date]:
    start = as_of - timedelta(days=history_lookback_days(config))
    end = as_of + timedelta(days=horizon_days + 30)
    return start, end


def analyze_dividend_history(
    events: list[DividendEvent],
    as_of: date,
    config: Config,
) -> DividendHistoryStats:
    lookback_start = as_of - timedelta(days=history_lookback_days(config))
    past = sorted(
        ev.registry_close
        for ev in _eligible_events(events)
        if lookback_start <= ev.registry_close <= as_of
    )
    count = len(past)
    if count == 0:
        return DividendHistoryStats(0, None, None, sparse=False)

    all_past = sorted(
        ev.registry_close
        for ev in _eligible_events(events)
        if ev.registry_close <= as_of
    )
    cycle_days: float | None = None
    if len(all_past) >= 2:
        gaps = [(all_past[i] - all_past[i - 1]).days for i in range(1, len(all_past))]
        cycle_days = sum(gaps) / len(gaps)
    elif count == 1:
        cycle_days = float(config.dividend_default_cycle_days)

    sparse = count == 1 or (cycle_days is not None and cycle_days >= 730)
    return DividendHistoryStats(
        payment_count=count,
        cycle_days=cycle_days,
        last_payment=past[-1],
        sparse=sparse,
    )


def dividend_return_decimal(
    events: list[DividendEvent],
    registry_from: date,
    registry_to: date,
    price: float,
    config: Config,
) -> float:
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
    stats: DividendHistoryStats,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> float:
    """
    Прокси с учётом редких выплат (раз в год / раз в несколько лет).

    E[див за горизонт] ≈ средний размер выплаты × (horizon / cycle),
    а не «годовая сумма / 12».
    """
    if price <= 0 or not config.include_dividends or not config.dividend_use_proxy:
        return 0.0
    if stats.payment_count == 0 or stats.cycle_days is None or stats.cycle_days <= 0:
        return 0.0

    lookback_start = as_of - timedelta(days=history_lookback_days(config))
    past_events = [
        ev
        for ev in _eligible_events(events)
        if lookback_start <= ev.registry_close <= as_of
    ]
    if not past_events:
        return 0.0

    total_net = sum(net_dividend_per_share(ev.value_per_share, config) for ev in past_events)
    avg_payment = total_net / len(past_events)
    cycle = max(stats.cycle_days, float(horizon_days))
    expected = avg_payment * min(1.0, horizon_days / cycle)
    return expected / price * 100.0


def _info_discount(div: DividendForecast, config: Config) -> float:
    if div.source == "moex":
        return 1.0
    if div.payment_count == 0:
        return config.dividend_no_info_discount
    if div.source == "proxy" and div.sparse:
        return config.dividend_sparse_discount
    return 1.0


def forecast_dividend_pct_1m(
    ticker: str,
    price: float,
    as_of: date,
    config: Config,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    events: list[DividendEvent] | None = None,
) -> DividendForecast:
    if price <= 0 or not config.include_dividends:
        return DividendForecast(
            0.0, 0.0, 0.0, "none", 0, None, False, config.dividend_no_info_discount
        )

    if events is None:
        start, end = dividend_preload_range(as_of, config, horizon_days=horizon_days)
        events = fetch_dividends(ticker, start, end)

    stats = analyze_dividend_history(events, as_of, config)
    announced = announced_dividend_pct_1m(events, as_of, price, config, horizon_days=horizon_days)
    proxy = proxy_dividend_pct_1m(
        events, as_of, price, config, stats, horizon_days=horizon_days
    )

    if announced > 0:
        div = DividendForecast(
            announced_pct=round(announced, 3),
            proxy_pct=round(proxy, 3),
            total_pct=round(announced, 3),
            source="moex",
            payment_count=stats.payment_count,
            cycle_days=stats.cycle_days,
            sparse=False,
            info_discount=1.0,
        )
        return div

    if proxy > 0:
        sparse = stats.sparse
        discount = _info_discount(
            DividendForecast(
                0, proxy, proxy, "proxy", stats.payment_count, stats.cycle_days, sparse
            ),
            config,
        )
        return DividendForecast(
            announced_pct=0.0,
            proxy_pct=round(proxy, 3),
            total_pct=round(proxy, 3),
            source="proxy",
            payment_count=stats.payment_count,
            cycle_days=round(stats.cycle_days, 0) if stats.cycle_days else None,
            sparse=sparse,
            info_discount=discount,
        )

    return DividendForecast(
        0.0,
        0.0,
        0.0,
        "none",
        stats.payment_count,
        stats.cycle_days,
        stats.sparse,
        _info_discount(
            DividendForecast(0, 0, 0, "none", 0, None, False),
            config,
        ),
    )


def adjusted_total_return_pct(
    price_return_pct: float,
    div: DividendForecast,
    config: Config,
) -> float:
    """
    Total с понижающим коэффициентом, если нет истории выплат
    или выплаты редкие (оценка ненадёжна).
    """
    raw = price_return_pct + div.total_pct
    if div.source == "moex":
        return raw

    discount = div.info_discount if div.info_discount > 0 else 1.0
    if div.payment_count == 0:
        return raw * discount

    if div.source == "proxy" and div.sparse:
        return price_return_pct + div.total_pct * discount

    return raw


def expected_dividend_pct_1m(
    ticker: str,
    price: float,
    as_of: date,
    config: Config,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    events: list[DividendEvent] | None = None,
) -> float:
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
