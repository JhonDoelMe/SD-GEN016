// ==========================================
// 9. Push Notifications & PWA Mobile Alerts
// ==========================================

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function areUint8ArraysEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

const _seenNotifLogIds = new Set();

function getToastTypeForNotificationEvent(eventType) {
  switch (eventType) {
    case 'AIR_ALERT_START':
    case 'CRITICAL_FAULT':
    case 'GENERATOR_SAFETY_STOP':
      return 'error';
    case 'AIR_ALERT_END':
    case 'GENERATOR_START':
      return 'success';
    case 'LOW_FUEL':
    case 'MAINTENANCE_DUE':
    case 'YASNO_OUTAGE_ALERT':
    case 'GENERATOR_HEARTBEAT':
    case 'FUEL_DISCREPANCY':
      return 'warning';
    default:
      return 'info';
  }
}

window.syncPushSubscriptionWithServer = async function(silent = true) {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    return false;
  }
  if (!token || !currentUser || Notification.permission !== 'granted') {
    return false;
  }

  try {
    const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` };
    const vapidFetch = await fetch('/api/v1/notifications/vapid-public-key', { headers });
    if (!vapidFetch.ok) return false;
    const vapidRes = await vapidFetch.json();
    if (!vapidRes || !vapidRes.public_key) return false;

    const applicationServerKey = urlBase64ToUint8Array(vapidRes.public_key);
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();

    // Verify existing browser subscription's applicationServerKey matches current server VAPID key
    if (sub && sub.options && sub.options.applicationServerKey) {
      const existingKey = new Uint8Array(sub.options.applicationServerKey);
      if (!areUint8ArraysEqual(existingKey, applicationServerKey)) {
        try { await sub.unsubscribe(); } catch (_) {}
        sub = null;
      }
    }

    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey
      });
    }

    const buildSubPayload = (s) => {
      const sj = s.toJSON();
      return {
        endpoint: s.endpoint,
        keys: {
          p256dh: sj.keys.p256dh,
          auth: sj.keys.auth
        },
        user_agent: navigator.userAgent,
        facility_id: (currentUser && currentUser.facility_id) ? currentUser.facility_id : null
      };
    };

    let subRes = await fetch('/api/v1/notifications/subscribe', {
      method: 'POST',
      headers,
      body: JSON.stringify(buildSubPayload(sub))
    });

    // Self-heal if endpoint was previously bound to another user on this shared browser (403)
    if (subRes.status === 403) {
      try { await sub.unsubscribe(); } catch (_) {}
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey
      });
      subRes = await fetch('/api/v1/notifications/subscribe', {
        method: 'POST',
        headers,
        body: JSON.stringify(buildSubPayload(sub))
      });
    }

    if (!subRes.ok) {
      if (!silent) {
        const errData = await subRes.json().catch(() => null);
        throw new Error(extractErrorMessage(errData, `Помилка реєстрації підписки (${subRes.status})`));
      }
      return false;
    }

    checkPushSubscriptionStatus();
    return true;
  } catch (err) {
    if (!silent) {
      showToast('Помилка підписки: ' + err.message, 'error');
    } else {
      console.warn('Auto push sync:', err);
    }
    return false;
  }
};

window.pollRecentNotifications = async function(isInitial = false) {
  if (!token || !currentUser || !hasPermission('notifications:view')) return;
  try {
    const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` };
    const res = await fetch('/api/v1/notifications/logs?limit=5', { headers });
    if (!res.ok) return;
    const logs = await res.json();
    if (!Array.isArray(logs) || logs.length === 0) return;

    let lastSeenId = parseInt(localStorage.getItem('sd_last_seen_notif_id') || '0', 10);
    const nowMs = Date.now();

    if (!lastSeenId && isInitial) {
      const newest = logs[0];
      let newestAgeMs = Infinity;
      if (newest && newest.created_at) {
        const iso = String(newest.created_at).endsWith('Z') ? newest.created_at : `${newest.created_at}Z`;
        newestAgeMs = nowMs - new Date(iso).getTime();
      }
      if (newest && newestAgeMs <= 90000) {
        lastSeenId = Math.max(0, newest.id - 1);
      } else {
        localStorage.setItem('sd_last_seen_notif_id', String(newest.id));
        return;
      }
    }

    const freshLogs = logs
      .filter((l) => l && l.id > lastSeenId && !_seenNotifLogIds.has(l.id))
      .sort((a, b) => a.id - b.id);

    if (freshLogs.length === 0) return;

    let maxId = lastSeenId;
    for (const log of freshLogs) {
      if (log.id > maxId) maxId = log.id;
      _seenNotifLogIds.add(log.id);

      // Filter by user's facility if non-admin restricted to a facility
      if (!isAdmin() && currentUser.facility_id && log.facility_id && log.facility_id !== currentUser.facility_id) {
        continue;
      }

      // Only alert for recent notifications (within last 10 minutes)
      let ageMs = 0;
      if (log.created_at) {
        const rawIso = String(log.created_at);
        const iso = (rawIso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(rawIso)) ? rawIso : `${rawIso}Z`;
        ageMs = nowMs - new Date(iso).getTime();
      }
      if (ageMs > 600000) continue;

      const tType = getToastTypeForNotificationEvent(log.event_type);
      showToast(`${log.title} — ${log.body}`, tType, 7500);

      // Also show native OS / Browser notification (deduplicated by tag 'sd-log-{id}' if WebPush already showed it)
      if ('Notification' in window && Notification.permission === 'granted' && 'serviceWorker' in navigator) {
        try {
          const reg = await navigator.serviceWorker.ready;
          await reg.showNotification(log.title, {
            body: log.body,
            icon: '/frontend/icons/icon-192.png',
            badge: '/frontend/icons/icon-192.png',
            tag: `sd-log-${log.id}`,
            renotify: false,
            data: {
              url: '/?tab=tab-dashboard',
              event_type: log.event_type,
              log_id: log.id
            }
          });
        } catch (_) {}
      }
    }

    if (maxId > lastSeenId) {
      localStorage.setItem('sd_last_seen_notif_id', String(maxId));
    }
  } catch (_) {}
};

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.addEventListener('message', (event) => {
    const msg = event.data;
    if (!msg || typeof msg !== 'object') return;
    if (msg.type === 'PUSH_SUBSCRIPTION_CHANGED') {
      window.syncPushSubscriptionWithServer(true);
      return;
    }
    if (msg.type === 'PUSH_NOTIFICATION_RECEIVED' && msg.payload) {
      const p = msg.payload;
      const logId = p.data && p.data.log_id ? Number(p.data.log_id) : null;
      if (logId) {
        _seenNotifLogIds.add(logId);
        const prevMax = parseInt(localStorage.getItem('sd_last_seen_notif_id') || '0', 10);
        if (logId > prevMax) {
          localStorage.setItem('sd_last_seen_notif_id', String(logId));
        }
      }
      const evType = p.data && p.data.event_type ? String(p.data.event_type) : '';
      const tType = getToastTypeForNotificationEvent(evType);
      showToast(`${p.title || 'Сповіщення'} — ${p.body || ''}`, tType, 7500);

      if (currentFacilityId && (evType.startsWith('AIR_ALERT') || evType.startsWith('YASNO') || evType.startsWith('GENERATOR'))) {
        loadFacilityIndicators(currentFacilityId, true);
        loadGeneratorData();
      }
    }
  });
}

