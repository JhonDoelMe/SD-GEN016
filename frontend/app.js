// Service Desk Бензинового Генератора - Frontend Application Logic

let token = localStorage.getItem('sd_token');
let currentUser = null;
let currentGenerator = null;
let activeRun = null;

// API Helper
async function api(endpoint, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const res = await fetch(`/api/v1${endpoint}`, { ...options, headers });
    if (res.status === 401) {
      token = null;
      localStorage.removeItem('sd_token');
      showAuthScreen();
      throw new Error('Потрібна авторизація');
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = data && data.detail ? data.detail : `Помилка сервера (${res.status})`;
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
  const modal = document.getElementById(id);
  if (modal) modal.style.display = 'flex';
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
    showAuthScreen();
    return;
  }
  try {
    currentUser = await api('/auth/me');
    document.getElementById('userGreeting').innerText = `${currentUser.full_name} (${currentUser.roles.join(', ') || 'користувач'})`;
    hideAuthScreen();
    loadAllData();
  } catch (_) {
    showAuthScreen();
  }
}

document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const loginInput = document.getElementById('loginUsername').value;
  const passInput = document.getElementById('loginPassword').value;

  try {
    const res = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ login: loginInput, password: passInput })
    });
    token = res.access_token;
    localStorage.setItem('sd_token', token);
    currentUser = res.user;
    document.getElementById('userGreeting').innerText = `${currentUser.full_name}`;
    hideAuthScreen();
    showToast(`Вітаємо, ${currentUser.full_name}!`, 'success');
    loadAllData();
  } catch (_) {}
});

document.getElementById('logoutBtn').addEventListener('click', async () => {
  try {
    await api('/auth/logout', { method: 'POST' });
  } catch (_) {}
  token = null;
  localStorage.removeItem('sd_token');
  currentUser = null;
  showAuthScreen();
});

// Tab Navigation
document.querySelectorAll('.nav-item').forEach((tab) => {
  tab.addEventListener('click', () => {
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
    if (paneId === 'tab-audit') loadAuditData();
    if (paneId === 'tab-reports') loadReport();
    if (paneId === 'tab-admin') loadUsersData();
  });
});

// Load All Dashboard Data
async function loadAllData() {
  await loadGeneratorData();
  await loadFuelSummary();
  await loadMaintenanceSummary();
  await loadRecentRuns();
}

// 1. Generator Data
async function loadGeneratorData() {
  try {
    currentGenerator = await api('/generator');
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
      badge.innerText = 'НЕИСПРАВЕН';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>⚠️</span><span>НЕСПРАВНІСТЬ (БЛОК)</span>';
    } else if (currentGenerator.status === 'BLOCKED') {
      badge.classList.add('badge-blocked');
      badge.innerText = 'ЗАБЛОКОВАНИЙ';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>🔒</span><span>ЗАБЛОКОВАНО</span>';
    } else {
      badge.classList.add('badge-stopped');
      badge.innerText = 'ОСТАНОВЛЕН';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
    }

    // Active Run Check
    activeRun = await api('/generator/active-run');
    if (activeRun) {
      banner.style.display = 'block';
      document.getElementById('activeRunStart').innerText = formatTime(activeRun.start_time);
      document.getElementById('activeRunHours').innerText = activeRun.start_hours.toFixed(1);
      startRunStopwatch();
    } else {
      banner.style.display = 'none';
      stopRunStopwatch();
    }
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
        body: JSON.stringify({ fuel_level_l: currentGenerator.fuel_tank_level_l })
      });
      showToast('Генератор успішно запущено!', 'success');
      loadAllData();
    } catch (_) {}
  }
});

