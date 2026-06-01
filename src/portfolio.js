'use strict';

const TARGET_ALLOCATION = {
  blue_chips: {
    label: 'Голубые фишки',
    target: 0.7,
    description: 'Крупные устойчивые компании для ядра портфеля.'
  },
  bonds: {
    label: 'Облигации',
    target: 0.2,
    description: 'Защитная часть портфеля с меньшей волатильностью.'
  },
  growth: {
    label: 'Быстрорастущие компании',
    target: 0.1,
    description: 'Небольшая доля компаний с высоким потенциалом и риском.'
  }
};

const DEFAULT_WATCHLIST = {
  blue_chips: [
    { symbol: 'AAPL', name: 'Apple', thesis: 'Сильная экосистема и устойчивые денежные потоки.' },
    { symbol: 'MSFT', name: 'Microsoft', thesis: 'Диверсифицированный бизнес, облако и корпоративный софт.' },
    { symbol: 'JNJ', name: 'Johnson & Johnson', thesis: 'Защитный сектор здравоохранения и дивидендная история.' },
    { symbol: 'PG', name: 'Procter & Gamble', thesis: 'Потребительские товары с устойчивым спросом.' },
    { symbol: 'KO', name: 'Coca-Cola', thesis: 'Глобальный бренд и предсказуемая дивидендная модель.' },
    { symbol: 'JPM', name: 'JPMorgan Chase', thesis: 'Крупный системный банк с широкой диверсификацией.' }
  ],
  bonds: [
    { symbol: 'BND', name: 'Vanguard Total Bond Market ETF', thesis: 'Широкая экспозиция на облигационный рынок США.' },
    { symbol: 'AGG', name: 'iShares Core U.S. Aggregate Bond ETF', thesis: 'Диверсифицированный облигационный ETF инвестиционного уровня.' },
    { symbol: 'IEF', name: 'iShares 7-10 Year Treasury Bond ETF', thesis: 'Среднесрочные казначейские облигации США.' },
    { symbol: 'SHY', name: 'iShares 1-3 Year Treasury Bond ETF', thesis: 'Короткие казначейские облигации с меньшей дюрацией.' }
  ],
  growth: [
    { symbol: 'NVDA', name: 'NVIDIA', thesis: 'Лидерство в ускорителях для AI и дата-центров.' },
    { symbol: 'AMZN', name: 'Amazon', thesis: 'AWS, e-commerce и масштабируемые платформенные бизнесы.' },
    { symbol: 'GOOGL', name: 'Alphabet', thesis: 'Поиск, реклама, облако и опциональность AI.' },
    { symbol: 'AMD', name: 'AMD', thesis: 'Конкурентные CPU/GPU и рост дата-центров.' },
    { symbol: 'ASML', name: 'ASML', thesis: 'Критически важное оборудование для полупроводников.' }
  ]
};

function normalizeTicker(ticker) {
  return String(ticker || '').trim().toUpperCase();
}

function normalizeAssetClass(assetClass) {
  return TARGET_ALLOCATION[assetClass] ? assetClass : 'blue_chips';
}

function toFiniteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function roundMoney(value) {
  return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
}

function validateTransaction(input) {
  const errors = [];
  const type = input.type === 'sell' ? 'sell' : 'buy';
  const ticker = normalizeTicker(input.ticker);
  const quantity = toFiniteNumber(input.quantity);
  const price = toFiniteNumber(input.price);
  const currency = String(input.currency || 'USD').trim().toUpperCase();

  if (!ticker) errors.push('Укажите тикер.');
  if (!quantity || quantity <= 0) errors.push('Количество должно быть больше 0.');
  if (!price || price <= 0) errors.push('Цена должна быть больше 0.');
  if (!/^[A-Z]{3}$/.test(currency)) errors.push('Валюта должна быть трехбуквенным кодом, например USD.');

  return {
    valid: errors.length === 0,
    errors,
    value: {
      id: input.id || createId(),
      type,
      ticker,
      name: String(input.name || '').trim(),
      assetClass: normalizeAssetClass(input.assetClass),
      quantity,
      price,
      currency,
      date: input.date || new Date().toISOString().slice(0, 10),
      notes: String(input.notes || '').trim(),
      createdAt: input.createdAt || new Date().toISOString()
    }
  };
}

