# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, cam1, H, tcj, check, token_de, db).
from datetime import timedelta as _td
from models import CuentaPOS, DetallePOS, Reservacion, ahora_local as _ahora, esquema_faltante


def _abrir_k(mesa):
    admin.post('/api/pos/abrir_mesa', json={'mesa': mesa, 'personas': 2}, headers=H)
    with app.app_context():
        return CuentaPOS.query.filter_by(mesa=mesa, estado='ABIERTA').first().id


def _cap(cid, desc, area, precio=50):
    r = admin.post('/api/pos/capturar_item', json={'cuenta_id': cid, 'descripcion': desc, 'precio': precio, 'cantidad': 1,
                   'clave': '09999', 'area_impresion': area, 'agrupar': False}, headers=H)
    return r.json.get('detalle_id')


def _kds(cli, area):
    return cli.get('/api/kds?area=' + area).json


def _ticket(d, mesa):
    return next((t for t in d.get('tickets', []) if t['mesa'] == mesa), None)

# ---------- KDS: solo lo enviado, separado por área ----------
k1 = _abrir_k('KDS1')
id_bebida = _cap(k1, 'LIMONADA KDS', 'BARRA')
id_plato = _cap(k1, 'CHILAQUILES KDS', 'COCINA')
check(_ticket(_kds(admin, 'BARRA'), 'KDS1') is None, 'KDS: lo capturado sin enviar no aparece')
r = admin.post(f'/api/pos/enviar_comanda/{k1}', json={}, headers=H)
check(r.status_code == 200, 'comanda enviada')
with app.app_context():
    d_beb = DetallePOS.query.get(id_bebida)
    check(d_beb.enviado_en is not None and d_beb.kds_estado == 'PENDIENTE', 'al enviar se registra la hora de envío (listener)')
tb = _ticket(_kds(admin, 'BARRA'), 'KDS1')
tc = _ticket(_kds(admin, 'COCINA'), 'KDS1')
check(tb and [l['descripcion'] for l in tb['lineas']] == ['LIMONADA KDS'], 'KDS Barra muestra solo la bebida')
check(tc and [l['descripcion'] for l in tc['lineas']] == ['CHILAQUILES KDS'] and tc['estado'] == 'PENDIENTE', 'KDS Cocina muestra solo el platillo')
check(clientes['paola'].get('/api/kds?area=COCINA').status_code == 200, 'mesero puede ver el KDS')
check(_ticket(_kds(cam1, 'COCINA'), 'KDS1') is None, 'otra sucursal no ve las comandas de la Matriz')
r = cam1.post('/api/kds/estado', json={'ids': tc['ids'], 'estado': 'LISTO'}, headers={'X-CSRFToken': token_de(cam1.get('/kds').get_data(as_text=True))})
check(r.json.get('actualizados') == 0, 'otra sucursal no puede cambiar comandas ajenas')
check(admin.post('/api/kds/estado', json={'ids': tc['ids'], 'estado': 'RARO'}, headers=H).status_code == 400, 'estado inválido rechazado')

# Agregar otro platillo después = ticket nuevo (otra ronda)
with app.app_context():
    d = DetallePOS.query.get(id_plato); d.enviado_en = d.enviado_en - _td(minutes=25); db.session.commit()
id_plato2 = _cap(k1, 'OMELETE KDS', 'COCINA')
admin.post(f'/api/pos/enviar_comanda/{k1}', json={}, headers=H)
tks = [t for t in _kds(admin, 'COCINA')['tickets'] if t['mesa'] == 'KDS1']
check(len(tks) == 2 and tks[0]['minutos'] >= 25 and [l['descripcion'] for l in tks[1]['lineas']] == ['OMELETE KDS'],
      'una ronda nueva es otro ticket; el viejo marca sus minutos de espera')

