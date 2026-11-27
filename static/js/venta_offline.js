/* Caja sin internet ("Venta sin internet").
   1) Avisa en grande cuando se cae el internet.
   2) Permite vender con el catálogo guardado: imprime comanda(s) y nota en la impresora de esta caja.
   3) Guarda cada venta en esta computadora con una llave única y la sube sola cuando vuelve el internet
      (el servidor la registra una sola vez aunque se reintente).
   Usa de la Caja: escHtml, construirHTMLNotaFinal, mandarImprimirHTMLDirecto, USUARIO_POS. */
(function () {
  const K_COLA = 'cc_ventas_offline', K_ERR = 'cc_ventas_offline_error', K_CAT = 'cc_catalogo_offline';
  let enLinea = navigator.onLine, subiendo = false, ticket = [], formaPago = 'EF', filtroCat = '';
  const $ = id => document.getElementById(id);
  const leer = k => { try { return JSON.parse(localStorage.getItem(k) || '[]'); } catch (e) { return []; } };
  const guardar = (k, v) => localStorage.setItem(k, JSON.stringify(v));
  const dinero = v => '$' + Number(v || 0).toFixed(2);
  const usuario = () => (typeof USUARIO_POS !== 'undefined' ? USUARIO_POS : '');
  const esc = s => (window.escHtml ? window.escHtml(s) : String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m])));

  // ---------- service worker (guarda la caja para abrir sin internet) ----------
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});

  // ---------- catálogo guardado ----------
  window.guardarCatalogoOffline = function (d) {
    try {
      localStorage.setItem(K_CAT, JSON.stringify({ guardado: new Date().toISOString(), categorias: d.categorias || [],
        productos: (d.productos || []).filter(p => !p.agotado && p.disponible !== false) }));
    } catch (e) {}
  };
  const catalogo = () => { try { return JSON.parse(localStorage.getItem(K_CAT) || 'null'); } catch (e) { return null; } };

  // ---------- ¿hay internet? (se deduce de las propias peticiones de la caja, sin tráfico extra) ----------
  const fetchOriginal = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : String((input && input.url) || '');
    const mismo = !/^https?:\/\//i.test(url) || url.indexOf(location.origin) === 0;
    return fetchOriginal.call(this, input, init).then(r => { if (mismo) marcarRed(true); return r; },
      err => { if (mismo) marcarRed(false); throw err; });
  };
  window.addEventListener('offline', () => marcarRed(false));
  window.addEventListener('online', () => { marcarRed(true); subirPendientes(); });

  function marcarRed(ok) {
    if (ok === enLinea) return;
    enLinea = ok;
    pintarBarra();
    if (ok) subirPendientes();
  }

  // ---------- barra de aviso ----------
  function pintarBarra() {
    let b = $('barraOffline');
    if (!b) {
      b = document.createElement('div');
      b.id = 'barraOffline';
      b.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:9000;display:none;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 16px;font-weight:800;font-size:14px;color:#fff;box-shadow:0 -4px 14px rgba(0,0,0,.25);';
      document.body.appendChild(b);
    }
    const pend = leer(K_COLA).length, errs = leer(K_ERR).length;
    if (enLinea && !pend && !errs) { b.style.display = 'none'; return; }
    b.style.display = 'flex';
    b.style.background = enLinea ? '#b45309' : '#b91c1c';
    b.innerHTML = (enLinea
      ? `<span>📶 Volvió el internet. ${pend ? `Subiendo ${pend} venta${pend > 1 ? 's' : ''} hechas sin internet…` : ''}</span>`
      : `<span style="font-size:16px;">⚠️ SIN INTERNET</span><span style="font-weight:600;">Sigue vendiendo con "Venta sin internet": se guarda en esta computadora y se sube sola al volver.</span>`)
      + (pend && !enLinea ? `<span style="background:rgba(0,0,0,.25);padding:3px 10px;border-radius:12px;">${pend} por subir</span>` : '')
      + (errs ? `<span style="background:#fff;color:#b91c1c;padding:3px 10px;border-radius:12px;cursor:pointer;" onclick="reintentarVentasOffline()">${errs} con problema · Reintentar</span>` : '')
      + `<button type="button" onclick="abrirVentaOffline()" style="margin-left:auto;height:40px;padding:0 16px;border-radius:9px;border:2px solid #fff;background:#fff;color:#b91c1c;font-weight:900;font-size:14px;cursor:pointer;">🧾 Venta sin internet</button>`;
  }

  // ---------- subir lo pendiente ----------
  async function subirPendientes() {
    if (subiendo || !enLinea) return;
    let cola = leer(K_COLA);
    if (!cola.length) { pintarBarra(); return; }
    subiendo = true;
    try {
      for (const v of cola.slice()) {
        let r, d;
        try {
          r = await fetch('/api/pos/venta_offline', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(v) });
          d = await r.json().catch(() => ({}));
        } catch (e) { break; }   // se volvió a ir el internet: se intenta después
        if (r.ok && d.ok) {
          cola = leer(K_COLA).filter(x => x.idem !== v.idem); guardar(K_COLA, cola);
          if (window.notificarBarra) notificarBarra(`✓ Venta sin internet registrada: folio ${d.folio}`);
        } else if (d.turno_cerrado) {
          if (window.notificarBarra) notificarBarra('🔒 Abre el turno de la caja para subir las ventas hechas sin internet.');
          break;
        } else if (r.redirected || r.status === 401 || (r.status === 400 && /sesión/i.test(d.msg || ''))) {
          if (window.notificarBarra) notificarBarra('🔑 Vuelve a iniciar sesión para subir las ventas hechas sin internet.');
          break;
        } else {
          // No se pudo registrar (dato raro): se aparta para revisarla, sin perderla ni trabar a las demás.
          cola = leer(K_COLA).filter(x => x.idem !== v.idem); guardar(K_COLA, cola);
          const errs = leer(K_ERR); errs.push(Object.assign({}, v, { error: d.msg || ('Error ' + r.status) })); guardar(K_ERR, errs);
        }
      }
    } finally {
      subiendo = false;
      pintarBarra();
      if (window.sincronizarCuentasEnVivoCaja) try { sincronizarCuentasEnVivoCaja(); } catch (e) {}
    }
  }
  window.reintentarVentasOffline = function () {
    const errs = leer(K_ERR);
    if (!errs.length) return;
    guardar(K_COLA, leer(K_COLA).concat(errs.map(v => { const x = Object.assign({}, v); delete x.error; return x; })));
    guardar(K_ERR, []);
    subirPendientes();
  };
  setInterval(() => { if (leer(K_COLA).length) subirPendientes(); }, 20000);

  // ---------- pantalla de venta ----------
  const PALABRAS_BARRA = ['caliente', 'fría', 'fria', 'frapp', 'infus', 'jugo', 'refresco', 'agua', 'postre', 'cerveza', 'coctel', 'cóctel', 'vino', 'café', 'cafe', 'bebida', 'barra', 'fruta', 'té'];
  const areaDe = p => (p.area_impresion === 'BARRA' || p.area_impresion === 'COCINA') ? p.area_impresion
    : (PALABRAS_BARRA.some(w => String(p.categoria || '').toLowerCase().includes(w)) ? 'BARRA' : 'COCINA');

  function crearModal() {
    if ($('modalVentaOffline')) return;
    const m = document.createElement('div');
    m.id = 'modalVentaOffline';
    m.style.cssText = 'position:fixed;inset:0;z-index:9500;background:rgba(11,41,36,.75);display:none;align-items:center;justify-content:center;';
    m.innerHTML = `<div style="background:#fff;width:96%;max-width:1150px;height:92vh;border-radius:14px;display:grid;grid-template-columns:1.35fr 1fr;overflow:hidden;font-family:'Open Sans',sans-serif;">
      <div style="display:flex;flex-direction:column;min-height:0;border-right:2px solid #e2e8f0;">
        <div style="background:#b91c1c;color:#fff;padding:10px 14px;font-weight:900;display:flex;justify-content:space-between;align-items:center;">
          <span>🧾 VENTA SIN INTERNET</span><span id="vo_cat_fecha" style="font-weight:600;font-size:11.5px;"></span></div>
        <div style="padding:8px;display:flex;gap:6px;"><input id="vo_buscar" placeholder="🔍 Buscar platillo..." style="flex:1;height:40px;border-radius:8px;border:1.5px solid #cbd5e1;padding:0 10px;font-weight:700;font-size:14px;" oninput="ventaOfflinePintar()"></div>
        <div id="vo_cats" style="display:flex;gap:5px;flex-wrap:wrap;padding:0 8px 8px;"></div>
        <div id="vo_prods" style="flex:1;overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px;padding:8px;align-content:start;"></div>
      </div>
      <div style="display:flex;flex-direction:column;min-height:0;padding:10px;">
        <div style="display:flex;gap:6px;margin-bottom:6px;"><input id="vo_mesa" placeholder="Mesa o nombre (opcional)" style="flex:1;height:38px;border-radius:8px;border:1.5px solid #cbd5e1;padding:0 10px;font-weight:700;"></div>
        <div id="vo_ticket" style="flex:1;overflow-y:auto;border:1.5px solid #e2e8f0;border-radius:10px;padding:6px;"></div>
        <div style="display:flex;justify-content:space-between;font-size:22px;font-weight:900;color:#0b2924;margin:8px 2px;"><span>TOTAL</span><span id="vo_total">$0.00</span></div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;" id="vo_formas">
          <button type="button" data-f="EF" onclick="ventaOfflineForma('EF')">💵 EFECTIVO</button>
          <button type="button" data-f="TARJ" onclick="ventaOfflineForma('TARJ')">💳 TARJETA</button>
          <button type="button" data-f="TRANS" onclick="ventaOfflineForma('TRANS')">🏦 TRANSF.</button>
        </div>
        <div id="vo_ef" style="display:flex;gap:6px;align-items:center;margin-top:6px;">
          <input id="vo_recibe" type="number" inputmode="decimal" placeholder="¿Con cuánto paga?" style="flex:1;height:42px;border-radius:8px;border:1.5px solid #cbd5e1;padding:0 10px;font-weight:800;font-size:16px;" oninput="ventaOfflineCambio()">
          <span style="font-weight:900;color:#16a34a;font-size:16px;" id="vo_cambio"></span>
        </div>
        <div style="display:grid;grid-template-columns:1.6fr 1fr;gap:6px;margin-top:8px;">
          <button type="button" onclick="ventaOfflineCobrar()" style="height:56px;border-radius:10px;border:2px solid #15803d;background:#16a34a;color:#fff;font-weight:900;font-size:16px;cursor:pointer;">✓ COBRAR E IMPRIMIR</button>
          <button type="button" onclick="cerrarVentaOffline()" style="height:56px;border-radius:10px;border:2px solid #fca5a5;background:#fff;color:#b91c1c;font-weight:900;font-size:15px;cursor:pointer;">✕ CERRAR</button>
        </div>
        <div style="font-size:11px;color:#64748b;margin-top:6px;">La comanda y la nota salen en la impresora de esta caja. La venta se guarda aquí y se sube sola cuando vuelva el internet.</div>
      </div></div>`;
    document.body.appendChild(m);
    m.querySelectorAll('#vo_formas button').forEach(b => { b.style.cssText = 'height:46px;border-radius:9px;border:2px solid #cbd5e1;background:#f8fafc;font-weight:900;font-size:13px;cursor:pointer;'; });
  }

  window.abrirVentaOffline = function () {
    crearModal();
    const cat = catalogo();
    if (!cat || !cat.productos.length) return alert('Esta computadora todavía no tiene el menú guardado. Abre la Caja una vez con internet.');
    $('vo_cat_fecha').innerText = 'Menú guardado: ' + new Date(cat.guardado).toLocaleString('es-MX');
    ticket = []; filtroCat = ''; $('vo_buscar').value = ''; $('vo_mesa').value = ''; $('vo_recibe').value = '';
    ventaOfflineForma('EF');
    window.ventaOfflinePintar();
    $('modalVentaOffline').style.display = 'flex';
    setTimeout(() => $('vo_buscar').focus(), 50);
  };
  window.cerrarVentaOffline = function () {
    if (ticket.length && !confirm('¿Cerrar sin cobrar? Se pierde lo capturado.')) return;
    $('modalVentaOffline').style.display = 'none';
  };

  window.ventaOfflinePintar = function () {
    const cat = catalogo() || { categorias: [], productos: [] };
    const cats = [...new Set(cat.productos.map(p => p.categoria))];
    $('vo_cats').innerHTML = ['', ...cats].map(c => `<button type="button" onclick="ventaOfflineCat(this.dataset.cat)" data-cat="${esc(c)}" style="height:32px;padding:0 10px;border-radius:16px;border:1.5px solid ${c === filtroCat ? '#13423b' : '#cbd5e1'};background:${c === filtroCat ? '#13423b' : '#fff'};color:${c === filtroCat ? '#fff' : '#334155'};font-weight:800;font-size:12px;cursor:pointer;">${c ? esc(c) : 'Todo'}</button>`).join('');
    const q = $('vo_buscar').value.trim().toLowerCase();
    const lista = cat.productos.filter(p => (!filtroCat || p.categoria === filtroCat) && (!q || p.nombre.toLowerCase().includes(q)));
    $('vo_prods').innerHTML = lista.map(p => `<button type="button" onclick="ventaOfflineAgregar(${Number(p.id)})" style="min-height:64px;border-radius:10px;border:1.5px solid #e2e8f0;background:#fff;cursor:pointer;text-align:left;padding:6px 8px;"><b style="font-size:12.5px;display:block;line-height:1.2;color:#0b2924;">${esc(p.nombre)}</b><span style="font-weight:800;color:#c98246;font-size:13px;">${dinero(p.precio)}</span></button>`).join('')
      || '<p style="grid-column:1/-1;color:#64748b;text-align:center;">Sin resultados.</p>';
    pintarTicket();
  };
  window.ventaOfflineCat = function (c) { filtroCat = c; window.ventaOfflinePintar(); };

  window.ventaOfflineAgregar = function (id) {
    const p = (catalogo() || { productos: [] }).productos.find(x => x.id === id);
    if (!p) return;
    const ya = ticket.find(x => x.producto_id === id && !x.nota);
    if (ya) ya.cantidad += 1;
    else ticket.push({ producto_id: p.id, nombre: p.nombre, precio: Number(p.precio || 0), cantidad: 1, nota: '', area: areaDe(p) });
    pintarTicket();
  };
  window.ventaOfflineCant = function (i, d) { ticket[i].cantidad += d; if (ticket[i].cantidad <= 0) ticket.splice(i, 1); pintarTicket(); };
  window.ventaOfflineNota = function (i) { const n = prompt('Nota para cocina/barra (ej. sin cebolla, leche de avena):', ticket[i].nota || ''); if (n !== null) { ticket[i].nota = n.trim().slice(0, 100); pintarTicket(); } };

  const totalTicket = () => Math.round(ticket.reduce((a, x) => a + x.precio * x.cantidad, 0) * 100) / 100;
  function pintarTicket() {
    $('vo_ticket').innerHTML = ticket.map((x, i) => `<div style="display:grid;grid-template-columns:1fr auto;gap:4px;padding:6px;border-bottom:1px solid #f1f5f9;">
      <div><b style="font-size:13px;">${esc(x.nombre)}</b>${x.nota ? `<div style="font-size:11.5px;color:#c98246;">› ${esc(x.nota)}</div>` : ''}
        <div style="font-size:11.5px;color:#64748b;">${dinero(x.precio)} c/u · ${x.area === 'BARRA' ? '☕ Barra' : '🍳 Cocina'}</div></div>
      <div style="display:flex;gap:4px;align-items:center;">
        <button type="button" onclick="ventaOfflineNota(${i})" title="Nota" style="width:32px;height:32px;border-radius:7px;border:1px solid #cbd5e1;background:#fff;cursor:pointer;">✎</button>
        <button type="button" onclick="ventaOfflineCant(${i},-1)" style="width:32px;height:32px;border-radius:7px;border:1px solid #cbd5e1;background:#fff;font-weight:900;cursor:pointer;">−</button>
        <b style="min-width:22px;text-align:center;">${x.cantidad}</b>
        <button type="button" onclick="ventaOfflineCant(${i},1)" style="width:32px;height:32px;border-radius:7px;border:1px solid #cbd5e1;background:#fff;font-weight:900;cursor:pointer;">+</button>
        <b style="min-width:70px;text-align:right;">${dinero(x.precio * x.cantidad)}</b></div></div>`).join('')
      || '<p style="color:#64748b;text-align:center;margin-top:30px;">Toca los platillos de la izquierda.</p>';
    $('vo_total').innerText = dinero(totalTicket());
    window.ventaOfflineCambio();
  }

  window.ventaOfflineForma = function (f) {
    formaPago = f;
    document.querySelectorAll('#vo_formas button').forEach(b => { const on = b.dataset.f === f; b.style.background = on ? '#13423b' : '#f8fafc'; b.style.color = on ? '#fff' : '#0b2924'; });
    $('vo_ef').style.display = f === 'EF' ? 'flex' : 'none';
  };
  window.ventaOfflineCambio = function () {
    const r = parseFloat($('vo_recibe').value || 0), t = totalTicket();
    $('vo_cambio').innerText = r > 0 ? (r >= t ? 'Cambio ' + dinero(r - t) : 'Falta ' + dinero(t - r)) : '';
  };

  function horaLocalISO(d) {
    const z = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}T${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`;
  }

  window.ventaOfflineCobrar = function () {
    if (!ticket.length) return alert('Agrega al menos un platillo.');
    const total = totalTicket();
    let recibe = total;
    if (formaPago === 'EF') {
      recibe = parseFloat($('vo_recibe').value || 0) || total;
      if (recibe + 0.009 < total) return alert('El efectivo no alcanza para el total.');
    }
    const pago = { EF: 0, TARJD: 0, TARJC: 0, TRANS: 0 };
    if (formaPago === 'EF') pago.EF = recibe; else if (formaPago === 'TARJ') pago.TARJD = total; else pago.TRANS = total;
    const ahora = new Date();
    const idem = ((window.crypto && crypto.randomUUID) ? crypto.randomUUID() : (Date.now().toString(36) + Math.random().toString(36).slice(2))).replace(/[^A-Za-z0-9_-]/g, '');
    const mesa = ($('vo_mesa').value || 'SIN INTERNET').trim().slice(0, 30);
    const venta = { idem, creada_en: horaLocalISO(ahora), mesa, mesero: usuario(), pago, propina: 0,
      items: ticket.map(x => ({ producto_id: x.producto_id, nombre: x.nombre, precio: x.precio, cantidad: x.cantidad, nota: x.nota })) };
    const cola = leer(K_COLA); cola.push(venta); guardar(K_COLA, cola);   // primero se guarda; luego se imprime

    // Comandas por área (cada una en su hoja) + nota de consumo
    const hora = ahora.toLocaleString('es-MX');
    const comandas = ['COCINA', 'BARRA'].map(area => {
      const its = ticket.filter(x => x.area === area);
      if (!its.length) return '';
      return `<div class="tk-hoja"><div class="ticket-termico"><div class="tk-tag">Sin internet</div><div class="tk-titulo">${area}</div>
        <div class="tk-mesa">${esc(mesa)}</div><div class="tk-meta"><div class="tk-fila"><span>Cajero ${esc(usuario())}</span><span>${hora}</span></div></div>
        <div class="tk-sep"></div><table class="tk-items">${its.map(x => `<tr><td class="tk-cant">${x.cantidad}</td><td class="tk-desc">${esc(x.nombre)}</td></tr>` +
          (x.nota ? `<tr class="tk-mod"><td></td><td class="tk-desc">› ${esc(x.nota.toUpperCase())}</td></tr>` : '')).join('')}</table><div class="tk-sep"></div></div></div>`;
    }).join('');
    const sub = Math.round(total / 1.16 * 100) / 100;
    const cNota = { mesero: usuario(), mesa, orden: 'SIN INTERNET', personas: 1, subtotal: sub.toFixed(2),
      descuento_monto: '0', iva: (total - sub).toFixed(2), total: total.toFixed(2), total_letras: '' };
    const nota = window.construirHTMLNotaFinal
      ? window.construirHTMLNotaFinal(cNota, 'PENDIENTE (sin internet)', { EF: pago.EF, TARJD: pago.TARJD, TARJC: 0, TRANS: pago.TRANS, VALE: 0, CRED: 0, PROP: 0 }, Math.max(0, recibe - total), '')
      : '';
    if (window.mandarImprimirHTMLDirecto) mandarImprimirHTMLDirecto(comandas + `<div class="tk-hoja">${nota}</div>`);
    if (formaPago === 'EF' && recibe > total) alert('Cambio: ' + dinero(recibe - total));
    ticket = [];
    $('modalVentaOffline').style.display = 'none';
    pintarBarra();
    subirPendientes();
  };

  document.addEventListener('DOMContentLoaded', () => { pintarBarra(); subirPendientes(); });
})();
