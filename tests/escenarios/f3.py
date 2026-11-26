# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, cam1, H, tcj, check, token_de, db).
import json as _json
from models import (InsumoBodegaPro, StockSucursal, TraspasoSucursal, MovimientoAlmacen, MovimientoCajaPOS,
                    ArqueoTurnoPOS, esquema_faltante)

MATRIZ, C1 = 'Quiosco Morisco (Matriz)', 'Caminante 1'
qm = clientes['quiosco']
HQ = {'X-CSRFToken': token_de(qm.get('/pedidos_sucursal').get_data(as_text=True))}
HC1 = {'X-CSRFToken': token_de(cam1.get('/pedidos_sucursal').get_data(as_text=True))}
HJ = {'X-CSRFToken': tcj}

with app.app_context():
    har = InsumoBodegaPro(nombre='HARINA TRASPASO', categoria='COCINA | Otros', unidad='KG', stock_actual=50.0,
                          stock_minimo=1.0, costo_unitario=10.0, activo=True)
    db.session.add(har); db.session.commit(); ID_H = har.id
    db.session.add(StockSucursal(sucursal=MATRIZ, insumo_id=ID_H, stock_actual=20.0, stock_minimo=1.0)); db.session.commit()


def _st(suc):
    with app.app_context():
        st = StockSucursal.query.filter_by(sucursal=suc, insumo_id=ID_H).first()
        return None if st is None else round(st.stock_actual, 3)

# ---------- Traspasos ----------
d = qm.get('/api/traspasos?sucursal=' + MATRIZ).json
check(d['ok'] and MATRIZ not in d['destinos'] and C1 in d['destinos'], 'traspasos: destinos excluyen la propia sucursal')
check(clientes['brayan'].get('/api/traspasos?sucursal=' + MATRIZ).status_code == 403, 'cajero no gestiona traspasos')
check(qm.post('/api/traspasos', json={'origen': C1, 'destino': MATRIZ, 'insumo_id': ID_H, 'cantidad': 1}, headers=HQ).status_code == 403,
      'no se puede enviar desde otra sucursal')
check(qm.post('/api/traspasos', json={'origen': MATRIZ, 'destino': MATRIZ, 'insumo_id': ID_H, 'cantidad': 1}, headers=HQ).status_code == 400,
      'destino igual al origen rechazado')
check(qm.post('/api/traspasos', json={'origen': MATRIZ, 'destino': C1, 'insumo_id': ID_H, 'cantidad': 25}, headers=HQ).status_code == 400
      and _st(MATRIZ) == 20.0, 'stock insuficiente rechazado sin tocar el stock')
r = qm.post('/api/traspasos', json={'origen': MATRIZ, 'destino': C1, 'insumo_id': ID_H, 'cantidad': 8, 'nota': 'urgente'}, headers=HQ)
T1 = r.json['traspaso']['id']
check(r.status_code == 200 and _st(MATRIZ) == 12.0 and _st(C1) is None, 'enviar descuenta del origen (destino aún no suma)')
with app.app_context():
    check(MovimientoAlmacen.query.filter(MovimientoAlmacen.tipo == 'TRASPASO_SALIDA', MovimientoAlmacen.nota.like(f'Traspaso #{T1}:%')).count() == 1,
          'movimiento TRASPASO_SALIDA registrado')
    check(InsumoBodegaPro.query.get(ID_H).stock_actual == 50.0, 'traspaso entre sucursales no toca la Bodega Central')
check([t['id'] for t in cam1.get('/api/traspasos?sucursal=' + C1).json['por_recibir']] == [T1], 'destino lo ve en "Por recibir"')
check(qm.post(f'/api/traspasos/{T1}/recibir', json={'cantidad_recibida': 8}, headers=HQ).status_code == 403, 'el origen no puede recibir su propio envío')
check(cam1.post(f'/api/traspasos/{T1}/recibir', json={'cantidad_recibida': 9}, headers=HC1).status_code == 400, 'no se recibe más de lo enviado')
r = cam1.post(f'/api/traspasos/{T1}/recibir', json={'cantidad_recibida': 6}, headers=HC1)
check(r.status_code == 200 and r.json['faltante_regresado'] == 2.0 and _st(C1) == 6.0 and _st(MATRIZ) == 14.0,
      f'recepción parcial: destino suma 6 y los 2 faltantes regresan al origen ({_st(C1)}, {_st(MATRIZ)})')
