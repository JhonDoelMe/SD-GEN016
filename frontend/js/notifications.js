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
const FCM_TOKEN_STORAGE_KEY = 'sd_fcm_device_token';
const FCM_OPT_OUT_KEY = 'sd_fcm_opted_out';
let _fcmListenersBound = false;

function getNativeFcmPlugin() {
  if (
    window.Capacitor &&
    typeof window.Capacitor.isNativePlatform === 'function' &&
    window.Capacitor.isNativePlatform() &&
    window.Capacitor.Plugins &&
    window.Capacitor.Plugins.FcmPush
  ) {
    return window.Capacitor.Plugins.FcmPush;
  }
  return null;
}

function bindNativeFcmListeners(fcmPlugin) {
  if (_fcmListenersBound || !fcmPlugin || typeof fcmPlugin.addListener !== 'function') return;
  _fcmListenersBound = true;

  fcmPlugin.addListener('fcmTokenRefresh', async (ev) => {
    const newToken = ev && ev.token ? String(ev.token).trim() : '';
    if (!newToken) return;
    localStorage.setItem(FCM_TOKEN_STORAGE_KEY, newToken);
    if (token && currentUser && localStorage.getItem(FCM_OPT_OUT_KEY) !== '1') {
      try {
        await api('/notifications/fcm/subscribe', {
          method: 'POST',
          body: JSON.stringify({
            token: newToken,
            user_agent: navigator.userAgent,
            facility_id: currentUser.facility_id || null,
          }),
        });
      } catch (_) {}
    }
  });

  fcmPlugin.addListener('fcmPushReceived', (p) => {
    if (!p || typeof p !== 'object') return;
    const logId = p.logId ? Number(p.logId) : null;
    if (logId) {
      _seenNotifLogIds.add(logId);
      const prevMax = parseInt(localStorage.getItem('sd_last_seen_notif_id') || '0', 10);
      if (logId > prevMax) {
        localStorage.setItem('sd_last_seen_notif_id', String(logId));
      }
    }
    const evType = p.eventType ? String(p.eventType) : '';
    const tType = getToastTypeForNotificationEvent(evType);
    showToast(`${p.title || 'Сповіщення'} — ${p.body || ''}`, tType, 7500);
    if (currentFacilityId && (evType.startsWith('AIR_ALERT') || evType.startsWith('YASNO') || evType.startsWith('GENERATOR'))) {
      loadFacilityIndicators(currentFacilityId, true);
      loadGeneratorData();
    }
  });
}

function getToastTypeForNotificationEvent(eventType) {
  switch (eventType) {
    case 'AIR_ALERT_START':
    case 'CRITICAL_FAULT':
    case 'GENERATOR_SAFETY_STOP':
    case 'EMPTY_TANK':
      return 'error';
    case 'AIR_ALERT_END':
    case 'GENERATOR_START':
      return 'success';
    case 'LOW_FUEL':
    case 'MAINTENANCE_DUE':
    case 'YASNO_OUTAGE_ALERT':
    case 'GENERATOR_HEARTBEAT':
    case 'FUEL_DISCREPANCY':
    case 'OUTSIDE_WORK_HOURS':
    case 'GENERATOR_AUTO_STOP':
      return 'warning';
    default:
      return 'info';
  }
}

window.syncPushSubscriptionWithServer = async function(silent = true) {
  const fcmPlugin = getNativeFcmPlugin();
  if (fcmPlugin) {
    bindNativeFcmListeners(fcmPlugin);
    if (!token || !currentUser || localStorage.getItem(FCM_OPT_OUT_KEY) === '1') {
      return false;
    }
    try {
      const st = await fcmPlugin.getStatus();
      if (!st || !st.isFirebaseConfigured || st.permissionState !== 'granted') {
        return false;
      }
      const regRes = await fcmPlugin.register();
      const fcmToken = regRes && regRes.token ? String(regRes.token).trim() : '';
      if (!fcmToken) return false;
      localStorage.setItem(FCM_TOKEN_STORAGE_KEY, fcmToken);
      await api('/notifications/fcm/subscribe', {
        method: 'POST',
        body: JSON.stringify({
          token: fcmToken,
          user_agent: navigator.userAgent,
          facility_id: currentUser.facility_id || null,
        }),
      });
      checkPushSubscriptionStatus();
      return true;
    } catch (err) {
      if (!silent) {
        showToast('Помилка підписки Android Push: ' + err.message, 'error');
      }
      return false;
    }
  }

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
    if (typeof window.loadBellFeed === 'function') {
      window.loadBellFeed(false);
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
      if (typeof window.loadBellFeed === 'function') {
        window.loadBellFeed(false);
      }
    }
  });
}

