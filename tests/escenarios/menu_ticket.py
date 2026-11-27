# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, H, check, db).
# Nota de consumo como la del Soft, área de impresión del platillo, pre-orden con precio de la sucursal,
# menú del cliente por sucursal e ícono de categoría.
from models import (Producto as _ProdM, CategoriaMenu as _CatM, PrecioSucursalPOS as _PSM, DetallePOS as _DetM,
                    ColaImpresionPOS as _ColaM, CuentaPOS as _CtaM)

with app.app_context():
    _cat = _CatM(nombre='Postres Prueba')
    db.session.add(_cat)
    _p1 = _ProdM(nombre='Pay de Queso Prueba', precio=50.0, categoria='Postres Prueba', descripcion='')
    _p2 = _ProdM(nombre='Flan Solo Matriz', precio=40.0, categoria='Postres Prueba', descripcion='')
    db.session.add_all([_p1, _p2])
    db.session.commit()
    CAT, P1, P2 = _cat.id, _p1.id, _p2.id
    # Caminante 1 vende el pay más caro y no vende el flan
    db.session.add_all([_PSM(producto_id=P1, sucursal='Caminante 1', precio=65.0, disponible=True),
                        _PSM(producto_id=P2, sucursal='Caminante 1', precio=None, disponible=False)])
    db.session.commit()

# área de impresión desde "Editar platillo" (como en el Soft)
r = admin.post(f'/admin/producto/editar/{P1}', data={'nombre': 'Pay de Queso Prueba', 'descripcion': '', 'precio': '50',
                                                      'categoria': 'Postres Prueba', 'area_impresion': 'COCINA', 'csrf_token': H['X-CSRFToken']})
check(r.status_code == 302, f'guardar platillo con área de impresión ({r.status_code})')
check('value="COCINA" selected' in admin.get(f'/admin/producto/editar/{P1}').get_data(as_text=True), 'el platillo recuerda su área de impresión')

# menú del cliente por sucursal
html_c1 = app.test_client().get('/?suc=C1').get_data(as_text=True)
html_qm = app.test_client().get('/?suc=QM').get_data(as_text=True)
check('Pay de Queso Prueba' in html_c1 and 'data-precio="65.0"' in html_c1 and 'Flan Solo Matriz' not in html_c1,
      'el menú del cliente en Caminante 1 trae su precio y oculta lo que no vende')
check('Flan Solo Matriz' in html_qm and 'data-precio="50.0"' in html_qm, 'el menú de la Matriz sigue con su precio')

# pre-orden: precio de la sucursal y área elegida en el platillo (no la adivinada por categoría)
r = app.test_client().post('/crear_preorden', json={'suc': 'C1', 'mesa': '9', 'cliente_nombre': 'Luis',
                                                     'detalle_items': '2x Pay de Queso Prueba ($100)', 'total': 100})
_pre = r.json['folio']
r = admin.post(f'/api/pos/confirmar_preorden_1clic/{_pre}', json={}, headers=H)
check(r.status_code == 200, f'confirmar pre-orden en Caminante 1 ({r.status_code} {r.get_data(as_text=True)[:120]})')
with app.app_context():
    _d = _DetM.query.filter_by(cuenta_id=r.json['cuenta_id']).filter(_DetM.descripcion == 'PAY DE QUESO PRUEBA').first()
    check(_d is not None and _d.precio_unitario == 65.0 and _d.area_impresion == 'COCINA',
          f'pre-orden cobra el precio de la sucursal y va al área del platillo ({_d and (_d.precio_unitario, _d.area_impresion)})')
    check(_CtaM.query.get(r.json['cuenta_id']).total == 130.0, 'total de la pre-orden con precio de la sucursal')
    check(_ColaM.query.filter_by(sucursal='Caminante 1', tipo='COMANDA_COCINA').count() >= 1, 'la pre-orden manda su comanda a cocina')

# ícono de la categoría
r = admin.post(f'/admin/categoria/{CAT}/icono', data={'icono': '🍰', 'csrf_token': H['X-CSRFToken']})
check(r.status_code == 302, 'guardar ícono de categoría')
r = admin.post(f'/admin/categoria/{CAT}/icono', data={'icono': '<script>', 'csrf_token': H['X-CSRFToken']})
with app.app_context():
    check(_CatM.query.get(CAT).icono == '🍰', 'solo se aceptan íconos de la lista')
html_c1 = app.test_client().get('/?suc=C1').get_data(as_text=True)
check('<span class="sbux-cat-emoji">🍰</span>' in html_c1, 'el menú del cliente muestra el ícono elegido')
check('Cambiar ícono' in admin.get('/admin_dashboard').get_data(as_text=True), 'Administración tiene "Cambiar ícono"')

# nota de consumo como la del Soft: sin lista de productos ni QR; y cada ticket en su hoja (corte)
_pos = admin.get('/pos').get_data(as_text=True)
_i = _pos.index('function construirHTMLNotaFinal(')
_nota = _pos[_i:_pos.index('\n  }\n', _i)]
check('NOTA DE CONSUMO' in _nota and 'filasTicketItems' not in _nota and 'armarBloquePinHTML' not in _nota,
      'la nota de consumo no repite los productos ni el QR')
check('class=\\"tk-hoja\\"' in _pos or 'class="tk-hoja"' in _pos, 'cada ticket de la cola sale en su propia hoja')

# cobro como el Soft: formas de pago en botones grandes, teclado grande, Exacto/billetes, propina y ACEPTAR/CANCELAR
check(all(x in _pos for x in ('data-m="EF"', 'data-m="PROP"', 'pagoExacto()', 'pagoRapido(500)', 'class="key-enter"', 'ACEPTAR', 'CANCELAR')),
      'cobro con botones grandes como el Soft (formas de pago, Exacto, billetes, propina, ACEPTAR/CANCELAR)')
