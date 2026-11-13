// ==========================================
// 📏 Fuel Measurement Mode & Commission Inventory (SuperAdmin)
// ==========================================

window._measurementState = null;

async function loadMeasurementStatus() {
  if (!token || !currentFacilityId) {
    window._measurementState = null;
    updateMeasurementHeaderUI();
    return null;
  }
  try {
    const data = await api(`/measurement/status?facility_id=${encodeURIComponent(currentFacilityId)}`, {
      suppressToast: true,
    });
    window._measurementState = data;
  } catch (_) {
    // Keep last state on transient error
  }
  updateMeasurementHeaderUI();
  if (typeof window.updateFuelAssessmentBlock === 'function') {
    window.updateFuelAssessmentBlock();
  }
  return window._measurementState;
}

function updateMeasurementHeaderUI() {
  const state = window._measurementState;
  const pill = document.getElementById('headerMeasurementBadge');
  const pillIcon = document.getElementById('measurementPillIcon');
  const pillText = document.getElementById('measurementPillText');
  const lockBanner = document.getElementById('measurementLockBanner');
  const lockBannerText = document.getElementById('measurementLockBannerText');
  const lockBannerBtn = document.getElementById('btnMeasurementBannerOpen');

  if (!state || !state.has_active || !state.active) {
    if (pill) pill.style.display = 'none';
    if (lockBanner) lockBanner.style.display = 'none';
    return;
  }

  const m = state.active;
  const measured = Number(m.measured_liters_total || 0);
  const minThresh = Number(m.min_liters_threshold || 100);

  if (pill && pillIcon && pillText) {
    pill.style.display = 'inline-flex';
    pill.className = 'header-pill pill-measurement';
    if (state.is_locked) {
      pill.classList.add('pill-meas-locked');
      pillIcon.innerText = m.status === 'PENDING_APPROVAL' ? '📄' : '🔒';
      pillText.innerText = m.status === 'PENDING_APPROVAL' ? 'Погодження' : 'Інвентаризація';
      pill.title = 'Об\'єкт очікує інвентаризації/погодження. Натисніть для перегляду деталей.';
    } else {
      pill.classList.add('pill-meas-active');
      pillIcon.innerText = '📏';
      pillText.innerText = `Замір: ${measured.toFixed(0)}/${minThresh.toFixed(0)}л`;
      pill.title = 'Активний режим вимірювання витрат палива. Натисніть для проміжних результатів.';
    }
  }

  if (lockBanner && lockBannerText) {
    lockBanner.style.display = 'flex';
    if (state.is_locked) {
      lockBanner.className = 'offline-sync-banner banner-conflict';
      const stageTxt = m.status === 'PENDING_APPROVAL'
        ? `PDF-відомість <b>${escapeHtml(m.statement_number || '')}</b> сформована — скачайте та натисніть «Погоджено» (Суперадмін).`
        : 'Внесіть залишок складу комісією (мін. 3 особи) для розблокування ГСМ.';
      lockBannerText.innerHTML = `🔒 <b>Склад ГСМ опечатано для інвентаризації (замір завершено):</b> залито <b>${measured.toFixed(1)} л</b> (${Number(m.total_hours_elapsed || 0).toFixed(2)} год → <b>${Number(m.calculated_consumption_l_per_h || 0).toFixed(3)} л/год</b>). Запуск і зупинка генератора працюють штатно. ${stageTxt}`;
    } else {
      lockBanner.className = 'offline-sync-banner banner-measurement';
      lockBannerText.innerHTML = `📏 <b>Режим вимірювання («від повного до повного»):</b> заправлено в бак <b>${measured.toFixed(1)} / ${minThresh.toFixed(0)} л</b> • обмеження на долив та попередження баку ігноруються • корекції заборонені.`;
    }
    if (lockBannerBtn) {
      lockBannerBtn.style.display = isSuperAdmin() ? 'inline-flex' : 'none';
    }
  }
}