// Stop Form Submit
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
      body: JSON.stringify({ end_hours: endHours, end_fuel_level_l: endFuel, note: note })
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
async function loadFuelSummary() {
  try {
    const s = await api('/fuel/summary');
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
    const receipts = await api('/fuel/receipts');
    const rTbody = document.querySelector('#fuelReceiptsTable tbody');
    rTbody.innerHTML = receipts.map((r) => `
      <tr>
        <td>${formatDateTime(r.created_at)}</td>
        <td><b>${r.liters.toFixed(1)} л</b></td>
        <td>${r.cost_total.toFixed(2)}</td>
        <td>${r.price_per_liter.toFixed(2)}</td>
        <td>${r.driver_name}</td>
        <td>${r.receipt_number}</td>
        <td>${r.user_name || '-'}</td>
      </tr>
    `).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--text-muted)">Надходжень не зареєстровано</td></tr>';

    const transfers = await api('/fuel/transfers');
    const tTbody = document.querySelector('#fuelTransfersTable tbody');
    tTbody.innerHTML = transfers.map((t) => `
      <tr>
        <td>${formatDateTime(t.created_at)}</td>
        <td><b style="color:#38bdf8;">+${t.liters.toFixed(1)} л</b></td>
        <td>${t.source_balance_before.toFixed(1)} → ${t.source_balance_after.toFixed(1)} л</td>
        <td>${t.tank_balance_before.toFixed(1)} → ${t.tank_balance_after.toFixed(1)} л</td>
        <td>${t.comment || '-'}</td>
        <td>${t.user_name || '-'}</td>
      </tr>
    `).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-muted)">Заправок не зареєстровано</td></tr>';
  } catch (_) {}
}

// Receipt Form Submit
document.getElementById('receiptForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    liters: parseFloat(document.getElementById('recLiters').value),
    cost_total: parseFloat(document.getElementById('recCostTotal').value),
    driver_name: document.getElementById('recDriver').value,
    receipt_number: document.getElementById('recNumber').value,
    fuel_type: document.getElementById('recFuelType').value,
    comment: document.getElementById('recComment').value
  };

  try {
    await api('/fuel/receipt', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalReceipt');
    showToast('Паливо успішно оприбутковано на склад ГСМ!', 'success');
    loadFuelData();
    loadFuelSummary();
  } catch (_) {}
});

// Transfer Form Submit
document.getElementById('transferForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    liters: parseFloat(document.getElementById('transLiters').value),
    comment: document.getElementById('transComment').value
  };

  try {
    await api('/fuel/transfer', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalTransfer');
    showToast('Бак генератора успішно заправлено!', 'success');
    loadAllData();
  } catch (_) {}
});

// 3. Maintenance (ТО)
async function loadMaintenanceSummary() {
  try {
    const m = await api('/maintenance/schedule');
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

async function loadMaintenanceData() {
  await loadMaintenanceSummary();
  try {
    const records = await api('/maintenance/records');
    const tbody = document.querySelector('#maintenanceHistoryTable tbody');
    tbody.innerHTML = records.map((r) => `
      <tr>
        <td>${formatDateTime(r.created_at)}</td>
        <td><span class="badge ${r.maintenance_type === 'SCHEDULED' ? 'badge-running' : 'badge-stopped'}">${r.maintenance_type === 'SCHEDULED' ? 'Регламентне' : 'Проміжне'}</span></td>
        <td><b>${r.operating_hours.toFixed(1)} год</b></td>
        <td>${r.work_description}</td>
        <td>${r.consumables_used || '-'}</td>
        <td>${r.cost.toFixed(2)} грн</td>
        <td>${r.user_name || '-'}</td>
      </tr>
    `).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--text-muted)">Записів ТО не знайдено</td></tr>';
  } catch (_) {}
}

// Maintenance Form Submit
document.getElementById('maintForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
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
    const faults = await api('/faults');
    const tbody = document.querySelector('#faultsTable tbody');
    tbody.innerHTML = faults.map((f) => `
      <tr>
        <td>#${f.id}</td>
        <td><span class="badge ${f.priority === 'CRITICAL' ? 'badge-faulty' : 'badge-maintenance'}">${f.priority}</span></td>
        <td><span class="badge badge-stopped">${f.status}</span></td>
        <td><b>${f.title}</b></td>
        <td>${f.description}</td>
        <td>${f.operating_hours.toFixed(1)} год</td>
        <td>${formatDateOnly(f.created_at)}</td>
        <td>
          ${f.status !== 'RESOLVED' && f.status !== 'CLOSED' ? `
            <button onclick="resolveFault(${f.id})" style="background:#22c55e; border:none; color:white; border-radius:4px; padding:0.25rem 0.5rem; cursor:pointer; font-size:0.75rem;">Усунути</button>
          ` : '<span style="color:#22c55e;">Усунено</span>'}
        </td>
      </tr>
    `).join('') || '<tr><td colspan="8" style="text-align:center; color:var(--text-muted)">Несправностей немає</td></tr>';
  } catch (_) {}
}

