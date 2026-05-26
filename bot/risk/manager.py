from __future__ import annotations

from dataclasses import dataclass

from bot.portfolio.state import PortfolioState


@dataclass
class RiskStatus:
    ok: bool
    drawdown_pct: float
    message: str


def check_risk(
    state: PortfolioState,
    prices: dict[str, float],
    max_drawdown_pct: float,
) -> RiskStatus:
    equity = state.total_equity(prices)
    if equity > state.peak_equity:
        state.peak_equity = equity

    drawdown = 0.0
    if state.peak_equity > 0:
        drawdown = (state.peak_equity - equity) / state.peak_equity * 100

    ok = drawdown < max_drawdown_pct
    message = (
        f"drawdown {drawdown:.1f}% >= {max_drawdown_pct}%"
        if not ok
        else "risk ok"
    )
    return RiskStatus(ok=ok, drawdown_pct=drawdown, message=message)
