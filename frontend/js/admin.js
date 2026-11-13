// 8. Admin (Facilities, Generators, Users Management, System Settings)
let allUsersCache = [];
let pendingDeleteGeneratorId = null;
let pendingDeleteFacilityId = null;

function renderManagedUserAvatarPreview(user) {
  const imgEl = document.getElementById('editUserAvatarImg');
  const initEl = document.getElementById('editUserAvatarInitials');
  const circleEl = document.getElementById('editUserAvatarCircle');
  const delBtn = document.getElementById('btnDeleteManagedAvatar');
  const fileIn = document.getElementById('editUserAvatarInput');
  if (fileIn) fileIn.value = '';
  if (!circleEl || !imgEl || !initEl) return;

  const displayName = user?.full_name || user?.login || '--';
  const initials = typeof window.getUserInitials === 'function' ? window.getUserInitials(displayName) : displayName.slice(0, 2).toUpperCase();
  const grad = typeof window.getAvatarGradient === 'function' ? window.getAvatarGradient(user?.login || displayName) : '';
  if (grad) circleEl.style.background = grad;

  if (user?.avatar_url) {
    imgEl.src = `${user.avatar_url}${user.avatar_url.includes('?') ? '&' : '?'}t=${Date.now()}`;
    imgEl.style.display = 'block';
    initEl.style.display = 'none';
    if (delBtn) delBtn.style.display = 'inline-flex';
  } else {
    imgEl.style.display = 'none';
    imgEl.removeAttribute('src');
    initEl.textContent = initials;
    initEl.style.display = 'flex';
    if (delBtn) delBtn.style.display = 'none';
  }
}

window.uploadManagedUserAvatar = async function (inputEl) {
  const file = inputEl?.files?.[0];
  if (!file) return;
  const uid = parseInt(document.getElementById('editUserId')?.value || '0', 10);
  if (!uid) return;
  if (file.size > 5 * 1024 * 1024) {
    showToast('Розмір зображення не повинен перевищувати 5 МБ', 'warning');
    inputEl.value = '';
    return;
  }
  try {
    const fd = new FormData();
    fd.append('file', file);
    const updated = await window.apiUpload(`/users/${uid}/avatar`, fd);
    const idx = allUsersCache.findIndex((u) => Number(u.id) === uid);
    if (idx >= 0) allUsersCache[idx] = { ...allUsersCache[idx], ...updated };
    renderManagedUserAvatarPreview(updated);
    if (currentUser && Number(currentUser.id) === uid) {
      currentUser.avatar_url = updated.avatar_url || null;
      window.updateAccountHeaderUI?.();
    }
    showToast('Аватар користувача оновлено', 'success');
    loadUsersData();
  } catch (err) {
    showToast(err.message || 'Помилка завантаження аватара', 'error');
  } finally {
    inputEl.value = '';
  }
};

