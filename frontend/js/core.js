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
  const protocol = window.location.protocol;
  const isDirectIp = /^(\d{1,3}\.){3}\d{1,3}$/.test(currentHost);
  const isNativeApp = !!(window.Capacitor || protocol === 'capacitor:' || protocol === 'file:');

  // Allow native mobile app, local host, and direct IP connections without rogue warning
  if (isNativeApp || isDirectIp || currentHost === 'localhost' || currentHost === '127.0.0.1') {
    return;
  }

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

// ==========================================
// 🌐 Dynamic API Base URL & Native Android Routing
// ==========================================
window.getDefaultNativeServerUrl = function() {
  const metaDomain = document.querySelector('meta[name="app-primary-domain"]')?.getAttribute('content');
  const primaryDomain = (metaDomain || window.__APP_PRIMARY_DOMAIN__ || 'sdgen.pp.ua').toLowerCase().trim();
  return `https://${primaryDomain}`;
};

// One-time cleanup if a previous build stored an unreachable raw IP default
(function migrateLegacyDefaultHost() {
  try {
    const saved = localStorage.getItem('sd_server_host');
    if (saved && /^https?:\/\/91\.219\.63\.40(:8000)?$/i.test(saved.trim())) {
      localStorage.removeItem('sd_server_host');
    }
  } catch (_) {}
})();

window.getApiBaseUrl = function() {
  const customHost = localStorage.getItem('sd_server_host');
  if (customHost && customHost.trim()) {
    return customHost.trim().replace(/\/+$/, '');
  }
  // When running inside Capacitor / native Android APK or file:// protocol
  if (window.Capacitor || window.location.protocol === 'capacitor:' || window.location.protocol === 'file:') {
    return window.getDefaultNativeServerUrl();
  }
  return '';
};

// Global transparent request routing for mobile APK & remote endpoints
(function setupApiRouting() {
  const originalFetch = window.fetch;
  window.fetch = function(input, init) {
    let url = typeof input === 'string' ? input : (input instanceof Request ? input.url : String(input));
    const baseUrl = typeof window.getApiBaseUrl === 'function' ? window.getApiBaseUrl() : '';
    if (baseUrl && typeof url === 'string') {
      if (url.startsWith('/api/') || url === '/health' || url.startsWith('/health/') || url.startsWith('/static/') || url.startsWith('/uploads/')) {
        url = baseUrl + url;
        if (input instanceof Request) {
          input = new Request(url, init || input);
        } else {
          input = url;
        }
      }
    }
    return originalFetch.call(this, input, init);
  };
})();

// Helper functions for Server Connection Settings
window.openServerSettingsModal = async function() {
  if (window.ViewLoader?.ensureModal) {
    await window.ViewLoader.ensureModal('modalServerSettings');
  }
  const modal = document.getElementById('modalServerSettings');
  if (!modal) return;
  const isNative = !!(window.Capacitor || window.location.protocol === 'capacitor:' || window.location.protocol === 'file:');
  const currentHost = localStorage.getItem('sd_server_host') ||
    (isNative ? window.getDefaultNativeServerUrl() : window.location.origin);
  const input = document.getElementById('inputServerHost');
  if (input) input.value = currentHost;
  const statusEl = document.getElementById('serverConnectionStatus');
  if (statusEl) {
    statusEl.textContent = '';
    statusEl.className = 'server-status-box';
    statusEl.style.display = 'none';
  }
  modal.style.display = 'flex';
  document.body.classList.add('modal-open');
  if (isNative) {
    if (window.ViewLoader?.ensureScript && typeof window.refreshOtaVersionBadge !== 'function') {
      await window.ViewLoader.ensureScript('ota-updater.js').catch(() => {});
    }
    if (typeof window.refreshOtaVersionBadge === 'function') {
      window.refreshOtaVersionBadge().catch(() => {});
    }
  }
};

