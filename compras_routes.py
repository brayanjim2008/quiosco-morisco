"""Compras e inventario avanzado: presentaciones de compra, sub-recetas (insumos elaborados) con producción,
y órdenes de compra a proveedores (sugeridas por stock y consumo, envío por WhatsApp, recepción y cuentas por pagar).
"""
import re
import urllib.parse
from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func

from models import (
    db, ahora_local, registrar_bitacora, InsumoBodegaPro, StockSucursal, MovimientoAlmacen, ProveedorAlmacen,
    RequerimientoBodega, PresentacionInsumo, RecetaElaborado, OrdenCompra, OrdenCompraDetalle,
)
from operacion_routes import (
    _num, _csv_excel, _puede_operar_conteo, _stock_teorico, existencia_total_insumo, costo_promedio_ponderado,
    registrar_compra, UBICACION_BODEGA,
)

compras_bp = Blueprint('compras', __name__)
ROLES_COMPRAS = ('admin', 'almacen')


def _solo_compras():
    if current_user.role not in ROLES_COMPRAS:
        return jsonify({'ok': False, 'msg': 'Solo Admin o Almacén.'}), 403
    return None


def _insumo_activo(insumo_id, bloquear=False):
    q = InsumoBodegaPro.query.filter(InsumoBodegaPro.id == int(insumo_id or 0), InsumoBodegaPro.activo.is_not(False))
    if bloquear:
        q = q.with_for_update()
    return q.first()


