// v8 — evict any 402/error responses that v7 cached for cross-origin paid APIs.
const CACHE = 'ape-v8';
const STATIC = ['/manifest.json', '/favicon.svg', '/icons.svg', '/app.png'];
const FEATURED_GEM_URL = 'https://ai.overguild.com/api/featured-gem';

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

  // Skip non-http(s) schemes (chrome-extension://, blob:, ...) — Cache API
  // rejects them and the resulting promise rejection spams the console.
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;

  // SRP: this SW owns the same-origin app shell only. Anything cross-origin
  // (agent-api, RPCs, third-party CDNs) MUST bypass the SW entirely — caching
  // a 402 challenge here makes the x402 retry-with-payment flow impossible
  // because the second fetch is served from cache before X-Payment-* headers
  // can hit the network. Same reasoning for non-GET requests.
  if (request.method !== 'GET') return;
  if (url.origin !== self.location.origin && request.url !== FEATURED_GEM_URL) return;

  // Featured gem: stale-while-revalidate. Splash gets a cached gem instantly,
  // background refresh updates it for next visit. Keeps the moment under 200ms.
  if (request.url === FEATURED_GEM_URL) {
    e.respondWith(
      caches.open(CACHE).then(c =>
        c.match(request).then(cached => {
          const fetchPromise = fetch(request).then(res => {
            if (res && res.ok) c.put(request, res.clone());
            return res;
          }).catch(() => cached);
          return cached || fetchPromise;
        })
      )
    );
    return;
  }

  // All other same-origin API: network only.
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(request));
    return;
  }

  // SPA navigation: serve index.html for all non-file paths
  if (request.mode === 'navigate') {
    e.respondWith(
      fetch('/index.html').then(res => {
        if (res && res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put('/index.html', clone));
        }
        return res;
      }).catch(() => caches.match('/index.html'))
    );
    return;
  }

  // JS/CSS: network-first; only cache OK responses so a transient 5xx doesn't
  // poison the cache and brick the next page load.
  if (url.pathname.endsWith('.js') || url.pathname.endsWith('.css')) {
    e.respondWith(
      fetch(request).then(res => {
        if (res && res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(request, clone));
        }
        return res;
      }).catch(() => caches.match(request))
    );
    return;
  }

  // Static assets (images, fonts): cache-first; only cache OK responses.
  e.respondWith(caches.match(request).then(r => r || fetch(request).then(res => {
    if (res && res.ok) {
      const clone = res.clone();
      caches.open(CACHE).then(c => c.put(request, clone));
    }
    return res;
  })));
});

self.addEventListener('push', e => {
  const data = e.data?.json() || { title: 'Kinetic', body: 'New signal!' };
  e.waitUntil(self.registration.showNotification(data.title, { body: data.body, icon: '/favicon.svg' }));
});
