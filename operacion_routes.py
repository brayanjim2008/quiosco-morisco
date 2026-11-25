import math
import csv
import urllib.parse
from io import StringIO
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, Response, session
from flask_login import login_required, current_user

from models import (
    db, ahora_local, inicio_hoy_local, SUCURSALES_OFICIALES,
    obtener_sucursal_activa, registrar_bitacora, sumar_stock_sucursal,
    Producto, ModificadorPOS, CuentaPOS, DetallePOS, BitacoraPOS, ArqueoTurnoPOS,
    InsumoBodegaPro, StockSucursal, RecetaPOS, RequerimientoBodega,
    MovimientoAlmacen, ProveedorAlmacen, RegistroAsistencia, RegistroMerma,
    EmpleadoNominaPOS, ConsumoEmpleadoPOS, ReciboNominaPOS
)

from models import aplicar_merma

operacion_bp = Blueprint('operacion', __name__)


def _num(valor, minimo=0.0, maximo=10_000_000.0):
    """Convierte a número finito dentro de rango; si no, lanza ValueError (la ruta responde 400)."""
    try:
        x = float(valor or 0)
    except (TypeError, ValueError):
        raise ValueError('Número inválido')
    if not math.isfinite(x) or x < minimo or x > maximo:
        raise ValueError('Número fuera de rango')
    return x


@operacion_bp.errorhandler(ValueError)
def _op_valor_invalido(e):
    db.session.rollback()
    return jsonify({'ok': False, 'msg': 'Dato numérico inválido o fuera de rango.'}), 400


@operacion_bp.errorhandler(KeyError)
def _op_dato_faltante(e):
    db.session.rollback()
    return jsonify({'ok': False, 'msg': f'Falta el dato requerido: {e}'}), 400


def _csv_excel(encabezados, filas, nombre_archivo):
    def generate():
        data = StringIO()
        data.write('\ufeff')  # BOM UTF-8 para acentos y ñ en Excel
        writer = csv.writer(data)
        writer.writerow(encabezados)
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for f in filas:
            writer.writerow(f)
            yield data.getvalue(); data.seek(0); data.truncate(0)
    resp = Response(generate(), mimetype='text/csv; charset=utf-8')
    resp.headers.set("Content-Disposition", "attachment", filename=nombre_archivo)
    return resp


# ==============================================================================
# 1. VISTAS PRINCIPALES (BODEGA CENTRAL, SUCURSALES, NÓMINA E INDUSTRIAL)
# ==============================================================================
@operacion_bp.route('/almacen_pro')
@login_required
def vista_almacen_pro():
    if current_user.role == 'sucursal':
        return redirect('/pedidos_sucursal')
    if current_user.role not in ['admin', 'almacen']:
        return redirect(url_for('admin_login'))
    return render_template('almacen_pro.html')


@operacion_bp.route('/pedidos_sucursal')
@login_required
def vista_pedidos_sucursal():
    if current_user.role == 'almacen':
        return redirect('/almacen_pro')
    if current_user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
    if current_user.role == 'cajero':
        return redirect(url_for('cajero_dashboard'))
    if current_user.role not in ['sucursal', 'admin']:
        return redirect(url_for('admin_login'))
    return render_template('pedidos_sucursal.html', sucursal=obtener_sucursal_activa(session))


@operacion_bp.route('/almacen/hoja_ruta_descarga')
@login_required
def almacen_hoja_ruta_descarga():
    if current_user.role not in ['admin', 'almacen']:
        return "Acceso denegado", 403
    sucursal_filtro = request.args.get('sucursal', 'TODAS')
    q = RequerimientoBodega.query.filter(RequerimientoBodega.fecha >= inicio_hoy_local())
    if sucursal_filtro != 'TODAS':
        q = q.filter_by(sucursal=sucursal_filtro)
    pedidos = q.order_by(RequerimientoBodega.sucursal.asc(), RequerimientoBodega.categoria.asc()).all()
    return render_template(
        'hoja_ruta_pdf.html',
        pedidos=pedidos, sucursal=sucursal_filtro,
        fecha=ahora_local().strftime('%d/%m/%Y %H:%M')
    )


@operacion_bp.route('/nomina_creditos')
@login_required
def vista_nomina_creditos():
    if current_user.role not in ['admin', 'cajero', 'sucursal']:
        return redirect(url_for('admin_login'))
    return render_template('nomina_creditos.html')


@operacion_bp.route('/industrial')
@login_required
def vista_industrial():
    if current_user.role != 'admin':
        return redirect(url_for('admin_login'))
    return render_template('panel_industrial.html', sucursales=SUCURSALES_OFICIALES)


