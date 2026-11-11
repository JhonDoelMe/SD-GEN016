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

  if (!isViewerOnly() && hasPermission('fuel:view')) {
    tasks.push(loadFuelSummary());
  } else {
    const cardStock = document.getElementById('cardStock');
    if (cardStock) cardStock.innerText = '-';
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
  applyRolePermissionsUI();
}

// 1. Generator Data
async function loadGeneratorData() {
  if (!currentGeneratorId) {
    currentGenerator = null;
    const nameEl = document.getElementById('genName');
    if (nameEl) nameEl.innerText = "Немає генератора";
    const modelEl = document.getElementById('genModel');
    if (modelEl) modelEl.innerText = "На обраному об'єкті ще немає генераторів. Натисніть «+ Генератор», щоб зареєструвати перший генератор.";
    const cardHours = document.getElementById('cardHours');
    if (cardHours) cardHours.innerText = "0,0";
    const cardTank = document.getElementById('cardTank');
    if (cardTank) cardTank.innerText = "0,0";
    const badge = document.getElementById('genStatusBadge');
    if (badge) {
      badge.className = 'badge';
      badge.innerText = 'ВІДСУТНІЙ';
    }
    const btn = document.getElementById('mainActionBtn');
    if (btn) {
      btn.className = 'btn-hero btn-disabled-role';
      btn.disabled = true;
      btn.innerHTML = '<span>➕</span><span>ДОДАЙТЕ ГЕНЕРАТОР НА ОБ\'ЄКТ</span>';
      btn.title = 'Натисніть кнопку "+ Генератор" у верхній панелі, щоб зареєструвати генератор';
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
    document.getElementById('genModel').innerText = `Модель: ${currentGenerator.model} | Серійний: ${currentGenerator.serial_number} | Потужність: ${currentGenerator.rated_power_kw} кВт`;
    document.getElementById('cardHours').innerText = currentGenerator.current_operating_hours.toFixed(1).replace('.', ',');

    const fuelL = currentGenerator.fuel_tank_level_l;
    const cardTank = document.getElementById('cardTank');
    const tankProgress = document.getElementById('tankProgress');
    const cardTankHoursRem = document.getElementById('cardTankHoursRem');

    cardTank.innerText = fuelL.toFixed(1).replace('.', ',');
    if (fuelL < 0) {
      cardTank.style.color = '#ef4444';
      if (tankProgress) tankProgress.style.width = '0%';
      if (cardTankHoursRem) {
        cardTankHoursRem.innerHTML = `<span style="color: #ef4444; font-weight: 600;">⚠️ Дефіцит: ${formatLiters(Math.abs(fuelL))} (потрібна заправка!)</span>`;
      }
    } else {
      cardTank.style.color = 'inherit';
      const cap = currentGenerator.tank_capacity_l || 25.0;
      const pct = Math.min(100, Math.max(0, Math.round((fuelL / cap) * 100)));
      if (tankProgress) tankProgress.style.width = `${pct}%`;
      const nominal = currentGenerator.nominal_consumption_l_per_h || 2.2;
      const hoursLeft = nominal > 0 ? (fuelL / nominal) : 0;
      if (cardTankHoursRem) {
        if (fuelL === 0) {
          cardTankHoursRem.innerHTML = `<span style="color: var(--text-muted);">вистачить на 0 год (бак порожній)</span>`;
        } else {
          cardTankHoursRem.innerHTML = `вистачить на ~<b>${hoursLeft.toFixed(1).replace('.', ',')}</b> год (при ${nominal} л/год)`;
        }
      }
    }

    // Status Badge & Action Button
    const badge = document.getElementById('genStatusBadge');
    const btn = document.getElementById('mainActionBtn');
    const banner = document.getElementById('activeRunBanner');
    const btnTransfer = document.getElementById('btnQuickTransfer');

    const isFuelDeficit = (fuelL <= 0);

    badge.className = 'badge';
    if (currentGenerator.status === 'RUNNING') {
      badge.classList.add('badge-running');
      badge.innerText = 'ПРАЦЮЄ';
      btn.className = 'btn-hero btn-stop';
      btn.innerHTML = '<span>⏹</span><span>ЗУПИНИТИ ГЕНЕРАТОР</span>';
      btn.removeAttribute('title');
    } else if (currentGenerator.status === 'MAINTENANCE_REQUIRED') {
      badge.classList.add('badge-maintenance');
      badge.innerText = 'ПОТРІБНЕ ТО';
      btn.className = 'btn-hero btn-start' + (isFuelDeficit ? ' btn-fuel-warning' : '');
      btn.innerHTML = isFuelDeficit
        ? '<span style="font-size: 1.35rem;">⚠️</span><span style="font-size: 1.4rem;">▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>'
        : '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
      if (isFuelDeficit) {
        btn.title = 'Увага: у баку за обліком 0 л (дефіцит)! Запуск дозволено за фактичним залишком палива.';
      } else {
        btn.removeAttribute('title');
      }
    } else if (currentGenerator.status === 'FAULTY') {
      badge.classList.add('badge-faulty');
      badge.innerText = 'НЕСПРАВНИЙ';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>⚠️</span><span>НЕСПРАВНІСТЬ (БЛОК)</span>';
      btn.removeAttribute('title');
    } else if (currentGenerator.status === 'BLOCKED') {
      badge.classList.add('badge-blocked');
      badge.innerText = 'ЗАБЛОКОВАНО';
      btn.className = 'btn-hero btn-start';
      btn.innerHTML = '<span>🔒</span><span>ЗАБЛОКОВАНО</span>';
      btn.removeAttribute('title');
    } else {
      badge.classList.add('badge-stopped');
      badge.innerText = 'ЗУПИНЕНО';
      btn.className = 'btn-hero btn-start' + (isFuelDeficit ? ' btn-fuel-warning' : '');
      btn.innerHTML = isFuelDeficit
        ? '<span style="font-size: 1.35rem;">⚠️</span><span style="font-size: 1.4rem;">▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>'
        : '<span>▶</span><span>ЗАПУСТИТИ ГЕНЕРАТОР</span>';
      if (isFuelDeficit) {
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
    if (typeof window.updateYasnoFuelReadiness === 'function') {
      window.updateYasnoFuelReadiness();
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

    // 2. Live Tank Level & 'вистачить на ... год' (can go negative into deficit!)
    const startFuel = activeRun.start_fuel_level_l ?? activeRun.start_fuel ?? currentGenerator.fuel_tank_level_l;
    const liveTank = startFuel - estConsumed;
    const cardTank = document.getElementById('cardTank');
    const tankProgress = document.getElementById('tankProgress');
    const cardTankHoursRem = document.getElementById('cardTankHoursRem');

    if (cardTank) {
      cardTank.innerText = liveTank.toFixed(1).replace('.', ',');
      const btnTransfer = document.getElementById('btnQuickTransfer');
      if (liveTank <= 0) {
        cardTank.style.color = '#ef4444';
        if (tankProgress) tankProgress.style.width = '0%';
        if (cardTankHoursRem) {
          cardTankHoursRem.innerHTML = `<span style="color: #ef4444; font-weight: 600;">⚠️ Дефіцит: ${formatLiters(Math.abs(liveTank))} (потрібна заправка!)</span>`;
        }
        if (btnTransfer && !isViewerOnly() && hasPermission('fuel:transfer')) {
          btnTransfer.classList.add('btn-action-refuel-highlight');
        }
      } else {
        cardTank.style.color = 'inherit';
        const cap = currentGenerator.tank_capacity_l || 25.0;
        const pct = Math.min(100, Math.max(0, Math.round((liveTank / cap) * 100)));
        if (tankProgress) tankProgress.style.width = `${pct}%`;
        const remHours = nominal > 0 ? (liveTank / nominal) : 0;
        if (cardTankHoursRem) {
          if (liveTank === 0) {
            cardTankHoursRem.innerHTML = `<span style="color: var(--text-muted);">вистачить на 0 год (бак порожній)</span>`;
          } else {
            cardTankHoursRem.innerHTML = `вистачить на ~<b>${remHours.toFixed(1).replace('.', ',')}</b> год (при ${nominal} л/год)`;
          }
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

    // 4. Periodically refresh YASNO fuel readiness during active run (every 30s)
    if (elapsedSeconds % 30 === 0 && typeof window.updateYasnoFuelReadiness === 'function') {
      window.updateYasnoFuelReadiness(liveTank);
    }
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

// Start / Stop Main Button Handler with Debounce and Safeguards
document.getElementById('mainActionBtn').addEventListener('click', async () => {
  if (!currentGenerator) return;
  if (isViewerOnly() || !hasPermission('generator:start')) {
    showToast('Керування генератором недоступне для ролі Спостерігач', 'warning');
    return;
  }

  const btn = document.getElementById('mainActionBtn');
  if (btn.disabled || btn.dataset.busy === 'true') return;

  if (currentCooldownSeconds > 0) {
    showToast(`Захист від передчасного запуску: зачекайте ще ${currentCooldownSeconds} с (технологічна пауза 60 с)`, 'warning');
    return;
  }

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
    // Safeguard: Maintenance Overdue Warning modal
    let forceStart = false;
    if (currentGenerator.status === 'MAINTENANCE_REQUIRED') {
      const confirmStart = confirm(
        '⚠️ УВАГА: Регламент технічного обслуговування (ТО) цього генератора прострочено!\n\nВи впевнені, що хочете запустити генератор до виконання регламентних робіт?'
      );
      if (!confirmStart) return;
      forceStart = true;
    }

    // Debounce & start generator
    btn.disabled = true;
    btn.dataset.busy = 'true';
    const oldText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Запуск...';

    try {
      await api('/generator/start', {
        method: 'POST',
        body: JSON.stringify({
          generator_id: currentGeneratorId,
          fuel_level_l: currentGenerator.fuel_tank_level_l,
          force_start: forceStart
        })
      });
      showToast('Генератор успішно запущено!', 'success');
      await loadAllData();
    } catch (_) {
      btn.innerHTML = oldText;
    } finally {
      btn.disabled = false;
      btn.dataset.busy = 'false';
    }
  }
});

// Stop Form Submit
// Manual Run Entry (Offline/Paper Log)
window.openManualRunModal = function() {
  if (isViewerOnly() || !hasPermission('generator:start')) {
    showToast('Ручне внесення мотогодин недоступне для ролі Спостерігач', 'warning');
    return;
  }
  if (!currentGenerator) {
    showToast('Будь ласка, спочатку оберіть генератор', 'warning');
    return;
  }
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const fmtLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  // Default: start 2 hours ago, end 1 hour ago
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

document.getElementById('manualRunEndHours')?.addEventListener('input', () => {
  document.getElementById('manualRunEndHours')?.setAttribute('data-manual-edited', 'true');
});

document.getElementById('manualRunForm')?.addEventListener('submit', async (e) => {
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
      body: JSON.stringify(body)
    });
    closeModal('modalManualRun');
    const durText = res.duration_formatted || `${res.duration_hours} год`;
    const fuelText = res.calculated_consumption_l != null ? `${res.calculated_consumption_l.toFixed(1)} л` : '-';
    showToast(`Сеанс роботи успішно внесено в журнал! Час: ${durText}, витрата: ${fuelText}`, 'success');
    loadGeneratorData();
    loadAllData();
    loadRecentRuns();
    if (typeof loadRunsTable === 'function') loadRunsTable();
  } catch (err) {
    showToast(err.message || 'Помилка при збереженні сеансу роботи', 'error');
  }
});


document.getElementById('stopGenForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  if (submitBtn && submitBtn.disabled) return;

  const endHoursVal = document.getElementById('stopEndHours').value;
  const endHours = endHoursVal !== '' && !isNaN(parseFloat(endHoursVal)) ? parseFloat(endHoursVal) : null;
  const endFuelVal = document.getElementById('stopEndFuel').value;
  const endFuel = endFuelVal !== '' && !isNaN(parseFloat(endFuelVal)) ? parseFloat(endFuelVal) : null;
  const note = document.getElementById('stopNote').value;

  let forceConfirm = false;

  // Typo Safeguard check on frontend
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
      })
    });
    closeModal('modalStopGen');
    stopRunStopwatch();
    startCooldownTimer(60);
    const durText = res.duration_formatted || formatDuration(res.duration_seconds) || `${res.duration_hours} год`;
    const fuelText = res.calculated_consumption_l != null ? `${res.calculated_consumption_l} л` : '-';
    showToast(`Генератор зупинено! Відпрацьовано: ${durText}, розхід: ${fuelText}`, 'success');
    loadAllData();
  } catch (err) {
    showToast(err.message || 'Помилка при зупинці генератора', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = 'Зупинити генератор';
    }
  }
});

