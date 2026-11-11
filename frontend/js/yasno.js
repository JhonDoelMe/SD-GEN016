// ===========================================================================
// YASNO Outage Schedule Functions
// ===========================================================================
window.loadFacilityOutageSchedule = async function(facilityId = null, forceRefresh = false) {
  const facId = facilityId || currentFacilityId;
  const card = document.getElementById('yasnoScheduleCard');
  if (!card) return;

  if (!facId) {
    card.style.display = 'none';
    return;
  }

  try {
    const tsBuster = Date.now();
    const url = `/facilities/${facId}/outage-schedule?_t=${tsBuster}${forceRefresh ? '&force_refresh=true' : ''}`;
    const data = await api(url);
    if (!data || !data.enabled || !data.configured) {
      window._yasnoLastData = data || null;
      card.style.display = 'none';
      if (typeof window.updateFuelAssessmentBlock === 'function') {
        window.updateFuelAssessmentBlock();
      }
      return;
    }

    card.style.display = 'block';

    // Title & Subtitle
    const titleEl = document.getElementById('yasnoCardTitle');
    if (titleEl) titleEl.innerText = 'Графік відключень YASNO';
    const subEl = document.getElementById('yasnoCardSubtitle');
    if (subEl) subEl.innerText = `${data.dso_name || 'ОСР'} • Черга ${data.group} (${data.facility_name})`;

    // Status Badge
    const badgeEl = document.getElementById('yasnoStatusBadge');
    if (badgeEl) {
      badgeEl.innerText = data.status_label || 'СВІТЛО Є 🟢';
      badgeEl.className = `badge badge-${data.status_color || 'success'}`;
    }

    // Message
    const msgEl = document.getElementById('yasnoStatusMessage');
    if (msgEl) msgEl.innerText = data.message || 'Електропостачання в нормі';

    // Next Outage Badge
    const nextEl = document.getElementById('yasnoNextOutageBadge');
    if (nextEl) {
      if (data.next_outage) {
        nextEl.style.display = 'inline-block';
        const dayWord = data.next_outage.day === 'today' ? 'сьогодні' : 'завтра';
        nextEl.innerHTML = `Наступне знеструмлення: <b>${data.next_outage.start} — ${data.next_outage.end}</b> (${dayWord}, через ${data.next_outage.human_until})`;
      } else {
        nextEl.style.display = 'inline-block';
        nextEl.innerHTML = 'Відключень не заплановано ✨';
      }
    }

    // 24h Timeline bar
    window._yasnoLastData = data;
    const hasTomorrowOutages = Array.isArray(data.timeline_tomorrow) && data.timeline_tomorrow.some(h => h.status === 'DEFINITE' || h.status === 'PROBABLE');
    const defaultDay = data.timeline_day || ((data.next_outage && data.next_outage.day === 'tomorrow' && hasTomorrowOutages) ? 'tomorrow' : 'today');
    window.renderYasnoTimeline(defaultDay);
    if (typeof window.updateFuelAssessmentBlock === 'function') {
      window.updateFuelAssessmentBlock();
    }

    // Indicator of current hour
    const curHourInd = document.getElementById('yasnoCurrentHourIndicator');
    if (curHourInd) {
      const now = new Date();
      const nowH = String(now.getHours()).padStart(2, '0');
      const nowM = String(now.getMinutes()).padStart(2, '0');
      curHourInd.innerText = `Зараз: ${nowH}:${nowM}`;
    }

    // Updated Time
    const updEl = document.getElementById('yasnoUpdatedTime');
    if (updEl) {
      const checkDt = data.checked_at ? new Date(data.checked_at) : new Date();
      const checkTimeStr = checkDt.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' });

      let yasnoInfo = '';
      const yasnoTimeRaw = data.yasno_updated_on || data.updated_at;
      if (yasnoTimeRaw) {
        try {
          const dtY = new Date(yasnoTimeRaw);
          const yTime = dtY.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' });
          yasnoInfo = ` <span style="opacity: 0.85; margin-left: 0.35rem;">• Розклад YASNO від ${yTime}</span>`;
        } catch (_) {}
      }

      updEl.innerHTML = `<span title="Час останньої синхронізації з сервером">Перевірено: <b>${checkTimeStr}</b></span>${yasnoInfo}`;
    }
  } catch (err) {
    console.warn('Failed to load YASNO outage schedule:', err);
    throw err;
  }
};

