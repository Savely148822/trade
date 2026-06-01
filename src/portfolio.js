'use strict';

const RUB = 'RUB';
const DEFAULT_COMMISSION_RATE = 0.0006;

const TARGET_ALLOCATION = {
  blue_chips: {
    label: 'Голубые фишки',
    target: 0.7,
    phase: 1,
    description: 'Крупные ликвидные компании Мосбиржи для ядра портфеля.'
  },
  bonds: {
    label: 'Облигации',
    target: 0.2,
    phase: 2,
    description: 'Рублевые облигации, в MVP приоритет — ОФЗ.'
  },
  growth: {
    label: 'Быстрорастущие компании',
    target: 0.1,
    phase: 3,
    description: 'Более рискованные акции с потенциалом роста.'
  }
};

const BUILD_ORDER = ['blue_chips', 'bonds', 'growth'];

const MARKET_UNIVERSE = {
  blue_chips: ['SBER', 'GAZP', 'LKOH', 'ROSN', 'TATN', 'GMKN', 'NVTK', 'PLZL', 'YDEX', 'T'],
  bonds: ['SU26243RMFS4', 'SU26244RMFS2', 'SU26238RMFS4', 'SU26240RMFS0'],
  growth: ['OZON', 'POSI', 'ASTR', 'WUSH', 'VKCO', 'HEAD', 'ETLN']
};

const FALLBACK_INSTRUMENTS = {
  SBER: { symbol: 'SBER', name: 'Сбербанк', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 320 },
  GAZP: { symbol: 'GAZP', name: 'Газпром', market: 'shares', board: 'TQBR', lotSize: 10, referencePrice: 160 },
  LKOH: { symbol: 'LKOH', name: 'Лукойл', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 7000 },
  ROSN: { symbol: 'ROSN', name: 'Роснефть', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 550 },
  TATN: { symbol: 'TATN', name: 'Татнефть', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 650 },
  GMKN: { symbol: 'GMKN', name: 'ГМК Норникель', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 130 },
  NVTK: { symbol: 'NVTK', name: 'Новатэк', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 1100 },
  PLZL: { symbol: 'PLZL', name: 'Полюс', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 2200 },
  YDEX: { symbol: 'YDEX', name: 'Яндекс', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 4300 },
  T: { symbol: 'T', name: 'Т-Технологии', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 3300 },
  OZON: { symbol: 'OZON', name: 'Ozon', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 4000 },
  POSI: { symbol: 'POSI', name: 'Positive Technologies', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 2800 },
  ASTR: { symbol: 'ASTR', name: 'Астра', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 500 },
  WUSH: { symbol: 'WUSH', name: 'Whoosh', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 180 },
  VKCO: { symbol: 'VKCO', name: 'VK', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 350 },
  HEAD: { symbol: 'HEAD', name: 'HeadHunter', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 3500 },
  ETLN: { symbol: 'ETLN', name: 'Эталон', market: 'shares', board: 'TQBR', lotSize: 1, referencePrice: 80 },
  SU26243RMFS4: { symbol: 'SU26243RMFS4', name: 'ОФЗ 26243', market: 'bonds', board: 'TQOB', lotSize: 1, referencePrice: 800 },
  SU26244RMFS2: { symbol: 'SU26244RMFS2', name: 'ОФЗ 26244', market: 'bonds', board: 'TQOB', lotSize: 1, referencePrice: 900 },
  SU26238RMFS4: { symbol: 'SU26238RMFS4', name: 'ОФЗ 26238', market: 'bonds', board: 'TQOB', lotSize: 1, referencePrice: 700 },
  SU26240RMFS0: { symbol: 'SU26240RMFS0', name: 'ОФЗ 26240', market: 'bonds', board: 'TQOB', lotSize: 1, referencePrice: 800 }
};

function normalizeTicker(ticker) {
  return String(ticker || '').trim().toUpperCase();
}

function normalizeAssetClass(assetClass) {
  return TARGET_ALLOCATION[assetClass] ? assetClass : 'blue_chips';
}

