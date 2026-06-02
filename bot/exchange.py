import json
import logging
from dataclasses import dataclass
from pathlib import Path

import ccxt

from bot.config import Config

logger = logging.getLogger(__name__)

STATE_FILE = Path("state.json")


@dataclass
class Balances:
    quote: float  # USDT
    base: float  # BTC и т.д.


class ExchangeClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._exchange = self._create_exchange()
        self._balances = self._load_or_init_balances()

    def _create_exchange(self) -> ccxt.Exchange:
        exchange_class = getattr(ccxt, self.config.exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"Unknown exchange: {self.config.exchange_id}")

        options: dict = {"enableRateLimit": True}
        if self.config.api_key and self.config.api_secret:
            options["apiKey"] = self.config.api_key
            options["apiSecret"] = self.config.api_secret

        return exchange_class(options)

    def _load_or_init_balances(self) -> Balances:
        if self.config.paper_trading and STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            return Balances(quote=data["quote"], base=data["base"])

        if self.config.paper_trading:
            return Balances(
                quote=self.config.paper_usdt_balance,
                base=self.config.paper_base_balance,
            )

        return self.fetch_live_balances()

    def _save_balances(self) -> None:
        if not self.config.paper_trading:
            return
        STATE_FILE.write_text(
            json.dumps({"quote": self._balances.quote, "base": self._balances.base})
        )

    def fetch_ohlcv(self) -> list[float]:
        limit = self.config.slow_ma_period + 5
        candles = self._exchange.fetch_ohlcv(
            self.config.symbol,
            timeframe=self.config.timeframe,
            limit=limit,
        )
        return [float(c[4]) for c in candles]

    def fetch_live_balances(self) -> Balances:
        balance = self._exchange.fetch_balance()
        base, quote = self.config.symbol.split("/")
        return Balances(
            quote=float(balance.get(quote, {}).get("free", 0) or 0),
            base=float(balance.get(base, {}).get("free", 0) or 0),
        )

    @property
    def balances(self) -> Balances:
        if not self.config.paper_trading:
            self._balances = self.fetch_live_balances()
        return self._balances

    def execute_signal(self, signal: str, price: float) -> str | None:
        if signal == "hold":
            return None

        base, quote = self.config.symbol.split("/")
        balances = self.balances

        if signal == "buy" and balances.quote > 0:
            amount_quote = balances.quote * self.config.trade_size_ratio
            amount_base = amount_quote / price
            if self.config.paper_trading:
                self._balances = Balances(
                    quote=balances.quote - amount_quote,
                    base=balances.base + amount_base,
                )
                self._save_balances()
                msg = (
                    f"[PAPER] BUY {amount_base:.8f} {base} @ {price:.2f} "
                    f"({amount_quote:.2f} {quote})"
                )
            else:
                order = self._exchange.create_market_buy_order(
                    self.config.symbol, amount_base
                )
                msg = f"LIVE BUY order: {order.get('id', order)}"
            logger.info(msg)
            return msg

        if signal == "sell" and balances.base > 0:
            amount_base = balances.base * self.config.trade_size_ratio
            amount_quote = amount_base * price
            if self.config.paper_trading:
                self._balances = Balances(
                    quote=balances.quote + amount_quote,
                    base=balances.base - amount_base,
                )
                self._save_balances()
                msg = (
                    f"[PAPER] SELL {amount_base:.8f} {base} @ {price:.2f} "
                    f"({amount_quote:.2f} {quote})"
                )
            else:
                order = self._exchange.create_market_sell_order(
                    self.config.symbol, amount_base
                )
                msg = f"LIVE SELL order: {order.get('id', order)}"
            logger.info(msg)
            return msg

        logger.info("Signal %s skipped: insufficient balance", signal)
        return None
