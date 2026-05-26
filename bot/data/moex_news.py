"""Новости MOEX (sitenews) — упоминания тикера в заголовках."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

SITENEWS_URL = "https://iss.moex.com/iss/sitenews.json"


@dataclass(frozen=True)
class NewsSentiment:
    ticker: str
    mentions_30d: int
    sentiment_score: float  # 0..1


_POSITIVE = re.compile(
    r"дивиденд|прибыл|рост|рекорд|повыш|одобр|buyback|выкуп",
    re.I,
)
_NEGATIVE = re.compile(
    r"убыт|санкц|снижен|пониж|дефолт|иск|штраф|отмен",
    re.I,
)


def _fetch_sitenews(limit: int = 200) -> list[tuple[date, str]]:
    params = {"iss.meta": "off", "limit": limit}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(SITENEWS_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()

    rows = payload.get("sitenews", {}).get("data", [])
    out: list[tuple[date, str]] = []
    for row in rows:
        if len(row) < 3:
            continue
        title = str(row[2])
        try:
            published = datetime.fromisoformat(str(row[3]).split()[0]).date()
        except ValueError:
            published = date.today()
        out.append((published, title))
    return out


def news_sentiment_for_ticker(
    ticker: str,
    as_of: date,
    *,
    lookback_days: int = 30,
    news_cache: list[tuple[date, str]] | None = None,
) -> NewsSentiment:
    items = news_cache if news_cache is not None else _fetch_sitenews(250)
    cutoff = as_of - timedelta(days=lookback_days)
    mentions = 0
    pos = neg = 0
    pat = re.compile(rf"\b{re.escape(ticker)}\b", re.I)

    for pub, title in items:
        if pub < cutoff or pub > as_of:
            continue
        if pat.search(title) or ticker.lower() in title.lower():
            mentions += 1
            if _POSITIVE.search(title):
                pos += 1
            if _NEGATIVE.search(title):
                neg += 1

    if mentions == 0:
        score = 0.5
    else:
        score = 0.5 + (pos - neg) / (mentions * 2)
        score = max(0.0, min(1.0, score))

    return NewsSentiment(ticker=ticker, mentions_30d=mentions, sentiment_score=score)
