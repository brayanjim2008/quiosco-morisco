import math
import re
from html import escape as _esc
from datetime import timedelta
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, Response
from flask_login import login_required, current_user

from models import (
    db, ahora_local, inicio_hoy_local, SUCURSALES_OFICIALES, PREFIJO_SUCURSAL,
    obtener_sucursal_activa, obtener_datos_ticket, validar_clave_admin, registrar_bitacora,
    generar_pin_unico, detectar_area_impresion, obtener_turno_activo,
    recalcular_totales_cuenta, descontar_recetas_local, invalidar_cache_publico,
    numero_a_letras_mxn,
    User, CategoriaMenu, Producto, PinCaja, PreOrden,
    ConfigPermisosPOS, TurnoPOS, MovimientoCajaPOS, CuentaPOS, DetallePOS,
    ColaImpresionPOS, ModificadorPOS, ProductoGrupoMod, PromocionPOS, BitacoraPOS,
    AlertaMesaPOS, ArqueoTurnoPOS, EmpleadoNominaPOS, ConsumoEmpleadoPOS,
    InsumoBodegaPro, StockSucursal, RegistroMerma, MovimientoAlmacen, aplicar_merma
)

pos_bp = Blueprint('pos', __name__)
ROLES_POS = ('admin', 'gerente', 'cajero', 'mesero', 'sucursal')
ROLES_CAJA = ('admin', 'gerente', 'cajero', 'sucursal')
ROLES_AUTH = ('admin', 'gerente')


def _autorizar_operacion(clave_admin='', permitir_si_flag=False):
    """Valida estrictamente la clave si se ingresa; si no se ingresa, solo permite si el flag de caja está activo."""
    clave_limpia = str(clave_admin or '').strip()
    if clave_limpia:
        return validar_clave_admin(clave_limpia)
    if permitir_si_flag and current_user.role in ROLES_CAJA:
        return current_user.username.upper()
    return None

def _cuenta_permitida(c):
    """Evita que un usuario de una sucursal opere cuentas de otra sucursal."""
    if current_user.role == 'admin':
        return True
    return (c.sucursal or 'Quiosco Morisco (Matriz)') == obtener_sucursal_activa(session)


def _num(valor, minimo=0.0, maximo=10_000_000.0):
    """Convierte a número finito dentro de rango; si no, lanza ValueError (la ruta responde 400)."""
    try:
        x = float(valor or 0)
    except (TypeError, ValueError):
        raise ValueError('Número inválido')
    if not math.isfinite(x) or x < minimo or x > maximo:
        raise ValueError('Número fuera de rango')
    return x


@pos_bp.errorhandler(ValueError)
def _pos_valor_invalido(e):
    db.session.rollback()
    return jsonify({'ok': False, 'msg': 'Dato numérico inválido o fuera de rango.'}), 400


@pos_bp.errorhandler(KeyError)
def _pos_dato_faltante(e):
    db.session.rollback()
    return jsonify({'ok': False, 'msg': f'Falta el dato requerido: {e}'}), 400


import json as _json_asig
from pathlib import Path as _Path_asig

_ASIG_MOD_FILE = _Path_asig("config_mods_productos.json")
_AREA_PROD_FILE = _Path_asig("config_areas_productos.json")
_MOTIVOS_FILE = _Path_asig("config_motivos_cancelacion.json")
_TIPOS_DESC_FILE = _Path_asig("config_tipos_descuento.json")
_CAJA_CFG_FILE = _Path_asig("config_caja_soft.json")

_CAJA_CFG_DEFAULT = {
    "bloquear_cierre_cuentas_abiertas": True,
    "tope_salvaguarda_efectivo": 5000.0
}

def _cargar_cfg_caja():
    if not _CAJA_CFG_FILE.exists():
        try:
            _CAJA_CFG_FILE.write_text(_json_asig.dumps(_CAJA_CFG_DEFAULT, indent=2), encoding="utf-8")
        except Exception:
            pass
        return dict(_CAJA_CFG_DEFAULT)
    try:
        raw = _json_asig.loads(_CAJA_CFG_FILE.read_text(encoding="utf-8"))
        out = dict(_CAJA_CFG_DEFAULT)
        if isinstance(raw, dict):
            out.update(raw)
        return out
    except Exception:
        return dict(_CAJA_CFG_DEFAULT)

_MOTIVOS_DEFAULT = [
    {"id": 1, "clave": "M01", "descripcion": "ERROR DE CAPTURA"},
    {"id": 2, "clave": "M02", "descripcion": "CLIENTE CAMBIÓ DE OPINIÓN"},
    {"id": 3, "clave": "M03", "descripcion": "DEMORA EN PREPARACIÓN"},
]

_TIPOS_DESC_DEFAULT = [
    {"id": 1, "clave": "D01", "descripcion": "CORTESÍA GERENCIA", "porcentaje": 100.0},
    {"id": 2, "clave": "D02", "descripcion": "DESCUENTO EMPLEADO", "porcentaje": 20.0},
    {"id": 3, "clave": "D03", "descripcion": "CLIENTE FRECUENTE", "porcentaje": 10.0},
]

