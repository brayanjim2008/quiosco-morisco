/* Modo sin internet de la Caja.
   - La pantalla /pos y el catálogo se piden primero a internet; si no hay, se usan los guardados.
   - Estilos, íconos y letras se guardan para que la caja se vea igual sin internet.
   - Nada que guarde o cobre (POST) pasa por aquí: eso lo maneja la página con su cola de "ventas sin internet". */
const CACHE = 'cc-pos-v1';
const PAGINAS = ['/pos'];
const DATOS = ['/api/pos/catalogo_completo'];
const ESTATICOS = /^(\/static\/|https:\/\/(fonts\.googleapis\.com|fonts\.gstatic\.com|cdnjs\.cloudflare\.com|cdn\.jsdelivr\.net)\/)/;

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PAGINAS).catch(() => {})));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('cc-pos-') && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function primeroInternet(req) {
  const cache = await caches.open(CACHE);
  try {
    const resp = await fetch(req);
    // Solo se guarda una respuesta buena y de la propia caja (no la pantalla de login de una sesión vencida).
    if (resp.ok && !resp.redirected) cache.put(req, resp.clone());
    return resp;
  } catch (err) {
    const guardada = await cache.match(req, { ignoreSearch: true });
    if (guardada) return guardada;
    throw err;
  }
}

async function primeroGuardado(req) {
  const cache = await caches.open(CACHE);
  const guardada = await cache.match(req);
  const red = fetch(req).then(resp => { if (resp.ok || resp.type === 'opaque') cache.put(req, resp.clone()); return resp; }).catch(() => null);
  return guardada || (await red) || Response.error();
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const mismo = url.origin === self.location.origin;
  if (mismo && (PAGINAS.includes(url.pathname) || DATOS.includes(url.pathname))) {
    e.respondWith(primeroInternet(req));
  } else if ((mismo && url.pathname.startsWith('/static/')) || ESTATICOS.test(req.url)) {
    e.respondWith(primeroGuardado(req));
  }
});