async function checkPushSubscriptionStatus() {
  const badge = document.getElementById('pushStatusBadge');
  const infoText = document.getElementById('pushDeviceInfoText');
  const btnSub = document.getElementById('btnSubscribePush');
  const btnUnsub = document.getElementById('btnUnsubscribePush');

  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    if (badge) {
      badge.className = 'badge badge-faulty';
      badge.innerText = 'НЕ ПІДТРИМУЄТЬСЯ';
    }
    if (infoText) {
      infoText.innerHTML = '⚠️ Ваш поточний браузер не підтримує Web Push API. Для отримання системних сповіщень у шторку використовуйте Google Chrome, Samsung Internet або встановіть додаток через меню PWA.';
    }
    if (btnSub) btnSub.style.display = 'none';
    if (btnUnsub) btnUnsub.style.display = 'none';
    return;
  }

  const permission = Notification.permission;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();

    if (sub && permission === 'granted') {
      if (badge) {
        badge.className = 'badge badge-running';
        badge.innerText = 'АКТИВНО 📲';
      }
      if (infoText) {
        infoText.innerHTML = '✅ <b>Сповіщення увімкнено!</b> Цей пристрій успішно підписаний на системні сповіщення (включно з повітряними тривогами та відбоями). Повідомлення надходитимуть у шторку пристрою, на екран блокування та на сайт.';
      }
      if (btnSub) btnSub.style.display = 'none';
      if (btnUnsub) btnUnsub.style.display = 'inline-block';
    } else if (permission === 'denied') {
      if (badge) {
        badge.className = 'badge badge-faulty';
        badge.innerText = 'ЗАБЛОКОВАНО';
      }
      if (infoText) {
        infoText.innerHTML = '🚫 <b>Дозвіл заблоковано в налаштуваннях браузера.</b> Щоб отримувати сповіщення, натисніть на значок замочка біля адреси сайту та дозвольте «Сповіщення».';
      }
      if (btnSub) {
        btnSub.style.display = 'inline-block';
        btnSub.disabled = true;
      }
      if (btnUnsub) btnUnsub.style.display = 'none';
    } else {
      if (badge) {
        badge.className = 'badge badge-stopped';
        badge.innerText = 'НЕ ПІДКЛЮЧЕНО';
      }
      if (infoText) {
        infoText.innerHTML = 'ℹ️ Сповіщення на цьому пристрої ще не увімкнені. Натисніть кнопку нижче, щоб отримувати сповіщення про повітряні тривоги, відбій, ТО, старт/стоп та залишок палива.';
      }
      if (btnSub) {
        btnSub.style.display = 'inline-block';
        btnSub.disabled = false;
      }
      if (btnUnsub) btnUnsub.style.display = 'none';
    }
  } catch (err) {
    console.warn('Error checking push subscription:', err);
  }
}

