"""Дивиденды по акциям MOEX ISS (на одну акцию, валюта выплаты)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://iss.moex.com/iss"
CACHE_DIR = Path("data/moex_cache/dividends")


@dataclass(frozen=True)
class DividendEvent:
    ticker: str
    registry_close: date
    value_per_share: float
    currency: str


def fetch_dividends(
    ticker: str,
    start: date,
    end: date,
    *,
    use_cache: bool = True,
) -> list[DividendEvent]:
    """События с датой отсечки (registryclosedate) в [start, end]."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{ticker}_{start}_{end}.json"
    if use_cache and cache_path.exists():
        raw = json.loads(cache_path.read_text())
        return [
            DividendEvent(
                ticker=ticker,
                registry_close=date.fromisoformat(e["registry_close"]),
                value_per_share=e["value"],
                currency=e["currency"],
            )
            for e in raw
        ]

    url = f"{BASE_URL}/securities/{ticker}/dividends.json"
    params = {"iss.meta": "off"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        payload = resp.json()

    rows = payload.get("dividends", {}).get("data", [])
    cols = payload.get("dividends", {}).get("columns", [])
    if not rows or not cols:
        return []

    idx = {c.lower(): i for i, c in enumerate(cols)}
    events: list[DividendEvent] = []
    for row in rows:
        try:
            reg = date.fromisoformat(str(row[idx["registryclosedate"]]).split()[0])
            value = float(row[idx["value"]])
            currency = str(row[idx.get("currencyid", idx.get("currency", "RUB"))])
        except (KeyError, ValueError, TypeError):
            continue
        if start <= reg <= end and value > 0:
            events.append(
                DividendEvent(
                    ticker=ticker,
                    registry_close=reg,
                    value_per_share=value,
                    currency=currency,
                )
            )

    events.sort(key=lambda e: e.registry_close)
    if use_cache:
        cache_path.write_text(
            json.dumps(
                [
                    {
                        "registry_close": e.registry_close.isoformat(),
                        "value": e.value_per_share,
                        "currency": e.currency,
                    }
                    for e in events
                ],
                ensure_ascii=False,
            )
        )
    return events


def load_dividends_by_day(
    tickers: list[str],
    start: date,
    end: date,
) -> dict[date, list[DividendEvent]]:
    """Все дивиденды по дате отсечки."""
    by_day: dict[date, list[DividendEvent]] = {}
    for t in tickers:
        for ev in fetch_dividends(t, start, end):
            by_day.setdefault(ev.registry_close, []).append(ev)
    return by_day


def events_on_day(
    tickers: list[str],
    day: date,
    *,
    lookback_days: int = 7,
) -> list[DividendEvent]:
    """События с отсечкой в [day - lookback, day] — на случай пропущенных циклов."""
    start = day - timedelta(days=lookback_days)
    out: list[DividendEvent] = []
    for t in tickers:
        for ev in fetch_dividends(t, start, day):
            if ev.registry_close == day:
                out.append(ev)
    return out
