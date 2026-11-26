"""Auxiliar de nómina (como el sistema anterior de Caminantes): descuentos, aguinaldos, bonos, permisos,
vacaciones, catálogos de nómina, bajas y aniversarios. Todos los importes se recalculan en el servidor."""
import json
import math
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from models import (
    db, ahora_local, registrar_bitacora, cfg_cargar, cfg_guardar, SUCURSAL_DEFAULT,
    EmpleadoNominaPOS, ConsumoEmpleadoPOS, DescuentoEmpleadoPOS, AguinaldoEmpleadoPOS, BonoEmpleadoPOS,
    PermisoEmpleadoPOS, VacacionEmpleadoPOS,
)

nomina_bp = Blueprint('nomina', __name__)

CLAVE_CATALOGOS = 'catalogos_nomina'
CATALOGOS_DEFAULT = {
    'areas': [
        {'nombre': 'SERVICIO', 'puestos': ['MESERO', 'CAPITAN', 'HOSTESS']},
        {'nombre': 'COCINA', 'puestos': ['COCINERO', 'AYUDANTE DE COCINA', 'LAVALOZA']},
        {'nombre': 'BARRA', 'puestos': ['BARISTA', 'BARTENDER']},
        {'nombre': 'CAJA', 'puestos': ['CAJERO']},
        {'nombre': 'ADMINISTRACION', 'puestos': ['GERENTE', 'ADMINISTRATIVO']},
        {'nombre': 'LIMPIEZA', 'puestos': ['INTENDENCIA']},
    ],
    'turnos': [
        {'nombre': 'MATUTINO', 'entrada': '07:00', 'salida': '15:00'},
        {'nombre': 'VESPERTINO', 'entrada': '15:00', 'salida': '23:00'},
    ],
    'tipos_baja': ['RENUNCIA VOLUNTARIA', 'ABANDONO DE TRABAJO', 'DESPIDO', 'TERMINO DE CONTRATO'],
    'tipos_permiso': [
        {'nombre': 'CON GOCE DE SUELDO', 'con_goce': True},
        {'nombre': 'SIN GOCE DE SUELDO', 'con_goce': False},
        {'nombre': 'INCAPACIDAD IMSS', 'con_goce': False},
    ],
    'prima_vacacional_pct': 40.0,      # el sistema anterior pagaba salario / 2.5 = 40 % (la ley pide mínimo 25 %)
    'max_dias_permiso_con_goce': 6,    # por año, como el sistema anterior
}
MAX_PCT_BONO = 100.0


# ------------------------------------------------------------------------------------------- utilidades
def _num(valor, minimo=0.0, maximo=1_000_000.0):
    try:
        x = float(valor or 0)
    except (TypeError, ValueError):
        raise ValueError('Número inválido')
    if not math.isfinite(x) or x < minimo or x > maximo:
        raise ValueError('Número fuera de rango')
    return round(x, 2)


