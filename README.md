# Trade — core-only движок (MOEX)

**100% капитала в core** — без satellite. Раз в месяц:

1. **Скан всей биржи** (акции TQBR) → топ-20 по momentum + ликвидность  
2. **Обновление `.env`** (`CORE_UNIVERSE`)  
3. **Пополнение** + ребаланс: из 20 держим **топ-5** с весами 1/σ  

## Команды

```bash
pip install -r requirements.txt
cp .env.example .env

# Разовый / ручной месячный скан
python3 -m bot.scan

# Paper-бот (скан автоматически в новом месяце)
python3 -m bot

# Бэктест (walk-forward: скан на каждый месяц по истории)
python3 -m bot.backtest
```

Отчёты скана: `data/scans/scan_YYYY-MM.json` и `.txt`.

## Скоринг скана

- Пул: топ-100 по обороту за день (≥ `MIN_DAILY_VOLUME_RUB`)
- Score: **70%** доходность за 6 мес + **30%** ликвидность
- БПИФ/ETF отфильтрованы

## Дивиденды

В бэктесте: дата отсечки MOEX ISS, налог `DIVIDEND_TAX_PCT`. Цены — close (не total return).

Не является инвестиционной рекомендацией.
