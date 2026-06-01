'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildPortfolio,
  buildPositions,
  calculateCash,
  findBuildPhase,
  validateTransaction
} = require('../src/portfolio');

test('cash balance increases on deposit and decreases on buy', () => {
  const cash = calculateCash(
    [{ type: 'deposit', amount: 10000 }],
    [tx({ ticker: 'SBER', quantity: 10, price: 300 })]
  );

  assert.equal(cash.deposited, 10000);
  assert.equal(cash.balance, 7000);
});

test('buildPositions calculates weighted cost basis after a partial sale', () => {
  const positions = buildPositions(
    [
      tx({ ticker: 'SBER', quantity: 10, price: 250 }),
      tx({ ticker: 'SBER', quantity: 10, price: 350 }),
      tx({ type: 'sell', ticker: 'SBER', quantity: 5, price: 360 })
    ],
    {
      SBER: { price: 400, currency: 'RUB', asOf: '2026-01-01T00:00:00.000Z', source: 'test' }
    }
  );

  assert.equal(positions.length, 1);
  assert.equal(positions[0].quantity, 15);
  assert.equal(positions[0].averagePrice, 300);
  assert.equal(positions[0].costBasis, 4500);
  assert.equal(positions[0].marketValue, 6000);
  assert.equal(positions[0].unrealizedPnl, 1500);
});

test('new cash recommends the blue chip phase first', () => {
  const portfolio = buildPortfolio([], {}, undefined, [{ type: 'deposit', amount: 5000 }]);

  assert.equal(portfolio.cash.balance, 5000);
  assert.equal(portfolio.recommendations[0].action, 'buy');
  assert.equal(portfolio.recommendations[0].phase, 'blue_chips');
  assert.equal(portfolio.recommendations[0].candidates[0].symbol, 'SBER');
});

test('after blue chip target is filled, the next phase is bonds', () => {
  const portfolio = buildPortfolio(
    [tx({ ticker: 'SBER', quantity: 20, price: 350 })],
    { SBER: { price: 350, currency: 'RUB', asOf: '2026-01-01T00:00:00.000Z', source: 'test' } },
    undefined,
    [{ type: 'deposit', amount: 10000 }]
  );

  assert.equal(portfolio.cash.balance, 3000);
  assert.equal(findBuildPhase(portfolio.allocation, portfolio.totals.assetsWithCash), 'bonds');
  assert.equal(portfolio.recommendations[0].phase, 'bonds');
  assert.equal(portfolio.recommendations[0].candidates[0].symbol, 'SU26243RMFS4');
});

test('validateTransaction rejects unsupported non-MOEX tickers and foreign currency', () => {
  const result = validateTransaction({ ticker: 'AAPL', quantity: 1, price: 100, currency: 'USD' });

  assert.equal(result.valid, false);
  assert.ok(result.errors.includes('Тикер должен быть из списка инструментов Мосбиржи в приложении.'));
  assert.ok(result.errors.includes('Сейчас поддерживается только рублевая торговля на Мосбирже.'));
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
    ...overrides
  };
}
