import logging
import time
from datetime import date, timedelta

from dotenv import load_dotenv

from bot.analytics.env_update import apply_scan_to_env
from bot.analytics.monthly_scan import save_scan_report, scan_promising_stocks
from bot.brokers.finam import FinamBroker
from bot.config import Config
from bot.data.moex_iss import fetch_history, fetch_last_price
from bot.portfolio.core_portfolio import rebalance_core_portfolio
from bot.portfolio.deposits import current_month_key, process_new_month
from bot.portfolio.dividends import process_dividends_through
from bot.portfolio.forecast_exits import apply_forecast_exits
from bot.portfolio.paper_status import log_paper_status
from bot.portfolio.state import load_state, save_state
from bot.risk.manager import check_risk

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


def run_monthly_scan_and_env(config: Config) -> list[str]:
    """Скан MOEX → отчёт → обновление .env → перезагрузка конфига."""
    report = scan_promising_stocks(config, date.today())
    save_scan_report(report)
    tickers = apply_scan_to_env(report)
    load_dotenv(override=True)
    logger.info("Monthly scan: CORE_UNIVERSE updated (%d tickers)", len(tickers))
    return tickers


def run_cycle(config: Config) -> None:
    broker = FinamBroker(config.finam_token, config.paper_trading)
    mode = "PAPER" if config.paper_trading else "LIVE"
    state = load_state(config.paper_initial_rub)

    month = current_month_key()
    if state.month_key != month:
        logger.info("=== New month: MOEX scan + .env + deposit + rebalance ===")
        universe = run_monthly_scan_and_env(config)
        config = Config.from_env()
        histories = _load_histories(universe)
        prices = _collect_prices(universe)
        process_new_month(state, prices, histories, date.today(), config, month, universe=universe)
    elif not state.core.positions and state.core.cash_rub >= config.core_min_trade_rub:
        universe = config.core_universe
        histories = _load_histories(universe)
        prices = _collect_prices(universe)
        rebalance_core_portfolio(
            state, prices, histories, date.today(), config, universe=universe, tag="INIT"
        )

    tickers = list(set(config.core_universe) | set(state.core.positions.keys()))
    prices = _collect_prices(tickers)

    if config.include_dividends and state.core.positions:
        div_net = process_dividends_through(state, date.today(), config)
        if div_net > 0:
            logger.info("Dividends credited: +%.0f RUB (total %.0f RUB)", div_net, state.total_dividends_net_rub)
            prices = _collect_prices(tickers)

    if state.core.positions and config.exit_on_negative_forecast:
        held = list(state.core.positions.keys())
        histories = _load_histories(held)
        ex_trades, ex_fees = apply_forecast_exits(
            state, prices, histories, config, date.today()
        )
        if ex_trades:
            logger.info("Forecast exits: %d sells, fees %.0f RUB", ex_trades, ex_fees)
            prices = _collect_prices(tickers)

    risk = check_risk(state, prices, config.max_drawdown_pct)
    equity = state.core.equity(prices)

    log_paper_status(state, prices, config)
    logger.info(
        "=== [%s] equity=%.0f RUB | DD=%.1f%% | universe %d | %s ===",
        mode,
        equity,
        risk.drawdown_pct,
        len(config.core_universe),
        risk.message,
    )
    save_state(state)
    _ = broker


def run_bot(config: Config) -> None:
    logger.info(
        "Core-only engine | scan top-%d / hold top-%d | deposit %.0f RUB/mo",
        config.scan_top_n,
        config.core_top_n,
        config.monthly_deposit_rub,
    )
    while True:
        try:
            run_cycle(config)
            load_dotenv(override=True)
            config = Config.from_env()
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception:
            logger.exception("Cycle error")
        time.sleep(config.poll_interval_sec)
