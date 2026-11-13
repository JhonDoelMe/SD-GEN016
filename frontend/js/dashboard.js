// Load All Dashboard Data (parallelized after facility & generator selection)
async function loadAllData() {
  if (!currentFacilityId) {
    await loadFacilitiesList();
  }
  if (!currentGeneratorId) {
    await loadGeneratorsList(currentFacilityId);
  }

  const tasks = [
    loadGeneratorData(),
    loadRecentRuns(),
    loadFacilityOutageSchedule(currentFacilityId),
    loadFacilityIndicators(currentFacilityId)
  ];

  if (typeof window.loadMeasurementStatus === 'function') {
    tasks.push(window.loadMeasurementStatus());
  }

  if (!isViewerOnly() && hasPermission('fuel:view')) {
    tasks.push(loadFuelSummary());
  } else {
    window._lastFuelSummary = null;
    const cardStock = document.getElementById('cardStock');
    if (cardStock) cardStock.innerText = '-';
    const cardStockSub = document.getElementById('cardStockSub');
    if (cardStockSub) cardStockSub.innerText = 'обмежений доступ';
  }

  if (!isViewerOnly() && hasPermission('maintenance:view')) {
    tasks.push(loadMaintenanceSummary());
  } else {
    const cardMaintRem = document.getElementById('cardMaintRem');
    if (cardMaintRem) cardMaintRem.innerHTML = `- <small style="font-size:0.9rem;">год</small>`;
    const cardMaintSub = document.getElementById('cardMaintSub');
    if (cardMaintSub) cardMaintSub.innerText = `доступно для оператора`;
  }

  await Promise.allSettled(tasks);
  if (typeof window.applyMeasurementTankDecor === 'function') {
    window.applyMeasurementTankDecor();
  }
  applyRolePermissionsUI();
}

// Lightweight KPI Summary Loaders (keeps Fuel & Operations modules lazy-loaded)
window.loadFuelSummary = async function () {
  if (isViewerOnly() || !hasPermission('fuel:view')) return;
  try {
    const params = [];
    if (currentFacilityId) params.push(`facility_id=${encodeURIComponent(currentFacilityId)}`);
    if (currentGeneratorId) params.push(`generator_id=${encodeURIComponent(currentGeneratorId)}`);
    const q = params.length ? '?' + params.join('&') : '';

    const s = await api(`/fuel/summary${q}`);
    window._lastFuelSummary = s;
    const cardStock = document.getElementById('cardStock');
    if (cardStock) cardStock.innerText = s.warehouse_balance_l.toFixed(1).replace('.', ',');
    const stockSub = document.getElementById('cardStockSub');
    if (stockSub) {
      const cTotal = Number(s.canisters_total || 0);
      const cFull = Number(s.canisters_full || 0);
      const cMod10 = cTotal % 10;
      const cMod100 = cTotal % 100;
      const canisterWord = (cMod10 === 1 && cMod100 !== 11)
        ? 'каністра'
        : (cMod10 >= 2 && cMod10 <= 4 && (cMod100 < 10 || cMod100 >= 20))
          ? 'каністри'
          : 'каністр';
      stockSub.innerText = cTotal > 0
        ? `${cFull}/${cTotal} повн. ${canisterWord}`
        : 'залишок палива';
    }
    const fuelStockBal = document.getElementById('fuelStockBal');
    if (fuelStockBal) fuelStockBal.innerText = formatLiters(s.warehouse_balance_l);
    const fuelTankBal = document.getElementById('fuelTankBal');
    if (fuelTankBal) fuelTankBal.innerText = formatLiters(s.tank_balance_l);
    const fuelTotalBought = document.getElementById('fuelTotalBought');
    if (fuelTotalBought) fuelTotalBought.innerText = formatLiters(s.total_received_l);
    const fuelTotalSpent = document.getElementById('fuelTotalSpent');
    if (fuelTotalSpent) fuelTotalSpent.innerText = formatMoney(s.total_spent_uah);
    const fuelAvgPrice = document.getElementById('fuelAvgPrice');
    if (fuelAvgPrice) fuelAvgPrice.innerText = formatPricePerLiter(s.avg_price_per_liter);

    if (typeof window.updateFuelAssessmentBlock === 'function') {
      window.updateFuelAssessmentBlock();
    }
  } catch (_) {}
};

window.loadMaintenanceSummary = async function () {
  if (isViewerOnly() || !hasPermission('maintenance:view')) return;
  const setText = (id, txt) => { const el = document.getElementById(id); if (el) el.innerText = txt; };
  try {
    if (!currentGeneratorId) {
      const cardRem = document.getElementById('cardMaintRem');
      if (cardRem) cardRem.innerHTML = `0,0 <small style="font-size:0.9rem;">год</small>`;
      setText('cardMaintSub', 'генератор не вибрано');
      setText('maintInterval', '-');
      setText('maintLast', '-');
      setText('maintNext', '-');
      setText('maintRemaining', '-');
      const prog = document.getElementById('maintProgress');
      if (prog) prog.style.width = '0%';
      return;
    }
    const q = `?generator_id=${currentGeneratorId}`;
    const m = await api(`/maintenance/schedule${q}`);
    cachedMaintenanceSchedule = m;
    const cardRem = document.getElementById('cardMaintRem');
    if (cardRem) cardRem.innerHTML = `${m.hours_remaining.toFixed(1).replace('.', ',')} <small style="font-size:0.9rem;">год</small>`;
    setText('cardMaintSub', `план: ${formatHoursCounter(m.next_due_hours)}`);
    setText('maintInterval', `${formatHoursCounter(m.interval_hours)}`);
    setText('maintLast', `${formatHoursCounter(m.last_performed_hours)}`);
    setText('maintNext', `${formatHoursCounter(m.next_due_hours)}`);
    setText('maintRemaining', `${formatHoursCounter(m.hours_remaining)}`);

    const remSpan = document.getElementById('maintRemaining');
    if (remSpan) {
      if (m.is_overdue) {
        remSpan.style.color = '#ef4444';
        remSpan.innerText += ' (ПРОСТРОЧЕНО!)';
      } else if (m.is_due) {
        remSpan.style.color = '#f59e0b';
        remSpan.innerText += ' (СКОРО ТО)';
      } else {
        remSpan.style.color = '#22c55e';
      }
    }

    const workedInCycle = m.current_operating_hours - m.last_performed_hours;
    const progressPct = Math.min(100, Math.max(0, Math.round((workedInCycle / m.interval_hours) * 100)));
    const prog = document.getElementById('maintProgress');
    if (prog) prog.style.width = `${progressPct}%`;
  } catch (_) {}
};