def _cargar_json_lista(ruta, default_items):
    if not ruta.exists():
        try:
            ruta.write_text(_json_asig.dumps(default_items, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return [dict(x) for x in default_items]
    try:
        raw = _json_asig.loads(ruta.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else [dict(x) for x in default_items]
    except Exception:
        return [dict(x) for x in default_items]

def _guardar_json_lista(ruta, items):
    ruta.write_text(_json_asig.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

def _cargar_areas_prods():
    if not _AREA_PROD_FILE.exists():
        return {}
    try:
        raw = _json_asig.loads(_AREA_PROD_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def _guardar_areas_prods(data):
    _AREA_PROD_FILE.write_text(_json_asig.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _cargar_asignaciones_mods():
    if not _ASIG_MOD_FILE.exists():
        return {}
    try:
        raw = _json_asig.loads(_ASIG_MOD_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def _guardar_asignaciones_mods(data):
    _ASIG_MOD_FILE.write_text(_json_asig.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _enriquecer_modificadores(mods):
    asigs = _cargar_asignaciones_mods()
    out = []
    for m in mods:
        reg = asigs.get(str(m.id), {})
        out.append({
            'id': m.id,
            'clave': m.clave,
            'grupo': m.grupo or 'SABORES',
            'nombre': m.nombre,
            'precio': m.precio,
            'area_impresion': m.area_impresion or '',
            'producto_ids': [int(x) for x in (reg.get('producto_ids') or [])],
            'categorias': [str(x).upper() for x in (reg.get('categorias') or [])]
        })
    return out

def _mapa_flujos_modificadores():
    flujos = {}
    for fg in ProductoGrupoMod.query.order_by(ProductoGrupoMod.orden.asc(), ProductoGrupoMod.id.asc()).all():
        key = fg.platillo_nombre.strip().upper()
        flujos.setdefault(key, []).append({
            'grupo': fg.grupo,
            'etiqueta': fg.etiqueta,
            'orden': fg.orden,
            'obligatorio': bool(fg.obligatorio),
            'max_seleccion': int(fg.max_seleccion or 0)
        })
    return flujos


def _resolver_area_modificador(mod_obj, area_padre):
    """Permite que modificadores como Fruta o Café Refill de un paquete salgan directo en BARRA."""
    area_ex = (mod_obj.get('area_impresion') or '').strip().upper()
    if area_ex in ('BARRA', 'COCINA'):
        return area_ex
    mod_id = mod_obj.get('id')
    if mod_id:
        m_bd = ModificadorPOS.query.get(int(mod_id))
        if m_bd and m_bd.area_impresion in ('BARRA', 'COCINA'):
            return m_bd.area_impresion
    nom = str(mod_obj.get('nombre') or mod_obj.get('descripcion') or '').strip().upper().lstrip('>')
    if nom:
        m_bd = ModificadorPOS.query.filter(db.func.upper(ModificadorPOS.nombre) == nom).first()
        if m_bd and m_bd.area_impresion in ('BARRA', 'COCINA'):
            return m_bd.area_impresion
    return area_padre


def _siguiente_folio_sucursal(sucursal):
    pref = PREFIJO_SUCURSAL.get(sucursal, 'QM')
    ult = CuentaPOS.query.filter(
        CuentaPOS.folio.like(f"{pref}-%")
    ).order_by(CuentaPOS.id.desc()).first()
    sig = 10001
    if ult and ult.folio:
        partes = ult.folio.split('-')
        if len(partes) == 2 and partes[1].isdigit():
            sig = int(partes[1]) + 1
    while CuentaPOS.query.filter_by(folio=f"{pref}-{sig}").first():
        sig += 1
    return f"{pref}-{sig}"


def _armar_ticket_precuenta_html(c):
    dt = obtener_datos_ticket(c.sucursal)
    filas = "".join([
        f"<tr><td style='width:14%;'>{'' if it.es_modificador else int(it.cantidad)}</td>"
        f"<td style='width:62%;'>{_esc(it.descripcion.lstrip('>'))}</td>"
        f"<td style='width:24%;text-align:right;'>${it.importe:.2f}</td></tr>"
        for it in c.detalles if (not it.es_modificador or it.importe > 0)
    ])
    apertura_str = c.apertura.strftime('%d/%m/%Y %I:%M:%S %p') if c.apertura else ''
    ahora_str = ahora_local().strftime('%d/%m/%Y %I:%M:%S %p')
    cajero_nom = current_user.username.upper() if current_user.is_authenticated else ''
    letras = numero_a_letras_mxn(c.total)
    return f"""
    <div class='ticket-termico'>
      <div style='text-align:center;line-height:1.25;'>
        <b>{dt['nombre_comercial']}</b><br>
        {dt['razon_social']}<br>
        RFC: {dt['rfc']}<br>
        {dt['direccion']}<br>
        {dt['ciudad']}<br>
        TEL: {dt['telefono']}
      </div>
      <div>================================</div>
      MESA: <b>{c.mesa}</b><br>
      MESERO: {c.mesero}<br>
      PERSONAS: {c.personas} &nbsp;&nbsp; ORDEN: <b>{c.orden}</b><br>
      FOLIO: <b>{c.folio or c.orden}</b><br>
      {apertura_str}<br>
      {ahora_str}<br>
      CAJERO: {cajero_nom}<br>
      <div>================================</div>
      <table style='width:100%;font-size:11.5px;'>
        <tr><td style='width:14%;'><b>CANT.</b></td><td style='width:62%;'><b>DESCRIPCION</b></td><td style='width:24%;text-align:right;'><b>IMPORTE</b></td></tr>
        {filas}
      </table>
      <div>================================</div>
      {f"<div style='text-align:right;'>DESCUENTO: -${c.descuento_monto:.2f}</div>" if c.descuento_monto > 0 else ""}
      <div style='text-align:right;font-size:17px;font-weight:900;margin:4px 0;'>TOTAL: &nbsp;&nbsp; ${c.total:.2f}</div>
      <div>================================</div>
      <div style='font-size:10.5px;margin:4px 0;'>{letras}</div>
      <div style='text-align:center;font-size:11px;margin:4px 0;'>SUBTOTAL: ${c.subtotal:.2f} &nbsp;&nbsp; IVA: ${c.iva:.2f}</div>
      <div style='text-align:center;font-size:10px;'>ESTE NO ES UN COMPROBANTE FISCAL<br>PROPINA NO INCLUIDA</div>
    </div>"""


# ==============================================================================
# VISTA PRINCIPAL Y CAMBIO DE SUCURSAL (4 SUCURSALES AISLADAS)
# ==============================================================================
@pos_bp.route('/pos')
@login_required
def vista_pos_soft():
    if current_user.role not in ROLES_CAJA:
        if current_user.role == 'mesero':
            return redirect(url_for('mesero_dashboard'))
        if current_user.role == 'almacen':
            return redirect('/almacen_pro')
        return redirect(url_for('admin_login'))

    suc = obtener_sucursal_activa(session)
    turno = obtener_turno_activo(suc)
    permisos = ConfigPermisosPOS.query.first()
    cuentas = CuentaPOS.query.filter_by(sucursal=suc, estado='ABIERTA').order_by(CuentaPOS.id.asc()).all()
    categorias_bd = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    productos = Producto.query.filter_by(agotado=False).order_by(Producto.categoria.asc(), Producto.nombre.asc()).all()
    empleados = EmpleadoNominaPOS.query.filter_by(activo=True).order_by(EmpleadoNominaPOS.nombre.asc()).all()
    return render_template(
        'pos_soft.html',
        sucursal=suc, sucursales=SUCURSALES_OFICIALES,
        datos_ticket=obtener_datos_ticket(suc),
        turno=turno, permisos=permisos, cuentas=cuentas,
        categorias=categorias_bd, productos=productos, empleados=empleados
    )


@pos_bp.route('/api/pos/cambiar_sucursal', methods=['POST'])
@login_required
def api_pos_cambiar_sucursal():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo administración puede cambiar de sucursal.'}), 403
    suc = str((request.json or {}).get('sucursal', '')).strip()
    if suc not in SUCURSALES_OFICIALES:
        return jsonify({'ok': False, 'msg': 'Sucursal inválida.'}), 400
    session['sucursal_activa'] = suc
    return jsonify({'ok': True, 'sucursal': suc})


# ==============================================================================
# MESAS, CUENTAS Y MAPA TABLET (INCLUYE ESTADO DIVIDIDA)
# ==============================================================================
@pos_bp.route('/api/pos/abrir_mesa', methods=['POST'])
@login_required
def api_pos_abrir_mesa():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    suc = obtener_sucursal_activa(session)
    mesa_nom = str(data.get('mesa', 'T01')).strip().upper()[:25]

    existente = CuentaPOS.query.filter_by(sucursal=suc, mesa=mesa_nom, estado='ABIERTA').first()
    if existente:
        return jsonify({'ok': True, 'cuenta_id': existente.id, 'ya_existia': True})

    turno = obtener_turno_activo(suc)
    hoy_inicio = inicio_hoy_local()
    num_orden = CuentaPOS.query.filter(CuentaPOS.sucursal == suc, CuentaPOS.apertura >= hoy_inicio).count() + 1
    area = '02 TERRAZA' if mesa_nom.startswith('T') else ('RAPIDO' if 'RAP' in mesa_nom else '01 COMEDOR')

    nueva = CuentaPOS(
        turno_id=turno.id, sucursal=suc, orden=f"A{num_orden}",
        area=area, mesa=mesa_nom,
        mesero=str(data.get('mesero', current_user.username)).strip().upper(),
        personas=max(1, int(data.get('personas', 1))),
        apertura=ahora_local(), estado='ABIERTA'
    )
    db.session.add(nueva)
    db.session.commit()
    return jsonify({'ok': True, 'cuenta_id': nueva.id})


@pos_bp.route('/api/pos/renombrar_mesa', methods=['POST'])
@pos_bp.route('/api/pos/asignar_mesa', methods=['POST'])
@login_required
def api_pos_renombrar_mesa():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    nueva_mesa = str(data.get('nueva_mesa', c.mesa)).strip().upper()[:25]
    if nueva_mesa != c.mesa:
        ocupada = CuentaPOS.query.filter_by(sucursal=c.sucursal, mesa=nueva_mesa, estado='ABIERTA').first()
        if ocupada and ocupada.id != c.id:
            return jsonify({'ok': False, 'msg': f'La cuenta {nueva_mesa} ya está ocupada en esta sucursal.'}), 400
        ant = c.mesa
        c.mesa = nueva_mesa
        c.area = '02 TERRAZA' if nueva_mesa.startswith('T') else '01 COMEDOR'
        registrar_bitacora('RENOMBRAR_CUENTA', c.mesa, c.total, f'{ant} -> {c.mesa}', sucursal=c.sucursal)
    if data.get('personas'):
        c.personas = max(1, int(data['personas']))
    db.session.commit()
    return jsonify({'ok': True, 'mesa': c.mesa})


@pos_bp.route('/api/pos/mover_mesa_rapido', methods=['POST'])
@login_required
def api_pos_mover_mesa_rapido():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    nueva_mesa = str(data.get('nueva_mesa', '')).strip().upper()[:25]
    if not nueva_mesa:
        return jsonify({'ok': False, 'msg': 'Selecciona una mesa destino.'}), 400
    ocupada = CuentaPOS.query.filter_by(sucursal=c.sucursal, mesa=nueva_mesa, estado='ABIERTA').first()
    if ocupada and ocupada.id != c.id:
        return jsonify({'ok': False, 'msg': f'La mesa {nueva_mesa} ya está ocupada.'}), 400
    ant = c.mesa
    c.mesa = nueva_mesa
    c.area = '02 TERRAZA' if nueva_mesa.startswith('T') else '01 COMEDOR'
    tiene_enviados = any(bool(d.impreso_comanda) for d in (c.detalles or []))
    if tiene_enviados:
        hora_txt = ahora_local().strftime('%d/%m/%Y %I:%M:%S %p')
        html_aviso = f"""
        <div class='ticket-termico'>
            <div style='text-align:center;font-weight:900;font-size:15px;'>⚠️ CAMBIO DE MESA</div>
            <div style='text-align:center;font-size:11px;'>{_esc(c.sucursal.upper())} | {hora_txt}</div>
            <div style='border-top:1px dashed #000;margin:6px 0;'></div>
            <div style='font-size:14px;font-weight:900;'>MESA ANTERIOR: {_esc(ant)}</div>
            <div style='font-size:16px;font-weight:900;'>NUEVA MESA:    {_esc(nueva_mesa)}</div>
            <div>MESERO: {_esc((c.mesero or current_user.username).upper())}</div>
        </div>"""
        db.session.add(ColaImpresionPOS(sucursal=c.sucursal, tipo='AVISO_CAMBIO_MESA', contenido_html=html_aviso, fecha=ahora_local()))
    db.session.commit()
    registrar_bitacora('MOVER_MESA', nueva_mesa, c.total, f'De {ant} a {nueva_mesa}', sucursal=c.sucursal)
    return jsonify({'ok': True, 'mesa': nueva_mesa, 'aviso_impreso': bool(tiene_enviados)})


@pos_bp.route('/api/pos/detalle_cuenta/<int:cuenta_id>')
@login_required
def api_pos_detalle_cuenta(cuenta_id):
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    c = CuentaPOS.query.get_or_404(cuenta_id)
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    detalles_ord = DetallePOS.query.filter_by(cuenta_id=c.id).order_by(DetallePOS.id.asc()).all()
    items = [{
        'id': d.id,
        'parent_detalle_id': d.parent_detalle_id,
        'mov': idx + 1,
        'comanda': d.num_comanda,
        'cantidad': f"{d.cantidad:.3f}",
        'cantidad_num': d.cantidad,
        'clave': d.clave,
        'descripcion': d.descripcion,
        'area_impresion': d.area_impresion,
        'precio': f"{d.precio_unitario:.2f}",
        'descuento_pct': d.descuento_pct or 0.0,
        'descuento_monto': f"{(d.descuento_monto or 0.0):.2f}",
        'promo_aplicada': d.promo_aplicada or '',
        'importe': f"{d.importe:.2f}",
        'es_modificador': d.es_modificador,
        'impreso': d.impreso_comanda
    } for idx, d in enumerate(detalles_ord)]

    return jsonify({
        'id': c.id, 'sucursal': c.sucursal, 'mesa': c.mesa, 'area': c.area,
        'mesero': c.mesero, 'personas': c.personas, 'orden': c.orden,
        'folio': c.folio or '0', 'estado': c.estado,
        'es_subcuenta_parte': bool(c.es_subcuenta_parte),
        'apertura': c.apertura.strftime('%d/%m/%Y %I:%M:%S %p') if c.apertura else '',
        'cierre': c.cierre.strftime('%d/%m/%Y %I:%M:%S %p') if c.cierre else '',
        'impresa': bool(c.impresa), 'observaciones': c.observaciones or '',
        'subtotal': f"{c.subtotal:.2f}", 'descuento_pct': c.descuento_pct or 0.0,
        'descuento_monto': f"{(c.descuento_monto or 0.0):.2f}", 'iva': f"{c.iva:.2f}",
        'total': f"{c.total:.2f}", 'total_num': c.total,
        'total_letras': numero_a_letras_mxn(c.total),
        'datos_ticket': obtener_datos_ticket(c.sucursal),
        'pago_efectivo': c.pago_efectivo or 0.0,
        'pago_tarjeta_debito': c.pago_tarjeta_debito or 0.0,
        'pago_tarjeta_credito': c.pago_tarjeta_credito or 0.0,
        'pago_transferencia': c.pago_transferencia or 0.0,
        'pago_otros': c.pago_otros or 0.0,
        'tarjeta_ultimos4': c.tarjeta_ultimos4 or '',
        'propina_tarjeta': c.propina_tarjeta or 0.0,
        'cambio': c.cambio or 0.0,
        'items': items
    })


@pos_bp.route('/api/pos/cuentas_abiertas_vivo')
@login_required
def api_pos_cuentas_abiertas_vivo():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'cuentas': []}), 403
    suc = obtener_sucursal_activa(session)
    abiertas = CuentaPOS.query.filter_by(sucursal=suc, estado='ABIERTA').order_by(CuentaPOS.id.asc()).all()
    ids_abiertas = [c.id for c in abiertas]
    alertas = (
        {a.cuenta_id: a.solicito_cuenta for a in AlertaMesaPOS.query.filter(AlertaMesaPOS.cuenta_id.in_(ids_abiertas)).all()}
        if ids_abiertas else {}
    )
    return jsonify({
        'ok': True, 'sucursal': suc,
        'cuentas': [{
            'id': c.id, 'mesa': c.mesa, 'impresa': bool(c.impresa),
            'mesero': c.mesero, 'orden': c.orden, 'total': f"{c.total:.2f}",
            'solicito_cuenta': bool(alertas.get(c.id, False))
        } for c in abiertas]
    })


@pos_bp.route('/api/pos/mesas_tablet_v2')
@login_required
def api_pos_mesas_tablet_v2():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'tarjetas': []}), 403
    suc = obtener_sucursal_activa(session)
    abiertas = CuentaPOS.query.filter_by(sucursal=suc, estado='ABIERTA').order_by(CuentaPOS.id.asc()).all()
    ids_abiertas = [c.id for c in abiertas]
    parent_ids = {c.parent_cuenta_id for c in abiertas if c.parent_cuenta_id}
    divididas_padres = (
        CuentaPOS.query.filter(CuentaPOS.id.in_(parent_ids), CuentaPOS.estado == 'DIVIDIDA').all()
        if parent_ids else []
    )
    alertas = (
        {a.cuenta_id: a for a in AlertaMesaPOS.query.filter(AlertaMesaPOS.cuenta_id.in_(ids_abiertas)).all()}
        if ids_abiertas else {}
    )
    ahora = ahora_local()

    # Agrupar subcuentas abiertas por mesa raíz (ej. M4-A, M4-1 -> M4)
    hijas_por_padre_id = {}
    for c in abiertas:
        if c.parent_cuenta_id:
            hijas_por_padre_id.setdefault(c.parent_cuenta_id, []).append(c)

    mapa_divididas = {}
    for p in divididas_padres:
        hijas = hijas_por_padre_id.get(p.id, [])
        if hijas:
            mapa_divididas[p.mesa.upper()] = (p, hijas)

    mapa_abiertas = {c.mesa.upper(): c for c in abiertas if not c.parent_cuenta_id or c.parent_cuenta_id not in [p.id for p, _ in mapa_divididas.values()]}
    orden_fijo = ['M1', 'M2', 'M3', 'M4', 'M5', 'M6'] + [f"T{i:02d}" for i in range(1, 13)]
    tarjetas = []
    vistas_ids = set()

    def _card_abierta(cod, c):
        al = alertas.get(c.id)
        mins = int((ahora - c.apertura).total_seconds() // 60) if c.apertura else 0
        return {
            'codigo': cod, 'ocupada': True, 'dividida': False, 'subcuentas': [],
            'impresa': bool(c.impresa), 'solicito_cuenta': bool(al.solicito_cuenta) if al else False,
            'minutos': max(0, mins), 'cuenta_id': c.id,
            'titulo': c.observaciones.strip().upper() if (c.observaciones and len(c.observaciones.strip()) <= 14) else c.mesa,
            'total': f"{c.total:.2f}", 'personas': c.personas, 'mesero': c.mesero, 'orden': c.orden
        }

    def _card_dividida(cod, padre, hijas):
        mins = int((ahora - padre.apertura).total_seconds() // 60) if padre.apertura else 0
        subs = []
        for h in hijas:
            vistas_ids.add(h.id)
            al = alertas.get(h.id)
            subs.append({
                'cuenta_id': h.id, 'mesa': h.mesa, 'total': f"{h.total:.2f}",
                'impresa': bool(h.impresa), 'mesero': h.mesero,
                'solicito_cuenta': bool(al.solicito_cuenta) if al else False
            })
        return {
            'codigo': cod, 'ocupada': True, 'dividida': True, 'subcuentas': subs,
            'impresa': all(h.impresa for h in hijas),
            'solicito_cuenta': any(s['solicito_cuenta'] for s in subs),
            'minutos': max(0, mins), 'cuenta_id': hijas[0].id,
            'titulo': cod, 'total': f"{sum(h.total for h in hijas):.2f}",
            'personas': padre.personas, 'mesero': padre.mesero, 'orden': padre.orden
        }

    for cod in orden_fijo:
        alt = f"M0{cod[1:]}" if (cod.startswith('M') and len(cod) == 2) else cod
        if cod in mapa_divididas or alt in mapa_divididas:
            p, hijas = mapa_divididas.get(cod) or mapa_divididas.get(alt)
            tarjetas.append(_card_dividida(cod, p, hijas))
            continue
        c = mapa_abiertas.get(cod) or mapa_abiertas.get(alt)
        if c:
            vistas_ids.add(c.id)
            tarjetas.append(_card_abierta(cod, c))
        else:
            tarjetas.append({
                'codigo': cod, 'ocupada': False, 'dividida': False, 'subcuentas': [],
                'impresa': False, 'solicito_cuenta': False, 'minutos': 0, 'cuenta_id': None,
                'titulo': cod, 'total': '0.00', 'personas': 0, 'mesero': '', 'orden': ''
            })

    # Cuentas libres o subcuentas que no pertenecen a M1-M6/T01-T12
    for p, hijas in mapa_divididas.values():
        if p.mesa.upper() not in orden_fijo:
            tarjetas.insert(0, _card_dividida(p.mesa, p, hijas))
    for c in abiertas:
        if c.id not in vistas_ids:
            tarjetas.insert(0, _card_abierta(c.mesa, c))

    return jsonify({'ok': True, 'sucursal': suc, 'tarjetas': tarjetas})


# ==============================================================================
# CAPTURA INTELIGENTE (AGRUPACIÓN + MODIFICADORES LIGADOS + PROMOCIONES)
# ==============================================================================
@pos_bp.route('/api/pos/capturar_item', methods=['POST'])
@login_required
def api_pos_capturar_item():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if c.estado != 'ABIERTA':
        return jsonify({'ok': False, 'msg': 'La cuenta ya está cerrada.'}), 400
    if c.impresa:
        return jsonify({'ok': False, 'msg': 'Cuenta impresa. Reábrela con clave para agregar productos.'}), 400

    cant = _num(data.get('cantidad', 1), minimo=0.001, maximo=999.0)
    precio = _num(data.get('precio', 0), maximo=100000.0)
    es_mod = bool(data.get('es_modificador', False))
    comanda = int(data.get('comanda', 1))
    clave = str(data.get('clave', '02001')).strip()
    desc_limpia = str(data.get('descripcion', '')).strip().upper().lstrip('>')
    desc = f">{desc_limpia}" if es_mod else desc_limpia
    area_req = str(data.get('area_impresion', '')).strip().upper()
    if area_req not in ('COCINA', 'BARRA'):
        pid_cap = data.get('producto_id')
        if not pid_cap:
            clv_num = str(clave).lstrip('0')
            if clv_num.isdigit():
                pid_cap = int(clv_num)
        if pid_cap:
            area_req = _cargar_areas_prods().get(str(int(pid_cap)), '')
    area_imp = area_req if area_req in ('COCINA', 'BARRA') else detectar_area_impresion(data.get('categoria', 'Barra'))
    mods_hijos = data.get('modificadores') or []
    agrupar = bool(data.get('agrupar', True))

    # Caso 1: Producto principal sin modificadores y sin separador intermedio -> agrupar si ya existe sin imprimir
    if not es_mod and not mods_hijos and agrupar and clave not in ('SEP', 'NOTA'):
        detalles_act = DetallePOS.query.filter_by(cuenta_id=c.id).order_by(DetallePOS.id.desc()).all()
        for d in detalles_act:
            if d.clave == 'SEP':
                break  # Respeta separadores de comanda
            if (not d.es_modificador and not d.impreso_comanda and d.num_comanda == comanda
                    and d.descripcion == desc and abs(d.precio_unitario - precio) < 0.01):
                tiene_hijos = DetallePOS.query.filter_by(cuenta_id=c.id, parent_detalle_id=d.id).first()
                if not tiene_hijos:
                    d.cantidad = round(d.cantidad + cant, 3)
                    d.importe = round(d.cantidad * d.precio_unitario, 2)
                    db.session.flush()
                    recalcular_totales_cuenta(c)
                    db.session.commit()
                    return jsonify({'ok': True, 'agrupado': True, 'detalle_id': d.id})

    # Si llega un modificador o comentario suelto, ligarlo al producto indicado o al último principal
    parent_id = data.get('parent_detalle_id')
    area_explicita = str(data.get('area_impresion', '')).strip().upper()
    if area_explicita in ('BARRA', 'COCINA'):
        area_imp = area_explicita
    elif es_mod and clave != 'SEP':
        ref_prod = DetallePOS.query.filter_by(id=int(parent_id), cuenta_id=c.id).first() if parent_id else None
        if not ref_prod:
            ref_prod = DetallePOS.query.filter_by(cuenta_id=c.id, es_modificador=False).order_by(DetallePOS.id.desc()).first()
        if ref_prod:
            parent_id = ref_prod.id
            area_imp = _resolver_area_modificador({'nombre': desc_limpia}, ref_prod.area_impresion)

    nuevo_item = DetallePOS(
        cuenta_id=c.id,
        parent_detalle_id=int(parent_id) if parent_id else None,
        num_comanda=comanda,
        cantidad=cant,
        clave=clave,
        descripcion=desc,
        area_impresion=area_imp,
        es_modificador=es_mod,
        precio_unitario=precio,
        importe=round(cant * precio, 2),
        impreso_comanda=False
    )
    db.session.add(nuevo_item)
    db.session.flush()

    # Si el frontend mandó modificadores/comentarios anidados, respetar área propia (ej. FRUTA/CAFÉ -> BARRA)
    for m in mods_hijos:
        m_cant = _num(m.get('cantidad', 1), minimo=0.001, maximo=999.0)
        m_pre = _num(m.get('precio', 0), maximo=100000.0)
        m_desc_raw = str(m.get('nombre') or m.get('descripcion') or '').strip().upper().lstrip('>')
        if not m_desc_raw:
            continue
        m_clave = str(m.get('clave', 'MOD')).strip().upper()
        m_area = area_imp if m_clave == 'NOTA' else _resolver_area_modificador(m, area_imp)
        db.session.add(DetallePOS(
            cuenta_id=c.id,
            parent_detalle_id=nuevo_item.id,
            num_comanda=comanda,
            cantidad=m_cant,
            clave=m_clave,
            descripcion=f">{m_desc_raw}",
            area_impresion=m_area,
            es_modificador=True,
            precio_unitario=m_pre,
            importe=round(m_cant * m_pre, 2),
            impreso_comanda=False
        ))

    db.session.flush()
    recalcular_totales_cuenta(c)
    db.session.commit()
    return jsonify({'ok': True, 'detalle_id': nuevo_item.id})


def _generar_comandas_pendientes(c):
    pendientes = DetallePOS.query.filter_by(cuenta_id=c.id, impreso_comanda=False).order_by(DetallePOS.id.asc()).all()
    if not pendientes:
        return False

    ya_tenia_enviados = DetallePOS.query.filter_by(cuenta_id=c.id, impreso_comanda=True).count() > 0
    titulo_estado = "== ADICIONAL ==" if ya_tenia_enviados else "== CUENTA NUEVA =="

    padres_map = {d.id: d for d in DetallePOS.query.filter_by(cuenta_id=c.id, es_modificador=False).all()}
    por_area = {'BARRA': [], 'COCINA': []}
    for d in pendientes:
        area = d.area_impresion if d.area_impresion in por_area else 'COCINA'
        por_area[area].append(d)
        d.impreso_comanda = True

    area_mesa_limpia = re.sub(r'^\d+\s*', '', (c.area or 'COMEDOR')).upper()
    ahora_str = ahora_local().strftime('%d/%m/%Y %I:%M:%S %p')

    for area_nom in ('BARRA', 'COCINA'):
        lista = por_area[area_nom]
        if not lista:
            continue
        filas = []
        tiempo_actual = None
        for it in lista:
            if not it.es_modificador and (it.num_comanda or 1) > 1 and it.num_comanda != tiempo_actual:
                tiempo_actual = it.num_comanda
                filas.append(f"<tr><td colspan='2' style='font-size:12px;padding-top:4px;'>--- TIEMPO {tiempo_actual} ---</td></tr>")
            if it.clave == 'SEP':
                filas.append("<tr><td colspan='2' style='text-align:center;font-size:12px;'>================================</td></tr>")
                continue
            texto_item = _esc(it.descripcion)
            # Si es un modificador de paquete ruteado a otra área (ej. FRUTA/CAFE en BARRA de un PAQUETE de COCINA), agregar referencia
            if it.es_modificador and it.parent_detalle_id and it.parent_detalle_id in padres_map:
                padre = padres_map[it.parent_detalle_id]
                if padre.area_impresion != area_nom:
                    texto_item = _esc(f"{it.descripcion.lstrip('>')} ({padre.descripcion})")
            if it.es_modificador and not (it.parent_detalle_id in padres_map and padres_map[it.parent_detalle_id].area_impresion != area_nom):
                filas.append(f"<tr><td style='width:14%;'></td><td style='width:86%;font-size:13px;padding-left:6px;'>{texto_item}</td></tr>")
            else:
                cant_txt = int(it.cantidad) if float(it.cantidad).is_integer() else f"{it.cantidad:g}"
                filas.append(f"<tr><td style='width:14%;font-size:16px;font-weight:900;'>{cant_txt}</td><td style='width:86%;font-size:16px;font-weight:900;'>{texto_item}</td></tr>")

        filas_html = "".join(filas)
        html_ticket = f"""
        <div class='ticket-termico' style='page-break-after:always;break-after:page;'>
            <div style='font-size:13px;font-weight:bold;'>{titulo_estado}</div>
            <div style='font-size:14px;font-weight:900;'>{area_nom} ({area_mesa_limpia}) ORDEN: {c.orden}</div>
            <div style='font-size:12px;'>{ahora_str}</div>
            <div style='font-size:13px;font-weight:bold;'>MESA: {_esc(c.mesa)} - PERSONAS: {c.personas} &nbsp;MESERO: {_esc(c.mesero)}</div>
            <div>================================</div>
            <table style='width:100%;border-collapse:collapse;'>{filas_html}</table>
            {f"<div style='margin-top:6px;font-size:12px;'><b>NOTA CUENTA:</b> {_esc(c.observaciones)}</div>" if c.observaciones else ""}
            <div>================================</div>
        </div>"""
        db.session.add(ColaImpresionPOS(sucursal=c.sucursal, tipo=f"COMANDA_{area_nom}", contenido_html=html_ticket, fecha=ahora_local()))
    return True


@pos_bp.route('/api/pos/enviar_comanda/<int:cuenta_id>', methods=['POST'])
@login_required
def api_pos_enviar_comanda(cuenta_id):
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    c = CuentaPOS.query.get_or_404(cuenta_id)
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if not _generar_comandas_pendientes(c):
        return jsonify({'ok': False, 'msg': 'No hay productos nuevos por enviar a cocina/barra.'})
    db.session.commit()
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/enviar_ronda_lote', methods=['POST'])
@login_required
def api_pos_enviar_ronda_lote():
    """Guarda toda la ronda confirmada por el mesero y genera comandas BARRA/COCINA en 1 sola petición atómica."""
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if c.estado != 'ABIERTA':
        return jsonify({'ok': False, 'msg': 'La cuenta ya está cerrada.'}), 400
    if c.impresa:
        return jsonify({'ok': False, 'msg': 'Cuenta impresa. Reábrela con clave de Admin/Gerente.'}), 400

    items = data.get('items') or []
    if not items:
        return jsonify({'ok': False, 'msg': 'No hay platillos en la ronda.'}), 400

    for it in items:
        clave = str(it.get('clave', '02001')).strip().upper()
        comanda = max(1, min(4, int(it.get('comanda', 1))))
        if clave == 'SEP':
            db.session.add(DetallePOS(
                cuenta_id=c.id, num_comanda=comanda, cantidad=1.0, clave='SEP',
                descripcion='============', area_impresion='COCINA',
                es_modificador=True, precio_unitario=0.0, importe=0.0, impreso_comanda=False
            ))
            continue

        cant = _num(it.get('cantidad', 1), minimo=0.001, maximo=999.0)
        precio = _num(it.get('precio', 0), maximo=100000.0)
        es_mod = bool(it.get('es_modificador', False))
        desc_limpia = str(it.get('descripcion', '')).strip().upper().lstrip('>')
        if not desc_limpia:
            continue
        desc = f">{desc_limpia}" if es_mod else desc_limpia
        area_imp = str(it.get('area_impresion', '')).strip().upper()
        if area_imp not in ('BARRA', 'COCINA'):
            area_imp = detectar_area_impresion(it.get('categoria', 'Barra'))

        nuevo_item = DetallePOS(
            cuenta_id=c.id, num_comanda=comanda, cantidad=cant, clave=clave,
            descripcion=desc, area_impresion=area_imp, es_modificador=es_mod,
            precio_unitario=precio, importe=round(cant * precio, 2), impreso_comanda=False
        )
        db.session.add(nuevo_item)
        db.session.flush()

        for m in (it.get('modificadores') or []):
            m_desc = str(m.get('nombre') or m.get('descripcion') or '').strip().upper().lstrip('>')
            if not m_desc:
                continue
            m_cant = _num(m.get('cantidad', 1), minimo=0.001, maximo=999.0)
            m_pre = _num(m.get('precio', 0), maximo=100000.0)
            m_clave = str(m.get('clave', 'MOD')).strip().upper()
            m_area = area_imp if m_clave == 'NOTA' else _resolver_area_modificador(m, area_imp)
            db.session.add(DetallePOS(
                cuenta_id=c.id, parent_detalle_id=nuevo_item.id, num_comanda=comanda,
                cantidad=m_cant, clave=m_clave, descripcion=f">{m_desc}",
                area_impresion=m_area, es_modificador=True, precio_unitario=m_pre,
                importe=round(m_cant * m_pre, 2), impreso_comanda=False
            ))

        nota_txt = str(it.get('comentario') or '').strip().upper()
        if nota_txt:
            db.session.add(DetallePOS(
                cuenta_id=c.id, parent_detalle_id=nuevo_item.id, num_comanda=comanda,
                cantidad=1.0, clave='NOTA', descripcion=f">NOTA: {nota_txt}",
                area_impresion=area_imp, es_modificador=True, precio_unitario=0.0,
                importe=0.0, impreso_comanda=False
            ))

    db.session.flush()
    recalcular_totales_cuenta(c)
    _generar_comandas_pendientes(c)
    db.session.commit()
    return jsonify({'ok': True, 'total': f"{c.total:.2f}"})


# ==============================================================================
# CANCELACIONES (INDIVIDUAL, PARCIAL POR LOTE Y ELIMINAR/CANCELAR CUENTA ABIERTA)
# ==============================================================================
@pos_bp.route('/api/pos/cancelar_item', methods=['POST'])
@login_required
def api_pos_cancelar_item():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    item = DetallePOS.query.get_or_404(int(data['item_id']))
    _cta_item = CuentaPOS.query.get(item.cuenta_id)
    if _cta_item is not None and not _cuenta_permitida(_cta_item):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    cuenta = item.cuenta

    # Si el producto aún no se envió a cocina/barra, se puede quitar sin contraseña
    era_impreso = bool(item.impreso_comanda)
    autorizo = current_user.username.upper()
    if era_impreso:
        permisos = ConfigPermisosPOS.query.first()
        permitir = bool(permisos and permisos.cajero_puede_cancelar)
        autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=permitir)
        if not autorizo:
            return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Requiere contraseña de Admin o Gerente.'}), 403

    cant_quitar = _num(data.get('cantidad', item.cantidad))
    motivo = str(data.get('motivo', '')).strip()
    monto_canc = round(min(cant_quitar, item.cantidad) * item.precio_unitario, 2)
    desc_item = item.descripcion

    if cant_quitar < item.cantidad and cant_quitar > 0:
        item.cantidad = round(item.cantidad - cant_quitar, 3)
        item.importe = round(item.cantidad * item.precio_unitario, 2)
    else:
        # Eliminar modificadores ligados a este producto principal
        if not item.es_modificador:
            hijos = DetallePOS.query.filter_by(cuenta_id=cuenta.id, parent_detalle_id=item.id).all()
            for h in hijos:
                monto_canc += h.importe
                db.session.delete(h)
        db.session.delete(item)

    db.session.flush()
    recalcular_totales_cuenta(cuenta)
    db.session.commit()

    if era_impreso:
        det_txt = f'Canceló {cant_quitar:g}x {desc_item}' + (f' ({motivo})' if motivo else '')
        registrar_bitacora('CANCELACION', cuenta.mesa, monto_canc, det_txt, autorizo=autorizo, sucursal=cuenta.sucursal)
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/cancelar_items_lote', methods=['POST'])
@login_required
def api_pos_cancelar_items_lote():
    """Cancelación parcial/múltiple estilo manual: cantidad a cancelar + motivo + clave."""
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    cuenta = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(cuenta):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    items_req = data.get('items', [])
    if not items_req:
        return jsonify({'ok': False, 'msg': 'Selecciona al menos un producto a cancelar.'}), 400

    permisos = ConfigPermisosPOS.query.first()
    permitir = bool(permisos and permisos.cajero_puede_cancelar)
    autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=permitir)
    if not autorizo:
        return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Contraseña de autorización incorrecta.'}), 403

    motivo_gral = str(data.get('motivo_general', '')).strip()
    total_cancelado = 0.0
    resumen_desc = []

    for req_it in items_req:
        det = DetallePOS.query.filter_by(id=int(req_it['id']), cuenta_id=cuenta.id).first()
        if not det:
            continue
        cant_c = _num(req_it.get('cantidad', det.cantidad))
        if cant_c <= 0:
            continue
        mot = str(req_it.get('motivo', '')).strip() or motivo_gral
        if cant_c >= det.cantidad:
            total_cancelado += det.importe
            resumen_desc.append(f"{det.cantidad:g}x {det.descripcion}" + (f" [{mot}]" if mot else ""))
            if not det.es_modificador:
                for h in DetallePOS.query.filter_by(cuenta_id=cuenta.id, parent_detalle_id=det.id).all():
                    total_cancelado += h.importe
                    db.session.delete(h)
            db.session.delete(det)
        else:
            monto_p = round(cant_c * det.precio_unitario, 2)
            total_cancelado += monto_p
            det.cantidad = round(det.cantidad - cant_c, 3)
            det.importe = round(det.cantidad * det.precio_unitario, 2)
            resumen_desc.append(f"{cant_c:g}x {det.descripcion}" + (f" [{mot}]" if mot else ""))

    db.session.flush()
    recalcular_totales_cuenta(cuenta)
    db.session.commit()
    registrar_bitacora('CANCELACION', cuenta.mesa, total_cancelado, ', '.join(resumen_desc), autorizo=autorizo, sucursal=cuenta.sucursal)
    return jsonify({'ok': True, 'total': cuenta.total})


@pos_bp.route('/api/pos/cancelar_cuenta_abierta', methods=['POST'])
@pos_bp.route('/api/pos/eliminar_cuenta_vacia', methods=['POST'])
@login_required
def api_pos_cancelar_cuenta_abierta():
    """Permite eliminar cuenta vacía o cancelar cuenta abierta con productos usando clave de Raquel."""
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if c.estado != 'ABIERTA':
        return jsonify({'ok': False, 'msg': 'La cuenta ya no está abierta.'}), 400

    tiene_prods = len(c.detalles) > 0
    motivo = str(data.get('motivo', '')).strip()
    autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=False)
    if not autorizo:
        return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Se requiere contraseña de Admin o Gerente.'}), 403

    if tiene_prods and not motivo:
        motivo = 'Cuenta cancelada por Administración'

    monto_ant = c.total
    mesa_nom = c.mesa
    c.estado = 'CANCELADA'
    c.cierre = ahora_local()
    db.session.commit()

    accion = 'CANCELACION' if tiene_prods else 'ELIMINAR_CUENTA'
    det = f"Cuenta cancelada ({len(c.detalles)} prod.): {motivo}" if tiene_prods else "Cuenta vacía eliminada"
    registrar_bitacora(accion, mesa_nom, monto_ant, det, autorizo=autorizo, sucursal=c.sucursal)
    return jsonify({'ok': True})


# ==============================================================================
# DESCUENTOS (GENERAL Y POR PRODUCTO)
# ==============================================================================
@pos_bp.route('/api/pos/descuento_autorizado', methods=['POST'])
@login_required
def api_pos_descuento_autorizado():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    pct = max(0.0, min(100.0, _num(data.get('porcentaje', 0), minimo=-1_000_000.0, maximo=1_000_000.0)))
    comentario = str(data.get('comentario', '')).strip()

    permisos = ConfigPermisosPOS.query.first()
    permitir = bool(permisos and permisos.cajero_puede_descontar)
    autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=permitir)
    if not autorizo:
        return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Contraseña de autorización incorrecta.'}), 403

    c.descuento_pct = pct
    recalcular_totales_cuenta(c)

    al = AlertaMesaPOS.query.filter_by(cuenta_id=c.id).first()
    motivo_txt = comentario or f'Descuento {pct:g}%'
    if not al:
        db.session.add(AlertaMesaPOS(cuenta_id=c.id, descuento_motivo=motivo_txt, fecha_alerta=ahora_local()))
    else:
        al.descuento_motivo = motivo_txt

    db.session.commit()
    registrar_bitacora('DESCUENTO', c.mesa, c.descuento_monto, f'{pct:g}% ({motivo_txt})', autorizo=autorizo, sucursal=c.sucursal)
    return jsonify({'ok': True, 'descuento_monto': c.descuento_monto, 'total': c.total})


@pos_bp.route('/api/pos/descuento_productos', methods=['POST'])
@login_required
def api_pos_descuento_productos():
    """Descuento individual por producto (solo a productos principales, no modificadores)."""
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    items_desc = data.get('items', [])
    if not items_desc:
        return jsonify({'ok': False, 'msg': 'Selecciona al menos un producto.'}), 400

    permisos = ConfigPermisosPOS.query.first()
    permitir = bool(permisos and permisos.cajero_puede_descontar)
    autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=permitir)
    if not autorizo:
        return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Contraseña de autorización incorrecta.'}), 403

    motivo_gral = str(data.get('motivo', '')).strip()
    aplicados = []
    for it in items_desc:
        det = DetallePOS.query.filter_by(id=int(it['id']), cuenta_id=c.id, es_modificador=False).first()
        if not det:
            continue
        pct = max(0.0, min(100.0, _num(it.get('porcentaje', 0), minimo=-1_000_000.0, maximo=1_000_000.0)))
        det.descuento_pct = pct
        det.promo_aplicada = None
        aplicados.append(f"{det.descripcion} ({pct:g}%)")

    db.session.flush()
    recalcular_totales_cuenta(c)
    db.session.commit()
    registrar_bitacora('DESCUENTO_PROD', c.mesa, c.descuento_monto, ', '.join(aplicados) + (f' - {motivo_gral}' if motivo_gral else ''), autorizo=autorizo, sucursal=c.sucursal)
    return jsonify({'ok': True, 'total': c.total})


# ==============================================================================
# DIVIDIR CUENTA (POR PARTES EDITABLES Y POR PRODUCTOS CON CANTIDADES PARCIALES)
# ==============================================================================
@pos_bp.route('/api/pos/dividir_partes', methods=['POST'])
@login_required
def api_pos_dividir_partes():
    """Divide en N subcuentas (hasta 26) o montos personalizados sin borrar los platillos originales."""
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c_orig = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c_orig):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if c_orig.estado != 'ABIERTA':
        return jsonify({'ok': False, 'msg': 'La cuenta no está abierta.'}), 400
    if c_orig.impresa:
        return jsonify({'ok': False, 'msg': 'No se puede dividir una cuenta impresa.'}), 400
    if c_orig.total <= 0:
        return jsonify({'ok': False, 'msg': 'La cuenta debe tener consumo mayor a $0.'}), 400

    montos_custom = data.get('montos')
    if montos_custom and isinstance(montos_custom, list) and len(montos_custom) >= 2:
        montos = [round(v, 2) for v in (_num(x, minimo=-1_000_000.0, maximo=1_000_000.0) for x in montos_custom) if v > 0]
        if len(montos) < 2:
            return jsonify({'ok': False, 'msg': 'Se requieren al menos 2 importes mayores a $0.'}), 400
        if abs(sum(montos) - c_orig.total) > 0.05:
            return jsonify({'ok': False, 'msg': f'La suma (${sum(montos):.2f}) debe igualar el total (${c_orig.total:.2f}).'}), 400
    else:
        partes = max(2, min(26, int(data.get('partes', 2))))
        base = round(c_orig.total / partes, 2)
        montos = [base] * partes
        dif = round(c_orig.total - sum(montos), 2)
        montos[0] = round(montos[0] + dif, 2)

    suc = c_orig.sucursal
    turno = obtener_turno_activo(suc)
    hoy_inicio = inicio_hoy_local()
    imprimir = bool(data.get('imprimir', False))

    # Conservamos los platillos reales en la cuenta padre (para reportes y recetas)
    c_orig.estado = 'DIVIDIDA'
    creadas = []
    for idx, monto in enumerate(montos):
        num_orden = CuentaPOS.query.filter(CuentaPOS.sucursal == suc, CuentaPOS.apertura >= hoy_inicio).count() + 1
        sub_mesa = f"{c_orig.mesa}-{idx + 1}"
        c_sub = CuentaPOS(
            turno_id=turno.id, sucursal=suc, parent_cuenta_id=c_orig.id,
            es_subcuenta_parte=True, orden=f"A{num_orden}", area=c_orig.area,
            mesa=sub_mesa, mesero=c_orig.mesero, personas=1,
            apertura=ahora_local(), impresa=imprimir, estado='ABIERTA'
        )
        db.session.add(c_sub)
        db.session.flush()
        db.session.add(DetallePOS(
            cuenta_id=c_sub.id, num_comanda=1, cantidad=1, clave='DIV',
            descripcion=f"PARTE {idx + 1}/{len(montos)} DE {c_orig.mesa}",
            area_impresion='BARRA', es_modificador=False,
            precio_unitario=monto, importe=monto, impreso_comanda=True
        ))
        db.session.flush()
        recalcular_totales_cuenta(c_sub)
        if imprimir:
            db.session.add(ColaImpresionPOS(sucursal=suc, tipo='PRECUENTA', contenido_html=_armar_ticket_precuenta_html(c_sub), fecha=ahora_local()))
        creadas.append({'id': c_sub.id, 'mesa': c_sub.mesa, 'total': f"{c_sub.total:.2f}"})

    db.session.commit()
    registrar_bitacora('DIVIDIR_PARTES', c_orig.mesa, c_orig.total, f'Dividida en {len(montos)} subcuentas', sucursal=suc)
    return jsonify({'ok': True, 'creadas': creadas})


