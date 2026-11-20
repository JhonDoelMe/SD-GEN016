// frontend/js/ota-updater.js
// Dual-channel OTA updater for Capacitor Android:
// 1) Web-Bundle OTA (ZIP + SHA-256 via setServerBasePath, zero APK permissions)
// 2) External browser redirect when a native APK update is required

(function () {
  const CHECK_INTERVAL_MS = 10 * 60 * 1000;
  const DISMISSED_KEY = 'sdgen_ota_dismissed_tag';
  const LAST_CHECK_KEY = 'sdgen_ota_last_check_ts';

  let currentAppInfo = null;
  let latestManifest = null;
  let currentUpdateMode = null; // 'web' | 'native'
  let isDownloading = false;
  let listenerBound = false;

  function getOtaPlugin() {
    if (
      window.Capacitor &&
      typeof window.Capacitor.isNativePlatform === 'function' &&
      window.Capacitor.isNativePlatform() &&
      window.Capacitor.Plugins &&
      window.Capacitor.Plugins.OtaUpdater
    ) {
      return window.Capacitor.Plugins.OtaUpdater;
    }
    return null;
  }

  function resolveOtaBaseUrl() {
    if (typeof window.getApiBaseUrl === 'function') {
      const apiBase = window.getApiBaseUrl();
      if (apiBase) {
        return apiBase.replace(/\/+$/, '') + '/ota';
      }
    }
    if (typeof window.getDefaultNativeServerUrl === 'function') {
      return window.getDefaultNativeServerUrl().replace(/\/+$/, '') + '/ota';
    }
    return 'https://sdgen.pp.ua/ota';
  }

  function formatSize(bytes) {
    const n = Number(bytes || 0);
    if (!Number.isFinite(n) || n <= 0) return '—';
    if (n < 1024 * 1024) {
      return `${Math.max(1, Math.round(n / 1024))} КБ`;
    }
    return `${(n / (1024 * 1024)).toFixed(2)} МБ`;
  }

  function escapeText(value) {
    if (typeof window.escapeHtml === 'function') {
      return window.escapeHtml(value);
    }
    return String(value ?? '').replace(/[&<>"']/g, (ch) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
    ));
  }

  function bindProgressListener(plugin) {
    if (listenerBound || typeof plugin.addListener !== 'function') return;
    listenerBound = true;
    plugin.addListener('otaDownloadProgress', (ev) => {
      const bar = document.getElementById('otaProgressBar');
      const txt = document.getElementById('otaProgressText');
      if (!bar || !txt) return;
      const pct = Number(ev?.percent ?? -1);
      const dl = Number(ev?.downloadedBytes ?? 0);
      const total = Number(ev?.totalBytes ?? 0);
      if (pct >= 0) {
        bar.style.width = `${Math.min(100, pct)}%`;
        txt.textContent = total > 0
          ? `Завантаження... ${pct}% (${formatSize(dl)} / ${formatSize(total)})`
          : `Завантаження... ${pct}%`;
      } else {
        bar.style.width = '50%';
        txt.textContent = `Завантаження... ${formatSize(dl)}`;
      }
    });
  }

  async function renderServerModalAppVersion(info) {
    const plugin = getOtaPlugin();
    if (!info && !currentAppInfo && plugin) {
      try {
        currentAppInfo = await plugin.getAppInfo();
      } catch (_) {}
    }
    const resolved = info || currentAppInfo;
    if (!resolved) return;
    const box = document.getElementById('nativeAppVersionRow');
    const label = document.getElementById('nativeAppVersionLabel');
    if (!box || !label) return;
    box.style.display = 'flex';
    const nativeCode = Number(resolved.nativeVersionCode ?? resolved.versionCode ?? 0);
    const webBuild = Number(resolved.webBuild ?? nativeCode);
    if (resolved.isWebOtaActive && webBuild > nativeCode) {
      label.textContent = `Android додаток: v${resolved.versionName || '—'} (Web #${webBuild} · APK #${nativeCode})`;
    } else {
      label.textContent = `Android додаток: v${resolved.versionName || '—'} (build ${nativeCode})`;
    }
  }

  function setStatusMessage(text, isError) {
    const el = document.getElementById('otaStatusMessage');
    if (!el) return;
    if (!text) {
      el.style.display = 'none';
      el.textContent = '';
      return;
    }
    el.style.display = 'block';
    el.style.background = isError ? 'rgba(239, 68, 68, 0.14)' : 'rgba(59, 130, 246, 0.14)';
    el.style.color = isError ? '#fca5a5' : '#93c5fd';
    el.textContent = text;
  }

  function buildDismissTag(mode, manifest) {
    if (mode === 'web') {
      return `web:${Number(manifest?.web_build || 0)}`;
    }
    return `native:${Number(manifest?.native?.version_code || 0)}`;
  }

  async function showUpdateModal(info, manifest, mode) {
    if (window.ViewLoader?.ensureModal) {
      try {
        await window.ViewLoader.ensureModal('modalAppUpdate');
      } catch (_) {}
    }
    const modal = document.getElementById('modalAppUpdate');
    if (!modal) return;

    currentUpdateMode = mode;
    const isNative = mode === 'native';
    const nativeInfo = manifest.native || {};

    const mandatory = isNative
      ? Boolean(manifest.native_update_required || nativeInfo.force_update || nativeInfo.is_mandatory)
      : Boolean(manifest.web_force_update || manifest.is_mandatory);

    modal.dataset.mandatory = mandatory ? 'true' : 'false';

    const titleEl = document.getElementById('otaModalTitle');
    const summaryEl = document.getElementById('otaVersionSummary');
    const changelogEl = document.getElementById('otaChangelogBox');
    const closeBtn = document.getElementById('otaCloseBtn');
    const laterBtn = document.getElementById('otaLaterBtn');
    const installBtn = document.getElementById('otaInstallBtn');
    const progWrap = document.getElementById('otaProgressWrap');
    const progBar = document.getElementById('otaProgressBar');

    const targetVerName = isNative ? nativeInfo.version_name : manifest.version_name;
    if (titleEl) {
      if (isNative) {
        titleEl.textContent = mandatory
          ? `Потрібне оновлення додатка v${targetVerName}`
          : `Доступне оновлення APK v${targetVerName}`;
      } else {
        titleEl.textContent = mandatory
          ? `Обов'язкове оновлення v${targetVerName}`
          : `Доступне оновлення v${targetVerName}`;
      }
    }

    if (summaryEl) {
      const curVer = escapeText(info.versionName || '—');
      const curBuild = Number(info.webBuild ?? info.versionCode ?? 0);
      if (isNative) {
        const curNative = Number(info.nativeVersionCode ?? info.versionCode ?? 0);
        summaryEl.innerHTML =
          `Поточна APK: <strong>v${curVer} (build ${curNative})</strong><br>` +
          `Нова версія APK: <strong>v${escapeText(nativeInfo.version_name)} (build ${Number(nativeInfo.version_code)})</strong>`;
      } else {
        summaryEl.innerHTML =
          `Поточна версія: <strong>v${curVer} (#${curBuild})</strong><br>` +
          `Нова версія: <strong>v${escapeText(manifest.version_name)} (#${Number(manifest.web_build)})</strong> · ${formatSize(manifest.file_size)} (швидке оновлення без перевстановлення APK)`;
      }
    }

    if (changelogEl) {
      const rawNotes = isNative ? nativeInfo.changelog : manifest.changelog;
      const notes = (rawNotes || '').trim() || 'Покращення стабільності, інтерфейсу та виправлення помилок.';
      changelogEl.innerHTML = escapeText(notes).replace(/\n/g, '<br>');
    }

    if (closeBtn) closeBtn.style.display = mandatory ? 'none' : '';
    if (laterBtn) laterBtn.style.display = mandatory ? 'none' : '';
    if (installBtn) {
      installBtn.disabled = false;
      installBtn.textContent = isNative ? 'Завантажити у браузері' : 'Оновити зараз';
    }
    if (progWrap) progWrap.style.display = 'none';
    if (progBar) progBar.style.width = '0%';

    if (isNative) {
      setStatusMessage(
        mandatory
          ? 'Ця збірка APK потребує оновлення базового пакета Android. Натисніть кнопку нижче, щоб завантажити нову версію через браузер.'
          : 'Для оновлення базового APK-пакета буде відкрито офіційну сторінку завантаження у браузері.',
        mandatory
      );
    } else {
      setStatusMessage(
        mandatory
          ? 'Доступне критичне оновлення інтерфейсу. Натисніть «Оновити зараз» — це займе кілька секунд.'
          : '',
        mandatory
      );
    }

    if (typeof window.openModal === 'function') {
      window.openModal('modalAppUpdate');
    } else {
      modal.style.display = 'flex';
    }
  }

  async function startOtaDownloadAndInstall() {
    const plugin = getOtaPlugin();
    if (!plugin || !latestManifest || isDownloading) return;

    const installBtn = document.getElementById('otaInstallBtn');
    const laterBtn = document.getElementById('otaLaterBtn');
    const progWrap = document.getElementById('otaProgressWrap');
    const progBar = document.getElementById('otaProgressBar');
    const progTxt = document.getElementById('otaProgressText');

    if (currentUpdateMode === 'native') {
      const targetUrl = latestManifest?.native?.landing_url || `${resolveOtaBaseUrl()}/`;
      try {
        await plugin.openBrowserUrl({ url: targetUrl });
        setStatusMessage('Офіційну сторінку завантаження APK відкрито у браузері.', false);
      } catch (err) {
        setStatusMessage(err?.message || 'Не вдалося відкрити сторінку завантаження у браузері.', true);
      }
      return;
    }

    isDownloading = true;
    bindProgressListener(plugin);
    setStatusMessage('', false);
    if (progWrap) progWrap.style.display = 'block';
    if (progBar) progBar.style.width = '0%';
    if (progTxt) progTxt.textContent = 'Підготовка Web-оновлення...';
    if (installBtn) {
      installBtn.disabled = true;
      installBtn.textContent = 'Завантаження...';
    }
    if (laterBtn) laterBtn.disabled = true;

    try {
      await plugin.downloadAndApplyWebBundle({
        url: latestManifest.download_url,
        sha256: latestManifest.sha256 || '',
        webBuild: Number(latestManifest.web_build),
        versionName: String(latestManifest.version_name || ''),
      });

      if (progTxt) progTxt.textContent = 'Оновлення застосовано. Перезавантаження інтерфейсу...';
      setStatusMessage('Оновлення успішно встановлено. Додаток перезавантажується...', false);
    } catch (err) {
      setStatusMessage(err?.message || 'Помилка під час завантаження оновлення.', true);
      if (installBtn) {
        installBtn.disabled = false;
        installBtn.textContent = 'Спробувати ще раз';
      }
    } finally {
      isDownloading = false;
      if (laterBtn) laterBtn.disabled = false;
    }
  }

  function dismissOtaUpdateModal() {
    const modal = document.getElementById('modalAppUpdate');
    if (modal && modal.dataset.mandatory === 'true') {
      return;
    }
    if (latestManifest && currentUpdateMode) {
      try {
        sessionStorage.setItem(DISMISSED_KEY, buildDismissTag(currentUpdateMode, latestManifest));
      } catch (_) {}
    }
    if (typeof window.closeModal === 'function') {
      window.closeModal('modalAppUpdate');
    } else if (modal) {
      modal.style.display = 'none';
    }
  }

  async function checkForAppUpdates(options = {}) {
    const manual = Boolean(options.manual);
    const plugin = getOtaPlugin();
    if (!plugin) {
      if (manual && typeof window.showToast === 'function') {
        window.showToast('Перевірка оновлень доступна лише в Android-додатку.', 'info');
      }
      return null;
    }

    try {
      currentAppInfo = await plugin.getAppInfo();
      await renderServerModalAppVersion(currentAppInfo);

      if (!manual) {
        try {
          const lastCheck = Number(sessionStorage.getItem(LAST_CHECK_KEY) || '0');
          if (Date.now() - lastCheck < CHECK_INTERVAL_MS) {
            return null;
          }
        } catch (_) {}
      }

      const nativeCode = Number(currentAppInfo.nativeVersionCode ?? currentAppInfo.versionCode ?? 0);
      const webBuild = Number(currentAppInfo.webBuild ?? nativeCode);
      const otaBase = resolveOtaBaseUrl();
      const url =
        `${otaBase}/api/web/latest?current_native_code=${encodeURIComponent(nativeCode)}` +
        `&current_web_build=${encodeURIComponent(webBuild)}&_t=${Date.now()}`;

      const res = await fetch(url, { method: 'GET', cache: 'no-store' });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const manifest = await res.json();
      try {
        sessionStorage.setItem(LAST_CHECK_KEY, String(Date.now()));
      } catch (_) {}

      latestManifest = manifest;
      const nativeInfo = manifest?.native || {};
      const nativeRequired = Boolean(manifest?.native_update_required || nativeInfo.force_update);
      const webAvailable = Boolean(manifest?.web_update_available);
      const nativeOptional = Boolean(nativeInfo.update_available && !nativeRequired);

      let targetMode = null;
      let mandatory = false;
      if (nativeRequired) {
        targetMode = 'native';
        mandatory = true;
      } else if (webAvailable) {
        targetMode = 'web';
        mandatory = Boolean(manifest.web_force_update);
      } else if (nativeOptional) {
        targetMode = 'native';
        mandatory = false;
      }

      if (targetMode) {
        const tag = buildDismissTag(targetMode, manifest);
        let dismissedTag = '';
        try {
          dismissedTag = sessionStorage.getItem(DISMISSED_KEY) || '';
        } catch (_) {}

        if (manual || mandatory || dismissedTag !== tag) {
          await showUpdateModal(currentAppInfo, manifest, targetMode);
        }
      } else if (manual && typeof window.showToast === 'function') {
        window.showToast(`У вас актуальна версія v${currentAppInfo.versionName}`);
      }

      return manifest;
    } catch (err) {
      if (manual && typeof window.showToast === 'function') {
        window.showToast(`Не вдалося перевірити оновлення: ${err.message}`, true);
      }
      return null;
    }
  }

  window.checkForAppUpdates = checkForAppUpdates;
  window.startOtaDownloadAndInstall = startOtaDownloadAndInstall;
  window.dismissOtaUpdateModal = dismissOtaUpdateModal;
  window.refreshOtaVersionBadge = () => renderServerModalAppVersion();

  let otaInitialized = false;
  function initOtaUpdater() {
    if (otaInitialized) return;
    otaInitialized = true;
    const plugin = getOtaPlugin();
    if (!plugin) return;

    if (typeof plugin.confirmWebBundle === 'function') {
      plugin.confirmWebBundle().catch(() => {});
    }
    plugin.cleanupDownloadedUpdates().catch(() => {});
    plugin.getAppInfo().then((info) => {
      currentAppInfo = info;
      renderServerModalAppVersion(info);
    }).catch(() => {});

    setTimeout(() => {
      checkForAppUpdates({ manual: false });
    }, 1200);

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        checkForAppUpdates({ manual: false });
      }
    });
  }

  // Script may be lazy-loaded by ViewLoader AFTER DOMContentLoaded has already fired
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOtaUpdater);
  } else {
    initOtaUpdater();
  }
})();