window.deleteManagedUserAvatar = async function () {
  const uid = parseInt(document.getElementById('editUserId')?.value || '0', 10);
  if (!uid) return;
  try {
    const updated = await api(`/users/${uid}/avatar`, { method: 'DELETE' });
    const idx = allUsersCache.findIndex((u) => Number(u.id) === uid);
    if (idx >= 0) allUsersCache[idx] = { ...allUsersCache[idx], avatar_url: null };
    renderManagedUserAvatarPreview(updated || { ...allUsersCache[idx], avatar_url: null });
    if (currentUser && Number(currentUser.id) === uid) {
      currentUser.avatar_url = null;
      window.updateAccountHeaderUI?.();
    }
    showToast('Аватар користувача видалено', 'info');
    loadUsersData();
  } catch (err) {
    showToast(err.message || 'Помилка видалення аватара', 'error');
  }
};

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
      const facName = u.facility ? u.facility.name : (u.facility_id ? `Об'єкт #${u.facility_id}` : 'Всі об\'єкти');
      const initials = typeof window.getUserInitials === 'function' ? window.getUserInitials(u.full_name || u.login) : String(u.login || '--').slice(0, 2).toUpperCase();
      const grad = typeof window.getAvatarGradient === 'function' ? window.getAvatarGradient(u.login || u.full_name) : 'linear-gradient(135deg,#3b82f6,#1d4ed8)';
      const avatarChip = u.avatar_url
        ? `<img src="${escapeHtml(u.avatar_url)}" alt="" style="width:28px;height:28px;border-radius:50%;object-fit:cover;flex-shrink:0;border:1px solid rgba(255,255,255,0.2);">`
        : `<span style="width:28px;height:28px;border-radius:50%;background:${grad};color:#fff;font-size:0.72rem;font-weight:700;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;">${escapeHtml(initials)}</span>`;

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
          <td><div style="display:flex;align-items:center;gap:0.5rem;">${avatarChip}<b>${escapeHtml(u.login)}</b></div></td>
          <td>${escapeHtml(u.full_name)}</td>
          <td>${escapeHtml(u.email || '-')}</td>
          <td><span class="badge ${u.is_active ? 'badge-running' : 'badge-faulty'}">${u.is_active ? 'Активний' : 'Заблокований'}</span></td>
          <td>${escapeHtml(rolesUa)} <small style="display:block;color:var(--text-muted);font-size:0.75rem;">🏢 ${escapeHtml(facName)}</small></td>
          <td>${actionsHtml}</td>
        </tr>
      `;
    }).join('');
  } catch (_) {}
}

// User Create Form Submit (delegated for lazy modal DOM)
document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'userCreateForm') return;
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

  const facVal = parseInt(document.getElementById('newUserFacility')?.value || '0', 10) || null;
  const body = {
    login: loginVal,
    full_name: fullNameVal,
    email: emailVal,
    password: passVal,
    facility_id: facVal,
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
window.openEditUserModal = async function(id) {
  if (!isSuperAdmin()) {
    showToast('Редагування користувачів доступне лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const u = allUsersCache.find((user) => Number(user.id) === Number(id));
  if (!u) {
    showToast('Користувача не знайдено', 'error');
    return;
  }
  if (u.is_superadmin) {
    showToast('Редагування облікового запису головного суперадміністратора заборонено', 'warning');
    return;
  }

  await window.ViewLoader?.ensureModal('modalUserEdit');
  if (typeof window.populateCachedFacilitySelects === 'function') {
    await window.populateCachedFacilitySelects();
  }

  document.getElementById('editUserId').value = u.id;
  document.getElementById('editUserLogin').value = u.login;
  document.getElementById('editUserName').value = u.full_name;
  document.getElementById('editUserEmail').value = u.email || '';
  document.getElementById('editUserActive').checked = Boolean(u.is_active);
  const userFacSelect = document.getElementById('editUserFacility');
  if (userFacSelect) {
    userFacSelect.value = u.facility_id ? String(u.facility_id) : '';
  }
  document.getElementById('editUserPassword').value = '';

  const roleSelect = document.getElementById('editUserRole');
  if (roleSelect) {
    const primaryRole = (u.roles && u.roles[0]) ? u.roles[0].name.toLowerCase() : '';
    if (primaryRole === 'admin') roleSelect.value = '2';
    else if (primaryRole === 'viewer') roleSelect.value = '4';
    else roleSelect.value = '3';
  }

  renderManagedUserAvatarPreview(u);
  await openModal('modalUserEdit');
};

document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'userEditForm') return;
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
  const facVal = parseInt(document.getElementById('editUserFacility')?.value || '0', 10) || null;

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
    facility_id: facVal,
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
window.openResetPasswordModal = async function(id) {
  if (!isSuperAdmin()) {
    showToast('Скидання паролів доступне лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const u = allUsersCache.find((user) => Number(user.id) === Number(id));
  if (!u) {
    showToast('Користувача не знайдено', 'error');
    return;
  }
  if (u.is_superadmin) {
    showToast('Скидання пароля головного суперадміністратора заборонено', 'warning');
    return;
  }

  await window.ViewLoader?.ensureModal('modalUserResetPassword');
  document.getElementById('resetUserId').value = u.id;
  document.getElementById('resetUserDisplayLogin').innerText = u.login;
  document.getElementById('resetUserDisplayName').innerText = u.full_name;
  document.getElementById('resetNewPassword').value = '';
  document.getElementById('resetConfirmPassword').value = '';

  await openModal('modalUserResetPassword');
};

document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'userResetPasswordForm') return;
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
window.openDeleteUserModal = async function(id) {
  if (!isSuperAdmin()) {
    showToast('Видалення користувачів доступне лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const u = allUsersCache.find((user) => Number(user.id) === Number(id));
  if (!u) {
    showToast('Користувача не знайдено', 'error');
    return;
  }
  if (u.is_superadmin) {
    showToast('Видалення головного суперадміністратора заборонено', 'warning');
    return;
  }

  await window.ViewLoader?.ensureModal('modalUserDelete');
  document.getElementById('deleteUserId').value = u.id;
  document.getElementById('deleteUserDisplayLogin').innerText = u.login;
  document.getElementById('deleteUserDisplayName').innerText = u.full_name;

  await openModal('modalUserDelete');
};

document.addEventListener('click', async (e) => {
  if (!e.target || e.target.id !== 'confirmDeleteUserBtn') return;
  if (!isSuperAdmin()) {
    showToast('Дія доступна лише Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  const userId = parseInt(document.getElementById('deleteUserId')?.value || '0', 10);
  if (!userId) return;

  try {
    const res = await api(`/users/${userId}`, { method: 'DELETE' });
    closeModal('modalUserDelete');
    showToast(res.message || 'Користувача успішно видалено!', 'success');
    loadUsersData();
  } catch (_) {}
});

// Admin Facilities & Generators Tables
window.renderAdminFacilitiesAndGenerators = async function(forceRefresh = false) {
  const facTbody = document.querySelector('#adminFacilitiesTable tbody');
  const genTbody = document.querySelector('#adminGeneratorsTable tbody');
  if (!facTbody && !genTbody) return;

  try {
    const canFac = hasPermission('facility:configure');
    const canGen = hasPermission('generator:configure');
    const canDeleteFac = isSuperAdmin();
    if (forceRefresh) window.invalidateFacilitiesCache?.();
    const facilities = typeof window.getFacilitiesCached === 'function' ? await window.getFacilitiesCached(forceRefresh) : await api('/facilities');
    const activeFacId = currentFacilityId || (facilities && facilities[0] ? facilities[0].id : null);
    const generators = activeFacId ? await api(`/generator/list?facility_id=${encodeURIComponent(activeFacId)}`) : [];

    if (facTbody) {
      facTbody.innerHTML = (facilities || []).map((f) => {
        const prov = (f.default_fuel_provider || 'wog').toUpperCase();
        const yasnoBadge = f.yasno_enabled
          ? `<span class="badge badge-running">Увімк. (${escapeHtml(f.yasno_group || '-')})</span>`
          : `<span class="badge badge-stopped">Вимк.</span>`;
        const locTxt = [f.city, f.address].filter(Boolean).join(', ') || '-';
        const deleteFacBtn = canDeleteFac
          ? `<button type="button" class="btn-action" style="padding:0.25rem 0.5rem;min-height:auto;font-size:0.8rem;border-color:rgba(239,68,68,0.45);color:#f87171;" onclick="openDeleteFacilityModal(${Number(f.id)})" title="Видалити об'єкт">🗑️</button>`
          : `<button type="button" class="btn-action" disabled style="padding:0.25rem 0.5rem;min-height:auto;font-size:0.8rem;opacity:0.45;cursor:not-allowed;" title="Видалення об'єктів доступне лише Головному адміністратору">🔒</button>`;
        const actionsHtml = canFac ? `
          <div style="display:flex;gap:0.35rem;justify-content:center;">
            <button type="button" class="btn-action" style="padding:0.25rem 0.5rem;min-height:auto;font-size:0.8rem;" onclick="openQuickEditFacilityModal(${Number(f.id)})" title="Налаштування об'єкта">✏️</button>
            ${deleteFacBtn}
          </div>` : '<span style="color:var(--text-muted);font-size:0.75rem;">Тільки перегляд</span>';
        return `
          <tr>
            <td>#${Number(f.id)}</td>
            <td><b>${escapeHtml(f.name)}</b></td>
            <td>${escapeHtml(locTxt)}</td>
            <td><span class="badge badge-stopped">${escapeHtml(prov)}</span></td>
            <td>${yasnoBadge}</td>
            <td style="text-align:center;">${actionsHtml}</td>
          </tr>`;
      }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Об\'єктів не знайдено</td></tr>';
    }

    if (genTbody) {
      genTbody.innerHTML = (generators || []).map((g) => {
        const actionsHtml = canGen ? `
          <div style="display:flex;gap:0.35rem;justify-content:center;">
            <button type="button" class="btn-action" style="padding:0.25rem 0.5rem;min-height:auto;font-size:0.8rem;" onclick="openQuickEditGeneratorModal(${Number(g.id)})" title="Редагувати генератор">✏️</button>
            <button type="button" class="btn-action" style="padding:0.25rem 0.5rem;min-height:auto;font-size:0.8rem;border-color:rgba(239,68,68,0.45);color:#f87171;" onclick="openDeleteGeneratorModal(${Number(g.id)})" title="Видалити генератор">🗑️</button>
          </div>` : '<span style="color:var(--text-muted);font-size:0.75rem;">Тільки перегляд</span>';
        const hoursVal = Number(g.current_operating_hours ?? g.total_operating_hours ?? 0).toFixed(1).replace('.', ',');
        const consVal = Number(g.nominal_consumption_l_per_h || 0).toFixed(1).replace('.', ',');
        const powerVal = Number(g.rated_power_kw || 0).toFixed(1).replace('.', ',');
        return `
          <tr>
            <td>#${Number(g.id)}</td>
            <td><b>${escapeHtml(g.name)}</b><small style="display:block;color:var(--text-muted);">${escapeHtml(g.model || '-')}</small></td>
            <td><code>${escapeHtml(g.serial_number || '-')}</code></td>
            <td>${escapeHtml(g.fuel_type || 'А-95')} • <b>${Number(g.tank_capacity_l || 0).toFixed(0)} л</b></td>
            <td>${consVal} л/год • ${powerVal} кВт</td>
            <td><b>${hoursVal} год</b></td>
            <td style="text-align:center;">${actionsHtml}</td>
          </tr>`;
      }).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">Генераторів на обраному об\'єкті не знайдено</td></tr>';
    }
  } catch (err) {
    console.warn('renderAdminFacilitiesAndGenerators error:', err);
  }
};

// Generator Deletion Handlers
window.openDeleteGeneratorModal = async function(genId = null) {
  if (!hasPermission('generator:configure')) {
    showToast('Видалення генератора доступне лише Адміністратору', 'warning');
    return;
  }
  const targetId = genId ? Number(genId) : (currentGeneratorId ? Number(currentGeneratorId) : null);
  if (!targetId) {
    showToast('Генератор не вибрано', 'error');
    return;
  }
  try {
    const gen = (currentGenerator && Number(currentGenerator.id) === targetId)
      ? currentGenerator
      : await api(`/generator?generator_id=${encodeURIComponent(targetId)}`);
    if (!gen) {
      showToast('Генератор не знайдено', 'error');
      return;
    }
    if (gen.status === 'RUNNING') {
      showToast('Неможливо видалити генератор, який зараз працює! Спершу зупиніть його.', 'error');
      return;
    }
    pendingDeleteGeneratorId = Number(gen.id);
    await window.ViewLoader?.ensureModal('modalDeleteGenerator');
    const text = document.getElementById('deleteGenConfirmText');
    if (text) {
      text.innerHTML = `Ви дійсно бажаєте видалити генератор <b>"${escapeHtml(gen.name)}"</b> (Модель: ${escapeHtml(gen.model)}, S/N: ${escapeHtml(gen.serial_number)})?`;
    }
    await openModal('modalDeleteGenerator');
  } catch (err) {
    showToast(err.message || 'Помилка завантаження генератора', 'error');
  }
};

window.confirmDeleteCurrentGenerator = async function() {
  const targetId = pendingDeleteGeneratorId || currentGeneratorId;
  if (!targetId) return;
  try {
    const res = await api(`/generator/${encodeURIComponent(targetId)}`, { method: 'DELETE' });
    pendingDeleteGeneratorId = null;
    if (Number(targetId) === Number(currentGeneratorId)) {
      localStorage.removeItem('sd_last_generator_id');
      if (currentFacilityId) {
        localStorage.removeItem(`sd_last_gen_facility_${currentFacilityId}`);
      }
      currentGeneratorId = null;
    }
    await loadGeneratorsList(currentFacilityId);
    await Promise.all([
      loadAllData(),
      window.renderAdminFacilitiesAndGenerators(true)
    ]);
    closeModal('modalDeleteGenerator');
    showToast(res.message || 'Генератор успішно видалено!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
};

// Facility Deletion Handlers
window.openDeleteFacilityModal = async function(facId = null) {
  if (!isSuperAdmin()) {
    showToast("Видалення об'єктів доступне лише Головному адміністратору 🔒", 'warning');
    return;
  }
  const targetId = facId ? Number(facId) : (currentFacilityId ? Number(currentFacilityId) : null);
  if (!targetId) {
    showToast("Будь ласка, спочатку оберіть об'єкт для видалення", 'warning');
    return;
  }

  try {
    const facilities = typeof window.getFacilitiesCached === 'function' ? await window.getFacilitiesCached() : await api('/facilities');
    if (!facilities || facilities.length <= 1) {
      showToast("Неможливо видалити єдиний об'єкт у системі", 'warning');
      return;
    }
    const targetFac = facilities.find(f => Number(f.id) === targetId) || { id: targetId, name: `ID ${targetId}` };
    const generators = await api(`/generator/list?facility_id=${encodeURIComponent(targetId)}`);

    const runningGen = (generators || []).find(g => g.status === 'RUNNING');
    if (runningGen) {
      showToast(`Неможливо видалити об'єкт: генератор "${runningGen.name}" наразі працює! Спершу зупиніть його.`, 'error');
      return;
    }

    pendingDeleteFacilityId = targetId;
    await window.ViewLoader?.ensureModal('modalDeleteFacility');
    const text = document.getElementById('deleteFacilityConfirmText');
    if (text) {
      text.innerHTML = `Ви дійсно бажаєте видалити об'єкт <b>"${escapeHtml(targetFac.name)}"</b>?`;
    }

    const warnBox = document.getElementById('deleteFacilityGenWarning');
    const cascadeCheckbox = document.getElementById('deleteFacilityCascadeCheckbox');
    if (cascadeCheckbox) cascadeCheckbox.checked = false;

    if (warnBox) {
      if (generators && generators.length > 0) {
        warnBox.style.display = 'block';
        warnBox.innerHTML = `⚠️ <b>Увага:</b> На цьому об'єкті зареєстровано <b>${generators.length}</b> генератор(ів)!<br>Щоб видалити цей об'єкт разом з ними, обов'язково активуйте чекбокс <b>«Каскадне видалення»</b> нижче.`;
      } else {
        warnBox.style.display = 'none';
      }
    }

    await openModal('modalDeleteFacility');
  } catch (err) {
    showToast(err.message, 'error');
  }
};

