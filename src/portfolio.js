'use strict';

const RUB = 'RUB';

const TARGET_ALLOCATION = {
  blue_chips: {
    label: 'Голубые фишки',
    target: 0.7,
    phase: 1,
    description: 'Первый слой портфеля: крупные устойчивые компании Мосбиржи.'
  },
  bonds: {
    label: 'Облигации',
    target: 0.2,
    phase: 2,
    description: 'Второй слой портфеля: рублевые ОФЗ для защитной части.'
  },
  growth: {
    label: 'Быстрорастущие компании',
    target: 0.1,
    phase: 3,
    description: 'Третий слой портфеля: небольшая доля более рискованных идей.'
  }
};

const BUILD_ORDER = ['blue_chips', 'bonds', 'growth'];

const MOEX_WATCHLIST = {
  blue_chips: [
    {
      symbol: 'SBER',
      name: 'Сбербанк',
      yahooSymbol: 'SBER.ME',
      lotSize: 10,
      referencePrice: 300,
      thesis: 'Ликвидная голубая фишка, системный банк и база для старта портфеля.'
    },
    {
      symbol: 'GAZP',
      name: 'Газпром',
      yahooSymbol: 'GAZP.ME',
      lotSize: 10,
      referencePrice: 160,
      thesis: 'Крупная сырьевая компания с высокой ликвидностью на Мосбирже.'
    },
    {
      symbol: 'LKOH',
      name: 'Лукойл',
      yahooSymbol: 'LKOH.ME',
      lotSize: 1,
      referencePrice: 7000,
      thesis: 'Одна из крупнейших нефтяных компаний, подходит для ядра при большем балансе.'
    },
    {
      symbol: 'TATN',
      name: 'Татнефть',
      yahooSymbol: 'TATN.ME',
      lotSize: 1,
      referencePrice: 650,
      thesis: 'Ликвидная нефтяная голубая фишка с дивидендной историей.'
    },
    {
      symbol: 'ROSN',
      name: 'Роснефть',
      yahooSymbol: 'ROSN.ME',
      lotSize: 1,
      referencePrice: 550,
      thesis: 'Крупный представитель нефтегазового сектора.'
    },
    {
      symbol: 'YDEX',
      name: 'Яндекс',
      yahooSymbol: 'YDEX.ME',
      lotSize: 1,
      referencePrice: 4300,
      thesis: 'Крупная технологическая компания Мосбиржи для доли качественного роста в ядре.'
    }
  ],
  bonds: [
    {
      symbol: 'SU26243RMFS4',
      name: 'ОФЗ 26243',
      lotSize: 1,
      referencePrice: 1000,
      thesis: 'Рублевая государственная облигация для защитной части портфеля.'
    },
    {
      symbol: 'SU26244RMFS2',
      name: 'ОФЗ 26244',
      lotSize: 1,
      referencePrice: 1000,
      thesis: 'ОФЗ с длиннее дюрацией для облигационного блока.'
    },
    {
      symbol: 'SU26238RMFS4',
      name: 'ОФЗ 26238',
      lotSize: 1,
      referencePrice: 1000,
      thesis: 'Государственная рублевая облигация для постепенного набора защитной доли.'
    },
    {
      symbol: 'SU26240RMFS0',
      name: 'ОФЗ 26240',
      lotSize: 1,
      referencePrice: 1000,
      thesis: 'Еще один кандидат ОФЗ для диверсификации облигационного слоя.'
    }
  ],
  growth: [
    {
      symbol: 'OZON',
      name: 'Ozon',
      yahooSymbol: 'OZON.ME',
      lotSize: 1,
      referencePrice: 4000,
      thesis: 'Высокорисковая идея на рост e-commerce, только после ядра и облигаций.'
    },
    {
      symbol: 'POSI',
      name: 'Positive Technologies',
      yahooSymbol: 'POSI.ME',
      lotSize: 1,
      referencePrice: 2800,
      thesis: 'Компания кибербезопасности с потенциалом роста и повышенной волатильностью.'
    },
    {
      symbol: 'ASTR',
      name: 'Астра',
      yahooSymbol: 'ASTR.ME',
      lotSize: 1,
      referencePrice: 500,
      thesis: 'Российский разработчик ПО, идея для небольшой рискованной части.'
    },
    {
      symbol: 'WUSH',
      name: 'Whoosh',
      yahooSymbol: 'WUSH.ME',
      lotSize: 1,
      referencePrice: 180,
      thesis: 'Небольшая компания с потенциально быстрым ростом и высоким риском.'
    }
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

function roundQuantity(value) {
  return Math.round((Number(value) + Number.EPSILON) * 1000000) / 1000000;
}

function createId(prefix) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function findInstrument(ticker, watchlist = MOEX_WATCHLIST) {
  const normalized = normalizeTicker(ticker);
  return Object.values(watchlist)
    .flat()
    .find((instrument) => instrument.symbol === normalized);
}

function validateCashDeposit(input) {
  const errors = [];
  const amount = toFiniteNumber(input.amount);

  if (!amount || amount <= 0) errors.push('Сумма пополнения должна быть больше 0.');

  return {
    valid: errors.length === 0,
    errors,
    value: {
      id: input.id || createId('cash'),
      type: 'deposit',
      amount,
      currency: RUB,
      date: input.date || new Date().toISOString().slice(0, 10),
      notes: String(input.notes || '').trim(),
      createdAt: input.createdAt || new Date().toISOString()
    }
  };
}

function validateTransaction(input, watchlist = MOEX_WATCHLIST) {
  const errors = [];
  const type = input.type === 'sell' ? 'sell' : 'buy';
  const ticker = normalizeTicker(input.ticker);
  const quantity = toFiniteNumber(input.quantity);
  const price = toFiniteNumber(input.price);
  const instrument = findInstrument(ticker, watchlist);
  const assetClass = instrument ? getInstrumentAssetClass(ticker, watchlist) : normalizeAssetClass(input.assetClass);

  if (!ticker) errors.push('Укажите тикер.');
  if (ticker && !instrument) errors.push('Тикер должен быть из списка инструментов Мосбиржи в приложении.');
  if (!quantity || quantity <= 0) errors.push('Количество должно быть больше 0.');
  if (!price || price <= 0) errors.push('Цена должна быть больше 0.');
  if (input.currency && String(input.currency).toUpperCase() !== RUB) {
    errors.push('Сейчас поддерживается только рублевая торговля на Мосбирже.');
  }

  return {
    valid: errors.length === 0,
    errors,
    value: {
      id: input.id || createId('tx'),
      type,
      ticker,
      name: instrument?.name || String(input.name || '').trim(),
      assetClass,
      quantity,
      price,
      currency: RUB,
      date: input.date || new Date().toISOString().slice(0, 10),
      notes: String(input.notes || '').trim(),
      createdAt: input.createdAt || new Date().toISOString()
    }
  };
}

function getInstrumentAssetClass(ticker, watchlist = MOEX_WATCHLIST) {
  const normalized = normalizeTicker(ticker);
  for (const [assetClass, instruments] of Object.entries(watchlist)) {
    if (instruments.some((instrument) => instrument.symbol === normalized)) return assetClass;
  }
  return 'blue_chips';
}

function calculateCash(cashMovements = [], transactions = []) {
  const deposited = cashMovements.reduce((sum, movement) => {
    const amount = toFiniteNumber(movement.amount);
    return movement.type === 'deposit' && amount ? sum + amount : sum;
  }, 0);

  const fromTrades = transactions.reduce((sum, transaction) => {
    const quantity = toFiniteNumber(transaction.quantity) || 0;
    const price = toFiniteNumber(transaction.price) || 0;
    const value = quantity * price;
    return transaction.type === 'sell' ? sum + value : sum - value;
  }, 0);

  return {
    deposited: roundMoney(deposited),
    balance: roundMoney(deposited + fromTrades)
  };
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
      currency: RUB,
      quantity: 0,
      costBasis: 0,
      buys: 0,
      sells: 0,
      transactions: []
    };

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
          currency: RUB,
          asOf: quote.asOf || null,
          source: quote.source || 'средняя цена'
        }
      };
    })
    .sort((a, b) => b.marketValue - a.marketValue);
}

