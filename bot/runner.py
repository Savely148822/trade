import logging
import time
from datetime import date, timedelta

from bot.brokers.finam import FinamBroker
from bot.config import Config
from bot.data.market_regime import fetch_market_regime, ticker_above_sma
from bot.data.moex_iss import fetch_daily_ohlc, fetch_history, fetch_last_price
from bot.portfolio.core_portfolio import rebalance_core_portfolio
from bot.portfolio.deposits import current_month_key, process_new_month
from bot.portfolio.executor import apply_satellite_signal
from bot.portfolio.rebalancer import (
    rebalance_portfolio,
    rebalance_satellite_profit_trim,
    should_rebalance_satellite_profit,
    should_rebalance_scheduled,
)
from bot.portfolio.state import load_state, save_state
from bot.risk.manager import check_risk
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


def _load_histories(tickers: list[str], lookback_days: int = 400) -> dict:
    end = date.today()
    start = end - timedelta(days=lookback_days)
    return {t: fetch_history(t, start, end) for t in tickers}


def run_cycle(config: Config) -> None:
    broker = FinamBroker(config.finam_token, config.paper_trading)
    mode = "PAPER" if config.paper_trading else "LIVE"
    state = load_state(config.paper_initial_rub, config.core_weight)

    all_tickers = list(set(config.core_universe + config.satellite_universe))
    prices = _collect_prices(all_tickers)
    today = date.today()
    histories = _load_histories(config.core_universe)

    month = current_month_key()
    if state.month_key != month:
        logger.info("--- New month: deposit + core portfolio rebalance ---")
        process_new_month(state, prices, histories, today, config, month)
        prices = _collect_prices(all_tickers)
    elif not state.core.positions and state.core.cash_rub >= config.min_trade_rub:
        logger.info("--- Initial core portfolio build ---")
        rebalance_core_portfolio(state, prices, histories, today, config, tag="INIT")
        prices = _collect_prices(all_tickers)

    profit_hit, profit_reason = should_rebalance_satellite_profit(
        state, prices, config.satellite_profit_rebalance_pct
    )
    if profit_hit:
        logger.info("--- Satellite profit trim: %s ---", profit_reason)
        rebalance_satellite_profit_trim(state, prices, config)
        prices = _collect_prices(all_tickers)

    if should_rebalance_scheduled(state, config.rebalance_interval_sec):
        logger.info("--- Scheduled 80/20 rebalance ---")
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
    _ = broker


def run_bot(config: Config) -> None:
    logger.info(
        "Capital engine | core top-%d momentum stocks | deposit %.0f RUB/mo | div=%s",
        config.core_top_n,
        config.monthly_deposit_rub,
        config.include_dividends,
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
