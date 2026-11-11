// =============================================================================
// Header Indicators: Weather & Air Alert Management
// =============================================================================
window._currentWeatherData = null;
window._currentAlertData = null;

window.loadFacilityIndicators = async function(facilityId, force = false) {
  if (!facilityId) {
    const wb = document.getElementById('headerWeatherBadge');
    const ab = document.getElementById('headerAlertBadge');
    if (wb) wb.style.display = 'none';
    if (ab) ab.style.display = 'none';
    return;
  }
  try {
    const endpoint = force
      ? `/facilities/${facilityId}/status-indicators?force=true&_t=${Date.now()}`
      : `/facilities/${facilityId}/status-indicators`;
    const res = await api(endpoint);
    if (!res) return;

    // 1. Weather Badge
    const weather = res.weather;
    window._currentWeatherData = weather;
    const weatherBadge = document.getElementById('headerWeatherBadge');
    if (weather && weather.is_available && weatherBadge) {
      const wIcon = document.getElementById('weatherPillIcon');
      const wText = document.getElementById('weatherPillText');
      const wCity = document.getElementById('weatherPillCity');
      if (wIcon) wIcon.innerText = weather.icon_emoji || '⛅';
      if (wText) wText.innerText = weather.temp_formatted || `${weather.temp_c}°C`;
      const cleanWCity = (weather.city || '').replace(/^(?:м\.|місто|смт|с\.)\s*/i, '').replace(/[,;].*$/, '').trim();
      if (wCity) wCity.innerText = cleanWCity || '';
      weatherBadge.style.display = 'inline-flex';
      weatherBadge.title = `Погода: ${weather.city}, ${weather.temp_formatted}, ${weather.description}. Натисніть для деталей.`;
    } else if (weatherBadge) {
      weatherBadge.style.display = 'none';
    }

    // 2. Alert Badge
    const alert = res.alert;
    window._currentAlertData = alert;
    const alertBadge = document.getElementById('headerAlertBadge');
    if (alert && alertBadge) {
      const level = alert.level || 'green';
      alertBadge.className = `header-pill pill-alert pill-alert-${level}`;
      const aIcon = document.getElementById('alertPillIcon');
      const aText = document.getElementById('alertPillText');
      const aReg = document.getElementById('alertPillRegion');

      if (aIcon) aIcon.innerText = alert.threat_icon || (level === 'green' ? '🟢' : '🚨');
      if (aText) {
        if (level === 'red') {
          const tType = (alert.threat_type || '').toLowerCase();
          if (tType.includes('ballistic')) aText.innerText = 'Балістика!';
          else if (tType.includes('mig31k')) aText.innerText = 'МіГ-31К!';
          else if (tType === 'cruise' || tType === 'cruise_missiles') aText.innerText = 'Крилаті ракети!';
          else if (tType.includes('bombs') || tType.includes('kab')) aText.innerText = 'КАБ!';
          else if (tType.includes('artillery') || tType.includes('shelling')) aText.innerText = 'Артобстріл!';
          else aText.innerText = 'Тривога!';
        } else if (level === 'yellow') {
          aText.innerText = 'БПЛА';
        } else {
          aText.innerText = 'Відбій';
        }
      }
      const cleanACity = (alert.city || '').replace(/^(?:м\.|місто|смт|с\.)\s*/i, '').replace(/[,;].*$/, '').trim();
      if (aReg) aReg.innerText = cleanACity || '';
      alertBadge.style.display = 'inline-flex';
      alertBadge.title = `Повітряна безпека: ${alert.threat_title} (${alert.region_name}). Натисніть для деталей.`;
    }
    if (typeof window.updateOperationalSafetyBanners === 'function') {
      window.updateOperationalSafetyBanners();
    }
  } catch (err) {
    console.warn("Не вдалося завантажити індикатори погоди та тривог:", err);
  }
};

window.isDieselGenerator = function(gen) {
  if (!gen) return false;
  const ft = String(gen.fuel_type || '').toLowerCase();
  const modelAndName = `${gen.name || ''} ${gen.model || ''}`.toLowerCase();
  return /дп|дизель|diesel/.test(ft) || /дизель|diesel/.test(modelAndName);
};

