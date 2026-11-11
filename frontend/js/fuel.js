// 2. Fuel Management
let cachedFuelPrices = null;

async function fetchFuelPricesCache() {
  try {
    cachedFuelPrices = await api('/system/fuel-prices');
  } catch (_) {}
  return cachedFuelPrices;
}

let cachedReceiptFacilities = [];

window.onReceiptFuelProviderChange = function () {
  const provider = (document.getElementById('recFuelProvider')?.value || 'wog').toLowerCase();
  const typeSel = document.getElementById('recFuelType');
  if (!typeSel) return;
  const curVal = typeSel.value;

  if (provider === 'okko') {
    typeSel.innerHTML = `
      <option value="А-95" selected>А-95 (OKKO А-95 Євро)</option>
      <option value="А-95 Pulls">А-95 Pulls (OKKO Pulls 95)</option>
      <option value="ДП">ДП (OKKO ДП Євро)</option>
      <option value="ДП Pulls">ДП Pulls (OKKO Pulls Дизель)</option>
      <option value="А-100 Pulls">А-100 Pulls (OKKO Pulls 100)</option>
      <option value="ГАЗ">ГАЗ (OKKO СПБТ)</option>
      <option value="А-92">А-92</option>
    `;
  } else if (provider === 'other') {
    typeSel.innerHTML = `
      <option value="А-95" selected>А-95</option>
      <option value="ДП">ДП</option>
      <option value="А-92">А-92</option>
      <option value="ГАЗ">ГАЗ</option>
    `;
  } else {
    // WOG
    typeSel.innerHTML = `
      <option value="А-95" selected>А-95 (WOG 95 Євро5-Е10)</option>
      <option value="А-95 Mustang">А-95 Mustang (WOG 95 Mustang)</option>
      <option value="ДП">ДП (WOG ДП Євро5)</option>
      <option value="ДП Mustang+">ДП Mustang+ (WOG ДП Mustang+)</option>
      <option value="ГАЗ">ГАЗ (WOG LPG)</option>
      <option value="А-92">А-92</option>
    `;
  }
  if ([...typeSel.options].some((o) => o.value === curVal)) {
    typeSel.value = curVal;
  }
  updateReceiptPriceEstimate();
};

window.updateReceiptPriceEstimate = function () {
  const hintEl = document.getElementById('recAutoPriceHint');
  if (!hintEl) return;
  const provider = (document.getElementById('recFuelProvider')?.value || 'wog').toLowerCase();
  const fuelType = document.getElementById('recFuelType')?.value || 'А-95';
  const litersVal = parseFloat(document.getElementById('recLiters')?.value || '0');
  const rawCost = document.getElementById('recCostTotal')?.value?.trim() || '';
  const costVal = rawCost ? parseFloat(rawCost) : 0;

  const isOkko = provider === 'okko';
  const fallbacks = isOkko ? {
    'А-95': 92.90,
    'А-95 Pulls': 95.90,
    'А-100 Pulls': 102.90,
    'ДП': 106.90,
    'ДП Pulls': 109.90,
    'ГАЗ': 59.90,
    'А-92': 92.90
  } : {
    'А-95': 92.90,
    'А-95 Mustang': 95.90,
    'А-100 Mustang': 102.90,
    'ДП': 103.50,
    'ДП Mustang+': 106.50,
    'ГАЗ': 52.50,
    'А-92': 89.90
  };

  const fuelsMap = isOkko ? cachedFuelPrices?.okko_fuels : cachedFuelPrices?.fuels;
  const fuelEntry = fuelsMap?.[fuelType] || cachedFuelPrices?.fuels?.[fuelType];
  const unitPrice = fuelEntry ? Number(fuelEntry.effective_price) : (fallbacks[fuelType] || 92.90);
  const defaultSrc = isOkko ? 'АЗК OKKO (okko.ua/fuels)' : 'АЗК WOG (wog.ua/ua/fuels/)';
  const srcName = fuelEntry ? fuelEntry.source_name : defaultSrc;

  if (costVal > 0 && litersVal > 0) {
    const manualPerL = (costVal / litersVal).toFixed(2);
    hintEl.innerHTML = `✅ Сума вказана за чеком: <b style="color:#4ade80;">${costVal.toFixed(2)} грн</b> (виходить <b>${manualPerL} грн/л</b>)`;
  } else if (litersVal > 0) {
    const autoSum = (litersVal * unitPrice).toFixed(2);
    hintEl.innerHTML = `💡 Авторозрахунок <b>${escapeHtml(fuelType)}</b> (${isOkko ? 'АЗК OKKO' : 'АЗК WOG'}): <b>${unitPrice.toFixed(2)} грн/л</b> <span style="color:var(--text-muted);">(${escapeHtml(srcName)})</span> → буде нараховано: <b style="color:#4ade80;">${autoSum} грн</b>`;
  } else {
    hintEl.innerHTML = `💡 Діюча ціна <b>${escapeHtml(fuelType)}</b> (${isOkko ? 'АЗК OKKO' : 'АЗК WOG'}): <b>${unitPrice.toFixed(2)} грн/л</b> <span style="color:var(--text-muted);">(${escapeHtml(srcName)})</span>. Введіть літри для авторозрахунку суми.`;
  }
};

