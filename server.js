'use strict';

const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { URL } = require('node:url');

const {
  DEFAULT_WATCHLIST,
  buildPortfolio,
  buildPositions,
  validateTransaction
} = require('./src/portfolio');

const PORT = Number(process.env.PORT || 3000);
const DATA_FILE = path.join(__dirname, 'data', 'portfolio.json');
const PUBLIC_DIR = path.join(__dirname, 'public');
const QUOTE_TTL_MS = 15 * 60 * 1000;

const DEFAULT_DATA = {
  transactions: [],
  quotes: {},
  watchlist: DEFAULT_WATCHLIST
};

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml; charset=utf-8'
};

async function loadData() {
  await fs.mkdir(path.dirname(DATA_FILE), { recursive: true });

  try {
    const raw = await fs.readFile(DATA_FILE, 'utf8');
    return {
      ...DEFAULT_DATA,
      ...JSON.parse(raw)
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
    const quotes = await hydrateQuotes(data, url.searchParams.get('refresh') === '1');
    await saveData(data);
    return sendJson(response, buildPortfolio(data.transactions, quotes, data.watchlist));
  }

  if (request.method === 'POST' && url.pathname === '/api/transactions') {
    const body = await readJsonBody(request);
    const validation = validateTransaction(body);

    if (!validation.valid) {
      return sendJson(response, { errors: validation.errors }, 400);
    }

    const data = await loadData();
    if (validation.value.type === 'sell') {
      const positions = buildPositions(data.transactions, data.quotes);
      const existing = positions.find((position) => position.ticker === validation.value.ticker);

      if (!existing || existing.quantity < validation.value.quantity) {
        return sendJson(response, { errors: ['Нельзя продать больше, чем есть в портфеле.'] }, 400);
      }
    }

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

  if (request.method === 'GET' && url.pathname === '/api/watchlist') {
    const data = await loadData();
    return sendJson(response, data.watchlist);
  }

  return sendJson(response, { error: 'API route not found' }, 404);
}

async function hydrateQuotes(data, forceRefresh = false) {
  const positions = buildPositions(data.transactions, data.quotes || {});
  const tickers = positions.map((position) => position.ticker);
  data.quotes = data.quotes || {};

  for (const ticker of tickers) {
    const cached = data.quotes[ticker];
    const isFresh = cached && Date.now() - new Date(cached.asOf || 0).getTime() < QUOTE_TTL_MS;

    if (!forceRefresh && isFresh) continue;

    try {
      data.quotes[ticker] = await fetchYahooQuote(ticker);
    } catch (error) {
      data.quotes[ticker] = {
        ...(cached || {}),
        error: error.message,
        source: cached?.source || 'manual',
        asOf: cached?.asOf || new Date().toISOString()
      };
    }
  }

  return data.quotes;
}

async function fetchYahooQuote(ticker) {
  if (typeof fetch !== 'function') {
    throw new Error('Node.js fetch API is unavailable. Use Node.js 18 or newer.');
  }

  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=1d&interval=1d`;
  const response = await fetch(url, {
    headers: {
      accept: 'application/json',
      'user-agent': 'lifetime-portfolio-local-app/0.1'
    }
  });

  if (!response.ok) {
    throw new Error(`Market data request failed with HTTP ${response.status}`);
  }

  const payload = await response.json();
  const result = payload.chart?.result?.[0];
  const meta = result?.meta;
  const price = Number(meta?.regularMarketPrice || meta?.previousClose);

  if (!Number.isFinite(price) || price <= 0) {
    throw new Error(`No market price returned for ${ticker}`);
  }

  return {
    price,
    currency: meta.currency || 'USD',
    asOf: new Date().toISOString(),
    source: 'Yahoo Finance'
  };
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
    console.log(`Lifetime portfolio assistant is running at http://localhost:${PORT}`);
  });
}

module.exports = {
  server,
  fetchYahooQuote,
  hydrateQuotes
};
