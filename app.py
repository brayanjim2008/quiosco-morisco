import os
import re
import csv
import json
import urllib.request
import urllib.parse
from io import StringIO, BytesIO
from datetime import timedelta

import segno
import cloudinary
import cloudinary.uploader
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, session, abort
from flask_login import login_user, login_required, logout_user, current_user
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
import math
import hmac
import secrets

from models import (
    db, login_manager, inicializar_sistema, ahora_local, inicio_hoy_local,
    SUCURSALES_OFICIALES, generar_pin_unico, obtener_sucursal_activa,
    cache_get, cache_set, invalidar_cache_publico, cargar_menu_quiosco_oficial, quitar_caracteres_html,
    PREFIJO_SUCURSAL, SUCURSAL_DEFAULT, sucursal_desde_codigo, sucursal_filtro, obtener_datos_ticket,
    esquema_faltante, CAMPOS_DATOS_TICKET, CLAVE_CFG_DATOS_TICKET, cfg_cargar, cfg_guardar, registrar_bitacora,
    User, CategoriaMenu, Producto, Premio, HistorialPremio, Galeria,
    Cliente, PinCaja, Evaluacion, Anuncio, PreOrden
)
from pos_routes import pos_bp, _cargar_areas_prods, _guardar_areas_prods
from operacion_routes import operacion_bp
from servicio_routes import servicio_bp
from compras_routes import compras_bp
from nomina_routes import nomina_bp
from alertas import alertas_bp
from propinas_routes import propinas_bp
from menu_routes import menu_bp
from respaldo import respaldo_bp
from reportes_routes import reportes_bp
from models import limite_intentos_excedido, registrar_intento_fallido, limpiar_intentos, productos_para_sucursal
from models import PERMISOS_USUARIO, permisos_propios, tiene_permiso

app = Flask(__name__)
# Render pone 1 proxy delante: ProxyFix toma la IP real que ese proxy agrega a X-Forwarded-For
# (la que el cliente no puede falsificar) y la deja en request.remote_addr.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)


def _env_requerida(nombre):
    """Lee una variable de entorno obligatoria; si falta, la app NO arranca (así nunca usa credenciales por defecto)."""
    valor = os.environ.get(nombre, '').strip()
    if not valor:
        raise RuntimeError(f"Falta la variable de entorno {nombre}. Defínela en Render (o en tu terminal local).")
    return valor


def _normalizar_db_url(url):
    """postgres:// o postgresql:// -> postgresql+psycopg2:// (el driver instalado en requirements.txt).
    SQLAlchemy 2.1 cambió el driver por defecto a psycopg 3, que no está instalado."""
    for prefijo in ('postgres://', 'postgresql://'):
        if url.startswith(prefijo):
            return 'postgresql+psycopg2://' + url[len(prefijo):]
    return url


app.secret_key = _env_requerida('SECRET_KEY')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=365)
# Cookies más seguras. En Render define COOKIE_SECURE=1 (requiere HTTPS); en local déjalo sin definir.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '0') == '1'
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_SECURE'] = app.config['SESSION_COOKIE_SECURE']

# --- CLOUDINARY (configura estas variables en Render para máxima seguridad) ---
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)

