'use strict';

const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const crypto = require('node:crypto');
const Database = require('better-sqlite3');
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
  validateCashDeposit,
  validateSettings,
  validateTransaction
} = require('./src/portfolio');

const PORT = Number(process.env.PORT || 3000);
const STORE_FILE = path.join(__dirname, 'data', 'service.sqlite');
const APP_SECRET = process.env.APP_SECRET || 'dev-secret-change-me';
const SESSION_COOKIE = 'portfolio_session';
const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const PUBLIC_DIR = path.join(__dirname, 'public');
const QUOTE_TTL_MS = 15 * 60 * 1000;
const HISTORY_TTL_MS = 12 * 60 * 60 * 1000;

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
    iisProfitExemptionYears: 10
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
  const database = await openDatabase();
  try {
    const rows = database.prepare('SELECT id, email, name, password_hash, password_salt, created_at, portfolio_json FROM users ORDER BY created_at').all();
    return {
      users: rows.map((row) => normalizeStoredUser({
        id: row.id,
        email: row.email,
        name: row.name,
        passwordHash: row.password_hash,
        passwordSalt: row.password_salt,
        createdAt: row.created_at,
        portfolio: safeJsonParse(row.portfolio_json, {})
      }))
    };
  } finally {
    database.close();
  }
}

async function saveStore(store) {
  const database = await openDatabase();
  try {
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
          portfolioJson: JSON.stringify(normalizePortfolio(user.portfolio))
        });
      }
    });
    write(store.users || []);
  } finally {
    database.close();
  }
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

function safeJsonParse(value, fallback) {
  try {
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
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

async function routeApi(request, response, url) {
  if (url.pathname.startsWith('/api/auth/')) {
    return routeAuth(request, response, url);
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

  if (request.method === 'POST' && url.pathname === '/api/transactions') {
    const body = await readJsonBody(request);
    const instrument = await fetchMoexInstrument(normalizeTicker(body.ticker), data.blueChipTickers);
    const validation = validateTransaction({
      ...body,
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

function sendJson(response, body, statusCode = 200, headers = {}) {
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    ...headers
  });
  response.end(JSON.stringify(body));
}

const server = http.createServer(async (request, response) => {
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
  });
}

module.exports = {
  server,
  fetchBlueChipTickers,
  fetchMoexInstrument,
  fetchMoexHistory,
  hydrateMarketData,
  tableRows
};
