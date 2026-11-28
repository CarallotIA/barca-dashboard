/* Permet obrir el dashboard sense connexió (carcassa de la web). Els àudios descarregats es guarden a IndexedDB, no aquí. */
const V = "fcb-shell-v1";
const SHELL = ["./", "index.html", "favicon.png", "apple-touch-icon.png", "logos/dazn.svg", "logos/movistar.svg", "logos/orange.svg", "logos/youtube.svg"];
self.addEventListener("install", e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const r = e.request;
  if (r.method !== "GET") return;
  const u = new URL(r.url);
  if (u.origin !== location.origin) return;           // APIs i imatges externes: sense tocar
  if (r.mode === "navigate") {                          // pàgina: sempre la més nova; sense xarxa, l'última guardada
    e.respondWith(fetch(r).then(res => { const c = res.clone(); caches.open(V).then(ch => ch.put("index.html", c)); return res; })
      .catch(() => caches.match("index.html")));
    return;
  }
  e.respondWith(caches.open(V).then(ch => ch.match(r).then(hit => {   // fotos, logos...: ràpid i es refresca
    const net = fetch(r).then(res => { if (res.ok) ch.put(r, res.clone()); return res; }).catch(() => hit);
    return hit || net;
  })));
});
