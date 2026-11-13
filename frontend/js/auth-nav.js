function showAuthScreen() {
  document.body.classList.add('not-authenticated');
  const overlay = document.getElementById('authOverlay');
  if (overlay) overlay.style.display = 'flex';
}

function hideAuthScreen() {
  document.body.classList.remove('not-authenticated');
  const overlay = document.getElementById('authOverlay');
  if (overlay) overlay.style.display = 'none';
}

function getRolesLabelUa(userObj) {
  const roles = userObj?.roles || [];
  const mapped = roles.map((r) => {
    const name = typeof r === 'string' ? r : r?.name;
    return ROLE_MAP_UA[name] || ROLE_MAP_UA[(name || '').toLowerCase()] || name;
  }).filter(Boolean);
  return mapped.join(', ') || 'користувач';
}

window.updateAccountHeaderUI = function () {
  if (!currentUser) return;
  const headerImg = document.getElementById('headerAvatarImg');
  const headerInit = document.getElementById('headerAvatarInitials');
  const dropImg = document.getElementById('dropdownAvatarImg');
  const dropInit = document.getElementById('dropdownAvatarInitials');
  const nameEl = document.getElementById('dropdownUserName');
  const loginEl = document.getElementById('dropdownUserLogin');
  const roleEl = document.getElementById('dropdownUserRole');
  const btnEl = document.getElementById('accountMenuBtn');

  if (typeof window.renderAvatarElement === 'function') {
    window.renderAvatarElement(headerImg, headerInit, currentUser);
    window.renderAvatarElement(dropImg, dropInit, currentUser);
  }
  const rolesUa = getRolesLabelUa(currentUser);
  if (nameEl) nameEl.innerText = currentUser.full_name || currentUser.login || 'Користувач';
  if (loginEl) loginEl.innerText = `@${currentUser.login || 'user'}${currentUser.email ? ' • ' + currentUser.email : ''}`;
  if (roleEl) roleEl.innerText = rolesUa;
  if (btnEl) btnEl.title = `${currentUser.full_name || currentUser.login} (${rolesUa})`;
};

window.closeAccountMenu = function () {
  const dd = document.getElementById('accountDropdown');
  const btn = document.getElementById('accountMenuBtn');
  if (dd) dd.style.display = 'none';
  if (btn) btn.setAttribute('aria-expanded', 'false');
};

window.toggleAccountMenu = function (e) {
  if (e) e.stopPropagation();
  const dd = document.getElementById('accountDropdown');
  const btn = document.getElementById('accountMenuBtn');
  if (!dd) return;
  const isVisible = dd.style.display === 'block';
  if (isVisible) {
    window.closeAccountMenu();
  } else {
    window.toggleNavDrawer(false);
    dd.style.display = 'block';
    if (btn) btn.setAttribute('aria-expanded', 'true');
  }
};

document.addEventListener('click', (e) => {
  const wrap = document.getElementById('accountMenuWrap');
  const dd = document.getElementById('accountDropdown');
  if (dd && dd.style.display === 'block' && wrap && !wrap.contains(e.target)) {
    window.closeAccountMenu();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    window.closeAccountMenu();
    window.toggleNavDrawer(false);
  }
});

// ---------------------------------------------------------------------------
// Account Profile, Avatar & Personal Push Modal
// ---------------------------------------------------------------------------

