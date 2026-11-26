# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, cam1, alm, H, HA, tcj, check, token_de, db).
from datetime import timedelta as _td
from models import (InsumoBodegaPro, StockSucursal, MovimientoAlmacen, ProveedorAlmacen, RequerimientoBodega,
                    OrdenCompra, ahora_local as _ahora, esquema_faltante)

HJ = {'X-CSRFToken': tcj}
HC1 = {'X-CSRFToken': token_de(cam1.get('/pedidos_sucursal').get_data(as_text=True))}


def _ins(nombre, unidad, stock, minimo, costo):
    with app.app_context():
        i = InsumoBodegaPro(nombre=nombre, categoria='BARRA | Insumos', unidad=unidad, stock_actual=stock,
                            stock_minimo=minimo, costo_unitario=costo, activo=True)
        db.session.add(i); db.session.commit()
        return i.id


def _i(iid):
    with app.app_context():
        i = InsumoBodegaPro.query.get(iid)
        return round(i.stock_actual, 3), round(i.costo_unitario, 4)


def _ss(suc, iid):
    with app.app_context():
        st = StockSucursal.query.filter_by(sucursal=suc, insumo_id=iid).first()
        return None if st is None else round(st.stock_actual, 3)

# ---------- Presentaciones de compra ----------
REF = _ins('REFRESCO OC', 'PZA', 2.0, 10.0, 0.0)
r = alm.post('/api/presentaciones', json={'insumo_id': REF, 'nombre': 'caja 24', 'factor': 24}, headers=HA)
P_CAJA = r.json.get('id')
check(r.status_code == 200 and P_CAJA, 'almacén crea presentación CAJA 24')
check(alm.post('/api/presentaciones', json={'insumo_id': REF, 'nombre': 'CAJA 24', 'factor': 24}, headers=HA).status_code == 400, 'presentación duplicada rechazada')
check(alm.post('/api/presentaciones', json={'insumo_id': REF, 'nombre': 'X', 'factor': 0}, headers=HA).status_code == 400, 'factor 0 rechazado')
check(clientes['brayan'].post('/api/presentaciones', json={'insumo_id': REF, 'nombre': 'Y', 'factor': 2}, headers=HJ).status_code == 403,
      'caja no administra presentaciones')
r = alm.post('/api/almacen/movimiento', json={'insumo_id': REF, 'tipo': 'ENTRADA_COMPRA', 'presentacion_id': P_CAJA,
             'cantidad_presentaciones': 3, 'costo_total': 720, 'proveedor': 'COCA'}, headers=HA)
check(r.status_code == 200 and r.json['cantidad'] == 72.0 and _i(REF) == (74.0, 10.0),
      f'compra 3 cajas x 24 = 72 pzas; costo directo $720/72 = $10 ({_i(REF)})')
with app.app_context():
    check(MovimientoAlmacen.query.filter(MovimientoAlmacen.insumo_nombre == 'REFRESCO OC', MovimientoAlmacen.nota.like('%3 x CAJA 24%')).first() is not None,
          'el movimiento anota la presentación')
OTRO = _ins('OTRO INSUMO OC', 'KG', 1.0, 1.0, 1.0)
check(alm.post('/api/almacen/movimiento', json={'insumo_id': OTRO, 'tipo': 'ENTRADA_COMPRA', 'presentacion_id': P_CAJA,
      'cantidad_presentaciones': 1, 'costo_total': 5}, headers=HA).status_code == 400, 'presentación de otro insumo rechazada')

# ---------- Sub-recetas (insumos elaborados) ----------
TOM = _ins('TOMATE OC', 'KG', 10.0, 1.0, 20.0)
CHI = _ins('CHILE OC', 'KG', 2.0, 0.5, 50.0)
SAL = _ins('SALSA DE LA CASA', 'LT', 0.0, 1.0, 0.0)
for ing, cant in ((TOM, 0.8), (CHI, 0.1)):
    check(alm.post('/api/elaborados/receta', json={'elaborado_id': SAL, 'insumo_id': ing, 'cantidad': cant}, headers=HA).status_code == 200,
          f'ingrediente {ing} agregado a la salsa')
check(alm.post('/api/elaborados/receta', json={'elaborado_id': SAL, 'insumo_id': SAL, 'cantidad': 1}, headers=HA).status_code == 400,
      'un elaborado no puede llevarse a sí mismo')
check(alm.post('/api/elaborados/receta', json={'elaborado_id': TOM, 'insumo_id': SAL, 'cantidad': 1}, headers=HA).status_code == 400,
      'ciclo detectado (tomate llevaría salsa que lleva tomate)')
with app.app_context():
    check(InsumoBodegaPro.query.get(TOM).es_elaborado in (False, None), 'el intento de ciclo no marca al tomate como elaborado')
