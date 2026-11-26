# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, cam1, check, token_de).
# Pantallas como Soft Restaurant: cancelación con motivo + ticket de CANCELACIÓN a cocina/barra,
# corte X/Z con desglose (tipo de producto, servicio, descuentos, cortesías, promedios, folios) y declaración del cajero.
from models import CuentaPOS as _CtaS, ColaImpresionPOS as _ColaS

HS = {'X-CSRFToken': token_de(cam1.get('/pedidos_sucursal').get_data(as_text=True))}
CLAVE_S = 'admin12345'
BASE_Z = {'EF': 0, 'TARJD': 0, 'TARJC': 0, 'TRANS': 0, 'VAL': 0, 'clave_admin': CLAVE_S}

# Turno limpio en Caminante 1 para poder comprobar los números exactos del corte
r = cam1.post('/api/pos/cerrar_turno_arqueo', json=BASE_Z, headers=HS)
check(r.status_code == 200, f'cierre previo para empezar turno limpio ({r.status_code})')
r = cam1.post('/api/pos/abrir_mesa', json={'mesa': 'SFT0', 'personas': 1}, headers=HS)
check(r.status_code == 409 and r.json.get('turno_cerrado'), 'después del corte Z la caja queda sin turno (no se abre otro solo)')
r = cam1.post('/api/pos/abrir_turno_real', json={'fondo_inicial': 0}, headers=HS)
check(r.status_code == 200, 'abrir turno nuevo después del Z')


def _abrir_s(mesa, personas):
    r = cam1.post('/api/pos/abrir_mesa', json={'mesa': mesa, 'personas': personas}, headers=HS)
    return r.json.get('cuenta_id')


def _cap_s(cid, desc, precio, area):
    return cam1.post('/api/pos/capturar_item', json={'cuenta_id': cid, 'descripcion': desc, 'precio': precio, 'cantidad': 1,
                                                     'clave': '07001', 'area_impresion': area}, headers=HS)


c1 = _abrir_s('SFT1', 2)
_cap_s(c1, 'LATTE PRUEBA', 65, 'BARRA')
_cap_s(c1, 'HUEVOS PRUEBA', 100, 'COCINA')
cam1.post(f'/api/pos/enviar_comanda/{c1}', json={}, headers=HS)
items = cam1.get(f'/api/pos/detalle_cuenta/{c1}').json['items']
id_latte = next(i['id'] for i in items if i['descripcion'] == 'LATTE PRUEBA')

r = cam1.post('/api/pos/cancelar_items_lote', json={'cuenta_id': c1, 'items': [{'id': id_latte, 'cantidad': 1}], 'clave_admin': CLAVE_S}, headers=HS)
check(r.status_code == 400 and 'motivo' in r.json.get('msg', ''), 'cancelar sin motivo se rechaza (como Soft)')
with app.app_context():
    antes = _ColaS.query.filter(_ColaS.tipo.like('CANCELACION%')).count()
r = cam1.post('/api/pos/cancelar_items_lote', json={'cuenta_id': c1, 'clave_admin': CLAVE_S,
              'items': [{'id': id_latte, 'cantidad': 1, 'motivo': 'CAMBIO DE OPINION CLIENTE'}]}, headers=HS)
check(r.status_code == 200 and r.json.get('aviso_cocina'), 'cancelar producto ya enviado avisa a cocina/barra')
with app.app_context():
    t = _ColaS.query.filter(_ColaS.tipo.like('CANCELACION%')).order_by(_ColaS.id.desc()).first()
    check(_ColaS.query.filter(_ColaS.tipo.like('CANCELACION%')).count() == antes + 1 and t.tipo == 'CANCELACION_BARRA'
          and '*** CANCELACION ***' in t.contenido_html and 'LATTE PRUEBA' in t.contenido_html
          and 'CAMBIO DE OPINION CLIENTE' in t.contenido_html and 'SFT1' in t.contenido_html,
          'ticket CANCELACION a BARRA con producto, motivo y mesa')
_cap_s(c1, 'LATTE PRUEBA', 65, 'BARRA')
id_nuevo = next(i['id'] for i in cam1.get(f'/api/pos/detalle_cuenta/{c1}').json['items'] if i['descripcion'] == 'LATTE PRUEBA')
r = cam1.post('/api/pos/cancelar_items_lote', json={'cuenta_id': c1, 'motivo_general': 'ERROR DE CAPTURA', 'clave_admin': CLAVE_S,
              'items': [{'id': id_nuevo, 'cantidad': 1}]}, headers=HS)
