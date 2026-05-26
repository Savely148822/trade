"""Исполнение сигналов в paper-режиме (виртуальный портфель)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

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
    message: str


def _buy(
    sleeve: SleeveState,
    sleeve_name: str,
    ticker: str,
    price: float,
    rub_amount: float,
) -> TradeResult | None:
    if rub_amount <= 0 or sleeve.cash_rub < rub_amount:
        return None
    qty = rub_amount / price
    sleeve.cash_rub -= rub_amount
    pos = sleeve.positions.get(ticker)
    if pos:
        total_qty = pos.qty + qty
        pos.avg_price = (pos.avg_price * pos.qty + price * qty) / total_qty
        pos.qty = total_qty
    else:
        sleeve.positions[ticker] = Position(qty=qty, avg_price=price)
    return TradeResult(
        sleeve_name, ticker, "buy", qty, price, rub_amount, f"BUY {qty:.4f} @ {price:.2f}"
    )


def _sell(
    sleeve: SleeveState,
    sleeve_name: str,
    ticker: str,
    price: float,
    fraction: float = 1.0,
) -> TradeResult | None:
    pos = sleeve.positions.get(ticker)
    if not pos or pos.qty <= 0:
        return None
    qty = pos.qty * fraction
    rub = qty * price
    pos.qty -= qty
    if pos.qty < 1e-8:
        del sleeve.positions[ticker]
    sleeve.cash_rub += rub
    return TradeResult(
        sleeve_name,
        ticker,
        "sell",
        qty,
        price,
        rub,
        f"SELL {qty:.4f} @ {price:.2f} ({fraction:.0%})",
    )


def apply_core_signal(state: PortfolioState, signal: CoreSignal) -> TradeResult | None:
    sleeve = state.core
    price = signal.price

    if signal.action == CoreAction.BUY:
        rub = sleeve.cash_rub * TRADE_FRACTION
        result = _buy(sleeve, "core", signal.ticker, price, rub)
        if result:
            result.message = f"[CORE] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    if signal.action == CoreAction.TRIM:
        result = _sell(sleeve, "core", signal.ticker, price, TRIM_FRACTION)
        if result:
            result.message = f"[CORE TRIM] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    if signal.action == CoreAction.SELL:
        result = _sell(sleeve, "core", signal.ticker, price, 1.0)
        if result:
            result.message = f"[CORE] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    return None


def apply_satellite_signal(
    state: PortfolioState, signal: SatelliteSignal
) -> TradeResult | None:
    sleeve = state.satellite
    price = signal.price

    if signal.action == SatelliteAction.BUY:
        rub = sleeve.cash_rub * TRADE_FRACTION
        result = _buy(sleeve, "satellite", signal.ticker, price, rub)
        if result:
            result.message = f"[SAT] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    if signal.action == SatelliteAction.SELL:
        result = _sell(sleeve, "satellite", signal.ticker, price, 1.0)
        if result:
            result.message = f"[SAT] {signal.reason} — {result.message}"
            logger.info(result.message)
        return result

    return None
