"""Menú y Platillos: UNA sola pantalla para todo lo del platillo (datos, foto, inglés, impresora, modificadores
por pasos, precio por sucursal), las categorías (con su ícono) y el catálogo de modificadores.
Antes esto estaba repartido entre Administración y la Caja."""
import math

from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user

from models import (
    db, Producto, CategoriaMenu, ModificadorPOS, ProductoGrupoMod, RecetaPOS, PrecioSucursalPOS, PromocionPOS,
    SUCURSALES_OFICIALES, invalidar_cache_publico, registrar_bitacora, cfg_cargar, cfg_guardar,
)

menu_bp = Blueprint('menu', __name__)

AREAS = ('COCINA', 'BARRA')
CLAVE_AREAS = 'config_areas_productos.json'      # misma configuración que usa la Caja
CLAVE_ASIG_MODS = 'config_mods_productos.json'


def _solo_admin():
    if not current_user.is_authenticated or current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo el administrador puede cambiar el menú.'}), 403
    return None


def _num(valor, maximo=100000.0):
    x = float(valor or 0)
    if not math.isfinite(x) or x < 0 or x > maximo:
        raise ValueError('Número fuera de rango')
    return round(x, 2)


def _texto(valor, largo):
    return str(valor or '').strip()[:largo]


def _areas():
    a = cfg_cargar(CLAVE_AREAS, {})
    return a if isinstance(a, dict) else {}


def _clave_nombre(nombre):
    return (nombre or '').strip().upper()


def _pasos_de(nombre):
    return ProductoGrupoMod.query.filter_by(platillo_nombre=_clave_nombre(nombre)).order_by(
        ProductoGrupoMod.orden.asc(), ProductoGrupoMod.id.asc()).all()


def _platillo_json(p, areas, precios, pasos):
    return {
        'id': p.id, 'nombre': p.nombre, 'nombre_en': p.nombre_en or '', 'descripcion': p.descripcion or '',
        'descripcion_en': p.descripcion_en or '', 'precio': float(p.precio or 0), 'categoria': p.categoria,
        'imagen_url': p.imagen_url or '', 'destacado': bool(p.destacado), 'agotado': bool(p.agotado),
        'area': areas.get(str(p.id), ''),
        'precios': precios.get(p.id, {}),
        'pasos': [{'grupo': f.grupo, 'etiqueta': f.etiqueta, 'obligatorio': bool(f.obligatorio),
                   'max_seleccion': int(f.max_seleccion or 0)} for f in pasos.get(_clave_nombre(p.nombre), [])],
    }


@menu_bp.route('/platillos')
@login_required
def vista_platillos():
    if current_user.role != 'admin':
        return redirect(url_for('admin_login'))
    from app import ICONOS_CATEGORIA
    return render_template('platillos.html', sucursales=SUCURSALES_OFICIALES, iconos=ICONOS_CATEGORIA)


@menu_bp.route('/api/menu/datos')
@login_required
def api_menu_datos():
    err = _solo_admin()
    if err:
        return err
    areas = _areas()
    precios = {}
    for r in PrecioSucursalPOS.query.all():
        precios.setdefault(r.producto_id, {})[r.sucursal] = {
            'precio': r.precio, 'disponible': r.disponible is not False}
    pasos = {}
    for f in ProductoGrupoMod.query.order_by(ProductoGrupoMod.orden.asc(), ProductoGrupoMod.id.asc()).all():
        pasos.setdefault(_clave_nombre(f.platillo_nombre), []).append(f)
    grupos = {}
    for m in ModificadorPOS.query.filter_by(activo=True).order_by(ModificadorPOS.grupo.asc(), ModificadorPOS.nombre.asc()).all():
        grupos.setdefault(m.grupo or 'SIN GRUPO', []).append({
            'id': m.id, 'clave': m.clave, 'nombre': m.nombre, 'precio': float(m.precio or 0), 'area': m.area_impresion or ''})
    cats = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    cuenta = {}
    for p in Producto.query.all():
        cuenta[p.categoria] = cuenta.get(p.categoria, 0) + 1
    return jsonify({
        'ok': True,
        'platillos': [_platillo_json(p, areas, precios, pasos)
                      for p in Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all()],
        'categorias': [{'id': c.id, 'nombre': c.nombre, 'nombre_en': c.nombre_en or '', 'icono': c.icono or '',
                        'imagen_url': c.imagen_url or '', 'platillos': cuenta.get(c.nombre, 0)} for c in cats],
        'grupos': grupos,
        'sucursales': SUCURSALES_OFICIALES,
    })


