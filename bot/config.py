import os
from dataclasses import dataclass

from dotenv import load_dotenv

from bot.universe import DEFAULT_CORE_UNIVERSE, DEFAULT_SATELLITE_UNIVERSE

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
    monthly_deposit_rub: float
    core_momentum_months: int
    core_top_n: int
    core_trend_sma: int
    core_vol_lookback: int
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
    satellite_min_equity_rub: float
    commission_pct: float
    min_trade_rub: float
    include_dividends: bool
    dividend_tax_pct: float
    inflation_annual_pct: float

    @classmethod
    def from_env(cls) -> "Config":
        core_w = float(os.getenv("CORE_WEIGHT", "0.8"))
        sat_w = float(os.getenv("SATELLITE_WEIGHT", "0.2"))
        if abs(core_w + sat_w - 1.0) > 0.01:
            raise ValueError("CORE_WEIGHT + SATELLITE_WEIGHT must equal 1.0")

        return cls(
            paper_trading=_bool(os.getenv("PAPER_TRADING"), True),
            finam_token=os.getenv("FINAM_TOKEN", ""),
            core_weight=core_w,
            satellite_weight=sat_w,
            paper_initial_rub=float(os.getenv("PAPER_INITIAL_RUB", "10000")),
            monthly_deposit_rub=float(os.getenv("MONTHLY_DEPOSIT_RUB", "2000")),
            core_momentum_months=int(os.getenv("CORE_MOMENTUM_MONTHS", "6")),
            core_top_n=int(os.getenv("CORE_TOP_N", "5")),
            core_trend_sma=int(os.getenv("CORE_TREND_SMA", "200")),
            core_vol_lookback=int(os.getenv("CORE_VOL_LOOKBACK", "20")),
            core_universe=_list(
                os.getenv("CORE_UNIVERSE"),
                ",".join(DEFAULT_CORE_UNIVERSE),
            ),
            satellite_universe=_list(
                os.getenv("SATELLITE_UNIVERSE"),
                ",".join(DEFAULT_SATELLITE_UNIVERSE),
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
                os.getenv(
                    "REBALANCE_INTERVAL_SEC",
                    str(30 * 24 * 3600),
                )
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
            satellite_min_equity_rub=float(os.getenv("SATELLITE_MIN_EQUITY_RUB", "30000")),
            commission_pct=float(os.getenv("COMMISSION_PCT", "0.1")),
            min_trade_rub=float(os.getenv("MIN_TRADE_RUB", "3000")),
            include_dividends=_bool(os.getenv("INCLUDE_DIVIDENDS"), True),
            dividend_tax_pct=float(os.getenv("DIVIDEND_TAX_PCT", "13")),
            inflation_annual_pct=float(os.getenv("INFLATION_ANNUAL_PCT", "8")),
        )
