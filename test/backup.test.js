'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const test = require('node:test');
const { spawn } = require('node:child_process');

process.env.PORTFOLIO_STORE_FILE = path.join(__dirname, '..', 'data', 'backup-api-test.sqlite');

const {
  BACKUP_FORMAT,
  BACKUP_VERSION,
  backupFileName,
  createPortfolioBackup,
  parsePortfolioBackup
} = require('../src/backup');
const { server } = require('../server');

const storePath = process.env.PORTFOLIO_STORE_FILE;
const backupPath = path.join(__dirname, '..', 'data', 'test-cloud-backup.json');
const cliStorePath = path.join(__dirname, '..', 'data', 'backup-cli-test.sqlite');

async function removeStore(filePath) {
  await fs.rm(filePath, { force: true });
  await fs.rm(filePath + '-wal', { force: true });
  await fs.rm(filePath + '-shm', { force: true });
}

test('backup helpers validate portable portfolio snapshots', () => {
  const backup = createPortfolioBackup({
    email: 'Trader@Example.com',
    name: 'Trader',
    portfolio: {
      cashMovements: [{ id: 'c1', type: 'deposit', amount: 10000 }],
      transactions: [{ id: 't1', type: 'buy', ticker: 'SBER', quantity: 10, price: 250 }],
      quotes: { SBER: { last: 251 } },
      blueChipTickers: ['SBER'],
      settings: { commissionRate: 0.0006, vkUserId: '1' }
    }
  });

  assert.equal(backup.format, BACKUP_FORMAT);
  assert.equal(backup.version, BACKUP_VERSION);
  assert.equal(backup.email, 'trader@example.com');
  assert.match(backupFileName(backup.email), /^moex-portfolio-trader_example\.com-\d{4}-\d{2}-\d{2}\.json$/);

  const parsed = parsePortfolioBackup(backup);
  assert.equal(parsed.valid, true);
  assert.equal(parsed.value.portfolio.transactions[0].ticker, 'SBER');

  const invalid = parsePortfolioBackup({ format: 'other', version: 1, portfolio: {} });
  assert.equal(invalid.valid, false);
  assert.ok(invalid.errors.some((error) => error.includes('формат')));
});

test('API export/import moves portfolio from one session to another', async () => {
  await removeStore(storePath);
  const base = await listen();

  try {
    const sourceCookie = await register(base, 'cloud@example.com', 'Cloud');
    const targetCookie = await register(base, 'pc@example.com', 'PC');

    const deposit = await fetch(`${base}/api/cash/deposits`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', cookie: sourceCookie },
      body: JSON.stringify({ amount: 75000, date: '2026-08-01', notes: 'cloud deposit' })
    });
    assert.equal(deposit.status, 201);

    const exported = await fetch(`${base}/api/backup/export`, {
      headers: { cookie: sourceCookie }
    });
    assert.equal(exported.status, 200);
    const backup = await exported.json();
    assert.equal(backup.format, BACKUP_FORMAT);
    assert.equal(backup.portfolio.cashMovements[0].amount, 75000);
    assert.equal(Boolean(backup.passwordHash), false);

    const imported = await fetch(`${base}/api/backup/import`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', cookie: targetCookie },
      body: JSON.stringify({ backup })
    });
    assert.equal(imported.status, 200);
    const importResult = await imported.json();
    assert.equal(importResult.cashMovements, 1);

    const portfolio = await fetch(`${base}/api/portfolio`, {
      headers: { cookie: targetCookie }
    });
    assert.equal(portfolio.status, 200);
    const body = await portfolio.json();
    assert.equal(body.cash.balance, 75000);
    assert.equal(body.cashMovements[0].amount, 75000);
  } finally {
    await closeServer();
    await removeStore(storePath);
  }
});

test('CLI import writes portable backup into local sqlite', async () => {
  await removeStore(cliStorePath);
  await fs.rm(backupPath, { force: true });
  await fs.mkdir(path.dirname(backupPath), { recursive: true });

  const backup = createPortfolioBackup({
    email: 'cli@example.com',
    name: 'CLI User',
    portfolio: {
      cashMovements: [{ id: 'c_cli', type: 'deposit', amount: 12345, date: '2026-08-10' }],
      transactions: [],
      quotes: {},
      blueChipTickers: [],
      settings: { commissionRate: 0.0006 }
    }
  });
  await fs.writeFile(backupPath, JSON.stringify(backup, null, 2));

  await runNode([
    'scripts/cloud-to-pc.js',
    'import',
    '-i',
    backupPath,
    '--email',
    'cli@example.com',
    '--name',
    'CLI User',
    '--password',
    'password-123'
  ], { PORTFOLIO_STORE_FILE: cliStorePath });

  const Database = require('better-sqlite3');
  const database = new Database(cliStorePath, { readonly: true });
  const row = database.prepare('SELECT email, portfolio_json FROM users WHERE email = ?').get('cli@example.com');
  database.close();

  assert.ok(row);
  const portfolio = JSON.parse(row.portfolio_json);
  assert.equal(portfolio.cashMovements[0].amount, 12345);

  await removeStore(cliStorePath);
  await fs.rm(backupPath, { force: true });
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

function runNode(args, env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, {
      cwd: path.join(__dirname, '..'),
      env: { ...process.env, DATABASE_URL: '', ...env },
      stdio: ['ignore', 'pipe', 'pipe']
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('close', (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(stderr || stdout || `exit ${code}`));
    });
  });
}