window.loadRecentRuns = async function () {
  try {
    const tbody = document.querySelector('#recentRunsTable tbody');
    if (!tbody) return;
    const q = currentGeneratorId ? '&generator_id=' + encodeURIComponent(currentGeneratorId) : '';
    const runs = await api('/generator/runs?limit=5' + q);
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
};

// 1. Generator Data
async function loadGeneratorData() {
  if (!currentGeneratorId) {
    currentGenerator = null;
    const nameEl = document.getElementById('genName');
    if (nameEl) nameEl.innerText = "Немає генератора";
    const modelEl = document.getElementById('genModel');
    if (modelEl) modelEl.innerText = "На обраному об'єкті ще немає генераторів. Додайте його в меню ⚙️ Адміністрування → Об'єкти та Генератори.";
    const cardHours = document.getElementById('cardHours');
    if (cardHours) cardHours.innerText = "0,0";
    const cardTank = document.getElementById('cardTank');
    if (cardTank) cardTank.innerText = "0,0";
    const cardTankCapSub = document.getElementById('cardTankCapSub');
    if (cardTankCapSub) cardTankCapSub.innerText = "немає генератора";
    if (typeof window.updateFuelAssessmentBlock === 'function') {
      window.updateFuelAssessmentBlock();
    }
    const badge = document.getElementById('genStatusBadge');
    if (badge) {
      badge.className = 'badge';
      badge.innerText = 'ВІДСУТНІЙ';
    }
    const btn = document.getElementById('mainActionBtn');
    if (btn) {
      btn.className = 'btn-hero btn-disabled-role';
      btn.disabled = true;
      btn.innerHTML = '<span>➕</span><span>ДОДАЙТЕ ГЕНЕРАТОР В АДМІНЦІ</span>';
      btn.title = "Перейдіть у меню ⚙️ Адміністрування → Об'єкти та Генератори";
    }
    return;
  }
  try {
    const qGenParam = `?generator_id=${encodeURIComponent(currentGeneratorId)}`;
    const [genData, activeRunData] = await Promise.all([
      api(`/generator${qGenParam}`),
      api(`/generator/active-run${qGenParam}`).catch(() => null)
    ]);
    currentGenerator = genData;
    if (!currentGenerator) return;
    currentGeneratorId = currentGenerator.id;
    const sel = document.getElementById('generatorSelect');
    if (sel && sel.value != currentGeneratorId) {
      sel.value = currentGeneratorId;
    }

    document.getElementById('genName').innerText = currentGenerator.name;
    const ratedKw = Number(currentGenerator.rated_power_kw || 0).toFixed(1).replace(/\.0$/, '').replace('.', ',');
    document.getElementById('genModel').innerText = `Модель: ${currentGenerator.model} | Серійний: ${currentGenerator.serial_number} | Потужність: ${ratedKw} кВт`;
    document.getElementById('cardHours').innerText = currentGenerator.current_operating_hours.toFixed(1).replace('.', ',');

    const fuelL = currentGenerator.fuel_tank_level_l;
    const cardTank = document.getElementById('cardTank');
    const tankProgress = document.getElementById('tankProgress');
    const cardTankCapSub = document.getElementById('cardTankCapSub');

    cardTank.innerText = fuelL.toFixed(1).replace('.', ',');
    const cap = currentGenerator.tank_capacity_l || 25.0;
    const inMeas = !!(window._measurementState && window._measurementState.is_measuring);
    if (fuelL < 0) {
      if (inMeas) {
        cardTank.style.color = '#38bdf8';
        if (tankProgress) tankProgress.style.width = '0%';
        if (cardTankCapSub) {
          cardTankCapSub.innerHTML = `<span style="color: #38bdf8; font-weight: 600;">📏 Режим заміру (попередження вимкнено)</span>`;
        }
      } else {
        cardTank.style.color = '#ef4444';
        if (tankProgress) tankProgress.style.width = '0%';
        if (cardTankCapSub) {
          cardTankCapSub.innerHTML = `<span style="color: #ef4444; font-weight: 600;">Дефіцит: ${formatLiters(Math.abs(fuelL))}</span>`;
        }
      }
    } else {
      cardTank.style.color = 'inherit';
      const pct = Math.min(100, Math.max(0, Math.round((fuelL / cap) * 100)));
      if (tankProgress) tankProgress.style.width = `${pct}%`;
      if (cardTankCapSub) {
        cardTankCapSub.innerText = (inMeas && fuelL <= 0)
          ? `0,0 з ${cap.toFixed(1).replace('.', ',')} л • 📏 Режим заміру`
          : `з ${cap.toFixed(1).replace('.', ',')} л (${pct}%)`;
      }
    }

    // Status Badge & Action Button
    const badge = document.getElementById('genStatusBadge');
    const btn = document.getElementById('mainActionBtn');
    const banner = document.getElementById('activeRunBanner');
    const btnTransfer = document.getElementById('btnQuickTransfer');

    const isFuelDeficit = (fuelL <= 0) && !inMeas;
    const canStartOrStop = !isViewerOnly() && hasPermission('generator:start');

    badge.className = 'badge';
    if (currentGenerator.status === 'RUNNING') {
      badge.classList.add('badge-running');
      badge.innerText = 'ПРАЦЮЄ';
      btn.className = 'btn-hero btn-stop' + (canStartOrStop ? '' : ' btn-disabled-role');
      btn.disabled = !canStartOrStop;
      btn.innerHTML = '<span>⏹</span><span>ЗУПИНИТИ ГЕНЕРАТОР</span>';
      if (!canStartOrStop) {
        btn.title = 'Керування генератором недоступне для поточної ролі';
      } else {
        btn.removeAttribute('title');
      }
    } else if (currentGenerator.status === 'MAINTENANCE_REQUIRED') {
      badge.classList.add('badge-maintenance');
      badge.innerText = 'ПОТРІБНЕ ТО';
      btn.className = 'btn-hero btn-start' + (isFuelDeficit ? ' btn-fuel-warning' : '') + (canStartOrStop ? '' : ' btn-disabled-role');
      btn.disabled = !canStartOrStop;
      btn.innerHTML = isFuelDeficit
        ? '<span style="font-size: 1.35rem;">⚠️</span><span style="font-size: 1.4rem;">▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>'
        : '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
      if (!canStartOrStop) {
        btn.title = 'Керування генератором недоступне для поточної ролі';
      } else if (isFuelDeficit) {
        btn.title = 'Увага: у баку за обліком 0 л (дефіцит)! Запуск дозволено за фактичним залишком палива.';
      } else {
        btn.removeAttribute('title');
      }
    } else if (currentGenerator.status === 'FAULTY') {
      badge.classList.add('badge-faulty');
      badge.innerText = 'НЕСПРАВНИЙ';
      btn.className = 'btn-hero btn-start' + (canStartOrStop ? '' : ' btn-disabled-role');
      btn.disabled = !canStartOrStop;
      btn.innerHTML = '<span>⚠️</span><span>НЕСПРАВНІСТЬ (БЛОК)</span>';
      if (!canStartOrStop) {
        btn.title = 'Керування генератором недоступне для поточної ролі';
      } else {
        btn.title = 'Генератор у статусі несправності. Усуньте несправність перед запуском.';
      }
    } else if (currentGenerator.status === 'BLOCKED') {
      badge.classList.add('badge-blocked');
      badge.innerText = 'ЗАБЛОКОВАНО';
      btn.className = 'btn-hero btn-start' + (canStartOrStop ? '' : ' btn-disabled-role');
      btn.disabled = !canStartOrStop;
      btn.innerHTML = '<span>🔒</span><span>ЗАБЛОКОВАНО</span>';
      if (!canStartOrStop) {
        btn.title = 'Керування генератором недоступне для поточної ролі';
      } else {
        btn.title = 'Генератор заблокований адміністратором або графіком роботи.';
      }
    } else {
      badge.classList.add('badge-stopped');
      badge.innerText = 'ЗУПИНЕНО';
      btn.className = 'btn-hero btn-start' + (isFuelDeficit ? ' btn-fuel-warning' : '') + (canStartOrStop ? '' : ' btn-disabled-role');
      btn.disabled = !canStartOrStop;
      btn.innerHTML = isFuelDeficit
        ? '<span style="font-size: 1.35rem;">⚠️</span><span style="font-size: 1.4rem;">▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>'
        : '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
      if (!canStartOrStop) {
        btn.title = 'Керування генератором недоступне для поточної ролі';
      } else if (isFuelDeficit) {
        btn.title = 'Увага: у баку за обліком 0 л (дефіцит)! Запуск дозволено за фактичним залишком палива.';
      } else {
        btn.removeAttribute('title');
      }
    }

    if (currentGenerator.status !== 'RUNNING') {
      const serverRem = parseInt(currentGenerator.cooldown_remaining_seconds, 10) || 0;
      if (serverRem > 0 && currentCooldownSeconds <= 0) {
        startCooldownTimer(serverRem);
      } else if (currentCooldownSeconds > 0) {
        btn.disabled = true;
        btn.className = 'btn-hero btn-cooldown';
        btn.innerHTML = `<span>⏳</span><span>ОХОЛОДЖЕННЯ: ${currentCooldownSeconds} с</span>`;
        btn.title = `Захист від випадкового/передчасного запуску. Повторний запуск буде доступний через ${currentCooldownSeconds} с (технологічна пауза 60 с).`;
      }
    } else {
      if (cooldownTimerInterval) {
        clearInterval(cooldownTimerInterval);
        cooldownTimerInterval = null;
      }
      currentCooldownSeconds = 0;
    }

    if (btnTransfer) {
      if (isFuelDeficit && !isViewerOnly() && hasPermission('fuel:transfer')) {
        btnTransfer.classList.add('btn-action-refuel-highlight');
      } else {
        btnTransfer.classList.remove('btn-action-refuel-highlight');
      }
    }

    // Active Run Check
    const btnManual = document.getElementById('btnOpenManualRun');
    if (btnManual) {
      btnManual.style.display = (currentGenerator && currentGenerator.status === 'RUNNING' ? 'none' : 'inline-flex');
    }

    activeRun = activeRunData;
    if (activeRun) {
      banner.style.display = 'block';
      document.getElementById('activeRunStart').innerText = formatTime(activeRun.start_time);
      document.getElementById('activeRunHours').innerText = activeRun.start_hours.toFixed(1).replace('.', ',');
      startRunStopwatch();
    } else {
      banner.style.display = 'none';
      stopRunStopwatch();
    }
    if (typeof window.updateOperationalSafetyBanners === 'function') {
      window.updateOperationalSafetyBanners();
    }
    if (typeof window.updateFuelAssessmentBlock === 'function') {
      window.updateFuelAssessmentBlock();
    }
    applyRolePermissionsUI();
  } catch (_) {}
}

let runTimerInterval = null;
let cooldownTimerInterval = null;
let currentCooldownSeconds = 0;

function startCooldownTimer(seconds) {
  if (cooldownTimerInterval) {
    clearInterval(cooldownTimerInterval);
    cooldownTimerInterval = null;
  }
  currentCooldownSeconds = Math.max(0, parseInt(seconds, 10) || 0);
  if (currentCooldownSeconds <= 0) return;

  const updateCooldownButton = () => {
    const btn = document.getElementById('mainActionBtn');
    if (!btn) return;
    if (currentGenerator && currentGenerator.status === 'RUNNING') {
      if (cooldownTimerInterval) {
        clearInterval(cooldownTimerInterval);
        cooldownTimerInterval = null;
      }
      currentCooldownSeconds = 0;
      return;
    }
    if (currentCooldownSeconds > 0) {
      btn.disabled = true;
      btn.className = 'btn-hero btn-cooldown';
      btn.innerHTML = `<span>⏳</span><span>ОХОЛОДЖЕННЯ: ${currentCooldownSeconds} с</span>`;
      btn.title = `Захист від випадкового/передчасного запуску. Повторний запуск буде доступний через ${currentCooldownSeconds} с (технологічна пауза 60 с).`;
    } else {
      if (cooldownTimerInterval) {
        clearInterval(cooldownTimerInterval);
        cooldownTimerInterval = null;
      }
      currentCooldownSeconds = 0;
      btn.disabled = false;
      btn.removeAttribute('title');
      if (currentGenerator) {
        const isFuelDeficit = (currentGenerator.fuel_tank_level_l <= 0);
        if (currentGenerator.status === 'MAINTENANCE_REQUIRED') {
          btn.className = 'btn-hero btn-start' + (isFuelDeficit ? ' btn-fuel-warning' : '');
          btn.innerHTML = isFuelDeficit
            ? '<span style="font-size: 1.35rem;">⚠️</span><span style="font-size: 1.4rem;">▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>'
            : '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
        } else if (currentGenerator.status === 'FAULTY') {
          btn.className = 'btn-hero btn-start';
          btn.innerHTML = '<span>⚠️</span><span>НЕСПРАВНІСТЬ (БЛОК)</span>';
        } else if (currentGenerator.status === 'BLOCKED') {
          btn.className = 'btn-hero btn-start';
          btn.innerHTML = '<span>🔒</span><span>ЗАБЛОКОВАНО</span>';
        } else {
          btn.className = 'btn-hero btn-start' + (isFuelDeficit ? ' btn-fuel-warning' : '');
          btn.innerHTML = isFuelDeficit
            ? '<span style="font-size: 1.35rem;">⚠️</span><span style="font-size: 1.4rem;">▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>'
            : '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
        }
      }
    }
  };

  updateCooldownButton();
  cooldownTimerInterval = setInterval(() => {
    currentCooldownSeconds--;
    updateCooldownButton();
  }, 1000);
}

let cachedMaintenanceSchedule = null;

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

  const elapsedHours = elapsedSeconds / 3600.0;
  const nominal = (currentGenerator && currentGenerator.nominal_consumption_l_per_h) || 2.2;
  const estConsumed = elapsedHours * nominal;

  const modalEstFuel = document.getElementById('stopEstFuelDisplay');
  if (modalEstFuel) {
    modalEstFuel.innerText = formatLiters(estConsumed);
  }

  // Live dynamic update of the 4 dashboard tiles during active run
  if (currentGenerator && currentGenerator.status === 'RUNNING') {
    // 1. Live Operating Hours (accumulative)
    const startH = activeRun.start_hours ?? currentGenerator.current_operating_hours;
    const liveHours = startH + elapsedHours;
    const cardHours = document.getElementById('cardHours');
    if (cardHours) cardHours.innerText = liveHours.toFixed(1).replace('.', ',');

    // 2. Live Tank Level (factual % in KPI card; autonomy estimate renders in #fuelAssessmentPanel)
    const startFuel = activeRun.start_fuel_level_l ?? activeRun.start_fuel ?? currentGenerator.fuel_tank_level_l;
    const liveTank = startFuel - estConsumed;
    const cardTank = document.getElementById('cardTank');
    const tankProgress = document.getElementById('tankProgress');
    const cardTankCapSub = document.getElementById('cardTankCapSub');

    if (cardTank) {
      cardTank.innerText = liveTank.toFixed(1).replace('.', ',');
      const btnTransfer = document.getElementById('btnQuickTransfer');
      const cap = currentGenerator.tank_capacity_l || 25.0;
      const inMeas = !!(window._measurementState && window._measurementState.is_measuring);
      if (liveTank <= 0) {
        if (inMeas) {
          cardTank.style.color = '#38bdf8';
          if (tankProgress) tankProgress.style.width = '0%';
          if (cardTankCapSub) {
            cardTankCapSub.innerHTML = `<span style="color: #38bdf8; font-weight: 600;">📏 Режим заміру (порожній бак ігнор.)</span>`;
          }
          if (btnTransfer) btnTransfer.classList.remove('btn-action-refuel-highlight');
        } else {
          cardTank.style.color = '#ef4444';
          if (tankProgress) tankProgress.style.width = '0%';
          if (cardTankCapSub) {
            cardTankCapSub.innerHTML = liveTank < 0
              ? `<span style="color: #ef4444; font-weight: 600;">Дефіцит: ${formatLiters(Math.abs(liveTank))}</span>`
              : `<span style="color: var(--text-muted);">з ${cap.toFixed(1).replace('.', ',')} л (0%)</span>`;
          }
          if (btnTransfer && !isViewerOnly() && hasPermission('fuel:transfer')) {
            btnTransfer.classList.add('btn-action-refuel-highlight');
          }
        }
      } else {
        cardTank.style.color = 'inherit';
        const pct = Math.min(100, Math.max(0, Math.round((liveTank / cap) * 100)));
        if (tankProgress) tankProgress.style.width = `${pct}%`;
        if (cardTankCapSub) {
          cardTankCapSub.innerText = `з ${cap.toFixed(1).replace('.', ',')} л (${pct}%)`;
        }
        if (btnTransfer) {
          btnTransfer.classList.remove('btn-action-refuel-highlight');
        }
      }
    }

    // 3. Live Maintenance countdown
    const cardMaintRem = document.getElementById('cardMaintRem');
    const cardMaintSub = document.getElementById('cardMaintSub');
    if (cardMaintRem && cachedMaintenanceSchedule) {
      const dueH = cachedMaintenanceSchedule.next_due_hours;
      const remMaint = dueH - liveHours;
      cardMaintRem.innerHTML = `${remMaint.toFixed(1).replace('.', ',')} <small style="font-size: 0.9rem;">год</small>`;
      if (remMaint <= 0) {
        cardMaintRem.style.color = '#ef4444';
        if (cardMaintSub) cardMaintSub.innerText = 'ПОТРІБНЕ ТО!';
      } else {
        cardMaintRem.style.color = 'inherit';
        if (cardMaintSub) cardMaintSub.innerText = `план: ${dueH.toFixed(0)} год`;
      }
    }

    // 4. Periodically refresh unified Fuel Assessment Block during active run (every 10s)
    if (elapsedSeconds % 10 === 0 && typeof window.updateFuelAssessmentBlock === 'function') {
      window.updateFuelAssessmentBlock(liveTank);
    }
  }
}