# --- BASE DE DATOS NEONDB (configura DATABASE_URL en Render) ---
app.config['SQLALCHEMY_DATABASE_URI'] = _normalizar_db_url(_env_requerida('DATABASE_URL'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # máx. 8 MB por petición (fotos)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True, "pool_recycle": 300, "pool_size": 5, "max_overflow": 5}

db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'admin_login'
login_manager.login_message = None

app.register_blueprint(pos_bp)
app.register_blueprint(operacion_bp)
app.register_blueprint(servicio_bp)
app.register_blueprint(compras_bp)
app.register_blueprint(nomina_bp)
app.register_blueprint(alertas_bp)
app.register_blueprint(propinas_bp)
app.register_blueprint(menu_bp)
app.register_blueprint(respaldo_bp)
app.register_blueprint(reportes_bp)


# ------------------------------------------------------------------------------
# Manejo global de errores: siempre rollback; las rutas /api/ responden JSON.
# ------------------------------------------------------------------------------
@app.errorhandler(ValueError)
@app.errorhandler(TypeError)
def _dato_invalido_global(e):
    """Un número o dato mal escrito en una API responde 400 con un mensaje claro (no 'Error interno')."""
    if not request.path.startswith('/api/'):
        return _manejar_error_global(e)
    db.session.rollback()
    app.logger.warning('Dato inválido en %s: %r', request.path, e)  # queda en el log por si fuera un error del sistema
    return jsonify({'ok': False, 'msg': 'Dato inválido o fuera de rango. Revisa lo que escribiste.'}), 400


@app.errorhandler(KeyError)
def _dato_faltante_global(e):
    if not request.path.startswith('/api/'):
        return _manejar_error_global(e)
    db.session.rollback()
    return jsonify({'ok': False, 'msg': 'Falta un dato requerido.'}), 400


@app.errorhandler(Exception)
def _manejar_error_global(e):
    db.session.rollback()
    codigo = e.code if isinstance(e, HTTPException) else 500
    if request.path.startswith('/api/'):
        if codigo >= 500:
            app.logger.exception(e)
            msg = 'Error interno del servidor.'
        else:
            msg = getattr(e, 'description', None) or 'Solicitud no válida.'
        return jsonify({'ok': False, 'msg': msg, 'error': msg}), codigo
    if isinstance(e, HTTPException):
        return e
    if app.debug:
        raise e
    app.logger.exception(e)
    return 'Error interno del servidor.', 500


# ------------------------------------------------------------------------------
# Protección CSRF: token por sesión. templates/_csrf.html lo agrega solo a cada fetch y formulario.
# Se exige a usuarios con sesión iniciada (los únicos cuyas acciones se pueden suplantar).
# ------------------------------------------------------------------------------
def _csrf_token():
    token = session.get('_csrf')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf'] = token
    return token


@app.context_processor
def _inyectar_csrf():
    return {'csrf_token': _csrf_token}


@app.before_request
def _verificar_csrf():
    if request.method in ('GET', 'HEAD', 'OPTIONS') or not current_user.is_authenticated:
        return None
    enviado = request.headers.get('X-CSRFToken') or request.form.get('csrf_token', '')
    esperado = session.get('_csrf', '')
    if not enviado or not esperado or not hmac.compare_digest(str(enviado), str(esperado)):
        abort(400, 'La sesión expiró o la solicitud no es válida. Recarga la página e intenta de nuevo.')
    return None


@app.after_request
def _encabezados_seguridad(resp):
    """Encabezados de seguridad del navegador en todas las respuestas."""
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')          # no adivinar tipos de archivo
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')              # otra página no puede meter el sistema en un marco
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    resp.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
    if request.is_secure:   # en Render (HTTPS): el navegador ya nunca usará http
        resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
    return resp


def _numero_seguro(valor, minimo=0.0, maximo=1_000_000.0):
    try:
        x = float(valor or 0)
    except (TypeError, ValueError):
        raise ValueError('Número inválido')
    if not math.isfinite(x) or x < minimo or x > maximo:
        raise ValueError('Número fuera de rango')
    return round(x, 2)


def _precio_form():
    try:
        return _numero_seguro(request.form.get('precio', ''), 0.0, 100000.0)
    except ValueError:
        abort(400, 'Precio inválido.')


def _texto_publico(valor, max_len):
    """Texto escrito por el público (pre-órdenes, evaluaciones, fidelidad): quita los caracteres con los que
    se arma HTML/JS. Así, aunque alguna pantalla interna olvide escapar, no se puede inyectar código."""
    return quitar_caracteres_html(valor).strip()[:max_len]


_TIPOS_IMAGEN_OK ={'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def _subir_imagen(archivo):
    """Valida tipo de imagen y credenciales de Cloudinary antes de subir. Devuelve la URL o None (y avisa con flash)."""
    if not (os.environ.get('CLOUDINARY_CLOUD_NAME') and os.environ.get('CLOUDINARY_API_KEY') and os.environ.get('CLOUDINARY_API_SECRET')):
        flash('Cloudinary no está configurado en el servidor: no se pudo subir la imagen.', 'danger')
        return None
    if (archivo.mimetype or '').lower() not in _TIPOS_IMAGEN_OK:
        flash('Formato de imagen no permitido. Usa JPG, PNG, WEBP o GIF.', 'danger')
        return None
    try:
        return cloudinary.uploader.upload(archivo).get('secure_url')
    except Exception as e:
        app.logger.exception(e)
        flash('No se pudo subir la imagen. Intenta de nuevo.', 'danger')
        return None


def _limitar_publico(nombre, max_req=15, ventana=300):
    """Limita peticiones por IP en rutas públicas (compartido entre workers vía limites_intentos). True si ya se excedió."""
    clave = f"{nombre}:{_ip_cliente()}"
    if limite_intentos_excedido(clave, max_req, ventana):
        return True
    registrar_intento_fallido(clave, ventana_seg=ventana)
    return False


def _ip_cliente():
    # Con ProxyFix, remote_addr ya es la IP real; no se lee X-Forwarded-For directo porque el cliente lo puede falsificar.
    return request.remote_addr or 'desconocida'


@login_manager.user_loader
def load_user(user_id):
    """user_id = "id:versión". Si la versión ya no coincide (contraseña cambiada o "cerrar sesión en todos lados"),
    la sesión deja de valer. Las sesiones viejas (solo "id") valen mientras la versión siga en 0."""
    uid, _, ver = str(user_id).partition(':')
    try:
        u = User.query.get(int(uid))
        ver = int(ver or 0)
    except (TypeError, ValueError):
        return None
    if u is None or ver != (u.sesion_version or 0):
        return None
    return u


def _cerrar_sesiones(u):
    """Invalida todas las sesiones abiertas del usuario (en cualquier aparato)."""
    u.sesion_version = (u.sesion_version or 0) + 1


@app.template_filter('opt_img')
def optimizar_imagen_cloudinary(url, ancho=500):
    if not url:
        return ''
    if 'res.cloudinary.com' in url and '/upload/' in url and 'q_auto' not in url:
        return url.replace('/upload/', f'/upload/f_auto,q_auto,w_{ancho}/')
    return url


def redirigir_segun_rol(user):
    if user.role == 'admin':
        return redirect('/industrial')
    if user.role == 'gerente':
        return redirect('/pos')
    if user.role == 'almacen':
        return redirect('/almacen_pro')
    if user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
    # Cajero y sucursal trabajan en la Caja: entran directo ahí.
    return redirect('/pos')


@app.route('/ping')
def ping_keep_alive():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "awake", "timestamp": ahora_local().strftime('%Y-%m-%d %H:%M:%S')}), 200
    except Exception as e:
        app.logger.exception(e)
        return jsonify({"status": "error"}), 500


@app.route('/api/traducir')
@login_required
def api_traducir():
    texto = request.args.get('q', '').strip()[:300]
    if not texto:
        return jsonify({"ok": False, "traduccion": ""})
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=es&tl=en&dt=t&q={urllib.parse.quote(texto)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            traduccion = "".join([parte[0] for parte in data[0] if parte[0]])
            return jsonify({"ok": True, "traduccion": traduccion})
    except Exception as e:
        app.logger.warning('Traducción falló: %s', e)
        return jsonify({"ok": False, "error": "No se pudo traducir en este momento."}), 502


# ==============================================================================
# MENÚ PÚBLICO, FIDELIDAD Y PRE-ÓRDENES
# ==============================================================================
def obtener_datos_menu(sucursal=None):
    """Carga categorías y productos en pocas consultas (sin N+1) como diccionarios ligeros.
    Con sucursal: precio de esa sucursal y sin los platillos que ahí no se venden."""
    categorias_bd = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    productos_bd = Producto.query.order_by(Producto.destacado.desc(), Producto.id.asc()).all()
    if sucursal:
        productos_bd = productos_para_sucursal(productos_bd, sucursal)
    prods_por_cat = {}
    for p in productos_bd:
        prods_por_cat.setdefault(p.categoria, []).append({
            'id': p.id, 'nombre': p.nombre, 'nombre_en': p.nombre_en,
            'descripcion': p.descripcion, 'descripcion_en': p.descripcion_en,
            'precio': p.precio, 'categoria': p.categoria,
            'imagen_url': p.imagen_url, 'destacado': p.destacado, 'agotado': p.agotado
        })
    categorias_dict = {}
    cat_traducciones = {}
    cat_iconos = {}
    for cat in categorias_bd:
        lista = prods_por_cat.get(cat.nombre)
        if lista:
            categorias_dict[cat.nombre] = lista
            cat_traducciones[cat.nombre] = cat.nombre_en if (cat.nombre_en and cat.nombre_en.strip()) else cat.nombre
            cat_iconos[cat.nombre] = {'icono': (cat.icono or '').strip(), 'imagen_url': cat.imagen_url or ''}
    return categorias_dict, cat_traducciones, cat_iconos


def obtener_meseros_eval():
    meseros = [u.username.capitalize() for u in User.query.filter_by(role='mesero').order_by(User.username.asc()).all()]
    return meseros if meseros else ['Paola', 'Daniel']


def obtener_contexto_publico(sucursal=None):
    """Cachea el menú público (uno por sucursal) en memoria por 45s para soportar cientos de comensales simultáneos."""
    clave_cache = f'menu_publico:{sucursal or "-"}'
    cached = cache_get(clave_cache, 45)
    if cached is not None:
        return cached

    categorias_dict, cat_traducciones, cat_iconos = obtener_datos_menu(sucursal)
    galeria = [{
        'imagen_url': g.imagen_url, 'titulo': g.titulo, 'descripcion': g.descripcion
    } for g in Galeria.query.order_by(Galeria.fecha_subida.desc()).all()]
    premios = [{
        'visitas_necesarias': p.visitas_necesarias, 'premio_es': p.premio_es, 'premio_en': p.premio_en
    } for p in Premio.query.order_by(Premio.visitas_necesarias.asc()).all()]
    anuncios_activos = [{
        'mensaje': a.mensaje, 'mensaje_en': a.mensaje_en, 'color': a.color,
        'imagen_url': a.imagen_url, 'texto_boton': a.texto_boton,
        'texto_boton_en': a.texto_boton_en, 'enlace': a.enlace, 'activo': a.activo
    } for a in Anuncio.query.filter_by(activo=True).order_by(Anuncio.id.desc()).all()]

    ctx = {
        'categorias': categorias_dict,
        'cat_traducciones': cat_traducciones,
        'cat_iconos': cat_iconos,
        'galeria': galeria,
        'premios': premios,
        'max_visitas': premios[-1]['visitas_necesarias'] if premios else 10,
        'metas_list': [p['visitas_necesarias'] for p in premios],
        'anuncios_activos': anuncios_activos,
        'anuncio': anuncios_activos[0] if anuncios_activos else None,
        'meseros_eval': obtener_meseros_eval()
    }
    return cache_set(clave_cache, ctx)


def _sucursal_publica():
    """Sucursal del comensal: ?suc=QM|C1|C2|C3 en el QR/NFC de la mesa. Se recuerda en su sesión para que no se
    pierda tras enviar un formulario. Un enlace de mesa SIN ?suc= (los QR/NFC ya instalados) vuelve a la Matriz."""
    codigo = request.args.get('suc', '').strip().upper()
    if codigo in PREFIJO_SUCURSAL.values():
        session['suc_publica'] = codigo
    elif 'mesa' in request.args or 'pin' in request.args:
        session.pop('suc_publica', None)
    return sucursal_desde_codigo(session.get('suc_publica'))


def _escape_wifi(valor):
    """Escapa los caracteres especiales del formato de QR de Wi-Fi (WIFI:T:WPA;S:...;P:...;;)."""
    return ''.join('\\' + ch if ch in '\\;,:"' else ch for ch in str(valor or ''))


def _contexto_sucursal_publica():
    suc = _sucursal_publica()
    datos = obtener_datos_ticket(suc)
    return {
        'sucursal_publica': suc,
        'suc_codigo': PREFIJO_SUCURSAL.get(suc, 'QM'),
        'wifi_red': datos.get('wifi_red', ''),
        'wifi_clave': datos.get('wifi_clave', ''),
        'wifi_qr_data': f"WIFI:T:WPA;S:{_escape_wifi(datos.get('wifi_red'))};P:{_escape_wifi(datos.get('wifi_clave'))};;",
    }


@app.route('/')
def index():
    ctx_suc = _contexto_sucursal_publica()
    return render_template('index.html', **obtener_contexto_publico(ctx_suc['sucursal_publica']), **ctx_suc)


@app.route('/qr.svg')
def qr_svg():
    """QR generado en el propio servidor (sin depender de api.qrserver.com): tickets, PINs, mesas y Wi-Fi."""
    data = request.args.get('data', '')
    if not data or len(data) > 300:
        abort(400, 'Texto de QR vacío o mayor a 300 caracteres.')
    try:
        tam = max(1, min(20, int(request.args.get('escala', 6))))
    except (TypeError, ValueError):
        tam = 6
    buf = BytesIO()
    segno.make(data, error='m', micro=False).save(buf, kind='svg', scale=tam, border=2, xmldecl=False)
    resp = Response(buf.getvalue(), mimetype='image/svg+xml')
    resp.headers['Content-Type'] = 'image/svg+xml'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


@app.route('/api/estado_menu_publico')
def api_estado_menu_publico():
    data = cache_get('estado_agotados', 15)
    if data is None:
        agotados = Producto.query.filter_by(agotado=True).all()
        data = {
            "agotados_ids": [p.id for p in agotados],
            "agotados_nombres": [p.nombre for p in agotados]
        }
        cache_set('estado_agotados', data)
    resp = jsonify(data)
    resp.headers['Cache-Control'] = 'public, max-age=10'
    return resp


@app.route('/crear_preorden', methods=['POST'])
def crear_preorden():
    if _limitar_publico('preorden', max_req=40, ventana=300):
        return jsonify({"ok": False, "error": "Demasiados pedidos seguidos desde este dispositivo. Espera unos minutos."}), 429
    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "Datos inválidos"}), 400
        mesa = _texto_publico(data.get('mesa', ''), 20)
        nombre = _texto_publico(data.get('cliente_nombre', ''), 80)
        items_txt = _texto_publico(data.get('detalle_items', ''), 2500)
        if not mesa or not nombre or not items_txt:
            return jsonify({"ok": False, "error": "Faltan datos de mesa o nombre"}), 400

        try:
            total_seguro = _numero_seguro(data.get('total', 0))
        except ValueError:
            return jsonify({"ok": False, "error": "Total inválido"}), 400
        nueva = PreOrden(
            mesa=mesa,
            cliente_nombre=nombre,
            modalidad=_texto_publico(data.get('modalidad', 'En Mesa'), 40),
            metodo_pago=_texto_publico(data.get('metodo_pago', 'Efectivo'), 40),
            detalle_items=items_txt,
            notas=_texto_publico(data.get('notas', ''), 300),
            total=total_seguro,
            estado="pendiente",
            fecha=ahora_local(),
            # ?suc= del QR/NFC (lo manda index.html); si no viene, la recordada en sesión; si no, Matriz.
            sucursal=sucursal_desde_codigo(data.get('suc') or session.get('suc_publica'))
        )
        db.session.add(nueva)
        db.session.commit()
        return jsonify({"ok": True, "folio": nueva.id, "hora": nueva.fecha.strftime('%H:%M')})
    except Exception as e:
        db.session.rollback()
        app.logger.exception(e)
        return jsonify({"ok": False, "error": "No se pudo registrar el pedido. Intenta de nuevo."}), 500


