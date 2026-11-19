from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import cloudinary
import cloudinary.uploader
import random
import string
import csv
from io import StringIO
import urllib.request
import urllib.parse
import json

app = Flask(__name__)
app.secret_key = 'clave_secreta_quiosco'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=365)

# --- CONFIGURACIÓN DE CLOUDINARY ---
cloudinary.config(
    cloud_name = "sgz4qrxq",
    api_key = "881332363648736",
    api_secret = "I7go-7PnNv1DQLJiGdkMB5wtXkc",
    secure = True
)

# --- CONFIGURACIÓN DE BASE DE DATOS ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://neondb_owner:npg_MdstoSpT2lu8@ep-blue-butterfly-befvzhn4-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True, "pool_recycle": 300}

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'
login_manager.login_message = None

# --- OPTIMIZADOR AUTOMÁTICO DE FOTOS CLOUDINARY ---
@app.template_filter('opt_img')
def optimizar_imagen_cloudinary(url, ancho=500):
    if not url:
        return ''
    if 'res.cloudinary.com' in url and '/upload/' in url and 'q_auto' not in url:
        return url.replace('/upload/', f'/upload/f_auto,q_auto,w_{ancho}/')
    return url

# --- RUTA ANTI-SUEÑO PARA MANTENER ENCENDIDO RENDER Y NEON DB 24/7 ---
@app.route('/ping')
def ping_keep_alive():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "awake", "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500

# --- TRADUCTOR AUTOMÁTICO DESDE EL SERVIDOR (SIN BLOQUEOS DEL NAVEGADOR) ---
@app.route('/api/traducir')
def api_traducir():
    texto = request.args.get('q', '').strip()
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
        return jsonify({"ok": False, "error": str(e)}), 500

# --- MODELOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='cajero')

class CategoriaMenu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    nombre_en = db.Column(db.String(50), nullable=True)

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    nombre_en = db.Column(db.String(100), nullable=True)
    descripcion = db.Column(db.Text, nullable=True)
    descripcion_en = db.Column(db.Text, nullable=True)
    precio = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    imagen_url = db.Column(db.String(255), nullable=True)
    destacado = db.Column(db.Boolean, default=False)
    agotado = db.Column(db.Boolean, default=False)

class Premio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    visitas_necesarias = db.Column(db.Integer, nullable=False, unique=True)
    premio_es = db.Column(db.String(150), nullable=False)
    premio_en = db.Column(db.String(150), nullable=True)

class HistorialPremio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20), nullable=False)
    premio_ganado = db.Column(db.String(150), nullable=False)
    visitas_alcanzadas = db.Column(db.Integer, nullable=False)
    entregado = db.Column(db.Boolean, default=False)
    entregado_por = db.Column(db.String(80), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.now)

class Galeria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    imagen_url = db.Column(db.String(255), nullable=False)
    titulo = db.Column(db.String(100), nullable=True)
    descripcion = db.Column(db.String(250), nullable=True)
    fecha_subida = db.Column(db.DateTime, default=datetime.now)

class Publicacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    titulo_en = db.Column(db.String(150), nullable=True)
    descripcion = db.Column(db.Text, nullable=False)
    descripcion_en = db.Column(db.Text, nullable=True)
    categoria = db.Column(db.String(50), nullable=False) 
    imagen_url = db.Column(db.String(255), nullable=True)
    fecha_publicacion = db.Column(db.DateTime, default=datetime.now)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    visitas = db.Column(db.Integer, default=0)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)

class PinCaja(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True)
    creado_por = db.Column(db.String(80), nullable=True, default='caja')
    folio_sr = db.Column(db.String(50), nullable=True, default='')
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)
    usado_por = db.Column(db.String(120), nullable=True)
    fecha_uso = db.Column(db.DateTime, nullable=True)

class Evaluacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesero_nombre = db.Column(db.String(100), nullable=False)
    mesero_calificacion = db.Column(db.Integer, nullable=False)
    limpieza = db.Column(db.Integer, nullable=False)
    calidad_comida = db.Column(db.Integer, nullable=False)
    comentarios = db.Column(db.Text, nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.now)

class Anuncio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mensaje = db.Column(db.String(250), nullable=False)
    mensaje_en = db.Column(db.String(250), nullable=True)
    color = db.Column(db.String(50), default="bg-dark text-white")
    imagen_url = db.Column(db.String(255), nullable=True)
    texto_boton = db.Column(db.String(50), nullable=True)
    texto_boton_en = db.Column(db.String(50), nullable=True)
    enlace = db.Column(db.String(500), nullable=True)
    activo = db.Column(db.Boolean, default=True)

class PreOrden(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesa = db.Column(db.String(30), nullable=False)
    cliente_nombre = db.Column(db.String(100), nullable=False)
    modalidad = db.Column(db.String(40), default="En Mesa")
    metodo_pago = db.Column(db.String(60), default="Efectivo")
    detalle_items = db.Column(db.Text, nullable=False)
    notas = db.Column(db.Text, nullable=True)
    total = db.Column(db.Float, nullable=False)
    estado = db.Column(db.String(30), default="pendiente")
    atendido_por = db.Column(db.String(80), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.now)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- AUTO-PARCHE DE BASE DE DATOS Y CREACIÓN DE EMPLEADOS ---
def inicializar_sistema():
    db.create_all()
    try:
        instrucciones = [
            "ALTER TABLE anuncio ADD COLUMN IF NOT EXISTS imagen_url VARCHAR(255);",
            "ALTER TABLE anuncio ADD COLUMN IF NOT EXISTS texto_boton VARCHAR(50);",
            "ALTER TABLE anuncio ADD COLUMN IF NOT EXISTS enlace VARCHAR(500);",
            "ALTER TABLE anuncio ADD COLUMN IF NOT EXISTS mensaje_en VARCHAR(250);",
            "ALTER TABLE anuncio ADD COLUMN IF NOT EXISTS texto_boton_en VARCHAR(50);",
            "ALTER TABLE producto ADD COLUMN IF NOT EXISTS agotado BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE galeria ADD COLUMN IF NOT EXISTS titulo VARCHAR(100);",
            "ALTER TABLE galeria ADD COLUMN IF NOT EXISTS descripcion VARCHAR(250);",
            "ALTER TABLE pin_caja ADD COLUMN IF NOT EXISTS creado_por VARCHAR(80) DEFAULT 'caja';",
            "ALTER TABLE pin_caja ADD COLUMN IF NOT EXISTS folio_sr VARCHAR(50) DEFAULT '';",
            "ALTER TABLE pin_caja ADD COLUMN IF NOT EXISTS fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE pin_caja ADD COLUMN IF NOT EXISTS usado_por VARCHAR(120);",
            "ALTER TABLE pin_caja ADD COLUMN IF NOT EXISTS fecha_uso TIMESTAMP;",
            "ALTER TABLE pre_orden ADD COLUMN IF NOT EXISTS atendido_por VARCHAR(80);"
        ]
        for sql in instrucciones:
            db.session.execute(text(sql))
        db.session.commit()
    except Exception:
        db.session.rollback()

    cuentas_equipo = [
        ('raquel', 'raquel2026', 'admin'),
        ('brayan', 'brayan123', 'cajero'),
        ('emili', 'emili123', 'cajero'),
        ('paola', 'paola123', 'mesero'),
        ('daniel', 'daniel123', 'mesero')
    ]
    try:
        for usr, pwd, rol in cuentas_equipo:
            existente = User.query.filter_by(username=usr).first()
            if not existente:
                db.session.add(User(username=usr, password=generate_password_hash(pwd), role=rol))
        db.session.commit()
    except Exception:
        db.session.rollback()

with app.app_context():
    inicializar_sistema()

def obtener_datos_menu():
    categorias_bd = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    categorias_dict = {}
    cat_traducciones = {}
    for cat in categorias_bd:
        productos = Producto.query.filter_by(categoria=cat.nombre).order_by(Producto.destacado.desc(), Producto.id.asc()).all()
        if productos:
            categorias_dict[cat.nombre] = productos
            cat_traducciones[cat.nombre] = cat.nombre_en if cat.nombre_en and cat.nombre_en.strip() != "" else cat.nombre
    return categorias_dict, cat_traducciones

# --- API PÚBLICA EN VIVO PARA CLIENTES (AGOTADOS CADA 4 SEGUNDOS) ---
@app.route('/api/estado_menu_publico')
def api_estado_menu_publico():
    agotados = Producto.query.filter_by(agotado=True).all()
    return jsonify({
        "agotados_ids": [p.id for p in agotados],
        "agotados_nombres": [p.nombre for p in agotados]
    })

# --- RUTAS DE PRE-ÓRDENES Y SINCRONIZACIÓN EN VIVO CADA 3 SEGUNDOS ---
@app.route('/crear_preorden', methods=['POST'])
def crear_preorden():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "Datos inválidos"}), 400
            
        mesa = str(data.get('mesa', '')).strip()
        nombre = str(data.get('cliente_nombre', '')).strip()
        modalidad = str(data.get('modalidad', 'En Mesa')).strip()
        metodo_pago = str(data.get('metodo_pago', 'Efectivo')).strip()
        items_txt = str(data.get('detalle_items', '')).strip()
        notas = str(data.get('notas', '')).strip()
        total = float(data.get('total', 0))

        if not mesa or not nombre or not items_txt:
            return jsonify({"ok": False, "error": "Faltan datos de mesa o nombre"}), 400

        nueva = PreOrden(
            mesa=mesa,
            cliente_nombre=nombre,
            modalidad=modalidad,
            metodo_pago=metodo_pago,
            detalle_items=items_txt,
            notas=notas,
            total=total,
            estado="pendiente",
            fecha=datetime.now()
        )
        db.session.add(nueva)
        db.session.commit()
        hora_str = nueva.fecha.strftime('%H:%M')
        return jsonify({"ok": True, "folio": nueva.id, "hora": hora_str})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/preordenes_pendientes')
@login_required
def api_preordenes_pendientes():
    ordenes = PreOrden.query.filter_by(estado='pendiente').order_by(PreOrden.fecha.desc()).all()
    resultado = []
    for o in ordenes:
        resultado.append({
            "id": o.id,
            "mesa": o.mesa,
            "cliente_nombre": o.cliente_nombre,
            "modalidad": o.modalidad,
            "metodo_pago": o.metodo_pago,
            "detalle_items": o.detalle_items,
            "notas": o.notas or "",
            "total": o.total,
            "hora": o.fecha.strftime('%H:%M') if o.fecha else ""
        })
    agotados_ids = [p.id for p in Producto.query.filter_by(agotado=True).all()]
    pins_activos = PinCaja.query.filter_by(activo=True).count()
    return jsonify({
        "total_pendientes": len(resultado),
        "ordenes": resultado,
        "agotados_ids": agotados_ids,
        "pins_activos": pins_activos
    })

@app.route('/atender_preorden/<int:id>', methods=['POST'])
@login_required
def atender_preorden(id):
    orden = PreOrden.query.get_or_404(id)
    accion = request.form.get('accion', 'atendido')
    orden.estado = accion
    orden.atendido_por = current_user.username
    db.session.commit()
    
    if accion == 'cancelado':
        flash(f'Pre-Orden #{orden.id} (Mesa {orden.mesa}) marcada como cliente retirado/cancelada.', 'danger')
    else:
        flash(f'Pre-Orden #{orden.id} (Mesa {orden.mesa}) confirmada por {current_user.username.capitalize()}.', 'success')
        
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
    return redirect(url_for('cajero_dashboard'))

# --- RUTA PROTEGIDA CON CANDADO DE ADMINISTRADOR ---
@app.route('/actualizar_db')
@login_required
def actualizar_db():
    if current_user.role != 'admin' or request.args.get('confirmar') != 'si':
        return "<h1>🔒 Ruta protegida por seguridad</h1><p>Solo el administrador puede inicializar tablas.</p>", 403
    inicializar_sistema()
    return "<h1>✅ Tablas verificadas y sincronizadas sin borrar tus datos.</h1><a href='/admin_dashboard'>Volver al Panel</a>"

@app.route('/')
def index():
    categorias_dict, cat_traducciones = obtener_datos_menu()
    galeria = Galeria.query.order_by(Galeria.fecha_subida.desc()).all()
    publicaciones = Publicacion.query.order_by(Publicacion.fecha_publicacion.desc()).all()
    premios_bd = Premio.query.order_by(Premio.visitas_necesarias.asc()).all()
    max_visitas = premios_bd[-1].visitas_necesarias if premios_bd else 10
    metas_list = [p.visitas_necesarias for p in premios_bd]
    anuncios_activos = Anuncio.query.filter_by(activo=True).order_by(Anuncio.id.desc()).all()
    anuncio = anuncios_activos[0] if anuncios_activos else None
    
    return render_template('index.html', categorias=categorias_dict, cat_traducciones=cat_traducciones,
                           galeria=galeria, publicaciones=publicaciones, premios=premios_bd, 
                           max_visitas=max_visitas, metas_list=metas_list, anuncio=anuncio, anuncios_activos=anuncios_activos)

@app.route('/registrar_consumo', methods=['POST'])
def registrar_consumo():
    nombre = request.form.get('nombre', '').strip()
    telefono = request.form.get('telefono', '').strip()
    pin_ingresado = request.form.get('pin', '').upper().strip()
    
    pin_valido = PinCaja.query.filter_by(codigo=pin_ingresado, activo=True).first()
    if not pin_valido:
        flash('PIN inválido o ya utilizado.', 'error')
        return redirect(url_for('index'))
        
    pin_valido.activo = False
    pin_valido.usado_por = f"{nombre} ({telefono})"
    pin_valido.fecha_uso = datetime.now()
    
    cliente = Cliente.query.filter_by(telefono=telefono).first()
    if not cliente:
        cliente = Cliente(telefono=telefono, nombre=nombre, visitas=1)
        db.session.add(cliente)
    else:
        cliente.visitas += 1
        cliente.nombre = nombre
        
        premios_bd = Premio.query.order_by(Premio.visitas_necesarias.asc()).all()
        if premios_bd:
            max_visitas = premios_bd[-1].visitas_necesarias
            if cliente.visitas > max_visitas:
                cliente.visitas = 1 

    premios_bd = Premio.query.order_by(Premio.visitas_necesarias.asc()).all()
    premio_actual = next((p for p in premios_bd if p.visitas_necesarias == cliente.visitas), None)
    
    if premio_actual:
        db.session.add(HistorialPremio(
            cliente_nombre=nombre,
            telefono=telefono,
            premio_ganado=premio_actual.premio_es,
            visitas_alcanzadas=cliente.visitas,
            entregado=False,
            fecha=datetime.now()
        ))
        flash(f'¡META ALCANZADA! Muestra esto en caja: {premio_actual.premio_es}', 'premio_interactivo')
    else:
        flash(f'¡Visita sellada, {nombre}! Llevas {cliente.visitas} consumos.', 'success')

    db.session.commit()
        
    categorias_dict, cat_traducciones = obtener_datos_menu()
    anuncios_activos = Anuncio.query.filter_by(activo=True).order_by(Anuncio.id.desc()).all()
    anuncio = anuncios_activos[0] if anuncios_activos else None
        
    return render_template('index.html', cliente=cliente, progreso=cliente.visitas,
                           categorias=categorias_dict, cat_traducciones=cat_traducciones,
                           galeria=Galeria.query.order_by(Galeria.fecha_subida.desc()).all(),
                           publicaciones=Publicacion.query.order_by(Publicacion.fecha_publicacion.desc()).all(),
                           premios=premios_bd, max_visitas=premios_bd[-1].visitas_necesarias if premios_bd else 10,
                           metas_list=[p.visitas_necesarias for p in premios_bd], premio_actual=premio_actual,
                           anuncio=anuncio, anuncios_activos=anuncios_activos)

@app.route('/enviar_evaluacion', methods=['POST'])
def enviar_evaluacion():
    db.session.add(Evaluacion(
        mesero_nombre=request.form.get('mesero_nombre'), mesero_calificacion=int(request.form.get('mesero_calificacion')),
        limpieza=int(request.form.get('limpieza')), calidad_comida=int(request.form.get('calidad_comida')), comentarios=request.form.get('comentarios', '')
    ))
    db.session.commit()
    flash('¡Gracias por tu evaluación!', 'success')
    return redirect(url_for('index'))

# --- ADMIN, CAJA Y MESEROS (AUTENTICACIÓN CON SESIÓN PERMANENTE DE 365 DÍAS) ---
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif current_user.role == 'mesero':
            return redirect(url_for('mesero_dashboard'))
        else:
            return redirect(url_for('cajero_dashboard'))

    if request.method == 'POST':
        username_input = request.form['username'].strip().lower()
        user = User.query.filter(db.func.lower(User.username) == username_input).first()
        if user and check_password_hash(user.password, request.form['password']):
            session.permanent = True
            login_user(user, remember=True, duration=timedelta(days=365))
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'mesero':
                return redirect(url_for('mesero_dashboard'))
            else:
                return redirect(url_for('cajero_dashboard'))
        flash('Usuario o contraseña incorrectos.', 'error')
    return render_template('admin_login.html')