window.resolveFault = async function(id) {
  const notes = prompt('Вкажіть примітки щодо усунення несправності:');
  if (notes === null) return;
  try {
    await api(`/faults/${id}/status`, {
      method: 'PUT',
      body: JSON.stringify({ status: 'RESOLVED', resolution_notes: notes })
    });
    showToast('Несправність позначено як усунену!', 'success');
    loadFaultsData();
    loadGeneratorData();
  } catch (_) {}
};

document.getElementById('faultForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
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
  } catch (_) {}
});

// 5. Runs History
async function loadRecentRuns() {
  try {
    const runs = await api('/generator/runs?limit=5');
    const tbody = document.querySelector('#recentRunsTable tbody');
    tbody.innerHTML = runs.map((r) => {
      const durText = r.duration_formatted || (r.duration_seconds != null ? formatDuration(r.duration_seconds) : (r.duration_hours ? r.duration_hours.toFixed(2) + ' год' : '-'));
      const consText = r.calculated_consumption_l != null ? (r.calculated_consumption_l < 0.1 && r.calculated_consumption_l > 0 ? r.calculated_consumption_l.toFixed(3) : r.calculated_consumption_l.toFixed(2)) + ' л' : '-';
      return `
        <tr>
          <td>${formatDateTime(r.start_time)}</td>
          <td>${r.start_hours.toFixed(1)} год</td>
          <td>${r.end_hours != null ? r.end_hours.toFixed(1) + ' год' : '<i>працює...</i>'}</td>
          <td><b style="color: #38bdf8; font-family: monospace;">${durText}</b></td>
          <td>${consText}</td>
          <td>${r.user_name || '-'}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-muted)">Циклів не знайдено</td></tr>';
  } catch (_) {}
}

async function loadRunsData() {
  try {
    const runs = await api('/generator/runs?limit=50');
    const tbody = document.querySelector('#allRunsTable tbody');
    tbody.innerHTML = runs.map((r) => {
      const durText = r.duration_formatted || (r.duration_seconds != null ? formatDuration(r.duration_seconds) : (r.duration_hours ? r.duration_hours.toFixed(2) + ' год' : '-'));
      const consText = r.calculated_consumption_l != null ? (r.calculated_consumption_l < 0.1 && r.calculated_consumption_l > 0 ? r.calculated_consumption_l.toFixed(3) : r.calculated_consumption_l.toFixed(2)) + ' л' : '-';
      return `
        <tr>
          <td>#${r.id}</td>
          <td>${formatDateTime(r.start_time)}</td>
          <td>${r.end_time ? formatDateTime(r.end_time) : '<i>в процесі...</i>'}</td>
          <td>${r.start_hours.toFixed(1)}</td>
          <td>${r.end_hours != null ? r.end_hours.toFixed(1) : '-'}</td>
          <td><b style="color: #38bdf8; font-family: monospace;">${durText}</b></td>
          <td>${consText}</td>
          <td>${r.start_fuel_level_l ?? '-'} → ${r.end_fuel_level_l ?? '-'} л</td>
          <td>${r.user_name || '-'}</td>
          <td>${r.note || '-'}</td>
        </tr>
      `;
    }).join('') || '<tr><td colspan="10" style="text-align:center; color:var(--text-muted)">Записів не знайдено</td></tr>';
  } catch (_) {}
}

// 6. Audit & System Adjustments
async function loadAuditData() {
  try {
    const logs = await api('/audit?limit=50');
    const tbody = document.querySelector('#auditTable tbody');
    tbody.innerHTML = logs.map((l) => `
      <tr>
        <td>${formatDateTime(l.created_at)}</td>
        <td>${l.user_name || 'Система'}</td>
        <td><b>${l.action}</b></td>
        <td>${l.entity_type} #${l.entity_id || ''}</td>
        <td style="font-family:monospace; font-size:0.75rem;">${l.details_json || '-'}</td>
        <td>${l.ip_address || '-'}</td>
      </tr>
    `).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-muted)">Аудит порожній</td></tr>';

    const adjustments = await api('/adjustments?limit=30');
    const adjTbody = document.querySelector('#adjustmentsTable tbody');
    adjTbody.innerHTML = adjustments.map((a) => `
      <tr>
        <td>${formatDateTime(a.created_at)}</td>
        <td>${a.user_name || '-'}</td>
        <td>${a.entity_type}</td>
        <td>${a.field_name}</td>
        <td><s style="color:#ef4444;">${a.old_value}</s></td>
        <td><b style="color:#22c55e;">${a.new_value}</b></td>
        <td>${a.reason}</td>
      </tr>
    `).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--text-muted)">Коригувань не виконувалось</td></tr>';
  } catch (_) {}
}

window.updateAdjFields = function() {
  const entity = document.getElementById('adjEntity').value;
  const fieldSelect = document.getElementById('adjField');
  fieldSelect.innerHTML = '';
  if (entity === 'Generator') {
    fieldSelect.innerHTML = `
      <option value="current_operating_hours">Мотогодини (current_operating_hours)</option>
      <option value="fuel_tank_level_l">Рівень у баку (fuel_tank_level_l)</option>
      <option value="status">Статус (STOPPED/RUNNING/MAINTENANCE_REQUIRED/FAULTY/BLOCKED)</option>
      <option value="nominal_consumption_l_per_h">Нормативний розхід (nominal_consumption_l_per_h)</option>
    `;
  } else if (entity === 'FuelStock') {
    fieldSelect.innerHTML = `<option value="current_balance_l">Залишок на складі (current_balance_l)</option>`;
  } else if (entity === 'MaintenanceSchedule') {
    fieldSelect.innerHTML = `
      <option value="interval_hours">Інтервал ТО (interval_hours)</option>
      <option value="next_due_hours">Наступне ТО (next_due_hours)</option>
      <option value="last_performed_hours">Останнє ТО (last_performed_hours)</option>
    `;
  }
};

document.getElementById('adjustmentForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const entity = document.getElementById('adjEntity').value;
  const field = document.getElementById('adjField').value;
  const newVal = document.getElementById('adjNewValue').value;
  const reason = document.getElementById('adjReason').value;

  const entityId = currentGenerator ? currentGenerator.id : 1;

  try {
    await api('/adjustments', {
      method: 'POST',
      body: JSON.stringify({
        entity_type: entity,
        entity_id: entityId,
        field_name: field,
        new_value: newVal,
        reason: reason
      })
    });
    closeModal('modalAdjustment');
    showToast('Системне коригування успішно виконано та внесено в аудит!', 'success');
    loadAuditData();
    loadAllData();
  } catch (_) {}
});

// 7. Reports
async function loadReport() {
  const startInput = document.getElementById('repStartDate').value;
  const endInput = document.getElementById('repEndDate').value;

  let query = '';
  if (startInput) query += `&start_date=${startInput}`;
  if (endInput) query += `&end_date=${endInput}`;

  try {
    const r = await api(`/reports/summary?${query.slice(1)}`);
    const container = document.getElementById('reportContainer');
    container.innerHTML = `
      <div class="metric-card">
        <div class="metric-label">Відпрацьовано мотогодин</div>
        <div class="metric-value">${r.total_operating_hours} год</div>
        <div class="metric-sub">${r.total_runs_count} пусків</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Розрахунковий розхід палива</div>
        <div class="metric-value">${r.total_calculated_consumption_l} л</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Оприбутковано на склад</div>
        <div class="metric-value">${r.total_fuel_received_l} л</div>
        <div class="metric-sub">${r.total_fuel_receipts_cost_uah} грн (${r.avg_fuel_price_per_liter} грн/л)</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Заправлено в бак</div>
        <div class="metric-value">${r.total_fuel_transferred_to_tank_l} л</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Виконано ТО</div>
        <div class="metric-value">${r.total_maintenance_count}</div>
        <div class="metric-sub">Регламентних: ${r.scheduled_maintenance_count} | Проміжних: ${r.intermediate_maintenance_count}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Витрати на ТО</div>
        <div class="metric-value">${r.total_maintenance_cost_uah} грн</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Несправності</div>
        <div class="metric-value">${r.total_faults_count}</div>
        <div class="metric-sub">Усунено: ${r.resolved_faults_count} | Відкрито: ${r.open_faults_count}</div>
      </div>
    `;
  } catch (_) {}
}

window.downloadReportCSV = function () {
  const startInput = document.getElementById('repStartDate').value;
  const endInput = document.getElementById('repEndDate').value;
  let url = '/api/v1/reports/export';
  const params = [];
  if (startInput) params.push(`start_date=${startInput}`);
  if (endInput) params.push(`end_date=${endInput}`);
  if (params.length) url += `?${params.join('&')}`;

  // Fetch with auth header and trigger download
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then((res) => res.blob())
    .then((blob) => {
      const a = document.createElement('a');
      a.href = window.URL.createObjectURL(blob);
      a.download = `generator_report_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
    })
    .catch(() => showToast('Помилка завантаження звіту', 'error'));
};

// 8. Admin (Users & Wizard)
async function loadUsersData() {
  try {
    const users = await api('/users');
    const tbody = document.querySelector('#usersTable tbody');
    tbody.innerHTML = users.map((u) => `
      <tr>
        <td>#${u.id}</td>
        <td><b>${u.login}</b></td>
        <td>${u.full_name}</td>
        <td>${u.email || '-'}</td>
        <td><span class="badge ${u.is_active ? 'badge-running' : 'badge-faulty'}">${u.is_active ? 'Активний' : 'Заблокований'}</span></td>
        <td>${u.roles.map((r) => r.name).join(', ') || '-'}</td>
        <td>
          ${!u.is_superadmin ? `
            <button onclick="toggleUserActive(${u.id}, ${!u.is_active})" style="background:none; border:1px solid var(--border-color); color:var(--text-primary); border-radius:4px; padding:0.25rem 0.5rem; cursor:pointer; font-size:0.75rem;">
              ${u.is_active ? 'Блокувати' : 'Розблокувати'}
            </button>
          ` : '<small style="color:#a855f7;">SuperAdmin</small>'}
        </td>
      </tr>
    `).join('');
  } catch (_) {}
}

window.toggleUserActive = async function(id, active) {
  try {
    await api(`/users/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ is_active: active })
    });
    showToast(`Статус користувача змінено на: ${active ? 'Активний' : 'Заблокований'}`, 'success');
    loadUsersData();
  } catch (_) {}
};

// User Create Form Submit
document.getElementById('userCreateForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    login: document.getElementById('newLogin').value,
    full_name: document.getElementById('newName').value,
    email: document.getElementById('newEmail').value || null,
    password: document.getElementById('newPassword').value,
    role_ids: [parseInt(document.getElementById('newUserRole').value)]
  };

  try {
    await api('/users', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalUserCreate');
    showToast('Користувача успішно створено!', 'success');
    loadUsersData();
  } catch (_) {}
});

// Generator Wizard Setup Submit
document.getElementById('wizardForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = {
    name: document.getElementById('wizName').value,
    model: document.getElementById('wizModel').value,
    manufacturer: document.getElementById('wizManufacturer').value,
    serial_number: document.getElementById('wizSerial').value,
    rated_power_kw: parseFloat(document.getElementById('wizPower').value),
    tank_capacity_l: parseFloat(document.getElementById('wizTankCap').value),
    nominal_consumption_l_per_h: parseFloat(document.getElementById('wizConsumption').value),
    initial_operating_hours: parseFloat(document.getElementById('wizInitHours').value),
    initial_fuel_tank_level_l: parseFloat(document.getElementById('wizInitFuel').value),
    maintenance_interval_hours: parseFloat(document.getElementById('wizMaintInterval').value),
    last_maintenance_performed_hours: document.getElementById('wizLastMaintHours').value ? parseFloat(document.getElementById('wizLastMaintHours').value) : null,
    work_schedule_start: document.getElementById('wizSchedStart').value,
    work_schedule_end: document.getElementById('wizSchedEnd').value,
    fuel_type: 'А-95',
    timezone: 'Europe/Kyiv'
  };

  try {
    await api('/generator/wizard', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalWizard');
    showToast('Параметри генератора успішно налаштовані через майстер!', 'success');
    loadAllData();
  } catch (_) {}
});

// Initialization on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  checkAuth();
});