# Flujo de estados
admin.post('/api/kds/estado', json={'ids': tks[0]['ids'], 'estado': 'PREPARANDO'}, headers=H)
check(_kds(admin, 'COCINA')['tickets'][0]['estado'] == 'PREPARANDO', 'PREPARANDO')
admin.post('/api/kds/estado', json={'ids': tks[0]['ids'], 'estado': 'LISTO'}, headers=H)
d = _kds(admin, 'COCINA')
check(next(t for t in d['tickets'] if t['clave'] == tks[0]['clave'])['estado'] == 'LISTO' and d['promedio_min'] is not None
      and d['promedio_min'] >= 25, f"LISTO y tiempo promedio de preparación ({d['promedio_min']} min)")
admin.post('/api/kds/estado', json={'ids': tks[0]['ids'], 'estado': 'ENTREGADO'}, headers=H)
check(all(t['clave'] != tks[0]['clave'] for t in _kds(admin, 'COCINA')['tickets']), 'ENTREGADO desaparece del monitor')

# Dividir por productos conserva hora y estado (no reaparece como nuevo)
k2 = _abrir_k('KDS2')
id_a = _cap(k2, 'TOSTADA KDS', 'COCINA')
_cap(k2, 'QUESADILLA KDS', 'COCINA')
admin.post(f'/api/pos/enviar_comanda/{k2}', json={}, headers=H)
admin.post('/api/kds/estado', json={'ids': [id_a], 'estado': 'LISTO'}, headers=H)
with app.app_context():
    env_a = DetallePOS.query.get(id_a).enviado_en
r = admin.post('/api/pos/dividir_cuenta_real', json={'cuenta_id': k2, 'subcuentas': {'B': [{'id': id_a, 'cantidad': 1}]}}, headers=H)
with app.app_context():
    movidos = DetallePOS.query.filter(DetallePOS.descripcion == 'TOSTADA KDS', DetallePOS.cuenta_id != k2).all()
check(r.status_code == 200 and movidos and movidos[0].enviado_en == env_a and movidos[0].kds_estado == 'LISTO',
      f'al dividir, el platillo conserva hora de envío y estado del KDS ({r.status_code})')

# Comandas viejas (sin hora de envío, de antes de esta versión) no aparecen
with app.app_context():
    DetallePOS.query.get(id_bebida).enviado_en = None; db.session.commit()
check(_ticket(_kds(admin, 'BARRA'), 'KDS1') is None, 'detalles sin hora de envío (históricos) no se muestran')

# Pantalla y configuración
h = admin.get('/kds').get_data(as_text=True)
check('Monitor' in h and 'api/kds' in h and 'csrf-token' in h, 'pantalla /kds')
check(admin.post('/api/kds/config', json={'amarillo': 8, 'rojo': 15}, headers=H).json.get('alertas') == {'amarillo': 8, 'rojo': 15},
      'admin ajusta tiempos de alerta')
check(_kds(admin, 'COCINA')['alertas'] == {'amarillo': 8, 'rojo': 15}, 'alertas nuevas en el monitor')
check(admin.post('/api/kds/config', json={'amarillo': 20, 'rojo': 10}, headers=H).status_code == 400, 'rojo debe ser mayor que amarillo')
check(clientes['brayan'].post('/api/kds/config', json={'amarillo': 5, 'rojo': 9}, headers={'X-CSRFToken': tcj}).status_code == 403,
      'solo admin cambia las alertas')
check('href="/kds"' in admin.get('/pos').get_data(as_text=True), 'POS tiene acceso al monitor de cocina')

# ---------- Reservaciones ----------
HJ = {'X-CSRFToken': tcj}
cuando = _ahora() + _td(hours=1)
F, HR = cuando.strftime('%Y-%m-%d'), cuando.strftime('%H:%M')
r = clientes['brayan'].post('/api/reservaciones', json={'nombre': 'Familia López', 'telefono': '967 123 4567', 'fecha': F, 'hora': HR,
                            'personas': 6, 'mesa': 'm5', 'notas': 'cumpleaños'}, headers=HJ)