function createId() {
  return `tx_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function buildPositions(transactions, quotes = {}) {
  const byTicker = new Map();

  for (const transaction of transactions || []) {
    const validated = validateTransaction(transaction);
    if (!validated.valid) continue;

    const tx = validated.value;
    const existing = byTicker.get(tx.ticker) || {
      ticker: tx.ticker,
      name: tx.name,
      assetClass: tx.assetClass,
      currency: tx.currency,
      quantity: 0,
      costBasis: 0,
      buys: 0,
      sells: 0,
      transactions: []
    };

    if (!existing.name && tx.name) existing.name = tx.name;
    existing.assetClass = tx.assetClass || existing.assetClass;
    existing.currency = tx.currency || existing.currency;
    existing.transactions.push(tx);

    if (tx.type === 'buy') {
      existing.quantity += tx.quantity;
      existing.costBasis += tx.quantity * tx.price;
      existing.buys += 1;
    } else {
      const quantityBeforeSale = existing.quantity;
      const averageCost = quantityBeforeSale > 0 ? existing.costBasis / quantityBeforeSale : 0;
      const closedQuantity = Math.min(tx.quantity, quantityBeforeSale);
      existing.quantity -= tx.quantity;
      existing.costBasis -= closedQuantity * averageCost;
      existing.sells += 1;
    }

    byTicker.set(tx.ticker, existing);
  }

  return Array.from(byTicker.values())
    .filter((position) => position.quantity > 0.0000001)
    .map((position) => {
      const quote = quotes[position.ticker] || {};
      const averagePrice = position.quantity > 0 ? position.costBasis / position.quantity : 0;
      const lastPrice = toFiniteNumber(quote.price) || averagePrice;
      const marketValue = position.quantity * lastPrice;
      const unrealizedPnl = marketValue - position.costBasis;
      const unrealizedPnlPct = position.costBasis > 0 ? unrealizedPnl / position.costBasis : 0;

      return {
        ...position,
        quantity: roundQuantity(position.quantity),
        costBasis: roundMoney(position.costBasis),
        averagePrice: roundMoney(averagePrice),
        lastPrice: roundMoney(lastPrice),
        marketValue: roundMoney(marketValue),
        unrealizedPnl: roundMoney(unrealizedPnl),
        unrealizedPnlPct,
        quote: {
          price: toFiniteNumber(quote.price) ? roundMoney(quote.price) : null,
          currency: quote.currency || position.currency,
          asOf: quote.asOf || null,
          source: quote.source || 'manual'
        }
      };
    })
    .sort((a, b) => b.marketValue - a.marketValue);
}

function roundQuantity(value) {
  return Math.round((Number(value) + Number.EPSILON) * 1000000) / 1000000;
}

function buildPortfolio(transactions, quotes = {}, watchlist = DEFAULT_WATCHLIST) {
  const positions = buildPositions(transactions, quotes);
  const totalValue = positions.reduce((sum, position) => sum + position.marketValue, 0);
  const totalCost = positions.reduce((sum, position) => sum + position.costBasis, 0);
  const unrealizedPnl = totalValue - totalCost;

  const allocation = Object.entries(TARGET_ALLOCATION).map(([key, meta]) => {
    const value = positions
      .filter((position) => position.assetClass === key)
      .reduce((sum, position) => sum + position.marketValue, 0);
    const current = totalValue > 0 ? value / totalValue : 0;

    return {
      key,
      label: meta.label,
      target: meta.target,
      current,
      value: roundMoney(value),
      drift: current - meta.target
    };
  });

  const currencies = Array.from(new Set(positions.map((position) => position.quote.currency || position.currency)));

  return {
    targets: TARGET_ALLOCATION,
    positions,
    allocation,
    transactions: [...(transactions || [])].sort((a, b) => String(b.date).localeCompare(String(a.date))),
    recommendations: buildRecommendations(positions, allocation, totalValue, watchlist),
    warnings: buildWarnings(currencies),
    totals: {
      value: roundMoney(totalValue),
      cost: roundMoney(totalCost),
      unrealizedPnl: roundMoney(unrealizedPnl),
      unrealizedPnlPct: totalCost > 0 ? unrealizedPnl / totalCost : 0,
      currencies
    }
  };
}

function buildWarnings(currencies) {
  if (currencies.length <= 1) return [];

  return [
    'В портфеле есть инструменты в разных валютах. MVP показывает сумму без FX-конвертации; для точной аллокации ведите позиции в одной базовой валюте.'
  ];
}

function buildRecommendations(positions, allocation, totalValue, watchlist = DEFAULT_WATCHLIST) {
  if (totalValue <= 0) {
    return [
      {
        action: 'start',
        title: 'Начать с целевой структуры 70/20/10',
        detail: 'Добавьте первые покупки: большую часть в голубые фишки, защитную часть в облигации и малую долю в рост.',
        candidates: [
          pickCandidate('blue_chips', positions, watchlist),
          pickCandidate('bonds', positions, watchlist),
          pickCandidate('growth', positions, watchlist)
        ].filter(Boolean)
      }
    ];
  }

  const recommendations = [];
  const rebalanceThreshold = 0.03;

  for (const item of allocation) {
    const targetValue = totalValue * item.target;
    const gapValue = targetValue - item.value;
    const absDrift = Math.abs(item.drift);

    if (item.drift < -rebalanceThreshold) {
      const candidate = pickCandidate(item.key, positions, watchlist);
      recommendations.push({
        action: 'buy',
        title: `Докупить: ${item.label}`,
        detail: `Доля ниже цели на ${formatPercent(absDrift)}. Для возврата к целевой структуре нужно докупить примерно на ${roundMoney(gapValue)}.`,
        amount: roundMoney(gapValue),
        assetClass: item.key,
        candidates: candidate ? [candidate] : []
      });
    }

    if (item.drift > rebalanceThreshold) {
      const largest = positions
        .filter((position) => position.assetClass === item.key)
        .sort((a, b) => b.marketValue - a.marketValue)[0];
      recommendations.push({
        action: 'sell',
        title: `Сократить: ${item.label}`,
        detail: `Доля выше цели на ${formatPercent(absDrift)}. Для ребаланса можно продать примерно на ${roundMoney(-gapValue)}.`,
        amount: roundMoney(-gapValue),
        assetClass: item.key,
        candidates: largest
          ? [
              {
                symbol: largest.ticker,
                name: largest.name || largest.ticker,
                thesis: 'Самая крупная позиция в перегруженной категории.'
              }
            ]
          : []
      });
    }
  }

  if (recommendations.length === 0) {
    recommendations.push({
      action: 'hold',
      title: 'Структура близка к цели',
      detail: 'Сильных отклонений от 70/20/10 нет. Новые покупки лучше направлять в категорию с минимальным текущим весом относительно цели.',
      candidates: [pickMostUnderweightCandidate(positions, allocation, watchlist)].filter(Boolean)
    });
  }

  return recommendations;
}

function pickCandidate(assetClass, positions, watchlist = DEFAULT_WATCHLIST) {
  const candidates = watchlist[assetClass] || [];
  const heldTickers = new Set(positions.map((position) => position.ticker));
  return candidates.find((candidate) => !heldTickers.has(candidate.symbol)) || candidates[0] || null;
}

function pickMostUnderweightCandidate(positions, allocation, watchlist) {
  const mostUnderweight = [...allocation].sort((a, b) => a.drift - b.drift)[0];
  return mostUnderweight ? pickCandidate(mostUnderweight.key, positions, watchlist) : null;
}

function formatPercent(value) {
  return `${Math.round(value * 1000) / 10}%`;
}

module.exports = {
  TARGET_ALLOCATION,
  DEFAULT_WATCHLIST,
  buildPortfolio,
  buildPositions,
  normalizeTicker,
  validateTransaction
};