window.openMeasurementStatusModal = async function () {
  await Promise.all([
    loadMeasurementStatus(),
    window.ViewLoader?.ensureModal('modalMeasurementStatus')
  ]);
  const state = window._measurementState;
  const body = document.getElementById('measurementStatusModalBody');
  const goAdminBtn = document.getElementById('btnModalMeasGoAdmin');
  if (goAdminBtn) {
    goAdminBtn.style.display = isSuperAdmin() ? 'inline-flex' : 'none';
  }
  if (!body) return;

  if (!state || !state.has_active || !state.active) {
    body.innerHTML = `<div class="offline-empty-state"><div class="offline-empty-title">Режим вимірювання наразі вимкнено</div><div class="offline-empty-sub">Об'єкт працює у штатному режимі.</div></div>`;
    await openModal('modalMeasurementStatus');
    return;
  }

  const m = state.active;
  const pct = Math.min(100, Math.max(0, Number(m.progress_pct || 0)));
  const transfers = Array.isArray(m.transfers) ? m.transfers : [];
  const stageUa = m.status === 'MEASURING'
    ? '📏 Активне вимірювання витрат'
    : (m.status === 'PENDING_INVENTORY' ? '🔒 Очікує інвентаризації комісією' : '📄 Очікує підпису PDF та погодження');

  const trHtml = transfers.length > 0
    ? `
      <div class="table-container" style="max-height: 210px; overflow-y: auto; margin-top: 0.75rem;">
        <table>
          <thead><tr><th>Дата</th><th>Долито в бак</th><th>Склад</th><th>Оператор</th></tr></thead>
          <tbody>
            ${transfers.map((tr) => `
              <tr>
                <td>${escapeHtml(formatDateTime(tr.created_at))}</td>
                <td><b style="color:#38bdf8;">+${Number(tr.liters).toFixed(1)} л</b></td>
                <td>${escapeHtml(tr.stock_name || '-')}</td>
                <td>${escapeHtml(tr.operator_name || '-')}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>`
    : '<div style="font-size:0.84rem; color:var(--text-muted); margin-top:0.65rem;">Дозаправок у бак з моменту старту заміру ще не було.</div>';

  body.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem; margin-bottom:0.75rem;">
      <div>
        <div style="font-weight:700; font-size:0.98rem;">${escapeHtml(m.generator_name || 'Генератор')} (${escapeHtml(m.fuel_type || '-')})</div>
        <div style="font-size:0.8rem; color:var(--text-muted);">Старт: ${escapeHtml(formatDateTime(m.started_at))} • Норма до: ${Number(m.old_nominal_consumption_l_per_h).toFixed(2)} л/год</div>
      </div>
      <span class="badge ${state.is_locked ? 'badge-faulty' : 'badge-running'}">${stageUa}</span>
    </div>

    <div class="meas-progress-wrap">
      <div style="display:flex; justify-content:space-between; font-size:0.84rem; margin-bottom:0.35rem;">
        <span>Лічильник по заправках у бак (від повного до повного)</span>
        <b>${Number(m.measured_liters_total).toFixed(1)} / ${Number(m.min_liters_threshold).toFixed(0)} л (${pct.toFixed(0)}%)</b>
      </div>
      <div class="progress-bar-bg"><div class="progress-bar-fill" style="width:${pct}%; background:${pct >= 100 ? '#22c55e' : '#38bdf8'};"></div></div>
    </div>

    <div class="meas-tiles-grid">
      <div class="oq-stat-tile">
        <span class="oq-stat-label">Стартовий бак (100%)</span>
        <span class="oq-stat-val">${Number(m.start_tank_level_l).toFixed(1)} л</span>
      </div>
      <div class="oq-stat-tile">
        <span class="oq-stat-label">Заправлено в бак</span>
        <span class="oq-stat-val" style="color:#38bdf8;">+${Number(m.added_during_measurement_l).toFixed(1)} л</span>
      </div>
      <div class="oq-stat-tile">
        <span class="oq-stat-label">Напрацьовано</span>
        <span class="oq-stat-val">${Number(m.elapsed_hours).toFixed(2)} год</span>
      </div>
      <div class="oq-stat-tile">
        <span class="oq-stat-label">${m.calculated_consumption_l_per_h != null ? 'Підсумок' : 'Поточна оцінка'}</span>
        <span class="oq-stat-val" style="color:#4ade80;">${(m.calculated_consumption_l_per_h ?? m.est_consumption_l_per_h) != null ? Number(m.calculated_consumption_l_per_h ?? m.est_consumption_l_per_h).toFixed(2) + ' л/г' : '—'}</span>
      </div>
    </div>

    <div style="margin-top:0.85rem; font-weight:600; font-size:0.88rem;">⛽ Заправки в бак за час вимірювання (${transfers.length})</div>
    ${trHtml}
  `;

  openModal('modalMeasurementStatus');
};

