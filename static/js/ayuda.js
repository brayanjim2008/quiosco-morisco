/* Botón "?" de ayuda: cada pantalla define window.AYUDA = { titulo, secciones: [{ t, pasos: [...] }] }
   y aquí se agrega el botón junto a la barra de módulos (o flotando si no hay barra). */
(function () {
  if (window.__ayudaLista) return;   // la barra de módulos puede incluirse dos veces en una página
  window.__ayudaLista = true;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]; }); }

  function abrir() {
    var a = window.AYUDA || {};
    var cuerpo = (a.secciones || []).map(function (s) {
      return '<div class="ay-sec"><h4>' + esc(s.t) + '</h4><ol>' +
        (s.pasos || []).map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') + '</ol></div>';
    }).join('');
    var m = document.getElementById('ayudaModal');
    if (!m) {
      m = document.createElement('div');
      m.id = 'ayudaModal';
      m.className = 'ay-fondo';
      m.addEventListener('click', function (e) { if (e.target === m) m.style.display = 'none'; });
      document.body.appendChild(m);
    }
    m.innerHTML = '<div class="ay-caja"><div class="ay-head"><span><i class="fa-solid fa-circle-question"></i> ' +
      esc(a.titulo || 'Cómo se usa esta pantalla') + '</span><button type="button" class="ay-x" aria-label="Cerrar">&times;</button></div>' +
      '<div class="ay-body">' + cuerpo + '</div></div>';
    m.querySelector('.ay-x').onclick = function () { m.style.display = 'none'; };
    m.style.display = 'flex';
  }
  window.abrirAyuda = abrir;

  document.addEventListener('DOMContentLoaded', function () {
    if (!window.AYUDA) return;
    function boton() {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'mod-btn ay-btn';
      b.title = 'Ayuda: cómo se usa esta pantalla (F1)';
      b.innerHTML = '<i class="fa-solid fa-circle-question"></i><span>Ayuda</span>';
      b.onclick = abrir;
      return b;
    }
    // La Caja tiene una barra en Inicio y otra en Mesas; si una barra está DENTRO de otra (Administración), solo la de afuera.
    var barras = Array.prototype.filter.call(document.querySelectorAll('.mod-bar'), function (b) {
      return !(b.parentElement && b.parentElement.closest('.mod-bar'));
    });
    if (barras.length) barras.forEach(function (bar) { bar.insertBefore(boton(), bar.firstChild); });
    else { var b = boton(); b.classList.add('ay-flotante'); document.body.appendChild(b); }
    document.addEventListener('keydown', function (e) { if (e.key === 'F1') { e.preventDefault(); abrir(); } });
  });
})();