@app.route('/api/preordenes_pendientes')
@login_required
def api_preordenes_pendientes():
    if current_user.role not in ['admin', 'gerente', 'cajero', 'mesero', 'sucursal']:
        return jsonify({"total_pendientes": 0, "ordenes": []}), 403
    suc = sucursal_filtro(session)
    ordenes = _preordenes_pendientes(suc)
    q_pins = PinCaja.query.filter_by(activo=True)
    if suc:
        q_pins = q_pins.filter(PinCaja.sucursal == suc)
    resultado = [{
        "id": o.id, "mesa": o.mesa, "cliente_nombre": o.cliente_nombre, "sucursal": o.sucursal or SUCURSAL_DEFAULT,
        "modalidad": o.modalidad, "metodo_pago": o.metodo_pago,
        "detalle_items": o.detalle_items, "notas": o.notas or "",
        "total": o.total, "hora": o.fecha.strftime('%H:%M') if o.fecha else ""
    } for o in ordenes]
    return jsonify({
        "total_pendientes": len(resultado),
        "ordenes": resultado,
        "agotados_ids": [p.id for p in Producto.query.filter_by(agotado=True).all()],
        "pins_activos": q_pins.count()
    })


def _preordenes_pendientes(suc):
    """Pre-órdenes pendientes; suc=None (admin) = todas las sucursales."""
    q = PreOrden.query.filter_by(estado='pendiente')
    if suc:
        q = q.filter(PreOrden.sucursal == suc)
    return q.order_by(PreOrden.fecha.desc()).all()


def _pins_activos(suc):
    q = PinCaja.query.filter_by(activo=True)
    if suc:
        q = q.filter(PinCaja.sucursal == suc)
    return q.all()


def _registro_de_mi_sucursal(registro):
    """El admin opera cualquier sucursal; los demás roles solo registros de su sucursal activa."""
    suc = sucursal_filtro(session)
    return suc is None or (registro.sucursal or SUCURSAL_DEFAULT) == suc


