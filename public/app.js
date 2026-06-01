'use strict';

const state = {
  portfolio: null,
  loading: false
};

const assetLabels = {
  blue_chips: 'Голубые фишки',
  bonds: 'Облигации',
  growth: 'Рост'
};

const form = document.querySelector('#transaction-form');
const formMessage = document.querySelector('#form-message');
const refreshButton = document.querySelector('#refresh-market');

document.addEventListener('DOMContentLoaded', () => {
  form.elements.date.value = new Date().toISOString().slice(0, 10);
  loadPortfolio();
});

refreshButton.addEventListener('click', () => loadPortfolio(true));

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  setMessage('Сохраняю сделку...');

  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());

  try {
    const response = await fetch('/api/transactions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error((result.errors || [result.error]).join(' '));
    }

    form.reset();
    form.elements.currency.value = payload.currency || 'USD';
    form.elements.date.value = new Date().toISOString().slice(0, 10);
    setMessage('Сделка сохранена.', 'ok');
    await loadPortfolio(true);
  } catch (error) {
    setMessage(error.message, 'error');
  }
});

async function loadPortfolio(refresh = false) {
  state.loading = true;
  refreshButton.disabled = true;
  refreshButton.textContent = refresh ? 'Обновляю...' : 'Загружаю...';

  try {
    const response = await fetch(`/api/portfolio${refresh ? '?refresh=1' : ''}`);
    state.portfolio = await response.json();
    render();
  } catch (error) {
    setMessage(`Не удалось загрузить портфель: ${error.message}`, 'error');
  } finally {
    state.loading = false;
    refreshButton.disabled = false;
    refreshButton.textContent = 'Обновить цены рынка';
  }
}

function render() {
  if (!state.portfolio) return;

  renderTotals(state.portfolio.totals);
  renderAllocation(state.portfolio.allocation);
  renderRecommendations(state.portfolio.recommendations);
  renderPositions(state.portfolio.positions);
  renderTransactions(state.portfolio.transactions);
  renderWarnings(state.portfolio.warnings);
}

function renderTotals(totals) {
  const currency = totals.currencies[0] || 'USD';
  document.querySelector('#total-value').textContent = formatMoney(totals.value, currency);
  document.querySelector('#total-cost').textContent = formatMoney(totals.cost, currency);

  const pnl = document.querySelector('#total-pnl');
  pnl.textContent = `${formatMoney(totals.unrealizedPnl, currency)} (${formatPercent(totals.unrealizedPnlPct)})`;
  pnl.className = totals.unrealizedPnl >= 0 ? 'positive' : 'negative';
}

function renderAllocation(allocation) {
  const root = document.querySelector('#allocation');
  root.innerHTML = allocation
    .map((item) => {
      const width = Math.min(Math.max(item.current * 100, 0), 100);
      return `
        <div class="allocation__row">
          <div class="allocation__meta">
            <strong>${item.label}</strong>
            <span>${formatPercent(item.current)} / цель ${formatPercent(item.target)}</span>
          </div>
          <div class="allocation__bar" aria-label="${item.label}">
            <div class="allocation__fill" style="width: ${width}%"></div>
          </div>
        </div>
      `;
    })
    .join('');
}

function renderRecommendations(recommendations) {
  const root = document.querySelector('#recommendations');
  root.innerHTML = recommendations
    .map((recommendation) => {
      const candidates = (recommendation.candidates || [])
        .map((candidate) => `<span class="tag">${candidate.symbol} · ${candidate.name}</span>`)
        .join('');
      const thesis = (recommendation.candidates || [])
        .map((candidate) => candidate.thesis)
        .filter(Boolean)
        .map((text) => `<p>${escapeHtml(text)}</p>`)
        .join('');

      return `
        <article class="recommendation">
          <h3>${escapeHtml(recommendation.title)}</h3>
          <p>${escapeHtml(recommendation.detail)}</p>
          <div>${candidates}</div>
          ${thesis}
        </article>
      `;
    })
    .join('');
}

function renderPositions(positions) {
  const root = document.querySelector('#positions');
  const marketStatus = document.querySelector('#market-status');

  if (positions.length === 0) {
    root.innerHTML = '<tr><td colspan="7">Пока нет позиций. Добавьте первую покупку слева.</td></tr>';
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
    : 'Для части позиций используются цены сделок, потому что рынок не вернул котировки.';

  root.innerHTML = positions
    .map((position) => {
      const currency = position.quote.currency || position.currency;
      const pnlClass = position.unrealizedPnl >= 0 ? 'positive' : 'negative';
      return `
        <tr>
          <td><strong>${position.ticker}</strong><br><small>${escapeHtml(position.name || '')}</small></td>
          <td>${assetLabels[position.assetClass] || position.assetClass}</td>
          <td>${formatQuantity(position.quantity)}</td>
          <td>${formatMoney(position.averagePrice, currency)}</td>
          <td>${formatMoney(position.lastPrice, currency)}<br><small>${position.quote.source}</small></td>
          <td>${formatMoney(position.marketValue, currency)}</td>
          <td class="${pnlClass}">${formatMoney(position.unrealizedPnl, currency)}<br><small>${formatPercent(position.unrealizedPnlPct)}</small></td>
        </tr>
      `;
    })
    .join('');
}

function renderTransactions(transactions) {
  const root = document.querySelector('#transactions');

  if (transactions.length === 0) {
    root.innerHTML = '<p class="message">История пустая.</p>';
    return;
  }

  root.innerHTML = transactions
    .map((transaction) => {
      const sign = transaction.type === 'sell' ? 'Продажа' : 'Покупка';
      return `
        <article class="transaction">
          <div>
            <strong>${sign}: ${transaction.ticker}</strong>
            <br>
            <small>
              ${transaction.date} · ${formatQuantity(transaction.quantity)} шт. по
              ${formatMoney(transaction.price, transaction.currency)} · ${assetLabels[transaction.assetClass]}
            </small>
          </div>
          <button class="link-button" type="button" data-delete="${transaction.id}">Удалить</button>
        </article>
      `;
    })
    .join('');

  root.querySelectorAll('[data-delete]').forEach((button) => {
    button.addEventListener('click', async () => {
      await deleteTransaction(button.dataset.delete);
    });
  });
}

function renderWarnings(warnings) {
  if (!warnings || warnings.length === 0) return;
  setMessage(warnings.join(' '), 'error');
}

async function deleteTransaction(id) {
  if (!confirm('Удалить сделку из истории?')) return;

  const response = await fetch(`/api/transactions/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });

  if (response.ok) {
    await loadPortfolio();
  }
}

function setMessage(text, type = '') {
  formMessage.textContent = text;
  formMessage.className = `message${type ? ` message--${type}` : ''}`;
}

function formatMoney(value, currency = 'USD') {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency,
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
