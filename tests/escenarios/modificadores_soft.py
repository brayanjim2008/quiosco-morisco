# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, check, db).
# Modificadores con los nombres y precios del Soft: una base con los nombres viejos se convierte sin perder recetas.
from models import (ModificadorPOS as _ModS, RecetaPOS as _RecS, InsumoBodegaPro as _InsS,
                    sincronizar_modificadores_guiados_quiosco as _sincS, ProductoGrupoMod as _FluS)

with app.app_context():
    m = _ModS.query.filter_by(grupo='CARGAS DE CAFE', nombre='DOBLE CARGA').first()
    m.grupo, m.nombre, m.precio = 'CARGAS DE CAFE', 'EXTRA SHOT CAFE', 18.0   # como estaba antes
    _MID = m.id
    _ins = _InsS(nombre='CAFE PRUEBA SOFT', categoria='GENERAL', unidad='KG', stock_actual=1, costo_unitario=300, activo=True)
    db.session.add(_ins)
    db.session.flush()
    db.session.add(_RecS(platillo_nombre='>EXTRA SHOT CAFE', insumo_id=_ins.id, cantidad_descontar=0.01))
    db.session.commit()
    _sincS()
    m = _ModS.query.get(_MID)
    check(m.nombre == 'DOBLE CARGA' and m.precio == 25.0 and m.clave == '03023' and m.activo,
          f'el modificador viejo queda con nombre, clave y precio del Soft ({m.nombre}, {m.clave}, {m.precio})')
    check(_RecS.query.filter_by(platillo_nombre='>DOBLE CARGA').count() == 1 and not _RecS.query.filter_by(platillo_nombre='>EXTRA SHOT CAFE').count(),
          'su receta pasa al nombre nuevo (sigue descontando inventario)')
    activos = {(x.grupo, x.nombre): x.precio for x in _ModS.query.filter_by(activo=True).all()}
    esperado = {('TIPO DE LECHE', 'LECHE DE AVENA'): 8.0, ('FRIO O CALIENTE', 'FRIO'): 5.0, ('SABORES', 'MOKA'): 15.0,
                ('SABORES', 'VAINILLA'): 15.0, ('SABORES', 'CARAMELO'): 15.0, ('TIPO DE VINO', 'MALBEC'): 0.0,
                ('TERMINO', 'BIEN COCIDO'): 0.0, ('SALSA CHILAQUILES', 'ROJOS'): 0.0, ('AL GUSTO BEBIDA', 'SIN AZUCAR'): 0.0}
    check(all(activos.get(k) == v for k, v in esperado.items()), 'están los modificadores del Soft con sus precios')
    check(('PREP HUEVOS', 'CON CHORIZO') not in activos and ('FRIO O CALIENTE', 'VERSION FRIA') not in activos,
          'ya no quedan los nombres viejos')
    fl = {(f.platillo_nombre, f.grupo) for f in _FluS.query.all()}
    check(('HAMBURGUESA MORISCO', 'TERMINO') in fl and ('VINO DE LA CASA (POR COPEO)', 'TIPO DE VINO') in fl,
          'la hamburguesa pide término y el vino pide cuál')

# Hoja de requerimiento como la de papel: botón de imprimir y el orden de la hoja en el catálogo
from operacion_routes import CATALOGO_LISTAS_REALES as _CLR
check(_CLR[0][1] == 'Pepino' and _CLR[0][0] == 'BARRA | Frutas y verduras', 'la lista de barra empieza como la hoja (Frutas y verduras, Pepino)')
_hp = admin.get('/pedidos_sucursal').get_data(as_text=True)
check('imprimirHojaRequerimiento' in _hp and 'Solicitado' in _hp and 'Recibido' in _hp, 'pedidos: botón de imprimir la hoja de requerimiento')
check('orden_hoja' in str(admin.get('/api/almacen/datos').json['insumos'][:1]), 'los insumos traen su lugar en la hoja')
