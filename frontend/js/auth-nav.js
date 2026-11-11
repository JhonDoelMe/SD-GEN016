function showAuthScreen() {
  document.body.classList.add('not-authenticated');
  document.getElementById('authOverlay').style.display = 'flex';
}

function hideAuthScreen() {
  document.body.classList.remove('not-authenticated');
  document.getElementById('authOverlay').style.display = 'none';
}

async function checkAuth() {
  if (!token) {
    token = localStorage.getItem('sd_token') || sessionStorage.getItem('sd_token');
  }

  try {
    currentUser = await api('/auth/me', { suppressToast: true });
  } catch (err) {
    if (err && err.isOffline && token && typeof window.OfflineQueue === 'object') {
      const cachedMe = await window.OfflineQueue.cacheGet('/auth/me');
      if (cachedMe && cachedMe.data) {
        currentUser = cachedMe.data;
        window.OfflineQueue.setOfflineMode(true, cachedMe.updated_at);
      }
    }
    if (!currentUser) {
      token = null;
      localStorage.removeItem('sd_token');
      sessionStorage.removeItem('sd_token');
      showAuthScreen();
      return;
    }
  }

  // User is authenticated
  hideAuthScreen();
  try {
    const rolesUa = (currentUser.roles || []).map(r => ROLE_MAP_UA[r] || ROLE_MAP_UA[r.toLowerCase()] || r).join(', ') || 'користувач';
    const greetEl = document.getElementById('userGreeting');
    if (greetEl) greetEl.innerText = `${currentUser.full_name} (${rolesUa})`;
    applyRolePermissionsUI();
    // Preload system status / default bindings cache before loading initial data
    if (!window.systemSettingsCache) {
      try { await refreshServerStatus(); } catch (_) {}
    }
    await loadAllData();
    if (typeof window.OfflineQueue === 'object') {
      window.OfflineQueue.updateOfflineUIStatus();
      if (navigator.onLine) {
        window.OfflineQueue.syncOfflineQueue({ silent: true }).catch(() => {});
      }
    }
    if (typeof window.syncPushSubscriptionWithServer === 'function') {
      window.syncPushSubscriptionWithServer(true);
    }
    if (typeof window.pollRecentNotifications === 'function') {
      window.pollRecentNotifications(true);
    }
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
    if (typeof window.OfflineQueue === 'object') {
      await window.OfflineQueue.cachePut('/auth/me', currentUser);
      window.OfflineQueue.updateOfflineUIStatus();
    }
    await loadAllData();
    if (typeof window.OfflineQueue === 'object' && navigator.onLine) {
      window.OfflineQueue.syncOfflineQueue({ silent: true }).catch(() => {});
    }
    if (typeof window.syncPushSubscriptionWithServer === 'function') {
      window.syncPushSubscriptionWithServer(true);
    }
    if (typeof window.pollRecentNotifications === 'function') {
      window.pollRecentNotifications(true);
    }
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
    await api('/auth/logout', { method: 'POST', suppressToast: true });
  } catch (_) {}
  if (typeof window.OfflineQueue === 'object') {
    await window.OfflineQueue.cachePut('/auth/me', null);
  }
  token = null;
  localStorage.removeItem('sd_token');
  sessionStorage.removeItem('sd_token');
  currentUser = null;
  showAuthScreen();
});

// Responsive Tab Navigation & Mobile Drawer
window.switchTab = function(paneId) {
  if (paneId === 'tab-measurement' && !isSuperAdmin()) {
    showToast('Розділ "Режим вимірювання" доступний лише Суперадміністратору 🔒', 'warning');
    return false;
  }
  const targetNav = document.querySelector(`.nav-item[data-tab="${paneId}"]`);
  if (targetNav && (targetNav.classList.contains('nav-item-disabled') || targetNav.getAttribute('aria-disabled') === 'true')) {
    const lockTitle = targetNav.getAttribute('title') || 'Розділ заблоковано для вашого рівня доступу 🔒';
    showToast(lockTitle, 'warning');
    return false;
  }

  // Update desktop top tabs
  document.querySelectorAll('.nav-item').forEach((t) => t.classList.remove('active'));
  if (targetNav) targetNav.classList.add('active');

  // Update mobile bottom nav items
  document.querySelectorAll('.mobile-nav-btn').forEach((b) => {
    if (b.getAttribute('data-tab') === paneId) {
      b.classList.add('active');
    } else {
      b.classList.remove('active');
    }
  });

  // If active tab is inside the "More" drawer, highlight "More" button
  const moreTabs = ['tab-faults', 'tab-notifications', 'tab-audit', 'tab-reports', 'tab-measurement', 'tab-admin'];
  const moreBtn = document.getElementById('btnMobileMore');
  if (moreBtn) {
    if (moreTabs.includes(paneId)) {
      moreBtn.classList.add('active');
    } else {
      moreBtn.classList.remove('active');
    }
  }

  // Update tab-pane visibility
  document.querySelectorAll('.tab-pane').forEach((p) => (p.style.display = 'none'));
  const pane = document.getElementById(paneId);
  if (pane) pane.style.display = 'block';

  // Close mobile more sheet if open
  if (typeof toggleMobileMoreSheet === 'function') {
    toggleMobileMoreSheet(false);
  }

  // Smooth scroll to top on tab change
  window.scrollTo({ top: 0, behavior: 'smooth' });

  // Refresh tab data
  if (paneId === 'tab-dashboard') loadAllData();
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
  if (paneId === 'tab-measurement' && typeof window.loadMeasurementTab === 'function') {
    window.loadMeasurementTab();
  }
  if (paneId === 'tab-admin') {
    loadUsersData();
    loadAdminSystemSettings();
    if (isSuperAdmin()) {
      loadBackupsList();
    }
  }
};