# ==============================================================================
# 2. CATÁLOGO REAL DE BARRA Y COCINA (CARGA LIMPIA SIN DUPLICADOS)
# ==============================================================================
@operacion_bp.route('/admin/cargar_listas_reales')
@login_required
def cargar_listas_reales():
    if current_user.role != 'admin':
        return "Solo administrador", 403

    catalogo = [
        # ================= BARRA =================
        ("BARRA | Frutas y verduras", "Pepino", "kg"),
        ("BARRA | Frutas y verduras", "Piña", "kg"),
        ("BARRA | Frutas y verduras", "Fresa fresca", "kg"),
        ("BARRA | Frutas y verduras", "Guineo", "kg"),
        ("BARRA | Frutas y verduras", "Limón amarillo", "kg"),
        ("BARRA | Frutas y verduras", "Arúgula", "gr"),
        ("BARRA | Frutas y verduras", "Menta / Hierbabuena", "manojo"),
        ("BARRA | Frutas y verduras", "Jamaica", "kg"),
        ("BARRA | Frutas y verduras", "Melón", "kg"),
        ("BARRA | Frutas y verduras", "Fresa congelada", "kg"),
        ("BARRA | Frutas y verduras", "Limón", "kg"),
        ("BARRA | Frutas y verduras", "Naranja", "kg"),
        ("BARRA | Frutas y verduras", "Mora", "gr"),
        ("BARRA | Especias", "Jengibre", "gr"),
        ("BARRA | Especias", "Vainilla", "bote"),
        ("BARRA | Especias", "Canela", "gr"),
        ("BARRA | Especias", "Pimienta negra", "gr"),
        ("BARRA | Especias", "Clavo de olor", "gr"),
        ("BARRA | Especias", "Cúrcuma", "gr"),
        ("BARRA | Insumos", "Toronjil", "gr"),
        ("BARRA | Insumos", "Moon milk", "kg"),
        ("BARRA | Insumos", "Maracuyá", "kg"),
        ("BARRA | Insumos", "Chai en polvo", "kg"),
        ("BARRA | Insumos", "Taro", "kg"),
        ("BARRA | Insumos", "Tapioca", "kg"),
        ("BARRA | Insumos", "Café en grano", "kg"),
        ("BARRA | Insumos", "Café molido para refill", "kg"),
        ("BARRA | Insumos", "Chocolate molido", "kg"),
        ("BARRA | Insumos", "Té negro", "gr"),
        ("BARRA | Insumos", "Crema Lyncott", "lt"),
        ("BARRA | Insumos", "Mermelada", "lt"),
        ("BARRA | Insumos", "Chispas de chocolate", "gr"),
        ("BARRA | Insumos", "Chispas multicolor", "gr"),
        ("BARRA | Insumos", "Obleas de taro", "paquete"),
        ("BARRA | Insumos", "Chocolate líquido", "lt"),
        ("BARRA | Insumos limpieza y baños", "Papel higiénico", "pzs"),
        ("BARRA | Insumos limpieza y baños", "Papel de manos", "pzs"),
        ("BARRA | Insumos limpieza y baños", "Jabón de manos", "lt"),
        ("BARRA | Insumos limpieza y baños", "Cloro", "lt"),
        ("BARRA | Insumos limpieza y baños", "Fabuloso", "lt"),
        ("BARRA | Insumos limpieza y baños", "Jabón en polvo", "kg"),
        ("BARRA | Insumos limpieza y baños", "Jabón líquido", "lt"),
        ("BARRA | Insumos limpieza y baños", "Bolsas para basura", "paquete"),
        ("BARRA | Insumos limpieza y baños", "Líquido limpia vidrios y superficies", "lt"),
        ("BARRA | Insumos limpieza y baños", "Insecticida", "pz"),
        ("BARRA | Insumos limpieza y baños", "Gel antibacterial", "lt"),
        ("BARRA | Insumos limpieza y baños", "Escoba", "pz"),
        ("BARRA | Insumos limpieza y baños", "Trapeador", "pz"),
        ("BARRA | Insumos limpieza y baños", "Esponjas de colores", "pz"),
        ("BARRA | Insumos limpieza y baños", "Fibra verde", "pz"),
        ("BARRA | Insumos limpieza y baños", "Desodorante de baño", "pz"),
        ("BARRA | Otros", "Azúcar en sobres (kg)", "kg"),
        ("BARRA | Otros", "Crema en polvo", "kg"),
        ("BARRA | Otros", "Azúcar", "kg"),
        ("BARRA | Otros", "Canela molida", "kg"),
        ("BARRA | Otros", "Yogurt griego", "gr"),
        ("BARRA | Otros", "Chía", "gr"),
        ("BARRA | Otros", "Tajín", "gr"),
        ("BARRA | Otros", "Salsa habanera", "ml"),
        ("BARRA | Otros", "Splenda (pzs)", "pzs"),
        ("BARRA | Otros", "Granola", "gr"),
        ("BARRA | Otros", "Nuez", "gr"),
        ("BARRA | Refrescos y leche", "Leche deslactosada", "lt"),
        ("BARRA | Refrescos y leche", "Leche entera", "lt"),
        ("BARRA | Refrescos y leche", "Carnation", "lt"),
        ("BARRA | Refrescos y leche", "Coca Cola", "paquete"),
        ("BARRA | Refrescos y leche", "Sprite", "paquete"),
        ("BARRA | Refrescos y leche", "Sidral", "paquete"),
        ("BARRA | Refrescos y leche", "Agua Ciel 600 ml", "paquete"),
        ("BARRA | Refrescos y leche", "Agua mineral 600 ml", "pzs"),
        ("BARRA | Refrescos y leche", "Agua mineral lata", "paquete"),
        ("BARRA | Cervezas", "XX Lager", "caja"),
        ("BARRA | Cervezas", "XX Ámbar", "caja"),
        ("BARRA | Cervezas", "Bohemia oscura", "caja"),
        ("BARRA | Cervezas", "Bohemia clara", "caja"),
        ("BARRA | Desechables", "Vasos de cartón", "pzs"),
        ("BARRA | Desechables", "Tapas para vasos de cartón", "pzs"),
        ("BARRA | Desechables", "Vasos de plástico", "pzs"),
        ("BARRA | Desechables", "Tapas de boquilla", "pzs"),
        ("BARRA | Desechables", "Tapas domo", "pzs"),
        ("BARRA | Desechables", "Bolsas de sellado al vacío", "rollo"),
        ("BARRA | Desechables", "Agitadores de madera", "paquete"),
        ("BARRA | Desechables", "Cucharas", "pzs"),
        ("BARRA | Desechables", "Pajillas", "pzs"),
        ("BARRA | Desechables", "Vasos 4oz (expreso)", "pzs"),
        ("BARRA | Desechables", "Servilletas", "paquete"),
        ("BARRA | Desechables", "Azúcar en sobres (caja)", "caja"),
        ("BARRA | Desechables", "Splenda (caja)", "caja"),
        ("BARRA | Desechables", "Popotes blancos", "pzs"),
        ("BARRA | Desechables", "Popotes negros", "pzs"),
        ("BARRA | Desechables", "Tenedores", "pzs"),
        ("BARRA | Insumos barra", "Rollos para tickets", "pzs"),
        ("BARRA | Insumos barra", "Tinta de sello", "pzs"),
        ("BARRA | Insumos barra", "Plumones", "pzs"),
        ("BARRA | Insumos barra", "Bloc de notas", "pzs"),
        ("BARRA | Insumos barra", "Cinta maskin", "pzs"),
        ("BARRA | Postres", "Corbata frutos rojos", "pzs"),
        ("BARRA | Postres", "Corbata guayaba", "pzs"),
        ("BARRA | Postres", "Chocolatín", "pzs"),
        ("BARRA | Postres", "Cuernito de nutella", "pzs"),
        ("BARRA | Postres", "Cheesecake", "pzs"),
        ("BARRA | Postres", "Flan", "pzs"),
        ("BARRA | Extras", "EXTRA / FUERA DE LISTA (BARRA)", "pz"),

        # ================= COCINA =================
        ("COCINA | Frutas y verduras", "Limón", "kg"),
        ("COCINA | Frutas y verduras", "Cilantro", "gr"),
        ("COCINA | Frutas y verduras", "Aguacate", "kg"),
        ("COCINA | Frutas y verduras", "Plátanos", "kg"),
        ("COCINA | Frutas y verduras", "Tomate cherry", "kg"),
        ("COCINA | Frutas y verduras", "Arúgula", "gr"),
        ("COCINA | Frutas y verduras", "Ajo", "pz"),
        ("COCINA | Frutas y verduras", "Cebolla", "kg"),
        ("COCINA | Frutas y verduras", "Lechuga", "kg"),
        ("COCINA | Frutas y verduras", "Rábano", "kg"),
        ("COCINA | Frutas y verduras", "Cebolla morada", "kg"),
        ("COCINA | Frutas y verduras", "Guineo", "kg"),
        ("COCINA | Frutas y verduras", "Fresa", "kg"),
        ("COCINA | Frutas y verduras", "Tomate rojo", "kg"),
        ("COCINA | Frutas y verduras", "Frambuesa", "kg"),
        ("COCINA | Aderezos y más", "Jocoque", "bote"),
        ("COCINA | Aderezos y más", "Queso de cabra", "kg"),
        ("COCINA | Aderezos y más", "Crema", "lt"),
        ("COCINA | Aderezos y más", "Mostaza", "lt"),
        ("COCINA | Aderezos y más", "Mayonesa", "kg"),
        ("COCINA | Aderezos y más", "Catsup", "lt"),
        ("COCINA | Aderezos y más", "Queso crema", "kg"),
        ("COCINA | Aderezos y más", "Queso doble crema (Philadelphia)", "kg"),
        ("COCINA | Aderezos y más", "Queso amarillo", "pz"),
        ("COCINA | Aderezos y más", "Salsa tabasco", "bote"),
        ("COCINA | Aderezos y más", "Salsa inglesa", "bote"),
        ("COCINA | Aderezos y más", "Miel", "lt"),
        ("COCINA | Aderezos y más", "Mantequilla", "gr"),
        ("COCINA | Aderezos y más", "Catsup en sobres", "caja"),
        ("COCINA | Enlatados", "Aceitunas sin hueso", "bote"),
        ("COCINA | Enlatados", "Chipotle", "bote"),
        ("COCINA | Enlatados", "Chiles en rajas", "bote"),
        ("COCINA | Enlatados", "Champiñones", "lt"),
        ("COCINA | Enlatados", "Pepinillos", "bote"),
        ("COCINA | Enlatados", "Chícharos", "lata"),
        ("COCINA | Enlatados", "Lechera", "pzs"),
        ("COCINA | Otros", "Papas a la francesa", "kg"),
        ("COCINA | Otros", "Sal", "kg"),
        ("COCINA | Otros", "Aceite", "lt"),
        ("COCINA | Otros", "Aceite de oliva", "lt"),
        ("COCINA | Otros", "Paprika", "bote"),
        ("COCINA | Otros", "Ajo en polvo", "bote"),
        ("COCINA | Otros", "Cebolla en polvo", "bote"),
        ("COCINA | Otros", "Harina de hotcakes", "kg"),
        ("COCINA | Otros", "Azúcar", "kg"),
        ("COCINA | Otros", "Huevos", "casillero"),
        ("COCINA | Otros", "Canela", "gr"),
        ("COCINA | Otros", "Vinagre de manzana", "lt"),
        ("COCINA | Panes", "Baguette de cereales", "pz"),
        ("COCINA | Panes", "Cuernitos", "pz"),
        ("COCINA | Panes", "Bimbollos", "pz"),
        ("COCINA | Panes", "Pan de molde de cereales", "pz"),
        ("COCINA | Desechables", "Bowl desechables", "pza"),
        ("COCINA | Desechables", "Salseras desechables", "pza"),
        ("COCINA | Desechables", "Charola craft", "pza"),
        ("COCINA | Desechables", "Bolsas craft", "pza"),
        ("COCINA | Desechables", "Papel de tortilla", "pza"),
        ("COCINA | Desechables", "L38", "pza"),
        ("COCINA | Desechables", "Bolsa transparente CH", "paquete"),
        ("COCINA | Desechables", "Bolsa transparente G", "paquete"),
        ("COCINA | Desechables", "Bolsa tipo camiseta G", "paquete"),
        ("COCINA | Desechables", "Papel encerado", "kg"),
        ("COCINA | Desechables", "Envases de 1 litro", "pza"),
        ("COCINA | Desechables", "Tapas de salseras blancas", "pza"),
        ("COCINA | Desechables", "Papel aluminio", "rollo"),
        ("COCINA | Desechables", "Plástico film", "rollo"),
        ("COCINA | Embutidos y más", "Jamón", "kg"),
        ("COCINA | Embutidos y más", "Tocino", "kg"),
        ("COCINA | Embutidos y más", "Jamón serrano", "kg"),
        ("COCINA | Embutidos y más", "Mortadela", "kg"),
        ("COCINA | Embutidos y más", "Pechuga congelada", "pz"),
        ("COCINA | Embutidos y más", "Chorizo", "kg"),
        ("COCINA | Preparados", "Asado coleto", "lt"),
        ("COCINA | Preparados", "Carne de hamburguesa", "pz"),
        ("COCINA | Preparados", "Salsa ranchera", "lt"),
        ("COCINA | Preparados", "Salsa de motuleños", "lt"),
        ("COCINA | Preparados", "Mole", "lt"),
        ("COCINA | Preparados", "Frijoles", "lt"),
        ("COCINA | Preparados", "Salsa matcha", "lt"),
        ("COCINA | Preparados", "Salsa verde picante", "lt"),
        ("COCINA | Insumos limpieza", "Piedra pómez", "pz"),
        ("COCINA | Insumos limpieza", "Fibra verde", "pz"),
        ("COCINA | Insumos limpieza", "Fibra metálica", "pz"),
        ("COCINA | Insumos limpieza", "Ajax", "pz"),
        ("COCINA | Insumos limpieza", "Guantes", "pz"),
        ("COCINA | Cocteles", "Naked n mumo", "lt"),
        ("COCINA | Cocteles", "Guabi", "lt"),
        ("COCINA | Cocteles", "Morajitio", "lt"),
        ("COCINA | Cocteles", "Margariteco", "lt"),
        ("COCINA | Extras", "EXTRA / FUERA DE LISTA (COCINA)", "pz"),
    ]

    viejos = [
        'LECHE ENTERA', 'LECHE DESLACTOSADA', 'LECHE DE ALMENDRAS',
        'CAFÉ EN GRANO CHIAPAS', 'JARABE CARAMELO', 'JARABE VAINILLA',
        'CHOCOLATE MOKA POLVO', 'BOLSA DE HIELO 5KG', 'HUEVO',
        'JAMÓN DE PAVO', 'QUESO MANCHEGO', 'NARANJA PARA JUGO',
        'VASO 12 OZ CON TAPA', 'SERVILLETAS'
    ]
    InsumoBodegaPro.query.filter(InsumoBodegaPro.nombre.in_(viejos)).delete(synchronize_session=False)

    agregados = 0
    for cat, nom, uni in catalogo:
        if not InsumoBodegaPro.query.filter_by(categoria=cat, nombre=nom).first():
            db.session.add(InsumoBodegaPro(categoria=cat, nombre=nom, unidad=uni, stock_actual=0, stock_minimo=2))
            agregados += 1

    db.session.commit()
    return f"Listo: se agregaron {agregados} productos de tus hojas de Barra y Cocina. <a href='/almacen_pro'>Ir a Bodega</a>"


