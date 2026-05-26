# Trade — core-only движок (MOEX), paper-first

**100% капитала в core.** Раз в месяц: скан MOEX → топ-N в `.env` → пополнение → ребаланс топ-5.

## Быстрый старт (paper)

```bash
pip install -r requirements.txt
cp .env.example .env
python3 -m bot.scan    # ручной скан + обновление CORE_UNIVERSE
python3 -m bot         # paper-цикл (скан автоматически в новом месяце)
```

Состояние: `data/portfolio_state.json`. Отчёты скана: `data/scans/scan_YYYY-MM.*`.

## Как работает отбор (paper)

1. **Скан** 100 ликвидных TQBR → прогноз total (цена + дивиденды).
2. **Adaptive fill** — если строгих имён мало, ослабляет порог по ступеням до `SCAN_MIN_UNIVERSE`.
3. **Портфель** — топ-5 из universe **в порядке скана** (`CORE_SELECT_SCAN_ORDER=true`).
4. **EXIT** — досрочная продажа при плохом total-прогнозе (с учётом комиссии).
5. **Дивиденды** — начисление на отсечку MOEX; прокси только для прогноза.

```env
SCAN_ADAPTIVE_FILL=true
SCAN_MIN_UNIVERSE=10
SCAN_MIN_FORECAST_PCT=0.5
CORE_SELECT_SCAN_ORDER=true
PAPER_TRADING=true
```

## Данные

| Слой | Источник |
|------|----------|
| Цена/объём | MOEX ISS |
| Макро | IMOEX, USD/RUB, ставка ЦБ |
| Фундаментал | ЦКИ (если есть) или прокси |
| Новости | MOEX sitenews |
| Дивиденды | MOEX dividends.json + прокси по истории |

## EXIT и комиссия

`EXIT_ON_NEGATIVE_FORECAST=true`, `SCAN_SELL_FORECAST_PCT=-1.0`, `EXIT_FEE_BUFFER=1.2`, `COMMISSION_PCT=0.1`.

## Дивиденды в прогнозе

- **MOEX** — объявленная отсечка в ближайший месяц.
- **Прокси** — цикл выплат за 36 мес (не «/12 каждый месяц»).
- **Скидки**: нет истории → total × 0.85; редкие выплаты → div × 0.90.

```env
DIVIDEND_USE_PROXY=true
DIVIDEND_HISTORY_MONTHS=36
DIVIDEND_NO_INFO_DISCOUNT=0.85
DIVIDEND_SPARSE_DISCOUNT=0.90
```

## Replay на истории (2 года)

Та же логика, что paper-бот, день за днём на MOEX (walk-forward, без look-ahead по ликвидности):

```bash
python3 -m bot.backtest
```

Период: `BACKTEST_START` / `BACKTEST_END` в `.env` (по умолчанию 2 года). Отчёт: `data/paper_replay_report.csv`, сравнение с IMOEX DCA.

Не является инвестиционной рекомендацией.