window.saveServerSettings = async function() {
  const input = document.getElementById('inputServerHost');
  const statusEl = document.getElementById('serverConnectionStatus');
  if (!input) return;
  let val = input.value.trim().replace(/\/+$/, '');
  if (!val) {
    localStorage.removeItem('sd_server_host');
    window.OfflineQueue?.syncNativeSession?.().catch(() => {});
    if (typeof showNotification === 'function') {
      showNotification('Налаштування сервера скинуто', 'info');
    }
    closeModal('modalServerSettings');
    updateServerHostLabel();
    return;
  }
  if (!val.startsWith('http://') && !val.startsWith('https://')) {
    val = 'https://' + val;
  }
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.textContent = '⏳ Перевірка з\'єднання з сервером...';
    statusEl.className = 'server-status-box status-pending';
  }
  try {
    const res = await fetch(`${val}/api/health`, { method: 'GET' });
    if (res.ok) {
      localStorage.setItem('sd_server_host', val);
      window.OfflineQueue?.syncNativeSession?.().catch(() => {});
      if (statusEl) {
        statusEl.textContent = '✅ З\'єднання успішне! Сервер активний.';
        statusEl.className = 'server-status-box status-success';
      }
      updateServerHostLabel();
      setTimeout(() => {
        closeModal('modalServerSettings');
        if (typeof showNotification === 'function') {
          showNotification(`Сервер оновлено: ${val}`, 'success');
        }
      }, 800);
      return;
    }
  } catch (err) {
    console.warn('Direct health check ping failed:', err);
  }
  if (statusEl) {
    statusEl.textContent = '❌ Сервер не відповів на /api/health — перевірте адресу або мережу. Зміни не збережено.';
    statusEl.className = 'server-status-box status-error';
  }
};

window.resetServerSettings = function() {
  localStorage.removeItem('sd_server_host');
  const input = document.getElementById('inputServerHost');
  const isNative = !!(window.Capacitor || window.location.protocol === 'capacitor:' || window.location.protocol === 'file:');
  if (input) {
    input.value = isNative ? window.getDefaultNativeServerUrl() : window.location.origin;
  }
  const statusEl = document.getElementById('serverConnectionStatus');
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.textContent = '🔄 Скинуто до стандартного сервера';
    statusEl.className = 'server-status-box status-info';
  }
  updateServerHostLabel();
};

window.isNativeClientApp = function() {
  return !!(window.Capacitor || window.location.protocol === 'capacitor:' || window.location.protocol === 'file:');
};

window.updateServerHostLabel = function() {
  const isNative = window.isNativeClientApp();
  const loginWrap = document.getElementById('loginServerSettingsWrap');
  if (loginWrap) {
    loginWrap.style.display = isNative ? 'block' : 'none';
  }
  const accountBtn = document.getElementById('accountServerSettingsBtn');
  if (accountBtn) {
    accountBtn.style.display = isNative ? 'flex' : 'none';
  }
  const lbl = document.getElementById('authServerLabel');
  if (lbl) {
    const base = window.getApiBaseUrl ? window.getApiBaseUrl() : '';
    lbl.textContent = base ? `Сервер: ${base.replace(/^https?:\/\//, '')}` : 'Сервер: цей хост';
  }
};

