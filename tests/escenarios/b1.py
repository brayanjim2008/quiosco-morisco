# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, cam1, H, check, login, token_de, db).
from datetime import timedelta as _td
from models import (InsumoBodegaPro, StockSucursal, MovimientoAlmacen, BitacoraPOS, ConteoInventario,
                    ConteoInventarioDetalle, esquema_faltante, ahora_local as _ahora, ESQUEMA_REQUERIDO)

with app.app_context():
    az = InsumoBodegaPro(nombre='AZUCAR CONTEO', categoria='BARRA | Insumos', unidad='KG', stock_actual=10.0, stock_minimo=1.0, costo_unitario=20.0, activo=True)
    va = InsumoBodegaPro(nombre='VASOS CONTEO', categoria='BARRA | Desechables', unidad='PZA', stock_actual=100.0, stock_minimo=10.0, costo_unitario=2.0, activo=True)
    le = InsumoBodegaPro(nombre='LECHE CONTEO', categoria='BARRA | Refrescos y leche', unidad='LT', stock_actual=40.0, stock_minimo=5.0, costo_unitario=30.0, activo=True)
    db.session.add_all([az, va, le]); db.session.commit()
    ID_AZ, ID_VA, ID_LE = az.id, va.id, le.id
    db.session.add_all([StockSucursal(sucursal='Caminante 1', insumo_id=ID_AZ, stock_actual=50.0, stock_minimo=1.0),
                        StockSucursal(sucursal='Caminante 1', insumo_id=ID_LE, stock_actual=10.0, stock_minimo=1.0)])
    db.session.commit()

alm = login('almacen', 'almacen12345')
t_alm = token_de(alm.get('/almacen_pro').get_data(as_text=True))
HA = {'X-CSRFToken': t_alm}
t_cam = token_de(cam1.get('/pedidos_sucursal').get_data(as_text=True))
HC = {'X-CSRFToken': t_cam}

def _stock(iid):
    with app.app_context():
        return InsumoBodegaPro.query.get(iid).stock_actual

def _stock_suc(suc, iid):
    with app.app_context():
        st = StockSucursal.query.filter_by(sucursal=suc, insumo_id=iid).first()
        return None if st is None else st.stock_actual

# ---------- Permisos ----------
check(clientes['brayan'].get('/api/conteos?ubicacion=BODEGA').status_code == 403, 'cajero no accede al conteo de bodega')
check(cam1.get('/api/conteos?ubicacion=BODEGA').status_code == 403, 'sucursal no accede al conteo de bodega')
check(cam1.get('/api/conteos?ubicacion=' + 'Quiosco Morisco (Matriz)').status_code == 403, 'sucursal no accede al conteo de otra sucursal')
check(alm.get('/api/conteos?ubicacion=Caminante 1').status_code == 403, 'almacén no accede al conteo de una sucursal')
check(admin.get('/api/conteos?ubicacion=Marte').status_code == 403, 'ubicación inválida rechazada')
check(admin.get('/api/conteos?ubicacion=Caminante 2').status_code == 200, 'admin accede a cualquier ubicación')

# ---------- Bodega: borrador -> aplicar ----------
d = alm.get('/api/conteos?ubicacion=BODEGA').json
check(d['ok'] and d['borrador'] is None, 'sin conteo en curso al inicio')
r = alm.post('/api/conteos/iniciar', json={'ubicacion': 'BODEGA'}, headers=HA)
c = r.json['conteo']; CID = c['id']
lin = {l['insumo_id']: l for l in c['lineas']}
check(c['estado'] == 'BORRADOR' and lin[ID_AZ]['teorico'] == 10.0 and lin[ID_AZ]['contado'] is None and c['capturadas'] == 0,
      'iniciar crea borrador con foto del teórico y nada capturado')