function _sumYasnoTodayRemMinutes(data) {
  if (!data) return 0;
  const now = new Date();
  const curMin = now.getHours() * 60 + now.getMinutes();
  if (Array.isArray(data.slots_today) && data.slots_today.length > 0) {
    return data.slots_today.reduce((acc, s) => {
      const end = Number(s.end);
      const start = Number(s.start);
      if (end > curMin) return acc + Math.max(0, end - Math.max(start, curMin));
      return acc;
    }, 0);
  }
  if (Array.isArray(data.timeline_today)) {
    const curHour = now.getHours();
    return data.timeline_today.reduce((acc, h) => {
      if (Number(h.hour) >= curHour && h.status === 'DEFINITE') return acc + 60;
      return acc;
    }, 0);
  }
  return 0;
}

function _sumYasnoTomorrowMinutes(data) {
  if (!data) return 0;
  if (Array.isArray(data.slots_tomorrow) && data.slots_tomorrow.length > 0) {
    return data.slots_tomorrow.reduce((acc, s) => acc + Math.max(0, Number(s.end) - Number(s.start)), 0);
  }
  if (Array.isArray(data.timeline_tomorrow)) {
    return data.timeline_tomorrow.reduce((acc, h) => acc + (h.status === 'DEFINITE' ? 60 : 0), 0);
  }
  return 0;
}

