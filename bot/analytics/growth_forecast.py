"""
Прогноз роста на ~1 месяц: цена/объём + макро (ЦБ, USD, IMOEX) + фундаментал + новости MOEX.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from bot.config import Config
from bot.data.fundamentals import FundamentalSnapshot, fetch_fundamentals, revenue_growth_proxy
from bot.data.macro import MacroSnapshot, build_macro_snapshot
from bot.data.moex_iss import OhlcBar, closes_before
from bot.data.moex_news import NewsSentiment, news_sentiment_for_ticker
from bot.strategies.cross_sectional import momentum_return

logger = logging.getLogger(__name__)

MODEL_PATH = Path("data/forecast_model.json")
FORWARD_DAYS = 21


@dataclass
class StockFeatures:
    ticker: str
    mom_1m: float
    mom_3m: float
    mom_6m: float
    mom_accel: float
    rs_vs_index_6m: float
    trend_slope_50: float
    vol_annual: float
    avg_turnover_rub: float
    last_price: float
    macro_risk_on: float
    revenue_growth_proxy: float
    news_sentiment: float
    roe_proxy: float
    margin_proxy: float


@dataclass
class ForecastResult:
    ticker: str
    forecast_1m_pct: float
    features: StockFeatures
    fundamentals: FundamentalSnapshot | None
    news: NewsSentiment | None
    liquidity_score: float
    composite_score: float


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _realized_vol(closes: list[float], period: int = 20) -> float:
    if len(closes) < period + 1:
        return 0.0
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(-period, 0)
        if closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def _macro_risk_from_index(index_series: dict[date, float], as_of: date) -> float:
    closes = [index_series[d] for d in sorted(index_series) if d <= as_of][-70:]
    if len(closes) < 22:
        return 0.0
    m1 = (closes[-1] - closes[-22]) / closes[-22] if closes[-22] else 0.0
    return m1 * 2.0


def extract_features(
    ticker: str,
    series: dict[date, OhlcBar],
    index_series: dict[date, float],
    as_of: date,
    *,
    macro: MacroSnapshot | None = None,
    news: NewsSentiment | None = None,
    fund: FundamentalSnapshot | None = None,
    turnover_days: int = 20,
) -> StockFeatures | None:
    need = 6 * 21 + 30
    closes = closes_before(series, as_of, need)
    if len(closes) < 6 * 21 + 5:
        return None

    mom_1m = momentum_return(closes, 1)
    mom_3m = momentum_return(closes, 3)
    mom_6m = momentum_return(closes, 6)
    if mom_1m is None or mom_3m is None or mom_6m is None:
        return None

    idx_closes = [index_series[d] for d in sorted(index_series) if d <= as_of][-need:]
    idx_mom_6m = momentum_return(idx_closes, 6) if len(idx_closes) >= 6 * 21 + 1 else 0.0
    rs = mom_6m - (idx_mom_6m or 0.0)

    sma50 = _sma(closes, 50)
    trend_slope = ((closes[-1] / sma50) - 1.0) if sma50 and sma50 > 0 else 0.0
    mom_accel = mom_3m - mom_6m / 2.0

    days = sorted(d for d in series if d <= as_of)[-turnover_days:]
    turnover = (
        sum(series[d].close * series[d].volume for d in days) / len(days) if days else 0.0
    )

    rev = fund.revenue_growth_proxy if fund else revenue_growth_proxy(series, as_of)
    macro_risk = macro.risk_on_score if macro else _macro_risk_from_index(index_series, as_of)
    news_s = news.sentiment_score if news else 0.5
    roe = fund.roe_proxy if fund and fund.roe_proxy is not None else 0.0
    margin = fund.net_margin_proxy if fund and fund.net_margin_proxy is not None else 0.0

    return StockFeatures(
        ticker=ticker,
        mom_1m=mom_1m,
        mom_3m=mom_3m,
        mom_6m=mom_6m,
        mom_accel=mom_accel,
        rs_vs_index_6m=rs,
        trend_slope_50=trend_slope,
        vol_annual=_realized_vol(closes),
        avg_turnover_rub=turnover,
        last_price=closes[-1],
        macro_risk_on=macro_risk,
        revenue_growth_proxy=rev,
        news_sentiment=news_s,
        roe_proxy=roe,
        margin_proxy=margin,
    )


def feature_vector(f: StockFeatures) -> list[float]:
    return [
        1.0,
        f.mom_1m,
        f.mom_3m,
        f.mom_6m,
        f.mom_accel,
        f.rs_vs_index_6m,
        f.trend_slope_50,
        -f.vol_annual,
        f.macro_risk_on,
        f.revenue_growth_proxy,
        f.news_sentiment - 0.5,
        f.roe_proxy,
        f.margin_proxy,
    ]


def _matrix_transpose(m: list[list[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*m, strict=True)]


def _solve_ridge(X: list[list[float]], y: list[float], alpha: float) -> list[float]:
    n_feat = len(X[0])
    xt = _matrix_transpose(X)
    xtx = [[sum(xt[i][k] * X[k][j] for k in range(len(X))) for j in range(n_feat)] for i in range(n_feat)]
    xty = [sum(xt[i][k] * y[k] for k in range(len(y))) for i in range(n_feat)]
    for i in range(n_feat):
        xtx[i][i] += alpha
    aug = [xtx[i][:] + [xty[i]] for i in range(n_feat)]
    for col in range(n_feat):
        pivot = max(range(col, n_feat), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col] or 1e-12
        for j in range(col, n_feat + 1):
            aug[col][j] /= div
        for row in range(n_feat):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(col, n_feat + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n_feat] for i in range(n_feat)]


def _forward_return(
    series: dict[date, OhlcBar],
    as_of: date,
    days: int = FORWARD_DAYS,
) -> float | None:
    ordered = sorted(d for d in series if d <= as_of)
    if len(ordered) < 2:
        return None
    start_px = series[ordered[-1]].close
    future_days = sorted(d for d in series if d > as_of)[:days]
    if not future_days:
        return None
    end_px = series[future_days[-1]].close
    if start_px <= 0:
        return None
    return (end_px - start_px) / start_px


def fit_forecast_model(
    histories: dict[str, dict[date, OhlcBar]],
    index_series: dict[date, float],
    as_of: date,
    config: Config,
) -> list[float]:
    train_days = config.forecast_train_days
    ordered_index_days = sorted(d for d in index_series if d <= as_of)
    if len(ordered_index_days) < train_days // 2:
        sample_dates = ordered_index_days[:: max(1, len(ordered_index_days) // 40)]
    else:
        sample_dates = ordered_index_days[-train_days :: FORWARD_DAYS]

    X: list[list[float]] = []
    y: list[float] = []
    for ticker, series in histories.items():
        for d in sample_dates:
            if d not in series:
                continue
            fwd = _forward_return(series, d, FORWARD_DAYS)
            if fwd is None:
                continue
            feat = extract_features(ticker, series, index_series, d)
            if not feat:
                continue
            if feat.avg_turnover_rub < config.scan_min_avg_turnover_rub:
                continue
            X.append(feature_vector(feat))
            y.append(fwd)

    if len(y) < config.forecast_min_train_samples:
        logger.warning("Forecast train: %d samples — default weights", len(y))
        return _default_weights()

    weights = _solve_ridge(X, y, config.forecast_ridge_alpha)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(
        json.dumps(
            {
                "as_of": as_of.isoformat(),
                "n_samples": len(y),
                "weights": weights,
                "forward_days": FORWARD_DAYS,
                "features": "price,macro,fund_proxy,news",
            },
            indent=2,
        )
    )
    logger.info("Forecast model fit: %d samples, %d features", len(y), len(weights))
    return weights


def _default_weights() -> list[float]:
    return [
        0.0,
        0.10,
        0.15,
        0.25,
        0.12,
        0.22,
        0.08,
        -0.04,
        0.15,
        0.18,
        0.06,
        0.05,
        0.04,
    ]


def load_model_weights() -> list[float] | None:
    if not MODEL_PATH.exists():
        return None
    raw = json.loads(MODEL_PATH.read_text())
    w = raw.get("weights")
    if w and len(w) == len(_default_weights()):
        return w
    return None


def predict_return(features: StockFeatures, weights: list[float]) -> float:
    x = feature_vector(features)
    if len(x) != len(weights):
        weights = _default_weights()
    return sum(w * xi for w, xi in zip(weights, x, strict=True))


def passes_strict_filters(
    features: StockFeatures,
    config: Config,
    fund: FundamentalSnapshot | None = None,
    news: NewsSentiment | None = None,
) -> tuple[bool, str]:
    if features.last_price < config.scan_min_price_rub:
        return False, f"price<{config.scan_min_price_rub}"
    if features.avg_turnover_rub < config.scan_min_avg_turnover_rub:
        return False, "low turnover"
    if fund and fund.list_level < config.scan_min_list_level:
        return False, f"list_level<{config.scan_min_list_level}"
    if config.scan_require_uptrend and features.mom_6m <= 0:
        return False, "mom6<=0"
    tol = config.scan_sma_tolerance_pct / 100.0
    if config.scan_require_uptrend and features.trend_slope_50 < -tol:
        return False, "below SMA50"
    if config.scan_require_beats_index and features.rs_vs_index_6m <= 0:
        return False, "lags IMOEX"
    if features.vol_annual > config.scan_max_vol_annual:
        return False, "too volatile"
    if config.scan_require_positive_fund:
        growth_ok = features.revenue_growth_proxy > 0 or (
            features.mom_6m > 0.03 and features.rs_vs_index_6m > 0
        )
        if not growth_ok:
            return False, "no growth signal"
    if config.scan_require_macro_risk and features.macro_risk_on < 0:
        return False, "macro_risk_off"
    if news and news.sentiment_score < config.scan_min_news_sentiment:
        return False, "weak news"
    return True, "ok"


def passes_relaxed_filters(features: StockFeatures, config: Config) -> tuple[bool, str]:
    if features.last_price < config.scan_min_price_rub:
        return False, f"price<{config.scan_min_price_rub}"
    if features.avg_turnover_rub < config.scan_min_avg_turnover_rub:
        return False, "low turnover"
    if features.vol_annual > config.scan_max_vol_annual:
        return False, "too volatile"
    return True, "ok"


def _build_forecast_results(
    feats_map: dict[str, StockFeatures],
    meta: dict[str, tuple[FundamentalSnapshot | None, NewsSentiment | None]],
    weights: list[float],
    config: Config,
) -> list[ForecastResult]:
    results: list[ForecastResult] = []
    max_turn = max((f.avg_turnover_rub for f in feats_map.values()), default=0.0)
    min_fc = config.scan_min_forecast_pct
    if config.scan_strict_only and min_fc <= 0:
        min_fc = 0.01

    for ticker, feat in feats_map.items():
        forecast = predict_return(feat, weights) * 100
        if min_fc > 0 and forecast < min_fc:
            continue
        if config.scan_strict_only and forecast <= 0:
            continue
        liq = feat.avg_turnover_rub / max_turn if max_turn else 0
        fund, news = meta.get(ticker, (None, None))
        composite = forecast * 0.80 + liq * 100 * 0.10 + feat.news_sentiment * 10
        results.append(
            ForecastResult(
                ticker=ticker,
                forecast_1m_pct=round(forecast, 2),
                features=feat,
                fundamentals=fund,
                news=news,
                liquidity_score=round(liq, 4),
                composite_score=round(composite, 3),
            )
        )
    results.sort(key=lambda r: r.composite_score, reverse=True)
    return results


def rank_with_forecast(
    candidates: list[tuple[str, dict[date, OhlcBar]]],
    index_series: dict[date, float],
    as_of: date,
    config: Config,
    *,
    weights: list[float] | None = None,
) -> list[ForecastResult]:
    w = weights or load_model_weights() or _default_weights()
    macro = build_macro_snapshot(as_of, config.market_index)
    news_cache = None
    if config.scan_use_news:
        from bot.data.moex_news import _fetch_sitenews

        news_cache = _fetch_sitenews(300)

    strict_map: dict[str, StockFeatures] = {}
    relaxed_map: dict[str, StockFeatures] = {}
    meta: dict[str, tuple[FundamentalSnapshot | None, NewsSentiment | None]] = {}

    static_cache: dict[str, FundamentalSnapshot] = {}

    for ticker, series in candidates:
        try:
            last_day = max(d for d in series if d <= as_of)
            if ticker not in static_cache:
                static_cache[ticker] = fetch_fundamentals(
                    ticker, series, as_of, series[last_day].close
                )
            fund = static_cache[ticker]
        except Exception:
            fund = None
        news = (
            news_sentiment_for_ticker(ticker, as_of, news_cache=news_cache)
            if config.scan_use_news
            else None
        )
        feat = extract_features(
            ticker, series, index_series, as_of, macro=macro, news=news, fund=fund
        )
        if not feat:
            continue
        meta[ticker] = (fund, news)
        if passes_strict_filters(feat, config, fund, news)[0]:
            strict_map[ticker] = feat
        elif not config.scan_strict_only and passes_relaxed_filters(feat, config)[0]:
            relaxed_map[ticker] = feat

    feats_map = strict_map
    results = _build_forecast_results(feats_map, meta, w, config)
    if (
        not config.scan_strict_only
        and len(results) < config.scan_top_n
        and relaxed_map
    ):
        for t, f in relaxed_map.items():
            if t not in feats_map:
                feats_map[t] = f
        results = _build_forecast_results(feats_map, meta, w, config)
    return results