r = alm.post('/api/conteos/iniciar', json={'ubicacion': 'BODEGA'}, headers=HA)
check(r.json['continuado'] and r.json['conteo']['id'] == CID, 'iniciar de nuevo continúa el mismo borrador (uno por ubicación)')
r = alm.post(f'/api/conteos/{CID}/capturar', json={'lineas': [{'insumo_id': ID_AZ, 'contado': 8}, {'insumo_id': ID_VA, 'contado': '105'}]}, headers=HA)
check(r.json['ok'] and r.json['guardadas'] == 2 and r.json['conteo']['capturadas'] == 2, 'guardar avance del borrador')
check(alm.post(f'/api/conteos/{CID}/capturar', json={'lineas': [{'insumo_id': ID_VA, 'contado': -1}]}, headers=HA).status_code == 400,
      'cantidad negativa rechazada')
# Mientras contaban se vendió 1 kg de azúcar: el teórico al aplicar debe ser 9 (no la foto de 10)
with app.app_context():
    InsumoBodegaPro.query.get(ID_AZ).stock_actual = 9.0; db.session.commit()
le_antes = _stock(ID_LE)
r = alm.post(f'/api/conteos/{CID}/aplicar', json={}, headers=HA)
# azúcar 8 - 9 = -1 x $20 = -20 ; vasos 105 - 100 = +5 x $2 = +10 ; Σ|dif| = 30
check(r.status_code == 200 and r.json['ajustes'] == 2 and r.json['valor_abs_total'] == 30.0,
      f"aplicar ajusta 2 líneas con Σ|dif| $30 ({r.status_code} {r.json.get('valor_abs_total')})")
check(_stock(ID_AZ) == 8.0 and _stock(ID_VA) == 105.0, 'el stock real queda igual a lo contado')
check(_stock(ID_LE) == le_antes, 'insumo no capturado NO se toca (no se pone en 0)')
with app.app_context():
    l_az = ConteoInventarioDetalle.query.filter_by(conteo_id=CID, insumo_id=ID_AZ).first()
    check(l_az.teorico == 9.0 and l_az.diferencia == -1.0 and l_az.valor_diferencia == -20.0,
          'el teórico se relee al aplicar (ventas durante el conteo)')
    movs = MovimientoAlmacen.query.filter_by(tipo='AJUSTE_CONTEO').filter(MovimientoAlmacen.nota.like(f'%Conteo #{CID}:%')).all()
    check(sorted(m.cantidad for m in movs) == [-1.0, 5.0], 'movimientos AJUSTE_CONTEO solo por líneas con diferencia')
    check(ConteoInventario.query.get(CID).estado == 'APLICADO', 'conteo queda APLICADO')
check(alm.post(f'/api/conteos/{CID}/capturar', json={'lineas': [{'insumo_id': ID_AZ, 'contado': 1}]}, headers=HA).status_code == 409,
      'no se puede editar un conteo aplicado')
check(alm.post(f'/api/conteos/{CID}/aplicar', json={}, headers=HA).status_code == 409, 'no se puede aplicar dos veces')

# ---------- CSV ----------
r = alm.get(f'/api/exportar/conteo/{CID}')
csv_txt = r.get_data(as_text=True)
check(r.status_code == 200 and 'text/csv' in r.headers['Content-Type'] and 'AZUCAR CONTEO' in csv_txt
      and 'No capturado' in csv_txt and 'Valor_Diferencia' in csv_txt and f'Conteo_{CID}_BODEGA' in r.headers.get('Content-Disposition', ''),
      'exporta CSV del conteo con capturados y no capturados')
check(clientes['brayan'].get(f'/api/exportar/conteo/{CID}').status_code == 403, 'cajero no exporta conteos')

# ---------- Sucursal: tope $500 con diferencias ABSOLUTAS ----------
r = cam1.post('/api/conteos/iniciar', json={'ubicacion': 'Caminante 1'}, headers=HC)
SID = r.json['conteo']['id']
lin = {l['insumo_id']: l for l in r.json['conteo']['lineas']}
check(lin[ID_AZ]['teorico'] == 50.0 and lin[ID_VA]['teorico'] == 0.0, 'teórico de sucursal = su stock local (0 si no tiene)')
# azúcar 50 -> 70: +20 x 20 = +400 ; leche 10 -> 6: -4 x 30 = -120 ; vasos 0 -> 3: +3 x 2 = +6
# neto = +286 (< 500) pero Σ|dif| = 526 (> 500) -> debe pedir clave
cam1.post(f'/api/conteos/{SID}/capturar', json={'lineas': [{'insumo_id': ID_AZ, 'contado': 70}, {'insumo_id': ID_LE, 'contado': 6},
                                                            {'insumo_id': ID_VA, 'contado': 3}]}, headers=HC)