document.addEventListener('DOMContentLoaded', () => {
  window.updateServerHostLabel();
});

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
  const canAccessAdmin = isAdmin()
    || hasPermission('facility:configure')
    || hasPermission('generator:configure')
    || hasPermission('fuel:configure')
    || hasPermission('users:manage')
    || hasPermission('settings:manage');

  const canAccessNetwork = isAdmin() || viewer || (Array.isArray(window._cachedFacilitiesList) && window._cachedFacilitiesList.length > 1);
  const tabRules = {
    'tab-dashboard': true,
    'tab-network': canAccessNetwork,
    'tab-fuel': !viewer,
    'tab-maintenance': !viewer,
    'tab-faults': !viewer,
    'tab-runs': !viewer,
    'tab-audit': isAdmin(),
    'tab-reports': isAdmin(),
    'tab-measurement': superadmin,
    'tab-admin': canAccessAdmin
  };

  const netNavBtn = document.getElementById('navTabNetwork');
  if (netNavBtn) {
    netNavBtn.style.display = canAccessNetwork ? '' : 'none';
  }

  const measNavBtn = document.getElementById('navTabMeasurement');
  if (measNavBtn) {
    measNavBtn.style.display = superadmin ? '' : 'none';
  }

  const adminNavBtn = document.getElementById('navTabAdmin');
  if (adminNavBtn) {
    adminNavBtn.style.display = canAccessAdmin ? '' : 'none';
  }

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

  // Filter Admin Subtabs by RBAC permissions
  const subtabRules = {
    'facilities': isAdmin() || hasPermission('facility:configure') || hasPermission('generator:configure'),
    'fuel-admin': isAdmin() || hasPermission('fuel:configure'),
    'notifications': isAdmin() || hasPermission('settings:manage'),
    'system': isAdmin() || hasPermission('settings:manage'),
    'users': isAdmin() || hasPermission('users:manage') || superadmin,
    'backups': superadmin,
    'server': superadmin,
  };
  document.querySelectorAll('#adminSubtabsBar .admin-subtab-btn').forEach((btn) => {
    const key = btn.getAttribute('data-subtab');
    const allowed = subtabRules[key] ?? isAdmin();
    btn.style.display = allowed ? 'inline-flex' : 'none';
  });
  const activeSubBtn = document.querySelector('#adminSubtabsBar .admin-subtab-btn.active');
  if (activeSubBtn && activeSubBtn.style.display === 'none') {
    const firstAllowed = Array.from(document.querySelectorAll('#adminSubtabsBar .admin-subtab-btn'))
      .find((b) => b.style.display !== 'none');
    if (firstAllowed && typeof window.switchAdminSubtab === 'function') {
      window.switchAdminSubtab(firstAllowed.getAttribute('data-subtab'));
    }
  }

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
  setBtnState('btnFuelNewStock', canConfigFuel, 'Створення складу ПММ доступне лише Адміністратору 🔒', '📦 + Новий склад 🔒');
  setBtnState('btnFuelNewCanisterPool', canConfigFuel, 'Налаштування пулів каністр доступне лише Адміністратору 🔒', '🛢️ + Пул каністр 🔒');
  setBtnState('btnFuelReceipt', hasPermission('fuel:receipt'), 'Оприбуткування палива недоступне для вашої ролі 🔒', '📥 + Прийняти паливо 🔒');
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

  // Admin-only settings cards placed inside domain subtabs
  const canManageSettings = isAdmin() || hasPermission('settings:manage');
  ['spoilerDefaultChain', 'fuelTariffsAdminCard', 'emailReportsAdminCard', 'spoilerSmtpGateways'].forEach((cardId) => {
    const el = document.getElementById(cardId);
    if (el) el.style.display = canManageSettings ? '' : 'none';
  });

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