window.refreshYasnoSchedule = async function(force = false) {
  if (!currentFacilityId) return;
  const btn = document.getElementById('btnRefreshYasno');
  if (btn) btn.classList.add('spinning');

  try {
    await loadFacilityOutageSchedule(currentFacilityId, force);
    if (force) {
      const now = new Date();
      const nowStr = now.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' });
      showToast(`Графік YASNO перевірено (${nowStr}) — дані актуальні`, 'info');
    }
  } catch (err) {
    if (force) {
      showToast('Не вдалося оновити графік YASNO. Спробуйте пізніше', 'error');
    }
  } finally {
    if (btn) btn.classList.remove('spinning');
  }
};


window._parseHhMmToMinutes = function(str) {
  if (!str || typeof str !== 'string' || !str.includes(':')) return null;
  const parts = str.split(':').map(Number);
  if (parts.length < 2 || Number.isNaN(parts[0]) || Number.isNaN(parts[1])) return null;
  return parts[0] * 60 + parts[1];
};

window.updateYasnoFuelReadiness = function(liveTankOverride = null) {
  if (typeof window.updateFuelAssessmentBlock === 'function') {
    window.updateFuelAssessmentBlock(liveTankOverride);
  }
};

window.switchYasnoTimelineDay = function(day) {
  window.renderYasnoTimeline(day);
};

window.renderYasnoTimeline = function(day = 'today') {
  const data = window._yasnoLastData;
  if (!data) return;

  const hasTomorrow = Array.isArray(data.timeline_tomorrow) && data.timeline_tomorrow.length === 24;
  const activeDay = (day === 'tomorrow' && hasTomorrow) ? 'tomorrow' : 'today';

  const labelEl = document.getElementById('yasnoTimelineLabel');
  if (labelEl) {
    labelEl.innerText = activeDay === 'tomorrow' ? '24-годинна шкала на завтра:' : '24-годинна шкала на сьогодні:';
  }

  const switchEl = document.getElementById('yasnoDaySwitch');
  if (switchEl) {
    switchEl.style.display = hasTomorrow ? 'inline-flex' : 'none';
  }
  const btnToday = document.getElementById('btnYasnoDayToday');
  const btnTomorrow = document.getElementById('btnYasnoDayTomorrow');
  if (btnToday) btnToday.classList.toggle('active', activeDay === 'today');
  if (btnTomorrow) btnTomorrow.classList.toggle('active', activeDay === 'tomorrow');

  const barEl = document.getElementById('yasnoTimelineBar');
  const sourceTimeline = activeDay === 'tomorrow' ? data.timeline_tomorrow : data.timeline_today;
  if (!barEl || !Array.isArray(sourceTimeline)) return;

  const hasMarkedHours = sourceTimeline.some(h => h.status === 'DEFINITE' || h.status === 'PROBABLE');
  let fallbackStartMin = null;
  let fallbackEndMin = null;
  let fallbackStatus = null;
  if (!hasMarkedHours && data.next_outage && data.next_outage.day === activeDay) {
    fallbackStartMin = window._parseHhMmToMinutes(data.next_outage.start);
    fallbackEndMin = window._parseHhMmToMinutes(data.next_outage.end);
    fallbackStatus = (String(data.next_outage.type || '').toLowerCase() === 'probable') ? 'PROBABLE' : 'DEFINITE';
  }

  const renderSig = `${activeDay}|${fallbackStartMin}|${fallbackEndMin}|${fallbackStatus}|` +
    sourceTimeline.map(h => `${h.hour}:${h.status}:${h.is_current ? 1 : 0}`).join(',');
  if (barEl.dataset.renderSig === renderSig) return;
  barEl.dataset.renderSig = renderSig;

  barEl.innerHTML = sourceTimeline.map(h => {
    let status = h.status;
    if (status === 'NOT_PLANNED' && fallbackStartMin !== null && fallbackEndMin !== null) {
      const hStart = h.hour * 60;
      const hEnd = (h.hour + 1) * 60;
      if (Math.max(fallbackStartMin, hStart) < Math.min(fallbackEndMin, hEnd)) {
        status = fallbackStatus;
      }
    }

    let cls = 'cell-not-planned';
    let tooltip = `${h.time_range}: Світло є 🟢`;
    if (status === 'DEFINITE') {
      cls = 'cell-definite';
      tooltip = `${h.time_range}: Планове відключення 🔴`;
    } else if (status === 'PROBABLE') {
      cls = 'cell-probable';
      tooltip = `${h.time_range}: Можливе відключення 🟡`;
    }
    if (h.is_current) cls += ' cell-current';

    return `<div class="yasno-hour-cell ${cls}" title="${tooltip}">
      <span class="hour-label">${h.label}</span>
      ${h.is_current ? '<span class="current-dot"></span>' : ''}
    </div>`;
  }).join('');
};