function buildPortfolio(transactions, quotes = {}, watchlist = MOEX_WATCHLIST, cashMovements = []) {
  const positions = buildPositions(transactions, quotes);
  const cash = calculateCash(cashMovements, transactions);
  const investedValue = positions.reduce((sum, position) => sum + position.marketValue, 0);
  const totalCost = positions.reduce((sum, position) => sum + position.costBasis, 0);
  const totalAssets = investedValue + cash.balance;
  const unrealizedPnl = investedValue - totalCost;

  const allocation = Object.entries(TARGET_ALLOCATION).map(([key, meta]) => {
    const value = positions
      .filter((position) => position.assetClass === key)
      .reduce((sum, position) => sum + position.marketValue, 0);
    const current = investedValue > 0 ? value / investedValue : 0;
    const planCurrent = totalAssets > 0 ? value / totalAssets : 0;

    return {
      key,
      label: meta.label,
      target: meta.target,
      current,
      planCurrent,
      value: roundMoney(value),
      targetValue: roundMoney(totalAssets * meta.target),
      remainingToTarget: roundMoney(Math.max(totalAssets * meta.target - value, 0)),
      drift: planCurrent - meta.target
    };
  });

  return {
    market: 'MOEX',
    currency: RUB,
    targets: TARGET_ALLOCATION,
    buildOrder: BUILD_ORDER,
    positions,
    allocation,
    cash,
    cashMovements: [...(cashMovements || [])].sort((a, b) => String(b.date).localeCompare(String(a.date))),
    transactions: [...(transactions || [])].sort((a, b) => String(b.date).localeCompare(String(a.date))),
    recommendations: buildRecommendations(positions, allocation, cash, totalAssets, quotes, watchlist),
    totals: {
      investedValue: roundMoney(investedValue),
      assetsWithCash: roundMoney(totalAssets),
      cost: roundMoney(totalCost),
      unrealizedPnl: roundMoney(unrealizedPnl),
      unrealizedPnlPct: totalCost > 0 ? unrealizedPnl / totalCost : 0,
      currency: RUB
    }
  };
}

