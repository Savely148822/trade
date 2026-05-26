"""Снимок рынка акций MOEX (борд TQBR)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://iss.moex.com/iss"
BOARD = "TQBR"

# БПИФ / ETF иногда торгуются на TQBR — отсекаем по тикеру
ETF_LIKE = frozenset(
    {
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
        "VTBX",
        "AKMB",
        "AMRE",
    }
)


@dataclass(frozen=True)
class MarketSnapshot:
    ticker: str
    last: float
    valtoday_rub: float
    voltoday: float
    numtrades: int


def fetch_tqbr_market_snapshot() -> list[MarketSnapshot]:
    """Все акции TQBR с оборотом за сегодня (MOEX ISS)."""
    url = (
        f"{BASE_URL}/engines/stock/markets/shares/boards/{BOARD}/securities.json"
    )
    params = {
        "iss.meta": "off",
        "iss.only": "marketdata",
        "marketdata.columns": "SECID,LAST,VOLTODAY,VALTODAY,NUMTRADES",
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()

    rows = payload.get("marketdata", {}).get("data", [])
    out: list[MarketSnapshot] = []
    for row in rows:
        if not row or row[0] in ETF_LIKE:
            continue
        try:
            last = float(row[1]) if row[1] is not None else 0.0
            valtoday = float(row[3]) if row[3] is not None else 0.0
            voltoday = float(row[2]) if row[2] is not None else 0.0
            numtrades = int(row[4]) if row[4] is not None else 0
        except (TypeError, ValueError):
            continue
        if last <= 0 or valtoday <= 0 or numtrades <= 0:
            continue
        out.append(
            MarketSnapshot(
                ticker=str(row[0]).upper(),
                last=last,
                valtoday_rub=valtoday,
                voltoday=voltoday,
                numtrades=numtrades,
            )
        )
    return out
