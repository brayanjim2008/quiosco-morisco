# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, alm, cam1, HA, check, db).
# Fase 5: órdenes por proveedor, cuentas por pagar con vencimientos y caducidades por lote.
from datetime import timedelta as _td5
from models import (InsumoBodegaPro as _Ins5, ProveedorAlmacen as _Prov5, LoteInsumoPOS as _Lote5,
                    ahora_local as _ah5)

with app.app_context():
    _a = _Ins5(nombre='LECHE F5', categoria='LACTEOS', unidad='LT', stock_actual=0, stock_minimo=10, costo_unitario=20, activo=True)
    _b = _Ins5(nombre='PAN F5', categoria='PANADERIA', unidad='PZA', stock_actual=0, stock_minimo=20, costo_unitario=5, activo=True)
    db.session.add_all([_a, _b])
    db.session.commit()
    LECHE, PAN = _a.id, _b.id

alm.post('/api/almacen/proveedor', json={'nombre': 'LACTEOS F5', 'dias_credito': 15}, headers=HA)
alm.post('/api/almacen/proveedor', json={'nombre': 'PANADERIA F5', 'dias_credito': 0, 'saldo_pendiente': 100}, headers=HA)
with app.app_context():
    PL = _Prov5.query.filter_by(nombre='LACTEOS F5').first().id
    PP = _Prov5.query.filter_by(nombre='PANADERIA F5').first().id

# proveedor habitual y una orden por proveedor
check(alm.post('/api/insumo/proveedor', json={'insumo_id': LECHE, 'proveedor_id': PL}, headers=HA).status_code == 200, 'guardar proveedor habitual del insumo')
sug = {s['insumo_id']: s for s in alm.get('/api/ordenes_compra').json['sugeridos']}
check(sug[LECHE]['proveedor_id'] == PL, 'la compra sugerida trae el proveedor habitual')
r = alm.post('/api/ordenes_compra/por_proveedor', json={'lineas': [
    {'insumo_id': LECHE, 'cantidad': 20, 'proveedor_id': PL}, {'insumo_id': PAN, 'cantidad': 40, 'proveedor_id': PP}]}, headers=HA)
check(r.status_code == 200 and len(r.json['ordenes']) == 2, f'una orden por proveedor con un clic ({r.json})')
oc_leche = next(o['id'] for o in r.json['ordenes'] if o['proveedor'] == 'LACTEOS F5')

# recibir con caducidad -> cargo con vencimiento a 15 días + lote
alm.post(f'/api/ordenes_compra/{oc_leche}/enviar', json={}, headers=HA)
det = next(o for o in alm.get('/api/ordenes_compra').json['ordenes'] if o['id'] == oc_leche)
cad = (_ah5().date() + _td5(days=3)).isoformat()
r = alm.post(f'/api/ordenes_compra/{oc_leche}/recibir', json={'lineas': [
    {'id': det['lineas'][0]['id'], 'recibido': 20, 'costo_real': 400, 'caducidad': cad}]}, headers=HA)
check(r.status_code == 200, f'recibir orden con caducidad ({r.status_code})')
cxp = {p['id']: p for p in alm.get('/api/cxp').json['proveedores']}
check(cxp[PL]['saldo'] == 400 and cxp[PL]['vencido'] == 0 and cxp[PL]['proximo_vence'],
      f'cuenta por pagar con 15 días de crédito: debe 400, nada vencido ({cxp[PL]})')
check(cxp[PP]['saldo'] == 100 and cxp[PP]['vencido'] == 100, f'saldo inicial de contado sale vencido ({cxp[PP]})')
r = alm.post('/api/cxp/abono', json={'proveedor_id': PL, 'monto': 500}, headers=HA)
check(r.status_code == 400, 'no se puede pagar más de lo que se debe')
r = alm.post('/api/cxp/abono', json={'proveedor_id': PL, 'monto': 150, 'forma_pago': 'TRANSFERENCIA', 'referencia': 'F-123'}, headers=HA)
check(r.status_code == 200 and r.json['saldo'] == 250, 'pago parcial al proveedor')
movs = alm.get(f'/api/cxp/{PL}/movimientos').json['movimientos']
check([m['tipo'] for m in movs] == ['ABONO', 'CARGO'] and movs[0]['referencia'] == 'F-123', 'historial de cargos y pagos')
check(cam1.get('/api/cxp').status_code == 403, 'la caja no ve cuentas por pagar')

# caducidades
lotes = alm.get('/api/lotes?dias=7').json['lotes']
lote = next(l for l in lotes if l['insumo_id'] == LECHE)
check(lote['dias'] == 3 and lote['cantidad'] == 20, f'el lote aparece por caducar en 3 días ({lote})')
with app.app_context():
    db.session.add(_Lote5(insumo_id=PAN, insumo_nombre='PAN F5', unidad='PZA', cantidad=5,
                          caducidad=_ah5().date() - _td5(days=1), recibido=_ah5()))
    db.session.commit()
alm.get('/api/lotes?dias=7')
check(any(a['tipo'] == 'CADUCADO' and 'PAN F5' in a['texto'] for a in admin.get('/api/alertas').json['alertas']),
      'un lote caducado manda alerta al dueño')
with app.app_context():
    stock_antes = _Ins5.query.get(LECHE).stock_actual
r = alm.post(f"/api/lotes/{lote['id']}/cerrar", json={'accion': 'MERMA', 'cantidad': 4}, headers=HA)
with app.app_context():
    check(r.status_code == 200 and abs(_Ins5.query.get(LECHE).stock_actual - (stock_antes - 4)) < 0.001 and _Lote5.query.get(lote['id']).estado == 'MERMA',
          'tirar lo caducado descuenta del stock y queda como merma')
check(alm.post(f"/api/lotes/{lote['id']}/cerrar", json={'accion': 'USADO'}, headers=HA).status_code == 409, 'un lote cerrado no se cierra dos veces')
r = alm.post('/api/lotes', json={'insumo_id': PAN, 'cantidad': 10, 'caducidad': '2030-01-01'}, headers=HA)
check(r.status_code == 200, 'registrar caducidad a mano')
h = alm.get('/almacen_pro').get_data(as_text=True)
check('id="sec_caducidad"' in h and 'ocCrearPorProveedor' in h and 'id="cxpTotales"' in h, 'Bodega: caducidades, órdenes por proveedor y cuentas por pagar')
