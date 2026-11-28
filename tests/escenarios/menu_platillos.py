# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, H, check, db).
# Menú y Platillos: una sola pantalla para platillo, preguntas (modificadores por pasos), categorías y modificadores.
from models import (Producto as _PrM, ProductoGrupoMod as _FgM, RecetaPOS as _ReM, InsumoBodegaPro as _InM,
                    ModificadorPOS as _MoM, CategoriaMenu as _CaM)

_T = {'X-CSRFToken': H['X-CSRFToken']}
check(admin.get('/platillos').status_code == 200, 'admin abre Menú y Platillos')
check(clientes['brayan'].get('/api/menu/datos').status_code == 403, 'la caja no puede cambiar el menú')
check(clientes['brayan'].post('/api/menu/platillo', data={'nombre': 'X', 'categoria': 'Postres'}, headers=_T).status_code in (400, 403),
      'la caja no puede crear platillos')

# categoría nueva con ícono
r = admin.post('/api/menu/categoria', data={'nombre': 'Tés Prueba', 'nombre_en': 'Teas', 'icono': '🍵'}, headers=_T)
check(r.status_code == 200 and r.json['ok'], f'crear categoría con ícono ({r.get_data(as_text=True)[:100]})')
_cat_id = r.json['id']

# platillo nuevo
r = admin.post('/api/menu/platillo', data={'nombre': 'Té Chai Prueba', 'categoria': 'Tés Prueba', 'precio': '60',
                                           'area': 'BARRA', 'descripcion': 'Rico', 'nombre_en': 'Chai', 'destacado': '1'}, headers=_T)
check(r.status_code == 200 and r.json['ok'], f'crear platillo ({r.get_data(as_text=True)[:120]})')
_pid = r.json['id']
r = admin.post('/api/menu/platillo', data={'nombre': 'té chai prueba', 'categoria': 'Tés Prueba', 'precio': '10'}, headers=_T)
check(r.status_code == 409, 'no deja dos platillos con el mismo nombre')
d = admin.get('/api/menu/datos').json
_p = next(p for p in d['platillos'] if p['id'] == _pid)
check(_p['area'] == 'BARRA' and _p['destacado'] and _p['nombre_en'] == 'Chai', 'el platillo guarda impresora, favorito e inglés')

# preguntas (modificadores por pasos)
r = admin.post(f'/api/menu/platillo/{_pid}/pasos', json={'pasos': [
    {'grupo': 'TIPO DE LECHE', 'etiqueta': 'Leche', 'obligatorio': True, 'max_seleccion': 1},
    {'grupo': 'AL GUSTO BEBIDA', 'etiqueta': 'Al gusto', 'obligatorio': False, 'max_seleccion': 0}]}, headers=_T)
check(r.status_code == 200, 'guardar preguntas del platillo')
flujo = admin.get('/api/pos/modificadores').json['flujos'].get('TÉ CHAI PRUEBA', [])
check([f['grupo'] for f in flujo] == ['TIPO DE LECHE', 'AL GUSTO BEBIDA'] and flujo[0]['obligatorio'] and not flujo[1]['obligatorio'],
      f'la tablet y la caja reciben las preguntas en orden ({flujo})')
r = admin.post(f'/api/menu/platillo/{_pid}/pasos', json={'pasos': [{'grupo': 'NO EXISTE'}]}, headers=_T)
check(r.status_code == 400, 'no acepta un grupo que no existe')

# renombrar: preguntas y receta lo siguen
with app.app_context():
    _ins = _InM(nombre='TE CHAI POLVO', categoria='GENERAL', unidad='KG', stock_actual=1, costo_unitario=100, activo=True)
    db.session.add(_ins)
    db.session.flush()
    _INS = _ins.id
    db.session.add(_ReM(platillo_nombre='TÉ CHAI PRUEBA', insumo_id=_INS, cantidad_descontar=0.02))
    db.session.commit()
r = admin.post('/api/menu/platillo', data={'id': _pid, 'nombre': 'Chai Latte Prueba', 'categoria': 'Tés Prueba', 'precio': '65', 'area': 'BARRA'}, headers=_T)
with app.app_context():
    check(r.status_code == 200 and _FgM.query.filter_by(platillo_nombre='CHAI LATTE PRUEBA').count() == 2
          and _ReM.query.filter_by(platillo_nombre='CHAI LATTE PRUEBA').count() == 1,
          'al renombrar el platillo, sus preguntas y su receta lo siguen')

# categoría: renombrar mueve sus platillos; no se borra si tiene platillos
r = admin.post('/api/menu/categoria', data={'id': _cat_id, 'nombre': 'Tés y Chai', 'icono': '🍵'}, headers=_T)
with app.app_context():
    check(r.status_code == 200 and _PrM.query.get(_pid).categoria == 'Tés y Chai', 'renombrar categoría mueve sus platillos')
check(admin.post(f'/api/menu/categoria/{_cat_id}/eliminar', headers=_T).status_code == 409, 'no borra una categoría con platillos')

# modificadores: agregar, editar (receta lo sigue), quitar
r = admin.post('/api/menu/modificador', json={'grupo': 'TIPO DE LECHE', 'nombre': 'LECHE DE COCO', 'precio': 12, 'area': 'BARRA'}, headers=_T)
check(r.status_code == 200, 'agregar opción a un grupo')
_mid = r.json['id']
check(admin.post('/api/menu/modificador', json={'grupo': 'TIPO DE LECHE', 'nombre': 'LECHE DE COCO'}, headers=_T).status_code == 409,
      'no repite una opción en el mismo grupo')