@app.route('/logout')
def logout():
    session.clear()
    logout_user()
    resp = redirect(url_for('admin_login'))
    resp.delete_cookie('remember_token')
    resp.delete_cookie('session')
    return resp

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
    if current_user.role != 'admin':
        return redirect(url_for('cajero_dashboard'))
        
    total_clientes = Cliente.query.count()
    total_visitas = db.session.query(db.func.sum(Cliente.visitas)).scalar() or 0
    promedio_est = db.session.query(db.func.avg(Evaluacion.mesero_calificacion)).scalar() or 0
    clientes_top = Cliente.query.order_by(Cliente.visitas.desc(), Cliente.fecha_registro.desc()).limit(30).all()
    preordenes = PreOrden.query.filter_by(estado='pendiente').order_by(PreOrden.fecha.desc()).all()

    ahora = datetime.now()
    hoy_inicio = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    hace_7_dias = hoy_inicio - timedelta(days=7)
    hace_30_dias = hoy_inicio - timedelta(days=30)

    ordenes_hoy = PreOrden.query.filter(PreOrden.fecha >= hoy_inicio, PreOrden.estado == 'atendido', PreOrden.total > 0).all()
    ordenes_semana = PreOrden.query.filter(PreOrden.fecha >= hace_7_dias, PreOrden.estado == 'atendido', PreOrden.total > 0).all()
    ordenes_mes = PreOrden.query.filter(PreOrden.fecha >= hace_30_dias, PreOrden.estado == 'atendido', PreOrden.total > 0).all()

    ventas_hoy = round(sum(o.total for o in ordenes_hoy), 2)
    ventas_semana = round(sum(o.total for o in ordenes_semana), 2)
    ventas_mes = round(sum(o.total for o in ordenes_mes), 2)

    pins_hoy = PinCaja.query.filter(PinCaja.fecha_creacion >= hoy_inicio).all()
    resumen_cajeros = {}
    for p in pins_hoy:
        autor = (p.creado_por or 'caja').capitalize()
        if autor not in resumen_cajeros:
            resumen_cajeros[autor] = {'generados': 0, 'usados': 0, 'activos': 0}
        resumen_cajeros[autor]['generados'] += 1
        if p.activo:
            resumen_cajeros[autor]['activos'] += 1
        else:
            resumen_cajeros[autor]['usados'] += 1

    historial_pins = PinCaja.query.order_by(PinCaja.id.desc()).limit(60).all()
    historial_premios = HistorialPremio.query.order_by(HistorialPremio.id.desc()).limit(40).all()
    usuarios = User.query.order_by(User.role.asc(), User.username.asc()).all()

    return render_template('admin_dashboard.html', 
                           categorias=CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all(),
                           premios=Premio.query.order_by(Premio.visitas_necesarias.asc()).all(),
                           historial_premios=historial_premios,
                           productos=Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all(), 
                           pins=PinCaja.query.filter_by(activo=True).all(),
                           historial_pins=historial_pins,
                           resumen_cajeros=resumen_cajeros,
                           total_pins_hoy=len(pins_hoy),
                           ventas_hoy=ventas_hoy, pedidos_hoy=len(ordenes_hoy),
                           ventas_semana=ventas_semana, pedidos_semana=len(ordenes_semana),
                           ventas_mes=ventas_mes, pedidos_mes=len(ordenes_mes),
                           usuarios=usuarios,
                           preordenes=preordenes,
                           evaluaciones=Evaluacion.query.order_by(Evaluacion.fecha.desc()).limit(30).all(),
                           clientes_top=clientes_top,
                           galeria=Galeria.query.order_by(Galeria.fecha_subida.desc()).all(),
                           publicaciones=Publicacion.query.order_by(Publicacion.fecha_publicacion.desc()).all(),
                           anuncios=Anuncio.query.order_by(Anuncio.id.desc()).all(),
                           total_clientes=total_clientes, total_visitas=total_visitas, promedio_est=round(promedio_est, 1))

@app.route('/cajero_dashboard')
@login_required
def cajero_dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if current_user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
        
    pins = PinCaja.query.filter_by(activo=True).all()
    preordenes = PreOrden.query.filter_by(estado='pendiente').order_by(PreOrden.fecha.desc()).all()
    hoy_inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    mis_pins_hoy = PinCaja.query.filter(PinCaja.creado_por == current_user.username, PinCaja.fecha_creacion >= hoy_inicio).count()
    historial_caja_hoy = PinCaja.query.filter(PinCaja.fecha_creacion >= hoy_inicio).order_by(PinCaja.id.desc()).limit(30).all()
    return render_template('cajero_dashboard.html', pins=pins, preordenes=preordenes, mis_pins_hoy=mis_pins_hoy, historial_caja_hoy=historial_caja_hoy)

@app.route('/mesero_dashboard')
@login_required
def mesero_dashboard():
    preordenes = PreOrden.query.filter_by(estado='pendiente').order_by(PreOrden.fecha.desc()).all()
    productos = Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all()
    return render_template('mesero_dashboard.html', preordenes=preordenes, productos=productos)

# --- GESTIÓN DE USUARIOS Y CONTRASEÑAS ---
@app.route('/admin/usuario/nuevo', methods=['POST'])
@login_required
def nuevo_usuario():
    if current_user.role != 'admin': return redirect(url_for('index'))
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'mesero')
    if username and password:
        if User.query.filter(db.func.lower(User.username) == username).first():
            flash('Ese nombre de usuario ya existe.', 'danger')
        else:
            db.session.add(User(username=username, password=generate_password_hash(password), role=role))
            db.session.commit()
            flash(f'Usuario {username} ({role}) creado con éxito.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/usuario/cambiar_pass/<int:id>', methods=['POST'])
@login_required
def cambiar_pass_usuario(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    u = User.query.get_or_404(id)
    nueva_pass = request.form.get('nueva_password', '').strip()
    if nueva_pass:
        u.password = generate_password_hash(nueva_pass)
        db.session.commit()
        flash(f'Contraseña de {u.username} actualizada.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/usuario/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_usuario(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    u = User.query.get_or_404(id)
    if u.id == current_user.id:
        flash('No puedes eliminar tu propio usuario activo.', 'danger')
    else:
        db.session.delete(u)
        db.session.commit()
        flash(f'Usuario {u.username} eliminado.', 'success')
    return redirect(url_for('admin_dashboard'))

# --- EXPORTACIÓN A EXCEL (CLIENTES, EVALUACIONES, PINS Y PRE-ÓRDENES) ---
@app.route('/admin/exportar_clientes')
@login_required
def exportar_clientes():
    if current_user.role != 'admin': return redirect(url_for('index'))
    clientes = Cliente.query.all()
    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(('ID', 'Nombre', 'Telefono', 'Visitas', 'Fecha_Registro'))
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for c in clientes:
            writer.writerow((c.id, c.nombre, c.telefono, c.visitas, c.fecha_registro.strftime('%Y-%m-%d')))
            yield data.getvalue(); data.seek(0); data.truncate(0)
    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="Base_Clientes_Quiosco.csv")
    return response

@app.route('/admin/exportar_evaluaciones')
@login_required
def exportar_evaluaciones():
    if current_user.role != 'admin': return redirect(url_for('index'))
    evaluaciones = Evaluacion.query.all()
    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(('ID', 'Mesero', 'Calificacion', 'Limpieza', 'Comida', 'Comentarios', 'Fecha'))
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for e in evaluaciones:
            writer.writerow((e.id, e.mesero_nombre, e.mesero_calificacion, e.limpieza, e.calidad_comida, e.comentarios, e.fecha.strftime('%Y-%m-%d')))
            yield data.getvalue(); data.seek(0); data.truncate(0)
    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="Evaluaciones_Meseros.csv")
    return response

@app.route('/admin/exportar_pins')
@login_required
def exportar_pins():
    if current_user.role != 'admin': return redirect(url_for('index'))
    todos_pins = PinCaja.query.order_by(PinCaja.id.desc()).all()
    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(('ID', 'PIN', 'Emitido_Por', 'Folio_SoftRestaurant', 'Fecha_Creacion', 'Estado', 'Canjeado_Por', 'Fecha_Canje'))
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for p in todos_pins:
            estado = 'Pendiente' if p.activo else 'Sellado'
            f_crea = p.fecha_creacion.strftime('%Y-%m-%d %H:%M') if p.fecha_creacion else ''
            f_uso = p.fecha_uso.strftime('%Y-%m-%d %H:%M') if p.fecha_uso else ''
            writer.writerow((p.id, p.codigo, p.creado_por or 'caja', p.folio_sr or '', f_crea, estado, p.usado_por or '', f_uso))
            yield data.getvalue(); data.seek(0); data.truncate(0)
    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="Auditoria_PINs_Quiosco.csv")
    return response

@app.route('/admin/exportar_preordenes')
@login_required
def exportar_preordenes():
    if current_user.role != 'admin': return redirect(url_for('index'))
    ordenes = PreOrden.query.order_by(PreOrden.id.desc()).all()
    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(('Folio', 'Mesa', 'Cliente', 'Modalidad', 'Pago', 'Detalle', 'Total', 'Estado', 'Atendido_Por', 'Fecha'))
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for o in ordenes:
            f_str = o.fecha.strftime('%Y-%m-%d %H:%M') if o.fecha else ''
            writer.writerow((o.id, o.mesa, o.cliente_nombre, o.modalidad, o.metodo_pago, o.detalle_items.replace('\n', ' | '), o.total, o.estado, o.atendido_por or '', f_str))
            yield data.getvalue(); data.seek(0); data.truncate(0)
    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="Reporte_Pedidos_Quiosco.csv")
    return response