window.confirmDeleteCurrentFacility = async function() {
  const targetId = pendingDeleteFacilityId || currentFacilityId;
  if (!targetId) return;
  const btn = document.getElementById('confirmDeleteFacilityBtn');
  const cascadeCheckbox = document.getElementById('deleteFacilityCascadeCheckbox');
  const cascade = cascadeCheckbox ? cascadeCheckbox.checked : false;

  if (btn) {
    btn.disabled = true;
    btn.innerText = 'Видалення...';
  }

  try {
    const res = await api(`/facilities/${encodeURIComponent(targetId)}?cascade=${cascade}`, { method: 'DELETE' });
    pendingDeleteFacilityId = null;
    window.invalidateFacilitiesCache?.();
    if (Number(targetId) === Number(currentFacilityId)) {
      localStorage.removeItem('sd_last_facility_id');
      localStorage.removeItem('sd_last_generator_id');
      localStorage.removeItem(`sd_last_gen_facility_${currentFacilityId}`);
      currentFacilityId = null;
      currentGeneratorId = null;
    }
    await loadFacilitiesList(true);
    await loadGeneratorsList(currentFacilityId);
    await Promise.all([
      loadAllData(),
      window.renderAdminFacilitiesAndGenerators(true),
      typeof loadFuelData === 'function' ? loadFuelData() : Promise.resolve()
    ]);
    closeModal('modalDeleteFacility');
    showToast(res.message || "Об'єкт успішно видалено!", 'success');
  } catch (err) {
    showToast(err.message || 'Помилка видалення об\'єкта', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = 'Підтвердити видалення';
    }
  }
};

// Modal Helpers for Facility and Generator Creation
window.openCreateFacilityModal = async function() {
  if (!hasPermission('facility:configure')) {
    showToast("Створення об'єктів доступне лише Адміністратору 🔒", 'warning');
    return;
  }
  await window.ViewLoader?.ensureModal('modalCreateFacility');
  const nameEl = document.getElementById('newFacilityName');
  if (nameEl) nameEl.value = '';
  const addrEl = document.getElementById('newFacilityAddress');
  if (addrEl) addrEl.value = '';
  const descEl = document.getElementById('newFacilityDescription');
  if (descEl) descEl.value = '';
  await openModal('modalCreateFacility');
};