function normalizeSettings(settings = {}) {
  const commissionRate = toFiniteNumber(settings.commissionRate);

  return {
    commissionRate:
      commissionRate !== null && commissionRate >= 0 && commissionRate <= 0.05
        ? commissionRate
        : DEFAULT_COMMISSION_RATE
  };
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

function getUniverseTickers() {
  return [...new Set(Object.values(MARKET_UNIVERSE).flat())];
}

function findInstrument(ticker) {
  return FALLBACK_INSTRUMENTS[normalizeTicker(ticker)] || null;
}

function classifyInstrument(instrument = {}, blueChipTickers = []) {
  const ticker = normalizeTicker(instrument.symbol || instrument.SECID);
  const market = instrument.market || instrument.marketType;
  const sector = String(instrument.sector || instrument.INSTRID || '').toUpperCase();
  const securityType = String(instrument.securityType || instrument.SECTYPE || '').toUpperCase();
  const blueChipSet = new Set([...MARKET_UNIVERSE.blue_chips, ...blueChipTickers].map(normalizeTicker));

  if (market === 'bonds' || ticker.startsWith('SU') || securityType === '3' || sector.includes('BOND')) {
    return 'bonds';
  }

  if (blueChipSet.has(ticker) || Number(instrument.capitalization || 0) > 500_000_000_000) {
    return 'blue_chips';
  }

  return 'growth';
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

function validateSettings(input) {
  const errors = [];
  const commissionRate = toFiniteNumber(input.commissionRate);

  if (commissionRate === null || commissionRate < 0 || commissionRate > 0.05) {
    errors.push('Комиссия должна быть числом от 0 до 5%.');
  }

  return {
    valid: errors.length === 0,
    errors,
    value: normalizeSettings({ commissionRate })
  };
}

function validateTransaction(input) {
  const errors = [];
  const type = input.type === 'sell' ? 'sell' : 'buy';
  const ticker = normalizeTicker(input.ticker);
  const quantity = toFiniteNumber(input.quantity);
  const price = toFiniteNumber(input.price);
  const fallback = findInstrument(ticker);
  const isMoexVerified = input.moexVerified === true || Boolean(fallback);

  if (!ticker) errors.push('Укажите тикер.');
  if (ticker && !isMoexVerified) errors.push('Тикер должен быть найден на Московской бирже.');
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
      name: String(input.name || fallback?.name || ticker).trim(),
      assetClass: normalizeAssetClass(input.assetClass || fallback?.assetClass),
      quantity,
      price,
      currency: RUB,
      date: input.date || new Date().toISOString().slice(0, 10),
      notes: String(input.notes || '').trim(),
      createdAt: input.createdAt || new Date().toISOString()
    }
  };
}

function tradeCashImpact(transaction, settings = {}) {
  const { commissionRate } = normalizeSettings(settings);
  const gross = (toFiniteNumber(transaction.quantity) || 0) * (toFiniteNumber(transaction.price) || 0);
  const commission = gross * commissionRate;
  const total = transaction.type === 'sell' ? gross - commission : gross + commission;

  return {
    gross: roundMoney(gross),
    commission: roundMoney(commission),
    total: roundMoney(total),
    signedCash: roundMoney(transaction.type === 'sell' ? total : -total)
  };
}

function calculateCash(cashMovements = [], transactions = [], settings = {}) {
  const deposited = cashMovements.reduce((sum, movement) => {
    const amount = toFiniteNumber(movement.amount);
    return movement.type === 'deposit' && amount ? sum + amount : sum;
  }, 0);

  const fromTrades = transactions.reduce((sum, transaction) => {
    return sum + tradeCashImpact(transaction, settings).signedCash;
  }, 0);

  return {
    deposited: roundMoney(deposited),
    balance: roundMoney(deposited + fromTrades)
  };
}

function buildPositions(transactions, quotes = {}, settings = {}) {
  const byTicker = new Map();

  for (const transaction of transactions || []) {
    const validated = validateTransaction({ ...transaction, moexVerified: true });
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
    existing.assetClass = tx.assetClass || existing.assetClass;
    existing.name = tx.name || existing.name;

    if (tx.type === 'buy') {
      const impact = tradeCashImpact(tx, settings);
      existing.quantity += tx.quantity;
      existing.costBasis += impact.total;
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
          ...quote,
          price: toFiniteNumber(quote.price) ? roundMoney(quote.price) : null,
          currency: RUB,
          asOf: quote.asOf || null,
          source: quote.source || 'средняя цена'
        }
      };
    })
    .sort((a, b) => b.marketValue - a.marketValue);
}

