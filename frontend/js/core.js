// ==========================================
// 🛡️ Anti-Phishing & Unauthorized Mirror Protection
// ==========================================
(function checkDomainIntegrity() {
  // Read dynamic primary domain injected from .env via meta tag or global config
  const metaDomain = document.querySelector('meta[name="app-primary-domain"]')?.getAttribute('content');
  const primaryDomain = (metaDomain || window.__APP_PRIMARY_DOMAIN__ || 'sdgen.pp.ua').toLowerCase().trim();

  const allowedHosts = [
    primaryDomain,
    `www.${primaryDomain}`,
    'sdgen.pp.ua',
    'www.sdgen.pp.ua',
    'generator-016.pp.ua',
    'www.generator-016.pp.ua',
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
    const targetState = isAllowed ? 'allowed' : (viewer ? 'locked-viewer' : 'locked-op');
    if (tab.getAttribute('data-role-state') === targetState) return;
    tab.setAttribute('data-role-state', targetState);
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
    if (typeof window.switchTab === 'function') {
      window.switchTab('tab-dashboard');
    } else {
      const dashTab = document.querySelector('.nav-item[data-tab="tab-dashboard"]');
      if (dashTab) {
        document.querySelectorAll('.nav-item').forEach((t) => t.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach((p) => (p.style.display = 'none'));
        dashTab.classList.add('active');
        const dashPane = document.getElementById('tab-dashboard');
        if (dashPane) dashPane.style.display = 'block';
      }
    }
  }

  // Update mobile navigation items visibility
  document.querySelectorAll('.mobile-more-item').forEach((item) => {
    const paneId = item.getAttribute('data-tab');
    if (!paneId) return;
    const isAllowed = tabRules[paneId] ?? true;
    item.style.display = isAllowed ? 'flex' : 'none';
  });
  document.querySelectorAll('.mobile-nav-btn').forEach((btn) => {
    const paneId = btn.getAttribute('data-tab');
    if (!paneId) return;
    const isAllowed = tabRules[paneId] ?? true;
    btn.style.opacity = isAllowed ? '' : '0.35';
    btn.style.pointerEvents = isAllowed ? '' : 'none';
  });

  // 2. Helper to set button state with visual lock
  const setBtnState = (btnId, isAllowed, reason, lockedHtml = null) => {
    const b = document.getElementById(btnId);
    if (!b) return;
    const stateKey = isAllowed ? 'allowed' : `locked:${reason}`;
    if (b.getAttribute('data-role-state') === stateKey && b.disabled === !isAllowed) return;
    b.setAttribute('data-role-state', stateKey);
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
  setBtnState('deleteFacilityBtn', canConfigFacility, "Видалення об'єктів доступне лише Адміністратору 🔒", "🗑️🔒");

  // Rigid facility binding for non-admin operators
  const mainFacSelect = document.getElementById('facilitySelect');
  if (mainFacSelect) {
    if (!isAdmin() && currentUser && currentUser.facility_id) {
      mainFacSelect.disabled = true;
      mainFacSelect.title = `Закріплено за вашим робочим об'єктом 🔒`;
    } else {
      mainFacSelect.disabled = false;
      mainFacSelect.removeAttribute('title');
    }
  }

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
  const btnTransferEl = document.getElementById('btnQuickTransfer');
  if (btnTransferEl) {
    const isDeficit = currentGenerator && (currentGenerator.fuel_tank_level_l <= 0);
    if (isDeficit && !viewer && hasPermission('fuel:transfer')) {
      btnTransferEl.classList.add('btn-action-refuel-highlight');
    } else {
      btnTransferEl.classList.remove('btn-action-refuel-highlight');
    }
  }
  setBtnState('btnQuickReceipt', !viewer && hasPermission('fuel:receipt'), 'Оприбуткування палива недоступне для вашої ролі 🔒', '<span class="icon">📥</span><span>+ Прийняти паливо 🔒</span>');
  setBtnState('btnQuickMaint', !viewer && (hasPermission('maintenance:create_intermediate') || hasPermission('maintenance:perform_scheduled')), 'Фіксація ТО недоступна для вашої ролі 🔒', '<span class="icon">🛠️</span><span>Зафіксувати ТО 🔒</span>');
  setBtnState('btnQuickFault', !viewer && hasPermission('faults:create'), 'Реєстрація несправності недоступна для вашої ролі 🔒', '<span class="icon">⚠️</span><span>Несправність 🔒</span>');

  // Fuel stock creation button (Admin/Superadmin only)
  const canConfigFuel = hasPermission('fuel:configure');
  setBtnState('btnFuelNewStock', canConfigFuel, 'Створення складу ГСМ доступне лише Адміністратору 🔒', '📦 + Додати склад ГСМ 🔒');
  setBtnState('btnFuelNewCanisterPool', canConfigFuel, 'Налаштування пулів каністр доступне лише Адміністратору 🔒', '🛢️ + Пул каністр 🔒');
  setBtnState('btnFuelReceipt', hasPermission('fuel:receipt'), 'Оприбуткування палива недоступне для вашої ролі 🔒', '+ Оприбуткувати 🔒');
  setBtnState('btnFuelTransfer', hasPermission('fuel:transfer'), 'Заправка бака недоступна для вашої ролі 🔒', '⛽ Заправити бак 🔒');

  // Maintenance buttons
  const canPerformSched = hasPermission('maintenance:perform_scheduled');
  setBtnState('btnRecalculateMaint', canPerformSched, 'Перерахунок нормативу ТО доступний лише Адміністратору 🔒', '🔄 Перерахувати 🔒');
  setBtnState('btnOpenMaintModal', hasPermission('maintenance:create_intermediate') || canPerformSched, 'Фіксація ТО недоступна для вашої ролі 🔒', '+ Зафіксувати ТО 🔒');

  const btnAdminResetMaint = document.getElementById('btnAdminResetMaint');
  if (btnAdminResetMaint) {
    btnAdminResetMaint.style.display = (canPerformSched || isAdmin()) ? 'inline-flex' : 'none';
  }

  const btnClearNotifLogs = document.getElementById('btnClearNotifLogs');
  if (btnClearNotifLogs) {
    btnClearNotifLogs.style.display = isAdmin() ? 'inline-flex' : 'none';
  }

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

  // Audit & adjustments buttons (SuperAdmin only!)
  setBtnState('btnOpenExportAudit', superadmin, 'Експорт аудиту в Excel доступний виключно Головному Суперадміністратору 🔒', '📊 Експорт аудиту в Excel 🔒');
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
let _toastTimerId = null;
function showToast(message, type = 'info', durationMs = 4000) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.innerText = message;
  toast.className = `toast ${type}`;
  toast.style.display = 'block';
  if (_toastTimerId) clearTimeout(_toastTimerId);
  _toastTimerId = setTimeout(() => {
    toast.style.display = 'none';
    _toastTimerId = null;
  }, durationMs);
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
  if (id === 'modalExportAudit' && !isSuperAdmin()) {
    showToast('Експорт аудиту в Excel доступний виключно Головному Суперадміністратору', 'warning');
    return;
  }
  if ((id === 'modalCreateBackup' || id === 'modalBackupSettings' || id === 'modalDeleteBackup' || id === 'modalConfirmRestore' || id === 'modalUploadRestore') && !isSuperAdmin()) {
    showToast('Керування резервними копіями та відновлення доступні виключно Головному Суперадміністратору', 'warning');
    return;
  }
  if ((id === 'modalCreateFacility' || id === 'modalQuickEditFacility' || id === 'modalDeleteFacility') && !hasPermission('facility:configure')) {
    showToast("Керування об'єктами доступне лише Адміністратору", 'warning');
    return;
  }
  if ((id === 'modalCreateGenerator' || id === 'modalQuickEditGenerator' || id === 'modalDeleteGenerator' || id === 'modalWizard') && !hasPermission('generator:configure')) {
    showToast('Керування генераторами доступне лише Адміністратору', 'warning');
    return;
  }
  if ((id === 'modalNewStock' || id === 'modalEditStock' || id === 'modalCanisterPool') && !hasPermission('fuel:configure')) {
    showToast('Керування складами ГСМ та каністрами доступне лише Адміністратору', 'warning');
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
  if (modal) {
    modal.style.display = 'flex';
    document.body.classList.add('modal-open');
    if (typeof toggleMobileMoreSheet === 'function') {
      toggleMobileMoreSheet(false);
    }
  }
  if (id === 'modalReceipt') setupReceiptModal();
  if (id === 'modalTransfer') setupTransferModal();
  if (id === 'modalNewStock') setupNewStockModal();
  if (id === 'modalAdjustment') openAdjustmentModal();
  if (id === 'modalExportAudit') openAuditExportModal();
  if (typeof window.updateOperationalSafetyBanners === 'function') {
    window.updateOperationalSafetyBanners();
  }
};

window.closeModal = function (id) {
  const modal = document.getElementById(id);
  if (modal) modal.style.display = 'none';
  const anyOpen = Array.from(document.querySelectorAll('.modal-overlay')).some(m => m.style.display === 'flex' || m.style.display === 'block');
  if (!anyOpen) {
    document.body.classList.remove('modal-open');
  }
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

