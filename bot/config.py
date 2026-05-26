import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _list(value: str | None, default: str) -> list[str]:
    raw = value if value else default
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


@dataclass(frozen=True)
class Config:
    paper_trading: bool
    finam_token: str
    core_weight: float
    satellite_weight: float
    paper_initial_rub: float
    core_ma_fast: int
    core_ma_slow: int
    core_momentum_months: int
    core_universe: list[str]
    satellite_universe: list[str]
    satellite_breakout_bars: int
    satellite_atr_period: int
    max_drawdown_pct: float
    satellite_monthly_loss_cap_pct: float
    min_daily_volume_rub: float
    poll_interval_sec: int
    rebalance_interval_sec: int
    market_index: str
    satellite_min_rvol: float
    satellite_index_sma_period: int
    satellite_ticker_sma_period: int
    satellite_require_close_confirm: bool
    satellite_profit_rebalance_pct: float

    @classmethod
    def from_env(cls) -> "Config":
        core_w = float(os.getenv("CORE_WEIGHT", "0.8"))
        sat_w = float(os.getenv("SATELLITE_WEIGHT", "0.2"))
        if abs(core_w + sat_w - 1.0) > 0.01:
            raise ValueError("CORE_WEIGHT + SATELLITE_WEIGHT must equal 1.0")

        fast = int(os.getenv("CORE_MA_FAST", "50"))
        slow = int(os.getenv("CORE_MA_SLOW", "200"))
        if fast >= slow:
            raise ValueError("CORE_MA_FAST must be less than CORE_MA_SLOW")

        return cls(
            paper_trading=_bool(os.getenv("PAPER_TRADING"), True),
            finam_token=os.getenv("FINAM_TOKEN", ""),
            core_weight=core_w,
            satellite_weight=sat_w,
            paper_initial_rub=float(os.getenv("PAPER_INITIAL_RUB", "1000000")),
            core_ma_fast=fast,
            core_ma_slow=slow,
            core_momentum_months=int(os.getenv("CORE_MOMENTUM_MONTHS", "6")),
            core_universe=_list(
                os.getenv("CORE_UNIVERSE"),
                "SBMX,TMOS,TRUR,SBGB,LQDT,SBER,LKOH,GAZP",
            ),
            satellite_universe=_list(
                os.getenv("SATELLITE_UNIVERSE"),
                "VTBR,AFKS,MTSS",
            ),
            satellite_breakout_bars=int(os.getenv("SATELLITE_BREAKOUT_BARS", "20")),
            satellite_atr_period=int(os.getenv("SATELLITE_ATR_PERIOD", "14")),
            max_drawdown_pct=float(os.getenv("MAX_DRAWDOWN_PCT", "20")),
            satellite_monthly_loss_cap_pct=float(
                os.getenv("SATELLITE_MONTHLY_LOSS_CAP_PCT", "10")
            ),
            min_daily_volume_rub=float(os.getenv("MIN_DAILY_VOLUME_RUB", "5000000")),
            poll_interval_sec=int(os.getenv("POLL_INTERVAL_SEC", "300")),
            rebalance_interval_sec=int(
                os.getenv("REBALANCE_INTERVAL_SEC", str(7 * 24 * 3600))
            ),
            market_index=os.getenv("MARKET_INDEX", "IMOEX").upper(),
            satellite_min_rvol=float(os.getenv("SATELLITE_MIN_RVOL", "1.5")),
            satellite_index_sma_period=int(
                os.getenv("SATELLITE_INDEX_SMA_PERIOD", "20")
            ),
            satellite_ticker_sma_period=int(
                os.getenv("SATELLITE_TICKER_SMA_PERIOD", "50")
            ),
            satellite_require_close_confirm=_bool(
                os.getenv("SATELLITE_REQUIRE_CLOSE_CONFIRM"), True
            ),
            satellite_profit_rebalance_pct=float(
                os.getenv("SATELLITE_PROFIT_REBALANCE_PCT", "20")
            ),
        )
