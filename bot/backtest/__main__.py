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
            (end - timedelta(days=730)).isoformat(),
        )
    )
    initial = float(os.getenv("BACKTEST_INITIAL_RUB", "10000"))
    monthly = float(os.getenv("BACKTEST_MONTHLY_DEPOSIT_RUB", "2000"))

    print(
        f"Backtest: {start} → {end} | start {initial:,.0f} RUB | "
        f"+{monthly:,.0f} RUB/month"
    )
    print(f"Core universe ({len(config.core_universe)}): {', '.join(config.core_universe)}")
    print(
        f"Strategy: top {config.core_top_n} × {config.core_momentum_months}m momentum, "
        f"price > SMA({config.core_trend_sma}), 1/σ weights"
    )
    print(f"Sat: {', '.join(config.satellite_universe)} (from {config.satellite_min_equity_rub:,.0f} RUB)")
    print(f"Dividends in sim: {config.include_dividends} (tax {config.dividend_tax_pct:.0f}%)\n")

    result = run_backtest(config, start, end, initial, monthly)
    print_report(result, config)
    print("Open data/backtest_report.csv in Excel/Sheets for charts.")


if __name__ == "__main__":
    main()