@app.route('/atender_preorden/<int:id>', methods=['POST'])
@login_required
def atender_preorden(id):
    if current_user.role not in ['admin', 'gerente', 'cajero', 'mesero', 'sucursal']:
        return redirigir_segun_rol(current_user)
    orden = PreOrden.query.get_or_404(id)
    if not _registro_de_mi_sucursal(orden):
        flash('Esa pre-orden pertenece a otra sucursal.', 'danger')
        return redirigir_segun_rol(current_user)
    accion = request.form.get('accion', 'atendido')
    if accion not in ('atendido', 'cancelado'):
        accion = 'atendido'
    orden.estado = accion
    orden.atendido_por = current_user.username
    db.session.commit()
    if accion == 'cancelado':
        flash(f'Pre-Orden #{orden.id} (Mesa {orden.mesa}) cancelada.', 'danger')
    else:
        flash(f'Pre-Orden #{orden.id} (Mesa {orden.mesa}) confirmada por {current_user.username.capitalize()}.', 'success')
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if current_user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
    return redirect(url_for('cajero_dashboard'))


@app.route('/registrar_consumo', methods=['POST'])
def registrar_consumo():
    nombre = _texto_publico(request.form.get('nombre', ''), 101)
    telefono = request.form.get('telefono', '').strip()
    pin_ingresado = request.form.get('pin', '').upper().strip()

    clave_rl = f"pin:{_ip_cliente()}"
    if limite_intentos_excedido(clave_rl, 10, 300):
        flash('Demasiados intentos. Espera unos minutos e inténtalo de nuevo.', 'error')
        return redirect(url_for('index'))
    if not nombre or len(nombre) > 100 or not (telefono.isdigit() and len(telefono) == 10):
        flash('Escribe tu nombre y un teléfono de 10 dígitos.', 'error')
        return redirect(url_for('index'))

    # El PIN se "reclama" con un UPDATE condicional: si dos personas lo usan a la vez, solo una lo consigue.
    reclamado = PinCaja.query.filter_by(codigo=pin_ingresado, activo=True).update(
        {'activo': False, 'usado_por': f"{nombre} ({telefono})", 'fecha_uso': ahora_local()},
        synchronize_session=False
    )
    if reclamado != 1:
        db.session.rollback()
        registrar_intento_fallido(clave_rl)
        flash('PIN inválido o ya utilizado.', 'error')
        return redirect(url_for('index'))

    cliente = Cliente.query.filter_by(telefono=telefono).first()
    premios_bd = Premio.query.order_by(Premio.visitas_necesarias.asc()).all()
    if not cliente:
        cliente = Cliente(telefono=telefono, nombre=nombre, visitas=1, fecha_registro=ahora_local())
        db.session.add(cliente)
    else:
        cliente.visitas += 1
        cliente.nombre = nombre
        if premios_bd and cliente.visitas > premios_bd[-1].visitas_necesarias:
            cliente.visitas = 1

    premio_actual = next((p for p in premios_bd if p.visitas_necesarias == cliente.visitas), None)
    if premio_actual:
        db.session.add(HistorialPremio(
            cliente_nombre=nombre, telefono=telefono,
            premio_ganado=premio_actual.premio_es, visitas_alcanzadas=cliente.visitas,
            entregado=False, fecha=ahora_local()
        ))
        flash(f'¡META ALCANZADA! Muestra esto en caja: {premio_actual.premio_es}', 'premio_interactivo')
    else:
        flash(f'¡Visita sellada, {nombre}! Llevas {cliente.visitas} consumos.', 'success')

    db.session.commit()
    limpiar_intentos(clave_rl)  # después del commit: solo se limpia si la visita sí quedó guardada
    return render_template(
        'index.html', cliente=cliente, progreso=cliente.visitas,
        premio_actual=premio_actual, **obtener_contexto_publico(_sucursal_publica()), **_contexto_sucursal_publica()
    )


@app.route('/enviar_evaluacion', methods=['POST'])
def enviar_evaluacion():
    if _limitar_publico('evaluacion', max_req=20, ventana=600):
        flash('Demasiados envíos seguidos. Intenta en unos minutos.', 'error')
        return redirect(url_for('index'))
    try:
        cal_mesero = int(request.form.get('mesero_calificacion', ''))
        cal_limpieza = int(request.form.get('limpieza', ''))
        cal_comida = int(request.form.get('calidad_comida', ''))
    except (TypeError, ValueError):
        cal_mesero = cal_limpieza = cal_comida = 0
    if not all(1 <= v <= 5 for v in (cal_mesero, cal_limpieza, cal_comida)):
        flash('Selecciona una calificación válida.', 'error')
        return redirect(url_for('index'))
    db.session.add(Evaluacion(
        mesero_nombre=_texto_publico(request.form.get('mesero_nombre'), 80),
        mesero_calificacion=cal_mesero,
        limpieza=cal_limpieza,
        calidad_comida=cal_comida,
        comentarios=_texto_publico(request.form.get('comentarios', ''), 600),
        fecha=ahora_local()
    ))
    db.session.commit()
    flash('¡Gracias por tu evaluación!', 'success')
    return redirect(url_for('index'))


# ==============================================================================
# AUTENTICACIÓN Y PANELES PRINCIPALES CON RBAC ESTRICTO
# ==============================================================================
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        return redirigir_segun_rol(current_user)
    if request.method == 'POST':
        username_input = request.form.get('username', '').strip().lower()
        password_input = request.form.get('password', '')
        clave_rl = f"login:{username_input}"
        if limite_intentos_excedido(clave_rl, 8, 300):
            flash('Demasiados intentos fallidos. Espera 5 minutos e inténtalo de nuevo.', 'error')
            return render_template('admin_login.html')
        user = User.query.filter(db.func.lower(User.username) == username_input).first()
        if user and check_password_hash(user.password, password_input):
            limpiar_intentos(clave_rl)
            session.permanent = True
            login_user(user, remember=True, duration=timedelta(days=365))
            if user.role == 'admin':
                session['sucursal_activa'] = user.sucursal or 'Quiosco Morisco (Matriz)'
            return redirigir_segun_rol(user)
        registrar_intento_fallido(clave_rl)
        flash('Usuario o contraseña incorrectos.', 'error')
    return render_template('admin_login.html')


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    """Cerrar sesión solo por POST con token CSRF (_verificar_csrf). Así otra página no puede sacar al cajero
    a mitad del turno con un simple enlace/imagen. Los botones "Salir" (<a href="/logout">) se convierten en POST
    desde templates/_csrf.html; si el JS fallara, este GET muestra un botón para confirmar."""
    if request.method == 'GET':
        if not current_user.is_authenticated:
            return redirect(url_for('admin_login'))
        return render_template('logout_confirmar.html')
    session.clear()
    logout_user()
    resp = redirect(url_for('admin_login'))
    resp.delete_cookie('remember_token')
    resp.delete_cookie('session')
    return resp


@app.route('/admin/cargar_menu_quiosco', methods=['POST'])
@login_required
def admin_cargar_menu_quiosco():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    creados, actualizados = cargar_menu_quiosco_oficial()
    flash(f'✅ Menú Quiosco Morisco sincronizado: {creados} nuevos, {actualizados} actualizados + modificadores guiados listos.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/actualizar_db')
@login_required
def actualizar_db():
    if current_user.role != 'admin' or request.args.get('confirmar') != 'si':
        return "<h1>🔒 Ruta protegida</h1>", 403
    inicializar_sistema(app)
    return "<h1>✅ Tablas verificadas sin borrar tus datos.</h1><a href='/admin_dashboard'>Volver</a>"


