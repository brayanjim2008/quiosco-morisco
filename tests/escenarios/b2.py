# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, H, tcj, check, db).
from models import InsumoBodegaPro, StockSucursal, Producto as _Prod

with app.app_context():
    leche = InsumoBodegaPro(nombre='LECHE PRUEBA', categoria='BARRA | Refrescos y leche', unidad='LT',
                            stock_actual=0.0, stock_minimo=2.0, costo_unitario=0.0, activo=True)
    cafe = InsumoBodegaPro(nombre='CAFE SIN COSTO', categoria='BARRA | Insumos', unidad='KG',
                           stock_actual=5.0, stock_minimo=1.0, costo_unitario=0.0, activo=True)
    db.session.add_all([leche, cafe]); db.session.commit()
    id_leche, id_cafe = leche.id, cafe.id
    db.session.add(StockSucursal(sucursal='Caminante 1', insumo_id=id_leche, stock_actual=2.0, stock_minimo=1.0))
    db.session.commit()

def _compra(cant, costo, insumo=None):
    return admin.post('/api/almacen/movimiento', json={'insumo_id': insumo or id_leche, 'tipo': 'ENTRADA_COMPRA',
                      'cantidad': cant, 'costo_total': costo, 'proveedor': 'LALA'}, headers=H)

def _leche():
    with app.app_context():
        i = InsumoBodegaPro.query.get(id_leche)
        return round(i.costo_unitario, 4), round(i.stock_actual, 2)

# 1) costo actual 0 (aunque haya 2 LT en Caminante 1): toma directo 200/10 = 20
r = _compra(10, 200)
check(r.status_code == 200 and _leche() == (20.0, 10.0) and r.json.get('costo_unitario') == 20.0,
      f'compra con costo cuando costo_unitario era 0 -> costo directo 20.00 ({_leche()})')
# 2) promedio con bodega (10) + sucursales (2) = 12: (12*20 + 125) / (12 + 5) = 21.4706
r = _compra(5, 125)
check(_leche() == (21.4706, 15.0), f'compra posterior promedia con bodega + sucursales -> 21.4706 ({_leche()})')
# 3) compra sin costo: no altera el costo, sí suma stock
r = _compra(3, 0)
check(_leche() == (21.4706, 18.0), f'compra sin costo no cambia costo_unitario ({_leche()})')
# 4) costo previo > 0 pero existencia total 0: toma directo la compra (30/1)
with app.app_context():
    InsumoBodegaPro.query.get(id_leche).stock_actual = 0.0
    StockSucursal.query.filter_by(insumo_id=id_leche).first().stock_actual = 0.0
    db.session.commit()
_compra(1, 30)
check(_leche() == (30.0, 1.0), f'sin existencia en ningún lado -> costo directo 30.00 ({_leche()})')
# 5) merma y traspaso no tocan el costo
admin.post('/api/almacen/movimiento', json={'insumo_id': id_leche, 'tipo': 'SALIDA_MERMA', 'cantidad': 0.5, 'costo_total': 99}, headers=H)
check(_leche()[0] == 30.0, 'merma no altera el costo promedio')
check(clientes['brayan'].post('/api/almacen/movimiento', json={'insumo_id': id_leche, 'tipo': 'ENTRADA_COMPRA', 'cantidad': 1, 'costo_total': 1},
      headers={'X-CSRFToken': tcj}).status_code == 403, 'cajero no puede registrar compras')

# ---------- Costeo de recetas ----------
with app.app_context():
    db.session.add(_Prod(nombre='Agua Cara', precio=10.0, categoria='Bebidas Calientes', descripcion=''))
    db.session.add(_Prod(nombre='Expreso Test', precio=40.0, categoria='Bebidas Calientes', descripcion=''))
    db.session.commit()
for plat, ins, cant in (('LATTE', id_leche, 0.25), ('AGUA CARA', id_leche, 1), ('EXPRESO TEST', id_cafe, 0.02),
                        ('>LECHE ALMENDRAS', id_leche, 0.1)):
    r = admin.post('/api/recetas', json={'platillo_nombre': plat, 'insumo_id': ins, 'cantidad_descontar': cant}, headers=H)
    check(r.status_code == 200, f'receta {plat} guardada')

d = admin.get('/api/recetas/costeo').json
filas = {f['clave']: f for f in d['filas']}
lat = filas.get('LATTE')
# Latte $65: sin IVA 65/1.16 = 56.03; costo 0.25 * 30 = 7.50; utilidad 48.53; margen 86.6%
check(lat and lat['precio_sin_iva'] == 56.03 and lat['costo'] == 7.5 and lat['utilidad'] == 48.53 and lat['margen_pct'] == 86.6
      and not lat['sin_receta'] and not lat['costo_supera_precio'] and lat['insumos_sin_costo'] == [],
      f"Latte: costo 7.50, utilidad 48.53, margen 86.6% ({lat and (lat['costo'], lat['utilidad'], lat['margen_pct'])})")
agua = filas.get('AGUA CARA')
check(agua and agua['costo'] == 30.0 and agua['costo_supera_precio'] and agua['margen_pct'] < 0,
      f"platillo con costo mayor a su precio sin IVA se marca ({agua and (agua['costo'], agua['precio_sin_iva'], agua['margen_pct'])})")
exp = filas.get('EXPRESO TEST')
check(exp and exp['insumos_sin_costo'] == ['CAFE SIN COSTO'] and exp['costo'] == 0.0, 'insumo con costo 0 se marca en el platillo')
mod = filas.get('>LECHE ALMENDRAS')
# modificador $15: sin IVA 12.93; costo 0.1 * 30 = 3.00; margen (12.93-3)/12.93 = 76.8%
check(mod and mod['es_modificador'] and mod['precio'] == 15.0 and mod['costo'] == 3.0 and mod['margen_pct'] == 76.8,
      f"modificador con su propio precio: margen 76.8% ({mod and (mod['precio'], mod['costo'], mod['margen_pct'])})")
sin = [f for f in d['filas'] if f['sin_receta']]
check(len(sin) > 0 and all(f['margen_pct'] is not None or f['precio'] == 0 for f in sin) and d['resumen']['sin_receta'] == len(sin),
      f"platillos sin receta se cuentan ({d['resumen']['sin_receta']})")
check(d['resumen']['costo_supera_precio'] >= 1 and d['resumen']['con_insumos_sin_costo'] >= 1, 'resumen cuenta alertas')
check(clientes['brayan'].get('/api/recetas/costeo').status_code == 403, 'costeo solo para admin')
html_ind = admin.get('/industrial').get_data(as_text=True)
check('tbodyCosteo' in html_ind and 'cargarCosteo' in html_ind, 'pestaña Recetas muestra costo y margen')
