# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, clientes, H, tcj, check, token_de, db).
from datetime import timedelta as _td
from models import ColaImpresionPOS, ahora_local as _ahora, esquema_faltante, inicializar_sistema

cj = clientes['brayan']
HJ = {'X-CSRFToken': tcj}
MATRIZ, C1 = 'Quiosco Morisco (Matriz)', 'Caminante 1'

def _reclamar(cli, hdr, disp='PC-A'):
    return cli.post('/api/pos/cola_impresion/reclamar', json={'dispositivo': disp}, headers=hdr)

def _ack(cli, hdr, ids):
    return cli.post('/api/pos/cola_impresion/ack', json={'ids': ids}, headers=hdr)

# Vaciar lo que dejaron los pasos anteriores (comandas de la prueba de humo)
_prev = _reclamar(cj, HJ).json['tickets']
if _prev:
    _ack(cj, HJ, [t['id'] for t in _prev])

with app.app_context():
    t1 = ColaImpresionPOS(sucursal=MATRIZ, tipo='COMANDA_COCINA', contenido_html='<p>T1</p>')
    t2 = ColaImpresionPOS(sucursal=MATRIZ, tipo='COMANDA_BARRA', contenido_html='<p>T2</p>')
    tc1 = ColaImpresionPOS(sucursal=C1, tipo='COMANDA_COCINA', contenido_html='<p>C1</p>')
    db.session.add_all([t1, t2, tc1]); db.session.commit()
    id1, id2, idc1 = t1.id, t2.id, tc1.id
    check(t1.estado == 'PENDIENTE' and t1.impreso is False, 'ticket nuevo nace PENDIENTE')

# Reclamar
r = _reclamar(cj, HJ, 'PC-CAJA')
ids = [t['id'] for t in r.json['tickets']]
check(r.status_code == 200 and ids == [id1, id2] and r.json['tickets'][0]['html'] == '<p>T1</p>',
      f'reclamar entrega los pendientes de su sucursal en orden: {ids}')
with app.app_context():
    t = ColaImpresionPOS.query.get(id1)
    check(t.estado == 'EN_PROCESO' and t.reclamado_por == 'PC-CAJA' and t.impreso is False, 'reclamados quedan EN_PROCESO (no impreso)')
    check(ColaImpresionPOS.query.get(idc1).estado == 'PENDIENTE', 'ticket de otra sucursal no se toca')
r = _reclamar(admin, H, 'PC-OTRA')
check([t['id'] for t in r.json['tickets']] == [], 'otra PC no recibe tickets ya reclamados (sin duplicados)')

# ACK idempotente
r1 = _ack(cj, HJ, [id1, id2])
r2 = _ack(cj, HJ, [id1, id2])
with app.app_context():
    a, b = ColaImpresionPOS.query.get(id1), ColaImpresionPOS.query.get(id2)
    check(r1.json['confirmados'] == 2 and r2.status_code == 200 and r2.json['ok']
          and a.estado == b.estado == 'IMPRESO' and a.impreso and b.impreso, 'ack marca IMPRESO + impreso=True y repetirlo no falla')
r = _ack(cj, HJ, [idc1])
with app.app_context():
    check(r.json['confirmados'] == 0 and ColaImpresionPOS.query.get(idc1).estado == 'PENDIENTE', 'ack no toca tickets de otra sucursal')
check(_ack(cj, HJ, ['x']).status_code == 400, 'ack con ids inválidos -> 400')
check(_reclamar(cj, HJ).json['tickets'] == [], 'impresos ya no se vuelven a entregar')

# Reintento tras 150 s sin ACK
with app.app_context():
    t3 = ColaImpresionPOS(sucursal=MATRIZ, tipo='COMANDA_COCINA', contenido_html='<p>T3</p>')
    db.session.add(t3); db.session.commit(); id3 = t3.id
check([t['id'] for t in _reclamar(cj, HJ, 'PC-CAJA').json['tickets']] == [id3], 'reclama T3')
with app.app_context():
    ColaImpresionPOS.query.get(id3).reclamado_en = _ahora() - _td(seconds=149); db.session.commit()
check(_reclamar(admin, H, 'PC-OTRA').json['tickets'] == [], 'a los 149 s sin ACK todavía no se reintenta')
with app.app_context():
    ColaImpresionPOS.query.get(id3).reclamado_en = _ahora() - _td(seconds=151); db.session.commit()
r = _reclamar(admin, H, 'PC-OTRA')
with app.app_context():
    t = ColaImpresionPOS.query.get(id3)
    check([x['id'] for x in r.json['tickets']] == [id3] and t.reclamado_por == 'PC-OTRA', 'a los 151 s sin ACK otra PC lo reimprime')
_ack(admin, H, [id3])

# Seguridad y compatibilidad
check(cj.post('/api/pos/cola_impresion/reclamar', json={}).status_code == 400, 'reclamar sin token CSRF -> 400')
check(clientes['paola'].post('/api/pos/cola_impresion/reclamar', json={},
      headers={'X-CSRFToken': token_de(clientes['paola'].get('/mesero_dashboard').get_data(as_text=True))}).json['tickets'] == [],
      'mesero no reclama tickets')
with app.app_context():
    t4 = ColaImpresionPOS(sucursal=MATRIZ, tipo='COMANDA_COCINA', contenido_html='<p>T4</p>')
    db.session.add(t4); db.session.commit(); id4 = t4.id
r = cj.get('/api/pos/cola_impresion')
with app.app_context():
    check(r.json.get('tickets') == [] and ColaImpresionPOS.query.get(id4).estado == 'PENDIENTE',
          'GET viejo ya no entrega ni marca nada (pestañas sin recargar)')
_ack(cj, HJ, [x['id'] for x in _reclamar(cj, HJ).json['tickets']])
html_pos = admin.get('/pos').get_data(as_text=True)
check('/api/pos/cola_impresion/reclamar' in html_pos and '/api/pos/cola_impresion/ack' in html_pos, 'pos_soft usa reclamar + ack')

# Migración: viejos impreso=TRUE -> IMPRESO; repetir la migración es seguro
with app.app_context():
    viejo_imp = ColaImpresionPOS(sucursal=MATRIZ, tipo='X', contenido_html='v', impreso=True, estado='PENDIENTE')
    viejo_pen = ColaImpresionPOS(sucursal=MATRIZ, tipo='X', contenido_html='p', impreso=False, estado='PENDIENTE')
    db.session.add_all([viejo_imp, viejo_pen]); db.session.commit()
    vi, vp = viejo_imp.id, viejo_pen.id
inicializar_sistema(app)
inicializar_sistema(app)
with app.app_context():
    check(ColaImpresionPOS.query.get(vi).estado == 'IMPRESO' and ColaImpresionPOS.query.get(vp).estado == 'PENDIENTE',
          'migración: impresos viejos -> IMPRESO, pendientes siguen PENDIENTE (idempotente)')
    ColaImpresionPOS.query.get(vp).estado = 'IMPRESO'; ColaImpresionPOS.query.get(vp).impreso = True; db.session.commit()
    check(esquema_faltante(db.engine) == [], 'ESQUEMA_REQUERIDO completo en la base de prueba')
