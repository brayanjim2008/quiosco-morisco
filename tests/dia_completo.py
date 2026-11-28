"""Simulación de un día real completo en una base TEMPORAL (nunca la real).
Roles: admin (raquel), almacén, sucursal Caminante 1, cajero (brayan), meseros (paola, daniel), cliente público."""
import os, re, sys, tempfile, json
PROY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(tempfile.mkdtemp(), 'dia.db').replace(os.sep, '/')
os.environ.update(SECRET_KEY='dia', RUN_DB_INIT='1', PASS_INICIAL_RAQUEL='admin12345', PASS_INICIAL_BRAYAN='cajero12345',
                  PASS_INICIAL_PAOLA='mesero12345', PASS_INICIAL_DANIEL='mesero12345', PASS_INICIAL_ALMACEN='almacen12345',
                  PASS_INICIAL_QUIOSCO='sucursal12345', PASS_INICIAL_GERENTE='gerente12345', PASS_INICIAL_CAMINANTE1='caminante12345')
sys.path.insert(0, PROY); os.chdir(PROY)
import app as appmod
from models import StockSucursal, InsumoBodegaPro, CuentaPOS, DetallePOS
app = appmod.app
MATRIZ, C1 = 'Quiosco Morisco (Matriz)', 'Caminante 1'
fallos, hallazgos = [], []

def check(c, m):
    print(('OK   ' if c else 'FALLO') + ' ' + m)
    if not c: fallos.append(m)

def nota(m):
    print('NOTA ' + m); hallazgos.append(m)

def tok(html):
    m = re.search(r'name="csrf-token" content="([^"]+)"', html); return m.group(1) if m else None

def login(u, p, pagina):
    c = app.test_client(); c.get('/admin_login')
    r = c.post('/admin_login', data={'username': u, 'password': p})
    check(r.status_code == 302, f'{u} entra')
    r = c.get(pagina); check(r.status_code == 200, f'{u} abre {pagina}')
    c.H = {'X-CSRFToken': tok(r.get_data(as_text=True))}
    return c

def J(r):
    try: return r.json or {}
    except Exception: return {}

def st(suc, iid):
    with app.app_context():
        s = StockSucursal.query.filter_by(sucursal=suc, insumo_id=iid).first(); return round(s.stock_actual, 4) if s else None

def bod(iid):
    with app.app_context(): return round(InsumoBodegaPro.query.get(iid).stock_actual, 4)

admin = login('raquel', 'admin12345', '/admin_dashboard')
alm = login('almacen', 'almacen12345', '/almacen_pro')
cam1 = login('caminante1', 'caminante12345', '/pedidos_sucursal')
caja = login('brayan', 'cajero12345', '/pos')
paola = login('paola', 'mesero12345', '/mesero_dashboard')
daniel = login('daniel', 'mesero12345', '/mesero_dashboard')

print('\n===== 1. ADMIN prepara el menú (7:00) =====')
r = admin.post('/api/menu/categoria', data={'nombre': 'Cafés', 'icono': '☕'}, headers=admin.H); check(J(r).get('ok'), 'categoría Cafés')
r = admin.post('/api/menu/categoria', data={'nombre': 'Hamburguesas', 'icono': '🍔'}, headers=admin.H); check(J(r).get('ok'), 'categoría Hamburguesas')
plat = {}
for nom, cat, pre, area in [('Americano Dia', 'Cafés', 45, 'BARRA'), ('Latte Dia', 'Cafés', 60, 'BARRA'),
                            ('Hamburguesa Dia', 'Hamburguesas', 120, 'COCINA')]:
    r = admin.post('/api/menu/platillo', data={'nombre': nom, 'categoria': cat, 'precio': str(pre), 'area': area}, headers=admin.H)
    check(J(r).get('ok'), f'platillo {nom} ${pre} → {area}'); plat[nom] = J(r).get('id')