check(r.status_code == 200 and not r.json.get('aviso_cocina'), 'producto aún no enviado se cancela sin imprimir aviso')
imprimir_cuenta(cam1, c1, HS)
r = cam1.post('/api/pos/pagar_cuenta', json={'cuenta_id': c1, 'efectivo': 100, 'idem': 'soft-c1'}, headers=HS)
check(r.status_code == 200, f'cobro cuenta 1 ($100) ({r.status_code})')

c2 = _abrir_s('SFT2', 1)
_cap_s(c2, 'LATTE PRUEBA', 65, 'BARRA')
cam1.post('/api/pos/descuento_autorizado', json={'cuenta_id': c2, 'porcentaje': 50, 'clave_admin': CLAVE_S}, headers=HS)
imprimir_cuenta(cam1, c2, HS)
r = cam1.post('/api/pos/pagar_cuenta', json={'cuenta_id': c2, 'efectivo': 32.5, 'idem': 'soft-c2'}, headers=HS)
check(r.status_code == 200, f'cobro cuenta 2 con 50% ($32.50) ({r.status_code})')

d = cam1.get('/api/pos/corte_caja').json
x = d.get('detalle') or {}
tipos = {t['tipo']: t for t in x.get('por_tipo', [])}
check(tipos.get('ALIMENTOS', {}).get('venta') == '86.21' and tipos.get('BEBIDAS', {}).get('venta') == '56.03'
      and tipos['ALIMENTOS']['cantidad'] == 1 and tipos['BEBIDAS']['cantidad'] == 1,
      f'venta por tipo de producto sin IVA ({x.get("por_tipo")})')
check(x.get('subtotal') == '142.24' and x.get('ventas_con_imp') == '132.50' and x.get('descuentos') == '28.02',
      f'subtotal, descuentos y venta con impuestos ({x.get("subtotal")}, {x.get("descuentos")}, {x.get("ventas_con_imp")})')
desc_t = {t['tipo']: t['monto'] for t in x.get('descuentos_tipo', [])}
check(desc_t.get('BEBIDAS') == '28.02' and x.get('total_cortesias') == '0.00', f'descuento por tipo ({desc_t})')
check(x.get('cuentas_normales') == 2 and x.get('cuentas_descuento') == 1 and x.get('cuentas_cortesia') == 0
      and x.get('comensales') == 3 and x.get('cuenta_promedio') == '66.25' and x.get('folio_inicial') != '-',
      f'cuentas, comensales, promedio y folios ({x})')
serv = {s['tipo']: s['venta'] for s in x.get('por_servicio', [])}
check(serv.get('COMEDOR') == '142.24', f'venta por tipo de servicio ({serv})')

cam1.post('/api/pos/movimiento_caja', json={'tipo': 'RETIRO', 'monto': 20, 'concepto': 'HIELO', 'categoria': 'HIELO', 'clave_admin': CLAVE_S}, headers=HS)
fm = cam1.get('/api/pos/corte_caja').json['detalle']
check(len(fm['folios_mesero']) == 1 and fm['folios_mesero'][0]['cuentas'] == 2 and fm['folios_mesero'][0]['folio_min'] != '-'
      and fm['total_gastos'] == '20.00' and fm['gastos'][0]['concepto'] == 'HIELO', f'corte con folios por mesero y gastos ({fm.get("folios_mesero")}, {fm.get("gastos")})')
EXTRAS = {'vales_ado': 3, 'vales_occ_desayuno': 2, 'vales_occ_comida': 1, 'vales_occ_cena': 0,
          'factura_folio_inicial': 'F-100', 'factura_folio_final': 'F-104', 'aclaraciones': 'Faltan 2.50 de cambio', 'responsable': 'gerente turno'}
r = cam1.post('/api/pos/cerrar_turno_arqueo', json=dict(BASE_Z, EF=110, extras=EXTRAS), headers=HS)
j = r.json or {}
check(j.get('extras', {}).get('vales_ado') == 3 and j['extras']['factura_folio_final'] == 'F-104' and j['extras']['responsable'] == 'GERENTE TURNO',
      f'Corte Z guarda vales ADO/OCC, facturas, aclaraciones y responsable ({j.get("extras")})')