@pos_bp.route('/api/pos/dividir_cuenta_real', methods=['POST'])
@login_required
def api_pos_dividir_cuenta_real():
    """Divide por productos hacia subcuentas A/B/C... con soporte de cantidades parciales y modificadores ligados."""
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c_orig = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c_orig):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if c_orig.estado != 'ABIERTA':
        return jsonify({'ok': False, 'msg': 'La cuenta no está abierta.'}), 400
    if c_orig.impresa:
        return jsonify({'ok': False, 'msg': 'No se puede dividir una cuenta impresa.'}), 400

    # Soporta formato multi-cuenta { "A": [{id, cantidad}], "B": [...] } o simple item_ids: [1,2]
    subcuentas_map = data.get('subcuentas')
    if not subcuentas_map:
        item_ids = [int(x) for x in data.get('item_ids', [])]
        if not item_ids:
            return jsonify({'ok': False, 'msg': 'Selecciona al menos un producto.'}), 400
        subcuentas_map = {'B': [{'id': iid} for iid in item_ids]}

    suc = c_orig.sucursal
    turno = obtener_turno_activo(suc)
    hoy_inicio = inicio_hoy_local()
    imprimir = bool(data.get('imprimir', False))
    creadas = []

    for letra, items_lista in subcuentas_map.items():
        if not items_lista:
            continue
        num_orden = CuentaPOS.query.filter(CuentaPOS.sucursal == suc, CuentaPOS.apertura >= hoy_inicio).count() + 1
        sub_mesa = f"{c_orig.mesa}-{str(letra).strip().upper()}"
        if CuentaPOS.query.filter_by(sucursal=suc, mesa=sub_mesa, estado='ABIERTA').first():
            sub_mesa = f"{c_orig.mesa}-{str(letra).strip().upper()}{num_orden}"

        c_nueva = CuentaPOS(
            turno_id=turno.id, sucursal=suc, parent_cuenta_id=c_orig.parent_cuenta_id or c_orig.id,
            orden=f"A{num_orden}", area=c_orig.area, mesa=sub_mesa,
            mesero=c_orig.mesero, personas=1, apertura=ahora_local(),
            descuento_pct=c_orig.descuento_pct, impresa=imprimir, estado='ABIERTA'
        )
        db.session.add(c_nueva)
        db.session.flush()

        movidos = 0
        for entry in items_lista:
            det_id = int(entry['id']) if isinstance(entry, dict) else int(entry)
            det = DetallePOS.query.filter_by(id=det_id, cuenta_id=c_orig.id).first()
            if not det:
                continue
            cant_mover = _num(entry.get('cantidad', det.cantidad)) if isinstance(entry, dict) else det.cantidad
            if cant_mover <= 0:
                continue

            if cant_mover >= det.cantidad:
                det.cuenta_id = c_nueva.id
                if not det.es_modificador:
                    for h in DetallePOS.query.filter_by(cuenta_id=c_orig.id, parent_detalle_id=det.id).all():
                        h.cuenta_id = c_nueva.id
                movidos += 1
            else:
                det.cantidad = round(det.cantidad - cant_mover, 3)
                det.importe = round(det.cantidad * det.precio_unitario, 2)
                clon = DetallePOS(
                    cuenta_id=c_nueva.id, num_comanda=det.num_comanda,
                    cantidad=cant_mover, clave=det.clave, descripcion=det.descripcion,
                    area_impresion=det.area_impresion, es_modificador=det.es_modificador,
                    precio_unitario=det.precio_unitario, descuento_pct=det.descuento_pct,
                    importe=round(cant_mover * det.precio_unitario, 2), impreso_comanda=det.impreso_comanda
                )
                db.session.add(clon)
                movidos += 1

        if movidos == 0:
            db.session.delete(c_nueva)
            continue

        db.session.flush()
        recalcular_totales_cuenta(c_nueva)
        if imprimir:
            db.session.add(ColaImpresionPOS(sucursal=suc, tipo='PRECUENTA', contenido_html=_armar_ticket_precuenta_html(c_nueva), fecha=ahora_local()))
        creadas.append({'id': c_nueva.id, 'mesa': c_nueva.mesa, 'total': f"{c_nueva.total:.2f}"})

    db.session.flush()
    # Si la cuenta original quedó sin productos, cerrarla como DIVIDIDA para no dejar basura en $0
    if len(c_orig.detalles) == 0:
        c_orig.estado = 'DIVIDIDA'
        c_orig.total = 0.0
        c_orig.subtotal = 0.0
        c_orig.iva = 0.0
    else:
        recalcular_totales_cuenta(c_orig)

    db.session.commit()
    registrar_bitacora('DIVIDIR_CUENTA', c_orig.mesa, c_orig.total, f"Subcuentas: {', '.join(x['mesa'] for x in creadas)}", sucursal=suc)
    return jsonify({'ok': True, 'nueva_cuenta_id': creadas[0]['id'] if creadas else c_orig.id, 'creadas': creadas})


