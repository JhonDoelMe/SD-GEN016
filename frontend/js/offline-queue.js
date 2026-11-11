// ==========================================
// 📴 Offline PWA Engine (IndexedDB Queue, Read Cache & Manual Conflict Resolution)
// ==========================================

(function () {
  const DB_NAME = 'sd_gen016_offline_db';
  const DB_VERSION = 1;
  const STORE_CACHE = 'read_cache';
  const STORE_QUEUE = 'mutation_queue';
  const FALLBACK_CACHE_KEY = 'sd_offline_read_cache_v1';
  const FALLBACK_QUEUE_KEY = 'sd_offline_mutation_queue_v1';

  let _dbPromise = null;
  let _isOfflineMode = !navigator.onLine;
  let _lastOfflineCacheTime = null;
  let _isSyncing = false;
  let _editingItemId = null;
  let _serverSnapCache = {};

  function createIdempotencyKey() {
    try {
      if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
      }
    } catch (_) {}
    return 'idem-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  }

  function _openDb() {
    if (_dbPromise) return _dbPromise;
    _dbPromise = new Promise((resolve) => {
      if (typeof indexedDB === 'undefined') {
        resolve(null);
        return;
      }
      try {
        const req = indexedDB.open(DB_NAME, DB_VERSION);
        req.onupgradeneeded = (event) => {
          const db = event.target.result;
          if (!db.objectStoreNames.contains(STORE_CACHE)) {
            db.createObjectStore(STORE_CACHE, { keyPath: 'key' });
          }
          if (!db.objectStoreNames.contains(STORE_QUEUE)) {
            const store = db.createObjectStore(STORE_QUEUE, { keyPath: 'id' });
            store.createIndex('created_at', 'created_at', { unique: false });
          }
        };
        req.onsuccess = (event) => resolve(event.target.result);
        req.onerror = () => resolve(null);
      } catch (_) {
        resolve(null);
      }
    });
    return _dbPromise;
  }

  function _readFallbackMap(storageKey, defaultVal) {
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : defaultVal;
    } catch (_) {
      return defaultVal;
    }
  }

  function _writeFallbackMap(storageKey, val) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(val));
    } catch (_) {}
  }

  async function cachePut(key, data) {
    if (!key) return;
    const rec = { key: String(key), data, updated_at: new Date().toISOString() };
    const db = await _openDb();
    if (!db) {
      const map = _readFallbackMap(FALLBACK_CACHE_KEY, {});
      map[rec.key] = rec;
      _writeFallbackMap(FALLBACK_CACHE_KEY, map);
      return;
    }
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_CACHE, 'readwrite');
        tx.objectStore(STORE_CACHE).put(rec);
        tx.oncomplete = () => resolve(true);
        tx.onerror = () => resolve(false);
      } catch (_) {
        resolve(false);
      }
    });
  }

  async function cacheGet(key) {
    if (!key) return null;
    const strKey = String(key);
    const db = await _openDb();
    if (!db) {
      const map = _readFallbackMap(FALLBACK_CACHE_KEY, {});
      return map[strKey] || null;
    }
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_CACHE, 'readonly');
        const req = tx.objectStore(STORE_CACHE).get(strKey);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => resolve(null);
      } catch (_) {
        resolve(null);
      }
    });
  }

  async function cacheGetAll() {
    const db = await _openDb();
    if (!db) {
      return Object.values(_readFallbackMap(FALLBACK_CACHE_KEY, {}));
    }
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_CACHE, 'readonly');
        const req = tx.objectStore(STORE_CACHE).getAll();
        req.onsuccess = () => resolve(Array.isArray(req.result) ? req.result : []);
        req.onerror = () => resolve([]);
      } catch (_) {
        resolve([]);
      }
    });
  }

  async function queueGetAll() {
    const db = await _openDb();
    if (!db) {
      const arr = _readFallbackMap(FALLBACK_QUEUE_KEY, []);
      return Array.isArray(arr) ? arr.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at))) : [];
    }
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_QUEUE, 'readonly');
        const req = tx.objectStore(STORE_QUEUE).getAll();
        req.onsuccess = () => {
          const rows = Array.isArray(req.result) ? req.result : [];
          rows.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
          resolve(rows);
        };
        req.onerror = () => resolve([]);
      } catch (_) {
        resolve([]);
      }
    });
  }

  async function queuePut(item) {
    const db = await _openDb();
    if (!db) {
      const arr = _readFallbackMap(FALLBACK_QUEUE_KEY, []);
      const idx = arr.findIndex((x) => x.id === item.id);
      if (idx >= 0) arr[idx] = item;
      else arr.push(item);
      _writeFallbackMap(FALLBACK_QUEUE_KEY, arr);
      return item;
    }
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_QUEUE, 'readwrite');
        tx.objectStore(STORE_QUEUE).put(item);
        tx.oncomplete = () => resolve(item);
        tx.onerror = () => resolve(item);
      } catch (_) {
        resolve(item);
      }
    });
  }

  async function queueDelete(id) {
    const db = await _openDb();
    if (!db) {
      const arr = _readFallbackMap(FALLBACK_QUEUE_KEY, []).filter((x) => x.id !== id);
      _writeFallbackMap(FALLBACK_QUEUE_KEY, arr);
      return;
    }
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_QUEUE, 'readwrite');
        tx.objectStore(STORE_QUEUE).delete(id);
        tx.oncomplete = () => resolve(true);
        tx.onerror = () => resolve(false);
      } catch (_) {
        resolve(false);
      }
    });
  }

  const CACHEABLE_PREFIXES = [
    '/auth/me',
    '/facilities',
    '/generator',
    '/fuel/stocks',
    '/fuel/stock',
    '/fuel/canisters',
    '/fuel/summary',
    '/fuel/receipts',
    '/fuel/transfers',
    '/maintenance/schedule',
    '/maintenance/records',
    '/faults',
    '/system/status',
    '/system/fuel-prices',
  ];

  function shouldCacheEndpoint(endpoint) {
    const clean = String(endpoint || '').split('?')[0];
    return CACHEABLE_PREFIXES.some((p) => clean === p || clean.startsWith(p + '/'));
  }

  function isNetworkFailure(err, resStatus = null) {
    if (!navigator.onLine) return true;
    if (resStatus && (resStatus === 502 || resStatus === 503 || resStatus === 504)) return true;
    if (!err) return false;
    const msg = String(err.message || err).toLowerCase();
    return err.name === 'TypeError' || msg.includes('failed to fetch') || msg.includes('networkerror') || msg.includes('load failed');
  }

  function setOfflineMode(isOffline, cacheTimeIso = null) {
    _isOfflineMode = !!isOffline;
    if (cacheTimeIso) _lastOfflineCacheTime = cacheTimeIso;
    updateOfflineUIStatus();
  }

  function _formatShortTime(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' });
    } catch (_) {
      return '';
    }
  }

  function _formatDateTimeSafe(iso) {
    if (!iso) return '-';
    if (typeof window.formatDateTime === 'function') {
      return window.formatDateTime(iso);
    }
    try {
      return new Date(iso).toLocaleString('uk-UA');
    } catch (_) {
      return String(iso);
    }
  }

  function _clone(obj) {
    try {
      return JSON.parse(JSON.stringify(obj));
    } catch (_) {
      return obj;
    }
  }

  async function _updateMatchingCaches(predicate, mutator) {
    const all = await cacheGetAll();
    for (const entry of all) {
      if (!entry || !predicate(entry.key, entry.data)) continue;
      const copy = _clone(entry.data);
      const changed = mutator(entry.key, copy);
      if (changed) {
        await cachePut(entry.key, copy);
      }
    }
  }

  // Keep read cache roughly aligned when operator performs sequential offline actions
  async function applyOptimisticOfflineEffect(item) {
    const type = item.action_type;
    const p = item.payload || {};

    if (type === 'fuel_transfer') {
      const liters = Number(p.liters || 0);
      if (liters <= 0) return;

      await _updateMatchingCaches(
        (k) => k.startsWith('/fuel/stocks'),
        (_k, stocks) => {
          if (!Array.isArray(stocks)) return false;
          const st = stocks.find((s) => Number(s.id) === Number(p.stock_id));
          if (!st) return false;
          st.current_balance_l = Math.max(0, Number(st.current_balance_l || 0) - liters);
          return true;
        }
      );

      await _updateMatchingCaches(
        (k) => k.startsWith('/fuel/canisters') && !k.includes('/transactions'),
        (_k, pools) => {
          if (!Array.isArray(pools)) return false;
          const pool = pools.find((pl) => Number(pl.stock_id) === Number(p.stock_id) && pl.is_active);
          if (!pool) return false;
          const vol = Number(pool.canister_volume_l || 20);
          let res = Number(pool.reserve_liters || 0);
          const fromRes = Math.min(res, liters);
          res -= fromRes;
          let rem = liters - fromRes;
          let opened = 0;
          if (rem > 0 && vol > 0) {
            opened = Math.min(Number(pool.full_count || 0), Math.ceil(rem / vol));
            pool.full_count = Math.max(0, Number(pool.full_count || 0) - opened);
            pool.empty_count = Number(pool.empty_count || 0) + opened;
            res = Math.max(0, res + opened * vol - rem);
          }
          pool.reserve_liters = Number(res.toFixed(3));
          pool.available_liters = Number((pool.full_count * vol + pool.reserve_liters).toFixed(3));
          return true;
        }
      );

      await _updateMatchingCaches(
        (k) => k === `/generator?generator_id=${p.generator_id}` || k.startsWith('/generator/list'),
        (_k, data) => {
          const list = Array.isArray(data) ? data : [data];
          const gen = list.find((g) => g && Number(g.id) === Number(p.generator_id));
          if (!gen) return false;
          const cap = Number(gen.tank_capacity_l || 25);
          gen.fuel_tank_level_l = Math.min(cap, Number(gen.fuel_tank_level_l || 0) + liters);
          return true;
        }
      );

      await _updateMatchingCaches(
        (k) => k.startsWith('/fuel/summary'),
        (_k, sum) => {
          if (!sum || typeof sum !== 'object') return false;
          sum.warehouse_balance_l = Math.max(0, Number(sum.warehouse_balance_l || 0) - liters);
          sum.generator_tank_l = Number(sum.generator_tank_l || 0) + liters;
          return true;
        }
      );
    } else if (type === 'canister_receive' || type === 'canister_dispatch' || type === 'canister_return_empty') {
      const m = String(item.endpoint || '').match(/\/fuel\/canisters\/(\d+)\//);
      const poolId = m ? Number(m[1]) : 0;
      const count = Number(p.count || 0);
      if (!poolId || count <= 0) return;
      let deltaL = 0;
      let stockIdRef = null;

      await _updateMatchingCaches(
        (k) => k.startsWith('/fuel/canisters') && !k.includes('/transactions'),
        (_k, pools) => {
          if (!Array.isArray(pools)) return false;
          const pool = pools.find((pl) => Number(pl.id) === poolId);
          if (!pool) return false;
          stockIdRef = Number(pool.stock_id);
          const vol = Number(pool.canister_volume_l || 20);
          if (type === 'canister_receive') {
            const away = Number(pool.away_refill_count || 0);
            const fromAway = Math.min(count, away);
            const fromEmpty = count - fromAway;
            pool.away_refill_count = Math.max(0, away - fromAway);
            pool.empty_count = Math.max(0, Number(pool.empty_count || 0) - fromEmpty);
            pool.full_count = Number(pool.full_count || 0) + count;
            deltaL = count * vol;
            pool.available_liters = Number((pool.full_count * vol + Number(pool.reserve_liters || 0)).toFixed(3));
          } else if (type === 'canister_dispatch') {
            pool.empty_count = Math.max(0, Number(pool.empty_count || 0) - count);
            pool.away_refill_count = Number(pool.away_refill_count || 0) + count;
          } else if (type === 'canister_return_empty') {
            pool.away_refill_count = Math.max(0, Number(pool.away_refill_count || 0) - count);
            pool.empty_count = Number(pool.empty_count || 0) + count;
          }
          return true;
        }
      );

      if (deltaL !== 0 && stockIdRef) {
        await _updateMatchingCaches(
          (k) => k.startsWith('/fuel/stocks'),
          (_k, stocks) => {
            if (!Array.isArray(stocks)) return false;
            const st = stocks.find((s) => Number(s.id) === stockIdRef);
            if (!st) return false;
            st.current_balance_l = Number(st.current_balance_l || 0) + deltaL;
            return true;
          }
        );
        await _updateMatchingCaches(
          (k) => k.startsWith('/fuel/summary'),
          (_k, sum) => {
            if (!sum || typeof sum !== 'object') return false;
            sum.warehouse_balance_l = Number(sum.warehouse_balance_l || 0) + deltaL;
            return true;
          }
        );
      }
    } else if (type === 'fuel_receipt') {
      const liters = Number(p.liters || 0);
      if (liters <= 0) return;
      await _updateMatchingCaches(
        (k) => k.startsWith('/fuel/stocks'),
        (_k, stocks) => {
          if (!Array.isArray(stocks)) return false;
          const st = stocks.find((s) => Number(s.id) === Number(p.stock_id));
          if (!st) return false;
          st.current_balance_l = Number(st.current_balance_l || 0) + liters;
          return true;
        }
      );
      await _updateMatchingCaches(
        (k) => k.startsWith('/fuel/summary'),
        (_k, sum) => {
          if (!sum || typeof sum !== 'object') return false;
          sum.warehouse_balance_l = Number(sum.warehouse_balance_l || 0) + liters;
          return true;
        }
      );
    } else if (type === 'gen_start' || type === 'gen_stop') {
      const nextStatus = type === 'gen_start' ? 'RUNNING' : 'STOPPED';
      await _updateMatchingCaches(
        (k) => k === `/generator?generator_id=${p.generator_id}` || k.startsWith('/generator/list'),
        (_k, data) => {
          const list = Array.isArray(data) ? data : [data];
          const gen = list.find((g) => g && Number(g.id) === Number(p.generator_id));
          if (!gen) return false;
          gen.status = nextStatus;
          if (type === 'gen_stop' && p.end_hours != null) {
            gen.current_operating_hours = Number(p.end_hours);
          }
          if (type === 'gen_stop' && p.end_fuel_level_l != null) {
            gen.fuel_tank_level_l = Number(p.end_fuel_level_l);
          }
          return true;
        }
      );
    }
  }

  async function enqueueMutation(endpoint, method, payload, offlineMeta = {}, existingKey = null) {
    const idempotencyKey = existingKey || payload?.idempotency_key || createIdempotencyKey();
    const cleanPayload = { ...(payload || {}), idempotency_key: idempotencyKey };
    const nowIso = new Date().toISOString();

    const item = {
      id: createIdempotencyKey(),
      idempotency_key: idempotencyKey,
      action_type: offlineMeta.action_type || 'generic_mutation',
      title: offlineMeta.title || 'Офлайн-операція',
      summary: offlineMeta.summary || `${method} ${endpoint}`,
      endpoint,
      method: (method || 'POST').toUpperCase(),
      payload: cleanPayload,
      facility_id: offlineMeta.facility_id || (typeof currentFacilityId !== 'undefined' ? currentFacilityId : null),
      facility_name: offlineMeta.facility_name || _getFacilityName(offlineMeta.facility_id),
      generator_id: offlineMeta.generator_id || (typeof currentGeneratorId !== 'undefined' ? currentGeneratorId : null),
      status: 'pending',
      error_message: null,
      http_status: null,
      retry_count: 0,
      created_at: nowIso,
      updated_at: nowIso,
    };

    await queuePut(item);
    await applyOptimisticOfflineEffect(item);
    setOfflineMode(!navigator.onLine);
    await updateOfflineUIStatus();
    return item;
  }

  function _getFacilityName(fid) {
    try {
      const sel = document.getElementById('facilitySelect');
      if (!sel) return null;
      const targetId = fid != null ? String(fid) : sel.value;
      const opt = Array.from(sel.options).find((o) => o.value === targetId);
      return opt ? opt.text : null;
    } catch (_) {
      return null;
    }
  }

  async function updateOfflineUIStatus() {
    const rows = await queueGetAll();
    const pendingCount = rows.filter((r) => r.status === 'pending' || r.status === 'syncing').length;
    const conflictCount = rows.filter((r) => r.status === 'conflict').length;
    const isOnline = navigator.onLine && !_isOfflineMode;

    const pill = document.getElementById('headerOfflineSyncBadge');
    const pillIcon = document.getElementById('offlinePillIcon');
    const pillText = document.getElementById('offlinePillText');

    if (pill && pillIcon && pillText) {
      pill.className = 'header-pill pill-offline-sync';
      if (conflictCount > 0) {
        pill.classList.add('pill-sync-conflict');
        pillIcon.innerText = '⚠️';
        pillText.innerText = `Конфлікти (${conflictCount})`;
        pill.title = `Виявлено ${conflictCount} конфлікт(ів) синхронізації. Натисніть для вирішення.`;
      } else if (pendingCount > 0) {
        pill.classList.add('pill-sync-pending');
        pillIcon.innerText = '🔄';
        pillText.innerText = isOnline ? `Черга (${pendingCount})` : `Офлайн (${pendingCount})`;
        pill.title = `В офлайн-черзі: ${pendingCount} операцій. Натисніть для перегляду.`;
      } else if (!isOnline) {
        pill.classList.add('pill-sync-offline');
        pillIcon.innerText = '🟠';
        const tStr = _lastOfflineCacheTime ? ` ${_formatShortTime(_lastOfflineCacheTime)}` : '';
        pillText.innerText = `Офлайн${tStr}`;
        pill.title = 'Відсутнє з\'єднання з сервером. Дані з локального кешу PWA.';
      } else {
        pill.classList.add('pill-sync-online');
        pillIcon.innerText = '🟢';
        pillText.innerText = 'Онлайн';
        pill.title = 'З\'єднання активне. Натисніть, щоб відкрити статус черги PWA.';
      }
    }

    const banner = document.getElementById('offlineSyncBanner');
    const bannerMsg = document.getElementById('offlineSyncBannerText');
    const bannerBtnSync = document.getElementById('btnOfflineBannerSync');
    if (banner && bannerMsg) {
      if (conflictCount === 0 && pendingCount === 0 && isOnline) {
        banner.style.display = 'none';
      } else {
        banner.style.display = 'flex';
        banner.className = 'offline-sync-banner ' + (conflictCount > 0 ? 'banner-conflict' : (!isOnline ? 'banner-offline' : 'banner-pending'));
        const parts = [];
        if (!isOnline) parts.push('🟠 <b>Офлайн-режим:</b> нові операції зберігаються локально в IndexedDB.');
        if (pendingCount > 0) parts.push(`⏳ Очікують відправки: <b>${pendingCount}</b>.`);
        if (conflictCount > 0) parts.push(`⚠️ Потребують вирішення вручну: <b>${conflictCount}</b>.`);
        bannerMsg.innerHTML = parts.join(' ');
        if (bannerBtnSync) {
          bannerBtnSync.style.display = (isOnline && pendingCount > 0) ? 'inline-flex' : 'none';
        }
      }
    }
  }

  async function _sendSingleQueueItem(item) {
    const authToken = (typeof token !== 'undefined' && token) || localStorage.getItem('sd_token') || sessionStorage.getItem('sd_token');
    if (!authToken) {
      return { outcome: 'auth_required', message: 'Необхідно увійти в систему для синхронізації.' };
    }

    const headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${authToken}`,
      'Idempotency-Key': item.idempotency_key,
    };

    try {
      const res = await fetch(`/api/v1${item.endpoint}`, {
        method: item.method || 'POST',
        headers,
        body: JSON.stringify({ ...(item.payload || {}), idempotency_key: item.idempotency_key }),
      });

      if (res.status === 502 || res.status === 503 || res.status === 504) {
        return { outcome: 'network_error', status: res.status };
      }

      const data = await res.json().catch(() => null);

      if (res.status === 401) {
        return { outcome: 'auth_required', message: 'Сесія закінчилась. Увійдіть знову для продовження синхронізації.' };
      }

      if (res.ok) {
        return { outcome: 'synced', data };
      }

      const errMsg = typeof extractErrorMessage === 'function'
        ? extractErrorMessage(data, `Помилка сервера (${res.status})`)
        : (data?.detail || `Помилка сервера (${res.status})`);
      return { outcome: 'conflict', status: res.status, message: String(errMsg) };
    } catch (err) {
      if (isNetworkFailure(err)) {
        return { outcome: 'network_error' };
      }
      return { outcome: 'conflict', status: 0, message: String(err?.message || 'Помилка мережі') };
    }
  }

  async function syncOfflineQueue({ silent = false } = {}) {
    if (_isSyncing) return { synced: 0, conflicts: 0, deferred: 0 };
    if (!navigator.onLine) {
      if (!silent && typeof showToast === 'function') {
        showToast('Немає з\'єднання з інтернетом — синхронізацію відкладено.', 'warning');
      }
      await updateOfflineUIStatus();
      return { synced: 0, conflicts: 0, deferred: 1 };
    }

    _isSyncing = true;
    let syncedCount = 0;
    let conflictCount = 0;
    let deferredCount = 0;

    try {
      const rows = await queueGetAll();
      const pending = rows.filter((r) => r.status === 'pending');
      if (pending.length === 0) {
        setOfflineMode(false);
        return { synced: 0, conflicts: rows.filter((r) => r.status === 'conflict').length, deferred: 0 };
      }

      for (const item of pending) {
        item.status = 'syncing';
        await queuePut(item);

        const result = await _sendSingleQueueItem(item);
        if (result.outcome === 'network_error') {
          item.status = 'pending';
          item.updated_at = new Date().toISOString();
          await queuePut(item);
          setOfflineMode(true);
          deferredCount += 1;
          break;
        }
        if (result.outcome === 'auth_required') {
          item.status = 'pending';
          item.updated_at = new Date().toISOString();
          await queuePut(item);
          if (!silent && typeof showToast === 'function') {
            showToast(result.message, 'warning');
          }
          if (typeof showAuthScreen === 'function') showAuthScreen();
          deferredCount += 1;
          break;
        }
        if (result.outcome === 'synced') {
          await queueDelete(item.id);
          syncedCount += 1;
          setOfflineMode(false);
        } else {
          item.status = 'conflict';
          item.http_status = result.status || 400;
          item.error_message = result.message || 'Сервер відхилив операцію.';
          item.retry_count = Number(item.retry_count || 0) + 1;
          item.updated_at = new Date().toISOString();
          await queuePut(item);
          conflictCount += 1;
        }
      }
    } finally {
      _isSyncing = false;
      await updateOfflineUIStatus();
      await renderQueueModal();
    }

    if (syncedCount > 0) {
      if (typeof showToast === 'function') {
        showToast(`✅ Синхронізовано офлайн-операцій: ${syncedCount}` + (conflictCount > 0 ? ` (конфліктів: ${conflictCount})` : ''), conflictCount > 0 ? 'warning' : 'success');
      }
      if (typeof loadAllData === 'function') {
        loadAllData().catch(() => {});
      }
      if (typeof loadFuelData === 'function' && document.getElementById('tab-fuel')?.style.display !== 'none') {
        loadFuelData().catch(() => {});
      }
    } else if (conflictCount > 0 && typeof showToast === 'function') {
      showToast(`⚠️ Виявлено ${conflictCount} конфлікт(ів) синхронізації — відкрийте чергу для ручного рішення`, 'warning');
    }

    return { synced: syncedCount, conflicts: conflictCount, deferred: deferredCount };
  }

  async function _fetchServerContextForFacility(facilityId, generatorId) {
    const cacheKey = `${facilityId || '0'}:${generatorId || '0'}`;
    if (!navigator.onLine) return _serverSnapCache[cacheKey] || null;
    try {
      const qFac = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
      const qGen = generatorId ? `?generator_id=${encodeURIComponent(generatorId)}` : '';
      const [gen, stocks, pools] = await Promise.all([
        generatorId ? api(`/generator${qGen}`, { suppressToast: true }).catch(() => null) : Promise.resolve(null),
        api(`/fuel/stocks${qFac}`, { suppressToast: true }).catch(() => []),
        api(`/fuel/canisters${qFac}`, { suppressToast: true }).catch(() => []),
      ]);
      const snap = { gen, stocks: Array.isArray(stocks) ? stocks : [], pools: Array.isArray(pools) ? pools : [] };
      _serverSnapCache[cacheKey] = snap;
      return snap;
    } catch (_) {
      return null;
    }
  }

  function _formatServerSnapshotHtml(snap) {
    if (!snap) return '';
    const parts = [];
    if (snap.gen) {
      const statusUa = snap.gen.status === 'RUNNING' ? 'Працює' : (snap.gen.status === 'FAULTY' ? 'Несправний' : 'Зупинено');
      parts.push(`⚡ <b>${escapeHtml(snap.gen.name)}</b>: ${statusUa}, бак <b>${Number(snap.gen.fuel_tank_level_l || 0).toFixed(1)}/${Number(snap.gen.tank_capacity_l || 25).toFixed(1)} л</b>, лічильник <b>${Number(snap.gen.current_operating_hours || 0).toFixed(1)} год</b>`);
    }
    if (snap.pools && snap.pools.length > 0) {
      for (const pl of snap.pools) {
        parts.push(`🛢️ <b>${escapeHtml(pl.name)}</b>: повних <b>${Number(pl.full_count)}</b>, порожніх <b>${Number(pl.empty_count)}</b>, на АЗС <b>${Number(pl.away_refill_count)}</b>, резерв <b>${Number(pl.reserve_liters || 0).toFixed(1)} л</b>`);
      }
    } else if (snap.stocks && snap.stocks.length > 0) {
      for (const st of snap.stocks) {
        parts.push(`📦 <b>${escapeHtml(st.name)}</b>: <b>${Number(st.current_balance_l || 0).toFixed(1)} л</b>`);
      }
    }
    if (parts.length === 0) return '';
    return `<div class="offline-server-snap"><div class="snap-title">Актуальний стан на сервері зараз:</div>${parts.map((line) => `<div>${line}</div>`).join('')}</div>`;
  }

  function _buildEditFormHtml(item) {
    const p = item.payload || {};
    const t = item.action_type;
    const esc = (v) => escapeHtml(v == null ? '' : String(v));
    let fieldsHtml = '';

    if (t === 'fuel_transfer') {
      fieldsHtml = `
        <div class="form-row-2">
          <div class="form-group"><label>Кількість літрів (л)</label><input type="number" step="0.1" min="0.1" id="oqEditLiters_${esc(item.id)}" value="${esc(p.liters)}"></div>
          <div class="form-group"><label>Коментар</label><input type="text" id="oqEditComment_${esc(item.id)}" value="${esc(p.comment || '')}"></div>
        </div>`;
    } else if (t === 'canister_receive') {
      fieldsHtml = `
        <div class="form-row-3">
          <div class="form-group"><label>Каністр (шт)</label><input type="number" step="1" min="1" id="oqEditCount_${esc(item.id)}" value="${esc(p.count)}"></div>
          <div class="form-group"><label>Сума чека (грн)</label><input type="number" step="0.01" min="0" id="oqEditCost_${esc(item.id)}" value="${esc(p.cost_total ?? '')}" placeholder="Авто"></div>
          <div class="form-group"><label>Номер чека</label><input type="text" id="oqEditNumber_${esc(item.id)}" value="${esc(p.receipt_number || '')}"></div>
        </div>
        <div class="form-row-2">
          <div class="form-group"><label>Хто доставив</label><input type="text" id="oqEditDriver_${esc(item.id)}" value="${esc(p.driver_name || '')}"></div>
          <div class="form-group"><label>Коментар</label><input type="text" id="oqEditComment_${esc(item.id)}" value="${esc(p.comment || '')}"></div>
        </div>
        <label class="checkbox-row"><input type="checkbox" id="oqEditForce_${esc(item.id)}" ${p.force_confirm ? 'checked' : ''}><span>Підтвердити нетиповий об'єм / ціну (force_confirm)</span></label>`;
    } else if (t === 'fuel_receipt') {
      fieldsHtml = `
        <div class="form-row-3">
          <div class="form-group"><label>Літри (л)</label><input type="number" step="0.1" min="0.1" id="oqEditLiters_${esc(item.id)}" value="${esc(p.liters)}"></div>
          <div class="form-group"><label>Сума чека (грн)</label><input type="number" step="0.01" min="0" id="oqEditCost_${esc(item.id)}" value="${esc(p.cost_total ?? '')}" placeholder="Авто"></div>
          <div class="form-group"><label>Номер чека</label><input type="text" id="oqEditNumber_${esc(item.id)}" value="${esc(p.receipt_number || '')}"></div>
        </div>
        <div class="form-row-2">
          <div class="form-group"><label>Хто доставив</label><input type="text" id="oqEditDriver_${esc(item.id)}" value="${esc(p.driver_name || '')}"></div>
          <div class="form-group"><label>Коментар</label><input type="text" id="oqEditComment_${esc(item.id)}" value="${esc(p.comment || '')}"></div>
        </div>
        <label class="checkbox-row"><input type="checkbox" id="oqEditForce_${esc(item.id)}" ${p.force_confirm ? 'checked' : ''}><span>Підтвердити нетиповий об'єм / ціну (force_confirm)</span></label>`;
    } else if (t === 'canister_dispatch' || t === 'canister_return_empty') {
      fieldsHtml = `
        <div class="form-row-2">
          <div class="form-group"><label>Кількість каністр (шт)</label><input type="number" step="1" min="1" id="oqEditCount_${esc(item.id)}" value="${esc(p.count)}"></div>
          <div class="form-group"><label>Коментар</label><input type="text" id="oqEditComment_${esc(item.id)}" value="${esc(p.comment || '')}"></div>
        </div>`;
    } else if (t === 'gen_start') {
      fieldsHtml = `
        <div class="form-row-2">
          <div class="form-group"><label>Рівень палива в баку (л)</label><input type="number" step="0.1" min="0" id="oqEditFuel_${esc(item.id)}" value="${esc(p.fuel_level_l ?? '')}"></div>
          <div class="form-group"><label>Причина примусового запуску</label><input type="text" id="oqEditForceReason_${esc(item.id)}" value="${esc(p.force_start_reason || '')}"></div>
        </div>
        <label class="checkbox-row"><input type="checkbox" id="oqEditForceMaint_${esc(item.id)}" ${p.force_start_with_maintenance ? 'checked' : ''}><span>Дозволити запуск при простроченому ТО</span></label>`;
    } else if (t === 'gen_stop') {
      fieldsHtml = `
        <div class="form-row-3">
          <div class="form-group"><label>Мотогодини зупинки</label><input type="number" step="0.1" min="0" id="oqEditEndHours_${esc(item.id)}" value="${esc(p.end_hours ?? '')}"></div>
          <div class="form-group"><label>Паливо в баку (л)</label><input type="number" step="0.1" min="0" id="oqEditEndFuel_${esc(item.id)}" value="${esc(p.end_fuel_level_l ?? '')}"></div>
          <div class="form-group"><label>Примітка</label><input type="text" id="oqEditNote_${esc(item.id)}" value="${esc(p.note || '')}"></div>
        </div>
        <label class="checkbox-row"><input type="checkbox" id="oqEditForce_${esc(item.id)}" ${p.force_confirm ? 'checked' : ''}><span>Підтвердити розбіжність мотогодин (force_confirm)</span></label>`;
    } else if (t === 'gen_manual_run') {
      fieldsHtml = `
        <div class="form-row-3">
          <div class="form-group"><label>Початкові мотогодини</label><input type="number" step="0.1" min="0" id="oqEditStartH_${esc(item.id)}" value="${esc(p.start_hours ?? '')}"></div>
          <div class="form-group"><label>Кінцеві мотогодини</label><input type="number" step="0.1" min="0" id="oqEditEndH_${esc(item.id)}" value="${esc(p.end_hours ?? '')}"></div>
          <div class="form-group"><label>Витрачене паливо (л)</label><input type="number" step="0.1" min="0" id="oqEditFuelUsed_${esc(item.id)}" value="${esc(p.fuel_consumed_l ?? '')}"></div>
        </div>
        <div class="form-group"><label>Примітка</label><input type="text" id="oqEditNote_${esc(item.id)}" value="${esc(p.note || '')}"></div>
        <label class="checkbox-row"><input type="checkbox" id="oqEditForce_${esc(item.id)}" ${p.force_confirm ? 'checked' : ''}><span>Підтвердити розбіжність мотогодин (force_confirm)</span></label>`;
    } else if (t === 'maint_record') {
      fieldsHtml = `
        <div class="form-row-2">
          <div class="form-group"><label>Мотогодини</label><input type="number" step="0.1" min="0" id="oqEditOpH_${esc(item.id)}" value="${esc(p.operating_hours ?? '')}"></div>
          <div class="form-group"><label>Вартість (грн)</label><input type="number" step="0.01" min="0" id="oqEditCost_${esc(item.id)}" value="${esc(p.cost ?? 0)}"></div>
        </div>
        <div class="form-group"><label>Виконані роботи</label><input type="text" id="oqEditWork_${esc(item.id)}" value="${esc(p.work_description || '')}"></div>`;
    } else if (t === 'fault_create') {
      fieldsHtml = `
        <div class="form-row-2">
          <div class="form-group"><label>Заголовок</label><input type="text" id="oqEditTitle_${esc(item.id)}" value="${esc(p.title || '')}"></div>
          <div class="form-group"><label>Пріоритет</label>
            <select id="oqEditPrio_${esc(item.id)}">
              <option value="LOW" ${p.priority === 'LOW' ? 'selected' : ''}>Низький</option>
              <option value="MEDIUM" ${p.priority === 'MEDIUM' ? 'selected' : ''}>Середній</option>
              <option value="HIGH" ${p.priority === 'HIGH' ? 'selected' : ''}>Високий</option>
              <option value="CRITICAL" ${p.priority === 'CRITICAL' ? 'selected' : ''}>Критичний</option>
            </select>
          </div>
        </div>
        <div class="form-group"><label>Опис несправності</label><input type="text" id="oqEditDesc_${esc(item.id)}" value="${esc(p.description || '')}"></div>`;
    }

    return `
      <div class="offline-edit-box">
        ${fieldsHtml}
        <div style="display:flex; gap:0.5rem; margin-top:0.65rem; flex-wrap:wrap;">
          <button type="button" class="btn-oq-chip btn-oq-chip-primary" onclick="OfflineQueue.saveAndRetry('${esc(item.id)}')">✓ Зберегти й надіслати</button>
          <button type="button" class="btn-oq-chip" onclick="OfflineQueue.toggleEdit('${esc(item.id)}')">Скасувати</button>
        </div>
      </div>`;
  }

  function _readEditedPayload(item) {
    const id = item.id;
    const p = _clone(item.payload || {});
    const t = item.action_type;
    const val = (elId) => document.getElementById(elId)?.value;
    const num = (elId, allowNull = false) => {
      const raw = val(elId);
      if (raw === undefined || raw === null || String(raw).trim() === '') return allowNull ? null : 0;
      const parsed = parseFloat(raw);
      return Number.isNaN(parsed) ? (allowNull ? null : 0) : parsed;
    };
    const intVal = (elId) => parseInt(val(elId) || '0', 10) || 0;
    const chk = (elId) => !!document.getElementById(elId)?.checked;

    let newSummary = item.summary;

    if (t === 'fuel_transfer') {
      p.liters = num(`oqEditLiters_${id}`);
      p.comment = (val(`oqEditComment_${id}`) || '').trim() || null;
      newSummary = `Заправка бака +${Number(p.liters).toFixed(1)} л`;
    } else if (t === 'canister_receive') {
      p.count = intVal(`oqEditCount_${id}`);
      const c = num(`oqEditCost_${id}`, true);
      p.cost_total = (c !== null && c > 0) ? c : null;
      p.receipt_number = (val(`oqEditNumber_${id}`) || '').trim();
      p.driver_name = (val(`oqEditDriver_${id}`) || '').trim();
      p.comment = (val(`oqEditComment_${id}`) || '').trim() || null;
      p.force_confirm = chk(`oqEditForce_${id}`);
      newSummary = `Прийом ${p.count} каністр (${p.receipt_number || 'без чека'})`;
    } else if (t === 'fuel_receipt') {
      p.liters = num(`oqEditLiters_${id}`);
      const c = num(`oqEditCost_${id}`, true);
      p.cost_total = (c !== null && c > 0) ? c : null;
      p.receipt_number = (val(`oqEditNumber_${id}`) || '').trim();
      p.driver_name = (val(`oqEditDriver_${id}`) || '').trim();
      p.comment = (val(`oqEditComment_${id}`) || '').trim() || null;
      p.force_confirm = chk(`oqEditForce_${id}`);
      newSummary = `Оприбуткування +${Number(p.liters).toFixed(1)} л`;
    } else if (t === 'canister_dispatch' || t === 'canister_return_empty') {
      p.count = intVal(`oqEditCount_${id}`);
      p.comment = (val(`oqEditComment_${id}`) || '').trim() || null;
      newSummary = t === 'canister_dispatch' ? `Відправка на АЗС: ${p.count} шт.` : `Повернення порожніми: ${p.count} шт.`;
    } else if (t === 'gen_start') {
      p.fuel_level_l = num(`oqEditFuel_${id}`, true);
      p.force_start_with_maintenance = chk(`oqEditForceMaint_${id}`);
      p.force_start_reason = (val(`oqEditForceReason_${id}`) || '').trim() || null;
    } else if (t === 'gen_stop') {
      p.end_hours = num(`oqEditEndHours_${id}`, true);
      p.end_fuel_level_l = num(`oqEditEndFuel_${id}`, true);
      p.note = (val(`oqEditNote_${id}`) || '').trim() || null;
      p.force_confirm = chk(`oqEditForce_${id}`);
    } else if (t === 'gen_manual_run') {
      p.start_hours = num(`oqEditStartH_${id}`, true);
      p.end_hours = num(`oqEditEndH_${id}`, true);
      p.fuel_consumed_l = num(`oqEditFuelUsed_${id}`, true);
      p.note = (val(`oqEditNote_${id}`) || '').trim() || null;
      p.force_confirm = chk(`oqEditForce_${id}`);
    } else if (t === 'maint_record') {
      p.operating_hours = num(`oqEditOpH_${id}`, true);
      p.cost = num(`oqEditCost_${id}`, false);
      p.work_description = (val(`oqEditWork_${id}`) || '').trim();
    } else if (t === 'fault_create') {
      p.title = (val(`oqEditTitle_${id}`) || '').trim();
      p.priority = val(`oqEditPrio_${id}`) || p.priority;
      p.description = (val(`oqEditDesc_${id}`) || '').trim();
    }
    return { payload: p, summary: newSummary };
  }

  async function renderQueueModal() {
    const modal = document.getElementById('modalOfflineQueue');
    if (!modal || modal.style.display === 'none') return;

    const listEl = document.getElementById('offlineQueueList');
    const summaryEl = document.getElementById('offlineModalSummary');
    const btnSyncAll = document.getElementById('btnOfflineModalSyncAll');
    if (!listEl) return;

    const rows = await queueGetAll();
    const pendingCnt = rows.filter((r) => r.status === 'pending' || r.status === 'syncing').length;
    const conflictCnt = rows.filter((r) => r.status === 'conflict').length;
    const isOnline = navigator.onLine && !_isOfflineMode;

    if (summaryEl) {
      summaryEl.innerHTML = `
        <div class="oq-stat-tile">
          <span class="oq-stat-label">Зв'язок</span>
          <span class="oq-stat-val" style="color:${isOnline ? '#4ade80' : '#fb923c'};">${isOnline ? '● Онлайн' : '● Офлайн'}</span>
        </div>
        <div class="oq-stat-tile">
          <span class="oq-stat-label">Очікують</span>
          <span class="oq-stat-val" style="color:${pendingCnt > 0 ? '#fbbf24' : 'var(--text-primary)'};">${pendingCnt}</span>
        </div>
        <div class="oq-stat-tile">
          <span class="oq-stat-label">Конфліктів</span>
          <span class="oq-stat-val" style="color:${conflictCnt > 0 ? '#f87171' : 'var(--text-primary)'};">${conflictCnt}</span>
        </div>
      `;
    }
    if (btnSyncAll) {
      btnSyncAll.disabled = !isOnline || pendingCnt === 0 || _isSyncing;
    }

    if (rows.length === 0) {
      listEl.innerHTML = `
        <div class="offline-empty-state">
          <div class="offline-empty-icon">✓</div>
          <div class="offline-empty-title">Черга синхронізації порожня</div>
          <div class="offline-empty-sub">Усі дії успішно передані на сервер.</div>
        </div>`;
      return;
    }

    // Fetch live server snapshots for any conflicted facilities when online
    const snapMap = {};
    if (navigator.onLine) {
      const seenKeys = new Set();
      for (const r of rows) {
        if (r.status !== 'conflict') continue;
        const k = `${r.facility_id || '0'}:${r.generator_id || '0'}`;
        if (!seenKeys.has(k)) {
          seenKeys.add(k);
          snapMap[k] = await _fetchServerContextForFacility(r.facility_id, r.generator_id);
        }
      }
    }

    listEl.innerHTML = rows.map((item) => {
      const isConflict = item.status === 'conflict';
      const statusBadge = isConflict
        ? `<span class="badge badge-faulty">⚠️ КОНФЛІКТ</span>`
        : `<span class="badge badge-maintenance">⏳ ОЧІКУЄ</span>`;
      const snapKey = `${item.facility_id || '0'}:${item.generator_id || '0'}`;
      const snapHtml = isConflict ? _formatServerSnapshotHtml(snapMap[snapKey]) : '';
      const errHtml = isConflict && item.error_message
        ? `<div class="offline-error-box">❗ <b>Відхилено сервером${item.http_status ? ` (HTTP ${Number(item.http_status)})` : ''}:</b> ${escapeHtml(item.error_message)}</div>`
        : '';
      const isEditing = _editingItemId === item.id;

      return `
        <div class="offline-queue-card ${isConflict ? 'card-conflict' : 'card-pending'}">
          <div class="oq-card-top">
            <div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
              ${statusBadge}
              <b>${escapeHtml(item.title)}</b>
              ${item.facility_name ? `<span class="oq-fac-chip">🏢 ${escapeHtml(item.facility_name)}</span>` : ''}
            </div>
            <span class="oq-time">${escapeHtml(_formatDateTimeSafe(item.created_at))}</span>
          </div>
          <div class="oq-summary">${escapeHtml(item.summary)}</div>
          ${errHtml}
          ${snapHtml}
          ${isEditing ? _buildEditFormHtml(item) : ''}
          ${!isEditing ? `
            <div class="oq-actions">
              <button type="button" class="btn-oq-chip btn-oq-chip-info" ${!navigator.onLine ? 'disabled' : ''} onclick="OfflineQueue.retryItem('${escapeHtml(item.id)}')">🔄 ${isConflict ? 'Повторити як є' : 'Надіслати'}</button>
              <button type="button" class="btn-oq-chip" onclick="OfflineQueue.toggleEdit('${escapeHtml(item.id)}')">✏️ Змінити</button>
              <button type="button" class="btn-oq-chip btn-oq-chip-danger" onclick="OfflineQueue.removeItem('${escapeHtml(item.id)}')">🗑️ Видалити</button>
            </div>
          ` : ''}
        </div>
      `;
    }).join('');
  }

  async function retryItem(id) {
    const rows = await queueGetAll();
    const item = rows.find((r) => r.id === id);
    if (!item) return;
    if (!navigator.onLine) {
      if (typeof showToast === 'function') showToast('Немає з\'єднання з сервером.', 'warning');
      return;
    }

    const result = await _sendSingleQueueItem(item);
    if (result.outcome === 'synced') {
      await queueDelete(item.id);
      if (_editingItemId === item.id) _editingItemId = null;
      setOfflineMode(false);
      await updateOfflineUIStatus();
      await renderQueueModal();
      if (typeof showToast === 'function') showToast(`✅ Операцію «${item.title}» синхронізовано!`, 'success');
      if (typeof loadAllData === 'function') loadAllData().catch(() => {});
      if (typeof loadFuelData === 'function' && document.getElementById('tab-fuel')?.style.display !== 'none') loadFuelData().catch(() => {});
    } else if (result.outcome === 'conflict') {
      item.status = 'conflict';
      item.http_status = result.status || 400;
      item.error_message = result.message;
      item.retry_count = Number(item.retry_count || 0) + 1;
      item.updated_at = new Date().toISOString();
      await queuePut(item);
      await updateOfflineUIStatus();
      await renderQueueModal();
      if (typeof showToast === 'function') showToast(`⚠️ Конфлікт: ${result.message}`, 'error');
    } else if (result.outcome === 'network_error') {
      setOfflineMode(true);
      await updateOfflineUIStatus();
      if (typeof showToast === 'function') showToast('Сервер недоступний. Спробуйте ще раз пізніше.', 'warning');
    } else if (result.outcome === 'auth_required') {
      if (typeof showToast === 'function') showToast(result.message, 'warning');
      if (typeof showAuthScreen === 'function') showAuthScreen();
    }
  }

  function toggleEdit(id) {
    _editingItemId = (_editingItemId === id) ? null : id;
    renderQueueModal();
  }

  async function saveAndRetry(id) {
    const rows = await queueGetAll();
    const item = rows.find((r) => r.id === id);
    if (!item) return;

    const oldCanon = JSON.stringify(item.payload || {});
    const { payload: newPayload, summary: newSummary } = _readEditedPayload(item);
    const newCanon = JSON.stringify(newPayload || {});

    // Edited parameters represent a modified intent -> generate fresh idempotency_key
    if (oldCanon !== newCanon) {
      const freshKey = createIdempotencyKey();
      newPayload.idempotency_key = freshKey;
      item.idempotency_key = freshKey;
    }
    item.payload = newPayload;
    item.summary = newSummary;
    item.status = 'pending';
    item.error_message = null;
    item.http_status = null;
    item.updated_at = new Date().toISOString();

    await queuePut(item);
    _editingItemId = null;
    await updateOfflineUIStatus();
    if (navigator.onLine) {
      await retryItem(id);
    } else {
      await renderQueueModal();
      if (typeof showToast === 'function') showToast('Зміни збережено у черзі (офлайн).', 'info');
    }
  }

  async function removeItem(id) {
    const rows = await queueGetAll();
    const item = rows.find((r) => r.id === id);
    if (!item) return;
    if (!confirm(`Видалити з черги «${item.title}» (${item.summary})?`)) return;
    await queueDelete(id);
    if (_editingItemId === id) _editingItemId = null;
    await updateOfflineUIStatus();
    await renderQueueModal();
    if (typeof showToast === 'function') showToast('Операцію видалено з локальної черги.', 'info');
  }

  function init() {
    window.addEventListener('online', () => {
      setOfflineMode(false);
      setTimeout(() => {
        syncOfflineQueue({ silent: false }).catch(() => {});
      }, 800);
    });
    window.addEventListener('offline', () => {
      setOfflineMode(true);
    });
    updateOfflineUIStatus();
  }

  window.openOfflineQueueModal = function () {
    _editingItemId = null;
    if (typeof openModal === 'function') {
      openModal('modalOfflineQueue');
    }
    renderQueueModal();
  };

  window.OfflineQueue = {
    init,
    createIdempotencyKey,
    shouldCacheEndpoint,
    isNetworkFailure,
    cachePut,
    cacheGet,
    enqueueMutation,
    queueGetAll,
    syncOfflineQueue,
    renderQueueModal,
    retryItem,
    toggleEdit,
    saveAndRetry,
    removeItem,
    setOfflineMode,
    updateOfflineUIStatus,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