def _renombrar_referencias(viejo, nuevo):
    """Al cambiar el nombre del platillo, sus pasos de modificadores, su receta y sus promociones lo siguen."""
    v, n = _clave_nombre(viejo), _clave_nombre(nuevo)
    if not v or v == n:
        return
    ProductoGrupoMod.query.filter_by(platillo_nombre=v).update({'platillo_nombre': n}, synchronize_session=False)
    for r in RecetaPOS.query.all():
        if _clave_nombre(r.platillo_nombre) == v:
            r.platillo_nombre = n
    for pr in PromocionPOS.query.filter_by(aplica_a='PRODUCTO').all():
        if _clave_nombre(pr.objetivo) == v:
            pr.objetivo = n


@menu_bp.route('/api/menu/platillo', methods=['POST'])
@login_required
def api_menu_guardar_platillo():
    """Crea o actualiza un platillo. Llega como formulario (puede traer foto)."""
    err = _solo_admin()
    if err:
        return err
    f = request.form
    nombre = _texto(f.get('nombre'), 100)
    categoria = _texto(f.get('categoria'), 50)
    if not nombre or not categoria:
        return jsonify({'ok': False, 'msg': 'Escribe el nombre y elige la categoría.'}), 400
    if not CategoriaMenu.query.filter_by(nombre=categoria).first():
        return jsonify({'ok': False, 'msg': 'Esa categoría no existe.'}), 400
    precio = _num(f.get('precio'))
    pid = int(f.get('id') or 0)
    repetido = next((x for x in Producto.query.all() if _clave_nombre(x.nombre) == _clave_nombre(nombre) and x.id != pid), None)
    if repetido:
        return jsonify({'ok': False, 'msg': f'Ya existe un platillo llamado "{repetido.nombre}".'}), 409
    if pid:
        p = Producto.query.get_or_404(pid)
        _renombrar_referencias(p.nombre, nombre)
        if abs(float(p.precio or 0) - precio) > 0.005:
            registrar_bitacora('CAMBIO_PRECIO', nombre, precio, f'${float(p.precio or 0):.2f} → ${precio:.2f}')
    else:
        p = Producto(nombre=nombre, precio=precio, categoria=categoria)
        db.session.add(p)
    p.nombre, p.precio, p.categoria = nombre, precio, categoria
    p.nombre_en = _texto(f.get('nombre_en'), 100)
    p.descripcion = _texto(f.get('descripcion'), 600)
    p.descripcion_en = _texto(f.get('descripcion_en'), 600)
    p.destacado = f.get('destacado') in ('1', 'true', 'on')
    p.agotado = f.get('agotado') in ('1', 'true', 'on')
    if f.get('quitar_foto') == '1':
        p.imagen_url = None
    aviso = ''
    foto = request.files.get('foto')
    if foto and foto.filename:
        from app import _subir_imagen   # misma validación y subida que el resto del sistema
        url = _subir_imagen(foto)
        if url:
            p.imagen_url = url
        else:
            aviso = ' La foto no se pudo subir (revisa el formato o la configuración de Cloudinary).'
    db.session.commit()
    areas = _areas()
    area = _texto(f.get('area'), 10).upper()
    if area in AREAS:
        areas[str(p.id)] = area
    else:
        areas.pop(str(p.id), None)
    cfg_guardar(CLAVE_AREAS, areas)
    invalidar_cache_publico()
    return jsonify({'ok': True, 'id': p.id, 'msg': 'Platillo guardado.' + aviso})


