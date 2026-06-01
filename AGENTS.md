# AGENTS.md

## Cursor Cloud specific instructions

### Repository layout

`main` only contains a placeholder README. The runnable product is on branch **`cursor/lifetime-portfolio-app-3eeb`** (Node.js MOEX lifetime portfolio web app). Other `cursor/*` branches are separate Python CLI trading bots; they are not part of this web app’s dev loop.

Check out the web app before installing or running anything:

```bash
git fetch origin cursor/lifetime-portfolio-app-3eeb
git checkout cursor/lifetime-portfolio-app-3eeb
```

### Services (this product)

| Service | Required | Notes |
|---------|----------|--------|
| Node.js 18+ | Yes | `package.json` `engines.node` |
| SQLite (`data/service.sqlite`) | Yes (dev) | Created automatically when `DATABASE_URL` is unset |
| MOEX ISS (`https://iss.moex.com/iss/`) | Yes | Live quotes, history, scoring; first `/api/daily-analysis` or full portfolio refresh can take ~20s |
| PostgreSQL | No (dev) | Optional via `DATABASE_URL` for production-style runs |
| VK API | No | Optional `VK_GROUP_TOKEN` for scheduled notifications |

### Commands

See `README.md` and `package.json` for full detail. Quick reference:

| Task | Command |
|------|---------|
| Install deps | `npm install` |
| Tests | `npm test` (Node built-in test runner; 15 tests) |
| Dev server | `npm start` → http://localhost:3000 (override with `PORT`) |
| Lint / build | Not configured in this repo |

Set `APP_SECRET` for anything beyond local smoke tests. Production requires a long random secret (`NODE_ENV=production` enforces length ≥ 32).

### Running the dev server

Use a persistent session (tmux) for long-running `npm start`. Default port is **3000**.

Example:

```bash
APP_SECRET=your-local-dev-secret npm start
```

### Hello-world / E2E smoke test

1. Open http://localhost:3000 and register or log in.
2. Record a cash deposit (ручной сигнал о внесении средств).
3. Confirm `/api/portfolio` returns `recommendations` with a `buy` action and live MOEX tickers, or use the “Что сделать сейчас” block in the UI.

API-only smoke (cookie session):

```bash
curl -c /tmp/cj.txt -X POST http://localhost:3000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","name":"Test","password":"password-123"}'
curl -b /tmp/cj.txt -X POST http://localhost:3000/api/cash/deposits \
  -H 'Content-Type: application/json' -d '{"amount":50000}'
curl -b /tmp/cj.txt http://localhost:3000/api/portfolio
```

### Gotchas

- **Detached HEAD on `main`**: Always check out `cursor/lifetime-portfolio-app-3eeb` (or the Python branch you intend to work on) before `npm install`.
- **No ESLint/Prettier**: `npm test` is the only automated quality gate for this app.
- **MOEX latency**: Endpoints that refresh market data may be slow on cold start; do not assume sub-second API responses.
- **SQLite path**: Tests delete `data/service.sqlite`; stop the dev server before `npm test` if you care about local DB contents.
