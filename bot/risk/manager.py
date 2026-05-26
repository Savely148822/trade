from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bot.portfolio.state import PortfolioState


@dataclass
class RiskStatus:
    ok: bool
    allow_satellite: bool
    drawdown_pct: float
    satellite_month_pnl_pct: float
    message: str


def check_risk(
    state: PortfolioState,
    prices: dict[str, float],
    max_drawdown_pct: float,
    satellite_monthly_loss_cap_pct: float,
) -> RiskStatus:
    equity = state.total_equity(prices)
    if equity > state.peak_equity:
        state.peak_equity = equity

    drawdown = 0.0
    if state.peak_equity > 0:
        drawdown = (state.peak_equity - equity) / state.peak_equity * 100

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    if state.month_key != month:
        state.month_key = month
        state.satellite_month_start_equity = state.satellite.equity(prices)

    sat_eq = state.satellite.equity(prices)
    start = state.satellite_month_start_equity or sat_eq
    sat_pnl_pct = ((sat_eq - start) / start * 100) if start else 0.0

    allow_sat = True
    msgs: list[str] = []

    if drawdown >= max_drawdown_pct:
        allow_sat = False
        msgs.append(f"drawdown {drawdown:.1f}% >= {max_drawdown_pct}%")

    if sat_pnl_pct <= -satellite_monthly_loss_cap_pct:
        allow_sat = False
        msgs.append(
            f"satellite month PnL {sat_pnl_pct:.1f}% <= -{satellite_monthly_loss_cap_pct}%"
        )

    ok = drawdown < max_drawdown_pct
    message = "; ".join(msgs) if msgs else "risk ok"

    return RiskStatus(
        ok=ok,
        allow_satellite=allow_sat,
        drawdown_pct=drawdown,
        satellite_month_pnl_pct=sat_pnl_pct,
        message=message,
    )