function buildPortfolio(transactions, quotes = {}, settings = {}, cashMovements = []) {
  const normalizedSettings = normalizeSettings(settings);
  const positions = buildPositions(transactions, quotes, normalizedSettings);
  const cash = calculateCash(cashMovements, transactions, normalizedSettings);
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
    dataSource: 'MOEX ISS',
    currency: RUB,
    settings: normalizedSettings,
    targets: TARGET_ALLOCATION,
    buildOrder: BUILD_ORDER,
    positions,
    allocation,
    cash,
    cashMovements: [...(cashMovements || [])].sort((a, b) => String(b.date).localeCompare(String(a.date))),
    transactions: [...(transactions || [])].sort((a, b) => String(b.date).localeCompare(String(a.date))),
    recommendations: buildRecommendations(positions, allocation, cash, totalAssets, quotes, normalizedSettings),
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

function buildRecommendations(positions, allocation, cash, totalAssets, quotes = {}, settings = {}) {
  const recommendations = [];
  const sellIdeas = buildSellIdeas(positions, allocation, quotes);
  recommendations.push(...sellIdeas);

  if (cash.balance <= 0) {
    recommendations.push({
      action: 'deposit',
      title: 'Пополните рублевый баланс',
      detail: 'Свободных рублей нет. После пополнения бот выберет следующий инструмент на Мосбирже.',
      phase: null,
      candidates: []
    });
    return recommendations;
  }

  const phase = findBuildPhase(allocation, totalAssets);
  const targetAllocation = allocation.find((item) => item.key === phase);
  const candidate = pickBestBuyCandidate(phase, cash.balance, positions, quotes, settings);

  if (!candidate) {
    recommendations.push({
      action: 'wait',
      title: `Нет подходящего инструмента для этапа: ${TARGET_ALLOCATION[phase].label}`,
      detail: 'MOEX ISS не вернул данные по кандидатам. Попробуйте обновить рынок позже.',
      phase,
      candidates: []
    });
    return recommendations;
  }

  if (!candidate.affordable) {
    recommendations.push({
      action: 'wait',
      title: `Копим на первый лот: ${TARGET_ALLOCATION[phase].label}`,
      detail: `Следующий этап — ${TARGET_ALLOCATION[phase].label}. На балансе ${roundMoney(cash.balance)} RUB, а самый доступный лот с комиссией стоит около ${roundMoney(candidate.lotCostWithCommission)} RUB.`,
      phase,
      missingAmount: roundMoney(candidate.lotCostWithCommission - cash.balance),
      candidates: [candidate.instrument]
    });
    return recommendations;
  }

  const maxLotsByCash = Math.floor(cash.balance / candidate.lotCostWithCommission);
  const maxLotsByGap = targetAllocation.remainingToTarget > 0
    ? Math.max(1, Math.floor(targetAllocation.remainingToTarget / candidate.lotCostWithCommission))
    : 1;
  const lotsToBuy = Math.max(1, Math.min(maxLotsByCash, maxLotsByGap));
  const estimatedCost = roundMoney(lotsToBuy * candidate.lotCostWithCommission);

  recommendations.push({
    action: 'buy',
    title: `Докупить ${candidate.instrument.symbol}: ${candidate.instrument.name}`,
    detail: `Этап ${TARGET_ALLOCATION[phase].phase}: ${TARGET_ALLOCATION[phase].label}. Скоринг покупки ${candidate.instrument.analysis?.buyScore ?? 0}/100. ${candidate.instrument.analysis?.summary || ''}`,
    phase,
    lotsToBuy,
    sharesToBuy: lotsToBuy * candidate.instrument.lotSize,
    estimatedCost,
    targetRemaining: targetAllocation.remainingToTarget,
    candidates: [candidate.instrument]
  });

  return recommendations;
}

function buildSellIdeas(positions, allocation, quotes = {}) {
  const ideas = [];

  for (const position of positions) {
    const quote = quotes[position.ticker] || {};
    const allocationItem = allocation.find((item) => item.key === position.assetClass);
    const overweight = allocationItem ? allocationItem.drift > 0.05 : false;
    const analysis = quote.analysis || {};
    const overbought = Number(analysis.overboughtScore || 0) >= 70;
    const weakScore = Number(analysis.buyScore || 0) < 35;

    if (!overweight && !overbought && !weakScore) continue;

    const trimAmount = overweight
      ? Math.min(position.marketValue, allocationItem.value - allocationItem.targetValue)
      : Math.min(position.marketValue * 0.25, position.marketValue);

    ideas.push({
      action: 'sell',
      title: `Рассмотреть сокращение ${position.ticker}`,
      detail: [
        overweight ? `Категория выше цели на ${formatPercent(allocationItem.drift)}.` : null,
        overbought ? `Бумага выглядит перекупленной: ${analysis.overboughtScore}/100.` : null,
        weakScore ? `Скоринг покупки низкий: ${analysis.buyScore}/100.` : null
      ].filter(Boolean).join(' '),
      phase: position.assetClass,
      estimatedSellAmount: roundMoney(Math.max(trimAmount, 0)),
      candidates: [
        {
          symbol: position.ticker,
          name: position.name,
          lotSize: quote.lotSize || 1,
          price: quote.price || position.lastPrice,
          lotCost: quote.lotCost || position.lastPrice,
          analysis
        }
      ]
    });
  }

  return ideas.sort((a, b) => (b.candidates[0].analysis?.overboughtScore || 0) - (a.candidates[0].analysis?.overboughtScore || 0));
}

function findBuildPhase(allocation, totalAssets) {
  if (totalAssets <= 0) return 'blue_chips';

  for (const phase of BUILD_ORDER) {
    const item = allocation.find((entry) => entry.key === phase);
    if (!item || item.value + 0.01 < item.targetValue) return phase;
  }

  return [...allocation].sort((a, b) => a.drift - b.drift)[0]?.key || 'blue_chips';
}

function pickBestBuyCandidate(assetClass, cashBalance, positions, quotes = {}, settings = {}) {
  const { commissionRate } = normalizeSettings(settings);
  const tickers = MARKET_UNIVERSE[assetClass] || [];
  const candidates = tickers
    .map((ticker, index) => {
      const fallback = findInstrument(ticker);
      const quote = quotes[ticker] || {};
      const price = toFiniteNumber(quote.price) || fallback?.referencePrice;
      const lotSize = quote.lotSize || fallback?.lotSize || 1;
      if (!price) return null;

      const heldValue = positions
        .filter((position) => position.ticker === ticker)
        .reduce((sum, position) => sum + position.marketValue, 0);
      const lotCost = price * lotSize;
      const lotCostWithCommission = lotCost * (1 + commissionRate);
      const analysis = quote.analysis || scoreInstrument({
        ...fallback,
        ...quote,
        assetClass,
        price,
        lotSize
      });

      return {
        instrument: {
          ...fallback,
          ...quote,
          symbol: ticker,
          name: quote.name || fallback?.name || ticker,
          assetClass,
          price: roundMoney(price),
          lotSize,
          lotCost: roundMoney(lotCost),
          lotCostWithCommission: roundMoney(lotCostWithCommission),
          analysis
        },
        lotCost,
        lotCostWithCommission,
        heldValue,
        index,
        buyScore: Number(analysis.buyScore || 0),
        overboughtScore: Number(analysis.overboughtScore || 0)
      };
    })
    .filter(Boolean);

  const affordable = candidates
    .filter((candidate) => candidate.lotCostWithCommission <= cashBalance && candidate.overboughtScore < 80)
    .sort((a, b) => b.buyScore - a.buyScore || a.heldValue - b.heldValue || a.index - b.index)[0];

  if (affordable) {
    return {
      affordable: true,
      ...affordable
    };
  }

  const cheapest = candidates.sort((a, b) => a.lotCostWithCommission - b.lotCostWithCommission)[0];
  return cheapest
    ? {
        affordable: false,
        ...cheapest
      }
    : null;
}

function scoreInstrument(instrument = {}) {
  const assetClass = normalizeAssetClass(instrument.assetClass || classifyInstrument(instrument));
  const spreadPercent = Number(instrument.spreadPercent || 0);
  const turnover = Number(instrument.turnover || 0);
  const pricePosition52w = clamp(Number(instrument.pricePosition52w ?? 0.5), 0, 1);
  const return20d = Number(instrument.return20d || 0);
  const return60d = Number(instrument.return60d || 0);
  const yieldValue = Number(instrument.yield || 0);
  const duration = Number(instrument.duration || 0);
  const listLevel = Number(instrument.listLevel || 3);
  const blueChipBonus = assetClass === 'blue_chips' ? 12 : 0;

  let buyScore = 50;
  let overboughtScore = 0;
  const reasons = [];
  const risks = [];

  if (assetClass === 'bonds') {
    buyScore += yieldValue >= 12 ? 20 : yieldValue >= 9 ? 12 : 0;
    buyScore += duration > 0 && duration <= 1800 ? 10 : duration > 2600 ? -8 : 0;
    buyScore += spreadPercent <= 0.2 ? 8 : spreadPercent > 1 ? -12 : 0;
    buyScore += turnover > 10_000_000 ? 7 : 0;
    overboughtScore = yieldValue > 0 && yieldValue < 8 ? 45 : 15;
    reasons.push(`Доходность ${yieldValue ? `${roundMoney(yieldValue)}%` : 'н/д'}, дюрация ${duration || 'н/д'}.`);
  } else {
    buyScore += blueChipBonus;
    buyScore += listLevel === 1 ? 8 : listLevel === 2 ? 3 : -5;
    buyScore += turnover > 500_000_000 ? 12 : turnover > 100_000_000 ? 7 : turnover < 5_000_000 ? -10 : 0;
    buyScore += spreadPercent <= 0.08 ? 8 : spreadPercent <= 0.25 ? 3 : -10;
    buyScore += pricePosition52w < 0.35 ? 12 : pricePosition52w < 0.7 ? 6 : pricePosition52w > 0.9 ? -18 : -8;
    buyScore += return20d > 0 && return20d < 0.12 ? 8 : return20d > 0.25 ? -15 : return20d < -0.18 ? -8 : 0;
    buyScore += assetClass === 'growth' && return60d > 0 && return60d < 0.35 ? 8 : 0;

    overboughtScore += pricePosition52w > 0.95 ? 45 : pricePosition52w > 0.85 ? 30 : pricePosition52w > 0.75 ? 15 : 0;
    overboughtScore += return20d > 0.25 ? 35 : return20d > 0.15 ? 20 : return20d > 0.08 ? 10 : 0;
    overboughtScore += spreadPercent > 0.5 ? 10 : 0;

    reasons.push(`Позиция в 52-недельном диапазоне: ${formatPercent(pricePosition52w)}.`);
    reasons.push(`20-дневная динамика: ${formatPercent(return20d)}.`);
    if (turnover) reasons.push(`Оборот за день около ${roundMoney(turnover).toLocaleString('ru-RU')} ₽.`);
  }

  if (overboughtScore >= 70) risks.push('Есть признаки перекупленности, покупку лучше не разгонять.');
  if (spreadPercent > 0.5) risks.push('Широкий спред ухудшает цену входа/выхода.');
  if (assetClass === 'growth') risks.push('Ростовая часть ограничена 10% из-за повышенного риска.');

  buyScore = Math.round(clamp(buyScore, 0, 100));
  overboughtScore = Math.round(clamp(overboughtScore, 0, 100));

  return {
    buyScore,
    sellScore: Math.round(clamp(overboughtScore + (100 - buyScore) * 0.25, 0, 100)),
    overboughtScore,
    summary: reasons[0] || 'Оценка построена по данным рынка MOEX ISS.',
    reasons,
    risks
  };
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 1000) / 10}%`;
}

module.exports = {
  RUB,
  DEFAULT_COMMISSION_RATE,
  TARGET_ALLOCATION,
  BUILD_ORDER,
  MARKET_UNIVERSE,
  FALLBACK_INSTRUMENTS,
  buildPortfolio,
  buildPositions,
  calculateCash,
  classifyInstrument,
  findBuildPhase,
  findInstrument,
  getUniverseTickers,
  normalizeSettings,
  normalizeTicker,
  scoreInstrument,
  tradeCashImpact,
  validateCashDeposit,
  validateSettings,
  validateTransaction
};