window.subscribeDevicePush = async function() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    showToast('Web Push не підтримується цим браузером', 'error');
    return;
  }

  try {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') {
      showToast('Дозвіл на сповіщення не надано користувачем', 'warning');
      checkPushSubscriptionStatus();
      return;
    }

    const ok = await window.syncPushSubscriptionWithServer(false);
    if (ok) {
      showToast('Пристрій успішно підписано на сповіщення!', 'success');
      checkPushSubscriptionStatus();
      loadNotificationSettings();
    }
  } catch (err) {
    showToast('Помилка підписки: ' + err.message, 'error');
  }
};

window.unsubscribeDevicePush = async function() {
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      try {
        await api('/notifications/unsubscribe', {
          method: 'POST',
          body: JSON.stringify({ endpoint: sub.endpoint })
        });
      } catch (_) {}
      await sub.unsubscribe();
    }
    showToast('Сповіщення для цього пристрою вимкнено', 'info');
    checkPushSubscriptionStatus();
    loadNotificationSettings();
  } catch (err) {
    showToast('Помилка відписки: ' + err.message, 'error');
  }
};

window.triggerTestPushNotification = async function() {
  try {
    showToast('Відправка тестового сповіщення...', 'info');
    // Ensure device subscription is synced before testing
    if (Notification.permission === 'granted') {
      await window.syncPushSubscriptionWithServer(true);
    }
    const res = await api('/notifications/test', {
      method: 'POST',
      body: JSON.stringify({
        title: '🔔 Тестове сповіщення Service Desk',
        body: 'Система сповіщень працює належним чином на вашому пристрої!'
      })
    });

    // Also trigger local notification if permission is granted as an instant preview
    if (Notification.permission === 'granted' && navigator.serviceWorker) {
      const reg = await navigator.serviceWorker.ready;
      reg.showNotification('🔔 Тестове сповіщення Service Desk', {
        body: 'Перевірка звуку, вібрації та шторки повідомлень виконана успішно!',
        icon: '/frontend/icons/icon-192.png',
        badge: '/frontend/icons/icon-192.png',
        vibrate: [200, 100, 200],
        tag: 'sd-test'
      });
    }

    showToast(`Тестове сповіщення успішно надіслано (доставлено: ${res.sent || 1})`, 'success');
    loadNotificationLogs();
  } catch (err) {
    showToast('Помилка відправки: ' + err.message, 'error');
  }
};

