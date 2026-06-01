'use strict';

const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const crypto = require('node:crypto');
const Database = require('better-sqlite3');
const { Pool } = require('pg');
const { URL } = require('node:url');

const {
  FALLBACK_INSTRUMENTS,
  MARKET_UNIVERSE,
  buildPortfolio,
  buildPositions,
  buildWithdrawalPlan,
  calculateCash,
  classifyInstrument,
  getUniverseTickers,
  normalizeSettings,
  normalizeTicker,
  scoreInstrument,
  tradeCashImpact,
  validateCashCorrection,
  validateCashDeposit,
  validateSettings,
  validateTransaction
} = require('./src/portfolio');

const PORT = Number(process.env.PORT || 3000);
const STORE_FILE = path.join(__dirname, 'data', 'service.sqlite');
const DATABASE_URL = process.env.DATABASE_URL || '';
const APP_SECRET = process.env.APP_SECRET || 'dev-secret-change-me';
const SESSION_COOKIE = 'portfolio_session';
const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const PUBLIC_DIR = path.join(__dirname, 'public');
const QUOTE_TTL_MS = 15 * 60 * 1000;
const HISTORY_TTL_MS = 12 * 60 * 60 * 1000;
const AUTH_RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000;
const AUTH_RATE_LIMIT_MAX = Number(process.env.AUTH_RATE_LIMIT_MAX || 20);
const VK_GROUP_TOKEN = process.env.VK_GROUP_TOKEN || '';
const NOTIFICATION_HOUR_UTC = Number(process.env.NOTIFICATION_HOUR_UTC || 7);
const authRateLimit = new Map();
let postgresPool = null;
let lastNotificationDate = '';

if (process.env.NODE_ENV === 'production' && (!process.env.APP_SECRET || APP_SECRET.length < 32 || APP_SECRET === 'dev-secret-change-me')) {
  throw new Error('APP_SECRET must be set to a long random value in production.');
}

const DEFAULT_PORTFOLIO = {
  cashMovements: [],
  transactions: [],
  quotes: {},
  blueChipTickers: [],
  settings: {
    commissionRate: 0.0006,
    accountType: 'iis3',
    iisOpenDate: '',
    claimedDeductionYears: [],
    incomeTaxRate: 0.13,
    iisMinYears: 5,
    iisProfitExemptionYears: 10,
    vkUserId: '',
    dailyNotifications: false
  }
};

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8'
};

function createDefaultPortfolio() {
  return structuredClone(DEFAULT_PORTFOLIO);
}

async function loadStore() {
  if (DATABASE_URL) return loadPostgresStore();

  const database = await openDatabase();
  try {
    const rows = database.prepare('SELECT id, email, name, password_hash, password_salt, created_at, portfolio_json FROM users ORDER BY created_at').all();
    return { users: rows.map(rowToUser) };
  } finally {
    database.close();
  }
}

async function saveStore(store) {
  if (DATABASE_URL) return savePostgresStore(store);

  const database = await openDatabase();
  try {
    const upsert = database.prepare(
      'INSERT INTO users (id, email, name, password_hash, password_salt, created_at, portfolio_json) VALUES (@id, @email, @name, @passwordHash, @passwordSalt, @createdAt, @portfolioJson) ' +
      'ON CONFLICT(id) DO UPDATE SET email = excluded.email, name = excluded.name, password_hash = excluded.password_hash, password_salt = excluded.password_salt, portfolio_json = excluded.portfolio_json'
    );
    const write = database.transaction((users) => {
      for (const user of users) {
        upsert.run(userToDbParams(user));
      }
    });
    write(store.users || []);
  } finally {
    database.close();
  }
}

async function loadPostgresStore() {
  const pool = await getPostgresPool();
  const result = await pool.query('SELECT id, email, name, password_hash, password_salt, created_at, portfolio_json FROM users ORDER BY created_at');
  return { users: result.rows.map(rowToUser) };
}

