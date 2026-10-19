// Service Desk Бензинового Генератора - Frontend Application Logic

let token = localStorage.getItem('sd_token') || sessionStorage.getItem('sd_token');
let currentUser = null;
let currentFacilityId = null;
let currentGeneratorId = null;
let currentGenerator = null;
let activeRun = null;

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
  const modal = document.getElementById(id);
  if (modal) modal.style.display = 'flex';
  if (id === 'modalReceipt') setupReceiptModal();
  if (id === 'modalTransfer') setupTransferModal();
  if (id === 'modalNewStock') setupNewStockModal();
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
    document.getElementById('userGreeting').innerText = `${currentUser.full_name} (${currentUser.roles.join(', ') || 'користувач'})`;
    hideAuthScreen();
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
    document.getElementById('userGreeting').innerText = `${currentUser.full_name}`;
    hideAuthScreen();
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
  await loadFuelSummary();
  await loadMaintenanceSummary();
  await loadRecentRuns();
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
        body: JSON.stringify({ generator_id: currentGeneratorId, fuel_level_l: currentGenerator.fuel_tank_level_l })
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
async function setupReceiptModal() {
  try {
    const facilities = await api('/facilities');
    const facSel = document.getElementById('recFacility');
    if (facSel && facilities && facilities.length > 0) {
      facSel.innerHTML = facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
      if (currentFacilityId && facilities.some(f => f.id === currentFacilityId)) {
        facSel.value = currentFacilityId;
      }
    }
    await updateReceiptStocks();
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
        </tr>
      `).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-muted)">Складів ГСМ не знайдено</td></tr>';
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
  const body = {
    facility_id: parseInt(document.getElementById('recFacility').value),
    stock_id: parseInt(stockVal),
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
    const faults = await api('/faults');
    const tbody = document.querySelector('#faultsTable tbody');
    tbody.innerHTML = faults.map((f) => `
      <tr>
        <td>#${Number(f.id)}</td>
        <td><span class="badge ${f.priority === 'CRITICAL' ? 'badge-faulty' : 'badge-maintenance'}">${escapeHtml(f.priority)}</span></td>
        <td><span class="badge badge-stopped">${escapeHtml(f.status)}</span></td>
        <td><b>${escapeHtml(f.title)}</b></td>
        <td>${escapeHtml(f.description)}</td>
        <td>${f.operating_hours.toFixed(1)} год</td>
        <td>${formatDateOnly(f.created_at)}</td>
        <td>
          ${f.status !== 'RESOLVED' && f.status !== 'CLOSED' ? `
            <button onclick="resolveFault(${Number(f.id)})" style="background:#22c55e; border:none; color:white; border-radius:4px; padding:0.25rem 0.5rem; cursor:pointer; font-size:0.75rem;">Усунути</button>
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
    await api(`/faults/${encodeURIComponent(id)}/status`, {
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
async function loadAuditData() {
  try {
    const logs = await api('/audit?limit=50');
    const tbody = document.querySelector('#auditTable tbody');
    tbody.innerHTML = logs.map((l) => `
      <tr>
        <td>${formatDateTime(l.created_at)}</td>
        <td>${escapeHtml(l.user_name || 'Система')}</td>
        <td><b>${escapeHtml(l.action)}</b></td>
        <td>${escapeHtml(l.entity_type)} #${escapeHtml(l.entity_id || '')}</td>
        <td style="font-family:monospace; font-size:0.75rem;">${escapeHtml(l.details_json || '-')}</td>
        <td>${escapeHtml(l.ip_address || '-')}</td>
      </tr>
    `).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-muted)">Аудит порожній</td></tr>';

    const adjustments = await api('/adjustments?limit=30');
    const adjTbody = document.querySelector('#adjustmentsTable tbody');
    adjTbody.innerHTML = adjustments.map((a) => `
      <tr>
        <td>${formatDateTime(a.created_at)}</td>
        <td>${escapeHtml(a.user_name || '-')}</td>
        <td>${escapeHtml(a.entity_type)}</td>
        <td>${escapeHtml(a.field_name)}</td>
        <td><s style="color:#ef4444;">${escapeHtml(a.old_value)}</s></td>
        <td><b style="color:#22c55e;">${escapeHtml(a.new_value)}</b></td>
        <td>${escapeHtml(a.reason)}</td>
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

// 8. Admin (Users & Wizard)
async function loadUsersData() {
  try {
    const users = await api('/users');
    const tbody = document.querySelector('#usersTable tbody');
    tbody.innerHTML = users.map((u) => `
      <tr>
        <td>#${Number(u.id)}</td>
        <td><b>${escapeHtml(u.login)}</b></td>
        <td>${escapeHtml(u.full_name)}</td>
        <td>${escapeHtml(u.email || '-')}</td>
        <td><span class="badge ${u.is_active ? 'badge-running' : 'badge-faulty'}">${u.is_active ? 'Активний' : 'Заблокований'}</span></td>
        <td>${escapeHtml(u.roles.map((r) => r.name).join(', ') || '-')}</td>
        <td>
          ${!u.is_superadmin ? `
            <button onclick="toggleUserActive(${Number(u.id)}, ${!u.is_active})" style="background:none; border:1px solid var(--border-color); color:var(--text-primary); border-radius:4px; padding:0.25rem 0.5rem; cursor:pointer; font-size:0.75rem;">
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
    await api(`/users/${encodeURIComponent(id)}`, {
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

// Generator Deletion Handlers
window.openDeleteGeneratorModal = function() {
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

// Initialization on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  setupPwaInstall();
  checkAuth();
  refreshServerStatus();
  setInterval(refreshServerStatus, 30000);
});

