"""Исполнение сигналов в paper-режиме (виртуальный портфель)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bot.config import Config
from bot.portfolio.state import PortfolioState, Position, SleeveState
from bot.strategies.core_momentum import CoreAction, CoreSignal
from bot.strategies.satellite_breakout import SatelliteAction, SatelliteSignal

logger = logging.getLogger(__name__)

TRIM_FRACTION = 0.35
TRADE_FRACTION = 0.25


@dataclass
class TradeResult:
    sleeve: str
    ticker: str
    side: str
    qty: float
    price: float
    rub: float
    commission_rub: float
    message: str


def _commission(amount: float, config: Config) -> float:
    return amount * config.commission_pct / 100.0


def buy_with_rules(
    sleeve: SleeveState,
    sleeve_name: str,
    ticker: str,
    price: float,
    rub_amount: float,
    config: Config,
    *,
    min_trade_override: float | None = None,
    tag: str = "",
) -> TradeResult | None:
    min_rub = min_trade_override if min_trade_override is not None else config.min_trade_rub
    if rub_amount < min_rub or price <= 0:
        return None

    fee = _commission(rub_amount, config)
    total = rub_amount + fee
    if sleeve.cash_rub < total:
        return None

    qty = rub_amount / price
    sleeve.cash_rub -= total
    pos = sleeve.positions.get(ticker)
    if pos:
        total_qty = pos.qty + qty
        pos.avg_price = (pos.avg_price * pos.qty + price * qty) / total_qty
        pos.qty = total_qty
    else:
        sleeve.positions[ticker] = Position(qty=qty, avg_price=price)

    prefix = f"[{tag}] " if tag else ""
    msg = f"{prefix}BUY {qty:.4f} @ {price:.2f} ({rub_amount:.0f} RUB, fee {fee:.0f})"
    return TradeResult(sleeve_name, ticker, "buy", qty, price, rub_amount, fee, msg)


def sell_with_rules(
    sleeve: SleeveState,
    sleeve_name: str,
    ticker: str,
    price: float,
    config: Config,
    fraction: float = 1.0,
    tag: str = "",
    min_trade_override: float | None = None,
) -> TradeResult | None:
    pos = sleeve.positions.get(ticker)
    if not pos or pos.qty <= 0 or price <= 0:
        return None

    qty = pos.qty * fraction
    gross = qty * price
    min_rub = min_trade_override if min_trade_override is not None else config.min_trade_rub
    if gross < min_rub and fraction < 1.0:
        return None

    fee = _commission(gross, config)
    pos.qty -= qty
    if pos.qty < 1e-8:
        del sleeve.positions[ticker]
    sleeve.cash_rub += gross - fee

    prefix = f"[{tag}] " if tag else ""
    msg = f"{prefix}SELL {qty:.4f} @ {price:.2f} ({fraction:.0%}, fee {fee:.0f})"
    return TradeResult(sleeve_name, ticker, "sell", qty, price, gross, fee, msg)


def apply_core_signal(state: PortfolioState, signal: CoreSignal, config: Config) -> TradeResult | None:
    sleeve = state.core
    price = signal.price

    if signal.action == CoreAction.BUY:
        rub = sleeve.cash_rub * TRADE_FRACTION
        result = buy_with_rules(sleeve, "core", signal.ticker, price, rub, config, tag="CORE")
        if result:
            result.message = f"[CORE] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    if signal.action == CoreAction.TRIM:
        result = sell_with_rules(
            sleeve, "core", signal.ticker, price, config, TRIM_FRACTION, tag="CORE TRIM"
        )
        if result:
            result.message = f"[CORE TRIM] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    if signal.action == CoreAction.SELL:
        result = sell_with_rules(sleeve, "core", signal.ticker, price, config, 1.0, tag="CORE")
        if result:
            result.message = f"[CORE] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    return None


def apply_satellite_signal(
    state: PortfolioState, signal: SatelliteSignal, config: Config
) -> TradeResult | None:
    sleeve = state.satellite
    price = signal.price

    if signal.action == SatelliteAction.BUY:
        rub = sleeve.cash_rub * TRADE_FRACTION
        result = buy_with_rules(sleeve, "satellite", signal.ticker, price, rub, config, tag="SAT")
        if result:
            result.message = f"[SAT] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    if signal.action == SatelliteAction.SELL:
        result = sell_with_rules(sleeve, "satellite", signal.ticker, price, config, 1.0, tag="SAT")
        if result:
            result.message = f"[SAT] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    return None