window.updateOperationalSafetyBanners = function() {
  // 1. Diesel Frost / Winter Fuel Notice (< 0°C, strictly for Diesel generators)
  const frostBanner = document.getElementById('genDieselFrostBanner');
  if (frostBanner) {
    const w = window._currentWeatherData;
    const isDiesel = window.isDieselGenerator(currentGenerator);
    const isSubZero = Boolean(w && w.is_available && typeof w.temp_c === 'number' && w.temp_c < 0);
    if (isDiesel && isSubZero) {
      const tempText = w.temp_formatted || `${Math.round(w.temp_c)}°C`;
      frostBanner.style.display = 'flex';
      frostBanner.innerHTML = `
        <span style="font-size: 1.15rem; line-height: 1.2; flex-shrink: 0;">❄️</span>
        <div><b>На об'єкті ${escapeHtml(tempText)}:</b> переконайтесь, що залито зимове ДП, та прогрійте двигун 3–5 хв без навантаження.</div>
      `;
    } else {
      frostBanner.style.display = 'none';
    }
  }

  // 2. Operator Safety Notice during Red Alert while Generator is RUNNING (strictly informational, zero blocking)
  const alertData = window._currentAlertData;
  const isRedAlert = Boolean(alertData && alertData.level === 'red');
  const isRunning = Boolean(currentGenerator && currentGenerator.status === 'RUNNING');
  const threatTitle = (alertData && alertData.threat_title) ? alertData.threat_title : 'Повітряна тривога';
  const infoHtml = `
    <span style="font-size: 1.15rem; line-height: 1.2; flex-shrink: 0;">🚨</span>
    <div><b>Безпека оператора (${escapeHtml(threatTitle)}):</b> на об'єкті триває 🔴 Червона тривога під час роботи генератора. Дотримуйтесь правил безпеки та утримайтесь від перебування на відкритому просторі біля обладнання (інформаційне нагадування).</div>
  `;

  const dashRedBanner = document.getElementById('redAlertRunSafetyBanner');
  if (dashRedBanner) {
    if (isRedAlert && isRunning) {
      dashRedBanner.style.display = 'flex';
      dashRedBanner.innerHTML = infoHtml;
    } else {
      dashRedBanner.style.display = 'none';
    }
  }

  const stopRedNotice = document.getElementById('stopModalRedAlertNotice');
  if (stopRedNotice) {
    if (isRedAlert && isRunning) {
      stopRedNotice.style.display = 'flex';
      stopRedNotice.innerHTML = infoHtml;
    } else {
      stopRedNotice.style.display = 'none';
    }
  }

  const transferRedNotice = document.getElementById('transferModalRedAlertNotice');
  if (transferRedNotice) {
    if (isRedAlert && isRunning) {
      transferRedNotice.style.display = 'flex';
      transferRedNotice.innerHTML = infoHtml;
    } else {
      transferRedNotice.style.display = 'none';
    }
  }
};

window.refreshFacilityIndicators = async function(manual = true) {
  if (!currentFacilityId) return;
  if (manual) showToast("Оновлення погоди та статусу тривоги...", "info");
  await window.loadFacilityIndicators(currentFacilityId, true);
  if (window._currentWeatherData && document.getElementById('modalWeatherDetails')?.classList.contains('active')) {
    window.populateWeatherModal(window._currentWeatherData);
  }
  if (window._currentAlertData && document.getElementById('modalAlertDetails')?.classList.contains('active')) {
    window.populateAlertModal(window._currentAlertData);
  }
  if (manual) showToast("Дані успішно оновлено!", "success");
};

window.openWeatherModal = async function() {
  openModal('modalWeatherDetails');
  if (!window._currentWeatherData || !Array.isArray(window._currentWeatherData.forecast) || window._currentWeatherData.forecast.length === 0) {
    if (currentFacilityId) await window.loadFacilityIndicators(currentFacilityId, true);
  }
  window.populateWeatherModal(window._currentWeatherData);
};

window.formatLocationDisplay = function(region, city) {
  let cleanCity = (city || '').replace(/^(?:м\.|місто|смт|с\.)\s*/i, '').trim();
  let cleanRegion = (region || '').trim();

  // Очищення розділових знаків у кінці рядків
  cleanCity = cleanCity.replace(/[,;.]+$/, '').trim();
  cleanRegion = cleanRegion.replace(/[,;.]+$/, '').trim();

  // Видалення повторного артефакту (область) або (район)
  cleanRegion = cleanRegion.replace(/\s*\((?:область|район)\)\s*$/i, '');
  if (cleanRegion && !cleanRegion.toLowerCase().endsWith('область') && !cleanRegion.toLowerCase().startsWith('м.') && cleanRegion !== 'Україна') {
    cleanRegion = `${cleanRegion} область`;
  }

  if (!cleanCity && !cleanRegion) return '📍 Україна';
  if (!cleanCity) return `📍 ${cleanRegion}`;
  if (!cleanRegion || cleanRegion === 'Україна') return `📍 м. ${cleanCity}`;

  const cLower = cleanCity.toLowerCase();
  const rLower = cleanRegion.toLowerCase();

  // Спеціальний випадок: м. Київ
  if (cLower === 'київ' || rLower === 'м. київ') {
    return '📍 м. Київ';
  }

  // Якщо місто збігається з областю/регіоном
  if (cLower === rLower) {
    return cleanRegion.startsWith('м.') ? `📍 ${cleanRegion}` : `📍 м. ${cleanCity}`;
  }

  // Якщо місто вже включає назву області (напр. "Самар, Дніпропетровська область")
  if (cLower.includes(rLower)) {
    return `📍 ${cleanCity}`;
  }

  // Якщо область вже включає назву міста (напр. "Дніпропетровська область, м. Самар")
  if (rLower.includes(cLower)) {
    return `📍 ${cleanRegion}`;
  }

  return `📍 ${cleanRegion}, м. ${cleanCity}`;
};

