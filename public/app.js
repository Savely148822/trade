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

const settingsForm = document.querySelector('#settings-form');
const depositForm = document.querySelector('#deposit-form');
const transactionForm = document.querySelector('#transaction-form');
const withdrawalForm = document.querySelector('#withdrawal-form');
const settingsMessage = document.querySelector('#settings-message');
const depositMessage = document.querySelector('#deposit-message');
const tradeMessage = document.querySelector('#trade-message');
const withdrawalMessage = document.querySelector('#withdrawal-message');
const refreshButton = document.querySelector('#refresh-market');

document.addEventListener('DOMContentLoaded', async () => {
  const today = new Date().toISOString().slice(0, 10);
  depositForm.elements.date.value = today;
  transactionForm.elements.date.value = today;
  await loadWatchlist();
  await loadPortfolio();
});

refreshButton.addEventListener('click', () => loadPortfolio(true));

settingsForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const commissionPercent = Number(settingsForm.elements.commissionPercent.value);
  const incomeTaxPercent = Number(settingsForm.elements.incomeTaxPercent.value);

  try {
    const response = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        commissionRate: commissionPercent / 100,
        accountType: 'iis3',
        iisOpenDate: settingsForm.elements.iisOpenDate.value,
        claimedDeductionYears: settingsForm.elements.claimedDeductionYears.value,
        incomeTaxRate: incomeTaxPercent / 100
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error((result.errors || [result.error]).join(' '));
    setMessage(settingsMessage, 'Настройки ИИС-3 и комиссия сохранены.', 'ok');
    await loadPortfolio();
  } catch (error) {
    setMessage(settingsMessage, error.message, 'error');
  }
});

withdrawalForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  setMessage(withdrawalMessage, 'Считаю план вывода...');

  try {
    const response = await fetch('/api/withdrawal-plan', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ amount: withdrawalForm.elements.amount.value })
    });
    const result = await response.json();
    if (!response.ok || result.plan?.valid === false) {
      throw new Error((result.plan?.errors || result.errors || [result.error]).join(' '));
    }
    renderWithdrawalPlan(result.plan);
    setMessage(withdrawalMessage, 'План готов.', 'ok');
  } catch (error) {
    setMessage(withdrawalMessage, error.message, 'error');
  }
});

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
    setMessage(depositMessage, 'Баланс пополнен.', 'ok');
    await loadPortfolio();
  } catch (error) {
    setMessage(depositMessage, error.message, 'error');
  }
});

transactionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  setMessage(tradeMessage, 'Проверяю тикер на MOEX и сохраняю сделку...');

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
    setMessage(tradeMessage, 'Сделка сохранена. Класс инструмента определен автоматически.', 'ok');
    await loadPortfolio(true);
  } catch (error) {
    setMessage(tradeMessage, error.message, 'error');
  }
});

async function loadWatchlist() {
  const response = await fetch('/api/watchlist');
  state.watchlist = await response.json();
  const datalist = document.querySelector('#ticker-list');

  datalist.innerHTML = Object.values(state.watchlist.universe || {})
    .flat()
    .map((ticker) => {
      const instrument = state.watchlist.instruments?.[ticker];
      return `<option value="${ticker}">${instrument?.name || ticker}</option>`;
    })
    .join('');
}

async function loadPortfolio(refresh = false) {
  refreshButton.disabled = true;
  refreshButton.textContent = refresh ? 'Обновляю MOEX...' : 'Загружаю...';

  try {
    const response = await fetch(`/api/portfolio${refresh ? '?refresh=1' : ''}`);
    state.portfolio = await response.json();
    render();
  } catch (error) {
    setMessage(tradeMessage, `Не удалось загрузить портфель: ${error.message}`, 'error');
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = 'Обновить рынок MOEX';
  }
}

function render() {
  if (!state.portfolio) return;

  renderSettings(state.portfolio.settings);
  renderTotals(state.portfolio);
  renderDailyAnalysis(state.portfolio.dailyAnalysis);
  renderRecommendations(state.portfolio.recommendations);
  renderAllocation(state.portfolio.allocation);
  renderPositions(state.portfolio.positions);
  renderCashHistory(state.portfolio.cashMovements);
  renderTransactions(state.portfolio.transactions);
}

function renderSettings(settings) {
  settingsForm.elements.commissionPercent.value = formatPlainNumber((settings.commissionRate || 0) * 100, 3);
  settingsForm.elements.iisOpenDate.value = settings.iisOpenDate || '';
  settingsForm.elements.claimedDeductionYears.value = (settings.claimedDeductionYears || []).join(', ');
  settingsForm.elements.incomeTaxPercent.value = formatPlainNumber((settings.incomeTaxRate || 0.13) * 100, 2);
}