@menu_bp.route('/api/menu/platillo/<int:pid>/eliminar', methods=['POST'])
@login_required
def api_menu_eliminar_platillo(pid):
    err = _solo_admin()
    if err:
        return err
    p = Producto.query.get_or_404(pid)
    nombre = p.nombre
    PrecioSucursalPOS.query.filter_by(producto_id=p.id).delete(synchronize_session=False)
    ProductoGrupoMod.query.filter_by(platillo_nombre=_clave_nombre(nombre)).delete(synchronize_session=False)
    db.session.delete(p)
    db.session.commit()
    areas = _areas()
    if areas.pop(str(pid), None) is not None:
        cfg_guardar(CLAVE_AREAS, areas)
    invalidar_cache_publico()
    registrar_bitacora('ELIMINAR_PLATILLO', nombre, 0.0, 'Eliminado desde Menú y Platillos')
    return jsonify({'ok': True})


@menu_bp.route('/api/menu/platillo/<int:pid>/pasos', methods=['POST'])
@login_required
def api_menu_pasos(pid):
    """Lo que se pregunta al pedir el platillo, en orden (ej. 1. Tipo de leche, 2. Sabor, 3. Temperatura)."""
    err = _solo_admin()
    if err:
        return err
    p = Producto.query.get_or_404(pid)
    pasos = (request.get_json(silent=True) or {}).get('pasos') or []
    grupos_ok = {g for (g,) in db.session.query(ModificadorPOS.grupo).filter(ModificadorPOS.activo.is_(True)).distinct()}
    limpios = []
    for i, x in enumerate(pasos[:12], start=1):
        grupo = _texto((x or {}).get('grupo'), 50).upper()
        if grupo not in grupos_ok:
            return jsonify({'ok': False, 'msg': f'El grupo "{grupo}" no existe.'}), 400
        if any(l['grupo'] == grupo for l in limpios):
            return jsonify({'ok': False, 'msg': f'El grupo {grupo} está repetido.'}), 400
        etiqueta = _texto(x.get('etiqueta'), 70) or grupo.capitalize()
        limpios.append({'grupo': grupo, 'etiqueta': etiqueta, 'orden': i, 'obligatorio': bool(x.get('obligatorio')),
                        'max_seleccion': 1 if int(x.get('max_seleccion') or 0) == 1 else 0})
    clave = _clave_nombre(p.nombre)
    ProductoGrupoMod.query.filter_by(platillo_nombre=clave).delete(synchronize_session=False)
    for l in limpios:
        db.session.add(ProductoGrupoMod(platillo_nombre=clave, **l))
    db.session.commit()
    return jsonify({'ok': True})


