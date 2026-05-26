"""Продажа по негативному прогнозу (с учётом комиссии брокера)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from bot.analytics.growth_forecast import (
    extract_features,
    load_model_weights,
    predict_return,
)
from bot.analytics.total_return import adjusted_total_return_pct, forecast_dividend_pct_1m
from bot.config import Config
from bot.data.fundamentals import fetch_fundamentals
from bot.data.macro import MacroSnapshot, build_macro_snapshot
from bot.data.moex_iss import OhlcBar, fetch_index_history
from bot.portfolio.executor import sell_with_rules
from bot.portfolio.state import PortfolioState

logger = logging.getLogger(__name__)


def round_trip_commission_rub(notional: float, config: Config) -> float:
    """Покупка + продажа на ту же сумму."""
    pct = config.commission_pct / 100.0
    return notional * pct * 2.0


def should_exit_position(
    forecast_1m_pct: float,
    position_value_rub: float,
    config: Config,
) -> tuple[bool, str]:
    """
    Продаём, если прогноз ниже порога И ожидаемый убыток за месяц
    больше круговой комиссии (иначе продажа «в минус» относительно fees).
    """
    if not config.exit_on_negative_forecast:
        return False, "exits disabled"
    if forecast_1m_pct >= config.scan_sell_forecast_pct:
        return False, "forecast ok"

    expected_loss = position_value_rub * abs(min(0.0, forecast_1m_pct)) / 100.0
    fees = round_trip_commission_rub(position_value_rub, config) * config.exit_fee_buffer
    if expected_loss < fees:
        return (
            False,
            f"hold: ожид.убыток {expected_loss:.0f} ₽ < комиссии {fees:.0f} ₽",
        )
    return (
        True,
        f"SELL: прогноз {forecast_1m_pct:+.1f}%/мес, убыток ~{expected_loss:.0f} ₽ > fees ~{fees:.0f} ₽",
    )


def apply_forecast_exits(
    state: PortfolioState,
    prices: dict[str, float],
    histories: dict[str, dict[date, OhlcBar]],
    config: Config,
    as_of: date,
    *,
    index_series: dict[date, OhlcBar] | None = None,
    macro: MacroSnapshot | None = None,
) -> tuple[int, float]:
    """Проверка всех core-позиций; полная продажа при сигнале выхода."""
    if not state.core.positions or not config.exit_on_negative_forecast:
        return 0, 0.0

    weights = load_model_weights()
    if not weights:
        logger.debug("Exit check: no forecast model weights")
        return 0, 0.0

    if index_series is None:
        index_start = as_of - timedelta(days=config.forecast_train_days + 120)
        index_series = fetch_index_history(config.market_index, index_start, as_of)
    if macro is None:
        macro = build_macro_snapshot(as_of, config.market_index)

    trades = 0
    commissions = 0.0

    for ticker in list(state.core.positions.keys()):
        px = prices.get(ticker)
        series = histories.get(ticker)
        if not px or not series:
            continue

        pos = state.core.positions[ticker]
        value = pos.qty * px
        if value < config.core_min_trade_rub:
            continue

        try:
            fund = fetch_fundamentals(ticker, series, as_of, px)
        except Exception:
            fund = None

        feat = extract_features(
            ticker, series, index_series, as_of, macro=macro, fund=fund
        )
        if not feat:
            continue

        price_fc_pct = predict_return(feat, weights) * 100.0
        if config.include_dividends:
            div_fc = forecast_dividend_pct_1m(ticker, px, as_of, config)
            forecast_pct = adjusted_total_return_pct(price_fc_pct, div_fc, config)
        else:
            forecast_pct = price_fc_pct
        exit_ok, reason = should_exit_position(forecast_pct, value, config)
        if not exit_ok:
            logger.debug("%s: %s (fcst %+.1f%%)", ticker, reason, forecast_pct)
            continue

        logger.info("%s: %s", ticker, reason)
        result = sell_with_rules(
            state.core,
            "core",
            ticker,
            px,
            config,
            1.0,
            tag="EXIT",
            min_trade_override=0,
        )
        if result:
            trades += 1
            commissions += result.commission_rub

    return trades, commissions
