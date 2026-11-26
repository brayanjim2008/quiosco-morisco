"""Escenario completo de humo: arranca la app con una base temporal y recorre pantallas, CSRF, cobro,
pre-órdenes por sucursal, cola de impresión, límite de intentos, caché, costo promedio y conteo físico.

Uso:  python tests/escenario_humo.py            (SQLite temporal)
      PRUEBAS_DATABASE_URL=postgresql://... python tests/escenario_humo.py   (PostgreSQL VACÍO de pruebas)
Sale con código 1 si alguna comprobación falla. Lo ejecuta tests/test_humo.py (pytest).
"""
import os, re, sys, tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PROYECTO = os.path.dirname(AQUI)
_url_pruebas = os.environ.get('PRUEBAS_DATABASE_URL', '').strip()
if _url_pruebas:
    os.environ['DATABASE_URL'] = _url_pruebas
else:
    db_path = os.path.join(tempfile.mkdtemp(), 'prueba.db')
    os.environ['DATABASE_URL'] = 'sqlite:///' + db_path.replace(os.sep, '/')
os.environ['SECRET_KEY'] = 'prueba-local'
os.environ['RUN_DB_INIT'] = '1'
os.environ['PASS_INICIAL_RAQUEL'] = 'admin12345'
os.environ['PASS_INICIAL_BRAYAN'] = 'cajero12345'
os.environ['PASS_INICIAL_PAOLA'] = 'mesero12345'
os.environ['PASS_INICIAL_DANIEL'] = 'mesero12345'
os.environ['PASS_INICIAL_ALMACEN'] = 'almacen12345'
os.environ['PASS_INICIAL_QUIOSCO'] = 'sucursal12345'
os.environ['PASS_INICIAL_GERENTE'] = 'gerente12345'
os.environ['PASS_INICIAL_CAMINANTE1'] = 'caminante12345'


def ejecutar_escenario(nombre):
    """Las partes comparten variables con este script (clientes, tokens, ids)."""
    ruta = os.path.join(AQUI, 'escenarios', nombre)
    exec(compile(open(ruta, encoding='utf-8').read(), ruta, 'exec'), globals())


sys.path.insert(0, PROYECTO)
os.chdir(PROYECTO)

import app as appmod
from models import db, Producto, CuentaPOS, DetallePOS, PreOrden, CategoriaMenu
app = appmod.app
app.config['TESTING'] = False

fallos = []
def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        fallos.append(msg)

def token_de(html):
    m = re.search(r'name="csrf-token" content="([^"]+)"', html)
    return m.group(1) if m else None

with app.app_context():
    db.session.add(CategoriaMenu(nombre='Bebidas Calientes', nombre_en='Hot'))
    db.session.add(Producto(nombre='Latte', precio=65.0, categoria='Bebidas Calientes', descripcion=''))
    db.session.commit()

# ---------- Público ----------
pub = app.test_client()
r = pub.get('/')
check(r.status_code == 200 and token_de(r.get_data(as_text=True)), 'index carga e incluye token CSRF')
r = pub.post('/crear_preorden', json={'mesa': '5', 'cliente_nombre': '<img src=x onerror=alert(1)>Ana',
                                      'detalle_items': '1x Latte', 'total': 65, 'notas': '"><svg onload=x>sin azucar'})
check(r.status_code == 200 and r.json.get('ok'), 'pre-orden pública funciona sin token (anónimo)')
with app.app_context():
    po = PreOrden.query.order_by(PreOrden.id.desc()).first()
    check('<' not in po.cliente_nombre and '"' not in po.notas and '>' not in po.notas,
          f'pre-orden guardada sin caracteres HTML: {po.cliente_nombre!r} / {po.notas!r}')
    preorden_id = po.id
r = pub.get('/admin_login')
check(r.status_code == 200 and token_de(r.get_data(as_text=True)), 'login carga con token')

# ---------- Pantallas por rol ----------
def login(usuario, clave):
    c = app.test_client()
    c.get('/admin_login')
    r = c.post('/admin_login', data={'username': usuario, 'password': clave})
    check(r.status_code == 302, f'login {usuario}')
    return c