@pos_bp.route('/api/pos/juntar_cuentas', methods=['POST'])
@login_required
def api_pos_juntar_cuentas():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c_orig = CuentaPOS.query.get_or_404(int(data['origen_id']))
    if not _cuenta_permitida(c_orig):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    c_dest = CuentaPOS.query.get_or_404(int(data['destino_id']))
    if not _cuenta_permitida(c_dest):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if c_orig.id == c_dest.id:
        return jsonify({'ok': False, 'msg': 'Selecciona una cuenta diferente.'}), 400
    if c_orig.sucursal != c_dest.sucursal:
        return jsonify({'ok': False, 'msg': 'No se pueden juntar cuentas de distintas sucursales.'}), 400
    if c_dest.impresa or c_orig.impresa:
        return jsonify({'ok': False, 'msg': 'No se pueden juntar cuentas impresas.'}), 400

    for det in list(c_orig.detalles):
        det.cuenta_id = c_dest.id
    c_dest.personas += c_orig.personas
    mesa_orig = c_orig.mesa
    c_orig.estado = 'COMBINADA'  # No genera falsa alerta de cancelación
    c_orig.cierre = ahora_local()
    db.session.flush()
    recalcular_totales_cuenta(c_dest)
    db.session.commit()
    registrar_bitacora('JUNTAR_CUENTAS', c_dest.mesa, c_dest.total, f'{mesa_orig} -> {c_dest.mesa}', sucursal=c_dest.sucursal)
    return jsonify({'ok': True, 'destino_id': c_dest.id, 'mesa': c_dest.mesa})


