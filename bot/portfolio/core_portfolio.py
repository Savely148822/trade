"""Сборка core-портфеля из акций: momentum + веса обратно волатильности."""

from __future__ import annotations

import logging
import math
from datetime import date

from bot.config import Config
from bot.data.moex_iss import OhlcBar, closes_before
from bot.portfolio.executor import buy_with_rules, sell_with_rules
from bot.portfolio.state import PortfolioState
from bot.strategies.cross_sectional import rank_by_momentum

logger = logging.getLogger(__name__)


def _realized_vol(closes: list[float], period: int = 20) -> float | None:
    if len(closes) < period + 1:
        return None
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(-period, 0)
        if closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def inverse_vol_weights(
    histories: dict[str, dict[date, OhlcBar]],
    tickers: list[str],
    as_of: date,
    vol_lookback: int = 20,
) -> dict[str, float]:
    inv: dict[str, float] = {}
    for t in tickers:
        closes = closes_before(histories.get(t, {}), as_of, vol_lookback + 5)
        vol = _realized_vol(closes, vol_lookback)
        if vol and vol > 1e-6:
            inv[t] = 1.0 / vol
        else:
            inv[t] = 1.0
    total = sum(inv.values())
    if total <= 0:
        n = len(tickers) or 1
        return {t: 1.0 / n for t in tickers}
    return {t: v / total for t, v in inv.items()}


def select_core_holdings(
    histories: dict[str, dict[date, OhlcBar]],
    as_of: date,
    config: Config,
) -> list[str]:
    sma = config.core_trend_sma if config.core_trend_sma > 0 else None
    ranked = rank_by_momentum(
        histories,
        config.core_universe,
        as_of,
        config.core_momentum_months,
        min_price_above_sma=sma,
    )
    if not ranked and sma:
        ranked = rank_by_momentum(
            histories,
            config.core_universe,
            as_of,
            config.core_momentum_months,
            min_price_above_sma=None,
        )
        if ranked:
            logger.info("Core: SMA(%s) filter empty — using momentum only", sma)
    if not ranked:
        # Крайний случай: равные веса по тем, у кого есть цена
        fallback = [t for t in config.core_universe if as_of in histories.get(t, {})]
        return fallback[: config.core_top_n]
    return [t for t, _ in ranked[: config.core_top_n]]


def rebalance_core_portfolio(
    state: PortfolioState,
    prices: dict[str, float],
    histories: dict[str, dict[date, OhlcBar]],
    as_of: date,
    config: Config,
    *,
    extra_cash: float = 0,
    tag: str = "CORE",
) -> tuple[int, float]:
    """
    Подгонка core к top-N momentum с весами 1/σ.
    extra_cash — новое пополнение в core перед ребалансом.
    """
    state.core.cash_rub += extra_cash
    holdings = select_core_holdings(histories, as_of, config)
    if not holdings:
        logger.warning("Core rebalance: no ranked tickers on %s", as_of)
        return 0, 0.0

    weights = inverse_vol_weights(histories, holdings, as_of, config.core_vol_lookback)
    trades = 0
    commissions = 0.0

    # Продажа бумаг вне списка
    for ticker in list(state.core.positions.keys()):
        if ticker not in holdings:
            px = prices.get(ticker)
            if not px:
                continue
            r = sell_with_rules(
                state.core, "core", ticker, px, config, 1.0, tag=tag, min_trade_override=0
            )
            if r:
                trades += 1
                commissions += r.commission_rub

    total_equity = state.core.equity(prices)
    if total_equity <= 0:
        return trades, commissions

    for ticker, w in weights.items():
        px = prices.get(ticker)
        if not px or px <= 0:
            continue
        target_rub = total_equity * w
        pos = state.core.positions.get(ticker)
        current_rub = pos.qty * px if pos else 0.0
        delta = target_rub - current_rub

        if delta > config.min_trade_rub:
            r = buy_with_rules(
                state.core,
                "core",
                ticker,
                px,
                min(delta, state.core.cash_rub * 0.99),
                config,
                min_trade_override=config.core_min_trade_rub,
                tag=tag,
            )
            if r:
                trades += 1
                commissions += r.commission_rub
        elif delta < -config.min_trade_rub and pos:
            fraction = min(1.0, abs(delta) / current_rub) if current_rub > 0 else 1.0
            r = sell_with_rules(
                state.core,
                "core",
                ticker,
                px,
                config,
                fraction,
                tag=tag,
                min_trade_override=0,
            )
            if r:
                trades += 1
                commissions += r.commission_rub

    logger.info(
        "[%s] holdings %s | weights %s",
        tag,
        ",".join(holdings),
        ",".join(f"{t}:{weights[t]:.0%}" for t in holdings),
    )
    return trades, commissions