// API Helper (with IndexedDB Read Cache & Offline Mutation Queue)
async function api(endpoint, options = {}) {
  const { offlineMeta, suppressToast, timeoutMs, headers: optHeaders, ...fetchOpts } = options;
  const headers = { 'Content-Type': 'application/json', ...(optHeaders || {}) };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const method = (fetchOpts.method || 'GET').toUpperCase();
  let parsedBody = null;
  let idempotencyKey = null;

  if (method !== 'GET' && offlineMeta && typeof window.OfflineQueue === 'object') {
    try {
      parsedBody = typeof fetchOpts.body === 'string'
        ? JSON.parse(fetchOpts.body)
        : (fetchOpts.body && typeof fetchOpts.body === 'object' ? { ...fetchOpts.body } : {});
    } catch (_) {
      parsedBody = {};
    }
    idempotencyKey = parsedBody.idempotency_key || headers['Idempotency-Key'] || window.OfflineQueue.createIdempotencyKey();
    parsedBody.idempotency_key = idempotencyKey;
    if (!parsedBody.event_timestamp) {
      parsedBody.event_timestamp = new Date().toISOString();
    }
    headers['Idempotency-Key'] = idempotencyKey;
    fetchOpts.body = JSON.stringify(parsedBody);

    if (!navigator.onLine) {
      const qItem = await window.OfflineQueue.enqueueMutation(endpoint, method, parsedBody, offlineMeta, idempotencyKey);
      return { _queuedOffline: true, queueItem: qItem };
    }
  }

  const effTimeoutMs = typeof timeoutMs === 'number' ? timeoutMs : 15000;
  let abortCtrl = null;
  let timeoutId = null;
  if (effTimeoutMs > 0 && !fetchOpts.signal && typeof AbortController === 'function') {
    abortCtrl = new AbortController();
    fetchOpts.signal = abortCtrl.signal;
    timeoutId = setTimeout(() => {
      try { abortCtrl.abort(); } catch (_) {}
    }, effTimeoutMs);
  }

  try {
    const res = await fetch(`/api/v1${endpoint}`, { ...fetchOpts, headers });
    if (timeoutId) { clearTimeout(timeoutId); timeoutId = null; }
    if (res.status === 408 || res.status === 502 || res.status === 503 || res.status === 504) {
      const gatewayErr = new Error(`Сервер тимчасово недоступний (${res.status})`);
      gatewayErr.httpStatus = res.status;
      gatewayErr.isOffline = true;
      throw gatewayErr;
    }

    const data = await res.json().catch(() => null);

    if (res.status === 401) {
      if (endpoint !== '/auth/login') {
        token = null;
        if (typeof currentUser !== 'undefined') currentUser = null;
        localStorage.removeItem('sd_token');
        sessionStorage.removeItem('sd_token');
        window.invalidateFacilitiesCache?.();
        window.OfflineQueue?.clearCacheOnly?.().catch(() => {});
        showAuthScreen();
        const authErr = new Error('Сесія закінчилась. Увійдіть знову (офлайн-чергу збережено)');
        authErr.isAuthError = true;
        throw authErr;
      } else {
        const msg = extractErrorMessage(data, 'Невірний логін або пароль');
        const loginErr = new Error(msg);
        loginErr.isAuthError = true;
        throw loginErr;
      }
    }

    if (!res.ok) {
      const msg = extractErrorMessage(data, `Помилка сервера (${res.status})`);
      throw new Error(msg);
    }

    if (typeof window.OfflineQueue === 'object') {
      window.OfflineQueue.setOfflineMode(false);
      if (method === 'GET' && window.OfflineQueue.shouldCacheEndpoint(endpoint)) {
        window.OfflineQueue.cachePut(endpoint, data);
      }
    }
    return data;
  } catch (err) {
    if (timeoutId) { clearTimeout(timeoutId); timeoutId = null; }
    if (err && err.name === 'AbortError') {
      const timeoutErr = new Error('Час очікування відповіді сервера вичерпано');
      timeoutErr.isOffline = true;
      timeoutErr.isTimeout = true;
      err = timeoutErr;
    }
    const oq = typeof window.OfflineQueue === 'object' ? window.OfflineQueue : null;
    if (!err.isAuthError && oq && oq.isNetworkFailure(err, err?.httpStatus)) {
      err.isOffline = true;
      if (method === 'GET' && oq.shouldCacheEndpoint(endpoint)) {
        const cached = await oq.cacheGet(endpoint);
        if (cached && cached.data !== undefined && cached.data !== null) {
          oq.setOfflineMode(true, cached.updated_at);
          return cached.data;
        }
      }
      if (method !== 'GET' && offlineMeta && parsedBody) {
        const qItem = await oq.enqueueMutation(endpoint, method, parsedBody, offlineMeta, idempotencyKey);
        return { _queuedOffline: true, queueItem: qItem };
      }
      oq.setOfflineMode(true);
    }

    if (!suppressToast) {
      showToast(err.message, 'error');
    }
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

// Modal Helpers & Lazy View Integration
window._openModalStack = window._openModalStack || [];

window.getTopOpenModalId = function () {
  const stack = Array.isArray(window._openModalStack) ? window._openModalStack : [];
  const candidates = [];
  const overlays = document.querySelectorAll('.modal-overlay');
  overlays.forEach((el, domIdx) => {
    if (!el || !el.id || el.id === 'authOverlay') return;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return;
    if (el.id === 'modalAppUpdate') {
      const closeBtn = document.getElementById('otaUpdateCloseBtn');
      if (closeBtn && closeBtn.style.display === 'none') return;
    }
    const zRaw = parseInt(style.zIndex, 10);
    const zIndex = Number.isFinite(zRaw) ? zRaw : 1000;
    const stackIdx = stack.indexOf(el.id);
    candidates.push({ id: el.id, zIndex, stackIdx, domIdx });
  });
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => {
    if (b.zIndex !== a.zIndex) return b.zIndex - a.zIndex;
    if (b.stackIdx !== a.stackIdx) return b.stackIdx - a.stackIdx;
    return b.domIdx - a.domIdx;
  });
  return candidates[0].id;
};

window.openModal = async function (id, options = {}) {
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
    showToast('Керування складами ПММ та каністрами доступне лише Адміністратору', 'warning');
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

  if (window.ViewLoader?.ensureModal) {
    await window.ViewLoader.ensureModal(id);
  }

  const modal = document.getElementById(id);
  if (id === 'modalMeasurementCancel' && !isSuperAdmin()) {
    showToast('Аварійне скасування доступне лише Суперадміністратору 🔒', 'warning');
    return;
  }
  if (id === 'modalReceipt' && typeof setupReceiptModal === 'function') await setupReceiptModal();
  if (id === 'modalTransfer' && typeof setupTransferModal === 'function') await setupTransferModal();
  if (id === 'modalNewStock' && typeof setupNewStockModal === 'function') await setupNewStockModal();
  if (id === 'modalFault') {
    const faultForm = document.getElementById('faultForm');
    if (faultForm) faultForm.reset();
  }
  if (modal) {
    modal.style.display = 'flex';
    window._openModalStack = (window._openModalStack || []).filter((mId) => mId !== id);
    window._openModalStack.push(id);
    document.body.classList.add('modal-open');
    if (typeof toggleNavDrawer === 'function') toggleNavDrawer(false);
    if (typeof closeAccountMenu === 'function') closeAccountMenu();
  }
  if (!options?.skipPostOpen) {
    if (id === 'modalAdjustment' && typeof setupAdjustmentModal === 'function') setupAdjustmentModal();
    if (id === 'modalExportAudit' && typeof setAuditExportPeriod === 'function') setAuditExportPeriod('month');
  }
  if (id === 'modalOfflineQueue' && typeof window.OfflineQueue === 'object') window.OfflineQueue.renderQueueModal();
  if (typeof window.updateOperationalSafetyBanners === 'function') {
    window.updateOperationalSafetyBanners();
  }
};

// Shared Multipart Upload Helper (supports Avatar uploads without JSON Content-Type)
window.apiUpload = async function (endpoint, formData, method = 'POST') {
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`/api/v1${endpoint}`, { method, body: formData, headers });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = extractErrorMessage(data, `Помилка завантаження файлу (${res.status})`);
    showToast(msg, 'error');
    throw new Error(msg);
  }
  return data;
};

