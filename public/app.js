'use strict';

const state = {
  portfolio: null,
  watchlist: {}
};

const assetLabels = {
  blue_chips: 'Голубые фишки',
  bonds: 'Облигации',
  growth: 'Рост'
};

const depositForm = document.querySelector('#deposit-form');
const transactionForm = document.querySelector('#transaction-form');
const depositMessage = document.querySelector('#deposit-message');
const tradeMessage = document.querySelector('#trade-message');
const refreshButton = document.querySelector('#refresh-market');

document.addEventListener('DOMContentLoaded', async () => {
  const today = new Date().toISOString().slice(0, 10);
  depositForm.elements.date.value = today;
  transactionForm.elements.date.value = today;
  await loadWatchlist();
  await loadPortfolio();
});

refreshButton.addEventListener('click', () => loadPortfolio(true));

depositForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  setMessage(depositMessage, 'Сохраняю пополнение...');

  const payload = Object.fromEntries(new FormData(depositForm).entries());

  try {
    const response = await fetch('/api/cash/deposits', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();

    if (!response.ok) throw new Error((result.errors || [result.error]).join(' '));

    depositForm.reset();
    depositForm.elements.date.value = new Date().toISOString().slice(0, 10);
    setMessage(depositMessage, 'Баланс пополнен. Смотрите блок “Что купить сейчас”.', 'ok');
    await loadPortfolio();
  } catch (error) {
    setMessage(depositMessage, error.message, 'error');
  }
});

transactionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  setMessage(tradeMessage, 'Сохраняю сделку...');

  const payload = Object.fromEntries(new FormData(transactionForm).entries());

  try {
    const response = await fetch('/api/transactions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();

    if (!response.ok) throw new Error((result.errors || [result.error]).join(' '));

    transactionForm.reset();
    transactionForm.elements.date.value = new Date().toISOString().slice(0, 10);
    setMessage(tradeMessage, 'Сделка сохранена.', 'ok');
    await loadPortfolio(true);
  } catch (error) {
    setMessage(tradeMessage, error.message, 'error');
  }
});

async function loadWatchlist() {
  const response = await fetch('/api/watchlist');
  state.watchlist = await response.json();
  const datalist = document.querySelector('#ticker-list');

  datalist.innerHTML = Object.values(state.watchlist)
    .flat()
    .map((instrument) => `<option value="${instrument.symbol}">${instrument.name}</option>`)
    .join('');
}

async function loadPortfolio(refresh = false) {
  refreshButton.disabled = true;
  refreshButton.textContent = refresh ? 'Обновляю...' : 'Загружаю...';

  try {
    const response = await fetch(`/api/portfolio${refresh ? '?refresh=1' : ''}`);
    state.portfolio = await response.json();
    render();
  } catch (error) {
    setMessage(tradeMessage, `Не удалось загрузить портфель: ${error.message}`, 'error');
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = 'Обновить цены рынка';
  }
}

function render() {
  if (!state.portfolio) return;

  renderTotals(state.portfolio);
  renderRecommendations(state.portfolio.recommendations);
  renderAllocation(state.portfolio.allocation);
  renderPositions(state.portfolio.positions);
  renderCashHistory(state.portfolio.cashMovements);
  renderTransactions(state.portfolio.transactions);
}

function renderTotals(portfolio) {
  document.querySelector('#cash-balance').textContent = formatMoney(portfolio.cash.balance);
  document.querySelector('#invested-value').textContent = formatMoney(portfolio.totals.investedValue);
  document.querySelector('#assets-with-cash').textContent = formatMoney(portfolio.totals.assetsWithCash);

  const pnl = document.querySelector('#total-pnl');
  pnl.textContent = `${formatMoney(portfolio.totals.unrealizedPnl)} (${formatPercent(portfolio.totals.unrealizedPnlPct)})`;
  pnl.className = portfolio.totals.unrealizedPnl >= 0 ? 'positive' : 'negative';
}

function renderRecommendations(recommendations) {
  const root = document.querySelector('#recommendations');

  root.innerHTML = recommendations
    .map((recommendation) => {
      const candidate = recommendation.candidates?.[0];
      const candidateHtml = candidate
        ? `
          <div class="candidate">
            <div>
              <span class="tag">${candidate.symbol}</span>
              <strong>${candidate.name}</strong>
              <p>${escapeHtml(candidate.thesis || '')}</p>
            </div>
            <dl>
              <div><dt>Лот</dt><dd>${candidate.lotSize || 1} шт.</dd></div>
              <div><dt>Цена</dt><dd>${formatMoney(candidate.price || candidate.referencePrice)}</dd></div>
              <div><dt>Лот стоит</dt><dd>${formatMoney(candidate.lotCost || ((candidate.price || candidate.referencePrice) * (candidate.lotSize || 1)))}</dd></div>
            </dl>
          </div>
        `
        : '';

      const orderHtml = recommendation.action === 'buy'
        ? `
          <div class="order-box">
            Купить: <strong>${recommendation.sharesToBuy} шт.</strong>
            (${recommendation.lotsToBuy} лот) примерно на
            <strong>${formatMoney(recommendation.estimatedCost)}</strong>
          </div>
        `
        : '';

      return `
        <article class="recommendation recommendation--${recommendation.action}">
          <p class="phase">Этап ${recommendation.phase || 'баланс'}</p>
          <h3>${escapeHtml(recommendation.title)}</h3>
          <p>${escapeHtml(recommendation.detail)}</p>
          ${orderHtml}
          ${candidateHtml}
        </article>
      `;
    })
    .join('');
}