window.openAccountProfileModal = async function (focusSection = null) {
  window.closeAccountMenu();
  window.toggleNavDrawer(false);
  if (window.ViewLoader?.ensureModal) {
    await window.ViewLoader.ensureModal('modalAccountProfile');
  }
  if (currentUser) {
    window.syncProfileModalUI(currentUser);
  }
  const curPwd = document.getElementById('profileCurrentPassword');
  const newPwd = document.getElementById('profileNewPassword');
  const cfmPwd = document.getElementById('profileConfirmPassword');
  if (curPwd) curPwd.value = '';
  if (newPwd) newPwd.value = '';
  if (cfmPwd) cfmPwd.value = '';

  await window.openModal('modalAccountProfile');
  if (typeof checkPushSubscriptionStatus === 'function') {
    checkPushSubscriptionStatus();
  }
  if (focusSection === 'push') {
    document.getElementById('profilePushSection')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
};

window.syncProfileModalUI = function (userObj) {
  if (!userObj) return;
  const img = document.getElementById('profileAvatarPreviewImg');
  const init = document.getElementById('profileAvatarInitials');
  const delBtn = document.getElementById('btnDeleteMyAvatar');
  const nameSummary = document.getElementById('profileSummaryName');
  const metaSummary = document.getElementById('profileSummaryMeta');
  const fullNameIn = document.getElementById('profileFullName');
  const emailIn = document.getElementById('profileEmail');

  if (typeof window.renderAvatarElement === 'function') {
    window.renderAvatarElement(img, init, userObj);
  }
  if (delBtn) {
    delBtn.style.display = userObj.avatar_url ? 'inline-flex' : 'none';
  }
  if (nameSummary) nameSummary.innerText = userObj.full_name || userObj.login;
  if (metaSummary) metaSummary.innerText = `@${userObj.login} • ${getRolesLabelUa(userObj)}`;
  if (fullNameIn) fullNameIn.value = userObj.full_name || '';
  if (emailIn) emailIn.value = userObj.email || '';
};

window.uploadMyAvatar = async function (input) {
  const file = input?.files?.[0];
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    showToast('Розмір файлу перевищує 5 МБ', 'warning');
    input.value = '';
    return;
  }
  const fd = new FormData();
  fd.append('file', file);
  try {
    const updated = await apiUpload('/auth/me/avatar', fd, 'POST');
    currentUser = updated;
    if (typeof window.OfflineQueue === 'object') {
      window.OfflineQueue.cachePut('/auth/me', currentUser).catch(() => {});
    }
    window.updateAccountHeaderUI();
    window.syncProfileModalUI(currentUser);
    if (typeof loadUsersData === 'function' && document.getElementById('usersTable')) {
      loadUsersData();
    }
    showToast('Аватар успішно оновлено!', 'success');
  } catch (_) {
  } finally {
    input.value = '';
  }
};

window.deleteMyAvatar = async function () {
  try {
    const updated = await api('/auth/me/avatar', { method: 'DELETE' });
    currentUser = updated;
    if (typeof window.OfflineQueue === 'object') {
      window.OfflineQueue.cachePut('/auth/me', currentUser).catch(() => {});
    }
    window.updateAccountHeaderUI();
    window.syncProfileModalUI(currentUser);
    if (typeof loadUsersData === 'function' && document.getElementById('usersTable')) {
      loadUsersData();
    }
    showToast('Аватар видалено', 'info');
  } catch (_) {}
};

// ---------------------------------------------------------------------------
// Auth Lifecycle (Optimized Non-Blocking Parallel Boot)
// ---------------------------------------------------------------------------

