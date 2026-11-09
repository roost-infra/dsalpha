/*
 * Minimal service worker: it makes the app installable and keeps hashed build
 * assets warm. Nothing that can go stale is cached.
 *
 * - The document is always fetched from the network, so a deploy is never
 *   pinned by an old worker (index.html has its own stale-build recovery).
 * - API, auth and streaming traffic is left alone, same-origin or not.
 * - Only /assets/ (content-hashed filenames) is cache-first.
 */
const CACHE = 'athena-assets-v1';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return;
  if (!url.pathname.startsWith('/assets/')) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(request);
      if (hit) return hit;
      const response = await fetch(request);
      if (response.ok) await cache.put(request, response.clone());
      return response;
    })(),
  );
});
