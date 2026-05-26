# Trade — движок приращения капитала (РФ)

Бот для роста капитала: **~80% core** (свой портфель акций MOEX), **~20% satellite** (импульс). Без БПИФ: core собирается из ликвидных акций по **cross-sectional momentum** и весам **1/σ**.

Данные и paper: **MOEX ISS**. Брокер live: **Финам** (фаза 2).

## План

[docs/ACTION_PLAN.md](docs/ACTION_PLAN.md)

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env
python3 -m bot
```

## Бэктест

```bash
python3 -m bot.backtest
```

По умолчанию ~2 года, 10 000 ₽ старт + 2 000 ₽/мес. В отчёте: дивиденды (нетто), комиссии, бенчмарк equal-weight по всему core-universe.

### Дивиденды и доходность цены

| Что учитывается | Как |
|-----------------|-----|
| Рост цены акций | Дневные **close** MOEX ISS |
| Дивиденды | `INCLUDE_DIVIDENDS=true`: выплаты по **дате отсечки** (registryclosedate), на кол-во акций в портфеле |
| Налог на дивы | `DIVIDEND_TAX_PCT` (по умолчанию 13%) |
| Комиссии | `COMMISSION_PCT` с оборота |
| Реинвест дивов | Зачисление в кэш рукава (core/sat), дальше в ежемесячный ребаланс |

**Не учитывается:** отсечка ≠ дата выплаты на счёт (упрощение), НДФЛ с продаж, купоны (только акции), корпоративные сплиты (редко — можно добавить).

Цены **не total return** — без дивидендов котировка занижает long-only доходность; с `INCLUDE_DIVIDENDS` картина ближе к реальности.

## Core-логика

1. Раз в месяц (после пополнения): ранжирование universe по доходности за `CORE_MOMENTUM_MONTHS` месяцев.
2. Фильтр: цена выше `CORE_TREND_SMA` (200).
3. Держим топ `CORE_TOP_N`, веса ∝ 1/volatility (`CORE_VOL_LOOKBACK`).
4. Продажа бумаг вне топа, подгонка весов.

## Satellite

Пробой + RVOL, IMOEX > SMA(20), тикер > SMA(50), equity ≥ `SATELLITE_MIN_EQUITY_RUB`.

## Архитектура

```
bot/
  strategies/cross_sectional.py
  portfolio/core_portfolio.py
  portfolio/dividends.py
  data/moex_iss.py
  data/moex_dividends.py
  analytics/benchmark.py
  backtest/engine.py
```

Не является инвестиционной рекомендацией.
