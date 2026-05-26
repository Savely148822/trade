"""Walk-forward replay на истории (2 года по умолчанию) — та же логика, что paper."""

import logging
import os
from datetime import date, timedelta

from bot.backtest.engine import print_report, run_paper_replay
from bot.config import Config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = Config.from_env()
    end = date.fromisoformat(os.getenv("BACKTEST_END", date.today().isoformat()))
    start = date.fromisoformat(
        os.getenv("BACKTEST_START", (end - timedelta(days=730)).isoformat())
    )
    initial = float(os.getenv("BACKTEST_INITIAL_RUB", str(config.paper_initial_rub)))
    monthly = float(os.getenv("BACKTEST_MONTHLY_DEPOSIT_RUB", str(config.monthly_deposit_rub)))

    print(
        f"Paper replay: {start} → {end} | {initial:,.0f} + {monthly:,.0f}/mo | "
        f"scan {config.scan_top_n} / hold {config.core_top_n} | "
        f"adaptive fill min {config.scan_min_universe}\n"
    )
    result = run_paper_replay(config, start, end, initial, monthly)
    print_report(result, config)


if __name__ == "__main__":
    main()
