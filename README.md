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
  strategies/            # core momentum, satellite breakout
  portfolio/             # paper-портфель и исполнение
  risk/                  # просадка, лимит satellite
  brokers/finam.py       # live — фаза 2
```

## Следующий шаг для вас

1. Открыть счёт **Финам**, получить токен Trade API.  
2. 2–4 недели гонять `PAPER_TRADING=true`.  
3. Подключить live (фаза 2 в плане).

Не является инвестиционной рекомендацией.
