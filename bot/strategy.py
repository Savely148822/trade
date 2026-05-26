from dataclasses import dataclass
from enum import Enum


class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class StrategyResult:
    signal: Signal
    fast_ma: float
    slow_ma: float
    price: float


def simple_moving_average(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def ma_crossover_signal(
    closes: list[float],
    fast_period: int,
    slow_period: int,
) -> StrategyResult | None:
    """Сигнал по пересечению двух SMA: быстрая выше медленной — покупка."""
    if len(closes) < slow_period + 1:
        return None

    prev_closes = closes[:-1]
    fast_prev = simple_moving_average(prev_closes, fast_period)
    slow_prev = simple_moving_average(prev_closes, slow_period)
    fast_now = simple_moving_average(closes, fast_period)
    slow_now = simple_moving_average(closes, slow_period)

    if None in (fast_prev, slow_prev, fast_now, slow_now):
        return None

    price = closes[-1]
    assert fast_prev is not None and slow_prev is not None
    assert fast_now is not None and slow_now is not None

    if fast_prev <= slow_prev and fast_now > slow_now:
        signal = Signal.BUY
    elif fast_prev >= slow_prev and fast_now < slow_now:
        signal = Signal.SELL
    else:
        signal = Signal.HOLD

    return StrategyResult(
        signal=signal,
        fast_ma=fast_now,
        slow_ma=slow_now,
        price=price,
    )