async function savePostgresStore(store) {
  const pool = await getPostgresPool();
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    for (const user of store.users || []) {
      const params = userToDbParams(user);
      await client.query(
        'INSERT INTO users (id, email, name, password_hash, password_salt, created_at, portfolio_json) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) ' +
        'ON CONFLICT(id) DO UPDATE SET email = excluded.email, name = excluded.name, password_hash = excluded.password_hash, password_salt = excluded.password_salt, portfolio_json = excluded.portfolio_json',
        [params.id, params.email, params.name, params.passwordHash, params.passwordSalt, params.createdAt, params.portfolioJson]
      );
    }
    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

async function getPostgresPool() {
  if (!postgresPool) {
    postgresPool = new Pool({
      connectionString: DATABASE_URL,
      ssl: process.env.PGSSLMODE === 'disable' ? false : process.env.NODE_ENV === 'production' ? { rejectUnauthorized: false } : false
    });
    await ensurePostgresSchema(postgresPool);
  }
  return postgresPool;
}

async function ensurePostgresSchema(pool) {
  await pool.query(
    'CREATE TABLE IF NOT EXISTS users (' +
      'id TEXT PRIMARY KEY, ' +
      'email TEXT NOT NULL UNIQUE, ' +
      'name TEXT NOT NULL, ' +
      'password_hash TEXT NOT NULL, ' +
      'password_salt TEXT NOT NULL, ' +
      'created_at TEXT NOT NULL, ' +
      'portfolio_json JSONB NOT NULL' +
    ')'
  );
}

async function openDatabase() {
  await fs.mkdir(path.dirname(STORE_FILE), { recursive: true });
  const database = new Database(STORE_FILE);
  database.pragma('journal_mode = WAL');
  database.pragma('foreign_keys = ON');
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
  return database;
}

function rowToUser(row) {
  return normalizeStoredUser({
    id: row.id,
    email: row.email,
    name: row.name,
    passwordHash: row.password_hash,
    passwordSalt: row.password_salt,
    createdAt: row.created_at,
    portfolio: typeof row.portfolio_json === 'string' ? safeJsonParse(row.portfolio_json, {}) : row.portfolio_json || {}
  });
}

function userToDbParams(user) {
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    passwordHash: user.passwordHash,
    passwordSalt: user.passwordSalt,
    createdAt: user.createdAt,
    portfolioJson: JSON.stringify(normalizePortfolio(user.portfolio))
  };
}

function safeJsonParse(value, fallback) {
  try { return value ? JSON.parse(value) : fallback; } catch { return fallback; }
}

function normalizeStoredUser(user) {
  return {
    id: user.id,
    email: normalizeEmail(user.email),
    name: String(user.name || '').trim(),
    passwordHash: user.passwordHash,
    passwordSalt: user.passwordSalt,
    createdAt: user.createdAt || new Date().toISOString(),
    portfolio: normalizePortfolio(user.portfolio || {})
  };
}

function normalizePortfolio(portfolio = {}) {
  return {
    ...createDefaultPortfolio(),
    ...portfolio,
    cashMovements: Array.isArray(portfolio.cashMovements) ? portfolio.cashMovements : [],
    transactions: Array.isArray(portfolio.transactions) ? portfolio.transactions : [],
    quotes: portfolio.quotes && typeof portfolio.quotes === 'object' ? portfolio.quotes : {},
    blueChipTickers: Array.isArray(portfolio.blueChipTickers) ? portfolio.blueChipTickers : [],
    settings: normalizeSettings(portfolio.settings || DEFAULT_PORTFOLIO.settings)
  };
}

function sanitizeUser(user) {
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    createdAt: user.createdAt
  };
}

function normalizeEmail(email) {
  return String(email || '').trim().toLowerCase();
}

function validateAuthInput(body, mode) {
  const errors = [];
  const email = normalizeEmail(body.email);
  const password = String(body.password || '');
  const name = String(body.name || '').trim();

  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) errors.push('Укажите корректный email.');
  if (password.length < 8) errors.push('Пароль должен быть не короче 8 символов.');
  if (mode === 'register' && !name) errors.push('Укажите имя.');

  return { valid: errors.length === 0, errors, email, password, name };
}

function hashPassword(password, salt = crypto.randomBytes(16).toString('hex')) {
  const hash = crypto.scryptSync(password, salt, 64).toString('hex');
  return { salt, hash };
}

function verifyPassword(password, salt, expectedHash) {
  const actual = Buffer.from(hashPassword(password, salt).hash, 'hex');
  const expected = Buffer.from(expectedHash || '', 'hex');
  return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
}

function createSessionToken(userId) {
  const payload = base64UrlEncode(JSON.stringify({ userId, exp: Date.now() + SESSION_TTL_MS }));
  const signature = crypto.createHmac('sha256', APP_SECRET).update(payload).digest('base64url');
  return payload + '.' + signature;
}

function verifySessionToken(token) {
  const [payload, signature] = String(token || '').split('.');
  if (!payload || !signature) return null;

  const expected = crypto.createHmac('sha256', APP_SECRET).update(payload).digest('base64url');
  if (!safeEqual(signature, expected)) return null;

  try {
    const session = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    if (!session.userId || Date.now() > session.exp) return null;
    return session;
  } catch {
    return null;
  }
}

