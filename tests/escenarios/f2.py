# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, cam1, H, tcj, capturar, check, db).
from models import CuentaPOS, ESQUEMA_REQUERIDO, esquema_faltante

CLAVE = 'admin12345'


def _abrir(mesa):
    admin.post('/api/pos/abrir_mesa', json={'mesa': mesa, 'personas': 1}, headers=H)
    with app.app_context():
        return CuentaPOS.query.filter_by(mesa=mesa, estado='ABIERTA').first().id


def _cta(cid):
    with app.app_context():
        c = CuentaPOS.query.get(cid)
        return round(c.total, 2), round(float(c.descuento_fijo or 0), 2), round(float(c.descuento_pct or 0), 2), c.estado

# ---------- Descuento en pesos ----------
ca = _abrir('F2A'); capturar(ca)                       # Latte $65
r = admin.post('/api/pos/descuento_autorizado', json={'cuenta_id': ca, 'tipo': 'MONTO', 'monto': 15, 'clave_admin': CLAVE}, headers=H)
check(r.status_code == 200 and _cta(ca)[:3] == (50.0, 15.0, 0.0), f'descuento fijo $15 sobre $65 -> total $50 ({_cta(ca)})')
check(admin.get(f'/api/pos/detalle_cuenta/{ca}').json.get('descuento_fijo') == 15.0, 'detalle de cuenta expone el descuento en pesos')
r = admin.post('/api/pos/descuento_autorizado', json={'cuenta_id': ca, 'porcentaje': 10, 'clave_admin': CLAVE}, headers=H)
check(_cta(ca)[:3] == (58.5, 0.0, 10.0), f'aplicar % reemplaza el descuento en pesos ({_cta(ca)})')
admin.post('/api/pos/descuento_autorizado', json={'cuenta_id': ca, 'tipo': 'MONTO', 'monto': 500, 'clave_admin': CLAVE}, headers=H)
check(_cta(ca)[0] == 0.0, 'descuento en pesos mayor que la cuenta deja el total en $0 (nunca negativo)')
admin.post('/api/pos/descuento_autorizado', json={'cuenta_id': ca, 'tipo': 'MONTO', 'monto': 20, 'clave_admin': CLAVE}, headers=H)
check(admin.post('/api/pos/descuento_autorizado', json={'cuenta_id': ca, 'tipo': 'MONTO', 'monto': 20}, headers=H).status_code == 403,
      'descuento en pesos también requiere autorización')
r = admin.post('/api/pos/dividir_cuenta_real', json={'cuenta_id': ca, 'subcuentas': {'B': []}}, headers=H)
check(r.status_code == 400 and 'pesos' in r.json.get('msg', ''), 'no se divide por productos una cuenta con descuento en pesos')
cb = _abrir('F2B'); capturar(cb)
r = admin.post('/api/pos/juntar_cuentas', json={'cuenta_origen_id': ca, 'cuenta_destino_id': cb, 'origen_id': ca, 'destino_id': cb}, headers=H)
check(r.status_code == 400, 'no se junta una cuenta con descuento en pesos (se perdería)')
with app.app_context():
    from models import BitacoraPOS
    check(BitacoraPOS.query.filter(BitacoraPOS.accion == 'DESCUENTO', BitacoraPOS.detalle.like('%fijo%')).first() is not None,
          'bitácora registra el descuento en pesos')

# ---------- Idempotencia del cobro ----------
cc = _abrir('F2C'); capturar(cc)                       # $65
imprimir_cuenta(admin, cc, H)
r1 = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': cc, 'efectivo': 100, 'idem': 'cobro-F2C-1'}, headers=H)
r2 = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': cc, 'efectivo': 100, 'idem': 'cobro-F2C-1'}, headers=H)
check(r1.status_code == 200 and r1.json['cambio'] == 35.0, 'primer cobro OK (cambio $35)')
check(r2.status_code == 200 and r2.json.get('repetido') and r2.json['folio'] == r1.json['folio'] and r2.json['cambio'] == 35.0,
      'reintento con la misma llave devuelve el mismo folio/cambio sin cobrar de nuevo')
check(admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': cc, 'efectivo': 100, 'idem': 'otra-llave'}, headers=H).status_code == 400,
      'con otra llave la cuenta ya cobrada se rechaza')
check(admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': cc, 'efectivo': 100}, headers=H).status_code == 400,
      'sin llave la cuenta ya cobrada se rechaza (como antes)')
