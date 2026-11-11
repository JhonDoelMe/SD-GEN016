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

    const stocks = await api(`/fuel/stocks${qFac}`);
    if (stockSel) {
      if (!stocks || stocks.length === 0) {
        stockSel.innerHTML = '<option value="">(Немає доступних складів)</option>';
      } else {
        stockSel.innerHTML = stocks.map(s => `<option value="${Number(s.id)}">${escapeHtml(s.name)} (${s.current_balance_l.toFixed(1)} л, ${escapeHtml(s.fuel_type || 'А-95')})</option>`).join('');
      }
    }

    const gens = await api(`/generator/list${qFac}`); window._transferModalStocks = stocks || []; window._transferModalGens = gens || [];
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
    document.getElementById('cardStock').innerText = s.warehouse_balance_l.toFixed(1).replace('.', ',');
    document.getElementById('fuelStockBal').innerText = formatLiters(s.warehouse_balance_l);
    document.getElementById('fuelTankBal').innerText = formatLiters(s.tank_balance_l);
    document.getElementById('fuelTotalBought').innerText = formatLiters(s.total_received_l);
    document.getElementById('fuelTotalSpent').innerText = formatMoney(s.total_spent_uah);
    document.getElementById('fuelAvgPrice').innerText = formatPricePerLiter(s.avg_price_per_liter);
  } catch (_) {}
}

async function loadFuelData() {
  try {
    const qFac = currentFacilityId ? `?facility_id=${encodeURIComponent(currentFacilityId)}` : '';
    const [, stocks, receipts, transfers] = await Promise.all([
      loadFuelSummary(),
      api(`/fuel/stocks${qFac}`),
      api(`/fuel/receipts${qFac}`),
      api(`/fuel/transfers${qFac}`)
    ]);

    // Stocks Table
    const sTbody = document.querySelector('#fuelStocksTable tbody');
    if (sTbody) {
      sTbody.innerHTML = stocks.map((s) => `
        <tr>
          <td>#${Number(s.id)}</td>
          <td><b>${escapeHtml(s.name)}</b></td>
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
      `).join('') || '<tr><td colspan="7" style="text-align:center; color:var(--text-muted)">Складів ГСМ не знайдено</td></tr>';
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
    window.renderPaginatedTable('fuelTransfersTable', transfers, (t) => `
      <tr>
        <td>${formatDateTime(t.created_at)}</td>
        <td>${escapeHtml(t.stock_name || '-')}</td>
        <td><b>${escapeHtml(t.generator_name || '-')}</b></td>
        <td><b style="color:#38bdf8;">+${formatLiters(t.liters)}</b></td>
        <td>${formatLiters(t.source_balance_before)} → ${formatLiters(t.source_balance_after)}</td>
        <td>${formatLiters(t.tank_balance_before)} → ${formatLiters(t.tank_balance_after)}</td>
        <td>${escapeHtml(t.comment || '-')}</td>
        <td>${escapeHtml(t.user_name || '-')}</td>
      </tr>
    `, 8, 'Заправок не зареєстровано', 10);
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
    if (typeof window.checkTransferClientBounds === 'function' && !window.checkTransferClientBounds()) return; await api('/fuel/transfer', { method: 'POST', body: JSON.stringify(body) });
    closeModal('modalTransfer');
    showToast('Бак генератора успішно заправлено!', 'success');
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
  return true;
};

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