r = cam1.post(f'/api/conteos/{SID}/aplicar', json={}, headers=HC)
check(r.status_code == 403 and r.json.get('requiere_admin') and r.json.get('valor_abs_total') == 526.0,
      f"sobrante y faltante NO se compensan: Σ|dif| $526 pide clave ({r.status_code} {r.json.get('valor_abs_total')})")
check(_stock_suc('Caminante 1', ID_AZ) == 50.0 and _stock_suc('Caminante 1', ID_VA) is None, 'sin clave no se ajusta nada')
with app.app_context():
    check(ConteoInventario.query.get(SID).estado == 'BORRADOR', 'el conteo sigue en BORRADOR')
r = cam1.post(f'/api/conteos/{SID}/aplicar', json={'clave_admin': 'clave-mala'}, headers=HC)
check(r.status_code == 403, 'clave incorrecta rechazada')
r = cam1.post(f'/api/conteos/{SID}/aplicar', json={'clave_admin': 'gerente12345'}, headers=HC)
check(r.status_code == 200 and r.json['autorizo'] == 'GERENTE (GERENTE)' and r.json['ajustes'] == 3, 'con clave de gerente se aplica')
check(_stock_suc('Caminante 1', ID_AZ) == 70.0 and _stock_suc('Caminante 1', ID_LE) == 6.0 and _stock_suc('Caminante 1', ID_VA) == 3.0,
      'stock de sucursal ajustado (y se crea la fila si no existía)')
check(_stock(ID_AZ) == 8.0, 'ajuste de sucursal no toca la bodega')
with app.app_context():
    bit = BitacoraPOS.query.filter_by(accion='AJUSTE_INVENTARIO', mesa=f'CONTEO #{SID}').first()
    check(bit is not None and bit.autorizo == 'GERENTE (GERENTE)' and bit.monto == 526.0 and bit.sucursal == 'Caminante 1',
          'bitácora registra el ajuste con quién autorizó')
    check(ConteoInventario.query.get(SID).autorizo == 'GERENTE (GERENTE)', 'el conteo guarda quién autorizó')

# ---------- Cancelar y borrador viejo ----------
r = admin.post('/api/conteos/iniciar', json={'ubicacion': 'Caminante 2'}, headers=H)
KID = r.json['conteo']['id']
with app.app_context():
    ConteoInventario.query.get(KID).fecha = _ahora() - _td(hours=25); db.session.commit()
check(admin.get('/api/conteos?ubicacion=Caminante 2').json['borrador']['borrador_viejo'] is True, 'avisa si el borrador tiene más de 24 h')
check(admin.post(f'/api/conteos/{KID}/aplicar', json={}, headers=H).status_code == 400, 'aplicar sin nada capturado -> 400')
r = admin.post(f'/api/conteos/{KID}/cancelar', headers=H)
d = admin.get('/api/conteos?ubicacion=Caminante 2').json
check(r.status_code == 200 and d['borrador'] is None and d['historial'][0]['estado'] == 'CANCELADO', 'cancelar deja el conteo en el historial')

# ---------- Pantallas y esquema ----------
h_alm = alm.get('/almacen_pro').get_data(as_text=True)
h_suc = cam1.get('/pedidos_sucursal').get_data(as_text=True)
check('id="sec_conteo"' in h_alm and 'JSON.parse(\'"BODEGA"\')' in h_alm, 'almacen_pro tiene la pestaña de conteo (BODEGA)')
check('id="sec_conteo"' in h_suc and 'JSON.parse(\'"Caminante 1"\')' in h_suc, 'pedidos_sucursal tiene la pestaña de conteo (su sucursal)')
with app.app_context():
    check({'conteos_inventario', 'conteos_inventario_detalle'} <= set(ESQUEMA_REQUERIDO) and esquema_faltante(db.engine) == [],
          'tablas de conteo en ESQUEMA_REQUERIDO y creadas')