async function checkPushSubscriptionStatus() {
  const badge = document.getElementById('pushStatusBadge');
  const infoText = document.getElementById('pushDeviceInfoText');
  const btnSub = document.getElementById('btnSubscribePush');
  const btnUnsub = document.getElementById('btnUnsubscribePush');

  const fcmPlugin = getNativeFcmPlugin();
  if (fcmPlugin) {
    bindNativeFcmListeners(fcmPlugin);
    try {
      const nativeStatus = await fcmPlugin.getStatus();
      let serverConfigured = false;
      if (token) {
        try {
          const srv = await api('/notifications/fcm/status');
          serverConfigured = Boolean(srv && srv.configured);
        } catch (_) {}
      }

      if (!nativeStatus || !nativeStatus.isFirebaseConfigured || (token && !serverConfigured)) {
        if (badge) {
          badge.className = 'badge badge-stopped';
          badge.innerText = 'ОЧІКУЄ FIREBASE';
        }
        if (infoText) {
          const missingClient = !nativeStatus || !nativeStatus.isFirebaseConfigured;
          const missingServer = token && !serverConfigured;
          const details = missingClient && missingServer
            ? 'У збірці APK відсутній google-services.json, а на сервері — ключ Firebase.'
            : (missingClient
              ? 'У цій збірці APK ще не підключено google-services.json.'
              : 'На сервері ще не додано Firebase Service Account JSON.');
          infoText.innerHTML = `⚙️ <b>Модуль Android Push (FCM) готовий до роботи.</b> ${details}`;
        }
        if (btnSub) {
          btnSub.style.display = 'inline-block';
          btnSub.disabled = true;
        }
        if (btnUnsub) btnUnsub.style.display = 'none';
        return;
      }

      const perm = nativeStatus.permissionState;
      const savedToken = localStorage.getItem(FCM_TOKEN_STORAGE_KEY);
      const optedOut = localStorage.getItem(FCM_OPT_OUT_KEY) === '1';

      if (perm === 'granted' && savedToken && !optedOut) {
        if (badge) {
          badge.className = 'badge badge-running';
          badge.innerText = 'АКТИВНО (ANDROID) 📲';
        }
        if (infoText) {
          infoText.innerHTML = '✅ <b>Нативні Android Push-сповіщення увімкнено!</b> Повідомлення надходитимуть у шторку та на екран блокування через Firebase Cloud Messaging, навіть коли додаток закрито.';
        }
        if (btnSub) btnSub.style.display = 'none';
        if (btnUnsub) btnUnsub.style.display = 'inline-block';
      } else if (perm === 'denied') {
        if (badge) {
          badge.className = 'badge badge-faulty';
          badge.innerText = 'ЗАБЛОКОВАНО';
        }
        if (infoText) {
          infoText.innerHTML = '🚫 <b>Дозвіл на сповіщення вимкнено в налаштуваннях Android.</b> Відкрийте Налаштування → Програми → SD-GEN016 → Сповіщення та увімкніть їх.';
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
          infoText.innerHTML = 'ℹ️ Натисніть кнопку нижче, щоб дозволити нативні push-сповіщення Android (тривоги, аварії, запуск/зупинка генератора, ТО та паливо).';
        }
        if (btnSub) {
          btnSub.style.display = 'inline-block';
          btnSub.disabled = false;
        }
        if (btnUnsub) btnUnsub.style.display = 'none';
      }
    } catch (err) {
      console.warn('Error checking native FCM push status:', err);
    }
    return;
  }

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
  const fcmPlugin = getNativeFcmPlugin();
  if (fcmPlugin) {
    try {
      const regRes = await fcmPlugin.register();
      if (!regRes || !regRes.granted) {
        showToast('Дозвіл на сповіщення не надано користувачем', 'warning');
        checkPushSubscriptionStatus();
        return;
      }
      const fcmToken = regRes.token ? String(regRes.token).trim() : '';
      if (!fcmToken) {
        showToast('Не вдалося отримати FCM токен пристрою', 'error');
        return;
      }
      localStorage.setItem(FCM_TOKEN_STORAGE_KEY, fcmToken);
      localStorage.removeItem(FCM_OPT_OUT_KEY);
      await api('/notifications/fcm/subscribe', {
        method: 'POST',
        body: JSON.stringify({
          token: fcmToken,
          user_agent: navigator.userAgent,
          facility_id: currentUser ? (currentUser.facility_id || null) : null,
        }),
      });
      showToast('Android Push-сповіщення успішно увімкнено!', 'success');
      checkPushSubscriptionStatus();
      loadNotificationSettings();
    } catch (err) {
      showToast('Помилка підписки Android Push: ' + err.message, 'error');
    }
    return;
  }

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
  const fcmPlugin = getNativeFcmPlugin();
  if (fcmPlugin) {
    try {
      const savedToken = localStorage.getItem(FCM_TOKEN_STORAGE_KEY);
      if (savedToken) {
        try {
          await api('/notifications/fcm/unsubscribe', {
            method: 'POST',
            body: JSON.stringify({ token: savedToken }),
          });
        } catch (_) {}
      }
      localStorage.removeItem(FCM_TOKEN_STORAGE_KEY);
      localStorage.setItem(FCM_OPT_OUT_KEY, '1');
      showToast('Android Push-сповіщення вимкнено', 'info');
      checkPushSubscriptionStatus();
      loadNotificationSettings();
    } catch (err) {
      showToast('Помилка відписки: ' + err.message, 'error');
    }
    return;
  }

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
  const fcmPlugin = getNativeFcmPlugin();
  if (fcmPlugin) {
    try {
      showToast('Відправка тестового Android Push-сповіщення...', 'info');
      await window.syncPushSubscriptionWithServer(true);
      const res = await api('/notifications/test', {
        method: 'POST',
        body: JSON.stringify({
          title: '🔔 Тестове сповіщення Service Desk',
          body: 'Нативні сповіщення Android (FCM) працюють належним чином!',
        }),
      });
      showToast(`Тестове сповіщення надіслано (доставлено: ${res.sent || 0})`, res.sent ? 'success' : 'warning');
      loadNotificationLogs();
    } catch (err) {
      showToast('Помилка відправки: ' + err.message, 'error');
    }
    return;
  }

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
    setCheck('notifOutsideScheduleEnabled', s.notify_outside_schedule !== false);
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
    notify_yasno_outages: document.getElementById('notifYasnoEnabled')?.checked ?? true,
    notify_outside_schedule: document.getElementById('notifOutsideScheduleEnabled')?.checked ?? true
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
      'OUTSIDE_WORK_HOURS': '⏰ Поза графіком',
      'GENERATOR_HEARTBEAT': '⏱️ Робота',
      'EMPTY_TANK': '🪫 Порожній бак',
      'LOW_FUEL': '⚠️ Паливо',
      'FUEL_DISCREPANCY': '⛽ Баланс',
      'MAINTENANCE_DUE': '🔧 ТО',
      'CRITICAL_FAULT': '🚨 Аварія',
      'AIR_ALERT_START': '🚨 Тривога',
      'AIR_ALERT_END': '🟢 Відбій',
      'YASNO_OUTAGE_ALERT': '⚡ YASNO',
      'EMAIL_SENT': '📧 Email',
      'EMAIL_FAILOVER': '📧 Резервний SMTP',
      'EMAIL_FAILED': '⚠️ Помилка Email',
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

// PWA Installation & First-Visit Prompt Logic (kept in core/notifications so it binds at boot)
let deferredInstallPrompt = null;

function setupPwaInstall() {
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const isIos = /iphone|ipad|ipod/.test(navigator.userAgent.toLowerCase());
  const banner = document.getElementById('pwaInstallBanner');
  const headerInstallBtn = document.getElementById('headerInstallBtn');
  const installBtn = document.getElementById('pwaInstallBtn');
  const dismissBtn = document.getElementById('pwaDismissBtn');

  if (isStandalone) {
    if (banner) banner.style.display = 'none';
    if (headerInstallBtn) headerInstallBtn.style.display = 'none';
    return;
  }

  const dismissedTime = localStorage.getItem('pwa_install_dismissed_at');
  const shouldShowPrompt = !dismissedTime || (Date.now() - parseInt(dismissedTime, 10) > 7 * 24 * 3600 * 1000);

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    if (headerInstallBtn) headerInstallBtn.style.display = 'inline-flex';
    if (shouldShowPrompt && banner) {
      banner.style.display = 'flex';
    }
  });

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

  const triggerInstallPrompt = async () => {
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
  };

  installBtn?.addEventListener('click', triggerInstallPrompt);
  headerInstallBtn?.addEventListener('click', triggerInstallPrompt);

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

