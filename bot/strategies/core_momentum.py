from dataclasses import dataclass
from enum import Enum


class CoreAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    TRIM = "trim"
    HOLD = "hold"


@dataclass(frozen=True)
class CoreSignal:
    ticker: str
    action: CoreAction
    score: float
    price: float
    reason: str


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _momentum_return(closes: list[float], months: int) -> float | None:
    days = months * 21
    if len(closes) < days + 1:
        return None
    start = closes[-days - 1]
    end = closes[-1]
    if start <= 0:
        return None
    return (end - start) / start


def evaluate_core(
    ticker: str,
    closes: list[float],
    ma_fast: int,
    ma_slow: int,
    momentum_months: int,
) -> CoreSignal | None:
    if len(closes) < ma_slow + 2:
        return None

    price = closes[-1]
    fast = _sma(closes, ma_fast)
    slow = _sma(closes, ma_slow)
    mom = _momentum_return(closes, momentum_months)
    if fast is None or slow is None or mom is None:
        return None

    prev_fast = _sma(closes[:-1], ma_fast)
    prev_slow = _sma(closes[:-1], ma_slow)
    assert prev_fast is not None and prev_slow is not None

    score = mom * 100 + (1 if fast > slow else -1) * 10

    # Перегрев: сильный отрыв от медленной MA
    extension = (price - slow) / slow if slow else 0
    if extension > 0.15 and price > fast:
        return CoreSignal(
            ticker=ticker,
            action=CoreAction.TRIM,
            score=score,
            price=price,
            reason=f"extension {extension:.1%} above slow MA — take partial profit",
        )

    if prev_fast <= prev_slow and fast > slow and mom > 0:
        return CoreSignal(
            ticker=ticker,
            action=CoreAction.BUY,
            score=score,
            price=price,
            reason="golden cross + positive momentum",
        )

    if price < slow or (prev_fast >= prev_slow and fast < slow):
        return CoreSignal(
            ticker=ticker,
            action=CoreAction.SELL,
            score=score,
            price=price,
            reason="below slow MA or death cross",
        )

    return CoreSignal(
        ticker=ticker,
        action=CoreAction.HOLD,
        score=score,
        price=price,
        reason="no change",
    )
