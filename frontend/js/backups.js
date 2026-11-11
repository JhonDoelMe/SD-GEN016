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

