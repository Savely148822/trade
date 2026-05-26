import logging
import time

from bot.brokers.finam import FinamBroker
from bot.config import Config
from bot.data.market_regime import fetch_market_regime, ticker_above_sma
from bot.data.moex_iss import fetch_daily_closes, fetch_daily_ohlc, fetch_last_price
from bot.portfolio.executor import apply_core_signal, apply_satellite_signal
from bot.portfolio.rebalancer import (
    rebalance_portfolio,
    should_rebalance,
    should_rebalance_satellite_profit,
)
from bot.portfolio.state import load_state, save_state
from bot.risk.manager import check_risk
from bot.strategies.core_momentum import CoreAction, evaluate_core
from bot.strategies.satellite_breakout import SatelliteAction, evaluate_satellite

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _collect_prices(tickers: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for t in tickers:
        px = fetch_last_price(t)
        if px is not None:
            prices[t] = px
    return prices


def run_cycle(config: Config) -> None:
    broker = FinamBroker(config.finam_token, config.paper_trading)
    mode = "PAPER" if config.paper_trading else "LIVE"
    state = load_state(config.paper_initial_rub, config.core_weight)

    all_tickers = list(set(config.core_universe + config.satellite_universe))
    prices = _collect_prices(all_tickers)

    profit_hit, profit_reason = should_rebalance_satellite_profit(
        state,
        prices,
        config.satellite_profit_rebalance_pct,
    )
    scheduled = should_rebalance(state, config.rebalance_interval_sec)

    if profit_hit or scheduled:
        if profit_hit:
            logger.info("--- Profit rebalance: %s ---", profit_reason)
            rebalance_portfolio(
                state,
                prices,
                config.core_weight,
                config.satellite_weight,
                full_liquidate=True,
                trigger="satellite_profit",
            )
        else:
            logger.info("--- Scheduled rebalance (80/20 from total equity) ---")
            rebalance_portfolio(
                state,
                prices,
                config.core_weight,
                config.satellite_weight,
                trigger="scheduled",
            )
        prices = _collect_prices(all_tickers)

    risk = check_risk(
        state,
        prices,
        config.max_drawdown_pct,
        config.satellite_monthly_loss_cap_pct,
    )
    equity = state.total_equity(prices)
    total_pnl = equity - state.initial_equity
    total_pnl_pct = (total_pnl / state.initial_equity * 100) if state.initial_equity else 0

    logger.info(
        "=== Cycle [%s] equity=%.0f RUB | total PnL %+.0f (%+.2f%%) | DD=%.1f%% | %s ===",
        mode,
        equity,
        total_pnl,
        total_pnl_pct,
        risk.drawdown_pct,
        risk.message,
    )

    core_signals = []
    for ticker in config.core_universe:
        closes = fetch_daily_closes(ticker, days=config.core_ma_slow + 30)
        sig = evaluate_core(
            ticker,
            closes,
            config.core_ma_fast,
            config.core_ma_slow,
            config.core_momentum_months,
        )
        if sig:
            logger.info(
                "CORE %s: %s (score=%.1f) — %s",
                ticker,
                sig.action.value,
                sig.score,
                sig.reason,
            )
            core_signals.append(sig)
            if sig.action in (CoreAction.SELL, CoreAction.TRIM):
                apply_core_signal(state, sig)

    buy_candidates = [s for s in core_signals if s.action == CoreAction.BUY]
    if buy_candidates:
        best = max(buy_candidates, key=lambda s: s.score)
        apply_core_signal(state, best)

    regime = fetch_market_regime(
        config.market_index,
        config.satellite_index_sma_period,
    )
    logger.info(
        "Market %s: %.2f / SMA=%.2f — %s",
        regime.index,
        regime.price,
        regime.sma,
        regime.reason,
    )

    if risk.allow_satellite and regime.allow_satellite_trades:
        for ticker in config.satellite_universe:
            bars = fetch_daily_ohlc(
                ticker,
                days=max(
                    config.satellite_breakout_bars + config.satellite_atr_period + 30,
                    config.satellite_ticker_sma_period + 10,
                ),
            )
            if not bars:
                continue

            closes = [b.close for b in bars]
            if not ticker_above_sma(closes, config.satellite_ticker_sma_period):
                logger.info(
                    "SAT %s skipped: below SMA(%d) on D1",
                    ticker,
                    config.satellite_ticker_sma_period,
                )
                continue

            sig = evaluate_satellite(
                ticker,
                [b.high for b in bars],
                [b.low for b in bars],
                closes,
                [b.volume for b in bars],
                config.satellite_breakout_bars,
                config.satellite_atr_period,
                config.satellite_min_rvol,
                config.satellite_require_close_confirm,
            )
            if not sig or sig.action == SatelliteAction.HOLD:
                if sig and sig.reason:
                    logger.debug("SAT %s hold: %s", ticker, sig.reason)
                continue
            logger.info(
                "SAT %s: %s — %s",
                ticker,
                sig.action.value,
                sig.reason,
            )
            apply_satellite_signal(state, sig)
    elif not risk.allow_satellite:
        logger.warning("Satellite paused (risk): %s", risk.message)
    else:
        logger.warning("Satellite paused (market): %s", regime.reason)

    if not config.paper_trading and broker.is_live_ready():
        logger.warning("Live mode: implement Finam order routing in phase 2")

    prices = _collect_prices(all_tickers)
    equity = state.total_equity(prices)
    core_eq = state.core.equity(prices)
    sat_eq = state.satellite.equity(prices)
    logger.info(
        "Portfolio: equity=%.0f | core=%.0f (%.1f%%) | sat=%.0f (%.1f%%) | pos core=%s sat=%s",
        equity,
        core_eq,
        (core_eq / equity * 100) if equity else 0,
        sat_eq,
        (sat_eq / equity * 100) if equity else 0,
        list(state.core.positions.keys()),
        list(state.satellite.positions.keys()),
    )
    save_state(state)


def run_bot(config: Config) -> None:
    rebalance_hours = config.rebalance_interval_sec / 3600
    logger.info(
        "Capital engine | core %.0f%% / sat %.0f%% | rebalance every %.1f h",
        config.core_weight * 100,
        config.satellite_weight * 100,
        rebalance_hours,
    )
    while True:
        try:
            run_cycle(config)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception:
            logger.exception("Cycle error")
        time.sleep(config.poll_interval_sec)