function renderTotals(portfolio) {
  document.querySelector('#cash-balance').textContent = formatMoney(portfolio.cash.balance);
  document.querySelector('#invested-value').textContent = formatMoney(portfolio.totals.investedValue);
  document.querySelector('#assets-with-cash').textContent = formatMoney(portfolio.totals.assetsWithCash);

  const pnl = document.querySelector('#total-pnl');
  pnl.textContent = `${formatMoney(portfolio.totals.unrealizedPnl)} (${formatPercent(portfolio.totals.unrealizedPnlPct)})`;
  pnl.className = portfolio.totals.unrealizedPnl >= 0 ? 'positive' : 'negative';
}

function renderDailyAnalysis(analysis) {
  const root = document.querySelector('#daily-analysis');
  if (!root) return;

  if (!analysis) {
    root.innerHTML = '<p class="message">Отчет появится после обновления рынка.</p>';
    return;
  }

  const impacts = (analysis.portfolio?.biggestImpacts || []).map((item) => `
    <article class="history-item">
      <div>
        <strong>${item.ticker}: ${formatMoney(item.dailyPnl)}</strong>
        <br>
        <small>${formatPercent(item.changePercent)} за день · ${escapeHtml(item.reason || '')}</small>
      </div>
      <span class="tag">${item.buyScore}/100</span>
    </article>
  `).join('');
  const risers = (analysis.market?.risers || []).slice(0, 3).map((item) => `<span class="tag positive">${item.symbol} ${formatPercent(item.changePercent)}</span>`).join('');
  const fallers = (analysis.market?.fallers || []).slice(0, 3).map((item) => `<span class="tag negative">${item.symbol} ${formatPercent(item.changePercent)}</span>`).join('');
  const buy = analysis.actions?.buy;
  const sells = (analysis.actions?.sells || []).map((item) => `<li>${escapeHtml(item.title)}${item.amount ? ` · ${formatMoney(item.amount)}` : ''}</li>`).join('');

  root.innerHTML = `
    <article class="recommendation">
      <h3>${escapeHtml(analysis.headline)}</h3>
      <p>${escapeHtml(analysis.portfolio?.explanation || '')}</p>
      <p>Рынок MOEX: растут ${analysis.market?.advancing || 0}, падают ${analysis.market?.declining || 0} из ${analysis.market?.trackedCount || 0} отслеживаемых.</p>
      <div>${risers}</div>
      <div>${fallers}</div>
      ${buy ? `<p><strong>Докупить:</strong> ${escapeHtml(buy.title)}${buy.amount ? ` · ${formatMoney(buy.amount)}` : ''}</p>` : ''}
      ${sells ? `<details open><summary>Что можно сократить</summary><ul>${sells}</ul></details>` : ''}
    </article>
    ${impacts || '<p class="message">Пока нет позиций для анализа портфеля.</p>'}
  `;
}
function renderRecommendations(recommendations) {
  const root = document.querySelector('#recommendations');

  root.innerHTML = recommendations
    .map((recommendation) => {
      const candidate = recommendation.candidates?.[0];
      const analysis = candidate?.analysis || {};
      const candidateHtml = candidate
        ? `
          <div class="candidate">
            <div>
              <span class="tag">${candidate.symbol}</span>
              <strong>${candidate.name}</strong>
              <p>${escapeHtml(analysis.summary || '')}</p>
              ${renderList('Почему', analysis.reasons)}
              ${renderList('Риски', analysis.risks)}
            </div>
            <dl>
              <div><dt>Лот</dt><dd>${candidate.lotSize || 1} шт.</dd></div>
              <div><dt>Цена</dt><dd>${formatMoney(candidate.price || 0)}</dd></div>
              <div><dt>Лот + комиссия</dt><dd>${formatMoney(candidate.lotCostWithCommission || candidate.lotCost || 0)}</dd></div>
              <div><dt>Buy score</dt><dd>${analysis.buyScore ?? 0}/100</dd></div>
              <div><dt>Перекупленность</dt><dd>${analysis.overboughtScore ?? 0}/100</dd></div>
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
        : recommendation.action === 'sell'
          ? `
            <div class="order-box order-box--sell">
              Возможное сокращение: примерно на
              <strong>${formatMoney(recommendation.estimatedSellAmount)}</strong>
            </div>
          `
          : '';

      return `
        <article class="recommendation recommendation--${recommendation.action}">
          <p class="phase">${recommendation.actionLabel || actionLabel(recommendation.action)} · ${assetLabels[recommendation.phase] || 'баланс'}</p>
          <h3>${escapeHtml(recommendation.title)}</h3>
          <p>${escapeHtml(recommendation.detail)}</p>
          ${orderHtml}
          ${candidateHtml}
        </article>
      `;
    })
    .join('');
}

function renderList(title, items = []) {
  if (!items.length) return '';
  return `
    <details>
      <summary>${title}</summary>
      <ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
    </details>
  `;
}

function actionLabel(action) {
  return {
    buy: 'Докупить',
    sell: 'Продать/сократить',
    wait: 'Подождать',
    deposit: 'Пополнить',
    tax: 'ИИС-3 / налоги'
  }[action] || action;
}

function renderWithdrawalPlan(plan) {
  const root = document.querySelector('#withdrawal-plan');
  if (!root) return;

  if (!plan) {
    root.innerHTML = '<p class="message">Введите сумму вывода, чтобы получить план продаж.</p>';
    return;
  }

  const warnings = (plan.warnings || [])
    .map((warning) => `<p class="message message--error">${escapeHtml(warning)}</p>`)
    .join('');
  const sales = (plan.sales || [])
    .map((sale) => `
      <article class="history-item">
        <div>
          <strong>${sale.ticker}: продать ${formatQuantity(sale.quantity)} шт.</strong>
          <br>
          <small>Ожидаемо к выводу ${formatMoney(sale.net)} · комиссия ${formatMoney(sale.commission)} · риск: ${escapeHtml(sale.taxRisk)}</small>
          <br>
          <small>${escapeHtml(sale.reason || sale.taxStatus || '')}</small>
        </div>
        <span class="tag">score ${sale.priorityScore}</span>
      </article>
    `)
    .join('');
  const shortfall = plan.shortfall > 0 ? ', не хватает ' + formatMoney(plan.shortfall) : '';

  root.innerHTML = `
    <article class="recommendation">
      <h3>Нужно вывести ${formatMoney(plan.amount)}</h3>
      <p>Свободный кеш: ${formatMoney(plan.cashUsed)}. Продажи должны дать примерно ${formatMoney(plan.targetFromSales)}.</p>
      <p>Расчетный итог к выводу: <strong>${formatMoney(plan.estimatedNet)}</strong>${shortfall}.</p>
    </article>
    ${warnings}
    ${sales || '<p class="message">Продажи не требуются или нет доступных лотов.</p>'}
  `;
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
    root.innerHTML = '<tr><td colspan="8">Пока нет позиций. Сначала пополните баланс, затем купите предложенный инструмент.</td></tr>';
    marketStatus.textContent = 'Источник данных: MOEX ISS. Позиции появятся после первой сделки.';
    return;
  }

  const latestQuote = positions
    .map((position) => position.quote.asOf)
    .filter(Boolean)
    .sort()
    .at(-1);
  marketStatus.textContent = latestQuote
    ? `Источник данных: MOEX ISS. Последнее обновление: ${new Date(latestQuote).toLocaleString('ru-RU')}.`
    : 'Источник данных: MOEX ISS. Если рынок не вернул цену, используется fallback.';

  root.innerHTML = positions
    .map((position) => {
      const pnlClass = position.unrealizedPnl >= 0 ? 'positive' : 'negative';
      const analysis = position.quote.analysis || {};
      return `
        <tr>
          <td><strong>${position.ticker}</strong><br><small>${escapeHtml(position.name || '')}</small></td>
          <td>${assetLabels[position.assetClass] || position.assetClass}</td>
          <td>${formatQuantity(position.quantity)}</td>
          <td>${formatMoney(position.averagePrice)}</td>
          <td>${formatMoney(position.lastPrice)}<br><small>${position.quote.source}</small></td>
          <td>${formatMoney(position.marketValue)}</td>
          <td class="${pnlClass}">${formatMoney(position.unrealizedPnl)}<br><small>${formatPercent(position.unrealizedPnlPct)}</small></td>
          <td>
            <strong>${analysis.buyScore ?? 0}/100</strong>
            <br><small>перегрев ${analysis.overboughtScore ?? 0}/100</small>
          </td>
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

function formatPlainNumber(value, digits = 2) {
  return Number(value || 0).toFixed(digits).replace(/\.?0+$/, '');
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
