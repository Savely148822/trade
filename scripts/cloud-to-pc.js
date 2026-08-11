#!/usr/bin/env node
'use strict';

/**
 * Перенос портфеля с облака/VPS (PostgreSQL) на локальный ПК (SQLite).
 *
 * Экспорт с VPS:
 *   DATABASE_URL=postgres://... node scripts/cloud-to-pc.js export --email you@example.com -o backup.json
 *
 * Импорт на ПК (без DATABASE_URL):
 *   node scripts/cloud-to-pc.js import -i backup.json --email you@example.com --name "Вы" --password "********"
 *
 * Если пользователь уже есть локально — portfolio будет заменён, пароль не меняется.
 * Если пользователя нет — создаётся новый аккаунт (нужны --name и --password).
 */

const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const Database = require('better-sqlite3');
const { Pool } = require('pg');
const { createPortfolioBackup, parsePortfolioBackup } = require('../src/backup');

const ROOT = path.join(__dirname, '..');
const STORE_FILE = process.env.PORTFOLIO_STORE_FILE
  ? path.resolve(process.env.PORTFOLIO_STORE_FILE)
  : path.join(ROOT, 'data', 'service.sqlite');
const DATABASE_URL = process.env.DATABASE_URL || '';

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.command || args.help) {
    printHelp();
    process.exit(args.help ? 0 : 1);
  }

  if (args.command === 'export') {
    await exportBackup(args);
    return;
  }

  if (args.command === 'import') {
    await importBackup(args);
    return;
  }

  printHelp();
  process.exit(1);
}

async function exportBackup(args) {
  const email = normalizeEmail(args.email);
  if (!email) throw new Error('Укажите --email для экспорта.');
  if (!args.output) throw new Error('Укажите -o/--output путь к файлу бэкапа.');

  const store = await loadStore();
  const user = store.users.find((item) => item.email === email);
  if (!user) throw new Error(`Пользователь ${email} не найден в источнике данных.`);

  const backup = createPortfolioBackup({
    email: user.email,
    name: user.name,
    portfolio: user.portfolio
  });

  await fs.mkdir(path.dirname(path.resolve(args.output)), { recursive: true });
  await fs.writeFile(path.resolve(args.output), JSON.stringify(backup, null, 2) + '\n', 'utf8');
  console.log(`Экспортировано в ${path.resolve(args.output)}`);
  console.log(`Источник: ${DATABASE_URL ? 'PostgreSQL (DATABASE_URL)' : 'локальный SQLite'}`);
  console.log(`Сделок: ${backup.portfolio.transactions.length}, движений кэша: ${backup.portfolio.cashMovements.length}`);
}

async function importBackup(args) {
  if (DATABASE_URL) {
    throw new Error('Импорт на ПК рассчитан на локальный SQLite. Уберите DATABASE_URL из окружения.');
  }

  const email = normalizeEmail(args.email);
  if (!email) throw new Error('Укажите --email аккаунта на ПК.');
  if (!args.input) throw new Error('Укажите -i/--input путь к файлу бэкапа.');

  const raw = await fs.readFile(path.resolve(args.input), 'utf8');
  const parsed = parsePortfolioBackup(raw);
  if (!parsed.valid) throw new Error(parsed.errors.join(' '));

  const store = await loadStore();
  let user = store.users.find((item) => item.email === email);

  if (!user) {
    const name = String(args.name || parsed.value.name || '').trim();
    const password = String(args.password || '');
    if (!name) throw new Error('Пользователь не найден. Укажите --name для создания аккаунта.');
    if (password.length < 8) throw new Error('Пользователь не найден. Укажите --password (мин. 8 символов).');

    const hashed = hashPassword(password);
    user = {
      id: 'usr_' + crypto.randomBytes(12).toString('hex'),
      email,
      name,
      passwordHash: hashed.hash,
      passwordSalt: hashed.salt,
      createdAt: new Date().toISOString(),
      portfolio: parsed.value.portfolio
    };
    store.users.push(user);
    console.log(`Создан локальный аккаунт ${email}`);
  } else {
    user.portfolio = parsed.value.portfolio;
    console.log(`Обновлён портфель локального аккаунта ${email}`);
  }

  await saveSqliteStore(store);
  console.log(`Импортировано в ${STORE_FILE}`);
  console.log(`Сделок: ${user.portfolio.transactions.length}, движений кэша: ${user.portfolio.cashMovements.length}`);
}

async function loadStore() {
  if (DATABASE_URL) return loadPostgresStore();
  return loadSqliteStore();
}