function base64UrlEncode(value) {
  return Buffer.from(value).toString('base64url');
}

function safeEqual(a, b) {
  const left = Buffer.from(String(a));
  const right = Buffer.from(String(b));
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function parseCookies(request) {
  return Object.fromEntries(String(request.headers.cookie || '')
    .split(';')
    .map((cookie) => cookie.trim())
    .filter(Boolean)
    .map((cookie) => {
      const index = cookie.indexOf('=');
      return [decodeURIComponent(cookie.slice(0, index)), decodeURIComponent(cookie.slice(index + 1))];
    }));
}

function sessionCookie(token) {
  const secure = process.env.NODE_ENV === 'production' ? '; Secure' : '';
  return SESSION_COOKIE + '=' + encodeURIComponent(token) + '; HttpOnly; SameSite=Lax; Path=/; Max-Age=' + Math.floor(SESSION_TTL_MS / 1000) + secure;
}

function clearSessionCookie() {
  return SESSION_COOKIE + '=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0';
}

async function getAuthContext(request) {
  const store = await loadStore();
  const session = verifySessionToken(parseCookies(request)[SESSION_COOKIE]);
  const user = session ? store.users.find((item) => item.id === session.userId) : null;
  return { store, user };
}

async function requireAuth(request, response) {
  const context = await getAuthContext(request);
  if (!context.user) {
    sendJson(response, { error: 'Authentication required' }, 401);
    return null;
  }
  return context;
}

function getClientIp(request) {
  return String(request.headers['x-forwarded-for'] || request.socket.remoteAddress || 'unknown').split(',')[0].trim();
}

function checkAuthRateLimit(request, response) {
  const key = getClientIp(request) + ':' + request.url;
  const now = Date.now();
  const entry = authRateLimit.get(key) || { count: 0, resetAt: now + AUTH_RATE_LIMIT_WINDOW_MS };

  if (now > entry.resetAt) {
    entry.count = 0;
    entry.resetAt = now + AUTH_RATE_LIMIT_WINDOW_MS;
  }

  entry.count += 1;
  authRateLimit.set(key, entry);

  if (entry.count > AUTH_RATE_LIMIT_MAX) {
    sendJson(response, { error: 'Too many auth attempts. Try later.' }, 429);
    return false;
  }

  return true;
}

async function routeApi(request, response, url) {
  if (url.pathname.startsWith('/api/auth/')) {
    return routeAuth(request, response, url);
  }

  if (request.method === 'POST' && url.pathname === '/api/notifications/test') {
    const context = await requireAuth(request, response);
    if (!context) return;
    await hydrateMarketData(context.user.portfolio, true);
    await saveStore(context.store);
    const portfolio = buildPortfolio(context.user.portfolio.transactions, context.user.portfolio.quotes, context.user.portfolio.settings, context.user.portfolio.cashMovements);
    const vkUserId = context.user.portfolio.settings.vkUserId;
    if (!vkUserId) return sendJson(response, { errors: ['Укажите VK user id в настройках.'] }, 400);
    const result = await sendVkMessage(vkUserId, formatVkDailyMessage(context.user, portfolio.dailyAnalysis));
    return sendJson(response, { ok: true, result });
  }

  if (request.method === 'GET' && url.pathname === '/api/watchlist') {
    return sendJson(response, {
      universe: MARKET_UNIVERSE,
      instruments: FALLBACK_INSTRUMENTS
    });
  }

  const context = await requireAuth(request, response);
  if (!context) return;

  const data = context.user.portfolio;

  if (request.method === 'GET' && url.pathname === '/api/portfolio') {
    await hydrateMarketData(data, url.searchParams.get('refresh') === '1');
    await saveStore(context.store);
    return sendJson(response, buildPortfolio(data.transactions, data.quotes, data.settings, data.cashMovements));
  }

  if (request.method === 'GET' && url.pathname === '/api/daily-analysis') {
    await hydrateMarketData(data, url.searchParams.get('refresh') === '1');
    await saveStore(context.store);
    const portfolio = buildPortfolio(data.transactions, data.quotes, data.settings, data.cashMovements);
    return sendJson(response, portfolio.dailyAnalysis);
  }

  if (request.method === 'POST' && url.pathname === '/api/settings') {
    const body = await readJsonBody(request);
    const validation = validateSettings(body);

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    data.settings = validation.value;
    await saveStore(context.store);
    return sendJson(response, { settings: data.settings });
  }

  if (request.method === 'POST' && url.pathname === '/api/withdrawal-plan') {
    const body = await readJsonBody(request);
    await hydrateMarketData(data, body.refresh === true);
    await saveStore(context.store);
    const portfolio = buildPortfolio(data.transactions, data.quotes, data.settings, data.cashMovements);
    const plan = buildWithdrawalPlan({
      amount: body.amount,
      positions: portfolio.positions,
      quotes: data.quotes,
      allocation: portfolio.allocation,
      cash: portfolio.cash,
      settings: data.settings,
      iisSummary: portfolio.iis,
      cashMovements: data.cashMovements
    });
    return sendJson(response, { plan });
  }

  if (request.method === 'POST' && url.pathname === '/api/cash/deposits') {
    const body = await readJsonBody(request);
    const validation = validateCashDeposit(body);

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    data.cashMovements.push(validation.value);
    await saveStore(context.store);
    return sendJson(response, { cashMovement: validation.value }, 201);
  }

  if (request.method === 'POST' && url.pathname === '/api/cash/balance-correction') {
    const body = await readJsonBody(request);
    const validation = validateCashCorrection(body);

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    const cash = calculateCash(data.cashMovements, data.transactions, data.settings);
    const targetBalance = validation.value.amount;
    const delta = Math.round((targetBalance - cash.balance + Number.EPSILON) * 100) / 100;
    const correction = {
      id: 'cash_' + Date.now().toString(36) + '_' + crypto.randomBytes(3).toString('hex'),
      type: 'adjustment',
      amount: delta,
      targetBalance,
      previousBalance: cash.balance,
      currency: 'RUB',
      date: validation.value.date,
      notes: validation.value.notes || 'Ручная корректировка доступного кэша',
      createdAt: new Date().toISOString()
    };
    data.cashMovements.push(correction);
    await saveStore(context.store);
    return sendJson(response, { cashMovement: correction }, 201);
  }

  if (request.method === 'POST' && url.pathname === '/api/transactions') {
    const body = await readJsonBody(request);
    const instrument = await fetchMoexInstrument(normalizeTicker(body.ticker), data.blueChipTickers);
    const enrichedBody = { ...body };
    const providedPrice = Number(enrichedBody.price);

    if (!Number.isFinite(providedPrice) || providedPrice <= 0) {
      const approximate = await fetchMoexApproxPriceForDate(instrument, enrichedBody.date);
      enrichedBody.price = approximate.price;
      enrichedBody.priceSource = approximate.source;
    } else {
      enrichedBody.priceSource = 'manual';
    }

    const validation = validateTransaction({
      ...enrichedBody,
      moexVerified: true,
      name: instrument.name,
      assetClass: instrument.assetClass
    });

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    const positions = buildPositions(data.transactions, data.quotes, data.settings);
    const cash = calculateCash(data.cashMovements, data.transactions, data.settings);
    const impact = tradeCashImpact(validation.value, data.settings);

    if (validation.value.type === 'buy' && cash.balance + 0.000001 < impact.total) {
      return sendJson(response, { errors: ['Недостаточно рублей на свободном балансе с учетом комиссии брокера.'] }, 400);
    }

    if (validation.value.type === 'sell') {
      const existing = positions.find((position) => position.ticker === validation.value.ticker);

      if (!existing || existing.quantity < validation.value.quantity) {
        return sendJson(response, { errors: ['Нельзя продать больше, чем есть в портфеле.'] }, 400);
      }
    }

    data.quotes[instrument.symbol] = {
      ...(data.quotes[instrument.symbol] || {}),
      ...instrument,
      asOf: instrument.asOf || new Date().toISOString()
    };
    data.transactions.push(validation.value);
    await saveStore(context.store);
    return sendJson(response, { transaction: validation.value }, 201);
  }

  if (request.method === 'DELETE' && url.pathname.startsWith('/api/transactions/')) {
    const id = decodeURIComponent(url.pathname.replace('/api/transactions/', ''));
    const before = data.transactions.length;
    data.transactions = data.transactions.filter((transaction) => transaction.id !== id);
    await saveStore(context.store);
    return sendJson(response, { deleted: before !== data.transactions.length });
  }

  if (request.method === 'DELETE' && url.pathname.startsWith('/api/cash/deposits/')) {
    const id = decodeURIComponent(url.pathname.replace('/api/cash/deposits/', ''));
    const before = data.cashMovements.length;
    data.cashMovements = data.cashMovements.filter((movement) => movement.id !== id);
    await saveStore(context.store);
    return sendJson(response, { deleted: before !== data.cashMovements.length });
  }

  return sendJson(response, { error: 'API route not found' }, 404);
}

async function routeAuth(request, response, url) {
  if (request.method === 'GET' && url.pathname === '/api/auth/me') {
    const context = await getAuthContext(request);
    if (!context.user) return sendJson(response, { user: null }, 401);
    return sendJson(response, { user: sanitizeUser(context.user) });
  }

  if (request.method === 'POST' && url.pathname === '/api/auth/register') {
    if (!checkAuthRateLimit(request, response)) return;
    const body = await readJsonBody(request);
    const validation = validateAuthInput(body, 'register');

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    const store = await loadStore();
    if (store.users.some((user) => user.email === validation.email)) {
      return sendJson(response, { errors: ['Пользователь с таким email уже зарегистрирован.'] }, 409);
    }

    const password = hashPassword(validation.password);
    const user = normalizeStoredUser({
      id: 'usr_' + crypto.randomBytes(12).toString('hex'),
      email: validation.email,
      name: validation.name,
      passwordHash: password.hash,
      passwordSalt: password.salt,
      createdAt: new Date().toISOString(),
      portfolio: createDefaultPortfolio()
    });
    store.users.push(user);
    await saveStore(store);

    return sendJson(response, { user: sanitizeUser(user) }, 201, {
      'set-cookie': sessionCookie(createSessionToken(user.id))
    });
  }

  if (request.method === 'POST' && url.pathname === '/api/auth/login') {
    if (!checkAuthRateLimit(request, response)) return;
    const body = await readJsonBody(request);
    const validation = validateAuthInput(body, 'login');

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    const store = await loadStore();
    const user = store.users.find((item) => item.email === validation.email);

    if (!user || !verifyPassword(validation.password, user.passwordSalt, user.passwordHash)) {
      return sendJson(response, { errors: ['Неверный email или пароль.'] }, 401);
    }

    return sendJson(response, { user: sanitizeUser(user) }, 200, {
      'set-cookie': sessionCookie(createSessionToken(user.id))
    });
  }

  if (request.method === 'POST' && url.pathname === '/api/auth/logout') {
    return sendJson(response, { ok: true }, 200, {
      'set-cookie': clearSessionCookie()
    });
  }

  return sendJson(response, { error: 'Auth route not found' }, 404);
}

async function hydrateMarketData(data, forceRefresh = false) {
  data.quotes = data.quotes || {};
  data.settings = normalizeSettings(data.settings);

  if (forceRefresh || !data.blueChipTickers?.length) {
    data.blueChipTickers = await fetchBlueChipTickers().catch(() => data.blueChipTickers || []);
  }

  const positionTickers = buildPositions(data.transactions, data.quotes, data.settings).map((position) => position.ticker);
  const tickers = [...new Set([...getUniverseTickers(), ...positionTickers])];

  for (const ticker of tickers) {
    const cached = data.quotes[ticker];
    const quoteFresh = cached && Date.now() - new Date(cached.asOf || 0).getTime() < QUOTE_TTL_MS;
    const historyFresh = cached && Date.now() - new Date(cached.historyAsOf || 0).getTime() < HISTORY_TTL_MS;

    if (!forceRefresh && quoteFresh && historyFresh && cached.analysis) continue;

    try {
      const instrument = await fetchMoexInstrument(ticker, data.blueChipTickers);
      const history = historyFresh && cached.history ? cached.history : await fetchMoexHistory(instrument);
      const withHistory = {
        ...instrument,
        history,
        historyAsOf: new Date().toISOString()
      };
      data.quotes[ticker] = {
        ...withHistory,
        analysis: scoreInstrument(withHistory)
      };
    } catch (error) {
      const fallback = FALLBACK_INSTRUMENTS[ticker];
      data.quotes[ticker] = {
        ...(cached || {}),
        ...(fallback || { symbol: ticker, name: ticker }),
        price: cached?.price || fallback?.referencePrice || null,
        lotSize: cached?.lotSize || fallback?.lotSize || 1,
        lotCost: cached?.lotCost || fallback?.referencePrice || null,
        currency: 'RUB',
        error: error.message,
        source: cached?.source || 'fallback',
        asOf: cached?.asOf || new Date().toISOString(),
        analysis: cached?.analysis || scoreInstrument({ ...(fallback || {}), price: fallback?.referencePrice })
      };
    }
  }

  return data.quotes;
}

async function fetchBlueChipTickers() {
  const payload = await fetchJson('https://iss.moex.com/iss/statistics/engines/stock/markets/index/analytics/MOEXBC/tickers.json?iss.meta=off');
  const rows = tableRows(payload.tickers);
  const maxTill = rows
    .map((row) => row.till)
    .filter(Boolean)
    .sort()
    .at(-1);

  return rows
    .filter((row) => row.till === maxTill)
    .map((row) => normalizeTicker(row.ticker));
}

async function fetchMoexInstrument(ticker, blueChipTickers = []) {
  const symbol = normalizeTicker(ticker);
  if (!symbol) throw new Error('Ticker is required');

  const fallback = FALLBACK_INSTRUMENTS[symbol];
  const route = fallback || await discoverMoexRoute(symbol);
  const url = `https://iss.moex.com/iss/engines/stock/markets/${route.market}/boards/${route.board}/securities/${encodeURIComponent(symbol)}.json?iss.meta=off&iss.only=securities,marketdata`;
  const payload = await fetchJson(url);
  const security = tableRows(payload.securities)[0];
  const marketdata = tableRows(payload.marketdata)[0] || {};

  if (!security) throw new Error(`MOEX security not found: ${symbol}`);

  const rawPrice = firstNumber(
    marketdata.LAST,
    marketdata.LCURRENTPRICE,
    marketdata.MARKETPRICE2,
    marketdata.MARKETPRICE,
    security.PREVPRICE,
    security.PREVWAPRICE,
    fallback?.referencePrice
  );
  const faceValue = firstNumber(security.FACEVALUEONSETTLEDATE, security.FACEVALUE, 1000);
  const accruedInterest = firstNumber(security.ACCRUEDINT, 0);
  const isBond = route.market === 'bonds';
  const price = isBond ? roundMoney((rawPrice / 100) * faceValue + accruedInterest) : roundMoney(rawPrice);
  const lotSize = Number(security.LOTSIZE || fallback?.lotSize || 1);
  const bid = firstNumber(marketdata.BID, marketdata.LASTBID);
  const offer = firstNumber(marketdata.OFFER, marketdata.LASTOFFER);
  const spreadPercent = bid && offer && price ? (offer - bid) / price : 0;
  const historyless = {
    symbol,
    name: security.SECNAME || security.SHORTNAME || fallback?.name || symbol,
    market: route.market,
    board: route.board,
    assetClass: classifyInstrument({
      symbol,
      market: route.market,
      securityType: security.SECTYPE,
      sector: security.INSTRID,
      capitalization: marketdata.ISSUECAPITALIZATION
    }, blueChipTickers),
    price,
    lotSize,
    lotCost: roundMoney(price * lotSize),
    faceValue,
    previousPrice: firstNumber(security.PREVPRICE, security.PREVWAPRICE),
    changePercent: firstNumber(marketdata.LASTTOPREVPRICE, marketdata.WAPTOPREVWAPRICEPRCNT, 0) / 100,
    spreadPercent,
    turnover: firstNumber(marketdata.VALTODAY_RUR, marketdata.VALTODAY, 0),
    numTrades: firstNumber(marketdata.NUMTRADES, 0),
    capitalization: firstNumber(marketdata.ISSUECAPITALIZATION, 0),
    listLevel: Number(security.LISTLEVEL || fallback?.listLevel || 3),
    yield: firstNumber(marketdata.YIELD, security.YIELDATPREVWAPRICE, security.COUPONPERCENT, 0),
    duration: firstNumber(marketdata.DURATION, 0),
    couponPercent: firstNumber(security.COUPONPERCENT, 0),
    accruedInterest,
    maturityDate: security.MATDATE || null,
    currency: 'RUB',
    source: 'MOEX ISS',
    asOf: new Date().toISOString()
  };

  return {
    ...historyless,
    analysis: scoreInstrument(historyless)
  };
}

async function discoverMoexRoute(symbol) {
  const payload = await fetchJson(`https://iss.moex.com/iss/securities/${encodeURIComponent(symbol)}.json?iss.meta=off`);
  const boards = tableRows(payload.boards).filter((board) => board.is_traded);
  const preferred = boards.find((board) => board.market === 'shares' && board.boardid === 'TQBR')
    || boards.find((board) => board.market === 'bonds' && board.boardid === 'TQOB')
    || boards.find((board) => ['shares', 'bonds'].includes(board.market));

  if (!preferred) throw new Error(`MOEX route not found for ${symbol}`);

  return {
    market: preferred.market,
    board: preferred.boardid
  };
}

async function fetchMoexApproxPriceForDate(instrument, dateValue) {
  if (!instrument?.market || !instrument?.board) {
    throw new Error('Не удалось определить режим торгов MOEX для оценки цены по дате.');
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateValue || ''))) {
    throw new Error('Укажите цену вручную или выберите корректную дату сделки.');
  }

  const target = new Date(String(dateValue) + 'T00:00:00.000Z');
  const from = new Date(target);
  from.setUTCDate(from.getUTCDate() - 14);
  const till = new Date(target);
  till.setUTCDate(till.getUTCDate() + 3);

  const url = 'https://iss.moex.com/iss/engines/stock/markets/' + instrument.market +
    '/boards/' + instrument.board +
    '/securities/' + encodeURIComponent(instrument.symbol) +
    '/candles.json?iss.meta=off&from=' + from.toISOString().slice(0, 10) +
    '&till=' + till.toISOString().slice(0, 10) +
    '&interval=24';
  const payload = await fetchJson(url);
  const candles = tableRows(payload.candles)
    .map((candle) => ({
      ...candle,
      close: Number(candle.close),
      time: new Date(String(candle.begin).slice(0, 10) + 'T00:00:00.000Z').getTime()
    }))
    .filter((candle) => Number.isFinite(candle.close) && Number.isFinite(candle.time));

  if (!candles.length) {
    throw new Error('MOEX ISS не вернул историческую цену за выбранную дату. Укажите цену вручную.');
  }

  const targetTime = target.getTime();
  const previousOrSame = candles
    .filter((candle) => candle.time <= targetTime)
    .sort((a, b) => b.time - a.time)[0];
  const selected = previousOrSame || candles.sort((a, b) => Math.abs(a.time - targetTime) - Math.abs(b.time - targetTime))[0];
  const faceValue = Number(instrument.faceValue || 1000);
  const price = instrument.market === 'bonds'
    ? (selected.close / 100) * faceValue + Number(instrument.accruedInterest || 0)
    : selected.close;

  return {
    price: roundMoney(price),
    source: 'moex-history:' + String(selected.begin).slice(0, 10)
  };
}

