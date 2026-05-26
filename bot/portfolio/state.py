from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path("data/portfolio_state.json")


@dataclass
class Position:
    qty: float
    avg_price: float


@dataclass
class SleeveState:
    cash_rub: float
    positions: dict[str, Position] = field(default_factory=dict)

    def equity(self, prices: dict[str, float]) -> float:
        total = self.cash_rub
        for ticker, pos in self.positions.items():
            px = prices.get(ticker, pos.avg_price)
            total += pos.qty * px
        return total


@dataclass
class PortfolioState:
    core: SleeveState
    satellite: SleeveState  # legacy JSON; всегда пустой в core-only
    initial_equity: float
    peak_equity: float
    equity_at_last_rebalance: float
    last_rebalance_at: str
    last_scheduled_rebalance_at: str
    satellite_month_start_equity: float
    satellite_baseline_equity: float
    month_key: str
    updated_at: str = ""

    def total_equity(self, prices: dict[str, float]) -> float:
        return self.core.equity(prices) + self.satellite.equity(prices)


def load_state(initial_rub: float) -> PortfolioState:
    if STATE_PATH.exists():
        raw = json.loads(STATE_PATH.read_text())
        return _from_dict(raw, fallback_initial=initial_rub)

    now = datetime.now(timezone.utc).isoformat()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    state = PortfolioState(
        core=SleeveState(cash_rub=initial_rub),
        satellite=SleeveState(cash_rub=0.0),
        initial_equity=initial_rub,
        peak_equity=initial_rub,
        equity_at_last_rebalance=initial_rub,
        last_rebalance_at=now,
        last_scheduled_rebalance_at=now,
        satellite_month_start_equity=0.0,
        satellite_baseline_equity=0.0,
        month_key=month,
        updated_at=now,
    )
    save_state(state)
    return state


def save_state(state: PortfolioState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(_to_dict(state), indent=2, ensure_ascii=False))


def _to_dict(state: PortfolioState) -> dict:
    def sleeve(s: SleeveState) -> dict:
        return {
            "cash_rub": s.cash_rub,
            "positions": {
                t: {"qty": p.qty, "avg_price": p.avg_price}
                for t, p in s.positions.items()
            },
        }

    return {
        "core": sleeve(state.core),
        "satellite": sleeve(state.satellite),
        "initial_equity": state.initial_equity,
        "peak_equity": state.peak_equity,
        "equity_at_last_rebalance": state.equity_at_last_rebalance,
        "last_rebalance_at": state.last_rebalance_at,
        "last_scheduled_rebalance_at": state.last_scheduled_rebalance_at,
        "satellite_month_start_equity": state.satellite_month_start_equity,
        "satellite_baseline_equity": state.satellite_baseline_equity,
        "month_key": state.month_key,
        "updated_at": state.updated_at,
    }


def _from_dict(raw: dict, fallback_initial: float) -> PortfolioState:
    def sleeve(data: dict) -> SleeveState:
        pos = {
            t: Position(qty=v["qty"], avg_price=v["avg_price"])
            for t, v in data.get("positions", {}).items()
        }
        return SleeveState(cash_rub=float(data["cash_rub"]), positions=pos)

    initial = float(raw.get("initial_equity", fallback_initial))
    now = datetime.now(timezone.utc).isoformat()
    state = PortfolioState(
        core=sleeve(raw["core"]),
        satellite=sleeve(raw.get("satellite", {"cash_rub": 0, "positions": {}})),
        initial_equity=initial,
        peak_equity=float(raw.get("peak_equity", initial)),
        equity_at_last_rebalance=float(
            raw.get("equity_at_last_rebalance", initial)
        ),
        last_rebalance_at=str(raw.get("last_rebalance_at", now)),
        last_scheduled_rebalance_at=str(
            raw.get("last_scheduled_rebalance_at", raw.get("last_rebalance_at", now))
        ),
        satellite_month_start_equity=float(raw.get("satellite_month_start_equity", 0)),
        satellite_baseline_equity=float(raw.get("satellite_baseline_equity", 0)),
        month_key=str(raw.get("month_key", datetime.now(timezone.utc).strftime("%Y-%m"))),
        updated_at=str(raw.get("updated_at", "")),
    )
    # Миграция: весь кэш satellite → core
    if state.satellite.cash_rub > 0 or state.satellite.positions:
        state.core.cash_rub += state.satellite.cash_rub
        for t, p in state.satellite.positions.items():
            if t in state.core.positions:
                old = state.core.positions[t]
                total_q = old.qty + p.qty
                state.core.positions[t] = Position(
                    qty=total_q,
                    avg_price=(old.avg_price * old.qty + p.avg_price * p.qty) / total_q,
                )
            else:
                state.core.positions[t] = p
        state.satellite = SleeveState(cash_rub=0.0)
        save_state(state)
    return state