check(cam1.post(f'/api/traspasos/{T1}/recibir', json={'cantidad_recibida': 1}, headers=HC1).status_code == 409, 'no se recibe dos veces')
r = qm.post('/api/traspasos', json={'origen': MATRIZ, 'destino': C1, 'insumo_id': ID_H, 'cantidad': 5}, headers=HQ)
T2 = r.json['traspaso']['id']
check(_st(MATRIZ) == 9.0, 'segundo envío descuenta 5')
r = cam1.post(f'/api/traspasos/{T2}/rechazar', json={'motivo': 'no lo pedimos'}, headers=HC1)
with app.app_context():
    t2 = TraspasoSucursal.query.get(T2)
    check(r.status_code == 200 and t2.estado == 'RECHAZADO' and 'no lo pedimos' in t2.nota and _st(MATRIZ) == 14.0 and _st(C1) == 6.0,
          'rechazo: todo regresa al origen y queda el motivo')
hist = {t['id']: t['estado'] for t in qm.get('/api/traspasos?sucursal=' + MATRIZ).json['historial']}
check(hist.get(T1) == 'RECIBIDO' and hist.get(T2) == 'RECHAZADO', 'historial del origen muestra ambos traspasos')
check('id="sec_traspasos"' in cam1.get('/pedidos_sucursal').get_data(as_text=True), 'pedidos_sucursal tiene la pestaña Traspasos')

# ---------- Catálogo de gastos y retiros por categoría ----------
d = clientes['brayan'].get('/api/gastos/catalogo').json
check(d['ok'] and 'HIELO' in d['categorias'] and len(d['denominaciones']) == 12, 'catálogo de gastos y denominaciones disponibles para caja')
r = clientes['brayan'].post('/api/pos/movimiento_caja', json={'tipo': 'RETIRO', 'monto': 80, 'concepto': 'bolsas de hielo',
                            'categoria': 'HIELO', 'clave_admin': 'admin12345'}, headers=HJ)
check(r.status_code == 200, 'retiro con categoría HIELO')
check(clientes['brayan'].post('/api/pos/movimiento_caja', json={'tipo': 'RETIRO', 'monto': 5, 'concepto': 'x', 'categoria': 'INVENTADA',
      'clave_admin': 'admin12345'}, headers=HJ).status_code == 400, 'categoría fuera del catálogo rechazada')
clientes['brayan'].post('/api/pos/movimiento_caja', json={'tipo': 'RETIRO', 'monto': 7, 'concepto': 'pantalla vieja', 'clave_admin': 'admin12345'}, headers=HJ)
clientes['brayan'].post('/api/pos/movimiento_caja', json={'tipo': 'DEPOSITO', 'monto': 50, 'concepto': 'fondo extra'}, headers=HJ)
with app.app_context():
    m_h = MovimientoCajaPOS.query.filter_by(concepto='BOLSAS DE HIELO').first()
    m_o = MovimientoCajaPOS.query.filter_by(concepto='PANTALLA VIEJA').first()
    m_d = MovimientoCajaPOS.query.filter_by(concepto='FONDO EXTRA').first()
    check(m_h.categoria_gasto == 'HIELO' and m_o.categoria_gasto == 'OTROS' and m_d.categoria_gasto is None,
          'sin categoría -> OTROS (pantallas viejas); depósitos sin categoría')