def _fecha(valor, requerida=True):
    txt = str(valor or '').strip()[:10]
    if not txt:
        if requerida:
            raise ValueError('Falta la fecha')
        return None
    try:
        return datetime.strptime(txt, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('Fecha inválida (usa AAAA-MM-DD)')


def _txt(valor, n=120):
    return str(valor or '').strip().upper()[:n]


def _solo_admin():
    return current_user.role != 'admin'


def catalogos():
    datos = cfg_cargar(CLAVE_CATALOGOS, CATALOGOS_DEFAULT)
    for k, v in CATALOGOS_DEFAULT.items():   # si se agregan llaves nuevas, conservan su valor por defecto
        datos.setdefault(k, json.loads(json.dumps(v)))
    return datos


def sueldo_diario(e):
    d = float(e.sueldo_diario or 0.0)
    if d <= 0:
        d = float(e.sueldo_base or 0.0) / max(1, int(e.dias_base or 6))
    return round(d, 2)


def sueldo_hora(e):
    h = float(e.sueldo_hora or 0.0)
    return round(h if h > 0 else sueldo_diario(e) / 8.0, 2)   # jornada de 8 h, como el sistema anterior


def antiguedad_anios(e, ref=None):
    if not e.fecha_ingreso:
        return 0
    ref = ref or ahora_local().date()
    anios = ref.year - e.fecha_ingreso.year - ((ref.month, ref.day) < (e.fecha_ingreso.month, e.fecha_ingreso.day))
    return max(0, anios)


def dias_vacaciones_ley(anios):
    """Días de vacaciones según la Ley Federal del Trabajo (reforma 2023, 'vacaciones dignas')."""
    if anios < 1:
        return 0
    if anios <= 5:
        return 10 + 2 * anios                 # 1→12, 2→14, 3→16, 4→18, 5→20
    return 22 + 2 * ((anios - 6) // 5)        # 6-10→22, 11-15→24, 16-20→26 ...


def fin_sin_domingos(inicio, dias):
    """Fecha del último día de vacaciones contando solo días que no son domingo (como el sistema anterior)."""
    if dias <= 0:
        return inicio
    d, contados = inicio, 0
    while True:
        if d.weekday() != 6:
            contados += 1
            if contados == dias:
                return d
        d += timedelta(days=1)


def saldo_deuda(emp_id):
    ult = DescuentoEmpleadoPOS.query.filter_by(empleado_id=emp_id).order_by(DescuentoEmpleadoPOS.id.desc()).first()
    return float(ult.saldo or 0.0) if ult else 0.0


def dias_permiso_con_goce_anio(emp_id, anio, excluir_id=None):
    q = PermisoEmpleadoPOS.query.filter(PermisoEmpleadoPOS.empleado_id == emp_id, PermisoEmpleadoPOS.con_goce == True,
                                        PermisoEmpleadoPOS.fecha_inicio >= date(anio, 1, 1),
                                        PermisoEmpleadoPOS.fecha_inicio <= date(anio, 12, 31))
    if excluir_id:
        q = q.filter(PermisoEmpleadoPOS.id != excluir_id)
    return sum(int(p.dias or 0) for p in q.all())


def pendientes_para_nomina(emp, bloquear=False):
    """Conceptos que la próxima nómina toma solos: permisos sin goce, prima vacacional, descuentos e Infonavit."""
    def q(modelo):
        x = modelo.query.filter_by(empleado_id=emp.id, aplicado=False)
        return x.with_for_update() if bloquear else x
    permisos = [p for p in q(PermisoEmpleadoPOS).all() if not p.con_goce]
    vacs = q(VacacionEmpleadoPOS).all()
    descs = q(DescuentoEmpleadoPOS).all()
    dias_perm = sum(int(p.dias or 0) for p in permisos)
    diario = sueldo_diario(emp)
    return {
        'permisos': permisos, 'vacaciones': vacs, 'descuentos': descs,
        'dias_permiso_sin_goce': dias_perm,
        'monto_permisos': round(dias_perm * diario, 2),
        'prima_vacacional': round(sum(v.prima or 0.0 for v in vacs), 2),
        'descuentos_empleado': round(sum(d.total or 0.0 for d in descs), 2),
        'infonavit': round(float(emp.infonavit or 0.0), 2),
    }


def resumen_pendientes(emp):
    p = pendientes_para_nomina(emp)
    return {k: v for k, v in p.items() if k not in ('permisos', 'vacaciones', 'descuentos')}


def aniversarios(empleados, margen=5):
    """Quién cumple años trabajando hoy, en los últimos o en los próximos `margen` días."""
    hoy = ahora_local().date()
    salida = []
    for e in empleados:
        if not e.fecha_ingreso or e.fecha_ingreso > hoy:
            continue
        for anio in (hoy.year - 1, hoy.year, hoy.year + 1):
            try:
                aniv = e.fecha_ingreso.replace(year=anio)
            except ValueError:            # 29 de febrero
                aniv = date(anio, 3, 1)
            dif = (aniv - hoy).days
            anios = anio - e.fecha_ingreso.year
            if abs(dif) <= margen and anios >= 1:
                cuando = 'HOY' if dif == 0 else (f'en {dif} día(s)' if dif > 0 else f'hace {-dif} día(s)')
                salida.append({'id': e.id, 'nombre': e.nombre, 'anios': anios, 'fecha': aniv.strftime('%d/%m/%Y'),
                               'cuando': cuando, 'dif': dif})
    return sorted(salida, key=lambda a: a['dif'])


def _emp(emp_id, bloquear=False):
    q = EmpleadoNominaPOS.query.filter_by(id=int(emp_id or 0))
    if bloquear:
        q = q.with_for_update()
    return q.first()


def _ser(obj, campos):
    out = {}
    for c in campos:
        v = getattr(obj, c)
        if isinstance(v, (date, datetime)):
            v = v.strftime('%Y-%m-%d %H:%M') if isinstance(v, datetime) else v.strftime('%Y-%m-%d')
        out[c] = v
    return out


CAMPOS = {
    'descuento': ['id', 'fecha', 'empleado_id', 'empleado_nombre', 'sucursal', 'saldo_anterior', 'playeras', 'gorras',
                  'mandiles', 'trastes_rotos', 'comandas_credito', 'abono_deuda', 'adelanto_sueldo', 'total', 'saldo',
                  'aplicado', 'usuario'],
    'aguinaldo': ['id', 'fecha_pago', 'empleado_id', 'empleado_nombre', 'sucursal', 'sueldo_diario', 'sueldo_quincena',
                  'dias_laborados', 'monto', 'usuario'],
    'bono': ['id', 'fecha', 'empleado_id', 'empleado_nombre', 'sucursal', 'sueldo_diario', 'dias_trabajados',
             'sueldo_quincena', 'liderazgo', 'iniciativa', 'puntualidad', 'eficiencia', 'productividad', 'total_pct',
             'importe', 'usuario'],
    'permiso': ['id', 'empleado_id', 'empleado_nombre', 'sucursal', 'tipo', 'con_goce', 'fecha_inicio', 'fecha_fin',
                'dias', 'observaciones', 'aplicado', 'usuario'],
    'vacacion': ['id', 'empleado_id', 'empleado_nombre', 'sucursal', 'antiguedad', 'dias', 'fecha_inicio', 'fecha_fin',
                 'sueldo_diario', 'salario', 'prima_pct', 'prima', 'importe', 'aplicado', 'usuario'],
}
MODELOS = {'descuento': DescuentoEmpleadoPOS, 'aguinaldo': AguinaldoEmpleadoPOS, 'bono': BonoEmpleadoPOS,
           'permiso': PermisoEmpleadoPOS, 'vacacion': VacacionEmpleadoPOS}
ORDEN = {'descuento': DescuentoEmpleadoPOS.fecha, 'aguinaldo': AguinaldoEmpleadoPOS.fecha_pago,
         'bono': BonoEmpleadoPOS.fecha, 'permiso': PermisoEmpleadoPOS.fecha_inicio,
         'vacacion': VacacionEmpleadoPOS.fecha_inicio}


# ------------------------------------------------------------------------------------------- catálogos
@nomina_bp.route('/api/nomina/catalogos', methods=['GET', 'POST'])
@login_required
def api_nomina_catalogos():
    if request.method == 'GET':
        return jsonify({'ok': True, 'catalogos': catalogos()})
    if _solo_admin():
        return jsonify({'ok': False, 'msg': 'Solo Admin.'}), 403
    d = request.json or {}
    try:
        areas = []
        for a in d.get('areas', []):
            nom = _txt(a.get('nombre'), 60)
            if nom:
                areas.append({'nombre': nom, 'puestos': sorted({_txt(p, 60) for p in a.get('puestos', []) if _txt(p, 60)})})
        turnos = []
        for t in d.get('turnos', []):
            nom = _txt(t.get('nombre'), 60)
            if nom:
                ent, sal = str(t.get('entrada') or '')[:5], str(t.get('salida') or '')[:5]
                for h in (ent, sal):
                    if h:
                        datetime.strptime(h, '%H:%M')
                turnos.append({'nombre': nom, 'entrada': ent, 'salida': sal})
        bajas = [_txt(b, 120) for b in d.get('tipos_baja', []) if _txt(b, 120)]
        permisos = [{'nombre': _txt(p.get('nombre'), 60), 'con_goce': bool(p.get('con_goce'))}
                    for p in d.get('tipos_permiso', []) if _txt(p.get('nombre'), 60)]
        prima = _num(d.get('prima_vacacional_pct', 25), minimo=25.0, maximo=100.0)
        max_goce = int(_num(d.get('max_dias_permiso_con_goce', 6), minimo=0, maximo=365))
    except ValueError as ex:
        return jsonify({'ok': False, 'msg': f'Dato inválido: {ex}. La prima vacacional no puede ser menor a 25 % (ley).'}), 400
    if not permisos:
        return jsonify({'ok': False, 'msg': 'Debe haber al menos un tipo de permiso.'}), 400
    nuevo = {'areas': areas, 'turnos': turnos, 'tipos_baja': bajas, 'tipos_permiso': permisos,
             'prima_vacacional_pct': prima, 'max_dias_permiso_con_goce': max_goce}
    cfg_guardar(CLAVE_CATALOGOS, nuevo)
    registrar_bitacora('CATALOGOS_NOMINA', '', 0.0, f'{len(areas)} áreas, {len(turnos)} turnos')
    return jsonify({'ok': True, 'catalogos': nuevo})


# ------------------------------------------------------------------------------------------- consulta
@nomina_bp.route('/api/nomina/empleado/<int:emp_id>')
@login_required
def api_nomina_empleado(emp_id):
    """Todo lo que necesita la pantalla de prestaciones para un empleado: datos para calcular e historial."""
    if _solo_admin():
        return jsonify({'ok': False}), 403
    e = _emp(emp_id)
    if not e:
        return jsonify({'ok': False, 'msg': 'Empleado no encontrado'}), 404
    hoy = ahora_local().date()
    cat = catalogos()
    anios = antiguedad_anios(e)
    inicio_anio = date(hoy.year, 1, 1)
    dias_anio = (hoy - max(inicio_anio, e.fecha_ingreso or inicio_anio)).days + 1
    vales = ConsumoEmpleadoPOS.query.filter_by(empleado_id=e.id, descontado=False).all()
    hist = {}
    for tipo, modelo in MODELOS.items():
        filas = modelo.query.filter_by(empleado_id=e.id).order_by(ORDEN[tipo].desc()).limit(40).all()
        hist[tipo] = [_ser(f, CAMPOS[tipo]) for f in filas]
    return jsonify({
        'ok': True,
        'empleado': {'id': e.id, 'nombre': e.nombre, 'puesto': e.puesto, 'sucursal': e.sucursal or SUCURSAL_DEFAULT,
                     'fecha_ingreso': e.fecha_ingreso.strftime('%Y-%m-%d') if e.fecha_ingreso else ''},
        'sueldo_diario': sueldo_diario(e), 'sueldo_hora': sueldo_hora(e),
        'antiguedad': anios, 'dias_vacaciones': dias_vacaciones_ley(anios),
        'prima_vacacional_pct': float(cat['prima_vacacional_pct']),
        'dias_laborados_anio': max(0, min(365, dias_anio)),
        'saldo_deuda': round(saldo_deuda(e.id), 2),
        'vales_pendientes': round(sum(v.monto for v in vales), 2),
        'aguinaldo_pagado_anio': any(a['fecha_pago'][:4] == str(hoy.year) for a in hist['aguinaldo']),
        'bono_pagado_anio': any(b['fecha'][:4] == str(hoy.year) for b in hist['bono']),
        'vacaciones_anio': any(v['fecha_inicio'][:4] == str(hoy.year) for v in hist['vacacion']),
        'dias_goce_usados': dias_permiso_con_goce_anio(e.id, hoy.year),
        'max_dias_goce': int(cat['max_dias_permiso_con_goce']),
        'pendientes_nomina': resumen_pendientes(e),
        'historial': hist,
    })


@nomina_bp.route('/api/nomina/reporte/<tipo>')
@login_required
def api_nomina_reporte(tipo):
    """Reporte general por tipo (como los listados del sistema anterior), filtrable por sucursal y fechas."""
    if _solo_admin():
        return jsonify({'ok': False}), 403
    if tipo not in MODELOS:
        return jsonify({'ok': False, 'msg': 'Tipo inválido'}), 404
    modelo, campo = MODELOS[tipo], ORDEN[tipo]
    q = modelo.query
    suc = request.args.get('sucursal', 'TODAS')
    if suc and suc != 'TODAS':
        q = q.filter(modelo.sucursal == suc)
    try:
        desde, hasta = _fecha(request.args.get('desde'), False), _fecha(request.args.get('hasta'), False)
    except ValueError as ex:
        return jsonify({'ok': False, 'msg': str(ex)}), 400
    if desde:
        q = q.filter(campo >= desde)
    if hasta:
        q = q.filter(campo < hasta + timedelta(days=1))
    filas = q.order_by(campo.desc()).limit(500).all()
    total_campo = {'descuento': 'total', 'aguinaldo': 'monto', 'bono': 'importe', 'permiso': 'dias', 'vacacion': 'importe'}[tipo]
    return jsonify({'ok': True, 'filas': [_ser(f, CAMPOS[tipo]) for f in filas],
                    'total': round(sum(float(getattr(f, total_campo) or 0) for f in filas), 2)})


# ------------------------------------------------------------------------------------------- altas
def _respuesta_error(ex):
    return jsonify({'ok': False, 'msg': str(ex)}), 400


@nomina_bp.route('/api/nomina/descuento', methods=['POST'])
@login_required
def api_nomina_descuento():
    """Descuento al empleado. Las comandas a crédito son sus vales de consumo pendientes: se marcan como
    descontados aquí (el sistema anterior las borraba) para que la nómina no las cobre dos veces."""
    if _solo_admin():
        return jsonify({'ok': False}), 403
    d = request.json or {}
    e = _emp(d.get('empleado_id'), bloquear=True)
    if not e:
        return jsonify({'ok': False, 'msg': 'Empleado no encontrado'}), 404
    try:
        vals = {k: _num(d.get(k, 0)) for k in ('playeras', 'gorras', 'mandiles', 'trastes_rotos', 'abono_deuda',
                                               'adelanto_sueldo', 'saldo_anterior')}
    except ValueError as ex:
        return _respuesta_error(ex)
    hoy = ahora_local()
    inicio = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
    if DescuentoEmpleadoPOS.query.filter(DescuentoEmpleadoPOS.empleado_id == e.id, DescuentoEmpleadoPOS.fecha >= inicio).first():
        return jsonify({'ok': False, 'msg': 'A este empleado ya se le registró un descuento hoy.'}), 409
    previo = DescuentoEmpleadoPOS.query.filter_by(empleado_id=e.id).first()
    saldo_ant = saldo_deuda(e.id) if previo else vals['saldo_anterior']   # la primera vez se captura la deuda inicial
    if vals['abono_deuda'] > saldo_ant + 0.01:
        return jsonify({'ok': False, 'msg': f'El abono (${vals["abono_deuda"]:.2f}) es mayor que la deuda (${saldo_ant:.2f}).'}), 400
    vales = []
    if bool(d.get('incluir_comandas', True)):
        vales = ConsumoEmpleadoPOS.query.filter_by(empleado_id=e.id, descontado=False).with_for_update().all()
    comandas = round(sum(v.monto for v in vales), 2)
    uniformes = vals['playeras'] + vals['gorras'] + vals['mandiles']
    total = round(uniformes + vals['trastes_rotos'] + comandas + vals['abono_deuda'] + vals['adelanto_sueldo'], 2)
    if total <= 0:
        return jsonify({'ok': False, 'msg': 'No hay nada que descontar.'}), 400
    for v in vales:
        v.descontado = True
    reg = DescuentoEmpleadoPOS(
        fecha=hoy, empleado_id=e.id, empleado_nombre=e.nombre, sucursal=e.sucursal or SUCURSAL_DEFAULT,
        saldo_anterior=round(saldo_ant, 2), playeras=vals['playeras'], gorras=vals['gorras'], mandiles=vals['mandiles'],
        trastes_rotos=vals['trastes_rotos'], comandas_credito=comandas, abono_deuda=vals['abono_deuda'],
        adelanto_sueldo=vals['adelanto_sueldo'], total=total, saldo=round(saldo_ant - vals['abono_deuda'], 2),
        usuario=current_user.username.upper())
    db.session.add(reg)
    db.session.commit()
    registrar_bitacora('DESCUENTO_EMPLEADO', e.nombre, total, f'Uniformes:{uniformes} Comandas:{comandas} Deuda:{reg.saldo}',
                       sucursal=e.sucursal)
    return jsonify({'ok': True, 'registro': _ser(reg, CAMPOS['descuento'])})


@nomina_bp.route('/api/nomina/aguinaldo', methods=['POST'])
@login_required
def api_nomina_aguinaldo():
    if _solo_admin():
        return jsonify({'ok': False}), 403
    d = request.json or {}
    e = _emp(d.get('empleado_id'), bloquear=True)
    if not e:
        return jsonify({'ok': False, 'msg': 'Empleado no encontrado'}), 404
    try:
        fecha = _fecha(d.get('fecha_pago'))
        dias = int(_num(d.get('dias_laborados', 0), minimo=1, maximo=366))
    except ValueError as ex:
        return _respuesta_error(ex)
    ya = AguinaldoEmpleadoPOS.query.filter(AguinaldoEmpleadoPOS.empleado_id == e.id,
                                           AguinaldoEmpleadoPOS.fecha_pago >= date(fecha.year, 1, 1),
                                           AguinaldoEmpleadoPOS.fecha_pago <= date(fecha.year, 12, 31)).first()
    if ya:
        return jsonify({'ok': False, 'msg': f'Ya se pagó aguinaldo a {e.nombre} en {fecha.year}.'}), 409
    diario = sueldo_diario(e)
    quincena = round(diario * 15, 2)
    reg = AguinaldoEmpleadoPOS(fecha_pago=fecha, empleado_id=e.id, empleado_nombre=e.nombre,
                               sucursal=e.sucursal or SUCURSAL_DEFAULT, sueldo_diario=diario, sueldo_quincena=quincena,
                               dias_laborados=dias, monto=round(quincena / 365 * dias, 2),
                               usuario=current_user.username.upper())
    db.session.add(reg)
    db.session.commit()
    registrar_bitacora('AGUINALDO', e.nombre, reg.monto, f'{dias} días laborados', sucursal=e.sucursal)
    return jsonify({'ok': True, 'registro': _ser(reg, CAMPOS['aguinaldo'])})


@nomina_bp.route('/api/nomina/bono', methods=['POST'])
@login_required
def api_nomina_bono():
    if _solo_admin():
        return jsonify({'ok': False}), 403
    d = request.json or {}
    e = _emp(d.get('empleado_id'), bloquear=True)
    if not e:
        return jsonify({'ok': False, 'msg': 'Empleado no encontrado'}), 404
    try:
        fecha = _fecha(d.get('fecha'))
        dias = int(_num(d.get('dias_trabajados', 0), minimo=1, maximo=31))
        pcts = {k: _num(d.get(k, 0), maximo=MAX_PCT_BONO)
                for k in ('liderazgo', 'iniciativa', 'puntualidad', 'eficiencia', 'productividad')}
    except ValueError as ex:
        return _respuesta_error(ex)
    total_pct = round(sum(pcts.values()), 2)
    if total_pct > MAX_PCT_BONO:
        return jsonify({'ok': False, 'msg': 'La suma de los porcentajes no puede pasar de 100 %.'}), 400
    if total_pct <= 0:
        return jsonify({'ok': False, 'msg': 'Captura al menos un porcentaje.'}), 400
    ya = BonoEmpleadoPOS.query.filter(BonoEmpleadoPOS.empleado_id == e.id, BonoEmpleadoPOS.fecha >= date(fecha.year, 1, 1),
                                      BonoEmpleadoPOS.fecha <= date(fecha.year, 12, 31)).first()
    if ya:
        return jsonify({'ok': False, 'msg': f'Ya se pagó bono a {e.nombre} en {fecha.year}.'}), 409
    diario = sueldo_diario(e)
    quincena = round(dias * diario, 2)
    reg = BonoEmpleadoPOS(fecha=fecha, empleado_id=e.id, empleado_nombre=e.nombre, sucursal=e.sucursal or SUCURSAL_DEFAULT,
                          sueldo_diario=diario, dias_trabajados=dias, sueldo_quincena=quincena, total_pct=total_pct,
                          importe=round(quincena * total_pct / 100, 2), usuario=current_user.username.upper(), **pcts)
    db.session.add(reg)
    db.session.commit()
    registrar_bitacora('BONO', e.nombre, reg.importe, f'{total_pct:g}% de ${quincena}', sucursal=e.sucursal)
    return jsonify({'ok': True, 'registro': _ser(reg, CAMPOS['bono'])})


@nomina_bp.route('/api/nomina/permiso', methods=['POST'])
@login_required
def api_nomina_permiso():
    if _solo_admin():
        return jsonify({'ok': False}), 403
    d = request.json or {}
    e = _emp(d.get('empleado_id'), bloquear=True)
    if not e:
        return jsonify({'ok': False, 'msg': 'Empleado no encontrado'}), 404
    try:
        ini, fin = _fecha(d.get('fecha_inicio')), _fecha(d.get('fecha_fin'))
    except ValueError as ex:
        return _respuesta_error(ex)
    if fin < ini:
        return jsonify({'ok': False, 'msg': 'La fecha final no puede ser antes de la inicial.'}), 400
    cat = catalogos()
    tipo = next((t for t in cat['tipos_permiso'] if t['nombre'] == _txt(d.get('tipo'), 60)), None)
    if not tipo:
        return jsonify({'ok': False, 'msg': 'Selecciona el tipo de permiso.'}), 400
    dias = (fin - ini).days + 1
    traslape = PermisoEmpleadoPOS.query.filter(PermisoEmpleadoPOS.empleado_id == e.id, PermisoEmpleadoPOS.fecha_inicio <= fin,
                                               PermisoEmpleadoPOS.fecha_fin >= ini).first()
    if traslape:
        return jsonify({'ok': False, 'msg': 'Ese empleado ya tiene un permiso en esas fechas.'}), 409
    if tipo['con_goce']:
        tope = int(cat['max_dias_permiso_con_goce'])
        usados = dias_permiso_con_goce_anio(e.id, ini.year)
        if usados + dias > tope:
            return jsonify({'ok': False, 'msg': f'Los permisos con goce no pueden pasar de {tope} días al año '
                                                f'(lleva {usados}, pide {dias}).'}), 400
    reg = PermisoEmpleadoPOS(empleado_id=e.id, empleado_nombre=e.nombre, sucursal=e.sucursal or SUCURSAL_DEFAULT,
                             tipo=tipo['nombre'], con_goce=bool(tipo['con_goce']), fecha_inicio=ini, fecha_fin=fin,
                             dias=dias, observaciones=str(d.get('observaciones') or '').strip()[:250],
                             aplicado=bool(tipo['con_goce']),   # con goce no descuenta nada en la nómina
                             usuario=current_user.username.upper())
    db.session.add(reg)
    db.session.commit()
    registrar_bitacora('PERMISO', e.nombre, 0.0, f'{tipo["nombre"]} {dias} día(s) {ini}', sucursal=e.sucursal)
    return jsonify({'ok': True, 'registro': _ser(reg, CAMPOS['permiso'])})


@nomina_bp.route('/api/nomina/vacacion', methods=['POST'])
@login_required
def api_nomina_vacacion():
    if _solo_admin():
        return jsonify({'ok': False}), 403
    d = request.json or {}
    e = _emp(d.get('empleado_id'), bloquear=True)
    if not e:
        return jsonify({'ok': False, 'msg': 'Empleado no encontrado'}), 404
    try:
        ini = _fecha(d.get('fecha_inicio'))
    except ValueError as ex:
        return _respuesta_error(ex)
    if not e.fecha_ingreso:
        return jsonify({'ok': False, 'msg': 'Captura primero la fecha de ingreso en la ficha del empleado.'}), 400
    anios = antiguedad_anios(e, ini)
    dias = dias_vacaciones_ley(anios)
    if dias <= 0:
        return jsonify({'ok': False, 'msg': 'Aún no cumple un año: todavía no le tocan vacaciones.'}), 400
    ya = VacacionEmpleadoPOS.query.filter(VacacionEmpleadoPOS.empleado_id == e.id,
                                          VacacionEmpleadoPOS.fecha_inicio >= date(ini.year, 1, 1),
                                          VacacionEmpleadoPOS.fecha_inicio <= date(ini.year, 12, 31)).first()
    if ya:
        return jsonify({'ok': False, 'msg': f'{e.nombre} ya tiene vacaciones registradas en {ini.year}.'}), 409
    pct = float(catalogos()['prima_vacacional_pct'])
    diario = sueldo_diario(e)
    salario = round(diario * dias, 2)
    prima = round(salario * pct / 100, 2)
    reg = VacacionEmpleadoPOS(empleado_id=e.id, empleado_nombre=e.nombre, sucursal=e.sucursal or SUCURSAL_DEFAULT,
                              antiguedad=anios, dias=dias, fecha_inicio=ini, fecha_fin=fin_sin_domingos(ini, dias),
                              sueldo_diario=diario, salario=salario, prima_pct=pct, prima=prima,
                              importe=round(salario + prima, 2), usuario=current_user.username.upper())
    db.session.add(reg)
    db.session.commit()
    registrar_bitacora('VACACIONES', e.nombre, reg.importe, f'{dias} días desde {ini}, prima ${prima}', sucursal=e.sucursal)
    return jsonify({'ok': True, 'registro': _ser(reg, CAMPOS['vacacion'])})


@nomina_bp.route('/api/nomina/<tipo>/<int:reg_id>', methods=['DELETE'])
@login_required
def api_nomina_borrar(tipo, reg_id):
    """Corrige una captura equivocada. Lo que ya entró a una nómina pagada no se puede borrar."""
    if _solo_admin():
        return jsonify({'ok': False}), 403
    if tipo not in MODELOS:
        return jsonify({'ok': False, 'msg': 'Tipo inválido'}), 404
    reg = MODELOS[tipo].query.get_or_404(reg_id)
    if getattr(reg, 'recibo_id', None):
        return jsonify({'ok': False, 'msg': 'Ya se aplicó en una nómina pagada: no se puede borrar.'}), 409
    if tipo == 'descuento':
        posterior = DescuentoEmpleadoPOS.query.filter(DescuentoEmpleadoPOS.empleado_id == reg.empleado_id,
                                                      DescuentoEmpleadoPOS.id > reg.id).first()
        if posterior:
            return jsonify({'ok': False, 'msg': 'Solo se puede borrar el último descuento del empleado (por el saldo de deuda).'}), 409
    monto = float(getattr(reg, 'total', None) or getattr(reg, 'monto', None) or getattr(reg, 'importe', None) or 0.0)
    db.session.delete(reg)
    db.session.commit()
    registrar_bitacora(f'BORRAR_{tipo.upper()}', reg.empleado_nombre, monto, f'Registro #{reg_id}', sucursal=reg.sucursal)
    return jsonify({'ok': True})


# ------------------------------------------------------------------------------------------- bajas
@nomina_bp.route('/api/nomina/bajas')
@login_required
def api_nomina_bajas():
    if _solo_admin():
        return jsonify({'ok': False}), 403
    bajas = EmpleadoNominaPOS.query.filter_by(activo=False).order_by(EmpleadoNominaPOS.fecha_baja.desc()).limit(300).all()
    return jsonify({'ok': True, 'bajas': [{
        'id': e.id, 'nombre': e.nombre, 'puesto': e.puesto, 'sucursal': e.sucursal or SUCURSAL_DEFAULT,
        'fecha_ingreso': e.fecha_ingreso.strftime('%Y-%m-%d') if e.fecha_ingreso else '',
        'fecha_baja': e.fecha_baja.strftime('%Y-%m-%d') if e.fecha_baja else '',
        'motivo_baja': e.motivo_baja or '', 'foto_url': e.foto_url or ''} for e in bajas]})


@nomina_bp.route('/api/nomina/reactivar/<int:emp_id>', methods=['POST'])
@login_required
def api_nomina_reactivar(emp_id):
    if _solo_admin():
        return jsonify({'ok': False}), 403
    e = EmpleadoNominaPOS.query.get_or_404(emp_id)
    e.activo, e.fecha_baja, e.motivo_baja = True, None, None
    db.session.commit()
    registrar_bitacora('REACTIVAR_EMPLEADO', e.nombre, 0.0, '', sucursal=e.sucursal)
    return jsonify({'ok': True})