pantallas = {
    ('raquel', 'admin12345'): ['/admin_dashboard', '/industrial', '/pos', '/nomina_creditos', '/almacen_pro',
                               '/mesero_dashboard', '/pedidos_sucursal', '/admin/producto/editar/1'],
    ('brayan', 'cajero12345'): ['/cajero_dashboard', '/pos'],
    ('paola', 'mesero12345'): ['/mesero_dashboard', '/pos'],
    ('almacen', 'almacen12345'): ['/almacen_pro'],
    ('quiosco', 'sucursal12345'): ['/pedidos_sucursal', '/pos'],
}
clientes = {}
for (u, p), rutas in pantallas.items():
    c = login(u, p)
    clientes[u] = c
    for ruta in rutas:
        r = c.get(ruta, follow_redirects=True)
        html = r.get_data(as_text=True)
        check(r.status_code == 200 and token_de(html) is not None, f'{u} abre {ruta} ({r.status_code})')

admin = clientes['raquel']
tok = token_de(admin.get('/pos').get_data(as_text=True))

# ---------- CSRF ----------
r = admin.post('/api/pos/abrir_mesa', json={'mesa': 'M1'})
check(r.status_code == 400 and r.json and not r.json.get('ok'), 'POST sin token es rechazado (400 JSON)')
r = admin.post('/api/pos/abrir_mesa', json={'mesa': 'M1'}, headers={'X-CSRFToken': 'falso'})
check(r.status_code == 400, 'POST con token falso es rechazado')
r = admin.post('/admin/categoria/nueva', data={'nombre': 'X'})
check(r.status_code == 400, 'formulario sin token es rechazado')
r = admin.post('/admin/categoria/nueva', data={'nombre': 'Postres', 'csrf_token': tok})
check(r.status_code == 302, 'formulario con token es aceptado')
H = {'X-CSRFToken': tok}

# ---------- Turno: como en Soft, sin turno abierto no se opera ----------
r = admin.post('/api/pos/abrir_mesa', json={'mesa': 'M0', 'personas': 2}, headers=H)
check(r.status_code == 409 and r.json.get('turno_cerrado'), 'sin turno abierto no se puede abrir mesa')
check(admin.get('/api/pos/corte_caja').status_code == 409, 'sin turno el corte X avisa (no crea un turno solo)')
r = admin.post('/api/pos/abrir_turno_real', json={'fondo_inicial': 500}, headers=H)
check(r.status_code == 200 and r.json['fondo'] == '500.00', 'abrir turno con fondo inicial')


def abrir_turnos():
    """Abre turno en todas las sucursales (para los escenarios que operan en varias)."""
    from models import TurnoPOS as _T, SUCURSALES_OFICIALES as _SO, ahora_local as _ahl
    with app.app_context():
        for _s in _SO:
            if not _T.query.filter_by(sucursal=_s, estado='ABIERTO').first():
                db.session.add(_T(sucursal=_s, cajero='PRUEBA', fondo_inicial=0.0, estado='ABIERTO', apertura=_ahl()))
        db.session.commit()


def imprimir_cuenta(cliente, cid, headers):
    """Precuenta: requisito para cobrar (como en Soft)."""
    return cliente.post(f'/api/pos/pin_inteligente/{cid}', json={}, headers=headers)


abrir_turnos()

# ---------- Flujo POS ----------
r = admin.post('/api/pos/abrir_mesa', json={'mesa': 'M1', 'personas': 2}, headers=H)
check(r.status_code == 200 and r.json.get('ok'), f'abrir mesa con token ({r.status_code} {r.get_data(as_text=True)[:150]})')
with app.app_context():
    cta = CuentaPOS.query.filter_by(mesa='M1', estado='ABIERTA').first()
    cuenta_id = cta.id if cta else None
check(cuenta_id is not None, 'cuenta creada')

def capturar(cid):
    r = admin.post('/api/pos/capturar_item', json={'cuenta_id': cid, 'descripcion': 'LATTE', 'precio': 65,
                                                   'cantidad': 1, 'clave': '00001'}, headers=H)
    return r
r = capturar(cuenta_id)
check(r.status_code == 200, f'capturar platillo ({r.status_code} {r.get_data(as_text=True)[:200]})')
with app.app_context():
    total = CuentaPOS.query.get(cuenta_id).total
check(total and total > 0, f'total de la cuenta = {total}')

# Sin imprimir la cuenta no se cobra
r = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': cuenta_id, 'efectivo': 200}, headers=H)
check(r.status_code == 409 and r.json.get('requiere_imprimir'), 'no se cobra sin imprimir la cuenta primero')
r = admin.post('/api/pos/abrir_mesa', json={'mesa': 'MV', 'personas': 1}, headers=H)
check(imprimir_cuenta(admin, r.json['cuenta_id'], H).status_code == 400, 'una cuenta vacía no se imprime')
r = imprimir_cuenta(admin, cuenta_id, H)
with app.app_context():
    _pend = DetallePOS.query.filter_by(cuenta_id=cuenta_id, impreso_comanda=False).count()