window.openCreateGeneratorModal = async function() {
  if (!hasPermission('generator:configure')) {
    showToast('Створення генераторів доступне лише Адміністратору 🔒', 'warning');
    return;
  }
  await window.ViewLoader?.ensureModal('modalCreateGenerator');
  if (typeof window.populateCachedFacilitySelects === 'function') {
    await window.populateCachedFacilitySelects();
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

  await openModal('modalCreateGenerator');
};

// Facility Create Form Submit (delegated)
document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'facilityCreateForm') return;
  e.preventDefault();
  const name = document.getElementById('newFacilityName')?.value?.trim();
  const address = document.getElementById('newFacilityAddress')?.value?.trim();
  let city = document.getElementById('newFacilityCity')?.value?.trim() || null;
  if (city) {
    city = city.replace(/^(?:м\.|місто|смт|с\.)\s*/i, '');
    const cParts = city.split(/[,;]/);
    if (cParts.length > 1 && cParts[0].trim()) city = cParts[0].trim();
  }
  const description = document.getElementById('newFacilityDescription')?.value?.trim();

  if (!name) {
    showToast("Вкажіть назву об'єкта", 'warning');
    return;
  }

  const yasno_enabled = document.getElementById('newFacilityYasnoEnabled')?.checked ?? false;
  const yasno_dso_id = parseInt(document.getElementById('newFacilityYasnoDso')?.value || '301');
  const yasno_group = document.getElementById('newFacilityYasnoGroup')?.value || null;
  const default_fuel_provider = (document.getElementById('newFacilityFuelProvider')?.value || 'wog').toLowerCase();

  try {
    const created = await api('/facilities', {
      method: 'POST',
      body: JSON.stringify({
        name, address, city, description, timezone: 'Europe/Kyiv',
        yasno_enabled, yasno_dso_id, yasno_group, yasno_region_id: 3,
        default_fuel_provider
      })
    });
    currentFacilityId = created.id;
    currentGeneratorId = null;
    localStorage.setItem('sd_last_facility_id', currentFacilityId);
    localStorage.removeItem('sd_last_generator_id');
    localStorage.removeItem(`sd_last_gen_facility_${currentFacilityId}`);

    window.invalidateFacilitiesCache?.();
    await loadFacilitiesList(true);
    if (document.getElementById('facilitySelect')) {
      document.getElementById('facilitySelect').value = created.id;
    }
    await loadGeneratorsList(currentFacilityId);
    await Promise.all([
      loadAllData(),
      window.renderAdminFacilitiesAndGenerators(true),
      typeof loadFuelData === 'function' ? loadFuelData() : Promise.resolve()
    ]);
    closeModal('modalCreateFacility');
    showToast(`Об'єкт "${created.name}" успішно створено!`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Generator Create Form Submit (delegated)
document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'generatorCreateForm') return;
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
    await Promise.all([
      loadAllData(),
      window.renderAdminFacilitiesAndGenerators(true)
    ]);
    closeModal('modalCreateGenerator');
    showToast(`Генератор "${created.name}" успішно створено!`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Quick Edit Facility Modal Handlers
window.openQuickEditFacilityModal = async function(facId = null) {
  if (!hasPermission('facility:configure')) {
    showToast("Редагування об'єкта доступне лише Адміністратору", 'warning');
    return;
  }
  const targetFacId = facId ? Number(facId) : (currentFacilityId ? Number(currentFacilityId) : null);
  if (!targetFacId) {
    showToast("Будь ласка, спочатку оберіть об'єкт", "warning");
    return;
  }
  try {
    await window.ViewLoader?.ensureModal('modalQuickEditFacility');
    const fac = await api(`/facilities/${encodeURIComponent(targetFacId)}`);
    document.getElementById('quickEditFacilityId').value = fac.id;
    document.getElementById('quickEditFacilityName').value = fac.name || '';
    document.getElementById('quickEditFacilityAddress').value = fac.address || '';
    if (document.getElementById('quickEditFacilityCity')) {
      document.getElementById('quickEditFacilityCity').value = fac.city || '';
    }
    document.getElementById('quickEditFacilityDescription').value = fac.description || '';

    const yasnoEn = document.getElementById('quickEditFacilityYasnoEnabled');
    if (yasnoEn) {
      yasnoEn.checked = !!fac.yasno_enabled;
      const fFields = document.getElementById('quickEditFacilityYasnoFields');
      if (fFields) fFields.style.display = yasnoEn.checked ? 'grid' : 'none';
    }
    const dsoSel = document.getElementById('quickEditFacilityYasnoDso');
    if (dsoSel) dsoSel.value = fac.yasno_dso_id || 301;
    const grpSel = document.getElementById('quickEditFacilityYasnoGroup');
    if (grpSel) grpSel.value = fac.yasno_group || '3.2';
    const provSel = document.getElementById('quickEditFacilityFuelProvider');
    if (provSel) provSel.value = (fac.default_fuel_provider || 'wog').toLowerCase();

    await openModal('modalQuickEditFacility');
  } catch (err) {
    showToast(err.message || "Не вдалося завантажити дані об'єкта", 'error');
  }
};

document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'quickEditFacilityForm') return;
  e.preventDefault();
  const facId = parseInt(document.getElementById('quickEditFacilityId').value);
  const name = document.getElementById('quickEditFacilityName').value.trim();
  const address = document.getElementById('quickEditFacilityAddress').value.trim();
  let city = document.getElementById('quickEditFacilityCity')?.value?.trim() || null;
  if (city) {
    city = city.replace(/^(?:м\.|місто|смт|с\.)\s*/i, '');
    const cParts = city.split(/[,;]/);
    if (cParts.length > 1 && cParts[0].trim()) city = cParts[0].trim();
  }
  const description = document.getElementById('quickEditFacilityDescription').value.trim();

  const yasno_enabled = document.getElementById('quickEditFacilityYasnoEnabled')?.checked ?? false;
  const yasno_dso_id = parseInt(document.getElementById('quickEditFacilityYasnoDso')?.value || '301');
  const yasno_group = document.getElementById('quickEditFacilityYasnoGroup')?.value || null;
  const default_fuel_provider = (document.getElementById('quickEditFacilityFuelProvider')?.value || 'wog').toLowerCase();

  try {
    const updated = await api(`/facilities/${facId}`, {
      method: 'PUT',
      body: JSON.stringify({
        name, address, city, description,
        yasno_enabled, yasno_dso_id, yasno_group, yasno_region_id: 3,
        default_fuel_provider
      })
    });
    window.invalidateFacilitiesCache?.();
    await loadFacilitiesList(true);
    if (document.getElementById('facilitySelect')) {
      document.getElementById('facilitySelect').value = updated.id;
    }
    await Promise.all([
      loadAllData(),
      window.renderAdminFacilitiesAndGenerators(true),
      typeof loadFuelData === 'function' ? loadFuelData() : Promise.resolve()
    ]);
    closeModal('modalQuickEditFacility');
    showToast(`Об'єкт "${updated.name}" успішно оновлено!`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Quick Edit Generator Modal Handlers
window.openQuickEditGeneratorModal = async function(genId = null) {
  if (!hasPermission('generator:configure')) {
    showToast('Редагування генератора доступне лише Адміністратору', 'warning');
    return;
  }
  const targetGenId = genId ? Number(genId) : (currentGeneratorId ? Number(currentGeneratorId) : null);
  if (!targetGenId) {
    showToast("Будь ласка, спочатку оберіть генератор", "warning");
    return;
  }
  try {
    await window.ViewLoader?.ensureModal('modalQuickEditGenerator');
    const gen = (currentGenerator && Number(currentGenerator.id) === targetGenId)
      ? currentGenerator
      : await api(`/generator?generator_id=${encodeURIComponent(targetGenId)}`);
    document.getElementById('quickEditGenId').value = gen.id;
    document.getElementById('quickEditGenName').value = gen.name || '';
    document.getElementById('quickEditGenModel').value = gen.model || '';
    document.getElementById('quickEditGenSerial').value = gen.serial_number || '';
    const roundClean = (v, dec = 2) => (v === null || v === undefined || v === '') ? '' : Number(Number(v).toFixed(dec));
    document.getElementById('quickEditGenPower').value = roundClean(gen.rated_power_kw, 1);
    document.getElementById('quickEditGenTank').value = roundClean(gen.tank_capacity_l, 1);
    document.getElementById('quickEditGenConsumption').value = roundClean(gen.nominal_consumption_l_per_h, 2);
    if (document.getElementById('quickEditGenFuelType')) {
      document.getElementById('quickEditGenFuelType').value = gen.fuel_type || 'А-95';
    }
    await openModal('modalQuickEditGenerator');
  } catch (err) {
    showToast(err.message || 'Не вдалося завантажити дані генератора', 'error');
  }
};

document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'quickEditGeneratorForm') return;
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
    await loadGeneratorsList(currentFacilityId);
    if (document.getElementById('generatorSelect') && Number(updated.id) === Number(currentGeneratorId)) {
      document.getElementById('generatorSelect').value = updated.id;
    }
    await Promise.all([
      loadAllData(),
      window.renderAdminFacilitiesAndGenerators(true)
    ]);
    closeModal('modalQuickEditGenerator');
    showToast(`Генератор "${updated.name}" успішно оновлено!`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Admin System Settings, WOG & OKKO Fuel Prices & DB Reset
let activeSettingsFuelProvider = 'wog';

window.switchSettingsFuelProvider = function(prov) {
  try {
    activeSettingsFuelProvider = (prov || 'wog').toLowerCase();
    const isOkko = activeSettingsFuelProvider === 'okko';

    const tabWog = document.getElementById('tabFuelProviderWog');
    const tabOkko = document.getElementById('tabFuelProviderOkko');
    const boardWog = document.getElementById('wogPriceBoard');
    const boardOkko = document.getElementById('okkoPriceBoard');
    const metaEl = document.getElementById('sysInternetPricesMeta');
    const urlEl = document.getElementById('sysFuelProviderUrl');
    const btnRefresh = document.getElementById('btnRefreshFuelPrices');
    const fp = cachedFuelPrices;

    if (tabWog) {
      if (isOkko) {
        tabWog.classList.remove('active-wog');
        tabWog.style.borderColor = 'transparent';
        tabWog.style.color = 'var(--text-muted)';
        tabWog.style.background = 'transparent';
        tabWog.style.boxShadow = 'none';
      } else {
        tabWog.classList.add('active-wog');
        tabWog.style.borderColor = '#22c55e';
        tabWog.style.color = '#4ade80';
        tabWog.style.background = 'rgba(34, 197, 94, 0.22)';
        tabWog.style.boxShadow = '0 0 10px rgba(34, 197, 94, 0.25)';
      }
    }

    if (tabOkko) {
      if (isOkko) {
        tabOkko.classList.add('active-okko');
        tabOkko.style.borderColor = '#eab308';
        tabOkko.style.color = '#facc15';
        tabOkko.style.background = 'rgba(234, 179, 8, 0.22)';
        tabOkko.style.boxShadow = '0 0 10px rgba(234, 179, 8, 0.25)';
      } else {
        tabOkko.classList.remove('active-okko');
        tabOkko.style.borderColor = 'transparent';
        tabOkko.style.color = 'var(--text-muted)';
        tabOkko.style.background = 'transparent';
        tabOkko.style.boxShadow = 'none';
      }
    }

    if (boardWog) boardWog.style.display = isOkko ? 'none' : 'grid';
    if (boardOkko) {
      boardOkko.style.display = isOkko ? 'grid' : 'none';
      if (isOkko && (!boardOkko.innerHTML || boardOkko.innerHTML.trim() === '')) {
        renderAdminFuelPricesHints(cachedFuelPrices || {});
      }
    }

    if (urlEl) {
      if (isOkko) {
        urlEl.href = 'https://www.okko.ua/fuels';
        urlEl.textContent = 'okko.ua/fuels';
      } else {
        urlEl.href = 'https://wog.ua/ua/fuels/';
        urlEl.textContent = 'wog.ua/ua/fuels';
      }
    }

    if (metaEl) {
      if (isOkko) {
        const upd = fp?.okko_prices_updated_at ? ` (оновлено: ${fp.okko_prices_updated_at})` : '';
        metaEl.textContent = `Джерело: ${fp?.okko_prices_source || 'АЗК OKKO (okko.ua/fuels)'}${upd}`;
      } else {
        const upd = fp?.internet_prices_updated_at ? ` (оновлено: ${fp.internet_prices_updated_at})` : '';
        metaEl.textContent = `Джерело: ${fp?.internet_prices_source || 'АЗК WOG (wog.ua/ua/fuels/)'}${upd}`;
      }
    }

    if (btnRefresh) {
      if (isOkko) {
        btnRefresh.style.borderColor = '#eab308';
        btnRefresh.style.color = '#facc15';
        btnRefresh.textContent = '🟡 Оновити ціни OKKO';
      } else {
        btnRefresh.style.borderColor = '#22c55e';
        btnRefresh.style.color = '#4ade80';
        btnRefresh.textContent = '🟢 Оновити ціни WOG';
      }
    }

    // Update hints under price inputs
    updateAdminPriceHintsForActiveProvider(activeSettingsFuelProvider);
  } catch (err) {
    console.error('Error switching fuel provider:', err);
  }
};

function updateAdminPriceHintsForActiveProvider(prov) {
  const fp = cachedFuelPrices;
  if (!fp) return;
  const isOkko = prov === 'okko';
  const hintMap = [
    { key: 'А-95', elId: 'sysNetHintA95', defWog: '92.90', defOkko: '92.90' },
    { key: 'ДП', elId: 'sysNetHintDP', defWog: '103.50', defOkko: '106.90' },
    { key: 'А-92', elId: 'sysNetHintA92', defWog: '92.90', defOkko: '92.90' }
  ];
  for (const { key, elId, defWog, defOkko } of hintMap) {
    const el = document.getElementById(elId);
    if (!el) continue;
    const wogInfo = fp.fuels?.[key];
    const okkoInfo = fp.okko_fuels?.[key];
    const activeInfo = isOkko ? (okkoInfo || wogInfo) : wogInfo;
    const wogP = wogInfo ? Number(wogInfo.internet_price).toFixed(2) : defWog;
    const okkoP = okkoInfo ? Number(okkoInfo.internet_price).toFixed(2) : defOkko;
    const activeLabel = isOkko ? 'OKKO' : 'WOG';
    const activeColor = isOkko ? '#facc15' : '#4ade80';
    const effP = activeInfo ? Number(activeInfo.effective_price).toFixed(2) : (isOkko ? okkoP : wogP);
    el.innerHTML = `WOG: ${wogP} грн/л | OKKO: ${okkoP} грн/л | Діюча (${activeLabel}): <b style="color: ${activeColor};">${effP} грн/л</b>`;
  }
}

function renderAdminFuelPricesHints(fp) {
  if (!fp || (!fp.fuels && !fp.okko_fuels && !fp.wog_lineup && !fp.okko_lineup)) return;
  cachedFuelPrices = fp;

  // Render WOG Price Board
  const boardWog = document.getElementById('wogPriceBoard');
  if (boardWog) {
    const lineup = Array.isArray(fp.wog_lineup) && fp.wog_lineup.length > 0 ? fp.wog_lineup : [
      { type: 'ДП', brand: 'Євро5', price: fp.fuels?.['ДП']?.internet_price ?? 103.50 },
      { type: 'ДП', brand: 'Mustang+', price: fp.fuels?.['ДП Mustang+']?.internet_price ?? 106.50 },
      { type: '95', brand: 'Євро5-Е10', price: fp.fuels?.['А-95']?.internet_price ?? 92.90 },
      { type: '95', brand: 'Mustang Євро5-Е10', price: fp.fuels?.['А-95 Mustang']?.internet_price ?? 95.90 },
      { type: '100', brand: 'Mustang Євро5-Е0', price: 102.90 },
      { type: 'ГАЗ', brand: '', price: fp.fuels?.['ГАЗ']?.internet_price ?? 52.50 },
      { type: 'AdBlue', brand: '', price: 61.90 }
    ];
    boardWog.innerHTML = lineup.map((item) => {
      const isMustang = String(item.brand || '').toLowerCase().includes('mustang');
      const badgeColor = isMustang ? '#ef4444' : '#22c55e';
      return `<div style="background: var(--bg-subtle); border: 1px solid var(--border-color); border-left: 3px solid ${badgeColor}; border-radius: 0.5rem; padding: 0.55rem 0.7rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem;">
        <div>
          <div style="font-weight: 800; font-size: 0.95rem; color: var(--text-primary); line-height: 1.1;">${escapeHtml(item.type)}</div>
          <div style="font-size: 0.72rem; color: ${isMustang ? 'var(--accent-red)' : 'var(--text-muted)'};">${escapeHtml(item.brand || 'Стандарт')}</div>
        </div>
        <div style="font-weight: 800; font-size: 1.05rem; color: var(--accent-green); white-space: nowrap;">${Number(item.price).toFixed(2)} <span style="font-size: 0.7rem; font-weight: 500; color: var(--text-muted);">₴</span></div>
      </div>`;
    }).join('');
  }

  // Render OKKO Price Board
  const boardOkko = document.getElementById('okkoPriceBoard');
  if (boardOkko) {
    const okkoLineup = Array.isArray(fp.okko_lineup) && fp.okko_lineup.length > 0 ? fp.okko_lineup : [
      { type: 'ДП', brand: 'Євро', price: fp.okko_fuels?.['ДП']?.internet_price ?? 106.90 },
      { type: 'ДП', brand: 'Pulls', price: fp.okko_fuels?.['ДП Pulls']?.internet_price ?? 109.90 },
      { type: '95', brand: 'Євро', price: fp.okko_fuels?.['А-95']?.internet_price ?? 92.90 },
      { type: '95', brand: 'Pulls', price: fp.okko_fuels?.['А-95 Pulls']?.internet_price ?? 95.90 },
      { type: '100', brand: 'Pulls', price: 102.90 },
      { type: 'ГАЗ', brand: 'СПБТ', price: fp.okko_fuels?.['ГАЗ']?.internet_price ?? 59.90 },
      { type: 'AdBlue', brand: '', price: 61.90 }
    ];
    boardOkko.innerHTML = okkoLineup.map((item) => {
      const isPulls = String(item.brand || '').toLowerCase().includes('pulls');
      const badgeColor = isPulls ? '#ef4444' : '#eab308';
      return `<div style="background: var(--bg-subtle); border: 1px solid var(--border-color); border-left: 3px solid ${badgeColor}; border-radius: 0.5rem; padding: 0.55rem 0.7rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem;">
        <div>
          <div style="font-weight: 800; font-size: 0.95rem; color: var(--text-primary); line-height: 1.1;">${escapeHtml(item.type)}</div>
          <div style="font-size: 0.72rem; color: ${isPulls ? 'var(--accent-red)' : 'var(--text-muted)'};">${escapeHtml(item.brand || 'Стандарт')}</div>
        </div>
        <div style="font-weight: 800; font-size: 1.05rem; color: #facc15; white-space: nowrap;">${Number(item.price).toFixed(2)} <span style="font-size: 0.7rem; font-weight: 500; color: var(--text-muted);">₴</span></div>
      </div>`;
    }).join('');
  }

  // Sync active view
  switchSettingsFuelProvider(activeSettingsFuelProvider);
}

async function loadAdminSystemSettings() {
  try {
    const res = await api('/system/settings');
    const s = res.settings || {};
    const fp = res.fuel_prices || null;
    window.systemSettingsCache = s;

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

    // Default Chain & Weekly Options (parallelized & deduplicated facilities request)
    const sharedFacilities = await api('/facilities').catch(() => []);
    await Promise.all([
      populateAdminDefaultChain(s.default_facility_id, s.default_generator_id, s.default_fuel_stock_id, sharedFacilities),
      populateAdminEmailWeeklyOptions(s.email_weekly_facility_id, s.email_weekly_generator_id, sharedFacilities)
    ]);

    // SMTP & Failover Settings
    if (document.getElementById('sysSmtpEnabled')) document.getElementById('sysSmtpEnabled').checked = s.smtp_enabled === true;
    if (document.getElementById('sysEmailNotifyPwdChange')) document.getElementById('sysEmailNotifyPwdChange').checked = s.email_notify_password_change !== false;
    if (document.getElementById('sysEmailNotifySafetyStop')) document.getElementById('sysEmailNotifySafetyStop').checked = s.email_notify_safety_stop !== false;
    if (document.getElementById('sysEmailWeeklyEnabled')) document.getElementById('sysEmailWeeklyEnabled').checked = s.email_weekly_report_enabled === true;
    if (document.getElementById('sysSmtpPrimaryHost')) document.getElementById('sysSmtpPrimaryHost').value = s.smtp_primary_host || 'smtp.gmail.com';
    if (document.getElementById('sysSmtpPrimaryPort')) document.getElementById('sysSmtpPrimaryPort').value = s.smtp_primary_port || 587;
    if (document.getElementById('sysSmtpPrimaryUser')) document.getElementById('sysSmtpPrimaryUser').value = s.smtp_primary_user || '';
    if (document.getElementById('sysSmtpPrimaryPassword')) {
      const pIn = document.getElementById('sysSmtpPrimaryPassword');
      if (s.smtp_primary_password === '********') {
        pIn.value = '';
        pIn.placeholder = '•••••••• (Пароль збережено, залиште пустим щоб не змінювати)';
      } else {
        pIn.value = s.smtp_primary_password || '';
        pIn.placeholder = '16-значний пароль додатку Google';
      }
    }
    if (document.getElementById('sysSmtpPrimarySsl')) document.getElementById('sysSmtpPrimarySsl').checked = s.smtp_primary_ssl === true;
    if (document.getElementById('sysSmtpPrimaryFrom')) document.getElementById('sysSmtpPrimaryFrom').value = s.smtp_primary_from || '';

    if (document.getElementById('sysSmtpFallbackEnabled')) document.getElementById('sysSmtpFallbackEnabled').checked = s.smtp_fallback_enabled === true;
    if (document.getElementById('sysSmtpFallbackHost')) document.getElementById('sysSmtpFallbackHost').value = s.smtp_fallback_host || 'smtp.ukr.net';
    if (document.getElementById('sysSmtpFallbackPort')) document.getElementById('sysSmtpFallbackPort').value = s.smtp_fallback_port || 465;
    if (document.getElementById('sysSmtpFallbackUser')) document.getElementById('sysSmtpFallbackUser').value = s.smtp_fallback_user || '';
    if (document.getElementById('sysSmtpFallbackPassword')) {
      const fbIn = document.getElementById('sysSmtpFallbackPassword');
      if (s.smtp_fallback_password === '********') {
        fbIn.value = '';
        fbIn.placeholder = '•••••••• (Пароль збережено, залиште пустим щоб не змінювати)';
      } else {
        fbIn.value = s.smtp_fallback_password || '';
        fbIn.placeholder = 'Пароль для зовнішніх програм Ukr.net';
      }
    }
    if (document.getElementById('sysSmtpFallbackSsl')) document.getElementById('sysSmtpFallbackSsl').checked = s.smtp_fallback_ssl !== false;
    if (document.getElementById('sysSmtpFallbackFrom')) document.getElementById('sysSmtpFallbackFrom').value = s.smtp_fallback_from || '';

    if (document.getElementById('sysEmailWeeklyRecipients')) document.getElementById('sysEmailWeeklyRecipients').value = s.email_weekly_recipients || '';
    if (document.getElementById('sysEmailWeeklyDay')) document.getElementById('sysEmailWeeklyDay').value = String(s.email_weekly_send_day ?? 0);
    if (document.getElementById('sysEmailWeeklyTime')) document.getElementById('sysEmailWeeklyTime').value = s.email_weekly_send_time || '08:00';

    renderAdminFuelPricesHints(fp);
  } catch (_) {}
}

async function populateAdminDefaultChain(defaultFacId, defaultGenId, defaultStockId, preloadedFacilities = null) {
  try {
    const facSel = document.getElementById('sysDefaultFacilityId');
    if (!facSel) return;

    const facilities = Array.isArray(preloadedFacilities) ? preloadedFacilities : await api('/facilities');
    facSel.innerHTML = '<option value="">(Авто / Перший об\'єкт)</option>' +
      (facilities || []).map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');

    if (defaultFacId && (facilities || []).some(f => Number(f.id) === Number(defaultFacId))) {
      facSel.value = String(defaultFacId);
    } else if ((facilities || []).length === 1) {
      facSel.value = String(facilities[0].id);
    } else {
      facSel.value = '';
    }

    await onAdminDefaultFacilityChange(defaultGenId, defaultStockId);
  } catch (e) {
    console.warn('populateAdminDefaultChain error:', e);
  }
}

window.onAdminDefaultFacilityChange = async function(preselectGenId = null, preselectStockId = null) {
  const facSel = document.getElementById('sysDefaultFacilityId');
  const genSel = document.getElementById('sysDefaultGeneratorId');
  const stockSel = document.getElementById('sysDefaultFuelStockId');
  if (!facSel || !genSel || !stockSel) return;

  const facId = parseInt(facSel.value || '0', 10);
  if (!facId) {
    genSel.innerHTML = '<option value="">(Авто / Перший генератор)</option>';
    stockSel.innerHTML = '<option value="">(Авто / Перший склад)</option>';
    return;
  }

  try {
    const [generators, stocks] = await Promise.all([
      api(`/generator/list?facility_id=${facId}`),
      api(`/fuel/stocks?facility_id=${facId}`)
    ]);

    const genList = Array.isArray(generators) ? generators : (generators && generators.id ? [generators] : []);
    genSel.innerHTML = '<option value="">(Авто / Перший генератор)</option>' +
      genList.map(g => `<option value="${Number(g.id)}">${escapeHtml(g.name)} (${escapeHtml(g.model || '')})</option>`).join('');
    if (preselectGenId && genList.some(g => Number(g.id) === Number(preselectGenId))) {
      genSel.value = String(preselectGenId);
    } else if (genList.length === 1) {
      genSel.value = String(genList[0].id);
    } else {
      genSel.value = '';
    }

    const stockList = Array.isArray(stocks) ? stocks : (stocks && stocks.id ? [stocks] : []);
    stockSel.innerHTML = '<option value="">(Авто / Перший склад)</option>' +
      stockList.map(s => {
        const bal = typeof s.current_balance_l === 'number' ? s.current_balance_l.toFixed(2).replace('.', ',') : (s.current_balance_l || '0,00');
        return `<option value="${Number(s.id)}">${escapeHtml(s.name)} (${escapeHtml(s.fuel_type || 'А-95')}: ${bal} л)</option>`;
      }).join('');
    if (preselectStockId && stockList.some(s => Number(s.id) === Number(preselectStockId))) {
      stockSel.value = String(preselectStockId);
    } else if (stockList.length === 1) {
      stockSel.value = String(stockList[0].id);
    } else {
      stockSel.value = '';
    }
  } catch (err) {
    console.warn('onAdminDefaultFacilityChange error:', err);
  }
};

window.saveDefaultChainSettings = async function() {
  const btn = document.getElementById('btnSaveDefaultChain');
  const facSel = document.getElementById('sysDefaultFacilityId');
  const genSel = document.getElementById('sysDefaultGeneratorId');
  const stockSel = document.getElementById('sysDefaultFuelStockId');

  const facId = parseInt(facSel?.value || '0', 10) || null;
  const genId = parseInt(genSel?.value || '0', 10) || null;
  const stockId = parseInt(stockSel?.value || '0', 10) || null;

  if (btn) {
    btn.disabled = true;
    btn.innerText = 'Збереження...';
  }

  try {
    const res = await api('/system/settings', {
      method: 'PUT',
      body: JSON.stringify({
        default_facility_id: facId,
        default_generator_id: genId,
        default_fuel_stock_id: stockId
      })
    });
    showToast('Стартовий ланцюжок за замовчуванням успішно збережено!', 'success');
    await loadAdminSystemSettings();
  } catch (err) {
    showToast('Помилка збереження ланцюжка: ' + (err.message || 'Невідома помилка'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '💾 Зберегти ланцюжок за замовчуванням';
    }
  }
};

async function populateAdminEmailWeeklyOptions(weeklyFacId, weeklyGenId, preloadedFacilities = null) {
  try {
    const facSel = document.getElementById('sysEmailWeeklyFacilityId');
    if (!facSel) return;

    const facilities = Array.isArray(preloadedFacilities) ? preloadedFacilities : await api('/facilities');
    facSel.innerHTML = '<option value="">(За замовчуванням)</option>' +
      (facilities || []).map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');

    if (weeklyFacId && (facilities || []).some(f => Number(f.id) === Number(weeklyFacId))) {
      facSel.value = String(weeklyFacId);
    } else {
      facSel.value = '';
    }

    await onAdminEmailWeeklyFacilityChange(weeklyGenId);
  } catch (e) {
    console.warn('populateAdminEmailWeeklyOptions error:', e);
  }
}

window.onAdminEmailWeeklyFacilityChange = async function(preselectGenId = null) {
  const facSel = document.getElementById('sysEmailWeeklyFacilityId');
  const genSel = document.getElementById('sysEmailWeeklyGeneratorId');
  if (!facSel || !genSel) return;

  const facId = parseInt(facSel.value || '0', 10);
  if (!facId) {
    genSel.innerHTML = '<option value="">(Усі генератори за замовчуванням)</option>';
    return;
  }

  try {
    const generators = await api(`/generator/list?facility_id=${facId}`);
    genSel.innerHTML = '<option value="">(Усі генератори об\'єкта)</option>' +
      (generators || []).map(g => `<option value="${Number(g.id)}">${escapeHtml(g.name)} (${escapeHtml(g.model)})</option>`).join('');
    if (preselectGenId && (generators || []).some(g => Number(g.id) === Number(preselectGenId))) {
      genSel.value = String(preselectGenId);
    } else {
      genSel.value = '';
    }
  } catch (err) {
    console.warn('onAdminEmailWeeklyFacilityChange error:', err);
  }
};

window.refreshFuelPricesFromInternet = async function () {
  try {
    const prov = (activeSettingsFuelProvider || 'wog').toLowerCase();
    const provLabel = prov === 'okko' ? 'АЗК OKKO (okko.ua)' : 'АЗК WOG (wog.ua)';
    showToast(`Запит актуальних цін з офіційного сайту ${provLabel}...`, 'info');
    const fp = await api(`/system/fuel-prices/refresh?provider=${encodeURIComponent(prov)}`, { method: 'POST' });
    renderAdminFuelPricesHints(fp);
    const fuelsDict = prov === 'okko' ? (fp?.okko_fuels || fp?.fuels) : fp?.fuels;
    const dp = Number(fuelsDict?.['ДП']?.internet_price ?? 103.50).toFixed(2);
    const a95 = Number(fuelsDict?.['А-95']?.internet_price ?? 92.90).toFixed(2);
    const gas = Number(fuelsDict?.['ГАЗ']?.internet_price ?? 52.50).toFixed(2);
    showToast(`Ціни ${prov === 'okko' ? 'АЗК OKKO' : 'АЗК WOG'} оновлено! ДП: ${dp} грн | А-95: ${a95} грн | ГАЗ: ${gas} грн`, 'success');
  } catch (_) {}
};

document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'systemSettingsForm') return;
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerText = '💾 Збереження налаштувань...';
  }

  const pPass = document.getElementById('sysSmtpPrimaryPassword')?.value;
  const fbPass = document.getElementById('sysSmtpFallbackPassword')?.value;

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
    email_weekly_report_enabled: document.getElementById('sysEmailWeeklyEnabled')?.checked ?? false,
    smtp_primary_host: document.getElementById('sysSmtpPrimaryHost')?.value.trim() || 'smtp.gmail.com',
    smtp_primary_port: parseInt(document.getElementById('sysSmtpPrimaryPort')?.value || '587', 10),
    smtp_primary_user: document.getElementById('sysSmtpPrimaryUser')?.value.trim() || '',
    smtp_primary_ssl: document.getElementById('sysSmtpPrimarySsl')?.checked ?? false,
    smtp_primary_from: document.getElementById('sysSmtpPrimaryFrom')?.value.trim() || '',
    smtp_fallback_enabled: document.getElementById('sysSmtpFallbackEnabled')?.checked ?? false,
    smtp_fallback_host: document.getElementById('sysSmtpFallbackHost')?.value.trim() || 'smtp.ukr.net',
    smtp_fallback_port: parseInt(document.getElementById('sysSmtpFallbackPort')?.value || '465', 10),
    smtp_fallback_user: document.getElementById('sysSmtpFallbackUser')?.value.trim() || '',
    smtp_fallback_ssl: document.getElementById('sysSmtpFallbackSsl')?.checked ?? true,
    smtp_fallback_from: document.getElementById('sysSmtpFallbackFrom')?.value.trim() || '',
    email_weekly_recipients: document.getElementById('sysEmailWeeklyRecipients')?.value.trim() || '',
    email_weekly_send_day: parseInt(document.getElementById('sysEmailWeeklyDay')?.value || '0', 10),
    email_weekly_send_time: document.getElementById('sysEmailWeeklyTime')?.value || '08:00',
    // Default Chain & Weekly target bindings
    default_facility_id: parseInt(document.getElementById('sysDefaultFacilityId')?.value || '0', 10) || null,
    default_generator_id: parseInt(document.getElementById('sysDefaultGeneratorId')?.value || '0', 10) || null,
    default_fuel_stock_id: parseInt(document.getElementById('sysDefaultFuelStockId')?.value || '0', 10) || null,
    email_weekly_facility_id: parseInt(document.getElementById('sysEmailWeeklyFacilityId')?.value || '0', 10) || null,
    email_weekly_generator_id: parseInt(document.getElementById('sysEmailWeeklyGeneratorId')?.value || '0', 10) || null
  };

  // Only pass password if user entered a new string; otherwise keep existing in DB
  if (pPass && pPass.trim() !== '') {
    body.smtp_primary_password = pPass;
  }
  if (fbPass && fbPass.trim() !== '') {
    body.smtp_fallback_password = fbPass;
  }

  try {
    const res = await api('/system/settings', { method: 'PUT', body: JSON.stringify(body) });
    renderAdminFuelPricesHints(res.fuel_prices);
    if (document.getElementById('sysApplyAllGens') && res.settings) {
      document.getElementById('sysApplyAllGens').checked = res.settings.apply_to_all_generators !== false;
    }
    showToast(res.message || 'Системні налаштування успішно збережено!', 'success');
    await loadAdminSystemSettings();
    loadAllData();
  } catch (err) {
    showToast('Помилка збереження налаштувань: ' + (err.message || 'Невідома помилка'), 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerText = '💾 Зберегти системні налаштування';
    }
  }
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
  await window.ViewLoader?.ensureModal('modalSystemReset');
  try {
    const facilities = typeof window.getFacilitiesCached === 'function' ? await window.getFacilitiesCached() : await api('/facilities');
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
  await openModal('modalSystemReset');
};

document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'systemResetForm') return;
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