window.updateFuelAssessmentBlock = function (liveTankOverride = null) {
  const panel = document.getElementById('fuelAssessmentPanel');
  if (!panel) return;

  if (!currentGenerator) {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = 'block';

  let fuelL = Number(currentGenerator.fuel_tank_level_l || 0);
  if (typeof liveTankOverride === 'number' && !Number.isNaN(liveTankOverride)) {
    fuelL = liveTankOverride;
  } else if (currentGenerator.status === 'RUNNING' && activeRun && activeRun.start_time) {
    const startDt = parseUTCDate(activeRun.start_time);
    if (startDt) {
      const elapsedH = Math.max(0, (Date.now() - startDt.getTime()) / 3600000);
      const nom = Number(currentGenerator.nominal_consumption_l_per_h || 2.2);
      const startFuel = activeRun.start_fuel_level_l ?? activeRun.start_fuel ?? fuelL;
      fuelL = startFuel - elapsedH * nom;
    }
  }

  const nominal = Number(currentGenerator.nominal_consumption_l_per_h || 2.2);
  const cap = Number(currentGenerator.tank_capacity_l || 25.0);
  const effTankL = Math.max(0, fuelL);
  const tankHours = nominal > 0 ? (effTankL / nominal) : 0;

  const summary = window._lastFuelSummary || null;
  const canSeeFuel = !isViewerOnly() && hasPermission('fuel:view') && summary;
  const stockL = canSeeFuel ? Math.max(0, Number(summary.warehouse_balance_l || 0)) : 0;
  const totalFuelL = effTankL + stockL;
  const totalHours = nominal > 0 ? (totalFuelL / nominal) : 0;

  const rateEl = document.getElementById('fuelAssessRateBadge');
  if (rateEl) {
    rateEl.innerText = `${currentGenerator.fuel_type || 'А-95'} • розхід ${nominal.toFixed(1).replace('.', ',')} л/год`;
  }

  const inMeas = !!(window._measurementState && window._measurementState.is_measuring);

  // 1. Tank autonomy sub-card
  const tHoursEl = document.getElementById('assessTankHours');
  const tSubEl = document.getElementById('assessTankSub');
  if (tHoursEl && tSubEl) {
    if (inMeas && fuelL <= 0) {
      tHoursEl.innerHTML = `<span style="color:#38bdf8;">📏 Режим заміру</span>`;
      tSubEl.innerHTML = `<span style="color:#bae6fd;">Попередження порожнього баку вимкнено під час вимірювання</span>`;
    } else if (fuelL < 0) {
      tHoursEl.innerHTML = `<span style="color:#ef4444;">⚠️ Дефіцит ${formatLiters(Math.abs(fuelL))}</span>`;
      tSubEl.innerHTML = `<span style="color:#fecaca;">Бак за обліком порожній — потрібна дозаправка</span>`;
    } else {
      tHoursEl.innerText = `~${formatHoursToHuman(tankHours)}`;
      tSubEl.innerText = `${effTankL.toFixed(1).replace('.', ',')} з ${cap.toFixed(1).replace('.', ',')} л у баку`;
    }
  }

  // 2. Total facility fuel autonomy sub-card (Tank + Canisters/Reserve or Warehouse)
  const totHoursEl = document.getElementById('assessTotalHours');
  const totSubEl = document.getElementById('assessTotalSub');
  if (totHoursEl && totSubEl) {
    if (!canSeeFuel) {
      totHoursEl.innerText = `~${formatHoursToHuman(tankHours)}`;
      totSubEl.innerText = 'Склад та каністри приховані для поточної ролі';
    } else {
      totHoursEl.innerText = `~${formatHoursToHuman(totalHours)}`;
      if (Number(summary.canisters_total || 0) > 0) {
        const resL = Number(summary.canister_reserve_l || 0);
        const awayNote = Number(summary.canisters_away || 0) > 0 ? ` • ${Number(summary.canisters_away)} на АЗС` : '';
        totSubEl.innerHTML = `<b>${totalFuelL.toFixed(1).replace('.', ',')} л</b>: бак (${effTankL.toFixed(1)}) + ${Number(summary.canisters_full)} повн. каністр + ${resL.toFixed(1)} л рез.${awayNote}`;
      } else {
        totSubEl.innerHTML = `<b>${totalFuelL.toFixed(1).replace('.', ',')} л</b>: бак (${effTankL.toFixed(1)} л) + склад (${stockL.toFixed(1)} л)`;
      }
    }
  }

  // 3. YASNO outage readiness sub-card
  const yasnoEl = document.getElementById('assessYasnoStatus');
  if (!yasnoEl) return;
  const data = window._yasnoLastData;
  if (!data || !data.enabled || !data.configured) {
    yasnoEl.className = 'yasno-fuel-readiness';
    yasnoEl.style.background = 'rgba(148, 163, 184, 0.08)';
    yasnoEl.style.border = '1px solid var(--border-color)';
    yasnoEl.style.color = 'var(--text-muted)';
    yasnoEl.innerHTML = 'Моніторинг графіка YASNO для цього об\'єкта не активний.';
    return;
  }

  yasnoEl.style.background = '';
  yasnoEl.style.border = '';
  yasnoEl.style.color = '';

  let slot = null;
  let isCurrentOutage = false;
  if (data.current_outage && data.current_outage.start && data.current_outage.end) {
    slot = data.current_outage;
    isCurrentOutage = true;
  } else if ((data.status === 'DEFINITE' || data.status === 'PROBABLE') && Array.isArray(data.slots_today)) {
    const now = new Date();
    const curMin = now.getHours() * 60 + now.getMinutes();
    const matchSlot = data.slots_today.find(s => Number(s.start) <= curMin && curMin < Number(s.end));
    if (matchSlot) {
      const fmtMin = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
      slot = { start: fmtMin(Number(matchSlot.start)), end: fmtMin(Number(matchSlot.end)) };
      isCurrentOutage = true;
    }
  }
  if (!slot && data.next_outage && data.next_outage.start && data.next_outage.end) {
    slot = data.next_outage;
  }

  const todayRemMin = _sumYasnoTodayRemMinutes(data);
  const tomorrowMin = _sumYasnoTomorrowMinutes(data);
  const plannedRemHours = (todayRemMin + tomorrowMin) / 60.0;
  const plannedNeedL = plannedRemHours * nominal;
  const planNote = plannedRemHours > 0
    ? `<br><span style="font-size:0.78rem; opacity:0.9;">Добовий план (залишок сьогодні + завтра): <b>~${escapeHtml(formatHoursToHuman(plannedRemHours))}</b> (~${plannedNeedL.toFixed(1).replace('.', ',')} л)${canSeeFuel ? (totalFuelL + 0.1 >= plannedNeedL ? ' — загального запасу <b>достатньо</b>' : ` — бракує <b>~${(plannedNeedL - totalFuelL).toFixed(1).replace('.', ',')} л</b> на об'єкті`) : ''}.</span>`
    : '';

  if (!slot) {
    const stdHours = 4.0;
    const stdNeed = stdHours * nominal;
    if (inMeas && fuelL <= 0) {
      yasnoEl.className = 'yasno-fuel-readiness';
      yasnoEl.innerHTML = `<div>📏 Триває контрольний замір витрати палива — попередження порожнього баку призупинено.${planNote}</div>`;
    } else if (tankHours + 0.05 >= stdHours && fuelL > 0) {
      yasnoEl.className = 'yasno-fuel-readiness readiness-ok';
      yasnoEl.innerHTML = `<div>✅ Запланованих відключень зараз немає. Палива в баку вистачить на стандартний 4-год слот.${planNote}</div>`;
    } else {
      const defL = Math.max(0.1, stdNeed - effTankL).toFixed(1).replace('.', ',');
      yasnoEl.className = `yasno-fuel-readiness ${fuelL <= 0 ? 'readiness-crit' : 'readiness-warn'}`;
      yasnoEl.innerHTML = `<div>⚠️ Планових відключень немає, але в баку мало палива для 4-год резерву (бракує ~<b>${defL} л</b>).${planNote}</div>`;
    }
    return;
  }

  const parseM = typeof window._parseHhMmToMinutes === 'function'
    ? window._parseHhMmToMinutes
    : (str) => {
        if (!str || !str.includes(':')) return null;
        const [hh, mm] = str.split(':').map(Number);
        return (Number.isNaN(hh) || Number.isNaN(mm)) ? null : hh * 60 + mm;
      };
  const startMin = parseM(slot.start);
  let endMin = parseM(slot.end);
  if (startMin === null || endMin === null) return;
  if (endMin <= startMin) endMin += 1440;

  let slotMin = endMin - startMin;
  if (isCurrentOutage) {
    const now = new Date();
    let nowMin = now.getHours() * 60 + now.getMinutes();
    if (nowMin < startMin && endMin > 1440) nowMin += 1440;
    if (nowMin >= startMin && nowMin < endMin) slotMin = Math.max(5, endMin - nowMin);
  }
  const slotHours = slotMin / 60.0;
  const needSlotL = slotHours * nominal;
  const slotDesc = isCurrentOutage
    ? `поточне відкл. до <b>${escapeHtml(slot.end)}</b> (${escapeHtml(formatHoursToHuman(slotHours))})`
    : `слот <b>${escapeHtml(slot.start)}–${escapeHtml(slot.end)}</b> (${escapeHtml(formatHoursToHuman(slotHours))})`;

  if (inMeas && fuelL <= 0) {
    yasnoEl.className = 'yasno-fuel-readiness';
    yasnoEl.innerHTML = `<div>📏 Триває контрольний замір (на ${slotDesc} потрібно ~${needSlotL.toFixed(1).replace('.', ',')} л).${planNote}</div>`;
  } else if (tankHours + 0.05 >= slotHours && fuelL > 0) {
    yasnoEl.className = 'yasno-fuel-readiness readiness-ok';
    yasnoEl.innerHTML = `<div>✅ На ${slotDesc} палива в баку <b>вистачить</b> (потрібно ~${needSlotL.toFixed(1).replace('.', ',')} л).${planNote}</div>`;
  } else {
    const defL = Math.max(0.1, needSlotL - effTankL).toFixed(1).replace('.', ',');
    yasnoEl.className = `yasno-fuel-readiness ${fuelL <= 0 ? 'readiness-crit' : 'readiness-warn'}`;
    yasnoEl.innerHTML = `<div>⚠️ На ${slotDesc} у баку <b>бракує ~${defL} л</b> — потрібна дозаправка.${planNote}</div>`;
  }
};

window.applyMeasurementTankDecor = function () {
  if (!currentGenerator) return;
  if (currentGenerator.status === 'RUNNING') {
    updateRunStopwatchDisplay();
    return;
  }
  const inMeas = !!(window._measurementState && window._measurementState.is_measuring);
  const fuelL = currentGenerator.fuel_tank_level_l || 0;
  const cap = currentGenerator.tank_capacity_l || 25.0;
  const cardTank = document.getElementById('cardTank');
  const cardTankCapSub = document.getElementById('cardTankCapSub');
  if (cardTank && fuelL < 0 && inMeas) {
    cardTank.style.color = '#38bdf8';
    if (cardTankCapSub) {
      cardTankCapSub.innerHTML = `<span style="color: #38bdf8; font-weight: 600;">📏 Режим заміру (попередження вимкнено)</span>`;
    }
  } else if (cardTankCapSub && inMeas && fuelL <= 0) {
    cardTankCapSub.innerText = `0,0 з ${cap.toFixed(1).replace('.', ',')} л • 📏 Режим заміру`;
  }
  const btn = document.getElementById('mainActionBtn');
  if (btn && inMeas && currentGenerator.status !== 'FAULTY' && currentGenerator.status !== 'BLOCKED') {
    btn.classList.remove('btn-fuel-warning');
  }
  updateFuelAssessmentBlock();
};

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

// Start / Stop Main Button Handler with Debounce and Safeguards (Delegated for Lazy Dashboard Mount)
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('#mainActionBtn');
  if (!btn) return;
  if (!currentGenerator) return;
  if (isViewerOnly() || !hasPermission('generator:start')) {
    showToast('Керування генератором недоступне для ролі Спостерігач', 'warning');
    return;
  }

  if (btn.disabled || btn.dataset.busy === 'true') return;

  if (currentCooldownSeconds > 0) {
    showToast(`Захист від передчасного запуску: зачекайте ще ${currentCooldownSeconds} с (технологічна пауза 60 с)`, 'warning');
    return;
  }

  if (currentGenerator.status === 'RUNNING') {
    if (window.ViewLoader?.ensureModal) {
      await window.ViewLoader.ensureModal('modalStopGen');
    }
    const endHoursInput = document.getElementById('stopEndHours');
    if (endHoursInput) {
      endHoursInput.value = '';
      endHoursInput.min = currentGenerator.current_operating_hours;
    }

    if (activeRun && activeRun.start_time) {
      const startDisp = document.getElementById('stopStartTimeDisplay');
      if (startDisp) startDisp.innerText = formatDateTime(activeRun.start_time);
      updateRunStopwatchDisplay();
    } else {
      const startDisp = document.getElementById('stopStartTimeDisplay');
      const durDisp = document.getElementById('stopDurationDisplay');
      const fuelDisp = document.getElementById('stopEstFuelDisplay');
      if (startDisp) startDisp.innerText = '-';
      if (durDisp) durDisp.innerText = '00:00:00';
      if (fuelDisp) fuelDisp.innerText = '0.000 л';
    }
    openModal('modalStopGen');
  } else {
    let forceStart = false;
    if (currentGenerator.status === 'MAINTENANCE_REQUIRED') {
      const confirmStart = confirm(
        '⚠️ УВАГА: Регламент технічного обслуговування (ТО) цього генератора прострочено!\n\nВи впевнені, що хочете запустити генератор до виконання регламентних робіт?'
      );
      if (!confirmStart) return;
      forceStart = true;
    }

    btn.disabled = true;
    btn.dataset.busy = 'true';
    const oldText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Запуск...';

    try {
      const startRes = await api('/generator/start', {
        method: 'POST',
        body: JSON.stringify({
          generator_id: currentGeneratorId,
          fuel_level_l: currentGenerator.fuel_tank_level_l,
          force_start: forceStart
        }),
        offlineMeta: {
          action_type: 'gen_start',
          title: 'Запуск генератора',
          summary: `${currentGenerator.name || 'Генератор'} (бак ${Number(currentGenerator.fuel_tank_level_l || 0).toFixed(1)} л)`,
          facility_id: currentFacilityId,
          generator_id: currentGeneratorId,
        }
      });
      if (startRes && startRes._queuedOffline) {
        showToast('📥 Запуск генератора збережено в офлайн-чергу (буде надіслано при появі мережі)', 'warning');
      } else {
        showToast('Генератор успішно запущено!', 'success');
      }
      await loadAllData();
    } catch (_) {
      btn.innerHTML = oldText;
    } finally {
      btn.disabled = false;
      btn.dataset.busy = 'false';
    }
  }
});