decl = {x['forma']: x for x in j.get('declaracion', [])}
check(r.status_code == 200 and j.get('corte', {}).get('detalle', {}).get('ventas_con_imp') == '132.50'
      and decl.get('EFECTIVO', {}).get('diferencia') == '-2.50' and len(decl) == 5,
      f'Corte Z trae el corte completo y la declaración por forma de pago ({decl.get("EFECTIVO")})')
abrir_turnos()

h_pos = admin.get('/pos').get_data(as_text=True)
check('class="tbl-canc"' in h_pos and 'id="descRapidos"' in h_pos and 'js/corte_ticket.js' in h_pos,
      'POS: cancelación en tabla, % rápidos en descuento y corte estilo Soft')

# Ficha del empleado como en Soft: sueldo diario/hora, contacto, emergencia, correo, acta, CURP y foto
from io import BytesIO as _BS
r = admin.post('/api/finanzas/empleado', json={'nombre': 'ana ficha', 'puesto': 'CAJERO', 'sucursal': 'Caminante 1',
               'sueldo_diario': 300, 'sueldo_hora': 40, 'telefono': '5512345678', 'email': 'Ana@Ejemplo.com',
               'contacto_emergencia': 'mama ana', 'telefono_emergencia': '5587654321', 'curp': 'gome800101hdfrrn09',
               'acta_nacimiento': True, 'fecha_ingreso': '2026-11-01', 'domicilio': 'calle 1'}, headers=H)
check(r.status_code == 200 and r.json.get('id'), f'alta de empleado con ficha completa ({r.status_code} {r.json})')
id_ana = r.json.get('id')
r = admin.post('/api/finanzas/empleado', json={'nombre': 'X', 'curp': 'MAL'}, headers=H)
check(r.status_code == 400 and 'CURP' in r.json.get('msg', ''), 'CURP con formato inválido se rechaza')
r = admin.put('/api/finanzas/empleado', json={'id': id_ana, 'email': 'no-es-correo'}, headers=H)
check(r.status_code == 400, 'correo inválido se rechaza')
r = admin.put('/api/finanzas/empleado', json={'id': id_ana, 'telefono': '5500000000', 'acta_nacimiento': False}, headers=H)
check(r.status_code == 200, 'editar ficha')
ana = next((e for e in admin.get('/api/finanzas/datos').json['empleados'] if e['id'] == id_ana), {})
check(ana.get('curp') == 'GOME800101HDFRRN09' and ana.get('email') == 'ana@ejemplo.com' and ana.get('telefono') == '5500000000'
      and ana.get('sueldo_diario') == 300 and ana.get('sueldo_hora') == 40 and ana.get('acta_nacimiento') is False
      and ana.get('contacto_emergencia') == 'MAMA ANA' and ana.get('fecha_ingreso') == '2026-11-01',
      f'la ficha se guarda y regresa al admin ({ana})')
emp_caja = next((e for e in cam1.get('/api/finanzas/datos').json.get('empleados', []) if e['id'] == id_ana), None)
check(emp_caja is not None and 'curp' not in emp_caja and 'telefono' not in emp_caja, 'caja no ve los datos personales del empleado')
r = admin.post(f'/api/finanzas/empleado_foto/{id_ana}', data={'foto': (_BS(b'texto'), 'a.txt', 'text/plain')},
               content_type='multipart/form-data', headers=H)
check(r.status_code == 400, 'foto con formato no permitido se rechaza')
check(cam1.post(f'/api/finanzas/empleado_foto/{id_ana}', data={}, headers=HS).status_code == 403, 'solo admin sube fotos de empleado')
h_nom = admin.get('/nomina_creditos').get_data(as_text=True)
check('id="modalFichaEmp"' in h_nom and 'id="emp_curp"' in h_nom and 'id="emp_foto"' in h_nom, 'Nómina: ficha del empleado con foto')
admin.delete('/api/finanzas/empleado', json={'id': id_ana, 'motivo_baja': 'PRUEBA'}, headers=H)

