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
    window.renderPaginatedTable('maintenanceHistoryTable', records, (r) => `
      <tr>
        <td>${formatDateTime(r.created_at)}</td>
        <td><span class="badge ${r.maintenance_type === 'SCHEDULED' ? 'badge-running' : 'badge-stopped'}">${r.maintenance_type === 'SCHEDULED' ? 'Регламентне' : 'Проміжне'}</span></td>
        <td><b>${formatHoursCounter(r.operating_hours)}</b></td>
        <td>${escapeHtml(r.work_description)}</td>
        <td>${escapeHtml(r.consumables_used || '-')}</td>
        <td>${formatMoney(r.cost)}</td>
        <td>${escapeHtml(r.user_name || '-')}</td>
      </tr>
    `, 7, 'Записів ТО не знайдено', 10);
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
    const res = await api('/maintenance/record', {
      method: 'POST',
      body: JSON.stringify(body),
      offlineMeta: {
        action_type: 'maint_record',
        title: 'Фіксація ТО генератора',
        summary: `${body.maintenance_type === 'SCHEDULED' ? 'Регламентне ТО' : 'Проміжне ТО'}: ${body.work_description}`,
        facility_id: currentFacilityId,
        generator_id: currentGeneratorId,
      }
    });
    closeModal('modalMaintenance');
    showToast(res?._queuedOffline ? '📥 Запис ТО збережено в офлайн-чергу!' : 'ТО успішно зафіксовано в системі!', res?._queuedOffline ? 'warning' : 'success');
    loadAllData();
  } catch (_) {}
});

window.openAdminResetMaintModal = function() {
  const m = cachedMaintenanceSchedule;
  const genName = document.getElementById('genName')?.innerText || 'Поточний генератор';
  const curHours = m ? m.current_operating_hours : (parseFloat(document.getElementById('cardHours')?.innerText?.replace(',', '.') || '0') || 0.0);
  const interval = (m && m.interval_hours) ? m.interval_hours : 300.0;

  const genNameIn = document.getElementById('adminResetGenName');
  if (genNameIn) genNameIn.value = genName;

  const curHoursIn = document.getElementById('adminResetCurrentHours');
  if (curHoursIn) curHoursIn.value = formatHoursCounter(curHours);

  const opHoursIn = document.getElementById('adminResetOperatingHours');
  if (opHoursIn) {
    opHoursIn.value = curHours.toFixed(1);
    opHoursIn.oninput = function() {
      const val = parseFloat(opHoursIn.value) || 0.0;
      const preview = document.getElementById('adminResetNextDuePreview');
      if (preview) {
        preview.innerText = `${(val + interval).toFixed(1).replace('.', ',')} год (+${interval.toFixed(0)} год регламенту)`;
      }
    };
  }

  const preview = document.getElementById('adminResetNextDuePreview');
  if (preview) {
    preview.innerText = `${(curHours + interval).toFixed(1).replace('.', ',')} год (+${interval.toFixed(0)} год регламенту)`;
  }

  const workDescIn = document.getElementById('adminResetWorkDesc');
  if (workDescIn) workDescIn.value = 'Планове регламентне ТО (сервісна служба)';

  const consIn = document.getElementById('adminResetConsumables');
  if (consIn) consIn.value = '';

  const costIn = document.getElementById('adminResetCost');
  if (costIn) costIn.value = '0.00';

  const commIn = document.getElementById('adminResetComment');
  if (commIn) commIn.value = '';

  openModal('modalAdminResetMaint');
};

window.submitAdminResetMaint = async function(e) {
  if (e) e.preventDefault();
  const btn = document.getElementById('btnSubmitAdminResetMaint');
  const opHours = parseFloat(document.getElementById('adminResetOperatingHours')?.value);
  if (isNaN(opHours) || opHours < 0) {
    showToast('Вкажіть коректні мотогодини виконання ТО', 'error');
    return;
  }

  const body = {
    generator_id: currentGeneratorId,
    maintenance_type: 'SCHEDULED',
    operating_hours: opHours,
    work_description: document.getElementById('adminResetWorkDesc')?.value || 'Планове регламентне ТО (сервісна служба)',
    consumables_used: document.getElementById('adminResetConsumables')?.value || '',
    cost: parseFloat(document.getElementById('adminResetCost')?.value) || 0.0,
    comment: document.getElementById('adminResetComment')?.value || ''
  };

  if (btn) {
    btn.disabled = true;
    btn.innerText = 'Скидання лічильника...';
  }

  try {
    const res = await api('/maintenance/record', {
      method: 'POST',
      body: JSON.stringify(body),
      offlineMeta: {
        action_type: 'maint_record',
        title: 'Регламентне ТО (скидання лічильника)',
        summary: `ТО на ${opHours.toFixed(1)} год: ${body.work_description}`,
        facility_id: currentFacilityId,
        generator_id: currentGeneratorId,
      }
    });
    closeModal('modalAdminResetMaint');
    showToast(res?._queuedOffline ? '📥 Скидання/ТО збережено в офлайн-чергу' : `Лічильник ТО успішно скинуто! Зафіксовано ТО на ${opHours.toFixed(1).replace('.', ',')} год`, res?._queuedOffline ? 'warning' : 'success');
    await loadMaintenanceData();
    await loadAllData();
  } catch (err) {
    showToast('Помилка скидання лічильника: ' + (err.message || 'Невідома помилка'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = 'Скинути лічильник та зафіксувати ТО';
    }
  }
};

// 4. Faults
async function loadFaultsData() {
  try {
    const qGen = currentGeneratorId ? `?generator_id=${encodeURIComponent(currentGeneratorId)}` : '';
    const faults = await api(`/faults${qGen}`);
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
    window.renderPaginatedTable('faultsTable', faults, (f) => {
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
    }, 8, 'Несправностей немає', 10);
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
    const res = await api('/faults', {
      method: 'POST',
      body: JSON.stringify(body),
      offlineMeta: {
        action_type: 'fault_create',
        title: 'Реєстрація несправності',
        summary: `${body.title} (${body.priority})`,
        facility_id: currentFacilityId,
        generator_id: currentGeneratorId,
      }
    });
    closeModal('modalFault');
    showToast(res?._queuedOffline ? '📥 Заявку про несправність збережено в офлайн-чергу' : 'Заявку про несправність створено!', res?._queuedOffline ? 'warning' : 'success');
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
    const runs = await api('/generator/runs?limit=200' + q);
    window.renderPaginatedTable('allRunsTable', runs, (r) => {
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
    }, 10, 'Записів не знайдено', 10);
  } catch (_) {}
}