@menu_bp.route('/api/menu/categoria', methods=['POST'])
@login_required
def api_menu_categoria():
    """Crea o edita una categoría (nombre, inglés, ícono y foto)."""
    err = _solo_admin()
    if err:
        return err
    f = request.form
    cid = int(f.get('id') or 0)
    nombre = _texto(f.get('nombre'), 50)
    if not nombre:
        return jsonify({'ok': False, 'msg': 'Escribe el nombre de la categoría.'}), 400
    otra = CategoriaMenu.query.filter_by(nombre=nombre).first()
    if otra and otra.id != cid:
        return jsonify({'ok': False, 'msg': 'Ya existe esa categoría.'}), 409
    if cid:
        c = CategoriaMenu.query.get_or_404(cid)
        if c.nombre != nombre:   # renombrar: sus platillos y asignaciones la siguen
            Producto.query.filter_by(categoria=c.nombre).update({'categoria': nombre}, synchronize_session=False)
            asig = cfg_cargar(CLAVE_ASIG_MODS, {})
            if isinstance(asig, dict):
                for reg in asig.values():
                    if isinstance(reg, dict) and reg.get('categorias'):
                        reg['categorias'] = [nombre.upper() if str(x).upper() == c.nombre.upper() else x for x in reg['categorias']]
                cfg_guardar(CLAVE_ASIG_MODS, asig)
            c.nombre = nombre
    else:
        c = CategoriaMenu(nombre=nombre)
        db.session.add(c)
    c.nombre_en = _texto(f.get('nombre_en'), 50)
    from app import ICONOS_CATEGORIA, _subir_imagen
    icono = _texto(f.get('icono'), 16)
    if icono == '' or icono in ICONOS_CATEGORIA:
        c.icono = icono or None
    if f.get('quitar_foto') == '1':
        c.imagen_url = None
    foto = request.files.get('foto')
    if foto and foto.filename:
        url = _subir_imagen(foto)
        if url:
            c.imagen_url = url
    db.session.commit()
    invalidar_cache_publico()
    return jsonify({'ok': True, 'id': c.id})


@menu_bp.route('/api/menu/categoria/<int:cid>/eliminar', methods=['POST'])
@login_required
def api_menu_eliminar_categoria(cid):
    err = _solo_admin()
    if err:
        return err
    c = CategoriaMenu.query.get_or_404(cid)
    if Producto.query.filter_by(categoria=c.nombre).first():
        return jsonify({'ok': False, 'msg': 'Primero mueve o elimina los platillos de esta categoría.'}), 409
    db.session.delete(c)
    db.session.commit()
    invalidar_cache_publico()
    return jsonify({'ok': True})


@menu_bp.route('/api/menu/modificador', methods=['POST'])
@login_required
def api_menu_modificador():
    """Crea o edita una opción de un grupo de modificadores (nombre, precio extra, impresora)."""
    err = _solo_admin()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    grupo = _texto(d.get('grupo'), 50).upper()
    nombre = _texto(d.get('nombre'), 100).upper().lstrip('>').strip()
    if not grupo or not nombre:
        return jsonify({'ok': False, 'msg': 'Escribe el grupo y el nombre.'}), 400
    precio = _num(d.get('precio'))
    area = _texto(d.get('area'), 10).upper()
    mid = int(d.get('id') or 0)
    otro = ModificadorPOS.query.filter_by(grupo=grupo, nombre=nombre).first()
    if otro and otro.id != mid:
        if otro.activo:
            return jsonify({'ok': False, 'msg': f'{nombre} ya está en {grupo}.'}), 409
        m = otro          # estaba apagado: se vuelve a usar
        m.activo = True
    elif mid:
        m = ModificadorPOS.query.get_or_404(mid)
        if m.nombre != nombre and not RecetaPOS.query.filter_by(platillo_nombre='>' + nombre).first():
            RecetaPOS.query.filter_by(platillo_nombre='>' + m.nombre).update(
                {'platillo_nombre': '>' + nombre}, synchronize_session=False)
    else:
        m = ModificadorPOS(clave=_texto(d.get('clave'), 20) or '03' + str(ModificadorPOS.query.count() + 100).zfill(3), activo=True)
        db.session.add(m)
    m.grupo, m.nombre, m.precio = grupo, nombre, precio
    m.area_impresion = area if area in AREAS else None
    if d.get('clave'):
        m.clave = _texto(d.get('clave'), 20)
    db.session.commit()
    return jsonify({'ok': True, 'id': m.id})


@menu_bp.route('/api/menu/modificador/<int:mid>/apagar', methods=['POST'])
@login_required
def api_menu_apagar_modificador(mid):
    """Se apaga (no se borra): hay ventas y recetas que lo mencionan."""
    err = _solo_admin()
    if err:
        return err
    m = ModificadorPOS.query.get_or_404(mid)
    m.activo = False
    db.session.commit()
    return jsonify({'ok': True})