# ==============================================================================
# 3. APIs DE BODEGA CENTRAL Y PEDIDOS POR LOTE (CON BLOQUEO Y DEVOLUCIÓN DE STOCK)
# ==============================================================================
@operacion_bp.route('/api/almacen/datos')
@login_required
def api_almacen_datos():
    if current_user.role not in ['admin', 'almacen', 'sucursal']:
        return jsonify({'ok': False, 'msg': 'Acceso denegado'}), 403

    hoy_inicio = inicio_hoy_local()
    suc_actual = obtener_sucursal_activa(session)
    insumos = InsumoBodegaPro.query.order_by(InsumoBodegaPro.categoria.asc(), InsumoBodegaPro.nombre.asc()).all()

    q_reqs = RequerimientoBodega.query.filter(RequerimientoBodega.fecha >= hoy_inicio)
    if current_user.role == 'sucursal':
        q_reqs = q_reqs.filter_by(sucursal=suc_actual)
    reqs = q_reqs.order_by(RequerimientoBodega.id.desc()).limit(250).all()

    # Mapa de stock local de la sucursal actual (Opción A)
    mapa_local = {
        s.insumo_id: {'stock': s.stock_actual, 'minimo': s.stock_minimo}
        for s in StockSucursal.query.filter_by(sucursal=suc_actual).all()
    }

    recomendaciones = []
    ya_en_rec = set()
    for r in reqs:
        if r.estado_bodega == 'NO_ENTREGADO' and r.insumo_nombre not in ya_en_rec:
            ya_en_rec.add(r.insumo_nombre)
            recomendaciones.append({
                'nombre': r.insumo_nombre, 'categoria': r.categoria,
                'motivo': f'{r.sucursal}: Agotado en ruta ({r.cantidad} {r.unidad})',
                'sugerido': max(r.cantidad, 2), 'unidad': r.unidad, 'urgencia': 'ALTA'
            })

    for i in insumos:
        if 'EXTRA / FUERA DE LISTA' in i.nombre:
            continue
        if i.stock_actual <= i.stock_minimo and i.nombre not in ya_en_rec:
            ya_en_rec.add(i.nombre)
            faltante = max(1, round((i.stock_minimo * 2) - i.stock_actual, 1))
            recomendaciones.append({
                'nombre': i.nombre, 'categoria': i.categoria,
                'motivo': f'Stock bajo central ({i.stock_actual} / mín {i.stock_minimo} {i.unidad})',
                'sugerido': faltante, 'unidad': i.unidad,
                'urgencia': 'ALTA' if i.stock_actual <= 0 else 'MEDIA'
            })

    return jsonify({
        'ok': True,
        'sucursal': suc_actual,
        'insumos': [{
            'id': i.id, 'nombre': i.nombre, 'categoria': i.categoria, 'unidad': i.unidad,
            'stock_actual': i.stock_actual, 'stock_minimo': i.stock_minimo,
            'costo_unitario': i.costo_unitario,
            'stock_local': mapa_local.get(i.id, {}).get('stock', 0.0),
            'minimo_local': mapa_local.get(i.id, {}).get('minimo', 2.0)
        } for i in insumos],
        'requerimientos': [{
            'id': r.id, 'fecha': r.fecha.strftime('%d/%m %H:%M'),
            'sucursal': r.sucursal or 'Quiosco Morisco (Matriz)',
            'area': r.area, 'insumo_id': r.insumo_id,
            'insumo_nombre': r.insumo_nombre, 'categoria': r.categoria,
            'cantidad': r.cantidad,
            'cantidad_entregada': r.cantidad_entregada if r.cantidad_entregada is not None else r.cantidad,
            'unidad': r.unidad, 'estado_bodega': r.estado_bodega,
            'confirmado_caja': r.confirmado_caja,
            'solicitado_por': r.solicitado_por, 'nota': r.nota or ''
        } for r in reqs],
        'movimientos': [{
            'id': m.id, 'fecha': m.fecha.strftime('%d/%m %H:%M'), 'tipo': m.tipo,
            'insumo_nombre': m.insumo_nombre, 'cantidad': m.cantidad,
            'costo_total': f"{m.costo_total:.2f}", 'proveedor': m.proveedor or '-',
            'usuario': m.usuario, 'nota': m.nota or ''
        } for m in MovimientoAlmacen.query.order_by(MovimientoAlmacen.id.desc()).limit(60).all()],
        'proveedores': [{
            'id': p.id, 'nombre': p.nombre, 'telefono': p.telefono,
            'categoria': p.categoria, 'saldo_pendiente': p.saldo_pendiente
        } for p in ProveedorAlmacen.query.order_by(ProveedorAlmacen.nombre.asc()).all()],
        'recomendaciones': recomendaciones
    })