// Shared Deduplicated Facilities Cache
let _facilitiesCachePromise = null;
window.getFacilitiesCached = async function (forceRefresh = false) {
  if (!forceRefresh && Array.isArray(window._cachedFacilitiesList) && window._cachedFacilitiesList.length > 0) {
    return window._cachedFacilitiesList;
  }
  if (!forceRefresh && _facilitiesCachePromise) return _facilitiesCachePromise;
  _facilitiesCachePromise = api('/facilities')
    .then((list) => {
      window._cachedFacilitiesList = Array.isArray(list) ? list : [];
      return window._cachedFacilitiesList;
    })
    .finally(() => {
      _facilitiesCachePromise = null;
    });
  return _facilitiesCachePromise;
};

window.invalidateFacilitiesCache = function () {
  window._cachedFacilitiesList = null;
  _facilitiesCachePromise = null;
};

// Live Server Status in Footer (Deduplicated & Throttled)
let _serverStatusInFlight = null;
let _lastServerStatusAt = 0;
window.refreshServerStatus = async function (force = false) {
  if (!force && _serverStatusInFlight) return _serverStatusInFlight;
  if (!force && Date.now() - _lastServerStatusAt < 8000 && window.systemSettingsCache) return;

  _serverStatusInFlight = (async () => {
    try {
      const headers = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const res = await fetch('/api/v1/system/status', { headers });
      if (!res.ok) return;
      const data = await res.json();
      _lastServerStatusAt = Date.now();

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

      window.systemSettingsCache = window.systemSettingsCache || {};
      if (data.default_facility_id !== undefined) window.systemSettingsCache.default_facility_id = data.default_facility_id;
      if (data.default_generator_id !== undefined) window.systemSettingsCache.default_generator_id = data.default_generator_id;
      if (data.default_fuel_stock_id !== undefined) window.systemSettingsCache.default_fuel_stock_id = data.default_fuel_stock_id;
    } catch (_) {}
  })().finally(() => {
    _serverStatusInFlight = null;
  });

  return _serverStatusInFlight;
};

