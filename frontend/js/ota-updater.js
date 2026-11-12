// frontend/js/ota-updater.js
// Native Android APK Over-The-Air (OTA) update checker, downloader & installer bridge

(function () {
  const CHECK_INTERVAL_MS = 10 * 60 * 1000;
  const DISMISSED_KEY = 'sdgen_ota_dismissed_code';
  const LAST_CHECK_KEY = 'sdgen_ota_last_check_ts';

  let currentAppInfo = null;
  let latestManifest = null;
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

  function formatMb(bytes) {
    const n = Number(bytes || 0);
    if (!Number.isFinite(n) || n <= 0) return '—';
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
          ? `Завантаження... ${pct}% (${formatMb(dl)} / ${formatMb(total)})`
          : `Завантаження... ${pct}%`;
      } else {
        bar.style.width = '50%';
        txt.textContent = `Завантаження... ${formatMb(dl)}`;
      }
    });
  }

  function renderServerModalAppVersion(info) {
    const box = document.getElementById('nativeAppVersionRow');
    const label = document.getElementById('nativeAppVersionLabel');
    if (!box || !label) return;
    box.style.display = 'flex';
    label.textContent = `Android додаток: v${info.versionName || '—'} (build ${info.versionCode || 0})`;
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

  function showUpdateModal(info, manifest) {
    const modal = document.getElementById('modalAppUpdate');
    if (!modal) return;

    const mandatory = Boolean(manifest.force_update) ||
      (Number(info.versionCode || 0) < Number(manifest.min_supported_version_code || 0)) ||
      Boolean(manifest.is_mandatory);

    modal.dataset.mandatory = mandatory ? 'true' : 'false';

    const titleEl = document.getElementById('otaModalTitle');
    const summaryEl = document.getElementById('otaVersionSummary');
    const changelogEl = document.getElementById('otaChangelogBox');
    const closeBtn = document.getElementById('otaCloseBtn');
    const laterBtn = document.getElementById('otaLaterBtn');
    const installBtn = document.getElementById('otaInstallBtn');
    const progWrap = document.getElementById('otaProgressWrap');
    const progBar = document.getElementById('otaProgressBar');

    if (titleEl) {
      titleEl.textContent = mandatory
        ? `Обов'язкове оновлення v${manifest.version_name}`
        : `Доступне оновлення v${manifest.version_name}`;
    }
    if (summaryEl) {
      summaryEl.innerHTML =
        `Поточна версія: <strong>v${escapeText(info.versionName)} (build ${Number(info.versionCode)})</strong><br>` +
        `Нова версія: <strong>v${escapeText(manifest.version_name)} (build ${Number(manifest.version_code)})</strong> · ${formatMb(manifest.file_size)}`;
    }
    if (changelogEl) {
      const notes = (manifest.changelog || '').trim() || 'Покращення стабільності та виправлення помилок.';
      changelogEl.innerHTML = escapeText(notes).replace(/\n/g, '<br>');
    }
    if (closeBtn) closeBtn.style.display = mandatory ? 'none' : '';
    if (laterBtn) laterBtn.style.display = mandatory ? 'none' : '';
    if (installBtn) {
      installBtn.disabled = false;
      installBtn.textContent = 'Оновити зараз';
    }
    if (progWrap) progWrap.style.display = 'none';
    if (progBar) progBar.style.width = '0%';
    setStatusMessage(
      mandatory
        ? 'Ця версія додатка більше не підтримується сервером. Оновіться, щоб продовжити роботу.'
        : '',
      mandatory
    );

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

    isDownloading = true;
    bindProgressListener(plugin);
    setStatusMessage('', false);
    if (progWrap) progWrap.style.display = 'block';
    if (progBar) progBar.style.width = '0%';
    if (progTxt) progTxt.textContent = 'Підготовка завантаження...';
    if (installBtn) {
      installBtn.disabled = true;
      installBtn.textContent = 'Завантаження...';
    }
    if (laterBtn) laterBtn.disabled = true;

    try {
      const res = await plugin.downloadAndInstall({
        url: latestManifest.download_url,
        sha256: latestManifest.sha256 || '',
        versionCode: Number(latestManifest.version_code),
      });

      if (res && res.status === 'permission_required') {
        setStatusMessage(
          'Увімкніть дозвіл «Встановлення з цього джерела» для SD-GEN016, після чого натисніть кнопку нижче ще раз.',
          false
        );
        if (installBtn) {
          installBtn.disabled = false;
          installBtn.textContent = 'Надати дозвіл і встановити';
        }
      } else {
        if (progTxt) progTxt.textContent = 'Інсталятор Android відкрито. Підтвердьте оновлення.';
        if (installBtn) {
          installBtn.disabled = false;
          installBtn.textContent = 'Відкрити інсталятор ще раз';
        }
      }
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
    if (latestManifest && latestManifest.version_code) {
      try {
        sessionStorage.setItem(DISMISSED_KEY, String(latestManifest.version_code));
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
    if (!plugin) return null;

    try {
      if (!currentAppInfo) {
        currentAppInfo = await plugin.getAppInfo();
        renderServerModalAppVersion(currentAppInfo);
      }

      if (!manual) {
        try {
          const lastCheck = Number(sessionStorage.getItem(LAST_CHECK_KEY) || '0');
          if (Date.now() - lastCheck < CHECK_INTERVAL_MS) {
            return null;
          }
        } catch (_) {}
      }

      const otaBase = resolveOtaBaseUrl();
      const url = `${otaBase}/api/latest?current_code=${encodeURIComponent(currentAppInfo.versionCode)}&_t=${Date.now()}`;
      const res = await fetch(url, { method: 'GET', cache: 'no-store' });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const manifest = await res.json();
      try {
        sessionStorage.setItem(LAST_CHECK_KEY, String(Date.now()));
      } catch (_) {}

      if (!manifest || !manifest.has_release) {
        if (manual && typeof window.showToast === 'function') {
          window.showToast('На сервері ще немає опублікованих релізів APK.');
        }
        return manifest;
      }

      latestManifest = manifest;
      const installedCode = Number(currentAppInfo.versionCode || 0);
      const latestCode = Number(manifest.version_code || 0);
      const minSupported = Number(manifest.min_supported_version_code || 0);
      const hasNewer = latestCode > installedCode;
      const mandatory = hasNewer && (installedCode < minSupported || Boolean(manifest.is_mandatory));

      if (hasNewer) {
        let dismissedCode = 0;
        try {
          dismissedCode = Number(sessionStorage.getItem(DISMISSED_KEY) || '0');
        } catch (_) {}

        if (manual || mandatory || dismissedCode < latestCode) {
          showUpdateModal(currentAppInfo, manifest);
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

  document.addEventListener('DOMContentLoaded', () => {
    const plugin = getOtaPlugin();
    if (!plugin) return;

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
  });
})();