@operacion_bp.route('/api/almacen/solicitar', methods=['POST'])
@login_required
def api_almacen_solicitar():
    if current_user.role not in ['admin', 'sucursal', 'almacen']:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    ins = InsumoBodegaPro.query.get(int(data['insumo_id'])) if data.get('insumo_id') else None
    cant = _num(data.get('cantidad', 1))
    if cant <= 0:
        return jsonify({'ok': False, 'msg': 'Cantidad inválida'}), 400
    suc_real = obtener_sucursal_activa(session) if current_user.role == 'sucursal' else str(data.get('sucursal', 'Quiosco Morisco (Matriz)'))
    db.session.add(RequerimientoBodega(
        fecha=ahora_local(), sucursal=suc_real,
        area=str(data.get('area', 'BARRA')).upper(),
        insumo_id=ins.id if ins else None,
        insumo_nombre=ins.nombre if ins else str(data.get('nombre', '')).strip().upper(),
        categoria=ins.categoria if ins else str(data.get('categoria', 'ABARROTES')).upper(),
        cantidad=cant, cantidad_entregada=cant,
        unidad=ins.unidad if ins else str(data.get('unidad', 'PZA')).upper(),
        estado_bodega='PENDIENTE', confirmado_caja=False,
        solicitado_por=current_user.username.upper(),
        nota=str(data.get('nota', '')).strip()
    ))
    db.session.commit()
    return jsonify({'ok': True})


@operacion_bp.route('/api/almacen/solicitar_lote', methods=['POST'])
@login_required
def api_almacen_solicitar_lote():
    """Envía toda la lista marcada por la sucursal en 1 sola petición rápida."""
    if current_user.role not in ['admin', 'sucursal', 'almacen']:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'ok': False, 'msg': 'Lista vacía'}), 400

    suc_real = obtener_sucursal_activa(session) if current_user.role == 'sucursal' else str(data.get('sucursal', 'Quiosco Morisco (Matriz)'))
    nota_base = str(data.get('nota', '')).strip()
    ahora = ahora_local()
    creados = 0

    for it in items:
        cant = _num(it.get('cantidad', 0))
        if cant <= 0:
            continue
        ins = InsumoBodegaPro.query.get(int(it['insumo_id'])) if it.get('insumo_id') else None
        if not ins:
            continue
        area_envio = 'COCINA' if (ins.categoria or '').startswith('COCINA |') else str(it.get('area', 'BARRA')).upper()
        db.session.add(RequerimientoBodega(
            fecha=ahora, sucursal=suc_real, area=area_envio,
            insumo_id=ins.id, insumo_nombre=ins.nombre, categoria=ins.categoria,
            cantidad=cant, cantidad_entregada=cant, unidad=ins.unidad,
            estado_bodega='PENDIENTE', confirmado_caja=False,
            solicitado_por=current_user.username.upper(),
            nota=str(it.get('nota', nota_base)).strip()
        ))
        creados += 1

    db.session.commit()
    return jsonify({'ok': True, 'creados': creados})


@operacion_bp.route('/api/almacen/estado_bodega', methods=['POST'])
@login_required
def api_almacen_estado_bodega():
    if current_user.role not in ['admin', 'almacen']:
        return jsonify({'ok': False, 'msg': 'Solo Bodega o Admin pueden despachar pedidos.'}), 403

    data = request.json or {}
    if data.get('todos_entregados'):
        suc_filtro = data.get('sucursal', 'TODAS')
        q = RequerimientoBodega.query.filter(
            RequerimientoBodega.fecha >= inicio_hoy_local(),
            RequerimientoBodega.estado_bodega == 'PENDIENTE'
        )
        if suc_filtro != 'TODAS':
            q = q.filter_by(sucursal=suc_filtro)
        entregados, sin_stock = 0, []
        for r in q.all():
            ins = InsumoBodegaPro.query.get(r.insumo_id) if r.insumo_id else None
            es_extra = ins and ('EXTRA / FUERA DE LISTA' in ins.nombre)
            if ins and not es_extra and ins.stock_actual < r.cantidad:
                sin_stock.append(f"{r.insumo_nombre} (stock: {ins.stock_actual}, pedido: {r.cantidad})")
                continue
            r.estado_bodega = 'ENTREGADO'
            r.cantidad_entregada = r.cantidad
            if ins and not es_extra:
                ins.stock_actual = round(ins.stock_actual - r.cantidad, 2)
            entregados += 1
        db.session.commit()
        return jsonify({'ok': True, 'entregados': entregados, 'sin_stock': sin_stock})

    r = RequerimientoBodega.query.get_or_404(int(data['id']))
    nuevo_est = str(data.get('estado', 'ENTREGADO')).upper()
    era_entregado = (r.estado_bodega == 'ENTREGADO')
    if r.confirmado_caja and nuevo_est != 'ENTREGADO':
        return jsonify({'ok': False, 'msg': 'La sucursal ya confirmó recepción de este insumo.'}), 400

    cant_ant = r.cantidad_entregada if r.cantidad_entregada is not None else r.cantidad
    cant_ent = _num(data['cantidad_entregada']) if ('cantidad_entregada' in data and data['cantidad_entregada'] is not None) else r.cantidad
    ins = InsumoBodegaPro.query.get(r.insumo_id) if r.insumo_id else None
    es_extra = ins and ('EXTRA / FUERA DE LISTA' in ins.nombre)

    # Si estaba ENTREGADO y se regresa a PENDIENTE o NO_ENTREGADO -> devolver stock a Bodega Central
    if era_entregado and nuevo_est != 'ENTREGADO':
        if ins and not es_extra:
            ins.stock_actual = round(ins.stock_actual + cant_ant, 2)
        r.estado_bodega = nuevo_est
        db.session.commit()
        return jsonify({'ok': True, 'devuelto': True})

    # Si pasa a ENTREGADO -> validar stock suficiente (bloqueo estricto) y descontar
    if nuevo_est == 'ENTREGADO' and not era_entregado:
        if cant_ent <= 0:
            return jsonify({'ok': False, 'msg': 'La cantidad a entregar debe ser mayor a 0.'}), 400
        if ins and not es_extra:
            if ins.stock_actual < cant_ent:
                return jsonify({
                    'ok': False,
                    'msg': f'Stock insuficiente de {ins.nombre}: solo hay {ins.stock_actual} {ins.unidad} en Bodega Central.'
                }), 400
            ins.stock_actual = round(ins.stock_actual - cant_ent, 2)

    r.estado_bodega = nuevo_est
    r.cantidad_entregada = cant_ent
    db.session.commit()
    return jsonify({'ok': True})


