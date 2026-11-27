# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, check, db).
# Fase 6: platillos en barras y estado de resultados (ventas − costo − mermas − gastos − nómina = utilidad).
from models import (CuentaPOS as _CtaE, DetallePOS as _DetE, RecetaPOS as _RecE, InsumoBodegaPro as _InsE,
                    RegistroMerma as _MerE, MovimientoCajaPOS as _MovE, TurnoPOS as _TurE, ReciboNominaPOS as _RecNE,
                    ahora_local as _ahE)

_SUC = 'Caminante 3'
_q = {'sucursal': _SUC}
check(clientes['brayan'].get('/api/reportes/estado_resultados').status_code == 403, 'la caja no ve la utilidad')

_antes = admin.get('/api/reportes/estado_resultados', query_string=_q).json
_mes = _ahE().month
_u0 = next(m for m in _antes['meses'] if m['numero'] == _mes)

with app.app_context():
    _ah = _ahE()
    ins = _InsE(nombre='INSUMO UTIL', categoria='GENERAL', unidad='PZA', stock_actual=10, costo_unitario=10, activo=True)
    db.session.add(ins)
    db.session.flush()
    db.session.add(_RecE(platillo_nombre='PLATILLO UTIL', insumo_id=ins.id, cantidad_descontar=1))
    t = _TurE(sucursal=_SUC, cajero='PRUEBA', fondo_inicial=0, estado='ABIERTO', apertura=_ah)
    db.session.add(t)
    db.session.flush()
    c = _CtaE(turno_id=t.id, sucursal=_SUC, orden='U1', mesa='U1', estado='PAGADA', total=116.0, subtotal=100.0,
              apertura=_ah, cierre=_ah, impresa=True, folio='C3-UTIL-1')
    db.session.add(c)
    db.session.flush()
    db.session.add(_DetE(cuenta_id=c.id, cantidad=2, clave='X', descripcion='PLATILLO UTIL', area_impresion='COCINA',
                         es_modificador=False, precio_unitario=58.0, importe=116.0, impreso_comanda=True))
    db.session.add(_MerE(fecha=_ah, sucursal=_SUC, insumo_nombre='INSUMO UTIL', cantidad=1, unidad='PZA', costo_total=5.0,
                         motivo='PRUEBA', usuario='PRUEBA'))
    db.session.add(_MovE(turno_id=t.id, tipo='RETIRO', monto=10.0, concepto='GAS', usuario='PRUEBA', fecha=_ah, categoria_gasto='GAS'))
    db.session.add(_RecNE(fecha=_ah, empleado_id=1, empleado_nombre='X', total_neto=40.0, propinas=10.0, sucursal=_SUC))
    t.estado = 'CERRADO'
    db.session.commit()

_desp = admin.get('/api/reportes/estado_resultados', query_string=_q).json
_u1 = next(m for m in _desp['meses'] if m['numero'] == _mes)
_dif = {k: round(_u1[k] - _u0[k], 2) for k in ('ventas', 'iva', 'costo', 'mermas', 'gastos', 'nomina', 'utilidad')}
check(_dif == {'ventas': 100.0, 'iva': 16.0, 'costo': 20.0, 'mermas': 5.0, 'gastos': 10.0, 'nomina': 30.0, 'utilidad': 35.0},
      f'estado de resultados: 100 − 20 costo − 5 merma − 10 gasto − 30 nómina = 35 ({_dif})')
check(abs(_desp['total']['utilidad'] - sum(m['utilidad'] for m in _desp['meses'])) < 0.05, 'el total del año suma los meses')

_pl = admin.get('/api/reportes/platillos', query_string=_q).json
_f = next((x for x in _pl['platillos'] if x['platillo'] == 'PLATILLO UTIL'), None)
check(_f is not None and _f['cantidad'] == 2 and _f['venta'] == 116.0 and _f['costo_unitario'] == 10.0 and _f['utilidad'] == 80.0,
      f'platillo: piezas, venta y ganancia (100 sin IVA − 20 de costo = 80) ({_f})')
check(isinstance(_pl['sin_venta'], list), 'lista de platillos que no se vendieron')
_hr = admin.get('/industrial').get_data(as_text=True)
check('data-tab="utilidad"' in _hr and 'id="plMasVendidos"' in _hr and 'estrella' not in _hr.lower() and 'caballo' not in _hr.lower(),
      'Reportes: pestañas Utilidad y Platillos en barras (sin "estrella/caballo")')

# Fase 8: guía por puesto
for _u, _h in (('raquel', 'dueno'), ('brayan', 'cajero'), ('paola', 'mesero')):
    _cg = admin if _u == 'raquel' else login(_u, {'brayan': 'cajero12345', 'paola': 'mesero12345'}[_u])
    _r = _cg.get('/guia')
    check(_r.status_code == 200 and f'"{_h}"' in _r.get_data(as_text=True), f'guía: {_u} abre primero la hoja de {_h}')
_g = admin.get('/guia').get_data(as_text=True)
check(all(f'id="h_{x}"' in _g for x in ('cajero', 'mesero', 'cocina', 'encargado', 'bodega', 'dueno')), 'la guía tiene una hoja por cada puesto')
check(app.test_client().get('/guia').status_code == 302, 'la guía pide iniciar sesión')