// ---------------------------------------------------------------------------
// Advanced Interactive SMTP Testing Modal & Weekly Report Dispatcher
// ---------------------------------------------------------------------------
let currentSmtpTestProvider = 'primary';

window.switchSmtpTestTab = function (provider) {
  currentSmtpTestProvider = provider;
  ['primary', 'fallback', 'failover'].forEach(p => {
    const btn = document.getElementById(`tabBtnSmtp${p.charAt(0).toUpperCase() + p.slice(1)}`);
    if (btn) {
      if (p === provider) btn.classList.add('active');
      else btn.classList.remove('active');
    }
  });

  const hostEl = document.getElementById('smtpTestHostDisplay');
  const userEl = document.getElementById('smtpTestUserDisplay');
  const sslEl = document.getElementById('smtpTestSslDisplay');
  const resCard = document.getElementById('smtpTestResultCard');
  if (resCard) resCard.style.display = 'none';

  if (provider === 'primary') {
    const host = document.getElementById('sysSmtpPrimaryHost')?.value.trim() || 'smtp.gmail.com';
    const port = document.getElementById('sysSmtpPrimaryPort')?.value || '587';
    const user = document.getElementById('sysSmtpPrimaryUser')?.value.trim() || '(не вказано)';
    const ssl = document.getElementById('sysSmtpPrimarySsl')?.checked;
    if (hostEl) hostEl.innerText = `${host}:${port}`;
    if (userEl) userEl.innerText = user;
    if (sslEl) sslEl.innerText = ssl ? 'Прямий SSL (порт 465)' : 'STARTTLS (порт 587)';
  } else if (provider === 'fallback') {
    const host = document.getElementById('sysSmtpFallbackHost')?.value.trim() || 'smtp.ukr.net';
    const port = document.getElementById('sysSmtpFallbackPort')?.value || '465';
    const user = document.getElementById('sysSmtpFallbackUser')?.value.trim() || '(не вказано)';
    const ssl = document.getElementById('sysSmtpFallbackSsl')?.checked;
    if (hostEl) hostEl.innerText = `${host}:${port}`;
    if (userEl) userEl.innerText = user;
    if (sslEl) sslEl.innerText = ssl ? 'Прямий SSL (порт 465 для Ukr.net)' : 'STARTTLS (порт 587)';
  } else {
    if (hostEl) hostEl.innerText = 'Primary -> Fallback (Автоматичний Failover)';
    if (userEl) userEl.innerText = 'Перевірка перемикання при недоступності основного';
    if (sslEl) sslEl.innerText = 'Динамічне резервування';
  }
};

