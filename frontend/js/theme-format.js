// ==========================================================================
// Theme Engine (Dark / Light / Auto by Device & Time-of-Day)
// ==========================================================================
const THEME_STORAGE_KEY = 'sd_theme_preference';
let lastEffectiveTheme = null;

function getThemePreference() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) || 'auto';
  } catch (_) {
    return 'auto';
  }
}

function isDaytime() {
  // Day: 07:00 to 20:00 local/Kyiv time
  const hour = new Date().getHours();
  return hour >= 7 && hour < 20;
}

function doesSystemPreferDark() {
  return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
}

function resolveEffectiveTheme(mode) {
  if (mode === 'light') return 'light';
  if (mode === 'dark') return 'dark';
  // 'auto' mode:
  // If nighttime (20:00 - 07:00) -> dark
  // If daytime (07:00 - 20:00): if system explicitly prefers dark -> dark, otherwise light
  if (!isDaytime()) return 'dark';
  if (doesSystemPreferDark()) return 'dark';
  return 'light';
}

function applyTheme(mode, notify = false) {
  const effective = resolveEffectiveTheme(mode);
  const root = document.documentElement;

  if (effective === 'light') {
    root.setAttribute('data-theme', 'light');
  } else {
    root.removeAttribute('data-theme');
  }

  // Update <meta name="theme-color"> for iOS / Android mobile status bars
  const metaTheme = document.getElementById('metaThemeColor') || document.querySelector('meta[name="theme-color"]');
  if (metaTheme) {
    metaTheme.setAttribute('content', effective === 'light' ? '#ffffff' : '#1e293b');
  }

  // Update header toggle button state and tooltip
  const btn = document.getElementById('themeToggleBtn');
  if (btn) {
    if (mode === 'auto') {
      btn.innerText = '🌓';
      const detail = effective === 'light' ? 'день / світла' : 'ніч / темна';
      btn.title = `Тема: Авто (${detail}). Натисніть для перемикання`;
      btn.setAttribute('aria-label', `Тема авто (${detail})`);
    } else if (mode === 'light') {
      btn.innerText = '☀️';
      btn.title = 'Тема: Світла (вручну). Натисніть для перемикання';
      btn.setAttribute('aria-label', 'Тема світла');
    } else {
      btn.innerText = '🌙';
      btn.title = 'Тема: Темна (вручну). Натисніть для перемикання';
      btn.setAttribute('aria-label', 'Тема темна');
    }
  }

  // Update mobile drawer theme icon
  const mobThemeIcon = document.getElementById('mobileMoreThemeIcon');
  if (mobThemeIcon) {
    mobThemeIcon.innerText = mode === 'auto' ? '🌓' : (mode === 'light' ? '☀️' : '🌙');
  }

  lastEffectiveTheme = effective;

  if (notify) {
    const messages = {
      auto: `Тема: Авто (${effective === 'light' ? 'Світла ☀️' : 'Темна 🌙'})`,
      light: 'Тема: Світла ☀️',
      dark: 'Тема: Темна 🌙'
    };
    showToast(messages[mode] || `Тема: ${mode}`, 'info');
  }
}

function cycleTheme() {
  const current = getThemePreference();
  let next;
  if (current === 'auto') {
    next = 'light';
  } else if (current === 'light') {
    next = 'dark';
  } else {
    next = 'auto';
  }
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch (_) {}
  applyTheme(next, true);
}

function checkAutoThemeTransition() {
  if (getThemePreference() === 'auto') {
    const effective = resolveEffectiveTheme('auto');
    if (effective !== lastEffectiveTheme) {
      applyTheme('auto', false);
    }
  }
}

function initTheme() {
  const currentPref = getThemePreference();
  applyTheme(currentPref, false);

  const btn = document.getElementById('themeToggleBtn');
  if (btn) {
    btn.onclick = cycleTheme;
  }

  // Listen to OS dark/light mode switches
  if (window.matchMedia) {
    try {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      if (mediaQuery.addEventListener) {
        mediaQuery.addEventListener('change', () => {
          if (getThemePreference() === 'auto') {
            applyTheme('auto', false);
          }
        });
      } else if (mediaQuery.addListener) {
        mediaQuery.addListener(() => {
          if (getThemePreference() === 'auto') {
            applyTheme('auto', false);
          }
        });
      }
    } catch (_) {}
  }
}