with app.app_context():
    db.session.add(_ReM(platillo_nombre='>LECHE DE COCO', insumo_id=_INS, cantidad_descontar=0.1))
    db.session.commit()
r = admin.post('/api/menu/modificador', json={'id': _mid, 'grupo': 'TIPO DE LECHE', 'nombre': 'COCO', 'precio': 14, 'area': 'BARRA'}, headers=_T)
with app.app_context():
    m = _MoM.query.get(_mid)
    check(r.status_code == 200 and m.nombre == 'COCO' and m.precio == 14 and _ReM.query.filter_by(platillo_nombre='>COCO').count() == 1,
          'editar opción: nombre y precio, y su receta la sigue')
admin.post(f'/api/menu/modificador/{_mid}/apagar', headers=_T)
with app.app_context():
    check(_MoM.query.get(_mid).activo is False, 'quitar opción la apaga (no se borra)')

# eliminar platillo limpia sus preguntas
check(admin.post(f'/api/menu/platillo/{_pid}/eliminar', headers=_T).status_code == 200, 'eliminar platillo')
with app.app_context():
    check(_PrM.query.get(_pid) is None and _FgM.query.filter_by(platillo_nombre='CHAI LATTE PRUEBA').count() == 0,
          'al eliminar el platillo se quitan sus preguntas')
check(admin.post(f'/api/menu/categoria/{_cat_id}/eliminar', headers=_T).status_code == 200, 'eliminar categoría vacía')
check('/platillos' in admin.get('/admin_dashboard').get_data(as_text=True), 'el menú de módulos lleva a Menú y Platillos')

# ---------- Receta desde Menú: al cobrar descuenta del stock local de la sucursal (puede quedar negativo) ----------
from models import StockSucursal as _StM
with app.app_context():
    _pr = _PrM(nombre='Cafe Receta Prueba', precio=58.0, categoria='Postres')
    _ic = _InM(nombre='CAFE GRANO RECETA', categoria='GENERAL', unidad='KG', stock_actual=10, costo_unitario=300, activo=True)
    _il = _InM(nombre='LECHE RECETA', categoria='GENERAL', unidad='LT', stock_actual=10, costo_unitario=20, activo=True)
    db.session.add_all([_pr, _ic, _il])
    db.session.commit()
    _PRC, _CAFE, _LECHE = _pr.id, _ic.id, _il.id
    db.session.add(_StM(sucursal='Quiosco Morisco (Matriz)', insumo_id=_LECHE, stock_actual=0.1, stock_minimo=1))
    db.session.commit()
r = admin.post('/api/menu/receta', json={'producto_id': _PRC, 'lineas': [{'insumo_id': _CAFE, 'cantidad': 0.018}, {'insumo_id': _LECHE, 'cantidad': 0.25}]}, headers=_T)
check(r.status_code == 200 and r.json['renglones'] == 2, f'guardar receta desde Menú ({r.get_data(as_text=True)[:100]})')
_pd = next(p for p in admin.get('/api/menu/datos').json['platillos'] if p['id'] == _PRC)
check(len(_pd['receta']) == 2 and _pd['receta'][0]['unidad'] == 'KG', 'el platillo trae su receta con unidades')
check(admin.post('/api/menu/receta', json={'producto_id': _PRC, 'lineas': [{'insumo_id': _CAFE, 'cantidad': 0}]}, headers=_T).status_code == 400,
      'no acepta cantidades en 0')
check(clientes['brayan'].post('/api/menu/receta', json={'producto_id': _PRC, 'lineas': []}).status_code in (400, 403), 'la caja no cambia recetas')

# vender 2 en la Matriz y cobrar
abrir_turnos()
from models import CuentaPOS as _CtaR2
admin.post('/api/pos/abrir_mesa', json={'mesa': 'RX1', 'personas': 1}, headers=H)
with app.app_context():
    _c = _CtaR2.query.filter_by(mesa='RX1', estado='ABIERTA').first()
    _cid, _suc = _c.id, _c.sucursal
    db.session.add(_StM(sucursal=_suc, insumo_id=_LECHE, stock_actual=0.1, stock_minimo=1)) if _suc != 'Quiosco Morisco (Matriz)' else None
    db.session.commit()
r = admin.post('/api/pos/capturar_item', json={'cuenta_id': _cid, 'producto_id': _PRC, 'descripcion': 'CAFE RECETA PRUEBA', 'precio': 58,
                                                'cantidad': 2, 'clave': f'0{_PRC}', 'categoria': 'Postres'}, headers=H)
check(r.status_code == 200, f'capturar el platillo con receta ({r.get_data(as_text=True)[:100]})')
imprimir_cuenta(admin, _cid, H)
r = admin.post('/api/pos/pagar_cuenta', json={'cuenta_id': _cid, 'efectivo': 200}, headers=H)
check(r.status_code == 200, f'cobrar la venta con receta ({r.get_data(as_text=True)[:120]})')
with app.app_context():
    _cafe = _StM.query.filter_by(sucursal=_suc, insumo_id=_CAFE).first()
    _leche = _StM.query.filter_by(sucursal=_suc, insumo_id=_LECHE).first()
    check(_cafe is not None and abs(_cafe.stock_actual - (-0.036)) < 0.0001, f'al cobrar descuenta el café de la sucursal (2 × 0.018) ({_cafe and _cafe.stock_actual})')
    check(_leche is not None and abs(_leche.stock_actual - (0.1 - 0.5)) < 0.0001,
          f'la leche queda en negativo si se vendió más de lo registrado ({_leche and _leche.stock_actual})')
check('NEGATIVO: falta registrar entrada' in admin.get('/pedidos_sucursal').get_data(as_text=True), 'Mi stock avisa cuando queda en negativo')