r = admin.post('/api/menu/platillo/%d/pasos' % plat['Latte Dia'], json={'pasos': [{'grupo': 'TIPO DE LECHE', 'obligatorio': False, 'max_seleccion': 1}]}, headers=admin.H)
check(r.status_code == 200, 'Latte pregunta tipo de leche')
r = admin.post('/api/pos/precios_sucursal', json={'sucursal': C1, 'producto_id': plat['Latte Dia'], 'precio': 55}, headers=admin.H)
check(r.status_code == 200, 'Latte en Caminante 1 cuesta $55')

# insumos con alta de almacén
ins = {}
for nom, cat, uni, costo in [('CAFE GRANO DIA', 'BARRA | Insumos', 'KG', 300), ('LECHE ENTERA DIA', 'BARRA | Insumos', 'LT', 22),
                             ('LECHE AVENA DIA', 'BARRA | Insumos', 'LT', 60), ('PAN HAMBURGUESA DIA', 'COCINA | Insumos', 'PZA', 6),
                             ('CARNE RES DIA', 'COCINA | Insumos', 'KG', 180)]:
    r = alm.post('/api/almacen/insumo', json={'nombre': nom, 'categoria': cat, 'unidad': uni, 'costo_unitario': costo, 'stock_minimo': 1}, headers=alm.H)
    if not J(r).get('ok'):
        r = admin.post('/api/almacen/insumo', json={'nombre': nom, 'categoria': cat, 'unidad': uni, 'costo_unitario': costo, 'stock_minimo': 1}, headers=admin.H)
    check(J(r).get('ok'), f'alta insumo {nom} ({r.status_code} {r.get_data(as_text=True)[:80]})')
with app.app_context():
    for i in InsumoBodegaPro.query.filter(InsumoBodegaPro.nombre.like('%DIA')).all(): ins[i.nombre] = i.id
CAFE, LECHE, AVENA, PAN, CARNE = (ins.get(k) for k in ['CAFE GRANO DIA', 'LECHE ENTERA DIA', 'LECHE AVENA DIA', 'PAN HAMBURGUESA DIA', 'CARNE RES DIA'])

for p, lineas in [('Americano Dia', [(CAFE, 0.018)]), ('Latte Dia', [(CAFE, 0.018), (LECHE, 0.25)]),
                  ('Hamburguesa Dia', [(PAN, 1), (CARNE, 0.15)])]:
    r = admin.post('/api/menu/receta', json={'producto_id': plat[p], 'lineas': [{'insumo_id': a, 'cantidad': b} for a, b in lineas]}, headers=admin.H)
    check(J(r).get('ok'), f'receta {p}')
d = J(admin.get('/api/menu/datos'))
avena = next((m for m in d.get('grupos', {}).get('TIPO DE LECHE', []) if 'AVENA' in m.get('nombre', '')), None)
if avena:
    r = admin.post('/api/menu/receta', json={'modificador_id': avena['id'], 'lineas': [{'insumo_id': AVENA, 'cantidad': 0.25}]}, headers=admin.H)
    check(J(r).get('ok'), f'receta del modificador {avena["nombre"]} (${avena.get("precio")})')
else:
    nota('no encontré LECHE DE AVENA en /api/menu/datos grupos: ' + json.dumps(d.get('grupos', [])[:1])[:300])
lp = next(p for p in d['platillos'] if p['id'] == plat['Latte Dia'])
print('   costo Latte según receta:', lp.get('costo'), lp.get('margen'), {k: lp[k] for k in lp if 'cost' in k or 'marg' in k})

print('\n===== 2. ALMACÉN recibe compra (8:00) =====')
for iid, cant in [(CAFE, 5), (LECHE, 40), (AVENA, 10), (PAN, 100), (CARNE, 15)]:
    r = alm.post('/api/almacen/movimiento', json={'insumo_id': iid, 'tipo': 'ENTRADA_COMPRA', 'cantidad': cant, 'costo_unitario': None, 'nota': 'compra día'}, headers=alm.H)
    check(r.status_code == 200, f'entrada compra insumo {iid} x{cant} ({r.status_code} {r.get_data(as_text=True)[:80]})')