async function checkAuth() {
  if (!token) {
    token = localStorage.getItem('sd_token') || sessionStorage.getItem('sd_token');
  }

  // Mount dashboard view HTML in parallel with auth check to save an entire RTT
  const dashMountPromise = window.ViewLoader?.ensureTab
    ? window.ViewLoader.ensureTab('tab-dashboard').catch(() => {})
    : Promise.resolve();

  try {
    const [meRes] = await Promise.all([
      api('/auth/me', { suppressToast: true }),
      dashMountPromise
    ]);
    currentUser = meRes;
  } catch (err) {
    await dashMountPromise;
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

  hideAuthScreen();
  try {
    window.updateAccountHeaderUI();
    applyRolePermissionsUI();

    // Load server status and facilities list in parallel instead of sequentially
    await Promise.allSettled([
      typeof refreshServerStatus === 'function' ? refreshServerStatus() : Promise.resolve(),
      loadFacilitiesList()
    ]);

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
    if (window.ViewLoader?.scheduleIdleWarmup) {
      window.ViewLoader.scheduleIdleWarmup();
    }
  } catch (dataErr) {
    console.error('Error loading initial dashboard data:', dataErr);
  }
}

document.getElementById('loginForm')?.addEventListener('submit', async (e) => {
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
    const dashMountPromise = window.ViewLoader?.ensureTab
      ? window.ViewLoader.ensureTab('tab-dashboard').catch(() => {})
      : Promise.resolve();

    const [res] = await Promise.all([
      api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ login: loginInput, password: passInput, remember_me: rememberMe })
      }),
      dashMountPromise
    ]);

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
    window.updateAccountHeaderUI();
    hideAuthScreen();
    applyRolePermissionsUI();
    showToast(`Вітаємо, ${currentUser.full_name}!`, 'success');
    if (typeof window.OfflineQueue === 'object') {
      await window.OfflineQueue.cachePut('/auth/me', currentUser);
      window.OfflineQueue.updateOfflineUIStatus();
    }
    await Promise.allSettled([
      typeof refreshServerStatus === 'function' ? refreshServerStatus() : Promise.resolve(),
      loadFacilitiesList(true)
    ]);
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
    if (window.ViewLoader?.scheduleIdleWarmup) {
      window.ViewLoader.scheduleIdleWarmup();
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

document.getElementById('logoutBtn')?.addEventListener('click', async () => {
  window.closeAccountMenu();
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
  window.invalidateFacilitiesCache?.();
  showAuthScreen();
});

// ---------------------------------------------------------------------------
// Slide-Over Navigation Drawer & Tab Routing
// ---------------------------------------------------------------------------

window.toggleNavDrawer = function (forceState) {
  const drawer = document.getElementById('navDrawer');
  const backdrop = document.getElementById('navDrawerBackdrop');
  if (!drawer || !backdrop) return;

  const isOpen = drawer.classList.contains('open');
  const next = forceState !== undefined ? forceState : !isOpen;

  if (next) {
    window.closeAccountMenu();
    drawer.classList.add('open');
    backdrop.classList.add('open');
    document.body.style.overflow = 'hidden';
  } else {
    drawer.classList.remove('open');
    backdrop.classList.remove('open');
    document.body.style.overflow = '';
  }
};
window.toggleMobileMoreSheet = window.toggleNavDrawer;

window.activeTabId = 'tab-dashboard';
window._tabSwitchSeq = 0;

window.switchTab = async function (paneId) {
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

  window.toggleNavDrawer(false);
  window.closeAccountMenu();

  const switchSeq = ++window._tabSwitchSeq;

  if (window.ViewLoader?.ensureTab) {
    try {
      await window.ViewLoader.ensureTab(paneId);
    } catch (err) {
      console.error(`Failed to load view for ${paneId}:`, err);
      if (typeof showToast === 'function') {
        showToast('Не вдалося завантажити розділ. Перевірте з\'єднання та спробуйте ще раз.', 'error');
      }
      return false;
    }
  }

  // Abort if user already initiated a newer tab switch while view was loading
  if (switchSeq !== window._tabSwitchSeq) return false;

  const pane = document.getElementById(paneId);
  if (!pane) {
    console.warn(`Tab pane #${paneId} was not found in DOM after loading.`);
    return false;
  }

  window.activeTabId = paneId;
  document.querySelectorAll('.nav-item').forEach((t) => t.classList.remove('active'));
  if (targetNav) targetNav.classList.add('active');

  const sectionLabel = document.getElementById('headerActiveSection');
  if (sectionLabel && targetNav) {
    const cleanText = (targetNav.getAttribute('data-orig-html') || targetNav.textContent || '')
      .replace(/<[^>]*>/g, '')
      .trim();
    sectionLabel.textContent = cleanText || '⚡ Головна';
  }

  document.querySelectorAll('.tab-pane').forEach((p) => {
    const isTarget = p.id === paneId;
    p.style.display = isTarget ? 'block' : 'none';
    p.classList.toggle('active', isTarget);
  });

  if (typeof applyRolePermissionsUI === 'function') {
    applyRolePermissionsUI();
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });

  if (paneId === 'tab-dashboard' && typeof loadAllData === 'function') await loadAllData();
  if (paneId === 'tab-fuel' && typeof loadFuelData === 'function') await loadFuelData();
  if (paneId === 'tab-maintenance' && typeof loadMaintenanceData === 'function') await loadMaintenanceData();
  if (paneId === 'tab-faults' && typeof loadFaultsData === 'function') await loadFaultsData();
  if (paneId === 'tab-runs' && typeof loadRunsData === 'function') await loadRunsData();
  if (paneId === 'tab-audit' && typeof loadAuditData === 'function') await loadAuditData();
  if (paneId === 'tab-reports' && typeof loadReport === 'function') await loadReport();
  if (paneId === 'tab-measurement' && typeof window.loadMeasurementTab === 'function') {
    await window.loadMeasurementTab();
  }
  if (paneId === 'tab-admin') {
    const savedSub = sessionStorage.getItem('sd_admin_subtab') || 'facilities';
    await window.switchAdminSubtab(savedSub);
  }
  return true;
};

