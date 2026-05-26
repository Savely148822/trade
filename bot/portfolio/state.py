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
    satellite: SleeveState
    peak_equity: float
    satellite_month_start_equity: float
    month_key: str
    updated_at: str = ""

    def total_equity(self, prices: dict[str, float]) -> float:
        return self.core.equity(prices) + self.satellite.equity(prices)


def load_state(initial_rub: float, core_weight: float) -> PortfolioState:
    if STATE_PATH.exists():
        raw = json.loads(STATE_PATH.read_text())
        return _from_dict(raw)

    core_cash = initial_rub * core_weight
    sat_cash = initial_rub * (1 - core_weight)
    now = datetime.now(timezone.utc).isoformat()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    state = PortfolioState(
        core=SleeveState(cash_rub=core_cash),
        satellite=SleeveState(cash_rub=sat_cash),
        peak_equity=initial_rub,
        satellite_month_start_equity=sat_cash,
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
        "peak_equity": state.peak_equity,
        "satellite_month_start_equity": state.satellite_month_start_equity,
        "month_key": state.month_key,
        "updated_at": state.updated_at,
    }


def _from_dict(raw: dict) -> PortfolioState:
    def sleeve(data: dict) -> SleeveState:
        pos = {
            t: Position(qty=v["qty"], avg_price=v["avg_price"])
            for t, v in data.get("positions", {}).items()
        }
        return SleeveState(cash_rub=float(data["cash_rub"]), positions=pos)

    return PortfolioState(
        core=sleeve(raw["core"]),
        satellite=sleeve(raw["satellite"]),
        peak_equity=float(raw["peak_equity"]),
        satellite_month_start_equity=float(raw["satellite_month_start_equity"]),
        month_key=str(raw["month_key"]),
        updated_at=str(raw.get("updated_at", "")),
    )