R1 = r.json['reservacion']['id']
check(r.status_code == 200 and r.json['reservacion']['mesa'] == 'M5' and r.json['reservacion']['estado'] == 'PENDIENTE', 'crear reservación')
media = (cuando + _td(minutes=30)).strftime('%H:%M')
fecha_media = (cuando + _td(minutes=30)).strftime('%Y-%m-%d')
r = clientes['brayan'].post('/api/reservaciones', json={'nombre': 'Otro', 'fecha': fecha_media, 'hora': media, 'mesa': 'M5'}, headers=HJ)
check(r.status_code == 409 and r.json.get('choque'), 'misma mesa a menos de 2 h -> aviso de choque')
r = clientes['brayan'].post('/api/reservaciones', json={'nombre': 'Otro', 'fecha': fecha_media, 'hora': media, 'mesa': 'M5', 'forzar': True}, headers=HJ)
R2 = r.json['reservacion']['id']
check(r.status_code == 200, 'con forzar se guarda a pesar del choque')
clientes['brayan'].post(f'/api/reservaciones/{R2}', json={'estado': 'CANCELADA'}, headers=HJ)
ayer = (_ahora() - _td(days=1)).strftime('%Y-%m-%d')
check(clientes['brayan'].post('/api/reservaciones', json={'nombre': 'Tarde', 'fecha': ayer, 'hora': '12:00'}, headers=HJ).status_code == 400,
      'no se reserva en el pasado')
lista = clientes['brayan'].get('/api/reservaciones?fecha=' + F).json['reservaciones']
check(any(x['id'] == R1 and x['notas'] == 'cumpleaños' for x in lista), 'agenda del día')
check(all(x['id'] != R1 for x in cam1.get('/api/reservaciones?fecha=' + F).json['reservaciones']), 'otra sucursal no ve la agenda')
tarj = {t['codigo']: t for t in admin.get('/api/pos/mesas_tablet_v2').json['tarjetas']}
check('Familia López' in tarj['M5'].get('reserva', ''), f"tablet marca la mesa M5 como reservada ({tarj['M5'].get('reserva')})")
check(cam1.post(f'/api/reservaciones/{R1}', json={'estado': 'CONFIRMADA'}, headers={'X-CSRFToken': token_de(cam1.get('/pedidos_sucursal').get_data(as_text=True))}).status_code == 403,
      'otra sucursal no modifica la reservación')
check(clientes['brayan'].post(f'/api/reservaciones/{R1}', json={'estado': 'CONFIRMADA'}, headers=HJ).json['reservacion']['estado'] == 'CONFIRMADA',
      'confirmar')
r = clientes['brayan'].post(f'/api/reservaciones/{R1}', json={'estado': 'LLEGO'}, headers=HJ)
with app.app_context():
    cta = CuentaPOS.query.get(r.json.get('cuenta_id')) if r.status_code == 200 else None
    check(cta is not None and cta.mesa == 'M5' and cta.personas == 6 and 'RESERVA: Familia López' in (cta.observaciones or ''),
          'LLEGÓ abre la mesa reservada con sus personas y nota')
check(clientes['brayan'].post(f'/api/reservaciones/{R1}', json={'estado': 'CANCELADA'}, headers=HJ).status_code == 409,
      'una reservación que ya llegó no se cancela')
r = clientes['brayan'].post('/api/reservaciones', json={'nombre': 'Sin mesa', 'fecha': F, 'hora': HR}, headers=HJ)
R3 = r.json['reservacion']['id']
check(clientes['brayan'].post(f'/api/reservaciones/{R3}', json={'estado': 'LLEGO'}, headers=HJ).status_code == 400, 'LLEGÓ sin mesa pide asignarla')
clientes['brayan'].post(f'/api/reservaciones/{R3}', json={'mesa': 'M5', 'forzar': True}, headers=HJ)
r = clientes['brayan'].post(f'/api/reservaciones/{R3}', json={'estado': 'LLEGO'}, headers=HJ)
check(r.status_code == 200 and r.json['cuenta_id'] == cta.id, 'si la mesa ya está abierta, se liga a esa cuenta')
check('Agenda del día' in clientes['brayan'].get('/reservaciones').get_data(as_text=True), 'pantalla /reservaciones')
with app.app_context():
    check(Reservacion.query.count() >= 3 and esquema_faltante(db.engine) == [], 'tablas de la Fase 4a en ESQUEMA_REQUERIDO y creadas')
