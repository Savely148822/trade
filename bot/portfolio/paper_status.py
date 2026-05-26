"""Сводка paper-портфеля для логов."""

from __future__ import annotations

import logging

from bot.config import Config
from bot.portfolio.state import PortfolioState

logger = logging.getLogger(__name__)


def log_paper_status(state: PortfolioState, prices: dict[str, float], config: Config) -> None:
    equity = state.core.equity(prices)
    if equity <= 0:
        return

    contributed = state.initial_equity + state.total_deposits_rub
    cash_pct = state.core.cash_rub / equity * 100
    pnl = equity - contributed
    pnl_pct = pnl / contributed * 100 if contributed > 0 else 0.0

    lines = [
        f"Paper | equity {equity:,.0f} ₽ | внесено {contributed:,.0f} ₽ | "
        f"P&L {pnl:+,.0f} ({pnl_pct:+.1f}%) | cash {cash_pct:.0f}% | div +{state.total_dividends_net_rub:,.0f} ₽",
    ]

    if state.core.positions:
        parts = []
        bond_t = config.bond_ticker.upper()
        for ticker, pos in sorted(state.core.positions.items()):
            px = prices.get(ticker, pos.avg_price)
            val = pos.qty * px
            wt = val / equity * 100
            upl = (px - pos.avg_price) / pos.avg_price * 100 if pos.avg_price else 0
            label = f"{ticker} {wt:.0f}%"
            if ticker.upper() == bond_t:
                label += " [bond]"
            else:
                label += f" ({upl:+.0f}%)"
            parts.append(label)
        lines.append("  " + " | ".join(parts))
    elif state.core.cash_rub >= config.core_min_trade_rub:
        lines.append("  позиций нет — кэш ждёт ребаланса")

    for line in lines:
        logger.info(line)
