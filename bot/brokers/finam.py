"""Адаптер Finam Trade API.

Фаза 1: paper через portfolio/executor.
Фаза 2: реализовать place_order через https://tradeapi.finam.ru/
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class FinamBroker:
    def __init__(self, token: str, paper: bool) -> None:
        self.token = token
        self.paper = paper

    def is_live_ready(self) -> bool:
        return bool(self.token) and not self.paper

    def place_market_order(self, ticker: str, side: str, qty: float) -> str:
        if self.paper:
            raise RuntimeError("Live orders disabled in paper mode")
        if not self.token:
            raise RuntimeError("FINAM_TOKEN is required for live trading")
        # TODO фаза 2: POST /orders через Trade API
        raise NotImplementedError(
            "Finam live orders — фаза 2. См. docs/ACTION_PLAN.md"
        )
