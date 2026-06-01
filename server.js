'use strict';

const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { URL } = require('node:url');

const {
  FALLBACK_INSTRUMENTS,
  MARKET_UNIVERSE,
  buildPortfolio,
  buildPositions,
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
const DATA_FILE = path.join(__dirname, 'data', 'portfolio.json');
const PUBLIC_DIR = path.join(__dirname, 'public');
const QUOTE_TTL_MS = 15 * 60 * 1000;
const HISTORY_TTL_MS = 12 * 60 * 60 * 1000;

const DEFAULT_DATA = {
  cashMovements: [],
  transactions: [],
  quotes: {},
  blueChipTickers: [],
  settings: {
    commissionRate: 0.0006
  }
};

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8'
};

async function loadData() {
  await fs.mkdir(path.dirname(DATA_FILE), { recursive: true });

  try {
    const raw = await fs.readFile(DATA_FILE, 'utf8');
    const parsed = JSON.parse(raw);
    return {
      ...DEFAULT_DATA,
      ...parsed,
      settings: normalizeSettings(parsed.settings)
    };
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    await saveData(DEFAULT_DATA);
    return structuredClone(DEFAULT_DATA);
  }
}

async function saveData(data) {
  await fs.mkdir(path.dirname(DATA_FILE), { recursive: true });
  await fs.writeFile(DATA_FILE, `${JSON.stringify(data, null, 2)}\n`);
}

async function routeApi(request, response, url) {
  if (request.method === 'GET' && url.pathname === '/api/portfolio') {
    const data = await loadData();
    await hydrateMarketData(data, url.searchParams.get('refresh') === '1');
    await saveData(data);
    return sendJson(response, buildPortfolio(data.transactions, data.quotes, data.settings, data.cashMovements));
  }

  if (request.method === 'GET' && url.pathname === '/api/watchlist') {
    return sendJson(response, {
      universe: MARKET_UNIVERSE,
      instruments: FALLBACK_INSTRUMENTS
    });
  }

  if (request.method === 'POST' && url.pathname === '/api/settings') {
    const body = await readJsonBody(request);
    const validation = validateSettings(body);

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    const data = await loadData();
    data.settings = validation.value;
    await saveData(data);
    return sendJson(response, { settings: data.settings });
  }

  if (request.method === 'POST' && url.pathname === '/api/cash/deposits') {
    const body = await readJsonBody(request);
    const validation = validateCashDeposit(body);

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    const data = await loadData();
    data.cashMovements.push(validation.value);
    await saveData(data);
    return sendJson(response, { cashMovement: validation.value }, 201);
  }

  if (request.method === 'POST' && url.pathname === '/api/transactions') {
    const body = await readJsonBody(request);
    const data = await loadData();
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
    await saveData(data);
    return sendJson(response, { transaction: validation.value }, 201);
  }

  if (request.method === 'DELETE' && url.pathname.startsWith('/api/transactions/')) {
    const id = decodeURIComponent(url.pathname.replace('/api/transactions/', ''));
    const data = await loadData();
    const before = data.transactions.length;
    data.transactions = data.transactions.filter((transaction) => transaction.id !== id);
    await saveData(data);
    return sendJson(response, { deleted: before !== data.transactions.length });
  }

  if (request.method === 'DELETE' && url.pathname.startsWith('/api/cash/deposits/')) {
    const id = decodeURIComponent(url.pathname.replace('/api/cash/deposits/', ''));
    const data = await loadData();
    const before = data.cashMovements.length;
    data.cashMovements = data.cashMovements.filter((movement) => movement.id !== id);
    await saveData(data);
    return sendJson(response, { deleted: before !== data.cashMovements.length });
  }

  return sendJson(response, { error: 'API route not found' }, 404);
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

function sendJson(response, body, statusCode = 200) {
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
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
