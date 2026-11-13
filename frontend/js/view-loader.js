// ==========================================================================
// 🧩 Modular View & Script Lazy Loader (No Build Step Required)
// ==========================================================================
(function initViewLoader() {
  const selfSrc = document.currentScript?.src || '';
  const vMatch = selfSrc.match(/[?&]v=([^&]+)/);
  const ASSET_VERSION = vMatch ? vMatch[1] : '5.6.9';

  const loadedViews = new Set();
  const viewPromises = new Map();
  const loadedScripts = new Set();
  const scriptPromises = new Map();

  // Pre-seed already loaded scripts from initial <script src> tags
  document.querySelectorAll('script[src]').forEach((s) => {
    const m = s.src.match(/\/frontend\/js\/([^?]+)/);
    if (m) loadedScripts.add(m[1]);
  });

  const TAB_REGISTRY = {
    'tab-dashboard':   { view: 'dashboard.html',   host: 'viewsHost', scripts: [] },
    'tab-fuel':        { view: 'fuel.html',        host: 'viewsHost', scripts: ['fuel.js'] },
    'tab-maintenance': { view: 'maintenance.html', host: 'viewsHost', scripts: ['operations.js'] },
    'tab-faults':      { view: 'faults.html',      host: 'viewsHost', scripts: ['operations.js'] },
    'tab-runs':        { view: 'runs.html',        host: 'viewsHost', scripts: ['operations.js'] },
    'tab-audit':       { view: 'audit.html',       host: 'viewsHost', scripts: ['audit-reports.js'] },
    'tab-reports':     { view: 'reports.html',     host: 'viewsHost', scripts: ['audit-reports.js'] },
    'tab-measurement': { view: 'measurement.html', host: 'viewsHost', scripts: ['measurement.js'] },
    'tab-admin':       { view: 'admin.html',       host: 'viewsHost', scripts: ['fuel.js', 'admin.js', 'backups.js'] },
  };

  const MODAL_REGISTRY = {
    // Account & App Modals
    modalAccountProfile:     { view: 'modals-account.html', scripts: [] },
    modalServerSettings:     { view: 'modals-account.html', scripts: [] },
    modalAppUpdate:          { view: 'modals-account.html', scripts: [] },

    // Operator Modals
    modalStopGen:            { view: 'modals-ops.html', scripts: [] },
    modalManualRun:          { view: 'modals-ops.html', scripts: [] },
    modalReceipt:            { view: 'modals-ops.html', scripts: ['fuel.js'] },
    modalTransfer:           { view: 'modals-ops.html', scripts: ['fuel.js'] },
    modalCanisterAction:     { view: 'modals-ops.html', scripts: ['fuel.js'] },
    modalMaintenance:        { view: 'modals-ops.html', scripts: ['operations.js'] },
    modalFault:              { view: 'modals-ops.html', scripts: ['operations.js'] },
    modalResolveFault:       { view: 'modals-ops.html', scripts: ['operations.js'] },

    // Admin Modals
    modalNewStock:           { view: 'modals-admin.html', scripts: ['fuel.js', 'admin.js'] },
    modalEditStock:          { view: 'modals-admin.html', scripts: ['fuel.js', 'admin.js'] },
    modalCanisterPool:       { view: 'modals-admin.html', scripts: ['fuel.js', 'admin.js'] },
    modalAdminResetMaint:    { view: 'modals-admin.html', scripts: ['operations.js', 'admin.js'] },
    modalExportAudit:        { view: 'modals-admin.html', scripts: ['audit-reports.js'] },
    modalAdjustment:         { view: 'modals-admin.html', scripts: ['audit-reports.js'] },
    modalUserCreate:         { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalUserEdit:           { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalUserResetPassword:  { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalUserDelete:         { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalCreateFacility:     { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalCreateGenerator:    { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalDeleteGenerator:    { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalDeleteFacility:     { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalQuickEditFacility:  { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalQuickEditGenerator: { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalSystemReset:        { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalCreateBackup:       { view: 'modals-admin.html', scripts: ['backups.js'] },
    modalBackupSettings:     { view: 'modals-admin.html', scripts: ['backups.js'] },
    modalConfirmRestore:     { view: 'modals-admin.html', scripts: ['backups.js'] },
    modalUploadRestore:      { view: 'modals-admin.html', scripts: ['backups.js'] },
    modalDeleteBackup:       { view: 'modals-admin.html', scripts: ['backups.js'] },
    modalSmtpTest:           { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalSendWeeklyReport:   { view: 'modals-admin.html', scripts: ['admin.js'] },
    modalMeasurementCancel:  { view: 'modals-admin.html', scripts: ['measurement.js'] },

    // Utility & Info Modals
    modalIosInstall:         { view: 'modals-utility.html', scripts: [] },
    modalForgotPassword:     { view: 'modals-utility.html', scripts: [] },
    modalResetPassword:      { view: 'modals-utility.html', scripts: [] },
    modalWeatherDetails:     { view: 'modals-utility.html', scripts: [] },
    modalAlertDetails:       { view: 'modals-utility.html', scripts: [] },
    modalMeasurementStatus:  { view: 'modals-utility.html', scripts: ['measurement.js'] },
    modalOfflineQueue:       { view: 'modals-utility.html', scripts: [] },

    // Legal Modals
    modalLicense:            { view: 'modals-legal.html', scripts: [] },
    modalPrivacyPolicy:      { view: 'modals-legal.html', scripts: [] },
    modalTermsOfService:     { view: 'modals-legal.html', scripts: [] },
    modalOperationalSafety:  { view: 'modals-legal.html', scripts: [] },
    modalDataGovernance:     { view: 'modals-legal.html', scripts: [] },
  };

  function resolveAssetUrl(relPath) {
    const base = typeof window.getApiBaseUrl === 'function' ? window.getApiBaseUrl() : '';
    const sep = relPath.includes('?') ? '&' : '?';
    return `${base}/frontend/${relPath}${sep}v=${encodeURIComponent(ASSET_VERSION)}`;
  }

  async function ensureView(viewFile, hostId) {
    if (!viewFile) return;
    if (loadedViews.has(viewFile)) return;
    if (viewPromises.has(viewFile)) return viewPromises.get(viewFile);

    const p = (async () => {
      const host = document.getElementById(hostId);
      if (!host) return;
      const resp = await fetch(resolveAssetUrl(`views/${viewFile}`), { credentials: 'same-origin' });
      if (!resp.ok) {
        throw new Error(`Не вдалося завантажити інтерфейс (${viewFile}: HTTP ${resp.status})`);
      }
      const html = await resp.text();
      const tpl = document.createElement('template');
      tpl.innerHTML = html.trim();
      host.appendChild(tpl.content);
      loadedViews.add(viewFile);

      if (typeof window.populateCachedFacilitySelects === 'function') {
        window.populateCachedFacilitySelects();
      }
      if (typeof window.applyRolePermissionsUI === 'function' && window.currentUser) {
        window.applyRolePermissionsUI();
      }
    })();

    viewPromises.set(viewFile, p);
    try {
      await p;
    } catch (err) {
      viewPromises.delete(viewFile);
      throw err;
    }
  }

  function ensureScript(scriptFile) {
    if (!scriptFile) return Promise.resolve();
    if (loadedScripts.has(scriptFile)) return Promise.resolve();
    if (scriptPromises.has(scriptFile)) return scriptPromises.get(scriptFile);

    const p = new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = resolveAssetUrl(`js/${scriptFile}`);
      el.async = false;
      el.onload = () => {
        loadedScripts.add(scriptFile);
        resolve();
      };
      el.onerror = () => {
        scriptPromises.delete(scriptFile);
        reject(new Error(`Не вдалося завантажити модуль (${scriptFile})`));
      };
      document.body.appendChild(el);
    });

    scriptPromises.set(scriptFile, p);
    return p;
  }

  async function ensureScripts(scripts) {
    if (!Array.isArray(scripts) || scripts.length === 0) return;
    await Promise.all(scripts.map((s) => ensureScript(s)));
  }

  async function ensureTab(paneId) {
    const cfg = TAB_REGISTRY[paneId];
    if (!cfg) return;
    // Load HTML partial BEFORE evaluating tab scripts so initial queries see mounted DOM
    await ensureView(cfg.view, cfg.host);
    await ensureScripts(cfg.scripts);
  }

  async function ensureModal(modalId) {
    const existing = document.getElementById(modalId);
    const cfg = MODAL_REGISTRY[modalId];
    if (existing) {
      if (cfg && cfg.scripts.length) await ensureScripts(cfg.scripts);
      return existing;
    }
    if (!cfg) return null;
    await ensureView(cfg.view, 'modalsHost');
    await ensureScripts(cfg.scripts);
    return document.getElementById(modalId);
  }

  function scheduleIdleWarmup() {
    const run = () => {
      ensureView('modals-account.html', 'modalsHost').catch(() => {});
      ensureView('modals-ops.html', 'modalsHost').catch(() => {});
      ensureView('modals-utility.html', 'modalsHost').catch(() => {});
    };
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(run, { timeout: 2500 });
    } else {
      setTimeout(run, 1500);
    }
  }

  // Load OTA updater script ONLY inside native Capacitor Android builds
  if (window.Capacitor || window.location.protocol === 'capacitor:' || window.location.protocol === 'file:') {
    ensureScript('ota-updater.js').catch(() => {});
  }

  window.ViewLoader = {
    ASSET_VERSION,
    ensureView,
    ensureScript,
    ensureScripts,
    ensureTab,
    ensureModal,
    scheduleIdleWarmup,
    isViewLoaded: (v) => loadedViews.has(v),
    isScriptLoaded: (s) => loadedScripts.has(s),
  };
})();
