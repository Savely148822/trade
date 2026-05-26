"""Ежемесячный скан MOEX: топ перспективных акций по momentum + ликвидность."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from bot.config import Config
from bot.data.moex_iss import OhlcBar, closes_before, fetch_history
from bot.data.moex_market import MarketSnapshot, fetch_tqbr_market_snapshot
from bot.strategies.cross_sectional import momentum_return

logger = logging.getLogger(__name__)

REPORT_DIR = Path("data/scans")


@dataclass
class ScanRow:
    rank: int
    ticker: str
    score: float
    momentum_6m_pct: float
    valtoday_mln: float
    last_price: float


@dataclass
class ScanReport:
    as_of: date
    month: str
    candidates_screened: int
    top_n: int
    picks: list[ScanRow]


def _liquidity_pool(
    snapshots: list[MarketSnapshot],
    min_valtoday_rub: float,
    pool_size: int,
) -> list[MarketSnapshot]:
    liquid = [s for s in snapshots if s.valtoday_rub >= min_valtoday_rub]
    liquid.sort(key=lambda s: s.valtoday_rub, reverse=True)
    return liquid[:pool_size]


def _avg_daily_turnover(
    series: dict[date, OhlcBar],
    as_of: date,
    days: int = 20,
) -> float:
    dlist = sorted(d for d in series if d <= as_of)[-days:]
    if not dlist:
        return 0.0
    return sum(series[d].close * series[d].volume for d in dlist) / len(dlist)


def _scan_from_histories(
    config: Config,
    as_of: date,
    histories: dict[str, dict[date, OhlcBar]],
) -> ScanReport:
    """Walk-forward: ликвидность и momentum только по истории до as_of."""
    month = as_of.strftime("%Y-%m")
    pool: list[tuple[str, float, float]] = []
    for ticker, series in histories.items():
        turnover = _avg_daily_turnover(series, as_of)
        if turnover < config.min_daily_volume_rub:
            continue
        closes = closes_before(series, as_of, config.core_momentum_months * 21 + 10)
        mom = momentum_return(closes, config.core_momentum_months)
        if mom is None:
            continue
        pool.append((ticker, turnover, mom))

    if not pool:
        return ScanReport(as_of, month, 0, config.scan_top_n, [])

    max_turn = max(p[1] for p in pool)
    scored: list[tuple[str, float, float, float]] = []
    for ticker, turnover, mom in pool:
        liq_norm = turnover / max_turn
        score = 0.7 * mom + 0.3 * liq_norm
        last = closes_before(histories[ticker], as_of, 1)[-1] if histories[ticker] else 0
        scored.append((ticker, score, mom * 100, turnover, last))

    scored.sort(key=lambda x: x[1], reverse=True)
    picks = [
        ScanRow(
            rank=i + 1,
            ticker=t,
            score=round(sc, 4),
            momentum_6m_pct=round(mom, 2),
            valtoday_mln=round(val / 1_000_000, 2),
            last_price=round(px, 2),
        )
        for i, (t, sc, mom, val, px) in enumerate(scored[: config.scan_top_n])
    ]
    return ScanReport(as_of, month, len(pool), config.scan_top_n, picks)


def scan_promising_stocks(
    config: Config,
    as_of: date | None = None,
    *,
    histories: dict | None = None,
) -> ScanReport:
    """
    Отбор top SCAN_TOP_N (default 20) из ликвидного пула MOEX TQBR.
    Score = 70% momentum (6m) + 30% ликвидность (оборот за день).
    """
    as_of = as_of or date.today()
    if histories and as_of < date.today():
        return _scan_from_histories(config, as_of, histories)

    month = as_of.strftime("%Y-%m")
    top_n = config.scan_top_n
    pool_size = config.scan_liquid_pool

    snapshots = fetch_tqbr_market_snapshot()
    pool = _liquidity_pool(snapshots, config.min_daily_volume_rub, pool_size)
    logger.info("Scan %s: %d liquid names (pool %d)", as_of, len(pool), pool_size)

    if not pool:
        return ScanReport(as_of, month, 0, top_n, [])

    max_val = max(s.valtoday_rub for s in pool)
    scored: list[tuple[str, float, float, float, float]] = []

    start = as_of - timedelta(days=config.core_momentum_months * 31 + 60)
    for snap in pool:
        if histories and snap.ticker in histories:
            series = histories[snap.ticker]
        else:
            series = fetch_history(snap.ticker, start, as_of)
        closes = closes_before(series, as_of, config.core_momentum_months * 21 + 10)
        mom = momentum_return(closes, config.core_momentum_months)
        if mom is None:
            continue
        liq_norm = snap.valtoday_rub / max_val if max_val else 0
        # momentum может быть отрицательным — сдвигаем для ранжирования
        mom_norm = mom
        score = 0.7 * mom_norm + 0.3 * liq_norm
        scored.append((snap.ticker, score, mom * 100, snap.valtoday_rub, snap.last))

    scored.sort(key=lambda x: x[1], reverse=True)
    picks = [
        ScanRow(
            rank=i + 1,
            ticker=t,
            score=round(sc, 4),
            momentum_6m_pct=round(mom, 2),
            valtoday_mln=round(val / 1_000_000, 2),
            last_price=round(px, 2),
        )
        for i, (t, sc, mom, val, px) in enumerate(scored[:top_n])
    ]

    return ScanReport(
        as_of=as_of,
        month=month,
        candidates_screened=len(pool),
        top_n=top_n,
        picks=picks,
    )


def save_scan_report(report: ScanReport) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"scan_{report.month}.json"
    path.write_text(
        json.dumps(
            {
                "as_of": report.as_of.isoformat(),
                "month": report.month,
                "candidates_screened": report.candidates_screened,
                "top_n": report.top_n,
                "picks": [asdict(p) for p in report.picks],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    txt = REPORT_DIR / f"scan_{report.month}.txt"
    lines = [
        f"MOEX scan {report.month} (as of {report.as_of})",
        f"Screened: {report.candidates_screened} liquid stocks",
        "",
        f"{'#':>3} {'Ticker':<8} {'Score':>8} {'Mom6m%':>8} {'Vol Mln':>10} {'Price':>10}",
        "-" * 52,
    ]
    for p in report.picks:
        lines.append(
            f"{p.rank:3d} {p.ticker:<8} {p.score:8.3f} {p.momentum_6m_pct:8.1f} "
            f"{p.valtoday_mln:10.1f} {p.last_price:10.2f}"
        )
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def print_scan_report(report: ScanReport) -> None:
    print("\n" + "=" * 60)
    print(f"MOEX MONTHLY SCAN — {report.month}")
    print("=" * 60)
    print(f"Date: {report.as_of} | Screened: {report.candidates_screened} names")
    print(f"\nTop {report.top_n} for CORE_UNIVERSE:\n")
    for p in report.picks:
        print(
            f"  {p.rank:2d}. {p.ticker:<6}  score {p.score:.3f}  "
            f"mom6m {p.momentum_6m_pct:+.1f}%  vol {p.valtoday_mln:.1f}M ₽"
        )
    tickers = ",".join(p.ticker for p in report.picks)
    print(f"\nCORE_UNIVERSE={tickers}")
    print("=" * 60 + "\n")