// Deterministic 2-Letter Monogram & Avatar Renderer
const AVATAR_GRADIENTS = [
  'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)',
  'linear-gradient(135deg, #059669 0%, #0d9488 100%)',
  'linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%)',
  'linear-gradient(135deg, #db2777 0%, #e11d48 100%)',
  'linear-gradient(135deg, #d97706 0%, #ea580c 100%)',
  'linear-gradient(135deg, #0891b2 0%, #0284c7 100%)',
];

window.getUserInitials = function (fullName, login) {
  const cleanName = (fullName || '').trim().replace(/\s+/g, ' ');
  if (cleanName) {
    const parts = cleanName.split(' ').filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    if (parts[0].length >= 2) {
      return parts[0].slice(0, 2).toUpperCase();
    }
    return parts[0][0].toUpperCase();
  }
  const cleanLogin = (login || 'SD').trim();
  return cleanLogin.slice(0, 2).toUpperCase() || 'SD';
};

window.getAvatarGradient = function (seedStr) {
  const s = String(seedStr || 'user');
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i);
    hash |= 0;
  }
  return AVATAR_GRADIENTS[Math.abs(hash) % AVATAR_GRADIENTS.length];
};

window.renderAvatarElement = function (imgEl, initialsEl, userObj) {
  if (!initialsEl && !imgEl) return;
  const fullName = userObj?.full_name || '';
  const login = userObj?.login || 'SD';
  const initials = window.getUserInitials(fullName, login);
  const grad = window.getAvatarGradient(login || fullName);

  if (initialsEl) {
    initialsEl.textContent = initials;
    initialsEl.style.background = grad;
  }
  if (imgEl) {
    const url = userObj?.avatar_url;
    if (url) {
      imgEl.onload = () => {
        imgEl.style.display = 'block';
        if (initialsEl) initialsEl.style.display = 'none';
      };
      imgEl.onerror = () => {
        imgEl.style.display = 'none';
        if (initialsEl) initialsEl.style.display = 'flex';
      };
      imgEl.src = url;
    } else {
      imgEl.removeAttribute('src');
      imgEl.style.display = 'none';
      if (initialsEl) initialsEl.style.display = 'flex';
    }
  }
};

