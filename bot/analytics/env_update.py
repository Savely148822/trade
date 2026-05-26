"""Обновление CORE_UNIVERSE в .env после месячного скана."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from bot.analytics.monthly_scan import ScanReport

logger = logging.getLogger(__name__)

ENV_PATH = Path(".env")
CORE_UNIVERSE_KEY = "CORE_UNIVERSE"


def update_core_universe_env(
    tickers: list[str],
    env_path: Path = ENV_PATH,
) -> None:
    if not tickers:
        logger.warning("Empty ticker list — .env not updated")
        return

    value = ",".join(tickers)
    line = f"{CORE_UNIVERSE_KEY}={value}\n"

    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        pattern = re.compile(rf"^{CORE_UNIVERSE_KEY}=.*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(f"{CORE_UNIVERSE_KEY}={value}", text)
        else:
            text = text.rstrip() + "\n" + line
        env_path.write_text(text, encoding="utf-8")
    else:
        env_path.write_text(line, encoding="utf-8")

    logger.info("Updated %s with %d tickers", env_path, len(tickers))


def apply_scan_to_env(report: ScanReport, env_path: Path = ENV_PATH) -> list[str]:
    tickers = [p.ticker for p in report.picks]
    if not tickers:
        logger.warning("No picks — .env left unchanged")
        return []
    update_core_universe_env(tickers, env_path)
    return tickers