async function loadNotificationSettings() {
  try {
    const s = await api('/notifications/settings');
    const setCheck = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };

    setCheck('notifMasterEnabled', s.notifications_enabled);
    setCheck('notifStartEnabled', s.notify_generator_start);
    setCheck('notifStopEnabled', s.notify_generator_stop);
    setCheck('notifLowFuelEnabled', s.notify_low_fuel);
    setVal('notifLowFuelThreshold', s.low_fuel_threshold_l);
    setCheck('notifMaintEnabled', s.notify_maintenance);
    setVal('notifMaxMaintPerDay', s.max_maintenance_notifications_per_day);
    setCheck('notifFaultsEnabled', s.notify_critical_faults);
    setCheck('notifAirAlertsEnabled', s.notify_air_alerts !== false);
    setCheck('notifAirAlertEndEnabled', s.notify_air_alert_end !== false);
    setCheck('notifYasnoEnabled', s.notify_yasno_outages !== false);
  } catch (_) {}
}

window.saveNotificationSettings = async function(e) {
  if (e) e.preventDefault();
  const body = {
    notifications_enabled: document.getElementById('notifMasterEnabled')?.checked ?? true,
    notify_generator_start: document.getElementById('notifStartEnabled')?.checked ?? true,
    notify_generator_stop: document.getElementById('notifStopEnabled')?.checked ?? true,
    notify_low_fuel: document.getElementById('notifLowFuelEnabled')?.checked ?? true,
    low_fuel_threshold_l: parseFloat(document.getElementById('notifLowFuelThreshold')?.value || '5.0'),
    notify_maintenance: document.getElementById('notifMaintEnabled')?.checked ?? true,
    max_maintenance_notifications_per_day: parseInt(document.getElementById('notifMaxMaintPerDay')?.value || '2', 10),
    notify_critical_faults: document.getElementById('notifFaultsEnabled')?.checked ?? true,
    notify_air_alerts: document.getElementById('notifAirAlertsEnabled')?.checked ?? true,
    notify_air_alert_end: document.getElementById('notifAirAlertEndEnabled')?.checked ?? true,
    notify_yasno_outages: document.getElementById('notifYasnoEnabled')?.checked ?? true
  };

  try {
    await api('/notifications/settings', {
      method: 'PUT',
      body: JSON.stringify(body)
    });
    showToast('Налаштування сповіщень успішно збережено!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
};

async function loadNotificationLogs() {
  try {
    const logs = await api('/notifications/logs?limit=100');
    const eventIcons = {
      'GENERATOR_START': '🟢 Пуск',
      'GENERATOR_STOP': '🔴 Зупинка',
      'GENERATOR_SAFETY_STOP': '🛑 Автостоп',
      'GENERATOR_AUTO_STOP': '🕒 Графік',
      'GENERATOR_HEARTBEAT': '⏱️ Робота',
      'LOW_FUEL': '⚠️ Паливо',
      'FUEL_DISCREPANCY': '⛽ Баланс',
      'MAINTENANCE_DUE': '🔧 ТО',
      'CRITICAL_FAULT': '🚨 Аварія',
      'AIR_ALERT_START': '🚨 Тривога',
      'AIR_ALERT_END': '🟢 Відбій',
      'YASNO_OUTAGE_ALERT': '⚡ YASNO',
      'TEST': '📲 Тест'
    };

    window.renderPaginatedTable('notifLogsTable', logs, l => `
      <tr>
        <td>${formatDateTime(l.created_at)}</td>
        <td><b>${eventIcons[l.event_type] || l.event_type}</b></td>
        <td><b>${escapeHtml(l.title)}</b></td>
        <td>${escapeHtml(l.body)}</td>
        <td>${l.recipients_count} пристр.</td>
        <td>
          <span style="color: ${l.success_count > 0 ? '#4ade80' : 'var(--text-muted)'};">
            ${l.success_count > 0 ? `✅ Доставлено (${l.success_count})` : (l.recipients_count === 0 ? 'ℹ️ На сайті / В додатку' : '⚠️ Помилка Push')}
          </span>
        </td>
      </tr>
    `, 6, 'Журнал сповіщень порожній', 10);
  } catch (_) {}
}

window.clearNotificationLogs = async function() {
  if (!confirm('Ви дійсно бажаєте безповоротно очистити весь журнал надісланих сповіщень?')) {
    return;
  }
  try {
    const res = await api('/notifications/logs', { method: 'DELETE' });
    showToast(`Журнал сповіщень успішно очищено (видалено записів: ${res.deleted_count || 0})`, 'success');
    await loadNotificationLogs();
  } catch (err) {
    showToast('Помилка очищення журналу: ' + (err.message || 'Невідома помилка'), 'error');
  }
};

// Initialization on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  startClock();
  setupPwaInstall();
  checkAuth();
  refreshServerStatus();
  setInterval(() => {
    if (!document.hidden) refreshServerStatus();
  }, 30000);
  setTimeout(checkPushSubscriptionStatus, 1500);

  // Audit export modal trigger listener
  document.getElementById('btnOpenExportAudit')?.addEventListener('click', (e) => {
    e.preventDefault();
    openAuditExportModal();
  });

  // Forgot password link listener
  document.getElementById('linkForgotPassword')?.addEventListener('click', (e) => {
    e.preventDefault();
    openForgotPasswordModal();
  });

  // Settings Fuel Provider tab switchers
  document.getElementById('tabFuelProviderWog')?.addEventListener('click', (e) => {
    e.preventDefault();
    window.switchSettingsFuelProvider('wog');
  });
  document.getElementById('tabFuelProviderOkko')?.addEventListener('click', (e) => {
    e.preventDefault();
    window.switchSettingsFuelProvider('okko');
  });

  // Check for reset_token in URL query parameters
  const urlParams = new URLSearchParams(window.location.search);
  const resetToken = urlParams.get('reset_token');
  if (resetToken) {
    const tokenInput = document.getElementById('resetPasswordToken');
    if (tokenInput) tokenInput.value = resetToken;
    const rfb = document.getElementById('resetPasswordFeedback');
    if (rfb) {
      rfb.className = 'feedback-box';
      rfb.innerText = '';
    }
    openModal('modalResetPassword');
    try {
      window.history.replaceState({}, document.title, window.location.pathname);
    } catch (_) {}
  }

  // Periodic background refresh for dashboard tiles (smart visibility-aware polling)
  let _isBgRefreshRunning = false;
  let _lastBgRefreshAt = Date.now();
  const runDashboardBackgroundRefresh = async () => {
    if (_isBgRefreshRunning || document.hidden || !token || !currentUser) return;
    _isBgRefreshRunning = true;
    _lastBgRefreshAt = Date.now();
    try {
      const tasks = [
        loadGeneratorData(),
        loadFacilityOutageSchedule(currentFacilityId),
        loadFacilityIndicators(currentFacilityId),
        window.pollRecentNotifications(false)
      ];
      if (!isViewerOnly() && hasPermission('fuel:view')) {
        tasks.push(loadFuelSummary());
      }
      if (!isViewerOnly() && hasPermission('maintenance:view')) {
        tasks.push(loadMaintenanceSummary());
      }
      await Promise.allSettled(tasks);
    } finally {
      _isBgRefreshRunning = false;
    }
  };

  setInterval(runDashboardBackgroundRefresh, 15000);

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && token && currentUser && (Date.now() - _lastBgRefreshAt > 5000)) {
      refreshServerStatus();
      runDashboardBackgroundRefresh();
    }
  });
});