async function setupReceiptModal() {
  try {
    const [facilities] = await Promise.all([
      api('/facilities'),
      fetchFuelPricesCache()
    ]);
    cachedReceiptFacilities = facilities || [];
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
  const provSel = document.getElementById('recFuelProvider');
  if (!facSel || !stockSel) return;
  const facId = parseInt(facSel.value, 10);

  if (provSel && cachedReceiptFacilities && cachedReceiptFacilities.length > 0) {
    const fac = cachedReceiptFacilities.find(f => Number(f.id) === facId);
    if (fac && fac.default_fuel_provider) {
      provSel.value = fac.default_fuel_provider.toLowerCase();
      onReceiptFuelProviderChange();
    }
  }
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

    const [stocks, gens, pools] = await Promise.all([
      api(`/fuel/stocks${qFac}`),
      api(`/generator/list${qFac}`),
      api(`/fuel/canisters${qFac}`).catch(() => []),
    ]);
    window._cachedCanisterPools = Array.isArray(pools) ? pools : [];
    if (stockSel) {
      if (!stocks || stocks.length === 0) {
        stockSel.innerHTML = '<option value="">(Немає доступних складів)</option>';
      } else {
        stockSel.innerHTML = stocks.map(s => `<option value="${Number(s.id)}">${escapeHtml(s.name)} (${s.current_balance_l.toFixed(1)} л, ${escapeHtml(s.fuel_type || 'А-95')})</option>`).join('');
      }
    }

    window._transferModalStocks = stocks || [];
    window._transferModalGens = gens || [];
    if (genSel) {
      if (!gens || gens.length === 0) {
        genSel.innerHTML = '<option value="">(Немає генераторів)</option>';
      } else {
        genSel.innerHTML = gens.map(g => { const cap = Number(g.tank_capacity_l || 25.0); const cur = Number(g.fuel_tank_level_l || 0); const free = Math.max(0, cap - cur); return `<option value="${Number(g.id)}">${escapeHtml(g.name)} (${escapeHtml(g.model)}, в баку: ${cur.toFixed(1)} / ${cap.toFixed(1)} л • вільно: ${free.toFixed(1)} л)</option>`; }).join('');
        if (currentGeneratorId && gens.some(g => g.id === currentGeneratorId)) genSel.value = currentGeneratorId;
        if (typeof window.updateTransferCapacityHint === 'function') window.updateTransferCapacityHint();
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
    window._lastFuelSummary = s;
    document.getElementById('cardStock').innerText = s.warehouse_balance_l.toFixed(1).replace('.', ',');
    const stockSub = document.getElementById('cardStockSub');
    if (stockSub) {
      stockSub.innerText = Number(s.canisters_total || 0) > 0
        ? `${Number(s.canisters_full)}/${Number(s.canisters_total)} повн. каністр`
        : 'залишок палива';
    }
    document.getElementById('fuelStockBal').innerText = formatLiters(s.warehouse_balance_l);
    document.getElementById('fuelTankBal').innerText = formatLiters(s.tank_balance_l);
    document.getElementById('fuelTotalBought').innerText = formatLiters(s.total_received_l);
    document.getElementById('fuelTotalSpent').innerText = formatMoney(s.total_spent_uah);
    document.getElementById('fuelAvgPrice').innerText = formatPricePerLiter(s.avg_price_per_liter);
    if (typeof window.updateFuelAssessmentBlock === 'function') {
      window.updateFuelAssessmentBlock();
    }
  } catch (_) {}
}

window._cachedCanisterPools = [];

const CANISTER_OP_UA = {
  'POOL_CREATED': { label: 'Створено пул', color: '#38bdf8' },
  'POOL_CONFIGURED': { label: 'Коригування пулу', color: '#a78bfa' },
  'DISPATCH_REFILL': { label: 'Віддано на АЗС', color: '#fbbf24' },
  'RECEIVE_REFILL': { label: 'Привезено з АЗС', color: '#4ade80' },
  'RETURN_EMPTY': { label: 'Повернуто пусті', color: '#94a3b8' },
  'CONSUME_TRANSFER': { label: 'Заправка бака', color: '#60a5fa' },
  'DIRECT_RECEIPT': { label: 'Пряме оприбутк.', color: '#4ade80' }
};

async function loadFuelData() {
  try {
    const qFac = currentFacilityId ? `?facility_id=${encodeURIComponent(currentFacilityId)}` : '';
    const [, stocks, receipts, transfers, pools, canisterTxs] = await Promise.all([
      loadFuelSummary(),
      api(`/fuel/stocks${qFac}`),
      api(`/fuel/receipts${qFac}`),
      api(`/fuel/transfers${qFac}`),
      api(`/fuel/canisters${qFac}`).catch(() => []),
      api(`/fuel/canisters/transactions${qFac}`).catch(() => [])
    ]);

    window._cachedCanisterPools = Array.isArray(pools) ? pools : [];
    renderCanisterPoolsSection(window._cachedCanisterPools, Array.isArray(canisterTxs) ? canisterTxs : []);

    // Stocks Table
    const sTbody = document.querySelector('#fuelStocksTable tbody');
    if (sTbody) {
      sTbody.innerHTML = stocks.map((s) => {
        const canisterSub = s.has_canister_pools
          ? `<div style="font-size: 0.74rem; color: var(--text-muted); margin-top: 2px;">🛢️ Повних: ${Number(s.canisters_full)}/${Number(s.canisters_total)} • Порожніх: ${Number(s.canisters_empty)} • АЗС: ${Number(s.canisters_away)} • Резерв: ${Number(s.canister_reserve_l || 0).toFixed(1)} л</div>`
          : '';
        return `
        <tr>
          <td>#${Number(s.id)}</td>
          <td><b>${escapeHtml(s.name)}</b>${canisterSub}</td>
          <td>${escapeHtml(s.facility_name || '-')}</td>
          <td><span class="badge badge-stopped">${escapeHtml(s.fuel_type)}</span></td>
          <td><b style="color:#38bdf8;">${formatLiters(s.current_balance_l)}</b></td>
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
      `;
      }).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--text-muted)">Складів ГСМ не знайдено</td></tr>';
    }

    // Receipts Table (Paginated: 10 per page)
    window.renderPaginatedTable('fuelReceiptsTable', receipts, (r) => {
      const isOkko = (r.fuel_provider || 'wog').toLowerCase() === 'okko';
      const provBadge = isOkko
        ? '<span class="badge" style="background: rgba(234, 179, 8, 0.2); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.4);">OKKO</span>'
        : '<span class="badge" style="background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4);">WOG</span>';
      return `
        <tr>
          <td>${formatDateTime(r.created_at)}</td>
          <td>${escapeHtml(r.facility_name || '-')}</td>
          <td><b>${escapeHtml(r.stock_name || '-')}</b></td>
          <td>${provBadge}</td>
          <td><b>${formatLiters(r.liters)}</b></td>
          <td>${formatMoney(r.cost_total)}</td>
          <td>${formatPricePerLiter(r.price_per_liter)}</td>
          <td>${escapeHtml(r.driver_name)}</td>
          <td>${escapeHtml(r.receipt_number)}</td>
          <td>${escapeHtml(r.user_name || '-')}</td>
        </tr>
      `;
    }, 10, 'Надходжень не зареєстровано', 10);

    // Transfers Table (Paginated: 10 per page)
    window.renderPaginatedTable('fuelTransfersTable', transfers, (t) => {
      let canNote = '';
      if (t.used_from_reserve_l !== null && t.used_from_reserve_l !== undefined) {
        const resPart = Number(t.used_from_reserve_l) > 0 ? `резерв ${Number(t.used_from_reserve_l).toFixed(1)} л` : '';
        const canPart = Number(t.opened_canisters_count) > 0 ? `${Number(t.opened_canisters_count)} кан.` : '';
        const joined = [resPart, canPart].filter(Boolean).join(' + ');
        if (joined) {
          canNote = `<div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">🛢️ ${joined} (зал. рез. ${Number(t.canister_reserve_after_l || 0).toFixed(1)} л)</div>`;
        }
      }
      return `
      <tr>
        <td>${formatDateTime(t.created_at)}</td>
        <td>${escapeHtml(t.stock_name || '-')}</td>
        <td><b>${escapeHtml(t.generator_name || '-')}</b></td>
        <td><b style="color:#38bdf8;">+${formatLiters(t.liters)}</b>${canNote}</td>
        <td>${formatLiters(t.source_balance_before)} → ${formatLiters(t.source_balance_after)}</td>
        <td>${formatLiters(t.tank_balance_before)} → ${formatLiters(t.tank_balance_after)}</td>
        <td>${escapeHtml(t.comment || '-')}</td>
        <td>${escapeHtml(t.user_name || '-')}</td>
      </tr>
    `;
    }, 8, 'Заправок не зареєстровано', 10);
  } catch (_) {}
}

// Receipt Form Submit with Volume and Price Safeguards
document.getElementById('receiptForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  if (submitBtn && submitBtn.disabled) return;

  const stockVal = document.getElementById('recStock').value;
  if (!stockVal) {
    showToast('Будь ласка, оберіть склад ГСМ або створіть його', 'error');
    return;
  }
  const rawCost = document.getElementById('recCostTotal').value.trim();
  const parsedCost = rawCost ? parseFloat(rawCost) : null;
  const liters = parseFloat(document.getElementById('recLiters').value);

  let forceConfirm = false;

  // Safeguard: Fuel Volume & Price Sanity Check
  if (liters > 1000.0) {
    const confirmed = confirm(
      `⚠️ Запобіжник об'єму палива!\n\n` +
      `Вказано ${liters.toFixed(1)} л палива (більше 1000 л).\n` +
      `Перевірте, чи немає опечатки в кількості літрів.\n\nПродовжити збереження?`
    );
    if (!confirmed) return;
    forceConfirm = true;
  }

  if (parsedCost && parsedCost > 0 && liters > 0) {
    const pricePerL = parsedCost / liters;
    if (pricePerL < 15.0 || pricePerL > 250.0) {
      const confirmed = confirm(
        `⚠️ Запобіжник вартості палива!\n\n` +
        `Розрахункова ціна становить ${pricePerL.toFixed(2)} грн/л (незвичний діапазон).\n` +
        `Перевірте загальну суму чека (${parsedCost.toFixed(2)} грн) та літри (${liters.toFixed(1)} л).\n\n` +
        `Зберегти чек з цією сумою?`
      );
      if (!confirmed) return;
      forceConfirm = true;
    }
  }

  const body = {
    facility_id: parseInt(document.getElementById('recFacility').value),
    stock_id: parseInt(stockVal),
    fuel_provider: document.getElementById('recFuelProvider')?.value || 'wog',
    liters: liters,
    cost_total: parsedCost && parsedCost > 0 ? parsedCost : null,
    driver_name: document.getElementById('recDriver').value,
    receipt_number: document.getElementById('recNumber').value,
    fuel_type: document.getElementById('recFuelType').value,
    comment: document.getElementById('recComment').value,
    force_confirm: forceConfirm
  };

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Збереження...';
  }

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
  } catch (err) {
    showToast(err.message || 'Помилка оприбуткування палива', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = 'Зберегти надходження';
    }
  }
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
  const sel = document.getElementById('editStockFuelType');
  let val = fuelType || 'А-95';
  if (sel) {
    if (![...sel.options].some(o => o.value === val)) {
      const lower = String(val).toLowerCase();
      if (lower.includes('дизель') || lower.includes('дп') || lower.includes('diesel')) val = 'ДП';
      else if (lower.includes('92')) val = 'А-92';
      else if (lower.includes('газ') || lower.includes('lpg')) val = 'ГАЗ';
      else val = 'А-95';
    }
    sel.value = val;
  }
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
    msg += `\r\n\r\nУвага: на складі є залишок ${balance.toFixed(1)} л. Його буде автоматично перенесено на основний склад об'єкта, щоб уникнути втрати даних обліку.`;
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
    if (typeof window.checkTransferClientBounds === 'function' && !window.checkTransferClientBounds()) return;
    const savedTr = await api('/fuel/transfer', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalTransfer');
    let toastMsg = `Бак генератора заправлено (+${Number(savedTr.liters || body.liters).toFixed(1)} л)!`;
    if (savedTr.used_from_reserve_l !== null && savedTr.used_from_reserve_l !== undefined) {
      const parts = [];
      if (Number(savedTr.used_from_reserve_l) > 0) parts.push(`${Number(savedTr.used_from_reserve_l).toFixed(1)} л з резерву`);
      if (Number(savedTr.opened_canisters_count) > 0) parts.push(`${Number(savedTr.opened_canisters_count)} каністр`);
      if (parts.length > 0) toastMsg += ` (${parts.join(' + ')}, у резерві: ${Number(savedTr.canister_reserve_after_l || 0).toFixed(1)} л)`;
    }
    showToast(toastMsg, 'success');
    loadAllData();
    loadFuelData();
  } catch (_) {}
});