# ==============================================================================
# PAGOS MIXTOS, VALE EMPLEADO, CAMBIO DE PAGO, REIMPRESIÓN Y CORTE X/Z
# ==============================================================================
@pos_bp.route('/api/pos/pagar_cuenta', methods=['POST'])
@login_required
def api_pos_pagar_cuenta():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False, 'msg': 'Los meseros no pueden cobrar cuentas.'}), 403

    data = request.json or {}
    ef = _num(data.get('efectivo', 0))
    td = _num(data.get('tarjeta_debito', 0))
    tc = _num(data.get('tarjeta_credito', 0))
    tr = _num(data.get('transferencia', 0))
    vale_emp = _num(data.get('vale_empleado', 0))
    propina = _num(data.get('propina', 0), maximo=100000.0)
    # Se bloquea la fila de la cuenta: si dos cajeros cobran a la vez, el segundo la verá ya PAGADA.
    c = CuentaPOS.query.filter_by(id=int(data['cuenta_id'])).with_for_update().first_or_404()
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if c.estado != 'ABIERTA':
        return jsonify({'ok': False, 'msg': 'Esta cuenta ya fue cerrada.'}), 400
    ult4 = str(data.get('tarjeta_ultimos4', '')).strip()[:4]
    emp_id = data.get('empleado_id')

    cubierto = round(ef + td + tc + tr + vale_emp, 2)
    if cubierto + 0.01 < c.total:
        return jsonify({'ok': False, 'msg': f'Monto insuficiente: cubierto ${cubierto:.2f} de ${c.total:.2f}.'}), 400
    if (td > 0 or tc > 0) and ult4 and not ult4.isdigit():
        return jsonify({'ok': False, 'msg': 'Los últimos 4 dígitos de la tarjeta deben ser numéricos.'}), 400

    if vale_emp > 0:
        emp = EmpleadoNominaPOS.query.get(int(emp_id)) if emp_id else None
        if not emp:
            return jsonify({'ok': False, 'msg': 'Selecciona el empleado para cargar el vale de consumo.'}), 400
        db.session.add(ConsumoEmpleadoPOS(
            fecha=ahora_local(), empleado_id=emp.id, empleado_nombre=emp.nombre,
            tipo='CONSUMO', concepto=f'CONSUMO POS MESA {c.mesa} ({c.orden})',
            monto=vale_emp, descontado=False, registrado_por=current_user.username.upper()
        ))

    if not c.folio:
        c.folio = _siguiente_folio_sucursal(c.sucursal)

    c.pago_efectivo = ef
    c.pago_tarjeta_debito = td
    c.pago_tarjeta_credito = tc
    c.pago_transferencia = tr
    c.pago_otros = vale_emp
    c.tarjeta_ultimos4 = ult4
    c.propina_tarjeta = propina
    c.cambio = round(max(0.0, cubierto - c.total), 2)
    c.cierre = ahora_local()
    c.estado = 'PAGADA'

    # Descuento automático de recetas en stock local de esta sucursal (Opción A)
    descontar_recetas_local(c)
    db.session.commit()
    return jsonify({'ok': True, 'folio': c.folio, 'cambio': c.cambio})


@pos_bp.route('/api/pos/cuentas_pagadas_turno')
@login_required
def api_pos_cuentas_pagadas_turno():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False}), 403
    suc = obtener_sucursal_activa(session)
    turno = obtener_turno_activo(suc)
    pagadas = CuentaPOS.query.filter_by(sucursal=suc, turno_id=turno.id, estado='PAGADA').order_by(CuentaPOS.id.desc()).all()
    return jsonify({
        'ok': True,
        'cuentas': [{
            'id': c.id, 'folio': c.folio or c.orden, 'mesa': c.mesa, 'mesero': c.mesero,
            'cierre': c.cierre.strftime('%H:%M') if c.cierre else '',
            'total': f"{c.total:.2f}", 'total_num': c.total,
            'efectivo': c.pago_efectivo or 0.0, 'tarjeta_debito': c.pago_tarjeta_debito or 0.0,
            'tarjeta_credito': c.pago_tarjeta_credito or 0.0, 'transferencia': c.pago_transferencia or 0.0,
            'vale_empleado': c.pago_otros or 0.0, 'propina': c.propina_tarjeta or 0.0,
            'tarjeta_ultimos4': c.tarjeta_ultimos4 or ''
        } for c in pagadas]
    })


@pos_bp.route('/api/pos/cambiar_forma_pago', methods=['POST'])
@login_required
def api_pos_cambiar_forma_pago():
    """Corrige la forma de pago de una cuenta ya cerrada con permiso/clave de Raquel."""
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    if c.estado != 'PAGADA':
        return jsonify({'ok': False, 'msg': 'Solo aplica a cuentas ya pagadas.'}), 400

    permisos = ConfigPermisosPOS.query.first()
    permitir = bool(permisos and permisos.cajero_puede_cambiar_pago)
    autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=permitir)
    if not autorizo:
        return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Requiere contraseña de Admin o Gerente.'}), 403

    ef = _num(data.get('efectivo', 0))
    td = _num(data.get('tarjeta_debito', 0))
    tc = _num(data.get('tarjeta_credito', 0))
    tr = _num(data.get('transferencia', 0))
    prop = _num(data.get('propina', c.propina_tarjeta or 0), maximo=100000.0)
    ult4 = str(data.get('tarjeta_ultimos4', c.tarjeta_ultimos4 or '')).strip()[:4]

    cubierto = round(ef + td + tc + tr + (c.pago_otros or 0.0), 2)
    if cubierto + 0.01 < c.total:
        return jsonify({'ok': False, 'msg': f'La suma (${cubierto:.2f}) no cubre el total (${c.total:.2f}).'}), 400

    antes = f"EF:${c.pago_efectivo:.0f} TD:${c.pago_tarjeta_debito:.0f} TC:${c.pago_tarjeta_credito:.0f} TR:${(c.pago_transferencia or 0):.0f}"
    c.pago_efectivo = ef
    c.pago_tarjeta_debito = td
    c.pago_tarjeta_credito = tc
    c.pago_transferencia = tr
    c.propina_tarjeta = prop
    c.tarjeta_ultimos4 = ult4
    c.cambio = round(max(0.0, cubierto - c.total), 2)
    db.session.commit()
    despues = f"EF:${ef:.0f} TD:${td:.0f} TC:${tc:.0f} TR:${tr:.0f}"
    registrar_bitacora('CAMBIO_PAGO', c.folio or c.mesa, c.total, f'{antes} -> {despues}', autorizo=autorizo, sucursal=c.sucursal)
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/abrir_turno_real', methods=['POST'])
@login_required
def api_pos_abrir_turno_real():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False, 'msg': 'Solo Caja, Gerente o Admin pueden abrir turno.'}), 403
    data = request.json or {}
    suc = obtener_sucursal_activa(session)
    fondo = _num(data.get('fondo_inicial', 0), maximo=1_000_000.0)
    turno = obtener_turno_activo(suc)
    autorizo = current_user.username.upper()
    # Si ya había un fondo capturado en el turno actual, modificarlo requiere clave de Admin o Gerente
    if turno.fondo_inicial and turno.fondo_inicial > 0 and abs(turno.fondo_inicial - fondo) > 0.01:
        autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=False)
        if not autorizo:
            return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Modificar el fondo de un turno ya abierto requiere clave de Admin o Gerente.'}), 403
    turno.fondo_inicial = fondo
    turno.cajero = current_user.username.upper()
    db.session.commit()
    registrar_bitacora('ABRIR_TURNO', f'TURNO #{turno.id}', fondo, f'Fondo inicial: ${fondo:.2f}', autorizo=autorizo, sucursal=suc)
    return jsonify({'ok': True, 'turno_id': turno.id, 'fondo': f"{fondo:.2f}"})


@pos_bp.route('/api/pos/movimiento_caja', methods=['POST'])
@login_required
def api_pos_movimiento_caja():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False, 'msg': 'Solo Caja puede registrar retiros o depósitos.'}), 403
    data = request.json or {}
    suc = obtener_sucursal_activa(session)
    turno = obtener_turno_activo(suc)
    monto = _num(data.get('monto', 0), maximo=1_000_000.0)
    tipo = str(data.get('tipo', 'RETIRO')).upper()
    if tipo not in ('RETIRO', 'DEPOSITO'):
        return jsonify({'ok': False, 'msg': 'Tipo de movimiento inválido'}), 400
    concepto = str(data.get('concepto', 'COMPRA DE INSUMOS')).strip().upper()
    if monto <= 0:
        return jsonify({'ok': False, 'msg': 'Monto inválido'}), 400

    autorizo = current_user.username.upper()
    if tipo == 'RETIRO':
        perm = ConfigPermisosPOS.query.first()
        permitir = bool(perm and perm.cajero_puede_retirar)
        autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=permitir)
        if not autorizo:
            return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Retirar efectivo requiere contraseña de Admin o Gerente.'}), 403

    db.session.add(MovimientoCajaPOS(turno_id=turno.id, tipo=tipo, monto=monto, concepto=concepto, usuario=current_user.username.upper(), fecha=ahora_local()))
    if tipo == 'RETIRO':
        turno.retiros_efectivo += monto
    else:
        turno.depositos_efectivo += monto

    html_vale = f"""
    <div class='ticket-termico'>
        <div style='text-align:center;font-weight:bold;font-size:15px;'>COMENSAL CONECTADO</div>
        <div style='text-align:center;font-size:11px;'>{suc.upper()}</div>
        <div style='text-align:center;font-weight:bold;'>VALE DE {tipo} DE CAJA</div>
        <div style='border-top:1px dashed #000;margin:6px 0;'></div>
        <div>FECHA: {ahora_local().strftime('%d/%m/%Y %I:%M %p')}</div>
        <div>CAJERO: {current_user.username.upper()}</div>
        <div>CONCEPTO: <b>{_esc(concepto)}</b></div>
        <div style='font-size:18px;font-weight:900;margin:8px 0;'>MONTO: ${monto:.2f}</div>
        <br><br><div style='border-top:1px solid #000;text-align:center;'>FIRMA DE RECIBIDO</div>
    </div>"""
    db.session.add(ColaImpresionPOS(sucursal=suc, tipo='VALE_CAJA', contenido_html=html_vale, fecha=ahora_local()))
    db.session.commit()
    registrar_bitacora(f'CAJA_{tipo}', f'TURNO #{turno.id}', monto, concepto, autorizo=autorizo, sucursal=suc)
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/corte_caja', methods=['GET'])
@login_required
def api_pos_corte_caja():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False}), 403
    suc = obtener_sucursal_activa(session)
    turno = obtener_turno_activo(suc)
    cuentas_pagadas = CuentaPOS.query.filter_by(sucursal=suc, turno_id=turno.id, estado='PAGADA').all()
    cuentas_abiertas = CuentaPOS.query.filter_by(sucursal=suc, estado='ABIERTA').count()

    ef_ventas = round(sum(max(0.0, (c.pago_efectivo or 0.0) - (c.cambio or 0.0)) for c in cuentas_pagadas), 2)
    tarj_debito = round(sum(c.pago_tarjeta_debito or 0.0 for c in cuentas_pagadas), 2)
    tarj_credito = round(sum(c.pago_tarjeta_credito or 0.0 for c in cuentas_pagadas), 2)
    transferencia = round(sum(c.pago_transferencia or 0.0 for c in cuentas_pagadas), 2)
    vales_emp = round(sum(c.pago_otros or 0.0 for c in cuentas_pagadas), 2)
    total_tarjeta = round(tarj_debito + tarj_credito, 2)
    propinas_tarj = round(sum(c.propina_tarjeta or 0.0 for c in cuentas_pagadas), 2)

    efectivo_final = round(turno.fondo_inicial + ef_ventas + turno.depositos_efectivo - turno.retiros_efectivo - propinas_tarj, 2)
    saldo_final = round(efectivo_final + total_tarjeta + transferencia + vales_emp, 2)
    perm_cx = ConfigPermisosPOS.query.first()
    ver_esperado = bool(current_user.role in ROLES_AUTH or (perm_cx and perm_cx.cajero_ver_esperado_z))

    # Desglose de ventas y propinas con tarjeta por mesero
    por_mesero = {}
    for c in cuentas_pagadas:
        m = (c.mesero or 'SIN MESERO').upper()
        por_mesero.setdefault(m, {'venta': 0.0, 'propina_tarjeta': 0.0, 'cuentas': 0})
        por_mesero[m]['venta'] = round(por_mesero[m]['venta'] + c.total, 2)
        por_mesero[m]['propina_tarjeta'] = round(por_mesero[m]['propina_tarjeta'] + (c.propina_tarjeta or 0.0), 2)
        por_mesero[m]['cuentas'] += 1

    return jsonify({
        'sucursal': suc,
        'apertura': turno.apertura.strftime('%d/%m/%Y %I:%M:%S %p'),
        'ahora': ahora_local().strftime('%d/%m/%Y %I:%M:%S %p'),
        'fondo_inicial': f"{turno.fondo_inicial:.2f}",
        'efectivo': f"{ef_ventas:.2f}",
        'tarjeta': f"{total_tarjeta:.2f}",
        'tarj_debito': f"{tarj_debito:.2f}",
        'tarj_credito': f"{tarj_credito:.2f}",
        'transferencia': f"{transferencia:.2f}",
        'vales_empleado': f"{vales_emp:.2f}",
        'depositos': f"{turno.depositos_efectivo:.2f}",
        'retiros': f"{turno.retiros_efectivo:.2f}",
        'cuentas_abiertas': int(cuentas_abiertas),
        'tope_salvaguarda': float(_cargar_cfg_caja().get('tope_salvaguarda_efectivo') or 5000.0),
        'excede_salvaguarda': bool(efectivo_final >= float(_cargar_cfg_caja().get('tope_salvaguarda_efectivo') or 5000.0)),
        'propinas_pagadas': f"{propinas_tarj:.2f}",
        'saldo_final': f"{saldo_final:.2f}",
        'efectivo_final': f"{efectivo_final:.2f}",
        'total_formas': f"{(ef_ventas + total_tarjeta + transferencia + vales_emp):.2f}",
        'ver_esperado': ver_esperado,
        'por_mesero': [{'mesero': k, **v} for k, v in sorted(por_mesero.items())]
    })