# ---- Lo que la caja (cajero / sucursal) ya no hace sin clave de Admin o Gerente ----
r = cam1.post('/api/mermas/registrar', json={'insumo_nombre': 'PAN', 'cantidad': 1, 'costo_total': 10, 'motivo': 'CAIDO'}, headers=HS)
check(r.status_code == 403 and r.json.get('requiere_admin'), 'merma de sucursal sin clave se rechaza')
r = cam1.post('/api/mermas/registrar', json={'insumo_nombre': 'PAN', 'cantidad': 1, 'costo_total': 10, 'motivo': 'CAIDO', 'clave_admin': CLAVE_S}, headers=HS)
check(r.status_code == 200, 'merma de sucursal con clave')
r = cam1.post('/api/pos/registrar_merma', json={'insumo_nombre': 'PAN', 'cantidad': 1, 'motivo': 'CAIDO', 'costo_unitario': 5}, headers=HS)
check(r.status_code == 403 and r.json.get('requiere_admin'), 'merma desde la caja sin clave se rechaza')
with app.app_context():
    from models import EmpleadoNominaPOS as _EmpS
    _e = _EmpS(nombre='VALE PRUEBA', sucursal='Caminante 1', activo=True); db.session.add(_e); db.session.commit(); _eid = _e.id
c3 = _abrir_s('SFT3', 1)
_cap_s(c3, 'LATTE PRUEBA', 65, 'BARRA')
imprimir_cuenta(cam1, c3, HS)
r = cam1.post('/api/pos/pagar_cuenta', json={'cuenta_id': c3, 'vale_empleado': 65, 'empleado_id': _eid, 'idem': 'soft-c3'}, headers=HS)
check(r.status_code == 403 and r.json.get('requiere_admin'), 'cargar la cuenta a un empleado sin clave se rechaza')
r = cam1.post('/api/pos/pagar_cuenta', json={'cuenta_id': c3, 'vale_empleado': 65, 'empleado_id': _eid, 'idem': 'soft-c3', 'clave_admin': CLAVE_S}, headers=HS)
check(r.status_code == 200, 'con clave sí se carga la cuenta al empleado')
r = imprimir_cuenta(cam1, c3, HS)
check(r.status_code == 200 and r.json.get('codigo'), 'el PIN del ticket final se obtiene con la cuenta ya pagada')
h = cam1.get('/nomina_creditos').get_data(as_text=True)
check('>CRÉDITOS<' in h and 'id="sec_prestaciones"' not in h and "cambiarTab('vales', this)\" style=\"display:none\"" in h,
      'la caja no ve Nómina ni vales de personal (solo Créditos y Checador)')
check('<span>Créditos</span>' in h, 'en la barra de módulos de la caja dice Créditos, no Nómina')

# ---- Historial de cortes Z por fechas y reimpresión ----
r = admin.get('/api/industrial/cortes?desde=2000-01-01&sucursal=Caminante 1')
cz = r.json.get('cortes', [])
check(r.status_code == 200 and len(cz) >= 2 and any(c['completo'] for c in cz), f'historial de cortes Z por fechas ({len(cz)})')
completo = next(c for c in cz if c['completo'])
z = admin.get(f"/api/industrial/corte/{completo['id']}").json
check(z['ok'] and z['corte']['detalle']['folios_mesero'] and z['extras']['factura_folio_final'] == 'F-104' and len(z['declaracion']) == 5,
      'el corte Z guardado trae todo para reimprimirlo igual')
check(admin.get('/api/industrial/cortes').status_code == 200 and cam1.get('/api/industrial/cortes').status_code == 403, 'historial de cortes solo admin')
check(cam1.post('/api/checador/registrar', json={'empleado_nombre': 'X'}, headers=HS).status_code == 403,
      'la captura manual de asistencia ya no la hace la caja (solo PIN)')
r = admin.get('/api/checador/lista?desde=2000-01-01&sucursal=TODAS')
check(r.status_code == 200 and 'fecha' in (r.json['asistencias'][0] if r.json['asistencias'] else {'fecha': 1}), 'reporte de asistencia por fechas')
h_ind = admin.get('/industrial').get_data(as_text=True)
check('id="cz_desde"' in h_ind and 'id="as_desde"' in h_ind and 'js/corte_ticket.js' in h_ind, 'Reportes: historial de cortes y asistencia por fechas')

