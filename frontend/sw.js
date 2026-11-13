const CACHE_NAME = 'sd-gen016-v5.6.7';
const STATIC_ASSETS = [
  '/',
  '/manifest.json',
  '/frontend/css/base.css?v=5.6.7',
  '/frontend/css/components.css?v=5.6.7',
  '/frontend/css/views.css?v=5.6.7',
  '/frontend/css/layout.css?v=5.6.7',
  '/frontend/js/view-loader.js?v=5.6.7',
  '/frontend/js/core.js?v=5.6.7',
  '/frontend/js/offline-queue.js?v=5.6.7',
  '/frontend/js/theme-format.js?v=5.6.7',
  '/frontend/js/auth-nav.js?v=5.6.7',
  '/frontend/js/dashboard.js?v=5.6.7',
  '/frontend/js/notifications.js?v=5.6.7',
  '/frontend/js/yasno.js?v=5.6.7',
  '/frontend/js/weather-alerts.js?v=5.6.7',
  '/frontend/views/dashboard.html?v=5.6.7',
  '/frontend/views/modals-account.html?v=5.6.7',
  '/frontend/views/modals-ops.html?v=5.6.7',
  '/frontend/icons/logo.png',
  '/frontend/icons/apple-touch-icon.png',
  '/frontend/icons/icon-192.png',
  '/frontend/icons/icon-512.png',
  '/frontend/icons/icon-maskable-192.png',
  '/frontend/icons/icon-maskable-512.png',
  '/frontend/favicon.ico'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('Some assets could not be cached immediately:', err);
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  // Do NOT intercept or cache API calls or authenticated uploads (avatars/PDFs)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/')) {
    return;
  }

  // Cache-First for versioned static frontend assets & lazy views/scripts/icons
  const isStaticAsset =
    url.pathname.startsWith('/frontend/css/') ||
    url.pathname.startsWith('/frontend/js/') ||
    url.pathname.startsWith('/frontend/views/') ||
    url.pathname.startsWith('/frontend/icons/') ||
    url.pathname === '/frontend/favicon.ico';

  if (isStaticAsset) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          if (response.status === 200) {
            const resClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
          }
          return response;
        });
      })
    );
    return;
  }

  // Network-first with cache fallback for HTML shell and manifest
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.status === 200) {
          const resClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
          return response;
        }
        if (response.status >= 500) {
          return caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) return cachedResponse;
            if (event.request.mode === 'navigate') {
              return caches.match('/').then((rootCache) => rootCache || response);
            }
            return response;
          });
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          if (event.request.mode === 'navigate') {
            return caches.match('/');
          }
        });
      })
  );
});

// Web Push Notification Event Handling (Android drawer / lock screen / Desktop)
self.addEventListener('push', (event) => {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (_) {
      data = { title: 'Service Desk Генератора', body: event.data.text() };
    }
  }

  const title = data.title || '🔔 Service Desk Генератора';
  const eventType = (data.data && data.data.event_type) ? String(data.data.event_type) : '';
  const isCritical = ['AIR_ALERT_START', 'CRITICAL_FAULT', 'LOW_FUEL', 'GENERATOR_SAFETY_STOP'].includes(eventType);

  const options = {
    body: data.body || '',
    icon: data.icon || '/frontend/icons/icon-192.png',
    badge: data.badge || '/frontend/icons/icon-192.png',
    tag: data.tag || 'sd-general-notification',
    data: data.data || { url: '/' },
    vibrate: isCritical ? [300, 120, 300, 120, 400] : [200, 100, 200],
    renotify: true,
    requireInteraction: isCritical
  };

  const notifyClientsPromise = self.clients
    .matchAll({ type: 'window', includeUncontrolled: true })
    .then((clientList) => {
      for (const client of clientList) {
        try {
          client.postMessage({
            type: 'PUSH_NOTIFICATION_RECEIVED',
            payload: {
              title,
              body: options.body,
              tag: options.tag,
              data: options.data
            }
          });
        } catch (_) {}
      }
    })
    .catch(() => {});

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(title, options),
      notifyClientsPromise
    ])
  );
});

self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        try {
          client.postMessage({ type: 'PUSH_SUBSCRIPTION_CHANGED' });
        } catch (_) {}
      }
    })
  );
});

// Notification Click Event Handling: focus or open app window to target tab
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url && 'focus' in client) {
          if ('navigate' in client && targetUrl !== '/') {
            client.navigate(targetUrl);
          }
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});