// Manual Run Entry (Offline/Paper Log)
window.openManualRunModal = async function () {
  if (isViewerOnly() || !hasPermission('generator:start')) {
    showToast('Ручне внесення мотогодин недоступне для ролі Спостерігач', 'warning');
    return;
  }
  if (!currentGenerator) {
    showToast('Будь ласка, спочатку оберіть генератор', 'warning');
    return;
  }
  if (window.ViewLoader?.ensureModal) {
    await window.ViewLoader.ensureModal('modalManualRun');
  }
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const fmtLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  const startD = new Date(now.getTime() - 2 * 3600 * 1000);
  const endD = new Date(now.getTime() - 1 * 3600 * 1000);

  const startInput = document.getElementById('manualRunStartTime');
  const endInput = document.getElementById('manualRunEndTime');
  if (startInput) startInput.value = fmtLocal(startD);
  if (endInput) endInput.value = fmtLocal(endD);

  const startHoursInput = document.getElementById('manualRunStartHours');
  if (startHoursInput) {
    startHoursInput.value = currentGenerator.current_operating_hours != null ? currentGenerator.current_operating_hours.toFixed(1) : '0.0';
  }

  const endHoursInput = document.getElementById('manualRunEndHours');
  if (endHoursInput) {
    endHoursInput.value = '';
    endHoursInput.removeAttribute('data-manual-edited');
  }

  const fuelInput = document.getElementById('manualRunFuelConsumed');
  if (fuelInput) fuelInput.value = '';

  const noteInput = document.getElementById('manualRunNote');
  if (noteInput) noteInput.value = '';

  calculateManualRunEstimates();
  openModal('modalManualRun');
};