# ---- Impresión por estación: cada PC pide solo lo que le toca (cocina / barra / caja) ----
c4 = _abrir_s('SFT4', 1)
_cap_s(c4, 'LATTE PRUEBA', 65, 'BARRA')
_cap_s(c4, 'HUEVOS PRUEBA', 100, 'COCINA')
cam1.post(f'/api/pos/enviar_comanda/{c4}', json={}, headers=HS)
r = cam1.post('/api/pos/cola_impresion/reclamar', json={'dispositivo': 'PC-BARRA', 'grupos': ['BARRA']}, headers=HS)
with app.app_context():
    tipos_b = {_ColaS.query.get(t['id']).tipo for t in r.json['tickets']}
check(tipos_b and tipos_b <= {'COMANDA_BARRA', 'CANCELACION_BARRA'}, f'la estación de barra solo recibe barra ({tipos_b})')
r = cam1.post('/api/pos/cola_impresion/reclamar', json={'dispositivo': 'PC-COCINA', 'grupos': ['COCINA']}, headers=HS)
with app.app_context():
    tipos_c = {_ColaS.query.get(t['id']).tipo for t in r.json['tickets']}
check('COMANDA_COCINA' in tipos_c and not (tipos_c & {'COMANDA_BARRA', 'PRECUENTA', 'VALE_CAJA'}), f'la estación de cocina solo recibe cocina ({tipos_c})')
r = cam1.post('/api/pos/cola_impresion/reclamar', json={'dispositivo': 'PC-CAJA', 'grupos': ['CAJA']}, headers=HS)
with app.app_context():
    tipos_j = {_ColaS.query.get(t['id']).tipo for t in r.json['tickets']}
check(not (tipos_j & {'COMANDA_COCINA', 'COMANDA_BARRA', 'CANCELACION_COCINA', 'CANCELACION_BARRA'}), f'la estación de caja no recibe comandas ({tipos_j})')
h_pos = cam1.get('/pos').get_data(as_text=True)
check('id="modalImpresora"' in h_pos and '--kiosk-printing' not in h_pos.split('impComando')[0][-50:], 'POS: pantalla de configuración de impresora')

# ---- Cambio rápido de usuario con PIN en la caja ----
with app.app_context():
    from models import User as _US
    _uid = _US.query.filter_by(username='brayan').first().id
    _mid = _US.query.filter_by(username='paola').first().id
_tk_adm = token_de(admin.get('/admin_dashboard').get_data(as_text=True))
admin.post(f'/admin/usuario/pin/{_uid}', data={'pin': '4821', 'csrf_token': _tk_adm})
admin.post(f'/admin/usuario/pin/{_mid}', data={'pin': '9999', 'csrf_token': _tk_adm})
with app.app_context():
    check(_US.query.get(_uid).pin_rapido and not _US.query.get(_mid).pin_rapido, 'Admin asigna PIN de caja (los meseros no llevan PIN de caja)')
r = cam1.post('/api/cambiar_usuario_pin', json={'pin': '0000'}, headers=HS)
check(r.status_code == 401, 'PIN incorrecto se rechaza')
r = cam1.post('/api/cambiar_usuario_pin', json={'pin': '4821'}, headers=HS)
check(r.status_code == 200 and r.json['usuario'] == 'BRAYAN', 'con su PIN el cajero entra en la misma caja sin cerrar sesión')
check('BRAYAN' in cam1.get('/pos').get_data(as_text=True), 'la caja ya trabaja con el nuevo usuario')

