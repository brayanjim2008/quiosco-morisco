# Se ejecuta dentro de tests/escenario_humo.py (usa app, pub, admin, clientes, H, tok, tcj, login, check, token_de).
from io import BytesIO as _B
from models import PinCaja, EmpleadoNominaPOS, RegistroAsistencia, ConsumoEmpleadoPOS, ReciboNominaPOS

# ================= QR local =================
r = pub.get('/qr.svg?data=hola')
check(r.status_code == 200 and r.data.lstrip().startswith(b'<svg') and r.headers['Content-Type'].startswith('image/svg+xml')
      and r.headers.get('X-Content-Type-Options') == 'nosniff' and 'max-age=86400' in r.headers.get('Cache-Control', ''),
      'qr.svg genera SVG con cabeceras correctas')
check(pub.get('/qr.svg?data=' + 'x' * 301).status_code == 400, 'qr.svg rechaza más de 300 caracteres')
check(pub.get('/qr.svg?data=' + 'x' * 300).status_code == 200, 'qr.svg acepta exactamente 300 caracteres')
check(pub.get('/qr.svg').status_code == 400, 'qr.svg sin data -> 400')
for ruta, cli in (('/', pub), ('/admin_dashboard', admin), ('/pos', admin), ('/mesero_dashboard', admin),
                  ('/cajero_dashboard', clientes['brayan'])):
    html = cli.get(ruta).get_data(as_text=True)
    check('qrserver' not in html, f'{ruta} ya no usa api.qrserver.com')

# ================= Pre-órdenes por sucursal =================
c1 = app.test_client()
html = c1.get('/?mesa=3&suc=C1').get_data(as_text=True)
check('Caminante1' in html and 'SUC_PUBLICA = "C1"' in html, 'index con ?suc=C1 muestra Wi-Fi de Caminante 1 y manda C1')
import re as _re, html as _html, urllib.parse as _up
_m = _re.search(r'src="(/qr\.svg\?escala=5&(?:amp;)?data=[^"]+)"', html)
_src = _html.unescape(_m.group(1)) if _m else ''
_data = _up.parse_qs(_up.urlparse(_src).query).get('data', [''])[0]
check(_m is not None and _data == 'WIFI:T:WPA;S:Caminante1;P:Corazonsc31;;' and pub.get(_src).status_code == 200,
      f'Wi-Fi de Caminante 1 con QR local: {_data!r}')
r = c1.post('/crear_preorden', json={'suc': 'C1', 'mesa': '3', 'cliente_nombre': 'Ana C1', 'detalle_items': '1x Latte ($65)', 'total': 65})
id_c1 = r.json['folio']
r = c1.post('/crear_preorden', json={'mesa': '4', 'cliente_nombre': 'Sesion C1', 'detalle_items': '1x Latte ($65)', 'total': 65})
id_c1b = r.json['folio']
html = c1.get('/?mesa=2').get_data(as_text=True)   # QR/NFC ya instalado en la Matriz (sin ?suc=)
check('SUC_PUBLICA = "QM"' in html and 'QuioscoMoriscoB' in html, 'enlace de mesa sin ?suc= vuelve a la Matriz')
r = c1.post('/crear_preorden', json={'suc': 'QM', 'mesa': '2', 'cliente_nombre': 'Ana QM', 'detalle_items': '1x Latte ($65)', 'total': 65})
id_qm = r.json['folio']
r = app.test_client().post('/crear_preorden', json={'mesa': '6', 'cliente_nombre': 'Sin suc', 'detalle_items': '1x Latte ($65)', 'total': 65})
id_sin = r.json['folio']
r = app.test_client().post('/crear_preorden', json={'suc': 'ZZ', 'mesa': '7', 'cliente_nombre': 'Suc mala', 'detalle_items': '1x Latte ($65)', 'total': 65})
id_mala = r.json['folio']
with app.app_context():
    sucs = {i: PreOrden.query.get(i).sucursal for i in (id_c1, id_c1b, id_qm, id_sin, id_mala)}
esperado = {id_c1: 'Caminante 1', id_c1b: 'Caminante 1', id_qm: 'Quiosco Morisco (Matriz)',
            id_sin: 'Quiosco Morisco (Matriz)', id_mala: 'Quiosco Morisco (Matriz)'}
check(sucs == esperado, f'sucursal guardada en pre-órdenes (C1, sesión C1, QM, sin suc, suc inválida): {sucs}')