window.calculateManualRunEstimates = function() {
  const startVal = document.getElementById('manualRunStartTime')?.value;
  const endVal = document.getElementById('manualRunEndTime')?.value;
  const durTextEl = document.getElementById('manualRunDurationText');
  const fuelTextEl = document.getElementById('manualRunFuelText');
  const endHoursEl = document.getElementById('manualRunEndHours');
  const startHoursEl = document.getElementById('manualRunStartHours');

  if (!startVal || !endVal || !durTextEl || !fuelTextEl) return;

  const startD = new Date(startVal);
  const endD = new Date(endVal);

  if (isNaN(startD.getTime()) || isNaN(endD.getTime()) || endD <= startD) {
    durTextEl.innerText = '00:00:00 (0.0 год)';
    durTextEl.style.color = '#ef4444';
    fuelTextEl.innerText = '~0.0 л';
    return;
  }

  durTextEl.style.color = '#38bdf8';
  const diffSec = Math.floor((endD.getTime() - startD.getTime()) / 1000);
  const diffHours = diffSec / 3600.0;
  const formatted = formatDuration(diffSec);

  durTextEl.innerText = `${formatted} (${diffHours.toFixed(2)} год)`;

  const consumptionRate = (currentGenerator && currentGenerator.nominal_consumption_l_per_h) || 2.2;
  const estFuel = diffHours * consumptionRate;
  fuelTextEl.innerText = `~${estFuel.toFixed(2)} л (при ${consumptionRate.toFixed(2)} л/год)`;

  if (startHoursEl && endHoursEl && !endHoursEl.getAttribute('data-manual-edited')) {
    const startH = parseFloat(startHoursEl.value) || 0.0;
    endHoursEl.value = (startH + diffHours).toFixed(1);
  }
};

