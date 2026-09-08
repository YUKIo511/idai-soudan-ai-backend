// 偉人相談AI Service Worker — アプリシェルのみキャッシュ。API 応答はキャッシュしない。
const CACHE = "idai-shell-v1";
const SHELL = [
  "/", "/index.html", "/app.js", "/styles.css",
  "/manifest.webmanifest", "/icon.svg", "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;                 // /consult 等は素通し（キャッシュしない）
  const url = new URL(request.url);
  if (url.pathname.startsWith("/consult")) return;
  if (url.pathname === "/characters" || url.pathname.startsWith("/characters/") ||
      url.pathname === "/healthz") {
    // 動的データ: network-first、失敗時のみキャッシュ
    e.respondWith(
      fetch(request).then((r) => { caches.open(CACHE).then((c) => c.put(request, r.clone())); return r; })
        .catch(() => caches.match(request))
    );
    return;
  }
  // アプリシェル: cache-first
  e.respondWith(caches.match(request).then((r) => r || fetch(request)));
});