@operacion_bp.route('/api/almacen/confirmar_caja', methods=['POST'])
@login_required
def api_almacen_confirmar_caja():
    """Sucursal confirma recepción y suma automáticamente a su Stock Local (Opción A)."""
    if current_user.role not in ['admin', 'sucursal', 'cajero']:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    r = RequerimientoBodega.query.get_or_404(int(data['id']))
    if current_user.role != 'admin' and (r.sucursal or '') != obtener_sucursal_activa(session):
        return jsonify({'ok': False, 'msg': 'Este pedido pertenece a otra sucursal.'}), 403
    recibido = bool(data.get('recibido', True))

    if recibido:
        if r.estado_bodega != 'ENTREGADO':
            return jsonify({'ok': False, 'msg': 'Bodega aún no ha marcado este pedido como entregado.'}), 400
        if not r.confirmado_caja:
            r.confirmado_caja = True
            cant_real = r.cantidad_entregada if r.cantidad_entregada is not None else r.cantidad
            if r.insumo_id and 'EXTRA / FUERA DE LISTA' not in (r.insumo_nombre or ''):
                sumar_stock_sucursal(r.sucursal, r.insumo_id, cant_real)
    else:
        if r.confirmado_caja:
            return jsonify({'ok': False, 'msg': 'Ya había sido confirmado como recibido.'}), 400
        # Si Bodega lo marcó entregado pero llegó faltante, devolver stock a bodega y marcar NO_ENTREGADO
        if r.estado_bodega == 'ENTREGADO' and r.insumo_id and 'EXTRA / FUERA DE LISTA' not in (r.insumo_nombre or ''):
            ins = InsumoBodegaPro.query.get(r.insumo_id)
            if ins:
                ins.stock_actual = round(ins.stock_actual + (r.cantidad_entregada or r.cantidad), 2)
        r.confirmado_caja = False
        r.estado_bodega = 'NO_ENTREGADO'

    db.session.commit()
    return jsonify({'ok': True})


@operacion_bp.route('/api/almacen/insumo', methods=['POST', 'DELETE'])
@login_required
def api_almacen_insumo():
    if current_user.role not in ['admin', 'almacen']:
        return jsonify({'ok': False, 'msg': 'Acceso denegado'}), 403
    data = request.json or {}
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip()
        if not nom:
            return jsonify({'ok': False, 'msg': 'Nombre requerido'}), 400
        db.session.add(InsumoBodegaPro(
            nombre=nom, categoria=str(data.get('categoria', 'BARRA | Otros')).strip(),
            unidad=str(data.get('unidad', 'pz')).strip(),
            stock_actual=_num(data.get('stock_actual', 0)),
            stock_minimo=_num(data.get('stock_minimo', 2)),
            costo_unitario=_num(data.get('costo_unitario', 0))
        ))
        db.session.commit()
        return jsonify({'ok': True})
    db.session.delete(InsumoBodegaPro.query.get_or_404(int(data['id'])))
    db.session.commit()
    return jsonify({'ok': True})


@operacion_bp.route('/api/almacen/movimiento', methods=['POST'])
@login_required
def api_almacen_movimiento():
    if current_user.role not in ['admin', 'almacen']:
        return jsonify({'ok': False, 'msg': 'Acceso denegado'}), 403
    data = request.json or {}
    ins = InsumoBodegaPro.query.get_or_404(int(data['insumo_id']))
    tipo = str(data.get('tipo', 'ENTRADA_COMPRA')).upper()
    cant = _num(data.get('cantidad', 0), minimo=-10_000_000.0)
    costo = _num(data.get('costo_total', 0))
    if cant <= 0:
        return jsonify({'ok': False, 'msg': 'Cantidad inválida'}), 400

    if tipo == 'ENTRADA_COMPRA':
        ins.stock_actual = round(ins.stock_actual + cant, 2)
    elif tipo in ('SALIDA_MERMA', 'TRASPASO'):
        ins.stock_actual = max(0.0, round(ins.stock_actual - cant, 2))

    db.session.add(MovimientoAlmacen(
        fecha=ahora_local(), tipo=tipo, insumo_nombre=ins.nombre, cantidad=cant,
        costo_total=costo, proveedor=str(data.get('proveedor', '')).strip().upper(),
        usuario=current_user.username.upper(), nota=str(data.get('nota', '')).strip()
    ))
    db.session.commit()
    return jsonify({'ok': True, 'stock_actual': ins.stock_actual})


@operacion_bp.route('/api/almacen/proveedor', methods=['POST'])
@login_required
def api_almacen_proveedor():
    if current_user.role not in ['admin', 'almacen']:
        return jsonify({'ok': False, 'msg': 'Acceso denegado'}), 403
    data = request.json or {}
    if data.get('pagar_id'):
        p = ProveedorAlmacen.query.get_or_404(int(data['pagar_id']))
        p.saldo_pendiente = max(0.0, round(p.saldo_pendiente - _num(data.get('abono', 0)), 2))
        db.session.commit()
        return jsonify({'ok': True})
    db.session.add(ProveedorAlmacen(
        nombre=str(data.get('nombre', '')).strip().upper(),
        telefono=str(data.get('telefono', '')).strip(),
        categoria=str(data.get('categoria', 'GENERAL')).strip().upper(),
        saldo_pendiente=_num(data.get('saldo_pendiente', 0))
    ))
    db.session.commit()
    return jsonify({'ok': True})


# ==============================================================================
# 4. STOCK LOCAL POR SUCURSAL Y RECETAS POS (OPCIÓN A)
# ==============================================================================
@operacion_bp.route('/api/sucursal/faltantes_sugeridos')
@login_required
def api_sucursal_faltantes_sugeridos():
    """Devuelve insumos con stock local bajo en la sucursal para prellenar pedidos."""
    if current_user.role not in ['admin', 'sucursal']:
        return jsonify({'ok': False, 'faltantes': []}), 403
    suc = obtener_sucursal_activa(session)
    registros = StockSucursal.query.filter_by(sucursal=suc).all()
    faltantes = []
    for st in registros:
        if st.stock_actual <= st.stock_minimo:
            ins = InsumoBodegaPro.query.get(st.insumo_id)
            if ins and 'EXTRA / FUERA DE LISTA' not in ins.nombre:
                sug = max(1.0, round((st.stock_minimo * 2) - st.stock_actual, 1))
                faltantes.append({'insumo_id': ins.id, 'nombre': ins.nombre, 'sugerido': sug, 'unidad': ins.unidad})
    return jsonify({'ok': True, 'sucursal': suc, 'faltantes': faltantes})


@operacion_bp.route('/api/stock_sucursal', methods=['GET', 'POST'])
@login_required
def api_stock_sucursal():
    """Consulta o ajusta el inventario local de cada sucursal."""
    if current_user.role not in ['admin', 'sucursal']:
        return jsonify({'ok': False}), 403
    if request.method == 'POST':
        if current_user.role != 'admin':
            return jsonify({'ok': False, 'msg': 'Solo Admin puede ajustar stock local manualmente.'}), 403
        d = request.json or {}
        suc = str(d.get('sucursal', 'Quiosco Morisco (Matriz)'))
        ins_id = int(d['insumo_id'])
        st = StockSucursal.query.filter_by(sucursal=suc, insumo_id=ins_id).first()
        if not st:
            st = StockSucursal(sucursal=suc, insumo_id=ins_id)
            db.session.add(st)
        st.stock_actual = max(0.0, _num(d.get('stock_actual', 0), minimo=-10_000_000.0))
        if 'stock_minimo' in d:
            st.stock_minimo = max(0.0, _num(d['stock_minimo'], minimo=-10_000_000.0))
        db.session.commit()
        return jsonify({'ok': True})

    suc = request.args.get('sucursal') if current_user.role == 'admin' else obtener_sucursal_activa(session)
    suc = suc or 'Quiosco Morisco (Matriz)'
    insumos = {i.id: i for i in InsumoBodegaPro.query.all()}
    lista = []
    for st in StockSucursal.query.filter_by(sucursal=suc).all():
        ins = insumos.get(st.insumo_id)
        if not ins:
            continue
        lista.append({
            'id': st.id, 'insumo_id': st.insumo_id, 'nombre': ins.nombre,
            'categoria': ins.categoria, 'unidad': ins.unidad,
            'stock_actual': st.stock_actual, 'stock_minimo': st.stock_minimo
        })
    return jsonify({'ok': True, 'sucursal': suc, 'items': lista})


