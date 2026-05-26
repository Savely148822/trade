"""Клиент публичного API Московской биржи (ISS)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://iss.moex.com/iss"

# TQBR — акции, TQTF — БПИФ/ETF
BOARD_BY_PREFIX: dict[str, str] = {}


def resolve_board(ticker: str) -> str:
    """Подбор режима торгов по тикеру (упрощённо)."""
    etf_like = (
        "SBMX",
        "TMOS",
        "TRUR",
        "SBGB",
        "LQDT",
        "TBRU",
        "TEMS",
        "TEUS",
        "TPAS",
        "GOLD",
        "SBGD",
    )
    if ticker in etf_like or ticker.startswith("TQ"):
        return "TQTF"
    return "TQBR"


@dataclass
class OhlcBar:
    open: float
    high: float
    low: float
    close: float
    volume: float


def _fetch_candles(ticker: str, days: int) -> list[list[float]]:
    board = resolve_board(ticker)
    url = (
        f"{BASE_URL}/engines/stock/markets/shares/boards/{board}"
        f"/securities/{ticker}/candles.json"
    )
    start = date.today() - timedelta(days=days + 30)
    params = {
        "interval": 24,
        "from": start.isoformat(),
        "iss.meta": "off",
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()

    candles = payload.get("candles", {}).get("data", [])
    if not candles:
        logger.warning("No candles for %s (board %s)", ticker, board)
        return []
    return candles[-days:]


def fetch_daily_closes(ticker: str, days: int = 250) -> list[float]:
    candles = _fetch_candles(ticker, days)
    return [float(row[1]) for row in candles]


def fetch_daily_ohlc(ticker: str, days: int = 120) -> list[OhlcBar]:
    candles = _fetch_candles(ticker, days)
    bars: list[OhlcBar] = []
    for row in candles:
        bars.append(
            OhlcBar(
                open=float(row[0]),
                close=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                volume=float(row[5]),
            )
        )
    return bars


def fetch_last_price(ticker: str) -> float | None:
    closes = fetch_daily_closes(ticker, days=5)
    return closes[-1] if closes else None


def fetch_index_closes(index: str, days: int = 120) -> list[float]:
    start = date.today() - timedelta(days=days + 30)
    url = (
        f"{BASE_URL}/engines/stock/markets/index/securities/{index}/candles.json"
    )
    params = {
        "interval": 24,
        "from": start.isoformat(),
        "iss.meta": "off",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()

    candles = payload.get("candles", {}).get("data", [])
    return [float(row[1]) for row in candles[-days:]]


def fetch_security_info(ticker: str) -> dict[str, Any] | None:
    url = f"{BASE_URL}/securities/{ticker}.json"
    params = {"iss.meta": "off"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        payload = resp.json()

    rows = payload.get("securities", {}).get("data", [])
    cols = payload.get("securities", {}).get("columns", [])
    if not rows:
        return None
    return dict(zip(cols, rows[0], strict=False))
