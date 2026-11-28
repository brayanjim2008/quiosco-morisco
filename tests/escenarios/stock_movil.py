# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, login, check, db, token_de).
# Conteo desde el celular y aviso de stock bajo con pedido a bodega en un toque.
from models import InsumoBodegaPro as _InS, StockSucursal as _StS, RequerimientoBodega as _RqS

_c1 = login('caminante1', 'caminante12345')
_HC = {'X-CSRFToken': token_de(_c1.get('/pedidos_sucursal').get_data(as_text=True))}
_SUC = 'Caminante 1'
r = _c1.get('/conteo_movil')
_h = r.get_data(as_text=True)
check(r.status_code == 200 and 'Contar inventario' in _h and 'value="Caminante 1"' in _h, 'la sucursal abre el conteo en el celular (solo su sucursal)')
check('Bodega Central' in admin.get('/conteo_movil').get_data(as_text=True), 'admin puede contar bodega o cualquier sucursal desde el celular')
check(clientes['paola'].get('/conteo_movil').status_code == 302, 'una mesera no entra al conteo')
check('/conteo_movil' in admin.get('/almacen_pro').get_data(as_text=True), 'Bodega tiene el botón «Contar con el celular»')

with app.app_context():
    _a = _InS(nombre='LECHE AVISO', categoria='BARRA | Insumos', unidad='LT', stock_actual=50, costo_unitario=20, activo=True)
    _b = _InS(nombre='CAFE AVISO', categoria='BARRA | Insumos', unidad='KG', stock_actual=50, costo_unitario=300, activo=True)
    db.session.add_all([_a, _b]); db.session.commit()
    _LA, _CA = _a.id, _b.id
    db.session.add_all([_StS(sucursal=_SUC, insumo_id=_LA, stock_actual=1, stock_minimo=5),
                        _StS(sucursal=_SUC, insumo_id=_CA, stock_actual=0, stock_minimo=1)])
    db.session.commit()
f = {x['insumo_id']: x for x in _c1.get('/api/sucursal/faltantes_sugeridos').json['faltantes']}
check(_LA in f and _CA in f and f[_CA]['agotado'] and f[_LA]['stock'] == 1 and f[_LA]['sugerido'] == 9,
      f'aviso de stock bajo: leche quedan 1 de mín 5 (sugiere 9) y café agotado ({f.get(_LA)}, {f.get(_CA)})')
check(list(f).index(_CA) < list(f).index(_LA), 'lo agotado sale antes que lo que solo está bajo')
r = _c1.post('/api/almacen/solicitar_lote', json={'items': [{'insumo_id': _LA, 'cantidad': 9}, {'insumo_id': _CA, 'cantidad': 2}], 'sucursal': _SUC}, headers=_HC)
check(r.status_code == 200 and r.json['ok'], 'pedir a bodega en un toque')
d = _c1.get('/api/sucursal/faltantes_sugeridos').json
check(_LA not in {x['insumo_id'] for x in d['faltantes']} and d['ya_pedidos'] >= 2, 'lo que ya se pidió y no ha llegado ya no se vuelve a sugerir')
with app.app_context():
    check(_RqS.query.filter_by(sucursal=_SUC, insumo_id=_LA).count() == 1, 'el pedido queda a nombre de Caminante 1')

# conteo a ciegas desde el celular: iniciar, capturar, aplicar
r = _c1.post('/api/conteos/iniciar', json={'ubicacion': _SUC}, headers=_HC)
_cid = r.json['conteo']['id']
r = _c1.post(f'/api/conteos/{_cid}/capturar', json={'lineas': [{'insumo_id': _LA, 'contado': 3}]}, headers=_HC)
check(r.status_code == 200, 'el celular guarda cada número al escribirlo')
r = _c1.post(f'/api/conteos/{_cid}/aplicar', json={}, headers=_HC)
with app.app_context():
    check(r.status_code == 200 and _StS.query.filter_by(sucursal=_SUC, insumo_id=_LA).first().stock_actual == 3,
          f'aplicar el conteo del celular ajusta el stock de la sucursal ({r.get_data(as_text=True)[:100]})')