// Initialization on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  startClock();
  setupPwaInstall();
  checkAuth();
  setInterval(() => {
    if (!document.hidden && token) refreshServerStatus();
  }, 30000);
  setTimeout(checkPushSubscriptionStatus, 1500);

  // Check for reset_token in URL query parameters
  const urlParams = new URLSearchParams(window.location.search);
  const resetToken = urlParams.get('reset_token');
  if (resetToken) {
    window.openModal('modalResetPassword').then(() => {
      const tokenInput = document.getElementById('resetPasswordToken');
      if (tokenInput) tokenInput.value = resetToken;
      const rfb = document.getElementById('resetPasswordFeedback');
      if (rfb) {
        rfb.className = 'feedback-box';
        rfb.innerText = '';
      }
    });
    try {
      window.history.replaceState({}, document.title, window.location.pathname);
    } catch (_) {}
  }

  // Periodic background refresh for active dashboard & header indicators
  let _isBgRefreshRunning = false;
  let _lastBgRefreshAt = Date.now();
  const runDashboardBackgroundRefresh = async () => {
    if (_isBgRefreshRunning || document.hidden || !token || !currentUser) return;
    _isBgRefreshRunning = true;
    _lastBgRefreshAt = Date.now();
    try {
      const tasks = [
        loadFacilityIndicators(currentFacilityId),
        window.pollRecentNotifications(false),
        window.loadBellFeed(false)
      ];
      if (!window.activeTabId || window.activeTabId === 'tab-dashboard') {
        tasks.push(loadGeneratorData());
        tasks.push(loadFacilityOutageSchedule(currentFacilityId));
        if (!isViewerOnly() && hasPermission('fuel:view') && typeof loadFuelSummary === 'function') {
          tasks.push(loadFuelSummary());
        }
        if (!isViewerOnly() && hasPermission('maintenance:view') && typeof loadMaintenanceSummary === 'function') {
          tasks.push(loadMaintenanceSummary());
        }
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

// ---------------------------------------------------------------------------
// Header Notification Bell (🔔) Feed & Interactive Popover
// ---------------------------------------------------------------------------
const _BELL_EVENT_EMOJI = {
  'GENERATOR_START': '🟢',
  'GENERATOR_STOP': '🔴',
  'GENERATOR_SAFETY_STOP': '🛑',
  'GENERATOR_AUTO_STOP': '🕒',
  'OUTSIDE_WORK_HOURS': '⏰',
  'GENERATOR_HEARTBEAT': '⏱️',
  'EMPTY_TANK': '🪫',
  'LOW_FUEL': '⚠️',
  'FUEL_DISCREPANCY': '⛽',
  'MAINTENANCE_DUE': '🔧',
  'CRITICAL_FAULT': '🚨',
  'AIR_ALERT_START': '🚨',
  'AIR_ALERT_END': '🟢',
  'YASNO_OUTAGE_ALERT': '⚡'
};

function _getBellTargetTab(eventType) {
  const viewer = typeof isViewerOnly === 'function' && isViewerOnly();
  switch (eventType) {
    case 'EMPTY_TANK':
    case 'LOW_FUEL':
    case 'FUEL_DISCREPANCY':
      return (!viewer && typeof hasPermission === 'function' && hasPermission('fuel:view')) ? 'tab-fuel' : 'tab-dashboard';
    case 'MAINTENANCE_DUE':
      return (!viewer && typeof hasPermission === 'function' && hasPermission('maintenance:view')) ? 'tab-maintenance' : 'tab-dashboard';
    case 'CRITICAL_FAULT':
      return (!viewer && typeof hasPermission === 'function' && hasPermission('faults:view')) ? 'tab-faults' : 'tab-dashboard';
    case 'GENERATOR_START':
    case 'GENERATOR_STOP':
    case 'GENERATOR_SAFETY_STOP':
    case 'GENERATOR_AUTO_STOP':
    case 'OUTSIDE_WORK_HOURS':
    case 'GENERATOR_HEARTBEAT':
      return (!viewer && typeof hasPermission === 'function' && hasPermission('runs:view')) ? 'tab-runs' : 'tab-dashboard';
    default:
      return 'tab-dashboard';
  }
}

function _renderBellFeed(data) {
  const badge = document.getElementById('bellUnreadCount');
  const bellBtn = document.getElementById('headerBellBadge');
  const listEl = document.getElementById('notificationsBellList');
  const openAllBtn = document.getElementById('btnOpenAllNotifs');
  if (!listEl) return;

  if (openAllBtn) {
    const canViewNotifTab = !(typeof isViewerOnly === 'function' && isViewerOnly())
      && typeof hasPermission === 'function'
      && hasPermission('notifications:view');
    openAllBtn.style.display = canViewNotifTab ? 'inline-block' : 'none';
  }

  const unreadCount = Number(data?.unread_count || 0);
  if (badge) {
    if (unreadCount > 0) {
      badge.innerText = unreadCount > 99 ? '99+' : String(unreadCount);
      badge.style.display = 'inline-flex';
    } else {
      badge.style.display = 'none';
    }
  }
  if (bellBtn) {
    bellBtn.classList.toggle('has-unread', unreadCount > 0);
    bellBtn.setAttribute(
      'aria-label',
      unreadCount > 0 ? `Сповіщення системи (${unreadCount} непрочитаних)` : 'Сповіщення системи'
    );
  }

  const items = Array.isArray(data?.items) ? data.items : [];
  if (items.length === 0) {
    listEl.innerHTML = '<div class="notifications-bell-empty">Поки що немає системних сповіщень</div>';
    return;
  }

  listEl.innerHTML = items.map((item) => {
    const rawTitle = String(item.title || 'Сповіщення').trim();
    const leadingEmojiMatch = rawTitle.match(/^([\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]\uFE0F?)\s*/u);
    const icon = _BELL_EVENT_EMOJI[item.event_type] || (leadingEmojiMatch ? leadingEmojiMatch[1] : '🔔');
    const cleanTitle = rawTitle.replace(/^(?:[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]\uFE0F?\s*)+/u, '').trim() || rawTitle;
    const isUnread = item.is_read === false;
    const unreadCls = isUnread ? ' is-unread' : '';
    const dotHtml = isUnread ? '<span class="notifications-bell-unread-dot" aria-label="Непрочитане"></span>' : '';
    const timeStr = typeof formatDateTime === 'function' ? formatDateTime(item.created_at) : String(item.created_at || '');
    return `
      <button type="button" class="notifications-bell-item${unreadCls}" data-event-type="${escapeHtml(item.event_type || '')}">
        <span class="notifications-bell-icon">${icon}</span>
        <div class="notifications-bell-content">
          <div class="notifications-bell-title">
            <span>${escapeHtml(cleanTitle)}</span>
            ${dotHtml}
          </div>
          <div class="notifications-bell-body">${escapeHtml(item.body || '')}</div>
          <div class="notifications-bell-meta">${escapeHtml(timeStr)}</div>
        </div>
      </button>
    `;
  }).join('');
}

window.loadBellFeed = async function(interactive = false) {
  if (!token || !currentUser) return null;
  try {
    const res = await fetch('/api/v1/notifications/feed?limit=25', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    if (!res.ok) {
      if (interactive) showToast('Не вдалося завантажити сповіщення', 'error');
      return null;
    }
    const data = await res.json();
    _renderBellFeed(data);
    return data;
  } catch (_) {
    if (interactive) showToast('Помилка з’єднання зі стрічкою сповіщень', 'error');
    return null;
  }
};

window.closeNotificationsBell = function() {
  const dd = document.getElementById('notificationsDropdown');
  const btn = document.getElementById('headerBellBadge');
  if (dd) dd.style.display = 'none';
  if (btn) btn.setAttribute('aria-expanded', 'false');
};

window.toggleNotificationsBell = function(e) {
  if (e) e.stopPropagation();
  const dd = document.getElementById('notificationsDropdown');
  const btn = document.getElementById('headerBellBadge');
  if (!dd) return;
  const isVisible = dd.style.display === 'block';
  if (isVisible) {
    window.closeNotificationsBell();
  } else {
    if (typeof window.closeAccountMenu === 'function') window.closeAccountMenu();
    if (typeof window.toggleNavDrawer === 'function') window.toggleNavDrawer(false);
    dd.style.display = 'block';
    if (btn) btn.setAttribute('aria-expanded', 'true');
    window.loadBellFeed(false);
  }
};

window.markAllNotificationsRead = async function() {
  if (!token || !currentUser) return;
  try {
    await api('/notifications/read', { method: 'POST' });
    await window.loadBellFeed(false);
  } catch (err) {
    showToast(err?.message || 'Не вдалося позначити прочитаними', 'error');
  }
};

window.openAllNotificationsLog = function() {
  window.closeNotificationsBell();
  if (typeof openTab === 'function') {
    openTab('tab-notifications');
  }
};

document.addEventListener('click', (e) => {
  const wrap = document.getElementById('headerBellWrap');
  const dd = document.getElementById('notificationsDropdown');
  if (dd && dd.style.display === 'block' && wrap && !wrap.contains(e.target)) {
    window.closeNotificationsBell();
  }
  const bellItem = e.target.closest?.('.notifications-bell-item');
  if (bellItem && wrap && wrap.contains(bellItem)) {
    const evType = bellItem.getAttribute('data-event-type') || '';
    const targetTab = _getBellTargetTab(evType);
    window.closeNotificationsBell();
    if (typeof openTab === 'function') {
      openTab(targetTab);
    }
  }
});




