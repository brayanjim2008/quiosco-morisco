# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, H, check, db).
from datetime import timedelta as _td
from sqlalchemy import text as _t
import models as _m
from models import (limite_intentos_excedido, registrar_intento_fallido, limpiar_intentos, LimiteIntento,
                    cache_get, cache_set, invalidar_cache_publico, CategoriaMenu, Evaluacion, esquema_faltante)

def _conteo(clave):
    with app.app_context():
        f = LimiteIntento.query.get(clave)
        return f.conteo if f else None

# ---------- Bloqueo por intentos (login real) ----------
cli = app.test_client()
cli.get('/admin_login')
for _ in range(8):
    cli.post('/admin_login', data={'username': 'almacen', 'password': 'mala'})
check(_conteo('login:almacen') == 8, 'los 8 intentos fallidos quedan en limites_intentos')
r = cli.post('/admin_login', data={'username': 'almacen', 'password': 'almacen12345'})
check(r.status_code == 200 and 'Demasiados intentos' in r.get_data(as_text=True), 'tras 8 fallos, hasta la clave correcta queda bloqueada')
with app.app_context():
    limpiar_intentos('login:almacen')
check(_conteo('login:almacen') is None, 'limpiar_intentos borra la clave')
r = cli.post('/admin_login', data={'username': 'almacen', 'password': 'almacen12345'})
check(r.status_code == 302, 'después de limpiar, el login correcto entra')

# ---------- Ventana y reinicio ----------
with app.app_context():
    for _ in range(5):
        registrar_intento_fallido('prueba:ventana', ventana_seg=300)
    check(limite_intentos_excedido('prueba:ventana', 5, 300), '5 intentos en la ventana -> bloqueado')
    check(not limite_intentos_excedido('prueba:ventana', 6, 300), 'por debajo del máximo -> pasa')
    f = LimiteIntento.query.get('prueba:ventana'); f.ventana_inicio = _m.ahora_local() - _td(seconds=301); db.session.commit()
    check(not limite_intentos_excedido('prueba:ventana', 5, 300), 'ventana vencida -> ya no bloquea')
    registrar_intento_fallido('prueba:ventana', ventana_seg=300)
check(_conteo('prueba:ventana') == 1, 'al registrar con ventana vencida el conteo reinicia en 1')

# ---------- Rollback de la ruta NO borra el intento (conexión independiente) ----------
with app.app_context():
    db.session.add(CategoriaMenu(nombre='NO_DEBE_GUARDARSE', nombre_en=''))
    registrar_intento_fallido('prueba:rollback')
    db.session.rollback()
    check(LimiteIntento.query.get('prueba:rollback') is not None and LimiteIntento.query.get('prueba:rollback').conteo == 1,
          'db.session.rollback() de la ruta no borra el intento registrado')
    check(CategoriaMenu.query.filter_by(nombre='NO_DEBE_GUARDARSE').first() is None,
          'registrar un intento no hace commit de la transacción de la ruta')

# ---------- Límite público (evaluaciones: 20 cada 600 s por IP) ----------
pub2 = app.test_client()
with app.app_context():
    antes = Evaluacion.query.count()
for _ in range(21):
    pub2.post('/enviar_evaluacion', data={'mesero_nombre': 'Paola', 'mesero_calificacion': '5', 'limpieza': '5', 'calidad_comida': '5'})
with app.app_context():
    check(Evaluacion.query.count() - antes == 20, 'evaluaciones: la #21 en la ventana se bloquea')

# ---------- Falla abierta si la tabla no responde ----------
with app.app_context():
    with db.engine.begin() as conn:
        conn.execute(_t('ALTER TABLE limites_intentos RENAME TO limites_intentos_tmp'))
    try:
        ok1 = limite_intentos_excedido('prueba:caida', 1, 300) is False
        registrar_intento_fallido('prueba:caida')   # no debe lanzar excepción
        limpiar_intentos('prueba:caida')
        ok2 = True
    except Exception:
        ok2 = False
    r = app.test_client().post('/crear_preorden', json={'mesa': '1', 'cliente_nombre': 'X', 'detalle_items': '1x Latte ($65)', 'total': 65})
    ok3 = r.status_code == 200
    with db.engine.begin() as conn:
        conn.execute(_t('ALTER TABLE limites_intentos_tmp RENAME TO limites_intentos'))
check(ok1 and ok2 and ok3, 'si la tabla falla, se deja pasar (falla abierta) y el menú público sigue funcionando')

# ---------- Caché compartida entre workers ----------
with app.app_context():
    cache_set('menu_publico', {'marca': 'vieja'})
    _m._CACHE_VERSION['revisado'] = 0.0
    check(cache_get('menu_publico', 45) == {'marca': 'vieja'}, 'caché local se sirve si la versión no cambió')
    v0 = _m._leer_version_cache()
    with db.engine.begin() as conn:   # simula que OTRO worker invalidó
        conn.execute(_t("UPDATE config_pos SET valor_json = CAST(CAST(valor_json AS INTEGER) + 1 AS VARCHAR(20)) WHERE clave = :c"),
                     {'c': _m.CLAVE_VERSION_CACHE})
    check(cache_get('menu_publico', 45) == {'marca': 'vieja'}, 'dentro de los 3 s no se consulta la versión (sigue la caché)')
    _m._CACHE_VERSION['revisado'] = 0.0   # simula que pasaron 3 s
    check(cache_get('menu_publico', 45) is None, 'al cambiar version_cache_publico se vacía la caché local')
    v1 = _m._leer_version_cache()
    check(int(v1) == int(v0) + 1, f'versión compartida avanzó ({v0} -> {v1})')
    cache_set('menu_publico', {'marca': 'x'})
    invalidar_cache_publico()
    check(int(_m._leer_version_cache()) == int(v1) + 1 and cache_get('menu_publico', 45) is None,
          'invalidar_cache_publico sube la versión compartida y vacía la local')

# ---------- Agotado visible por la API pública tras invalidar ----------
with app.app_context():
    _p = Producto.query.filter_by(nombre='Latte').first(); _pid = _p.id
pub3 = app.test_client()
antes_ag = _pid in pub3.get('/api/estado_menu_publico').json['agotados_ids']
r = admin.post(f'/admin/producto/toggle_agotado/{_pid}', headers=dict(H, **{'X-Requested-With': 'XMLHttpRequest'}))
despues_ag = _pid in pub3.get('/api/estado_menu_publico').json['agotados_ids']
check(r.status_code == 200 and antes_ag != despues_ag, 'marcar agotado se refleja de inmediato en el menú público')
admin.post(f'/admin/producto/toggle_agotado/{_pid}', headers=dict(H, **{'X-Requested-With': 'XMLHttpRequest'}))

with app.app_context():
    check('limites_intentos' in _m.ESQUEMA_REQUERIDO and esquema_faltante(db.engine) == [], 'limites_intentos en ESQUEMA_REQUERIDO y creada')