print('   bodega café/leche/pan:', bod(CAFE), bod(LECHE), bod(PAN))

print('\n===== 3. SUCURSALES piden a bodega y reciben (8:30) =====')
for cli, suc, pedido in [(cam1, C1, [(CAFE, 1), (LECHE, 10), (PAN, 20), (CARNE, 3)]),
                         (admin, MATRIZ, [(CAFE, 2), (LECHE, 15), (AVENA, 4), (PAN, 40), (CARNE, 6)])]:
    r = cli.post('/api/almacen/solicitar_lote', json={'sucursal': suc, 'items': [{'insumo_id': a, 'cantidad': b} for a, b in pedido]}, headers=cli.H)
    check(J(r).get('ok'), f'{suc} pide {len(pedido)} insumos a bodega ({r.get_data(as_text=True)[:80]})')
r = alm.post('/api/almacen/estado_bodega', json={'todos_entregados': True, 'sucursal': 'TODAS'}, headers=alm.H)
check(J(r).get('ok') and not J(r).get('sin_stock'), f'bodega entrega todo ({J(r)})')
from models import RequerimientoBodega
with app.app_context():
    reqs = [(x.id, x.sucursal, x.insumo_id, x.cantidad) for x in RequerimientoBodega.query.all()]
for rid, suc, iid, cant in reqs:
    cli = cam1 if suc == C1 else admin
    recib = cant - 1 if (suc == C1 and iid == PAN) else cant  # Caminante 1 recibe 1 pan menos (llegó aplastado)
    r = cli.post('/api/almacen/confirmar_caja', json={'id': rid, 'recibido': True, 'cantidad_recibida': recib}, headers=cli.H)
    check(r.status_code == 200, f'{suc} confirma recepción insumo {iid}: {recib} ({r.get_data(as_text=True)[:80]})')
check(st(C1, PAN) == 19 and bod(PAN) == 100 - 60 + 1, f'pan: Caminante 1 tiene 19, el faltante regresa a bodega ({st(C1, PAN)}, bodega {bod(PAN)})')
check(st(MATRIZ, LECHE) == 15, f'Matriz tiene 15 lt de leche ({st(MATRIZ, LECHE)})')
st0 = {k: st(MATRIZ, v) for k, v in [('cafe', CAFE), ('leche', LECHE), ('avena', AVENA), ('pan', PAN), ('carne', CARNE)]}
st0c1 = {k: st(C1, v) for k, v in [('cafe', CAFE), ('leche', LECHE), ('pan', PAN), ('carne', CARNE)]}

print('\n===== 4. CAJERO abre turno (9:00) =====')
r = caja.post('/api/pos/abrir_mesa', json={'mesa': '1', 'personas': 2}, headers=caja.H)
check(r.status_code == 409, 'sin turno no deja abrir mesa')
r = paola.post('/api/pos/abrir_turno_real', json={'fondo_inicial': 500}, headers=paola.H)
check(r.status_code in (403, 400), f'una mesera no puede abrir la caja ({r.status_code})')
r = caja.post('/api/pos/abrir_turno_real', json={'fondo_inicial': 500}, headers=caja.H)
check(J(r).get('ok'), f'cajero abre turno con $500 ({r.get_data(as_text=True)[:80]})')
r = cam1.post('/api/pos/abrir_turno_real', json={'fondo_inicial': 300}, headers=cam1.H)
check(J(r).get('ok'), 'Caminante 1 abre su turno con $300')

