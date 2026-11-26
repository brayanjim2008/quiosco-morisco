# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, cam1, check, H).
# Auxiliar de nómina como el sistema anterior: expediente, descuentos, aguinaldo, bonos, permisos, vacaciones,
# catálogos, bajas con motivo, aniversarios y nómina con todos los conceptos.
from datetime import timedelta as _td
from models import (EmpleadoNominaPOS as _Emp, ConsumoEmpleadoPOS as _Cons, ReciboNominaPOS as _Rec,
                    DescuentoEmpleadoPOS as _Desc, PermisoEmpleadoPOS as _Perm, VacacionEmpleadoPOS as _Vac, ahora_local as _ahora)
import nomina_routes as _nr

_hoy = _ahora().date()
check([_nr.dias_vacaciones_ley(a) for a in (0, 1, 2, 5, 6, 10, 11)] == [0, 12, 14, 20, 22, 22, 24], 'tabla de vacaciones LFT 2023')
check(_nr.fin_sin_domingos(_ahora().date().replace(year=2026, month=11, day=27), 3).isoformat() == '2026-11-30',
      'el fin de vacaciones salta domingos (vie 27 + 3 días hábiles = lun 30)')

ingreso = _hoy.replace(year=_hoy.year - 3) - _td(days=2)   # 3 años y 2 días: aniversario hace 2 días
r = admin.post('/api/finanzas/empleado', json={
    'nombre': 'pedro nomina', 'puesto': 'MESERO', 'sucursal': 'Caminante 1', 'sueldo_diario': 300, 'sueldo_base': 1800,
    'dias_base': 6, 'fecha_ingreso': ingreso.isoformat(), 'rfc': 'GOMP800101AB1', 'nss': '12345678901', 'infonavit': 50,
    'area': 'SERVICIO', 'turno': 'MATUTINO', 'sexo': 'HOMBRE', 'documentos': ['acta', 'curp', 'inventado']}, headers=H)
check(r.status_code == 200, f'alta con expediente completo ({r.status_code} {r.json})')
pid = r.json['id']
check(admin.post('/api/finanzas/empleado', json={'nombre': 'X', 'rfc': 'MALO'}, headers=H).status_code == 400, 'RFC inválido se rechaza')
check(admin.post('/api/finanzas/empleado', json={'nombre': 'X', 'nss': '123'}, headers=H).status_code == 400, 'NSS inválido se rechaza')
d = admin.get('/api/finanzas/datos').json
yo = next(e for e in d['empleados'] if e['id'] == pid)
check(yo['documentos'] == ['acta', 'curp'] and yo['acta_nacimiento'] is True and yo['rfc'] == 'GOMP800101AB1'
      and yo['antiguedad'] == 3 and yo['infonavit'] == 50, f'expediente guardado ({yo})')
check(any(a['id'] == pid and a['anios'] == 3 for a in d['aniversarios']), 'aviso de aniversario laboral (±5 días)')

# Catálogos
r = admin.get('/api/nomina/catalogos')
cat = r.json['catalogos']
check(any(t['nombre'] == 'SIN GOCE DE SUELDO' and not t['con_goce'] for t in cat['tipos_permiso']), 'catálogos con tipos de permiso')
check(admin.post('/api/nomina/catalogos', json=dict(cat, prima_vacacional_pct=10), headers=H).status_code == 400,
      'prima vacacional menor a 25 % se rechaza (ley)')
check(cam1.get('/api/nomina/empleado/%d' % pid).status_code == 403, 'caja no entra al auxiliar de nómina')

# Descuentos: el vale de consumo pendiente entra como "comanda a crédito" y no se cobra dos veces
admin.post('/api/finanzas/consumo_empleado', json={'empleado_id': pid, 'tipo': 'CONSUMO', 'monto': 80, 'concepto': 'COMIDA'}, headers=H)
r = admin.post('/api/nomina/descuento', json={'empleado_id': pid, 'playeras': 50, 'saldo_anterior': 500, 'abono_deuda': 100}, headers=H)
check(r.status_code == 200 and r.json['registro']['total'] == 230 and r.json['registro']['saldo'] == 400
      and r.json['registro']['comandas_credito'] == 80, f'descuento: uniformes + comandas + abono, deuda 500→400 ({r.json})')
with app.app_context():
    check(_Cons.query.filter_by(empleado_id=pid, descontado=False).count() == 0, 'la comanda a crédito queda descontada')
r = admin.post('/api/nomina/descuento', json={'empleado_id': pid, 'gorras': 10}, headers=H)
check(r.status_code == 409, 'solo un descuento por día por empleado')