window.openSmtpTestModal = async function (provider = 'primary') {
  if (!isAdmin()) {
    showToast('Тестування пошти доступне лише адміністратору системи', 'warning');
    return;
  }
  await window.ViewLoader?.ensureModal('modalSmtpTest');
  const defaultEmail = currentUser?.email || document.getElementById('sysSmtpPrimaryUser')?.value || '';
  const input = document.getElementById('smtpTestRecipientInput');
  if (input) input.value = defaultEmail;

  const spinner = document.getElementById('smtpTestSpinner');
  if (spinner) spinner.style.display = 'none';
  const resCard = document.getElementById('smtpTestResultCard');
  if (resCard) {
    resCard.style.display = 'none';
    resCard.innerHTML = '';
  }

  switchSmtpTestTab(provider);
  await openModal('modalSmtpTest');
};

window.executeSmtpModalTest = async function () {
  const recipient = document.getElementById('smtpTestRecipientInput')?.value.trim();
  const btn = document.getElementById('btnRunSmtpTest');
  const spinner = document.getElementById('smtpTestSpinner');
  const resCard = document.getElementById('smtpTestResultCard');

  if (!recipient || !recipient.includes('@')) {
    showToast('Будь ласка, введіть коректну адресу email отримувача', 'warning');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerText = '⏳ Надсилання...';
  }
  if (spinner) spinner.style.display = 'block';
  if (resCard) resCard.style.display = 'none';

  // Read live form values for on-the-fly test
  const pPass = document.getElementById('sysSmtpPrimaryPassword')?.value;
  const fbPass = document.getElementById('sysSmtpFallbackPassword')?.value;

  const payload = {
    recipient: recipient,
    provider: currentSmtpTestProvider,
    smtp_primary_host: document.getElementById('sysSmtpPrimaryHost')?.value.trim() || 'smtp.gmail.com',
    smtp_primary_port: parseInt(document.getElementById('sysSmtpPrimaryPort')?.value || '587', 10),
    smtp_primary_user: document.getElementById('sysSmtpPrimaryUser')?.value.trim() || '',
    smtp_primary_password: pPass || undefined,
    smtp_primary_ssl: document.getElementById('sysSmtpPrimarySsl')?.checked ?? false,
    smtp_primary_from: document.getElementById('sysSmtpPrimaryFrom')?.value.trim() || '',
    smtp_fallback_enabled: document.getElementById('sysSmtpFallbackEnabled')?.checked ?? false,
    smtp_fallback_host: document.getElementById('sysSmtpFallbackHost')?.value.trim() || 'smtp.ukr.net',
    smtp_fallback_port: parseInt(document.getElementById('sysSmtpFallbackPort')?.value || '465', 10),
    smtp_fallback_user: document.getElementById('sysSmtpFallbackUser')?.value.trim() || '',
    smtp_fallback_password: fbPass || undefined,
    smtp_fallback_ssl: document.getElementById('sysSmtpFallbackSsl')?.checked ?? true,
    smtp_fallback_from: document.getElementById('sysSmtpFallbackFrom')?.value.trim() || ''
  };

  try {
    const res = await api('/system/email/test', {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    if (spinner) spinner.style.display = 'none';
    if (resCard) {
      resCard.style.display = 'block';

      if (res.status === 'ok') {
        resCard.className = 'test-result-box success';
        resCard.innerHTML = `
          <div style="font-weight: 700; font-size: 1rem; margin-bottom: 0.4rem; display: flex; align-items: center; gap: 0.4rem;">
            <span>🟢</span> <span>Тестовий лист успішно надіслано!</span>
          </div>
          <div style="font-size: 0.85rem; line-height: 1.5;">
            <div><b>Шлюз:</b> ${escapeHtml(res.provider?.toUpperCase())} (${escapeHtml(res.host || '')}:${res.port || ''})</div>
            <div><b>Отримувач:</b> ${escapeHtml(res.recipient || recipient)}</div>
            <div><b>Час виконання:</b> ${escapeHtml(res.tested_at || '')} (${res.duration_ms || 0} мс)</div>
            <div style="margin-top: 0.5rem; color: #4ade80;">
              ✨ Повідомлення відправлено. Перевірте скриньку отримувача (також перевірте папку «Спам» або «Оповіщення»).
            </div>
          </div>
        `;
        showToast('Тестовий лист успішно надіслано!', 'success');
      } else if (res.status === 'warning') {
        resCard.className = 'test-result-box warning';
        resCard.innerHTML = `
          <div style="font-weight: 700; font-size: 1rem; margin-bottom: 0.4rem; display: flex; align-items: center; gap: 0.4rem;">
            <span>⚠️</span> <span>Спрацював резервний канал (Failover)!</span>
          </div>
          <div style="font-size: 0.85rem; line-height: 1.5;">
            <div>${escapeHtml(res.warning || res.message || '')}</div>
            <div style="margin-top: 0.4rem;"><b>Доставлено через:</b> ${escapeHtml(res.provider?.toUpperCase())} (${escapeHtml(res.host || '')})</div>
            <div><b>Отримувач:</b> ${escapeHtml(res.recipient || recipient)}</div>
          </div>
        `;
        showToast('Спрацював резервний SMTP (Failover)!', 'warning');
      } else {
        resCard.className = 'test-result-box error';
        resCard.innerHTML = `
          <div style="font-weight: 700; font-size: 1rem; margin-bottom: 0.4rem; display: flex; align-items: center; gap: 0.4rem;">
            <span>🔴</span> <span>Помилка доставки тестового листа</span>
          </div>
          <div style="font-size: 0.85rem; line-height: 1.5;">
            <div><b>Сервер:</b> ${escapeHtml(res.host || '')}</div>
            <div style="color: #fca5a5; margin-top: 0.35rem; font-family: monospace; background: rgba(0,0,0,0.25); padding: 0.4rem 0.6rem; border-radius: 4px;">
              ${escapeHtml(res.error || 'Невідома помилка SMTP')}
            </div>
            ${res.hint ? `<div class="test-hint-box"><b>💡 Інструкція з вирішення:</b>
${escapeHtml(res.hint)}</div>` : ''}
          </div>
        `;
        showToast('Помилка надсилання тестового листа', 'error');
      }
    }
  } catch (err) {
    if (spinner) spinner.style.display = 'none';
    if (resCard) {
      resCard.style.display = 'block';
      resCard.className = 'test-result-box error';
      resCard.innerHTML = `
        <div style="font-weight: 700; font-size: 1rem; margin-bottom: 0.4rem;">🔴 Помилка запиту до сервера</div>
        <div style="font-size: 0.85rem; color: #fca5a5;">${escapeHtml(err.message || 'Не вдалося виконати запит')}</div>
      `;
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '🚀 Запустити тест';
    }
  }
};

async function populateWeeklyReportModalSelectors() {
  const facSel = document.getElementById('weeklyReportFacilitySelect');
  const genSel = document.getElementById('weeklyReportGeneratorSelect');
  if (!facSel || !genSel) return;

  try {
    const facilities = await api('/facilities');
    facSel.innerHTML = (facilities || []).map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');

    const targetFac = currentFacilityId || (facilities && facilities[0] ? facilities[0].id : null);
    if (targetFac && (facilities || []).some(f => f.id === targetFac)) {
      facSel.value = targetFac;
    }

    await onWeeklyReportModalFacilityChange(currentGeneratorId);
  } catch (e) {
    console.warn('populateWeeklyReportModalSelectors error:', e);
  }
}

window.onWeeklyReportModalFacilityChange = async function(preselectGenId = null) {
  const facSel = document.getElementById('weeklyReportFacilitySelect');
  const genSel = document.getElementById('weeklyReportGeneratorSelect');
  if (!facSel || !genSel) return;

  const facId = parseInt(facSel.value || '0', 10);
  if (!facId) return;

  try {
    const generators = await api(`/generator/list?facility_id=${facId}`);
    if (!generators || generators.length === 0) {
      genSel.innerHTML = '<option value="">(Немає генераторів на об\'єкті)</option>';
    } else {
      genSel.innerHTML = '<option value="">(Усі генератори об\'єкта)</option>' +
        generators.map(g => `<option value="${Number(g.id)}">${escapeHtml(g.name)} (${escapeHtml(g.model)})</option>`).join('');
      if (preselectGenId && generators.some(g => g.id === preselectGenId)) {
        genSel.value = preselectGenId;
      }
    }
  } catch (e) {
    console.warn('onWeeklyReportModalFacilityChange error:', e);
  }
};

window.openSendWeeklyReportModal = async function () {
  if (!isAdmin()) {
    showToast('Відправка звітів доступна лише адміністратору системи', 'warning');
    return;
  }
  await window.ViewLoader?.ensureModal('modalSendWeeklyReport');
  const configured = document.getElementById('sysEmailWeeklyRecipients')?.value.trim() || currentUser?.email || '';
  const input = document.getElementById('weeklyReportRecipientsInput');
  if (input) input.value = configured;

  const spinner = document.getElementById('weeklyReportSpinner');
  if (spinner) spinner.style.display = 'none';
  const resBox = document.getElementById('weeklyReportResultBox');
  if (resBox) {
    resBox.style.display = 'none';
    resBox.innerHTML = '';
  }

  await populateWeeklyReportModalSelectors();

  await openModal('modalSendWeeklyReport');
};

window.executeSendWeeklyReport = async function () {
  const recipients = document.getElementById('weeklyReportRecipientsInput')?.value.trim();
  const facId = parseInt(document.getElementById('weeklyReportFacilitySelect')?.value || '0', 10) || null;
  const genId = parseInt(document.getElementById('weeklyReportGeneratorSelect')?.value || '0', 10) || null;
  const btn = document.getElementById('btnSubmitWeeklyReport');
  const spinner = document.getElementById('weeklyReportSpinner');
  const resBox = document.getElementById('weeklyReportResultBox');

  if (!recipients) {
    showToast('Будь ласка, введіть щонайменше одну адресу email', 'warning');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerText = '📊 Генерація...';
  }
  if (spinner) spinner.style.display = 'block';
  if (resBox) resBox.style.display = 'none';

  try {
    let url = `/system/email/weekly-digest/send?recipient=${encodeURIComponent(recipients)}`;
    if (facId) url += `&facility_id=${facId}`;
    if (genId) url += `&generator_id=${genId}`;
    const res = await api(url, {
      method: 'POST'
    });
    if (spinner) spinner.style.display = 'none';
    if (resBox) {
      resBox.style.display = 'block';
      resBox.className = 'test-result-box success';
      resBox.innerHTML = `
        <div style="font-weight: 700;">✅ Звіт Excel успішно згенеровано та надіслано!</div>
        <div style="margin-top: 0.35rem; font-size: 0.83rem;">Отримувачі: ${escapeHtml(recipients)}</div>
      `;
    }
    showToast(res.message || 'Звіт Excel успішно відправлено на пошту!', 'success');
  } catch (err) {
    if (spinner) spinner.style.display = 'none';
    if (resBox) {
      resBox.style.display = 'block';
      resBox.className = 'test-result-box error';
      resBox.innerHTML = `
        <div style="font-weight: 700;">❌ Помилка відправки щотижневого звіту</div>
        <div style="margin-top: 0.35rem; font-size: 0.83rem;">${escapeHtml(err.message)}</div>
      `;
    }
    showToast(`Помилка відправки звіту: ${err.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '✉️ Надіслати звіт зараз';
    }
  }
};

// Aliases for compatibility
window.triggerSmtpTest = function (provider) {
  openSmtpTestModal(provider);
};

window.triggerManualWeeklyReportEmail = function () {
  openSendWeeklyReportModal();
};