@pos_bp.route('/api/pos/cerrar_turno_arqueo', methods=['POST'])
@login_required
def api_pos_cerrar_turno_arqueo():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False, 'msg': 'Solo Caja o Admin pueden cerrar turno.'}), 403
    data = request.json or {}
    suc = obtener_sucursal_activa(session)
    turno = obtener_turno_activo(suc)
    cfg_cj = _cargar_cfg_caja()
    abiertas_act = CuentaPOS.query.filter_by(sucursal=suc, estado='ABIERTA').count()
    if abiertas_act > 0 and cfg_cj.get('bloquear_cierre_cuentas_abiertas', True):
        aut_ab = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=False)
        if not aut_ab:
            return jsonify({
                'ok': False,
                'requiere_admin': True,
                'msg': f'Hay {abiertas_act} cuenta(s) abierta(s). Ciérralas o ingresa clave de Admin/Gerente para forzar el cierre de turno.'
            }), 403
    cuentas_pagadas = CuentaPOS.query.filter_by(sucursal=suc, turno_id=turno.id, estado='PAGADA').all()

    ef_esp = sum(max(0.0, (c.pago_efectivo or 0.0) - (c.cambio or 0.0)) for c in cuentas_pagadas)
    td_esp = sum(c.pago_tarjeta_debito or 0.0 for c in cuentas_pagadas)
    tc_esp = sum(c.pago_tarjeta_credito or 0.0 for c in cuentas_pagadas)
    tr_esp = sum(c.pago_transferencia or 0.0 for c in cuentas_pagadas)
    val_esp = sum(c.pago_otros or 0.0 for c in cuentas_pagadas)
    prop_esp = sum(c.propina_tarjeta or 0.0 for c in cuentas_pagadas)
    efectivo_esperado = round(turno.fondo_inicial + ef_esp + turno.depositos_efectivo - turno.retiros_efectivo - prop_esp, 2)
    esperado_total = round(efectivo_esperado + td_esp + tc_esp + tr_esp + val_esp, 2)

    ef_dec = _num(data.get('EF', 0))
    td_dec = _num(data.get('TARJD', 0))
    tc_dec = _num(data.get('TARJC', 0))
    tr_dec = _num(data.get('TRANS', 0))
    val_dec = _num(data.get('VAL', 0))
    declarado_total = round(ef_dec + td_dec + tc_dec + tr_dec + val_dec, 2)
    diferencia = round(declarado_total - esperado_total, 2)

    db.session.add(ArqueoTurnoPOS(
        sucursal=suc, turno_id=turno.id, cajero=current_user.username.upper(), fecha=ahora_local(),
        ef_declarado=ef_dec, td_declarado=td_dec, tc_declarado=tc_dec, trans_declarado=tr_dec,
        val_declarado=val_dec, esperado_total=esperado_total,
        declarado_total=declarado_total, diferencia=diferencia
    ))

    turno.cierre = ahora_local()
    turno.estado = 'CERRADO'
    nuevo_turno = TurnoPOS(sucursal=suc, cajero=current_user.username.upper(), fondo_inicial=0.0, estado='ABIERTO', apertura=ahora_local())
    db.session.add(nuevo_turno)
    db.session.flush()
    for ca in CuentaPOS.query.filter_by(sucursal=suc, estado='ABIERTA').all():
        ca.turno_id = nuevo_turno.id

    # Limpieza automática de cola de impresión vieja (>7 días) para mantener BD rápida por años
    limite_limpieza = ahora_local() - timedelta(days=7)
    ColaImpresionPOS.query.filter(ColaImpresionPOS.impreso == True, ColaImpresionPOS.fecha < limite_limpieza).delete(synchronize_session=False)
    db.session.commit()
    registrar_bitacora('CIERRE_CAJA', f'TURNO #{turno.id}', declarado_total, f'Esperado: ${esperado_total:.2f} | Dif: ${diferencia:.2f}', sucursal=suc)
    return jsonify({'ok': True, 'sucursal': suc, 'esperado': f"{esperado_total:.2f}", 'declarado': f"{declarado_total:.2f}", 'diferencia': f"{diferencia:.2f}"})


# ==============================================================================
# PIN INTELIGENTE, IMPRESIÓN, REABRIR, REIMPRIMIR, MI VENTA, CATÁLOGOS Y PROMOS
# ==============================================================================
@pos_bp.route('/api/pos/pin_inteligente/<int:cuenta_id>', methods=['POST'])
@login_required
def api_pos_pin_inteligente(cuenta_id):
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    c = CuentaPOS.query.get_or_404(cuenta_id)
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    c.impresa = True
    ref_folio = f"CTA-{c.id}-{c.orden}"

    pin_existente = PinCaja.query.filter_by(folio_sr=ref_folio, activo=True).first()
    if pin_existente:
        db.session.commit()
        return jsonify({'ok': True, 'codigo': pin_existente.codigo, 'reimpreso': True, 'folio_sr': ref_folio, 'hora': pin_existente.fecha_creacion.strftime('%d/%m/%Y %H:%M')})

    nuevo_pin = PinCaja(
        codigo=generar_pin_unico(), activo=True,
        creado_por=current_user.username, folio_sr=ref_folio, fecha_creacion=ahora_local()
    )
    db.session.add(nuevo_pin)
    db.session.commit()
    return jsonify({'ok': True, 'codigo': nuevo_pin.codigo, 'reimpreso': False, 'folio_sr': ref_folio, 'hora': nuevo_pin.fecha_creacion.strftime('%d/%m/%Y %H:%M')})


@pos_bp.route('/api/pos/cola_impresion')
@login_required
def api_pos_cola_impresion():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'tickets': []})
    suc = obtener_sucursal_activa(session)
    pendientes = ColaImpresionPOS.query.filter_by(sucursal=suc, impreso=False).order_by(ColaImpresionPOS.id.asc()).all()
    textos = [p.contenido_html for p in pendientes]
    for p in pendientes:
        p.impreso = True
    if pendientes:
        db.session.commit()
    return jsonify({'tickets': textos})


@pos_bp.route('/api/pos/solicitar_cuenta/<int:cuenta_id>', methods=['POST'])
@login_required
def api_pos_solicitar_cuenta(cuenta_id):
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    c = CuentaPOS.query.get_or_404(cuenta_id)
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    al = AlertaMesaPOS.query.filter_by(cuenta_id=c.id).first()
    if not al:
        db.session.add(AlertaMesaPOS(cuenta_id=c.id, solicito_cuenta=True, fecha_alerta=ahora_local()))
    else:
        al.solicito_cuenta = True
        al.fecha_alerta = ahora_local()
    db.session.commit()
    return jsonify({'ok': True, 'mesa': c.mesa})


@pos_bp.route('/api/pos/guardar_obs', methods=['POST'])
@login_required
def api_pos_guardar_obs():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    c.observaciones = str(data.get('observaciones', '')).strip()
    db.session.commit()
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/cambiar_mesero', methods=['POST'])
@login_required
def api_pos_cambiar_mesero():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    nuevo_mesero = str(data.get('nuevo_mesero', '')).strip().upper()
    if not nuevo_mesero:
        return jsonify({'ok': False, 'msg': 'Selecciona un mesero.'}), 400
    ant = c.mesero
    c.mesero = nuevo_mesero
    db.session.commit()
    registrar_bitacora('CAMBIAR_MESERO', c.mesa, c.total, f'{ant} -> {nuevo_mesero}', sucursal=c.sucursal)
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/reabrir_cuenta', methods=['POST'])
@login_required
def api_pos_reabrir_cuenta():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=False)
    if not autorizo:
        return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Requiere contraseña de Admin o Gerente.'}), 403
    c.impresa = False
    al = AlertaMesaPOS.query.filter_by(cuenta_id=c.id).first()
    if al:
        al.solicito_cuenta = False
    db.session.commit()
    registrar_bitacora('REABRIR_CUENTA', c.mesa, c.total, 'Cuenta impresa reabierta', autorizo=autorizo, sucursal=c.sucursal)
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/reimprimir_productos', methods=['POST'])
@login_required
def api_pos_reimprimir_productos():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if not _cuenta_permitida(c):
        return jsonify({'ok': False, 'msg': 'Cuenta de otra sucursal.'}), 403
    item_ids = [int(x) for x in data.get('item_ids', [])]
    if not item_ids:
        return jsonify({'ok': False, 'msg': 'Selecciona al menos un producto.'}), 400
    perm = ConfigPermisosPOS.query.first()
    permitir = bool(perm and perm.cajero_puede_reimprimir)
    autorizo = _autorizar_operacion(data.get('clave_admin', ''), permitir_si_flag=permitir)
    if not autorizo:
        return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Requiere contraseña de autorización.'}), 403

    items = [d for d in c.detalles if d.id in item_ids]
    ahora_str = ahora_local().strftime('%d/%m/%Y %I:%M:%S %p')
    filas_html = "".join([
        f"<tr><td style='width:20%;font-weight:bold;'>{'' if it.es_modificador else int(it.cantidad)}</td>"
        f"<td style='width:80%;font-weight:bold;'>{_esc(it.descripcion)}</td></tr>"
        for it in items
    ])
    html_t = f"""
    <div class='ticket-termico'>
        <div style='font-size:17px;font-weight:900;text-align:center;'>*** REIMPRESIÓN COMANDA ***</div>
        <div style='text-align:center;font-size:12px;'>MESA: <b>{c.mesa}</b> | ORDEN: <b>{c.orden}</b></div>
        <div style='text-align:center;font-size:11px;'>MESERO: {c.mesero} | {ahora_str}</div>
        <div style='border-top:2px dashed #000;margin:6px 0;'></div>
        <table style='width:100%;font-size:15px;'>{filas_html}</table>
        <div style='border-top:2px dashed #000;margin:8px 0;'></div>
    </div>"""
    db.session.add(ColaImpresionPOS(sucursal=c.sucursal, tipo='REIMPRESION', contenido_html=html_t, fecha=ahora_local()))
    db.session.commit()
    registrar_bitacora('REIMPRIMIR_PROD', c.mesa, 0.0, f'Reimpresos {len(items)} prod.', autorizo=autorizo, sucursal=c.sucursal)
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/mi_venta')
@login_required
def api_pos_mi_venta():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    suc = obtener_sucursal_activa(session)
    turno = obtener_turno_activo(suc)
    todas = CuentaPOS.query.filter_by(sucursal=suc, turno_id=turno.id).order_by(CuentaPOS.id.desc()).all()
    abiertas, por_pagar, pagadas = [], [], []
    for c in todas:
        if c.estado in ('CANCELADA', 'DIVIDIDA', 'COMBINADA'):
            continue
        obj = {
            'id': c.id, 'mesa': c.mesa, 'area': c.area, 'orden': c.orden,
            'folio': c.folio or '0', 'mesero': c.mesero,
            'total': f"{c.total:.2f}", 'total_num': c.total,
            'cierre': c.cierre.strftime('%d/%m %H:%M') if c.cierre else ''
        }
        if c.estado == 'PAGADA':
            pagadas.append(obj)
        elif c.impresa:
            por_pagar.append(obj)
        else:
            abiertas.append(obj)
    meseros = [u.username.upper() for u in User.query.filter(User.role.in_(['mesero', 'cajero', 'gerente', 'admin'])).all()]
    return jsonify({
        'ok': True, 'sucursal': suc,
        'abiertas': abiertas, 'por_pagar': por_pagar, 'pagadas': pagadas,
        'total_abiertas': f"{sum(x['total_num'] for x in abiertas):.2f}",
        'total_por_pagar': f"{sum(x['total_num'] for x in por_pagar):.2f}",
        'total_pagadas': f"{sum(x['total_num'] for x in pagadas):.2f}",
        'gran_total': f"{sum(x['total_num'] for x in abiertas + por_pagar + pagadas):.2f}",
        'meseros': meseros
    })