# ---- Alertas al dueño ----
r = admin.post('/api/alertas/config', json={'cancelacion_min': 10, 'efectivo_max': 1, 'telegram_chat_id': 'abc'}, headers=H)
check(r.status_code == 400, 'chat id de Telegram inválido se rechaza')
r = admin.post('/api/alertas/config', json={'cancelacion_min': 10, 'efectivo_max': 1, 'activas': True}, headers=H)
check(r.status_code == 200, 'configurar límites de alertas')
c5 = _abrir_s('SFT5', 1)
_cap_s(c5, 'LATTE PRUEBA', 65, 'BARRA')
_cap_s(c5, 'HUEVOS PRUEBA', 100, 'COCINA')
cam1.post(f'/api/pos/enviar_comanda/{c5}', json={}, headers=HS)
_it = next(i['id'] for i in cam1.get(f'/api/pos/detalle_cuenta/{c5}').json['items'] if i['descripcion'] == 'HUEVOS PRUEBA')
cam1.post('/api/pos/cancelar_items_lote', json={'cuenta_id': c5, 'clave_admin': CLAVE_S, 'items': [{'id': _it, 'cantidad': 1, 'motivo': 'PRUEBA ALERTA'}]}, headers=HS)
imprimir_cuenta(cam1, c5, HS)
cam1.post('/api/pos/pagar_cuenta', json={'cuenta_id': c5, 'efectivo': 65, 'idem': 'soft-c5'}, headers=HS)
cam1.post('/api/pos/pagar_cuenta', json={'cuenta_id': c5, 'efectivo': 65, 'idem': 'soft-c5'}, headers=HS)
al = admin.get('/api/alertas').json['alertas']
check(any(a['tipo'] == 'CANCELACION' and 'PRUEBA ALERTA' in a['texto'] for a in al), 'alerta por cancelación grande')
check(sum(1 for a in al if a['tipo'] == 'EFECTIVO_ALTO') == 1, 'una sola alerta de efectivo alto por turno')
check(cam1.get('/api/alertas').status_code == 403, 'las alertas solo las ve el Admin')
r = admin.post('/api/alertas/prueba', json={}, headers=H)
check(r.status_code == 200 and r.json['enviado'] is False, 'sin Telegram configurado la prueba lo explica (no truena)')
admin.post('/api/alertas/config', json={'cancelacion_min': 200, 'efectivo_max': 5000}, headers=H)

# ---- Precios por sucursal y promociones por sucursal ----
with app.app_context():
    from models import Producto as _Prod
    _pp = _Prod(nombre='CAFE SUCURSAL', precio=40.0, categoria='Bebidas Calientes', descripcion=''); db.session.add(_pp); db.session.commit(); _ppid = _pp.id
SUC_ADM = 'Quiosco Morisco (Matriz)'
r = admin.post('/api/pos/precios_sucursal', json={'sucursal': SUC_ADM, 'producto_id': _ppid, 'precio': 55}, headers=H)
check(r.status_code == 200, 'Admin pone precio especial en una sucursal')
check(cam1.post('/api/pos/precios_sucursal', json={'sucursal': SUC_ADM, 'producto_id': _ppid, 'precio': 1}, headers=HS).status_code == 403,
      'solo Admin cambia precios por sucursal')
_ca = admin.post('/api/pos/abrir_mesa', json={'mesa': 'PS1', 'personas': 1}, headers=H).json['cuenta_id']
admin.post('/api/pos/capturar_item', json={'cuenta_id': _ca, 'descripcion': 'CAFE SUCURSAL', 'precio': 40, 'cantidad': 1}, headers=H)
_it = [i for i in admin.get(f'/api/pos/detalle_cuenta/{_ca}').json['items'] if i['descripcion'] == 'CAFE SUCURSAL'][0]
check(abs(float(str(_it['precio']).replace('$', '')) - 55) < 0.01, f'se cobra el precio de la sucursal aunque el navegador mande otro ({_it["precio"]})')
cat = admin.get('/api/pos/catalogo_completo').json['productos']
check(next(p for p in cat if p['id'] == _ppid)['precio'] == 55, 'el catálogo de la caja muestra el precio de la sucursal')
admin.post('/api/pos/precios_sucursal', json={'sucursal': SUC_ADM, 'producto_id': _ppid, 'precio': None, 'disponible': False}, headers=H)
cat = admin.get('/api/pos/catalogo_completo').json['productos']
_cp = next(p for p in cat if p['id'] == _ppid)
check(_cp['disponible'] is False and _cp['agotado'] is False, 'un platillo que no se vende en la sucursal sale como no disponible (sin marcarlo agotado en todas)')
check('CAFE SUCURSAL' not in admin.get('/mesero_dashboard').get_data(as_text=True), 'la tablet del mesero no lo muestra en esa sucursal')
admin.post('/api/pos/precios_sucursal', json={'sucursal': SUC_ADM, 'producto_id': _ppid, 'precio': None, 'disponible': True}, headers=H)
admin.post('/api/pos/promociones', json={'nombre': 'PROMO OTRA SUC', 'tipo': 'DESCUENTO_PCT', 'valor': 50, 'aplica_a': 'PRODUCTO',
                                         'objetivo': 'CAFE SUCURSAL', 'hora_inicio': '00:00', 'hora_fin': '23:59', 'sucursal': 'Caminante 2'}, headers=H)
