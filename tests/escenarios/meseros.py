# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, login, H, check, token_de).
# Regla de la jefa: cada mesero ve y opera solo sus cuentas; las de otro se ven ocupadas pero sin datos.
from models import CuentaPOS as _Cta

paola = clientes['paola']
daniel = login('daniel', 'mesero12345')
Hp = {'X-CSRFToken': token_de(paola.get('/mesero_dashboard').get_data(as_text=True))}
Hd = {'X-CSRFToken': token_de(daniel.get('/mesero_dashboard').get_data(as_text=True))}

r = paola.post('/api/pos/abrir_mesa', json={'mesa': 'MSR1', 'personas': 2, 'mesero': 'DANIEL'}, headers=Hp)
check(r.status_code == 200 and r.json.get('ok'), 'mesera abre su mesa')
cta_paola = r.json.get('cuenta_id')
with app.app_context():
    check(_Cta.query.get(cta_paola).mesero == 'PAOLA', 'la cuenta queda a nombre de quien la abrió (no se puede abrir a nombre de otro)')

r = daniel.get(f'/api/pos/detalle_cuenta/{cta_paola}')
check(r.status_code == 403, 'otro mesero NO puede ver el detalle de la cuenta')
r = daniel.post('/api/pos/capturar_item', json={'cuenta_id': cta_paola, 'descripcion': 'X', 'precio': 10, 'cantidad': 1,
                'clave': '09999', 'area_impresion': 'COCINA'}, headers=Hd)
check(r.status_code == 403, 'otro mesero NO puede capturar en la cuenta')
r = daniel.post('/api/pos/solicitar_cuenta/%d' % cta_paola, json={}, headers=Hd)
check(r.status_code == 403, 'otro mesero NO puede pedir la cuenta')
check(paola.get(f'/api/pos/detalle_cuenta/{cta_paola}').status_code == 200, 'la dueña sí ve su cuenta')

t9 = next(t for t in daniel.get('/api/pos/mesas_tablet_v2').json['tarjetas'] if t['codigo'] == 'MSR1')
check(t9['ocupada'] and t9['ajena'] and t9['cuenta_id'] is None and t9['total'] == '0.00',
      'en la tablet del otro mesero la mesa sale ocupada, sin id ni total')
t9p = next(t for t in paola.get('/api/pos/mesas_tablet_v2').json['tarjetas'] if t['codigo'] == 'MSR1')
check(not t9p['ajena'] and t9p['cuenta_id'] == cta_paola, 'en la tablet de la dueña la mesa es suya')
r = daniel.post('/api/pos/abrir_mesa', json={'mesa': 'MSR1', 'personas': 2}, headers=Hd)
check(not (r.json or {}).get('ok'), 'no se puede abrir otra cuenta en una mesa ocupada por otro mesero')

ids_venta_d = [c['id'] for k in ('abiertas', 'por_pagar', 'pagadas') for c in (daniel.get('/api/pos/mi_venta').json.get(k) or [])]
check(cta_paola not in ids_venta_d, 'Mi Venta del otro mesero no incluye cuentas ajenas')

r = paola.post('/api/pos/cambiar_mesero', json={'cuenta_id': cta_paola, 'nuevo_mesero': 'DANIEL'}, headers=Hp)
check(r.status_code == 403, 'un mesero no puede pasarse cuentas por su cuenta (lo hace caja)')
r = admin.post('/api/pos/cambiar_mesero', json={'cuenta_id': cta_paola, 'nuevo_mesero': 'DANIEL'}, headers=H)
check(r.status_code == 200, 'caja/gerencia sí cambia el mesero')
check(daniel.get(f'/api/pos/detalle_cuenta/{cta_paola}').status_code == 200 and
      paola.get(f'/api/pos/detalle_cuenta/{cta_paola}').status_code == 403, 'tras el cambio, la cuenta pasa al nuevo mesero')
check(admin.get(f'/api/pos/detalle_cuenta/{cta_paola}').status_code == 200, 'caja sigue viendo todas las cuentas')
admin.post('/api/pos/cancelar_cuenta_abierta', json={'cuenta_id': cta_paola, 'motivo': 'prueba'}, headers=H)

# ---- Aviso "platillo listo" en la tablet del mesero ----
r = paola.post('/api/pos/abrir_mesa', json={'mesa': 'LST1', 'personas': 1}, headers=Hp)
_cl = r.json['cuenta_id']
paola.post('/api/pos/capturar_item', json={'cuenta_id': _cl, 'descripcion': 'MOLLETES', 'precio': 80, 'cantidad': 2,
           'clave': '01', 'area_impresion': 'COCINA'}, headers=Hp)
paola.post(f'/api/pos/enviar_comanda/{_cl}', json={}, headers=Hp)
_idl = [i['id'] for i in paola.get(f'/api/pos/detalle_cuenta/{_cl}').json['items'] if i['descripcion'] == 'MOLLETES']
check(not [x for x in paola.get('/api/kds/listos').json['listos'] if x['id'] in _idl], 'antes de que cocina lo marque, no hay aviso')
admin.post('/api/kds/estado', json={'ids': _idl, 'estado': 'LISTO'}, headers=H)
lp = paola.get('/api/kds/listos').json['listos']
check(any(x['id'] in _idl and x['mesa'] == 'LST1' for x in lp), 'la mesera ve el aviso de su platillo listo')
check(not [x for x in daniel.get('/api/kds/listos').json['listos'] if x['id'] in _idl], 'otro mesero no ve los platillos de mesas ajenas')
paola.post('/api/kds/estado', json={'ids': _idl, 'estado': 'ENTREGADO'}, headers=Hp)
check(not [x for x in paola.get('/api/kds/listos').json['listos'] if x['id'] in _idl], 'al entregarlo el aviso desaparece')
