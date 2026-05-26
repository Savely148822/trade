import logging
import time

from bot.brokers.finam import FinamBroker
from bot.config import Config
from bot.data.market_regime import fetch_market_regime, ticker_above_sma
from bot.data.moex_iss import fetch_daily_closes, fetch_daily_ohlc, fetch_last_price
from bot.portfolio.deposits import current_month_key, process_new_month
from bot.portfolio.executor import apply_core_signal, apply_satellite_signal
from bot.portfolio.rebalancer import (
    rebalance_portfolio,
    rebalance_satellite_profit_trim,
    should_rebalance_satellite_profit,
    should_rebalance_scheduled,
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


def _sum_commission(result) -> float:
    return result.commission_rub if result else 0.0


def run_cycle(config: Config) -> None:
    broker = FinamBroker(config.finam_token, config.paper_trading)
    mode = "PAPER" if config.paper_trading else "LIVE"
    state = load_state(config.paper_initial_rub, config.core_weight)

    all_tickers = list(
        set(config.core_universe + config.satellite_universe + config.core_dca_universe)
    )
    prices = _collect_prices(all_tickers)

    month = current_month_key()
    if state.month_key != month:
        logger.info("--- New month: deposit + DCA + rebalance ---")
        process_new_month(state, prices, config, month)
        prices = _collect_prices(all_tickers)

    profit_hit, profit_reason = should_rebalance_satellite_profit(
        state, prices, config.satellite_profit_rebalance_pct
    )
    if profit_hit:
        logger.info("--- Satellite profit trim: %s ---", profit_reason)
        rebalance_satellite_profit_trim(state, prices, config)
        prices = _collect_prices(all_tickers)

    if should_rebalance_scheduled(state, config.rebalance_interval_sec):
        logger.info("--- Scheduled monthly rebalance ---")
        rebalance_portfolio(state, prices, config)
        prices = _collect_prices(all_tickers)

    risk = check_risk(
        state,
        prices,
        config.max_drawdown_pct,
        config.satellite_monthly_loss_cap_pct,
    )
    equity = state.total_equity(prices)

    logger.info(
        "=== Cycle [%s] equity=%.0f RUB | DD=%.1f%% | %s ===",
        mode,
        equity,
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
                apply_core_signal(state, sig, config)

    buy_candidates = [s for s in core_signals if s.action == CoreAction.BUY]
    if buy_candidates:
        best = max(buy_candidates, key=lambda s: s.score)
        apply_core_signal(state, best, config)

    regime = fetch_market_regime(
        config.market_index,
        config.satellite_index_sma_period,
    )
    sat_allowed = equity >= config.satellite_min_equity_rub

    if risk.allow_satellite and regime.allow_satellite_trades and sat_allowed:
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
                continue
            logger.info("SAT %s: %s — %s", ticker, sig.action.value, sig.reason)
            apply_satellite_signal(state, sig, config)
    elif not sat_allowed:
        logger.info(
            "Satellite off: equity %.0f < min %.0f RUB",
            equity,
            config.satellite_min_equity_rub,
        )
    elif not risk.allow_satellite:
        logger.warning("Satellite paused (risk): %s", risk.message)
    else:
        logger.warning("Satellite paused (market): %s", regime.reason)

    prices = _collect_prices(all_tickers)
    equity = state.total_equity(prices)
    core_eq = state.core.equity(prices)
    sat_eq = state.satellite.equity(prices)
    logger.info(
        "Portfolio: equity=%.0f | core=%.0f (%.1f%%) | sat=%.0f (%.1f%%)",
        equity,
        core_eq,
        (core_eq / equity * 100) if equity else 0,
        sat_eq,
        (sat_eq / equity * 100) if equity else 0,
    )
    save_state(state)


def run_bot(config: Config) -> None:
    logger.info(
        "Capital engine | core %.0f%% | deposit %.0f RUB/mo | DCA=%s | sat if equity>=%.0f",
        config.core_weight * 100,
        config.monthly_deposit_rub,
        config.core_dca_enabled,
        config.satellite_min_equity_rub,
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
