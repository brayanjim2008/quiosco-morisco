"""Reparto diario de propinas en partes iguales entre el personal que trabajó ese día en la sucursal.
Las propinas con tarjeta se suman solas de las cuentas cobradas; el efectivo del bote se captura."""
import json
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, session
from flask_login import login_required, current_user

from models import (
    db, ahora_local, registrar_bitacora, obtener_sucursal_activa, SUCURSALES_OFICIALES, autorizo_supervisor,
    CuentaPOS, RegistroAsistencia, EmpleadoNominaPOS, RepartoPropinasPOS,
)

propinas_bp = Blueprint('propinas', __name__)
ROLES_PROPINAS = ('admin', 'gerente', 'cajero', 'sucursal')


def _fecha(txt):
    try:
        return datetime.strptime(str(txt or '')[:10], '%Y-%m-%d').date()
    except ValueError:
        return ahora_local().date()


def _sucursal(pedida):
    if current_user.role == 'admin' and pedida in SUCURSALES_OFICIALES:
        return pedida
    return obtener_sucursal_activa(session)


def _propinas_tarjeta(suc, dia):
    ini = datetime.combine(dia, datetime.min.time())
    cuentas = CuentaPOS.query.filter(CuentaPOS.sucursal == suc, CuentaPOS.estado == 'PAGADA',
                                     CuentaPOS.cierre >= ini, CuentaPOS.cierre < ini + timedelta(days=1)).all()
    return round(sum(c.propina_tarjeta or 0.0 for c in cuentas), 2), len([c for c in cuentas if (c.propina_tarjeta or 0) > 0])


def _quienes_trabajaron(suc, dia):
    ini = datetime.combine(dia, datetime.min.time())
    regs = RegistroAsistencia.query.filter(RegistroAsistencia.sucursal == suc, RegistroAsistencia.tipo == 'ENTRADA',
                                           RegistroAsistencia.fecha >= ini, RegistroAsistencia.fecha < ini + timedelta(days=1)).all()
    nombres = {(r.empleado_nombre or '').strip().upper() for r in regs if r.empleado_nombre}
    # Quien atendió mesas ese día también trabajó aunque no haya checado (sale ya marcado para el reparto).
    meseros = db.session.query(CuentaPOS.mesero).filter(CuentaPOS.sucursal == suc, CuentaPOS.apertura >= ini,
                                                        CuentaPOS.apertura < ini + timedelta(days=1)).distinct().all()
    nombres |= {(m or '').strip().upper() for (m,) in meseros if m and (m or '').strip().upper() not in ('CAJA', 'SIN MESERO', 'PUBLICO')}
    return sorted(n for n in nombres if n)


def _ser(r):
    return {'id': r.id, 'fecha': r.fecha.strftime('%Y-%m-%d'), 'sucursal': r.sucursal, 'tarjeta': r.total_tarjeta,
            'efectivo': r.total_efectivo, 'total': r.total, 'por_persona': r.por_persona,
            'reparto': json.loads(r.reparto_json or '[]'), 'usuario': r.usuario,
            'creado': r.creado.strftime('%d/%m/%Y %H:%M') if r.creado else ''}


@propinas_bp.route('/api/propinas/dia')
@login_required
def api_propinas_dia():
    if current_user.role not in ROLES_PROPINAS:
        return jsonify({'ok': False}), 403
    suc = _sucursal(request.args.get('sucursal'))
    dia = _fecha(request.args.get('fecha'))
    tarjeta, n_cuentas = _propinas_tarjeta(suc, dia)
    previo = RepartoPropinasPOS.query.filter_by(sucursal=suc, fecha=dia).first()
    personal = [e.nombre.upper() for e in EmpleadoNominaPOS.query.filter_by(activo=True, sucursal=suc)
                .order_by(EmpleadoNominaPOS.nombre.asc()).all()]
    historial = RepartoPropinasPOS.query.filter_by(sucursal=suc).order_by(RepartoPropinasPOS.fecha.desc()).limit(10).all()
    return jsonify({'ok': True, 'sucursal': suc, 'fecha': dia.strftime('%Y-%m-%d'),
                    'tarjeta': tarjeta, 'cuentas_con_propina': n_cuentas,
                    'trabajaron': _quienes_trabajaron(suc, dia), 'personal': personal,
                    'reparto_guardado': _ser(previo) if previo else None,
                    'historial': [_ser(h) for h in historial]})


@propinas_bp.route('/api/propinas/repartir', methods=['POST'])
@login_required
def api_propinas_repartir():
    if current_user.role not in ROLES_PROPINAS:
        return jsonify({'ok': False}), 403
    d = request.get_json(silent=True) or {}
    suc = _sucursal(d.get('sucursal'))
    dia = _fecha(d.get('fecha'))
    if dia > ahora_local().date():
        return jsonify({'ok': False, 'msg': 'No se puede repartir un día que no ha pasado.'}), 400
    try:
        efectivo = round(float(d.get('efectivo') or 0), 2)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'msg': 'El efectivo debe ser un número.'}), 400
    if efectivo < 0 or efectivo > 1_000_000:
        return jsonify({'ok': False, 'msg': 'Efectivo inválido.'}), 400
    nombres = []
    for n in d.get('empleados') or []:
        n = str(n or '').strip().upper()[:100]
        if n and n not in nombres:
            nombres.append(n)
    if not nombres:
        return jsonify({'ok': False, 'msg': 'Selecciona a las personas que trabajaron.'}), 400
    previo = RepartoPropinasPOS.query.filter_by(sucursal=suc, fecha=dia).first()
    autorizo = ''
    if previo:
        autorizo = autorizo_supervisor(d.get('clave_admin'))
        if not autorizo:
            return jsonify({'ok': False, 'requiere_admin': True,
                            'msg': 'Las propinas de ese día ya se repartieron. Para rehacerlo se necesita clave de Admin o Gerente.'}), 403
    tarjeta, _ = _propinas_tarjeta(suc, dia)
    total = round(tarjeta + efectivo, 2)
    centavos = int(round(total * 100))
    base, sobra = divmod(centavos, len(nombres))
    # los centavos que no se pueden dividir parejo se le dan a los primeros de la lista
    reparto = [{'nombre': n, 'monto': (base + (1 if i < sobra else 0)) / 100} for i, n in enumerate(nombres)]
    if previo:
        db.session.delete(previo)
        db.session.flush()
    r = RepartoPropinasPOS(fecha=dia, sucursal=suc, total_tarjeta=tarjeta, total_efectivo=efectivo, total=total,
                           por_persona=base / 100, reparto_json=json.dumps(reparto, ensure_ascii=False),
                           usuario=current_user.username.upper(), creado=ahora_local())
    db.session.add(r)
    db.session.commit()
    registrar_bitacora('REPARTO_PROPINAS', dia.strftime('%d/%m/%Y'), total,
                       f'{len(nombres)} personas, ${base / 100:.2f} c/u' + (' (rehecho)' if previo else ''), autorizo=autorizo or '', sucursal=suc)
    return jsonify({'ok': True, 'reparto': _ser(r)})