window._getSelectedTransferEntities = function() {
  const stockSel = document.getElementById('transStock');
  const genSel = document.getElementById('transGenerator');
  const stockId = stockSel ? parseInt(stockSel.value, 10) : NaN;
  const genId = genSel ? parseInt(genSel.value, 10) : NaN;
  const stocks = Array.isArray(window._transferModalStocks) ? window._transferModalStocks : [];
  const gens = Array.isArray(window._transferModalGens) ? window._transferModalGens : [];
  const stock = stocks.find(s => Number(s.id) === stockId) || null;
  const gen = gens.find(g => Number(g.id) === genId) || null;
  return { stock, gen };
};

window.updateTransferCapacityHint = function() {
  const { stock, gen } = window._getSelectedTransferEntities();
  const inputEl = document.getElementById('transLiters');
  const hintEl = document.getElementById('transCapacityHint');
  const fillBtn = document.getElementById('btnTransFillTank');
  const submitBtn = document.querySelector('#transferForm button[type="submit"]');
  if (!inputEl || !hintEl) return;

  if (!gen) {
    hintEl.innerHTML = '';
    if (fillBtn) fillBtn.style.display = 'none';
    if (submitBtn) submitBtn.disabled = false;
    return;
  }

  const cap = Number(gen.tank_capacity_l || 25.0);
  const inTank = Number(gen.fuel_tank_level_l || 0);
  const freeInTank = Math.max(0, Number((cap - inTank).toFixed(1)));
  const stockBal = stock ? Math.max(0, Number(Number(stock.current_balance_l || 0).toFixed(1))) : 0;
  const maxAllowed = stock ? Math.max(0, Number(Math.min(freeInTank, stockBal).toFixed(1))) : freeInTank;

  inputEl.max = String(maxAllowed > 0 ? maxAllowed : 0);
  inputEl.placeholder = maxAllowed > 0 ? `макс. ${maxAllowed.toFixed(1)} л` : 'бак повний (0.0 л)';

  if (fillBtn) {
    if (maxAllowed > 0) {
      fillBtn.style.display = 'inline-block';
      fillBtn.innerText = `⚡ До повного (+${maxAllowed.toFixed(1)} л)`;
    } else {
      fillBtn.style.display = 'none';
    }
  }

  window.validateTransferLitersInput();
};

