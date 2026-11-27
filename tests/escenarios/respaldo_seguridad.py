# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, H, check, db, login).
# Respaldo completo (descargar y restaurar), cerrar sesión a distancia y encabezados de seguridad.
import io as _io
import os as _os
import tempfile as _tf
import zipfile as _zf
import json as _js

_T = {'X-CSRFToken': H['X-CSRFToken']}

# ---------- respaldo ----------
check(clientes['brayan'].post('/api/respaldo/descargar', headers={'X-CSRFToken': token_de(clientes['brayan'].get('/pos').get_data(as_text=True))}).status_code == 403,
      'la caja no puede descargar el respaldo')
r = admin.post('/api/respaldo/descargar', headers=_T)
check(r.status_code == 200 and r.mimetype == 'application/zip', f'descargar respaldo completo ({r.status_code})')
_zip = _zf.ZipFile(_io.BytesIO(r.data))
_man = _js.loads(_zip.read('manifiesto.json'))
with app.app_context():
    from models import CuentaPOS as _CtaR, DetallePOS as _DetR, User as _UsR, Producto as _ProdR
    _cuentas, _detalles, _usuarios, _prods = _CtaR.query.count(), _DetR.query.count(), _UsR.query.count(), _ProdR.query.count()
check(_man['tablas'].get('cuentas_pos') == _cuentas and _man['tablas'].get('detalles_pos') == _detalles and _cuentas > 0,
      f'el respaldo trae todas las ventas ({_man["tablas"].get("cuentas_pos")} de {_cuentas})')
check('cola_impresion_pos' not in _man['tablas'], 'no respalda la cola de impresión (temporal)')
est = admin.get('/api/respaldo/estado').json
check(est['ok'] and est['estado'].get('ultimo'), 'queda registrado cuándo fue el último respaldo')

# restaurar en una base nueva y vacía: mismos conteos
_tmpdir = _tf.mkdtemp()
_zp = _os.path.join(_tmpdir, 'r.zip')
open(_zp, 'wb').write(r.data)
from flask import Flask as _Fl
from flask_sqlalchemy import SQLAlchemy as _SA  # noqa: F401  (se usa la misma db de models)
import models as _mods
_app2 = _Fl('restaurar_prueba')
_app2.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + _os.path.join(_tmpdir, 'nueva.db').replace(_os.sep, '/')
_app2.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
_mods.db.init_app(_app2)
from restaurar_respaldo import restaurar as _restaurar
_restaurar(_zp, _app2, _mods.db, salida=lambda *_a: None)
with _app2.app_context():
    _ok = (_CtaR.query.count() == _cuentas and _DetR.query.count() == _detalles and _UsR.query.count() == _usuarios
           and _ProdR.query.count() == _prods)
    _c1 = _CtaR.query.order_by(_CtaR.id.asc()).first()
    _fecha_ok = _c1 is not None and _c1.apertura is not None and hasattr(_c1.apertura, 'year')
check(_ok and _fecha_ok, 'restaurar el respaldo en una base vacía recupera ventas, productos y usuarios con sus fechas')
try:
    _restaurar(_zp, _app2, _mods.db, salida=lambda *_a: None)
    check(False, 'restaurar sobre una base con ventas se detiene')
except SystemExit:
    check(True, 'restaurar sobre una base con ventas se detiene (no mezcla información)')

# respaldo automático del día: solo uno aunque cierren varias cajas
from respaldo import respaldo_diario as _rd
with app.app_context():
    from models import ConfigPOS as _CfgR, ahora_local as _ahR
    _hoy = _ahR().date().isoformat()
_h1 = _rd(app)
_h2 = _rd(app)
_h1.join(30)
_h2.join(30)
with app.app_context():
    check(_CfgR.query.get(f'respaldo_auto_{_hoy}') is not None, 'el respaldo automático del día queda marcado (uno por día)')

# ---------- cerrar sesión a distancia ----------
with app.app_context():
    _pid = _UsR.query.filter_by(username='paola').first().id
_tab = login('paola', 'mesero12345')
check(_tab.get('/mesero_dashboard').status_code == 200, 'la tablet de la mesera está dentro')
r = admin.post(f'/admin/usuario/cerrar_sesiones/{_pid}', data={'csrf_token': H['X-CSRFToken']})
check(r.status_code == 302, 'admin cierra la sesión de la mesera en todos lados')
r = _tab.get('/mesero_dashboard')
check(r.status_code == 302 and '/admin_login' in r.headers.get('Location', ''), 'la tablet perdida queda fuera de inmediato')
check(login('paola', 'mesero12345').get('/mesero_dashboard').status_code == 200, 'la mesera vuelve a entrar con su contraseña')
r = admin.post(f'/admin/usuario/cerrar_sesiones/{_pid}', data={})
check(r.status_code == 400, 'cerrar sesiones sin token es rechazado')
with app.app_context():
    _rid = _UsR.query.filter_by(username='raquel').first().id
r = admin.post(f'/admin/usuario/cerrar_sesiones/{_rid}', data={'csrf_token': H['X-CSRFToken']})
check(admin.get('/admin_dashboard').status_code == 200, 'si el admin cierra sus propias sesiones, sigue dentro en este aparato')

# ---------- encabezados ----------
r = admin.get('/admin_dashboard')
check(r.headers.get('X-Frame-Options') == 'SAMEORIGIN' and r.headers.get('X-Content-Type-Options') == 'nosniff'
      and 'Referrer-Policy' in r.headers, 'encabezados de seguridad en las páginas')
check('id="tabbtn-respaldo"' in r.get_data(as_text=True), 'Administración tiene la pestaña de Respaldo')
