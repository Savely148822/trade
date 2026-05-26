from dataclasses import dataclass
from enum import Enum


class SatelliteAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class SatelliteSignal:
    ticker: str
    action: SatelliteAction
    price: float
    stop_price: float | None
    reason: str


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    trs: list[float] = []
    for i in range(-period, 0):
        h, l, c_prev = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    return sum(trs) / len(trs)


def evaluate_satellite(
    ticker: str,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    breakout_bars: int,
    atr_period: int,
) -> SatelliteSignal | None:
    need = max(breakout_bars + 2, atr_period + 2)
    if len(closes) < need:
        return None

    price = closes[-1]
    upper = max(highs[-breakout_bars - 1 : -1])
    lower = min(lows[-breakout_bars - 1 : -1])
    atr = _atr(highs, lows, closes, atr_period)

    if atr is None:
        return None

    if price > upper:
        return SatelliteSignal(
            ticker=ticker,
            action=SatelliteAction.BUY,
            price=price,
            stop_price=price - 2 * atr,
            reason=f"breakout above {upper:.2f}",
        )

    if price < lower:
        return SatelliteSignal(
            ticker=ticker,
            action=SatelliteAction.SELL,
            price=price,
            stop_price=price + 2 * atr,
            reason=f"breakdown below {lower:.2f}",
        )

    return SatelliteSignal(
        ticker=ticker,
        action=SatelliteAction.HOLD,
        price=price,
        stop_price=None,
        reason="inside range",
    )