window.fillTransferTankMax = function() {
  const { stock, gen } = window._getSelectedTransferEntities();
  const inputEl = document.getElementById('transLiters');
  if (!gen || !inputEl) return;
  const cap = Number(gen.tank_capacity_l || 25.0);
  const inTank = Number(gen.fuel_tank_level_l || 0);
  const freeInTank = Math.max(0, Number((cap - inTank).toFixed(1)));
  const stockBal = stock ? Math.max(0, Number(Number(stock.current_balance_l || 0).toFixed(1))) : freeInTank;
  const maxAllowed = Math.max(0, Number(Math.min(freeInTank, stockBal).toFixed(1)));
  if (maxAllowed > 0) {
    inputEl.value = maxAllowed.toFixed(1);
    window.validateTransferLitersInput();
  }
};

window.validateTransferLitersInput = function() {
  const { stock, gen } = window._getSelectedTransferEntities();
  const inputEl = document.getElementById('transLiters');
  const hintEl = document.getElementById('transCapacityHint');
  const submitBtn = document.querySelector('#transferForm button[type="submit"]');
  if (!inputEl || !hintEl || !gen) return true;

  const cap = Number(gen.tank_capacity_l || 25.0);
  const inTank = Number(gen.fuel_tank_level_l || 0);
  const freeInTank = Math.max(0, Number((cap - inTank).toFixed(1)));
  const stockBal = stock ? Math.max(0, Number(Number(stock.current_balance_l || 0).toFixed(1))) : 0;
  const maxAllowed = stock ? Math.max(0, Number(Math.min(freeInTank, stockBal).toFixed(1))) : freeInTank;
  const rawVal = inputEl.value.trim();
  const val = rawVal !== '' ? parseFloat(rawVal) : null;

  if (freeInTank <= 0) {
    hintEl.innerHTML = `<span style="color: #ef4444; font-weight: 600;">⛔ Бак генератора вже повний (${inTank.toFixed(1)} з ${cap.toFixed(1)} л). Заправка неможлива.</span>`;
    if (submitBtn) submitBtn.disabled = true;
    return false;
  }

  if (stock && stockBal <= 0) {
    hintEl.innerHTML = `<span style="color: #ef4444; font-weight: 600;">⛔ На обраному складі ГСМ немає палива (0.0 л).</span>`;
    if (submitBtn) submitBtn.disabled = true;
    return false;
  }

  if (val !== null && !Number.isNaN(val)) {
    if (val > freeInTank + 0.001) {
      hintEl.innerHTML = `<span style="color: #ef4444; font-weight: 600;">⚠️ Перевищення ємності бака! Місткість: ${cap.toFixed(1)} л, в баку: ${inTank.toFixed(1)} л. Влізе максимум: <b>${freeInTank.toFixed(1)} л</b>.</span>`;
      if (submitBtn) submitBtn.disabled = true;
      return false;
    }
    if (stock && val > stockBal + 0.001) {
      hintEl.innerHTML = `<span style="color: #ef4444; font-weight: 600;">⚠️ На складі недостатньо палива! Доступно на складі: <b>${stockBal.toFixed(1)} л</b>.</span>`;
      if (submitBtn) submitBtn.disabled = true;
      return false;
    }
  }

  if (submitBtn) submitBtn.disabled = false;
  const afterTank = (val !== null && !Number.isNaN(val) && val > 0) ? Math.min(cap, inTank + val) : null;
  const afterText = afterTank !== null ? ` • Після заправки буде: <b style="color: #4ade80;">${afterTank.toFixed(1)} / ${cap.toFixed(1)} л</b>` : '';
  hintEl.innerHTML = `Місткість бака: <b>${cap.toFixed(1)} л</b> • Зараз у баку: <b>${inTank.toFixed(1)} л</b> • Вільно в баку: <b style="color: var(--accent-cyan);">${freeInTank.toFixed(1)} л</b> (макс. до заправки: <b>${maxAllowed.toFixed(1)} л</b>)${afterText}`;

  const canHintEl = document.getElementById('transCanisterBreakdownHint');
  if (canHintEl) {
    const stockPool = stock && Array.isArray(window._cachedCanisterPools)
      ? window._cachedCanisterPools.find(p => Number(p.stock_id) === Number(stock.id) && p.is_active)
      : null;
    if (stockPool && val !== null && !Number.isNaN(val) && val > 0 && val <= maxAllowed + 0.001) {
      const vol = Number(stockPool.canister_volume_l || 20);
      const res = Number(stockPool.reserve_liters || 0);
      const fromRes = Math.min(res, val);
      const rem = Math.max(0, val - fromRes);
      const opened = rem > 1e-6 ? Math.ceil((rem - 1e-6) / vol) : 0;
      const newRes = rem > 1e-6 ? Math.max(0, (opened * vol) - rem) : Math.max(0, res - val);
      const segs = [];
      if (fromRes > 0) segs.push(`<b>${fromRes.toFixed(1)} л</b> з резерву`);
      if (opened > 0) segs.push(`<b>${opened} кан. × ${vol.toFixed(0)} л</b>`);
      canHintEl.style.display = 'block';
      canHintEl.innerHTML = `🛢️ Пул «${escapeHtml(stockPool.name)}»: спочатку ${segs.join(' + ')} → у резерві залишиться <b>${newRes.toFixed(1)} л</b> (вільно каністр: ${Number(stockPool.full_count) - opened} повн.)`;
    } else if (stockPool) {
      canHintEl.style.display = 'block';
      canHintEl.innerHTML = `🛢️ Пул «${escapeHtml(stockPool.name)}»: повних <b>${Number(stockPool.full_count)} × ${Number(stockPool.canister_volume_l).toFixed(0)} л</b>, у резерві <b>${Number(stockPool.reserve_liters).toFixed(1)} л</b> (йде першим)`;
    } else {
      canHintEl.style.display = 'none';
      canHintEl.innerHTML = '';
    }
  }
  return true;
};