window.switchAdminSubtab = async function (subtab) {
  const btns = Array.from(document.querySelectorAll('#adminSubtabsBar .admin-subtab-btn'));
  if (btns.length === 0) return;

  let targetBtn = btns.find((b) => b.getAttribute('data-subtab') === subtab && b.style.display !== 'none');
  if (!targetBtn) {
    targetBtn = btns.find((b) => b.style.display !== 'none') || btns[0];
    subtab = targetBtn?.getAttribute('data-subtab') || 'facilities';
  }

  sessionStorage.setItem('sd_admin_subtab', subtab);
  btns.forEach((b) => b.classList.toggle('active', b.getAttribute('data-subtab') === subtab));
  document.querySelectorAll('.admin-subpane').forEach((p) => {
    p.classList.toggle('active', p.id === `adminPane-${subtab}`);
  });

  if (subtab === 'facilities' && typeof window.renderAdminFacilitiesAndGenerators === 'function') {
    await window.renderAdminFacilitiesAndGenerators();
  } else if (subtab === 'fuel-admin' && typeof loadFuelData === 'function') {
    await loadFuelData();
  } else if (subtab === 'notifications') {
    if (typeof loadNotificationSettings === 'function') loadNotificationSettings();
    if (typeof loadNotificationLogs === 'function') loadNotificationLogs();
  } else if (subtab === 'system' && typeof loadAdminSystemSettings === 'function') {
    await loadAdminSystemSettings();
  } else if (subtab === 'users' && typeof loadUsersData === 'function') {
    await loadUsersData();
  } else if (subtab === 'backups' && isSuperAdmin() && typeof loadBackupsList === 'function') {
    await loadBackupsList();
  }
};

document.addEventListener('click', (e) => {
  const tab = e.target?.closest?.('.nav-item[data-tab]');
  if (!tab) return;
  e.preventDefault();
  const paneId = tab.getAttribute('data-tab');
  if (paneId) switchTab(paneId);
});

// ---------------------------------------------------------------------------
// Facilities & Generators Selectors (Moved from admin.js so Switcher works before lazy Admin loads)
// ---------------------------------------------------------------------------