async function fetchMoexHistory(instrument) {
  if (!instrument.market || !instrument.board) return [];

  const from = new Date();
  from.setDate(from.getDate() - 430);
  const fromDate = from.toISOString().slice(0, 10);
  const url = `https://iss.moex.com/iss/engines/stock/markets/${instrument.market}/boards/${instrument.board}/securities/${encodeURIComponent(instrument.symbol)}/candles.json?iss.meta=off&from=${fromDate}&interval=24`;
  const payload = await fetchJson(url);
  const candles = tableRows(payload.candles);
  const closes = candles.map((candle) => Number(candle.close)).filter(Number.isFinite);

  if (closes.length === 0) return [];

  const latestClose = closes.at(-1);
  const high52 = Math.max(...closes);
  const low52 = Math.min(...closes);
  const sma20 = average(closes.slice(-20));
  const sma50 = average(closes.slice(-50));
  const close20 = closes.length > 20 ? closes.at(-21) : closes[0];
  const close60 = closes.length > 60 ? closes.at(-61) : closes[0];
  const pricePosition52w = high52 > low52 ? (latestClose - low52) / (high52 - low52) : 0.5;

  Object.assign(instrument, {
    high52,
    low52,
    sma20,
    sma50,
    pricePosition52w,
    return20d: close20 ? latestClose / close20 - 1 : 0,
    return60d: close60 ? latestClose / close60 - 1 : 0
  });

  return candles.slice(-260);
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: {
      accept: 'application/json',
      'user-agent': 'lifetime-moex-portfolio-local-app/0.3'
    }
  });

  if (!response.ok) {
    throw new Error(`MOEX ISS request failed with HTTP ${response.status}`);
  }

  return response.json();
}

