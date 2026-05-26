import os
from dataclasses import dataclass

from dotenv import load_dotenv

from bot.universe import DEFAULT_CORE_UNIVERSE

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
    paper_initial_rub: float
    monthly_deposit_rub: float
    core_momentum_months: int
    core_top_n: int
    core_trend_sma: int
    core_vol_lookback: int
    core_universe: list[str]
    scan_top_n: int
    scan_liquid_pool: int
    max_drawdown_pct: float
    min_daily_volume_rub: float
    poll_interval_sec: int
    market_index: str
    commission_pct: float
    min_trade_rub: float
    core_min_trade_rub: float
    include_dividends: bool
    dividend_tax_pct: float
    inflation_annual_pct: float

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            paper_trading=_bool(os.getenv("PAPER_TRADING"), True),
            finam_token=os.getenv("FINAM_TOKEN", ""),
            paper_initial_rub=float(os.getenv("PAPER_INITIAL_RUB", "10000")),
            monthly_deposit_rub=float(os.getenv("MONTHLY_DEPOSIT_RUB", "2000")),
            core_momentum_months=int(os.getenv("CORE_MOMENTUM_MONTHS", "6")),
            core_top_n=int(os.getenv("CORE_TOP_N", "5")),
            core_trend_sma=int(os.getenv("CORE_TREND_SMA", "0")),
            core_vol_lookback=int(os.getenv("CORE_VOL_LOOKBACK", "20")),
            core_universe=_list(
                os.getenv("CORE_UNIVERSE"),
                ",".join(DEFAULT_CORE_UNIVERSE),
            ),
            scan_top_n=int(os.getenv("SCAN_TOP_N", "20")),
            scan_liquid_pool=int(os.getenv("SCAN_LIQUID_POOL", "100")),
            max_drawdown_pct=float(os.getenv("MAX_DRAWDOWN_PCT", "20")),
            min_daily_volume_rub=float(os.getenv("MIN_DAILY_VOLUME_RUB", "5_000_000").replace("_", "")),
            poll_interval_sec=int(os.getenv("POLL_INTERVAL_SEC", "300")),
            market_index=os.getenv("MARKET_INDEX", "IMOEX").upper(),
            commission_pct=float(os.getenv("COMMISSION_PCT", "0.1")),
            min_trade_rub=float(os.getenv("MIN_TRADE_RUB", "3000")),
            core_min_trade_rub=float(os.getenv("CORE_MIN_TRADE_RUB", "500")),
            include_dividends=_bool(os.getenv("INCLUDE_DIVIDENDS"), True),
            dividend_tax_pct=float(os.getenv("DIVIDEND_TAX_PCT", "13")),
            inflation_annual_pct=float(os.getenv("INFLATION_ANNUAL_PCT", "8")),
        )