document.addEventListener('input', (e) => {
  if (e.target && e.target.id === 'manualRunEndHours') {
    e.target.setAttribute('data-manual-edited', 'true');
  }
});

document.addEventListener('submit', async (e) => {
  const form = e.target;
  if (!form || !form.id) return;

  if (form.id === 'manualRunForm') {
    e.preventDefault();
    if (!currentGeneratorId) {
      showToast('Генератор не обрано', 'error');
      return;
    }
    const startVal = document.getElementById('manualRunStartTime').value;
    const endVal = document.getElementById('manualRunEndTime').value;
    if (!startVal || !endVal) {
      showToast('Вкажіть час запуску та зупинки', 'warning');
      return;
    }
    const startD = new Date(startVal);
    const endD = new Date(endVal);
    if (endD <= startD) {
      showToast('Час зупинки повинен бути пізнішим за час запуску', 'warning');
      return;
    }

    const startHVal = document.getElementById('manualRunStartHours').value;
    const endHVal = document.getElementById('manualRunEndHours').value;
    const fuelVal = document.getElementById('manualRunFuelConsumed').value;
    const noteVal = document.getElementById('manualRunNote').value.trim();

    const body = {
      generator_id: currentGeneratorId,
      start_time: startD.toISOString(),
      end_time: endD.toISOString(),
      start_hours: startHVal !== '' && !isNaN(parseFloat(startHVal)) ? parseFloat(startHVal) : null,
      end_hours: endHVal !== '' && !isNaN(parseFloat(endHVal)) ? parseFloat(endHVal) : null,
      fuel_consumed_l: fuelVal !== '' && !isNaN(parseFloat(fuelVal)) ? parseFloat(fuelVal) : null,
      note: noteVal || 'Внесено вручну (запис з паперового журналу)'
    };

    try {
      const res = await api('/generator/manual-run', {
        method: 'POST',
        body: JSON.stringify(body),
        offlineMeta: {
          action_type: 'gen_manual_run',
          title: 'Ручний запис роботи (журнал)',
          summary: `${currentGenerator?.name || 'Генератор'}: ${startVal} → ${endVal}`,
          facility_id: currentFacilityId,
          generator_id: currentGeneratorId,
        }
      });
      closeModal('modalManualRun');
      if (res && res._queuedOffline) {
        showToast('📥 Ручний запис роботи збережено в офлайн-чергу', 'warning');
      } else {
        const durText = res.duration_formatted || `${res.duration_hours} год`;
        const fuelText = res.calculated_consumption_l != null ? `${res.calculated_consumption_l.toFixed(1)} л` : '-';
        showToast(`Сеанс роботи успішно внесено в журнал! Час: ${durText}, витрата: ${fuelText}`, 'success');
      }
      loadGeneratorData();
      loadAllData();
      loadRecentRuns();
      if (typeof loadRunsTable === 'function') loadRunsTable();
    } catch (err) {
      showToast(err.message || 'Помилка при збереженні сеансу роботи', 'error');
    }
    return;
  }

  if (form.id === 'stopGenForm') {
    e.preventDefault();
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn && submitBtn.disabled) return;

    const endHoursVal = document.getElementById('stopEndHours').value;
    const endHours = endHoursVal !== '' && !isNaN(parseFloat(endHoursVal)) ? parseFloat(endHoursVal) : null;
    const endFuelVal = document.getElementById('stopEndFuel').value;
    const endFuel = endFuelVal !== '' && !isNaN(parseFloat(endFuelVal)) ? parseFloat(endFuelVal) : null;
    const note = document.getElementById('stopNote').value;

    let forceConfirm = false;

    if (endHours !== null && currentGenerator) {
      const startH = activeRun?.start_hours ?? currentGenerator.current_operating_hours;
      const deltaH = endHours - startH;
      let elapsedH = 0;
      if (activeRun?.start_time) {
        elapsedH = Math.max(0, (Date.now() - new Date(activeRun.start_time).getTime()) / 3600000);
      }

      const isSuspicious = (deltaH > 14.0) || (elapsedH > 0.02 && Math.abs(deltaH - elapsedH) > 2.0);
      if (isSuspicious) {
        const confirmed = confirm(
          `⚠️ Запобіжник опечатки мотогодин!\n\n` +
          `Напрацювання за введеним лічильником: ${deltaH.toFixed(2)} год.\n` +
          `Час роботи за таймером: ${elapsedH.toFixed(2)} год.\n\n` +
          `Різниця суттєва. Можлива опечатка (зайва цифра або пропущена крапка)!\n` +
          `Ви впевнені, що показник ${endHours} правильний?`
        );
        if (!confirmed) {
          return;
        }
        forceConfirm = true;
      }
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Зупинка...';
    }

    try {
      const res = await api('/generator/stop', {
        method: 'POST',
        body: JSON.stringify({
          generator_id: currentGeneratorId,
          end_hours: endHours,
          end_fuel_level_l: endFuel,
          note: note,
          force_confirm: forceConfirm
        }),
        offlineMeta: {
          action_type: 'gen_stop',
          title: 'Зупинка генератора',
          summary: `${currentGenerator?.name || 'Генератор'}${endHours != null ? ` (мотогод: ${endHours})` : ''}`,
          facility_id: currentFacilityId,
          generator_id: currentGeneratorId,
        }
      });
      closeModal('modalStopGen');
      stopRunStopwatch();
      if (res && res._queuedOffline) {
        showToast('📥 Зупинку генератора збережено в офлайн-чергу', 'warning');
      } else {
        startCooldownTimer(60);
        const durText = res.duration_formatted || formatDuration(res.duration_seconds) || `${res.duration_hours} год`;
        const fuelText = res.calculated_consumption_l != null ? `${res.calculated_consumption_l} л` : '-';
        showToast(`Генератор зупинено! Відпрацьовано: ${durText}, розхід: ${fuelText}`, 'success');
      }
      loadAllData();
    } catch (err) {
      showToast(err.message || 'Помилка при зупинці генератора', 'error');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = 'Зупинити генератор';
      }
    }
  }
});