# Aguinaldo: (300 x 15 / 365) x 100 = 1232.88, uno por año
r = admin.post('/api/nomina/aguinaldo', json={'empleado_id': pid, 'fecha_pago': _hoy.isoformat(), 'dias_laborados': 100}, headers=H)
check(r.status_code == 200 and r.json['registro']['monto'] == 1232.88 and r.json['registro']['sueldo_quincena'] == 4500,
      f'aguinaldo con la fórmula anterior ({r.json})')
check(admin.post('/api/nomina/aguinaldo', json={'empleado_id': pid, 'fecha_pago': _hoy.isoformat(), 'dias_laborados': 5}, headers=H).status_code == 409,
      'un solo aguinaldo por año')

# Bonos: 15 días x 300 = 4500; 20 % → 900; tope 100 %
r = admin.post('/api/nomina/bono', json={'empleado_id': pid, 'fecha': _hoy.isoformat(), 'dias_trabajados': 15,
                                         'liderazgo': 60, 'puntualidad': 50}, headers=H)
check(r.status_code == 400, 'bono con más de 100 % se rechaza')
r = admin.post('/api/nomina/bono', json={'empleado_id': pid, 'fecha': _hoy.isoformat(), 'dias_trabajados': 15,
                                         'liderazgo': 10, 'puntualidad': 10}, headers=H)
check(r.status_code == 200 and r.json['registro']['importe'] == 900, f'bono = quincena x % ({r.json})')

# Permisos: con goce máx 6 días/año; sin goce se descuenta en la nómina
r = admin.post('/api/nomina/permiso', json={'empleado_id': pid, 'tipo': 'CON GOCE DE SUELDO',
                                            'fecha_inicio': '2026-01-05', 'fecha_fin': '2026-01-11'}, headers=H)
check(r.status_code == 400 and '6' in r.json['msg'], 'permiso con goce de más de 6 días al año se rechaza')
r = admin.post('/api/nomina/permiso', json={'empleado_id': pid, 'tipo': 'SIN GOCE DE SUELDO',
                                            'fecha_inicio': '2026-02-02', 'fecha_fin': '2026-02-03'}, headers=H)
check(r.status_code == 200 and r.json['registro']['dias'] == 2, 'permiso sin goce de 2 días')
check(admin.post('/api/nomina/permiso', json={'empleado_id': pid, 'tipo': 'SIN GOCE DE SUELDO',
                                              'fecha_inicio': '2026-02-03', 'fecha_fin': '2026-02-04'}, headers=H).status_code == 409,
      'no se permiten permisos encimados')

# Vacaciones: 3 años → 16 días; salario 4800; prima 40 % = 1920
r = admin.post('/api/nomina/vacacion', json={'empleado_id': pid, 'fecha_inicio': _hoy.isoformat()}, headers=H)
check(r.status_code == 200 and r.json['registro']['dias'] == 16 and r.json['registro']['salario'] == 4800
      and r.json['registro']['prima'] == 1920, f'vacaciones por antigüedad con prima ({r.json})')

info = admin.get('/api/nomina/empleado/%d' % pid).json
pn = info['pendientes_nomina']
check(pn['descuentos_empleado'] == 230 and pn['monto_permisos'] == 600 and pn['prima_vacacional'] == 1920 and pn['infonavit'] == 50,
      f'pendientes para la siguiente nómina ({pn})')

# Nómina: 6/6 días (1800) + 1 turno extra (300) + 2 h extra (2 x 37.50) + prima 1920
#         - 1 falta doble (600) - permisos 600 - infonavit 50 - descuentos 230 = 2615
r = admin.post('/api/finanzas/generar_nomina', json={'empleado_id': pid, 'dias_trabajados': 6, 'turnos_extra': 1,
               'horas_extra': 2, 'faltas': 1, 'retardos': 2, 'observaciones': 'prueba'}, headers=H)
j = r.json or {}
check(r.status_code == 200 and j['recibo']['total_neto'] == 2615.0 and j['recibo']['detalle']['retardos'] == 2,
      f'nómina con todos los conceptos del sistema anterior ({j})')
with app.app_context():
    rid = j['recibo']['id']
    check(_Desc.query.filter_by(empleado_id=pid, aplicado=False).count() == 0
          and _Perm.query.filter_by(empleado_id=pid, recibo_id=rid).count() == 1
          and _Vac.query.filter_by(empleado_id=pid, recibo_id=rid).count() == 1, 'lo aplicado queda ligado al recibo')
