"""Ежемесячный скан MOEX: прогноз роста + жёсткие фильтры → топ-20."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from bot.analytics.growth_forecast import (
    fit_forecast_model,
    rank_with_forecast,
)
from bot.config import Config
from bot.data.moex_iss import OhlcBar, fetch_history, fetch_index_history
from bot.data.moex_market import fetch_tqbr_market_snapshot

logger = logging.getLogger(__name__)

REPORT_DIR = Path("data/scans")


@dataclass
class ScanRow:
    rank: int
    ticker: str
    score: float
    forecast_1m_pct: float
    momentum_6m_pct: float
    rs_vs_index_pct: float
    valtoday_mln: float
    last_price: float


@dataclass
class ScanReport:
    as_of: date
    month: str
    candidates_screened: int
    passed_filters: int
    top_n: int
    picks: list[ScanRow]
    model_samples: int = 0


def _liquidity_pool_from_snapshot(
    config: Config,
) -> list[tuple[str, float]]:
    snapshots = fetch_tqbr_market_snapshot()
    liquid = [s for s in snapshots if s.valtoday_rub >= config.min_daily_volume_rub]
    liquid.sort(key=lambda s: s.valtoday_rub, reverse=True)
    return [(s.ticker, s.valtoday_rub) for s in liquid[: config.scan_liquid_pool]]


def _load_histories_for_pool(
    tickers: list[str],
    as_of: date,
    config: Config,
    existing: dict[str, dict[date, OhlcBar]] | None,
) -> dict[str, dict[date, OhlcBar]]:
    histories = dict(existing or {})
    start = as_of - timedelta(days=config.forecast_train_days + 120)
    for t in tickers:
        if t not in histories:
            h = fetch_history(t, start, as_of)
            if h:
                histories[t] = h
    return histories


def scan_promising_stocks(
    config: Config,
    as_of: date | None = None,
    *,
    histories: dict[str, dict[date, OhlcBar]] | None = None,
) -> ScanReport:
    as_of = as_of or date.today()
    month = as_of.strftime("%Y-%m")

    if histories:
        pool_tickers = list(histories.keys())[: config.scan_liquid_pool]
    else:
        pool_tickers = [t for t, _ in _liquidity_pool_from_snapshot(config)]

    index_start = as_of - timedelta(days=config.forecast_train_days + 120)
    index_series = fetch_index_history(config.market_index, index_start, as_of)
    histories = _load_histories_for_pool(pool_tickers, as_of, config, histories)

    weights = fit_forecast_model(histories, index_series, as_of, config)
    model_samples = 0
    if (Path("data/forecast_model.json")).exists():
        raw = json.loads(Path("data/forecast_model.json").read_text())
        model_samples = int(raw.get("n_samples", 0))

    candidates = [(t, histories[t]) for t in pool_tickers if t in histories]
    ranked = rank_with_forecast(candidates, index_series, as_of, config, weights=weights)

    picks = [
        ScanRow(
            rank=i + 1,
            ticker=r.ticker,
            score=r.composite_score,
            forecast_1m_pct=r.forecast_1m_pct,
            momentum_6m_pct=round(r.features.mom_6m * 100, 2),
            rs_vs_index_pct=round(r.features.rs_vs_index_6m * 100, 2),
            valtoday_mln=round(r.features.avg_turnover_rub / 1_000_000, 2),
            last_price=round(r.features.last_price, 2),
        )
        for i, r in enumerate(ranked[: config.scan_top_n])
    ]

    logger.info(
        "Scan %s: pool=%d → after filters+forecast=%d → top %d",
        as_of,
        len(candidates),
        len(ranked),
        len(picks),
    )

    return ScanReport(
        as_of=as_of,
        month=month,
        candidates_screened=len(candidates),
        passed_filters=len(ranked),
        top_n=config.scan_top_n,
        picks=picks,
        model_samples=model_samples,
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
                "passed_filters": report.passed_filters,
                "model_train_samples": report.model_samples,
                "top_n": report.top_n,
                "picks": [asdict(p) for p in report.picks],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    txt = REPORT_DIR / f"scan_{report.month}.txt"
    lines = [
        f"MOEX GROWTH SCAN {report.month} (as of {report.as_of})",
        f"Pool: {report.candidates_screened} | Passed forecast+filters: {report.passed_filters}",
        f"Forecast model trained on {report.model_samples} samples",
        "",
        f"{'#':>3} {'Tkr':<6} {'Fcst1m%':>8} {'Mom6m%':>8} {'vsIMOEX':>8} {'VolMln':>8} {'Score':>8}",
        "-" * 58,
    ]
    for p in report.picks:
        lines.append(
            f"{p.rank:3d} {p.ticker:<6} {p.forecast_1m_pct:8.1f} {p.momentum_6m_pct:8.1f} "
            f"{p.rs_vs_index_pct:8.1f} {p.valtoday_mln:8.1f} {p.score:8.2f}"
        )
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def print_scan_report(report: ScanReport) -> None:
    print("\n" + "=" * 64)
    print(f"MOEX GROWTH FORECAST SCAN — {report.month}")
    print("=" * 64)
    print(
        f"Прогноз: ожидаемая доходность за ~1 мес (21 день) по модели на истории."
    )
    print(
        f"В рейтинг: {report.passed_filters} из {report.candidates_screened} "
        f"(строгие фильтры + при нехватке — только ликвидность)"
    )
    print(f"Обучение модели: {report.model_samples} наблюдений\n")
    for p in report.picks:
        print(
            f"  {p.rank:2d}. {p.ticker:<6}  прогноз {p.forecast_1m_pct:+.1f}%/мес  "
            f"mom6m {p.momentum_6m_pct:+.1f}%  vs индекс {p.rs_vs_index_pct:+.1f}%"
        )
    if report.picks:
        print(f"\nCORE_UNIVERSE={','.join(p.ticker for p in report.picks)}")
    else:
        print("\n⚠ Ни одна бумага не прошла фильтры — CORE_UNIVERSE не меняем.")
    print("=" * 64 + "\n")