window.populateWeatherModal = function(w) {
  if (!w || !w.is_available) {
    const loc = document.getElementById('weatherHeroLoc');
    if (loc) loc.innerText = "Погодні дані завантажуються...";
    const fcSec = document.getElementById('weatherForecastSection');
    if (fcSec) fcSec.style.display = 'none';
    return;
  }
  const icon = document.getElementById('weatherHeroIcon');
  const temp = document.getElementById('weatherHeroTemp');
  const desc = document.getElementById('weatherHeroDesc');
  const loc = document.getElementById('weatherHeroLoc');
  const feels = document.getElementById('weatherParamFeels');
  const hum = document.getElementById('weatherParamHumidity');
  const wind = document.getElementById('weatherParamWind');
  const press = document.getElementById('weatherParamPressure');
  const fcSection = document.getElementById('weatherForecastSection');
  const fcGrid = document.getElementById('weatherForecastGrid');
  const advText = document.getElementById('weatherGenAdviceText');
  const sync = document.getElementById('weatherSyncTime');

  if (icon) icon.innerText = w.icon_emoji || '⛅';
  if (temp) temp.innerText = w.temp_formatted || `${w.temp_c}°C`;
  if (desc) desc.innerText = w.description || 'Хмарно';
  const cleanCity = (w.city || '').replace(/^(?:м\.|місто|смт|с\.)\s*/i, '').replace(/[,;].*$/, '').trim();
  if (loc) loc.innerText = `📍 м. ${cleanCity || 'Самар'}`;
  if (feels) feels.innerText = w.feels_like_formatted || `${w.feels_like_c}°C`;
  if (hum) hum.innerText = `${w.humidity_percent}%`;
  if (wind) wind.innerText = `${w.wind_speed_mps} м/с`;
  if (press) press.innerText = `${w.pressure_mmhg} мм рт. ст.`;

  if (fcSection && fcGrid) {
    const days = Array.isArray(w.forecast) ? w.forecast : [];
    if (days.length > 0) {
      fcGrid.innerHTML = days.map((d) => {
        const popHtml = (d.pop_percent && d.pop_percent >= 20)
          ? `<span class="fc-day-pop">💧 ${d.pop_percent}%</span>`
          : `<span class="fc-day-pop fc-day-pop-empty">&nbsp;</span>`;
        const safeDesc = String(d.description || '').replace(/"/g, '&quot;');
        return `
          <div class="weather-forecast-day" title="${safeDesc}">
            <span class="fc-day-label">${d.day_label || d.date}</span>
            <span class="fc-day-icon">${d.icon_emoji || '⛅'}</span>
            <div class="fc-day-temps">
              <span class="fc-temp-max">${d.temp_max_formatted || ''}</span>
              <span class="fc-temp-min">${d.temp_min_formatted || ''}</span>
            </div>
            ${popHtml}
          </div>
        `;
      }).join('');
      fcSection.style.display = 'block';
    } else {
      fcGrid.innerHTML = '';
      fcSection.style.display = 'none';
    }
  }

  if (advText) {
    let tip = w.generator_tip || 'Штатні умови експлуатації генератора.';
    if (typeof w.temp_c === 'number' && w.temp_c < 0) {
      if (window.isDieselGenerator(currentGenerator)) {
        tip = `❄️ На об'єкті ${w.temp_formatted || `${Math.round(w.temp_c)}°C`}: переконайтесь, що залито зимове ДП, та прогрійте двигун 3–5 хв без навантаження.`;
      } else {
        tip = `❄️ На об'єкті ${w.temp_formatted || `${Math.round(w.temp_c)}°C`}: перед подачею навантаження прогрійте бензиновий двигун 2–3 хв на холостому ходу.`;
      }
    }
    advText.innerText = tip;
  }
  if (sync) {
    let dtStr = 'щойно';
    if (w.updated_at) {
      try {
        let rawIso = String(w.updated_at);
        if (!rawIso.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(rawIso)) {
          rawIso += 'Z';
        }
        dtStr = new Date(rawIso).toLocaleTimeString('uk-UA', {
          timeZone: 'Europe/Kyiv',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit'
        });
      } catch (_) {
        dtStr = 'щойно';
      }
    }
    sync.innerText = `Оновлено: ${dtStr} (Київ)`;
  }
};

window.openAlertModal = function() {
  if (!window._currentAlertData) {
    if (currentFacilityId) window.loadFacilityIndicators(currentFacilityId);
  }
  window.populateAlertModal(window._currentAlertData);
  openModal('modalAlertDetails');
};

window.populateAlertModal = function(a) {
  if (!a) return;
  const heroCard = document.getElementById('alertHeroCard');
  const heroIcon = document.getElementById('alertHeroIcon');
  const heroStatus = document.getElementById('alertHeroStatus');
  const heroThreat = document.getElementById('alertHeroThreat');
  const heroLoc = document.getElementById('alertHeroLoc');
  const heroTime = document.getElementById('alertHeroTime');
  const verifBanner = document.getElementById('alertVerificationBanner');
  const verifIcon = document.getElementById('alertVerificationIcon');
  const verifText = document.getElementById('alertVerificationText');
  const advBody = document.getElementById('alertAdviceBody');
  const provEl = document.getElementById('alertSyncProvider');

  const level = a.level || 'green';
  const tType = (a.threat_type || '').toLowerCase();
  if (heroCard) {
    heroCard.className = `alert-hero-card hero-alert-${level}`;
  }
  if (heroIcon) heroIcon.innerText = a.threat_icon || (level === 'green' ? '🟢' : '🚨');
  if (heroStatus) {
    if (level === 'red') {
      if (tType.includes('artillery') || tType.includes('shelling')) {
        heroStatus.innerText = 'ЗАГРОЗА АРТОБСТРІЛУ';
      } else if (tType.includes('bombs') || tType.includes('kab')) {
        heroStatus.innerText = 'ЗАГРОЗА АВІАБОМБ (КАБ)';
      } else if (tType.includes('ballistic')) {
        heroStatus.innerText = 'ЗАГРОЗА БАЛІСТИКИ';
      } else if (tType.includes('mig31k')) {
        heroStatus.innerText = 'РАКЕТНА НЕБЕЗПЕКА (МіГ-31К)';
      } else if (tType === 'cruise' || tType === 'cruise_missiles') {
        heroStatus.innerText = 'РАКЕТНА НЕБЕЗПЕКА';
      } else {
        heroStatus.innerText = 'ПОВІТРЯНА ТРИВОГА';
      }
    } else if (level === 'yellow') {
      heroStatus.innerText = 'ПІДВИЩЕНА ЗАГРОЗА (БПЛА)';
    } else {
      heroStatus.innerText = 'ВІДБІЙ ТРИВОГИ (БЕЗПЕЧНО)';
    }
  }
  if (heroThreat) heroThreat.innerText = a.threat_title || 'Загроз не зафіксовано';
  if (heroLoc) heroLoc.innerText = window.formatLocationDisplay(a.region_name, a.city);

  if (heroTime) {
    if (a.is_active && a.started_at) {
      try {
        let rawStart = String(a.started_at);
        if (!rawStart.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(rawStart)) {
          rawStart += 'Z';
        }
        const dt = new Date(rawStart);
        const timeStr = dt.toLocaleTimeString('uk-UA', {
          timeZone: 'Europe/Kyiv',
          hour: '2-digit',
          minute: '2-digit'
        });
        const durMin = a.duration_minutes || Math.max(1, Math.floor((Date.now() - dt.getTime()) / 60000));
        heroTime.innerText = `⏱ Триває з ${timeStr} (${durMin} хв)`;
        heroTime.style.display = 'inline-block';
      } catch (e) {
        heroTime.style.display = 'none';
      }
    } else {
      heroTime.style.display = 'none';
    }
  }

  if (verifBanner && verifText && verifIcon) {
    const vStatus = a.verification_status || 'verified';
    let vClass = 'verif-verified';
    let vEmoji = '✅';
    let defaultNote = 'Підтверджено обома джерелами (Alerts.in.ua + UkraineAlarm)';

    if (vStatus === 'insurance_hold') {
      vClass = 'verif-insurance';
      vEmoji = '🛡️';
      defaultNote = 'Страхування відбою: утримується вищий рівень безпеки';
    } else if (vStatus === 'single_source' || vStatus === 'mock') {
      vClass = 'verif-single';
      vEmoji = 'ℹ️';
      defaultNote = 'Моніторинг за одним джерелом';
    }

    verifBanner.className = `alert-verification-banner ${vClass}`;
    verifIcon.innerText = vEmoji;
    verifText.innerText = a.verification_note || defaultNote;
  }

  if (advBody) advBody.innerText = a.operator_advice || 'Дозволено штатну роботу.';
  if (provEl) provEl.innerText = `Джерела: ${a.provider || 'Alerts.in.ua + UkraineAlarm'}`;
};
