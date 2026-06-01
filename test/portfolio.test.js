'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { buildPortfolio, buildPositions, validateTransaction } = require('../src/portfolio');

test('buildPositions calculates weighted cost basis after a partial sale', () => {
  const positions = buildPositions(
    [
      tx({ ticker: 'AAPL', quantity: 10, price: 100 }),
      tx({ ticker: 'AAPL', quantity: 10, price: 200 }),
      tx({ type: 'sell', ticker: 'AAPL', quantity: 5, price: 220 })
    ],
    {
      AAPL: { price: 250, currency: 'USD', asOf: '2026-01-01T00:00:00.000Z', source: 'test' }
    }
  );

  assert.equal(positions.length, 1);
  assert.equal(positions[0].quantity, 15);
  assert.equal(positions[0].averagePrice, 150);
  assert.equal(positions[0].costBasis, 2250);
  assert.equal(positions[0].marketValue, 3750);
  assert.equal(positions[0].unrealizedPnl, 1500);
});

test('buildPortfolio recommends buying bonds when defensive allocation is under target', () => {
  const portfolio = buildPortfolio(
    [
      tx({ ticker: 'MSFT', assetClass: 'blue_chips', quantity: 9, price: 100 }),
      tx({ ticker: 'NVDA', assetClass: 'growth', quantity: 1, price: 100 })
    ],
    {
      MSFT: { price: 100, currency: 'USD', asOf: '2026-01-01T00:00:00.000Z', source: 'test' },
      NVDA: { price: 100, currency: 'USD', asOf: '2026-01-01T00:00:00.000Z', source: 'test' }
    }
  );

  assert.equal(portfolio.totals.value, 1000);
  assert.ok(portfolio.recommendations.some((item) => item.action === 'buy' && item.assetClass === 'bonds'));
});

test('validateTransaction rejects missing ticker and invalid numbers', () => {
  const result = validateTransaction({ ticker: '', quantity: 0, price: -1, currency: 'USD' });

  assert.equal(result.valid, false);
  assert.ok(result.errors.includes('Укажите тикер.'));
  assert.ok(result.errors.includes('Количество должно быть больше 0.'));
  assert.ok(result.errors.includes('Цена должна быть больше 0.'));
});

function tx(overrides = {}) {
  return {
    id: `test-${Math.random()}`,
    type: 'buy',
    ticker: 'AAPL',
    name: '',
    assetClass: 'blue_chips',
    quantity: 1,
    price: 100,
    currency: 'USD',
    date: '2026-01-01',
    notes: '',
    createdAt: '2026-01-01T00:00:00.000Z',
    ...overrides
  };
}