print('\n===== 5. MESEROS toman comandas (10:00) =====')
r = paola.post('/api/pos/abrir_mesa', json={'mesa': '5', 'personas': 3}, headers=paola.H)
check(J(r).get('ok'), f'Paola abre mesa 5 ({r.get_data(as_text=True)[:100]})')
with app.app_context():
    m5 = CuentaPOS.query.filter_by(mesa='5', estado='ABIERTA').first().id
    print('   mesa 5 mesero:', CuentaPOS.query.get(m5).mesero)
ronda = [{'descripcion': 'Latte Dia', 'precio': 1, 'cantidad': 2, 'clave': f'0{plat["Latte Dia"]}', 'categoria': 'Cafés', 'area_impresion': 'BARRA',
          'modificadores': [{'nombre': avena['nombre'] if avena else 'LECHE DE AVENA', 'precio': 0, 'cantidad': 1}]},
         {'descripcion': 'Hamburguesa Dia', 'precio': 120, 'cantidad': 1, 'clave': f'0{plat["Hamburguesa Dia"]}', 'categoria': 'Hamburguesas',
          'area_impresion': 'COCINA', 'comentario': 'sin cebolla', 'modificadores': [{'nombre': 'TERMINO MEDIO', 'precio': 0}]},
         {'descripcion': 'Americano Dia', 'precio': 45, 'cantidad': 1, 'clave': f'0{plat["Americano Dia"]}', 'categoria': 'Cafés', 'area_impresion': 'BARRA'}]
r = paola.post('/api/pos/enviar_ronda_lote', json={'cuenta_id': m5, 'items': ronda}, headers=paola.H)
check(J(r).get('ok'), f'Paola manda ronda ({r.get_data(as_text=True)[:100]})')
det = J(paola.get(f'/api/pos/detalle_cuenta/{m5}'))
total5 = float(det.get('total') or det.get('cuenta', {}).get('total') or 0)
print('   total mesa 5:', total5)
esperado = 2 * 60 + 2 * (avena.get('precio', 0) if avena else 0) * 1 + 120 + 45
check(abs(total5 - esperado) < 0.01, f'precio corregido por el servidor (latte mandado a $1): {total5} vs {esperado}')
from models import ColaImpresionPOS
with app.app_context():
    tipos = sorted(set((t.tipo) for t in ColaImpresionPOS.query.filter_by(sucursal=MATRIZ).all()))
    hb = [t.contenido_html for t in ColaImpresionPOS.query.filter_by(sucursal=MATRIZ, tipo='COMANDA_BARRA').all()]
    hc = [t.contenido_html for t in ColaImpresionPOS.query.filter_by(sucursal=MATRIZ, tipo='COMANDA_COCINA').all()]
check('COMANDA_BARRA' in tipos and 'COMANDA_COCINA' in tipos, f'la comanda se divide en barra y cocina ({tipos})')
check(any('LATTE' in h and 'AVENA' in h for h in hb) and not any('HAMBURGUESA' in h for h in hb), 'barra: lattes con avena, sin hamburguesa')
check(any('HAMBURGUESA' in h and 'SIN CEBOLLA' in h for h in hc) and not any('LATTE' in h for h in hc), 'cocina: hamburguesa con nota sin cebolla, sin cafés')
r = daniel.get(f'/api/pos/detalle_cuenta/{m5}')
check(r.status_code == 403, f'Daniel no ve la mesa de Paola ({r.status_code})')
r = daniel.post('/api/pos/abrir_mesa', json={'mesa': '8', 'personas': 2}, headers=daniel.H)
with app.app_context():
    m8 = CuentaPOS.query.filter_by(mesa='8', estado='ABIERTA').first().id
r = daniel.post('/api/pos/enviar_ronda_lote', json={'cuenta_id': m8, 'items': [
    {'descripcion': 'Hamburguesa Dia', 'precio': 120, 'cantidad': 2, 'clave': f'0{plat["Hamburguesa Dia"]}', 'categoria': 'Hamburguesas'},
    {'descripcion': 'Americano Dia', 'precio': 45, 'cantidad': 2, 'clave': f'0{plat["Americano Dia"]}', 'categoria': 'Cafés'}]}, headers=daniel.H)