@operacion_bp.route('/api/recetas', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_recetas():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Admin puede gestionar recetas.'}), 403
    if request.method == 'GET':
        insumos_map = {i.id: i for i in InsumoBodegaPro.query.all()}
        recs = RecetaPOS.query.order_by(RecetaPOS.platillo_nombre.asc()).all()
        prods = [p.nombre.upper() for p in Producto.query.order_by(Producto.nombre.asc()).all()]
        mods = [f">{m.nombre.upper()}" for m in ModificadorPOS.query.filter_by(activo=True).all()]
        return jsonify({
            'ok': True,
            'platillos_disponibles': prods + mods,
            'insumos': [
                {'id': i.id, 'nombre': i.nombre, 'categoria': i.categoria, 'unidad': i.unidad}
                for i in InsumoBodegaPro.query.order_by(InsumoBodegaPro.categoria.asc(), InsumoBodegaPro.nombre.asc()).all()
                if 'EXTRA / FUERA DE LISTA' not in i.nombre
            ],
            'recetas': [{
                'id': r.id, 'platillo_nombre': r.platillo_nombre,
                'insumo_id': r.insumo_id,
                'insumo_nombre': insumos_map[r.insumo_id].nombre if r.insumo_id in insumos_map else f'#{r.insumo_id}',
                'unidad': insumos_map[r.insumo_id].unidad if r.insumo_id in insumos_map else '',
                'cantidad_descontar': r.cantidad_descontar
            } for r in recs]
        })

    data = request.json or {}
    if request.method == 'POST':
        plat = str(data.get('platillo_nombre', '')).strip().upper()
        ins_id = int(data.get('insumo_id', 0))
        cant = _num(data.get('cantidad_descontar', 0))
        if not plat or ins_id <= 0 or cant <= 0:
            return jsonify({'ok': False, 'msg': 'Completa platillo, insumo y cantidad mayor a 0.'}), 400
        db.session.add(RecetaPOS(platillo_nombre=plat, insumo_id=ins_id, cantidad_descontar=cant))
        db.session.commit()
        return jsonify({'ok': True})

    db.session.delete(RecetaPOS.query.get_or_404(int(data['id'])))
    db.session.commit()
    return jsonify({'ok': True})


# ==============================================================================
# 5. CHECADOR, MERMAS Y NÓMINA / VALES (SIN CRÉDITOS A CLIENTES)
# ==============================================================================
@operacion_bp.route('/api/checador/registrar', methods=['POST'])
@login_required
def api_checador_registrar():
    if current_user.role not in ['admin', 'sucursal']:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    suc = obtener_sucursal_activa(session) if current_user.role == 'sucursal' else (data.get('sucursal') or obtener_sucursal_activa(session))
    emp = str(data.get('empleado_nombre', '')).strip().upper()
    tipo = str(data.get('tipo', 'ENTRADA')).upper()
    if not emp:
        return jsonify({'ok': False, 'msg': 'Nombre de empleado requerido'}), 400
    db.session.add(RegistroAsistencia(fecha=ahora_local(), sucursal=suc, empleado_nombre=emp, tipo=tipo, notas=str(data.get('notas', '')).strip()))
    db.session.commit()
    return jsonify({'ok': True})


@operacion_bp.route('/api/checador/lista')
@login_required
def api_checador_lista():
    if current_user.role not in ['admin', 'sucursal']:
        return jsonify({'ok': False}), 403
    q = RegistroAsistencia.query.filter(RegistroAsistencia.fecha >= inicio_hoy_local())
    if current_user.role == 'sucursal':
        q = q.filter_by(sucursal=obtener_sucursal_activa(session))
    registros = q.order_by(RegistroAsistencia.id.desc()).all()
    return jsonify({'ok': True, 'asistencias': [{
        'id': a.id, 'hora': a.fecha.strftime('%H:%M:%S'), 'sucursal': a.sucursal,
        'empleado': a.empleado_nombre, 'tipo': a.tipo, 'notas': a.notas
    } for a in registros]})


@operacion_bp.route('/api/mermas/registrar', methods=['POST'])
@login_required
def api_mermas_registrar():
    if current_user.role not in ['admin', 'sucursal']:
        return jsonify({'ok': False, 'msg': 'Sin permiso'}), 403
    data = request.json or {}
    suc = obtener_sucursal_activa(session) if current_user.role == 'sucursal' else (data.get('sucursal') or obtener_sucursal_activa(session))
    ins = str(data.get('insumo_nombre', '')).strip().upper()
    if not ins:
        return jsonify({'ok': False, 'msg': 'Nombre de insumo requerido'}), 400
    cantidad = _num(data.get('cantidad', 1), minimo=0.001, maximo=100000.0)
    costo_raw = data.get('costo_total')
    costo_total = _num(costo_raw) if costo_raw not in (None, '') else None
    aplicar_merma(
        ins, cantidad, str(data.get('motivo', 'Merma')).strip(), suc, current_user.username.upper(),
        unidad=str(data.get('unidad', 'PZA')).upper(), costo_total=costo_total
    )
    db.session.commit()
    return jsonify({'ok': True})


@operacion_bp.route('/api/mermas/resumen')
@login_required
def api_mermas_resumen():
    if current_user.role not in ['admin', 'sucursal']:
        return jsonify({'ok': False}), 403
    primer_dia_mes = ahora_local().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    q = RegistroMerma.query.filter(RegistroMerma.fecha >= primer_dia_mes)
    if current_user.role == 'sucursal':
        q = q.filter_by(sucursal=obtener_sucursal_activa(session))
    mermas_mes = q.all()
    por_sucursal = {}
    for m in mermas_mes:
        por_sucursal[m.sucursal] = round(por_sucursal.get(m.sucursal, 0.0) + m.costo_total, 2)

    q_ult = RegistroMerma.query
    if current_user.role == 'sucursal':
        q_ult = q_ult.filter_by(sucursal=obtener_sucursal_activa(session))
    return jsonify({
        'ok': True,
        'total_mes': round(sum(m.costo_total for m in mermas_mes), 2),
        'por_sucursal': por_sucursal,
        'mermas': [{
            'id': m.id, 'fecha': m.fecha.strftime('%d/%m %H:%M'), 'sucursal': m.sucursal,
            'insumo': m.insumo_nombre, 'cantidad': f"{m.cantidad} {m.unidad}",
            'costo': f"${m.costo_total:.2f}", 'motivo': m.motivo, 'usuario': m.usuario
        } for m in q_ult.order_by(RegistroMerma.id.desc()).limit(50).all()]
    })


@operacion_bp.route('/api/finanzas/datos')
@login_required
def api_finanzas_datos():
    if current_user.role not in ['admin', 'cajero', 'sucursal']:
        return jsonify({'ok': False}), 403
    es_admin = (current_user.role == 'admin')
    empleados = EmpleadoNominaPOS.query.filter_by(activo=True).order_by(EmpleadoNominaPOS.nombre.asc()).all()
    consumos = ConsumoEmpleadoPOS.query.order_by(ConsumoEmpleadoPOS.id.desc()).limit(100).all()
    pendientes_todos = ConsumoEmpleadoPOS.query.filter_by(descontado=False).all()
    recibos = ReciboNominaPOS.query.order_by(ReciboNominaPOS.id.desc()).limit(60).all() if es_admin else []

    adeudo_emp = {}
    for c in pendientes_todos:
        adeudo_emp[c.empleado_id] = round(adeudo_emp.get(c.empleado_id, 0.0) + c.monto, 2)

    return jsonify({
        'ok': True,
        'es_admin': es_admin,
        'empleados': [{
            'id': e.id, 'nombre': e.nombre, 'puesto': e.puesto,
            'sueldo_base': e.sueldo_base if es_admin else 0.0, 'periodo': e.periodo,
            'consumo_pendiente': adeudo_emp.get(e.id, 0.0)
        } for e in empleados],
        'consumos': [{
            'id': c.id, 'fecha': c.fecha.strftime('%d/%m %H:%M'),
            'empleado_id': c.empleado_id, 'empleado_nombre': c.empleado_nombre,
            'tipo': c.tipo, 'concepto': c.concepto, 'monto': c.monto, 'descontado': c.descontado
        } for c in consumos],
        'recibos': [{
            'id': r.id, 'fecha': r.fecha.strftime('%d/%m/%Y %H:%M'),
            'empleado_nombre': r.empleado_nombre, 'puesto': r.puesto,
            'periodo_texto': r.periodo_texto, 'sueldo_base': r.sueldo_base,
            'bonos': r.bonos, 'propinas': r.propinas,
            'descuentos_consumo': r.descuentos_consumo, 'otros_descuentos': r.otros_descuentos,
            'total_neto': r.total_neto, 'pagado_por': r.pagado_por
        } for r in recibos]
    })

@operacion_bp.route('/api/finanzas/empleado', methods=['POST', 'DELETE'])
@login_required
def api_finanzas_empleado():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Admin puede modificar empleados.'}), 403
    data = request.json or {}
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip().upper()
        if not nom:
            return jsonify({'ok': False, 'msg': 'Nombre requerido'}), 400
        db.session.add(EmpleadoNominaPOS(
            nombre=nom, puesto=str(data.get('puesto', 'MESERO')).strip().upper(),
            sueldo_base=_num(data.get('sueldo_base', 1500)),
            periodo=str(data.get('periodo', 'SEMANAL')).strip().upper(), activo=True
        ))
        db.session.commit()
        return jsonify({'ok': True})
    e = EmpleadoNominaPOS.query.get_or_404(int(data['id']))
    e.activo = False
    db.session.commit()
    return jsonify({'ok': True})


@operacion_bp.route('/api/finanzas/consumo_empleado', methods=['POST'])
@login_required
def api_finanzas_consumo_empleado():
    if current_user.role not in ['admin', 'cajero', 'sucursal']:
        return jsonify({'ok': False}), 403
    data = request.json or {}
    emp = EmpleadoNominaPOS.query.get_or_404(int(data['empleado_id']))
    monto = _num(data.get('monto', 0))
    if monto <= 0:
        return jsonify({'ok': False, 'msg': 'Monto inválido'}), 400
    concepto = str(data.get('concepto', 'Consumo personal')).strip().upper()
    tipo = str(data.get('tipo', 'CONSUMO')).strip().upper()
    db.session.add(ConsumoEmpleadoPOS(
        fecha=ahora_local(), empleado_id=emp.id, empleado_nombre=emp.nombre,
        tipo=tipo, concepto=concepto, monto=monto, descontado=False,
        registrado_por=current_user.username.upper()
    ))
    db.session.commit()
    registrar_bitacora('VALE_EMPLEADO', emp.nombre, monto, f'{tipo}: {concepto}')
    return jsonify({'ok': True})


@operacion_bp.route('/api/finanzas/generar_nomina', methods=['POST'])
@login_required
def api_finanzas_generar_nomina():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Admin puede pagar nómina.'}), 403
    data = request.json or {}
    emp = EmpleadoNominaPOS.query.get_or_404(int(data['empleado_id']))
    bonos = _num(data.get('bonos', 0))
    propinas = _num(data.get('propinas', 0))
    otros_desc = _num(data.get('otros_descuentos', 0))
    periodo_txt = str(data.get('periodo_texto', emp.periodo)).strip().upper()

    pendientes = ConsumoEmpleadoPOS.query.filter_by(empleado_id=emp.id, descontado=False).all()
    desc_consumo = round(sum(p.monto for p in pendientes), 2)
    for p in pendientes:
        p.descontado = True

    total_neto = round(emp.sueldo_base + bonos + propinas - desc_consumo - otros_desc, 2)
    recibo = ReciboNominaPOS(
        fecha=ahora_local(), empleado_id=emp.id, empleado_nombre=emp.nombre, puesto=emp.puesto,
        periodo_texto=periodo_txt, sueldo_base=emp.sueldo_base, bonos=bonos, propinas=propinas,
        descuentos_consumo=desc_consumo, otros_descuentos=otros_desc,
        total_neto=total_neto, pagado_por=current_user.username.upper()
    )
    db.session.add(recibo)
    db.session.commit()
    registrar_bitacora('PAGO_NOMINA', emp.nombre, total_neto, f'Base:${emp.sueldo_base} + Bonos:${bonos} - Vales:${desc_consumo}')
    return jsonify({'ok': True, 'recibo': {
        'id': recibo.id, 'fecha': recibo.fecha.strftime('%d/%m/%Y %H:%M'),
        'empleado_nombre': recibo.empleado_nombre, 'puesto': recibo.puesto,
        'periodo_texto': recibo.periodo_texto, 'sueldo_base': recibo.sueldo_base,
        'bonos': recibo.bonos, 'propinas': recibo.propinas,
        'descuentos_consumo': recibo.descuentos_consumo,
        'otros_descuentos': recibo.otros_descuentos, 'total_neto': recibo.total_neto
    }})


# ==============================================================================
# 6. PANEL INDUSTRIAL (RESUMEN REAL 4 SUCURSALES, WHATSAPP Y EXCEL)
# ==============================================================================
@operacion_bp.route('/api/industrial/cancelaciones_alerta')
@login_required
def api_industrial_cancelaciones_alerta():
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    cancelaciones = BitacoraPOS.query.filter(
        BitacoraPOS.fecha >= inicio_hoy_local(),
        BitacoraPOS.accion.in_(['CANCELACION', 'ELIMINAR_CUENTA'])
    ).order_by(BitacoraPOS.id.desc()).all()

    conteo = {}
    for c in cancelaciones:
        usr = c.usuario.upper()
        conteo[usr] = conteo.get(usr, 0) + 1

    alertas = [{
        'usuario': usr, 'total_cancelaciones': cnt,
        'alerta': f'⚠️ ALERTA ROJA: {usr} ha cancelado {cnt} órdenes/productos hoy.'
    } for usr, cnt in conteo.items() if cnt >= 5]

    return jsonify({
        'ok': True,
        'total_cancelaciones_hoy': len(cancelaciones),
        'alertas_criticas': alertas,
        'detalle': [{
            'hora': c.fecha.strftime('%H:%M:%S'), 'sucursal': c.sucursal or '-',
            'usuario': c.usuario, 'autorizo': c.autorizo or '-',
            'mesa': c.mesa, 'monto': f"${c.monto:.2f}", 'detalle': c.detalle
        } for c in cancelaciones]
    })


@operacion_bp.route('/api/industrial/resumen_general')
@login_required
def api_industrial_resumen_general():
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    hoy_inicio = inicio_hoy_local()
    cuentas_hoy = CuentaPOS.query.filter(CuentaPOS.cierre >= hoy_inicio, CuentaPOS.estado == 'PAGADA').all()

    sucursales = {s: {'total': 0.0, 'cuentas': 0} for s in SUCURSALES_OFICIALES}
    for c in cuentas_hoy:
        suc = c.sucursal if c.sucursal in sucursales else 'Quiosco Morisco (Matriz)'
        sucursales[suc]['total'] = round(sucursales[suc]['total'] + c.total, 2)
        sucursales[suc]['cuentas'] += 1

    arqueos = ArqueoTurnoPOS.query.order_by(ArqueoTurnoPOS.id.desc()).limit(20).all()
    cortes_data = [{
        'fecha': a.fecha.strftime('%d/%m %H:%M'), 'sucursal': a.sucursal or 'Quiosco Morisco (Matriz)',
        'turno': f"#{a.turno_id}", 'cajero': a.cajero,
        'esperado': f"${a.esperado_total:.2f}", 'declarado': f"${a.declarado_total:.2f}",
        'diferencia': f"${a.diferencia:.2f}",
        'estatus': 'OK' if abs(a.diferencia) < 1 else ('FALTANTE' if a.diferencia < 0 else 'SOBRANTE')
    } for a in arqueos]

    primer_dia = ahora_local().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    detalles_mes = DetallePOS.query.join(CuentaPOS).filter(
        CuentaPOS.apertura >= primer_dia,
        CuentaPOS.estado.in_(['PAGADA', 'DIVIDIDA']),
        CuentaPOS.es_subcuenta_parte == False,
        DetallePOS.es_modificador == False,
        DetallePOS.clave != 'DIV'
    ).all()
    conteo_prod = {}
    for d in detalles_mes:
        nom = d.descripcion.lstrip('>').strip().upper()
        conteo_prod[nom] = conteo_prod.get(nom, 0) + int(d.cantidad)

    menos_vendidos = []
    for p in Producto.query.filter_by(agotado=False).all():
        vtas = conteo_prod.get(p.nombre.upper(), 0)
        if vtas < 3:
            menos_vendidos.append({
                'categoria': p.categoria, 'nombre': p.nombre,
                'precio': f"${p.precio:.2f}", 'ventas': vtas,
                'accion': 'Promocionar o revisar carta'
            })
    menos_vendidos = sorted(menos_vendidos, key=lambda x: x['ventas'])[:25]

    return jsonify({'ok': True, 'ventas': sucursales, 'cortes': cortes_data, 'menos_vendidos': menos_vendidos})


@operacion_bp.route('/api/industrial/resumen_whatsapp')
@login_required
def api_industrial_resumen_whatsapp():
    """Genera un resumen ejecutivo ordenado listo para enviar por WhatsApp en 1 clic."""
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    hoy_inicio = inicio_hoy_local()
    cuentas_hoy = CuentaPOS.query.filter(CuentaPOS.cierre >= hoy_inicio, CuentaPOS.estado == 'PAGADA').all()
    suc_tot = {s: {'venta': 0.0, 'ctas': 0} for s in SUCURSALES_OFICIALES}
    ef_tot = tarj_tot = trans_tot = 0.0
    for c in cuentas_hoy:
        s = c.sucursal if c.sucursal in suc_tot else 'Quiosco Morisco (Matriz)'
        suc_tot[s]['venta'] = round(suc_tot[s]['venta'] + c.total, 2)
        suc_tot[s]['ctas'] += 1
        ef_tot += max(0.0, (c.pago_efectivo or 0.0) - (c.cambio or 0.0))
        tarj_tot += (c.pago_tarjeta_debito or 0.0) + (c.pago_tarjeta_credito or 0.0)
        trans_tot += (c.pago_transferencia or 0.0)

    gran_total = round(sum(v['venta'] for v in suc_tot.values()), 2)
    mermas_hoy = RegistroMerma.query.filter(RegistroMerma.fecha >= hoy_inicio).all()
    tot_merma = round(sum(m.costo_total for m in mermas_hoy), 2)
    canc_hoy = BitacoraPOS.query.filter(
        BitacoraPOS.fecha >= hoy_inicio,
        BitacoraPOS.accion.in_(['CANCELACION', 'ELIMINAR_CUENTA'])
    ).count()
    cortes_hoy = ArqueoTurnoPOS.query.filter(ArqueoTurnoPOS.fecha >= hoy_inicio).all()
    dif_total = round(sum(a.diferencia for a in cortes_hoy), 2)

    lineas = [
        f"*📊 REPORTE DIARIO • COMENSAL CONECTADO*",
        f"📅 {ahora_local().strftime('%d/%m/%Y %I:%M %p')}",
        "",
        "*💰 VENTAS POR SUCURSAL:*"
    ]
    for s in SUCURSALES_OFICIALES:
        lineas.append(f"• {s}: *${suc_tot[s]['venta']:,.2f}* ({suc_tot[s]['ctas']} ctas)")
    lineas += [
        f"*TOTAL GENERAL: ${gran_total:,.2f}*",
        "",
        "*💳 FORMAS DE PAGO:*",
        f"• Efectivo: ${ef_tot:,.2f}",
        f"• Tarjeta: ${tarj_tot:,.2f}",
        f"• Transferencia: ${trans_tot:,.2f}",
        "",
        "*🛡️ CONTROL Y AUDITORÍA:*",
        f"• Cancelaciones hoy: {canc_hoy}",
        f"• Mermas hoy: ${tot_merma:,.2f}",
        f"• Cortes cerrados: {len(cortes_hoy)} (Dif. acumulada: ${dif_total:,.2f})"
    ]
    texto = "\n".join(lineas)
    return jsonify({'ok': True, 'texto': texto, 'wa_url': f"https://wa.me/?text={urllib.parse.quote(texto)}"})


@operacion_bp.route('/api/exportar/ventas_sucursales')
@login_required
def exportar_ventas_sucursales():
    if current_user.role != 'admin':
        return "Acceso denegado", 403
    cuentas = CuentaPOS.query.filter_by(estado='PAGADA').order_by(CuentaPOS.id.desc()).all()
    filas = [(
        c.folio or c.orden, c.sucursal or 'Quiosco Morisco (Matriz)', c.mesa, c.mesero,
        c.apertura.strftime('%Y-%m-%d %H:%M') if c.apertura else '',
        c.cierre.strftime('%Y-%m-%d %H:%M') if c.cierre else '',
        c.pago_efectivo or 0, c.pago_tarjeta_debito or 0, c.pago_tarjeta_credito or 0,
        c.pago_transferencia or 0, c.pago_otros or 0, c.tarjeta_ultimos4 or '',
        c.propina_tarjeta or 0, c.total
    ) for c in cuentas]
    return _csv_excel(
        ('Folio', 'Sucursal', 'Mesa', 'Mesero', 'Apertura', 'Cierre', 'Efectivo', 'Tarjeta_Debito', 'Tarjeta_Credito', 'Transferencia', 'Vale_Empleado', 'Ult4_Tarjeta', 'Propina_Tarjeta', 'Total'),
        filas, f"Ventas_4Sucursales_{ahora_local().strftime('%Y%m%d')}.csv"
    )


@operacion_bp.route('/api/exportar/mermas')
@login_required
def exportar_mermas():
    if current_user.role != 'admin':
        return "Acceso denegado", 403
    filas = [(
        m.id, m.fecha.strftime('%Y-%m-%d %H:%M'), m.sucursal, m.insumo_nombre,
        m.cantidad, m.unidad, m.costo_total, m.motivo, m.usuario
    ) for m in RegistroMerma.query.order_by(RegistroMerma.id.desc()).all()]
    return _csv_excel(
        ('ID', 'Fecha', 'Sucursal', 'Insumo', 'Cantidad', 'Unidad', 'Costo_Total', 'Motivo', 'Registrado_Por'),
        filas, f"Reporte_Mermas_{ahora_local().strftime('%Y%m%d')}.csv"
    )


@operacion_bp.route('/api/exportar/cortes_caja')
@login_required
def exportar_cortes_caja():
    if current_user.role != 'admin':
        return "Acceso denegado", 403
    filas = [(
        a.turno_id, a.sucursal or 'Quiosco Morisco (Matriz)', a.fecha.strftime('%Y-%m-%d %H:%M'),
        a.cajero, a.esperado_total, a.declarado_total, a.diferencia,
        a.ef_declarado, a.td_declarado, a.tc_declarado, a.trans_declarado or 0, a.val_declarado
    ) for a in ArqueoTurnoPOS.query.order_by(ArqueoTurnoPOS.id.desc()).all()]
    return _csv_excel(
        ('Turno_ID', 'Sucursal', 'Fecha', 'Cajero', 'Esperado_Total', 'Declarado_Total', 'Diferencia', 'Efectivo', 'Tarjeta_D', 'Tarjeta_C', 'Transferencia', 'Vales'),
        filas, f"Historial_Cortes_Caja_{ahora_local().strftime('%Y%m%d')}.csv"
    )