check(r.status_code == 200 and _pend == 0, 'al imprimir la cuenta se mandan a cocina/barra los productos pendientes')
r = admin.post('/api/pos/capturar_item', json={'cuenta_id': cuenta_id, 'descripcion': 'X', 'precio': 1, 'cantidad': 1}, headers=H)
check(r.status_code == 400, 'cuenta impresa ya no acepta productos')
# Tarjeta que excede el total -> rechazado
r = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': cuenta_id, 'tarjeta_debito': total + 400}, headers=H)
check(r.status_code == 400, 'tarjeta mayor al total es rechazada (no hay cambio en efectivo de un pago con tarjeta)')
# Efectivo con cambio -> OK
r = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': cuenta_id, 'efectivo': 200}, headers=H)
check(r.status_code == 200 and abs(r.json.get('cambio', -1) - (200 - total)) < 0.01, f'pago en efectivo con cambio correcto ({r.get_data(as_text=True)[:120]})')
r = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': cuenta_id, 'efectivo': 200}, headers=H)
check(r.status_code == 400, 'no se puede cobrar dos veces la misma cuenta')

# Mixto: efectivo + tarjeta
r = admin.post('/api/pos/abrir_mesa', json={'mesa': 'M2', 'personas': 1}, headers=H)
with app.app_context():
    c2 = CuentaPOS.query.filter_by(mesa='M2', estado='ABIERTA').first().id
capturar(c2)
imprimir_cuenta(admin, c2, H)
r = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': c2, 'efectivo': 20, 'tarjeta_debito': 50}, headers=H)
check(r.status_code == 200 and abs(r.json.get('cambio') - 5.0) < 0.01, f'pago mixto 20 EF + 50 TD sobre 65: cambio 5 ({r.get_data(as_text=True)[:120]})')

# Cambiar forma de pago con tarjeta excedida -> rechazado
r = admin.post('/api/pos/cambiar_forma_pago', json={'cuenta_id': c2, 'tarjeta_debito': 500}, headers=H)
check(r.status_code == 403 and r.json.get('requiere_admin'), 'cambiar forma de pago sin clave pide autorización')
r = admin.post('/api/pos/cambiar_forma_pago', json={'cuenta_id': c2, 'tarjeta_debito': 500, 'clave_admin': 'admin12345'}, headers=H)
check(r.status_code == 400, f'con clave, tarjeta > total es rechazado ({r.status_code} {r.get_data(as_text=True)[:120]})')
r = admin.post('/api/pos/cambiar_forma_pago', json={'cuenta_id': c2, 'efectivo': 100, 'clave_admin': 'admin12345'}, headers=H)
check(r.status_code == 200, 'con clave, cambiar a efectivo 100 funciona')
r = admin.get('/api/pos/cuentas_pagadas_turno')
c2row = [x for x in r.json['cuentas'] if x['id'] == c2][0]
check(abs(c2row['efectivo'] - 100) < 0.01, 'forma de pago actualizada')

r = admin.get('/api/pos/corte_caja')
check(r.status_code == 200 and 'efectivo' in r.json, f'corte de caja responde (efectivo={r.json.get("efectivo")})')

# Pre-orden confirmada en el POS
r = admin.post(f'/api/pos/confirmar_preorden_1clic/{preorden_id}', json={}, headers=H)
check(r.status_code == 200, f'confirmar pre-orden pública en POS ({r.status_code} {r.get_data(as_text=True)[:150]})')

# Cajero: generar PIN con cantidad inválida ya no truena
cj = clientes['brayan']
tcj = token_de(cj.get('/cajero_dashboard').get_data(as_text=True))
r = cj.post('/caja/generar_pin', data={'cantidad': 'abc', 'csrf_token': tcj})
check(r.status_code == 302, 'generar PIN con cantidad inválida no truena')

# Fidelidad con PIN
with app.app_context():
    from models import PinCaja
    pin = PinCaja.query.filter_by(activo=True).first().codigo
check(len(pin) == 4 and pin.isdigit(), f'PIN generado: {pin}')
r = pub.post('/registrar_consumo', data={'nombre': 'Luis <b>', 'telefono': '9671234567', 'pin': pin})
check(r.status_code == 200, 'registrar consumo con PIN')

# Punto 5: platillo con apóstrofo en pre-orden -> precio y nombre del catálogo
with app.app_context():
    db.session.add(Producto(nombre="Cafe D'Olla", precio=50.0, categoria='Bebidas Calientes', descripcion=''))
    db.session.commit()
