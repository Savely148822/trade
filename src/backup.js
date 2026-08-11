'use strict';

const BACKUP_FORMAT = 'moex-portfolio-backup';
const BACKUP_VERSION = 1;

function createPortfolioBackup({ email = '', name = '', portfolio }) {
  return {
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    exportedAt: new Date().toISOString(),
    email: String(email || '').trim().toLowerCase(),
    name: String(name || '').trim(),
    portfolio: clonePortfolio(portfolio)
  };
}

function parsePortfolioBackup(raw) {
  const errors = [];
  const backup = typeof raw === 'string' ? safeJsonParse(raw) : raw;

  if (!backup || typeof backup !== 'object' || Array.isArray(backup)) {
    return { valid: false, errors: ['Файл бэкапа должен быть JSON-объектом.'] };
  }

  if (backup.format !== BACKUP_FORMAT) {
    errors.push(`Неизвестный формат бэкапа (ожидается ${BACKUP_FORMAT}).`);
  }

  if (Number(backup.version) !== BACKUP_VERSION) {
    errors.push(`Неподдерживаемая версия бэкапа (ожидается ${BACKUP_VERSION}).`);
  }

  if (!backup.portfolio || typeof backup.portfolio !== 'object' || Array.isArray(backup.portfolio)) {
    errors.push('В бэкапе нет объекта portfolio.');
  }

  if (errors.length) {
    return { valid: false, errors };
  }

  return {
    valid: true,
    errors: [],
    value: {
      format: BACKUP_FORMAT,
      version: BACKUP_VERSION,
      exportedAt: String(backup.exportedAt || ''),
      email: String(backup.email || '').trim().toLowerCase(),
      name: String(backup.name || '').trim(),
      portfolio: clonePortfolio(backup.portfolio)
    }
  };
}

function backupFileName(email = '') {
  const stamp = new Date().toISOString().slice(0, 10);
  const safeEmail = String(email || 'portfolio')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'portfolio';
  return `moex-portfolio-${safeEmail}-${stamp}.json`;
}

function clonePortfolio(portfolio = {}) {
  return {
    cashMovements: Array.isArray(portfolio.cashMovements)
      ? portfolio.cashMovements.map((item) => ({ ...item }))
      : [],
    transactions: Array.isArray(portfolio.transactions)
      ? portfolio.transactions.map((item) => ({ ...item }))
      : [],
    quotes: portfolio.quotes && typeof portfolio.quotes === 'object' && !Array.isArray(portfolio.quotes)
      ? { ...portfolio.quotes }
      : {},
    blueChipTickers: Array.isArray(portfolio.blueChipTickers) ? [...portfolio.blueChipTickers] : [],
    settings: portfolio.settings && typeof portfolio.settings === 'object'
      ? { ...portfolio.settings }
      : {}
  };
}

function safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

module.exports = {
  BACKUP_FORMAT,
  BACKUP_VERSION,
  backupFileName,
  createPortfolioBackup,
  parsePortfolioBackup
};
