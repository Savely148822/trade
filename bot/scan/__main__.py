"""Запуск месячного скана: python -m bot.scan"""

import logging
from datetime import date

from dotenv import load_dotenv

from bot.analytics.env_update import apply_scan_to_env
from bot.analytics.monthly_scan import print_scan_report, save_scan_report, scan_promising_stocks
from bot.config import Config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()
    config = Config.from_env()

    report = scan_promising_stocks(config, date.today())
    print_scan_report(report)
    path = save_scan_report(report)
    tickers = apply_scan_to_env(report)
    load_dotenv(override=True)
    print(f"Saved: {path}")
    if tickers:
        print(f"Updated .env CORE_UNIVERSE ({len(tickers)} tickers)")
    else:
        print("No tickers passed strict forecast filters — .env unchanged")
    print("Reload config in bot on next cycle.\n")


if __name__ == "__main__":
    main()