async function loadSqliteStore() {
  await fs.mkdir(path.dirname(STORE_FILE), { recursive: true });
  const database = new Database(STORE_FILE);
  try {
    database.exec(
      'CREATE TABLE IF NOT EXISTS users (' +
        'id TEXT PRIMARY KEY, ' +
        'email TEXT NOT NULL UNIQUE, ' +
        'name TEXT NOT NULL, ' +
        'password_hash TEXT NOT NULL, ' +
        'password_salt TEXT NOT NULL, ' +
        'created_at TEXT NOT NULL, ' +
        'portfolio_json TEXT NOT NULL' +
      ')'
    );
    const rows = database.prepare(
      'SELECT id, email, name, password_hash, password_salt, created_at, portfolio_json FROM users ORDER BY created_at'
    ).all();
    return { users: rows.map(rowToUser) };
  } finally {
    database.close();
  }
}

async function saveSqliteStore(store) {
  await fs.mkdir(path.dirname(STORE_FILE), { recursive: true });
  const database = new Database(STORE_FILE);
  try {
    database.exec(
      'CREATE TABLE IF NOT EXISTS users (' +
        'id TEXT PRIMARY KEY, ' +
        'email TEXT NOT NULL UNIQUE, ' +
        'name TEXT NOT NULL, ' +
        'password_hash TEXT NOT NULL, ' +
        'password_salt TEXT NOT NULL, ' +
        'created_at TEXT NOT NULL, ' +
        'portfolio_json TEXT NOT NULL' +
      ')'
    );
    const upsert = database.prepare(
      'INSERT INTO users (id, email, name, password_hash, password_salt, created_at, portfolio_json) VALUES (@id, @email, @name, @passwordHash, @passwordSalt, @createdAt, @portfolioJson) ' +
      'ON CONFLICT(id) DO UPDATE SET email = excluded.email, name = excluded.name, password_hash = excluded.password_hash, password_salt = excluded.password_salt, portfolio_json = excluded.portfolio_json'
    );
    const write = database.transaction((users) => {
      for (const user of users) {
        upsert.run({
          id: user.id,
          email: user.email,
          name: user.name,
          passwordHash: user.passwordHash,
          passwordSalt: user.passwordSalt,
          createdAt: user.createdAt,
          portfolioJson: JSON.stringify(user.portfolio || {})
        });
      }
    });
    write(store.users || []);
  } finally {
    database.close();
  }
}

async function loadPostgresStore() {
  const pool = new Pool({
    connectionString: DATABASE_URL,
    ssl: process.env.PGSSLMODE === 'disable'
      ? false
      : process.env.NODE_ENV === 'production'
        ? { rejectUnauthorized: false }
        : false
  });

  try {
    const result = await pool.query(
      'SELECT id, email, name, password_hash, password_salt, created_at, portfolio_json FROM users ORDER BY created_at'
    );
    return { users: result.rows.map(rowToUser) };
  } finally {
    await pool.end();
  }
}

function rowToUser(row) {
  return {
    id: row.id,
    email: normalizeEmail(row.email),
    name: String(row.name || '').trim(),
    passwordHash: row.password_hash,
    passwordSalt: row.password_salt,
    createdAt: row.created_at,
    portfolio: typeof row.portfolio_json === 'string'
      ? safeJsonParse(row.portfolio_json, {})
      : row.portfolio_json || {}
  };
}

function hashPassword(password, salt = crypto.randomBytes(16).toString('hex')) {
  const hash = crypto.scryptSync(password, salt, 64).toString('hex');
  return { salt, hash };
}

function normalizeEmail(email) {
  return String(email || '').trim().toLowerCase();
}

function safeJsonParse(value, fallback) {
  try {
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

function parseArgs(argv) {
  const args = { command: '', help: false, email: '', name: '', password: '', input: '', output: '' };
  if (!argv.length) return args;
  args.command = argv[0];

  for (let i = 1; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--help' || token === '-h') args.help = true;
    else if (token === '--email') args.email = argv[++i] || '';
    else if (token === '--name') args.name = argv[++i] || '';
    else if (token === '--password') args.password = argv[++i] || '';
    else if (token === '-i' || token === '--input') args.input = argv[++i] || '';
    else if (token === '-o' || token === '--output') args.output = argv[++i] || '';
    else throw new Error(`Неизвестный аргумент: ${token}`);
  }

  return args;
}

function printHelp() {
  console.log(`Использование:
  node scripts/cloud-to-pc.js export --email you@example.com -o backup.json
  node scripts/cloud-to-pc.js import -i backup.json --email you@example.com [--name "Имя" --password "********"]

Экспорт читает DATABASE_URL (PostgreSQL) или локальный data/service.sqlite.
Импорт пишет только в локальный SQLite и требует отсутствия DATABASE_URL.`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
