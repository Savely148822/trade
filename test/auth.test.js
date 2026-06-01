'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const test = require('node:test');

const { server } = require('../server');

const storePath = path.join(__dirname, '..', 'data', 'service.json');

test('service auth protects portfolio data per user', async () => {
  await fs.rm(storePath, { force: true });
  const base = await listen();

  try {
    const unauthorized = await fetch(`${base}/api/cash/deposits`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ amount: 1000 })
    });
    assert.equal(unauthorized.status, 401);

    const firstCookie = await register(base, 'first@example.com', 'Первый');
    const secondCookie = await register(base, 'second@example.com', 'Второй');

    const firstDeposit = await deposit(base, firstCookie, 5000);
    const secondDeposit = await deposit(base, secondCookie, 12000);
    assert.equal(firstDeposit.status, 201);
    assert.equal(secondDeposit.status, 201);

    const raw = await fs.readFile(storePath, 'utf8');
    const store = JSON.parse(raw);
    const first = store.users.find((user) => user.email === 'first@example.com');
    const second = store.users.find((user) => user.email === 'second@example.com');

    assert.equal(first.portfolio.cashMovements[0].amount, 5000);
    assert.equal(second.portfolio.cashMovements[0].amount, 12000);
  } finally {
    await closeServer();
    await fs.rm(storePath, { force: true });
  }
});

async function listen() {
  await new Promise((resolve) => server.listen(0, resolve));
  return `http://127.0.0.1:${server.address().port}`;
}

async function closeServer() {
  if (!server.listening) return;
  await new Promise((resolve) => server.close(resolve));
}

async function register(base, email, name) {
  const response = await fetch(`${base}/api/auth/register`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, name, password: 'password-123' })
  });

  assert.equal(response.status, 201);
  return response.headers.get('set-cookie').split(';')[0];
}

function deposit(base, cookie, amount) {
  return fetch(`${base}/api/cash/deposits`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      cookie
    },
    body: JSON.stringify({ amount, date: '2026-01-01' })
  });
}
