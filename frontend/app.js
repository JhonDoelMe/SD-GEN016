// ==========================================
// 🛡️ Anti-Phishing & Unauthorized Mirror Protection
// ==========================================
(function checkDomainIntegrity() {
  // Read dynamic primary domain injected from .env via meta tag or global config
  const metaDomain = document.querySelector('meta[name="app-primary-domain"]')?.getAttribute('content');
  const primaryDomain = (metaDomain || window.__APP_PRIMARY_DOMAIN__ || 'generator-016.pp.ua').toLowerCase().trim();

  const allowedHosts = [
    primaryDomain,
    `www.${primaryDomain}`,
    'localhost',
    '127.0.0.1'
  ];
  const currentHost = (window.location.hostname || '').toLowerCase();

  // If accessed via unauthorized domain mirror / rogue clone
  if (
    currentHost &&
    !allowedHosts.includes(currentHost) &&
    !currentHost.endsWith('.local') &&
    !currentHost.startsWith('192.168.') &&
    !currentHost.startsWith('10.') &&
    !currentHost.startsWith('172.')
  ) {
    console.error('🚨 CRITICAL SECURITY ALERT: Unauthorized Mirror / Phishing Domain detected:', currentHost);

    // 1. Immediately wipe all local credentials to protect user tokens from phishing
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch (e) {}

    const officialUrl = `https://${primaryDomain}`;

    // 2. Render blocking alert and auto-redirect to official domain
    const renderAlert = () => {
      document.body.innerHTML = `
        <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #0f172a; color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px; box-sizing: border-box; text-align: center;">
          <div style="max-width: 520px; width: 100%; background: #1e293b; border: 2px solid #ef4444; border-radius: 16px; padding: 36px 24px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);">
            <div style="font-size: 56px; margin-bottom: 16px; line-height: 1;">🚨</div>
            <h1 style="color: #ef4444; font-size: 22px; font-weight: 700; margin: 0 0 12px;">УВАГА: НЕБЕЗПЕЧНИЙ САЙТ-КЛОН!</h1>
            <p style="color: #cbd5e1; font-size: 15px; line-height: 1.6; margin: 0 0 14px;">
              Ви перейшли за сторонньою несанкціонованою адресою (<span style="color: #f87171; font-weight: 600;">${currentHost}</span>).
            </p>
            <p style="color: #94a3b8; font-size: 13.5px; line-height: 1.5; margin: 0 0 24px;">
              Введення будь-яких логінів та паролів на цьому дзеркалі суворо заблоковано для запобігання перехопленню конфіденційних даних та облікових записів.
            </p>
            <a href="${officialUrl}" style="display: inline-block; background: #2563eb; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);">
              Перейти на офіційний сайт ${primaryDomain}
            </a>
            <div style="margin-top: 16px; font-size: 12px; color: #64748b;">
              Автоматичне перенаправлення через 4 секунди...
            </div>
          </div>
        </div>
      `;
      setTimeout(() => {
        window.location.replace(officialUrl);
      }, 4000);
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', renderAlert);
    } else {
      renderAlert();
    }

    // 3. Stop all further application execution
    throw new Error('Script execution halted: Unauthorized domain mirror detected.');
  }
})();

// Service Desk Бензинового Генератора - Frontend Application Logic

let token = localStorage.getItem('sd_token') || sessionStorage.getItem('sd_token');
let currentUser = null;
let currentFacilityId = null;
let currentGeneratorId = null;
let currentGenerator = null;
let activeRun = null;

const ROLE_MAP_UA = {
  'superadmin': 'Головний адміністратор',
  'SuperAdmin': 'Головний адміністратор',
  'admin': 'Адміністратор',
  'Admin': 'Адміністратор',
  'operator': 'Оператор',
  'Operator': 'Оператор',
  'viewer': 'Спостерігач',
  'Viewer': 'Спостерігач'
};

function hasRole(roleName) {
  if (!currentUser) return false;
  if (currentUser.is_superadmin) return true;
  const target = (roleName || '').toLowerCase();
  return (currentUser.roles || []).some((r) => (r || '').toLowerCase() === target);
}

function hasPermission(permCode) {
  if (!currentUser) return false;
  if (currentUser.is_superadmin || hasRole('superadmin')) return true;
  return (currentUser.permissions || []).includes(permCode);
}

function isSuperAdmin() {
  return currentUser && (currentUser.is_superadmin || hasRole('superadmin'));
}

function isAdmin() {
  return currentUser && (isSuperAdmin() || hasRole('admin'));
}

function isOperator() {
  return currentUser && (isAdmin() || hasRole('operator'));
}

function isViewerOnly() {
  return currentUser && hasRole('viewer') && !hasRole('operator') && !hasRole('admin') && !currentUser.is_superadmin;
}

function applyRolePermissionsUI() {
  if (!currentUser) return;

  const viewer = isViewerOnly();
  const operator = isOperator() && !isAdmin();
  const admin = isAdmin() && !isSuperAdmin();
  const superadmin = isSuperAdmin();

  // 1. Navigation Tabs restrictions
  const tabRules = {
    'tab-dashboard': true, // always accessible
    'tab-fuel': !viewer,
    'tab-maintenance': !viewer,
    'tab-faults': !viewer,
    'tab-runs': !viewer,
    'tab-notifications': !viewer,
    'tab-audit': isAdmin(),
    'tab-reports': isAdmin(),
    'tab-admin': isAdmin()
  };

  document.querySelectorAll('.nav-item').forEach((tab) => {
    const paneId = tab.getAttribute('data-tab');
    const isAllowed = tabRules[paneId] ?? true;
    let orig = tab.getAttribute('data-orig-html');
    if (!orig) {
      orig = tab.innerHTML;
      tab.setAttribute('data-orig-html', orig);
    }
    if (!isAllowed) {
      tab.classList.add('nav-item-disabled');
      tab.setAttribute('aria-disabled', 'true');
      const cleanText = orig.replace(/<span class="nav-lock-badge".*?<\/span>/g, '').trim();
      tab.innerHTML = `${cleanText} <span class="nav-lock-badge">🔒</span>`;
      tab.setAttribute('title', viewer ? 'Розділ заблоковано для ролі Спостерігач 🔒' : 'Розділ заблоковано для ролі Оператор (потрібні права Адміністратора) 🔒');
    } else {
      tab.classList.remove('nav-item-disabled');
      tab.removeAttribute('aria-disabled');
      tab.innerHTML = orig;
      tab.removeAttribute('title');
    }
  });

  // If user is currently in a forbidden tab, switch to dashboard immediately
  const activeTab = document.querySelector('.nav-item.active');
  if (activeTab && activeTab.classList.contains('nav-item-disabled')) {
    const dashTab = document.querySelector('.nav-item[data-tab="tab-dashboard"]');
    if (dashTab) {
      document.querySelectorAll('.nav-item').forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach((p) => (p.style.display = 'none'));
      dashTab.classList.add('active');
      const dashPane = document.getElementById('tab-dashboard');
      if (dashPane) dashPane.style.display = 'block';
    }
  }

  // 2. Helper to set button state with visual lock
  const setBtnState = (btnId, isAllowed, reason, lockedHtml = null) => {
    const b = document.getElementById(btnId);
    if (!b) return;
    let orig = b.getAttribute('data-orig-html');
    if (!orig) {
      orig = b.innerHTML;
      b.setAttribute('data-orig-html', orig);
    }
    if (!isAllowed) {
      b.disabled = true;
      b.classList.add('btn-disabled-role');
      b.title = reason;
      if (lockedHtml) {
        b.innerHTML = lockedHtml;
      } else if (!b.innerHTML.includes('🔒')) {
        b.innerHTML = `${orig} <span class="nav-lock-badge">🔒</span>`;
      }
    } else {
      b.disabled = false;
      b.classList.remove('btn-disabled-role');
      b.removeAttribute('title');
      b.innerHTML = orig;
    }
  };

  // 3. Facilities management buttons (Admin/Superadmin only)
  const canConfigFacility = hasPermission('facility:configure');
  setBtnState('addFacilityBtn', canConfigFacility, "Додавання об'єктів доступне лише Адміністратору 🔒", "+ Об'єкт 🔒");
  setBtnState('quickEditFacilityBtn', canConfigFacility, "Редагування об'єктів доступне лише Адміністратору 🔒", "⚙️🔒");

  // 4. Generators management buttons (Admin/Superadmin only)
  const canConfigGen = hasPermission('generator:configure');
  setBtnState('addGeneratorBtn', canConfigGen, 'Створення генераторів доступне лише Адміністратору 🔒', '+ Генератор 🔒');
  setBtnState('quickEditGeneratorBtn', canConfigGen, 'Редагування генераторів доступне лише Адміністратору 🔒', '⚙️🔒');
  setBtnState('deleteGeneratorBtn', canConfigGen, 'Видалення генераторів доступне лише Адміністратору 🔒', '🗑️🔒');

  // 5. Dashboard main buttons
  if (viewer) {
    const mainBtn = document.getElementById('mainActionBtn');
    if (mainBtn) {
      mainBtn.disabled = true;
      mainBtn.className = 'btn-hero btn-disabled-role';
      mainBtn.innerHTML = '<span>🔒</span><span>ЗАПУСК ЗАБЛОКОВАНО (СПОСТЕРІГАЧ)</span>';
      mainBtn.title = 'Запуск та зупинка генератора недоступні для ролі Спостерігач 🔒';
    }
    const manualBtn = document.getElementById('btnOpenManualRun');
    if (manualBtn) {
      manualBtn.style.display = 'none';
    }
  }

  // Quick Action Buttons on Dashboard
  setBtnState('btnQuickTransfer', !viewer && hasPermission('fuel:transfer'), 'Заправка генератора недоступна для вашої ролі 🔒', '<span class="icon">⛽</span><span>Заправити бак 🔒</span>');
  setBtnState('btnQuickReceipt', !viewer && hasPermission('fuel:receipt'), 'Оприбуткування палива недоступне для вашої ролі 🔒', '<span class="icon">📥</span><span>+ Прийняти паливо 🔒</span>');
  setBtnState('btnQuickMaint', !viewer && (hasPermission('maintenance:create_intermediate') || hasPermission('maintenance:perform_scheduled')), 'Фіксація ТО недоступна для вашої ролі 🔒', '<span class="icon">🛠️</span><span>Зафіксувати ТО 🔒</span>');
  setBtnState('btnQuickFault', !viewer && hasPermission('faults:create'), 'Реєстрація несправності недоступна для вашої ролі 🔒', '<span class="icon">⚠️</span><span>Несправність 🔒</span>');

  // Fuel stock creation button (Admin/Superadmin only)
  const canConfigFuel = hasPermission('fuel:configure');
  setBtnState('btnFuelNewStock', canConfigFuel, 'Створення складу ГСМ доступне лише Адміністратору 🔒', '📦 + Додати склад ГСМ 🔒');
  setBtnState('btnFuelReceipt', hasPermission('fuel:receipt'), 'Оприбуткування палива недоступне для вашої ролі 🔒', '+ Оприбуткувати 🔒');
  setBtnState('btnFuelTransfer', hasPermission('fuel:transfer'), 'Заправка бака недоступна для вашої ролі 🔒', '⛽ Заправити бак 🔒');

  // Maintenance buttons
  const canPerformSched = hasPermission('maintenance:perform_scheduled');
  setBtnState('btnRecalculateMaint', canPerformSched, 'Перерахунок нормативу ТО доступний лише Адміністратору 🔒', '🔄 Перерахувати 🔒');
  setBtnState('btnOpenMaintModal', hasPermission('maintenance:create_intermediate') || canPerformSched, 'Фіксація ТО недоступна для вашої ролі 🔒', '+ Зафіксувати ТО 🔒');

  // Maintenance Type selector in modal
  const maintTypeSel = document.getElementById('maintType');
  if (maintTypeSel) {
    const schedOpt = maintTypeSel.querySelector('option[value="SCHEDULED"]');
    if (schedOpt) {
      if (!canPerformSched) {
        schedOpt.disabled = true;
        schedOpt.text = 'Регламентне ТО (тільки для Адміністратора 🔒)';
        if (maintTypeSel.value === 'SCHEDULED') maintTypeSel.value = 'INTERMEDIATE';
      } else {
        schedOpt.disabled = false;
        schedOpt.text = 'Регламентне ТО (скидає та подовжує інтервал)';
      }
    }
  }

  // Faults button
  setBtnState('btnOpenFaultModal', hasPermission('faults:create'), 'Реєстрація несправностей недоступна для вашої ролі 🔒', '+ Зафіксувати дефект 🔒');

  // Audit adjustments button (SuperAdmin only!)
  setBtnState('btnOpenAdjustment', superadmin, 'Системні коригування лічильників доступні виключно Головному Суперадміністратору 🔒', '⚙️ Системне коригування 🔒');

  // Admin tab buttons
  setBtnState('btnSystemReset', superadmin, 'Очищення даних та скидання БД доступне виключно Головному Суперадміністратору 🔒', '⚠️ Очищення та скидання БД 🔒');
  setBtnState('btnOpenUserCreateModal', superadmin, 'Створення користувачів доступне виключно Головному Суперадміністратору 🔒', '+ Створити користувача 🔒');
  setBtnState('btnRefreshFuelPrices', hasPermission('settings:manage'), 'Оновлення цін доступне лише Адміністратору 🔒', '🔄 Оновити ціни 🔒');

  // Backup panel and buttons (SuperAdmin only!)
  const panelBackups = document.getElementById('panelBackups');
  if (panelBackups) {
    panelBackups.style.display = superadmin ? 'block' : 'none';
  }
  setBtnState('btnOpenCreateBackup', superadmin, 'Створення резервних копій доступне виключно Головному Суперадміністратору 🔒', '➕ Створити бекап зараз 🔒');
  setBtnState('btnOpenUploadRestore', superadmin, 'Відновлення з бекапу доступне виключно Головному Суперадміністратору 🔒', '📤 Завантажити архів та відновити 🔒');
  setBtnState('btnOpenBackupSettings', superadmin, 'Налаштування розкладу доступні виключно Головному Суперадміністратору 🔒', '⚙️ Розклад автобекапу 🔒');
}


// HTML Escaping Helper (Protects against Stored & Reflected XSS)
function escapeHtml(val) {
  if (val === null || val === undefined) return '';
  return String(val)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function extractErrorMessage(data, fallback) {
  if (!data || !data.detail) return fallback;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((item) => (item && item.msg ? String(item.msg).replace(/^Value error,\s*/i, '') : JSON.stringify(item)))
      .join('; ');
  }
  return fallback;
}

// API Helper
async function api(endpoint, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const res = await fetch(`/api/v1${endpoint}`, { ...options, headers });
    const data = await res.json().catch(() => null);

    if (res.status === 401) {
      if (endpoint !== '/auth/login') {
        token = null;
        localStorage.removeItem('sd_token');
        sessionStorage.removeItem('sd_token');
        showAuthScreen();
        throw new Error('Сесія закінчилась. Будь ласка, увійдіть знову');
      } else {
        const msg = extractErrorMessage(data, 'Невірний логін або пароль');
        throw new Error(msg);
      }
    }

    if (!res.ok) {
      const msg = extractErrorMessage(data, `Помилка сервера (${res.status})`);
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    showToast(err.message, 'error');
    throw err;
  }
}

// Toast Helper
function showToast(message, type = 'info') {
  const toast = document.getElementById('toast');
  toast.innerText = message;
  toast.className = `toast ${type}`;
  toast.style.display = 'block';
  setTimeout(() => {
    toast.style.display = 'none';
  }, 4000);
}

// Modal Helpers
window.openModal = function (id) {
  // Security guard against unauthorized modal opening
  if (id === 'modalSystemReset' && !isSuperAdmin()) {
    showToast('Скидання бази даних доступне виключно Головному Суперадміністратору', 'warning');
    return;
  }
  if (id === 'modalAdjustment' && !isSuperAdmin()) {
    showToast('Системне коригування лічильників доступне виключно Головному Суперадміністратору', 'warning');
    return;
  }
  if ((id === 'modalCreateBackup' || id === 'modalBackupSettings' || id === 'modalDeleteBackup' || id === 'modalConfirmRestore' || id === 'modalUploadRestore') && !isSuperAdmin()) {
    showToast('Керування резервними копіями та відновлення доступні виключно Головному Суперадміністратору', 'warning');
    return;
  }
  if ((id === 'modalCreateFacility' || id === 'modalQuickEditFacility') && !hasPermission('facility:configure')) {
    showToast("Керування об'єктами доступне лише Адміністратору", 'warning');
    return;
  }
  if ((id === 'modalCreateGenerator' || id === 'modalQuickEditGenerator' || id === 'modalDeleteGenerator' || id === 'modalWizard') && !hasPermission('generator:configure')) {
    showToast('Керування генераторами доступне лише Адміністратору', 'warning');
    return;
  }
  if ((id === 'modalNewStock' || id === 'modalEditStock') && !hasPermission('fuel:configure')) {
    showToast('Керування складами ГСМ доступне лише Адміністратору', 'warning');
    return;
  }
  if (id === 'modalUserCreate' && !hasPermission('users:manage')) {
    showToast('Керування користувачами доступне лише Адміністратору', 'warning');
    return;
  }
  if (id === 'modalReceipt' && !hasPermission('fuel:receipt')) {
    showToast('Оприбуткування палива недоступне для вашої ролі', 'warning');
    return;
  }
  if (id === 'modalTransfer' && !hasPermission('fuel:transfer')) {
    showToast('Заправка бака недоступна для вашої ролі', 'warning');
    return;
  }
  if (id === 'modalFault' && !hasPermission('faults:create')) {
    showToast('Реєстрація несправностей недоступна для вашої ролі', 'warning');
    return;
  }
  if (id === 'modalResolveFault' && !hasPermission('faults:manage')) {
    showToast('Усунення дефектів доступне лише Адміністратору', 'warning');
    return;
  }
  if (id === 'modalMaintenance' && !hasPermission('maintenance:create_intermediate') && !hasPermission('maintenance:perform_scheduled')) {
    showToast('Фіксація ТО недоступна для вашої ролі', 'warning');
    return;
  }
  if (id === 'modalStopGen' && !hasPermission('generator:stop')) {
    showToast('Зупинка генератора недоступна для вашої ролі', 'warning');
    return;
  }

  const modal = document.getElementById(id);
  if (modal) modal.style.display = 'flex';
  if (id === 'modalReceipt') setupReceiptModal();
  if (id === 'modalTransfer') setupTransferModal();
  if (id === 'modalNewStock') setupNewStockModal();
  if (id === 'modalAdjustment') openAdjustmentModal();
};

window.closeModal = function (id) {
  const modal = document.getElementById(id);
  if (modal) modal.style.display = 'none';
};

// Kyiv Live Clock & Universal Formatters
let kyivTz = 'Europe/Kyiv';
try {
  new Intl.DateTimeFormat('uk-UA', { timeZone: kyivTz }).format(new Date());
} catch (_) {
  try {
    kyivTz = 'Europe/Kiev';
    new Intl.DateTimeFormat('uk-UA', { timeZone: kyivTz }).format(new Date());
  } catch (_) {
    kyivTz = undefined;
  }
}

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

function updateKyivClock() {
  try {
    const el = document.getElementById('clockKyiv');
    if (!el) return;
    const now = new Date();
    const kyivTime = new Intl.DateTimeFormat('uk-UA', {
      timeZone: kyivTz,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).format(now);
    el.innerText = `${kyivTime} (Київ)`;

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
    return new Intl.DateTimeFormat('uk-UA', {
      timeZone: kyivTz,
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).format(d);
  } catch (_) {
    return d.toLocaleString('uk-UA');
  }
}

function formatDateOnly(val) {
  const d = parseUTCDate(val);
  if (!d || isNaN(d.getTime())) return '-';
  try {
    return new Intl.DateTimeFormat('uk-UA', {
      timeZone: kyivTz,
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    }).format(d);
  } catch (_) {
    return d.toLocaleDateString('uk-UA');
  }
}

function formatTime(val) {
  const d = parseUTCDate(val);
  if (!d || isNaN(d.getTime())) return '-';
  try {
    return new Intl.DateTimeFormat('uk-UA', {
      timeZone: kyivTz,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).format(d);
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
  return `${new Intl.NumberFormat('uk-UA', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(n)} год`;
}

function formatMoney(amount) {
  if (amount == null || isNaN(amount)) return '0,00 грн';
  const n = Number(amount);
  return `${new Intl.NumberFormat('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)} грн`;
}

function formatLiters(liters, decimals = 2) {
  if (liters == null || isNaN(liters)) return `0,${'0'.repeat(decimals)} л`;
  const n = Number(liters);
  return `${new Intl.NumberFormat('uk-UA', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(n)} л`;
}

function formatPricePerLiter(price) {
  if (price == null || isNaN(price)) return '0,00 грн/л';
  const n = Number(price);
  return `${new Intl.NumberFormat('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)} грн/л`;
}

// Auth Lifecycle
function showAuthScreen() {
  document.getElementById('authOverlay').style.display = 'flex';
}

function hideAuthScreen() {
  document.getElementById('authOverlay').style.display = 'none';
}

async function checkAuth() {
  if (!token) {
    token = localStorage.getItem('sd_token') || sessionStorage.getItem('sd_token');
  }

  try {
    currentUser = await api('/auth/me');
  } catch (err) {
    // Only real auth error redirects to login modal
    token = null;
    localStorage.removeItem('sd_token');
    sessionStorage.removeItem('sd_token');
    showAuthScreen();
    return;
  }

  // User is authenticated
  hideAuthScreen();
  try {
    const rolesUa = (currentUser.roles || []).map(r => ROLE_MAP_UA[r] || ROLE_MAP_UA[r.toLowerCase()] || r).join(', ') || 'користувач';
    const greetEl = document.getElementById('userGreeting');
    if (greetEl) greetEl.innerText = `${currentUser.full_name} (${rolesUa})`;
    applyRolePermissionsUI();
    await loadAllData();
  } catch (dataErr) {
    console.error('Error loading initial dashboard data:', dataErr);
  }
}

document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const loginInput = document.getElementById('loginUsername').value.trim();
  const passInput = document.getElementById('loginPassword').value;
  const rememberMe = document.getElementById('loginRememberMe')?.checked ?? true;
  const loginBtn = document.getElementById('loginSubmitBtn');
  const errorBox = document.getElementById('loginError');

  if (errorBox) {
    errorBox.style.display = 'none';
    errorBox.innerText = '';
  }

  if (!loginInput) {
    if (errorBox) {
      errorBox.style.display = 'block';
      errorBox.innerText = '❌ Будь ласка, введіть логін користувача';
    }
    return;
  }

  if (!passInput) {
    if (errorBox) {
      errorBox.style.display = 'block';
      errorBox.innerText = '❌ Будь ласка, введіть пароль';
    }
    return;
  }

  if (loginBtn) {
    loginBtn.disabled = true;
    loginBtn.innerText = 'Вхід...';
  }

  try {
    const res = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ login: loginInput, password: passInput, remember_me: rememberMe })
    });
    token = res.access_token;
    if (rememberMe) {
      localStorage.setItem('sd_token', token);
      localStorage.setItem('sd_remember_me', 'true');
    } else {
      sessionStorage.setItem('sd_token', token);
      localStorage.removeItem('sd_token');
      localStorage.setItem('sd_remember_me', 'false');
    }
    currentUser = res.user;
    const rolesUa = (currentUser.roles || []).map(r => ROLE_MAP_UA[r] || ROLE_MAP_UA[r.toLowerCase()] || r).join(', ') || 'користувач';
    document.getElementById('userGreeting').innerText = `${currentUser.full_name} (${rolesUa})`;
    hideAuthScreen();
    applyRolePermissionsUI();
    showToast(`Вітаємо, ${currentUser.full_name}!`, 'success');
    loadAllData();
  } catch (err) {
    if (errorBox) {
      errorBox.style.display = 'block';
      errorBox.innerText = `❌ ${err.message || 'Невірний логін або пароль'}`;
    }
  } finally {
    if (loginBtn) {
      loginBtn.disabled = false;
      loginBtn.innerText = 'Увійти в систему';
    }
  }
});