check(J(r).get('ok'), 'Daniel manda ronda en mesa 8')
# cancelar 1 americano: mesero sin clave no puede
with app.app_context():
    am8 = DetallePOS.query.filter_by(cuenta_id=m8, descripcion='AMERICANO DIA').first().id
r = daniel.post('/api/pos/cancelar_items_lote', json={'cuenta_id': m8, 'items': [{'id': am8, 'cantidad': 1}]}, headers=daniel.H)
check(r.status_code in (400, 403), f'mesero no cancela sin clave ({r.status_code})')
r = daniel.post('/api/pos/cancelar_items_lote', json={'cuenta_id': m8, 'items': [{'id': am8, 'cantidad': 1}], 'clave_admin': 'admin12345', 'motivo_general': 'se equivocó'}, headers=daniel.H)
check(r.status_code == 200, f'con clave de admin sí cancela 1 americano ({r.get_data(as_text=True)[:100]})')
r = daniel.get('/api/pos/mi_venta'); print('   mi venta Daniel:', str(J(r))[:200])

print('\n===== 6. CLIENTE pide desde el QR (11:00) =====')
pub = app.test_client()
r = pub.post('/crear_preorden', json={'mesa': '3', 'cliente_nombre': 'Ana', 'detalle_items': '1x Americano Dia', 'total': 45, 'suc': 'C1'})
check(J(r).get('ok'), 'pre-orden desde el celular de una mesa de Caminante 1')
from models import PreOrden
with app.app_context():
    po = PreOrden.query.order_by(PreOrden.id.desc()).first().id
check(caja.post(f'/api/pos/confirmar_preorden_1clic/{po}', json={}, headers=caja.H).status_code == 403, 'la caja de la Matriz no puede tomar la pre-orden de Caminante 1')
r = cam1.post(f'/api/pos/confirmar_preorden_1clic/{po}', json={}, headers=cam1.H)
check(r.status_code == 200, f'Caminante 1 confirma la pre-orden en 1 clic ({r.get_data(as_text=True)[:100]})')
with app.app_context():
    _cpo = CuentaPOS.query.get(J(r).get('cuenta_id'))
    check(_cpo is not None and _cpo.sucursal == C1, 'la cuenta de la pre-orden se abre en Caminante 1')

print('\n===== 7. COBRAR (13:00) =====')
r = paola.post(f'/api/pos/solicitar_cuenta/{m5}', json={}, headers=paola.H); check(r.status_code == 200, 'Paola pide la cuenta')
r = caja.post(f'/api/pos/pin_inteligente/{m5}', json={}, headers=caja.H); check(r.status_code == 200, 'cajero imprime precuenta')
r = paola.post('/api/pos/enviar_ronda_lote', json={'cuenta_id': m5, 'items': ronda[2:]}, headers=paola.H)
check(r.status_code == 400, 'cuenta impresa: ya no se agregan cosas sin reabrir')
r = caja.post('/api/pos/pagar_cuenta', json={'cuenta_id': m5, 'efectivo': 200, 'tarjeta_debito': total5 - 200, 'propina': 30, 'idem': 'm5'}, headers=caja.H)
check(J(r).get('ok'), f'cobro mixto efectivo + tarjeta + $30 propina ({r.get_data(as_text=True)[:150]})')
r2 = caja.post('/api/pos/pagar_cuenta', json={'cuenta_id': m5, 'efectivo': 200, 'tarjeta_debito': total5 - 200, 'propina': 30, 'idem': 'm5'}, headers=caja.H)
print('   doble clic en cobrar:', r2.status_code, r2.get_data(as_text=True)[:100])
caja.post(f'/api/pos/pin_inteligente/{m8}', json={}, headers=caja.H)
det8 = J(caja.get(f'/api/pos/detalle_cuenta/{m8}')); total8 = float(det8.get('total') or det8.get('cuenta', {}).get('total') or 0)
check(abs(total8 - (240 + 45)) < 0.01, f'mesa 8 total tras cancelar 1 americano = 285 ({total8})')
r = caja.post('/api/pos/pagar_cuenta', json={'cuenta_id': m8, 'efectivo': 500}, headers=caja.H)
check(J(r).get('ok'), f'mesa 8 paga con $500 en efectivo ({r.get_data(as_text=True)[:150]})')
print('   cambio:', J(r).get('cambio'))

