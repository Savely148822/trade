"""Макро: IMOEX, USD/RUB (MOEX), ключевая ставка ЦБ."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from bot.data.moex_iss import fetch_index_history

logger = logging.getLogger(__name__)

CBR_KEYRATE_FALLBACK_PCT = 21.0
_KEY_RATE_CACHE: float | None = None


@dataclass(frozen=True)
class MacroSnapshot:
    as_of: date
    imoex_mom_1m: float
    imoex_mom_3m: float
    usdrub_mom_1m: float
    cbr_key_rate_pct: float
    risk_on_score: float  # выше = благоприятнее для акций РФ


def _mom_from_closes(closes: list[float], days: int) -> float:
    if len(closes) < days + 1:
        return 0.0
    start = closes[-days - 1]
    end = closes[-1]
    if start <= 0:
        return 0.0
    return (end - start) / start


def fetch_usdrub_history(start: date, end: date) -> dict[date, float]:
    url = (
        "https://iss.moex.com/iss/engines/currency/markets/selt"
        "/securities/USD000UTSTOM/candles.json"
    )
    params = {
        "interval": 24,
        "from": start.isoformat(),
        "till": end.isoformat(),
        "iss.meta": "off",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()

    out: dict[date, float] = {}
    for row in payload.get("candles", {}).get("data", []):
        day = date.fromisoformat(str(row[6]).split()[0])
        if start <= day <= end:
            out[day] = float(row[1])
    return out


def fetch_cbr_key_rate() -> float:
    """Ключевая ставка ЦБ, %. ISS/ЦБ API нестабилен — fallback из env."""
    global _KEY_RATE_CACHE
    if _KEY_RATE_CACHE is not None:
        return _KEY_RATE_CACHE

    import os

    fallback = float(os.getenv("CBR_KEY_RATE_PCT", str(CBR_KEYRATE_FALLBACK_PCT)))
    try:
        url = "https://www.cbr.ru/hd_base/KeyRate/"
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
        import re

        m = re.findall(r"(\d{1,2}[,.]\d+)\s*%", resp.text)
        if m:
            _KEY_RATE_CACHE = float(m[-1].replace(",", "."))
            return _KEY_RATE_CACHE
    except Exception as e:
        logger.debug("CBR key rate: %s — using fallback %.1f%%", e, fallback)
    _KEY_RATE_CACHE = fallback
    return _KEY_RATE_CACHE


def build_macro_snapshot(as_of: date, index_ticker: str = "IMOEX") -> MacroSnapshot:
    start = as_of - timedelta(days=120)
    index = fetch_index_history(index_ticker, start, as_of)
    idx_closes = [index[d] for d in sorted(index) if d <= as_of]
    fx = fetch_usdrub_history(start, as_of)
    fx_closes = [fx[d] for d in sorted(fx) if d <= as_of]

    imoex_1m = _mom_from_closes(idx_closes, 21)
    imoex_3m = _mom_from_closes(idx_closes, 63)
    usd_1m = _mom_from_closes(fx_closes, 21) if fx_closes else 0.0
    key_rate = fetch_cbr_key_rate()

    # risk_on: растущий рынок, не убегание в USD, умеренная ставка
    risk = imoex_1m * 2.0 - usd_1m * 0.5 - (key_rate / 100) * 0.1

    return MacroSnapshot(
        as_of=as_of,
        imoex_mom_1m=imoex_1m,
        imoex_mom_3m=imoex_3m,
        usdrub_mom_1m=usd_1m,
        cbr_key_rate_pct=key_rate,
        risk_on_score=risk,
    )