@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)

    hoy_inicio = inicio_hoy_local()
    hace_7_dias = hoy_inicio - timedelta(days=7)
    hace_30_dias = hoy_inicio - timedelta(days=30)

    ordenes_hoy = PreOrden.query.filter(PreOrden.fecha >= hoy_inicio, PreOrden.estado == 'atendido', PreOrden.total > 0).all()
    ordenes_semana = PreOrden.query.filter(PreOrden.fecha >= hace_7_dias, PreOrden.estado == 'atendido', PreOrden.total > 0).all()
    ordenes_mes = PreOrden.query.filter(PreOrden.fecha >= hace_30_dias, PreOrden.estado == 'atendido', PreOrden.total > 0).all()

    pins_hoy = PinCaja.query.filter(PinCaja.fecha_creacion >= hoy_inicio).all()
    resumen_cajeros = {}
    for p in pins_hoy:
        autor = (p.creado_por or 'caja').capitalize()
        resumen_cajeros.setdefault(autor, {'generados': 0, 'usados': 0, 'activos': 0})
        resumen_cajeros[autor]['generados'] += 1
        resumen_cajeros[autor]['activos' if p.activo else 'usados'] += 1

    return render_template(
        'admin_dashboard.html',
        sucursales=SUCURSALES_OFICIALES,
        categorias=CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all(),
        iconos_categoria=ICONOS_CATEGORIA,
        premios=Premio.query.order_by(Premio.visitas_necesarias.asc()).all(),
        historial_premios=HistorialPremio.query.order_by(HistorialPremio.id.desc()).limit(40).all(),
        productos=Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all(),
        pins=PinCaja.query.filter_by(activo=True).all(),
        historial_pins=PinCaja.query.order_by(PinCaja.id.desc()).limit(60).all(),
        resumen_cajeros=resumen_cajeros, total_pins_hoy=len(pins_hoy),
        ventas_hoy=round(sum(o.total for o in ordenes_hoy), 2), pedidos_hoy=len(ordenes_hoy),
        ventas_semana=round(sum(o.total for o in ordenes_semana), 2), pedidos_semana=len(ordenes_semana),
        ventas_mes=round(sum(o.total for o in ordenes_mes), 2), pedidos_mes=len(ordenes_mes),
        usuarios=User.query.order_by(User.role.asc(), User.username.asc()).all(),
        preordenes=PreOrden.query.filter_by(estado='pendiente').order_by(PreOrden.fecha.desc()).all(),
        evaluaciones=Evaluacion.query.order_by(Evaluacion.fecha.desc()).limit(30).all(),
        clientes_top=Cliente.query.order_by(Cliente.visitas.desc(), Cliente.fecha_registro.desc()).limit(30).all(),
        galeria=Galeria.query.order_by(Galeria.fecha_subida.desc()).all(),
        anuncios=Anuncio.query.order_by(Anuncio.id.desc()).all(),
        total_clientes=Cliente.query.count(),
        total_visitas=db.session.query(db.func.sum(Cliente.visitas)).scalar() or 0,
        promedio_est=round(db.session.query(db.func.avg(Evaluacion.mesero_calificacion)).scalar() or 0, 1)
    )


@app.route('/cajero_dashboard')
@login_required
def cajero_dashboard():
    if current_user.role not in ['gerente', 'cajero', 'sucursal']:
        return redirigir_segun_rol(current_user)
    hoy_inicio = inicio_hoy_local()
    suc = obtener_sucursal_activa(session)  # este panel no lo usa el admin: siempre filtra por sucursal
    return render_template(
        'cajero_dashboard.html',
        sucursal=suc,
        pins=_pins_activos(suc),
        preordenes=_preordenes_pendientes(suc),
        mis_pins_hoy=PinCaja.query.filter(PinCaja.creado_por == current_user.username, PinCaja.fecha_creacion >= hoy_inicio).count(),
        historial_caja_hoy=PinCaja.query.filter(PinCaja.fecha_creacion >= hoy_inicio, PinCaja.sucursal == suc)
                                        .order_by(PinCaja.id.desc()).limit(30).all()
    )


@app.route('/mesero_dashboard')
@login_required
def mesero_dashboard():
    if current_user.role not in ['admin', 'gerente', 'cajero', 'mesero', 'sucursal']:
        return redirigir_segun_rol(current_user)
    return render_template(
        'mesero_dashboard.html',
        sucursal=obtener_sucursal_activa(session),
        sucursales=SUCURSALES_OFICIALES,
        preordenes=_preordenes_pendientes(sucursal_filtro(session)),
        productos=productos_para_sucursal(Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all(), obtener_sucursal_activa(session))
    )


