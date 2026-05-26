import logging
import os
from datetime import date, timedelta

from bot.backtest.engine import print_report, run_backtest
from bot.config import Config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = Config.from_env()
    end = date.fromisoformat(os.getenv("BACKTEST_END", date.today().isoformat()))
    start = date.fromisoformat(
        os.getenv(
            "BACKTEST_START",
            (end - timedelta(days=365)).isoformat(),
        )
    )
    initial = float(os.getenv("BACKTEST_INITIAL_RUB", "10000"))
    monthly = float(os.getenv("BACKTEST_MONTHLY_DEPOSIT_RUB", "1000"))

    print(
        f"Backtest: {start} → {end} | start {initial:,.0f} RUB | "
        f"+{monthly:,.0f} RUB/month"
    )
    print(f"Core: {', '.join(config.core_universe)}")
    print(f"Sat:  {', '.join(config.satellite_universe)}\n")

    result = run_backtest(config, start, end, initial, monthly)
    print_report(result)


if __name__ == "__main__":
    main()
