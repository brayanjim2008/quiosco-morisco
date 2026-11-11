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

# --- MODELOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='cajero') # 'admin', 'cajero', 'mesero'

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

    # Estadísticas de Ventas y Pedidos (Hoy, 7 días, 30 días)
    ordenes_hoy = PreOrden.query.filter(PreOrden.fecha >= hoy_inicio, PreOrden.estado == 'atendido', PreOrden.total > 0).all()
    ordenes_semana = PreOrden.query.filter(PreOrden.fecha >= hace_7_dias, PreOrden.estado == 'atendido', PreOrden.total > 0).all()
    ordenes_mes = PreOrden.query.filter(PreOrden.fecha >= hace_30_dias, PreOrden.estado == 'atendido', PreOrden.total > 0).all()

    ventas_hoy = round(sum(o.total for o in ordenes_hoy), 2)
    ventas_semana = round(sum(o.total for o in ordenes_semana), 2)
    ventas_mes = round(sum(o.total for o in ordenes_mes), 2)

    # Corte de PINs del día por Cajero
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

if __name__ == '__main__':
    app.run(debug=True, port=10000)