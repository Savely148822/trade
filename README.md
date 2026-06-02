# Trade Bot

Торговый бот для криптобирж на Python. Подключается к биржам через [CCXT](https://github.com/ccxt/ccxt) (Binance, Bybit, OKX, Kraken и др.) и торгует по стратегии пересечения скользящих средних (MA crossover).

По умолчанию работает в **режиме paper trading** — реальные деньги не тратятся.

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m bot
```

## Настройка

Скопируйте `.env.example` в `.env` и отредактируйте переменные:

| Переменная | Описание |
|------------|----------|
| `EXCHANGE_ID` | ID биржи в CCXT (`binance`, `bybit`, `okx`, …) |
| `API_KEY` / `API_SECRET` | Ключи API (нужны только для live-режима) |
| `PAPER_TRADING` | `true` — симуляция, `false` — реальные ордера |
| `SYMBOL` | Пара, например `BTC/USDT` |
| `TIMEFRAME` | Таймфрейм свечей: `1m`, `5m`, `1h`, `4h`, `1d` |
| `FAST_MA_PERIOD` | Период быстрой SMA |
| `SLOW_MA_PERIOD` | Период медленной SMA |
| `TRADE_SIZE_RATIO` | Доля баланса на сделку (0.0–1.0) |
| `POLL_INTERVAL_SEC` | Как часто проверять рынок (секунды) |

## Стратегия

Бот считает две простые скользящие средние (SMA) по ценам закрытия:

- **Покупка** — быстрая MA пересекает медленную снизу вверх
- **Продажа** — быстрая MA пересекает медленную сверху вниз

Это учебная стратегия, не финансовый совет. Перед live-торговлей протестируйте на paper и оцените риски.

## Live-торговля

1. Создайте API-ключи на бирже с правами только на торговлю (без вывода).
2. Укажите `API_KEY` и `API_SECRET` в `.env`.
3. Установите `PAPER_TRADING=false`.
4. Запустите бота: `python -m bot`.

## Структура проекта

```
bot/
  config.py      # загрузка настроек из .env
  exchange.py    # работа с биржей и paper-балансом
  strategy.py    # MA crossover
  runner.py      # основной цикл
  __main__.py    # точка входа
```

## Остановка

`Ctrl+C` — бот завершит работу. В paper-режиме баланс сохраняется в `state.json`.
