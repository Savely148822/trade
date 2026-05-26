"""Cross-sectional momentum: ранжирование бумаг по доходности за N месяцев."""

from __future__ import annotations

from datetime import date

from bot.data.moex_iss import OhlcBar, closes_before


def momentum_return(closes: list[float], months: int, days_per_month: int = 21) -> float | None:
    need = months * days_per_month + 1
    if len(closes) < need:
        return None
    start_px = closes[-need]
    end_px = closes[-1]
    if start_px <= 0:
        return None
    return (end_px - start_px) / start_px


def rank_by_momentum(
    histories: dict[str, dict[date, OhlcBar]],
    universe: list[str],
    as_of: date,
    momentum_months: int,
    *,
    min_price_above_sma: int | None = 200,
) -> list[tuple[str, float]]:
    """Список (ticker, momentum) по убыванию momentum."""
    scored: list[tuple[str, float]] = []
    for ticker in universe:
        series = histories.get(ticker, {})
        need = momentum_months * 21 + 5
        if min_price_above_sma:
            need = max(need, min_price_above_sma + 2)
        closes = closes_before(series, as_of, need)
        mom = momentum_return(closes, momentum_months)
        if mom is None:
            continue
        if min_price_above_sma and len(closes) >= min_price_above_sma:
            sma = sum(closes[-min_price_above_sma:]) / min_price_above_sma
            if closes[-1] < sma:
                continue
        scored.append((ticker, mom))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
