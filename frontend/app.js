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

// Kyiv Live Clock
function startClock() {
  setInterval(() => {
    try {
      const now = new Date();
      const kyivTime = new Intl.DateTimeFormat('uk-UA', {
        timeZone: 'Europe/Kyiv',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      }).format(now);
      document.getElementById('clockKyiv').innerText = `${kyivTime} (Київ)`;
    } catch (_) {}
  }, 1000);
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
  return new Intl.DateTimeFormat('uk-UA', {
    timeZone: 'Europe/Kyiv',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(d);
}

function formatDateOnly(val) {
  const d = parseUTCDate(val);
  if (!d || isNaN(d.getTime())) return '-';
  return new Intl.DateTimeFormat('uk-UA', {
    timeZone: 'Europe/Kyiv',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  }).format(d);
}

function formatTime(val) {
  const d = parseUTCDate(val);
  if (!d || isNaN(d.getTime())) return '-';
  return new Intl.DateTimeFormat('uk-UA', {
    timeZone: 'Europe/Kyiv',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(d);
}

function formatDuration(totalSeconds) {
  if (totalSeconds == null || isNaN(totalSeconds) || totalSeconds < 0) return '00:00:00';
  const sec = Math.floor(totalSeconds);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
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
    const rolesUa = (currentUser.roles || []).map(r => ROLE_MAP_UA[r] || ROLE_MAP_UA[r.toLowerCase()] || r).join(', ') || 'користувач';
    document.getElementById('userGreeting').innerText = `${currentUser.full_name} (${rolesUa})`;
    hideAuthScreen();
    applyRolePermissionsUI();
    loadAllData();
  } catch (_) {
    token = null;
    localStorage.removeItem('sd_token');
    sessionStorage.removeItem('sd_token');
    showAuthScreen();
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
  try {
    let url = '/generator';
    const params = [];
    if (currentGeneratorId) params.push(`generator_id=${encodeURIComponent(currentGeneratorId)}`);
    if (currentFacilityId) params.push(`facility_id=${encodeURIComponent(currentFacilityId)}`);
    if (params.length) url += `?${params.join('&')}`;

    currentGenerator = await api(url);
    if (!currentGenerator) return;
    currentGeneratorId = currentGenerator.id;
    const sel = document.getElementById('generatorSelect');
    if (sel && sel.value != currentGeneratorId) {
      sel.value = currentGeneratorId;
    }

    document.getElementById('genName').innerText = currentGenerator.name;
    document.getElementById('genModel').innerText = `Модель: ${currentGenerator.model} | Серійний: ${currentGenerator.serial_number} | Потужність: ${currentGenerator.rated_power_kw} кВт`;
    document.getElementById('cardHours').innerText = currentGenerator.current_operating_hours.toFixed(1);
    document.getElementById('cardTank').innerText = currentGenerator.fuel_tank_level_l.toFixed(1);

    const pct = Math.min(100, Math.round((currentGenerator.fuel_tank_level_l / currentGenerator.tank_capacity_l) * 100));
    document.getElementById('tankProgress').style.width = `${pct}%`;

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
      document.getElementById('activeRunHours').innerText = activeRun.start_hours.toFixed(1);
      startRunStopwatch();
    } else {
      banner.style.display = 'none';
      stopRunStopwatch();
    }
    applyRolePermissionsUI();
  } catch (_) {}
}

let runTimerInterval = null;

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

  const modalEstFuel = document.getElementById('stopEstFuelDisplay');
  if (modalEstFuel && currentGenerator) {
    const estLiters = (elapsedSeconds / 3600.0) * (currentGenerator.nominal_consumption_l_per_h || 2.2);
    modalEstFuel.innerText = (estLiters < 0.1 && estLiters > 0 ? estLiters.toFixed(3) : estLiters.toFixed(2)) + ' л';
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

// Start / Stop Main Button Handler
document.getElementById('mainActionBtn').addEventListener('click', async () => {
  if (!currentGenerator) return;
  if (isViewerOnly() || !hasPermission('generator:start')) {
    showToast('Керування генератором недоступне для ролі Спостерігач', 'warning');
    return;
  }

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
    // Start Generator directly
    try {
      await api('/generator/start', {
        method: 'POST',
        body: JSON.stringify({ generator_id: currentGeneratorId, fuel_level_l: currentGenerator.fuel_tank_level_l })
      });
      showToast('Генератор успішно запущено!', 'success');
      loadAllData();
    } catch (_) {}
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
  const endHoursVal = document.getElementById('stopEndHours').value;
  const endHours = endHoursVal !== '' && !isNaN(parseFloat(endHoursVal)) ? parseFloat(endHoursVal) : null;
  const endFuelVal = document.getElementById('stopEndFuel').value;
  const endFuel = endFuelVal !== '' && !isNaN(parseFloat(endFuelVal)) ? parseFloat(endFuelVal) : null;
  const note = document.getElementById('stopNote').value;

  try {
    const res = await api('/generator/stop', {
      method: 'POST',
      body: JSON.stringify({ generator_id: currentGeneratorId, end_hours: endHours, end_fuel_level_l: endFuel, note: note })
    });
    closeModal('modalStopGen');
    stopRunStopwatch();
    const durText = res.duration_formatted || formatDuration(res.duration_seconds) || `${res.duration_hours} год`;
    const fuelText = res.calculated_consumption_l != null ? `${res.calculated_consumption_l} л` : '-';
    showToast(`Генератор зупинено! Відпрацьовано: ${durText}, розхід: ${fuelText}`, 'success');
    loadAllData();
  } catch (_) {}
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
    document.getElementById('cardStock').innerText = s.warehouse_balance_l.toFixed(1);
    document.getElementById('fuelStockBal').innerText = `${s.warehouse_balance_l.toFixed(1)} л`;
    document.getElementById('fuelTankBal').innerText = `${s.tank_balance_l.toFixed(1)} л`;
    document.getElementById('fuelTotalBought').innerText = `${s.total_received_l.toFixed(1)} л`;
    document.getElementById('fuelTotalSpent').innerText = `${s.total_spent_uah.toFixed(2)} грн`;
    document.getElementById('fuelAvgPrice').innerText = `${s.avg_price_per_liter.toFixed(2)} грн/л`;
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
          <td><b style="color:#38bdf8;">${s.current_balance_l.toFixed(1)} л</b></td>
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
          <td><b>${r.liters.toFixed(1)} л</b></td>
          <td>${r.cost_total.toFixed(2)}</td>
          <td>${r.price_per_liter.toFixed(2)}</td>
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
          <td><b style="color:#38bdf8;">+${t.liters.toFixed(1)} л</b></td>
          <td>${t.source_balance_before.toFixed(1)} → ${t.source_balance_after.toFixed(1)} л</td>
          <td>${t.tank_balance_before.toFixed(1)} → ${t.tank_balance_after.toFixed(1)} л</td>
          <td>${escapeHtml(t.comment || '-')}</td>
          <td>${escapeHtml(t.user_name || '-')}</td>
        </tr>
      `).join('') || '<tr><td colspan="8" style="text-align:center; color:var(--text-muted)">Заправок не зареєстровано</td></tr>';
    }
  } catch (_) {}
}

// Receipt Form Submit
document.getElementById('receiptForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const stockVal = document.getElementById('recStock').value;
  if (!stockVal) {
    showToast('Будь ласка, оберіть склад ГСМ або створіть його', 'error');
    return;
  }
  const rawCost = document.getElementById('recCostTotal').value.trim();
  const parsedCost = rawCost ? parseFloat(rawCost) : null;

  const body = {
    facility_id: parseInt(document.getElementById('recFacility').value),
    stock_id: parseInt(stockVal),
    liters: parseFloat(document.getElementById('recLiters').value),
    cost_total: parsedCost && parsedCost > 0 ? parsedCost : null,
    driver_name: document.getElementById('recDriver').value,
    receipt_number: document.getElementById('recNumber').value,
    fuel_type: document.getElementById('recFuelType').value,
    comment: document.getElementById('recComment').value
  };

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
  } catch (_) {}
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
    msg += `\n\nУвага: на складі є залишок ${balance.toFixed(1)} л. Його буде автоматично перенесено на основний склад об'єкта, щоб уникнути втрати даних обліку.`;
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
    document.getElementById('cardMaintRem').innerHTML = `${m.hours_remaining.toFixed(1)} <small style="font-size:0.9rem;">год</small>`;
    document.getElementById('cardMaintSub').innerText = `план: ${m.next_due_hours.toFixed(0)} год`;
    document.getElementById('maintInterval').innerText = `${m.interval_hours.toFixed(0)} год`;
    document.getElementById('maintLast').innerText = `${m.last_performed_hours.toFixed(1)} год`;
    document.getElementById('maintNext').innerText = `${m.next_due_hours.toFixed(1)} год`;
    document.getElementById('maintRemaining').innerText = `${m.hours_remaining.toFixed(1)} год`;

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
        <td><b>${r.operating_hours.toFixed(1)} год</b></td>
        <td>${escapeHtml(r.work_description)}</td>
        <td>${escapeHtml(r.consumables_used || '-')}</td>
        <td>${r.cost.toFixed(2)} грн</td>
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
          <td>${f.operating_hours.toFixed(1)} год</td>
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
      const durText = r.duration_formatted || (r.duration_seconds != null ? formatDuration(r.duration_seconds) : (r.duration_hours ? r.duration_hours.toFixed(2) + ' год' : '-'));
      const consText = r.calculated_consumption_l != null ? (r.calculated_consumption_l < 0.1 && r.calculated_consumption_l > 0 ? r.calculated_consumption_l.toFixed(3) : r.calculated_consumption_l.toFixed(2)) + ' л' : '-';
      return `
        <tr>
          <td>${formatDateTime(r.start_time)}</td>
          <td>${r.start_hours.toFixed(1)} год</td>
          <td>${r.end_hours != null ? r.end_hours.toFixed(1) + ' год' : '<i>працює...</i>'}</td>
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
      const durText = r.duration_formatted || (r.duration_seconds != null ? formatDuration(r.duration_seconds) : (r.duration_hours ? r.duration_hours.toFixed(2) + ' год' : '-'));
      const consText = r.calculated_consumption_l != null ? (r.calculated_consumption_l < 0.1 && r.calculated_consumption_l > 0 ? r.calculated_consumption_l.toFixed(3) : r.calculated_consumption_l.toFixed(2)) + ' л' : '-';
      return `
        <tr>
          <td>#${Number(r.id)}</td>
          <td>${formatDateTime(r.start_time)}</td>
          <td>${r.end_time ? formatDateTime(r.end_time) : '<i>в процесі...</i>'}</td>
          <td>${r.start_hours.toFixed(1)}</td>
          <td>${r.end_hours != null ? r.end_hours.toFixed(1) : '-'}</td>
          <td><b style="color: #38bdf8; font-family: monospace;">${escapeHtml(durText)}</b></td>
          <td>${escapeHtml(consText)}</td>
          <td>${escapeHtml(r.start_fuel_level_l ?? '-')} → ${escapeHtml(r.end_fuel_level_l ?? '-')} л</td>
          <td>${escapeHtml(r.user_name || '-')}</td>
          <td>${escapeHtml(r.note || '-')}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="10" style="text-align:center; color:var(--text-muted)">Записів не знайдено</td></tr>';
  } catch (_) {}
}

// 6. Audit & System Adjustments
const AUDIT_ACTION_MAP_UA = {
  'LOGIN': 'Вхід у систему',
  'LOGIN_FAIL': 'Невдала спроба входу',
  'LOGOUT': 'Вихід із системи',
  'GENERATOR_START': 'Запуск генератора',
  'GENERATOR_STOP': 'Зупинка генератора',
  'FUEL_RECEIPT': 'Оприбуткування палива',
  'FUEL_RECEIPT_ADDED': 'Оприбуткування палива',
  'FUEL_DISPENSE': 'Заправка генератора',
  'FUEL_TRANSFERRED': 'Заправка бака генератора',
  'MAINTENANCE_RECORD': 'Технічне обслуговування',
  'MAINTENANCE_RECORDED': 'Фіксація ТО',
  'FAULT_CREATE': 'Реєстрація несправності',
  'FAULT_REPORTED': 'Повідомлення про несправність',
  'FAULT_UPDATE': 'Оновлення несправності',
  'FAULT_RESOLVED': 'Усунення несправності',
  'ADJUSTMENT': 'Коригування даних',
  'ADJUSTMENT_APPLIED': 'Системне коригування лічильників',
  'USER_CREATE': 'Створення користувача',
  'USER_UPDATE': 'Оновлення користувача',
  'USER_TOGGLE_ACTIVE': 'Зміна активності користувача',
  'SETTINGS_UPDATE': 'Зміна налаштувань',
  'SYSTEM_SETTINGS_UPDATED': 'Оновлення налаштувань',
  'WIZARD_SETUP': 'Налаштування через майстер',
  'FACILITY_CREATE': 'Створення об\'єкту',
  'FACILITY_CREATED': 'Створення об\'єкту',
  'FACILITY_UPDATED': 'Оновлення об\'єкту',
  'FACILITY_DELETED': 'Видалення об\'єкту',
  'GENERATOR_CREATE': 'Створення генератора',
  'GENERATOR_UPDATED': 'Оновлення параметрів генератора',
  'GENERATOR_DELETE': 'Видалення генератора',
  'SYSTEM_FACTORY_RESET': 'Скидання до заводських налаштувань',
  'SYSTEM_CLEAR_DATA': 'Очищення робочих даних',
  'SYSTEM_RESET': 'Очищення / скидання даних',
  'FACILITY_SETTINGS_UPDATE': 'Оновлення налаштувань об\'єкту',
  'GENERATOR_QUICK_CONFIG': 'Швидке налаштування генератора',
  'FUEL_PRICES_REFRESHED': 'Оновлення цін АЗК WOG',
  'SCHEDULE_RECALCULATED': 'Перерахунок графіка ТО',
  'FUEL_STOCK_UPDATED': 'Оновлення складу ГСМ',
  'FUEL_STOCK_DELETED': 'Видалення складу ГСМ',
  'GENERATOR_MANUAL_RUN_ADDED': 'Внесення роботи генератора вручну'
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

// ROLE_MAP_UA defined at the top

async function loadAuditData() {
  try {
    const logs = await api('/audit?limit=50');
    const tbody = document.querySelector('#auditTable tbody');
    tbody.innerHTML = logs.map((l) => {
      const actionUa = AUDIT_ACTION_MAP_UA[l.action] || l.action;
      const entityUa = AUDIT_ENTITY_MAP_UA[l.entity_type] || l.entity_type;
      return `
        <tr>
          <td>${formatDateTime(l.created_at)}</td>
          <td>${escapeHtml(l.user_name || 'Система')}</td>
          <td><b>${escapeHtml(actionUa)}</b></td>
          <td>${escapeHtml(entityUa)} #${escapeHtml(l.entity_id || '')}</td>
          <td style="font-family:monospace; font-size:0.75rem;">${escapeHtml(l.details_json || '-')}</td>
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
      const gens = await api(`/generators${q}`);
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
      targetSel.innerHTML = `<option value="1">Основний генератор (за замовчуванням)</option>`;
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
      const gens = await api(`/generators${q}`);
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

  document.getElementById('repStartDate').value = fmt(start);
  document.getElementById('repEndDate').value = fmt(end);
  loadReport();
};

async function loadReport() {
  const startInput = document.getElementById('repStartDate').value;
  const endInput = document.getElementById('repEndDate').value;

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
    const container = document.getElementById('reportContainer');
    container.innerHTML = `
      <div class="metric-card">
        <div class="metric-label">Відпрацьовано мотогодин</div>
        <div class="metric-value">${escapeHtml(r.total_operating_hours)} год</div>
        <div class="metric-sub">${escapeHtml(r.total_runs_count)} пусків</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Розрахунковий розхід палива</div>
        <div class="metric-value">${escapeHtml(r.total_calculated_consumption_l)} л</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Оприбутковано на склад</div>
        <div class="metric-value">${escapeHtml(r.total_fuel_received_l)} л</div>
        <div class="metric-sub">${escapeHtml(r.total_fuel_receipts_cost_uah)} грн (${escapeHtml(r.avg_fuel_price_per_liter)} грн/л)</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Заправлено в бак</div>
        <div class="metric-value">${escapeHtml(r.total_fuel_transferred_to_tank_l)} л</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Виконано ТО</div>
        <div class="metric-value">${escapeHtml(r.total_maintenance_count)}</div>
        <div class="metric-sub">Регламентних: ${escapeHtml(r.scheduled_maintenance_count)} | Проміжних: ${escapeHtml(r.intermediate_maintenance_count)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Витрати на ТО</div>
        <div class="metric-value">${escapeHtml(r.total_maintenance_cost_uah)} грн</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Несправності</div>
        <div class="metric-value">${escapeHtml(r.total_faults_count)}</div>
        <div class="metric-sub">Усунено: ${escapeHtml(r.resolved_faults_count)} | Відкрито: ${escapeHtml(r.open_faults_count)}</div>
      </div>
    `;
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

// Facility Create Form Submit
document.getElementById('facilityCreateForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('newFacilityName').value;
  const address = document.getElementById('newFacilityAddress').value;
  const description = document.getElementById('newFacilityDescription').value;

  try {
    const created = await api('/facilities', {
      method: 'POST',
      body: JSON.stringify({ name, address, description, timezone: 'Europe/Kyiv' })
    });
    closeModal('modalCreateFacility');
    showToast(`Об'єкт "${created.name}" успішно створено!`, 'success');
    await loadFacilitiesList();
    currentFacilityId = created.id;
    localStorage.setItem('sd_last_facility_id', currentFacilityId);
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
  const body = {
    facility_id: parseInt(document.getElementById('newGenFacilityId').value) || currentFacilityId || 1,
    name: document.getElementById('newGenName').value,
    model: document.getElementById('newGenModel').value,
    manufacturer: document.getElementById('newGenManufacturer').value,
    serial_number: document.getElementById('newGenSerial').value,
    rated_power_kw: parseFloat(document.getElementById('newGenPower').value),
    tank_capacity_l: parseFloat(document.getElementById('newGenTank').value),
    fuel_type: document.getElementById('newGenFuelType').value,
    nominal_consumption_l_per_h: parseFloat(document.getElementById('newGenConsumption').value),
    initial_operating_hours: parseFloat(document.getElementById('newGenInitialHours').value) || 0.0,
    initial_fuel_tank_level_l: parseFloat(document.getElementById('newGenInitialFuel').value) || 0.0,
    maintenance_interval_hours: parseFloat(document.getElementById('newGenMaintInterval').value) || 300.0,
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
    await loadGeneratorsList(currentFacilityId);
    currentGeneratorId = created.id;
    localStorage.setItem('sd_last_generator_id', currentGeneratorId);
    if (currentFacilityId) {
      localStorage.setItem(`sd_last_gen_facility_${currentFacilityId}`, currentGeneratorId);
    }
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
    const res = await fetch('/api/v1/system/status');
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
      return `<div style="background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(148, 163, 184, 0.22); border-left: 3px solid ${badgeColor}; border-radius: 0.5rem; padding: 0.55rem 0.7rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem;">
        <div>
          <div style="font-weight: 800; font-size: 0.95rem; color: #f8fafc; line-height: 1.1;">${escapeHtml(item.type)}</div>
          <div style="font-size: 0.72rem; color: ${isMustang ? '#fca5a5' : '#94a3b8'};">${escapeHtml(item.brand || 'Стандарт')}</div>
        </div>
        <div style="font-weight: 800; font-size: 1.05rem; color: #4ade80; white-space: nowrap;">${Number(item.price).toFixed(2)} <span style="font-size: 0.7rem; font-weight: 500; color: #94a3b8;">₴</span></div>
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
    apply_to_all_generators: document.getElementById('sysApplyAllGens').checked
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
  startClock();
  setupPwaInstall();
  checkAuth();
  refreshServerStatus();
  setInterval(refreshServerStatus, 30000);
  setTimeout(checkPushSubscriptionStatus, 1500);
});


