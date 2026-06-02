import logging
import time

from bot.config import Config
from bot.exchange import ExchangeClient
from bot.strategy import Signal, ma_crossover_signal

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_bot(config: Config) -> None:
    client = ExchangeClient(config)
    mode = "PAPER" if config.paper_trading else "LIVE"

    logger.info(
        "Bot started [%s] %s on %s | %s | MA(%d/%d)",
        mode,
        config.exchange_id,
        config.symbol,
        config.timeframe,
        config.fast_ma_period,
        config.slow_ma_period,
    )
    logger.info(
        "Balances: quote=%.2f base=%.8f",
        client.balances.quote,
        client.balances.base,
    )

    while True:
        try:
            closes = client.fetch_ohlcv()
            result = ma_crossover_signal(
                closes,
                config.fast_ma_period,
                config.slow_ma_period,
            )

            if result is None:
                logger.info("Not enough candles, waiting...")
            else:
                logger.info(
                    "Price=%.2f fast_ma=%.2f slow_ma=%.2f signal=%s",
                    result.price,
                    result.fast_ma,
                    result.slow_ma,
                    result.signal.value,
                )
                if result.signal != Signal.HOLD:
                    client.execute_signal(result.signal.value, result.price)

            logger.info(
                "Portfolio: quote=%.2f base=%.8f",
                client.balances.quote,
                client.balances.base,
            )
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception:
            logger.exception("Error in main loop")

        time.sleep(config.poll_interval_sec)
