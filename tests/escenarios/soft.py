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
r = cam1.post('/api/pos/pagar_cuenta', json={'cuenta_id': c1, 'efectivo': 100, 'idem': 'soft-c1'}, headers=HS)
check(r.status_code == 200, f'cobro cuenta 1 ($100) ({r.status_code})')

c2 = _abrir_s('SFT2', 1)
_cap_s(c2, 'LATTE PRUEBA', 65, 'BARRA')
cam1.post('/api/pos/descuento_autorizado', json={'cuenta_id': c2, 'porcentaje': 50, 'clave_admin': CLAVE_S}, headers=HS)
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

r = cam1.post('/api/pos/cerrar_turno_arqueo', json=dict(BASE_Z, EF=130), headers=HS)
j = r.json or {}
decl = {x['forma']: x for x in j.get('declaracion', [])}
check(r.status_code == 200 and j.get('corte', {}).get('detalle', {}).get('ventas_con_imp') == '132.50'
      and decl.get('EFECTIVO', {}).get('diferencia') == '-2.50' and len(decl) == 5,
      f'Corte Z trae el corte completo y la declaración por forma de pago ({decl.get("EFECTIVO")})')

h_pos = admin.get('/pos').get_data(as_text=True)
check('class="tbl-canc"' in h_pos and 'id="descRapidos"' in h_pos and 'function textoCorteSoft' in h_pos,
      'POS: cancelación en tabla, % rápidos en descuento y corte estilo Soft')