function tableRows(table) {
  if (!table?.columns || !table?.data) return [];

  return table.data.map((row) => Object.fromEntries(table.columns.map((column, index) => [column, row[index]])));
}

function firstNumber(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number) && number !== 0) return number;
  }

  return 0;
}

function roundMoney(value) {
  return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
}

function average(values) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function formatVkDailyMessage(user, analysis) {
  const lines = [
    'Ежедневный анализ портфеля',
    user.name ? 'Пользователь: ' + user.name : '',
    '',
    analysis.headline || '',
    analysis.portfolio?.explanation || '',
    ''
  ];

  if (analysis.actions?.buy) {
    lines.push('Докупить: ' + analysis.actions.buy.title);
  }

  for (const sell of analysis.actions?.sells || []) {
    lines.push('Сократить: ' + sell.title);
  }

  for (const tax of analysis.actions?.taxes || []) {
    lines.push('ИИС-3: ' + tax.title);
  }

  return lines.filter(Boolean).join('\n').slice(0, 3500);
}

async function sendVkMessage(userId, message) {
  if (!VK_GROUP_TOKEN || !userId) return { skipped: true };
  const params = new URLSearchParams({
    access_token: VK_GROUP_TOKEN,
    v: '5.199',
    user_id: String(userId),
    random_id: String(Date.now()),
    message
  });
  const response = await fetch('https://api.vk.com/method/messages.send', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: params
  });
  const payload = await response.json();
  if (payload.error) throw new Error('VK error: ' + payload.error.error_msg);
  return payload;
}