# ==============================================================================
# PRESENTACIONES DE COMPRA (CAJA, PAQUETE, COSTAL...)
# ==============================================================================
@compras_bp.route('/api/presentaciones', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_presentaciones():
    err = _solo_compras()
    if err:
        return err
    if request.method == 'GET':
        pres = PresentacionInsumo.query.filter_by(activo=True).order_by(PresentacionInsumo.insumo_id, PresentacionInsumo.factor).all()
        nombres = {i.id: (i.nombre, i.unidad) for i in InsumoBodegaPro.query.all()}
        return jsonify({'ok': True, 'presentaciones': [{
            'id': p.id, 'insumo_id': p.insumo_id, 'insumo_nombre': nombres.get(p.insumo_id, ('', ''))[0],
            'unidad': nombres.get(p.insumo_id, ('', ''))[1], 'nombre': p.nombre, 'factor': p.factor} for p in pres]})
    data = request.get_json(silent=True) or {}
    if request.method == 'DELETE':
        p = PresentacionInsumo.query.get_or_404(int(data.get('id') or 0))
        p.activo = False  # baja lógica: las órdenes viejas conservan su texto
        db.session.commit()
        return jsonify({'ok': True})
    ins = _insumo_activo(data.get('insumo_id'))
    if not ins:
        return jsonify({'ok': False, 'msg': 'Insumo no encontrado.'}), 404
    nombre = str(data.get('nombre', '')).strip().upper()[:60]
    factor = round(_num(data.get('factor', 0), maximo=100_000.0), 4)
    if not nombre or factor <= 0:
        return jsonify({'ok': False, 'msg': 'Nombre y factor (mayor a 0) requeridos.'}), 400
    if PresentacionInsumo.query.filter_by(insumo_id=ins.id, nombre=nombre, activo=True).first():
        return jsonify({'ok': False, 'msg': 'Ya existe esa presentación para el insumo.'}), 400
    p = PresentacionInsumo(insumo_id=ins.id, nombre=nombre, factor=factor, activo=True)
    db.session.add(p)
    db.session.commit()
    return jsonify({'ok': True, 'id': p.id})


# ==============================================================================
# SUB-RECETAS: INSUMOS ELABORADOS (SALSAS, BASES, JARABES) Y PRODUCCIÓN
# ==============================================================================
def _crea_ciclo(elaborado_id, insumo_id):
    """True si usar `insumo_id` como ingrediente de `elaborado_id` crea un ciclo (A lleva B y B lleva A...)."""
    if elaborado_id == insumo_id:
        return True
    pendientes, vistos = [insumo_id], set()
    while pendientes:
        actual = pendientes.pop()
        if actual == elaborado_id:
            return True
        if actual in vistos:
            continue
        vistos.add(actual)
        pendientes.extend(r.insumo_id for r in RecetaElaborado.query.filter_by(elaborado_id=actual).all())
    return False


def _receta_json(elab, insumos):
    lineas, costo = [], 0.0
    for r in RecetaElaborado.query.filter_by(elaborado_id=elab.id).order_by(RecetaElaborado.id).all():
        ing = insumos.get(r.insumo_id)
        cu = float(ing.costo_unitario or 0.0) if ing else 0.0
        costo += r.cantidad * cu
        lineas.append({'id': r.id, 'insumo_id': r.insumo_id, 'insumo_nombre': ing.nombre if ing else f'#{r.insumo_id}',
                       'unidad': ing.unidad if ing else '', 'cantidad': r.cantidad, 'costo_unitario': round(cu, 4),
                       'sin_costo': cu <= 0})
    return {'id': elab.id, 'nombre': elab.nombre, 'unidad': elab.unidad, 'stock_bodega': round(float(elab.stock_actual or 0.0), 3),
            'costo_unitario': round(float(elab.costo_unitario or 0.0), 4), 'costo_receta': round(costo, 4), 'receta': lineas}


@compras_bp.route('/api/elaborados')
@login_required
def api_elaborados():
    if current_user.role not in ('admin', 'almacen', 'sucursal'):
        return jsonify({'ok': False}), 403
    insumos = {i.id: i for i in InsumoBodegaPro.query.filter(InsumoBodegaPro.activo.is_not(False)).all()}
    elaborados = sorted((i for i in insumos.values() if i.es_elaborado), key=lambda x: x.nombre)
    return jsonify({'ok': True, 'elaborados': [_receta_json(e, insumos) for e in elaborados]})


@compras_bp.route('/api/elaborados/receta', methods=['POST', 'DELETE'])
@login_required
def api_elaborados_receta():
    """POST {elaborado_id, insumo_id, cantidad}: agrega/actualiza un ingrediente (marca el insumo como elaborado).
    POST {elaborado_id, es_elaborado: false}: lo desmarca. DELETE {id}: quita un ingrediente."""
    err = _solo_compras()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if request.method == 'DELETE':
        db.session.delete(RecetaElaborado.query.get_or_404(int(data.get('id') or 0)))
        db.session.commit()
        return jsonify({'ok': True})
    elab = _insumo_activo(data.get('elaborado_id'))
    if not elab:
        return jsonify({'ok': False, 'msg': 'Insumo elaborado no encontrado.'}), 404
    if data.get('es_elaborado') is False:
        RecetaElaborado.query.filter_by(elaborado_id=elab.id).delete()
        elab.es_elaborado = False
        db.session.commit()
        return jsonify({'ok': True})
    elab.es_elaborado = True
    if data.get('insumo_id') in (None, ''):
        db.session.commit()
        return jsonify({'ok': True})
    ing = _insumo_activo(data.get('insumo_id'))
    if not ing:
        return jsonify({'ok': False, 'msg': 'Ingrediente no encontrado.'}), 404
    cantidad = round(_num(data.get('cantidad', 0), maximo=100_000.0), 4)
    if cantidad <= 0:
        return jsonify({'ok': False, 'msg': 'Cantidad mayor a 0 requerida.'}), 400
    if _crea_ciclo(elab.id, ing.id):
        db.session.rollback()
        return jsonify({'ok': False, 'msg': f'{ing.nombre} no puede ser ingrediente de {elab.nombre} (se forma un ciclo).'}), 400
    linea = RecetaElaborado.query.filter_by(elaborado_id=elab.id, insumo_id=ing.id).first()
    if linea:
        linea.cantidad = cantidad
    else:
        db.session.add(RecetaElaborado(elaborado_id=elab.id, insumo_id=ing.id, cantidad=cantidad))
    db.session.commit()
    return jsonify({'ok': True})


def _sumar_en(ubicacion, ins, cantidad):
    if ubicacion == UBICACION_BODEGA:
        ins.stock_actual = round(float(ins.stock_actual or 0.0) + cantidad, 3)
        return
    st = StockSucursal.query.filter_by(sucursal=ubicacion, insumo_id=ins.id).with_for_update().first()
    if not st:
        st = StockSucursal(sucursal=ubicacion, insumo_id=ins.id, stock_actual=0.0, stock_minimo=2.0)
        db.session.add(st)
    st.stock_actual = round(float(st.stock_actual or 0.0) + cantidad, 3)


@compras_bp.route('/api/elaborados/producir', methods=['POST'])
@login_required
def api_elaborados_producir():
    """Produce N unidades de un elaborado en BODEGA o en una sucursal: descuenta ingredientes de ESA ubicación,
    suma el elaborado ahí y actualiza su costo promedio con el costo real de los ingredientes."""
    data = request.get_json(silent=True) or {}
    ubicacion = str(data.get('ubicacion', '')).strip()
    if not _puede_operar_conteo(ubicacion):
        return jsonify({'ok': False, 'msg': 'Sin permiso para esta ubicación.'}), 403
    elab = _insumo_activo(data.get('elaborado_id'), bloquear=True)
    if not elab or not elab.es_elaborado:
        return jsonify({'ok': False, 'msg': 'Elige un insumo elaborado.'}), 400
    cantidad = round(_num(data.get('cantidad', 0), maximo=100_000.0), 3)
    if cantidad <= 0:
        return jsonify({'ok': False, 'msg': 'Cantidad a producir mayor a 0.'}), 400
    receta = RecetaElaborado.query.filter_by(elaborado_id=elab.id).all()
    if not receta:
        return jsonify({'ok': False, 'msg': f'{elab.nombre} no tiene receta de producción.'}), 400

    consumo, faltantes, costo_total = [], [], 0.0
    for r in receta:
        ing = _insumo_activo(r.insumo_id, bloquear=True)
        if not ing:
            continue
        fila, disponible = _stock_teorico(ubicacion, ing, bloquear=True)
        necesario = round(r.cantidad * cantidad, 3)
        if necesario > disponible + 0.0005:
            faltantes.append(f'{ing.nombre}: necesitas {necesario:g} {ing.unidad}, hay {disponible:g}')
        consumo.append((ing, fila, disponible, necesario))
        costo_total += necesario * float(ing.costo_unitario or 0.0)
    if faltantes and not data.get('forzar'):
        db.session.rollback()
        return jsonify({'ok': False, 'faltantes': faltantes, 'msg': 'Faltan ingredientes en ' + ubicacion + ':\n' + '\n'.join(faltantes)}), 409

    ahora, usuario = ahora_local(), current_user.username.upper()
    for ing, fila, disponible, necesario in consumo:
        nuevo = round(max(0.0, disponible - necesario), 3)
        if ubicacion == UBICACION_BODEGA:
            ing.stock_actual = nuevo
        else:
            if fila is None:
                fila = StockSucursal(sucursal=ubicacion, insumo_id=ing.id, stock_actual=0.0, stock_minimo=2.0)
                db.session.add(fila)
            fila.stock_actual = nuevo
        db.session.add(MovimientoAlmacen(fecha=ahora, tipo='CONSUMO_PRODUCCION', insumo_nombre=ing.nombre, cantidad=necesario,
                                         costo_total=round(necesario * float(ing.costo_unitario or 0.0), 2), proveedor='',
                                         usuario=usuario, nota=f'[{ubicacion}] Producción de {cantidad:g} {elab.unidad} {elab.nombre}'[:200]))
    costo_total = round(costo_total, 2)
    if costo_total > 0:
        elab.costo_unitario = costo_promedio_ponderado(float(elab.costo_unitario or 0.0), existencia_total_insumo(elab),
                                                       cantidad, costo_total)
    _sumar_en(ubicacion, elab, cantidad)
    db.session.add(MovimientoAlmacen(fecha=ahora, tipo='PRODUCCION', insumo_nombre=elab.nombre, cantidad=cantidad,
                                     costo_total=costo_total, proveedor='', usuario=usuario,
                                     nota=(f'[{ubicacion}] Producción' + (' (forzada con faltantes)' if faltantes else ''))[:200]))
    db.session.commit()
    registrar_bitacora('PRODUCCION', elab.nombre, costo_total, f'{ubicacion}: {cantidad:g} {elab.unidad}' +
                       (f' | faltantes: {"; ".join(faltantes)}' if faltantes else ''), sucursal=ubicacion)
    return jsonify({'ok': True, 'costo_total': costo_total, 'costo_unitario': round(float(elab.costo_unitario or 0.0), 4),
                    'faltantes': faltantes})


# ==============================================================================
# ÓRDENES DE COMPRA (SUGERIDAS POR STOCK Y CONSUMO) Y CUENTAS POR PAGAR
# ==============================================================================
DIAS_CONSUMO = 14      # ventana para estimar el consumo diario (lo que Bodega entregó a sucursales)
DIAS_COBERTURA = 7     # la orden sugerida cubre una semana de consumo


def sugeridos_compra():
    """Insumos a comprar: stock bajo el mínimo o que no alcanza para 3 días de consumo.
    Cantidad = lo necesario para llegar a max(2 × mínimo, 7 días de consumo)."""
    desde = ahora_local() - timedelta(days=DIAS_CONSUMO)
    consumo = dict(db.session.query(RequerimientoBodega.insumo_id, func.sum(RequerimientoBodega.cantidad_entregada)).filter(
        RequerimientoBodega.estado_bodega == 'ENTREGADO', RequerimientoBodega.fecha >= desde,
        RequerimientoBodega.insumo_id.isnot(None)).group_by(RequerimientoBodega.insumo_id).all())
    salida = []
    for i in InsumoBodegaPro.query.filter(InsumoBodegaPro.activo.is_not(False)).order_by(InsumoBodegaPro.categoria, InsumoBodegaPro.nombre).all():
        if 'EXTRA / FUERA DE LISTA' in (i.nombre or '') or i.es_elaborado:
            continue
        stock, minimo = float(i.stock_actual or 0.0), float(i.stock_minimo or 0.0)
        diario = float(consumo.get(i.id) or 0.0) / DIAS_CONSUMO
        if not (stock <= minimo or (diario > 0 and stock < diario * 3)):
            continue
        objetivo = max(minimo * 2, diario * DIAS_COBERTURA)
        sugerido = round(max(1.0, objetivo - stock), 1)
        motivo = f'Stock {stock:g} / mín {minimo:g}' + (f' • consume {diario:.1f}/día' if diario else '')
        salida.append({'insumo_id': i.id, 'nombre': i.nombre, 'categoria': i.categoria, 'unidad': i.unidad,
                       'stock': round(stock, 3), 'minimo': minimo, 'consumo_diario': round(diario, 2), 'sugerido': sugerido,
                       'costo_unitario': round(float(i.costo_unitario or 0.0), 4), 'motivo': motivo,
                       'urgencia': 'ALTA' if stock <= 0 else 'MEDIA'})
    return salida


def _orden_json(o, con_lineas=True):
    lineas = OrdenCompraDetalle.query.filter_by(orden_id=o.id).order_by(OrdenCompraDetalle.id).all() if con_lineas else []
    return {
        'id': o.id, 'fecha': o.fecha.strftime('%d/%m/%Y %H:%M') if o.fecha else '', 'proveedor_id': o.proveedor_id,
        'proveedor_nombre': o.proveedor_nombre or 'SIN PROVEEDOR', 'estado': o.estado, 'nota': o.nota or '',
        'creado_por': o.creado_por, 'total_estimado': round(float(o.total_estimado or 0.0), 2),
        'total_real': None if o.total_real is None else round(float(o.total_real), 2),
        'recibido_en': o.recibido_en.strftime('%d/%m/%Y %H:%M') if o.recibido_en else '', 'recibido_por': o.recibido_por or '',
        'lineas': [{
            'id': l.id, 'insumo_id': l.insumo_id, 'insumo_nombre': l.insumo_nombre, 'unidad': l.unidad,
            'presentacion_id': l.presentacion_id, 'presentacion_nombre': l.presentacion_nombre or '', 'factor': l.factor,
            'cantidad_presentaciones': l.cantidad_presentaciones, 'cantidad': l.cantidad,
            'costo_estimado': round(float(l.costo_estimado or 0.0), 2),
            'cantidad_recibida': l.cantidad_recibida, 'costo_real': None if l.costo_real is None else round(float(l.costo_real), 2),
        } for l in lineas],
    }


def _armar_lineas(orden, lineas_raw):
    """Crea las líneas de una orden. Cada una: {insumo_id, cantidad (presentaciones o unidades), presentacion_id?, costo_estimado?}."""
    total = 0.0
    for item in lineas_raw[:300]:
        ins = _insumo_activo(item.get('insumo_id'))
        if not ins:
            raise ValueError('Insumo inválido en la orden.')
        n = round(_num(item.get('cantidad', 0), maximo=1_000_000.0), 3)
        if n <= 0:
            continue
        pres = None
        if item.get('presentacion_id'):
            pres = PresentacionInsumo.query.filter_by(id=int(item['presentacion_id']), insumo_id=ins.id, activo=True).first()
            if not pres:
                raise ValueError(f'Presentación inválida para {ins.nombre}.')
        factor = float(pres.factor) if pres else 1.0
        unidades = round(n * factor, 3)
        costo = item.get('costo_estimado')
        costo = round(_num(costo, maximo=10_000_000.0), 2) if costo not in (None, '') else round(unidades * float(ins.costo_unitario or 0.0), 2)
        db.session.add(OrdenCompraDetalle(
            orden_id=orden.id, insumo_id=ins.id, insumo_nombre=ins.nombre, unidad=ins.unidad,
            presentacion_id=pres.id if pres else None, presentacion_nombre=pres.nombre if pres else '', factor=factor,
            cantidad_presentaciones=n, cantidad=unidades, costo_estimado=costo))
        total += costo
    orden.total_estimado = round(total, 2)


@compras_bp.route('/api/ordenes_compra', methods=['GET', 'POST'])
@login_required
def api_ordenes_compra():
    err = _solo_compras()
    if err:
        return err
    if request.method == 'GET':
        ordenes = OrdenCompra.query.order_by(OrdenCompra.id.desc()).limit(60).all()
        provs = ProveedorAlmacen.query.order_by(ProveedorAlmacen.nombre).all()
        return jsonify({'ok': True, 'ordenes': [_orden_json(o) for o in ordenes], 'sugeridos': sugeridos_compra(),
                        'proveedores': [{'id': p.id, 'nombre': p.nombre, 'telefono': p.telefono or '',
                                         'saldo_pendiente': round(float(p.saldo_pendiente or 0.0), 2)} for p in provs]})
    data = request.get_json(silent=True) or {}
    prov = ProveedorAlmacen.query.get(int(data['proveedor_id'])) if data.get('proveedor_id') else None
    if data.get('proveedor_id') and not prov:
        return jsonify({'ok': False, 'msg': 'Proveedor no encontrado.'}), 404
    lineas = data.get('lineas') or []
    if not lineas and data.get('desde_sugeridos'):
        lineas = [{'insumo_id': s['insumo_id'], 'cantidad': s['sugerido']} for s in sugeridos_compra()]
    if not lineas:
        return jsonify({'ok': False, 'msg': 'La orden no tiene productos.'}), 400
    o = OrdenCompra(fecha=ahora_local(), proveedor_id=prov.id if prov else None, proveedor_nombre=prov.nombre if prov else '',
                    estado='BORRADOR', nota=str(data.get('nota', '')).strip()[:250], creado_por=current_user.username.upper())
    db.session.add(o)
    db.session.flush()
    try:
        _armar_lineas(o, lineas)
    except ValueError as e:
        db.session.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 400
    if not OrdenCompraDetalle.query.filter_by(orden_id=o.id).count():
        db.session.rollback()
        return jsonify({'ok': False, 'msg': 'Todas las cantidades están en 0.'}), 400
    db.session.commit()
    return jsonify({'ok': True, 'orden': _orden_json(o)})


def _orden_bloqueada(orden_id):
    o = OrdenCompra.query.filter_by(id=orden_id).with_for_update().first()
    if not o:
        return None, (jsonify({'ok': False, 'msg': 'Orden no encontrada.'}), 404)
    return o, None


@compras_bp.route('/api/ordenes_compra/<int:orden_id>/lineas', methods=['POST'])
@login_required
def api_orden_lineas(orden_id):
    """Reemplaza las líneas de una orden en BORRADOR (editar cantidades, presentaciones o costos)."""
    err = _solo_compras()
    if err:
        return err
    o, err = _orden_bloqueada(orden_id)
    if err:
        return err
    if o.estado != 'BORRADOR':
        return jsonify({'ok': False, 'msg': 'Solo se editan órdenes en borrador.'}), 409
    data = request.get_json(silent=True) or {}
    if 'proveedor_id' in data:
        prov = ProveedorAlmacen.query.get(int(data['proveedor_id'])) if data.get('proveedor_id') else None
        o.proveedor_id, o.proveedor_nombre = (prov.id, prov.nombre) if prov else (None, '')
    OrdenCompraDetalle.query.filter_by(orden_id=o.id).delete()
    try:
        _armar_lineas(o, data.get('lineas') or [])
    except ValueError as e:
        db.session.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 400
    db.session.commit()
    return jsonify({'ok': True, 'orden': _orden_json(o)})


@compras_bp.route('/api/ordenes_compra/<int:orden_id>/enviar', methods=['POST'])
@login_required
def api_orden_enviar(orden_id):
    err = _solo_compras()
    if err:
        return err
    o, err = _orden_bloqueada(orden_id)
    if err:
        return err
    if o.estado not in ('BORRADOR', 'ENVIADA'):
        return jsonify({'ok': False, 'msg': f'La orden está {o.estado}.'}), 409
    o.estado = 'ENVIADA'
    db.session.commit()
    lineas = OrdenCompraDetalle.query.filter_by(orden_id=o.id).order_by(OrdenCompraDetalle.id).all()
    texto = '\n'.join([f'*ORDEN DE COMPRA #{o.id}*', f'Proveedor: {o.proveedor_nombre or "-"}', ''] + [
        f'• {l.insumo_nombre}: {l.cantidad_presentaciones:g} {l.presentacion_nombre or l.unidad}' for l in lineas
    ] + (['', f'Nota: {o.nota}'] if o.nota else []))
    prov = ProveedorAlmacen.query.get(o.proveedor_id) if o.proveedor_id else None
    tel = re.sub(r'\D', '', prov.telefono or '') if prov else ''
    if len(tel) == 10:
        tel = '52' + tel
    wa = f"https://wa.me/{tel}?text={urllib.parse.quote(texto)}" if tel else f"https://wa.me/?text={urllib.parse.quote(texto)}"
    return jsonify({'ok': True, 'texto': texto, 'wa_url': wa, 'orden': _orden_json(o)})


@compras_bp.route('/api/ordenes_compra/<int:orden_id>/cancelar', methods=['POST'])
@login_required
def api_orden_cancelar(orden_id):
    err = _solo_compras()
    if err:
        return err
    o, err = _orden_bloqueada(orden_id)
    if err:
        return err
    if o.estado not in ('BORRADOR', 'ENVIADA'):
        return jsonify({'ok': False, 'msg': f'La orden está {o.estado}.'}), 409
    o.estado = 'CANCELADA'
    db.session.commit()
    return jsonify({'ok': True})


@compras_bp.route('/api/ordenes_compra/<int:orden_id>/recibir', methods=['POST'])
@login_required
def api_orden_recibir(orden_id):
    """Recepción: por línea {id, recibido (en presentaciones o unidades, según la línea), costo_real (total)}.
    Cada línea recibida entra a Bodega con costo promedio; el total real se suma a lo que se le debe al proveedor."""
    err = _solo_compras()
    if err:
        return err
    o, err = _orden_bloqueada(orden_id)
    if err:
        return err
    if o.estado not in ('BORRADOR', 'ENVIADA'):
        return jsonify({'ok': False, 'msg': f'La orden ya está {o.estado}.'}), 409
    data = request.get_json(silent=True) or {}
    capturas = {int(x.get('id')): x for x in (data.get('lineas') or []) if str(x.get('id', '')).isdigit()}
    total_real, recibidas = 0.0, 0
    for l in OrdenCompraDetalle.query.filter_by(orden_id=o.id).all():
        cap = capturas.get(l.id, {})
        recibido_n = round(_num(cap.get('recibido', l.cantidad_presentaciones), maximo=1_000_000.0), 3)
        unidades = round(recibido_n * float(l.factor or 1.0), 3)
        if cap.get('costo_real') not in (None, ''):
            costo = round(_num(cap.get('costo_real'), maximo=10_000_000.0), 2)
        else:  # proporcional a lo pedido
            costo = round(float(l.costo_estimado or 0.0) * (recibido_n / l.cantidad_presentaciones), 2) if l.cantidad_presentaciones else 0.0
        l.cantidad_recibida, l.costo_real = unidades, costo
        if unidades <= 0:
            continue
        ins = _insumo_activo(l.insumo_id, bloquear=True)
        if not ins:
            continue
        registrar_compra(ins, unidades, costo, proveedor=o.proveedor_nombre, usuario=current_user.username.upper(),
                         nota=f'OC #{o.id}' + (f' ({recibido_n:g} x {l.presentacion_nombre})' if l.presentacion_nombre else ''))
        total_real += costo
        recibidas += 1
    o.total_real = round(total_real, 2)
    o.estado, o.recibido_en, o.recibido_por = 'RECIBIDA', ahora_local(), current_user.username.upper()
    if o.proveedor_id and total_real > 0:  # cuentas por pagar
        prov = ProveedorAlmacen.query.filter_by(id=o.proveedor_id).with_for_update().first()
        if prov:
            prov.saldo_pendiente = round(float(prov.saldo_pendiente or 0.0) + total_real, 2)
    db.session.commit()
    registrar_bitacora('ORDEN_COMPRA_RECIBIDA', f'OC #{o.id}', total_real, f'{o.proveedor_nombre or "SIN PROVEEDOR"}: {recibidas} producto(s)',
                       sucursal='BODEGA')
    return jsonify({'ok': True, 'total_real': o.total_real, 'orden': _orden_json(o)})


@compras_bp.route('/api/exportar/orden_compra/<int:orden_id>')
@login_required
def exportar_orden_compra(orden_id):
    err = _solo_compras()
    if err:
        return err
    o = OrdenCompra.query.get_or_404(orden_id)
    filas = [(l.insumo_nombre, l.presentacion_nombre or l.unidad, l.cantidad_presentaciones, l.unidad, l.cantidad,
              l.costo_estimado, '' if l.cantidad_recibida is None else l.cantidad_recibida,
              '' if l.costo_real is None else l.costo_real)
             for l in OrdenCompraDetalle.query.filter_by(orden_id=o.id).order_by(OrdenCompraDetalle.id).all()]
    return _csv_excel(('Insumo', 'Presentacion', 'Cantidad_Pedida', 'Unidad', 'Unidades', 'Costo_Estimado', 'Unidades_Recibidas', 'Costo_Real'),
                      filas, f'Orden_Compra_{o.id}_{o.estado}.csv')