document.getElementById('logoutBtn').addEventListener('click', async () => {
  try {
    await api('/auth/logout', { method: 'POST' });
  } catch (_) {}
  token = null;
  localStorage.removeItem('sd_token');
  sessionStorage.removeItem('sd_token');
  currentUser = null;
  showAuthScreen();
});

// Tab Navigation
document.querySelectorAll('.nav-item').forEach((tab) => {
  tab.addEventListener('click', (e) => {
    if (tab.classList.contains('nav-item-disabled')) {
      e.preventDefault();
      e.stopPropagation();
      showToast('Розділ заблоковано для вашої ролі 🔒', 'warning');
      return false;
    }

    document.querySelectorAll('.nav-item').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach((p) => (p.style.display = 'none'));

    tab.classList.add('active');
    const paneId = tab.getAttribute('data-tab');
    const pane = document.getElementById(paneId);
    if (pane) pane.style.display = 'block';

    // Refresh tab data
    if (paneId === 'tab-fuel') loadFuelData();
    if (paneId === 'tab-maintenance') loadMaintenanceData();
    if (paneId === 'tab-faults') loadFaultsData();
    if (paneId === 'tab-runs') loadRunsData();
    if (paneId === 'tab-notifications') {
      loadNotificationSettings();
      loadNotificationLogs();
      checkPushSubscriptionStatus();
    }
    if (paneId === 'tab-audit') loadAuditData();
    if (paneId === 'tab-reports') loadReport();
    if (paneId === 'tab-admin') {
      loadUsersData();
      loadAdminSystemSettings();
      if (isSuperAdmin()) {
        loadBackupsList();
      }
    }
  });
});

// Facilities & Generators Management
async function loadFacilitiesList() {
  try {
    const facilities = await api('/facilities');
    const sel = document.getElementById('facilitySelect');
    const modalSel = document.getElementById('newGenFacilityId');
    if (!sel) return;

    sel.innerHTML = facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
    if (modalSel) {
      modalSel.innerHTML = facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
    }

    if (facilities.length > 0) {
      const savedFacilityId = parseInt(localStorage.getItem('sd_last_facility_id') || '0', 10);
      if (savedFacilityId && facilities.some(f => f.id === savedFacilityId)) {
        currentFacilityId = savedFacilityId;
      } else if (!currentFacilityId || !facilities.some(f => f.id === currentFacilityId)) {
        currentFacilityId = facilities[0].id;
      }
      sel.value = currentFacilityId;
      localStorage.setItem('sd_last_facility_id', currentFacilityId);
    }
  } catch (err) {
    console.warn('loadFacilitiesList:', err);
  }
}

async function loadGeneratorsList(facilityId) {
  try {
    const url = `/generator/list${facilityId ? '?facility_id=' + encodeURIComponent(facilityId) : ''}`;
    const generators = await api(url);
    const sel = document.getElementById('generatorSelect');
    if (!sel) return;

    if (!generators || generators.length === 0) {
      sel.innerHTML = '<option value="">(Немає генераторів)</option>';
      currentGenerator = null;
      currentGeneratorId = null;
    } else {
      sel.innerHTML = generators.map(g => `<option value="${Number(g.id)}">${escapeHtml(g.name)} (${escapeHtml(g.model)})</option>`).join('');
      
      const savedGenForFac = parseInt(localStorage.getItem(`sd_last_gen_facility_${facilityId}`) || '0', 10);
      const savedGlobalGen = parseInt(localStorage.getItem('sd_last_generator_id') || '0', 10);
      const targetGenId = (savedGenForFac && generators.some(g => g.id === savedGenForFac))
        ? savedGenForFac
        : ((savedGlobalGen && generators.some(g => g.id === savedGlobalGen)) ? savedGlobalGen : null);

      if (targetGenId) {
        currentGeneratorId = targetGenId;
      } else if (!currentGeneratorId || !generators.some(g => g.id === currentGeneratorId)) {
        currentGeneratorId = generators[0].id;
      }
      sel.value = currentGeneratorId;
      localStorage.setItem('sd_last_generator_id', currentGeneratorId);
      if (facilityId) {
        localStorage.setItem(`sd_last_gen_facility_${facilityId}`, currentGeneratorId);
      }
    }
  } catch (err) {
    console.warn('loadGeneratorsList:', err);
  }
}

// Load All Dashboard Data
async function loadAllData() {
  if (!currentFacilityId) {
    await loadFacilitiesList();
  }
  if (!currentGeneratorId) {
    await loadGeneratorsList(currentFacilityId);
  }
  await loadGeneratorData();
  if (!isViewerOnly() && hasPermission('fuel:view')) {
    await loadFuelSummary();
  } else {
    const cardStock = document.getElementById('cardStock');
    if (cardStock) cardStock.innerText = '-';
  }
  if (!isViewerOnly() && hasPermission('maintenance:view')) {
    await loadMaintenanceSummary();
  } else {
    const cardMaintRem = document.getElementById('cardMaintRem');
    if (cardMaintRem) cardMaintRem.innerHTML = `- <small style="font-size:0.9rem;">год</small>`;
    const cardMaintSub = document.getElementById('cardMaintSub');
    if (cardMaintSub) cardMaintSub.innerText = `доступно для оператора`;
  }
  await loadRecentRuns();
  applyRolePermissionsUI();
}

// 1. Generator Data
async function loadGeneratorData() {
  if (!currentGeneratorId) {
    currentGenerator = null;
    const nameEl = document.getElementById('genName');
    if (nameEl) nameEl.innerText = "Немає генератора";
    const modelEl = document.getElementById('genModel');
    if (modelEl) modelEl.innerText = "На обраному об'єкті ще немає генераторів. Натисніть «+ Генератор», щоб зареєструвати перший генератор.";
    const cardHours = document.getElementById('cardHours');
    if (cardHours) cardHours.innerText = "0,0";
    const cardTank = document.getElementById('cardTank');
    if (cardTank) cardTank.innerText = "0,0";
    const badge = document.getElementById('genStatusBadge');
    if (badge) {
      badge.className = 'badge';
      badge.innerText = 'ВІДСУТНІЙ';
    }
    const btn = document.getElementById('mainActionBtn');
    if (btn) {
      btn.className = 'btn-hero btn-disabled-role';
      btn.disabled = true;
      btn.innerHTML = '<span>➕</span><span>ДОДАЙТЕ ГЕНЕРАТОР НА ОБ\'ЄКТ</span>';
      btn.title = 'Натисніть кнопку "+ Генератор" у верхній панелі, щоб зареєструвати генератор';
    }
    return;
  }
  try {
    let url = `/generator?generator_id=${encodeURIComponent(currentGeneratorId)}`;
    currentGenerator = await api(url);
    if (!currentGenerator) return;
    currentGeneratorId = currentGenerator.id;
    const sel = document.getElementById('generatorSelect');
    if (sel && sel.value != currentGeneratorId) {
      sel.value = currentGeneratorId;
    }

    document.getElementById('genName').innerText = currentGenerator.name;
    document.getElementById('genModel').innerText = `Модель: ${currentGenerator.model} | Серійний: ${currentGenerator.serial_number} | Потужність: ${currentGenerator.rated_power_kw} кВт`;
    document.getElementById('cardHours').innerText = currentGenerator.current_operating_hours.toFixed(1).replace('.', ',');

    const fuelL = currentGenerator.fuel_tank_level_l;
    const cardTank = document.getElementById('cardTank');
    const tankProgress = document.getElementById('tankProgress');
    const cardTankHoursRem = document.getElementById('cardTankHoursRem');

    cardTank.innerText = fuelL.toFixed(1).replace('.', ',');
    if (fuelL < 0) {
      cardTank.style.color = '#ef4444';
      if (tankProgress) tankProgress.style.width = '0%';
      if (cardTankHoursRem) {
        cardTankHoursRem.innerHTML = `<span style="color: #ef4444; font-weight: 600;">⚠️ Дефіцит: ${formatLiters(Math.abs(fuelL))} (потрібна заправка!)</span>`;
      }
    } else {
      cardTank.style.color = 'inherit';
      const cap = currentGenerator.tank_capacity_l || 25.0;
      const pct = Math.min(100, Math.max(0, Math.round((fuelL / cap) * 100)));
      if (tankProgress) tankProgress.style.width = `${pct}%`;
      const nominal = currentGenerator.nominal_consumption_l_per_h || 2.2;
      const hoursLeft = nominal > 0 ? (fuelL / nominal) : 0;
      if (cardTankHoursRem) {
        if (fuelL === 0) {
          cardTankHoursRem.innerHTML = `<span style="color: var(--text-muted);">вистачить на 0 год (бак порожній)</span>`;
        } else {
          cardTankHoursRem.innerHTML = `вистачить на ~<b>${hoursLeft.toFixed(1).replace('.', ',')}</b> год (при ${nominal} л/год)`;
        }
      }
    }

    // Status Badge & Action Button
    const badge = document.getElementById('genStatusBadge');
    const btn = document.getElementById('mainActionBtn');
    const banner = document.getElementById('activeRunBanner');

    badge.className = 'badge';
    if (currentGenerator.status === 'RUNNING') {
      badge.classList.add('badge-running');
      badge.innerText = 'ПРАЦЮЄ';
      btn.className = 'btn-hero btn-stop';
      btn.innerHTML = '<span>⏹</span><span>ЗУПИНИТИ ГЕНЕРАТОР</span>';
    } else if (currentGenerator.status === 'MAINTENANCE_REQUIRED') {
      badge.classList.add('badge-maintenance');
      badge.innerText = 'ПОТРІБНЕ ТО';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
    } else if (currentGenerator.status === 'FAULTY') {
      badge.classList.add('badge-faulty');
      badge.innerText = 'НЕСПРАВНИЙ';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>⚠️</span><span>НЕСПРАВНІСТЬ (БЛОК)</span>';
    } else if (currentGenerator.status === 'BLOCKED') {
      badge.classList.add('badge-blocked');
      badge.innerText = 'ЗАБЛОКОВАНО';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>🔒</span><span>ЗАБЛОКОВАНО</span>';
    } else {
      badge.classList.add('badge-stopped');
      badge.innerText = 'ЗУПИНЕНО';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
    }

    // Active Run Check
        const btnManual = document.getElementById('btnOpenManualRun');
    if (btnManual) {
      btnManual.style.display = (currentGenerator && currentGenerator.status === 'RUNNING' ? 'none' : 'inline-flex');
    }

    activeRun = await api(`/generator/active-run${currentGeneratorId ? '?generator_id=' + encodeURIComponent(currentGeneratorId) : ''}`);
    if (activeRun) {
      banner.style.display = 'block';
      document.getElementById('activeRunStart').innerText = formatTime(activeRun.start_time);
      document.getElementById('activeRunHours').innerText = activeRun.start_hours.toFixed(1).replace('.', ',');
      startRunStopwatch();
    } else {
      banner.style.display = 'none';
      stopRunStopwatch();
    }
    applyRolePermissionsUI();
  } catch (_) {}
}

let runTimerInterval = null;

let cachedMaintenanceSchedule = null;

function updateRunStopwatchDisplay() {
  if (!activeRun || !activeRun.start_time) return;
  const startDt = parseUTCDate(activeRun.start_time);
  if (!startDt) return;
  const now = new Date();
  const elapsedSeconds = Math.max(0, Math.floor((now.getTime() - startDt.getTime()) / 1000));
  const durFormatted = formatDuration(elapsedSeconds);

  const bannerDur = document.getElementById('activeRunDuration');
  if (bannerDur) bannerDur.innerText = durFormatted;

  const modalDur = document.getElementById('stopDurationDisplay');
  if (modalDur) modalDur.innerText = durFormatted;

  const elapsedHours = elapsedSeconds / 3600.0;
  const nominal = (currentGenerator && currentGenerator.nominal_consumption_l_per_h) || 2.2;
  const estConsumed = elapsedHours * nominal;

  const modalEstFuel = document.getElementById('stopEstFuelDisplay');
  if (modalEstFuel) {
    modalEstFuel.innerText = formatLiters(estConsumed);
  }

  // Live dynamic update of the 4 dashboard tiles during active run
  if (currentGenerator && currentGenerator.status === 'RUNNING') {
    // 1. Live Operating Hours (accumulative)
    const startH = activeRun.start_hours ?? currentGenerator.current_operating_hours;
    const liveHours = startH + elapsedHours;
    const cardHours = document.getElementById('cardHours');
    if (cardHours) cardHours.innerText = liveHours.toFixed(1).replace('.', ',');

    // 2. Live Tank Level & 'вистачить на ... год' (can go negative into deficit!)
    const startFuel = activeRun.start_fuel_level_l ?? activeRun.start_fuel ?? currentGenerator.fuel_tank_level_l;
    const liveTank = startFuel - estConsumed;
    const cardTank = document.getElementById('cardTank');
    const tankProgress = document.getElementById('tankProgress');
    const cardTankHoursRem = document.getElementById('cardTankHoursRem');

    if (cardTank) {
      cardTank.innerText = liveTank.toFixed(1).replace('.', ',');
      if (liveTank < 0) {
        cardTank.style.color = '#ef4444';
        if (tankProgress) tankProgress.style.width = '0%';
        if (cardTankHoursRem) {
          cardTankHoursRem.innerHTML = `<span style="color: #ef4444; font-weight: 600;">⚠️ Дефіцит: ${formatLiters(Math.abs(liveTank))} (потрібна заправка!)</span>`;
        }
      } else {
        cardTank.style.color = 'inherit';
        const cap = currentGenerator.tank_capacity_l || 25.0;
        const pct = Math.min(100, Math.max(0, Math.round((liveTank / cap) * 100)));
        if (tankProgress) tankProgress.style.width = `${pct}%`;
        const remHours = nominal > 0 ? (liveTank / nominal) : 0;
        if (cardTankHoursRem) {
          if (liveTank === 0) {
            cardTankHoursRem.innerHTML = `<span style="color: var(--text-muted);">вистачить на 0 год (бак порожній)</span>`;
          } else {
            cardTankHoursRem.innerHTML = `вистачить на ~<b>${remHours.toFixed(1).replace('.', ',')}</b> год (при ${nominal} л/год)`;
          }
        }
      }
    }

    // 3. Live Maintenance countdown
    const cardMaintRem = document.getElementById('cardMaintRem');
    const cardMaintSub = document.getElementById('cardMaintSub');
    if (cardMaintRem && cachedMaintenanceSchedule) {
      const dueH = cachedMaintenanceSchedule.next_due_hours;
      const remMaint = dueH - liveHours;
      cardMaintRem.innerHTML = `${remMaint.toFixed(1).replace('.', ',')} <small style="font-size: 0.9rem;">год</small>`;
      if (remMaint <= 0) {
        cardMaintRem.style.color = '#ef4444';
        if (cardMaintSub) cardMaintSub.innerText = 'ПОТРІБНЕ ТО!';
      } else {
        cardMaintRem.style.color = 'inherit';
        if (cardMaintSub) cardMaintSub.innerText = `план: ${dueH.toFixed(0)} год`;
      }
    }
  }
}

function startRunStopwatch() {
  if (runTimerInterval) clearInterval(runTimerInterval);
  updateRunStopwatchDisplay();
  runTimerInterval = setInterval(updateRunStopwatchDisplay, 1000);
}

function stopRunStopwatch() {
  if (runTimerInterval) {
    clearInterval(runTimerInterval);
    runTimerInterval = null;
  }
}

// Start / Stop Main Button Handler with Debounce and Safeguards
document.getElementById('mainActionBtn').addEventListener('click', async () => {
  if (!currentGenerator) return;
  if (isViewerOnly() || !hasPermission('generator:start')) {
    showToast('Керування генератором недоступне для ролі Спостерігач', 'warning');
    return;
  }

  const btn = document.getElementById('mainActionBtn');
  if (btn.disabled || btn.dataset.busy === 'true') return;

  if (currentGenerator.status === 'RUNNING') {
    // Open Stop Modal
    const endHoursInput = document.getElementById('stopEndHours');
    endHoursInput.value = '';
    endHoursInput.min = currentGenerator.current_operating_hours;

    if (activeRun && activeRun.start_time) {
      document.getElementById('stopStartTimeDisplay').innerText = formatDateTime(activeRun.start_time);
      updateRunStopwatchDisplay();
    } else {
      document.getElementById('stopStartTimeDisplay').innerText = '-';
      document.getElementById('stopDurationDisplay').innerText = '00:00:00';
      document.getElementById('stopEstFuelDisplay').innerText = '0.000 л';
    }
    openModal('modalStopGen');
  } else {
    // Safeguard: Maintenance Overdue Warning modal
    if (currentGenerator.status === 'MAINTENANCE_REQUIRED') {
      const confirmStart = confirm(
        '⚠️ УВАГА: Регламент технічного обслуговування (ТО) цього генератора прострочено!\n\nВи впевнені, що хочете запустити генератор до виконання регламентних робіт?'
      );
      if (!confirmStart) return;
    }

    // Debounce & start generator
    btn.disabled = true;
    btn.dataset.busy = 'true';
    const oldText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Запуск...';

    try {
      await api('/generator/start', {
        method: 'POST',
        body: JSON.stringify({ generator_id: currentGeneratorId, fuel_level_l: currentGenerator.fuel_tank_level_l })
      });
      showToast('Генератор успішно запущено!', 'success');
      await loadAllData();
    } catch (_) {
    } finally {
      btn.disabled = false;
      btn.dataset.busy = 'false';
      btn.innerHTML = oldText;
    }
  }
});

// Stop Form Submit
// Manual Run Entry (Offline/Paper Log)
window.openManualRunModal = function() {
  if (isViewerOnly() || !hasPermission('generator:start')) {
    showToast('Ручне внесення мотогодин недоступне для ролі Спостерігач', 'warning');
    return;
  }
  if (!currentGenerator) {
    showToast('Будь ласка, спочатку оберіть генератор', 'warning');
    return;
  }
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const fmtLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  // Default: start 2 hours ago, end 1 hour ago
  const startD = new Date(now.getTime() - 2 * 3600 * 1000);
  const endD = new Date(now.getTime() - 1 * 3600 * 1000);

  const startInput = document.getElementById('manualRunStartTime');
  const endInput = document.getElementById('manualRunEndTime');
  if (startInput) startInput.value = fmtLocal(startD);
  if (endInput) endInput.value = fmtLocal(endD);

  const startHoursInput = document.getElementById('manualRunStartHours');
  if (startHoursInput) {
    startHoursInput.value = currentGenerator.current_operating_hours != null ? currentGenerator.current_operating_hours.toFixed(1) : '0.0';
  }

  const endHoursInput = document.getElementById('manualRunEndHours');
  if (endHoursInput) {
    endHoursInput.value = '';
    endHoursInput.removeAttribute('data-manual-edited');
  }

  const fuelInput = document.getElementById('manualRunFuelConsumed');
  if (fuelInput) fuelInput.value = '';

  const noteInput = document.getElementById('manualRunNote');
  if (noteInput) noteInput.value = '';

  calculateManualRunEstimates();
  openModal('modalManualRun');
};

window.calculateManualRunEstimates = function() {
  const startVal = document.getElementById('manualRunStartTime')?.value;
  const endVal = document.getElementById('manualRunEndTime')?.value;
  const durTextEl = document.getElementById('manualRunDurationText');
  const fuelTextEl = document.getElementById('manualRunFuelText');
  const endHoursEl = document.getElementById('manualRunEndHours');
  const startHoursEl = document.getElementById('manualRunStartHours');

  if (!startVal || !endVal || !durTextEl || !fuelTextEl) return;

  const startD = new Date(startVal);
  const endD = new Date(endVal);

  if (isNaN(startD.getTime()) || isNaN(endD.getTime()) || endD <= startD) {
    durTextEl.innerText = '00:00:00 (0.0 год)';
    durTextEl.style.color = '#ef4444';
    fuelTextEl.innerText = '~0.0 л';
    return;
  }

  durTextEl.style.color = '#38bdf8';
  const diffSec = Math.floor((endD.getTime() - startD.getTime()) / 1000);
  const diffHours = diffSec / 3600.0;
  const formatted = formatDuration(diffSec);

  durTextEl.innerText = `${formatted} (${diffHours.toFixed(2)} год)`;

  const consumptionRate = (currentGenerator && currentGenerator.nominal_consumption_l_per_h) || 2.2;
  const estFuel = diffHours * consumptionRate;
  fuelTextEl.innerText = `~${estFuel.toFixed(2)} л (при ${consumptionRate.toFixed(2)} л/год)`;

  if (startHoursEl && endHoursEl && !endHoursEl.getAttribute('data-manual-edited')) {
    const startH = parseFloat(startHoursEl.value) || 0.0;
    endHoursEl.value = (startH + diffHours).toFixed(1);
  }
};

document.getElementById('manualRunEndHours')?.addEventListener('input', () => {
  document.getElementById('manualRunEndHours')?.setAttribute('data-manual-edited', 'true');
});

document.getElementById('manualRunForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!currentGeneratorId) {
    showToast('Генератор не обрано', 'error');
    return;
  }
  const startVal = document.getElementById('manualRunStartTime').value;
  const endVal = document.getElementById('manualRunEndTime').value;
  if (!startVal || !endVal) {
    showToast('Вкажіть час запуску та зупинки', 'warning');
    return;
  }
  const startD = new Date(startVal);
  const endD = new Date(endVal);
  if (endD <= startD) {
    showToast('Час зупинки повинен бути пізнішим за час запуску', 'warning');
    return;
  }

  const startHVal = document.getElementById('manualRunStartHours').value;
  const endHVal = document.getElementById('manualRunEndHours').value;
  const fuelVal = document.getElementById('manualRunFuelConsumed').value;
  const noteVal = document.getElementById('manualRunNote').value.trim();

  const body = {
    generator_id: currentGeneratorId,
    start_time: startD.toISOString(),
    end_time: endD.toISOString(),
    start_hours: startHVal !== '' && !isNaN(parseFloat(startHVal)) ? parseFloat(startHVal) : null,
    end_hours: endHVal !== '' && !isNaN(parseFloat(endHVal)) ? parseFloat(endHVal) : null,
    fuel_consumed_l: fuelVal !== '' && !isNaN(parseFloat(fuelVal)) ? parseFloat(fuelVal) : null,
    note: noteVal || 'Внесено вручну (запис з паперового журналу)'
  };

  try {
    const res = await api('/generator/manual-run', {
      method: 'POST',
      body: JSON.stringify(body)
    });
    closeModal('modalManualRun');
    const durText = res.duration_formatted || `${res.duration_hours} год`;
    const fuelText = res.calculated_consumption_l != null ? `${res.calculated_consumption_l.toFixed(1)} л` : '-';
    showToast(`Сеанс роботи успішно внесено в журнал! Час: ${durText}, витрата: ${fuelText}`, 'success');
    loadGeneratorData();
    loadAllData();
    loadRecentRuns();
    if (typeof loadRunsTable === 'function') loadRunsTable();
  } catch (err) {
    showToast(err.message || 'Помилка при збереженні сеансу роботи', 'error');
  }
});