window.cycleTheme = cycleTheme;
window.applyTheme = applyTheme;

// Singleton Intl formatters (avoids re-instantiating formatters on every second tick & table cell)
const _fmtKyivTime = new Intl.DateTimeFormat('uk-UA', {
  timeZone: kyivTz,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false
});
const _fmtKyivDateTime = new Intl.DateTimeFormat('uk-UA', {
  timeZone: kyivTz,
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false
});
const _fmtKyivDateOnly = new Intl.DateTimeFormat('uk-UA', {
  timeZone: kyivTz,
  day: 'numeric',
  month: 'short',
  year: 'numeric'
});
const _fmtNum1 = new Intl.NumberFormat('uk-UA', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const _fmtNum2 = new Intl.NumberFormat('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const _fmtNumCache = { 1: _fmtNum1, 2: _fmtNum2 };

function updateKyivClock() {
  try {
    const el = document.getElementById('clockKyiv');
    if (!el) return;
    const now = new Date();
    const kyivTime = _fmtKyivTime.format(now);
    const nextText = `${kyivTime} (Київ)`;
    if (el.innerText !== nextText) el.innerText = nextText;

    // Check auto theme day/night transition on minute boundary
    if (now.getSeconds() === 0) {
      checkAutoThemeTransition();
    }
  } catch (_) {
    const el = document.getElementById('clockKyiv');
    if (el) {
      const d = new Date();
      el.innerText = d.toTimeString().slice(0, 8) + ' (Київ)';
    }
  }
}

function startClock() {
  updateKyivClock();
  setInterval(updateKyivClock, 1000);
}

// Universal UTC & Kyiv Date/Time Formatters
function parseUTCDate(val) {
  if (!val) return null;
  if (typeof val === 'string') {
    // If backend returns ISO string without timezone indicator (e.g. 2026-10-05T11:22:25),
    // append 'Z' so JavaScript treats it as UTC rather than local time.
    if (!val.endsWith('Z') && !val.includes('+') && !val.match(/[0-9]{2}:[0-9]{2}-[0-9]{2}/)) {
      val = val + 'Z';
    }
  }
  return new Date(val);
}

function formatDateTime(val) {
  const d = parseUTCDate(val);
  if (!d || isNaN(d.getTime())) return '-';
  try {
    return _fmtKyivDateTime.format(d);
  } catch (_) {
    return d.toLocaleString('uk-UA');
  }
}

function formatDateOnly(val) {
  const d = parseUTCDate(val);
  if (!d || isNaN(d.getTime())) return '-';
  try {
    return _fmtKyivDateOnly.format(d);
  } catch (_) {
    return d.toLocaleDateString('uk-UA');
  }
}

function formatTime(val) {
  const d = parseUTCDate(val);
  if (!d || isNaN(d.getTime())) return '-';
  try {
    return _fmtKyivTime.format(d);
  } catch (_) {
    return d.toLocaleTimeString('uk-UA');
  }
}

function formatDuration(totalSeconds) {
  if (totalSeconds == null || isNaN(totalSeconds) || totalSeconds < 0) return '00:00:00';
  const sec = Math.floor(totalSeconds);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function formatHoursToHms(hours) {
  if (hours == null || isNaN(hours) || Number(hours) < 0) return '00:00:00';
  const totalSeconds = Math.round(Number(hours) * 3600);
  return formatDuration(totalSeconds);
}

function formatHoursToHuman(hours) {
  if (hours == null || isNaN(hours) || Number(hours) <= 0) return '0 хв';
  const totalMinutes = Math.round(Number(hours) * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m} хв`;
  return `${h} год ${String(m).padStart(2, '0')} хв`;
}

function formatHoursCounter(hours) {
  if (hours == null || isNaN(hours)) return '0,0 год';
  const n = Number(hours);
  return `${_fmtNum1.format(n)} год`;
}

function formatMoney(amount) {
  if (amount == null || isNaN(amount)) return '0,00 грн';
  const n = Number(amount);
  return `${_fmtNum2.format(n)} грн`;
}

function formatLiters(liters, decimals = 2) {
  if (liters == null || isNaN(liters)) return `0,${'0'.repeat(decimals)} л`;
  const n = Number(liters);
  let fmt = _fmtNumCache[decimals];
  if (!fmt) {
    fmt = new Intl.NumberFormat('uk-UA', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    _fmtNumCache[decimals] = fmt;
  }
  return `${fmt.format(n)} л`;
}

function formatPricePerLiter(price) {
  if (price == null || isNaN(price)) return '0,00 грн/л';
  const n = Number(price);
  return `${_fmtNum2.format(n)} грн/л`;
}

// ==========================================================================
// Universal Client-Side Pagination (10 records per page)
// ==========================================================================
const _tablePaginationState = {};

function _renderTablePage(tableId) {
  const st = _tablePaginationState[tableId];
  if (!st) return;
  const table = document.getElementById(tableId);
  const tbody = table ? (table.querySelector('tbody') || document.getElementById(`${tableId}Body`)) : document.getElementById(`${tableId}Body`);
  if (!tbody) return;

  const total = st.items.length;
  const pageSize = st.pageSize || 10;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (st.page > totalPages) st.page = totalPages;
  if (st.page < 1) st.page = 1;

  if (total === 0) {
    tbody.innerHTML = `<tr><td colspan="${st.colspan}" style="text-align:center; color:var(--text-muted); padding: 1.1rem;">${st.emptyText}</td></tr>`;
  } else {
    const startIdx = (st.page - 1) * pageSize;
    const pageItems = st.items.slice(startIdx, startIdx + pageSize);
    tbody.innerHTML = pageItems.map((item, idx) => st.renderRowFn(item, startIdx + idx)).join('');
  }

  const wrapper = (table && (table.closest('.table-wrapper') || table.closest('.table-container'))) || table;
  if (!wrapper || !wrapper.parentNode) return;

  let bar = document.getElementById(`pag-${tableId}`);
  if (total <= pageSize) {
    if (bar) bar.style.display = 'none';
    return;
  }

  if (!bar) {
    bar = document.createElement('div');
    bar.id = `pag-${tableId}`;
    bar.className = 'pagination-bar';
    wrapper.parentNode.insertBefore(bar, wrapper.nextSibling);
  }

  const fromNum = (st.page - 1) * pageSize + 1;
  const toNum = Math.min(total, st.page * pageSize);

  const maxBtns = 5;
  let startP = Math.max(1, st.page - Math.floor(maxBtns / 2));
  let endP = Math.min(totalPages, startP + maxBtns - 1);
  if (endP - startP + 1 < maxBtns) {
    startP = Math.max(1, endP - maxBtns + 1);
  }

  let pageBtnsHtml = '';
  for (let p = startP; p <= endP; p++) {
    pageBtnsHtml += `<button type="button" class="pagination-btn ${p === st.page ? 'active' : ''}" onclick="changeTablePage('${tableId}', ${p})">${p}</button>`;
  }

  bar.style.display = 'flex';
  bar.innerHTML = `
    <div class="pagination-info">
      Показано <b>${fromNum}–${toNum}</b> із <b>${total}</b> • Сторінка <b>${st.page}</b> з <b>${totalPages}</b>
    </div>
    <div class="pagination-controls">
      <button type="button" class="pagination-btn" onclick="changeTablePage('${tableId}', ${st.page - 1})" ${st.page <= 1 ? 'disabled' : ''}>« Попередня</button>
      ${pageBtnsHtml}
      <button type="button" class="pagination-btn" onclick="changeTablePage('${tableId}', ${st.page + 1})" ${st.page >= totalPages ? 'disabled' : ''}>Наступна »</button>
    </div>
  `;
}

window.renderPaginatedTable = function(tableId, items, renderRowFn, colspan, emptyText, pageSize = 10) {
  const prev = _tablePaginationState[tableId];
  const arr = Array.isArray(items) ? items : [];
  const totalPages = Math.max(1, Math.ceil(arr.length / pageSize));
  const keepPage = prev && prev.page ? Math.min(prev.page, totalPages) : 1;
  _tablePaginationState[tableId] = {
    items: arr,
    renderRowFn,
    colspan,
    emptyText,
    pageSize,
    page: keepPage
  };
  _renderTablePage(tableId);
};

window.changeTablePage = function(tableId, nextPage) {
  const st = _tablePaginationState[tableId];
  if (!st) return;
  const totalPages = Math.max(1, Math.ceil(st.items.length / (st.pageSize || 10)));
  const target = Math.max(1, Math.min(totalPages, parseInt(nextPage, 10) || 1));
  if (target === st.page) return;
  st.page = target;
  _renderTablePage(tableId);
};

// Auth Lifecycle