# Caminante 1 vende Latte a su precio
r = cam1.post('/api/pos/abrir_mesa', json={'mesa': 'P1', 'personas': 1}, headers=cam1.H)
with app.app_context():
    cp = CuentaPOS.query.filter_by(mesa='P1', estado='ABIERTA', sucursal=C1).first().id
cam1.post('/api/pos/enviar_ronda_lote', json={'cuenta_id': cp, 'items': [
    {'descripcion': 'Latte Dia', 'precio': 60, 'cantidad': 3, 'clave': f'0{plat["Latte Dia"]}', 'categoria': 'Cafés'},
    {'descripcion': 'Hamburguesa Dia', 'precio': 120, 'cantidad': 1, 'clave': f'0{plat["Hamburguesa Dia"]}', 'categoria': 'Hamburguesas'}]}, headers=cam1.H)
cam1.post(f'/api/pos/pin_inteligente/{cp}', json={}, headers=cam1.H)
dc = J(cam1.get(f'/api/pos/detalle_cuenta/{cp}')); tc1 = float(dc.get('total') or dc.get('cuenta', {}).get('total') or 0)
check(abs(tc1 - (3 * 55 + 120)) < 0.01, f'Caminante 1 cobra el Latte a $55 ({tc1})')
r = cam1.post('/api/pos/pagar_cuenta', json={'cuenta_id': cp, 'transferencia': tc1}, headers=cam1.H)
check(J(r).get('ok'), 'Caminante 1 cobra por transferencia')

print('\n===== 8. STOCK después de vender =====')
# Matriz: latte x2 (café .036, leche .5, avena .5 por 2 mods? -> mod cantidad 1 por latte), hamburguesas 1+2, americanos 1+1
exp = {'cafe': st0['cafe'] - (2 * 0.018 + 2 * 0.018), 'leche': st0['leche'] - 2 * 0.25, 'pan': st0['pan'] - 3, 'carne': st0['carne'] - 3 * 0.15}
for k, iid in [('cafe', CAFE), ('leche', LECHE), ('pan', PAN), ('carne', CARNE)]:
    check(abs(st(MATRIZ, iid) - exp[k]) < 0.0001, f'Matriz {k}: {st0[k]} → {st(MATRIZ, iid)} (esperado {round(exp[k], 4)})')
check(abs(st(MATRIZ, AVENA) - (st0['avena'] - 0.5)) < 1e-4, f"avena: 2 lattes con avena = 0.5 lt ({st0['avena']} → {st(MATRIZ, AVENA)})")
check(abs(st(C1, CAFE) - (st0c1['cafe'] - 3 * 0.018)) < 1e-4 and abs(st(C1, PAN) - (st0c1['pan'] - 1)) < 1e-4,
      f'Caminante 1 descontó lo suyo (café {st(C1, CAFE)}, pan {st(C1, PAN)})')