r = admin.post('/api/industrial/flujo_dinero', json={'sucursal': C1, 'tipo': 'RETIRO', 'monto': 300, 'concepto': 'tanque', 'categoria': 'GAS'}, headers=H)
check(r.status_code == 200, 'retiro desde el panel industrial con categoría GAS')
r = admin.post('/api/gastos/catalogo', json={'nombre': 'Fumigacion'}, headers=H)
check(r.status_code == 200 and 'FUMIGACION' in r.json['categorias'], 'admin agrega categoría')
check(admin.delete('/api/gastos/catalogo', json={'nombre': 'OTROS'}, headers=H).status_code == 400, 'OTROS no se puede quitar')
r = admin.delete('/api/gastos/catalogo', json={'nombre': 'FUMIGACION'}, headers=H)
check(r.status_code == 200 and 'FUMIGACION' not in r.json['categorias'], 'admin quita categoría')
check(clientes['brayan'].post('/api/gastos/catalogo', json={'nombre': 'X'}, headers=HJ).status_code == 403, 'caja no modifica el catálogo')
d = admin.get('/api/industrial/gastos').json
cats = {c['categoria']: c['monto'] for c in d['por_categoria']}
sucs = {c['sucursal']: c['monto'] for c in d['por_sucursal']}
check(d['ok'] and cats.get('HIELO') == 80.0 and cats.get('GAS') == 300.0 and sucs.get(C1, 0) >= 300.0,
      f'reporte de gastos por categoría y sucursal ({cats})')
d1 = admin.get('/api/industrial/gastos?sucursal=' + C1).json
check(all(g['sucursal'] == C1 for g in d1['gastos']) and 'HIELO' not in {c['categoria'] for c in d1['por_categoria']}, 'filtro por sucursal')
t = admin.get('/api/exportar/gastos').get_data(as_text=True)
check('HIELO' in t and 'GAS' in t and 'Categoria' in t, 'CSV de gastos')
check(clientes['brayan'].get('/api/industrial/gastos').status_code == 403, 'reporte de gastos solo admin')
h_ind = admin.get('/industrial').get_data(as_text=True)
check('id="sec_gastos"' in h_ind and 'id="fl_reg_cat"' in h_ind, 'panel industrial: pestaña Gastos y categoría en retiros')
h_pos = admin.get('/pos').get_data(as_text=True)
check('id="movCajaCategoria"' in h_pos and 'id="gridDenominaciones"' in h_pos, 'POS: categoría en retiros y conteo por denominaciones')

# ---------- Arqueo por denominaciones (Corte Z de Caminante 1) ----------
base = {'EF': 1000, 'TARJD': 0, 'TARJC': 0, 'TRANS': 0, 'VAL': 0, 'clave_admin': 'admin12345'}
r = cam1.post('/api/pos/cerrar_turno_arqueo', json=dict(base, denominaciones={'B500': 2, 'M10': 3}), headers=HC1)
check(r.status_code == 400 and 'no coincide' in r.json.get('msg', ''), 'efectivo distinto al conteo por denominación se rechaza')
r = cam1.post('/api/pos/cerrar_turno_arqueo', json=dict(base, EF=1030, denominaciones={'B999': 1}), headers=HC1)
check(r.status_code == 400, 'denominación desconocida rechazada')
r = cam1.post('/api/pos/cerrar_turno_arqueo', json=dict(base, EF=1030, denominaciones={'B500': 2, 'M10': 3}), headers=HC1)
check(r.status_code == 200 and r.json['declarado'] == '1030.00' and [x['clave'] for x in r.json['denominaciones']] == ['B500', 'M10'],
      f"Corte Z con $1,030 contados en billetes y monedas ({r.status_code} {r.get_data(as_text=True)[:120]})")
abrir_turnos()
with app.app_context():
    arq = ArqueoTurnoPOS.query.filter_by(sucursal=C1).order_by(ArqueoTurnoPOS.id.desc()).first()
    check(_json.loads(arq.denominaciones_json) == {'B500': 2, 'M10': 3} and arq.ef_declarado == 1030.0, 'desglose guardado en el arqueo')
h = cam1.get('/api/pos/historial_arqueos').json
check(any(a.get('denominaciones') for a in h.get('arqueos', [])), 'historial de arqueos incluye el desglose')

with app.app_context():
    check(esquema_faltante(db.engine) == [], 'tablas y columnas de la Fase 3 en ESQUEMA_REQUERIDO y creadas')