window.loadMeasurementTab = async function () {
  if (!isSuperAdmin()) return;
  const container = document.getElementById('measurementWorkspace');
  const historyBody = document.getElementById('measurementHistoryTableBody');
  if (!container) return;

  await loadMeasurementStatus();
  const state = window._measurementState;

  let gens = [];
  try {
    gens = await api(`/generator/list${currentFacilityId ? '?facility_id=' + encodeURIComponent(currentFacilityId) : ''}`, { suppressToast: true });
  } catch (_) {}

  if (!state || !state.has_active || !state.active) {
    const activeGen = gens.find((g) => Number(g.id) === Number(currentGeneratorId)) || gens[0] || currentGenerator;
    const isFull = activeGen && Number(activeGen.fuel_tank_level_l) >= Number(activeGen.tank_capacity_l) - 0.1;
    const isStopped = activeGen && activeGen.status !== 'RUNNING' && activeGen.status !== 'BLOCKED' && activeGen.status !== 'FAULTY';
    const canStart = !!activeGen && isFull && isStopped;

    const genOptions = (gens || []).map((g) => `<option value="${Number(g.id)}" ${activeGen && Number(g.id) === Number(activeGen.id) ? 'selected' : ''}>${escapeHtml(g.name)} (${escapeHtml(g.model)} • ${Number(g.fuel_tank_level_l).toFixed(1)}/${Number(g.tank_capacity_l).toFixed(1)} л)</option>`).join('');

    container.innerHTML = `
      <div class="panel">
        <div class="panel-header">
          <div>
            <h3>📏 Запуск контрольного режиму вимірювання</h3>
            <p style="font-size:0.84rem; color:var(--text-muted); margin:0.25rem 0 0;">
              Точний розрахунок фактичних витрат (л/год) методом «від повного до повного» (мін. 100 л по заправках у бак) без блокування запуску генератора під час інвентаризації.
            </p>
          </div>
        </div>
        <div class="form-row-2" style="margin-top:0.75rem;">
          <div class="form-group">
            <label>Генератор для заміру</label>
            <select id="measStartGenSelect" onchange="onMeasStartGenChange()">${genOptions || '<option value="">Немає генераторів</option>'}</select>
          </div>
          <div class="form-group">
            <label>Умова старту</label>
            <div id="measStartEligibilityBox" style="padding:0.62rem 0.85rem; border-radius:0.55rem; border:1px solid ${canStart ? 'rgba(34,197,94,0.4)' : 'rgba(245,158,11,0.45)'}; background:${canStart ? 'rgba(34,197,94,0.1)' : 'rgba(245,158,11,0.1)'}; font-size:0.84rem;">
              ${!activeGen ? 'Генератор не обрано' : (!isStopped ? '⚠️ Спочатку зупиніть генератор' : (!isFull ? `⚠️ Бак неповний (${Number(activeGen.fuel_tank_level_l).toFixed(1)} / ${Number(activeGen.tank_capacity_l).toFixed(1)} л) — заправте до 100%` : `✅ Бак повний (${Number(activeGen.tank_capacity_l).toFixed(1)} л). Готово до старту!`))}
            </div>
          </div>
        </div>
        <div style="display:flex; gap:0.6rem; flex-wrap:wrap; margin-top:0.5rem;">
          <button type="button" id="btnStartMeasurement" class="btn-primary" style="width:auto; margin:0; padding:0.75rem 1.35rem;" ${!canStart ? 'disabled' : ''} onclick="startMeasurementMode()">📏 Увімкнути режим вимірювання</button>
          ${!isFull && activeGen ? `<button type="button" class="btn-secondary" style="width:auto; margin:0;" onclick="openModal('modalTransfer')">⛽ Заправити бак до повного</button>` : ''}
        </div>
      </div>
    `;
    window._measCandidateGens = gens || [];
  } else {
    const m = state.active;
    if (m.status === 'MEASURING') {
      const pct = Math.min(100, Math.max(0, Number(m.progress_pct || 0)));
      const transfers = Array.isArray(m.transfers) ? m.transfers : [];
      container.innerHTML = `
        <div class="panel" style="border-color: rgba(56, 189, 248, 0.45);">
          <div class="panel-header" style="flex-wrap:wrap; gap:0.65rem;">
            <div>
              <h3>📏 Триває контрольний замір — ${escapeHtml(m.generator_name || 'Генератор')}</h3>
              <p style="font-size:0.83rem; color:var(--text-muted); margin:0.2rem 0 0;">
                Старт: ${escapeHtml(formatDateTime(m.started_at))} • Мотогодини старту: <b>${Number(m.start_operating_hours).toFixed(1)}</b> • Поточні: <b>${Number(m.current_operating_hours).toFixed(1)}</b>
              </p>
            </div>
            <button type="button" class="btn-oq-chip btn-oq-chip-danger" onclick="openCancelMeasurementModal(${Number(m.id)})">✖️ Аварійне скасування</button>
          </div>

          <div class="meas-progress-wrap" style="margin:0.85rem 0;">
            <div style="display:flex; justify-content:space-between; font-size:0.88rem; margin-bottom:0.35rem;">
              <span>Лічильник по заправках у бак («у вихлопну трубу», мін. 100.0 л)</span>
              <b>${Number(m.measured_liters_total).toFixed(1)} / ${Number(m.min_liters_threshold).toFixed(0)} л (${pct.toFixed(1)}%)</b>
            </div>
            <div class="progress-bar-bg"><div class="progress-bar-fill" style="width:${pct}%; background:${pct >= 100 ? '#22c55e' : '#38bdf8'};"></div></div>
          </div>

          <div class="meas-tiles-grid">
            <div class="oq-stat-tile"><span class="oq-stat-label">Стартовий бак (100%)</span><span class="oq-stat-val">${Number(m.start_tank_level_l).toFixed(1)} л</span></div>
            <div class="oq-stat-tile"><span class="oq-stat-label">Заправлено в бак</span><span class="oq-stat-val" style="color:#38bdf8;">+${Number(m.added_during_measurement_l).toFixed(1)} л</span></div>
            <div class="oq-stat-tile"><span class="oq-stat-label">Відпрацьовано</span><span class="oq-stat-val">${Number(m.elapsed_hours).toFixed(2)} год</span></div>
            <div class="oq-stat-tile"><span class="oq-stat-label">Оцінка л/год</span><span class="oq-stat-val" style="color:#4ade80;">${m.est_consumption_l_per_h != null ? Number(m.est_consumption_l_per_h).toFixed(3) : '—'}</span></div>
          </div>

          <div class="form-row-2" style="margin-top:1rem; padding-top:0.85rem; border-top:1px dashed var(--border-color);">
            <div class="form-group">
              <label>Кінцеві мотогодини (залиште поточні або уточніть)</label>
              <input type="number" step="0.1" min="${Number(m.current_operating_hours)}" id="measFinishEndHours" value="${Number(m.current_operating_hours).toFixed(1)}">
            </div>
            <div class="form-group">
              <label>Завершення після фінальної заправки</label>
              <button type="button" class="btn-primary" style="margin:0; width:100%;" ${!m.can_finish_full ? 'disabled' : ''} onclick="finishMeasurementFull(${Number(m.id)})">
                ✅ Бак повний — завершити замір
              </button>
            </div>
          </div>
          ${!m.can_finish_full ? `
            <div style="font-size:0.82rem; color:#fbbf24; margin-top:0.4rem;">
              ${m.is_generator_running ? '⚠️ Генератор зараз працює — зупиніть його на Головній, долийте бак під кришку та підтвердьте «Бак повний».' : `⚠️ За заправками в бак потрібно набрати щонайменше 100 л (залишилось ще ${Number(m.liters_remaining_to_min).toFixed(1)} л).`}
            </div>
          ` : ''}

          <div style="margin-top:1rem;">
            <b style="font-size:0.88rem;">Дозаправки під час заміру (${transfers.length})</b>
            ${transfers.length ? `
              <div class="table-container" style="max-height:200px; overflow-y:auto; margin-top:0.45rem;">
                <table><thead><tr><th>Час</th><th>Літри</th><th>Склад</th><th>Оператор</th></tr></thead>
                <tbody>${transfers.map((tr) => `<tr><td>${escapeHtml(formatDateTime(tr.created_at))}</td><td><b>+${Number(tr.liters).toFixed(1)} л</b></td><td>${escapeHtml(tr.stock_name)}</td><td>${escapeHtml(tr.operator_name || '-')}</td></tr>`).join('')}</tbody>
                </table>
              </div>` : '<div style="font-size:0.82rem; color:var(--text-muted); margin-top:0.3rem;">Дозаправок ще не зафіксовано.</div>'}
          </div>
        </div>
      `;
    } else {
      // PENDING_INVENTORY or PENDING_APPROVAL
      const pools = Array.isArray(m.current_pools) ? m.current_pools : [];
      const stocks = Array.isArray(m.current_stocks) ? m.current_stocks : [];
      const factData = m.inventory_fact || {};
      const factStockMap = {};
      (factData.stocks || []).forEach((fs) => { factStockMap[Number(fs.stock_id)] = fs; });

      const poolsByStock = {};
      pools.forEach((p) => {
        const sid = Number(p.stock_id);
        if (!poolsByStock[sid]) poolsByStock[sid] = [];
        poolsByStock[sid].push(p);
      });
      window._measStockPoolsMap = poolsByStock;

      const existingMembers = (Array.isArray(m.commission_members) && m.commission_members.length >= 3)
        ? m.commission_members
        : [
            { role: 'Голова комісії', name: '' },
            { role: 'Член комісії', name: '' },
            { role: 'Матеріально відповідальна особа', name: '' },
          ];

      const isApproval = m.status === 'PENDING_APPROVAL';
      const pdfDownloaded = !!m.document_downloaded_at;
      const tankCapVal = Number(m.tank_capacity_l || m.start_tank_level_l || 0);

      container.innerHTML = `
        <div class="panel" style="border-color: rgba(245, 158, 11, 0.5);">
          <div class="panel-header" style="flex-wrap:wrap; gap:0.65rem;">
            <div>
              <h3>🔒 Склад ГСМ опечатано для інвентаризації — ${escapeHtml(m.generator_name || 'Генератор')}</h3>
              <p style="font-size:0.83rem; color:var(--text-muted); margin:0.2rem 0 0;">
                Відомість: <b>${escapeHtml(m.statement_number || 'Буде присвоєно')}</b> • Залито в бак: <b>${Number(m.total_fuel_consumed_l || 0).toFixed(1)} л</b> за <b>${Number(m.total_hours_elapsed || 0).toFixed(2)} год</b> → Новий розхід: <b style="color:#4ade80;">${Number(m.calculated_consumption_l_per_h || 0).toFixed(3)} л/год</b> (було ${Number(m.old_nominal_consumption_l_per_h).toFixed(3)})
              </p>
              <div style="font-size:0.8rem; color:#4ade80; margin-top:0.25rem;">
                ⚡ Запуск та зупинка генератора працюють без обмежень (об'єкт готовий до роботи під час знеструмлення).
              </div>
            </div>
            <button type="button" class="btn-oq-chip btn-oq-chip-danger" onclick="openCancelMeasurementModal(${Number(m.id)})">✖️ Аварійне скасування</button>
          </div>

          <form id="measInventoryForm" onsubmit="submitMeasurementInventoryForm(event, ${Number(m.id)})">
            <div class="form-row-2" style="margin-top:0.75rem;">
              <div class="form-group">
                <label>Стан баку генератора</label>
                <div style="padding:0.65rem 0.85rem; border-radius:0.55rem; border:1px solid rgba(34,197,94,0.45); background:rgba(34,197,94,0.1); font-size:0.88rem;">
                  ✅ <b>Бак повний (100% = ${tankCapVal.toFixed(1)} л)</b> — зафіксовано при завершенні заміру
                </div>
              </div>
              <div class="form-group">
                <label>Примітка комісії (необов'язково)</label>
                <input type="text" id="invNotes" value="${escapeHtml(factData.notes || '')}" placeholder="Коментар щодо результатів інвентаризації">
              </div>
            </div>

            ${stocks.length > 0 ? `
              <h4 style="margin:0.85rem 0 0.45rem; font-size:0.95rem;">📦 Фактичні залишки на складах ГСМ (система автоматично рахує каністри й резерв)</h4>
              <div class="table-container">
                <table id="invStocksTable">
                  <thead><tr><th>Склад ГСМ</th><th>За обліком (л)</th><th>Факт склад (л) *</th><th>Авто-розклад по каністрах та резерву</th></tr></thead>
                  <tbody>
                    ${stocks.map((s) => {
                      const sid = Number(s.stock_id);
                      const fs = factStockMap[sid];
                      const fv = fs ? Number(fs.fact_balance_l) : Number(s.book_balance_l);
                      const sPools = poolsByStock[sid] || [];
                      const previewHtml = _computeStockBreakdownPreview(sPools, fv, Number(s.book_balance_l));
                      return `
                        <tr data-stock-id="${sid}" data-book="${Number(s.book_balance_l)}">
                          <td><b>${escapeHtml(s.stock_name)}</b><div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(s.fuel_type)}</div></td>
                          <td>${Number(s.book_balance_l).toFixed(1)} л</td>
                          <td><input type="number" min="0" step="0.1" class="inv-stock-fact" style="width:115px;" value="${fv.toFixed(1)}" oninput="recalcInvStockRow(this)" required></td>
                          <td class="inv-stock-breakdown">${previewHtml}</td>
                        </tr>`;
                    }).join('')}
                  </tbody>
                </table>
              </div>
            ` : '<div style="font-size:0.84rem; color:var(--text-muted); margin:0.65rem 0;">Активних складів ГСМ не знайдено.</div>'}

            <div style="display:flex; justify-content:space-between; align-items:center; margin:1rem 0 0.5rem;">
              <h4 style="margin:0; font-size:0.95rem;">👥 Склад комісії (мінімум 3 особи)</h4>
              <button type="button" class="btn-oq-chip btn-oq-chip-info" onclick="addCommissionMemberRow()">+ Додати члена</button>
            </div>
            <div id="invCommissionList" style="display:flex; flex-direction:column; gap:0.5rem;">
              ${existingMembers.map((cm, idx) => _renderCommissionRowHtml(cm.role, cm.name, idx)).join('')}
            </div>

            <div style="margin-top:1rem;">
              <button type="submit" class="btn-primary">${isApproval ? '💾 Оновити дані та переформувати PDF-відомість' : '📄 Зафіксувати акт та сформувати PDF-відомість (А4 Альбом)'}</button>
            </div>
          </form>

          ${isApproval ? `
            <div class="offline-edit-box" style="margin-top:1.1rem; padding-top:1rem; border-top:1px solid var(--border-color);">
              <h4 style="margin:0 0 0.6rem; font-size:0.98rem;">📑 Крок 2–3: Підписання та погодження відомості (${escapeHtml(m.statement_number || '')})</h4>
              <div class="offline-toolbar-actions">
                <button type="button" class="btn-secondary btn-oq-toolbar" onclick="downloadMeasurementPdf(${Number(m.id)})">
                  📥 Скачати PDF (А4 Альбом)
                </button>
                <button type="button" id="btnApproveMeasurement" class="btn-primary btn-oq-toolbar" ${!pdfDownloaded ? 'disabled' : ''} onclick="approveMeasurementMode(${Number(m.id)})">
                  ✅ Погоджено (Затвердити)
                </button>
              </div>
              <div style="font-size:0.83rem; color:${pdfDownloaded ? '#4ade80' : '#fbbf24'};">
                ${pdfDownloaded
                  ? `✓ Відомість завантажено (${escapeHtml(formatDateTime(m.document_downloaded_at))}). Після підписання комісією натисніть «✅ Погоджено».`
                  : '⚠️ Спочатку скачайте сформовану PDF-відомість для підпису комісією — після цього активується кнопка «Погоджено».'}
              </div>
            </div>
          ` : ''}
        </div>
      `;
    }
  }

  // History table
  if (historyBody) {
    try {
      const hist = await api(`/measurement/history?facility_id=${encodeURIComponent(currentFacilityId || '')}&limit=30`, { suppressToast: true });
      const stMap = {
        MEASURING: ['badge-running', 'Вимірювання'],
        PENDING_INVENTORY: ['badge-maintenance', 'Очікує інвентаризації'],
        PENDING_APPROVAL: ['badge-maintenance', 'На погодженні'],
        APPROVED: ['badge-stopped', 'Погоджено'],
        CANCELLED: ['badge-faulty', 'Скасовано'],
      };
      window.renderPaginatedTable('measurementHistoryTable', hist, (item) => {
        const [bCls, bLbl] = stMap[item.status] || ['badge', item.status];
        const canPdf = item.status === 'PENDING_APPROVAL' || item.status === 'APPROVED';
        const commText = (item.commission_members || []).map((c) => c.name).filter(Boolean).join(', ') || '-';
        return `
          <tr>
            <td><b>${escapeHtml(item.statement_number || `#${item.id}`)}</b></td>
            <td><span class="badge ${bCls}">${escapeHtml(bLbl)}</span></td>
            <td>${escapeHtml(item.generator_name || '-')}</td>
            <td>${escapeHtml(formatDateTime(item.started_at))}</td>
            <td>${item.total_fuel_consumed_l != null ? `${Number(item.total_fuel_consumed_l).toFixed(1)} л` : `${Number(item.measured_liters_total).toFixed(1)} л`}</td>
            <td>${Number(item.old_nominal_consumption_l_per_h).toFixed(2)} → <b style="color:#4ade80;">${item.calculated_consumption_l_per_h != null ? Number(item.calculated_consumption_l_per_h).toFixed(3) : '-'}</b></td>
            <td style="font-size:0.8rem;">${escapeHtml(commText)}</td>
            <td>${canPdf ? `<button type="button" class="btn-oq-chip btn-oq-chip-info" onclick="downloadMeasurementPdf(${Number(item.id)})">📥 PDF</button>` : (item.cancel_reason ? `<span style="font-size:0.78rem; color:var(--text-muted);" title="${escapeHtml(item.cancel_reason)}">Причина в аудит</span>` : '-')}</td>
          </tr>`;
      }, 8, 'Замірів ще не проводилось', 10);
    } catch (_) {}
  }
};

function _renderCommissionRowHtml(role = '', name = '', idx = 0) {
  return `
    <div class="form-row-2 inv-commission-row" style="align-items:center;">
      <input type="text" class="inv-comm-role" value="${escapeHtml(role)}" placeholder="Посада (напр. Голова комісії)" required>
      <div style="display:flex; gap:0.4rem;">
        <input type="text" class="inv-comm-name" value="${escapeHtml(name)}" placeholder="Прізвище І.П." required style="flex:1;">
        <button type="button" class="btn-oq-chip btn-oq-chip-danger" onclick="removeCommissionMemberRow(this)" title="Прибрати">✕</button>
      </div>
    </div>`;
}

window.addCommissionMemberRow = function () {
  const list = document.getElementById('invCommissionList');
  if (!list) return;
  const idx = list.querySelectorAll('.inv-commission-row').length;
  list.insertAdjacentHTML('beforeend', _renderCommissionRowHtml('Член комісії', '', idx));
};

window.removeCommissionMemberRow = function (btn) {
  const list = document.getElementById('invCommissionList');
  if (!list) return;
  if (list.querySelectorAll('.inv-commission-row').length <= 3) {
    showToast('У складі комісії повинно бути мінімум 3 особи!', 'warning');
    return;
  }
  btn.closest('.inv-commission-row')?.remove();
};

function _computeStockBreakdownPreview(pools, targetVal, bookVal) {
  const val = Math.max(0, Number.isNaN(targetVal) ? 0 : Number(targetVal));
  const diff = val - Number(bookVal || 0);
  const dClr = Math.abs(diff) < 0.01 ? 'var(--text-muted)' : (diff > 0 ? '#4ade80' : '#f87171');
  const diffBadge = `<span style="color:${dClr}; font-size:0.78rem; margin-left:0.3rem;">(${diff >= 0 ? '+' : ''}${diff.toFixed(1)} л)</span>`;

  if (!Array.isArray(pools) || !pools.length) {
    return `<b>${val.toFixed(1)} л</b> (без пулу каністр)${diffBadge}`;
  }

  let maxCap = 0;
  pools.forEach((p) => { maxCap += Number(p.total_count || 0) * Number(p.canister_volume_l || 20); });
  if (val > maxCap + 0.001) {
    return `<span style="color:#f87171; font-weight:600;">⚠️ Перевищує місткість каністр (${maxCap.toFixed(0)} л)</span>`;
  }

  let rem = val;
  const parts = [];
  pools.forEach((p) => {
    const vol = Number(p.canister_volume_l || 20) || 20;
    const total = Number(p.total_count || 0);
    const pMax = total * vol;
    const alloc = Math.min(rem, pMax);
    rem = Math.max(0, rem - alloc);
    const nFull = Math.min(total, Math.floor((alloc + 1e-6) / vol));
    const nRes = Math.max(0, alloc - nFull * vol);
    const freeSlots = total - nFull;
    const nAway = Math.min(Number(p.book_away || 0), freeSlots);
    const nEmpty = Math.max(0, freeSlots - nAway);
    const awayTxt = nAway > 0 ? ` • ${nAway} на АЗС` : '';
    parts.push(`<b>${nFull} повн.</b> × ${vol.toFixed(0)} л + <b style="color:#38bdf8;">${nRes.toFixed(1)} л резерв</b> • ${nEmpty} пор.${awayTxt}`);
  });
  return `${parts.join('; ')}${diffBadge}`;
}

window.recalcInvStockRow = function (el) {
  const tr = el.closest('tr');
  if (!tr) return;
  const sid = Number(tr.getAttribute('data-stock-id'));
  const bookVal = parseFloat(tr.getAttribute('data-book') || '0') || 0;
  const val = parseFloat(el.value || '0');
  const pools = (window._measStockPoolsMap && window._measStockPoolsMap[sid]) || [];
  const cell = tr.querySelector('.inv-stock-breakdown');
  if (cell) {
    cell.innerHTML = _computeStockBreakdownPreview(pools, val, bookVal);
  }
};

window.onMeasStartGenChange = function () {
  const sel = document.getElementById('measStartGenSelect');
  const box = document.getElementById('measStartEligibilityBox');
  const btn = document.getElementById('btnStartMeasurement');
  if (!sel || !box || !btn) return;
  const g = (window._measCandidateGens || []).find((x) => Number(x.id) === Number(sel.value));
  if (!g) return;
  const isFull = Number(g.fuel_tank_level_l) >= Number(g.tank_capacity_l) - 0.1;
  const isStopped = g.status !== 'RUNNING' && g.status !== 'BLOCKED' && g.status !== 'FAULTY';
  const ok = isFull && isStopped;
  btn.disabled = !ok;
  box.style.borderColor = ok ? 'rgba(34,197,94,0.4)' : 'rgba(245,158,11,0.45)';
  box.style.background = ok ? 'rgba(34,197,94,0.1)' : 'rgba(245,158,11,0.1)';
  box.innerHTML = !isStopped
    ? '⚠️ Спочатку зупиніть генератор'
    : (!isFull ? `⚠️ Бак неповний (${Number(g.fuel_tank_level_l).toFixed(1)} / ${Number(g.tank_capacity_l).toFixed(1)} л) — заправте до 100%` : `✅ Бак повний (${Number(g.tank_capacity_l).toFixed(1)} л). Готово до старту!`);
};

window.startMeasurementMode = async function () {
  const genId = parseInt(document.getElementById('measStartGenSelect')?.value || currentGeneratorId || '0', 10);
  if (!genId) return;
  try {
    await api('/measurement/start', {
      method: 'POST',
      body: JSON.stringify({ facility_id: currentFacilityId, generator_id: genId }),
    });
    showToast('📏 Режим вимірювання увімкнено! Ведеться лічильник витрат.', 'success');
    await Promise.allSettled([loadMeasurementTab(), loadAllData()]);
  } catch (_) {}
};

window.finishMeasurementFull = async function (measurementId) {
  const endH = parseFloat(document.getElementById('measFinishEndHours')?.value || '0');
  if (!confirm('Підтверджуєте, що після фінальної заправки бак генератора 100% ПОВНИЙ і контрольний замір завершено?\nЗапуск/зупинка генератора залишаться доступними, а склад ГСМ буде зафіксовано до підписання PDF комісією.')) return;
  try {
    await api(`/measurement/${encodeURIComponent(measurementId)}/finish-full`, {
      method: 'POST',
      body: JSON.stringify({ end_operating_hours: Number.isNaN(endH) ? null : endH }),
    });
    showToast('✅ Бак підтверджено повним! Заповніть залишок складу комісією (мін. 3 особи).', 'warning');
    await Promise.allSettled([loadMeasurementTab(), loadAllData()]);
  } catch (_) {}
};

window.submitMeasurementInventoryForm = async function (e, measurementId) {
  e.preventDefault();
  const notes = document.getElementById('invNotes')?.value.trim() || null;

  const stocks = [];
  document.querySelectorAll('#invStocksTable tbody tr').forEach((tr) => {
    stocks.push({
      stock_id: parseInt(tr.getAttribute('data-stock-id'), 10),
      fact_balance_l: parseFloat(tr.querySelector('.inv-stock-fact')?.value || '0') || 0.0,
    });
  });

  const commission_members = [];
  document.querySelectorAll('#invCommissionList .inv-commission-row').forEach((row) => {
    const role = row.querySelector('.inv-comm-role')?.value.trim() || '';
    const name = row.querySelector('.inv-comm-name')?.value.trim() || '';
    if (role || name) commission_members.push({ role, name });
  });

  if (commission_members.length < 3) {
    showToast('У складі комісії повинно бути щонайменше 3 особи!', 'error');
    return;
  }

  try {
    await api(`/measurement/${encodeURIComponent(measurementId)}/inventory`, {
      method: 'POST',
      body: JSON.stringify({
        tank_full_confirmed: true,
        stocks,
        commission_members,
        notes,
      }),
    });
    showToast('📄 Акт інвентаризації збережено! Скачайте PDF-відомість А4 Альбом.', 'success');
    await loadMeasurementTab();
  } catch (_) {}
};

window.downloadMeasurementPdf = async function (measurementId) {
  try {
    showToast('Формування PDF-відомості (А4 Альбом)...', 'info');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`/api/v1/measurement/${encodeURIComponent(measurementId)}/statement-pdf`, {
      headers,
      credentials: 'same-origin',
    });
    if (!res.ok) {
      let msg = `Помилка генерації PDF (${res.status})`;
      try {
        const j = await res.json();
        msg = extractErrorMessage(j, msg);
      } catch (_) {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Inventory_Statement_${measurementId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    showToast('📥 PDF-відомість завантажено! Кнопка «Погоджено» тепер активна.', 'success');
    await loadMeasurementTab();
  } catch (err) {
    showToast(err.message || 'Помилка завантаження PDF', 'error');
  }
};

window.approveMeasurementMode = async function (measurementId) {
  if (!confirm('Підтверджуєте погодження підписаної відомості, оновлення норми витрат (л/год) та фіксацію фактичних залишків складу (каністри та резерв перераховуються автоматично)?')) return;
  try {
    await api(`/measurement/${encodeURIComponent(measurementId)}/approve`, { method: 'POST' });
    showToast('✅ Погоджено! Фактичний розхід і залишки зафіксовано, система у звичайному режимі.', 'success');
    await Promise.allSettled([loadMeasurementTab(), loadAllData(), loadFuelData()]);
  } catch (_) {}
};

window.openCancelMeasurementModal = async function (measurementId) {
  await window.ViewLoader?.ensureModal('modalMeasurementCancel');
  const idEl = document.getElementById('cancelMeasurementId');
  const reasonEl = document.getElementById('cancelMeasurementReason');
  if (idEl) idEl.value = String(measurementId);
  if (reasonEl) reasonEl.value = '';
  await openModal('modalMeasurementCancel');
};

document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'measurementCancelForm') return;
  e.preventDefault();
  const id = document.getElementById('cancelMeasurementId')?.value;
  const reason = document.getElementById('cancelMeasurementReason')?.value.trim() || '';
  if (reason.length < 5) {
    showToast('Вкажіть змістовну причину аварійного скасування (мін. 5 символів)', 'warning');
    return;
  }
  try {
    await api(`/measurement/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
    closeModal('modalMeasurementCancel');
    showToast('Режим вимірювання аварійно скасовано Суперадміністратором.', 'info');
    await Promise.allSettled([loadMeasurementTab(), loadAllData()]);
  } catch (_) {}
});