async function runDailyNotifications(force = false) {
  if (!VK_GROUP_TOKEN) return { sent: 0, skipped: 'VK_GROUP_TOKEN is not configured' };
  const now = new Date();
  const today = now.toISOString().slice(0, 10);

  if (!force && (now.getUTCHours() !== NOTIFICATION_HOUR_UTC || lastNotificationDate === today)) {
    return { sent: 0, skipped: 'not scheduled time' };
  }

  const store = await loadStore();
  let sent = 0;

  for (const user of store.users) {
    const vkUserId = user.portfolio?.settings?.vkUserId;
    if (!user.portfolio?.settings?.dailyNotifications || !vkUserId) continue;
    await hydrateMarketData(user.portfolio, false);
    const portfolio = buildPortfolio(user.portfolio.transactions, user.portfolio.quotes, user.portfolio.settings, user.portfolio.cashMovements);
    await sendVkMessage(vkUserId, formatVkDailyMessage(user, portfolio.dailyAnalysis));
    sent += 1;
  }

  await saveStore(store);
  lastNotificationDate = today;
  return { sent };
}

function startDailyNotifier() {
  if (!VK_GROUP_TOKEN) return;
  setInterval(() => {
    runDailyNotifications(false).catch((error) => console.error('Daily notification failed:', error));
  }, 15 * 60 * 1000).unref();
}