window.populateCachedFacilitySelects = function () {
  const facilities = Array.isArray(window._cachedFacilitiesList) ? window._cachedFacilitiesList : [];
  if (facilities.length === 0) return;
  const optsHtml = facilities.map((f) => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
  const allOptsHtml = '<option value="">(Усі об\'єкти / Не обмежено)</option>' + optsHtml;

  const modalSel = document.getElementById('newGenFacilityId');
  if (modalSel) modalSel.innerHTML = optsHtml;
  const userFacSel = document.getElementById('newUserFacility');
  if (userFacSel) userFacSel.innerHTML = allOptsHtml;
  const editUserFacSel = document.getElementById('editUserFacility');
  if (editUserFacSel) editUserFacSel.innerHTML = allOptsHtml;
};

async function loadFacilitiesList(forceRefresh = false) {
  try {
    const facilities = typeof getFacilitiesCached === 'function'
      ? await getFacilitiesCached(forceRefresh)
      : await api('/facilities');

    window._cachedFacilitiesList = Array.isArray(facilities) ? facilities : [];
    if (typeof cachedReceiptFacilities !== 'undefined') {
      cachedReceiptFacilities = window._cachedFacilitiesList;
    }

    const sel = document.getElementById('facilitySelect');
    if (sel) {
      sel.innerHTML = window._cachedFacilitiesList
        .map((f) => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`)
        .join('');
    }
    window.populateCachedFacilitySelects();

    if (window._cachedFacilitiesList.length > 0) {
      if (!isAdmin() && currentUser && currentUser.facility_id) {
        currentFacilityId = currentUser.facility_id;
      } else {
        const sysDefaultFac = window.systemSettingsCache?.default_facility_id;
        const savedFacilityId = parseInt(localStorage.getItem('sd_last_facility_id') || '0', 10);
        if (savedFacilityId && window._cachedFacilitiesList.some((f) => f.id === savedFacilityId)) {
          currentFacilityId = savedFacilityId;
        } else if (sysDefaultFac && window._cachedFacilitiesList.some((f) => f.id === sysDefaultFac)) {
          currentFacilityId = sysDefaultFac;
        } else if (!currentFacilityId || !window._cachedFacilitiesList.some((f) => f.id === currentFacilityId)) {
          currentFacilityId = window._cachedFacilitiesList[0].id;
        }
      }
      if (sel) sel.value = currentFacilityId;
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
    window._cachedGeneratorsList = Array.isArray(generators) ? generators : [];
    const sel = document.getElementById('generatorSelect');
    if (!sel) return;

    if (window._cachedGeneratorsList.length === 0) {
      sel.innerHTML = '<option value="">(Немає генераторів)</option>';
      currentGenerator = null;
      currentGeneratorId = null;
    } else {
      sel.innerHTML = window._cachedGeneratorsList
        .map((g) => `<option value="${Number(g.id)}">${escapeHtml(g.name)} (${escapeHtml(g.model)})</option>`)
        .join('');

      const sysDefaultGen = window.systemSettingsCache?.default_generator_id;
      const savedGenForFac = parseInt(localStorage.getItem(`sd_last_gen_facility_${facilityId}`) || '0', 10);
      const savedGlobalGen = parseInt(localStorage.getItem('sd_last_generator_id') || '0', 10);
      const targetGenId = (savedGenForFac && window._cachedGeneratorsList.some((g) => g.id === savedGenForFac))
        ? savedGenForFac
        : ((savedGlobalGen && window._cachedGeneratorsList.some((g) => g.id === savedGlobalGen))
          ? savedGlobalGen
          : ((sysDefaultGen && window._cachedGeneratorsList.some((g) => g.id === sysDefaultGen)) ? sysDefaultGen : null));

      if (targetGenId) {
        currentGeneratorId = targetGenId;
      } else if (!currentGeneratorId || !window._cachedGeneratorsList.some((g) => g.id === currentGeneratorId)) {
        currentGeneratorId = window._cachedGeneratorsList[0].id;
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

document.getElementById('facilitySelect')?.addEventListener('change', async (e) => {
  const targetId = parseInt(e.target.value, 10);
  if (!isAdmin() && currentUser && currentUser.facility_id && targetId !== currentUser.facility_id) {
    showToast("Ви не можете вибрати інший об'єкт, ви закріплені за своїм об'єктом!", 'warning');
    e.target.value = currentUser.facility_id;
    return;
  }
  currentFacilityId = targetId;
  localStorage.setItem('sd_last_facility_id', currentFacilityId);
  currentGeneratorId = null;
  await loadGeneratorsList(currentFacilityId);
  await Promise.all([
    loadAllData(),
    (window.activeTabId === 'tab-admin' && typeof window.renderAdminFacilitiesAndGenerators === 'function')
      ? window.renderAdminFacilitiesAndGenerators(true)
      : Promise.resolve(),
    ((window.activeTabId === 'tab-fuel' || (window.activeTabId === 'tab-admin' && sessionStorage.getItem('sd_admin_subtab') === 'fuel-admin')) && typeof loadFuelData === 'function')
      ? loadFuelData()
      : Promise.resolve()
  ]);
});

document.getElementById('generatorSelect')?.addEventListener('change', async (e) => {
  currentGeneratorId = parseInt(e.target.value, 10);
  localStorage.setItem('sd_last_generator_id', currentGeneratorId);
  if (currentFacilityId) {
    localStorage.setItem(`sd_last_gen_facility_${currentFacilityId}`, currentGeneratorId);
  }
  await loadAllData();
});

// ---------------------------------------------------------------------------
// Delegated Forms: Account Profile, Change Password, Forgot/Reset Password
// ---------------------------------------------------------------------------

window.openForgotPasswordModal = async function () {
  await window.openModal('modalForgotPassword');
  const input = document.getElementById('forgotLoginOrEmail');
  if (input) input.value = '';
  const fb = document.getElementById('forgotPasswordFeedback');
  if (fb) {
    fb.className = 'feedback-box';
    fb.innerText = '';
  }
};

document.addEventListener('submit', async (e) => {
  const form = e.target;
  if (!form || !form.id) return;

  if (form.id === 'accountProfileForm') {
    e.preventDefault();
    const fullName = document.getElementById('profileFullName')?.value.trim();
    const emailRaw = document.getElementById('profileEmail')?.value.trim();
    const btn = document.getElementById('btnSaveProfile');
    if (!fullName) {
      showToast('ПІБ не може бути порожнім', 'warning');
      return;
    }
    if (btn) btn.disabled = true;
    try {
      const updated = await api('/auth/me', {
        method: 'PUT',
        body: JSON.stringify({ full_name: fullName, email: emailRaw || null })
      });
      currentUser = updated;
      if (typeof window.OfflineQueue === 'object') {
        window.OfflineQueue.cachePut('/auth/me', currentUser).catch(() => {});
      }
      window.updateAccountHeaderUI();
      window.syncProfileModalUI(currentUser);
      showToast('Дані профілю збережено!', 'success');
    } catch (_) {
    } finally {
      if (btn) btn.disabled = false;
    }
    return;
  }

  if (form.id === 'accountChangePasswordForm') {
    e.preventDefault();
    const curPwd = document.getElementById('profileCurrentPassword')?.value || '';
    const newPwd = document.getElementById('profileNewPassword')?.value || '';
    const cfmPwd = document.getElementById('profileConfirmPassword')?.value || '';
    const btn = document.getElementById('btnChangeMyPassword');
    if (!curPwd) {
      showToast('Введіть поточний пароль', 'warning');
      return;
    }
    if (newPwd.length < 8 || !/[a-zA-Zа-яА-ЯіїєґІЇЄҐ]/.test(newPwd) || !/\d/.test(newPwd)) {
      showToast('Новий пароль має містити мінімум 8 символів, літери та цифри', 'warning');
      return;
    }
    if (newPwd !== cfmPwd) {
      showToast('Підтвердження нового пароля не співпадає', 'warning');
      return;
    }
    if (btn) btn.disabled = true;
    try {
      await api('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: curPwd, new_password: newPwd })
      });
      form.reset();
      showToast('Пароль успішно змінено!', 'success');
    } catch (_) {
    } finally {
      if (btn) btn.disabled = false;
    }
    return;
  }

  if (form.id === 'forgotPasswordForm') {
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
    return;
  }

  if (form.id === 'resetPasswordForm') {
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
  }
});