els = {e['id']: e for e in cam1.get('/api/elaborados').json['elaborados']}
check(SAL in els and els[SAL]['costo_receta'] == 21.0, f"costo de receta por litro = 0.8x20 + 0.1x50 = $21 ({els.get(SAL, {}).get('costo_receta')})")
check(cam1.post('/api/elaborados/receta', json={'elaborado_id': SAL, 'insumo_id': TOM, 'cantidad': 1}, headers=HC1).status_code == 403,
      'sucursal no edita recetas de elaborados')
r = alm.post('/api/elaborados/producir', json={'elaborado_id': SAL, 'cantidad': 5, 'ubicacion': 'BODEGA'}, headers=HA)
check(r.status_code == 200 and r.json['costo_total'] == 105.0 and _i(TOM)[0] == 6.0 and _i(CHI)[0] == 1.5 and _i(SAL) == (5.0, 21.0),
      f'producir 5 LT en bodega descuenta ingredientes y la salsa queda a $21/LT ({_i(TOM)}, {_i(CHI)}, {_i(SAL)})')
with app.app_context():
    check(MovimientoAlmacen.query.filter_by(tipo='PRODUCCION', insumo_nombre='SALSA DE LA CASA').count() == 1 and
          MovimientoAlmacen.query.filter(MovimientoAlmacen.tipo == 'CONSUMO_PRODUCCION', MovimientoAlmacen.nota.like('%SALSA DE LA CASA%')).count() == 2,
          'movimientos PRODUCCION y CONSUMO_PRODUCCION')
r = alm.post('/api/elaborados/producir', json={'elaborado_id': SAL, 'cantidad': 30, 'ubicacion': 'BODEGA'}, headers=HA)
check(r.status_code == 409 and any('TOMATE OC' in f for f in r.json['faltantes']) and _i(TOM)[0] == 6.0,
      'sin ingredientes suficientes avisa los faltantes y no toca nada')
check(alm.post('/api/elaborados/producir', json={'elaborado_id': TOM, 'cantidad': 1, 'ubicacion': 'BODEGA'}, headers=HA).status_code == 400,
      'solo se producen insumos elaborados')
# Producción en sucursal
r = cam1.post('/api/elaborados/producir', json={'elaborado_id': SAL, 'cantidad': 2, 'ubicacion': 'Caminante 1'}, headers=HC1)
check(r.status_code == 409, 'en sucursal sin ingredientes locales avisa faltantes')
with app.app_context():
    db.session.add_all([StockSucursal(sucursal='Caminante 1', insumo_id=TOM, stock_actual=5.0, stock_minimo=1.0),
                        StockSucursal(sucursal='Caminante 1', insumo_id=CHI, stock_actual=1.0, stock_minimo=0.1)])
    db.session.commit()
r = cam1.post('/api/elaborados/producir', json={'elaborado_id': SAL, 'cantidad': 2, 'ubicacion': 'Caminante 1'}, headers=HC1)
check(r.status_code == 200 and _ss('Caminante 1', TOM) == 3.4 and _ss('Caminante 1', CHI) == 0.8 and _ss('Caminante 1', SAL) == 2.0
      and _i(TOM)[0] == 6.0 and _i(SAL)[0] == 5.0, 'producción en sucursal usa y suma solo stock local')
check(cam1.post('/api/elaborados/producir', json={'elaborado_id': SAL, 'cantidad': 1, 'ubicacion': 'BODEGA'}, headers=HC1).status_code == 403,
      'sucursal no produce en bodega')

# ---------- Órdenes de compra ----------
AGU = _ins('AGUA OC', 'PZA', 1.0, 5.0, 8.0)
with app.app_context():
    db.session.add(RequerimientoBodega(fecha=_ahora() - _td(days=2), sucursal='Caminante 1', area='BARRA', insumo_id=AGU, insumo_nombre='AGUA OC',
                                       categoria='BARRA | Insumos', cantidad=28, cantidad_entregada=28, unidad='PZA', estado_bodega='ENTREGADO'))
    db.session.commit()
d = alm.get('/api/ordenes_compra').json
sug = {s['insumo_id']: s for s in d['sugeridos']}
check(AGU in sug and sug[AGU]['consumo_diario'] == 2.0 and sug[AGU]['sugerido'] == 13.0,
      f"sugerido por consumo: 28 en 14 días = 2/día x 7 = 14 - 1 en stock = 13 ({sug.get(AGU)})")
check(REF not in sug and SAL not in sug, 'no sugiere lo que tiene stock ni los elaborados')
alm.post('/api/almacen/proveedor', json={'nombre': 'AGUAS DEL VALLE', 'telefono': '967 555 1234', 'categoria': 'BEBIDAS', 'saldo_pendiente': 0}, headers=HA)
with app.app_context():
    PROV = ProveedorAlmacen.query.filter_by(nombre='AGUAS DEL VALLE').first().id