window.toggleMobileMoreSheet = function(forceState) {
  const sheet = document.getElementById('mobileMoreSheet');
  const backdrop = document.getElementById('mobileMoreBackdrop');
  if (!sheet || !backdrop) return;

  const isOpen = sheet.classList.contains('open');
  const next = forceState !== undefined ? forceState : !isOpen;

  if (next) {
    sheet.classList.add('open');
    backdrop.classList.add('open');
    document.body.style.overflow = 'hidden';
  } else {
    sheet.classList.remove('open');
    backdrop.classList.remove('open');
    document.body.style.overflow = '';
  }
};

document.querySelectorAll('.nav-item').forEach((tab) => {
  tab.addEventListener('click', (e) => {
    e.preventDefault();
    const paneId = tab.getAttribute('data-tab');
    switchTab(paneId);
  });
});

// Facilities & Generators Management
async function loadFacilitiesList() {
  try {
    const facilities = await api('/facilities');
    cachedReceiptFacilities = facilities || [];
    const sel = document.getElementById('facilitySelect');
    const modalSel = document.getElementById('newGenFacilityId');
    const userFacSel = document.getElementById('newUserFacility');
    const editUserFacSel = document.getElementById('editUserFacility');
    if (!sel) return;

    sel.innerHTML = facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
    if (modalSel) {
      modalSel.innerHTML = facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
    }
    if (userFacSel) {
      userFacSel.innerHTML = '<option value="">(Усі об\'єкти / Не обмежено)</option>' +
        facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
    }
    if (editUserFacSel) {
      editUserFacSel.innerHTML = '<option value="">(Усі об\'єкти / Не обмежено)</option>' +
        facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
    }

    if (facilities.length > 0) {
      if (!isAdmin() && currentUser && currentUser.facility_id) {
        currentFacilityId = currentUser.facility_id;
      } else {
        const sysDefaultFac = window.systemSettingsCache?.default_facility_id;
        const savedFacilityId = parseInt(localStorage.getItem('sd_last_facility_id') || '0', 10);
        if (savedFacilityId && facilities.some(f => f.id === savedFacilityId)) {
          currentFacilityId = savedFacilityId;
        } else if (sysDefaultFac && facilities.some(f => f.id === sysDefaultFac)) {
          currentFacilityId = sysDefaultFac;
        } else if (!currentFacilityId || !facilities.some(f => f.id === currentFacilityId)) {
          currentFacilityId = facilities[0].id;
        }
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
      
      const sysDefaultGen = window.systemSettingsCache?.default_generator_id;
      const savedGenForFac = parseInt(localStorage.getItem(`sd_last_gen_facility_${facilityId}`) || '0', 10);
      const savedGlobalGen = parseInt(localStorage.getItem('sd_last_generator_id') || '0', 10);
      const targetGenId = (savedGenForFac && generators.some(g => g.id === savedGenForFac))
        ? savedGenForFac
        : ((savedGlobalGen && generators.some(g => g.id === savedGlobalGen))
          ? savedGlobalGen
          : ((sysDefaultGen && generators.some(g => g.id === sysDefaultGen)) ? sysDefaultGen : null));

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

// ---------------------------------------------------------------------------
// Email System & Password Reset Handlers
// ---------------------------------------------------------------------------

window.openForgotPasswordModal = function () {
  const input = document.getElementById('forgotLoginOrEmail');
  if (input) input.value = '';
  const fb = document.getElementById('forgotPasswordFeedback');
  if (fb) {
    fb.className = 'feedback-box';
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
      fb.className = 'feedback-box success';
      fb.innerText = res.message || 'Якщо користувача знайдено, посилання надіслано на вашу пошту.';
    }
    showToast('Запит прийнято! Перевірте поштову скриньку', 'success');
  } catch (err) {
    if (fb) {
      fb.className = 'feedback-box error';
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
      fb.className = 'feedback-box error';
      fb.innerText = err.message || 'Помилка скидання пароля';
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '💾 Зберегти новий пароль';
    }
  }
});

