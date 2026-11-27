# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, H, check, db, abrir_turnos).
# Fase 7: ventas hechas sin internet se suben una sola vez, con precio del catálogo, al turno abierto.
from models import (CuentaPOS as _CtaO, DetallePOS as _DetO, Producto as _ProdO, TurnoPOS as _TurO,
                    obtener_sucursal_activa as _sucO)

abrir_turnos()
_T = {'X-CSRFToken': H['X-CSRFToken']}
with app.app_context():
    _p = _ProdO.query.filter(_ProdO.precio > 0).order_by(_ProdO.id.asc()).first()
    _PID, _PRECIO, _NOM = _p.id, float(_p.precio), _p.nombre.upper()
    _antes = _CtaO.query.count()

_venta = {'idem': 'prueba-offline-0001', 'creada_en': '2000-01-01T10:00:00', 'mesa': 'T09', 'mesero': 'RAQUEL',
          'pago': {'EF': _PRECIO * 2 + 50, 'TARJD': 0, 'TARJC': 0, 'TRANS': 0}, 'propina': 0,
          'items': [{'producto_id': _PID, 'nombre': _NOM, 'precio': 1, 'cantidad': 2, 'nota': 'sin hielo'}]}
r = admin.post('/api/pos/venta_offline', json=_venta, headers=_T)
check(r.status_code == 200 and r.json.get('ok') and r.json.get('folio'), f'subir venta hecha sin internet ({r.get_data(as_text=True)[:150]})')
_folio = r.json.get('folio')
with app.app_context():
    c = _CtaO.query.filter_by(folio=_folio).first()
    check(c is not None and c.estado == 'PAGADA' and abs(c.total - _PRECIO * 2) < 0.01 and c.observaciones == 'VENTA SIN INTERNET',
          f'queda como cuenta PAGADA con el precio del catálogo, no el que mandó el navegador ({c and c.total} vs {_PRECIO * 2})')
    check(abs((c.cambio or 0) - 50) < 0.01, 'el cambio se calcula con el total real')
    check(_DetO.query.filter_by(cuenta_id=c.id, es_modificador=True).first().descripcion == '>SIN HIELO', 'la nota de la venta se guarda')
    check(c.cierre.year != 2000, 'una hora de venta que no cuadra con el turno se toma como la de ahora')
r = admin.post('/api/pos/venta_offline', json=_venta, headers=_T)
with app.app_context():
    check(r.status_code == 200 and r.json.get('repetida') and r.json.get('folio') == _folio and _CtaO.query.count() == _antes + 1,
          'si la misma venta se sube dos veces (se cortó la red), se registra UNA sola vez')

r = admin.post('/api/pos/venta_offline', json={'idem': 'corta'}, headers=_T)
check(r.status_code == 400, 'venta sin llave válida se rechaza')
r = admin.post('/api/pos/venta_offline', json=dict(_venta, idem='prueba-offline-0002', items=[]), headers=_T)
check(r.status_code == 400, 'venta sin productos se rechaza')
check(clientes['paola'].post('/api/pos/venta_offline', json=_venta).status_code in (302, 400, 403), 'un mesero no sube ventas de caja')

# sin turno abierto: la venta espera (409) y no se pierde
with app.app_context():
    _suc = 'Quiosco Morisco (Matriz)'
    _abiertos = [t.id for t in _TurO.query.filter_by(sucursal=_suc, estado='ABIERTO').all()]
    _TurO.query.filter(_TurO.id.in_(_abiertos)).update({'estado': 'CERRADO'}, synchronize_session=False)
    db.session.commit()
r = admin.post('/api/pos/venta_offline', json=dict(_venta, idem='prueba-offline-0003'), headers=_T)
check(r.status_code == 409 and r.json.get('turno_cerrado'), 'sin turno abierto la venta espera (no se registra en el aire)')
with app.app_context():
    _TurO.query.filter(_TurO.id.in_(_abiertos)).update({'estado': 'ABIERTO'}, synchronize_session=False)
    db.session.commit()

# la caja se puede abrir sin internet
r = app.test_client().get('/sw.js')
check(r.status_code == 200 and 'javascript' in r.mimetype and r.headers.get('Service-Worker-Allowed') == '/', 'el service worker se sirve desde la raíz')
_hp = admin.get('/pos').get_data(as_text=True)
check('js/venta_offline.js' in _hp and 'guardarCatalogoOffline' in _hp, 'la Caja trae el modo sin internet')