@pos_bp.route('/api/pos/confirmar_preorden_1clic/<int:preorden_id>', methods=['POST'])
@login_required
def api_confirmar_preorden_1clic(preorden_id):
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False}), 403
    orden = PreOrden.query.filter_by(id=preorden_id).with_for_update().first_or_404()
    if orden.estado == 'atendido':
        return jsonify({'ok': True, 'msg': 'Ya había sido enviada'})
    if orden.estado != 'pendiente':
        return jsonify({'ok': False, 'msg': 'Esta pre-orden fue cancelada o ya no está pendiente.'}), 400

    data = request.get_json(silent=True) or {}
    suc = obtener_sucursal_activa(session)
    mesero_asignado = (data.get('mesero') or current_user.username).strip().upper()
    orden.estado = 'atendido'
    orden.atendido_por = mesero_asignado

    mesa_raw = orden.mesa.strip().upper()
    mesa_pos = f"T{int(mesa_raw):02d}" if mesa_raw.isdigit() else mesa_raw
    turno = obtener_turno_activo(suc)
    cuenta = CuentaPOS.query.filter_by(sucursal=suc, mesa=mesa_pos, estado='ABIERTA').first()
    if not cuenta:
        num_orden = CuentaPOS.query.filter(CuentaPOS.sucursal == suc, CuentaPOS.apertura >= inicio_hoy_local()).count() + 1
        cuenta = CuentaPOS(
            turno_id=turno.id, sucursal=suc, orden=f"A{num_orden}",
            area='02 TERRAZA' if mesa_pos.startswith('T') else '01 COMEDOR',
            mesa=mesa_pos, mesero=mesero_asignado, personas=2,
            observaciones=orden.notas, apertura=ahora_local(), estado='ABIERTA'
        )
        db.session.add(cuenta)
        db.session.flush()
    elif orden.notas:
        cuenta.observaciones = f"{cuenta.observaciones or ''} | {orden.notas}".strip(' |')

    por_area = {'BARRA': [], 'COCINA': []}
    for linea in orden.detalle_items.split('\n'):
        linea = linea.strip()
        if not linea:
            continue
        m = re.search(r'(\d+)x\s+(.+?)\s+\(\$([\d\.]+)\)', linea)
        if m:
            cant, nom_prod, importe_tot = float(m.group(1)), m.group(2).strip(), float(m.group(3))
            precio_u = round(importe_tot / cant, 2) if cant > 0 else importe_tot
        else:
            cant, nom_prod, precio_u, importe_tot = 1.0, linea.replace('•', '').strip(), 0.0, 0.0

        prod_bd = Producto.query.filter(db.func.lower(Producto.nombre) == nom_prod.lower()).first()
        if cant <= 0 or cant > 99:
            continue
        if prod_bd:
            # El texto de la pre-orden lo escribe el cliente: el precio real sale siempre del catálogo.
            precio_u = round(float(prod_bd.precio or 0), 2)
            importe_tot = round(precio_u * cant, 2)
        area_imp = detectar_area_impresion(prod_bd.categoria if prod_bd else 'Barra')
        det = DetallePOS(
            cuenta_id=cuenta.id, num_comanda=1, cantidad=cant,
            clave=f"0{prod_bd.id}" if prod_bd else "PRE",
            descripcion=nom_prod.upper(), area_impresion=area_imp,
            es_modificador=False, precio_unitario=precio_u, importe=importe_tot, impreso_comanda=True
        )
        db.session.add(det)
        por_area[area_imp].append(det)

    if orden.notas:
        mod_nota = DetallePOS(
            cuenta_id=cuenta.id, num_comanda=1, cantidad=1.0, clave='NOTA',
            descripcion=f">{orden.notas.upper()}", area_impresion='COCINA',
            es_modificador=True, precio_unitario=0.0, importe=0.0, impreso_comanda=True
        )
        db.session.add(mod_nota)
        por_area['BARRA'].append(mod_nota)
        por_area['COCINA'].append(mod_nota)

    db.session.flush()
    recalcular_totales_cuenta(cuenta)

    ahora_str = ahora_local().strftime('%d/%m/%Y %I:%M:%S %p')
    for area_nom, lista in por_area.items():
        if not [x for x in lista if not x.es_modificador]:
            continue
        filas_html = "".join([
            f"<tr><td style='width:20%;font-weight:bold;'>{'' if it.es_modificador else int(it.cantidad)}</td>"
            f"<td style='width:80%;font-weight:bold;'>{_esc(it.descripcion)}</td></tr>" for it in lista
        ])
        html_t = f"""
        <div class='ticket-termico'>
            <div style='font-size:17px;font-weight:900;text-align:center;'>*** PRE-ORDEN {area_nom} ***</div>
            <div style='text-align:center;font-size:12px;'>MESA: <b>{_esc(cuenta.mesa)}</b> | CLIENTE: <b>{_esc(orden.cliente_nombre.upper())}</b></div>
            <div style='text-align:center;font-size:11px;'>CONFIRMÓ: {_esc(mesero_asignado)} | {ahora_str}</div>
            <div style='border-top:2px dashed #000;margin:6px 0;'></div>
            <table style='width:100%;font-size:15px;'>{filas_html}</table>
            <div style='border-top:2px dashed #000;margin:8px 0;'></div>
        </div>"""
        db.session.add(ColaImpresionPOS(sucursal=suc, tipo=f"COMANDA_{area_nom}", contenido_html=html_t, fecha=ahora_local()))

    db.session.commit()
    return jsonify({'ok': True, 'mesa': cuenta.mesa, 'cuenta_id': cuenta.id})


@pos_bp.route('/api/pos/modificadores', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_pos_modificadores():
    if request.method == 'GET':
        mods = ModificadorPOS.query.filter_by(activo=True).order_by(ModificadorPOS.id.asc()).all()
        return jsonify({
            'ok': True,
            'modificadores': [
                {'id': m.id, 'clave': m.clave, 'grupo': m.grupo or 'SABORES', 'nombre': m.nombre, 'precio': m.precio, 'area_impresion': m.area_impresion or ''}
                for m in mods
            ],
            'flujos': _mapa_flujos_modificadores()
        })
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Raquel (Admin) puede modificar catálogos.'}), 403
    data = request.json or {}
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip().upper().lstrip('>')
        if not nom:
            return jsonify({'ok': False, 'msg': 'Nombre requerido'}), 400
        area_m = str(data.get('area_impresion', '')).strip().upper()
        db.session.add(ModificadorPOS(
            clave=str(data.get('clave', f"030{ModificadorPOS.query.count() + 20}")).strip(),
            grupo=str(data.get('grupo', 'SABORES')).strip().upper(),
            nombre=nom, precio=_num(data.get('precio', 0), maximo=100000.0),
            area_impresion=area_m if area_m in ('BARRA', 'COCINA') else None,
            activo=True
        ))
        db.session.commit()
        return jsonify({'ok': True})
    m = ModificadorPOS.query.get_or_404(int(data['id']))
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/promociones', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def api_pos_promociones():
    if request.method == 'GET':
        promos = PromocionPOS.query.order_by(PromocionPOS.id.desc()).all()
        return jsonify({'ok': True, 'promociones': [{
            'id': p.id, 'nombre': p.nombre, 'tipo': p.tipo, 'valor': p.valor,
            'por_cada': p.por_cada, 'regala': p.regala, 'aplica_a': p.aplica_a,
            'objetivo': p.objetivo, 'dias': p.dias,
            'hora_inicio': p.hora_inicio, 'hora_fin': p.hora_fin, 'activa': p.activa
        } for p in promos]})
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Raquel (Admin) puede gestionar promociones.'}), 403
    data = request.json or {}
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip().upper()
        obj = str(data.get('objetivo', '')).strip().upper()
        if not nom or not obj:
            return jsonify({'ok': False, 'msg': 'Nombre y objetivo requeridos'}), 400
        db.session.add(PromocionPOS(
            nombre=nom, tipo=str(data.get('tipo', 'DESCUENTO_PCT')).upper(),
            valor=_num(data.get('valor', 0), maximo=100000.0), por_cada=int(data.get('por_cada', 2)),
            regala=int(data.get('regala', 1)), aplica_a=str(data.get('aplica_a', 'CATEGORIA')).upper(),
            objetivo=obj, dias=str(data.get('dias', '0,1,2,3,4,5,6')),
            hora_inicio=str(data.get('hora_inicio', '00:00'))[:5],
            hora_fin=str(data.get('hora_fin', '23:59'))[:5], activa=True
        ))
        db.session.commit()
        return jsonify({'ok': True})
    if request.method == 'PUT':
        p = PromocionPOS.query.get_or_404(int(data['id']))
        p.activa = not p.activa
        db.session.commit()
        return jsonify({'ok': True, 'activa': p.activa})
    p = PromocionPOS.query.get_or_404(int(data['id']))
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})



@pos_bp.route('/api/pos/modificadores_asignacion', methods=['POST'])
@login_required
def api_pos_modificadores_asignacion():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Administrador puede asignar modificadores.'}), 403
    data = request.json or {}
    mod_id = int(data.get('mod_id', 0))
    if not mod_id:
        return jsonify({'ok': False, 'msg': 'Modificador inválido.'}), 400
    ModificadorPOS.query.get_or_404(mod_id)
    prod_ids = [int(x) for x in (data.get('producto_ids') or []) if str(x).isdigit()]
    cats = [str(x).strip().upper() for x in (data.get('categorias') or []) if str(x).strip()]
    asigs = _cargar_asignaciones_mods()
    asigs[str(mod_id)] = {'producto_ids': prod_ids, 'categorias': cats}
    _guardar_asignaciones_mods(asigs)
    return jsonify({'ok': True, 'mod_id': mod_id, 'producto_ids': prod_ids, 'categorias': cats})



@pos_bp.route('/api/pos/producto_compuesto', methods=['POST'])
@login_required
def api_pos_producto_compuesto():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Administrador puede configurar productos compuestos.'}), 403
    data = request.json or {}
    prod_id = int(data.get('producto_id', 0))
    if not prod_id:
        return jsonify({'ok': False, 'msg': 'Producto inválido.'}), 400
    Producto.query.get_or_404(prod_id)
    mod_ids_sel = set(int(x) for x in (data.get('mod_ids') or []) if str(x).isdigit())
    asigs = _cargar_asignaciones_mods()
    todos_mods = ModificadorPOS.query.filter_by(activo=True).all()
    for m in todos_mods:
        k = str(m.id)
        reg = asigs.get(k) or {'producto_ids': [], 'categorias': []}
        pids = [int(x) for x in (reg.get('producto_ids') or []) if int(x) != prod_id]
        if m.id in mod_ids_sel:
            pids.append(prod_id)
        reg['producto_ids'] = pids
        reg['categorias'] = [str(x).upper() for x in (reg.get('categorias') or [])]
        if reg['producto_ids'] or reg['categorias']:
            asigs[k] = reg
        elif k in asigs:
            del asigs[k]
    _guardar_asignaciones_mods(asigs)
    return jsonify({'ok': True, 'producto_id': prod_id, 'total_mods': len(mod_ids_sel)})