# --- RUTAS DE PREMIOS E HISTORIAL DE CANJES ---
@app.route('/admin/premio/nuevo', methods=['POST'])
@login_required
def nuevo_premio():
    if current_user.role != 'admin': return redirect(url_for('index'))
    visitas = request.form.get('visitas')
    if Premio.query.filter_by(visitas_necesarias=visitas).first():
        flash('Ya existe una meta con ese número de visitas.', 'danger')
    else:
        db.session.add(Premio(
            visitas_necesarias=visitas,
            premio_es=request.form.get('premio_es'),
            premio_en=request.form.get('premio_en', '')
        ))
        db.session.commit()
        flash('Meta de fidelidad agregada.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/premio/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_premio(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    db.session.delete(Premio.query.get_or_404(id))
    db.session.commit()
    flash('Meta eliminada.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/premio_entregado/<int:id>', methods=['POST'])
@login_required
def marcar_premio_entregado(id):
    hp = HistorialPremio.query.get_or_404(id)
    hp.entregado = True
    hp.entregado_por = current_user.username
    db.session.commit()
    flash(f'Premio ({hp.premio_ganado}) de {hp.cliente_nombre} marcado como entregado.', 'success')
    return redirect(url_for('admin_dashboard'))

# --- CATEGORÍAS ---
@app.route('/admin/categoria/nueva', methods=['POST'])
@login_required
def nueva_categoria():
    if current_user.role != 'admin': return redirect(url_for('index'))
    nombre = request.form.get('nombre')
    if nombre and not CategoriaMenu.query.filter_by(nombre=nombre).first():
        db.session.add(CategoriaMenu(nombre=nombre, nombre_en=request.form.get('nombre_en', '')))
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/categoria/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_categoria(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    cat = CategoriaMenu.query.get_or_404(id)
    if Producto.query.filter_by(categoria=cat.nombre).first():
        flash('No puedes borrar una categoría en uso.', 'danger')
    else:
        db.session.delete(cat)
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- PRODUCTOS Y BOTONES RÁPIDOS DE 1 CLIC ---
@app.route('/admin/producto/nuevo', methods=['POST'])
@login_required
def nuevo_producto():
    if current_user.role != 'admin': return redirect(url_for('index'))
    img_url = cloudinary.uploader.upload(request.files['foto']).get('secure_url') if 'foto' in request.files and request.files['foto'].filename != '' else None
    
    destacado = True if request.form.get('destacado') == 'on' else False
    agotado = True if request.form.get('agotado') == 'on' else False
    
    db.session.add(Producto(
        nombre=request.form['nombre'], nombre_en=request.form.get('nombre_en', ''), descripcion=request.form['descripcion'], 
        descripcion_en=request.form.get('descripcion_en', ''), precio=request.form['precio'], categoria=request.form['categoria'], 
        imagen_url=img_url, destacado=destacado, agotado=agotado
    ))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/producto/toggle_destacado/<int:id>', methods=['POST'])
@login_required
def toggle_destacado(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    p = Producto.query.get_or_404(id)
    p.destacado = not p.destacado
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"ok": True, "destacado": p.destacado})
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/producto/toggle_agotado/<int:id>', methods=['POST'])
@login_required
def toggle_agotado(id):
    if current_user.role not in ['admin', 'mesero']:
        return redirect(url_for('index'))
    p = Producto.query.get_or_404(id)
    p.agotado = not p.agotado
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"ok": True, "agotado": p.agotado})
    if current_user.role == 'mesero':
        flash(f'{p.nombre}: {"🚫 Marcado como AGOTADO" if p.agotado else "✅ Marcado como DISPONIBLE"}', 'success')
        return redirect(url_for('mesero_dashboard'))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/producto/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_producto(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    p = Producto.query.get_or_404(id)
    if request.method == 'POST':
        p.nombre, p.nombre_en = request.form['nombre'], request.form.get('nombre_en', '')
        p.descripcion, p.descripcion_en = request.form['descripcion'], request.form.get('descripcion_en', '')
        p.precio, p.categoria = request.form['precio'], request.form['categoria']
        
        p.destacado = True if request.form.get('destacado') == 'on' else False
        p.agotado = True if request.form.get('agotado') == 'on' else False
        
        if 'foto' in request.files and request.files['foto'].filename != '':
            p.imagen_url = cloudinary.uploader.upload(request.files['foto']).get('secure_url')
        db.session.commit()
        flash('Platillo actualizado correctamente.', 'success')
        return redirect(url_for('admin_dashboard'))
        
    categorias_bd = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    return render_template('editar_producto.html', producto=p, categorias=categorias_bd)

@app.route('/admin/producto/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_producto(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    db.session.delete(Producto.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- GALERÍA ---
@app.route('/agregar_galeria', methods=['POST'])
@login_required
def agregar_galeria():
    if current_user.role != 'admin': return redirect(url_for('index'))
    if 'foto' in request.files and request.files['foto'].filename != '':
        nueva_foto = Galeria(
            imagen_url=cloudinary.uploader.upload(request.files['foto']).get('secure_url'),
            titulo=request.form.get('titulo', ''),
            descripcion=request.form.get('descripcion', '')
        )
        db.session.add(nueva_foto)
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/editar_galeria/<int:id>', methods=['POST'])
@login_required
def editar_galeria(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    g = Galeria.query.get_or_404(id)
    g.titulo = request.form.get('titulo', '')
    g.descripcion = request.form.get('descripcion', '')
    db.session.commit()
    flash('Foto de galería actualizada.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/eliminar_galeria/<int:id>')
@login_required
def eliminar_galeria(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    db.session.delete(Galeria.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- ANUNCIOS (CARRUSEL MULTI-BANNER) ---
@app.route('/admin/anuncio/nuevo', methods=['POST'])
@login_required
def nuevo_anuncio():
    if current_user.role != 'admin': return redirect(url_for('index'))
    try:
        img_url = None
        if 'foto' in request.files and request.files['foto'].filename != '':
            img_url = cloudinary.uploader.upload(request.files['foto']).get('secure_url')
        
        nuevo = Anuncio(
            mensaje=request.form.get('mensaje', 'Sin mensaje'),
            mensaje_en=request.form.get('mensaje_en', ''),
            color=request.form.get('color', 'bg-dark text-white'),
            imagen_url=img_url, 
            texto_boton=request.form.get('texto_boton', ''), 
            texto_boton_en=request.form.get('texto_boton_en', ''),
            enlace=request.form.get('enlace', ''), 
            activo=True if request.form.get('activo') == 'on' else False
        )
        db.session.add(nuevo)
        db.session.commit()
        flash('Portada agregada al carrusel.', 'success')
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        db.session.rollback()
        return f"<h1>Error: {str(e)}</h1><a href='/admin_dashboard'>Volver</a>"

@app.route('/admin/anuncio/toggle/<int:id>', methods=['POST'])
@login_required
def toggle_anuncio(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    an = Anuncio.query.get_or_404(id)
    an.activo = not an.activo
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/anuncio/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_anuncio(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    db.session.delete(Anuncio.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- CAJA: GENERAR, ANULAR Y LIMPIAR PINs ---
@app.route('/caja/generar_pin', methods=['POST'])
@login_required
def generar_pin():
    if current_user.role == 'mesero':
        flash('Los meseros no tienen permiso para generar PINs.', 'danger')
        return redirect(url_for('mesero_dashboard'))
        
    cantidad = int(request.form.get('cantidad', 1))
    folio_sr = request.form.get('folio_sr', '').strip()
    ahora = datetime.now()
    
    for _ in range(cantidad):
        codigo = ''.join(random.choices(string.digits, k=4))
        db.session.add(PinCaja(
            codigo=codigo,
            creado_por=current_user.username,
            folio_sr=folio_sr,
            fecha_creacion=ahora
        ))
    db.session.commit()
    flash(f'¡Se generaron {cantidad} PIN(s) registrados a nombre de {current_user.username.capitalize()}!', 'success')
    
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('cajero_dashboard'))

@app.route('/caja/eliminar_pin/<int:id>', methods=['POST'])
@login_required
def eliminar_pin_individual(id):
    if current_user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
    pin = PinCaja.query.get_or_404(id)
    codigo_borrado = pin.codigo
    db.session.delete(pin)
    db.session.commit()
    flash(f'PIN {codigo_borrado} anulado y eliminado correctamente.', 'success')
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('cajero_dashboard'))

@app.route('/admin/limpiar_pins_activos', methods=['POST'])
@login_required
def limpiar_pins_activos():
    if current_user.role != 'admin':
        return redirect(url_for('cajero_dashboard'))
    borrados = PinCaja.query.filter_by(activo=True).delete()
    db.session.commit()
    flash(f'Se limpiaron {borrados} PIN(s) pendientes que no fueron utilizados.', 'success')
    return redirect(url_for('admin_dashboard'))
# ==============================================================================
# ANEXO MÓDULO POS PROFESIONAL (ESTILO SOFT RESTAURANT) + ALMACÉN
# Se pega antes de: if __name__ == '__main__':
# ==============================================================================

class ConfigPermisosPOS(db.Model):
    __tablename__ = 'config_permisos_pos'
    id = db.Column(db.Integer, primary_key=True)
    cajero_puede_cancelar = db.Column(db.Boolean, default=True)
    cajero_puede_descontar = db.Column(db.Boolean, default=True)
    cajero_puede_cambiar_pago = db.Column(db.Boolean, default=True)
    tipo_cambio_dll = db.Column(db.Float, default=13.0)

class TurnoPOS(db.Model):
    __tablename__ = 'turnos_pos'
    id = db.Column(db.Integer, primary_key=True)
    cajero = db.Column(db.String(80), nullable=False)
    apertura = db.Column(db.DateTime, default=datetime.now)
    cierre = db.Column(db.DateTime, nullable=True)
    fondo_inicial = db.Column(db.Float, default=0.0)
    depositos_efectivo = db.Column(db.Float, default=0.0)
    retiros_efectivo = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(20), default='ABIERTO') # ABIERTO / CERRADO

class MovimientoCajaPOS(db.Model):
    __tablename__ = 'movimientos_caja_pos'
    id = db.Column(db.Integer, primary_key=True)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos_pos.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False) # RETIRO / DEPOSITO
    monto = db.Column(db.Float, nullable=False)
    concepto = db.Column(db.String(200), nullable=False)
    usuario = db.Column(db.String(80), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.now)

class CuentaPOS(db.Model):
    __tablename__ = 'cuentas_pos'
    id = db.Column(db.Integer, primary_key=True)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos_pos.id'), nullable=True)
    folio = db.Column(db.String(20), unique=True, nullable=True) # Ej. A10690
    orden = db.Column(db.String(15), nullable=False) # Ej. A1, A26
    area = db.Column(db.String(40), default='01 COMEDOR') # 01 COMEDOR, 02 TERRAZA, RAPIDO
    mesa = db.Column(db.String(25), nullable=False) # T01..T12, M01..M06
    mesero = db.Column(db.String(60), default='MANUEL')
    personas = db.Column(db.Integer, default=1)
    observaciones = db.Column(db.Text, nullable=True)
    apertura = db.Column(db.DateTime, default=datetime.now)
    cierre = db.Column(db.DateTime, nullable=True)
    impresa = db.Column(db.Boolean, default=False)
    
    subtotal = db.Column(db.Float, default=0.0)
    descuento_pct = db.Column(db.Float, default=0.0)
    descuento_monto = db.Column(db.Float, default=0.0)
    iva = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, default=0.0)
    
    pago_efectivo = db.Column(db.Float, default=0.0)
    pago_tarjeta_debito = db.Column(db.Float, default=0.0)
    pago_tarjeta_credito = db.Column(db.Float, default=0.0)
    pago_otros = db.Column(db.Float, default=0.0)
    propina_tarjeta = db.Column(db.Float, default=0.0)
    cambio = db.Column(db.Float, default=0.0)
    
    estado = db.Column(db.String(20), default='ABIERTA') # ABIERTA / PAGADA / CANCELADA
    detalles = db.relationship('DetallePOS', backref='cuenta', lazy=True, cascade="all, delete-orphan")

class DetallePOS(db.Model):
    __tablename__ = 'detalles_pos'
    id = db.Column(db.Integer, primary_key=True)
    cuenta_id = db.Column(db.Integer, db.ForeignKey('cuentas_pos.id'), nullable=False)
    num_comanda = db.Column(db.Integer, default=1)
    cantidad = db.Column(db.Float, default=1.0)
    clave = db.Column(db.String(20), default='00001')
    descripcion = db.Column(db.String(150), nullable=False)
    area_impresion = db.Column(db.String(20), default='BARRA') # BARRA / COCINA
    es_modificador = db.Column(db.Boolean, default=False)
    precio_unitario = db.Column(db.Float, default=0.0)
    importe = db.Column(db.Float, default=0.0)
    impreso_comanda = db.Column(db.Boolean, default=False)

class ColaImpresionPOS(db.Model):
    __tablename__ = 'cola_impresion_pos'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(30), nullable=False) # COMANDA_BARRA, COMANDA_COCINA, PRECUENTA, NOTA_CONSUMO, VALE_CAJA, CORTE_X
    contenido_html = db.Column(db.Text, nullable=False)
    impreso = db.Column(db.Boolean, default=False)
    fecha = db.Column(db.DateTime, default=datetime.now)

with app.app_context():
    db.create_all()
    if not ConfigPermisosPOS.query.first():
        db.session.add(ConfigPermisosPOS())
        db.session.commit()

def recalcular_totales_cuenta(c):
    bruto = sum(d.importe for d in c.detalles)
    desc = round(bruto * (c.descuento_pct / 100.0), 2)
    c.descuento_monto = desc
    c.total = round(max(0.0, bruto - desc), 2)
    c.subtotal = round(c.total / 1.16, 2)
    c.iva = round(c.total - c.subtotal, 2)

def detectar_area_impresion(categoria_nombre):
    cat = (categoria_nombre or '').lower()
    palabras_barra = ['caliente', 'fría', 'fria', 'frapp', 'infus', 'jugo', 'refresco', 'agua', 'postre', 'cerveza', 'coctel', 'café', 'cafe']
    for p in palabras_barra:
        if p in cat:
            return 'BARRA'
    return 'COCINA'

def obtener_turno_activo():
    t = TurnoPOS.query.filter_by(estado='ABIERTO').order_by(TurnoPOS.id.desc()).first()
    if not t:
        t = TurnoPOS(cajero='CAJERO T1', fondo_inicial=0.0, estado='ABIERTO')
        db.session.add(t)
        db.session.commit()
    return t

# --- PANTALLA PRINCIPAL DEL POS (CAJERO / MESERO / ADMIN) ---
@app.route('/pos')
@login_required
def vista_pos_soft():
    turno = obtener_turno_activo()
    permisos = ConfigPermisosPOS.query.first()
    cuentas = CuentaPOS.query.filter_by(estado='ABIERTA').order_by(CuentaPOS.id.asc()).all()
    categorias_bd = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    productos = Producto.query.filter_by(agotado=False).order_by(Producto.categoria.asc(), Producto.nombre.asc()).all()
    return render_template('pos_soft.html', turno=turno, permisos=permisos, cuentas=cuentas, categorias=categorias_bd, productos=productos)

# --- ABRIR MESA, TERRAZA O SERVICIO RÁPIDO ---
@app.route('/api/pos/abrir_mesa', methods=['POST'])
@login_required
def api_pos_abrir_mesa():
    data = request.json
    mesa_nom = str(data.get('mesa', 'T01')).strip().upper()
    existente = CuentaPOS.query.filter_by(mesa=mesa_nom, estado='ABIERTA').first()
    if existente:
        return jsonify({'ok': True, 'cuenta_id': existente.id, 'ya_existia': True})

    turno = obtener_turno_activo()
    hoy_inicio = datetime.now().replace(hour=0, minute=0, second=0)
    num_orden = CuentaPOS.query.filter(CuentaPOS.apertura >= hoy_inicio).count() + 1
    area = '02 TERRAZA' if mesa_nom.startswith('T') else ('RAPIDO' if 'RAP' in mesa_nom else '01 COMEDOR')

    nueva = CuentaPOS(
        turno_id=turno.id,
        orden=f"A{num_orden}",
        area=area,
        mesa=mesa_nom,
        mesero=str(data.get('mesero', current_user.username)).upper(),
        personas=int(data.get('personas', 1)),
        estado='ABIERTA'
    )
    db.session.add(nueva)
    db.session.commit()
    return jsonify({'ok': True, 'cuenta_id': nueva.id})

# --- RENOMBRAR O CAMBIAR DE MESA ---
@app.route('/api/pos/renombrar_mesa', methods=['POST'])
@login_required
def api_pos_renombrar_mesa():
    data = request.json
    c = CuentaPOS.query.get_or_404(data['cuenta_id'])
    c.mesa = str(data['nueva_mesa']).strip().upper()
    if data.get('personas'):
        c.personas = int(data['personas'])
    db.session.commit()
    return jsonify({'ok': True})

# --- CONSULTAR DETALLE DE UNA CUENTA EN VIVO ---
@app.route('/api/pos/detalle_cuenta/<int:cuenta_id>')
@login_required
def api_pos_detalle_cuenta(cuenta_id):
    c = CuentaPOS.query.get_or_404(cuenta_id)
    items = [{
        'id': d.id,
        'mov': idx + 1,
        'comanda': d.num_comanda,
        'cantidad': f"{d.cantidad:.3f}",
        'clave': d.clave,
        'descripcion': d.descripcion,
        'area_impresion': d.area_impresion,
        'precio': f"{d.precio_unitario:.2f}",
        'importe': f"{d.importe:.2f}",
        'es_modificador': d.es_modificador,
        'impreso': d.impreso_comanda
    } for idx, d in enumerate(c.detalles)]

    return jsonify({
        'id': c.id, 'mesa': c.mesa, 'area': c.area, 'mesero': c.mesero,
        'personas': c.personas, 'orden': c.orden, 'folio': c.folio or '0',
        'apertura': c.apertura.strftime('%d/%m/%Y %I:%M:%S %p'),
        'impresa': c.impresa, 'observaciones': c.observaciones or '',
        'subtotal': f"{c.subtotal:.2f}", 'descuento_pct': c.descuento_pct,
        'descuento_monto': f"{c.descuento_monto:.2f}", 'iva': f"{c.iva:.2f}",
        'total': f"{c.total:.2f}", 'total_num': c.total, 'items': items
    })

# --- CAPTURAR PLATILLO Y MODIFICADORES (>) ---
@app.route('/api/pos/capturar_item', methods=['POST'])
@login_required
def api_pos_capturar_item():
    data = request.json
    c = CuentaPOS.query.get_or_404(data['cuenta_id'])
    if c.estado != 'ABIERTA':
        return jsonify({'ok': False, 'msg': 'La cuenta ya está cerrada'}), 400

    cant = float(data.get('cantidad', 1))
    precio = float(data.get('precio', 0))
    es_mod = bool(data.get('es_modificador', False))
    desc = f">{data['descripcion'].upper()}" if es_mod else data['descripcion'].upper()
    area_imp = detectar_area_impresion(data.get('categoria', 'Barra'))

    nuevo_item = DetallePOS(
        cuenta_id=c.id,
        num_comanda=int(data.get('comanda', 1)),
        cantidad=cant,
        clave=str(data.get('clave', '02001')),
        descripcion=desc,
        area_impresion=area_imp,
        es_modificador=es_mod,
        precio_unitario=precio,
        importe=round(cant * precio, 2),
        impreso_comanda=False
    )
    db.session.add(nuevo_item)
    db.session.flush()
    recalcular_totales_cuenta(c)
    db.session.commit()
    return jsonify({'ok': True})

# --- ENVIAR COMANDA CORTANDO POR SEPARADO COCINA Y BARRA ---
@app.route('/api/pos/enviar_comanda/<int:cuenta_id>', methods=['POST'])
@login_required
def api_pos_enviar_comanda(cuenta_id):
    c = CuentaPOS.query.get_or_404(cuenta_id)
    pendientes = [d for d in c.detalles if not d.impreso_comanda]
    if not pendientes:
        return jsonify({'ok': False, 'msg': 'No hay productos nuevos por enviar a cocina/barra.'})

    por_area = {'BARRA': [], 'COCINA': []}
    for d in pendientes:
        por_area[d.area_impresion].append(d)
        d.impreso_comanda = True

    ahora_str = datetime.now().strftime('%d/%m/%Y %I:%M:%S %p')
    for area_nom, lista in por_area.items():
        if not lista:
            continue
        filas_html = "".join([
            f"<tr><td style='width:20%;font-weight:bold;'>{'' if it.es_modificador else int(it.cantidad)}</td>"
            f"<td style='width:80%;font-weight:bold;'>{it.descripcion}</td></tr>"
            for it in lista
        ])
        html_ticket = f"""
        <div class='ticket-termico'>
            <div style='font-size:18px;font-weight:900;text-align:center;'>*** ORDEN {area_nom} ***</div>
            <div style='text-align:center;font-size:12px;'>MESA: <b>{c.mesa}</b> | ORDEN: <b>{c.orden}</b></div>
            <div style='text-align:center;font-size:11px;'>MESERO: {c.mesero} | {ahora_str}</div>
            <div style='border-top:2px dashed #000;margin:6px 0;'></div>
            <table style='width:100%;font-size:15px;'>{filas_html}</table>
            {f"<div style='margin-top:6px;font-size:12px;'><b>NOTA:</b> {c.observaciones}</div>" if c.observaciones else ""}
            <div style='border-top:2px dashed #000;margin:8px 0;'></div>
        </div>
        """
        db.session.add(ColaImpresionPOS(tipo=f"COMANDA_{area_nom}", contenido_html=html_ticket))

    db.session.commit()
    return jsonify({'ok': True})

# --- CANCELAR PRODUCTO O APLICAR DESCUENTO (CON PERMISOS DE RAQUEL) ---
@app.route('/api/pos/cancelar_item', methods=['POST'])
@login_required
def api_pos_cancelar_item():
    if current_user.role == 'mesero':
        return jsonify({'ok': False, 'msg': 'El mesero no tiene permiso para cancelar productos.'}), 403

    permisos = ConfigPermisosPOS.query.first()
    data = request.json
    if current_user.role != 'admin' and not permisos.cajero_puede_cancelar:
        clave_admin = str(data.get('clave_admin', '')).strip()
        admin_usr = User.query.filter_by(role='admin').first()
        if not admin_usr or not check_password_hash(admin_usr.password, clave_admin):
            return jsonify({'ok': False, 'requiere_admin': True, 'msg': 'Cancelación bloqueada por Administración. Ingresa la clave de Raquel.'}), 403

    item = DetallePOS.query.get_or_404(data['item_id'])
    cuenta = item.cuenta
    db.session.delete(item)
    db.session.flush()
    recalcular_totales_cuenta(cuenta)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/pos/descuento', methods=['POST'])
@login_required
def api_pos_descuento():
    if current_user.role == 'mesero':
        return jsonify({'ok': False, 'msg': 'Solo Caja o Administración pueden aplicar descuentos.'}), 403
    c = CuentaPOS.query.get_or_404(request.json['cuenta_id'])
    c.descuento_pct = float(request.json.get('porcentaje', 0))
    recalcular_totales_cuenta(c)
    db.session.commit()
    return jsonify({'ok': True})

# --- PAGAR CUENTA (SOLO CAJERO/ADMIN) CON CÁLCULO DE PROPINA OCULTA ---
@app.route('/api/pos/pagar_cuenta', methods=['POST'])
@login_required
def api_pos_pagar_cuenta():
    if current_user.role == 'mesero':
        return jsonify({'ok': False, 'msg': 'Los meseros no pueden cobrar cuentas.'}), 403

    data = request.json
    c = CuentaPOS.query.get_or_404(data['cuenta_id'])
    if not c.folio:
        ultimo = CuentaPOS.query.filter(CuentaPOS.folio.isnot(None)).order_by(CuentaPOS.id.desc()).first()
        sig_num = (int(ultimo.folio[1:]) + 1) if (ultimo and ultimo.folio.startswith('A')) else 10692
        c.folio = f"A{sig_num}"

    c.pago_efectivo = float(data.get('efectivo', 0))
    c.pago_tarjeta_debito = float(data.get('tarjeta_debito', 0))
    c.pago_tarjeta_credito = float(data.get('tarjeta_credito', 0))
    c.propina_tarjeta = float(data.get('propina', 0))
    c.cambio = float(data.get('cambio', 0))
    c.cierre = datetime.now()
    c.estado = 'PAGADA'
    db.session.commit()
    return jsonify({'ok': True, 'folio': c.folio})

# --- RETIRO / DEPÓSITO DE EFECTIVO EN CAJA CON IMPRESIÓN DE VALE ---
@app.route('/api/pos/movimiento_caja', methods=['POST'])
@login_required
def api_pos_movimiento_caja():
    if current_user.role == 'mesero':
        return jsonify({'ok': False, 'msg': 'Solo Caja puede registrar retiros o compras.'}), 403
    data = request.json
    turno = obtener_turno_activo()
    monto = float(data.get('monto', 0))
    tipo = data.get('tipo', 'RETIRO')
    concepto = str(data.get('concepto', 'Compra de insumos')).upper()

    mov = MovimientoCajaPOS(turno_id=turno.id, tipo=tipo, monto=monto, concepto=concepto, usuario=current_user.username.upper())
    db.session.add(mov)
    if tipo == 'RETIRO':
        turno.retiros_efectivo += monto
    else:
        turno.depositos_efectivo += monto

    html_vale = f"""
    <div class='ticket-termico'>
        <div style='text-align:center;font-weight:bold;font-size:15px;'>QUIOSCO MORISCO BISTRÓ</div>
        <div style='text-align:center;font-weight:bold;'>VALE DE {tipo} DE CAJA</div>
        <div style='border-top:1px dashed #000;margin:6px 0;'></div>
        <div>FECHA: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}</div>
        <div>CAJERO: {current_user.username.upper()}</div>
        <div>CONCEPTO: <b>{concepto}</b></div>
        <div style='font-size:18px;font-weight:900;margin:8px 0;'>MONTO: ${monto:.2f}</div>
        <br><br><div style='border-top:1px solid #000;text-align:center;'>FIRMA DE RECIBIDO</div>
    </div>
    """
    db.session.add(ColaImpresionPOS(tipo='VALE_CAJA', contenido_html=html_vale))
    db.session.commit()
    return jsonify({'ok': True})

# --- PRECORTE (CORTE X) Y CORTE FINAL (CORTE Z) IDÉNTICO A TU FOTO ---
@app.route('/api/pos/corte_caja', methods=['GET', 'POST'])
@login_required
def api_pos_corte_caja():
    turno = obtener_turno_activo()
    cuentas_pagadas = CuentaPOS.query.filter_by(turno_id=turno.id, estado='PAGADA').all()
    cuentas_abiertas = CuentaPOS.query.filter_by(estado='ABIERTA').count()

    ef_ventas = sum(max(0.0, c.pago_efectivo - c.cambio) for c in cuentas_pagadas)
    tarj_debito = sum(c.pago_tarjeta_debito for c in cuentas_pagadas)
    tarj_credito = sum(c.pago_tarjeta_credito for c in cuentas_pagadas)
    total_tarjeta_sin_prop = tarj_debito + tarj_credito
    propinas_tarj = sum(c.propina_tarjeta for c in cuentas_pagadas)

    # Matemática exacta de tu foto de Corte de Caja X:
    # Efectivo Final = Efectivo Ventas + Depósitos - Retiros - Propinas Pagadas a Meseros
    efectivo_final = round(turno.fondo_inicial + ef_ventas + turno.depositos_efectivo - turno.retiros_efectivo - propinas_tarj, 2)
    saldo_final = round(efectivo_final + total_tarjeta_sin_prop, 2)

    if request.method == 'POST' and request.json.get('cerrar_turno'):
        # Se cierra el turno actual (las cuentas en terraza abiertas siguen vivas para el siguiente turno)
        turno.cierre = datetime.now()
        turno.estado = 'CERRADO'
        nuevo_turno = TurnoPOS(cajero=current_user.username.upper(), fondo_inicial=0.0, estado='ABIERTO')
        db.session.add(nuevo_turno)
        db.session.flush()
        # Pasar las terrazas/mesas que sigan abiertas al nuevo turno sin borrarlas
        for ca in CuentaPOS.query.filter_by(estado='ABIERTA').all():
            ca.turno_id = nuevo_turno.id
        db.session.commit()

    return jsonify({
        'apertura': turno.apertura.strftime('%d/%m/%Y %I:%M:%S %p'),
        'ahora': datetime.now().strftime('%d/%m/%Y %I:%M:%S %p'),
        'efectivo': f"{ef_ventas:.2f}",
        'tarjeta': f"{total_tarjeta_sin_prop:.2f}",
        'tarj_debito': f"{tarj_debito:.2f}",
        'tarj_credito': f"{tarj_credito:.2f}",
        'depositos': f"{turno.depositos_efectivo:.2f}",
        'retiros': f"{turno.retiros_efectivo:.2f}",
        'propinas_pagadas': f"{propinas_tarj:.2f}",
        'saldo_final': f"{saldo_final:.2f}",
        'efectivo_final': f"{efectivo_final:.2f}",
        'total_formas': f"{(ef_ventas + total_tarjeta_sin_prop):.2f}",
        'cuentas_abiertas': cuentas_abiertas
    })

# --- COLA DE IMPRESIÓN SILENCIOSA PARA LA ÚNICA IMPRESORA DE CAJA ---
@app.route('/api/pos/cola_impresion')
@login_required
def api_pos_cola_impresion():
    pendientes = ColaImpresionPOS.query.filter_by(impreso=False).order_by(ColaImpresionPOS.id.asc()).all()
    textos = [p.contenido_html for p in pendientes]
    for p in pendientes:
        p.impreso = True
    if pendientes:
        db.session.commit()
    return jsonify({'tickets': textos})    
# ==============================================================================
# BLOQUE 2: REQUERIMIENTOS BARRA/COCINA, ALMACÉN, RECETAS Y 1-CLIC PREÓRDENES
# Pegar justo antes de: if __name__ == '__main__':
# ==============================================================================
import re

class InsumoAlmacen(db.Model):
    __tablename__ = 'insumos_almacen'
    id = db.Column(db.Integer, primary_key=True)
    area = db.Column(db.String(20), nullable=False) # BARRA / COCINA
    subcategoria = db.Column(db.String(60), nullable=False)
    producto = db.Column(db.String(120), nullable=False)
    unidad = db.Column(db.String(30), nullable=False)
    stock_actual = db.Column(db.Float, default=10.0)
    stock_minimo = db.Column(db.Float, default=2.0)
    agotado_bodega = db.Column(db.Boolean, default=False)

class RecetaInsumoPOS(db.Model):
    __tablename__ = 'recetas_insumos_pos'
    id = db.Column(db.Integer, primary_key=True)
    platillo_nombre = db.Column(db.String(120), nullable=False) # Ej. CAPUCHINO o >LECHE DESLACTOSADA
    insumo_id = db.Column(db.Integer, db.ForeignKey('insumos_almacen.id'), nullable=False)
    cantidad_descontar = db.Column(db.Float, nullable=False) # Ej. 0.333 lt para 1 taza (1 L = 3 tazas)

class RequerimientoInterno(db.Model):
    __tablename__ = 'requerimientos_internos'
    id = db.Column(db.Integer, primary_key=True)
    folio = db.Column(db.String(20), nullable=False)
    area = db.Column(db.String(20), nullable=False) # BARRA / COCINA
    fecha = db.Column(db.DateTime, default=datetime.now)
    solicitado_por = db.Column(db.String(80), nullable=False)
    estado = db.Column(db.String(25), default='PENDIENTE') # PENDIENTE / ENTREGADO / PARCIAL
    notas_extra = db.Column(db.Text, nullable=True) # Ej. 2 Cheesecake, 1 Flan
    items = db.relationship('DetalleRequerimiento', backref='requerimiento', lazy=True, cascade="all, delete-orphan")

class DetalleRequerimiento(db.Model):
    __tablename__ = 'detalles_requerimiento'
    id = db.Column(db.Integer, primary_key=True)
    requerimiento_id = db.Column(db.Integer, db.ForeignKey('requerimientos_internos.id'), nullable=False)
    insumo_id = db.Column(db.Integer, nullable=True)
    subcategoria = db.Column(db.String(60), nullable=False)
    producto = db.Column(db.String(120), nullable=False)
    unidad = db.Column(db.String(30), nullable=False)
    solicitado = db.Column(db.Float, default=0.0)
    recibido = db.Column(db.Float, default=0.0)
    estado_item = db.Column(db.String(25), default='PENDIENTE') # PENDIENTE / ENTREGADO / AGOTADO

def sembrar_catalogo_hojas_quiosco():
    if InsumoAlmacen.query.count() > 0:
        return
    datos_hojas = {
        'BARRA': {
            'Frutas y verduras': [('Pepino','kg'),('Piña','kg'),('Fresa fresca','kg'),('Guineo','kg'),('Limón amarillo','kg'),('Arugula','kg'),('Menta/hierbabuena','gr'),('Jamaica','manojo'),('Melón','kg'),('Fresa congelada','gr'),('Limón','kg'),('Naranja','kg'),('Mora','gr')],
            'Especias': [('Jengibre','gr'),('Vainilla','bote'),('Canela','gr'),('Pimienta negra','gr'),('Clavo de olor','gr'),('Curcuma','gr')],
            'Insumos': [('Toronjil','gr'),('Moon milk','Kg'),('Maracuya','Kg'),('Chai en polvo','Kg'),('Taro','Kg'),('Tapioca','kg'),('Café en grano','kg'),('Café molido para refill','kg'),('Chocolate molido','kg'),('Té negro','gr'),('Crema lyncott','gr'),('Mermelada','lt'),('Chispas de chocolate','gr'),('Chispas multicolor','gr'),('Obleas de taro','paquete'),('Chocolate liquido','lt')],
            'Insumos limpieza y baños': [('Papel higienico','pzs'),('Papel de manos','pzs'),('Jabon de manos','lt'),('Cloro','lt'),('Fabuloso','lt'),('Jabon en polvo','kg'),('Jabon liquido','lt'),('Bolsas para basura','paquete'),('Liquido limpia vidrios y superficies','lt'),('Insecticida','pz'),('Gel antibacterial','lt'),('Escoba','pz'),('Trapeador','pz'),('Esponjas de colores','pz'),('Fibra verde','pz'),('Desodorante de baño','pz')],
            'Otros': [('Azucar en sobres','kg'),('Crema en polvo','kg'),('Azúcar','kg'),('Canela molida','kg'),('Yogurth griego','gr'),('Chia','gr'),('Tajin','gr'),('Salsa habanera','ml'),('splenda','pzs'),('Granola','gr'),('Nuez','gr')],
            'Refrescos y leche': [('Leche deslactosada','lt'),('Leche entera','lt'),('Carnation','lt'),('Coca cola','paquete'),('Sprite','paquete'),('Sidral','paquete'),('Agua ciel 600 ml','paquete'),('Agua mineral 600 ml','pza'),('Agua mineral lata','paquete')],
            'Cervezas': [('XX Lager','Caja'),('XX Ambar','Caja'),('Bohemia oscura','Caja'),('Bohemia clara','Caja')],
            'Desechables': [('Vasos de carton','pzs'),('Tapas para vasos de carton','pzs'),('Vasos de plastico','pzs'),('Tapas de boquilla','pzs'),('Tapas domo','pzs'),('Bolsas de sellado al vacio','rollo'),('Agitador de madera','paquete'),('Cucharas','pzs'),('Fajillas','pzs'),('Vasos 4oz (expreso)','pzs'),('Agitadores de madera','paquete'),('Servilletas','paquete'),('Azucar en sobres (caja)','caja'),('Splenda (caja)','caja'),('Popotes blancos','pzs'),('Popotes negros','pzs'),('Tenedores','pzs')],
            'Insumos barra': [('Rollos para tickets','pzs'),('Tinta de sello','pzs'),('Plumones','pzs'),('Bloc de notas','pzs'),('Cinta maskin','pzs')],
            'Postres': [('Corbata frutos rojos','pzs'),('Corbata guayaba','pzs'),('Chocolatin','pzs'),('Cuernito de nutella','pzs'),('Cheesecake','pzs'),('Flan','pzs')]
        },
        'COCINA': {
            'Frutas y verduras': [('Limón','lt'),('Cilantro','gr'),('Aguacate','kg'),('Platanos','kg'),('Tomate cherry','kg'),('Arugula','gr'),('Ajo','pz'),('Cebolla','kg'),('Lechuga','kg'),('Rabano','kg'),('Cebolla morada','kg'),('Guineo','kg'),('Fresa','kg'),('Tomate rojo','kg'),('Frambuesa','kg')],
            'Aderezos y más': [('Jocoque','bote'),('Queso de cabra','kg'),('Crema','lt'),('Mostaza','lt'),('Mayonesa','kg'),('Catsup','lt'),('Queso crema','kg'),('Queso doble crema (philadelphia)','kg'),('Queso amarillo','pz'),('Salsa tabasco','bote'),('Salsa inglesa','bote'),('Miel','lt'),('Mantequilla','gr'),('Catsup en sobres','caja')],
            'Enlatados': [('Aceitunas sin hueso','bote'),('Chipotle','bote'),('Chiles en rajas','Bote'),('champiñones','lt'),('Pepinillos','bote'),('Chicharos','lata'),('Lechera','pzs')],
            'Otros': [('Papas a la francesa','kg'),('Sal','kg'),('Aceite','lt'),('Aceite de oliva','lt'),('Papikra','bote'),('Ajo en polvo','bote'),('Cebolla en polvo','bote'),('Harina de hotcakes','kg'),('Azucar','kg'),('Huevos','casillero'),('Canela','gr'),('Vinagre de manzana','lt')],
            'Panes': [('Baguete de cereales','pz'),('Cuernitos','pz'),('Bimbollos','pz'),('Pan de molde de cereales','pz')],
            'Desechables': [('Bowl desechables','Pza'),('Salseras desechables','Pza'),('Charola craft','Pza'),('Bolsas craft','Pza'),('Papel de tortilla','pza'),('L38','pza'),('Bolsa transparente CH','paquete'),('Bolsa transparente G','paquete'),('Bolsa tipo camiseta G','paquete'),('Papel encerado','kg'),('Envases de 1 litro','pza'),('Tapas de salseras blancas','pza'),('Papel aluminio','rollo'),('Plastico film','rollo')],
            'Embutidos y mas': [('Jamon','kg'),('Tocino','kg'),('Jamón serrano','kg'),('Mortadela','kg'),('Pechuga congelada','pz'),('Chorizo','kg')],
            'Preparados': [('Asado coleto','lt'),('Carne de hamburguesa','pz'),('Salsa ranchera','lt'),('Salsa de motuleños','lt'),('Mole','lt'),('Frijoles','lt'),('Salsa matcha','lt'),('Salsa verde picante','lt')],
            'Insumos limpieza': [('Piedra pomez','pz'),('Fibra verde','pz'),('Fibra metalica','pz'),('Ajax','pz'),('Guantes','pz')],
            'Cocteles': [('Naked n mumo','lt'),('Guabi','lt'),('Morajillo','lt'),('Margariteco','lt')]
        }
    }
    for area, subcats in datos_hojas.items():
        for subcat, prods in subcats.items():
            for nom, uni in prods:
                db.session.add(InsumoAlmacen(area=area, subcategoria=subcat, producto=nom, unidad=uni, stock_actual=10.0, stock_minimo=2.0))
    
    # Crear usuario de Almacén Externo si no existe
    if not User.query.filter_by(username='almacen').first():
        db.session.add(User(username='almacen', password=generate_password_hash('almacen123'), role='almacen'))
    db.session.commit()

with app.app_context():
    db.create_all()
    sembrar_catalogo_hojas_quiosco()

# Función que descuenta leche/insumos automáticamente al cobrar o comandar
def descontar_insumos_por_venta(cuenta_obj):
    recetas = RecetaInsumoPOS.query.all()
    if not recetas:
        return
    for det in cuenta_obj.detalles:
        nom_limpio = det.descripcion.strip().upper()
        for r in recetas:
            if r.platillo_nombre.strip().upper() == nom_limpio:
                ins = InsumoAlmacen.query.get(r.insumo_id)
                if ins:
                    ins.stock_actual = round(max(0.0, ins.stock_actual - (r.cantidad_descontar * det.cantidad)), 3)

# --- 1 CLIC: PASAR PRE-ORDEN DE PLAQUITA DIRECTO AL POS E IMPRIMIR COMANDA ---
@app.route('/api/pos/confirmar_preorden_1clic/<int:preorden_id>', methods=['POST'])
@login_required
def api_confirmar_preorden_1clic(preorden_id):
    orden = PreOrden.query.get_or_404(preorden_id)
    if orden.estado == 'atendido':
        return jsonify({'ok': True, 'msg': 'Ya había sido enviada'})

    orden.estado = 'atendido'
    orden.atendido_por = current_user.username

    # Mapear número de plaquita (1 a 10) a T01..T10 o usar el nombre directo
    mesa_raw = orden.mesa.strip().upper()
    if mesa_raw.isdigit():
        mesa_pos = f"T{int(mesa_raw):02d}"
    else:
        mesa_pos = mesa_raw

    turno = obtener_turno_activo()
    cuenta = CuentaPOS.query.filter_by(mesa=mesa_pos, estado='ABIERTA').first()
    if not cuenta:
        hoy_inicio = datetime.now().replace(hour=0, minute=0, second=0)
        num_orden = CuentaPOS.query.filter(CuentaPOS.apertura >= hoy_inicio).count() + 1
        cuenta = CuentaPOS(
            turno_id=turno.id, orden=f"A{num_orden}",
            area='02 TERRAZA' if mesa_pos.startswith('T') else '01 COMEDOR',
            mesa=mesa_pos, mesero=current_user.username.upper(), personas=2,
            observaciones=orden.notas, estado='ABIERTA'
        )
        db.session.add(cuenta)
        db.session.flush()
    elif orden.notas:
        cuenta.observaciones = f"{cuenta.observaciones or ''} | {orden.notas}".strip(' |')

    # Parsear cada línea de la preorden: "• 2x Capuchino ($130)"
    por_area = {'BARRA': [], 'COCINA': []}
    for linea in orden.detalle_items.split('\n'):
        linea = linea.strip()
        if not linea:
            continue
        m = re.search(r'(\d+)x\s+(.+?)\s+\(\$([\d\.]+)\)', linea)
        if m:
            cant = float(m.group(1))
            nom_prod = m.group(2).strip()
            importe_tot = float(m.group(3))
            precio_u = round(importe_tot / cant, 2) if cant > 0 else importe_tot
        else:
            cant = 1.0
            nom_prod = linea.replace('•', '').strip()
            precio_u = 0.0
            importe_tot = 0.0

        prod_bd = Producto.query.filter(db.func.lower(Producto.nombre) == nom_prod.lower()).first()
        cat_nom = prod_bd.categoria if prod_bd else 'Barra'
        clave_p = f"0{prod_bd.id}" if prod_bd else "PRE"
        area_imp = detectar_area_impresion(cat_nom)

        det = DetallePOS(
            cuenta_id=cuenta.id, num_comanda=1, cantidad=cant, clave=clave_p,
            descripcion=nom_prod.upper(), area_impresion=area_imp,
            es_modificador=False, precio_unitario=precio_u, importe=importe_tot,
            impreso_comanda=True
        )
        db.session.add(det)
        por_area[area_imp].append(det)

    if orden.notas:
        mod_nota = DetallePOS(
            cuenta_id=cuenta.id, num_comanda=1, cantidad=1.0, clave='NOTA',
            descripcion=f">{orden.notas.upper()}", area_impresion='COCINA',
            es_modificador=True, precio_unitario=0.0, importe=0.0, impreso_comanda=True
        )
        db.session.add(mod_nota)
        por_area['BARRA'].append(mod_nota)
        por_area['COCINA'].append(mod_nota)

    db.session.flush()
    recalcular_totales_cuenta(cuenta)
    descontar_insumos_por_venta(cuenta)

    # Mandar a imprimir automáticamente a la impresora única de Caja (separando Barra y Cocina)
    ahora_str = datetime.now().strftime('%d/%m/%Y %I:%M:%S %p')
    for area_nom, lista in por_area.items():
        reales = [x for x in lista if not x.es_modificador]
        if not reales:
            continue
        filas_html = "".join([
            f"<tr><td style='width:20%;font-weight:bold;'>{'' if it.es_modificador else int(it.cantidad)}</td>"
            f"<td style='width:80%;font-weight:bold;'>{it.descripcion}</td></tr>"
            for it in lista
        ])
        html_t = f"""
        <div class='ticket-termico'>
            <div style='font-size:17px;font-weight:900;text-align:center;'>*** PRE-ORDEN {area_nom} ***</div>
            <div style='text-align:center;font-size:12px;'>MESA: <b>{cuenta.mesa}</b> | CLIENTE: <b>{orden.cliente_nombre.upper()}</b></div>
            <div style='text-align:center;font-size:11px;'>CONFIRMÓ: {current_user.username.upper()} | {ahora_str}</div>
            <div style='border-top:2px dashed #000;margin:6px 0;'></div>
            <table style='width:100%;font-size:15px;'>{filas_html}</table>
            <div style='border-top:2px dashed #000;margin:8px 0;'></div>
        </div>"""
        db.session.add(ColaImpresionPOS(tipo=f"COMANDA_{area_nom}", contenido_html=html_t))

    db.session.commit()
    return jsonify({'ok': True, 'mesa': cuenta.mesa, 'cuenta_id': cuenta.id})

# --- VISTA DE HOJAS DE REQUERIMIENTO INTERNO (BARRA / COCINA) Y ALMACÉN ---
@app.route('/almacen_requerimientos')
@login_required
def almacen_requerimientos():
    insumos = InsumoAlmacen.query.order_by(InsumoAlmacen.id.asc()).all()
    requerimientos = RequerimientoInterno.query.order_by(RequerimientoInterno.id.desc()).limit(25).all()
    recetas = RecetaInsumoPOS.query.all()
    productos_menu = Producto.query.order_by(Producto.nombre.asc()).all()
    permisos = ConfigPermisosPOS.query.first()
    return render_template('almacen_requerimientos.html',
                           insumos=insumos, requerimientos=requerimientos,
                           recetas=recetas, productos_menu=productos_menu, permisos=permisos)

@app.route('/api/almacen/crear_requerimiento', methods=['POST'])
@login_required
def api_crear_requerimiento():
    data = request.json
    area = data.get('area', 'BARRA')
    hoy_num = RequerimientoInterno.query.count() + 1
    nuevo_req = RequerimientoInterno(
        folio=f"REQ-{hoy_num:04d}", area=area,
        solicitado_por=current_user.username.upper(),
        notas_extra=data.get('notas_extra', ''), estado='PENDIENTE'
    )
    db.session.add(nuevo_req)
    db.session.flush()

    for it in data.get('items', []):
        cant_sol = float(it.get('solicitado', 0))
        if cant_sol > 0:
            ins = InsumoAlmacen.query.get(int(it['insumo_id']))
            if ins:
                db.session.add(DetalleRequerimiento(
                    requerimiento_id=nuevo_req.id, insumo_id=ins.id,
                    subcategoria=ins.subcategoria, producto=ins.producto,
                    unidad=ins.unidad, solicitado=cant_sol, recibido=0.0,
                    estado_item='PENDIENTE'
                ))
    db.session.commit()
    return jsonify({'ok': True, 'folio': nuevo_req.folio})

@app.route('/api/almacen/surtir_item', methods=['POST'])
@login_required
def api_surtir_item():
    data = request.json
    det = DetalleRequerimiento.query.get_or_404(data['detalle_id'])
    det.recibido = float(data.get('recibido', det.solicitado))
    det.estado_item = data.get('estado_item', 'ENTREGADO') # ENTREGADO / AGOTADO / PENDIENTE

    if det.insumo_id:
        ins = InsumoAlmacen.query.get(det.insumo_id)
        if ins:
            if det.estado_item == 'ENTREGADO':
                ins.stock_actual = round(ins.stock_actual + det.recibido, 2)
                ins.agotado_bodega = False
            elif det.estado_item == 'AGOTADO':
                ins.agotado_bodega = True

    # Verificar si toda la hoja ya fue revisada
    req = det.requerimiento
    if all(x.estado_item in ['ENTREGADO', 'AGOTADO'] for x in req.items):
        req.estado = 'ENTREGADO'
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/almacen/guardar_receta', methods=['POST'])
@login_required
def api_guardar_receta():
    data = request.json
    nueva = RecetaInsumoPOS(
        platillo_nombre=str(data['platillo']).strip().upper(),
        insumo_id=int(data['insumo_id']),
        cantidad_descontar=float(data['cantidad'])
    )
    db.session.add(nueva)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/pos/permisos_raquel', methods=['POST'])
@login_required
def api_permisos_raquel():
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    p = ConfigPermisosPOS.query.first()
    data = request.json
    p.cajero_puede_cancelar = bool(data.get('cancelar', True))
    p.cajero_puede_descontar = bool(data.get('descontar', True))
    p.cajero_puede_cambiar_pago = bool(data.get('cambiar_pago', True))
    db.session.commit()
    return jsonify({'ok': True})

# ==============================================================================
# BLOQUE 3: MODIFICADORES EDITABLES POR RAQUEL + ALGORITMO PIN INTELIGENTE + TABLET
# Pegar justo antes de: if __name__ == '__main__':
# ==============================================================================
class ModificadorPOS(db.Model):
    __tablename__ = 'modificadores_pos'
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(20), nullable=False, default='03001')
    grupo = db.Column(db.String(50), nullable=False, default='SABORES')
    nombre = db.Column(db.String(100), nullable=False)
    precio = db.Column(db.Float, default=0.0)
    activo = db.Column(db.Boolean, default=True)

def sembrar_modificadores_iniciales():
    try:
        db.session.execute(text("ALTER TABLE modificadores_pos ADD COLUMN IF NOT EXISTS grupo VARCHAR(50) DEFAULT 'SABORES';"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    iniciales = [
        ('03001', 'TIPO DE LECHE', 'NORMAL (ENTERA)', 0.0),
        ('03002', 'TIPO DE LECHE', 'LECHE DESLACTOSADA', 0.0),
        ('03003', 'TIPO DE LECHE', 'LECHE ALMENDRAS', 15.0),
        ('03010', 'CARGAS DE CAFE', 'CARGA NORMAL', 0.0),
        ('03011', 'CARGAS DE CAFE', 'EXTRA SHOT CAFE', 18.0),
        ('03012', 'CARGAS DE CAFE', 'DESCAFEINADO', 0.0),
        ('03021', 'SABORES', 'CARAMELO', 15.0),
        ('03022', 'SABORES', 'MOKA', 15.0),
        ('03023', 'SABORES', 'NORMAL', 0.0),
        ('03024', 'SABORES', 'VAINILLA', 15.0),
        ('03030', 'FRIO O CALIENTE', 'CALIENTE', 0.0),
        ('03031', 'FRIO O CALIENTE', 'FRIO', 5.0),
        ('03040', 'EXTRAS ALIMENTOS', 'FRUTAS PAQUETE', 0.0),
        ('03041', 'EXTRAS ALIMENTOS', 'JAMON', 0.0),
        ('03042', 'EXTRAS ALIMENTOS', 'CAFE REFILL', 0.0),
        ('03043', 'EXTRAS ALIMENTOS', 'SIN CEBOLLA', 0.0),
        ('03044', 'EXTRAS ALIMENTOS', 'SIN HIELO', 0.0),
        ('03045', 'EXTRAS ALIMENTOS', 'PARA LLEVAR', 0.0)
    ]
    for clv, grp, nom, pre in iniciales:
        existente = ModificadorPOS.query.filter_by(nombre=nom).first()
        if not existente:
            db.session.add(ModificadorPOS(clave=clv, grupo=grp, nombre=nom, precio=pre, activo=True))
        else:
            existente.grupo = grp
    db.session.commit()

with app.app_context():
    db.create_all()
    sembrar_modificadores_iniciales()

# --- API DE MODIFICADORES PARA QUE RAQUEL LOS AGREGUE/EDITE/ELIMINE ---
@app.route('/api/pos/modificadores', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_pos_modificadores():
    if request.method == 'GET':
        mods = ModificadorPOS.query.filter_by(activo=True).order_by(ModificadorPOS.id.asc()).all()
        return jsonify({'ok': True, 'modificadores': [
            {'id': m.id, 'clave': m.clave, 'grupo': getattr(m, 'grupo', 'SABORES') or 'SABORES', 'nombre': m.nombre, 'precio': m.precio} for m in mods
        ]})

    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Raquel (Admin) puede modificar catálogos.'}), 403

    data = request.json
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip().upper().replace('>', '')
        grp = str(data.get('grupo', 'SABORES')).strip().upper()
        pre = float(data.get('precio', 0))
        clv = str(data.get('clave', f"030{ModificadorPOS.query.count()+20}")).strip()
        if not nom:
            return jsonify({'ok': False, 'msg': 'Escribe el nombre del modificador'}), 400
        nuevo = ModificadorPOS(clave=clv, grupo=grp, nombre=nom, precio=pre, activo=True)
        db.session.add(nuevo)
        db.session.commit()
        return jsonify({'ok': True})

    if request.method == 'DELETE':
        m = ModificadorPOS.query.get_or_404(int(data.get('id')))
        db.session.delete(m)
        db.session.commit()
        return jsonify({'ok': True})

# --- ALGORITMO INTELIGENTE DE PIN DE CONSUMO (GENERA O REIMPRIME SI NO SE HA CANJEADO) ---
@app.route('/api/pos/pin_inteligente/<int:cuenta_id>', methods=['POST'])
@login_required
def api_pos_pin_inteligente(cuenta_id):
    c = CuentaPOS.query.get_or_404(cuenta_id)
    c.impresa = True
    ref_folio = f"CTA-{c.id}-{c.orden}"

    # 1. Buscar si esta cuenta ya tiene un PIN generado que NO haya sido canjeado (activo=True)
    pin_existente = PinCaja.query.filter_by(folio_sr=ref_folio, activo=True).first()
    if pin_existente:
        db.session.commit()
        return jsonify({
            'ok': True,
            'codigo': pin_existente.codigo,
            'reimpreso': True,
            'folio_sr': ref_folio,
            'hora': pin_existente.fecha_creacion.strftime('%d/%m/%Y %H:%M')
        })

    # 2. Si no existe o ya lo canjearon, genera un código único nuevo de 4 dígitos
    while True:
        nuevo_cod = ''.join(random.choices(string.digits, k=4))
        if not PinCaja.query.filter_by(codigo=nuevo_cod, activo=True).first():
            break

    nuevo_pin = PinCaja(
        codigo=nuevo_cod,
        activo=True,
        creado_por=current_user.username,
        folio_sr=ref_folio,
        fecha_creacion=datetime.now()
    )
    db.session.add(nuevo_pin)
    db.session.commit()
    return jsonify({
        'ok': True,
        'codigo': nuevo_pin.codigo,
        'reimpreso': False,
        'folio_sr': ref_folio,
        'hora': nuevo_pin.fecha_creacion.strftime('%d/%m/%Y %H:%M')
    })

# --- API EN VIVO PARA LAS TARJETAS DE LA TABLET DEL MESERO (M1..M6 Y T01..T12) ---
@app.route('/api/pos/estado_mesas_tablet')
@login_required
def api_pos_estado_mesas_tablet():
    abiertas = CuentaPOS.query.filter_by(estado='ABIERTA').order_by(CuentaPOS.id.asc()).all()
    mapa_abiertas = {c.mesa.upper(): c for c in abiertas}

    orden_fijo = ['M1','M2','M3','M4','M5','M6'] + [f"T{i:02d}" for i in range(1, 13)]
    tarjetas = []
    vistas = set()

    for cod in orden_fijo:
        alt = f"M0{cod[1:]}" if (cod.startswith('M') and len(cod)==2) else cod
        c = mapa_abiertas.get(cod) or mapa_abiertas.get(alt)
        if c:
            vistas.add(c.id)
            tarjetas.append({
                'codigo': cod,
                'ocupada': True,
                'cuenta_id': c.id,
                'titulo': c.observaciones.strip().upper() if (c.observaciones and len(c.observaciones.strip())<=14) else c.mesa,
                'total': f"{c.total:.2f}",
                'personas': c.personas,
                'mesero': c.mesero
            })
        else:
            tarjetas.append({
                'codigo': cod,
                'ocupada': False,
                'cuenta_id': None,
                'titulo': cod,
                'total': '0.00',
                'personas': 0,
                'mesero': ''
            })

    for c in abiertas:
        if c.id not in vistas:
            tarjetas.insert(0, {
                'codigo': c.mesa,
                'ocupada': True,
                'cuenta_id': c.id,
                'titulo': c.mesa,
                'total': f"{c.total:.2f}",
                'personas': c.personas,
                'mesero': c.mesero
            })

    return jsonify({'ok': True, 'tarjetas': tarjetas})

# --- GUARDAR OBSERVACIONES O CLIENTE EN LA CUENTA ---
@app.route('/api/pos/guardar_obs', methods=['POST'])
@login_required
def api_pos_guardar_obs():
    data = request.json
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    c.observaciones = str(data.get('observaciones', '')).strip()
    db.session.commit()
    return jsonify({'ok': True})

# ==============================================================================
# API RÁPIDA DE CATÁLOGOS EN VIVO PARA RAQUEL (DESDE EL POS VERDE MORISCO)
# ==============================================================================

@app.route('/api/pos/catalogo_completo')
@login_required
def api_pos_catalogo_completo():
    cats = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    prods = Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all()
    mods = ModificadorPOS.query.filter_by(activo=True).order_by(ModificadorPOS.id.asc()).all()
    return jsonify({
        'ok': True,
        'categorias': [{'id': c.id, 'nombre': c.nombre, 'nombre_en': c.nombre_en or ''} for c in cats],
        'productos': [{
            'id': p.id, 'nombre': p.nombre, 'precio': p.precio,
            'categoria': p.categoria, 'agotado': p.agotado, 'destacado': p.destacado
        } for p in prods],
        'modificadores': [{
            'id': m.id, 'clave': m.clave,
            'grupo': getattr(m, 'grupo', 'SABORES') or 'SABORES',
            'nombre': m.nombre, 'precio': m.precio
        } for m in mods]
    })

@app.route('/api/pos/admin_producto', methods=['POST', 'PUT', 'DELETE'])
@login_required
def api_pos_admin_producto():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Raquel (Admin) puede modificar productos.'}), 403
    data = request.json
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip()
        cat = str(data.get('categoria', '')).strip()
        pre = float(data.get('precio', 0))
        desc = str(data.get('descripcion', '')).strip()
        if not nom or not cat:
            return jsonify({'ok': False, 'msg': 'Nombre y categoría requeridos'}), 400
        nuevo = Producto(nombre=nom, precio=pre, categoria=cat, descripcion=desc, agotado=False, destacado=False)
        db.session.add(nuevo)
        db.session.commit()
        return jsonify({'ok': True})

    if request.method == 'PUT':
        p = Producto.query.get_or_404(int(data['id']))
        p.nombre = str(data.get('nombre', p.nombre)).strip()
        p.precio = float(data.get('precio', p.precio))
        p.categoria = str(data.get('categoria', p.categoria)).strip()
        db.session.commit()
        return jsonify({'ok': True})

    if request.method == 'DELETE':
        p = Producto.query.get_or_404(int(data['id']))
        db.session.delete(p)
        db.session.commit()
        return jsonify({'ok': True})

@app.route('/api/pos/admin_categoria', methods=['POST', 'DELETE'])
@login_required
def api_pos_admin_categoria():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Raquel (Admin) puede modificar categorías.'}), 403
    data = request.json
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip()
        if nom and not CategoriaMenu.query.filter_by(nombre=nom).first():
            db.session.add(CategoriaMenu(nombre=nom, nombre_en=str(data.get('nombre_en', '')).strip()))
            db.session.commit()
        return jsonify({'ok': True})

    if request.method == 'DELETE':
        c = CategoriaMenu.query.get_or_404(int(data['id']))
        if Producto.query.filter_by(categoria=c.nombre).first():
            return jsonify({'ok': False, 'msg': 'No puedes borrar una categoría que tiene platillos.'}), 400
        db.session.delete(c)
        db.session.commit()
        return jsonify({'ok': True})
    
# ==============================================================================
# FASE 1 PRO: BITÁCORA, AUTORIZACIONES, ARQUEO DE CAJA, ALERTAS Y RELOJ DE MESAS
# Pegar justo antes de: if __name__ == '__main__':
# ==============================================================================

class BitacoraPOS(db.Model):
    __tablename__ = 'bitacora_pos'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    usuario = db.Column(db.String(80), nullable=False)
    autorizo = db.Column(db.String(80), nullable=True)
    accion = db.Column(db.String(60), nullable=False)  # DESCUENTO, CANCELACION, MOVER_MESA, DIVIDIR, CIERRE_CAJA, RETIRO
    mesa = db.Column(db.String(30), nullable=True)
    monto = db.Column(db.Float, default=0.0)
    detalle = db.Column(db.String(255), nullable=True)

class AlertaMesaPOS(db.Model):
    __tablename__ = 'alertas_mesa_pos'
    id = db.Column(db.Integer, primary_key=True)
    cuenta_id = db.Column(db.Integer, unique=True, nullable=False)
    solicito_cuenta = db.Column(db.Boolean, default=False)
    descuento_motivo = db.Column(db.String(200), nullable=True)
    fecha_alerta = db.Column(db.DateTime, default=datetime.now)

class ArqueoTurnoPOS(db.Model):
    __tablename__ = 'arqueos_turno_pos'
    id = db.Column(db.Integer, primary_key=True)
    turno_id = db.Column(db.Integer, nullable=False)
    cajero = db.Column(db.String(80), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.now)
    ef_declarado = db.Column(db.Float, default=0.0)
    td_declarado = db.Column(db.Float, default=0.0)
    tc_declarado = db.Column(db.Float, default=0.0)
    amex_declarado = db.Column(db.Float, default=0.0)
    cr_declarado = db.Column(db.Float, default=0.0)
    dll_declarado = db.Column(db.Float, default=0.0)
    val_declarado = db.Column(db.Float, default=0.0)
    esperado_total = db.Column(db.Float, default=0.0)
    declarado_total = db.Column(db.Float, default=0.0)
    diferencia = db.Column(db.Float, default=0.0)

with app.app_context():
    db.create_all()

def registrar_bitacora(accion, mesa='', monto=0.0, detalle='', autorizo=''):
    try:
        db.session.add(BitacoraPOS(
            usuario=current_user.username.upper() if current_user.is_authenticated else 'SISTEMA',
            autorizo=autorizo.upper() if autorizo else '',
            accion=accion,
            mesa=str(mesa),
            monto=float(monto or 0),
            detalle=str(detalle)[:250]
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

def validar_clave_admin(clave_ingresada):
    clave = str(clave_ingresada or '').strip()
    if not clave:
        return None
    admins = User.query.filter_by(role='admin').all()
    for adm in admins:
        if check_password_hash(adm.password, clave):
            return adm.username.upper()
    return None

# --- 1. ESTADO DE MESAS EN VIVO (CON RELOJ DE ESTANCIA, IMPRESA Y ALERTA DE CUENTA) ---
@app.route('/api/pos/mesas_tablet_v2')
@login_required
def api_pos_mesas_tablet_v2():
    abiertas = CuentaPOS.query.filter_by(estado='ABIERTA').order_by(CuentaPOS.id.asc()).all()
    mapa_abiertas = {c.mesa.upper(): c for c in abiertas}
    alertas = {a.cuenta_id: a for a in AlertaMesaPOS.query.all()}
    ahora = datetime.now()

    orden_fijo = ['M1','M2','M3','M4','M5','M6'] + [f"T{i:02d}" for i in range(1, 13)]
    tarjetas = []
    vistas = set()

    def armar_tarjeta(cod, c):
        if c:
            al = alertas.get(c.id)
            mins = int((ahora - c.apertura).total_seconds() // 60) if c.apertura else 0
            return {
                'codigo': cod,
                'ocupada': True,
                'impresa': bool(c.impresa),
                'solicito_cuenta': bool(al.solicito_cuenta) if al else False,
                'minutos': max(0, mins),
                'cuenta_id': c.id,
                'titulo': c.observaciones.strip().upper() if (c.observaciones and len(c.observaciones.strip()) <= 14) else c.mesa,
                'total': f"{c.total:.2f}",
                'personas': c.personas,
                'mesero': c.mesero,
                'orden': c.orden
            }
        return {
            'codigo': cod, 'ocupada': False, 'impresa': False,
            'solicito_cuenta': False, 'minutos': 0, 'cuenta_id': None,
            'titulo': cod, 'total': '0.00', 'personas': 0, 'mesero': '', 'orden': ''
        }

    for cod in orden_fijo:
        alt = f"M0{cod[1:]}" if (cod.startswith('M') and len(cod) == 2) else cod
        c = mapa_abiertas.get(cod) or mapa_abiertas.get(alt)
        if c:
            vistas.add(c.id)
        tarjetas.append(armar_tarjeta(cod, c))

    for c in abiertas:
        if c.id not in vistas:
            tarjetas.insert(0, armar_tarjeta(c.mesa, c))

    return jsonify({'ok': True, 'tarjetas': tarjetas})

# --- 2. SOLICITAR CUENTA A CAJA (HACE PARPADEAR LA MESA EN EL MONITOR DEL CAJERO) ---
@app.route('/api/pos/solicitar_cuenta/<int:cuenta_id>', methods=['POST'])
@login_required
def api_pos_solicitar_cuenta(cuenta_id):
    c = CuentaPOS.query.get_or_404(cuenta_id)
    al = AlertaMesaPOS.query.filter_by(cuenta_id=c.id).first()
    if not al:
        al = AlertaMesaPOS(cuenta_id=c.id, solicito_cuenta=True, fecha_alerta=datetime.now())
        db.session.add(al)
    else:
        al.solicito_cuenta = True
        al.fecha_alerta = datetime.now()
    db.session.commit()
    return jsonify({'ok': True, 'mesa': c.mesa})

# --- 3. MOVER / TRASPASAR MESA (EJ. T02 -> M3 POR LLUVIA) ---
@app.route('/api/pos/mover_mesa_rapido', methods=['POST'])
@login_required
def api_pos_mover_mesa_rapido():
    data = request.json
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    nueva_mesa = str(data.get('nueva_mesa', '')).strip().upper()
    if not nueva_mesa:
        return jsonify({'ok': False, 'msg': 'Selecciona una mesa destino.'}), 400
    ocupada = CuentaPOS.query.filter_by(mesa=nueva_mesa, estado='ABIERTA').first()
    if ocupada and ocupada.id != c.id:
        return jsonify({'ok': False, 'msg': f'La mesa {nueva_mesa} ya está ocupada.'}), 400

    mesa_anterior = c.mesa
    c.mesa = nueva_mesa
    c.area = '02 TERRAZA' if nueva_mesa.startswith('T') else '01 COMEDOR'
    db.session.commit()
    registrar_bitacora('MOVER_MESA', nueva_mesa, c.total, f'Movida de {mesa_anterior} a {nueva_mesa}')
    return jsonify({'ok': True, 'mesa': nueva_mesa})

# --- 4. DESCUENTO CON CRITERIO, COMENTARIO Y CONTRASEÑA DE AUTORIZACIÓN ---
@app.route('/api/pos/descuento_autorizado', methods=['POST'])
@login_required
def api_pos_descuento_autorizado():
    data = request.json
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    pct = float(data.get('porcentaje', 0))
    criterio = str(data.get('criterio', 'CORTESIA')).strip().upper()
    comentario = str(data.get('comentario', '')).strip()
    clave = data.get('clave_admin', '')

    autorizo = current_user.username.upper() if current_user.role == 'admin' else validar_clave_admin(clave)
    if not autorizo:
        return jsonify({'ok': False, 'msg': 'Contraseña de autorización incorrecta.'}), 403

    c.descuento_pct = max(0.0, min(100.0, pct))
    recalcular_totales_cuenta(c)

    al = AlertaMesaPOS.query.filter_by(cuenta_id=c.id).first()
    motivo_txt = f"{criterio}: {comentario}" if comentario else criterio
    if not al:
        db.session.add(AlertaMesaPOS(cuenta_id=c.id, descuento_motivo=motivo_txt))
    else:
        al.descuento_motivo = motivo_txt

    db.session.commit()
    registrar_bitacora('DESCUENTO', c.mesa, c.descuento_monto, f'{pct}% ({motivo_txt})', autorizo=autorizo)
    return jsonify({'ok': True, 'descuento_monto': c.descuento_monto, 'total': c.total})

# --- 5. DIVIDIR CUENTA REAL (SEPARA PRODUCTOS SELECCIONADOS A UNA CUENTA NUEVA) ---
@app.route('/api/pos/dividir_cuenta_real', methods=['POST'])
@login_required
def api_pos_dividir_cuenta_real():
    data = request.json
    c_orig = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    item_ids = [int(x) for x in data.get('item_ids', [])]
    if not item_ids:
        return jsonify({'ok': False, 'msg': 'Selecciona al menos un producto para mover.'}), 400

    turno = obtener_turno_activo()
    hoy_inicio = datetime.now().replace(hour=0, minute=0, second=0)
    num_orden = CuentaPOS.query.filter(CuentaPOS.apertura >= hoy_inicio).count() + 1
    nueva_mesa = f"{c_orig.mesa}-B"
    if CuentaPOS.query.filter_by(mesa=nueva_mesa, estado='ABIERTA').first():
        nueva_mesa = f"{c_orig.mesa}-{num_orden}"

    c_nueva = CuentaPOS(
        turno_id=turno.id, orden=f"A{num_orden}", area=c_orig.area,
        mesa=nueva_mesa, mesero=c_orig.mesero, personas=1, estado='ABIERTA'
    )
    db.session.add(c_nueva)
    db.session.flush()

    for det in list(c_orig.detalles):
        if det.id in item_ids:
            det.cuenta_id = c_nueva.id

    db.session.flush()
    recalcular_totales_cuenta(c_orig)
    recalcular_totales_cuenta(c_nueva)
    db.session.commit()
    registrar_bitacora('DIVIDIR_CUENTA', c_orig.mesa, c_nueva.total, f'Separó {len(item_ids)} prod. a {nueva_mesa}')
    return jsonify({'ok': True, 'nueva_cuenta_id': c_nueva.id, 'nueva_mesa': nueva_mesa})

# --- 6. CIERRE DE CAJA POR IMPORTES DECLARADOS (ARQUEO VISIBLE) ---
@app.route('/api/pos/cerrar_turno_arqueo', methods=['POST'])
@login_required
def api_pos_cerrar_turno_arqueo():
    if current_user.role == 'mesero':
        return jsonify({'ok': False, 'msg': 'Solo Caja o Admin pueden cerrar turno.'}), 403

    data = request.json
    turno = obtener_turno_activo()
    cuentas_pagadas = CuentaPOS.query.filter_by(turno_id=turno.id, estado='PAGADA').all()

    ef_esp = sum(max(0.0, c.pago_efectivo - c.cambio) for c in cuentas_pagadas)
    td_esp = sum(c.pago_tarjeta_debito for c in cuentas_pagadas)
    tc_esp = sum(c.pago_tarjeta_credito for c in cuentas_pagadas)
    prop_esp = sum(c.propina_tarjeta for c in cuentas_pagadas)
    efectivo_esperado_caja = round(turno.fondo_inicial + ef_esp + turno.depositos_efectivo - turno.retiros_efectivo - prop_esp, 2)
    esperado_total = round(efectivo_esperado_caja + td_esp + tc_esp, 2)

    ef_dec = float(data.get('EF', 0))
    td_dec = float(data.get('TARJD', 0))
    tc_dec = float(data.get('TARJC', 0))
    amex_dec = float(data.get('AMEX', 0))
    cr_dec = float(data.get('CR', 0))
    dll_dec = float(data.get('DLL', 0))
    val_dec = float(data.get('VAL', 0))
    declarado_total = round(ef_dec + td_dec + tc_dec + amex_dec + cr_dec + dll_dec + val_dec, 2)
    diferencia = round(declarado_total - esperado_total, 2)

    arqueo = ArqueoTurnoPOS(
        turno_id=turno.id, cajero=current_user.username.upper(),
        ef_declarado=ef_dec, td_declarado=td_dec, tc_declarado=tc_dec,
        amex_declarado=amex_dec, cr_declarado=cr_dec, dll_declarado=dll_dec, val_declarado=val_dec,
        esperado_total=esperado_total, declarado_total=declarado_total, diferencia=diferencia
    )
    db.session.add(arqueo)

    turno.cierre = datetime.now()
    turno.estado = 'CERRADO'
    nuevo_turno = TurnoPOS(cajero=current_user.username.upper(), fondo_inicial=0.0, estado='ABIERTO')
    db.session.add(nuevo_turno)
    db.session.flush()
    for ca in CuentaPOS.query.filter_by(estado='ABIERTA').all():
        ca.turno_id = nuevo_turno.id

    db.session.commit()
    registrar_bitacora('CIERRE_CAJA', f'TURNO #{turno.id}', declarado_total, f'Esperado: ${esperado_total} | Dif: ${diferencia}')
    return jsonify({
        'ok': True, 'esperado': f"{esperado_total:.2f}",
        'declarado': f"{declarado_total:.2f}", 'diferencia': f"{diferencia:.2f}"
    })

# --- 7. CONSULTAR BITÁCORA DE AUDITORÍA (MÓDULO A) ---
@app.route('/api/pos/bitacora_auditoria')
@login_required
def api_pos_bitacora_auditoria():
    regs = BitacoraPOS.query.order_by(BitacoraPOS.id.desc()).limit(80).all()
    return jsonify({'ok': True, 'registros': [{
        'fecha': r.fecha.strftime('%d/%m %H:%M'),
        'usuario': r.usuario, 'autorizo': r.autorizo or '-',
        'accion': r.accion, 'mesa': r.mesa or '-',
        'monto': f"{r.monto:.2f}", 'detalle': r.detalle or ''
    } for r in regs]})
# ==============================================================================
# # ==============================================================================
# FASE 2 PRO: ALMACÉN INTELIGENTE, BODEGA POR CATEGORÍAS, CAJA Y PROVEEDORES
# ==============================================================================

class InsumoBodegaPro(db.Model):
    __tablename__ = 'insumos_bodega_pro'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(60), nullable=False, default='ABARROTES')
    unidad = db.Column(db.String(20), nullable=False, default='PZA')
    stock_actual = db.Column(db.Float, default=0.0)
    stock_minimo = db.Column(db.Float, default=5.0)
    costo_unitario = db.Column(db.Float, default=0.0)

class RequerimientoBodega(db.Model):
    __tablename__ = 'requerimientos_bodega'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    area = db.Column(db.String(30), nullable=False, default='BARRA')  # BARRA o COCINA
    insumo_id = db.Column(db.Integer, nullable=True)
    insumo_nombre = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(60), nullable=False, default='ABARROTES')
    cantidad = db.Column(db.Float, default=1.0)
    unidad = db.Column(db.String(20), default='PZA')
    estado_bodega = db.Column(db.String(25), default='PENDIENTE')  # PENDIENTE, ENTREGADO, NO_ENTREGADO
    confirmado_caja = db.Column(db.Boolean, default=False)
    solicitado_por = db.Column(db.String(60), default='CAJA')
    nota = db.Column(db.String(180), default='')

class MovimientoAlmacen(db.Model):
    __tablename__ = 'movimientos_almacen'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    tipo = db.Column(db.String(30), nullable=False)  # ENTRADA_COMPRA, SALIDA_MERMA, TRASPASO
    insumo_nombre = db.Column(db.String(120), nullable=False)
    cantidad = db.Column(db.Float, default=0.0)
    costo_total = db.Column(db.Float, default=0.0)
    proveedor = db.Column(db.String(100), default='')
    usuario = db.Column(db.String(60), default='')
    nota = db.Column(db.String(200), default='')

class ProveedorAlmacen(db.Model):
    __tablename__ = 'proveedores_almacen'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(40), default='')
    categoria = db.Column(db.String(60), default='GENERAL')
    saldo_pendiente = db.Column(db.Float, default=0.0)

def sembrar_insumos_bodega_pro():
    if InsumoBodegaPro.query.count() > 0:
        return
    base = [
        ('LECHE ENTERA', 'LÁCTEOS', 'LT', 12, 6, 26.0),
        ('LECHE DESLACTOSADA', 'LÁCTEOS', 'LT', 8, 5, 29.0),
        ('LECHE DE ALMENDRAS', 'LÁCTEOS', 'LT', 3, 4, 48.0),
        ('CAFÉ EN GRANO CHIAPAS', 'CAFÉ Y BARRA', 'KG', 5, 3, 240.0),
        ('JARABE CARAMELO', 'CAFÉ Y BARRA', 'LT', 2, 2, 165.0),
        ('JARABE VAINILLA', 'CAFÉ Y BARRA', 'LT', 2, 2, 165.0),
        ('CHOCOLATE MOKA POLVO', 'CAFÉ Y BARRA', 'KG', 2, 2, 180.0),
        ('BOLSA DE HIELO 5KG', 'CAFÉ Y BARRA', 'PZA', 4, 5, 35.0),
        ('HUEVO', 'COCINA Y FRESCOS', 'KG', 6, 4, 48.0),
        ('JAMÓN DE PAVO', 'COCINA Y FRESCOS', 'KG', 2, 2, 145.0),
        ('QUESO MANCHEGO', 'COCINA Y FRESCOS', 'KG', 3, 2, 170.0),
        ('NARANJA PARA JUGO', 'FRUTAS Y VERDURAS', 'KG', 10, 8, 22.0),
        ('VASO 12 OZ CON TAPA', 'DESECHABLES', 'PQTE', 3, 4, 95.0),
        ('SERVILLETAS', 'DESECHABLES', 'PQTE', 6, 4, 38.0)
    ]
    for nom, cat, uni, st, mn, cst in base:
        db.session.add(InsumoBodegaPro(
            nombre=nom, categoria=cat, unidad=uni,
            stock_actual=st, stock_minimo=mn, costo_unitario=cst
        ))
    db.session.commit()

with app.app_context():
    db.create_all()
    sembrar_insumos_bodega_pro()

@app.route('/almacen_pro')
@login_required
def vista_almacen_pro():
    return render_template('almacen_pro.html')

@app.route('/api/almacen/datos')
@login_required
def api_almacen_datos():
    insumos = InsumoBodegaPro.query.order_by(InsumoBodegaPro.categoria.asc(), InsumoBodegaPro.nombre.asc()).all()
    reqs = RequerimientoBodega.query.order_by(RequerimientoBodega.id.desc()).limit(100).all()
    movs = MovimientoAlmacen.query.order_by(MovimientoAlmacen.id.desc()).limit(60).all()
    provs = ProveedorAlmacen.query.order_by(ProveedorAlmacen.nombre.asc()).all()

    # MOTOR INTELIGENTE DE RECOMENDACIÓN DE COMPRAS
    recomendaciones = []
    ya_en_rec = set()

    # 1. Insumos que Bodega marcó como NO_ENTREGADO recientemente
    for r in reqs:
        if r.estado_bodega == 'NO_ENTREGADO' and r.insumo_nombre not in ya_en_rec:
            ya_en_rec.add(r.insumo_nombre)
            recomendaciones.append({
                'nombre': r.insumo_nombre,
                'categoria': r.categoria,
                'motivo': f'Bodega marcó NO ENTREGADO ({r.cantidad} {r.unidad})',
                'sugerido': max(r.cantidad, 2),
                'unidad': r.unidad,
                'urgencia': 'ALTA'
            })

    # 2. Insumos cuyo stock actual está igual o debajo del mínimo
    for i in insumos:
        if i.stock_actual <= i.stock_minimo and i.nombre not in ya_en_rec:
            ya_en_rec.add(i.nombre)
            faltante = max(1, round((i.stock_minimo * 2) - i.stock_actual, 1))
            recomendaciones.append({
                'nombre': i.nombre,
                'categoria': i.categoria,
                'motivo': f'Stock bajo ({i.stock_actual} / mín {i.stock_minimo} {i.unidad})',
                'sugerido': faltante,
                'unidad': i.unidad,
                'urgencia': 'ALTA' if i.stock_actual <= 0 else 'MEDIA'
            })

    return jsonify({
        'ok': True,
        'insumos': [{
            'id': i.id, 'nombre': i.nombre, 'categoria': i.categoria, 'unidad': i.unidad,
            'stock_actual': i.stock_actual, 'stock_minimo': i.stock_minimo, 'costo_unitario': i.costo_unitario
        } for i in insumos],
        'requerimientos': [{
            'id': r.id, 'fecha': r.fecha.strftime('%d/%m %H:%M'), 'area': r.area,
            'insumo_nombre': r.insumo_nombre, 'categoria': r.categoria,
            'cantidad': r.cantidad, 'unidad': r.unidad,
            'estado_bodega': r.estado_bodega, 'confirmado_caja': r.confirmado_caja,
            'solicitado_por': r.solicitado_por, 'nota': r.nota or ''
        } for r in reqs],
        'movimientos': [{
            'id': m.id, 'fecha': m.fecha.strftime('%d/%m %H:%M'), 'tipo': m.tipo,
            'insumo_nombre': m.insumo_nombre, 'cantidad': m.cantidad,
            'costo_total': f"{m.costo_total:.2f}", 'proveedor': m.proveedor or '-',
            'usuario': m.usuario, 'nota': m.nota or ''
        } for m in movs],
        'proveedores': [{
            'id': p.id, 'nombre': p.nombre, 'telefono': p.telefono,
            'categoria': p.categoria, 'saldo_pendiente': p.saldo_pendiente
        } for p in provs],
        'recomendaciones': recomendaciones
    })

@app.route('/api/almacen/insumo', methods=['POST', 'DELETE'])
@login_required
def api_almacen_insumo():
    data = request.json
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip().upper()
        if not nom:
            return jsonify({'ok': False, 'msg': 'Nombre requerido'}), 400
        nuevo = InsumoBodegaPro(
            nombre=nom,
            categoria=str(data.get('categoria', 'ABARROTES')).strip().upper(),
            unidad=str(data.get('unidad', 'PZA')).strip().upper(),
            stock_actual=float(data.get('stock_actual', 0)),
            stock_minimo=float(data.get('stock_minimo', 5)),
            costo_unitario=float(data.get('costo_unitario', 0))
        )
        db.session.add(nuevo)
        db.session.commit()
        return jsonify({'ok': True})

    ins = InsumoBodegaPro.query.get_or_404(int(data['id']))
    db.session.delete(ins)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/almacen/solicitar', methods=['POST'])
@login_required
def api_almacen_solicitar():
    data = request.json
    ins = InsumoBodegaPro.query.get(int(data['insumo_id'])) if data.get('insumo_id') else None
    req = RequerimientoBodega(
        area=str(data.get('area', 'BARRA')).upper(),
        insumo_id=ins.id if ins else None,
        insumo_nombre=ins.nombre if ins else str(data.get('nombre', '')).strip().upper(),
        categoria=ins.categoria if ins else str(data.get('categoria', 'ABARROTES')).upper(),
        cantidad=float(data.get('cantidad', 1)),
        unidad=ins.unidad if ins else str(data.get('unidad', 'PZA')).upper(),
        estado_bodega='PENDIENTE',
        confirmado_caja=False,
        solicitado_por=current_user.username.upper(),
        nota=str(data.get('nota', '')).strip()
    )
    db.session.add(req)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/almacen/estado_bodega', methods=['POST'])
@login_required
def api_almacen_estado_bodega():
    data = request.json
    if data.get('todos_entregados'):
        pendientes = RequerimientoBodega.query.filter_by(estado_bodega='PENDIENTE').all()
        for r in pendientes:
            r.estado_bodega = 'ENTREGADO'
            if r.insumo_id:
                ins = InsumoBodegaPro.query.get(r.insumo_id)
                if ins:
                    ins.stock_actual = max(0.0, round(ins.stock_actual - r.cantidad, 2))
        db.session.commit()
        return jsonify({'ok': True})

    r = RequerimientoBodega.query.get_or_404(int(data['id']))
    nuevo_est = str(data.get('estado', 'ENTREGADO')).upper()
    era_entregado = (r.estado_bodega == 'ENTREGADO')
    r.estado_bodega = nuevo_est
    if nuevo_est == 'ENTREGADO' and not era_entregado and r.insumo_id:
        ins = InsumoBodegaPro.query.get(r.insumo_id)
        if ins:
            ins.stock_actual = max(0.0, round(ins.stock_actual - r.cantidad, 2))
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/almacen/confirmar_caja', methods=['POST'])
@login_required
def api_almacen_confirmar_caja():
    data = request.json
    r = RequerimientoBodega.query.get_or_404(int(data['id']))
    recibido = bool(data.get('recibido', True))
    r.confirmado_caja = recibido
    if not recibido:
        r.estado_bodega = 'NO_ENTREGADO'
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/almacen/movimiento', methods=['POST'])
@login_required
def api_almacen_movimiento():
    data = request.json
    ins = InsumoBodegaPro.query.get_or_404(int(data['insumo_id']))
    tipo = str(data.get('tipo', 'ENTRADA_COMPRA')).upper()
    cant = float(data.get('cantidad', 0))
    costo = float(data.get('costo_total', 0))
    prov = str(data.get('proveedor', '')).strip().upper()
    nota = str(data.get('nota', '')).strip()

    if tipo == 'ENTRADA_COMPRA':
        ins.stock_actual = round(ins.stock_actual + cant, 2)
    elif tipo in ('SALIDA_MERMA', 'TRASPASO'):
        ins.stock_actual = max(0.0, round(ins.stock_actual - cant, 2))

    db.session.add(MovimientoAlmacen(
        tipo=tipo, insumo_nombre=ins.nombre, cantidad=cant,
        costo_total=costo, proveedor=prov,
        usuario=current_user.username.upper(), nota=nota
    ))
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/almacen/proveedor', methods=['POST'])
@login_required
def api_almacen_proveedor():
    data = request.json
    if data.get('pagar_id'):
        p = ProveedorAlmacen.query.get_or_404(int(data['pagar_id']))
        abono = float(data.get('abono', 0))
        p.saldo_pendiente = max(0.0, round(p.saldo_pendiente - abono, 2))
        db.session.commit()
        return jsonify({'ok': True})

    db.session.add(ProveedorAlmacen(
        nombre=str(data.get('nombre', '')).strip().upper(),
        telefono=str(data.get('telefono', '')).strip(),
        categoria=str(data.get('categoria', 'GENERAL')).strip().upper(),
        saldo_pendiente=float(data.get('saldo_pendiente', 0))
    ))
    db.session.commit()
    return jsonify({'ok': True})

# ==============================================================================
# FASE 3 PRO: CRÉDITOS A CLIENTES, CONSUMO DE EMPLEADOS (VALES) Y NÓMINA
# Pegar justo antes de: if __name__ == '__main__':
# ==============================================================================

class CreditoClientePOS(db.Model):
    __tablename__ = 'creditos_clientes_pos'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    cliente_nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(30), default='')
    concepto = db.Column(db.String(200), default='Consumo en Mesa')
    monto_total = db.Column(db.Float, default=0.0)
    saldo_pendiente = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(20), default='PENDIENTE')  # PENDIENTE / PAGADO
    registrado_por = db.Column(db.String(60), default='CAJA')

class EmpleadoNominaPOS(db.Model):
    __tablename__ = 'empleados_nomina_pos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    puesto = db.Column(db.String(60), default='MESERO')
    sueldo_base = db.Column(db.Float, default=1500.0)
    periodo = db.Column(db.String(20), default='SEMANAL')  # SEMANAL / QUINCENAL
    activo = db.Column(db.Boolean, default=True)

class ConsumoEmpleadoPOS(db.Model):
    __tablename__ = 'consumos_empleados_pos'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    empleado_id = db.Column(db.Integer, nullable=False)
    empleado_nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(30), default='CONSUMO')  # CONSUMO / PRESTAMO / ADELANTO
    concepto = db.Column(db.String(200), nullable=False)
    monto = db.Column(db.Float, default=0.0)
    descontado = db.Column(db.Boolean, default=False)
    registrado_por = db.Column(db.String(60), default='CAJA')

class ReciboNominaPOS(db.Model):
    __tablename__ = 'recibos_nomina_pos'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    empleado_id = db.Column(db.Integer, nullable=False)
    empleado_nombre = db.Column(db.String(100), nullable=False)
    puesto = db.Column(db.String(60), default='')
    periodo_texto = db.Column(db.String(60), default='SEMANAL')
    sueldo_base = db.Column(db.Float, default=0.0)
    bonos = db.Column(db.Float, default=0.0)
    propinas = db.Column(db.Float, default=0.0)
    descuentos_consumo = db.Column(db.Float, default=0.0)
    otros_descuentos = db.Column(db.Float, default=0.0)
    total_neto = db.Column(db.Float, default=0.0)
    pagado_por = db.Column(db.String(60), default='ADMIN')

def sembrar_empleados_nomina():
    if EmpleadoNominaPOS.query.count() > 0:
        return
    base = [
        ('PAOLA', 'MESERO', 1500.0, 'SEMANAL'),
        ('DANIEL', 'MESERO', 1500.0, 'SEMANAL'),
        ('BRAYAN', 'CAJERO / BARISTA', 1800.0, 'SEMANAL'),
        ('EMILI', 'CAJERO', 1600.0, 'SEMANAL')
    ]
    for nom, pue, sue, per in base:
        db.session.add(EmpleadoNominaPOS(nombre=nom, puesto=pue, sueldo_base=sue, periodo=per, activo=True))
    db.session.commit()

with app.app_context():
    db.create_all()
    sembrar_empleados_nomina()

@app.route('/nomina_creditos')
@login_required
def vista_nomina_creditos():
    if current_user.role == 'mesero':
        return redirect(url_for('mesero_dashboard'))
    return render_template('nomina_creditos.html')

@app.route('/api/finanzas/datos')
@login_required
def api_finanzas_datos():
    creditos = CreditoClientePOS.query.order_by(CreditoClientePOS.id.desc()).limit(80).all()
    empleados = EmpleadoNominaPOS.query.filter_by(activo=True).order_by(EmpleadoNominaPOS.nombre.asc()).all()
    consumos = ConsumoEmpleadoPOS.query.order_by(ConsumoEmpleadoPOS.id.desc()).limit(100).all()
    recibos = ReciboNominaPOS.query.order_by(ReciboNominaPOS.id.desc()).limit(60).all()

    # Calcular deuda de consumos pendientes por cada empleado
    adeudo_emp = {}
    for c in consumos:
        if not c.descontado:
            adeudo_emp[c.empleado_id] = round(adeudo_emp.get(c.empleado_id, 0.0) + c.monto, 2)

    return jsonify({
        'ok': True,
        'creditos': [{
            'id': cr.id, 'fecha': cr.fecha.strftime('%d/%m %H:%M'),
            'cliente_nombre': cr.cliente_nombre, 'telefono': cr.telefono,
            'concepto': cr.concepto, 'monto_total': cr.monto_total,
            'saldo_pendiente': cr.saldo_pendiente, 'estado': cr.estado
        } for cr in creditos],
        'empleados': [{
            'id': e.id, 'nombre': e.nombre, 'puesto': e.puesto,
            'sueldo_base': e.sueldo_base, 'periodo': e.periodo,
            'consumo_pendiente': adeudo_emp.get(e.id, 0.0)
        } for e in empleados],
        'consumos': [{
            'id': c.id, 'fecha': c.fecha.strftime('%d/%m %H:%M'),
            'empleado_id': c.empleado_id, 'empleado_nombre': c.empleado_nombre,
            'tipo': c.tipo, 'concepto': c.concepto, 'monto': c.monto,
            'descontado': c.descontado
        } for c in consumos],
        'recibos': [{
            'id': r.id, 'fecha': r.fecha.strftime('%d/%m/%Y %H:%M'),
            'empleado_nombre': r.empleado_nombre, 'puesto': r.puesto,
            'periodo_texto': r.periodo_texto, 'sueldo_base': r.sueldo_base,
            'bonos': r.bonos, 'propinas': r.propinas,
            'descuentos_consumo': r.descuentos_consumo,
            'otros_descuentos': r.otros_descuentos,
            'total_neto': r.total_neto, 'pagado_por': r.pagado_por
        } for r in recibos]
    })

@app.route('/api/finanzas/credito', methods=['POST'])
@login_required
def api_finanzas_credito():
    data = request.json
    if data.get('abonar_id'):
        cr = CreditoClientePOS.query.get_or_404(int(data['abonar_id']))
        abono = float(data.get('abono', 0))
        cr.saldo_pendiente = max(0.0, round(cr.saldo_pendiente - abono, 2))
        if cr.saldo_pendiente <= 0:
            cr.estado = 'PAGADO'
        db.session.commit()
        registrar_bitacora('ABONO_CREDITO', cr.cliente_nombre, abono, f'Saldo restante: ${cr.saldo_pendiente:.2f}')
        return jsonify({'ok': True, 'saldo': cr.saldo_pendiente})

    monto = float(data.get('monto', 0))
    nom = str(data.get('cliente_nombre', '')).strip().upper()
    if not nom or monto <= 0:
        return jsonify({'ok': False, 'msg': 'Nombre y monto requeridos'}), 400
    nuevo = CreditoClientePOS(
        cliente_nombre=nom,
        telefono=str(data.get('telefono', '')).strip(),
        concepto=str(data.get('concepto', 'Consumo en Mesa')).strip(),
        monto_total=monto, saldo_pendiente=monto, estado='PENDIENTE',
        registrado_por=current_user.username.upper()
    )
    db.session.add(nuevo)
    db.session.commit()
    registrar_bitacora('NUEVO_CREDITO', nom, monto, nuevo.concepto)
    return jsonify({'ok': True})

@app.route('/api/finanzas/empleado', methods=['POST', 'DELETE'])
@login_required
def api_finanzas_empleado():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Admin puede modificar empleados.'}), 403
    data = request.json
    if request.method == 'POST':
        nom = str(data.get('nombre', '')).strip().upper()
        if not nom:
            return jsonify({'ok': False, 'msg': 'Nombre requerido'}), 400
        db.session.add(EmpleadoNominaPOS(
            nombre=nom,
            puesto=str(data.get('puesto', 'MESERO')).strip().upper(),
            sueldo_base=float(data.get('sueldo_base', 1500)),
            periodo=str(data.get('periodo', 'SEMANAL')).strip().upper(),
            activo=True
        ))
        db.session.commit()
        return jsonify({'ok': True})

    e = EmpleadoNominaPOS.query.get_or_404(int(data['id']))
    e.activo = False
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/finanzas/consumo_empleado', methods=['POST'])
@login_required
def api_finanzas_consumo_empleado():
    data = request.json
    emp = EmpleadoNominaPOS.query.get_or_404(int(data['empleado_id']))
    monto = float(data.get('monto', 0))
    concepto = str(data.get('concepto', 'Consumo de personal')).strip().upper()
    tipo = str(data.get('tipo', 'CONSUMO')).strip().upper()
    if monto <= 0:
        return jsonify({'ok': False, 'msg': 'Monto inválido'}), 400
    db.session.add(ConsumoEmpleadoPOS(
        empleado_id=emp.id, empleado_nombre=emp.nombre,
        tipo=tipo, concepto=concepto, monto=monto,
        descontado=False, registrado_por=current_user.username.upper()
    ))
    db.session.commit()
    registrar_bitacora('VALE_EMPLEADO', emp.nombre, monto, f'{tipo}: {concepto}')
    return jsonify({'ok': True})

@app.route('/api/finanzas/generar_nomina', methods=['POST'])
@login_required
def api_finanzas_generar_nomina():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo Admin puede generar nómina.'}), 403
    data = request.json
    emp = EmpleadoNominaPOS.query.get_or_404(int(data['empleado_id']))
    bonos = float(data.get('bonos', 0))
    propinas = float(data.get('propinas', 0))
    otros_desc = float(data.get('otros_descuentos', 0))
    periodo_txt = str(data.get('periodo_texto', emp.periodo)).strip().upper()

    # Sumar y liquidar automáticamente todos los consumos/vales pendientes del empleado
    pendientes = ConsumoEmpleadoPOS.query.filter_by(empleado_id=emp.id, descontado=False).all()
    desc_consumo = round(sum(p.monto for p in pendientes), 2)
    for p in pendientes:
        p.descontado = True

    total_neto = round(emp.sueldo_base + bonos + propinas - desc_consumo - otros_desc, 2)
    recibo = ReciboNominaPOS(
        empleado_id=emp.id, empleado_nombre=emp.nombre, puesto=emp.puesto,
        periodo_texto=periodo_txt, sueldo_base=emp.sueldo_base,
        bonos=bonos, propinas=propinas,
        descuentos_consumo=desc_consumo, otros_descuentos=otros_desc,
        total_neto=total_neto, pagado_por=current_user.username.upper()
    )
    db.session.add(recibo)
    db.session.commit()
    registrar_bitacora('PAGO_NOMINA', emp.nombre, total_neto, f'Base:${emp.sueldo_base} + Bonos:${bonos} - Vales:${desc_consumo}')
    return jsonify({
        'ok': True,
        'recibo': {
            'id': recibo.id, 'fecha': recibo.fecha.strftime('%d/%m/%Y %H:%M'),
            'empleado_nombre': recibo.empleado_nombre, 'puesto': recibo.puesto,
            'periodo_texto': recibo.periodo_texto, 'sueldo_base': recibo.sueldo_base,
            'bonos': recibo.bonos, 'propinas': recibo.propinas,
            'descuentos_consumo': recibo.descuentos_consumo,
            'otros_descuentos': recibo.otros_descuentos,
            'total_neto': recibo.total_neto
        }
    })
# ==============================================================================
# MOTOR SOFT RESTAURANT MÓVIL PRO (MODO CAPITÁN + SINCRONIZACIÓN CAJA EN VIVO)
# Pegar justo antes de: if __name__ == '__main__':
# ==============================================================================

@app.route('/api/pos/abrir_turno_real', methods=['POST'])
@login_required
def api_pos_abrir_turno_real():
    if current_user.role == 'mesero':
        return jsonify({'ok': False, 'msg': 'Solo Caja o Admin pueden abrir turno.'}), 403
    data = request.json
    fondo = float(data.get('fondo_inicial', 0))
    turno = obtener_turno_activo()
    turno.fondo_inicial = fondo
    turno.cajero = current_user.username.upper()
    db.session.commit()
    registrar_bitacora('ABRIR_TURNO', f'TURNO #{turno.id}', fondo, f'Fondo inicial: ${fondo:.2f}')
    return jsonify({'ok': True, 'turno_id': turno.id, 'fondo': f"{fondo:.2f}"})

# 1. LISTA EN VIVO DE CUENTAS PARA CAJA (SIN RECARGAR F5, CON PALOMITA ✅ Y ALERTA)
@app.route('/api/pos/cuentas_abiertas_vivo')
@login_required
def api_pos_cuentas_abiertas_vivo():
    abiertas = CuentaPOS.query.filter_by(estado='ABIERTA').order_by(CuentaPOS.id.asc()).all()
    alertas = {a.cuenta_id: a.solicito_cuenta for a in AlertaMesaPOS.query.all()}
    return jsonify({
        'ok': True,
        'cuentas': [{
            'id': c.id,
            'mesa': c.mesa,
            'impresa': bool(c.impresa),
            'mesero': c.mesero,
            'orden': c.orden,
            'total': f"{c.total:.2f}",
            'solicito_cuenta': bool(alertas.get(c.id, False))
        } for c in abiertas]
    })

# 2. JUNTAR CUENTAS (TRASPASA TODOS LOS PRODUCTOS DE ORIGEN A DESTINO)
@app.route('/api/pos/juntar_cuentas', methods=['POST'])
@login_required
def api_pos_juntar_cuentas():
    data = request.json
    c_orig = CuentaPOS.query.get_or_404(int(data['origen_id']))
    c_dest = CuentaPOS.query.get_or_404(int(data['destino_id']))
    if c_orig.id == c_dest.id:
        return jsonify({'ok': False, 'msg': 'Selecciona una cuenta diferente.'}), 400
    if c_dest.impresa:
        return jsonify({'ok': False, 'msg': 'La cuenta destino ya está impresa.'}), 400

    for det in list(c_orig.detalles):
        det.cuenta_id = c_dest.id
    c_dest.personas += c_orig.personas
    mesa_orig = c_orig.mesa
    c_orig.estado = 'CANCELADA'
    db.session.flush()
    recalcular_totales_cuenta(c_dest)
    db.session.commit()
    registrar_bitacora('JUNTAR_CUENTAS', c_dest.mesa, c_dest.total, f'Se juntó {mesa_orig} en {c_dest.mesa}')
    return jsonify({'ok': True, 'destino_id': c_dest.id, 'mesa': c_dest.mesa})

# 3. DIVIDIR CUENTA POR PARTES IGUALES (EJ. 2, 3, 4 PARTES)
@app.route('/api/pos/dividir_partes', methods=['POST'])
@login_required
def api_pos_dividir_partes():
    data = request.json
    c_orig = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    partes = max(2, min(10, int(data.get('partes', 2))))
    if c_orig.impresa:
        return jsonify({'ok': False, 'msg': 'No se puede dividir una cuenta impresa.'}), 400

    monto_parte = round(c_orig.total / partes, 2)
    turno = obtener_turno_activo()
    hoy_inicio = datetime.now().replace(hour=0, minute=0, second=0)
    letras = ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']

    # Reemplazar detalle original por su parte proporcional y crear las subcuentas
    for d in list(c_orig.detalles):
        db.session.delete(d)
    db.session.add(DetallePOS(
        cuenta_id=c_orig.id, num_comanda=1, cantidad=1, clave='DIV',
        descripcion=f'CONSUMO DIVIDIDO (1/{partes}) {c_orig.mesa}',
        area_impresion='BARRA', es_modificador=False,
        precio_unitario=monto_parte, importe=monto_parte, impreso_comanda=True
    ))
    recalcular_totales_cuenta(c_orig)

    creadas = []
    for i in range(partes - 1):
        num_orden = CuentaPOS.query.filter(CuentaPOS.apertura >= hoy_inicio).count() + 1 + i
        sub_mesa = f"{c_orig.mesa}-{letras[i]}"
        c_sub = CuentaPOS(
            turno_id=turno.id, orden=f"A{num_orden}", area=c_orig.area,
            mesa=sub_mesa, mesero=c_orig.mesero, personas=1, estado='ABIERTA'
        )
        db.session.add(c_sub)
        db.session.flush()
        db.session.add(DetallePOS(
            cuenta_id=c_sub.id, num_comanda=1, cantidad=1, clave='DIV',
            descripcion=f'CONSUMO DIVIDIDO ({i+2}/{partes}) {c_orig.mesa}',
            area_impresion='BARRA', es_modificador=False,
            precio_unitario=monto_parte, importe=monto_parte, impreso_comanda=True
        ))
        recalcular_totales_cuenta(c_sub)
        creadas.append(sub_mesa)

    db.session.commit()
    registrar_bitacora('DIVIDIR_PARTES', c_orig.mesa, c_orig.total, f'Dividida en {partes} partes de ${monto_parte}')
    return jsonify({'ok': True, 'creadas': creadas})

# 4. CAMBIAR MESERO DE UNA CUENTA
@app.route('/api/pos/cambiar_mesero', methods=['POST'])
@login_required
def api_pos_cambiar_mesero():
    data = request.json
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    nuevo_mesero = str(data.get('nuevo_mesero', '')).strip().upper()
    if not nuevo_mesero:
        return jsonify({'ok': False, 'msg': 'Selecciona un mesero.'}), 400
    ant = c.mesero
    c.mesero = nuevo_mesero
    db.session.commit()
    registrar_bitacora('CAMBIAR_MESERO', c.mesa, c.total, f'{ant} -> {nuevo_mesero}')
    return jsonify({'ok': True})

# 5. REABRIR CUENTA IMPRESA (CON CONTRASEÑA DE AUTORIZACIÓN)
@app.route('/api/pos/reabrir_cuenta', methods=['POST'])
@login_required
def api_pos_reabrir_cuenta():
    data = request.json
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    clave = data.get('clave_admin', '')
    autorizo = current_user.username.upper() if current_user.role == 'admin' else validar_clave_admin(clave)
    if not autorizo:
        return jsonify({'ok': False, 'msg': 'Contraseña de autorización incorrecta.'}), 403
    c.impresa = False
    al = AlertaMesaPOS.query.filter_by(cuenta_id=c.id).first()
    if al:
        al.solicito_cuenta = False
    db.session.commit()
    registrar_bitacora('REABRIR_CUENTA', c.mesa, c.total, 'Cuenta impresa reabierta', autorizo=autorizo)
    return jsonify({'ok': True})

# 6. ELIMINAR CUENTA VACÍA (SOLO SI NO TIENE PRODUCTOS NI ESTÁ IMPRESA)
@app.route('/api/pos/eliminar_cuenta_vacia', methods=['POST'])
@login_required
def api_pos_eliminar_cuenta_vacia():
    data = request.json
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    if len(c.detalles) > 0 or c.impresa:
        return jsonify({'ok': False, 'msg': 'Solo se pueden eliminar cuentas vacías y sin imprimir.'}), 400
    clave = data.get('clave_admin', '')
    autorizo = current_user.username.upper() if current_user.role == 'admin' else validar_clave_admin(clave)
    if not autorizo:
        return jsonify({'ok': False, 'msg': 'Contraseña de autorización incorrecta.'}), 403
    mesa_nom = c.mesa
    c.estado = 'CANCELADA'
    db.session.commit()
    registrar_bitacora('ELIMINAR_CUENTA', mesa_nom, 0.0, 'Cuenta vacía eliminada', autorizo=autorizo)
    return jsonify({'ok': True})

# 7. REIMPRIMIR PRODUCTOS SELECCIONADOS A COCINA / BARRA
@app.route('/api/pos/reimprimir_productos', methods=['POST'])
@login_required
def api_pos_reimprimir_productos():
    data = request.json
    c = CuentaPOS.query.get_or_404(int(data['cuenta_id']))
    item_ids = [int(x) for x in data.get('item_ids', [])]
    if not item_ids:
        return jsonify({'ok': False, 'msg': 'Selecciona al menos un producto.'}), 400

    items = [d for d in c.detalles if d.id in item_ids]
    ahora_str = datetime.now().strftime('%d/%m/%Y %I:%M:%S %p')
    filas_html = "".join([
        f"<tr><td style='width:20%;font-weight:bold;'>{'' if it.es_modificador else int(it.cantidad)}</td>"
        f"<td style='width:80%;font-weight:bold;'>{it.descripcion}</td></tr>"
        for it in items
    ])
    html_t = f"""
    <div class='ticket-termico'>
        <div style='font-size:17px;font-weight:900;text-align:center;'>*** REIMPRESIÓN COMANDA ***</div>
        <div style='text-align:center;font-size:12px;'>MESA: <b>{c.mesa}</b> | ORDEN: <b>{c.orden}</b></div>
        <div style='text-align:center;font-size:11px;'>MESERO: {c.mesero} | {ahora_str}</div>
        <div style='border-top:2px dashed #000;margin:6px 0;'></div>
        <table style='width:100%;font-size:15px;'>{filas_html}</table>
        <div style='border-top:2px dashed #000;margin:8px 0;'></div>
    </div>"""
    db.session.add(ColaImpresionPOS(tipo='REIMPRESION', contenido_html=html_t))
    db.session.commit()
    registrar_bitacora('REIMPRIMIR_PROD', c.mesa, 0.0, f'Reimpresos {len(items)} productos')
    return jsonify({'ok': True})

# 8. PANTALLA "MI VENTA" DEL MESERO (ABIERTAS | POR PAGAR | PAGADAS)
@app.route('/api/pos/mi_venta')
@login_required
def api_pos_mi_venta():
    turno = obtener_turno_activo()
    todas = CuentaPOS.query.filter_by(turno_id=turno.id).order_by(CuentaPOS.id.desc()).all()
    abiertas, por_pagar, pagadas = [], [], []
    for c in todas:
        if c.estado == 'CANCELADA':
            continue
        obj = {
            'id': c.id, 'mesa': c.mesa, 'area': c.area, 'orden': c.orden,
            'folio': c.folio or '0', 'mesero': c.mesero,
            'total': f"{c.total:.2f}", 'total_num': c.total,
            'cierre': c.cierre.strftime('%d/%m %H:%M') if c.cierre else ''
        }
        if c.estado == 'PAGADA':
            pagadas.append(obj)
        elif c.impresa:
            por_pagar.append(obj)
        else:
            abiertas.append(obj)

    meseros = [u.username.upper() for u in User.query.filter(User.role.in_(['mesero', 'cajero', 'admin'])).all()]
    return jsonify({
        'ok': True,
        'abiertas': abiertas,
        'por_pagar': por_pagar,
        'pagadas': pagadas,
        'total_abiertas': f"{sum(x['total_num'] for x in abiertas):.2f}",
        'total_por_pagar': f"{sum(x['total_num'] for x in por_pagar):.2f}",
        'total_pagadas': f"{sum(x['total_num'] for x in pagadas):.2f}",
        'gran_total': f"{sum(x['total_num'] for x in abiertas + por_pagar + pagadas):.2f}",
        'meseros': meseros
    })
if __name__ == '__main__':
    app.run(debug=True, port=10000)