document.getElementById('stopGenForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  if (submitBtn && submitBtn.disabled) return;

  const endHoursVal = document.getElementById('stopEndHours').value;
  const endHours = endHoursVal !== '' && !isNaN(parseFloat(endHoursVal)) ? parseFloat(endHoursVal) : null;
  const endFuelVal = document.getElementById('stopEndFuel').value;
  const endFuel = endFuelVal !== '' && !isNaN(parseFloat(endFuelVal)) ? parseFloat(endFuelVal) : null;
  const note = document.getElementById('stopNote').value;

  let forceConfirm = false;

  // Typo Safeguard check on frontend
  if (endHours !== null && currentGenerator) {
    const startH = activeRun?.start_hours ?? currentGenerator.current_operating_hours;
    const deltaH = endHours - startH;
    let elapsedH = 0;
    if (activeRun?.start_time) {
      elapsedH = Math.max(0, (Date.now() - new Date(activeRun.start_time).getTime()) / 3600000);
    }

    const isSuspicious = (deltaH > 14.0) || (elapsedH > 0.02 && Math.abs(deltaH - elapsedH) > 2.0);
    if (isSuspicious) {
      const confirmed = confirm(
        `⚠️ Запобіжник опечатки мотогодин!\n\n` +
        `Напрацювання за введеним лічильником: ${deltaH.toFixed(2)} год.\n` +
        `Час роботи за таймером: ${elapsedH.toFixed(2)} год.\n\n` +
        `Різниця суттєва. Можлива опечатка (зайва цифра або пропущена крапка)!\n` +
        `Ви впевнені, що показник ${endHours} правильний?`
      );
      if (!confirmed) {
        return;
      }
      forceConfirm = true;
    }
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Зупинка...';
  }

  try {
    const res = await api('/generator/stop', {
      method: 'POST',
      body: JSON.stringify({
        generator_id: currentGeneratorId,
        end_hours: endHours,
        end_fuel_level_l: endFuel,
        note: note,
        force_confirm: forceConfirm
      })
    });
    closeModal('modalStopGen');
    stopRunStopwatch();
    const durText = res.duration_formatted || formatDuration(res.duration_seconds) || `${res.duration_hours} год`;
    const fuelText = res.calculated_consumption_l != null ? `${res.calculated_consumption_l} л` : '-';
    showToast(`Генератор зупинено! Відпрацьовано: ${durText}, розхід: ${fuelText}`, 'success');
    loadAllData();
  } catch (err) {
    showToast(err.message || 'Помилка при зупинці генератора', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = 'Зупинити генератор';
    }
  }
});

// 2. Fuel Management
let cachedFuelPrices = null;

async function fetchFuelPricesCache() {
  try {
    cachedFuelPrices = await api('/system/fuel-prices');
  } catch (_) {}
  return cachedFuelPrices;
}

window.updateReceiptPriceEstimate = function () {
  const hintEl = document.getElementById('recAutoPriceHint');
  if (!hintEl) return;
  const fuelType = document.getElementById('recFuelType')?.value || 'А-95';
  const litersVal = parseFloat(document.getElementById('recLiters')?.value || '0');
  const rawCost = document.getElementById('recCostTotal')?.value?.trim() || '';
  const costVal = rawCost ? parseFloat(rawCost) : 0;

  const wogFallbacks = {
    'А-95': 92.90,
    'А-95 Mustang': 95.90,
    'ДП': 103.50,
    'ДП Mustang+': 106.50,
    'ГАЗ': 52.50,
    'А-92': 89.90
  };
  const fuelEntry = cachedFuelPrices?.fuels?.[fuelType];
  const unitPrice = fuelEntry ? Number(fuelEntry.effective_price) : (wogFallbacks[fuelType] || 92.90);
  const srcName = fuelEntry ? fuelEntry.source_name : 'АЗК WOG (wog.ua/ua/fuels/)';

  if (costVal > 0 && litersVal > 0) {
    const manualPerL = (costVal / litersVal).toFixed(2);
    hintEl.innerHTML = `✅ Сума вказана за чеком: <b style="color:#4ade80;">${costVal.toFixed(2)} грн</b> (виходить <b>${manualPerL} грн/л</b>)`;
  } else if (litersVal > 0) {
    const autoSum = (litersVal * unitPrice).toFixed(2);
    hintEl.innerHTML = `💡 Авторозрахунок <b>${escapeHtml(fuelType)}</b>: <b>${unitPrice.toFixed(2)} грн/л</b> <span style="color:var(--text-muted);">(${escapeHtml(srcName)})</span> → буде нараховано: <b style="color:#4ade80;">${autoSum} грн</b>`;
  } else {
    hintEl.innerHTML = `💡 Діюча ціна <b>${escapeHtml(fuelType)}</b>: <b>${unitPrice.toFixed(2)} грн/л</b> <span style="color:var(--text-muted);">(${escapeHtml(srcName)})</span>. Введіть літри для авторозрахунку суми.`;
  }
};

async function setupReceiptModal() {
  try {
    const [facilities] = await Promise.all([
      api('/facilities'),
      fetchFuelPricesCache()
    ]);
    const facSel = document.getElementById('recFacility');
    if (facSel && facilities && facilities.length > 0) {
      facSel.innerHTML = facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
      if (currentFacilityId && facilities.some(f => f.id === currentFacilityId)) {
        facSel.value = currentFacilityId;
      }
    }
    await updateReceiptStocks();
    updateReceiptPriceEstimate();
  } catch (err) {
    console.warn('setupReceiptModal error:', err);
  }
}

async function updateReceiptStocks() {
  const facSel = document.getElementById('recFacility');
  const stockSel = document.getElementById('recStock');
  if (!facSel || !stockSel) return;
  const facId = facSel.value;
  try {
    const stocks = await api(`/fuel/stocks?facility_id=${encodeURIComponent(facId)}`);
    if (!stocks || stocks.length === 0) {
      stockSel.innerHTML = '<option value="">(Немає складів — створіть новий склад)</option>';
    } else {
      stockSel.innerHTML = stocks.map(s => `<option value="${Number(s.id)}">${escapeHtml(s.name)} (залишок: ${s.current_balance_l.toFixed(1)} л)</option>`).join('');
    }
  } catch (_) {
    stockSel.innerHTML = '<option value="">(Помилка завантаження)</option>';
  }
}

document.getElementById('recFacility')?.addEventListener('change', updateReceiptStocks);

async function setupNewStockModal() {
  try {
    const facilities = await api('/facilities');
    const facSel = document.getElementById('newStockFacility');
    if (facSel && facilities && facilities.length > 0) {
      facSel.innerHTML = facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
      if (currentFacilityId && facilities.some(f => f.id === currentFacilityId)) {
        facSel.value = currentFacilityId;
      }
    }
  } catch (err) {
    console.warn('setupNewStockModal error:', err);
  }
}

async function setupTransferModal() {
  try {
    const stockSel = document.getElementById('transStock');
    const genSel = document.getElementById('transGenerator');
    const qFac = currentFacilityId ? `?facility_id=${encodeURIComponent(currentFacilityId)}` : '';

    const stocks = await api(`/fuel/stocks${qFac}`);
    if (stockSel) {
      if (!stocks || stocks.length === 0) {
        stockSel.innerHTML = '<option value="">(Немає доступних складів)</option>';
      } else {
        stockSel.innerHTML = stocks.map(s => `<option value="${Number(s.id)}">${escapeHtml(s.name)} (${s.current_balance_l.toFixed(1)} л)</option>`).join('');
      }
    }

    const gens = await api(`/generator/list${qFac}`);
    if (genSel) {
      if (!gens || gens.length === 0) {
        genSel.innerHTML = '<option value="">(Немає генераторів)</option>';
      } else {
        genSel.innerHTML = gens.map(g => `<option value="${Number(g.id)}">${escapeHtml(g.name)} (${escapeHtml(g.model)}, в баку: ${g.fuel_tank_level_l.toFixed(1)} л)</option>`).join('');
        if (currentGeneratorId && gens.some(g => g.id === currentGeneratorId)) {
          genSel.value = currentGeneratorId;
        }
      }
    }
  } catch (err) {
    console.warn('setupTransferModal error:', err);
  }
}

async function loadFuelSummary() {
  if (isViewerOnly() || !hasPermission('fuel:view')) return;
  try {
    const params = [];
    if (currentFacilityId) params.push(`facility_id=${encodeURIComponent(currentFacilityId)}`);
    if (currentGeneratorId) params.push(`generator_id=${encodeURIComponent(currentGeneratorId)}`);
    const q = params.length ? '?' + params.join('&') : '';

    const s = await api(`/fuel/summary${q}`);
    document.getElementById('cardStock').innerText = s.warehouse_balance_l.toFixed(1).replace('.', ',');
    document.getElementById('fuelStockBal').innerText = formatLiters(s.warehouse_balance_l);
    document.getElementById('fuelTankBal').innerText = formatLiters(s.tank_balance_l);
    document.getElementById('fuelTotalBought').innerText = formatLiters(s.total_received_l);
    document.getElementById('fuelTotalSpent').innerText = formatMoney(s.total_spent_uah);
    document.getElementById('fuelAvgPrice').innerText = formatPricePerLiter(s.avg_price_per_liter);
  } catch (_) {}
}

async function loadFuelData() {
  await loadFuelSummary();
  try {
    const qFac = currentFacilityId ? `?facility_id=${encodeURIComponent(currentFacilityId)}` : '';

    // Stocks Table
    const stocks = await api(`/fuel/stocks${qFac}`);
    const sTbody = document.querySelector('#fuelStocksTable tbody');
    if (sTbody) {
      sTbody.innerHTML = stocks.map((s) => `
        <tr>
          <td>#${Number(s.id)}</td>
          <td><b>${escapeHtml(s.name)}</b></td>
          <td>${escapeHtml(s.facility_name || '-')}</td>
          <td><span class="badge badge-stopped">${escapeHtml(s.fuel_type)}</span></td>
          <td><b style="color:#38bdf8;">${formatLiters(s.current_balance_l)}</b></td>
          <td>${formatDateTime(s.updated_at)}</td>
          <td style="white-space:nowrap; text-align:center;">
            ${hasPermission('fuel:configure') ? `
              <button class="btn-action" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.8rem; display: inline-flex;" onclick="openEditStockModal(${Number(s.id)}, '${escapeHtml(s.name).replace(/'/g, "\\'")}', '${escapeHtml(s.fuel_type).replace(/'/g, "\\'")}')" title="Редагувати склад">✏️</button>
              <button class="btn-action" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.8rem; display: inline-flex; border-color: #ef4444; color: #f87171;" onclick="deleteFuelStock(${Number(s.id)}, '${escapeHtml(s.name).replace(/'/g, "\\'")}', ${Number(s.current_balance_l)})" title="Видалити склад">🗑️</button>
            ` : `
              <button class="btn-action btn-disabled-role" disabled style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.8rem; display: inline-flex; opacity: 0.35; cursor: not-allowed;" title="Редагування складу доступне лише Адміністратору">✏️</button>
              <button class="btn-action btn-disabled-role" disabled style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.8rem; display: inline-flex; opacity: 0.35; cursor: not-allowed; border-color: rgba(255,255,255,0.15); color: var(--text-muted);" title="Видалення складу доступне лише Адміністратору">🗑️</button>
            `}
          </td>
        </tr>
      `).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--text-muted)">Складів ГСМ не знайдено</td></tr>';
    }

    // Receipts Table
    const receipts = await api(`/fuel/receipts${qFac}`);
    const rTbody = document.querySelector('#fuelReceiptsTable tbody');
    if (rTbody) {
      rTbody.innerHTML = receipts.map((r) => `
        <tr>
          <td>${formatDateTime(r.created_at)}</td>
          <td>${escapeHtml(r.facility_name || '-')}</td>
          <td><b>${escapeHtml(r.stock_name || '-')}</b></td>
          <td><b>${formatLiters(r.liters)}</b></td>
          <td>${formatMoney(r.cost_total)}</td>
          <td>${formatPricePerLiter(r.price_per_liter)}</td>
          <td>${escapeHtml(r.driver_name)}</td>
          <td>${escapeHtml(r.receipt_number)}</td>
          <td>${escapeHtml(r.user_name || '-')}</td>
        </tr>
      `).join('') || '<tr><td colspan="9" style="text-align:center; color:var(--text-muted)">Надходжень не зареєстровано</td></tr>';
    }

    // Transfers Table
    const transfers = await api(`/fuel/transfers${qFac}`);
    const tTbody = document.querySelector('#fuelTransfersTable tbody');
    if (tTbody) {
      tTbody.innerHTML = transfers.map((t) => `
        <tr>
          <td>${formatDateTime(t.created_at)}</td>
          <td>${escapeHtml(t.stock_name || '-')}</td>
          <td><b>${escapeHtml(t.generator_name || '-')}</b></td>
          <td><b style="color:#38bdf8;">+${formatLiters(t.liters)}</b></td>
          <td>${formatLiters(t.source_balance_before)} → ${formatLiters(t.source_balance_after)}</td>
          <td>${formatLiters(t.tank_balance_before)} → ${formatLiters(t.tank_balance_after)}</td>
          <td>${escapeHtml(t.comment || '-')}</td>
          <td>${escapeHtml(t.user_name || '-')}</td>
        </tr>
      `).join('') || '<tr><td colspan="8" style="text-align:center; color:var(--text-muted)">Заправок не зареєстровано</td></tr>';
    }
  } catch (_) {}
}

// Receipt Form Submit with Volume and Price Safeguards
document.getElementById('receiptForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  if (submitBtn && submitBtn.disabled) return;

  const stockVal = document.getElementById('recStock').value;
  if (!stockVal) {
    showToast('Будь ласка, оберіть склад ГСМ або створіть його', 'error');
    return;
  }
  const rawCost = document.getElementById('recCostTotal').value.trim();
  const parsedCost = rawCost ? parseFloat(rawCost) : null;
  const liters = parseFloat(document.getElementById('recLiters').value);

  let forceConfirm = false;

  // Safeguard: Fuel Volume & Price Sanity Check
  if (liters > 1000.0) {
    const confirmed = confirm(
      `⚠️ Запобіжник об'єму палива!\n\n` +
      `Вказано ${liters.toFixed(1)} л палива (більше 1000 л).\n` +
      `Перевірте, чи немає опечатки в кількості літрів.\n\nПродовжити збереження?`
    );
    if (!confirmed) return;
    forceConfirm = true;
  }

  if (parsedCost && parsedCost > 0 && liters > 0) {
    const pricePerL = parsedCost / liters;
    if (pricePerL < 15.0 || pricePerL > 250.0) {
      const confirmed = confirm(
        `⚠️ Запобіжник вартості палива!\n\n` +
        `Розрахункова ціна становить ${pricePerL.toFixed(2)} грн/л (незвичний діапазон).\n` +
        `Перевірте загальну суму чека (${parsedCost.toFixed(2)} грн) та літри (${liters.toFixed(1)} л).\n\n` +
        `Зберегти чек з цією сумою?`
      );
      if (!confirmed) return;
      forceConfirm = true;
    }
  }

  const body = {
    facility_id: parseInt(document.getElementById('recFacility').value),
    stock_id: parseInt(stockVal),
    liters: liters,
    cost_total: parsedCost && parsedCost > 0 ? parsedCost : null,
    driver_name: document.getElementById('recDriver').value,
    receipt_number: document.getElementById('recNumber').value,
    fuel_type: document.getElementById('recFuelType').value,
    comment: document.getElementById('recComment').value,
    force_confirm: forceConfirm
  };

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Збереження...';
  }

  try {
    const saved = await api('/fuel/receipt', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalReceipt');
    document.getElementById('recLiters').value = '';
    document.getElementById('recCostTotal').value = '';
    document.getElementById('recComment').value = '';
    showToast(
      `Паливо оприбутковано: +${Number(saved.liters).toFixed(1)} л на суму ${Number(saved.cost_total).toFixed(2)} грн (${Number(saved.price_per_liter).toFixed(2)} грн/л)!`,
      'success'
    );
    loadFuelData();
    loadFuelSummary();
  } catch (err) {
    showToast(err.message || 'Помилка оприбуткування палива', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = 'Зберегти надходження';
    }
  }
});

// Create New Fuel Stock Form Submit
document.getElementById('newStockForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const facilityId = parseInt(document.getElementById('newStockFacility').value) || currentFacilityId || 1;
  const name = document.getElementById('newStockName').value.trim();
  const fuelType = document.getElementById('newStockFuelType').value;
  const initBal = parseFloat(document.getElementById('newStockInitialBalance').value) || 0.0;

  try {
    const created = await api('/fuel/stock/new', {
      method: 'POST',
      body: JSON.stringify({
        facility_id: facilityId,
        name: name,
        fuel_type: fuelType,
        initial_balance_l: initBal
      })
    });
    closeModal('modalNewStock');
    showToast(`Склад ГСМ "${created.name}" успішно створено!`, 'success');
    document.getElementById('newStockName').value = '';
    document.getElementById('newStockInitialBalance').value = '0.0';
    loadFuelData();
    loadFuelSummary();
  } catch (_) {}
});

// Edit Fuel Stock Modal and Form Submit
window.openEditStockModal = function(id, name, fuelType) {
  document.getElementById('editStockId').value = id;
  document.getElementById('editStockName').value = name;
  document.getElementById('editStockFuelType').value = fuelType || 'А-95';
  openModal('modalEditStock');
};

const editStockForm = document.getElementById('editStockForm');
if (editStockForm) {
  editStockForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('editStockId').value;
    const name = document.getElementById('editStockName').value.trim();
    const fuelType = document.getElementById('editStockFuelType').value;
    try {
      await api(`/fuel/stocks/${encodeURIComponent(id)}`, {
        method: 'PUT',
        body: JSON.stringify({ name, fuel_type: fuelType })
      });
      closeModal('modalEditStock');
      showToast('Склад ГСМ успішно оновлено!', 'success');
      loadFuelData();
      loadFuelSummary();
    } catch (_) {}
  });
}

window.deleteFuelStock = async function(id, name, balance) {
  let msg = `Ви впевнені, що хочете видалити склад "${name}"?`;
  if (balance > 0) {
    msg += `\r\n\r\nУвага: на складі є залишок ${balance.toFixed(1)} л. Його буде автоматично перенесено на основний склад об'єкта, щоб уникнути втрати даних обліку.`;
  }
  if (!confirm(msg)) return;
  try {
    const res = await api(`/fuel/stocks/${encodeURIComponent(id)}`, { method: 'DELETE' });
    showToast(res.detail || 'Склад ГСМ успішно видалено!', 'success');
    loadFuelData();
    loadFuelSummary();
  } catch (_) {}
};

// Transfer Form Submit
document.getElementById('transferForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const stockVal = document.getElementById('transStock').value;
  const genVal = document.getElementById('transGenerator').value;
  if (!stockVal) {
    showToast('Будь ласка, оберіть склад ГСМ', 'error');
    return;
  }
  if (!genVal) {
    showToast('Будь ласка, оберіть генератор', 'error');
    return;
  }
  const body = {
    generator_id: parseInt(genVal),
    stock_id: parseInt(stockVal),
    facility_id: currentFacilityId || null,
    liters: parseFloat(document.getElementById('transLiters').value),
    comment: document.getElementById('transComment').value
  };

  try {
    await api('/fuel/transfer', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalTransfer');
    showToast('Бак генератора успішно заправлено!', 'success');
    loadAllData();
    loadFuelData();
  } catch (_) {}
});

// 3. Maintenance (ТО)
async function loadMaintenanceSummary() {
  if (isViewerOnly() || !hasPermission('maintenance:view')) return;
  try {
    if (!currentGeneratorId) {
      document.getElementById('cardMaintRem').innerHTML = `0.0 <small style="font-size:0.9rem;">год</small>`;
      document.getElementById('cardMaintSub').innerText = `генератор не вибрано`;
      document.getElementById('maintInterval').innerText = `-`;
      document.getElementById('maintLast').innerText = `-`;
      document.getElementById('maintNext').innerText = `-`;
      document.getElementById('maintRemaining').innerText = `-`;
      document.getElementById('maintProgress').style.width = `0%`;
      return;
    }
    const q = `?generator_id=${currentGeneratorId}`;
    const m = await api(`/maintenance/schedule${q}`);
    cachedMaintenanceSchedule = m;
    document.getElementById('cardMaintRem').innerHTML = `${m.hours_remaining.toFixed(1).replace('.', ',')} <small style="font-size:0.9rem;">год</small>`;
    document.getElementById('cardMaintSub').innerText = `план: ${formatHoursCounter(m.next_due_hours)}`;
    document.getElementById('maintInterval').innerText = `${formatHoursCounter(m.interval_hours)}`;
    document.getElementById('maintLast').innerText = `${formatHoursCounter(m.last_performed_hours)}`;
    document.getElementById('maintNext').innerText = `${formatHoursCounter(m.next_due_hours)}`;
    document.getElementById('maintRemaining').innerText = `${formatHoursCounter(m.hours_remaining)}`;

    const remSpan = document.getElementById('maintRemaining');
    if (m.is_overdue) {
      remSpan.style.color = '#ef4444';
      remSpan.innerText += ' (ПРОСТРОЧЕНО!)';
    } else if (m.is_due) {
      remSpan.style.color = '#f59e0b';
      remSpan.innerText += ' (СКОРО ТО)';
    } else {
      remSpan.style.color = '#22c55e';
    }

    const workedInCycle = m.current_operating_hours - m.last_performed_hours;
    const progressPct = Math.min(100, Math.max(0, Math.round((workedInCycle / m.interval_hours) * 100)));
    document.getElementById('maintProgress').style.width = `${progressPct}%`;
  } catch (_) {}
}

window.recalculateMaintenanceSchedule = async function() {
  try {
    const q = currentGeneratorId ? `?generator_id=${currentGeneratorId}` : '';
    const m = await api(`/maintenance/schedule/recalculate${q}`, { method: 'POST' });
    showToast(`Графік ТО перераховано! Наступне ТО: ${m.next_due_hours} год, залишилося: ${m.hours_remaining} год`, 'success');
    await loadMaintenanceSummary();
    await loadMaintenanceData();
  } catch (err) {
    showToast(err.message, 'error');
  }
};

async function loadMaintenanceData() {
  await loadMaintenanceSummary();
  try {
    const q = currentGeneratorId ? `?generator_id=${encodeURIComponent(currentGeneratorId)}` : '';
    const records = await api(`/maintenance/records${q}`);
    const tbody = document.querySelector('#maintenanceHistoryTable tbody');
    tbody.innerHTML = records.map((r) => `
      <tr>
        <td>${formatDateTime(r.created_at)}</td>
        <td><span class="badge ${r.maintenance_type === 'SCHEDULED' ? 'badge-running' : 'badge-stopped'}">${r.maintenance_type === 'SCHEDULED' ? 'Регламентне' : 'Проміжне'}</span></td>
        <td><b>${formatHoursCounter(r.operating_hours)}</b></td>
        <td>${escapeHtml(r.work_description)}</td>
        <td>${escapeHtml(r.consumables_used || '-')}</td>
        <td>${formatMoney(r.cost)}</td>
        <td>${escapeHtml(r.user_name || '-')}</td>
      </tr>
    `).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--text-muted)">Записів ТО не знайдено</td></tr>';
  } catch (_) {}
}

// Maintenance Form Submit
document.getElementById('maintForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    generator_id: currentGeneratorId,
    maintenance_type: document.getElementById('maintType').value,
    work_description: document.getElementById('maintWork').value,
    consumables_used: document.getElementById('maintConsumables').value,
    cost: parseFloat(document.getElementById('maintCost').value) || 0.0
  };

  try {
    await api('/maintenance/record', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalMaintenance');
    showToast('ТО успішно зафіксовано в системі!', 'success');
    loadAllData();
  } catch (_) {}
});

