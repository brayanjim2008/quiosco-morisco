"""Modo sin internet de la Caja.

Cuando se cae el internet, la caja (guardada en el navegador por /sw.js) permite seguir vendiendo con
"Venta sin internet": imprime la comanda y la nota en la impresora de esa caja y guarda la venta en el aparato.
Al volver el internet, cada venta se sube aquí UNA sola vez (llave única por venta): se registra como cuenta
PAGADA en el turno abierto, con folio, descuento de recetas y bitácora. Los precios se corrigen con el catálogo,
igual que una captura normal.
"""
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, session, send_from_directory, current_app
from flask_login import login_required, current_user

from models import (
    db, ahora_local, CuentaPOS, DetallePOS, Producto, obtener_sucursal_activa, obtener_turno_activo,
    recalcular_totales_cuenta, descontar_recetas_local, detectar_area_impresion, registrar_bitacora,
    inicio_hoy_local, MSG_TURNO_CERRADO,
)

offline_bp = Blueprint('offline', __name__)
ROLES_CAJA = ('admin', 'gerente', 'cajero', 'sucursal')
FORMAS = ('EF', 'TARJD', 'TARJC', 'TRANS')


@offline_bp.route('/sw.js')
def service_worker():
    """El service worker debe servirse desde la raíz para poder guardar /pos y funcionar sin internet."""
    resp = send_from_directory(current_app.static_folder, 'js/sw.js', mimetype='application/javascript')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp


def _num(v, maximo=1_000_000.0):
    x = float(v or 0)
    if not (0 <= x <= maximo):
        raise ValueError('Número fuera de rango')
    return round(x, 2)


@offline_bp.route('/api/pos/venta_offline', methods=['POST'])
@login_required
def api_venta_offline():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False, 'msg': 'Solo la caja registra ventas.'}), 403
    from pos_routes import _mapas_precios, _precio_servidor, _siguiente_folio_sucursal, _cargar_areas_prods
    d = request.get_json(silent=True) or {}
    llave = re.sub(r'[^A-Za-z0-9_-]', '', str(d.get('idem') or ''))[:60]
    if len(llave) < 8:
        return jsonify({'ok': False, 'msg': 'Venta sin llave.'}), 400
    idem = 'OFF' + llave
    previa = CuentaPOS.query.filter_by(cobro_idem=idem).first()
    if previa:   # ya se había subido (se cortó la respuesta): no se registra dos veces
        return jsonify({'ok': True, 'folio': previa.folio, 'repetida': True})

    suc = obtener_sucursal_activa(session)
    turno = obtener_turno_activo(suc)
    if not turno:
        return jsonify({'ok': False, 'turno_cerrado': True, 'msg': MSG_TURNO_CERRADO}), 409

    items = d.get('items') or []
    if not items or len(items) > 200:
        return jsonify({'ok': False, 'msg': 'La venta no tiene productos.'}), 400
    pago = {k: _num((d.get('pago') or {}).get(k)) for k in FORMAS}
    propina = _num(d.get('propina'))

    ahora = ahora_local()
    # Hora de la venta (la manda la caja en hora local); si no cuadra con el turno, se usa la de ahora.
    try:
        cuando = datetime.fromisoformat(str(d.get('creada_en'))[:19])
        if not (turno.apertura <= cuando <= ahora):
            cuando = ahora
    except (TypeError, ValueError):
        cuando = ahora

    mesa = re.sub(r'[<>"\'`]', '', str(d.get('mesa') or 'SIN INTERNET'))[:30] or 'SIN INTERNET'
    num_orden = CuentaPOS.query.filter(CuentaPOS.sucursal == suc, CuentaPOS.apertura >= inicio_hoy_local()).count() + 1
    c = CuentaPOS(turno_id=turno.id, sucursal=suc, orden=f'A{num_orden}', mesa=mesa,
                  mesero=(str(d.get('mesero') or current_user.username)).strip().upper()[:60], personas=1,
                  observaciones='VENTA SIN INTERNET', apertura=cuando, estado='ABIERTA', impresa=True)
    db.session.add(c)
    db.session.flush()

    mapas = _mapas_precios(suc)
    areas = _cargar_areas_prods()
    productos = {p.id: p for p in Producto.query.all()}
    for it in items:
        cant = _num(it.get('cantidad') or 1, maximo=999)
        if cant <= 0:
            continue
        p = productos.get(int(it.get('producto_id') or 0))
        nombre = (p.nombre if p else re.sub(r'[<>"\'`]', '', str(it.get('nombre') or '')))[:150].upper()
        if not nombre:
            continue
        precio = _precio_servidor(False, nombre, 'X', _num(it.get('precio')), mapas)
        area = areas.get(str(p.id), '') if p else ''
        area = area if area in ('COCINA', 'BARRA') else detectar_area_impresion(p.categoria if p else 'Barra')
        db.session.add(DetallePOS(cuenta_id=c.id, num_comanda=1, cantidad=cant, clave=f'0{p.id}' if p else 'OFF',
                                  descripcion=nombre, area_impresion=area, es_modificador=False,
                                  precio_unitario=precio, importe=round(precio * cant, 2), impreso_comanda=True))
        nota = re.sub(r'[<>"\'`]', '', str(it.get('nota') or '')).strip()[:100]
        if nota:
            db.session.add(DetallePOS(cuenta_id=c.id, num_comanda=1, cantidad=1, clave='NOTA', descripcion='>' + nota.upper(),
                                      area_impresion=area, es_modificador=True, precio_unitario=0.0, importe=0.0,
                                      impreso_comanda=True))
    db.session.flush()
    recalcular_totales_cuenta(c)
    if c.total <= 0:
        db.session.rollback()
        return jsonify({'ok': False, 'msg': 'La venta quedó en $0.'}), 400

    cubierto = round(sum(pago.values()), 2)
    c.folio = _siguiente_folio_sucursal(suc)
    c.pago_efectivo, c.pago_tarjeta_debito, c.pago_tarjeta_credito, c.pago_transferencia = pago['EF'], pago['TARJD'], pago['TARJC'], pago['TRANS']
    c.propina_tarjeta = propina
    c.cambio = round(min(pago['EF'], max(0.0, cubierto - c.total)), 2)
    c.cierre = cuando
    c.estado = 'PAGADA'
    c.cobro_idem = idem
    descontar_recetas_local(c)
    db.session.commit()
    dif = round(cubierto - c.total, 2)
    registrar_bitacora('VENTA_SIN_INTERNET', mesa, c.total,
                       f'Folio {c.folio}, capturada {cuando:%d/%m %H:%M}' + (f' · cobrado ${cubierto:.2f} (dif. {dif:+.2f})' if dif < -0.01 else ''),
                       sucursal=suc)
    return jsonify({'ok': True, 'folio': c.folio, 'total': c.total, 'diferencia': dif if dif < -0.01 else 0.0})