async function routeStatic(request, response, url) {
  const requestedPath = url.pathname === '/' ? '/index.html' : url.pathname;
  const safePath = path.normalize(decodeURIComponent(requestedPath)).replace(/^(\.\.[/\\])+/, '');
  const filePath = path.join(PUBLIC_DIR, safePath);

  if (!filePath.startsWith(PUBLIC_DIR)) {
    response.writeHead(403);
    response.end('Forbidden');
    return;
  }

  try {
    const content = await fs.readFile(filePath);
    response.writeHead(200, {
      'content-type': MIME_TYPES[path.extname(filePath)] || 'application/octet-stream'
    });
    response.end(content);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    response.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
    response.end('Not found');
  }
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    let body = '';
    request.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        request.destroy(new Error('Request body is too large'));
      }
    });
    request.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
    request.on('error', reject);
  });
}

function applySecurityHeaders(response) {
  response.setHeader('x-content-type-options', 'nosniff');
  response.setHeader('x-frame-options', 'DENY');
  response.setHeader('referrer-policy', 'strict-origin-when-cross-origin');
  response.setHeader('permissions-policy', 'camera=(), microphone=(), geolocation=()');
  response.setHeader('content-security-policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'");
  if (process.env.NODE_ENV === 'production') {
    response.setHeader('strict-transport-security', 'max-age=15552000; includeSubDomains');
  }
}

function sendJson(response, body, statusCode = 200, headers = {}) {
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    ...headers
  });
  response.end(JSON.stringify(body));
}

const server = http.createServer(async (request, response) => {
  applySecurityHeaders(response);
  try {
    const url = new URL(request.url, `http://${request.headers.host}`);

    if (url.pathname.startsWith('/api/')) {
      await routeApi(request, response, url);
      return;
    }

    await routeStatic(request, response, url);
  } catch (error) {
    console.error(error);
    sendJson(response, { error: error.message || 'Internal server error' }, 500);
  }
});

if (require.main === module) {
  server.listen(PORT, () => {
    console.log(`MOEX portfolio assistant is running at http://localhost:${PORT}`);
    startDailyNotifier();
  });
}

module.exports = {
  server,
  fetchBlueChipTickers,
  fetchMoexInstrument,
  fetchMoexApproxPriceForDate,
  fetchMoexHistory,
  hydrateMarketData,
  tableRows,
  formatVkDailyMessage,
  runDailyNotifications,
  sendVkMessage
};