cam1 = login('caminante1', 'caminante12345')
pend_bray = {o['id'] for o in clientes['brayan'].get('/api/preordenes_pendientes').json['ordenes']}
pend_cam = {o['id'] for o in cam1.get('/api/preordenes_pendientes').json['ordenes']}
pend_adm = {o['id'] for o in admin.get('/api/preordenes_pendientes').json['ordenes']}
check(id_c1 not in pend_bray and id_qm in pend_bray, 'cajero de la Matriz no ve pre-órdenes de Caminante 1')
check(id_c1 in pend_cam and id_qm not in pend_cam, 'Caminante 1 solo ve las suyas')
check({id_c1, id_qm} <= pend_adm, 'admin ve las de todas las sucursales')
html_caj = clientes['brayan'].get('/cajero_dashboard').get_data(as_text=True)
check('Ana C1' not in html_caj and 'Ana QM' in html_caj, 'cajero_dashboard filtra pre-órdenes por sucursal')
html_mes = clientes['paola'].get('/mesero_dashboard').get_data(as_text=True)
check('Ana C1' not in html_mes, 'mesero_dashboard filtra pre-órdenes por sucursal')

tb = token_de(clientes['brayan'].get('/pos').get_data(as_text=True))
r = clientes['brayan'].post(f'/api/pos/confirmar_preorden_1clic/{id_c1}', json={}, headers={'X-CSRFToken': tb})
check(r.status_code == 403, 'cajero de la Matriz no puede confirmar pre-orden de Caminante 1')
tc1 = token_de(cam1.get('/pos').get_data(as_text=True))
r = cam1.post(f'/api/pos/confirmar_preorden_1clic/{id_c1}', json={}, headers={'X-CSRFToken': tc1})
with app.app_context():
    cta_c1 = CuentaPOS.query.get(r.json.get('cuenta_id')) if r.status_code == 200 else None
    check(cta_c1 is not None and cta_c1.sucursal == 'Caminante 1', 'Caminante 1 confirma su pre-orden y la cuenta se abre en Caminante 1')
r = admin.post(f'/api/pos/confirmar_preorden_1clic/{id_c1b}', json={}, headers=H)
with app.app_context():
    cta_b = CuentaPOS.query.get(r.json.get('cuenta_id')) if r.status_code == 200 else None
    check(cta_b is not None and cta_b.sucursal == 'Caminante 1', 'admin confirma pre-orden de C1 y la cuenta va a Caminante 1')
r = clientes['brayan'].post(f'/atender_preorden/{id_mala}', data={'accion': 'atendido', 'csrf_token': tcj})
with app.app_context():
    check(PreOrden.query.get(id_mala).estado == 'atendido', 'cajero atiende pre-orden de su sucursal')
r = clientes['brayan'].post(f'/atender_preorden/{id_c1}', data={'accion': 'cancelado', 'csrf_token': tcj})
with app.app_context():
    check(PreOrden.query.get(id_c1).estado == 'atendido', 'cajero de la Matriz no puede cancelar pre-orden de Caminante 1')

# ================= PINs por sucursal =================
tcam = token_de(cam1.get('/pedidos_sucursal').get_data(as_text=True))
cam1.post('/caja/generar_pin', data={'cantidad': '1', 'csrf_token': tcam})
with app.app_context():
    pin_c1 = PinCaja.query.filter_by(sucursal='Caminante 1', activo=True).first()
    check(pin_c1 is not None, 'PIN generado por Caminante 1 queda en Caminante 1')
    pin_c1_id, pin_c1_cod = pin_c1.id, pin_c1.codigo
html_caj = clientes['brayan'].get('/cajero_dashboard').get_data(as_text=True)
check(f'?pin={pin_c1_cod}' not in html_caj, 'cajero de la Matriz no ve PINs de Caminante 1')
clientes['brayan'].post(f'/caja/eliminar_pin/{pin_c1_id}', data={'csrf_token': tcj})
with app.app_context():
    check(PinCaja.query.get(pin_c1_id) is not None, 'cajero de la Matriz no puede anular PIN de Caminante 1')
app.test_client().post('/registrar_consumo', data={'nombre': 'Rosa', 'telefono': '9670000001', 'pin': pin_c1_cod})
with app.app_context():
    check(PinCaja.query.get(pin_c1_id).activo is False, 'el canje público del PIN sigue siendo global')

# ================= Empleados por sucursal =================
r = admin.post('/api/finanzas/empleado', json={'nombre': 'LUZ', 'puesto': 'MESERO', 'sucursal': 'Caminante 1', 'pin_checador': '7788'}, headers=H)
check(r.status_code == 200 and r.json.get('ok'), 'admin da de alta empleado en Caminante 1')
r = admin.post('/api/finanzas/empleado', json={'nombre': 'X', 'sucursal': 'Marte'}, headers=H)
check(r.status_code == 400, 'sucursal inválida rechazada')
with app.app_context():
    luz_id = EmpleadoNominaPOS.query.filter_by(nombre='LUZ').first().id