// 4. Faults
async function loadFaultsData() {
  try {
    const qGen = currentGeneratorId ? `?generator_id=${encodeURIComponent(currentGeneratorId)}` : '';
    const faults = await api(`/faults${qGen}`);
    const tbody = document.querySelector('#faultsTable tbody');
    const prioMap = { CRITICAL: 'Критичний', HIGH: 'Високий', MEDIUM: 'Середній', LOW: 'Низький' };
    const statMap = {
      NEW: 'Нова',
      ACCEPTED: 'Прийнято',
      OPEN: 'Відкрито',
      IN_PROGRESS: 'В роботі',
      PENDING: 'В очікуванні',
      RESOLVED: 'Усунено',
      CLOSED: 'Закрито'
    };
    tbody.innerHTML = faults.map((f) => {
      const isResolved = f.status === 'RESOLVED' || f.status === 'CLOSED';
      const resolvedInfo = isResolved
        ? `Усунув: ${escapeHtml(f.resolved_by_name || 'Оператор')}${f.resolution_notes ? ' | ' + escapeHtml(f.resolution_notes) : ''}`
        : '';
      return `
        <tr>
          <td>#${Number(f.id)}</td>
          <td><span class="badge ${f.priority === 'CRITICAL' ? 'badge-faulty' : 'badge-maintenance'}">${escapeHtml(prioMap[f.priority] || f.priority)}</span></td>
          <td><span class="badge ${isResolved ? 'badge-running' : 'badge-stopped'}" title="${resolvedInfo}">${escapeHtml(statMap[f.status] || f.status)}</span></td>
          <td><b>${escapeHtml(f.title)}</b></td>
          <td>${escapeHtml(f.description)}</td>
          <td>${formatHoursCounter(f.operating_hours)}</td>
          <td>${formatDateOnly(f.created_at)}</td>
          <td>
            ${!isResolved ? (hasPermission('faults:manage') ? `
              <button class="btn-action" onclick="openResolveFaultModal(${Number(f.id)}, '${escapeHtml(f.title).replace(/'/g, "\\'")}')" style="background:#22c55e; border:none; color:white; border-radius:4px; padding:0.35rem 0.65rem; cursor:pointer; font-size:0.8rem; font-weight:600;" title="Усунути несправність">Усунути</button>
            ` : `
              <button class="btn-action btn-disabled-role" disabled style="background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.15); color:var(--text-muted); border-radius:4px; padding:0.35rem 0.65rem; cursor:not-allowed; font-size:0.8rem; opacity:0.45;" title="Усунення дефектів доступне лише Адміністратору">Усунути (тільки Адмін 🔒)</button>
            `) : `<span style="color:#22c55e; font-size:0.85rem;" title="${resolvedInfo}">✓ Усунено</span>`}
          </td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="8" style="text-align:center; color:var(--text-muted)">Несправностей немає</td></tr>';
  } catch (err) {
    console.warn('loadFaultsData error:', err);
  }
}

window.openResolveFaultModal = function(id, title) {
  const idEl = document.getElementById('resolveFaultId');
  const infoEl = document.getElementById('resolveFaultInfo');
  const notesEl = document.getElementById('resolveFaultNotes');
  if (idEl) idEl.value = id;
  if (infoEl) infoEl.innerText = `#${id}: ${title}`;
  if (notesEl) notesEl.value = '';
  openModal('modalResolveFault');
};

const resolveFaultForm = document.getElementById('resolveFaultForm');
if (resolveFaultForm) {
  resolveFaultForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('resolveFaultId').value;
    const notes = document.getElementById('resolveFaultNotes').value.trim();
    try {
      await api(`/faults/${encodeURIComponent(id)}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: 'RESOLVED', resolution_notes: notes })
      });
      closeModal('modalResolveFault');
      showToast('Несправність успішно позначено як усунену!', 'success');
      loadFaultsData();
      loadGeneratorData();
      loadAllData();
    } catch (err) {
      showToast(err.message || 'Помилка при усуненні несправності', 'error');
    }
  });
}

window.resolveFault = async function(id) {
  window.openResolveFaultModal(id, '');
};

document.getElementById('faultForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    generator_id: currentGeneratorId || null,
    title: document.getElementById('faultTitle').value,
    priority: document.getElementById('faultPriority').value,
    description: document.getElementById('faultDesc').value
  };

  try {
    await api('/faults', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalFault');
    showToast('Заявку про несправність створено!', 'success');
    loadFaultsData();
    loadGeneratorData();
  } catch (err) {
    showToast(err.message || 'Помилка при створенні несправності', 'error');
  }
});

// 5. Runs History
async function loadRecentRuns() {
  try {
    const q = currentGeneratorId ? '&generator_id=' + encodeURIComponent(currentGeneratorId) : '';
    const runs = await api('/generator/runs?limit=5' + q);
    const tbody = document.querySelector('#recentRunsTable tbody');
    tbody.innerHTML = runs.map((r) => {
      const durText = r.duration_formatted || (r.duration_seconds != null ? formatDuration(r.duration_seconds) : (r.duration_hours ? formatHoursToHms(r.duration_hours) : '-'));
      const consText = r.calculated_consumption_l != null ? formatLiters(r.calculated_consumption_l) : '-';
      return `
        <tr>
          <td>${formatDateTime(r.start_time)}</td>
          <td>${formatHoursCounter(r.start_hours)}</td>
          <td>${r.end_hours != null ? formatHoursCounter(r.end_hours) : '<i>працює...</i>'}</td>
          <td><b style="color: #38bdf8; font-family: monospace;">${escapeHtml(durText)}</b></td>
          <td>${escapeHtml(consText)}</td>
          <td>${escapeHtml(r.user_name || '-')}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-muted)">Циклів не знайдено</td></tr>';
  } catch (_) {}
}

async function loadRunsData() {
  try {
    const q = currentGeneratorId ? '&generator_id=' + encodeURIComponent(currentGeneratorId) : '';
    const runs = await api('/generator/runs?limit=50' + q);
    const tbody = document.querySelector('#allRunsTable tbody');
    tbody.innerHTML = runs.map((r) => {
      const durText = r.duration_formatted || (r.duration_seconds != null ? formatDuration(r.duration_seconds) : (r.duration_hours ? formatHoursToHms(r.duration_hours) : '-'));
      const consText = r.calculated_consumption_l != null ? formatLiters(r.calculated_consumption_l) : '-';
      const startFuel = r.start_fuel_level_l != null ? formatLiters(r.start_fuel_level_l) : '-';
      const endFuel = r.end_fuel_level_l != null ? formatLiters(r.end_fuel_level_l) : '-';
      return `
        <tr>
          <td>#${Number(r.id)}</td>
          <td>${formatDateTime(r.start_time)}</td>
          <td>${r.end_time ? formatDateTime(r.end_time) : '<i>в процесі...</i>'}</td>
          <td>${formatHoursCounter(r.start_hours)}</td>
          <td>${r.end_hours != null ? formatHoursCounter(r.end_hours) : '-'}</td>
          <td><b style="color: #38bdf8; font-family: monospace;">${escapeHtml(durText)}</b></td>
          <td>${escapeHtml(consText)}</td>
          <td>${startFuel} → ${endFuel}</td>
          <td>${escapeHtml(r.user_name || '-')}</td>
          <td>${escapeHtml(r.note || '-')}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="10" style="text-align:center; color:var(--text-muted)">Записів не знайдено</td></tr>';
  } catch (_) {}
}

// 6. Audit & System Adjustments
const AUDIT_ACTION_MAP_UA = {
  // Auth
  'LOGIN': 'Вхід у систему',
  'LOGIN_FAIL': 'Невдала спроба входу',
  'LOGOUT': 'Вихід із системи',
  'AUTH_LOGIN_SUCCESS': 'Успішний вхід у систему',
  'AUTH_LOGIN_FAILED': 'Невдала спроба входу',
  'AUTH_LOGIN_LOCKED': 'Тимчасове блокування входу',
  'AUTH_LOGIN_BLOCKED': 'Блокування входу',
  'AUTH_LOGOUT': 'Вихід із системи',
  'USER_LOGIN': 'Вхід у систему',
  'USER_LOGOUT': 'Вихід із системи',

  // Generator
  'GENERATOR_START': 'Запуск генератора',
  'GENERATOR_STOP': 'Зупинка генератора',
  'GENERATOR_CREATE': 'Створення генератора',
  'GENERATOR_CREATED': 'Створення генератора',
  'GENERATOR_UPDATED': 'Оновлення параметрів генератора',
  'GENERATOR_DELETE': 'Видалення генератора',
  'GENERATOR_DELETED': 'Видалення генератора',
  'GENERATOR_MANUAL_RUN_ADDED': 'Ручне внесення мотогодин',
  'GENERATOR_QUICK_CONFIG': 'Швидке налаштування генератора',
  'GENERATOR_WIZARD_CONFIGURED': 'Первинне налаштування генератора',
  'WIZARD_SETUP': 'Налаштування через майстер',

  // Fuel
  'FUEL_RECEIPT': 'Оприбуткування палива на склад',
  'FUEL_RECEIPT_ADDED': 'Оприбуткування палива на склад',
  'FUEL_DISPENSE': 'Заправка генератора',
  'FUEL_TRANSFER_TO_TANK': 'Заправка бака зі складу',
  'FUEL_TRANSFERRED': 'Заправка бака зі складу',
  'FUEL_STOCK_CREATED': 'Створення складу ГСМ',
  'FUEL_STOCK_UPDATED': 'Оновлення складу ГСМ',
  'FUEL_STOCK_DELETED': 'Видалення складу ГСМ',
  'FUEL_PRICES_REFRESHED': 'Оновлення цін АЗК WOG',

  // Maintenance
  'MAINTENANCE_RECORD': 'Технічне обслуговування',
  'MAINTENANCE_RECORDED': 'Запис ТО',
  'MAINTENANCE_INTERMEDIATE': 'Проміжне ТО',
  'MAINTENANCE_SCHEDULED': 'Регламентне ТО',
  'MAINTENANCE_SCHEDULE_RECALCULATED': 'Перерахунок графіка ТО',
  'SCHEDULE_RECALCULATED': 'Перерахунок графіка ТО',

  // Faults
  'FAULT_CREATE': 'Реєстрація несправності',
  'FAULT_REPORTED': 'Повідомлення про несправність',
  'FAULT_UPDATE': 'Оновлення несправності',
  'FAULT_STATUS_UPDATED': 'Зміна статусу несправності',
  'FAULT_RESOLVED': 'Усунення несправності',

  // Adjustments & Settings
  'ADJUSTMENT': 'Коригування лічильників',
  'ADJUSTMENT_APPLIED': 'Системне коригування лічильників',
  'SYSTEM_ADJUSTMENT': 'Системне коригування лічильників',
  'NOTIFICATION_SETTINGS_UPDATED': 'Оновлення налаштувань сповіщень',
  'SETTINGS_UPDATE': 'Зміна налаштувань',
  'SYSTEM_SETTINGS_UPDATED': 'Оновлення налаштувань',
  'SYSTEM_SETTINGS_RESET': 'Скидання системних налаштувань',
  'SYSTEM_FACTORY_RESET': 'Скидання до заводських налаштувань',
  'SYSTEM_CLEAR_DATA': 'Очищення робочих даних',
  'SYSTEM_FACILITY_CLEAN': 'Очищення даних об\'єкта',
  'SYSTEM_REPORTS_CLEAN': 'Очищення звітів',
  'SYSTEM_RESET': 'Очищення / скидання даних',

  // Users
  'USER_CREATE': 'Створення користувача',
  'USER_CREATED': 'Створення користувача',
  'USER_UPDATE': 'Редагування користувача',
  'USER_UPDATED': 'Редагування користувача',
  'USER_DELETED': 'Видалення користувача',
  'USER_PASSWORD_RESET': 'Скидання пароля користувача',
  'USER_TOGGLE_ACTIVE': 'Зміна активності користувача',

  // Facility
  'FACILITY_CREATE': 'Створення об\'єкта',
  'FACILITY_CREATED': 'Створення об\'єкта',
  'FACILITY_UPDATED': 'Оновлення об\'єкта',
  'FACILITY_DELETED': 'Видалення об\'єкта',
  'FACILITY_SETTINGS_UPDATE': 'Оновлення налаштувань об\'єкта'
};

const AUDIT_ENTITY_MAP_UA = {
  'User': 'Користувач',
  'Facility': 'Об\'єкт',
  'Generator': 'Генератор',
  'FuelStock': 'Склад палива',
  'FuelReceipt': 'Оприбуткування палива',
  'FuelTransaction': 'Заправка палива',
  'FuelTransfer': 'Заправка палива',
  'GeneratorRun': 'Робота генератора',
  'MaintenanceRecord': 'Запис ТО',
  'MaintenanceSchedule': 'Графік ТО',
  'FaultReport': 'Несправність',
  'Fault': 'Несправність',
  'SystemSettings': 'Системні налаштування',
  'SystemSetting': 'Системні налаштування',
  'SystemAdjustment': 'Коригування',
  'System': 'Система'
};

const ADJUSTMENT_FIELD_MAP_UA = {
  'current_operating_hours': 'Мотогодини',
  'fuel_tank_level_l': 'Рівень у баку (л)',
  'status': 'Статус генератора',
  'nominal_consumption_l_per_h': 'Нормативний розхід (л/год)',
  'current_balance_l': 'Залишок на складі (л)',
  'interval_hours': 'Інтервал ТО (год)',
  'next_due_hours': 'Наступне ТО (мотогодини)',
  'last_performed_hours': 'Останнє ТО (мотогодини)',
  'name': 'Назва',
  'address': 'Адреса'
};

function formatAuditDetailsUa(detailsRaw, action) {
  if (!detailsRaw) return '-';
  let details = detailsRaw;
  if (typeof detailsRaw === 'string') {
    try {
      details = JSON.parse(detailsRaw);
    } catch (_) {
      return detailsRaw;
    }
  }
  if (!details || typeof details !== 'object') return String(details);

  // 1. Зупинка генератора
  if (details.duration_seconds !== undefined || details.calculated_consumption_l !== undefined) {
    const parts = [];
    if (details.duration_formatted) parts.push(`Час: ${details.duration_formatted}`);
    if (details.calculated_consumption_l !== undefined) parts.push(`Витрата: ${formatLiters(details.calculated_consumption_l)}`);
    if (details.end_fuel_level_l !== undefined) parts.push(`Залишок: ${formatLiters(details.end_fuel_level_l)}`);
    if (details.end_hours !== undefined) parts.push(`Мотогодини: ${formatHoursCounter(details.end_hours)}`);
    return parts.join(' | ') || JSON.stringify(details);
  }

  // 2. Запуск генератора
  if (details.start_hours !== undefined && details.start_fuel !== undefined) {
    return `Початкові мотогодини: ${formatHoursCounter(details.start_hours)} | Паливо в баку: ${formatLiters(details.start_fuel)}`;
  }

  // 3. Системне коригування
  if (details.field) {
    const fieldMap = {
      current_operating_hours: 'Мотогодини',
      fuel_tank_level_l: 'Бак генератора',
      stock_balance_l: 'Залишок на складі'
    };
    const fName = fieldMap[details.field] || details.field;
    let res = `Коригування '${fName}': ${details.old_value !== undefined ? details.old_value : '-'} ➔ ${details.new_value !== undefined ? details.new_value : '-'}`;
    if (details.reason) res += ` (${details.reason})`;
    return res;
  }

  // 4. Оприбуткування палива
  if (details.receipt_id !== undefined && details.cost_total !== undefined) {
    const stName = details.stock_name ? ` (${details.stock_name})` : '';
    const lit = details.liters !== undefined ? formatLiters(details.liters) : '-';
    const cst = details.cost_total !== undefined ? formatMoney(details.cost_total) : '-';
    return `Оприбутковано ${lit} на суму ${cst}${stName}`;
  }

  // 5. Заправка в бак
  if (details.liters !== undefined && (details.stock_before !== undefined || details.tank_before !== undefined)) {
    return `Заправлено в бак: ${formatLiters(details.liters)}`;
  }

  // 6. Користувачі
  if (details.login && (details.roles || action === 'USER_CREATED' || action === 'USER_DELETED' || action === 'USER_UPDATED')) {
    const roleMap = { superadmin: 'Суперадміністратор', admin: 'Адміністратор', operator: 'Оператор', viewer: 'Спостерігач' };
    const rolesUa = Array.isArray(details.roles) ? details.roles.map(r => roleMap[r] || r).join(', ') : '';
    return `Користувач: ${details.login}${rolesUa ? ` (Роль: ${rolesUa})` : ''}`;
  }

  // 7. Сповіщення
  if (details.updated_keys) {
    return 'Оновлено параметри та перемикачі сповіщень';
  }

  // 8. Перерахунок регламенту ТО
  if (details.next_due_hours !== undefined && details.interval_hours !== undefined) {
    return `Мотогодини: ${details.current_hours !== undefined ? details.current_hours : '-'} год | Наступне планове ТО: ${details.next_due_hours} год`;
  }

  // 9. Запис ТО
  if (details.work && details.type) {
    const mType = details.type === 'SCHEDULED' ? 'Регламентне ТО' : 'Проміжне ТО';
    return `${mType} | Роботи: ${details.work} | Вартість: ${details.cost || 0} грн`;
  }

  // 10. Загальний переклад
  const keyTrans = {
    title: 'Назва', description: 'Опис', priority: 'Пріоритет', status: 'Статус', operating_hours: 'Мотогодини',
    liters: 'Літри', cost: 'Вартість', cost_total: 'Загальна сума', source: 'Джерело', updated_at: 'Оновлено',
    name: 'Назва', fuel_type: 'Тип палива', reason: 'Причина', field: 'Поле', old_value: 'Було', new_value: 'Стало'
  };
  const valTrans = {
    STOPPED: 'Зупинено', RUNNING: 'В роботі', MAINTENANCE: 'На обслуговуванні', FAULT: 'Несправність',
    LOW: 'Низький', MEDIUM: 'Середній', HIGH: 'Високий', CRITICAL: 'Критичний',
    SCHEDULED: 'Регламентне ТО', INTERMEDIATE: 'Проміжне ТО'
  };

  const parts = [];
  for (const [k, v] of Object.entries(details)) {
    if (['facility_id', 'generator_id', 'run_id', 'stock_id', 'user_id'].includes(k)) continue;
    const kUa = keyTrans[k] || k;
    const vUa = typeof v === 'string' ? (valTrans[v.toUpperCase()] || v) : (typeof v === 'object' ? JSON.stringify(v) : v);
    parts.push(`${kUa}: ${vUa}`);
  }
  return parts.join(' | ') || JSON.stringify(details);
}

// ROLE_MAP_UA defined at the top

async function loadAuditData() {
  try {
    const logs = await api('/audit?limit=50');
    const tbody = document.querySelector('#auditTable tbody');
    tbody.innerHTML = logs.map((l) => {
      const actionUa = AUDIT_ACTION_MAP_UA[l.action] || l.action;
      const entityUa = AUDIT_ENTITY_MAP_UA[l.entity_type] || l.entity_type;
      const detailsUa = formatAuditDetailsUa(l.details_json, l.action);
      return `
        <tr>
          <td>${formatDateTime(l.created_at)}</td>
          <td>${escapeHtml(l.user_name || 'Система')}</td>
          <td><b>${escapeHtml(actionUa)}</b></td>
          <td>${escapeHtml(entityUa)} #${escapeHtml(l.entity_id || '')}</td>
          <td style="font-size:0.82rem; line-height:1.4;">${escapeHtml(detailsUa)}</td>
          <td>${escapeHtml(l.ip_address || '-')}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-muted)">Аудит порожній</td></tr>';

    const qFac = currentFacilityId ? `&facility_id=${encodeURIComponent(currentFacilityId)}` : '';
    const adjustments = await api(`/adjustments?limit=50${qFac}`);
    const adjTbody = document.querySelector('#adjustmentsTable tbody');
    adjTbody.innerHTML = adjustments.map((a) => {
      const entityUa = AUDIT_ENTITY_MAP_UA[a.entity_type] || a.entity_type;
      const fieldUa = ADJUSTMENT_FIELD_MAP_UA[a.field_name] || a.field_name;
      const facName = a.facility_name || (a.facility_id ? `Об'єкт #${a.facility_id}` : 'Базовий об\'єкт');
      const targetName = a.target_name || `${entityUa} #${a.entity_id}`;
      return `
        <tr>
          <td>${formatDateTime(a.created_at)}</td>
          <td>${escapeHtml(a.user_name || '-')}</td>
          <td><span class="badge" style="background: rgba(14, 165, 233, 0.15); color: #38bdf8;">${escapeHtml(facName)}</span></td>
          <td><b>${escapeHtml(targetName)}</b></td>
          <td>${escapeHtml(entityUa)}</td>
          <td>${escapeHtml(fieldUa)}</td>
          <td><s style="color:#ef4444;">${escapeHtml(a.old_value)}</s></td>
          <td><b style="color:#22c55e;">${escapeHtml(a.new_value)}</b></td>
          <td>${escapeHtml(a.reason)}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="9" style="text-align:center; color:var(--text-muted)">Коригувань не виконувалось</td></tr>';
  } catch (_) {}
}

window.openAdjustmentModal = async function() {
  if (!isSuperAdmin()) {
    showToast('Системне коригування лічильників доступне виключно Головному Суперадміністратору', 'warning');
    return;
  }
  const modal = document.getElementById('modalAdjustment');
  if (modal) modal.style.display = 'flex';

  // 1. Immediately & synchronously populate facility dropdown from header selector if available
  const mainFacSel = document.getElementById('facilitySelect');
  const facSel = document.getElementById('adjFacility');
  if (facSel && mainFacSel && mainFacSel.options.length > 0) {
    facSel.innerHTML = mainFacSel.innerHTML;
    if (currentFacilityId && Array.from(facSel.options).some(o => o.value == currentFacilityId)) {
      facSel.value = currentFacilityId;
    }
  }

  // 2. Synchronously ensure fields dropdown has initial options for current entity
  const fieldSelect = document.getElementById('adjField');
  const entitySel = document.getElementById('adjEntity');
  const entity = entitySel ? entitySel.value : 'FuelStock';
  if (fieldSelect && (!fieldSelect.options || fieldSelect.options.length === 0)) {
    if (entity === 'FuelStock') {
      fieldSelect.innerHTML = `
        <option value="current_balance_l">Залишок на складі (л)</option>
        <option value="name">Назва складу</option>
      `;
    } else if (entity === 'Generator') {
      fieldSelect.innerHTML = `
        <option value="current_operating_hours">Мотогодини</option>
        <option value="fuel_tank_level_l">Рівень у баку (л)</option>
        <option value="status">Статус генератора</option>
        <option value="nominal_consumption_l_per_h">Нормативний розхід (л/год)</option>
      `;
    }
  }

  // 3. Asynchronously load fresh data
  await setupAdjustmentModal();
};

async function setupAdjustmentModal() {
  try {
    const facSel = document.getElementById('adjFacility');
    let facilities = null;
    try {
      facilities = await api('/facilities');
    } catch (_) {}

    if (facSel && facilities && Array.isArray(facilities) && facilities.length > 0) {
      facSel.innerHTML = facilities.map((f) => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
      if (currentFacilityId && facilities.some((f) => f.id === currentFacilityId)) {
        facSel.value = currentFacilityId;
      }
    } else if (facSel && facSel.options.length === 0) {
      const mainFacSel = document.getElementById('facilitySelect');
      if (mainFacSel && mainFacSel.options.length > 0) {
        facSel.innerHTML = mainFacSel.innerHTML;
      } else {
        facSel.innerHTML = '<option value="1">Основний об\'єкт</option>';
      }
    }
  } catch (err) {
    console.warn('setupAdjustmentModal error:', err);
  } finally {
    await onAdjFacilityOrEntityChange();
  }
}
window.setupAdjustmentModal = setupAdjustmentModal;

window.onAdjFacilityOrEntityChange = async function() {
  const facSel = document.getElementById('adjFacility');
  const facilityId = (facSel && parseInt(facSel.value, 10)) || currentFacilityId || 1;
  const entity = document.getElementById('adjEntity').value;
  const targetSel = document.getElementById('adjTargetItem');
  const targetLabel = document.getElementById('adjTargetLabel');
  const fieldSelect = document.getElementById('adjField');

  if (entity === 'FuelStock') {
    if (targetLabel) targetLabel.innerText = 'Цільовий склад ГСМ';
    fieldSelect.innerHTML = `
      <option value="current_balance_l">Залишок на складі (л)</option>
      <option value="name">Назва складу</option>
    `;
    targetSel.innerHTML = '<option value="" disabled selected>Завантаження складів...</option>';
    try {
      const q = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
      const stocks = await api(`/fuel/stocks${q}`);
      if (stocks && stocks.length > 0) {
        targetSel.innerHTML = stocks.map((s) => `
          <option value="${s.id}" data-type="FuelStock" data-balance="${s.current_balance_l}" data-name="${escapeHtml(s.name)}">
            ${escapeHtml(s.name)} (${escapeHtml(s.fuel_type)}) — залишок: ${s.current_balance_l} л
          </option>
        `).join('');
      } else {
        targetSel.innerHTML = `<option value="" disabled selected>Немає складів на цьому об'єкті</option>`;
      }
    } catch (_) {
      targetSel.innerHTML = `<option value="1" data-balance="0.0">Основний склад ГСМ (за замовчуванням)</option>`;
    }
  } else if (entity === 'Generator') {
    if (targetLabel) targetLabel.innerText = 'Цільовий генератор';
    fieldSelect.innerHTML = `
      <option value="current_operating_hours">Мотогодини</option>
      <option value="fuel_tank_level_l">Рівень у баку (л)</option>
      <option value="status">Статус генератора</option>
      <option value="nominal_consumption_l_per_h">Нормативний розхід (л/год)</option>
    `;
    targetSel.innerHTML = '<option value="" disabled selected>Завантаження генераторів...</option>';
    try {
      const q = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
      const gens = await api(`/generator/list${q}`);
      if (gens && gens.length > 0) {
        targetSel.innerHTML = gens.map((g) => `
          <option value="${g.id}" data-type="Generator" data-hours="${g.current_operating_hours}" data-fuel="${g.fuel_tank_level_l}" data-status="${g.status}" data-consumption="${g.nominal_consumption_l_per_h}">
            ${escapeHtml(g.name)} (${escapeHtml(g.model || 'Генератор')})
          </option>
        `).join('');
      } else {
        targetSel.innerHTML = `<option value="" disabled selected>Немає генераторів на цьому об'єкті</option>`;
      }
    } catch (_) {
      targetSel.innerHTML = `<option value="" disabled selected>Помилка завантаження генераторів</option>`;
    }
  } else if (entity === 'MaintenanceSchedule') {
    if (targetLabel) targetLabel.innerText = 'Цільовий регламент ТО';
    fieldSelect.innerHTML = `
      <option value="interval_hours">Інтервал ТО (год)</option>
      <option value="next_due_hours">Наступне ТО (мотогодини)</option>
      <option value="last_performed_hours">Останнє ТО (мотогодини)</option>
    `;
    targetSel.innerHTML = '<option value="" disabled selected>Завантаження графіків ТО...</option>';
    try {
      const q = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
      const gens = await api(`/generator/list${q}`);
      const genIds = (gens || []).map(g => g.id);
      const scheds = await api('/maintenance/schedules');
      const filtered = (scheds || []).filter(s => genIds.length === 0 || genIds.includes(s.generator_id));
      if (filtered && filtered.length > 0) {
        targetSel.innerHTML = filtered.map((s) => `
          <option value="${s.id}" data-type="MaintenanceSchedule" data-interval="${s.interval_hours}" data-due="${s.next_due_hours}" data-performed="${s.last_performed_hours}">
            ${escapeHtml(s.title || 'Регламентне ТО')} (Генератор #${s.generator_id})
          </option>
        `).join('');
      } else {
        targetSel.innerHTML = `<option value="" disabled selected>Немає графіків ТО для об'єкта</option>`;
      }
    } catch (_) {
      targetSel.innerHTML = `<option value="1">Регламентне ТО (за замовчуванням)</option>`;
    }
  } else if (entity === 'Facility') {
    if (targetLabel) targetLabel.innerText = 'Цільовий об\'єкт';
    fieldSelect.innerHTML = `
      <option value="name">Назва об'єкта</option>
      <option value="address">Адреса об'єкта</option>
    `;
    const selOpt = facSel ? facSel.options[facSel.selectedIndex] : null;
    const facName = selOpt ? selOpt.text : `Об'єкт #${facilityId}`;
    targetSel.innerHTML = `<option value="${facilityId}" data-type="Facility" data-name="${escapeHtml(facName)}">${escapeHtml(facName)}</option>`;
  }

  onAdjTargetItemChange();
};

window.onAdjTargetItemChange = function() {
  onAdjFieldChange();
};

window.onAdjFieldChange = function() {
  const targetSel = document.getElementById('adjTargetItem');
  const field = document.getElementById('adjField').value;
  const hintEl = document.getElementById('adjCurrentValHint');
  const inputEl = document.getElementById('adjNewValue');
  if (!targetSel || !hintEl) return;

  const opt = targetSel.options[targetSel.selectedIndex];
  if (!opt || opt.disabled) {
    hintEl.innerText = '';
    return;
  }

  let val = '';
  if (field === 'current_balance_l') val = opt.getAttribute('data-balance') || '';
  else if (field === 'current_operating_hours') val = opt.getAttribute('data-hours') || '';
  else if (field === 'fuel_tank_level_l') val = opt.getAttribute('data-fuel') || '';
  else if (field === 'status') val = opt.getAttribute('data-status') || '';
  else if (field === 'nominal_consumption_l_per_h') val = opt.getAttribute('data-consumption') || '';
  else if (field === 'interval_hours') val = opt.getAttribute('data-interval') || '';
  else if (field === 'next_due_hours') val = opt.getAttribute('data-due') || '';
  else if (field === 'last_performed_hours') val = opt.getAttribute('data-performed') || '';
  else if (field === 'name') val = opt.getAttribute('data-name') || '';

  if (val !== '') {
    hintEl.innerText = `Поточне значення: ${val}`;
    if (inputEl && !inputEl.value) {
      inputEl.placeholder = `Поточне: ${val}`;
    }
  } else {
    hintEl.innerText = '';
    if (inputEl) inputEl.placeholder = 'Нове значення';
  }
};

window.updateAdjFields = function() {
  window.onAdjFacilityOrEntityChange();
};

document.getElementById('adjustmentForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const facSel = document.getElementById('adjFacility');
  const facilityId = facSel ? parseInt(facSel.value, 10) : currentFacilityId;
  const entity = document.getElementById('adjEntity').value;
  const targetSel = document.getElementById('adjTargetItem');
  const targetId = targetSel ? parseInt(targetSel.value, 10) : null;
  const field = document.getElementById('adjField').value;
  const newVal = document.getElementById('adjNewValue').value.trim();
  const reason = document.getElementById('adjReason').value.trim();

  if (!targetId || isNaN(targetId)) {
    showToast('Будь ласка, оберіть цільовий склад або елемент для коригування', 'warning');
    return;
  }
  if (!newVal) {
    showToast('Введіть нове значення', 'warning');
    return;
  }
  if (reason.length < 5) {
    showToast('Обов\'язково вкажіть детальну причину коригування (не менше 5 символів)', 'warning');
    return;
  }

  try {
    await api('/adjustments', {
      method: 'POST',
      body: JSON.stringify({
        entity_type: entity,
        entity_id: targetId,
        facility_id: facilityId || null,
        field_name: field,
        new_value: newVal,
        reason: reason
      })
    });
    closeModal('modalAdjustment');
    showToast('Системне коригування успішно виконано та внесено в журнал аудиту!', 'success');
    loadAuditData();
    loadAllData();
    if (typeof loadFuelData === 'function') loadFuelData();
  } catch (_) {}
});

// 7. Reports
window.setReportPeriod = function(preset) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  let start = new Date(now);
  let end = new Date(now);

  if (preset === 'today') {
    // start is today
  } else if (preset === 'week') {
    start.setDate(now.getDate() - 7);
  } else if (preset === 'month') {
    start.setMonth(now.getMonth() - 1);
  } else if (preset === 'quarter') {
    start.setMonth(now.getMonth() - 3);
  } else if (preset === 'all') {
    start = new Date(2020, 0, 1);
  }

  // Highlight active preset button
  const presetButtons = document.querySelectorAll('#reportPresetGroup button');
  presetButtons.forEach(btn => {
    if (btn.getAttribute('data-preset') === preset) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  const startEl = document.getElementById('repStartDate');
  const endEl = document.getElementById('repEndDate');
  if (startEl) startEl.value = fmt(start);
  if (endEl) endEl.value = fmt(end);

  loadReport(true);
};

window.onReportCustomDateChange = function() {
  const presetButtons = document.querySelectorAll('#reportPresetGroup button');
  presetButtons.forEach(btn => btn.classList.remove('active'));
};

window.switchReportSubtab = function(tabKey) {
  const tabs = ['runs', 'transfers', 'receipts', 'maint'];
  const tabBtnMap = {
    runs: 'btnRepTabRuns',
    transfers: 'btnRepTabTransfers',
    receipts: 'btnRepTabReceipts',
    maint: 'btnRepTabMaint'
  };
  const paneMap = {
    runs: 'repPaneRuns',
    transfers: 'repPaneTransfers',
    receipts: 'repPaneReceipts',
    maint: 'repPaneMaint'
  };

  tabs.forEach(key => {
    const btn = document.getElementById(tabBtnMap[key]);
    const pane = document.getElementById(paneMap[key]);
    if (btn) {
      if (key === tabKey) btn.classList.add('active');
      else btn.classList.remove('active');
    }
    if (pane) {
      pane.style.display = (key === tabKey) ? 'block' : 'none';
    }
  });
};

async function loadReport(isUserTriggered = false) {
  const startInput = document.getElementById('repStartDate')?.value;
  const endInput = document.getElementById('repEndDate')?.value;
  const btn = document.getElementById('btnGenerateReport');
  const iconEl = document.getElementById('btnGenerateReportIcon');
  const textEl = document.getElementById('btnGenerateReportText');

  if (isUserTriggered && btn) {
    btn.disabled = true;
    if (iconEl) iconEl.textContent = '⏳';
    if (textEl) textEl.textContent = 'Формування...';
  }

  const params = [];
  if (currentGeneratorId) params.push(`generator_id=${encodeURIComponent(currentGeneratorId)}`);
  if (currentFacilityId) params.push(`facility_id=${encodeURIComponent(currentFacilityId)}`);
  if (startInput) params.push(`start_date=${encodeURIComponent(startInput)}`);
  if (endInput) params.push(`end_date=${encodeURIComponent(endInput)}`);
  const q = params.length ? '?' + params.join('&') : '';

  try {
    const r = await api(`/reports/summary${q}`);
    const startEl = document.getElementById('repStartDate');
    const endEl = document.getElementById('repEndDate');
    if (startEl && !startEl.value && r.start_date) startEl.value = String(r.start_date).slice(0, 10);
    if (endEl && !endEl.value && r.end_date) endEl.value = String(r.end_date).slice(0, 10);

    // 1. Update Status Banner
    const banner = document.getElementById('reportStatusBanner');
    const statusPeriod = document.getElementById('reportStatusPeriod');
    const statusTarget = document.getElementById('reportStatusTarget');
    const statusGenAt = document.getElementById('reportStatusGeneratedAt');
    if (banner && statusPeriod && statusTarget && statusGenAt) {
      let daysCount = '';
      if (r.start_date && r.end_date) {
        const d1 = new Date(r.start_date);
        const d2 = new Date(r.end_date);
        const diffDays = Math.round(Math.abs(d2 - d1) / (1000 * 60 * 60 * 24)) + 1;
        daysCount = ` (${diffDays} ${diffDays === 1 ? 'день' : (diffDays < 5 ? 'дні' : 'днів')})`;
      }
      const periodStart = r.start_date_human || formatDateOnly(r.start_date);
      const periodEnd = r.end_date_human || formatDateOnly(r.end_date);
      statusPeriod.textContent = `Період звітності: ${periodStart} — ${periodEnd}${daysCount}`;
      const facName = r.facility_name || (facilitySelect?.selectedOptions?.[0]?.text || 'Основний об\'єкт');
      const genName = r.generator_name || (generatorSelect?.selectedOptions?.[0]?.text || 'Генератор');
      statusTarget.textContent = `Об'єкт: ${facName} | Обладнання: ${genName}`;
      const nowStr = formatDateTime(new Date());
      statusGenAt.textContent = `Сформовано: ${nowStr}`;
      banner.style.display = 'flex';
    }

    // 2. Metrics Cards
    const container = document.getElementById('reportContainer');
    const totalCosts = (r.total_costs_uah !== undefined && r.total_costs_uah !== null)
      ? r.total_costs_uah
      : (Number(r.total_fuel_receipts_cost_uah || 0) + Number(r.total_maintenance_cost_uah || 0)).toFixed(2);

    const avgCons = (r.avg_consumption_l_per_hour !== undefined && r.avg_consumption_l_per_hour !== null)
      ? r.avg_consumption_l_per_hour
      : (r.total_operating_hours > 0 ? (r.total_calculated_consumption_l / r.total_operating_hours).toFixed(2) : 0);

    const avgRunDur = (r.avg_run_duration_hours !== undefined && r.avg_run_duration_hours !== null)
      ? r.avg_run_duration_hours
      : (r.total_runs_count > 0 ? (r.total_operating_hours / r.total_runs_count) : 0);

    const totalOperatingHoursDisplay = r.total_operating_hours_human || formatHoursToHuman(r.total_operating_hours);
    const avgRunDurationDisplay = r.avg_run_duration_human || formatHoursToHuman(avgRunDur);

    container.innerHTML = `
      <div class="metric-card">
        <div class="metric-label">Відпрацьовано мотогодин</div>
        <div class="metric-value">${escapeHtml(totalOperatingHoursDisplay)}</div>
        <div class="metric-sub">${escapeHtml(r.total_runs_count)} пусків (сер. ${escapeHtml(avgRunDurationDisplay)})</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Розрахунковий розхід палива</div>
        <div class="metric-value">${escapeHtml(formatLiters(r.total_calculated_consumption_l))}</div>
        <div class="metric-sub">Сер. розхід: ${escapeHtml(formatLiters(avgCons))}/год</div>
      </div>
      <div class="metric-card" style="border-color: rgba(34, 197, 94, 0.4);">
        <div class="metric-label">Загальні витрати за період</div>
        <div class="metric-value" style="color: #4ade80;">${escapeHtml(formatMoney(totalCosts))}</div>
        <div class="metric-sub">Паливо: ${escapeHtml(formatMoney(r.total_fuel_receipts_cost_uah))} | ТО: ${escapeHtml(formatMoney(r.total_maintenance_cost_uah))}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Оприбутковано на склад</div>
        <div class="metric-value">${escapeHtml(formatLiters(r.total_fuel_received_l))}</div>
        <div class="metric-sub">${escapeHtml(formatMoney(r.total_fuel_receipts_cost_uah))} (${escapeHtml(formatPricePerLiter(r.avg_fuel_price_per_liter))})</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Заправлено в бак</div>
        <div class="metric-value">${escapeHtml(formatLiters(r.total_fuel_transferred_to_tank_l))}</div>
        <div class="metric-sub">Залишок у баку: ${escapeHtml(formatLiters(r.current_tank_level_l))}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Виконано ТО</div>
        <div class="metric-value">${escapeHtml(r.total_maintenance_count)}</div>
        <div class="metric-sub">Регламентних: ${escapeHtml(r.scheduled_maintenance_count)} | Проміжних: ${escapeHtml(r.intermediate_maintenance_count)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Витрати на сервіс / ТО</div>
        <div class="metric-value">${escapeHtml(formatMoney(r.total_maintenance_cost_uah))}</div>
        <div class="metric-sub">${escapeHtml(r.total_maintenance_count)} операцій обслуговування</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Несправності / Інциденти</div>
        <div class="metric-value">${escapeHtml(r.total_faults_count)}</div>
        <div class="metric-sub">Усунено: ${escapeHtml(r.resolved_faults_count)} | Відкрито: ${escapeHtml(r.open_faults_count)}</div>
      </div>
    `;

    // 3. Detailed Logs & Subtabs
    const detailsSection = document.getElementById('reportDetailsSection');
    if (detailsSection) {
      detailsSection.style.display = 'block';

      const runs = r.runs || [];
      const transfers = r.fuel_transfers || [];
      const receipts = r.fuel_receipts || [];
      const maint = r.maintenance_records || [];

      // Badges
      const bRuns = document.getElementById('repBadgeRuns');
      const bTr = document.getElementById('repBadgeTransfers');
      const bRec = document.getElementById('repBadgeReceipts');
      const bMaint = document.getElementById('repBadgeMaint');
      if (bRuns) bRuns.textContent = runs.length;
      if (bTr) bTr.textContent = transfers.length;
      if (bRec) bRec.textContent = receipts.length;
      if (bMaint) bMaint.textContent = maint.length;

      // Table 1: Runs
      const runsTbody = document.getElementById('repRunsTableBody');
      if (runsTbody) {
        if (!runs.length) {
          runsTbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:1.5rem;">Немає зафіксованих пусків за обраний період</td></tr>`;
        } else {
          runsTbody.innerHTML = runs.map(row => `
            <tr>
              <td><b>${escapeHtml(row.start_time)}</b></td>
              <td>${escapeHtml(row.end_time || 'В роботі')}</td>
              <td><b style="color: #38bdf8; font-family: monospace;">${escapeHtml(row.duration_formatted || formatHoursToHms(row.duration_hours))}</b></td>
              <td>${formatHoursCounter(row.start_hours)} ➔ ${row.end_hours !== null && row.end_hours !== undefined ? formatHoursCounter(row.end_hours) : '-'}</td>
              <td style="color:#38bdf8; font-weight:600;">${formatLiters(row.calculated_consumption_l)}</td>
              <td>${escapeHtml(row.operator_name || '-')}</td>
            </tr>
          `).join('');
        }
      }

      // Table 2: Fuel Transfers
      const trTbody = document.getElementById('repTransfersTableBody');
      if (trTbody) {
        if (!transfers.length) {
          trTbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding:1.5rem;">Немає заправок бака за обраний період</td></tr>`;
        } else {
          trTbody.innerHTML = transfers.map(row => `
            <tr>
              <td><b>${escapeHtml(row.created_at)}</b></td>
              <td style="color:#4ade80; font-weight:700;">${formatLiters(row.liters)}</td>
              <td>${escapeHtml(row.stock_name || 'Склад ГСМ')}</td>
              <td>${escapeHtml(row.generator_name || 'Генератор')}</td>
              <td>${escapeHtml(row.operator_name || '-')}</td>
            </tr>
          `).join('');
        }
      }

      // Table 3: Fuel Receipts
      const recTbody = document.getElementById('repReceiptsTableBody');
      if (recTbody) {
        if (!receipts.length) {
          recTbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-muted); padding:1.5rem;">Немає надходжень на склад за обраний період</td></tr>`;
        } else {
          recTbody.innerHTML = receipts.map(row => `
            <tr>
              <td><b>${escapeHtml(row.created_at)}</b></td>
              <td style="color:#4ade80; font-weight:700;">${formatLiters(row.liters)}</td>
              <td>${formatPricePerLiter(row.price_per_liter)}</td>
              <td style="font-weight:600;">${formatMoney(row.cost_total)}</td>
              <td>${escapeHtml(row.supplier || '-')}</td>
              <td>${escapeHtml(row.stock_name || 'Склад ГСМ')}</td>
              <td>${escapeHtml(row.operator_name || '-')}</td>
            </tr>
          `).join('');
        }
      }

      // Table 4: Maintenance
      const maintTbody = document.getElementById('repMaintTableBody');
      if (maintTbody) {
        if (!maint.length) {
          maintTbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-muted); padding:1.5rem;">Немає записів обслуговування за обраний період</td></tr>`;
        } else {
          maintTbody.innerHTML = maint.map(row => `
            <tr>
              <td><b>${escapeHtml(row.created_at)}</b></td>
              <td><span class="badge" style="background: rgba(6,182,212,0.15); color: var(--accent-cyan);">${escapeHtml(row.maintenance_type)}</span></td>
              <td>${formatHoursCounter(row.operating_hours)}</td>
              <td>${escapeHtml(row.work_description || '-')}</td>
              <td style="font-weight:600;">${formatMoney(row.cost)}</td>
              <td>${escapeHtml(row.technician || '-')}</td>
              <td>${escapeHtml(row.operator_name || '-')}</td>
            </tr>
          `).join('');
        }
      }
    }

    if (isUserTriggered) {
      const periodStart = r.start_date_human || formatDateOnly(r.start_date);
      const periodEnd = r.end_date_human || formatDateOnly(r.end_date);
      showToast(`Звіт за період ${periodStart} — ${periodEnd} успішно сформовано!`, 'success');
    }
  } catch (err) {
    const container = document.getElementById('reportContainer');
    if (container) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 0.75rem; padding: 1.5rem; text-align: center; color: #f87171;">
          <div style="font-size: 1.15rem; font-weight: 700; margin-bottom: 0.35rem;">⚠️ Не вдалося завантажити показники звіту</div>
          <div style="font-size: 0.95rem;">${escapeHtml(err.message || 'Помилка отримання зведених даних')}</div>
        </div>
      `;
    }
    if (isUserTriggered) {
      showToast(`Помилка формування звіту: ${err.message || 'Невідома помилка'}`, 'error');
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      if (iconEl) iconEl.textContent = '🔄';
      if (textEl) textEl.textContent = 'Сформувати звіт';
    }
  }
}

window.downloadReportCSV = function () {
  showToast('Експорт у форматі CSV вимкнено. Звіти формуються виключно у форматі Excel (.xlsx)', 'info');
};

window.downloadReportExcel = async function () {
  const startInput = document.getElementById('repStartDate').value;
  const endInput = document.getElementById('repEndDate').value;
  let url = '/api/v1/reports/export-excel';
  const params = [];
  if (currentGeneratorId) params.push(`generator_id=${encodeURIComponent(currentGeneratorId)}`);
  if (currentFacilityId) params.push(`facility_id=${encodeURIComponent(currentFacilityId)}`);
  if (startInput) params.push(`start_date=${encodeURIComponent(startInput)}`);
  if (endInput) params.push(`end_date=${encodeURIComponent(endInput)}`);
  if (params.length) url += `?${params.join('&')}`;

  try {
    showToast('Формування динамічного Excel звіту (.xlsx)...', 'info');
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(url, { headers, credentials: 'same-origin' });
    if (!res.ok) {
      let errMsg = `Помилка сервера при створенні Excel (${res.status})`;
      try {
        const errJson = await res.json();
        errMsg = extractErrorMessage(errJson, errMsg);
      } catch (_) {}
      throw new Error(errMsg);
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    const dateStr = new Date().toISOString().slice(0, 10);
    a.download = `ServiceDesk_Report_${dateStr}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast('Excel звіт (.xlsx) успішно згенеровано та завантажено!', 'success');
  } catch (err) {
    showToast(err.message || 'Помилка завантаження Excel звіту', 'error');
  }
};

// 8. Admin (Users Management - SuperAdmin Only)
let allUsersCache = [];

async function loadUsersData() {
  try {
    const users = await api('/users');
    allUsersCache = users || [];
    const tbody = document.querySelector('#usersTable tbody');
    if (!tbody) return;
    const canManage = isSuperAdmin();

    tbody.innerHTML = allUsersCache.map((u) => {
      const rolesUa = (u.roles || []).map((r) => ROLE_MAP_UA[r.name] || r.name).join(', ') || '-';
      const isSuper = u.is_superadmin;

      let actionsHtml = '';
      if (isSuper) {
        actionsHtml = `<span class="badge" style="background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); font-size: 0.75rem;">⭐ Головний адмін (захищено)</span>`;
      } else if (canManage) {
        actionsHtml = `
          <div style="display: flex; gap: 0.35rem; align-items: center;">
            <button type="button" class="btn-action" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.8rem;" onclick="openEditUserModal(${Number(u.id)})" title="Редагувати користувача (ПІБ, логін, email, роль, статус)">✏️</button>
            <button type="button" class="btn-action" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.8rem;" onclick="openResetPasswordModal(${Number(u.id)})" title="Встановити новий пароль">🔑</button>
            <button type="button" class="btn-action" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.8rem; color: #ef4444;" onclick="openDeleteUserModal(${Number(u.id)})" title="Видалити користувача">🗑️</button>
          </div>
        `;
      } else {
        actionsHtml = `<span style="color: var(--text-muted); font-size: 0.75rem;">Тільки Суперадмін 🔒</span>`;
      }

      return `
        <tr>
          <td>#${Number(u.id)}</td>
          <td><b>${escapeHtml(u.login)}</b></td>
          <td>${escapeHtml(u.full_name)}</td>
          <td>${escapeHtml(u.email || '-')}</td>
          <td><span class="badge ${u.is_active ? 'badge-running' : 'badge-faulty'}">${u.is_active ? 'Активний' : 'Заблокований'}</span></td>
          <td>${escapeHtml(rolesUa)}</td>
          <td>${actionsHtml}</td>
        </tr>
      `;
    }).join('');
  } catch (_) {}
}

// User Create Form Submit
document.getElementById('userCreateForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!isSuperAdmin()) {
    showToast('Створення користувачів доступне лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const loginVal = document.getElementById('newLogin').value.trim();
  const fullNameVal = document.getElementById('newName').value.trim();
  const emailVal = document.getElementById('newEmail').value.trim() || null;
  const passVal = document.getElementById('newPassword').value;

  if (!/^[a-zA-Z0-9_.\-]{3,50}$/.test(loginVal)) {
    showToast("Логін повинен містити 3–50 символів (латинські літери, цифри, '_', '.', '-')", 'error');
    return;
  }
  if (passVal.length < 8 || !/[a-zA-Zа-яА-ЯіїєґІЇЄҐ]/.test(passVal) || !/\d/.test(passVal)) {
    showToast('Пароль повинен містити щонайменше 8 символів, літери та цифри', 'error');
    return;
  }

  const body = {
    login: loginVal,
    full_name: fullNameVal,
    email: emailVal,
    password: passVal,
    role_ids: [parseInt(document.getElementById('newUserRole').value, 10)]
  };

  try {
    await api('/users', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalUserCreate');
    showToast('Користувача успішно створено!', 'success');
    loadUsersData();
  } catch (_) {}
});

// Edit User Modal & Form
window.openEditUserModal = function(id) {
  if (!isSuperAdmin()) {
    showToast('Редагування користувачів доступне лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const u = allUsersCache.find((user) => user.id === id);
  if (!u) {
    showToast('Користувача не знайдено', 'error');
    return;
  }
  if (u.is_superadmin) {
    showToast('Редагування облікового запису головного суперадміністратора заборонено', 'warning');
    return;
  }

  document.getElementById('editUserId').value = u.id;
  document.getElementById('editUserLogin').value = u.login;
  document.getElementById('editUserName').value = u.full_name;
  document.getElementById('editUserEmail').value = u.email || '';
  document.getElementById('editUserActive').checked = Boolean(u.is_active);
  document.getElementById('editUserPassword').value = '';

  const roleSelect = document.getElementById('editUserRole');
  if (roleSelect) {
    const primaryRole = (u.roles && u.roles[0]) ? u.roles[0].name.toLowerCase() : '';
    if (primaryRole === 'admin') roleSelect.value = '2';
    else if (primaryRole === 'viewer') roleSelect.value = '4';
    else roleSelect.value = '3';
  }

  openModal('modalUserEdit');
};

document.getElementById('userEditForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!isSuperAdmin()) {
    showToast('Дія доступна лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const userId = parseInt(document.getElementById('editUserId').value);
  const loginVal = document.getElementById('editUserLogin').value.trim();
  const nameVal = document.getElementById('editUserName').value.trim();
  const emailVal = document.getElementById('editUserEmail').value.trim() || null;
  const roleVal = parseInt(document.getElementById('editUserRole').value);
  const activeVal = document.getElementById('editUserActive').checked;
  const passVal = document.getElementById('editUserPassword').value;

  if (!/^[a-zA-Z0-9_.\-]{3,50}$/.test(loginVal)) {
    showToast("Логін повинен містити 3–50 символів (латинські літери, цифри, '_', '.', '-')", 'error');
    return;
  }
  if (!nameVal) {
    showToast("ПІБ є обов'язковим", 'error');
    return;
  }
  if (passVal && (passVal.length < 8 || !/[a-zA-Zа-яА-ЯіїєґІЇЄҐ]/.test(passVal) || !/\d/.test(passVal))) {
    showToast('Новий пароль повинен містити щонайменше 8 символів, літери та цифри', 'error');
    return;
  }

  const payload = {
    login: loginVal,
    full_name: nameVal,
    email: emailVal,
    role_ids: [roleVal],
    is_active: activeVal
  };
  if (passVal) {
    payload.password = passVal;
  }

  try {
    await api(`/users/${userId}`, {
      method: 'PUT',
      body: JSON.stringify(payload)
    });
    closeModal('modalUserEdit');
    showToast('Дані користувача успішно оновлено!', 'success');
    loadUsersData();
  } catch (_) {}
});

// Reset Password Modal & Form
window.openResetPasswordModal = function(id) {
  if (!isSuperAdmin()) {
    showToast('Скидання паролів доступне лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const u = allUsersCache.find((user) => user.id === id);
  if (!u) {
    showToast('Користувача не знайдено', 'error');
    return;
  }
  if (u.is_superadmin) {
    showToast('Скидання пароля головного суперадміністратора заборонено', 'warning');
    return;
  }

  document.getElementById('resetUserId').value = u.id;
  document.getElementById('resetUserDisplayLogin').innerText = u.login;
  document.getElementById('resetUserDisplayName').innerText = u.full_name;
  document.getElementById('resetNewPassword').value = '';
  document.getElementById('resetConfirmPassword').value = '';

  openModal('modalUserResetPassword');
};

document.getElementById('userResetPasswordForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!isSuperAdmin()) {
    showToast('Дія доступна лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const userId = parseInt(document.getElementById('resetUserId').value);
  const p1 = document.getElementById('resetNewPassword').value;
  const p2 = document.getElementById('resetConfirmPassword').value;

  if (p1 !== p2) {
    showToast('Введені паролі не співпадають', 'error');
    return;
  }
  if (p1.length < 8 || !/[a-zA-Zа-яА-ЯіїєґІЇЄҐ]/.test(p1) || !/\d/.test(p1)) {
    showToast('Пароль повинен містити щонайменше 8 символів, літери та цифри', 'error');
    return;
  }

  try {
    const res = await api(`/users/${userId}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: p1 })
    });
    closeModal('modalUserResetPassword');
    showToast(res.message || 'Пароль успішно змінено!', 'success');
  } catch (_) {}
});

// Delete User Modal
window.openDeleteUserModal = function(id) {
  if (!isSuperAdmin()) {
    showToast('Видалення користувачів доступне лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const u = allUsersCache.find((user) => user.id === id);
  if (!u) {
    showToast('Користувача не знайдено', 'error');
    return;
  }
  if (u.is_superadmin) {
    showToast('Видалення головного суперадміністратора заборонено', 'warning');
    return;
  }

  document.getElementById('deleteUserId').value = u.id;
  document.getElementById('deleteUserDisplayLogin').innerText = u.login;
  document.getElementById('deleteUserDisplayName').innerText = u.full_name;

  openModal('modalUserDelete');
};

document.getElementById('confirmDeleteUserBtn')?.addEventListener('click', async () => {
  if (!isSuperAdmin()) {
    showToast('Дія доступна лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const userId = parseInt(document.getElementById('deleteUserId').value);
  if (!userId) return;

  try {
    const res = await api(`/users/${userId}`, { method: 'DELETE' });
    closeModal('modalUserDelete');
    showToast(res.message || 'Користувача успішно видалено!', 'success');
    loadUsersData();
  } catch (_) {}
});

// Generator Deletion Handlers
window.openDeleteGeneratorModal = function() {
  if (!hasPermission('generator:configure')) {
    showToast('Видалення генератора доступне лише Адміністратору', 'warning');
    return;
  }
  if (!currentGenerator) {
    showToast('Генератор не вибрано', 'error');
    return;
  }
  if (currentGenerator.status === 'RUNNING') {
    showToast('Неможливо видалити генератор, який зараз працює! Спершу зупиніть його.', 'error');
    return;
  }
  const text = document.getElementById('deleteGenConfirmText');
  if (text) {
    text.innerHTML = `Ви дійсно бажаєте видалити генератор <b>"${escapeHtml(currentGenerator.name)}"</b> (Модель: ${escapeHtml(currentGenerator.model)}, S/N: ${escapeHtml(currentGenerator.serial_number)})?`;
  }
  openModal('modalDeleteGenerator');
};

window.confirmDeleteCurrentGenerator = async function() {
  if (!currentGeneratorId) return;
  try {
    const res = await api(`/generator/${currentGeneratorId}`, { method: 'DELETE' });
    closeModal('modalDeleteGenerator');
    showToast(res.message || 'Генератор успішно видалено!', 'success');
    localStorage.removeItem('sd_last_generator_id');
    if (currentFacilityId) {
      localStorage.removeItem(`sd_last_gen_facility_${currentFacilityId}`);
    }
    currentGeneratorId = null;
    await loadGeneratorsList(currentFacilityId);
    await loadAllData();
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// Modal Helpers for Facility and Generator Creation
window.openCreateFacilityModal = function() {
  if (!hasPermission('facility:configure')) {
    showToast("Створення об'єктів доступне лише Адміністратору 🔒", 'warning');
    return;
  }
  const nameEl = document.getElementById('newFacilityName');
  if (nameEl) nameEl.value = '';
  const addrEl = document.getElementById('newFacilityAddress');
  if (addrEl) addrEl.value = '';
  const descEl = document.getElementById('newFacilityDescription');
  if (descEl) descEl.value = '';
  openModal('modalCreateFacility');
};

window.openCreateGeneratorModal = function() {
  if (!hasPermission('generator:configure')) {
    showToast('Створення генераторів доступне лише Адміністратору 🔒', 'warning');
    return;
  }
  const modalSel = document.getElementById('newGenFacilityId');
  if (modalSel && currentFacilityId) {
    modalSel.value = currentFacilityId;
  }
  const nameEl = document.getElementById('newGenName');
  if (nameEl) nameEl.value = '';
  const modelEl = document.getElementById('newGenModel');
  if (modelEl) modelEl.value = '';
  const mfgEl = document.getElementById('newGenManufacturer');
  if (mfgEl) mfgEl.value = '';
  const snEl = document.getElementById('newGenSerial');
  if (snEl) snEl.value = '';
  const powerEl = document.getElementById('newGenPower');
  if (powerEl) powerEl.value = '5.0';
  const tankEl = document.getElementById('newGenTank');
  if (tankEl) tankEl.value = '25.0';
  const consEl = document.getElementById('newGenConsumption');
  if (consEl) consEl.value = '2.2';
  const hoursEl = document.getElementById('newGenInitialHours');
  if (hoursEl) hoursEl.value = '0.0';
  const fuelEl = document.getElementById('newGenInitialFuel');
  if (fuelEl) fuelEl.value = '0.0';
  const maintEl = document.getElementById('newGenMaintInterval');
  if (maintEl) maintEl.value = '300';

  openModal('modalCreateGenerator');
};

// Facility Create Form Submit
document.getElementById('facilityCreateForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('newFacilityName')?.value?.trim();
  const address = document.getElementById('newFacilityAddress')?.value?.trim();
  const description = document.getElementById('newFacilityDescription')?.value?.trim();

  if (!name) {
    showToast("Вкажіть назву об'єкта", 'warning');
    return;
  }

  try {
    const created = await api('/facilities', {
      method: 'POST',
      body: JSON.stringify({ name, address, description, timezone: 'Europe/Kyiv' })
    });
    closeModal('modalCreateFacility');
    showToast(`Об'єкт "${created.name}" успішно створено!`, 'success');

    currentFacilityId = created.id;
    currentGeneratorId = null;
    localStorage.setItem('sd_last_facility_id', currentFacilityId);
    localStorage.removeItem('sd_last_generator_id');
    localStorage.removeItem(`sd_last_gen_facility_${currentFacilityId}`);

    await loadFacilitiesList();
    if (document.getElementById('facilitySelect')) {
      document.getElementById('facilitySelect').value = created.id;
    }
    await loadGeneratorsList(currentFacilityId);
    await loadAllData();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Generator Create Form Submit
document.getElementById('generatorCreateForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const chosenFacilityId = parseInt(document.getElementById('newGenFacilityId')?.value) || currentFacilityId || 1;
  const name = document.getElementById('newGenName')?.value?.trim();
  const model = document.getElementById('newGenModel')?.value?.trim();
  const manufacturer = document.getElementById('newGenManufacturer')?.value?.trim();
  const serial_number = document.getElementById('newGenSerial')?.value?.trim();

  if (!name) {
    showToast("Вкажіть назву генератора", 'warning');
    return;
  }
  if (!model) {
    showToast("Вкажіть модель генератора", 'warning');
    return;
  }
  if (!manufacturer) {
    showToast("Вкажіть виробника генератора", 'warning');
    return;
  }
  if (!serial_number) {
    showToast("Вкажіть серійний номер", 'warning');
    return;
  }

  const body = {
    facility_id: chosenFacilityId,
    name: name,
    model: model,
    manufacturer: manufacturer,
    serial_number: serial_number,
    rated_power_kw: parseFloat(document.getElementById('newGenPower')?.value) || 5.0,
    tank_capacity_l: parseFloat(document.getElementById('newGenTank')?.value) || 25.0,
    fuel_type: document.getElementById('newGenFuelType')?.value || 'А-95',
    nominal_consumption_l_per_h: parseFloat(document.getElementById('newGenConsumption')?.value) || 2.2,
    initial_operating_hours: parseFloat(document.getElementById('newGenInitialHours')?.value) || 0.0,
    initial_fuel_tank_level_l: parseFloat(document.getElementById('newGenInitialFuel')?.value) || 0.0,
    maintenance_interval_hours: parseFloat(document.getElementById('newGenMaintInterval')?.value) || 300.0,
    work_schedule_start: "08:00",
    work_schedule_end: "20:00",
    timezone: "Europe/Kyiv"
  };

  try {
    const created = await api('/generator', {
      method: 'POST',
      body: JSON.stringify(body)
    });
    closeModal('modalCreateGenerator');
    showToast(`Генератор "${created.name}" успішно створено!`, 'success');

    // Switch facility context if created on another facility
    currentFacilityId = chosenFacilityId;
    localStorage.setItem('sd_last_facility_id', currentFacilityId);
    if (document.getElementById('facilitySelect')) {
      document.getElementById('facilitySelect').value = currentFacilityId;
    }

    currentGeneratorId = created.id;
    localStorage.setItem('sd_last_generator_id', currentGeneratorId);
    localStorage.setItem(`sd_last_gen_facility_${currentFacilityId}`, currentGeneratorId);

    await loadGeneratorsList(currentFacilityId);
    if (document.getElementById('generatorSelect')) {
      document.getElementById('generatorSelect').value = created.id;
    }
    await loadAllData();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Dropdowns Change Listeners
document.getElementById('facilitySelect')?.addEventListener('change', async (e) => {
  currentFacilityId = parseInt(e.target.value);
  localStorage.setItem('sd_last_facility_id', currentFacilityId);
  currentGeneratorId = null;
  await loadGeneratorsList(currentFacilityId);
  await loadAllData();
});

document.getElementById('generatorSelect')?.addEventListener('change', async (e) => {
  currentGeneratorId = parseInt(e.target.value);
  localStorage.setItem('sd_last_generator_id', currentGeneratorId);
  if (currentFacilityId) {
    localStorage.setItem(`sd_last_gen_facility_${currentFacilityId}`, currentGeneratorId);
  }
  await loadAllData();
});

// Quick Edit Facility Modal Handlers
window.openQuickEditFacilityModal = async function() {
  if (!hasPermission('facility:configure')) {
    showToast("Редагування об'єкта доступне лише Адміністратору", 'warning');
    return;
  }
  if (!currentFacilityId) {
    showToast("Будь ласка, спочатку оберіть об'єкт", "warning");
    return;
  }
  try {
    const fac = await api(`/facilities/${currentFacilityId}`);
    document.getElementById('quickEditFacilityId').value = fac.id;
    document.getElementById('quickEditFacilityName').value = fac.name || '';
    document.getElementById('quickEditFacilityAddress').value = fac.address || '';
    document.getElementById('quickEditFacilityDescription').value = fac.description || '';
    openModal('modalQuickEditFacility');
  } catch (err) {
    showToast(err.message || "Не вдалося завантажити дані об'єкта", 'error');
  }
};

document.getElementById('quickEditFacilityForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const facId = parseInt(document.getElementById('quickEditFacilityId').value);
  const name = document.getElementById('quickEditFacilityName').value.trim();
  const address = document.getElementById('quickEditFacilityAddress').value.trim();
  const description = document.getElementById('quickEditFacilityDescription').value.trim();

  try {
    const updated = await api(`/facilities/${facId}`, {
      method: 'PUT',
      body: JSON.stringify({ name, address, description })
    });
    closeModal('modalQuickEditFacility');
    showToast(`Об'єкт "${updated.name}" успішно оновлено!`, 'success');
    await loadFacilitiesList();
    if (document.getElementById('facilitySelect')) {
      document.getElementById('facilitySelect').value = updated.id;
    }
    await loadAllData();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Quick Edit Generator Modal Handlers
window.openQuickEditGeneratorModal = async function() {
  if (!hasPermission('generator:configure')) {
    showToast('Редагування генератора доступне лише Адміністратору', 'warning');
    return;
  }
  if (!currentGeneratorId) {
    showToast("Будь ласка, спочатку оберіть генератор", "warning");
    return;
  }
  try {
    const gen = currentGenerator || await api(`/generator?generator_id=${currentGeneratorId}`);
    document.getElementById('quickEditGenId').value = gen.id;
    document.getElementById('quickEditGenName').value = gen.name || '';
    document.getElementById('quickEditGenModel').value = gen.model || '';
    document.getElementById('quickEditGenSerial').value = gen.serial_number || '';
    document.getElementById('quickEditGenPower').value = gen.rated_power_kw || '';
    document.getElementById('quickEditGenTank').value = gen.tank_capacity_l || '';
    document.getElementById('quickEditGenConsumption').value = gen.nominal_consumption_l_per_h || '';
    if (document.getElementById('quickEditGenFuelType')) {
      document.getElementById('quickEditGenFuelType').value = gen.fuel_type || 'А-95';
    }
    openModal('modalQuickEditGenerator');
  } catch (err) {
    showToast(err.message || 'Не вдалося завантажити дані генератора', 'error');
  }
};

document.getElementById('quickEditGeneratorForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const genId = parseInt(document.getElementById('quickEditGenId').value);
  const body = {
    name: document.getElementById('quickEditGenName').value.trim(),
    model: document.getElementById('quickEditGenModel').value.trim(),
    serial_number: document.getElementById('quickEditGenSerial').value.trim(),
    rated_power_kw: parseFloat(document.getElementById('quickEditGenPower').value),
    tank_capacity_l: parseFloat(document.getElementById('quickEditGenTank').value),
    fuel_type: document.getElementById('quickEditGenFuelType').value,
    nominal_consumption_l_per_h: parseFloat(document.getElementById('quickEditGenConsumption').value)
  };

  try {
    const updated = await api(`/generator/${genId}`, {
      method: 'PUT',
      body: JSON.stringify(body)
    });
    closeModal('modalQuickEditGenerator');
    showToast(`Генератор "${updated.name}" успішно оновлено!`, 'success');
    await loadGeneratorsList(currentFacilityId);
    if (document.getElementById('generatorSelect')) {
      document.getElementById('generatorSelect').value = updated.id;
    }
    await loadAllData();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// PWA Installation & First-Visit Prompt Logic
let deferredInstallPrompt = null;

function setupPwaInstall() {
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const isIos = /iphone|ipad|ipod/.test(navigator.userAgent.toLowerCase());
  const banner = document.getElementById('pwaInstallBanner');
  const headerInstallBtn = document.getElementById('headerInstallBtn');
  const installBtn = document.getElementById('pwaInstallBtn');
  const dismissBtn = document.getElementById('pwaDismissBtn');

  // If already running in standalone PWA app mode, hide install buttons
  if (isStandalone) {
    if (banner) banner.style.display = 'none';
    if (headerInstallBtn) headerInstallBtn.style.display = 'none';
    return;
  }

  // Check dismissal timestamp
  const dismissedTime = localStorage.getItem('pwa_install_dismissed_at');
  const shouldShowPrompt = !dismissedTime || (Date.now() - parseInt(dismissedTime, 10) > 7 * 24 * 3600 * 1000);

  // Native beforeinstallprompt event (Android / Chromium)
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    if (headerInstallBtn) headerInstallBtn.style.display = 'inline-flex';
    if (shouldShowPrompt && banner) {
      banner.style.display = 'flex';
    }
  });

  // Prompt on first visit if not dismissed
  if (shouldShowPrompt && banner) {
    setTimeout(() => {
      const activeStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
      if (!activeStandalone) {
        banner.style.display = 'flex';
        if (headerInstallBtn) headerInstallBtn.style.display = 'inline-flex';
      }
    }, 1200);
  } else if (headerInstallBtn) {
    headerInstallBtn.style.display = 'inline-flex';
  }

  // Click install on banner
  installBtn?.addEventListener('click', async () => {
    if (deferredInstallPrompt) {
      deferredInstallPrompt.prompt();
      const choice = await deferredInstallPrompt.userChoice;
      if (choice.outcome === 'accepted') {
        if (banner) banner.style.display = 'none';
        if (headerInstallBtn) headerInstallBtn.style.display = 'none';
        localStorage.setItem('pwa_installed', 'true');
      }
      deferredInstallPrompt = null;
    } else if (isIos) {
      openModal('modalIosInstall');
    } else {
      showToast('Натисніть на значок встановлення в адресному рядку браузера або меню ⋮ -> "Встановити додаток"', 'info');
    }
  });

  // Click install in header
  headerInstallBtn?.addEventListener('click', async () => {
    if (deferredInstallPrompt) {
      deferredInstallPrompt.prompt();
      const choice = await deferredInstallPrompt.userChoice;
      if (choice.outcome === 'accepted') {
        if (headerInstallBtn) headerInstallBtn.style.display = 'none';
        if (banner) banner.style.display = 'none';
      }
      deferredInstallPrompt = null;
    } else if (isIos) {
      openModal('modalIosInstall');
    } else {
      showToast('Натисніть на значок встановлення в адресному рядку браузера або меню ⋮ -> "Встановити додаток"', 'info');
    }
  });

  // Click dismiss
  dismissBtn?.addEventListener('click', () => {
    if (banner) banner.style.display = 'none';
    localStorage.setItem('pwa_install_dismissed_at', Date.now().toString());
  });

  window.addEventListener('appinstalled', () => {
    if (banner) banner.style.display = 'none';
    if (headerInstallBtn) headerInstallBtn.style.display = 'none';
    localStorage.setItem('pwa_installed', 'true');
    showToast('Додаток успішно встановлено!', 'success');
  });
}

// Live Server Status in Footer
async function refreshServerStatus() {
  try {
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch('/api/v1/system/status', { headers });
    if (!res.ok) return;
    const data = await res.json();

    const statusEl = document.getElementById('footerServerStatus');
    const cpuEl = document.getElementById('footerCpu');
    const ramEl = document.getElementById('footerRam');
    const ramMbEl = document.getElementById('footerRamMb');
    const dbEl = document.getElementById('footerDb');
    const uptimeEl = document.getElementById('footerUptime');

    if (statusEl) statusEl.textContent = data.status === 'online' ? 'Онлайн' : data.status;
    if (cpuEl) cpuEl.textContent = `${data.cpu.percent}%`;
    if (ramEl) ramEl.textContent = `${data.memory.percent}%`;
    if (ramMbEl) ramMbEl.textContent = `(${Math.round(data.memory.used_mb)} / ${Math.round(data.memory.total_mb)} МБ)`;
    if (dbEl) {
      dbEl.textContent = data.database.status === 'connected' ? 'OK' : 'Помилка';
      dbEl.style.color = data.database.status === 'connected' ? '#22c55e' : '#ef4444';
    }
    if (uptimeEl) uptimeEl.textContent = data.uptime.formatted || `${data.uptime.seconds}с`;
  } catch (_) {}
}

// Admin System Settings, WOG Fuel Prices & DB Reset
function renderAdminFuelPricesHints(fp) {
  if (!fp || !fp.fuels) return;
  cachedFuelPrices = fp;
  const metaEl = document.getElementById('sysInternetPricesMeta');
  if (metaEl) {
    const upd = fp.internet_prices_updated_at ? ` (оновлено: ${fp.internet_prices_updated_at})` : '';
    metaEl.textContent = `Джерело: ${fp.internet_prices_source || 'АЗК WOG (wog.ua/ua/fuels/)'}${upd}`;
  }

  // Render WOG Price Board
  const boardEl = document.getElementById('wogPriceBoard');
  if (boardEl) {
    const lineup = Array.isArray(fp.wog_lineup) && fp.wog_lineup.length > 0 ? fp.wog_lineup : [
      { type: 'ДП', brand: 'Євро5', price: fp.fuels['ДП']?.internet_price ?? 103.50 },
      { type: 'ДП', brand: 'Mustang+', price: fp.fuels['ДП Mustang+']?.internet_price ?? 106.50 },
      { type: '95', brand: 'Євро5-Е10', price: fp.fuels['А-95']?.internet_price ?? 92.90 },
      { type: '95', brand: 'Mustang Євро5-Е10', price: fp.fuels['А-95 Mustang']?.internet_price ?? 95.90 },
      { type: '100', brand: 'Mustang Євро5-Е0', price: 102.90 },
      { type: 'ГАЗ', brand: '', price: fp.fuels['ГАЗ']?.internet_price ?? 52.50 },
      { type: 'AdBlue', brand: '', price: 61.90 }
    ];
    boardEl.innerHTML = lineup.map((item) => {
      const isMustang = String(item.brand || '').toLowerCase().includes('mustang');
      const badgeColor = isMustang ? '#ef4444' : '#3b82f6';
      return `<div style="background: var(--bg-subtle); border: 1px solid var(--border-color); border-left: 3px solid ${badgeColor}; border-radius: 0.5rem; padding: 0.55rem 0.7rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem;">
        <div>
          <div style="font-weight: 800; font-size: 0.95rem; color: var(--text-primary); line-height: 1.1;">${escapeHtml(item.type)}</div>
          <div style="font-size: 0.72rem; color: ${isMustang ? 'var(--accent-red)' : 'var(--text-muted)'};">${escapeHtml(item.brand || 'Стандарт')}</div>
        </div>
        <div style="font-weight: 800; font-size: 1.05rem; color: var(--accent-green); white-space: nowrap;">${Number(item.price).toFixed(2)} <span style="font-size: 0.7rem; font-weight: 500; color: var(--text-muted);">₴</span></div>
      </div>`;
    }).join('');
  }

  const map = [
    ['А-95', 'sysNetHintA95', 'WOG 95 Євро5'],
    ['ДП', 'sysNetHintDP', 'WOG ДП Євро5'],
    ['А-92', 'sysNetHintA92', 'Індикатор А-92']
  ];
  for (const [fKey, elId, labelPrefix] of map) {
    const el = document.getElementById(elId);
    const info = fp.fuels[fKey];
    if (el && info) {
      el.textContent = `${labelPrefix}: ${Number(info.internet_price).toFixed(2)} грн/л | Діюча: ${Number(info.effective_price).toFixed(2)} грн/л`;
    }
  }
}

async function loadAdminSystemSettings() {
  try {
    const res = await api('/system/settings');
    const s = res.settings || {};
    const fp = res.fuel_prices || null;

    if (document.getElementById('sysOrgName')) document.getElementById('sysOrgName').value = s.organization_name || 'MAXI-UA LLC';
    if (document.getElementById('sysTimezone')) document.getElementById('sysTimezone').value = s.facility_timezone || 'Europe/Kyiv';
    if (document.getElementById('sysWorkStart')) document.getElementById('sysWorkStart').value = s.work_schedule_start || '08:00';
    if (document.getElementById('sysWorkEnd')) document.getElementById('sysWorkEnd').value = s.work_schedule_end || '20:00';
    if (document.getElementById('sysMaintInterval')) document.getElementById('sysMaintInterval').value = s.default_maintenance_interval_hours ?? 300;
    if (document.getElementById('sysPriceA95')) document.getElementById('sysPriceA95').value = s.fuel_price_a95 ?? 0;
    if (document.getElementById('sysPriceA92')) document.getElementById('sysPriceA92').value = s.fuel_price_a92 ?? 0;
    if (document.getElementById('sysPriceDP')) document.getElementById('sysPriceDP').value = s.fuel_price_dp ?? 0;
    if (document.getElementById('sysEnforceSchedule')) document.getElementById('sysEnforceSchedule').checked = s.enforce_work_schedule !== false;
    if (document.getElementById('sysAutoFetchPrices')) document.getElementById('sysAutoFetchPrices').checked = s.auto_fetch_fuel_prices !== false;
    if (document.getElementById('sysApplyAllGens')) document.getElementById('sysApplyAllGens').checked = s.apply_to_all_generators !== false;

    // SMTP & Failover Settings
    if (document.getElementById('sysSmtpEnabled')) document.getElementById('sysSmtpEnabled').checked = s.smtp_enabled === true;
    if (document.getElementById('sysEmailNotifyPwdChange')) document.getElementById('sysEmailNotifyPwdChange').checked = s.email_notify_password_change !== false;
    if (document.getElementById('sysEmailNotifySafetyStop')) document.getElementById('sysEmailNotifySafetyStop').checked = s.email_notify_safety_stop !== false;
    if (document.getElementById('sysEmailWeeklyEnabled')) document.getElementById('sysEmailWeeklyEnabled').checked = s.email_weekly_report_enabled === true;
    if (document.getElementById('sysSmtpPrimaryHost')) document.getElementById('sysSmtpPrimaryHost').value = s.smtp_primary_host || 'smtp.gmail.com';
    if (document.getElementById('sysSmtpPrimaryPort')) document.getElementById('sysSmtpPrimaryPort').value = s.smtp_primary_port || 587;
    if (document.getElementById('sysSmtpPrimaryUser')) document.getElementById('sysSmtpPrimaryUser').value = s.smtp_primary_user || '';
    if (document.getElementById('sysSmtpPrimaryPassword')) document.getElementById('sysSmtpPrimaryPassword').value = s.smtp_primary_password || '';
    if (document.getElementById('sysSmtpPrimarySsl')) document.getElementById('sysSmtpPrimarySsl').checked = s.smtp_primary_ssl === true;
    if (document.getElementById('sysSmtpPrimaryFrom')) document.getElementById('sysSmtpPrimaryFrom').value = s.smtp_primary_from || '';

    if (document.getElementById('sysSmtpFallbackEnabled')) document.getElementById('sysSmtpFallbackEnabled').checked = s.smtp_fallback_enabled === true;
    if (document.getElementById('sysSmtpFallbackHost')) document.getElementById('sysSmtpFallbackHost').value = s.smtp_fallback_host || 'smtp.ukr.net';
    if (document.getElementById('sysSmtpFallbackPort')) document.getElementById('sysSmtpFallbackPort').value = s.smtp_fallback_port || 465;
    if (document.getElementById('sysSmtpFallbackUser')) document.getElementById('sysSmtpFallbackUser').value = s.smtp_fallback_user || '';
    if (document.getElementById('sysSmtpFallbackPassword')) document.getElementById('sysSmtpFallbackPassword').value = s.smtp_fallback_password || '';
    if (document.getElementById('sysSmtpFallbackSsl')) document.getElementById('sysSmtpFallbackSsl').checked = s.smtp_fallback_ssl !== false;
    if (document.getElementById('sysSmtpFallbackFrom')) document.getElementById('sysSmtpFallbackFrom').value = s.smtp_fallback_from || '';

    if (document.getElementById('sysEmailWeeklyRecipients')) document.getElementById('sysEmailWeeklyRecipients').value = s.email_weekly_recipients || '';
    if (document.getElementById('sysEmailWeeklyDay')) document.getElementById('sysEmailWeeklyDay').value = String(s.email_weekly_send_day ?? 0);
    if (document.getElementById('sysEmailWeeklyTime')) document.getElementById('sysEmailWeeklyTime').value = s.email_weekly_send_time || '08:00';

    renderAdminFuelPricesHints(fp);
  } catch (_) {}
}

window.refreshFuelPricesFromInternet = async function () {
  try {
    showToast('Запит актуальних цін з офіційного сайту АЗК WOG (wog.ua)...', 'info');
    const fp = await api('/system/fuel-prices/refresh', { method: 'POST' });
    renderAdminFuelPricesHints(fp);
    const dp = Number(fp?.fuels?.['ДП']?.internet_price ?? 103.50).toFixed(2);
    const a95 = Number(fp?.fuels?.['А-95']?.internet_price ?? 92.90).toFixed(2);
    const gas = Number(fp?.fuels?.['ГАЗ']?.internet_price ?? 52.50).toFixed(2);
    showToast(`Ціни АЗК WOG оновлено! ДП: ${dp} грн | А-95: ${a95} грн | ГАЗ: ${gas} грн`, 'success');
  } catch (_) {}
};

document.getElementById('systemSettingsForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    organization_name: document.getElementById('sysOrgName').value.trim() || 'MAXI-UA LLC',
    facility_timezone: document.getElementById('sysTimezone').value,
    work_schedule_start: document.getElementById('sysWorkStart').value,
    work_schedule_end: document.getElementById('sysWorkEnd').value,
    default_maintenance_interval_hours: parseFloat(document.getElementById('sysMaintInterval').value) || 300.0,
    fuel_price_a95: parseFloat(document.getElementById('sysPriceA95').value) || 0.0,
    fuel_price_a92: parseFloat(document.getElementById('sysPriceA92').value) || 0.0,
    fuel_price_dp: parseFloat(document.getElementById('sysPriceDP').value) || 0.0,
    enforce_work_schedule: document.getElementById('sysEnforceSchedule').checked,
    auto_fetch_fuel_prices: document.getElementById('sysAutoFetchPrices').checked,
    apply_to_all_generators: document.getElementById('sysApplyAllGens').checked,
    // SMTP & Failover Settings
    smtp_enabled: document.getElementById('sysSmtpEnabled')?.checked ?? false,
    email_notify_password_change: document.getElementById('sysEmailNotifyPwdChange')?.checked ?? true,
    email_notify_safety_stop: document.getElementById('sysEmailNotifySafetyStop')?.checked ?? true,
    email_notify_weekly_report: document.getElementById('sysEmailWeeklyEnabled')?.checked ?? false,
    email_weekly_report_enabled: document.getElementById('sysEmailWeeklyEnabled')?.checked ?? false,
    smtp_primary_host: document.getElementById('sysSmtpPrimaryHost')?.value.trim() || 'smtp.gmail.com',
    smtp_primary_port: parseInt(document.getElementById('sysSmtpPrimaryPort')?.value || '587', 10),
    smtp_primary_user: document.getElementById('sysSmtpPrimaryUser')?.value.trim() || '',
    smtp_primary_password: document.getElementById('sysSmtpPrimaryPassword')?.value || '',
    smtp_primary_ssl: document.getElementById('sysSmtpPrimarySsl')?.checked ?? false,
    smtp_primary_from: document.getElementById('sysSmtpPrimaryFrom')?.value.trim() || '',
    smtp_fallback_enabled: document.getElementById('sysSmtpFallbackEnabled')?.checked ?? false,
    smtp_fallback_host: document.getElementById('sysSmtpFallbackHost')?.value.trim() || 'smtp.ukr.net',
    smtp_fallback_port: parseInt(document.getElementById('sysSmtpFallbackPort')?.value || '465', 10),
    smtp_fallback_user: document.getElementById('sysSmtpFallbackUser')?.value.trim() || '',
    smtp_fallback_password: document.getElementById('sysSmtpFallbackPassword')?.value || '',
    smtp_fallback_ssl: document.getElementById('sysSmtpFallbackSsl')?.checked ?? true,
    smtp_fallback_from: document.getElementById('sysSmtpFallbackFrom')?.value.trim() || '',
    email_weekly_recipients: document.getElementById('sysEmailWeeklyRecipients')?.value.trim() || '',
    email_weekly_send_day: parseInt(document.getElementById('sysEmailWeeklyDay')?.value || '0', 10),
    email_weekly_send_time: document.getElementById('sysEmailWeeklyTime')?.value || '08:00'
  };

  try {
    const res = await api('/system/settings', { method: 'PUT', body: JSON.stringify(body) });
    renderAdminFuelPricesHints(res.fuel_prices);
    if (document.getElementById('sysApplyAllGens') && res.settings) {
      document.getElementById('sysApplyAllGens').checked = res.settings.apply_to_all_generators !== false;
    }
    showToast(res.message || 'Системні налаштування успішно збережено!', 'success');
    loadAllData();
  } catch (_) {}
});

window.toggleResetFacilitySelect = function () {
  const mode = document.getElementById('resetModeSelect')?.value;
  const grp = document.getElementById('resetFacilityGroup');
  if (grp) {
    grp.style.display = mode === 'facility_clean' ? 'block' : 'none';
  }
};

window.openSystemResetModal = async function () {
  if (!isSuperAdmin()) {
    showToast('Очищення даних та скидання БД доступне виключно Головному Суперадміністратору', 'warning');
    return;
  }
  try {
    const facilities = await api('/facilities');
    const sel = document.getElementById('resetFacilitySelect');
    if (sel && facilities) {
      sel.innerHTML = facilities.map((f) => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
      if (currentFacilityId && facilities.some((f) => f.id === currentFacilityId)) {
        sel.value = currentFacilityId;
      }
    }
  } catch (_) {}
  if (document.getElementById('resetAdminPassword')) document.getElementById('resetAdminPassword').value = '';
  if (document.getElementById('resetConfirmCode')) document.getElementById('resetConfirmCode').value = '';
  toggleResetFacilitySelect();
  openModal('modalSystemReset');
};

document.getElementById('systemResetForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const mode = document.getElementById('resetModeSelect').value;
  const facId = parseInt(document.getElementById('resetFacilitySelect')?.value || '0', 10) || currentFacilityId || 1;
  const adminPassword = document.getElementById('resetAdminPassword').value;
  const confirmCode = document.getElementById('resetConfirmCode').value.trim();

  try {
    const res = await api('/system/reset', {
      method: 'POST',
      body: JSON.stringify({
        mode: mode,
        facility_id: mode === 'facility_clean' ? facId : null,
        admin_password: adminPassword,
        confirm_code: confirmCode
      })
    });
    closeModal('modalSystemReset');
    showToast(res.message || 'Очищення успішно виконано!', 'success');
    if (mode === 'factory_reset') {
      localStorage.removeItem('sd_last_facility_id');
      localStorage.removeItem('sd_last_generator_id');
      currentFacilityId = null;
      currentGeneratorId = null;
    }
    await loadFacilitiesList();
    await loadGeneratorsList(currentFacilityId);
    await loadAllData();
    await loadAdminSystemSettings();
    await loadUsersData();
  } catch (_) {}
});

// ==========================================
// 8.1 System Backups Management (SuperAdmin Only)
// ==========================================

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '0 Б';
  const k = 1024;
  const sizes = ['Б', 'КБ', 'МБ', 'ГБ'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const val = (bytes / Math.pow(k, i)).toFixed(i === 0 ? 0 : 2);
  return `${val} ${sizes[i]}`;
}

let backupsCache = [];

window.loadBackupsList = async function (isUserTriggered = false) {
  if (!isSuperAdmin()) return;

  try {
    const res = await api('/backups');
    backupsCache = res.backups || [];

    // Update statistics badges
    const statCount = document.getElementById('backupStatCount');
    if (statCount) statCount.textContent = res.total_count ?? backupsCache.length;

    const statSize = document.getElementById('backupStatSize');
    if (statSize) statSize.textContent = formatBytes(res.total_size_bytes || 0);

    // Fetch and display schedule status
    try {
      const settRes = await api('/backups/settings');
      const sett = settRes.settings || settRes || {};
      const statSchedule = document.getElementById('backupStatSchedule');
      if (statSchedule) {
        if (sett.backup_auto_enabled) {
          const freqUa = sett.backup_frequency === 'weekly' ? 'щотижня' : 'щодня';
          const typeUa = sett.backup_default_type === 'full' ? 'повний' : 'частковий';
          statSchedule.innerHTML = `<span style="color: #4ade80;">Увімкнено (${freqUa} о ${escapeHtml(sett.backup_schedule_time || '03:00')}, тип: ${typeUa}, ротація: ${Number(sett.backup_retention_count || 7)})</span>`;
        } else {
          statSchedule.innerHTML = `<span style="color: #94a3b8;">Вимкнено (лише вручну)</span>`;
        }
      }
    } catch (_) {}

    // Render table rows
    const tbody = document.querySelector('#backupsTable tbody');
    if (tbody) {
      if (backupsCache.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">Резервних копій ще не створено. Натисніть «➕ Створити бекап зараз» для першого збереження.</td></tr>';
      } else {
        tbody.innerHTML = backupsCache.map((b) => {
          const rawType = b.backup_type || b.type || 'full';
          const isFull = rawType === 'full';
          const typeLabel = isFull ? '📦 Повний' : '📑 Частковий';
          const badgeClass = isFull ? 'badge-running' : 'badge-blocked';
          const fileSafe = escapeHtml(b.filename).replace(/'/g, "\\'");
          const noteText = b.notes || b.note || '';
          const infoDetails = isFull
            ? `Таблиць: <b>${Number(b.tables_count || 0)}</b> | Записів: <b>${Number(b.records_count || 0)}</b> | Файлів сервера: <b>${Number(b.files_count || 0)}</b>`
            : `Таблиць: <b>${Number(b.tables_count || 0)}</b> | Записів: <b>${Number(b.records_count || 0)}</b> | <span>Конфіг + .env</span>`;

          return `
            <tr>
              <td style="white-space: nowrap;">${formatDateTime(b.created_at)}</td>
              <td><span class="badge ${badgeClass}" title="${escapeHtml(b.backup_type_ua || typeLabel)}">${typeLabel}</span></td>
              <td><code style="font-size: 0.82rem; color: #38bdf8;">${escapeHtml(b.filename)}</code></td>
              <td style="white-space: nowrap;"><b>${formatBytes(b.size_bytes)}</b></td>
              <td style="font-size: 0.85rem;">${infoDetails}</td>
              <td>
                <div style="font-weight: 600;">${escapeHtml(b.created_by || 'system')}</div>
                ${noteText ? `<div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 0.15rem;">${escapeHtml(noteText)}</div>` : ''}
              </td>
              <td style="text-align: center; white-space: nowrap;">
                <div style="display: flex; gap: 0.4rem; justify-content: center; align-items: center;">
                  <button type="button" class="btn-action" style="padding: 0.3rem 0.65rem; min-height: auto; font-size: 0.8rem; border-color: #38bdf8; color: #38bdf8;" onclick="downloadBackup('${fileSafe}')" title="Завантажити архів бекапу (.zip)">
                    📥 Завантажити
                  </button>
                  <button type="button" class="btn-action" style="padding: 0.3rem 0.65rem; min-height: auto; font-size: 0.8rem; border-color: #f97316; color: #fb923c;" onclick="openRestoreModal('${fileSafe}')" title="Відновити систему з цього бекапу">
                    🔄 Відновити
                  </button>
                  <button type="button" class="btn-action" style="padding: 0.3rem 0.6rem; min-height: auto; font-size: 0.8rem; border-color: #ef4444; color: #f87171;" onclick="openDeleteBackupModal('${fileSafe}')" title="Видалити бекап">
                    🗑️
                  </button>
                </div>
              </td>
            </tr>
          `;
        }).join('');
      }
    }

    if (isUserTriggered) {
      showToast('Список резервних копій оновлено!', 'success');
    }
  } catch (err) {
    if (isUserTriggered) {
      showToast(`Помилка завантаження бекапів: ${err.message || 'Невідома помилка'}`, 'error');
    }
  }
};

window.openCreateBackupModal = function () {
  if (!isSuperAdmin()) {
    showToast('Створення бекапів доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const noteInput = document.getElementById('backupNote');
  if (noteInput) noteInput.value = '';
  const radioFull = document.querySelector('input[name="backupTypeChoice"][value="full"]');
  if (radioFull) radioFull.checked = true;
  openModal('modalCreateBackup');
};

document.getElementById('createBackupForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!isSuperAdmin()) {
    showToast('Створення бекапів доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }

  const submitBtn = document.getElementById('btnSubmitCreateBackup');
  const typeVal = document.querySelector('input[name="backupTypeChoice"]:checked')?.value || 'full';
  const noteVal = document.getElementById('backupNote')?.value.trim() || null;

  try {
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerText = '⏳ Створення архіву...';
    }
    showToast('Формування резервної копії системи. Зачекайте...', 'info');

    const res = await api('/backups', {
      method: 'POST',
      body: JSON.stringify({ backup_type: typeVal, type: typeVal, notes: noteVal, note: noteVal })
    });

    closeModal('modalCreateBackup');
    showToast(res.message || 'Резервну копію успішно створено!', 'success');
    await loadBackupsList();
  } catch (err) {
    showToast(err.message || 'Помилка створення резервної копії', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerText = '🚀 Запустити створення';
    }
  }
});

window.downloadBackup = async function (filename) {
  if (!isSuperAdmin()) {
    showToast('Завантаження бекапів доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }

  try {
    showToast(`Завантаження резервної копії ${filename}...`, 'info');
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(`/api/v1/backups/${encodeURIComponent(filename)}/download`, {
      headers,
      credentials: 'same-origin'
    });
    if (!res.ok) {
      let errMsg = `Помилка сервера при завантаженні (${res.status})`;
      try {
        const errJson = await res.json();
        errMsg = extractErrorMessage(errJson, errMsg);
      } catch (_) {}
      throw new Error(errMsg);
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast(`Файл ${filename} успішно завантажено!`, 'success');
  } catch (err) {
    showToast(err.message || 'Помилка завантаження резервної копії', 'error');
  }
};

window.openDeleteBackupModal = function (filename) {
  if (!isSuperAdmin()) {
    showToast('Видалення бекапів доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const disp = document.getElementById('deleteBackupFilenameDisplay');
  if (disp) disp.textContent = filename;
  const hid = document.getElementById('deleteBackupFilenameHidden');
  if (hid) hid.value = filename;
  openModal('modalDeleteBackup');
};

window.confirmDeleteCurrentBackup = async function () {
  if (!isSuperAdmin()) {
    showToast('Видалення бекапів доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const hid = document.getElementById('deleteBackupFilenameHidden');
  const filename = hid?.value;
  if (!filename) return;

  const btn = document.getElementById('confirmDeleteBackupBtn');
  try {
    if (btn) {
      btn.disabled = true;
      btn.innerText = '⏳ Видалення...';
    }
    const res = await api(`/backups/${encodeURIComponent(filename)}`, {
      method: 'DELETE'
    });
    closeModal('modalDeleteBackup');
    showToast(res.message || `Бекап ${filename} успішно видалено!`, 'success');
    await loadBackupsList();
  } catch (err) {
    showToast(err.message || 'Помилка видалення резервної копії', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = 'Підтвердити видалення';
    }
  }
};

window.openRestoreModal = async function (filename) {
  if (!isSuperAdmin()) {
    showToast('Відновлення з бекапу доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const dispName = document.getElementById('restoreFilenameDisplay');
  const dispDetails = document.getElementById('restoreDetailsDisplay');
  const hidName = document.getElementById('restoreFilenameHidden');
  const confirmWord = document.getElementById('restoreConfirmWordInput');

  if (dispName) dispName.textContent = filename;
  if (hidName) hidName.value = filename;
  if (confirmWord) confirmWord.value = '';
  if (dispDetails) dispDetails.innerHTML = '<i>Завантаження метаданих архіву...</i>';

  openModal('modalConfirmRestore');

  try {
    const res = await api(`/backups/${encodeURIComponent(filename)}/inspect`);
    const m = res.manifest || {};
    const bType = m.backup_type_ua || (m.backup_type === 'full' ? 'Повний бекап' : 'Частковий бекап');
    const records = m.records_count ?? 0;
    const tables = m.tables_count ?? 0;
    const size = res.size_formatted || '';
    if (dispDetails) {
      dispDetails.innerHTML = `
        <b>Тип:</b> ${escapeHtml(bType)} | <b>Розмір:</b> ${escapeHtml(size)}<br>
        <b>Створено:</b> ${formatDateTime(m.created_at)} (автор: <b>${escapeHtml(m.created_by || 'system')}</b>)<br>
        <b>Вміст БД:</b> ${Number(tables)} таблиць (${Number(records)} записів)
      `;
    }
  } catch (err) {
    if (dispDetails) dispDetails.textContent = `Попередження: не вдалося завантажити розширені метадані: ${err.message}`;
  }
};

document.getElementById('confirmRestoreForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!isSuperAdmin()) {
    showToast('Відновлення системи доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }

  const filename = document.getElementById('restoreFilenameHidden')?.value;
  const word = document.getElementById('restoreConfirmWordInput')?.value?.trim() || '';
  const restoreFiles = document.getElementById('restoreFilesCheckbox')?.checked ?? true;
  const btn = document.getElementById('btnSubmitRestore');

  if (word.toUpperCase() !== 'ВІДНОВИТИ') {
    showToast('Введіть точне слово ВІДНОВИТИ для підтвердження!', 'error');
    return;
  }

  try {
    if (btn) {
      btn.disabled = true;
      btn.innerText = '⏳ Відновлення системи... Зачекайте...';
    }
    showToast('Розпочато процедуру відновлення бази даних. Створюється snapshot безпеки...', 'info');

    const res = await api(`/backups/${encodeURIComponent(filename)}/restore`, {
      method: 'POST',
      body: JSON.stringify({
        confirmation: word,
        restore_files: restoreFiles
      })
    });

    closeModal('modalConfirmRestore');
    showToast(res.message || 'Систему успішно відновлено!', 'success');
    await loadBackupsList();

    if (typeof loadOverviewData === 'function') loadOverviewData();
  } catch (err) {
    showToast(err.message || 'Помилка відновлення системи', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '🔄 Підтвердити та відновити';
    }
  }
});

window.openUploadRestoreModal = function () {
  if (!isSuperAdmin()) {
    showToast('Відновлення з бекапу доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const fileInput = document.getElementById('uploadRestoreFileInput');
  const confirmWord = document.getElementById('uploadRestoreConfirmWordInput');
  if (fileInput) fileInput.value = '';
  if (confirmWord) confirmWord.value = '';
  openModal('modalUploadRestore');
};

document.getElementById('btnOpenUploadRestore')?.addEventListener('click', (e) => {
  e.preventDefault();
  openUploadRestoreModal();
});

document.getElementById('uploadRestoreForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!isSuperAdmin()) {
    showToast('Відновлення системи доступне виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }

  const fileInput = document.getElementById('uploadRestoreFileInput');
  const file = fileInput?.files?.[0];
  if (!file) {
    showToast('Оберіть zip-файл резервної копії для завантаження!', 'warning');
    return;
  }

  const word = document.getElementById('uploadRestoreConfirmWordInput')?.value?.trim() || '';
  if (word.toUpperCase() !== 'ВІДНОВИТИ') {
    showToast('Введіть точне слово ВІДНОВИТИ для підтвердження!', 'error');
    return;
  }

  const restoreFiles = document.getElementById('uploadRestoreFilesCheckbox')?.checked ?? true;
  const btn = document.getElementById('btnSubmitUploadRestore');

  const formData = new FormData();
  formData.append('file', file);
  formData.append('confirmation', word);
  formData.append('restore_files', restoreFiles ? 'true' : 'false');

  try {
    if (btn) {
      btn.disabled = true;
      btn.innerText = '⏳ Завантаження та розгортання...';
    }
    showToast('Завантаження архіву на сервер та відновлення даних...', 'info');

    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/v1/backups/upload-restore', {
      method: 'POST',
      headers,
      body: formData,
      credentials: 'same-origin'
    });

    if (!response.ok) {
      let errMsg = `Помилка відновлення (${response.status})`;
      try {
        const errJson = await response.json();
        errMsg = extractErrorMessage(errJson, errMsg);
      } catch (_) {}
      throw new Error(errMsg);
    }

    const res = await response.json();
    closeModal('modalUploadRestore');
    showToast(res.message || 'Архів завантажено та систему успішно відновлено!', 'success');
    await loadBackupsList();

    if (typeof loadOverviewData === 'function') loadOverviewData();
  } catch (err) {
    showToast(err.message || 'Помилка завантаження або відновлення архіву', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '🚀 Завантажити та відновити';
    }
  }
});

window.openBackupSettingsModal = async function () {
  if (!isSuperAdmin()) {
    showToast('Налаштування розкладу доступні виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }

  try {
    const res = await api('/backups/settings');
    const s = res.settings || res || {};

    const chkAuto = document.getElementById('cfgBackupAutoEnabled');
    if (chkAuto) chkAuto.checked = Boolean(s.backup_auto_enabled);

    const inpTime = document.getElementById('cfgBackupScheduleTime');
    if (inpTime) inpTime.value = (s.backup_schedule_time || '03:00').slice(0, 5);

    const selFreq = document.getElementById('cfgBackupFrequency');
    if (selFreq) selFreq.value = s.backup_frequency || 'daily';

    const selType = document.getElementById('cfgBackupDefaultType');
    if (selType) {
      const defType = (s.backup_default_type === 'partial' || s.backup_default_type === 'db_only') ? 'partial' : 'full';
      selType.value = defType;
    }

    const inpRet = document.getElementById('cfgBackupRetentionCount');
    if (inpRet) inpRet.value = s.backup_retention_count ?? 7;

    openModal('modalBackupSettings');
  } catch (err) {
    showToast(`Помилка отримання налаштувань: ${err.message || 'Невідома помилка'}`, 'error');
  }
};

document.getElementById('backupSettingsForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!isSuperAdmin()) {
    showToast('Налаштування розкладу доступні виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }

  const btn = document.getElementById('btnSubmitSaveBackupSettings');
  const autoEnabled = Boolean(document.getElementById('cfgBackupAutoEnabled')?.checked);
  const schedTime = (document.getElementById('cfgBackupScheduleTime')?.value || '03:00').trim().slice(0, 5);
  const freq = document.getElementById('cfgBackupFrequency')?.value || 'daily';
  const defType = document.getElementById('cfgBackupDefaultType')?.value || 'full';
  const retCount = parseInt(document.getElementById('cfgBackupRetentionCount')?.value || '7', 10);

  try {
    if (btn) {
      btn.disabled = true;
      btn.innerText = '⏳ Збереження...';
    }
    const res = await api('/backups/settings', {
      method: 'PUT',
      body: JSON.stringify({
        backup_auto_enabled: autoEnabled,
        backup_schedule_time: schedTime,
        backup_frequency: freq,
        backup_default_type: defType,
        backup_retention_count: retCount
      })
    });

    closeModal('modalBackupSettings');
    showToast(res.message || 'Налаштування автобекапу успішно збережено!', 'success');
    await loadBackupsList();
  } catch (err) {
    showToast(err.message || 'Помилка збереження налаштувань автобекапу', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '💾 Зберегти налаштування';
    }
  }
});

// ==========================================
// 9. Push Notifications & PWA Mobile Alerts
// ==========================================

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function checkPushSubscriptionStatus() {
  const badge = document.getElementById('pushStatusBadge');
  const infoText = document.getElementById('pushDeviceInfoText');
  const btnSub = document.getElementById('btnSubscribePush');
  const btnUnsub = document.getElementById('btnUnsubscribePush');

  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    if (badge) {
      badge.className = 'badge badge-faulty';
      badge.innerText = 'НЕ ПІДТРИМУЄТЬСЯ';
    }
    if (infoText) {
      infoText.innerHTML = '⚠️ Ваш поточний браузер не підтримує Web Push API. Для отримання системних сповіщень у шторку використовуйте Google Chrome, Samsung Internet або встановіть додаток через меню PWA.';
    }
    if (btnSub) btnSub.style.display = 'none';
    if (btnUnsub) btnUnsub.style.display = 'none';
    return;
  }

  const permission = Notification.permission;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();

    if (sub && permission === 'granted') {
      if (badge) {
        badge.className = 'badge badge-running';
        badge.innerText = 'АКТИВНО 📲';
      }
      if (infoText) {
        infoText.innerHTML = '✅ <b>Сповіщення увімкнено!</b> Цей пристрій успішно підписаний на системні сповіщення. Повідомлення надходитимуть у шторку Android та на екран блокування.';
      }
      if (btnSub) btnSub.style.display = 'none';
      if (btnUnsub) btnUnsub.style.display = 'inline-block';
    } else if (permission === 'denied') {
      if (badge) {
        badge.className = 'badge badge-faulty';
        badge.innerText = 'ЗАБЛОКОВАНО';
      }
      if (infoText) {
        infoText.innerHTML = '🚫 <b>Дозвіл заблоковано в налаштуваннях браузера.</b> Щоб отримувати сповіщення, натисніть на значок замочка біля адреси сайту та дозвольте «Сповіщення».';
      }
      if (btnSub) {
        btnSub.style.display = 'inline-block';
        btnSub.disabled = true;
      }
      if (btnUnsub) btnUnsub.style.display = 'none';
    } else {
      if (badge) {
        badge.className = 'badge badge-stopped';
        badge.innerText = 'НЕ ПІДКЛЮЧЕНО';
      }
      if (infoText) {
        infoText.innerHTML = 'ℹ️ Сповіщення на цьому пристрої ще не увімкнені. Натисніть кнопку нижче, щоб отримувати нагадування про ТО, старт/стоп та залишок палива.';
      }
      if (btnSub) {
        btnSub.style.display = 'inline-block';
        btnSub.disabled = false;
      }
      if (btnUnsub) btnUnsub.style.display = 'none';
    }
  } catch (err) {
    console.warn('Error checking push subscription:', err);
  }
}

window.subscribeDevicePush = async function() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    showToast('Web Push не підтримується цим браузером', 'error');
    return;
  }

  try {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') {
      showToast('Дозвіл на сповіщення не надано користувачем', 'warning');
      checkPushSubscriptionStatus();
      return;
    }

    // Get VAPID public key from backend
    const vapidRes = await api('/notifications/vapid-public-key');
    const applicationServerKey = urlBase64ToUint8Array(vapidRes.public_key);

    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: applicationServerKey
      });
    }

    const subJson = sub.toJSON();
    await api('/notifications/subscribe', {
      method: 'POST',
      body: JSON.stringify({
        endpoint: sub.endpoint,
        keys: {
          p256dh: subJson.keys.p256dh,
          auth: subJson.keys.auth
        },
        user_agent: navigator.userAgent,
        facility_id: currentFacilityId || null
      })
    });

    showToast('Пристрій успішно підписано на сповіщення!', 'success');
    checkPushSubscriptionStatus();
    loadNotificationSettings();
  } catch (err) {
    showToast('Помилка підписки: ' + err.message, 'error');
  }
};

window.unsubscribeDevicePush = async function() {
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await api('/notifications/unsubscribe', {
        method: 'POST',
        body: JSON.stringify({ endpoint: sub.endpoint })
      });
      await sub.unsubscribe();
    }
    showToast('Сповіщення для цього пристрою вимкнено', 'info');
    checkPushSubscriptionStatus();
    loadNotificationSettings();
  } catch (err) {
    showToast('Помилка відписки: ' + err.message, 'error');
  }
};

window.triggerTestPushNotification = async function() {
  try {
    showToast('Відправка тестового сповіщення...', 'info');
    const res = await api('/notifications/test', {
      method: 'POST',
      body: JSON.stringify({
        title: '🔔 Тестове сповіщення Service Desk',
        body: 'Система сповіщень працює належним чином на вашому пристрої!'
      })
    });

    // Also trigger local notification if permission is granted as an instant preview
    if (Notification.permission === 'granted' && navigator.serviceWorker) {
      const reg = await navigator.serviceWorker.ready;
      reg.showNotification('🔔 Тестове сповіщення Service Desk', {
        body: 'Перевірка звуку, вібрації та шторки повідомлень виконана успішно!',
        icon: '/frontend/icons/icon-192.png',
        badge: '/frontend/icons/icon-192.png',
        vibrate: [200, 100, 200],
        tag: 'sd-test'
      });
    }

    showToast(`Тестове сповіщення успішно надіслано (доставлено: ${res.sent || 1})`, 'success');
    loadNotificationLogs();
  } catch (err) {
    showToast('Помилка відправки: ' + err.message, 'error');
  }
};

async function loadNotificationSettings() {
  try {
    const s = await api('/notifications/settings');
    const setCheck = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };

    setCheck('notifMasterEnabled', s.notifications_enabled);
    setCheck('notifStartEnabled', s.notify_generator_start);
    setCheck('notifStopEnabled', s.notify_generator_stop);
    setCheck('notifLowFuelEnabled', s.notify_low_fuel);
    setVal('notifLowFuelThreshold', s.low_fuel_threshold_l);
    setCheck('notifMaintEnabled', s.notify_maintenance);
    setVal('notifMaxMaintPerDay', s.max_maintenance_notifications_per_day);
    setCheck('notifFaultsEnabled', s.notify_critical_faults);
  } catch (_) {}
}

window.saveNotificationSettings = async function(e) {
  if (e) e.preventDefault();
  const body = {
    notifications_enabled: document.getElementById('notifMasterEnabled')?.checked ?? true,
    notify_generator_start: document.getElementById('notifStartEnabled')?.checked ?? true,
    notify_generator_stop: document.getElementById('notifStopEnabled')?.checked ?? true,
    notify_low_fuel: document.getElementById('notifLowFuelEnabled')?.checked ?? true,
    low_fuel_threshold_l: parseFloat(document.getElementById('notifLowFuelThreshold')?.value || '5.0'),
    notify_maintenance: document.getElementById('notifMaintEnabled')?.checked ?? true,
    max_maintenance_notifications_per_day: parseInt(document.getElementById('notifMaxMaintPerDay')?.value || '2', 10),
    notify_critical_faults: document.getElementById('notifFaultsEnabled')?.checked ?? true
  };

  try {
    await api('/notifications/settings', {
      method: 'PUT',
      body: JSON.stringify(body)
    });
    showToast('Налаштування сповіщень успішно збережено!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
};

async function loadNotificationLogs() {
  try {
    const logs = await api('/notifications/logs?limit=30');
    const tbody = document.querySelector('#notifLogsTable tbody');
    if (!tbody) return;

    const eventIcons = {
      'GENERATOR_START': '🟢 Пуск',
      'GENERATOR_STOP': '🔴 Зупинка',
      'LOW_FUEL': '⚠️ Паливо',
      'MAINTENANCE_DUE': '🔧 ТО',
      'CRITICAL_FAULT': '🚨 Аварія',
      'TEST': '📲 Тест'
    };

    tbody.innerHTML = logs.map(l => `
      <tr>
        <td>${formatDateTime(l.created_at)}</td>
        <td><b>${eventIcons[l.event_type] || l.event_type}</b></td>
        <td><b>${escapeHtml(l.title)}</b></td>
        <td>${escapeHtml(l.body)}</td>
        <td>${l.recipients_count} пристр.</td>
        <td>
          <span style="color: ${l.success_count > 0 ? '#4ade80' : 'var(--text-muted)'};">
            ${l.success_count > 0 ? `✅ Доставлено (${l.success_count})` : (l.recipients_count === 0 ? 'ℹ️ Без підписників' : '⚠️ Помилка')}
          </span>
        </td>
      </tr>
    `).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-muted)">Журнал сповіщень порожній</td></tr>';
  } catch (_) {}
}

// Initialization on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  startClock();
  setupPwaInstall();
  checkAuth();
  refreshServerStatus();
  setInterval(refreshServerStatus, 30000);
  setTimeout(checkPushSubscriptionStatus, 1500);

  // Check for reset_token in URL query parameters
  const urlParams = new URLSearchParams(window.location.search);
  const resetToken = urlParams.get('reset_token');
  if (resetToken) {
    const tokenInput = document.getElementById('resetPasswordToken');
    if (tokenInput) tokenInput.value = resetToken;
    openModal('modalResetPassword');
    try {
      window.history.replaceState({}, document.title, window.location.pathname);
    } catch (_) {}
  }

  // Periodic background refresh for dashboard tiles (updates metrics live without manual F5)
  setInterval(() => {
    if (token && currentUser) {
      loadGeneratorData();
      if (!isViewerOnly() && hasPermission('fuel:view')) {
        loadFuelSummary();
      }
      if (!isViewerOnly() && hasPermission('maintenance:view')) {
        loadMaintenanceSummary();
      }
    }
  }, 15000);
});




// ---------------------------------------------------------------------------
// Email System & Password Reset Handlers
// ---------------------------------------------------------------------------

window.openForgotPasswordModal = function () {
  const input = document.getElementById('forgotLoginOrEmail');
  if (input) input.value = '';
  const fb = document.getElementById('forgotPasswordFeedback');
  if (fb) {
    fb.style.display = 'none';
    fb.innerText = '';
  }
  openModal('modalForgotPassword');
};

document.getElementById('forgotPasswordForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('forgotLoginOrEmail')?.value.trim();
  const btn = document.getElementById('btnSubmitForgotPassword');
  const fb = document.getElementById('forgotPasswordFeedback');

  if (!input) {
    showToast('Будь ласка, введіть логін або email', 'warning');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerText = 'Надсилання...';
  }

  try {
    const res = await api('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ login_or_email: input })
    });
    if (fb) {
      fb.style.display = 'block';
      fb.style.background = 'rgba(34, 197, 94, 0.15)';
      fb.style.border = '1px solid rgba(34, 197, 94, 0.4)';
      fb.style.color = '#4ade80';
      fb.innerText = res.message || 'Якщо користувача знайдено, посилання надіслано на вашу пошту.';
    }
    showToast('Запит прийнято! Перевірте поштову скриньку', 'success');
  } catch (err) {
    if (fb) {
      fb.style.display = 'block';
      fb.style.background = 'rgba(239, 68, 68, 0.15)';
      fb.style.border = '1px solid rgba(239, 68, 68, 0.4)';
      fb.style.color = '#f87171';
      fb.innerText = err.message || 'Помилка надсилання запиту';
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '✉️ Надіслати посилання';
    }
  }
});

document.getElementById('resetPasswordForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const tokenVal = document.getElementById('resetPasswordToken')?.value.trim();
  const newPwd = document.getElementById('resetPasswordNew')?.value;
  const confirmPwd = document.getElementById('resetPasswordConfirm')?.value;
  const btn = document.getElementById('btnSubmitResetPassword');
  const fb = document.getElementById('resetPasswordFeedback');

  if (!tokenVal) {
    showToast('Введіть токен відновлення', 'warning');
    return;
  }
  if (!newPwd || newPwd.length < 8) {
    showToast('Пароль повинен містити щонайменше 8 символів', 'warning');
    return;
  }
  if (newPwd !== confirmPwd) {
    if (fb) {
      fb.style.display = 'block';
      fb.style.background = 'rgba(239, 68, 68, 0.15)';
      fb.style.border = '1px solid rgba(239, 68, 68, 0.4)';
      fb.style.color = '#f87171';
      fb.innerText = 'Введені паролі не співпадають!';
    }
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerText = 'Збереження...';
  }

  try {
    const res = await api('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token: tokenVal, new_password: newPwd })
    });
    closeModal('modalResetPassword');
    showToast(res.message || 'Пароль успішно змінено! Увійдіть з новим паролем.', 'success');
    showAuthScreen();
  } catch (err) {
    if (fb) {
      fb.style.display = 'block';
      fb.style.background = 'rgba(239, 68, 68, 0.15)';
      fb.style.border = '1px solid rgba(239, 68, 68, 0.4)';
      fb.style.color = '#f87171';
      fb.innerText = err.message || 'Помилка скидання пароля';
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '💾 Зберегти новий пароль';
    }
  }
});

window.triggerSmtpTest = async function (provider) {
  const defaultEmail = currentUser?.email || document.getElementById('sysSmtpPrimaryUser')?.value || '';
  const recipient = prompt(`Введіть адресу email для отримання тестового листа (${provider.toUpperCase()}):`, defaultEmail);
  if (!recipient || !recipient.trim()) return;

  try {
    showToast(`Надсилання тестового листа через ${provider.toUpperCase()}...`, 'info');
    const res = await api('/system/email/test', {
      method: 'POST',
      body: JSON.stringify({ recipient: recipient.trim(), provider: provider })
    });
    if (res.warning) {
      showToast(`⚠️ ${res.warning}`, 'warning');
    } else {
      showToast(`✅ Тестовий лист успішно надіслано на ${recipient} (через ${res.provider?.toUpperCase()} SMTP)!`, 'success');
    }
  } catch (err) {
    showToast(`❌ Помилка SMTP тесту: ${err.message}`, 'error');
  }
};

window.triggerManualWeeklyReportEmail = async function () {
  const configured = document.getElementById('sysEmailWeeklyRecipients')?.value.trim() || currentUser?.email || '';
  const recipient = prompt('Введіть адреси email для відправки щотижневого звіту (через кому):', configured);
  if (!recipient || !recipient.trim()) return;

  try {
    showToast('Генерація книги Excel та надсилання звіту на email...', 'info');
    const res = await api(`/system/email/weekly-digest/send?recipient=${encodeURIComponent(recipient.trim())}`, {
      method: 'POST'
    });
    showToast(res.message || 'Звіт Excel успішно відправлено на пошту!', 'success');
  } catch (err) {
    showToast(`❌ Помилка відправки звіту: ${err.message}`, 'error');
  }
};