@pos_bp.route('/api/pos/motivos_cancelacion', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_pos_motivos_cancelacion():
    if request.method == 'GET':
        return jsonify({'ok': True, 'motivos': _cargar_json_lista(_MOTIVOS_FILE, _MOTIVOS_DEFAULT)})
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Administración.'}), 403
    items = _cargar_json_lista(_MOTIVOS_FILE, _MOTIVOS_DEFAULT)
    data = request.json or {}
    if request.method == 'DELETE':
        mid = int(data.get('id', 0))
        items = [x for x in items if int(x.get('id', 0)) != mid]
        _guardar_json_lista(_MOTIVOS_FILE, items)
        return jsonify({'ok': True})
    desc = str(data.get('descripcion', '')).strip().upper()
    if not desc:
        return jsonify({'ok': False, 'msg': 'Escribe la descripción del motivo.'}), 400
    clv = str(data.get('clave', '')).strip().upper() or f"M{len(items)+1:02d}"
    nxt_id = max([int(x.get('id', 0)) for x in items] + [0]) + 1
    items.append({'id': nxt_id, 'clave': clv, 'descripcion': desc})
    _guardar_json_lista(_MOTIVOS_FILE, items)
    return jsonify({'ok': True, 'id': nxt_id})


@pos_bp.route('/api/pos/tipos_descuento', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_pos_tipos_descuento():
    if request.method == 'GET':
        return jsonify({'ok': True, 'tipos_descuento': _cargar_json_lista(_TIPOS_DESC_FILE, _TIPOS_DESC_DEFAULT)})
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Administración.'}), 403
    items = _cargar_json_lista(_TIPOS_DESC_FILE, _TIPOS_DESC_DEFAULT)
    data = request.json or {}
    if request.method == 'DELETE':
        did = int(data.get('id', 0))
        items = [x for x in items if int(x.get('id', 0)) != did]
        _guardar_json_lista(_TIPOS_DESC_FILE, items)
        return jsonify({'ok': True})
    desc = str(data.get('descripcion', '')).strip().upper()
    pct = _num(data.get('porcentaje', 0), minimo=-1_000_000.0, maximo=1_000_000.0)
    if not desc:
        return jsonify({'ok': False, 'msg': 'Escribe la descripción del descuento.'}), 400
    if pct < 0 or pct > 100:
        return jsonify({'ok': False, 'msg': 'El porcentaje debe estar entre 0 y 100.'}), 400
    clv = str(data.get('clave', '')).strip().upper() or f"D{len(items)+1:02d}"
    nxt_id = max([int(x.get('id', 0)) for x in items] + [0]) + 1
    items.append({'id': nxt_id, 'clave': clv, 'descripcion': desc, 'porcentaje': round(pct, 2)})
    _guardar_json_lista(_TIPOS_DESC_FILE, items)
    return jsonify({'ok': True, 'id': nxt_id})


@pos_bp.route('/api/pos/suspender_producto', methods=['POST'])
@login_required
def api_pos_suspender_producto():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    pid = data.get('producto_id')
    if not pid:
        return jsonify({'ok': False, 'msg': 'Falta producto_id.'}), 400
    p = Producto.query.get_or_404(int(pid))
    nuevo_estado = not bool(p.agotado) if 'agotado' not in data else bool(data.get('agotado'))
    p.agotado = nuevo_estado
    db.session.commit()
    invalidar_cache_publico()
    suc = obtener_sucursal_activa(session)
    accion = 'SUSPENDER_PROD' if p.agotado else 'REACTIVAR_PROD'
    detalle = f"{'Suspendido/Agotado' if p.agotado else 'Reactivado'}: {p.nombre}"
    registrar_bitacora(accion, str(p.id), p.precio or 0.0, detalle, sucursal=suc)
    return jsonify({'ok': True, 'producto_id': p.id, 'agotado': bool(p.agotado), 'nombre': p.nombre})


@pos_bp.route('/api/pos/alertas_stock', methods=['GET'])
@login_required
def api_pos_alertas_stock():
    if current_user.role not in ROLES_POS and current_user.role != 'almacen':
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    suc = obtener_sucursal_activa(session)
    insumos = InsumoBodegaPro.query.order_by(InsumoBodegaPro.nombre.asc()).all()
    stocks = {s.insumo_id: s for s in StockSucursal.query.filter_by(sucursal=suc).all()}
    bajos = []
    for ins in insumos:
        st = stocks.get(ins.id)
        actual = float(st.stock_actual if st is not None else (ins.stock_actual or 0.0))
        minimo = float(st.stock_minimo if st is not None else (ins.stock_minimo or 2.0))
        if actual <= minimo:
            bajos.append({
                'id': ins.id,
                'nombre': ins.nombre,
                'categoria': ins.categoria,
                'unidad': ins.unidad,
                'stock_actual': round(actual, 3),
                'stock_minimo': round(minimo, 3),
                'critico': actual <= 0.0
            })
    return jsonify({'ok': True, 'sucursal': suc, 'total_bajos': len(bajos), 'insumos': bajos})


@pos_bp.route('/api/pos/registrar_merma', methods=['POST'])
@login_required
def api_pos_registrar_merma():
    if current_user.role not in ROLES_POS and current_user.role != 'almacen':
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    nombre = str(data.get('insumo_nombre', '')).strip().upper()
    cantidad = _num(data.get('cantidad', 0), maximo=100000.0)
    motivo = str(data.get('motivo', '')).strip().upper()
    if not nombre or cantidad <= 0 or not motivo:
        return jsonify({'ok': False, 'msg': 'Indica insumo, cantidad mayor a 0 y motivo.'}), 400
    suc = obtener_sucursal_activa(session)
    unidad = str(data.get('unidad', 'PZA')).strip().upper() or 'PZA'
    costo_u = _num(data.get('costo_unitario', 0), maximo=1_000_000.0)
    costo_tot = aplicar_merma(nombre, cantidad, motivo, suc, current_user.username.upper(), unidad=unidad, costo_unitario=costo_u)
    db.session.commit()
    registrar_bitacora('MERMA_INSUMO', nombre, costo_tot, f'{cantidad} {unidad} - {motivo}', sucursal=suc)
    return jsonify({'ok': True, 'costo_total': costo_tot})


@pos_bp.route('/api/pos/historial_arqueos', methods=['GET'])
@login_required
def api_pos_historial_arqueos():
    if current_user.role not in ROLES_CAJA and current_user.role not in ROLES_AUTH:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    suc = obtener_sucursal_activa(session)
    rows = ArqueoTurnoPOS.query.filter_by(sucursal=suc).order_by(ArqueoTurnoPOS.id.desc()).limit(25).all()
    items = [{
        'id': r.id,
        'turno_id': r.turno_id,
        'cajero': r.cajero,
        'fecha': r.fecha.strftime('%d/%m/%Y %I:%M %p') if r.fecha else '',
        'esperado_total': round(float(r.esperado_total or 0.0), 2),
        'declarado_total': round(float(r.declarado_total or 0.0), 2),
        'diferencia': round(float(r.diferencia or 0.0), 2)
    } for r in rows]
    return jsonify({'ok': True, 'sucursal': suc, 'arqueos': items})


@pos_bp.route('/api/pos/resumen_operativo', methods=['GET'])
@login_required
def api_pos_resumen_operativo():
    if current_user.role not in ROLES_POS:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    suc = obtener_sucursal_activa(session)
    turno = obtener_turno_activo(suc)
    pagadas = CuentaPOS.query.filter_by(sucursal=suc, turno_id=turno.id, estado='PAGADA').all()
    venta_total = round(sum(float(c.total or 0.0) for c in pagadas), 2)
    prop_tarj = round(sum(float(c.propina_tarjeta or 0.0) for c in pagadas), 2)
    mermas = RegistroMerma.query.filter_by(sucursal=suc).order_by(RegistroMerma.id.desc()).limit(20).all()
    merma_total = round(sum(float(m.costo_total or 0.0) for m in mermas), 2)
    return jsonify({
        'ok': True,
        'sucursal': suc,
        'turno_id': turno.id,
        'cuentas_pagadas': len(pagadas),
        'venta_total': venta_total,
        'propina_tarjeta': prop_tarj,
        'merma_reciente_costo': merma_total,
        'mermas': [{
            'id': m.id,
            'fecha': m.fecha.strftime('%d/%m/%Y %H:%M') if m.fecha else '',
            'insumo': m.insumo_nombre,
            'cantidad': float(m.cantidad or 0.0),
            'unidad': m.unidad,
            'costo_total': round(float(m.costo_total or 0.0), 2),
            'motivo': m.motivo
        } for m in mermas]
    })


@pos_bp.route('/api/pos/respaldo_config', methods=['POST'])
@login_required
def api_pos_respaldo_config():
    if current_user.role not in ROLES_AUTH:
        return jsonify({'ok': False, 'msg': 'Solo Admin o Gerente pueden generar respaldos.'}), 403
    stamp = ahora_local().strftime('%Y%m%d_%H%M%S')
    archivos_cfg = {
        "config_mods_productos.json": _ASIG_MOD_FILE,
        "config_areas_productos.json": _AREA_PROD_FILE,
        "config_motivos_cancelacion.json": _MOTIVOS_FILE,
        "config_tipos_descuento.json": _TIPOS_DESC_FILE,
        "config_caja_soft.json": _CAJA_CFG_FILE,
    }
    snapshot = {}
    for nombre_cfg, ruta in archivos_cfg.items():
        if ruta.exists():
            try:
                snapshot[nombre_cfg] = _json_asig.loads(ruta.read_text(encoding="utf-8"))
            except Exception:
                snapshot[nombre_cfg] = ruta.read_text(encoding="utf-8", errors="ignore")
    nombre_archivo = f"respaldo_pos_{stamp}.json"
    suc = obtener_sucursal_activa(session)
    registrar_bitacora('RESPALDO_POS', nombre_archivo, 0.0, f'{len(snapshot)} archivos respaldados', sucursal=suc)
    contenido = _json_asig.dumps(snapshot, indent=2, ensure_ascii=False)
    return Response(contenido, mimetype='application/json',
                    headers={'Content-Disposition': f'attachment; filename="{nombre_archivo}"'})


@pos_bp.route('/api/pos/catalogo_completo')
@login_required
def api_pos_catalogo_completo():
    cats = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    prods = Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all()
    mods = ModificadorPOS.query.filter_by(activo=True).order_by(ModificadorPOS.id.asc()).all()
    promos = PromocionPOS.query.order_by(PromocionPOS.id.desc()).all()
    perm = ConfigPermisosPOS.query.first()
    return jsonify({
        'ok': True,
        'categorias': [{'id': c.id, 'nombre': c.nombre, 'nombre_en': c.nombre_en or ''} for c in cats],
        'productos': [{'id': p.id, 'nombre': p.nombre, 'precio': p.precio, 'categoria': p.categoria, 'agotado': p.agotado, 'destacado': p.destacado, 'area_impresion': _cargar_areas_prods().get(str(p.id), '')} for p in prods],
        'modificadores': _enriquecer_modificadores(mods),
        'flujos': _mapa_flujos_modificadores(),
        'promociones': [{'id': pr.id, 'nombre': pr.nombre, 'tipo': pr.tipo, 'valor': pr.valor, 'por_cada': pr.por_cada, 'regala': pr.regala, 'aplica_a': pr.aplica_a, 'objetivo': pr.objetivo, 'dias': pr.dias, 'hora_inicio': pr.hora_inicio, 'hora_fin': pr.hora_fin, 'activa': pr.activa} for pr in promos],
        'permisos': {
            'cancelar': bool(perm.cajero_puede_cancelar) if perm else False,
            'descontar': bool(perm.cajero_puede_descontar) if perm else False,
            'cambiar_pago': bool(perm.cajero_puede_cambiar_pago) if perm else False,
            'reimprimir': bool(perm.cajero_puede_reimprimir) if perm else False,
            'retirar': bool(perm.cajero_puede_retirar) if perm else False,
            'ver_esperado_z': bool(perm.cajero_ver_esperado_z) if perm else False
        }
    })


@pos_bp.route('/api/pos/admin_producto', methods=['POST', 'PUT', 'DELETE'])
@login_required
def api_pos_admin_producto():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Raquel (Admin).'}), 403
    data = request.json or {}
    if request.method == 'POST':
        nom, cat = str(data.get('nombre', '')).strip(), str(data.get('categoria', '')).strip()
        if not nom or not cat:
            return jsonify({'ok': False, 'msg': 'Nombre y categoría requeridos'}), 400
        nuevo_p = Producto(
            nombre=nom,
            precio=_num(data.get('precio', 0), maximo=100000.0),
            categoria=cat,
            descripcion=str(data.get('descripcion', '')).strip(),
            agotado=bool(data.get('agotado', False))
        )
        db.session.add(nuevo_p)
        db.session.commit()
        area_p = str(data.get('area_impresion', '')).strip().upper()
        areas = _cargar_areas_prods()
        if area_p in ('COCINA', 'BARRA'):
            areas[str(nuevo_p.id)] = area_p
            _guardar_areas_prods(areas)
        invalidar_cache_publico()
        return jsonify({'ok': True, 'id': nuevo_p.id})
    if request.method == 'PUT':
        p = Producto.query.get_or_404(int(data['id']))
        p.nombre = str(data.get('nombre', p.nombre)).strip()
        p.precio = _num(data.get('precio', p.precio), maximo=100000.0)
        p.categoria = str(data.get('categoria', p.categoria)).strip()
        if 'agotado' in data:
            p.agotado = bool(data.get('agotado'))
        db.session.commit()
        if 'area_impresion' in data:
            area_p = str(data.get('area_impresion', '')).strip().upper()
            areas = _cargar_areas_prods()
            if area_p in ('COCINA', 'BARRA'):
                areas[str(p.id)] = area_p
            else:
                areas.pop(str(p.id), None)
            _guardar_areas_prods(areas)
        invalidar_cache_publico()
        return jsonify({'ok': True, 'id': p.id})
    pid_del = int(data['id'])
    db.session.delete(Producto.query.get_or_404(pid_del))
    db.session.commit()
    areas = _cargar_areas_prods()
    if str(pid_del) in areas:
        areas.pop(str(pid_del), None)
        _guardar_areas_prods(areas)
    invalidar_cache_publico()
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/admin_categoria', methods=['POST', 'DELETE'])
@login_required
def api_pos_admin_categoria():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Raquel (Admin).'}), 403
    data = request.json or {}
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip()
        if nom and not CategoriaMenu.query.filter_by(nombre=nom).first():
            db.session.add(CategoriaMenu(nombre=nom, nombre_en=str(data.get('nombre_en', '')).strip()))
            db.session.commit()
            invalidar_cache_publico()
        return jsonify({'ok': True})
    c = CategoriaMenu.query.get_or_404(int(data['id']))
    if Producto.query.filter_by(categoria=c.nombre).first():
        return jsonify({'ok': False, 'msg': 'No puedes borrar una categoría con platillos.'}), 400
    db.session.delete(c)
    db.session.commit()
    invalidar_cache_publico()
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/permisos_raquel', methods=['GET', 'POST'])
@login_required
def api_permisos_raquel():
    p = ConfigPermisosPOS.query.first()
    if request.method == 'GET':
        return jsonify({
            'ok': True,
            'cancelar': bool(p.cajero_puede_cancelar),
            'descontar': bool(p.cajero_puede_descontar),
            'cambiar_pago': bool(p.cajero_puede_cambiar_pago),
            'reimprimir': bool(p.cajero_puede_reimprimir),
            'retirar': bool(p.cajero_puede_retirar),
            'ver_esperado_z': bool(p.cajero_ver_esperado_z)
        })
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    data = request.json or {}
    p.cajero_puede_cancelar = bool(data.get('cancelar', False))
    p.cajero_puede_descontar = bool(data.get('descontar', False))
    p.cajero_puede_cambiar_pago = bool(data.get('cambiar_pago', False))
    p.cajero_puede_reimprimir = bool(data.get('reimprimir', False))
    p.cajero_puede_retirar = bool(data.get('retirar', False))
    p.cajero_ver_esperado_z = bool(data.get('ver_esperado_z', False))
    db.session.commit()
    return jsonify({'ok': True})


@pos_bp.route('/api/pos/bitacora_auditoria')
@login_required
def api_pos_bitacora_auditoria():
    if current_user.role not in ROLES_CAJA:
        return jsonify({'ok': False}), 403
    q = BitacoraPOS.query
    if current_user.role != 'admin':
        q = q.filter_by(sucursal=obtener_sucursal_activa(session))
    regs = q.order_by(BitacoraPOS.id.desc()).limit(100).all()
    return jsonify({'ok': True, 'registros': [{
        'fecha': r.fecha.strftime('%d/%m %H:%M'), 'sucursal': r.sucursal or '',
        'usuario': r.usuario, 'autorizo': r.autorizo or '-',
        'accion': r.accion, 'mesa': r.mesa or '-',
        'monto': f"{r.monto:.2f}", 'detalle': r.detalle or ''
    } for r in regs]})