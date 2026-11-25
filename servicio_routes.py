"""Servicio en piso: Monitor de Cocina/Barra (KDS) y Reservaciones ligadas a mesas.

Módulo aparte para no seguir creciendo pos_routes.py.
"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session, redirect, url_for
from flask_login import current_user, login_required

from models import (
    db, ahora_local, inicio_hoy_local, obtener_sucursal_activa, obtener_turno_activo, registrar_bitacora,
    cfg_cargar, cfg_guardar, SUCURSALES_OFICIALES, CuentaPOS, DetallePOS, Reservacion,
)
from pos_routes import ROLES_POS, _lock_advisory, _num

servicio_bp = Blueprint('servicio', __name__)

# ==============================================================================
# MONITOR DE COCINA / BARRA (KDS)
# ==============================================================================
KDS_AREAS = ('COCINA', 'BARRA')
KDS_ESTADOS = ('PENDIENTE', 'PREPARANDO', 'LISTO', 'ENTREGADO')
KDS_VENTANA_HORAS = 12          # comandas más viejas no se muestran
KDS_AGRUPAR_SEG = 5             # platillos enviados con <5 s de diferencia = mismo ticket
CLAVE_CFG_KDS = 'kds_alertas'
KDS_ALERTAS_DEFAULT = {'amarillo': 10, 'rojo': 20}   # minutos


def _area(d):
    return d.area_impresion if d.area_impresion in KDS_AREAS else 'COCINA'


def kds_alertas():
    cfg = cfg_cargar(CLAVE_CFG_KDS, KDS_ALERTAS_DEFAULT)
    try:
        return {'amarillo': int(cfg.get('amarillo', 10)), 'rojo': int(cfg.get('rojo', 20))}
    except Exception:
        return dict(KDS_ALERTAS_DEFAULT)


def _estado_agregado(estados):
    if estados and all(e == 'LISTO' for e in estados):
        return 'LISTO'
    if any(e in ('PREPARANDO', 'LISTO') for e in estados):
        return 'PREPARANDO'
    return 'PENDIENTE'


def kds_tickets(suc, area):
    """Tickets activos de un área: platillos ya enviados (enviado_en), no entregados, de cuentas abiertas o
    recién pagadas de la sucursal. Cada platillo lleva sus modificadores; un modificador de OTRA área
    (p. ej. el café de un paquete) aparece como línea propia en su área."""
    ahora = ahora_local()
    filas = db.session.query(DetallePOS, CuentaPOS).join(CuentaPOS, CuentaPOS.id == DetallePOS.cuenta_id).filter(
        CuentaPOS.sucursal == suc,
        CuentaPOS.estado.in_(('ABIERTA', 'PAGADA')),
        CuentaPOS.es_subcuenta_parte.isnot(True),
        DetallePOS.enviado_en.isnot(None),
        DetallePOS.enviado_en >= ahora - timedelta(hours=KDS_VENTANA_HORAS),
        DetallePOS.kds_estado != 'ENTREGADO',
        DetallePOS.clave != 'SEP',
    ).order_by(DetallePOS.enviado_en.asc(), DetallePOS.id.asc()).all()

    cuentas, padres, mods_por_padre, notas = {}, {}, {}, {}
    for d, c in filas:
        cuentas[c.id] = c
        if d.clave == 'NOTA' or (d.es_modificador and not d.parent_detalle_id and d.clave == 'NOTA'):
            notas.setdefault(c.id, []).append(d)
        elif d.es_modificador and d.parent_detalle_id:
            mods_por_padre.setdefault(d.parent_detalle_id, []).append(d)
        elif not d.es_modificador:
            padres[d.id] = d
    padres_todos = dict(padres)
    faltan = [pid for pid in mods_por_padre if pid not in padres_todos]
    if faltan:  # el padre puede estar ENTREGADO o fuera de la ventana; se necesita su nombre
        padres_todos.update({p.id: p for p in DetallePOS.query.filter(DetallePOS.id.in_(faltan)).all()})

    lineas = []  # (cuenta_id, enviado_en, linea)
    for pid, d in padres.items():
        if _area(d) != area:
            continue
        mods = [m for m in mods_por_padre.get(pid, []) if _area(m) == area or not m.area_impresion]
        lineas.append((d.cuenta_id, d.enviado_en, {
            'ids': [d.id] + [m.id for m in mods], 'cantidad': d.cantidad, 'descripcion': d.descripcion,
            'mods': [m.descripcion.lstrip('>').strip() for m in mods], 'estado': d.kds_estado or 'PENDIENTE',
        }))
    for pid, mods in mods_por_padre.items():
        padre = padres_todos.get(pid)
        for m in mods:
            if not m.area_impresion or _area(m) != area or (padre and _area(padre) == area):
                continue
            lineas.append((m.cuenta_id, m.enviado_en, {
                'ids': [m.id], 'cantidad': m.cantidad, 'descripcion': m.descripcion.lstrip('>').strip(),
                'mods': [f'para: {padre.descripcion}' if padre else ''], 'estado': m.kds_estado or 'PENDIENTE',
            }))

    tickets = []
    for cid, env, lin in sorted(lineas, key=lambda x: (x[0], x[1])):
        t = tickets[-1] if tickets else None
        if not t or t['cuenta_id'] != cid or (env - t['_ultimo']).total_seconds() > KDS_AGRUPAR_SEG:
            c = cuentas[cid]
            t = {'cuenta_id': cid, 'mesa': c.mesa, 'mesero': c.mesero or '', 'orden': c.orden or '',
                 'cuenta_pagada': c.estado == 'PAGADA', '_inicio': env, '_ultimo': env, 'lineas': [], 'notas': []}
            tickets.append(t)
        t['_ultimo'] = env
        t['lineas'].append(lin)
    usados = set()
    for t in tickets:  # las notas del pedido van al primer ticket de COCINA de esa cuenta
        if area == 'COCINA' and t['cuenta_id'] in notas and t['cuenta_id'] not in usados:
            usados.add(t['cuenta_id'])
            t['notas'] = [n.descripcion.lstrip('>').strip() for n in notas[t['cuenta_id']]]
            t['lineas_nota_ids'] = [n.id for n in notas[t['cuenta_id']]]
    salida = []
    for t in sorted(tickets, key=lambda x: x['_inicio']):
        ids = [i for lin in t['lineas'] for i in lin['ids']] + t.get('lineas_nota_ids', [])
        salida.append({
            'clave': f"{t['cuenta_id']}-{t['_inicio'].strftime('%H%M%S')}", 'cuenta_id': t['cuenta_id'],
            'mesa': t['mesa'], 'mesero': t['mesero'], 'orden': t['orden'], 'cuenta_pagada': t['cuenta_pagada'],
            'enviado': t['_inicio'].strftime('%H:%M'),
            'minutos': int((ahora - t['_inicio']).total_seconds() // 60),
            'estado': _estado_agregado([lin['estado'] for lin in t['lineas']]),
            'lineas': t['lineas'], 'notas': t['notas'], 'ids': ids,
        })
    return salida


def _kds_tiempo_promedio(suc, area):
    """Minutos promedio de preparación (enviado -> listo) de hoy en el área."""
    filas = db.session.query(DetallePOS).join(CuentaPOS, CuentaPOS.id == DetallePOS.cuenta_id).filter(
        CuentaPOS.sucursal == suc, DetallePOS.kds_listo_en >= inicio_hoy_local(), DetallePOS.enviado_en.isnot(None),
        DetallePOS.es_modificador.isnot(True)).all()
    tiempos = [(d.kds_listo_en - d.enviado_en).total_seconds() / 60 for d in filas
               if _area(d) == area and d.kds_listo_en >= d.enviado_en]
    return round(sum(tiempos) / len(tiempos), 1) if tiempos else None


@servicio_bp.route('/kds')
@login_required
def vista_kds():
    if current_user.role not in ROLES_POS:
        return redirect(url_for('admin_login'))
    return render_template('kds.html', sucursal=obtener_sucursal_activa(session))


@servicio_bp.route('/api/kds')
@login_required
def api_kds():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    area = str(request.args.get('area', 'COCINA')).upper()
    if area not in KDS_AREAS:
        return jsonify({'ok': False, 'msg': 'Área inválida.'}), 400
    suc = obtener_sucursal_activa(session)
    return jsonify({'ok': True, 'sucursal': suc, 'area': area, 'ahora': ahora_local().strftime('%H:%M:%S'),
                    'alertas': kds_alertas(), 'tickets': kds_tickets(suc, area),
                    'promedio_min': _kds_tiempo_promedio(suc, area)})


@servicio_bp.route('/api/kds/estado', methods=['POST'])
@login_required
def api_kds_estado():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.get_json(silent=True) or {}
    estado = str(data.get('estado', '')).upper()
    if estado not in KDS_ESTADOS:
        return jsonify({'ok': False, 'msg': 'Estado inválido.'}), 400
    try:
        ids = sorted({int(x) for x in (data.get('ids') or [])})[:300]
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'msg': 'ids inválidos'}), 400
    if not ids:
        return jsonify({'ok': True, 'actualizados': 0})
    suc = obtener_sucursal_activa(session)
    detalles = db.session.query(DetallePOS).join(CuentaPOS, CuentaPOS.id == DetallePOS.cuenta_id).filter(
        DetallePOS.id.in_(ids), CuentaPOS.sucursal == suc).all()
    ahora = ahora_local()
    for d in detalles:
        d.kds_estado = estado
        if estado == 'LISTO' and not d.kds_listo_en:
            d.kds_listo_en = ahora
        elif estado in ('PENDIENTE', 'PREPARANDO'):
            d.kds_listo_en = None
    db.session.commit()
    return jsonify({'ok': True, 'actualizados': len(detalles)})


@servicio_bp.route('/api/kds/config', methods=['POST'])
@login_required
def api_kds_config():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Admin.'}), 403
    data = request.get_json(silent=True) or {}
    amarillo = int(_num(data.get('amarillo', 10), minimo=1, maximo=240))
    rojo = int(_num(data.get('rojo', 20), minimo=1, maximo=480))
    if rojo <= amarillo:
        return jsonify({'ok': False, 'msg': 'El tiempo en rojo debe ser mayor que el amarillo.'}), 400
    cfg_guardar(CLAVE_CFG_KDS, {'amarillo': amarillo, 'rojo': rojo})
    return jsonify({'ok': True, 'alertas': {'amarillo': amarillo, 'rojo': rojo}})


# ==============================================================================
# RESERVACIONES LIGADAS A MESAS
# ==============================================================================
RESERVA_ESTADOS_ACTIVOS = ('PENDIENTE', 'CONFIRMADA')
RESERVA_CHOQUE_HORAS = 2        # misma mesa con otra reserva activa a menos de 2 h = choque
RESERVA_TRANSICIONES = {
    'PENDIENTE': {'CONFIRMADA', 'LLEGO', 'NO_LLEGO', 'CANCELADA'},
    'CONFIRMADA': {'PENDIENTE', 'LLEGO', 'NO_LLEGO', 'CANCELADA'},
    'LLEGO': set(), 'NO_LLEGO': {'PENDIENTE'}, 'CANCELADA': {'PENDIENTE'},
}


def _suc_reservas():
    """Admin puede pedir otra sucursal con ?sucursal= / campo 'sucursal'; los demás, solo la suya."""
    suc = obtener_sucursal_activa(session)
    if current_user.role == 'admin':
        pedida = str((request.args.get('sucursal') or (request.get_json(silent=True) or {}).get('sucursal') or '')).strip()
        if pedida in SUCURSALES_OFICIALES:
            return pedida
    return suc


def _reserva_json(r):
    return {
        'id': r.id, 'sucursal': r.sucursal, 'fecha': r.fecha_hora.strftime('%Y-%m-%d'), 'hora': r.fecha_hora.strftime('%H:%M'),
        'nombre': r.nombre, 'telefono': r.telefono or '', 'personas': r.personas, 'mesa': r.mesa or '',
        'notas': r.notas or '', 'estado': r.estado, 'creado_por': r.creado_por, 'cuenta_id': r.cuenta_id,
    }


def _choque_mesa(suc, mesa, fecha_hora, excluir_id=None):
    if not mesa:
        return None
    q = Reservacion.query.filter(
        Reservacion.sucursal == suc, Reservacion.mesa == mesa, Reservacion.estado.in_(RESERVA_ESTADOS_ACTIVOS),
        Reservacion.fecha_hora > fecha_hora - timedelta(hours=RESERVA_CHOQUE_HORAS),
        Reservacion.fecha_hora < fecha_hora + timedelta(hours=RESERVA_CHOQUE_HORAS))
    if excluir_id:
        q = q.filter(Reservacion.id != excluir_id)
    return q.first()


def reservas_proximas_por_mesa(suc):
    """{mesa: '20:00 NOMBRE (4p)'} para reservas activas de -30 min a +3 h (para marcar mesas en el POS)."""
    ahora = ahora_local()
    filas = Reservacion.query.filter(
        Reservacion.sucursal == suc, Reservacion.estado.in_(RESERVA_ESTADOS_ACTIVOS), Reservacion.mesa.isnot(None),
        Reservacion.fecha_hora >= ahora - timedelta(minutes=30), Reservacion.fecha_hora <= ahora + timedelta(hours=3)
    ).order_by(Reservacion.fecha_hora.asc()).all()
    salida = {}
    for r in filas:
        salida.setdefault(r.mesa, f"{r.fecha_hora.strftime('%H:%M')} {r.nombre} ({r.personas}p)")
    return salida


def _abrir_o_ligar_cuenta(suc, mesa, personas, observacion):
    """Igual que abrir mesa en el POS: si la mesa ya tiene cuenta abierta se liga a esa."""
    _lock_advisory(f'mesa:{suc}:{mesa}')
    existente = CuentaPOS.query.filter_by(sucursal=suc, mesa=mesa, estado='ABIERTA').first()
    if existente:
        return existente
    turno = obtener_turno_activo(suc)
    num_orden = CuentaPOS.query.filter(CuentaPOS.sucursal == suc, CuentaPOS.apertura >= inicio_hoy_local()).count() + 1
    area = '02 TERRAZA' if mesa.startswith('T') else ('RAPIDO' if 'RAP' in mesa else '01 COMEDOR')
    c = CuentaPOS(turno_id=turno.id, sucursal=suc, orden=f"A{num_orden}", area=area, mesa=mesa,
                  mesero=current_user.username.upper(), personas=max(1, personas), observaciones=observacion[:250],
                  apertura=ahora_local(), estado='ABIERTA')
    db.session.add(c)
    db.session.flush()
    return c


@servicio_bp.route('/reservaciones')
@login_required
def vista_reservaciones():
    if current_user.role not in ROLES_POS:
        return redirect(url_for('admin_login'))
    return render_template('reservaciones.html', sucursal=obtener_sucursal_activa(session), sucursales=SUCURSALES_OFICIALES)


@servicio_bp.route('/api/reservaciones', methods=['GET', 'POST'])
@login_required
def api_reservaciones():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    suc = _suc_reservas()
    if request.method == 'GET':
        try:
            dia = datetime.strptime(request.args.get('fecha') or ahora_local().strftime('%Y-%m-%d'), '%Y-%m-%d')
        except ValueError:
            return jsonify({'ok': False, 'msg': 'Fecha inválida.'}), 400
        filas = Reservacion.query.filter(Reservacion.sucursal == suc, Reservacion.fecha_hora >= dia,
                                         Reservacion.fecha_hora < dia + timedelta(days=1)).order_by(Reservacion.fecha_hora.asc()).all()
        return jsonify({'ok': True, 'sucursal': suc, 'fecha': dia.strftime('%Y-%m-%d'), 'reservaciones': [_reserva_json(r) for r in filas]})

    data = request.get_json(silent=True) or {}
    nombre = str(data.get('nombre', '')).strip()[:100]
    if not nombre:
        return jsonify({'ok': False, 'msg': 'Nombre requerido.'}), 400
    try:
        fecha_hora = datetime.strptime(f"{data.get('fecha', '')} {data.get('hora', '')}", '%Y-%m-%d %H:%M')
    except ValueError:
        return jsonify({'ok': False, 'msg': 'Fecha u hora inválida.'}), 400
    if fecha_hora < ahora_local() - timedelta(hours=1):
        return jsonify({'ok': False, 'msg': 'La fecha de la reservación ya pasó.'}), 400
    personas = int(_num(data.get('personas', 2), minimo=1, maximo=200))
    mesa = str(data.get('mesa', '')).strip().upper()[:25] or None
    telefono = ''.join(ch for ch in str(data.get('telefono', '')) if ch.isdigit() or ch in '+ ')[:20]
    choque = _choque_mesa(suc, mesa, fecha_hora)
    if choque and not data.get('forzar'):
        return jsonify({'ok': False, 'choque': True,
                        'msg': f'La mesa {mesa} ya tiene la reserva de {choque.nombre} a las {choque.fecha_hora.strftime("%H:%M")}.'}), 409
    r = Reservacion(sucursal=suc, fecha_hora=fecha_hora, nombre=nombre, telefono=telefono, personas=personas, mesa=mesa,
                    notas=str(data.get('notas', '')).strip()[:250], estado='PENDIENTE', creado_por=current_user.username.upper())
    db.session.add(r)
    db.session.commit()
    return jsonify({'ok': True, 'reservacion': _reserva_json(r)})


@servicio_bp.route('/api/reservaciones/<int:reserva_id>', methods=['POST'])
@login_required
def api_reservacion_actualizar(reserva_id):
    """Cambia estado y/o mesa. LLEGO abre (o liga) la cuenta de la mesa reservada."""
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    r = Reservacion.query.filter_by(id=reserva_id).with_for_update().first()
    if not r:
        return jsonify({'ok': False, 'msg': 'Reservación no encontrada.'}), 404
    if current_user.role != 'admin' and r.sucursal != obtener_sucursal_activa(session):
        return jsonify({'ok': False, 'msg': 'Reservación de otra sucursal.'}), 403
    data = request.get_json(silent=True) or {}
    if 'mesa' in data:
        nueva_mesa = str(data.get('mesa') or '').strip().upper()[:25] or None
        choque = _choque_mesa(r.sucursal, nueva_mesa, r.fecha_hora, excluir_id=r.id)
        if choque and not data.get('forzar'):
            return jsonify({'ok': False, 'choque': True,
                            'msg': f'La mesa {nueva_mesa} ya tiene la reserva de {choque.nombre} a las {choque.fecha_hora.strftime("%H:%M")}.'}), 409
        r.mesa = nueva_mesa
    estado = str(data.get('estado', '')).upper()
    cuenta_id = None
    if estado:
        if estado not in RESERVA_TRANSICIONES.get(r.estado, set()):
            return jsonify({'ok': False, 'msg': f'No se puede pasar de {r.estado} a {estado}.'}), 409
        if estado == 'LLEGO':
            if not r.mesa:
                return jsonify({'ok': False, 'msg': 'Asigna una mesa antes de marcar que llegó.'}), 400
            c = _abrir_o_ligar_cuenta(r.sucursal, r.mesa, r.personas, f'RESERVA: {r.nombre} ({r.personas}p) {r.notas or ""}'.strip())
            r.cuenta_id = cuenta_id = c.id
        r.estado = estado
    db.session.commit()
    if estado:
        registrar_bitacora(f'RESERVA_{estado}', r.mesa or '', 0.0, f'{r.nombre} {r.fecha_hora.strftime("%d/%m %H:%M")}', sucursal=r.sucursal)
    return jsonify({'ok': True, 'reservacion': _reserva_json(r), 'cuenta_id': cuenta_id})