with app.app_context():
    check(CuentaPOS.query.get(cc).cobro_idem == 'cobro-F2C-1', 'la llave queda guardada en la cuenta')
html_pos = admin.get('/pos').get_data(as_text=True)
check('llaveCobro(' in html_pos and 'descModoGral' in html_pos, 'POS envía llave de cobro y tiene selector % / $')

# ---------- Datos de ticket y Wi-Fi editables ----------
d = admin.get('/api/admin/datos_ticket').json
check(d['ok'] and d['sucursales']['Caminante 1']['wifi_red'] == 'Caminante1', 'admin lee los datos actuales por sucursal')
datos = dict(d['sucursales']['Caminante 1'], wifi_red='CaminanteUno', wifi_clave='claveSegura1', telefono='9670001111')
r = admin.post('/api/admin/datos_ticket', json={'sucursal': 'Caminante 1', 'datos': datos}, headers=H)
check(r.status_code == 200 and r.json['datos']['wifi_red'] == 'CaminanteUno', 'admin guarda Wi-Fi y teléfono de Caminante 1')
html = app.test_client().get('/?mesa=1&suc=C1').get_data(as_text=True)
check('CaminanteUno' in html and 'claveSegura1' in html, 'el menú público de C1 muestra el Wi-Fi editado')
html_qm = app.test_client().get('/?mesa=1').get_data(as_text=True)
check('QuioscoMoriscoB' in html_qm and 'CaminanteUno' not in html_qm, 'la Matriz conserva su Wi-Fi')
check(admin.post('/api/admin/datos_ticket', json={'sucursal': 'Caminante 1', 'datos': dict(datos, rfc='XYZ')}, headers=H).status_code == 400,
      'RFC inválido rechazado')
check(admin.post('/api/admin/datos_ticket', json={'sucursal': 'Caminante 1', 'datos': dict(datos, wifi_clave='corta')}, headers=H).status_code == 400,
      'clave Wi-Fi menor a 8 caracteres rechazada')
check(admin.post('/api/admin/datos_ticket', json={'sucursal': 'Marte', 'datos': datos}, headers=H).status_code == 400, 'sucursal inválida rechazada')
r = admin.post('/api/admin/datos_ticket', json={'sucursal': 'Caminante 1', 'datos': dict(datos, telefono='')}, headers=H)
check(r.json['datos']['telefono'] == '9671802660', 'campo vacío vuelve al valor de siempre')
check(clientes['brayan'].get('/api/admin/datos_ticket').status_code == 403, 'solo admin edita datos de ticket')
check('dt_sucursal' in admin.get('/admin_dashboard').get_data(as_text=True), 'panel admin tiene la tarjeta de datos de ticket')

# ---------- CSV de créditos ----------
HJ = {'X-CSRFToken': tcj}
r = clientes['brayan'].post('/api/creditos/cliente', json={'nombre': 'Cliente Matriz CSV', 'limite_credito': 1000}, headers=HJ)
cid_cred = r.json['id']
clientes['brayan'].post('/api/creditos/movimiento', json={'cliente_id': cid_cred, 'tipo': 'CARGO', 'monto': 120, 'concepto': 'consumo'}, headers=HJ)
r = admin.get('/api/exportar/creditos')
t = r.get_data(as_text=True)
check(r.status_code == 200 and 'text/csv' in r.headers['Content-Type'] and 'CLIENTE MATRIZ CSV' in t and '120.0' in t,
      'CSV de saldos de crédito (admin)')
check('CLIENTE MATRIZ CSV' not in cam1.get('/api/exportar/creditos').get_data(as_text=True), 'Caminante 1 no ve créditos de la Matriz')
t = clientes['brayan'].get('/api/exportar/creditos_movimientos').get_data(as_text=True)
check('CARGO' in t and 'CLIENTE MATRIZ CSV' in t, 'CSV de movimientos de crédito (caja de su sucursal)')
check(admin.get('/api/exportar/creditos_movimientos?desde=2026-99-01').status_code == 400, 'fecha inválida rechazada')
check('/api/exportar/creditos' in admin.get('/nomina_creditos').get_data(as_text=True), 'botones de Excel en Créditos')
check(clientes['paola'].get('/api/exportar/creditos').status_code == 403, 'mesero no exporta créditos')

with app.app_context():
    check(ESQUEMA_REQUERIDO.get('cuentas_pos') == {'descuento_fijo', 'cobro_idem'} and esquema_faltante(db.engine) == [],
          'columnas nuevas en ESQUEMA_REQUERIDO y creadas')
