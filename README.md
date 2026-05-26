# Trade — core-only движок (MOEX), paper-first

**80% акции / 20% облигации (SBGB)** + core. Раз в месяц: скан → universe → ребаланс.

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env
python3 -m bot.scan
python3 -m bot
```

## Портфель

| Доля | Инструмент | Логика |
|------|------------|--------|
| **80%** | топ-3…5 акций из скана | inverse-vol, **мин. 3 позиции** |
| **20%** | `BOND_TICKER=SBGB` | ETF на ОФЗ, ребаланс каждый месяц |

```env
CORE_TOP_N=5
CORE_MIN_POSITIONS=3
BOND_ALLOCATION_PCT=20
BOND_TICKER=SBGB
SCAN_ADAPTIVE_MAX_TIER=liquid-positive   # не опускаться до liquid-top
```

## Adaptive fill

Ступени: `strict` → `strict-soft` → `strict-positive` → `liquid-positive` → `liquid-top`.  
По умолчанию **не ниже `liquid-positive`** — слабые имена из `liquid-top` не попадают в universe.

## Дивиденды — как считаем (реальная история MOEX)

**Источник:** `iss.moex.com/iss/securities/{TICKER}/dividends.json` — фактические выплаты с датой отсечки и суммой на акцию.

**Paper / replay начисляет так:**

1. В день **отсечки** (`registry_close`) смотрим: есть ли акции в портфеле.
2. Если да → `qty × value × (1 − DIVIDEND_TAX_PCT)` в кэш.
3. Если нет → 0.

**Купил в середине года?**

- Купил **до отсечки** → получишь эту выплату (как у брокера, если успел на реестр).
- Купил **после отсечки** → эту выплату не получишь, только следующую.
- Решение совета директоров уже заложено в MOEX: в API только **объявленные** выплаты, не «может быть».

**Прокси-дивиденды** (`DIVIDEND_USE_PROXY`) — **только для прогноза** в скане/EXIT, в кэш не начисляются.

**Почему за год ~3k ₽ дивов?** Портфель 20–30k, бумаги-плательщики (SBER, X5, VTBR, LEAS, EUTR…), несколько отсечек в год, сумма растёт с размером позиции. Это не «лишние» деньги — они уже в `equity` (кэш после отсечки).

## Replay на истории

```bash
python3 -m bot.backtest
```

Отчёт: `data/paper_replay_report.csv` (сравнение с IMOEX DCA).

Не является инвестиционной рекомендацией.