admin.post('/api/pos/capturar_item', json={'cuenta_id': _ca, 'descripcion': 'CAFE SUCURSAL', 'precio': 40, 'cantidad': 1}, headers=H)
_items = [i for i in admin.get(f'/api/pos/detalle_cuenta/{_ca}').json['items'] if i['descripcion'] == 'CAFE SUCURSAL']
check(all(not i.get('promo_aplicada') and float(i.get('descuento_pct') or 0) == 0 for i in _items), f'una promoción de otra sucursal no aplica aquí ({_items})')

# ---- Reparto de propinas del día (parejo entre los que trabajaron) ----
from models import RegistroAsistencia as _RA, ahora_local as _ahl2
with app.app_context():
    for _n in ('ANA', 'BETO', 'CARLA'):
        db.session.add(_RA(fecha=_ahl2(), sucursal=SUC_ADM, empleado_nombre=_n, tipo='ENTRADA'))
    db.session.commit()
_cp2 = admin.post('/api/pos/abrir_mesa', json={'mesa': 'PP1', 'personas': 1}, headers=H).json['cuenta_id']
admin.post('/api/pos/capturar_item', json={'cuenta_id': _cp2, 'descripcion': 'CAFE SUCURSAL', 'precio': 55, 'cantidad': 1}, headers=H)
imprimir_cuenta(admin, _cp2, H)
_tot2 = admin.get(f'/api/pos/detalle_cuenta/{_cp2}').json['total_num']
_rpp = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': _cp2, 'tarjeta_debito': _tot2, 'propina': 20, 'idem': 'pp-1'}, headers=H)
check(_rpp.status_code == 200, 'cobro con tarjeta y propina')
d = admin.get('/api/propinas/dia').json
check(d['tarjeta'] >= 20 and {'ANA', 'BETO', 'CARLA'} <= set(d['trabajaron']), f'propinas con tarjeta del día y quiénes checaron ({d["tarjeta"]}, {d["trabajaron"]})')
r = admin.post('/api/propinas/repartir', json={'efectivo': 100, 'empleados': ['ANA', 'BETO', 'CARLA']}, headers=H)
rp = r.json.get('reparto', {})
check(r.status_code == 200 and abs(sum(x['monto'] for x in rp['reparto']) - rp['total']) < 0.005 and len(rp['reparto']) == 3,
      f'reparto parejo que suma exacto ({rp.get("reparto")}, total {rp.get("total")})')
r = cam1.post('/api/propinas/repartir', json={'efectivo': 50, 'empleados': ['ANA']}, headers=HS)
check(r.status_code == 403 and r.json.get('requiere_admin'), 'rehacer un reparto ya hecho pide clave de Admin o Gerente')
r2 = admin.post('/api/propinas/repartir', json={'efectivo': 0, 'empleados': ['ANA']}, headers=H)
check(r2.status_code == 200, 'Admin puede rehacer el reparto (es supervisor)')

# ---- Permisos por usuario ----
with app.app_context():
    from models import User as _U2
    _bid = _U2.query.filter_by(username='brayan').first().id
r = admin.get(f'/api/usuarios/{_bid}/permisos')
check(r.status_code == 200 and any(p['clave'] == 'mermas' and p['efectivo'] is False for p in r.json['permisos']), 'el cajero pide clave para mermas por defecto')
r = admin.post(f'/api/usuarios/{_bid}/permisos', json={'mermas': True, 'cancelar': False}, headers=H)
check(r.status_code == 200 and next(p for p in r.json['permisos'] if p['clave'] == 'mermas')['efectivo'] is True, 'Admin le da permiso de mermas a un cajero')
# cam1 ahora trabaja como BRAYAN (cambio con PIN más arriba)
r = cam1.post('/api/pos/registrar_merma', json={'insumo_nombre': 'PAN', 'cantidad': 1, 'motivo': 'CAIDO', 'costo_unitario': 5}, headers=HS)
check(r.status_code == 200, f'con su permiso propio registra la merma sin clave ({r.status_code})')
check(cam1.get(f'/api/usuarios/{_bid}/permisos').status_code == 403, 'solo Admin ve y cambia permisos')
admin.post(f'/api/usuarios/{_bid}/permisos', json={'mermas': None, 'cancelar': None}, headers=H)
check(next(p for p in admin.get(f'/api/usuarios/{_bid}/permisos').json['permisos'] if p['clave'] == 'mermas')['propio'] is None, 'volver al permiso general')
