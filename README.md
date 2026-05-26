# Trade — движок приращения капитала (РФ)

Бот для **устойчивого роста капитала**: ~80% в долгую (БПИФ и акции MOEX), ~20% в тактический рукав. Весь доход реинвестируется в paper/live-портфель. Брокер: **Финам** (фаза 2), данные и paper — **MOEX ISS**.

## План действий

Пошаговый чеклист: [docs/ACTION_PLAN.md](docs/ACTION_PLAN.md)

## Быстрый старт (фаза 1 — paper)

```bash
pip install -r requirements.txt
cp .env.example .env
python -m bot
```

Состояние виртуального портфеля: `data/portfolio_state.json`.

## Архитектура

```
bot/
  config.py              # .env
  runner.py              # главный цикл
  data/moex_iss.py       # котировки MOEX
  data/market_regime.py  # IMOEX, RVOL
  strategies/            # core momentum, satellite breakout
  portfolio/             # paper-портфель, ребаланс 80/20
  risk/                  # просадка, лимит satellite
  brokers/finam.py       # live — фаза 2
```

**Satellite:** пробой по закрытию, RVOL ≥ 1.5, IMOEX выше SMA(20), тикер выше SMA(50).

**Ребаланс (раз в месяц):** `REBALANCE_INTERVAL_SEC` ≈ 30 дней — мягкая подгонка **80/20** (сливки с перевеса, без продажи всего портфеля).  
**Satellite +20%:** только **сливки** лишнего с спутника до новых 20% от total; остаток спутника **остаётся в бумагах**.

## Следующий шаг для вас

1. Открыть счёт **Финам**, получить токен Trade API.  
2. 2–4 недели гонять `PAPER_TRADING=true`.  
3. Подключить live (фаза 2 в плане).

Не является инвестиционной рекомендацией.
