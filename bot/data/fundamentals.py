"""Фундаментал: МСФО (ЦКИ MOEX при доступе) + публичные прокси с ISS."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from bot.data.moex_iss import OhlcBar

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/moex_cache/fundamentals")
CCI_MSFO_URL = "https://iss.moex.com/iss/cci/accounting/msfo-full/indicators.json"
_CCI_MSFO_DISABLED = CACHE_DIR / "_cci_msfo_unavailable"


@dataclass(frozen=True)
class FundamentalSnapshot:
    ticker: str
    list_level: int
    market_cap_rub: float
    revenue_growth_proxy: float  # динамика оборота 3м
    msfo_available: bool
    net_margin_proxy: float | None  # из МСФО, если есть
    roe_proxy: float | None
    source_note: str


def _fetch_security_static(ticker: str) -> dict:
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
    params = {"iss.meta": "off", "iss.only": "securities"}
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    cols = payload["securities"]["columns"]
    row = payload["securities"]["data"][0]
    return dict(zip(cols, row, strict=False))


def revenue_growth_proxy(series: dict[date, OhlcBar], as_of: date) -> float:
    return _revenue_growth_proxy(series, as_of)


def _revenue_growth_proxy(series: dict[date, OhlcBar], as_of: date) -> float:
    days = sorted(d for d in series if d <= as_of)
    if len(days) < 80:
        return 0.0
    recent = days[-63:]
    prior = days[-126:-63]
    if not prior:
        return 0.0

    def _avg_turnover(dlist: list[date]) -> float:
        vals = [series[d].close * series[d].volume for d in dlist]
        return sum(vals) / len(vals) if vals else 0.0

    a = _avg_turnover(recent)
    b = _avg_turnover(prior)
    if b <= 0:
        return 0.0
    return (a - b) / b


def _try_fetch_msfo_cci(ticker: str) -> dict[str, float] | None:
    """ЦКИ MOEX — нужна подписка; при отказе возвращает None."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if _CCI_MSFO_DISABLED.exists():
        return None
    cache = CACHE_DIR / f"msfo_{ticker}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    try:
        params = {"iss.meta": "off", "limit": 50}
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(CCI_MSFO_URL, params=params)
        if "json" not in (resp.headers.get("content-type") or "").lower():
            _CCI_MSFO_DISABLED.write_text("1")
            return None
        payload = resp.json()
        # Структура ЦКИ varies; ищем ticker в ответе
        for block in payload.values():
            if not isinstance(block, dict) or "data" not in block:
                continue
            cols = [c.lower() for c in block.get("columns", [])]
            for row in block.get("data", []):
                rowd = dict(zip(cols, row, strict=False))
                secid = str(rowd.get("secid") or rowd.get("ticker") or "").upper()
                if secid != ticker:
                    continue
                out: dict[str, float] = {}
                for key in ("roe", "net_margin", "revenue_growth", "pe"):
                    for k, v in rowd.items():
                        if key in k and v is not None:
                            try:
                                out[key] = float(v)
                            except (TypeError, ValueError):
                                pass
                if out:
                    cache.write_text(json.dumps(out))
                    return out
    except Exception as e:
        logger.debug("MSFO CCI for %s: %s", ticker, e)
    return None


def fetch_fundamentals(
    ticker: str,
    series: dict[date, OhlcBar],
    as_of: date,
    last_price: float,
) -> FundamentalSnapshot:
    static = _fetch_security_static(ticker)
    issue_size = float(static.get("ISSUESIZE") or 0)
    list_level = int(static.get("LISTLEVEL") or 0)
    market_cap = last_price * issue_size if issue_size and last_price else 0.0
    rev_proxy = _revenue_growth_proxy(series, as_of)

    msfo = _try_fetch_msfo_cci(ticker)
    msfo_ok = msfo is not None
    margin = msfo.get("net_margin") if msfo else None
    roe = msfo.get("roe") if msfo else None
    if msfo and "revenue_growth" in msfo:
        rev_proxy = msfo["revenue_growth"]

    note = "MSFO CCI" if msfo_ok else "proxy: ISS turnover + ISSUESIZE"

    return FundamentalSnapshot(
        ticker=ticker,
        list_level=list_level,
        market_cap_rub=market_cap,
        revenue_growth_proxy=rev_proxy,
        msfo_available=msfo_ok,
        net_margin_proxy=margin,
        roe_proxy=roe,
        source_note=note,
    )
