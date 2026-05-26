import logging
import time

from bot.brokers.finam import FinamBroker
from bot.config import Config
from bot.data.moex_iss import fetch_daily_closes, fetch_daily_ohlc, fetch_last_price
from bot.portfolio.executor import apply_core_signal, apply_satellite_signal
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

    risk = check_risk(
        state,
        prices,
        config.max_drawdown_pct,
        config.satellite_monthly_loss_cap_pct,
    )
    equity = state.total_equity(prices)

    logger.info(
        "=== Cycle [%s / Finam] equity=%.0f RUB | drawdown=%.1f%% | %s ===",
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
                apply_core_signal(state, sig)

    buy_candidates = [s for s in core_signals if s.action == CoreAction.BUY]
    if buy_candidates:
        best = max(buy_candidates, key=lambda s: s.score)
        apply_core_signal(state, best)

    if risk.allow_satellite:
        for ticker in config.satellite_universe:
            bars = fetch_daily_ohlc(
                ticker, days=config.satellite_breakout_bars + config.satellite_atr_period + 10
            )
            if not bars:
                continue
            highs = [b.high for b in bars]
            lows = [b.low for b in bars]
            closes = [b.close for b in bars]
            sig = evaluate_satellite(
                ticker,
                highs,
                lows,
                closes,
                config.satellite_breakout_bars,
                config.satellite_atr_period,
            )
            if not sig or sig.action == SatelliteAction.HOLD:
                continue
            logger.info("SAT %s: %s — %s", ticker, sig.action.value, sig.reason)
            apply_satellite_signal(state, sig)
    else:
        logger.warning("Satellite trading paused: %s", risk.message)

    if not config.paper_trading and broker.is_live_ready():
        logger.warning("Live mode: implement Finam order routing in phase 2")

    prices = _collect_prices(all_tickers)
    equity = state.total_equity(prices)
    logger.info(
        "Portfolio: equity=%.0f | core cash=%.0f | sat cash=%.0f | positions core=%s sat=%s",
        equity,
        state.core.cash_rub,
        state.satellite.cash_rub,
        list(state.core.positions.keys()),
        list(state.satellite.positions.keys()),
    )
    save_state(state)


def run_bot(config: Config) -> None:
    logger.info(
        "Capital engine started | core %.0f%% / satellite %.0f%% | broker=Finam",
        config.core_weight * 100,
        config.satellite_weight * 100,
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
