"""
Прогноз роста на 1 месяц (≈21 торг. день) по факторам цены/объёма.

Это количественная модель на истории MOEX, не «гарантия» и не ML-оракул.
Коэффициенты переобучаются на скользящем окне при каждом скане.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from bot.config import Config
from bot.data.moex_iss import OhlcBar, closes_before
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
    mom_accel: float  # mom_3m - mom_6m/2
    rs_vs_index_6m: float
    trend_slope_50: float  # % выше/ниже SMA50
    vol_annual: float
    avg_turnover_rub: float
    last_price: float


@dataclass
class ForecastResult:
    ticker: str
    forecast_1m_pct: float
    features: StockFeatures
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


def extract_features(
    ticker: str,
    series: dict[date, OhlcBar],
    index_series: dict[date, float],
    as_of: date,
    *,
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
    ]


def _matrix_transpose(m: list[list[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*m, strict=True)]


def _mat_vec_mul(m: list[list[float]], v: list[float]) -> list[float]:
    return [sum(a * b for a, b in zip(row, v, strict=True)) for row in m]


def _solve_ridge(X: list[list[float]], y: list[float], alpha: float) -> list[float]:
    """(X'X + αI) w = X'y"""
    n_feat = len(X[0])
    xt = _matrix_transpose(X)
    xtx = [[sum(xt[i][k] * X[k][j] for k in range(len(X))) for j in range(n_feat)] for i in range(n_feat)]
    xty = [sum(xt[i][k] * y[k] for k in range(len(y))) for i in range(n_feat)]
    for i in range(n_feat):
        xtx[i][i] += alpha
    # Гаусс для малых матриц (8x8)
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
    """Обучение на панели: прошлые даты × тикеры с известным forward return."""
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
        logger.warning(
            "Forecast train: only %d samples — using default weights", len(y)
        )
        return _default_weights()

    weights = _solve_ridge(X, y, config.forecast_ridge_alpha)
    _save_model(weights, len(y), as_of)
    logger.info("Forecast model fit: %d samples, %d features", len(y), len(weights))
    return weights


def _default_weights() -> list[float]:
    """Эвристика, если мало данных для обучения."""
    return [0.0, 0.15, 0.25, 0.35, 0.20, 0.30, 0.10, -0.05]


def _save_model(weights: list[float], n_samples: int, as_of: date) -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(
        json.dumps(
            {
                "as_of": as_of.isoformat(),
                "n_samples": n_samples,
                "weights": weights,
                "forward_days": FORWARD_DAYS,
            },
            indent=2,
        )
    )


def load_model_weights() -> list[float] | None:
    if not MODEL_PATH.exists():
        return None
    raw = json.loads(MODEL_PATH.read_text())
    return raw.get("weights")


def predict_return(features: StockFeatures, weights: list[float]) -> float:
    x = feature_vector(features)
    return sum(w * xi for w, xi in zip(weights, x, strict=True))


def passes_relaxed_filters(features: StockFeatures, config: Config) -> tuple[bool, str]:
    """Только ликвидность и волатильность — если строгих кандидатов мало."""
    if features.last_price < config.scan_min_price_rub:
        return False, f"price<{config.scan_min_price_rub}"
    if features.avg_turnover_rub < config.scan_min_avg_turnover_rub:
        return False, "low turnover"
    if features.vol_annual > config.scan_max_vol_annual:
        return False, "too volatile"
    return True, "ok"


def passes_strict_filters(features: StockFeatures, config: Config) -> tuple[bool, str]:
    if features.last_price < config.scan_min_price_rub:
        return False, f"price<{config.scan_min_price_rub}"
    if features.avg_turnover_rub < config.scan_min_avg_turnover_rub:
        return False, "low turnover"
    if config.scan_require_uptrend and features.mom_6m <= 0:
        return False, "mom6<=0"
    if config.scan_require_uptrend and features.trend_slope_50 < 0:
        return False, "below SMA50"
    if config.scan_require_beats_index and features.rs_vs_index_6m <= 0:
        return False, "lags IMOEX"
    if features.vol_annual > config.scan_max_vol_annual:
        return False, "too volatile"
    return True, "ok"


def _build_forecast_results(
    feats_map: dict[str, StockFeatures],
    weights: list[float],
    config: Config,
) -> list[ForecastResult]:
    results: list[ForecastResult] = []
    max_turn = max((f.avg_turnover_rub for f in feats_map.values()), default=0.0)
    for ticker, feat in feats_map.items():
        forecast = predict_return(feat, weights) * 100
        liq = feat.avg_turnover_rub / max_turn if max_turn else 0
        composite = forecast * 0.85 + liq * 100 * 0.15
        results.append(
            ForecastResult(
                ticker=ticker,
                forecast_1m_pct=round(forecast, 2),
                features=feat,
                liquidity_score=round(liq, 4),
                composite_score=round(composite, 3),
            )
        )
    results.sort(key=lambda r: r.composite_score, reverse=True)
    if config.scan_min_forecast_pct > 0:
        filtered = [r for r in results if r.forecast_1m_pct >= config.scan_min_forecast_pct]
        if filtered:
            return filtered
        logger.warning(
            "No names with forecast >= %.1f%% — using relative top ranks",
            config.scan_min_forecast_pct,
        )
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
    strict_map: dict[str, StockFeatures] = {}
    relaxed_map: dict[str, StockFeatures] = {}

    for ticker, series in candidates:
        feat = extract_features(ticker, series, index_series, as_of)
        if not feat:
            continue
        if passes_strict_filters(feat, config)[0]:
            strict_map[ticker] = feat
        elif passes_relaxed_filters(feat, config)[0]:
            relaxed_map[ticker] = feat

    feats_map = strict_map
    results = _build_forecast_results(feats_map, w, config)
    if len(results) < config.scan_top_n and relaxed_map:
        logger.info(
            "Strict filters: %d names — adding relaxed (liquidity only)",
            len(results),
        )
        for t, f in relaxed_map.items():
            if t not in feats_map:
                feats_map[t] = f
        results = _build_forecast_results(feats_map, w, config)
    return results
