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
    scan_min_forecast_pct: float
    scan_min_avg_turnover_rub: float
    scan_min_price_rub: float
    scan_max_vol_annual: float
    scan_require_uptrend: bool
    scan_require_beats_index: bool
    scan_strict_only: bool
    scan_require_positive_fund: bool
    scan_require_macro_risk: bool
    scan_min_list_level: int
    scan_sma_tolerance_pct: float
    scan_min_news_sentiment: float
    scan_use_news: bool
    exit_on_negative_forecast: bool
    scan_sell_forecast_pct: float
    exit_fee_buffer: float
    forecast_train_days: int
    forecast_min_train_samples: int
    forecast_ridge_alpha: float
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
            scan_min_forecast_pct=float(os.getenv("SCAN_MIN_FORECAST_PCT", "1.0")),
            scan_min_avg_turnover_rub=float(
                os.getenv("SCAN_MIN_AVG_TURNOVER_RUB", "20_000_000").replace("_", "")
            ),
            scan_min_price_rub=float(os.getenv("SCAN_MIN_PRICE_RUB", "10")),
            scan_max_vol_annual=float(os.getenv("SCAN_MAX_VOL_ANNUAL", "0.8")),
            scan_require_uptrend=_bool(os.getenv("SCAN_REQUIRE_UPTREND"), True),
            scan_require_beats_index=_bool(os.getenv("SCAN_REQUIRE_BEATS_INDEX"), True),
            scan_strict_only=_bool(os.getenv("SCAN_STRICT_ONLY"), True),
            scan_require_positive_fund=_bool(os.getenv("SCAN_REQUIRE_POSITIVE_FUND"), True),
            scan_require_macro_risk=_bool(os.getenv("SCAN_REQUIRE_MACRO_RISK"), False),
            scan_min_list_level=int(os.getenv("SCAN_MIN_LIST_LEVEL", "1")),
            scan_sma_tolerance_pct=float(os.getenv("SCAN_SMA_TOLERANCE_PCT", "3.0")),
            scan_min_news_sentiment=float(os.getenv("SCAN_MIN_NEWS_SENTIMENT", "0.0")),
            scan_use_news=_bool(os.getenv("SCAN_USE_NEWS"), True),
            exit_on_negative_forecast=_bool(os.getenv("EXIT_ON_NEGATIVE_FORECAST"), True),
            scan_sell_forecast_pct=float(os.getenv("SCAN_SELL_FORECAST_PCT", "-1.0")),
            exit_fee_buffer=float(os.getenv("EXIT_FEE_BUFFER", "1.2")),
            forecast_train_days=int(os.getenv("FORECAST_TRAIN_DAYS", "504")),
            forecast_min_train_samples=int(os.getenv("FORECAST_MIN_TRAIN_SAMPLES", "80")),
            forecast_ridge_alpha=float(os.getenv("FORECAST_RIDGE_ALPHA", "1.0")),
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
