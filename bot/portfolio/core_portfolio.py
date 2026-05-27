"""Сборка core-портфеля: акции + доля облигаций (SBGB)."""

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


def _has_bar(histories: dict[str, dict[date, OhlcBar]], ticker: str, as_of: date) -> bool:
    return as_of in histories.get(ticker, {})


def _passes_sma(
    histories: dict[str, dict[date, OhlcBar]],
    ticker: str,
    as_of: date,
    config: Config,
) -> bool:
    sma = config.core_trend_sma
    if sma <= 0:
        return True
    closes = closes_before(histories[ticker], as_of, sma + 5)
    if len(closes) < sma:
        return True
    s = sum(closes[-sma:]) / sma
    tol = config.scan_sma_tolerance_pct / 100.0
    return closes[-1] >= s * (1.0 - tol)


def select_core_holdings(
    histories: dict[str, dict[date, OhlcBar]],
    as_of: date,
    config: Config,
    *,
    universe: list[str] | None = None,
) -> list[str]:
    """
    Минимум CORE_MIN_POSITIONS имён из universe (порядок скана сохраняем).
    Не держим 100% в одной акции, если в universe есть альтернативы.
    """
    tickers = universe if universe is not None else config.core_universe
    if not tickers:
        return []

    min_n = max(1, min(config.core_min_positions, config.core_top_n))
    target_n = config.core_top_n
    candidates = [t for t in tickers if _has_bar(histories, t, as_of)]
    if not candidates:
        return []

    picked: list[str] = []

    if config.core_select_scan_order and universe:
        for t in candidates:
            if not _passes_sma(histories, t, as_of, config):
                continue
            picked.append(t)
            if len(picked) >= target_n:
                break

        if len(picked) < min_n:
            for t in candidates:
                if t in picked:
                    continue
                picked.append(t)
                if len(picked) >= min_n:
                    break

    if len(picked) < min_n:
        ranked = rank_by_momentum(
            histories,
            candidates,
            as_of,
            config.core_momentum_months,
            min_price_above_sma=None,
        )
        for t, _ in ranked:
            if t not in picked:
                picked.append(t)
            if len(picked) >= min_n:
                break

    if len(picked) < min_n:
        for t in candidates:
            if t not in picked:
                picked.append(t)
            if len(picked) >= min_n:
                break

    picked = picked[:target_n]
    if len(picked) < min_n:
        logger.warning(
            "Core: only %d stocks (min %d) on %s",
            len(picked),
            min_n,
            as_of,
        )
    else:
        logger.info("Core: %d stocks → %s", len(picked), ",".join(picked))
    return picked


def _rebalance_leg(
    state,
    ticker: str,
    target_rub: float,
    price: float,
    config: Config,
    tag: str,
) -> tuple[int, float]:
    trades = 0
    commissions = 0.0
    pos = state.core.positions.get(ticker)
    current = pos.qty * price if pos else 0.0
    delta = target_rub - current
    if delta > config.core_min_trade_rub:
        r = buy_with_rules(
            state.core,
            "core",
            ticker,
            price,
            min(delta, state.core.cash_rub * 0.99),
            config,
            min_trade_override=config.core_min_trade_rub,
            tag=tag,
        )
        if r:
            trades += 1
            commissions += r.commission_rub
    elif delta < -config.core_min_trade_rub and pos:
        fraction = min(1.0, abs(delta) / current) if current > 0 else 1.0
        r = sell_with_rules(
            state.core,
            "core",
            ticker,
            price,
            config,
            fraction,
            tag=tag,
            min_trade_override=0,
        )
        if r:
            trades += 1
            commissions += r.commission_rub
    return trades, commissions


def rebalance_core_portfolio(
    state: PortfolioState,
    prices: dict[str, float],
    histories: dict[str, dict[date, OhlcBar]],
    as_of: date,
    config: Config,
    *,
    extra_cash: float = 0,
    universe: list[str] | None = None,
    tag: str = "CORE",
) -> tuple[int, float]:
    state.core.cash_rub += extra_cash
    bond_t = config.bond_ticker.upper()
    bond_frac = max(0.0, min(config.bond_allocation_pct, 100.0)) / 100.0
    stock_frac = 1.0 - bond_frac

    holdings = select_core_holdings(histories, as_of, config, universe=universe)
    if not holdings and bond_frac <= 0:
        logger.warning("Core rebalance: no ranked tickers on %s", as_of)
        return 0, 0.0

    keep = set(holdings) | ({bond_t} if bond_frac > 0 else set())
    trades = 0
    commissions = 0.0

    for ticker in list(state.core.positions.keys()):
        if ticker in keep:
            continue
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

    if bond_frac > 0:
        bond_px = prices.get(bond_t)
        if bond_px and bond_px > 0:
            bt, bc = _rebalance_leg(
                state,
                bond_t,
                total_equity * bond_frac,
                bond_px,
                config,
                f"{tag} BOND",
            )
            trades += bt
            commissions += bc
        else:
            logger.warning("Bond %s: no price on %s — stock leg uses full equity", bond_t, as_of)

    if holdings and stock_frac > 0:
        weights = inverse_vol_weights(histories, holdings, as_of, config.core_vol_lookback)
        stock_pool = total_equity * stock_frac
        for ticker, w in weights.items():
            px = prices.get(ticker)
            if not px or px <= 0:
                continue
            tt, tc = _rebalance_leg(
                state,
                ticker,
                stock_pool * w,
                px,
                config,
                tag,
            )
            trades += tt
            commissions += tc
        logger.info(
            "[%s] stocks %s (%.0f%%) | %s",
            tag,
            ",".join(holdings),
            stock_frac * 100,
            ",".join(f"{t}:{weights[t]:.0%}" for t in holdings),
        )

    if bond_frac > 0:
        logger.info("[%s] bond %s target %.0f%%", tag, bond_t, bond_frac * 100)

    return trades, commissions
