// ==========================================================================
// 🏢 Multi-Facility Network Overview Controller
// ==========================================================================

(function () {
  function genStatusBadgeHtml(status) {
    if (status === 'RUNNING') return '<span class="badge badge-running">ПРАЦЮЄ</span>';
    if (status === 'MAINTENANCE_REQUIRED') return '<span class="badge badge-faulty">ПОТРІБНЕ ТО</span>';
    if (status === 'CRITICAL_FAULT' || status === 'FAULT') return '<span class="badge badge-faulty">НЕСПРАВНІСТЬ</span>';
    return '<span class="badge badge-stopped">ЗУПИНЕНО</span>';
  }

  function alertBadgeHtml(alert) {
    if (!alert) return '';
    const lvl = alert.level || 'green';
    if (lvl === 'red') {
      return `<span class="net-pill net-pill-danger">${escapeHtml(alert.threat_icon || '🚨')} ${escapeHtml(alert.threat_title || 'Тривога')}</span>`;
    }
    if (lvl === 'yellow') {
      return `<span class="net-pill net-pill-warn">${escapeHtml(alert.threat_icon || '🛸')} ${escapeHtml(alert.threat_title || 'Загроза')}</span>`;
    }
    return '<span class="net-pill net-pill-ok">🟢 Без тривоги</span>';
  }

  function weatherBadgeHtml(w) {
    if (!w) return '';
    const temp = w.is_available ? `${escapeHtml(w.icon_emoji || '⛅')} ${escapeHtml(w.temp_formatted || '--')}` : '⛅ —';
    if (w.has_warnings && w.top_warning) {
      const cls = w.max_warning_level === 'red'
        ? 'net-pill-danger'
        : (w.max_warning_level === 'orange' ? 'net-pill-orange' : 'net-pill-warn');
      return `<span class="net-pill ${cls}" title="${escapeHtml(w.top_warning.event || '')}">${temp} · ${escapeHtml(w.top_warning.icon || '⚠️')} ${escapeHtml(w.top_warning.level_ua || 'Попередження')}</span>`;
    }
    return `<span class="net-pill net-pill-neutral">${temp}</span>`;
  }

  window.openNetworkFacility = async function (facilityId, generatorId = null) {
    const facSel = document.getElementById('facilitySelect');
    if (facSel) {
      facSel.value = String(facilityId);
    }
    currentFacilityId = Number(facilityId);
    localStorage.setItem('sd_last_facility_id', String(currentFacilityId));

    if (typeof loadGeneratorsList === 'function') {
      await loadGeneratorsList(currentFacilityId);
    }
    if (generatorId) {
      const genSel = document.getElementById('generatorSelect');
      if (genSel) genSel.value = String(generatorId);
      currentGeneratorId = Number(generatorId);
      localStorage.setItem(`sd_last_generator_${currentFacilityId}`, String(currentGeneratorId));
    }
    if (typeof window.switchTab === 'function') {
      await window.switchTab('tab-dashboard');
    } else if (typeof loadAllData === 'function') {
      await loadAllData();
    }
  };

  window.loadNetworkOverview = async function (force = false) {
    const kpiBox = document.getElementById('networkSummaryKpis');
    const gridBox = document.getElementById('networkFacilitiesGrid');
    if (!gridBox) return;

    try {
      if (force && typeof showToast === 'function') {
        showToast('Оновлення зведення мережі...', 'info');
      }
      const data = await api(`/facilities/overview${force ? `?force=true&_t=${Date.now()}` : ''}`);
      const s = data?.summary || {};
      const items = Array.isArray(data?.facilities) ? data.facilities : [];

      if (kpiBox) {
        const attnCount = Number(s.maintenance_due_count || 0) + Number(s.low_fuel_count || 0) + Number(s.critical_faults_count || 0);
        const extRisks = Number(s.active_air_alerts_count || 0) + Number(s.weather_warnings_count || 0);
        kpiBox.innerHTML = `
          <div class="metric-card">
            <div class="metric-label">Усього об'єктів</div>
            <div class="metric-value">${Number(s.total_facilities || 0)}</div>
            <div class="metric-sub">під контролем</div>
          </div>
          <div class="metric-card" style="border-color: rgba(34, 197, 94, 0.4);">
            <div class="metric-label">Генераторів у роботі</div>
            <div class="metric-value" style="color: ${Number(s.running_generators || 0) > 0 ? '#4ade80' : 'var(--text-primary)'};">${Number(s.running_generators || 0)}</div>
            <div class="metric-sub">активні запуски зараз</div>
          </div>
          <div class="metric-card" style="${attnCount > 0 ? 'border-color: rgba(245, 158, 11, 0.55);' : ''}">
            <div class="metric-label">Потребує уваги</div>
            <div class="metric-value" style="color: ${attnCount > 0 ? '#fbbf24' : '#4ade80'};">${attnCount}</div>
            <div class="metric-sub">ТО: ${Number(s.maintenance_due_count || 0)} · Паливо: ${Number(s.low_fuel_count || 0)} · Крит.: ${Number(s.critical_faults_count || 0)}</div>
          </div>
          <div class="metric-card" style="${extRisks > 0 ? 'border-color: rgba(239, 68, 68, 0.45);' : ''}">
            <div class="metric-label">Тривоги та погода</div>
            <div class="metric-value" style="color: ${extRisks > 0 ? '#f87171' : '#4ade80'};">${extRisks}</div>
            <div class="metric-sub">Повітр.: ${Number(s.active_air_alerts_count || 0)} · Шторм УкрГМЦ: ${Number(s.weather_warnings_count || 0)}</div>
          </div>
        `;
      }

      if (items.length === 0) {
        gridBox.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 2rem;">Доступні об\'єкти відсутні.</div>';
        return;
      }

      gridBox.innerHTML = items.map((fac) => {
        const gensHtml = (fac.generators && fac.generators.length > 0)
          ? fac.generators.map((g) => {
              const maintColor = g.is_maint_overdue ? '#f87171' : (g.is_maint_due ? '#fbbf24' : '#4ade80');
              const maintText = g.is_maint_overdue
                ? `Прострочено (${formatHoursCounter(Math.abs(g.hours_to_maintenance))})`
                : `${formatHoursCounter(g.hours_to_maintenance)}`;
              return `
                <div class="net-gen-box">
                  <div class="net-gen-head">
                    <div>
                      <strong>⚡ ${escapeHtml(g.name)}</strong>
                      <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(g.model || '')} · ${formatHoursCounter(g.current_operating_hours)}</div>
                    </div>
                    ${genStatusBadgeHtml(g.status)}
                  </div>
                  <div class="net-gen-metrics">
                    <div>
                      <span class="net-m-lbl">Бак:</span>
                      <b>${escapeHtml(formatLiters(g.fuel_tank_level_l))}</b>
                      <small style="color: var(--text-muted);">(${Number(g.fuel_percent || 0)}% з ${Number(g.tank_capacity_l || 0)} л)</small>
                    </div>
                    <div>
                      <span class="net-m-lbl">До ТО:</span>
                      <b style="color: ${maintColor};">${maintText}</b>
                    </div>
                  </div>
                </div>
              `;
            }).join('')
          : '<div style="font-size: 0.85rem; color: var(--text-muted); padding: 0.5rem 0;">Генератори ще не додані</div>';

        const measPill = fac.measurement_status
          ? '<span class="net-pill net-pill-warn">📏 Замір / Інвентаризація</span>'
          : '';
        const faultPill = fac.open_faults_count > 0
          ? `<span class="net-pill ${fac.critical_faults_count > 0 ? 'net-pill-danger' : 'net-pill-warn'}">⚠️ Дефектів: ${Number(fac.open_faults_count)}</span>`
          : '';

        const firstGenId = (fac.generators && fac.generators[0]) ? Number(fac.generators[0].id) : 'null';

        return `
          <div class="network-facility-card">
            <div class="net-fac-header">
              <div>
                <h4 style="margin: 0 0 0.15rem 0;">🏢 ${escapeHtml(fac.name)}</h4>
                <small style="color: var(--text-muted);">${escapeHtml(fac.city || fac.address || 'Локація не вказана')}</small>
              </div>
              <button type="button" class="btn-primary" style="padding: 0.4rem 0.85rem; font-size: 0.82rem; min-height: auto;" onclick="openNetworkFacility(${Number(fac.id)}, ${firstGenId})">Відкрити →</button>
            </div>

            <div class="net-fac-pills">
              ${alertBadgeHtml(fac.alert)}
              ${weatherBadgeHtml(fac.weather)}
              ${faultPill}
              ${measPill}
            </div>

            <div class="net-fac-stock-row">
              <span>🛢️ Склад ПММ: <b>${escapeHtml(formatLiters(fac.stock_balance_l))}</b></span>
              <span>🧴 Каністри: <b>${Number(fac.canisters_full || 0)} / ${Number(fac.canisters_total || 0)} повн.</b></span>
            </div>

            <div class="net-fac-gens">
              ${gensHtml}
            </div>
          </div>
        `;
      }).join('');
    } catch (err) {
      gridBox.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; color: #f87171; padding: 1.5rem;">Не вдалося завантажити зведення мережі: ${escapeHtml(err.message || '')}</div>`;
    }
  };
})();
