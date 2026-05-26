"""Режим рынка и вспомогательные метрики для satellite."""

from __future__ import annotations

from dataclasses import dataclass

from bot.data.moex_iss import fetch_index_closes


@dataclass(frozen=True)
class MarketRegime:
    index: str
    price: float
    sma: float
    allow_satellite_trades: bool
    reason: str


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def relative_volume(volumes: list[float], lookback: int = 20) -> float | None:
    if len(volumes) < lookback + 1:
        return None
    avg = sum(volumes[-lookback - 1 : -1]) / lookback
    if avg <= 0:
        return None
    return volumes[-1] / avg


def ticker_above_sma(closes: list[float], period: int) -> bool:
    sma = _sma(closes, period)
    if sma is None:
        return False
    return closes[-1] > sma


def fetch_market_regime(index: str, sma_period: int) -> MarketRegime:
    closes = fetch_index_closes(index, days=sma_period + 30)
    if not closes:
        return MarketRegime(
            index=index,
            price=0.0,
            sma=0.0,
            allow_satellite_trades=False,
            reason=f"no data for index {index}",
        )

    price = closes[-1]
    sma = _sma(closes, sma_period)
    if sma is None:
        return MarketRegime(
            index=index,
            price=price,
            sma=0.0,
            allow_satellite_trades=False,
            reason="insufficient index history",
        )

    ok = price > sma
    return MarketRegime(
        index=index,
        price=price,
        sma=sma,
        allow_satellite_trades=ok,
        reason=f"index {'above' if ok else 'below'} SMA({sma_period})",
    )