window.closeModal = function (id) {
  const modal = document.getElementById(id);
  if (modal) modal.style.display = 'none';
  if (Array.isArray(window._openModalStack)) {
    window._openModalStack = window._openModalStack.filter((mId) => mId !== id);
  }
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

function _parseFilenameFromDisposition(disposition) {
  if (!disposition || typeof disposition !== 'string') return '';
  const utfMatch = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition);
  if (utfMatch && utfMatch[1]) {
    try {
      return decodeURIComponent(utfMatch[1].trim().replace(/^["']|["']$/g, ''));
    } catch (_) {}
  }
  const asciiMatch = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition);
  return asciiMatch && asciiMatch[1] ? asciiMatch[1].trim() : '';
}

function _blobToBase64Payload(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      const commaIdx = result.indexOf(',');
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
    };
    reader.onerror = () => reject(new Error('Не вдалося прочитати завантажений файл'));
    reader.readAsDataURL(blob);
  });
}

window.saveDownloadedBlob = async function (blob, filename, mimeType = '', openAfterSave = true) {
  const safeName = (filename && String(filename).trim()) || 'sdgen_download.bin';
  const filePlugin = (
    window.Capacitor &&
    typeof window.Capacitor.isNativePlatform === 'function' &&
    window.Capacitor.isNativePlatform() &&
    window.Capacitor.Plugins &&
    window.Capacitor.Plugins.FileDownload
  ) ? window.Capacitor.Plugins.FileDownload : null;

  if (filePlugin) {
    const base64Data = await _blobToBase64Payload(blob);
    const nativeRes = await filePlugin.saveAndOpen({
      fileName: safeName,
      mimeType: mimeType || blob.type || '',
      base64Data,
      openAfterSave: openAfterSave !== false,
    });
    return { native: true, ...nativeRes };
  }

  const blobUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = safeName;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => {
    try { window.URL.revokeObjectURL(blobUrl); } catch (_) {}
  }, 1500);
  return { native: false, fileName: safeName };
};

window.downloadAuthorizedFile = async function ({
  url,
  fallbackFilename,
  mimeType = '',
  defaultErrorMessage = 'Помилка завантаження файлу',
  openAfterSave = true,
} = {}) {
  const headers = {};
  if (typeof token !== 'undefined' && token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(url, { headers, credentials: 'same-origin' });
  if (!res.ok) {
    let errMsg = `${defaultErrorMessage} (${res.status})`;
    try {
      const errJson = await res.json();
      errMsg = extractErrorMessage(errJson, errMsg);
    } catch (_) {}
    throw new Error(errMsg);
  }

  const dispositionName = _parseFilenameFromDisposition(res.headers.get('Content-Disposition'));
  const finalFilename = dispositionName || fallbackFilename || 'sdgen_download.bin';

  const blob = await res.blob();
  if (!blob || blob.size <= 0) {
    throw new Error('Сервер повернув порожній файл.');
  }
  return window.saveDownloadedBlob(blob, finalFilename, mimeType || blob.type || '', openAfterSave);
};

window.showDownloadResultToast = function (dl, webMessage, nativeLabel = 'Файл') {
  if (dl?.native) {
    if (dl.canceled) {
      showToast('Збереження файлу скасовано', 'info');
      return false;
    }
    if (dl.savedToDownloads) {
      showToast(`${nativeLabel} збережено у ${dl.displayPath || 'Download'}!`, 'success');
      return true;
    }
    const reason = dl.saveError ? `: ${dl.saveError}` : '';
    showToast(`Не вдалося зберегти файл у Завантаження${reason}`, 'error');
    return false;
  }
  showToast(webMessage, 'success');
  return true;
};

