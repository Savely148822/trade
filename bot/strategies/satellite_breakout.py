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
    rvol: float | None
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
    volumes: list[float],
    breakout_bars: int,
    atr_period: int,
    min_rvol: float,
    require_close_confirm: bool = True,
) -> SatelliteSignal | None:
    need = max(breakout_bars + 2, atr_period + 2, 22)
    if len(closes) < need or len(volumes) < need:
        return None

    price = closes[-1]
    prev_close = closes[-2]
    upper = max(highs[-breakout_bars - 1 : -1])
    lower = min(lows[-breakout_bars - 1 : -1])
    atr = _atr(highs, lows, closes, atr_period)

    avg_vol = sum(volumes[-21:-1]) / 20
    rvol = (volumes[-1] / avg_vol) if avg_vol > 0 else None

    if atr is None:
        return None

    def _rvol_ok() -> bool:
        if rvol is None:
            return False
        return rvol >= min_rvol

    # Пробой: закрытие выше уровня (не только тень)
    breakout_close = price > upper
    if require_close_confirm:
        breakout_close = breakout_close and prev_close <= upper

    if breakout_close:
        if not _rvol_ok():
            return SatelliteSignal(
                ticker=ticker,
                action=SatelliteAction.HOLD,
                price=price,
                stop_price=None,
                rvol=rvol,
                reason=f"breakout but RVOL {rvol:.2f} < {min_rvol}" if rvol else "no RVOL",
            )
        return SatelliteSignal(
            ticker=ticker,
            action=SatelliteAction.BUY,
            price=price,
            stop_price=price - 2 * atr,
            rvol=rvol,
            reason=f"close breakout above {upper:.2f}, RVOL={rvol:.2f}",
        )

    breakdown_close = price < lower
    if require_close_confirm:
        breakdown_close = breakdown_close and prev_close >= lower

    if breakdown_close:
        return SatelliteSignal(
            ticker=ticker,
            action=SatelliteAction.SELL,
            price=price,
            stop_price=price + 2 * atr,
            rvol=rvol,
            reason=f"close breakdown below {lower:.2f}",
        )

    return SatelliteSignal(
        ticker=ticker,
        action=SatelliteAction.HOLD,
        price=price,
        stop_price=None,
        rvol=rvol,
        reason="inside range",
    )