r = alm.post('/api/ordenes_compra', json={'proveedor_id': PROV, 'desde_sugeridos': True, 'nota': 'urgente'}, headers=HA)
OC = r.json['orden']
linea_agua = next(l for l in OC['lineas'] if l['insumo_id'] == AGU)
check(r.status_code == 200 and OC['estado'] == 'BORRADOR' and linea_agua['cantidad'] == 13.0 and linea_agua['costo_estimado'] == 104.0,
      'orden desde sugeridos: 13 pzas, costo estimado $104')
P_PAQ = alm.post('/api/presentaciones', json={'insumo_id': AGU, 'nombre': 'PAQUETE 6', 'factor': 6}, headers=HA).json['id']
r = alm.post(f"/api/ordenes_compra/{OC['id']}/lineas", json={'lineas': [{'insumo_id': AGU, 'cantidad': 2, 'presentacion_id': P_PAQ, 'costo_estimado': 90}]}, headers=HA)
check(r.status_code == 200 and [(l['cantidad'], l['presentacion_nombre']) for l in r.json['orden']['lineas']] == [(12.0, 'PAQUETE 6')]
      and r.json['orden']['total_estimado'] == 90.0, 'editar orden: 2 paquetes de 6 = 12 pzas, $90')
r = alm.post(f"/api/ordenes_compra/{OC['id']}/enviar", headers=HA)
check(r.status_code == 200 and r.json['orden']['estado'] == 'ENVIADA' and 'wa.me/529675551234' in r.json['wa_url'] and 'AGUA OC' in r.json['texto'],
      'enviar: WhatsApp al proveedor con la orden')
check(alm.post(f"/api/ordenes_compra/{OC['id']}/lineas", json={'lineas': []}, headers=HA).status_code == 409, 'una orden enviada ya no se edita')
lid = r.json['orden']['lineas'][0]['id']
r = alm.post(f"/api/ordenes_compra/{OC['id']}/recibir", json={'lineas': [{'id': lid, 'recibido': 2, 'costo_real': 96}]}, headers=HA)
# existencia 1 a $8 + compra 12 por $96 -> (1x8 + 96) / 13 = 8.0
check(r.status_code == 200 and r.json['total_real'] == 96.0 and _i(AGU) == (13.0, 8.0), f'recibir suma 12 pzas a bodega con costo promedio ({_i(AGU)})')
with app.app_context():
    check(ProveedorAlmacen.query.get(PROV).saldo_pendiente == 96.0, 'lo recibido se suma a la cuenta por pagar del proveedor')
    check(MovimientoAlmacen.query.filter(MovimientoAlmacen.nota.like(f"OC #{OC['id']}%")).count() == 1, 'entrada de almacén ligada a la OC')
check(alm.post(f"/api/ordenes_compra/{OC['id']}/recibir", json={}, headers=HA).status_code == 409, 'no se recibe dos veces')
check(alm.post(f"/api/ordenes_compra/{OC['id']}/cancelar", headers=HA).status_code == 409, 'una orden recibida no se cancela')
r = alm.post('/api/ordenes_compra', json={'lineas': [{'insumo_id': AGU, 'cantidad': 5}]}, headers=HA)
oc2 = r.json['orden']['id']
check(alm.post(f'/api/ordenes_compra/{oc2}/cancelar', headers=HA).status_code == 200, 'cancelar orden en borrador')
check(alm.post('/api/ordenes_compra', json={'lineas': [{'insumo_id': AGU, 'cantidad': 0}]}, headers=HA).status_code == 400, 'orden con todo en 0 rechazada')
t = alm.get(f"/api/exportar/orden_compra/{OC['id']}").get_data(as_text=True)
check('AGUA OC' in t and 'PAQUETE 6' in t and 'Costo_Real' in t, 'CSV de la orden de compra')
check(clientes['brayan'].get('/api/ordenes_compra').status_code == 403 and cam1.get('/api/ordenes_compra').status_code == 403,
      'órdenes de compra solo admin/almacén')
with app.app_context():
    check(OrdenCompra.query.count() >= 2 and esquema_faltante(db.engine) == [], 'tablas de la Fase 4b en ESQUEMA_REQUERIDO y creadas')

# ---------- Pantallas ----------
h_alm = alm.get('/almacen_pro').get_data(as_text=True)
check('id="sec_produccion"' in h_alm and 'id="sec_ordenes"' in h_alm and 'id="mov_pres"' in h_alm and 'id="re_elab"' in h_alm,
      'Bodega: pestañas Producción y Órdenes de compra, y compra por presentación')
h_suc = cam1.get('/pedidos_sucursal').get_data(as_text=True)
check('id="sec_produccion"' in h_suc and 'id="re_elab"' not in h_suc and 'id="pp_insumo"' not in h_suc and '"Caminante 1"' in h_suc,
      'Sucursal: puede producir pero no edita recetas ni presentaciones')
