'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildPortfolio,
  buildPositions,
  calculateCash,
  classifyInstrument,
  scoreInstrument,
  tradeCashImpact,
  validateSettings,
  validateTransaction
} = require('../src/portfolio');

const settings = { commissionRate: 0.0006 };

test('cash balance accounts for broker commission on buy and sell', () => {
  const buy = tx({ type: 'buy', ticker: 'SBER', quantity: 10, price: 300 });
  const sell = tx({ type: 'sell', ticker: 'SBER', quantity: 2, price: 350 });
  const cash = calculateCash([{ type: 'deposit', amount: 10000 }], [buy, sell], settings);

  assert.equal(tradeCashImpact(buy, settings).total, 3001.8);
  assert.equal(tradeCashImpact(sell, settings).total, 699.58);
  assert.equal(cash.balance, 7697.78);
});

test('buildPositions includes buy commission in cost basis', () => {
  const positions = buildPositions(
    [
      tx({ ticker: 'SBER', quantity: 10, price: 250 }),
      tx({ ticker: 'SBER', quantity: 10, price: 350 }),
      tx({ type: 'sell', ticker: 'SBER', quantity: 5, price: 360 })
    ],
    {
      SBER: { price: 400, currency: 'RUB', asOf: '2026-01-01T00:00:00.000Z', source: 'test' }
    },
    settings
  );

  assert.equal(positions.length, 1);
  assert.equal(positions[0].quantity, 15);
  assert.equal(positions[0].averagePrice, 300.18);
  assert.equal(positions[0].marketValue, 6000);
  assert.equal(positions[0].unrealizedPnl, 1497.3);
});

test('new cash recommends the best blue chip candidate first', () => {
  const portfolio = buildPortfolio(
    [],
    {
      SBER: quoted('SBER', 'blue_chips', { buyScore: 88, overboughtScore: 10 }),
      GAZP: quoted('GAZP', 'blue_chips', { buyScore: 55, overboughtScore: 20 })
    },
    settings,
    [{ type: 'deposit', amount: 5000 }]
  );

  assert.equal(portfolio.cash.balance, 5000);
  assert.equal(portfolio.recommendations.at(-1).action, 'buy');
  assert.equal(portfolio.recommendations.at(-1).phase, 'blue_chips');
  assert.equal(portfolio.recommendations.at(-1).candidates[0].symbol, 'SBER');
});

test('overweight and overbought positions produce a sell idea', () => {
  const portfolio = buildPortfolio(
    [tx({ ticker: 'SBER', quantity: 20, price: 300 })],
    {
      SBER: quoted('SBER', 'blue_chips', { buyScore: 25, overboughtScore: 85 }, 400)
    },
    settings,
    [{ type: 'deposit', amount: 7000 }]
  );

  assert.ok(portfolio.recommendations.some((item) => item.action === 'sell' && item.candidates[0].symbol === 'SBER'));
});

test('classifyInstrument separates bonds, blue chips and growth shares', () => {
  assert.equal(classifyInstrument({ symbol: 'SU26243RMFS4', market: 'bonds' }), 'bonds');
  assert.equal(classifyInstrument({ symbol: 'SBER', market: 'shares' }, ['SBER']), 'blue_chips');
  assert.equal(classifyInstrument({ symbol: 'WUSH', market: 'shares' }, ['SBER']), 'growth');
});

test('scoreInstrument penalizes overbought shares', () => {
  const score = scoreInstrument({
    symbol: 'TEST',
    assetClass: 'growth',
    market: 'shares',
    pricePosition52w: 0.97,
    return20d: 0.3,
    turnover: 1_000_000,
    spreadPercent: 0.01,
    listLevel: 1
  });

  assert.ok(score.overboughtScore >= 70);
  assert.ok(score.buyScore < 60);
});

test('settings and transaction validation enforce RUB MOEX workflow', () => {
  const invalidSettings = validateSettings({ commissionRate: -1 });
  const invalidTransaction = validateTransaction({ ticker: 'AAPL', quantity: 1, price: 100, currency: 'USD' });

  assert.equal(invalidSettings.valid, false);
  assert.equal(invalidTransaction.valid, false);
  assert.ok(invalidTransaction.errors.includes('Тикер должен быть найден на Московской бирже.'));
  assert.ok(invalidTransaction.errors.includes('Сейчас поддерживается только рублевая торговля на Мосбирже.'));
});

function tx(overrides = {}) {
  return {
    id: `test-${Math.random()}`,
    type: 'buy',
    ticker: 'SBER',
    name: 'Сбербанк',
    assetClass: 'blue_chips',
    quantity: 1,
    price: 100,
    currency: 'RUB',
    date: '2026-01-01',
    notes: '',
    createdAt: '2026-01-01T00:00:00.000Z',
    moexVerified: true,
    ...overrides
  };
}

function quoted(symbol, assetClass, analysis, price = 300) {
  return {
    symbol,
    name: symbol,
    assetClass,
    price,
    lotSize: 1,
    lotCost: price,
    source: 'test',
    asOf: '2026-01-01T00:00:00.000Z',
    analysis
  };
}