// ---------------------------------------------------------------------------
// Canister Pools Management UI (Stage 2)
// ---------------------------------------------------------------------------

function renderCanisterPoolsSection(pools, txs) {
  const pill = document.getElementById('canisterPoolsSummaryPill');
  const tbody = document.querySelector('#canisterPoolsTable tbody');
  const txSection = document.getElementById('canisterTxSection');

  if (pill) {
    if (!pools || pools.length === 0) {
      pill.innerHTML = 'Пули каністр ще не налаштовані (звичайний облік складу)';
    } else {
      const totFull = pools.reduce((a, p) => a + Number(p.full_count || 0), 0);
      const totEmpty = pools.reduce((a, p) => a + Number(p.empty_count || 0), 0);
      const totAway = pools.reduce((a, p) => a + Number(p.away_refill_count || 0), 0);
      const totRes = pools.reduce((a, p) => a + Number(p.reserve_liters || 0), 0);
      const totAvail = pools.reduce((a, p) => a + Number(p.available_liters || 0), 0);
      pill.innerHTML = `Повні: <b style="color:#4ade80;">${totFull}</b> • Порожні: <b>${totEmpty}</b> • На АЗС: <b style="color:#fbbf24;">${totAway}</b> • Резерв: <b style="color:#38bdf8;">${totRes.toFixed(1)} л</b> • Усього: <b>${totAvail.toFixed(1)} л</b>`;
    }
  }

  const canTransfer = hasPermission('fuel:transfer');
  const canReceipt = hasPermission('fuel:receipt');
  const canConfigure = hasPermission('fuel:configure');

  if (tbody) {
    if (!pools || pools.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:var(--text-muted);">Пули каністр не налаштовані. Натисніть «🛢️ + Пул каністр» щоб закріпити каністри за об\'єктом.</td></tr>';
    } else {
      tbody.innerHTML = pools.map((p) => `
        <tr>
          <td><b>${escapeHtml(p.name)}</b></td>
          <td>${escapeHtml(p.stock_name || '-')}</td>
          <td><span class="badge badge-stopped">${escapeHtml(p.fuel_type)}</span></td>
          <td>${Number(p.canister_volume_l).toFixed(0)} л</td>
          <td><b style="color:#4ade80;">${Number(p.full_count)}</b> <span style="color:var(--text-muted); font-size:0.75rem;">з ${Number(p.total_count)}</span></td>
          <td><b>${Number(p.empty_count)}</b></td>
          <td>${Number(p.away_refill_count) > 0 ? `<b style="color:#fbbf24;">${Number(p.away_refill_count)}</b>` : '0'}</td>
          <td><b style="color:#38bdf8;">${Number(p.reserve_liters).toFixed(1)} л</b></td>
          <td><b>${formatLiters(p.available_liters)}</b></td>
          <td style="white-space: nowrap; text-align: center;">
            <button type="button" class="btn-action" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.78rem; display: inline-flex;" ${(!canTransfer || Number(p.empty_count) === 0) ? 'disabled' : ''} onclick="openCanisterActionModal(${Number(p.id)}, 'dispatch')" title="Віддати порожні каністри на заправку">📤 На АЗС</button>
            <button type="button" class="btn-action" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.78rem; display: inline-flex; border-color: #4ade80; color: #4ade80;" ${(!canReceipt || (Number(p.away_refill_count) === 0 && Number(p.empty_count) === 0)) ? 'disabled' : ''} onclick="openCanisterActionModal(${Number(p.id)}, 'receive')" title="Привезли заправлені каністри з АЗС">📥 Привезли</button>
            ${Number(p.away_refill_count) > 0 && canTransfer ? `<button type="button" class="btn-action" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.78rem; display: inline-flex;" onclick="openCanisterActionModal(${Number(p.id)}, 'return')" title="Повернути каністри порожніми без заправки">↩️</button>` : ''}
            ${canConfigure ? `
              <button type="button" class="btn-action" style="padding: 0.25rem 0.45rem; min-height: auto; font-size: 0.78rem; display: inline-flex;" onclick="openEditCanisterPoolModal(${Number(p.id)})" title="Редагувати пул">✏️</button>
              <button type="button" class="btn-action" style="padding: 0.25rem 0.45rem; min-height: auto; font-size: 0.78rem; display: inline-flex; border-color: #ef4444; color: #f87171;" onclick="deleteCanisterPool(${Number(p.id)}, '${escapeHtml(p.name).replace(/'/g, "\\'")}', ${Number(p.available_liters)})" title="Видалити пул">🗑️</button>
            ` : ''}
          </td>
        </tr>
      `).join('');
    }
  }

  if (txSection) {
    txSection.style.display = (pools.length > 0 || (txs && txs.length > 0)) ? 'block' : 'none';
  }
  if (typeof window.renderPaginatedTable === 'function') {
    window.renderPaginatedTable('canisterTxTable', txs || [], (t) => {
      const meta = CANISTER_OP_UA[t.operation] || { label: t.operation, color: '#cbd5e1' };
      const cntTxt = Number(t.count) > 0 ? `${Number(t.count)} шт.` : '—';
      return `
        <tr>
          <td>${formatDateTime(t.created_at)}</td>
          <td><b>${escapeHtml(t.pool_name || `#${t.pool_id}`)}</b></td>
          <td><span style="color:${meta.color}; font-weight:600;">${escapeHtml(meta.label)}</span></td>
          <td>${cntTxt}</td>
          <td>${Number(t.reserve_before).toFixed(1)} → <b>${Number(t.reserve_after).toFixed(1)} л</b></td>
          <td>повні: <b>${Number(t.full_after)}</b> / пусті: ${Number(t.empty_after)} / АЗС: ${Number(t.away_after)}</td>
          <td>${escapeHtml(t.comment || '-')}</td>
          <td>${escapeHtml(t.user_name || '-')}</td>
        </tr>
      `;
    }, 8, 'Операцій з каністрами ще не зафіксовано', 10);
  }
}

window._canisterModalStocks = [];

window.openCreateCanisterPoolModal = async function () {
  if (!hasPermission('fuel:configure')) {
    showToast('Керування пулами каністр доступне лише Адміністратору', 'warning');
    return;
  }
  document.getElementById('canPoolId').value = '';
  document.getElementById('canPoolModalTitle').innerText = '🛢️ Налаштувати пул каністр об\'єкта';
  document.getElementById('canPoolName').value = 'Каністри 20л';
  document.getElementById('canPoolVolume').value = '20';
  document.getElementById('canPoolFull').value = '5';
  document.getElementById('canPoolEmpty').value = '0';
  document.getElementById('canPoolAway').value = '0';
  document.getElementById('canPoolReserve').value = '0.0';

  const facSel = document.getElementById('canPoolFacility');
  const stockSel = document.getElementById('canPoolStock');
  if (facSel) facSel.disabled = false;
  if (stockSel) stockSel.disabled = false;

  try {
    const facilities = await api('/facilities');
    if (facSel && facilities?.length) {
      facSel.innerHTML = facilities.map(f => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
      if (currentFacilityId && facilities.some(f => Number(f.id) === Number(currentFacilityId))) {
        facSel.value = currentFacilityId;
      }
    }
    await window.onCanisterPoolFacilityChange();
    openModal('modalCanisterPool');
    window.updateCanisterPoolFormPreview();
  } catch (err) {
    showToast(err.message || 'Помилка відкриття форми каністр', 'error');
  }
};

window.onCanisterPoolFacilityChange = async function () {
  const facId = parseInt(document.getElementById('canPoolFacility')?.value || '0', 10);
  const stockSel = document.getElementById('canPoolStock');
  if (!stockSel || !facId) return;
  try {
    const stocks = await api(`/fuel/stocks?facility_id=${encodeURIComponent(facId)}`);
    window._canisterModalStocks = stocks || [];
    if (!stocks || stocks.length === 0) {
      stockSel.innerHTML = '<option value="">(Немає складів ГСМ)</option>';
    } else {
      stockSel.innerHTML = stocks.map(s => `<option value="${Number(s.id)}">${escapeHtml(s.name)} (${escapeHtml(s.fuel_type)}, зараз ${Number(s.current_balance_l).toFixed(1)} л)</option>`).join('');
    }
    window.updateCanisterPoolFormPreview();
  } catch (_) {}
};

window.autoFillCanisterCountsFromStock = function () {
  const stockId = parseInt(document.getElementById('canPoolStock')?.value || '0', 10);
  const vol = parseFloat(document.getElementById('canPoolVolume')?.value || '20') || 20;
  const st = (window._canisterModalStocks || []).find(s => Number(s.id) === stockId);
  if (!st) return;
  const bal = Math.max(0, Number(st.current_balance_l || 0));
  const full = Math.floor((bal + 1e-6) / vol);
  const res = Math.max(0, Number((bal - full * vol).toFixed(2)));
  document.getElementById('canPoolFull').value = String(full);
  document.getElementById('canPoolReserve').value = res.toFixed(1);
  window.updateCanisterPoolFormPreview();
};

window.openEditCanisterPoolModal = async function (poolId) {
  if (!hasPermission('fuel:configure')) {
    showToast('Керування пулами каністр доступне лише Адміністратору', 'warning');
    return;
  }
  const pool = (window._cachedCanisterPools || []).find(p => Number(p.id) === Number(poolId));
  if (!pool) return;

  document.getElementById('canPoolId').value = String(pool.id);
  document.getElementById('canPoolModalTitle').innerText = `✏️ Редагувати пул «${pool.name}»`;
  document.getElementById('canPoolName').value = pool.name;
  document.getElementById('canPoolVolume').value = String(pool.canister_volume_l);
  document.getElementById('canPoolFull').value = String(pool.full_count);
  document.getElementById('canPoolEmpty').value = String(pool.empty_count);
  document.getElementById('canPoolAway').value = String(pool.away_refill_count);
  document.getElementById('canPoolReserve').value = Number(pool.reserve_liters).toFixed(1);

  const facSel = document.getElementById('canPoolFacility');
  const stockSel = document.getElementById('canPoolStock');
  if (facSel) {
    facSel.innerHTML = `<option value="${Number(pool.facility_id)}">${escapeHtml(pool.facility_name || `Об'єкт #${pool.facility_id}`)}</option>`;
    facSel.disabled = true;
  }
  if (stockSel) {
    stockSel.innerHTML = `<option value="${Number(pool.stock_id)}">${escapeHtml(pool.stock_name || `Склад #${pool.stock_id}`)} (${escapeHtml(pool.fuel_type)})</option>`;
    stockSel.disabled = true;
  }
  openModal('modalCanisterPool');
  window.updateCanisterPoolFormPreview();
};

window.updateCanisterPoolFormPreview = function () {
  const hint = document.getElementById('canPoolLiveHint');
  if (!hint) return;
  const vol = parseFloat(document.getElementById('canPoolVolume')?.value || '20') || 20;
  const full = Math.max(0, parseInt(document.getElementById('canPoolFull')?.value || '0', 10) || 0);
  const empty = Math.max(0, parseInt(document.getElementById('canPoolEmpty')?.value || '0', 10) || 0);
  const away = Math.max(0, parseInt(document.getElementById('canPoolAway')?.value || '0', 10) || 0);
  const res = Math.max(0, parseFloat(document.getElementById('canPoolReserve')?.value || '0') || 0);
  const total = full + empty + away;
  const avail = full * vol + res;
  if (res >= vol) {
    hint.innerHTML = `<span style="color:#ef4444;">⚠️ Залишок резерву (${res.toFixed(1)} л) має бути меншим за об'єм 1 каністри (${vol.toFixed(1)} л)!</span>`;
    return;
  }
  hint.innerHTML = `Усього закріплено каністр: <b>${total} шт. × ${vol.toFixed(0)} л</b> • Доступний залишок на складі стане: <b style="color:#4ade80;">${avail.toFixed(1)} л</b> (${full} повн. + ${res.toFixed(1)} л резерву)`;
};

document.getElementById('canisterPoolForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const editId = document.getElementById('canPoolId').value.trim();
  const payload = {
    name: document.getElementById('canPoolName').value.trim(),
    canister_volume_l: parseFloat(document.getElementById('canPoolVolume').value),
    full_count: parseInt(document.getElementById('canPoolFull').value, 10) || 0,
    empty_count: parseInt(document.getElementById('canPoolEmpty').value, 10) || 0,
    away_refill_count: parseInt(document.getElementById('canPoolAway').value, 10) || 0,
    reserve_liters: parseFloat(document.getElementById('canPoolReserve').value) || 0.0,
  };
  try {
    if (editId) {
      await api(`/fuel/canisters/${encodeURIComponent(editId)}`, { method: 'PUT', body: JSON.stringify(payload) });
      showToast('Пул каністр оновлено та синхронізовано зі складом!', 'success');
    } else {
      payload.facility_id = parseInt(document.getElementById('canPoolFacility').value, 10);
      payload.stock_id = parseInt(document.getElementById('canPoolStock').value, 10);
      await api('/fuel/canisters', { method: 'POST', body: JSON.stringify(payload) });
      showToast('Пул каністр створено!', 'success');
    }
    closeModal('modalCanisterPool');
    await loadFuelData();
  } catch (err) {
    showToast(err.message || 'Помилка збереження пулу каністр', 'error');
  }
});

window.deleteCanisterPool = async function (poolId, name, avail) {
  if (avail > 0) {
    showToast(`Неможливо видалити пул «${name}», доки в ньому є ${avail.toFixed(1)} л палива.`, 'warning');
    return;
  }
  if (!confirm(`Видалити пул каністр "${name}"?`)) return;
  try {
    await api(`/fuel/canisters/${encodeURIComponent(poolId)}`, { method: 'DELETE' });
    showToast(`Пул каністр "${name}" видалено`, 'success');
    await loadFuelData();
  } catch (err) {
    showToast(err.message || 'Помилка видалення пулу каністр', 'error');
  }
};

window.openCanisterActionModal = async function (poolId, mode) {
  const pool = (window._cachedCanisterPools || []).find(p => Number(p.id) === Number(poolId));
  if (!pool) return;
  if (!cachedFuelPrices) await fetchFuelPricesCache();

  document.getElementById('canActionPoolId').value = String(pool.id);
  document.getElementById('canActionMode').value = mode;
  document.getElementById('canActionComment').value = '';
  document.getElementById('canActionCostTotal').value = '';
  document.getElementById('canActionReceiptNo').value = '';

  const titleEl = document.getElementById('canActionTitle');
  const srcGroup = document.getElementById('canActionSourceGroup');
  const recFields = document.getElementById('canActionReceiveFields');
  const countEl = document.getElementById('canActionCount');
  const submitBtn = document.getElementById('canActionSubmitBtn');

  if (mode === 'dispatch') {
    titleEl.innerText = '📤 Віддати порожні каністри на заправку';
    srcGroup.style.display = 'none';
    recFields.style.display = 'none';
    countEl.value = '1';
    countEl.max = String(pool.empty_count);
    submitBtn.innerText = '📤 Відправити на заправку';
  } else if (mode === 'return') {
    titleEl.innerText = '↩️ Повернути каністри порожніми';
    srcGroup.style.display = 'none';
    recFields.style.display = 'none';
    countEl.value = '1';
    countEl.max = String(pool.away_refill_count);
    submitBtn.innerText = '↩️ Повернути на об\'єкт';
  } else {
    titleEl.innerText = '📥 Привезли заправлені каністри';
    srcGroup.style.display = 'block';
    recFields.style.display = 'block';
    document.getElementById('canActionCreateReceipt').checked = true;
    const srcSel = document.getElementById('canActionSource');
    srcSel.value = Number(pool.away_refill_count) > 0 ? 'away' : 'empty';
    countEl.value = String(Math.max(1, Number(pool.away_refill_count) || 1));
    window.toggleCanisterReceiptInputs();
    submitBtn.innerText = '📥 Зарахувати каністри';
  }

  openModal('modalCanisterAction');
  window.updateCanisterActionPreview();
};

window.toggleCanisterReceiptInputs = function () {
  const checked = document.getElementById('canActionCreateReceipt')?.checked;
  const box = document.getElementById('canActionReceiptInputs');
  if (box) box.style.display = checked ? 'block' : 'none';
};

window.updateCanisterActionPreview = function () {
  const poolId = parseInt(document.getElementById('canActionPoolId')?.value || '0', 10);
  const mode = document.getElementById('canActionMode')?.value;
  const pool = (window._cachedCanisterPools || []).find(p => Number(p.id) === poolId);
  if (!pool) return;

  const cnt = Math.max(1, parseInt(document.getElementById('canActionCount')?.value || '1', 10) || 1);
  const vol = Number(pool.canister_volume_l || 20);
  const infoEl = document.getElementById('canActionPoolInfo');
  if (infoEl) {
    infoEl.innerHTML = `Пул: <b>${escapeHtml(pool.name)}</b> (${escapeHtml(pool.fuel_type)}, ${vol.toFixed(0)} л) • Повні: <b style="color:#4ade80;">${Number(pool.full_count)}</b> • Порожні: <b>${Number(pool.empty_count)}</b> • На АЗС: <b style="color:#fbbf24;">${Number(pool.away_refill_count)}</b>`;
  }

  if (mode === 'receive') {
    const src = document.getElementById('canActionSource')?.value || 'away';
    const maxCnt = src === 'away' ? Number(pool.away_refill_count) : Number(pool.empty_count);
    const countEl = document.getElementById('canActionCount');
    if (countEl) countEl.max = String(Math.max(1, maxCnt));
    const liters = cnt * vol;
    const prov = document.getElementById('canActionProvider')?.value || 'wog';
    const fuelsMap = prov === 'okko' ? cachedFuelPrices?.okko_fuels : cachedFuelPrices?.fuels;
    const fEntry = fuelsMap?.[pool.fuel_type] || cachedFuelPrices?.fuels?.[pool.fuel_type];
    const unitP = fEntry ? Number(fEntry.effective_price) : 92.90;
    const rawCost = document.getElementById('canActionCostTotal')?.value?.trim();
    const costNum = rawCost ? parseFloat(rawCost) : 0;
    const hintEl = document.getElementById('canActionAutoPriceHint');
    if (hintEl) {
      if (costNum > 0) {
        hintEl.innerHTML = `✅ Повернення <b>${cnt} шт. (+${liters.toFixed(1)} л)</b> • Сума: <b>${costNum.toFixed(2)} грн</b> (${(costNum / liters).toFixed(2)} грн/л)`;
      } else {
        hintEl.innerHTML = `💡 Повернення <b>${cnt} шт. (+${liters.toFixed(1)} л)</b> • Авторозрахунок: ~<b>${(liters * unitP).toFixed(2)} грн</b> (${unitP.toFixed(2)} грн/л)`;
      }
    }
  }
};

document.getElementById('canisterActionForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const poolId = document.getElementById('canActionPoolId').value;
  const mode = document.getElementById('canActionMode').value;
  const count = parseInt(document.getElementById('canActionCount').value, 10);
  const comment = document.getElementById('canActionComment').value.trim() || null;

  try {
    if (mode === 'dispatch') {
      await api(`/fuel/canisters/${encodeURIComponent(poolId)}/dispatch`, {
        method: 'POST',
        body: JSON.stringify({ count, comment })
      });
      showToast(`Відправлено на заправку: ${count} каністр`, 'success');
    } else if (mode === 'return') {
      await api(`/fuel/canisters/${encodeURIComponent(poolId)}/return-empty`, {
        method: 'POST',
        body: JSON.stringify({ count, comment })
      });
      showToast(`Повернуто порожніми: ${count} каністр`, 'success');
    } else {
      const source = document.getElementById('canActionSource').value;
      const createReceipt = document.getElementById('canActionCreateReceipt').checked;
      const rawCost = document.getElementById('canActionCostTotal').value.trim();
      const body = {
        count,
        source,
        create_receipt: createReceipt,
        fuel_provider: document.getElementById('canActionProvider').value,
        cost_total: rawCost ? parseFloat(rawCost) : null,
        driver_name: document.getElementById('canActionDriver').value.trim() || 'Доставка каністр',
        receipt_number: document.getElementById('canActionReceiptNo').value.trim() || null,
        comment
      };
      await api(`/fuel/canisters/${encodeURIComponent(poolId)}/receive`, {
        method: 'POST',
        body: JSON.stringify(body)
      });
      showToast(`Прийнято заправлених каністр: ${count} шт.`, 'success');
    }
    closeModal('modalCanisterAction');
    await loadFuelData();
    loadAllData();
  } catch (err) {
    showToast(err.message || 'Помилка операції з каністрами', 'error');
  }
});

window.checkTransferClientBounds = function() {
  const { stock, gen } = window._getSelectedTransferEntities();
  const inputEl = document.getElementById('transLiters');
  if (!gen || !inputEl) return true;
  const val = parseFloat(inputEl.value);
  const cap = Number(gen.tank_capacity_l || 25.0);
  const inTank = Number(gen.fuel_tank_level_l || 0);
  const freeInTank = Math.max(0, Number((cap - inTank).toFixed(1)));
  const stockBal = stock ? Math.max(0, Number(Number(stock.current_balance_l || 0).toFixed(1))) : 0;

  if (Number.isNaN(val) || val <= 0) {
    showToast('Вкажіть коректну кількість літрів (> 0)', 'error');
    return false;
  }
  if (val > freeInTank + 0.001) {
    showToast(`Перевищення місткості бака (${cap.toFixed(1)} л)! У баку вже ${inTank.toFixed(1)} л, можна додати максимум ${freeInTank.toFixed(1)} л`, 'error');
    return false;
  }
  if (stock && val > stockBal + 0.001) {
    showToast(`Недостатньо палива на складі! Доступно: ${stockBal.toFixed(1)} л`, 'error');
    return false;
  }
  return true;
};