print('\n===== 9. MERMA, RETIRO, PROPINAS (17:00) =====')
r = cam1.post('/api/mermas/registrar', json={'insumo_nombre': 'LECHE ENTERA DIA', 'cantidad': 1, 'motivo': 'SE CORTÓ', 'unidad': 'LT', 'clave_admin': 'admin12345'}, headers=cam1.H)
check(J(r).get('ok'), f'merma de 1 lt de leche en Caminante 1 ({r.get_data(as_text=True)[:100]})')
print('   leche C1 tras merma:', st(C1, LECHE))
r = caja.post('/api/pos/movimiento_caja', json={'tipo': 'RETIRO', 'monto': 80, 'concepto': 'hielo', 'categoria': 'HIELO', 'clave_admin': 'admin12345'}, headers=caja.H)
check(J(r).get('ok'), f'retiro $80 de hielo ({r.get_data(as_text=True)[:100]})')
pr = J(caja.get('/api/propinas/dia'))
check(pr.get('tarjeta') == 30 and {'PAOLA', 'DANIEL'} <= set(pr.get('trabajaron', [])), f"propinas: $30 de tarjeta y Paola y Daniel ya marcados ({pr.get('tarjeta')}, {pr.get('trabajaron')})")
r = caja.post('/api/propinas/repartir', json={'efectivo': 90, 'empleados': pr.get('trabajaron', [])}, headers=caja.H)
check(J(r).get('ok'), f'reparto de propinas $30 tarjeta + $90 bote ({r.get_data(as_text=True)[:120]})')

print('\n===== 10. CORTE X y Z (22:00) =====')
x = J(caja.get('/api/pos/corte_caja'))
print('   corte X:', {k: x.get(k) for k in ['venta', 'efectivo', 'tarjeta', 'transferencia', 'retiros', 'fondo_inicial', 'efectivo_final', 'propina_tarjeta', 'propinas_pagadas', 'cuentas']})
ef_esperado = 500 + 200 + 285 - 80 - 30
print('   efectivo esperado en caja (fondo + ventas efectivo - retiro):', ef_esperado, '(propina tarjeta $30 aparte)')
r = caja.post('/api/pos/cerrar_turno_arqueo', json={'EF': ef_esperado, 'TARJD': total5 - 200, 'TARJC': 0, 'TRANS': 0, 'VAL': 0, 'clave_admin': 'admin12345'}, headers=caja.H)
z = J(r)
check(z.get('ok'), f'corte Z de la Matriz ({r.get_data(as_text=True)[:200]})')
print('   Z:', {k: z.get(k) for k in ['declarado', 'esperado', 'diferencia', 'venta', 'efectivo']})
r = caja.post('/api/pos/abrir_mesa', json={'mesa': '9'}, headers=caja.H)
check(r.status_code == 409, 'después del Z ya no se abren mesas')

print('\n===== 11. ADMIN revisa reportes (23:00) =====')
for u in ['/api/reportes/estado_resultados', '/api/reportes/platillos', '/api/industrial/resumen_general', '/api/industrial/cortes',
          '/api/mermas/resumen', '/api/industrial/reporte_ventas_detalle', '/api/exportar/ventas_detalle', '/api/exportar/cortes_caja']:
    r = admin.get(u); check(r.status_code == 200, f'admin abre {u} ({r.status_code})')
er = J(admin.get('/api/reportes/estado_resultados')); print('   estado de resultados nov:', [m for m in er.get('meses', []) if m['numero'] == 11], {k: v for k, v in er.items() if k != 'meses'})
rp = J(admin.get('/api/reportes/platillos')); print('   platillos:', str(rp)[:500])
for pag in ['/industrial', '/almacen_pro', '/nomina_creditos', '/pedidos_sucursal', '/platillos', '/pos', '/admin_dashboard', '/kds', '/reservaciones', '/guia']:
    r = admin.get(pag); check(r.status_code == 200, f'pantalla {pag}')

print('\n=====', 'FALLOS:', len(fallos)); [print(' -', f) for f in fallos]
print('NOTAS:'); [print(' -', h) for h in hallazgos]
print('RESULTADO: TODO OK' if not fallos else 'RESULTADO: HAY FALLOS')
sys.exit(1 if fallos else 0)
