const CACHE_NAME = 'sd-gen016-v4.5';
const STATIC_ASSETS = [
  '/',
  '/manifest.json',
  '/frontend/styles.css?v=4.5',
  '/frontend/app.js?v=4.5',
  '/frontend/icons/icon-192.png',
  '/frontend/icons/icon-512.png',
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

  // Do NOT intercept or cache API requests - let browser fetch natively
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // Network first with cache fallback for HTML and static assets
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
  const options = {
    body: data.body || '',
    icon: data.icon || '/frontend/icons/icon-192.png',
    badge: data.badge || '/frontend/icons/icon-192.png',
    tag: data.tag || 'sd-general-notification',
    data: data.data || { url: '/' },
    vibrate: [200, 100, 200, 100, 200],
    renotify: true,
    requireInteraction: false
  };

  event.waitUntil(self.registration.showNotification(title, options));
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