# ==============================================================================
# CRUD ADMINISTRATIVO (USUARIOS, MENÚ, GALERÍA, BANNERS, PREMIOS, PINS, CSV)
# ==============================================================================
@app.route('/admin/usuario/nuevo', methods=['POST'])
@login_required
def nuevo_usuario():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'mesero')
    sucursal = request.form.get('sucursal', 'Quiosco Morisco (Matriz)')
    if role not in ('admin', 'gerente', 'cajero', 'mesero', 'sucursal', 'almacen') or sucursal not in SUCURSALES_OFICIALES:
        flash('Rol o sucursal inválidos.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if username and len(password) < 8:
        flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if username and password:
        if User.query.filter(db.func.lower(User.username) == username).first():
            flash('Ese nombre de usuario ya existe.', 'danger')
        else:
            db.session.add(User(username=username, password=generate_password_hash(password), role=role, sucursal=sucursal))
            db.session.commit()
            invalidar_cache_publico()
            flash(f'Usuario {username} ({role} • {sucursal}) creado con éxito.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/usuario/cambiar_pass/<int:id>', methods=['POST'])
@login_required
def cambiar_pass_usuario(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    u = User.query.get_or_404(id)
    nueva_pass = request.form.get('nueva_password', '').strip()
    if nueva_pass and len(nueva_pass) < 8:
        flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if nueva_pass:
        u.password = generate_password_hash(nueva_pass)
        _cerrar_sesiones(u)   # con la contraseña nueva, nadie sigue dentro con la vieja
        db.session.commit()
        if u.id == current_user.id:
            login_user(u, remember=True, duration=timedelta(days=365))   # quien la cambió sigue trabajando
        registrar_bitacora('CAMBIO_PASSWORD', u.username.upper(), 0.0, 'Contraseña cambiada; se cerraron sus sesiones')
        flash(f'Contraseña de {u.username} actualizada. Se cerró su sesión en todos los aparatos.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/usuario/cerrar_sesiones/<int:id>', methods=['POST'])
@login_required
def cerrar_sesiones_usuario(id):
    """Tablet o celular perdido: saca a esa persona de todos los aparatos de inmediato."""
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    u = User.query.get_or_404(id)
    _cerrar_sesiones(u)
    db.session.commit()
    if u.id == current_user.id:
        login_user(u, remember=True, duration=timedelta(days=365))
    registrar_bitacora('CERRAR_SESIONES', u.username.upper(), 0.0, 'Se cerró su sesión en todos los aparatos')
    flash(f'Listo: {u.username} quedó fuera de todos los aparatos. Tendrá que volver a entrar con su contraseña.', 'success')
    return redirect(url_for('admin_dashboard'))


ROLES_PIN_RAPIDO = ('admin', 'gerente', 'cajero', 'sucursal')


def _usuario_con_pin(pin, excluir_id=None):
    for u in User.query.filter(User.pin_rapido.isnot(None)).all():
        if u.id != excluir_id and check_password_hash(u.pin_rapido, pin):
            return u
    return None


@app.route('/admin/usuario/pin/<int:id>', methods=['POST'])
@login_required
def pin_usuario(id):
    """PIN de 4 a 6 dígitos para cambiar de usuario en la caja sin cerrar sesión (vacío = quitarlo)."""
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    u = User.query.get_or_404(id)
    pin = request.form.get('pin', '').strip()
    if not pin:
        u.pin_rapido = None
        db.session.commit()
        flash(f'PIN de {u.username} eliminado.', 'success')
        return redirect(url_for('admin_dashboard'))
    if u.role not in ROLES_PIN_RAPIDO:
        flash('El PIN de caja es solo para cajeros, sucursales, gerentes y admin.', 'danger')
    elif not (pin.isdigit() and 4 <= len(pin) <= 6):
        flash('El PIN debe ser de 4 a 6 números.', 'danger')
    elif _usuario_con_pin(pin, excluir_id=u.id):
        flash('Ese PIN ya lo tiene otro usuario. Elige otro.', 'danger')
    else:
        u.pin_rapido = generate_password_hash(pin)
        db.session.commit()
        flash(f'PIN de caja de {u.username} guardado.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/api/usuarios/<int:id>/permisos', methods=['GET', 'POST'])
@login_required
def api_permisos_usuario(id):
    """Permisos propios de un usuario. null = usa el permiso general de caja."""
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    u = User.query.get_or_404(id)
    if request.method == 'POST':
        d = request.get_json(silent=True) or {}
        propios = permisos_propios(u)
        for k, _, _ in PERMISOS_USUARIO:
            if k in d:
                if d[k] is None:
                    propios.pop(k, None)
                else:
                    propios[k] = bool(d[k])
        u.permisos_json = json.dumps(propios) if propios else None
        db.session.commit()
        registrar_bitacora('PERMISOS_USUARIO', u.username.upper(), 0.0,
                           ', '.join(f"{k}={'SI' if v else 'NO'}" for k, v in propios.items()) or 'usa los generales')
    propios = permisos_propios(u)
    return jsonify({'ok': True, 'usuario': u.username.upper(), 'rol': u.role,
                    'siempre_todo': u.role in ('admin', 'gerente'),
                    'permisos': [{'clave': k, 'texto': t, 'propio': propios.get(k), 'efectivo': tiene_permiso(k, u)}
                                 for k, t, _ in PERMISOS_USUARIO]})


@app.route('/api/cambiar_usuario_pin', methods=['POST'])
@login_required
def api_cambiar_usuario_pin():
    """Cambio rápido de cajero en la misma computadora: el que llega teclea su PIN y queda trabajando
    con su usuario (cancelaciones, cobros y cortes salen a su nombre)."""
    if current_user.role not in ROLES_PIN_RAPIDO:
        return jsonify({'ok': False, 'msg': 'Sin permiso.'}), 403
    clave_rl = f"pinrapido:{_ip_cliente()}"
    if limite_intentos_excedido(clave_rl, 6, 300):
        return jsonify({'ok': False, 'msg': 'Demasiados intentos. Espera 5 minutos.'}), 429
    pin = str((request.get_json(silent=True) or {}).get('pin', '')).strip()
    u = _usuario_con_pin(pin) if (pin.isdigit() and 4 <= len(pin) <= 6) else None
    if not u or u.role not in ROLES_PIN_RAPIDO:
        registrar_intento_fallido(clave_rl, ventana_seg=300)
        return jsonify({'ok': False, 'msg': 'PIN incorrecto.'}), 401
    limpiar_intentos(clave_rl)
    anterior = current_user.username.upper()
    suc_actual = session.get('sucursal_activa')
    login_user(u, remember=True, duration=timedelta(days=365))
    if u.role == 'admin' and suc_actual:
        session['sucursal_activa'] = suc_actual
    registrar_bitacora('CAMBIO_USUARIO', '', 0.0, f'{anterior} -> {u.username.upper()}', autorizo=u.username.upper())
    return jsonify({'ok': True, 'usuario': u.username.upper(), 'rol': u.role})


@app.route('/admin/usuario/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_usuario(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    u = User.query.get_or_404(id)
    if u.id == current_user.id:
        flash('No puedes eliminar tu propio usuario activo.', 'danger')
    else:
        nombre_u = u.username
        db.session.delete(u)
        db.session.commit()
        invalidar_cache_publico()
        flash(f'Usuario {nombre_u} eliminado.', 'success')
    return redirect(url_for('admin_dashboard'))


def _respuesta_csv_excel(encabezados, filas, nombre_archivo):
    def generate():
        data = StringIO()
        data.write('\ufeff')  # BOM UTF-8 para abrir acentos y ñ perfecto en Excel
        writer = csv.writer(data)
        writer.writerow(encabezados)
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for f in filas:
            writer.writerow(f)
            yield data.getvalue(); data.seek(0); data.truncate(0)
    resp = Response(generate(), mimetype='text/csv; charset=utf-8')
    resp.headers.set("Content-Disposition", "attachment", filename=nombre_archivo)
    return resp


@app.route('/admin/exportar_clientes')
@login_required
def exportar_clientes():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    filas = [(c.id, c.nombre, c.telefono, c.visitas, c.fecha_registro.strftime('%Y-%m-%d')) for c in Cliente.query.all()]
    return _respuesta_csv_excel(('ID', 'Nombre', 'Teléfono', 'Visitas', 'Fecha_Registro'), filas, 'Base_Clientes_ComensalConectado.csv')


@app.route('/admin/exportar_evaluaciones')
@login_required
def exportar_evaluaciones():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    filas = [(e.id, e.mesero_nombre, e.mesero_calificacion, e.limpieza, e.calidad_comida, e.comentarios, e.fecha.strftime('%Y-%m-%d')) for e in Evaluacion.query.all()]
    return _respuesta_csv_excel(('ID', 'Mesero', 'Calificación', 'Limpieza', 'Comida', 'Comentarios', 'Fecha'), filas, 'Evaluaciones_Meseros.csv')


@app.route('/admin/exportar_pins')
@login_required
def exportar_pins():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    filas = []
    for p in PinCaja.query.order_by(PinCaja.id.desc()).all():
        filas.append((
            p.id, p.codigo, p.creado_por or 'caja', p.folio_sr or '',
            p.fecha_creacion.strftime('%Y-%m-%d %H:%M') if p.fecha_creacion else '',
            'Pendiente' if p.activo else 'Sellado', p.usado_por or '',
            p.fecha_uso.strftime('%Y-%m-%d %H:%M') if p.fecha_uso else ''
        ))
    return _respuesta_csv_excel(('ID', 'PIN', 'Emitido_Por', 'Folio_Caja', 'Fecha_Creacion', 'Estado', 'Canjeado_Por', 'Fecha_Canje'), filas, 'Auditoria_PINs_ComensalConectado.csv')


@app.route('/admin/exportar_preordenes')
@login_required
def exportar_preordenes():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    filas = [(
        o.id, o.mesa, o.cliente_nombre, o.modalidad, o.metodo_pago,
        o.detalle_items.replace('\n', ' | '), o.total, o.estado,
        o.atendido_por or '', o.fecha.strftime('%Y-%m-%d %H:%M') if o.fecha else ''
    ) for o in PreOrden.query.order_by(PreOrden.id.desc()).all()]
    return _respuesta_csv_excel(('Folio', 'Mesa', 'Cliente', 'Modalidad', 'Pago', 'Detalle', 'Total', 'Estado', 'Atendido_Por', 'Fecha'), filas, 'Reporte_PreOrdenes.csv')


@app.route('/admin/premio/nuevo', methods=['POST'])
@login_required
def nuevo_premio():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    try:
        visitas = int(request.form.get('visitas', ''))
    except (TypeError, ValueError):
        visitas = 0
    if visitas <= 0 or visitas > 1000:
        flash('Las visitas necesarias deben ser un número entero mayor a 0.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if Premio.query.filter_by(visitas_necesarias=visitas).first():
        flash('Ya existe una meta con ese número de visitas.', 'danger')
    else:
        db.session.add(Premio(visitas_necesarias=visitas, premio_es=request.form.get('premio_es'), premio_en=request.form.get('premio_en', '')))
        db.session.commit()
        invalidar_cache_publico()
        flash('Meta de fidelidad agregada.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/premio/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_premio(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    db.session.delete(Premio.query.get_or_404(id))
    db.session.commit()
    invalidar_cache_publico()
    flash('Meta eliminada.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/premio_entregado/<int:id>', methods=['POST'])
@login_required
def marcar_premio_entregado(id):
    if current_user.role not in ['admin', 'gerente', 'cajero']:
        return redirigir_segun_rol(current_user)
    hp = HistorialPremio.query.get_or_404(id)
    hp.entregado = True
    hp.entregado_por = current_user.username
    db.session.commit()
    flash(f'Premio ({hp.premio_ganado}) de {hp.cliente_nombre} marcado como entregado.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/categoria/nueva', methods=['POST'])
@login_required
def nueva_categoria():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    nombre = request.form.get('nombre', '').strip()
    if nombre and not CategoriaMenu.query.filter_by(nombre=nombre).first():
        db.session.add(CategoriaMenu(nombre=nombre, nombre_en=request.form.get('nombre_en', '')))
        db.session.commit()
        invalidar_cache_publico()
    return redirect(url_for('admin_dashboard'))


ICONOS_CATEGORIA = ['🍳', '🥐', '🥞', '🥨', '🥪', '🍔', '🌮', '🌯', '🥗', '🍝', '🍕', '🍗', '🥩', '🍤', '🍟',
                    '🍰', '🍨', '🍪', '☕', '🍵', '🧋', '🧊', '🍹', '🍊', '🥤', '🍋', '🍺', '🍷', '🍽️']


@app.route('/admin/categoria/<int:id>/icono', methods=['POST'])
@login_required
def icono_categoria(id):
    """Cambia el ícono (emoji de la lista) o la foto de una categoría del menú."""
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    cat = CategoriaMenu.query.get_or_404(id)
    icono = request.form.get('icono', '').strip()
    if icono in ICONOS_CATEGORIA or icono == '':
        cat.icono = icono or None
    foto = request.files.get('foto')
    if foto and foto.filename:
        url = _subir_imagen(foto)
        if url:
            cat.imagen_url = url
    if request.form.get('quitar_foto') == '1':
        cat.imagen_url = None
    db.session.commit()
    invalidar_cache_publico()
    flash(f'Categoría {cat.nombre}: ícono actualizado.', 'success')
    return redirect(url_for('admin_dashboard') + '#categorias')


@app.route('/admin/categoria/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_categoria(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    cat = CategoriaMenu.query.get_or_404(id)
    if Producto.query.filter_by(categoria=cat.nombre).first():
        flash('No puedes borrar una categoría en uso.', 'danger')
    else:
        db.session.delete(cat)
        db.session.commit()
        invalidar_cache_publico()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/producto/nuevo', methods=['POST'])
@login_required
def nuevo_producto():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    img_url = _subir_imagen(request.files['foto']) if ('foto' in request.files and request.files['foto'].filename != '') else None
    nuevo = Producto(
        nombre=request.form['nombre'], nombre_en=request.form.get('nombre_en', ''),
        descripcion=request.form['descripcion'], descripcion_en=request.form.get('descripcion_en', ''),
        precio=_precio_form(), categoria=request.form['categoria'],
        imagen_url=img_url, destacado=(request.form.get('destacado') == 'on'),
        agotado=(request.form.get('agotado') == 'on')
    )
    db.session.add(nuevo)
    db.session.commit()
    _guardar_area_producto(nuevo.id, request.form.get('area_impresion'))
    invalidar_cache_publico()
    return redirect(url_for('admin_dashboard'))


def _guardar_area_producto(producto_id, area):
    """Dónde se imprime el platillo (la misma configuración que usa la Caja). Vacío = automática por categoría."""
    area = (area or '').strip().upper()
    areas = _cargar_areas_prods()
    if area in ('COCINA', 'BARRA'):
        areas[str(producto_id)] = area
    else:
        areas.pop(str(producto_id), None)
    _guardar_areas_prods(areas)


@app.route('/admin/producto/toggle_destacado/<int:id>', methods=['POST'])
@login_required
def toggle_destacado(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    p = Producto.query.get_or_404(id)
    p.destacado = not p.destacado
    db.session.commit()
    invalidar_cache_publico()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"ok": True, "destacado": p.destacado})
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/producto/toggle_agotado/<int:id>', methods=['POST'])
@login_required
def toggle_agotado(id):
    if current_user.role not in ['admin', 'gerente', 'mesero', 'cajero', 'sucursal']:
        return jsonify({"ok": False}), 403
    p = Producto.query.get_or_404(id)
    p.agotado = not p.agotado
    db.session.commit()
    invalidar_cache_publico()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"ok": True, "agotado": p.agotado})
    if current_user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/producto/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_producto(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    p = Producto.query.get_or_404(id)
    if request.method == 'POST':
        p.nombre, p.nombre_en = request.form['nombre'], request.form.get('nombre_en', '')
        p.descripcion, p.descripcion_en = request.form['descripcion'], request.form.get('descripcion_en', '')
        p.precio, p.categoria = _precio_form(), request.form['categoria']
        p.destacado = (request.form.get('destacado') == 'on')
        p.agotado = (request.form.get('agotado') == 'on')
        if 'foto' in request.files and request.files['foto'].filename != '':
            _nueva_img = _subir_imagen(request.files['foto'])
            if _nueva_img:  # si falla la subida se conserva la foto actual
                p.imagen_url = _nueva_img
        db.session.commit()
        _guardar_area_producto(p.id, request.form.get('area_impresion'))
        invalidar_cache_publico()
        flash('Platillo actualizado correctamente.', 'success')
        return redirect(url_for('admin_dashboard'))
    return redirect(f'/platillos#p{p.id}')   # todo el platillo se edita en Menú y Platillos


@app.route('/admin/producto/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_producto(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    db.session.delete(Producto.query.get_or_404(id))
    db.session.commit()
    invalidar_cache_publico()
    return redirect(url_for('admin_dashboard'))


@app.route('/agregar_galeria', methods=['POST'])
@login_required
def agregar_galeria():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    if 'foto' in request.files and request.files['foto'].filename != '':
        url_g = _subir_imagen(request.files['foto'])
        if url_g:
            db.session.add(Galeria(
                imagen_url=url_g,
                titulo=request.form.get('titulo', '')[:100], descripcion=request.form.get('descripcion', '')[:250],
                fecha_subida=ahora_local()
            ))
            db.session.commit()
            invalidar_cache_publico()
    return redirect(url_for('admin_dashboard'))


@app.route('/editar_galeria/<int:id>', methods=['POST'])
@login_required
def editar_galeria(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    g = Galeria.query.get_or_404(id)
    g.titulo = request.form.get('titulo', '')
    g.descripcion = request.form.get('descripcion', '')
    db.session.commit()
    invalidar_cache_publico()
    flash('Foto de galería actualizada.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/eliminar_galeria/<int:id>', methods=['POST'])
@login_required
def eliminar_galeria(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    db.session.delete(Galeria.query.get_or_404(id))
    db.session.commit()
    invalidar_cache_publico()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/anuncio/nuevo', methods=['POST'])
@login_required
def nuevo_anuncio():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    img_url = _subir_imagen(request.files['foto']) if ('foto' in request.files and request.files['foto'].filename != '') else None
    db.session.add(Anuncio(
        mensaje=request.form.get('mensaje', 'Sin mensaje'), mensaje_en=request.form.get('mensaje_en', ''),
        color=request.form.get('color', 'bg-dark text-white'), imagen_url=img_url,
        texto_boton=request.form.get('texto_boton', ''), texto_boton_en=request.form.get('texto_boton_en', ''),
        enlace=request.form.get('enlace', ''), activo=(request.form.get('activo') == 'on')
    ))
    db.session.commit()
    invalidar_cache_publico()
    flash('Portada agregada al carrusel.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/anuncio/toggle/<int:id>', methods=['POST'])
@login_required
def toggle_anuncio(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    an = Anuncio.query.get_or_404(id)
    an.activo = not an.activo
    db.session.commit()
    invalidar_cache_publico()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/anuncio/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_anuncio(id):
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    db.session.delete(Anuncio.query.get_or_404(id))
    db.session.commit()
    invalidar_cache_publico()
    return redirect(url_for('admin_dashboard'))


@app.route('/caja/generar_pin', methods=['POST'])
@login_required
def generar_pin():
    if current_user.role not in ['admin', 'gerente', 'cajero', 'sucursal']:
        return redirigir_segun_rol(current_user)
    try:
        cantidad = max(1, min(30, int(request.form.get('cantidad', 1))))
    except (TypeError, ValueError):
        cantidad = 1
    folio_sr = request.form.get('folio_sr', '').strip()[:50]
    ahora = ahora_local()
    suc_pin = obtener_sucursal_activa(session)
    for _ in range(cantidad):
        db.session.add(PinCaja(
            codigo=generar_pin_unico(), creado_por=current_user.username,
            folio_sr=folio_sr, fecha_creacion=ahora, sucursal=suc_pin
        ))
    db.session.commit()
    flash(f'Se generaron {cantidad} PIN(s) a nombre de {current_user.username.capitalize()}.', 'success')
    return redirect(url_for('admin_dashboard' if current_user.role == 'admin' else 'cajero_dashboard'))


@app.route('/caja/eliminar_pin/<int:id>', methods=['POST'])
@login_required
def eliminar_pin_individual(id):
    if current_user.role not in ['admin', 'gerente', 'cajero', 'sucursal']:
        return redirigir_segun_rol(current_user)
    pin = PinCaja.query.get_or_404(id)
    if not _registro_de_mi_sucursal(pin):
        flash('Ese PIN pertenece a otra sucursal.', 'danger')
        return redirigir_segun_rol(current_user)
    cod = pin.codigo
    db.session.delete(pin)
    db.session.commit()
    flash(f'PIN {cod} anulado.', 'success')
    return redirect(url_for('admin_dashboard' if current_user.role == 'admin' else 'cajero_dashboard'))


@app.route('/api/admin/datos_ticket', methods=['GET', 'POST'])
@login_required
def api_admin_datos_ticket():
    """Datos fiscales del ticket y Wi-Fi por sucursal, editables por el admin (se guardan en config_pos)."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Admin.'}), 403
    if request.method == 'GET':
        return jsonify({'ok': True, 'campos': list(CAMPOS_DATOS_TICKET),
                        'sucursales': {s: obtener_datos_ticket(s) for s in SUCURSALES_OFICIALES}})
    data = request.get_json(silent=True) or {}
    suc = str(data.get('sucursal', '')).strip()
    if suc not in SUCURSALES_OFICIALES:
        return jsonify({'ok': False, 'msg': 'Sucursal inválida.'}), 400
    nuevos = {}
    for campo, largo in CAMPOS_DATOS_TICKET.items():
        valor = str((data.get('datos') or {}).get(campo, '')).strip()
        if len(valor) > largo:
            return jsonify({'ok': False, 'msg': f'"{campo}" admite máximo {largo} caracteres.'}), 400
        nuevos[campo] = valor
    if nuevos['rfc'] and not re.fullmatch(r'[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}', nuevos['rfc'].upper()):
        return jsonify({'ok': False, 'msg': 'RFC con formato inválido (12 o 13 caracteres).'}), 400
    nuevos['rfc'] = nuevos['rfc'].upper()
    if nuevos['wifi_clave'] and len(nuevos['wifi_clave']) < 8:
        return jsonify({'ok': False, 'msg': 'La clave de Wi-Fi (WPA) debe tener al menos 8 caracteres.'}), 400
    todo = cfg_cargar(CLAVE_CFG_DATOS_TICKET, {})
    todo = todo if isinstance(todo, dict) else {}
    todo[suc] = nuevos
    cfg_guardar(CLAVE_CFG_DATOS_TICKET, todo)
    invalidar_cache_publico()  # tickets, menú público (Wi-Fi) y otros workers ven el cambio
    registrar_bitacora('DATOS_TICKET', suc, 0.0, 'Datos de ticket / Wi-Fi actualizados', sucursal=suc)
    return jsonify({'ok': True, 'datos': obtener_datos_ticket(suc)})


@app.route('/admin/limpiar_pins_activos', methods=['POST'])
@login_required
def limpiar_pins_activos():
    if current_user.role != 'admin':
        return redirigir_segun_rol(current_user)
    borrados = PinCaja.query.filter_by(activo=True).delete()
    db.session.commit()
    flash(f'Se limpiaron {borrados} PIN(s) pendientes sin usar.', 'success')
    return redirect(url_for('admin_dashboard'))


if os.environ.get('RUN_DB_INIT', '0') == '1':
    inicializar_sistema(app)
else:
    # Red de seguridad: si falta cualquier tabla/columna de models.ESQUEMA_REQUERIDO (primer deploy de una
    # versión nueva), se migra sola aunque RUN_DB_INIT no esté activo (ALTER ... IF NOT EXISTS, sin borrar datos).
    # Si no, la app consultaría columnas inexistentes y se caería.
    try:
        with app.app_context():
            _faltan = esquema_faltante(db.engine)
            if _faltan:
                app.logger.warning('Esquema incompleto, migrando: %s', ', '.join(_faltan))
                inicializar_sistema(app)
                _siguen = esquema_faltante(db.engine)
                if _siguen:
                    app.logger.error('Tras migrar siguen faltando: %s', ', '.join(_siguen))
    except Exception as _e_init:
        print('Aviso: no se pudo verificar el esquema al arrancar:', _e_init)

if __name__ == '__main__':
    inicializar_sistema(app)
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', port=10000)