function renderAllocation(allocation) {
  const root = document.querySelector('#allocation');

  root.innerHTML = allocation
    .map((item) => {
      const width = Math.min(Math.max(item.planCurrent * 100, 0), 100);
      return `
        <div class="allocation__row">
          <div class="allocation__meta">
            <strong>${item.label}</strong>
            <span>${formatPercent(item.planCurrent)} / цель ${formatPercent(item.target)}</span>
          </div>
          <div class="allocation__sub">
            Есть ${formatMoney(item.value)} · до цели ${formatMoney(item.remainingToTarget)}
          </div>
          <div class="allocation__bar" aria-label="${item.label}">
            <div class="allocation__fill" style="width: ${width}%"></div>
          </div>
        </div>
      `;
    })
    .join('');
}

function renderPositions(positions) {
  const root = document.querySelector('#positions');
  const marketStatus = document.querySelector('#market-status');

  if (positions.length === 0) {
    root.innerHTML = '<tr><td colspan="7">Пока нет позиций. Сначала пополните баланс, затем купите предложенный инструмент.</td></tr>';
    marketStatus.textContent = 'Позиции появятся после первой сделки.';
    return;
  }

  const latestQuote = positions
    .map((position) => position.quote.asOf)
    .filter(Boolean)
    .sort()
    .at(-1);
  marketStatus.textContent = latestQuote
    ? `Последнее обновление котировок: ${new Date(latestQuote).toLocaleString('ru-RU')}.`
    : 'Если рынок не вернул цену, используется средняя цена покупки или ориентир.';

  root.innerHTML = positions
    .map((position) => {
      const pnlClass = position.unrealizedPnl >= 0 ? 'positive' : 'negative';
      return `
        <tr>
          <td><strong>${position.ticker}</strong><br><small>${escapeHtml(position.name || '')}</small></td>
          <td>${assetLabels[position.assetClass] || position.assetClass}</td>
          <td>${formatQuantity(position.quantity)}</td>
          <td>${formatMoney(position.averagePrice)}</td>
          <td>${formatMoney(position.lastPrice)}<br><small>${position.quote.source}</small></td>
          <td>${formatMoney(position.marketValue)}</td>
          <td class="${pnlClass}">${formatMoney(position.unrealizedPnl)}<br><small>${formatPercent(position.unrealizedPnlPct)}</small></td>
        </tr>
      `;
    })
    .join('');
}

function renderCashHistory(cashMovements) {
  const root = document.querySelector('#cash-history');

  if (!cashMovements.length) {
    root.innerHTML = '<p class="message">Пополнений пока нет.</p>';
    return;
  }

  root.innerHTML = cashMovements
    .map((movement) => `
      <article class="history-item">
        <div>
          <strong>${formatMoney(movement.amount)}</strong>
          <br>
          <small>${movement.date}${movement.notes ? ` · ${escapeHtml(movement.notes)}` : ''}</small>
        </div>
        <button class="link-button" type="button" data-delete-deposit="${movement.id}">Удалить</button>
      </article>
    `)
    .join('');

  root.querySelectorAll('[data-delete-deposit]').forEach((button) => {
    button.addEventListener('click', () => deleteCashDeposit(button.dataset.deleteDeposit));
  });
}

function renderTransactions(transactions) {
  const root = document.querySelector('#transactions');

  if (!transactions.length) {
    root.innerHTML = '<p class="message">Сделок пока нет.</p>';
    return;
  }

  root.innerHTML = transactions
    .map((transaction) => {
      const sign = transaction.type === 'sell' ? 'Продажа' : 'Покупка';
      return `
        <article class="history-item">
          <div>
            <strong>${sign}: ${transaction.ticker}</strong>
            <br>
            <small>
              ${transaction.date} · ${formatQuantity(transaction.quantity)} шт. по
              ${formatMoney(transaction.price)} · ${assetLabels[transaction.assetClass]}
            </small>
          </div>
          <button class="link-button" type="button" data-delete-transaction="${transaction.id}">Удалить</button>
        </article>
      `;
    })
    .join('');

  root.querySelectorAll('[data-delete-transaction]').forEach((button) => {
    button.addEventListener('click', () => deleteTransaction(button.dataset.deleteTransaction));
  });
}

async function deleteCashDeposit(id) {
  if (!confirm('Удалить пополнение баланса?')) return;

  const response = await fetch(`/api/cash/deposits/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });

  if (response.ok) await loadPortfolio();
}

async function deleteTransaction(id) {
  if (!confirm('Удалить сделку из истории?')) return;

  const response = await fetch(`/api/transactions/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });

  if (response.ok) await loadPortfolio();
}

function setMessage(element, text, type = '') {
  element.textContent = text;
  element.className = `message${type ? ` message--${type}` : ''}`;
}

function formatMoney(value) {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 2
  }).format(Number(value || 0));
}

function formatPercent(value) {
  return new Intl.NumberFormat('ru-RU', {
    style: 'percent',
    maximumFractionDigits: 1
  }).format(Number(value || 0));
}

function formatQuantity(value) {
  return new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 6
  }).format(Number(value || 0));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}