r = admin.post('/api/finanzas/generar_nomina', json={'empleado_id': pid, 'dias_trabajados': 6}, headers=H)
check(r.status_code == 200 and r.json['recibo']['total_neto'] == 1750.0, 'la siguiente nómina ya no repite descuentos (1800 - infonavit 50)')
d_id = info['historial']['descuento'][0]['id']
check(admin.delete('/api/nomina/descuento/%d' % d_id, headers=H).status_code == 409, 'no se borra lo que ya entró a una nómina')
rep = admin.get('/api/nomina/reporte/aguinaldo?sucursal=Caminante 1').json
check(rep['ok'] and rep['total'] >= 1232.88, 'reporte general de aguinaldos por sucursal')

# Baja con motivo y reactivación
check(admin.delete('/api/finanzas/empleado', json={'id': pid}, headers=H).status_code == 400, 'la baja pide motivo')
r = admin.delete('/api/finanzas/empleado', json={'id': pid, 'motivo_baja': 'RENUNCIA VOLUNTARIA'}, headers=H)
check(r.status_code == 200, 'baja con motivo')
b = admin.get('/api/nomina/bajas').json['bajas']
check(any(x['id'] == pid and x['motivo_baja'] == 'RENUNCIA VOLUNTARIA' and x['fecha_baja'] for x in b), 'lista de bajas con motivo y fecha')
check(admin.post('/api/nomina/reactivar/%d' % pid, headers=H).status_code == 200, 'reactivar empleado')
admin.delete('/api/finanzas/empleado', json={'id': pid, 'motivo_baja': 'PRUEBA'}, headers=H)

h_nom = admin.get('/nomina_creditos').get_data(as_text=True)
check('id="sec_prestaciones"' in h_nom and 'id="sec_catalogos"' in h_nom and 'class="emp-doc"' in h_nom
      and 'id="nom_faltas"' in h_nom, 'pantalla: prestaciones, catálogos, documentos y conceptos de nómina')
check('id="sec_prestaciones"' not in cam1.get('/nomina_creditos').get_data(as_text=True), 'la caja no ve el auxiliar de nómina')

# ---- Retardos automáticos (horario del turno vs. checador) ----
from datetime import datetime as _dt, timedelta as _td2
from models import RegistroAsistencia as _RAs
cat = admin.get('/api/nomina/catalogos').json['catalogos']
r = admin.post('/api/nomina/catalogos', json=dict(cat, tolerancia_retardo_min=10, retardos_por_falta=2), headers=H)
check(r.status_code == 200 and r.json['catalogos']['retardos_por_falta'] == 2, 'configurar tolerancia y retardos por falta')
r = admin.post('/api/finanzas/empleado', json={'nombre': 'rita retardos', 'sucursal': 'Caminante 1', 'turno': 'MATUTINO',
               'sueldo_diario': 200, 'sueldo_base': 1200, 'dias_base': 6}, headers=H)
rid = r.json['id']
_h = _ahora().replace(second=0, microsecond=0)
with app.app_context():
    for dias_atras, hh, mm in ((1, 7, 25), (2, 7, 5), (3, 7, 40), (4, 6, 55)):   # turno MATUTINO entra 07:00
        d0 = (_h - _td2(days=dias_atras)).replace(hour=hh, minute=mm)
        db.session.add(_RAs(fecha=d0, sucursal='Caminante 1', empleado_nombre='RITA RETARDOS', tipo='ENTRADA'))
    db.session.commit()
info = admin.get(f'/api/nomina/empleado/{rid}').json['retardos']
check(info['turno_con_horario'] and info['retardos'] == 2 and info['dias_descuento'] == 1,
      f'2 retardos (07:25 y 07:40) con tolerancia de 10 min = 1 día de descuento ({info})')
r = admin.post('/api/finanzas/generar_nomina', json={'empleado_id': rid, 'dias_trabajados': 6, 'retardos': info['retardos']}, headers=H)
check(r.status_code == 200 and r.json['recibo']['detalle']['monto_retardos'] == 200 and r.json['recibo']['total_neto'] == 1000,
      f'la nómina descuenta el día por retardos (1200 - 200) ({r.json["recibo"]["detalle"].get("monto_retardos")})')
asis = admin.get('/api/checador/lista?desde=2000-01-01&empleado=RITA').json['asistencias']
check(sorted(a['retardo_min'] for a in asis) == [0, 0, 25, 40], f'el reporte de asistencia marca los minutos tarde ({[a["retardo_min"] for a in asis]})')
admin.post('/api/nomina/catalogos', json=dict(cat), headers=H)