r = pub.post('/crear_preorden', json={'mesa': '9', 'cliente_nombre': 'Eva', 'detalle_items': "2x Cafe D'Olla ($2)", 'total': 2})
po9 = r.json.get('folio')
r = admin.post(f'/api/pos/confirmar_preorden_1clic/{po9}', json={}, headers=H)
with app.app_context():
    det = DetallePOS.query.filter(DetallePOS.descripcion.like('CAFE D%')).order_by(DetallePOS.id.desc()).first()
check(det is not None and det.precio_unitario == 50.0 and det.descripcion == "CAFE D'OLLA" and det.importe == 100.0,
      f"pre-orden con apostrofo usa precio/nombre del catalogo: {det and (det.descripcion, det.precio_unitario, det.importe)}")

# Punto 1: tolerancia de centavo por redondeo
r = admin.post('/api/pos/abrir_mesa', json={'mesa': 'M7'}, headers=H)
with app.app_context():
    c7 = CuentaPOS.query.filter_by(mesa='M7', estado='ABIERTA').first().id
capturar(c7)
imprimir_cuenta(admin, c7, H)
r = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': c7, 'tarjeta_debito': 65.005}, headers=H)
check(r.status_code == 200, f'tarjeta = total + medio centavo se acepta ({r.status_code})')

# Casos de Prioridad 1 (sucursales, QR local, CSRF multipart)
ejecutar_escenario('p1.py')

# Logout y ping
r = admin.get('/ping')
check(r.status_code == 200, 'ping')
# Casos de A1 (cola de impresión) + B3 (ESQUEMA_REQUERIDO)
ejecutar_escenario('a1.py')

# Casos de A2 (límite de intentos y caché compartidos)
ejecutar_escenario('a2.py')

# Casos de B2 (costo promedio y margen por platillo)
ejecutar_escenario('b2.py')

# Casos de B1 (conteo físico)
ejecutar_escenario('b1.py')

# Fase 2: descuento en pesos, idempotencia del cobro, datos de ticket editables, CSV de créditos
ejecutar_escenario('f2.py')

# Fase 3: traspasos entre sucursales, catálogo de gastos, arqueo por denominaciones
ejecutar_escenario('f3.py')

# Fase 4a: monitor de cocina/barra (KDS) y reservaciones
ejecutar_escenario('f4a.py')

# Fase 4b: presentaciones de compra, sub-recetas con producción, órdenes de compra
ejecutar_escenario('f4b.py')

# Meseros: cada uno solo ve y opera sus cuentas
ejecutar_escenario('meseros.py')

# Como Soft: cancelación con aviso a cocina, corte X/Z con desglose completo
ejecutar_escenario('soft.py')

# Auxiliar de nómina: descuentos, aguinaldo, bonos, permisos, vacaciones, catálogos y bajas
ejecutar_escenario('nomina.py')

# ================= A3: /logout por POST + XSS en onclick =================
for _ruta in ('/nomina_creditos', '/almacen_pro', '/pedidos_sucursal', '/mesero_dashboard', '/pos', '/industrial'):
    _html = admin.get(_ruta).get_data(as_text=True)
    check(".replace(/'/g, '')}')" not in _html and "'${codSafe}'" not in _html, f'{_ruta}: sin nombres entre comillas en onclick')
html_ind = admin.get('/industrial').get_data(as_text=True)
check('chart.js@4.4.1/dist/chart.umd.js' in html_ind, 'Chart.js con versión fija')
r = admin.get('/logout')
check(r.status_code == 200 and 'Cerrar sesión' in r.get_data(as_text=True), 'GET /logout solo muestra confirmación')
check(admin.get('/admin_dashboard').status_code == 200, 'GET /logout NO cierra la sesión')
check(admin.post('/logout').status_code == 400, 'POST /logout sin token es rechazado (CSRF)')
check(admin.get('/admin_dashboard').status_code == 200, 'la sesión sigue tras POST sin token')
r = admin.post('/logout', data={'csrf_token': tok})
check(r.status_code == 302, 'POST /logout con token cierra sesión')
r = admin.get('/admin_dashboard')
check(r.status_code == 302 and '/admin_login' in r.headers.get('Location', ''), 'después del logout pide login')
check(app.test_client().get('/logout').status_code == 302, 'GET /logout sin sesión redirige al login')
r = clientes['brayan'].get('/logout')
check('csrf-token' in r.get_data(as_text=True), 'página de confirmación incluye token')

print('\nRESULTADO:', 'TODO OK' if not fallos else f'{len(fallos)} FALLOS')
for f in fallos:
    print('  -', f)

sys.exit(1 if fallos else 0)
