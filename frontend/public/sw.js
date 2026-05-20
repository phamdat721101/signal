const CACHE = 'ape-v4';
const STATIC = ['/manifest.json', '/favicon.svg', '/icons.svg', '/app.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const { request } = e;
  const url = new URL(request.url);

  // API calls: network only
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(request));
    return;
  }

  // SPA navigation: serve index.html for all non-file paths
  if (request.mode === 'navigate') {
    e.respondWith(
      fetch('/index.html').then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put('/index.html', clone));
        return res;
      }).catch(() => caches.match('/index.html'))
    );
    return;
  }

  // JS/CSS: network-first
  if (url.pathname.endsWith('.js') || url.pathname.endsWith('.css')) {
    e.respondWith(
      fetch(request).then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(request, clone));
        return res;
      }).catch(() => caches.match(request))
    );
    return;
  }

  // Static assets (images, fonts): cache-first
  e.respondWith(caches.match(request).then(r => r || fetch(request).then(res => {
    const clone = res.clone();
    caches.open(CACHE).then(c => c.put(request, clone));
    return res;
  })));
});

self.addEventListener('push', e => {
  const data = e.data?.json() || { title: 'Kinetic', body: 'New signal!' };
  e.waitUntil(self.registration.showNotification(data.title, { body: data.body, icon: '/favicon.svg' }));
});
