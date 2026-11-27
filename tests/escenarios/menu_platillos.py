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
