import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    exchange_id: str
    api_key: str
    api_secret: str
    paper_trading: bool
    symbol: str
    timeframe: str
    fast_ma_period: int
    slow_ma_period: int
    trade_size_ratio: float
    poll_interval_sec: int
    paper_usdt_balance: float
    paper_base_balance: float

    @classmethod
    def from_env(cls) -> "Config":
        fast = int(os.getenv("FAST_MA_PERIOD", "9"))
        slow = int(os.getenv("SLOW_MA_PERIOD", "21"))
        if fast >= slow:
            raise ValueError("FAST_MA_PERIOD must be less than SLOW_MA_PERIOD")

        ratio = float(os.getenv("TRADE_SIZE_RATIO", "0.95"))
        if not 0 < ratio <= 1:
            raise ValueError("TRADE_SIZE_RATIO must be between 0 and 1")

        return cls(
            exchange_id=os.getenv("EXCHANGE_ID", "binance").lower(),
            api_key=os.getenv("API_KEY", ""),
            api_secret=os.getenv("API_SECRET", ""),
            paper_trading=_bool(os.getenv("PAPER_TRADING"), True),
            symbol=os.getenv("SYMBOL", "BTC/USDT"),
            timeframe=os.getenv("TIMEFRAME", "1h"),
            fast_ma_period=fast,
            slow_ma_period=slow,
            trade_size_ratio=ratio,
            poll_interval_sec=int(os.getenv("POLL_INTERVAL_SEC", "60")),
            paper_usdt_balance=float(os.getenv("PAPER_USDT_BALANCE", "10000")),
            paper_base_balance=float(os.getenv("PAPER_BASE_BALANCE", "0")),
        )