function buildRecommendations(positions, allocation, cash, totalAssets, quotes = {}, watchlist = MOEX_WATCHLIST) {
  if (cash.balance <= 0) {
    return [
      {
        action: 'deposit',
        title: 'Пополните рублевый баланс',
        detail: 'Сначала внесите сумму на баланс. После этого бот предложит конкретную покупку на Мосбирже.',
        phase: null,
        candidates: []
      }
    ];
  }

  const phase = findBuildPhase(allocation, totalAssets);
  const targetAllocation = allocation.find((item) => item.key === phase);
  const candidate = pickAffordableCandidate(phase, cash.balance, positions, quotes, watchlist);

  if (!candidate.affordable) {
    return [
      {
        action: 'wait',
        title: `Копим на первый лот: ${TARGET_ALLOCATION[phase].label}`,
        detail: `Следующий этап портфеля — ${TARGET_ALLOCATION[phase].label}. На балансе ${roundMoney(cash.balance)} RUB, а самый доступный лот из списка стоит около ${roundMoney(candidate.lotCost)} RUB.`,
        phase,
        missingAmount: roundMoney(candidate.lotCost - cash.balance),
        candidates: [candidate.instrument]
      }
    ];
  }

  const maxLotsByCash = Math.floor(cash.balance / candidate.lotCost);
  const maxLotsByGap = targetAllocation.remainingToTarget > 0
    ? Math.max(1, Math.floor(targetAllocation.remainingToTarget / candidate.lotCost))
    : 1;
  const lotsToBuy = Math.max(1, Math.min(maxLotsByCash, maxLotsByGap));
  const estimatedCost = roundMoney(lotsToBuy * candidate.lotCost);

  return [
    {
      action: 'buy',
      title: `Купить ${candidate.instrument.symbol}: ${candidate.instrument.name}`,
      detail: `Сейчас собираем этап ${TARGET_ALLOCATION[phase].phase}: ${TARGET_ALLOCATION[phase].label}. Купите ${lotsToBuy} лот(а) по ${candidate.instrument.lotSize} шт., ориентировочно на ${estimatedCost} RUB.`,
      phase,
      lotsToBuy,
      sharesToBuy: lotsToBuy * candidate.instrument.lotSize,
      estimatedCost,
      targetRemaining: targetAllocation.remainingToTarget,
      candidates: [candidate.instrument]
    }
  ];
}

function findBuildPhase(allocation, totalAssets) {
  if (totalAssets <= 0) return 'blue_chips';

  for (const phase of BUILD_ORDER) {
    const item = allocation.find((entry) => entry.key === phase);
    if (!item || item.value + 0.01 < item.targetValue) return phase;
  }

  return [...allocation].sort((a, b) => a.drift - b.drift)[0]?.key || 'blue_chips';
}

function pickAffordableCandidate(assetClass, cashBalance, positions, quotes = {}, watchlist = MOEX_WATCHLIST) {
  const instruments = (watchlist[assetClass] || []).map((instrument) => {
    const quotePrice = toFiniteNumber(quotes[instrument.symbol]?.price);
    const price = quotePrice || instrument.referencePrice;
    const lotSize = instrument.lotSize || 1;
    const heldValue = positions
      .filter((position) => position.ticker === instrument.symbol)
      .reduce((sum, position) => sum + position.marketValue, 0);

    return {
      instrument: {
        ...instrument,
        price: roundMoney(price),
        lotCost: roundMoney(price * lotSize),
        priceSource: quotePrice ? quotes[instrument.symbol].source : 'ориентир'
      },
      price,
      lotCost: price * lotSize,
      heldValue
    };
  });

  const affordable = instruments
    .filter((candidate) => candidate.lotCost <= cashBalance)
    .sort((a, b) => a.heldValue - b.heldValue || a.lotCost - b.lotCost)[0];

  if (affordable) {
    return {
      affordable: true,
      ...affordable
    };
  }

  const cheapest = instruments.sort((a, b) => a.lotCost - b.lotCost)[0];
  return {
    affordable: false,
    ...cheapest
  };
}

module.exports = {
  RUB,
  TARGET_ALLOCATION,
  BUILD_ORDER,
  MOEX_WATCHLIST,
  buildPortfolio,
  buildPositions,
  calculateCash,
  findBuildPhase,
  findInstrument,
  normalizeTicker,
  validateCashDeposit,
  validateTransaction
};