nomb_bray = {e['nombre'] for e in clientes['brayan'].get('/api/finanzas/datos').json['empleados']}
nomb_cam = {e['nombre'] for e in cam1.get('/api/finanzas/datos').json['empleados']}
nomb_adm = {e['nombre'] for e in admin.get('/api/finanzas/datos').json['empleados']}
check('LUZ' not in nomb_bray and 'PAOLA' in nomb_bray, 'cajero de la Matriz solo ve su personal')
check('LUZ' in nomb_cam and 'PAOLA' not in nomb_cam, 'Caminante 1 solo ve su personal')
check({'LUZ', 'PAOLA'} <= nomb_adm, 'admin ve todo el personal')
r = clientes['brayan'].post('/api/finanzas/consumo_empleado', json={'empleado_id': luz_id, 'monto': 50}, headers={'X-CSRFToken': tcj})
check(r.status_code == 403, 'cajero de la Matriz no carga vales a personal de Caminante 1')
r = cam1.post('/api/finanzas/consumo_empleado', json={'empleado_id': luz_id, 'monto': 50, 'concepto': 'comida'}, headers={'X-CSRFToken': tcam})
check(r.status_code == 403 and r.json.get('requiere_admin'), 'crédito / vale de empleado sin clave se rechaza en caja')
r = cam1.post('/api/finanzas/consumo_empleado', json={'empleado_id': luz_id, 'monto': 50, 'concepto': 'comida', 'clave_admin': 'admin12345'}, headers={'X-CSRFToken': tcam})
check(r.status_code == 200, 'Caminante 1 carga vale a su personal con clave de Admin/Gerente')
with app.app_context():
    check(ConsumoEmpleadoPOS.query.filter_by(empleado_id=luz_id).first().sucursal == 'Caminante 1', 'vale guardado con sucursal')
cam_fin = cam1.get('/api/finanzas/datos').json
check(any(c['empleado_nombre'] == 'LUZ' for c in cam_fin['consumos']) and
      [e for e in cam_fin['empleados'] if e['nombre'] == 'LUZ'][0]['consumo_pendiente'] == 50.0, 'vale pendiente visible en su sucursal')
check(not any(c['empleado_nombre'] == 'LUZ' for c in clientes['brayan'].get('/api/finanzas/datos').json['consumos']),
      'vales de otra sucursal no se ven en la Matriz')
pers_bray = {p['nombre'] for p in clientes['brayan'].get('/api/pos/personas_descuento').json['personas']}
check('LUZ' not in pers_bray, 'personas_descuento filtra por sucursal')
r = admin.put('/api/finanzas/empleado', json={'id': luz_id, 'sucursal': 'Caminante 2'}, headers=H)
check(r.status_code == 200 and r.json.get('sucursal') == 'Caminante 2', 'admin cambia sucursal principal del empleado')
r = admin.put('/api/finanzas/empleado', json={'id': luz_id, 'sucursal': 'Marte'}, headers=H)
check(r.status_code == 400, 'cambio a sucursal inválida rechazado')
r = clientes['brayan'].post('/api/checador/pin', json={'pin': '7788'}, headers={'X-CSRFToken': tcj})
check(r.status_code == 200 and r.json.get('sucursal') == 'Quiosco Morisco (Matriz)', 'checador permite checar en otra sucursal')
with app.app_context():
    reg = RegistroAsistencia.query.filter_by(empleado_nombre='LUZ').first()
    check(reg is not None and reg.sucursal == 'Quiosco Morisco (Matriz)', 'asistencia guarda la sucursal donde checó')
r = admin.post('/api/finanzas/generar_nomina', json={'empleado_id': luz_id, 'permitir_negativo': True}, headers=H)
with app.app_context():
    rec = ReciboNominaPOS.query.filter_by(empleado_id=luz_id).first()
    check(rec is not None and rec.sucursal == 'Caminante 2' and rec.descuentos_consumo == 50.0,
          'recibo de nómina con sucursal del empleado y descuenta el vale hecho en otra sucursal')
html_nom = admin.get('/nomina_creditos').get_data(as_text=True)
check('id="emp_sucursal"' in html_nom and 'JSON.parse(\'["Quiosco Morisco (Matriz)"' in html_nom, 'nómina muestra selector de sucursal')

# ================= CSRF en multipart (fotos) =================
r = admin.post('/admin/producto/nuevo', data={'nombre': 'Pan', 'descripcion': 'x', 'precio': '10', 'categoria': 'Postres',
               'csrf_token': tok, 'foto': (_B(b''), '')}, content_type='multipart/form-data')
check(r.status_code == 302, 'formulario multipart con token pasa CSRF')
r = admin.post('/admin/producto/nuevo', data={'nombre': 'Pan2', 'descripcion': 'x', 'precio': '10', 'categoria': 'Postres',
               'foto': (_B(b''), '')}, content_type='multipart/form-data')
check(r.status_code == 400, 'formulario multipart sin token es rechazado')
