import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import random
from datetime import datetime
import cloudinary
import cloudinary.uploader
from sqlalchemy import text

app = Flask(__name__)
app.config['SECRET_KEY'] = 'quiosco_morisco_secret_key_2026'

# ==========================================
# CONFIGURACIÓN DE CLOUDINARY (FOTOS)
# ==========================================
cloudinary.config(
    cloud_name = "sgz4qrxq",
    api_key = "881332363648736",
    api_secret = "I7go-7PnNv1DQLJiGdkMB5wtXkc",
    secure = True
)

# ==========================================
# CONFIGURACIÓN DE LA BASE DE DATOS RENDER
# ==========================================
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg://quiosco_bd_user:7AFl5Li1wKm3VsFipWpTSLm9Z9BGFjUE@dpg-dbcki3k...' # Asegúrate de que esta URL esté completa en tu archivo real
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

# --- MODELOS DE LA BASE DE DATOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    nombre_en = db.Column(db.String(100), nullable=True) # NUEVO INGLÉS
    categoria = db.Column(db.String(50), nullable=False)
    precio = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    descripcion_en = db.Column(db.Text, nullable=True) # NUEVO INGLÉS
    imagen_url = db.Column(db.String(250), nullable=True)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20), unique=True, nullable=False)
    consumos = db.Column(db.Integer, default=0)

class Configuracion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meta_1 = db.Column(db.Integer, default=5)
    premio_1 = db.Column(db.String(150), default="Bebida Gratis")
    premio_1_en = db.Column(db.String(150), default="Free Drink") # NUEVO INGLÉS
    meta_2 = db.Column(db.Integer, default=10)
    premio_2 = db.Column(db.String(150), default="Platillo Gratis")
    premio_2_en = db.Column(db.String(150), default="Free Dish") # NUEVO INGLÉS

class PinCaja(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)

class HistorialPin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), nullable=False)
    creado_por = db.Column(db.String(100), default="Caja / Maestro")
    fecha_creacion = db.Column(db.String(50), nullable=False)

class Evaluacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    limpieza = db.Column(db.Integer, nullable=False)
    mesero_nombre = db.Column(db.String(50), nullable=False)
    mesero_calificacion = db.Column(db.Integer, nullable=False)
    calidad_comida = db.Column(db.Integer, nullable=False, default=5)
    tiempo_espera = db.Column(db.String(50), nullable=False, default='Adecuado')
    comentarios = db.Column(db.Text, nullable=True)
    fecha = db.Column(db.String(50), nullable=False)

# NUEVA TABLA PARA GALERÍA
class Galeria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    imagen_url = db.Column(db.String(255), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# RUTA MÁGICA DE ACTUALIZACIÓN
# ==========================================
@app.route('/actualizar_db')
def actualizar_db():
    try:
        db.session.execute(text('ALTER TABLE producto ADD COLUMN nombre_en VARCHAR(100);'))
        db.session.execute(text('ALTER TABLE producto ADD COLUMN descripcion_en TEXT;'))
        db.session.execute(text('ALTER TABLE configuracion ADD COLUMN premio_1_en VARCHAR(150);'))
        db.session.execute(text('ALTER TABLE configuracion ADD COLUMN premio_2_en VARCHAR(150);'))
        db.session.commit()
    except Exception as e:
        db.session.rollback() 
    
    db.create_all() 
    return "¡Base de datos actualizada con éxito para Inglés y Galería!"

# --- RUTAS PÚBLICAS ---
@app.route('/')
def index():
    telefono_cliente = session.get('telefono_cliente')
    cliente = Cliente.query.filter_by(telefono=telefono_cliente).first() if telefono_cliente else None
    progreso = cliente.consumos if cliente else 0

    config = Configuracion.query.first()
    meta_1 = config.meta_1 if config else 5
    meta_2 = config.meta_2 if config else 10
    
    # Extraer textos en inglés (con validación por si están vacíos)
    premio_1 = config.premio_1 if config else "Bebida Gratis"
    premio_1_en = config.premio_1_en if config and config.premio_1_en else premio_1
    premio_2 = config.premio_2 if config else "Platillo Gratis"
    premio_2_en = config.premio_2_en if config and config.premio_2_en else premio_2

    productos = Producto.query.all()
    categorias = {}
    for p in productos:
        if p.categoria not in categorias:
            categorias[p.categoria] = []
        categorias[p.categoria].append(p)
        
    galeria = Galeria.query.all()

    return render_template('index.html', cliente=cliente, progreso=progreso, 
                           meta_1=meta_1, meta_2=meta_2, categorias=categorias, 
                           premio_1=premio_1, premio_1_en=premio_1_en, 
                           premio_2=premio_2, premio_2_en=premio_2_en, galeria=galeria)

@app.route('/registrar_consumo', methods=['POST'])
def registrar_consumo():
    nombre = request.form.get('nombre')
    telefono = request.form.get('telefono')
    pin_ingresado = request.form.get('pin')

    pin_valido = PinCaja.query.filter_by(codigo=pin_ingresado).first()
    if not pin_valido:
        flash("PIN incorrecto o ya utilizado. Pídelo en caja.", "error")
        return redirect(url_for('index'))

    cliente = Cliente.query.filter_by(telefono=telefono).first()
    if not cliente:
        cliente = Cliente(nombre=nombre, telefono=telefono, consumos=0)
        db.session.add(cliente)
        db.session.commit()

    cliente.consumos += 1
    session['telefono_cliente'] = cliente.telefono

    historial = HistorialPin(
        codigo=pin_valido.codigo,
        fecha_creacion=datetime.now().strftime("%d/%m/%Y %H:%M")
    )
    db.session.add(historial)
    db.session.delete(pin_valido)
    db.session.commit()

    config = Configuracion.query.first()
    meta_1 = config.meta_1 if config else 5
    meta_2 = config.meta_2 if config else 10

    if cliente.consumos == meta_1 or cliente.consumos == meta_2:
        flash(f"¡Felicidades {cliente.nombre}! Has ganado tu recompensa.", "premio_interactivo")
    else:
        flash(f"¡Visita registrada con éxito! Llevas {cliente.consumos} consumos.", "exito")

    return redirect(url_for('index'))

@app.route('/enviar_evaluacion', methods=['POST'])
def enviar_evaluacion():
    limpieza = int(request.form.get('limpieza'))
    mesero_nombre = request.form.get('mesero_nombre')
    mesero_calificacion = int(request.form.get('mesero_calificacion'))
    calidad_comida = int(request.form.get('calidad_comida'))
    tiempo_espera = request.form.get('tiempo_espera')
    comentarios = request.form.get('comentarios', '')

    nueva_evaluacion = Evaluacion(
        limpieza=limpieza,
        mesero_nombre=mesero_nombre,
        mesero_calificacion=mesero_calificacion,
        calidad_comida=calidad_comida,
        tiempo_espera=tiempo_espera,
        comentarios=comentarios,
        fecha=datetime.now().strftime("%d/%m/%Y %H:%M")
    )
    db.session.add(nueva_evaluacion)
    db.session.commit()
    flash("¡Gracias por calificar tu experiencia!", "exito")
    return redirect(url_for('index'))

# --- RUTAS DE ADMINISTRACIÓN ---
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        flash("Credenciales incorrectas", "error")
    return render_template('admin_login.html')

@app.route('/admin')
@login_required
def admin_dashboard():
    # Desviar a los cajeros
    if current_user.username in ['caja1', 'caja2']:
        pins = PinCaja.query.all()
        return render_template('cajero_dashboard.html', pins=pins)

    # Cargar información para el administrador
    productos = Producto.query.all()
    clientes = Cliente.query.all()
    pins = PinCaja.query.all()
    historial = HistorialPin.query.all()
    evaluaciones = Evaluacion.query.order_by(Evaluacion.id.desc()).all()
    config = Configuracion.query.first()
    galeria = Galeria.query.all()
    
    meta_1 = config.meta_1 if config else 5
    premio_1 = config.premio_1 if config else "Bebida Gratis"
    meta_2 = config.meta_2 if config else 10
    premio_2 = config.premio_2 if config else "Platillo Gratis"

    return render_template('admin_dashboard.html',
                           productos=productos,
                           clientes=clientes,
                           pins=pins,
                           historial=historial,
                           evaluaciones=evaluaciones,
                           meta_1=meta_1, premio_1=premio_1,
                           meta_2=meta_2, premio_2=premio_2,
                           config=config, galeria=galeria)

@app.route('/caja/generar_pin', methods=['POST'])
@login_required
def generar_pin():
    nuevo_codigo = str(random.randint(1000, 9999))
    while PinCaja.query.filter_by(codigo=nuevo_codigo).first():
        nuevo_codigo = str(random.randint(1000, 9999))

    pin = PinCaja(codigo=nuevo_codigo)
    db.session.add(pin)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/configurar_premio', methods=['POST'])
@login_required
def configurar_premio():
    config = Configuracion.query.first()
    if not config:
        config = Configuracion()
        db.session.add(config)

    config.meta_1 = int(request.form.get('meta_1', 5))
    config.premio_1 = request.form.get('premio_1', 'Bebida Gratis')
    config.premio_1_en = request.form.get('premio_1_en', config.premio_1) # INGLÉS
    config.meta_2 = int(request.form.get('meta_2', 10))
    config.premio_2 = request.form.get('premio_2', 'Platillo Gratis')
    config.premio_2_en = request.form.get('premio_2_en', config.premio_2) # INGLÉS
    
    db.session.commit()
    flash("Configuración de premios actualizada", "exito")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/producto/nuevo', methods=['POST'])
@login_required
def nuevo_producto():
    nombre = request.form.get('nombre')
    nombre_en = request.form.get('nombre_en', '')
    categoria = request.form.get('categoria')
    precio = float(request.form.get('precio'))
    descripcion = request.form.get('descripcion')
    descripcion_en = request.form.get('descripcion_en', '')
    
    imagen_url = ""
    foto = request.files.get('foto')
    if foto and foto.filename != '':
        respuesta = cloudinary.uploader.upload(foto)
        imagen_url = respuesta.get('secure_url')

    prod = Producto(nombre=nombre, nombre_en=nombre_en, categoria=categoria, 
                    precio=precio, descripcion=descripcion, descripcion_en=descripcion_en, imagen_url=imagen_url)
    db.session.add(prod)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/producto/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_producto(id):
    p = Producto.query.get_or_404(id)
    if request.method == 'POST':
        p.nombre = request.form.get('nombre')
        p.nombre_en = request.form.get('nombre_en', p.nombre_en)
        p.categoria = request.form.get('categoria')
        p.precio = float(request.form.get('precio'))
        p.descripcion = request.form.get('descripcion')
        p.descripcion_en = request.form.get('descripcion_en', p.descripcion_en)
        
        foto = request.files.get('foto')
        if foto and foto.filename != '':
            respuesta = cloudinary.uploader.upload(foto)
            p.imagen_url = respuesta.get('secure_url')
            
        db.session.commit()
        flash("Platillo actualizado correctamente", "exito")
        return redirect(url_for('admin_dashboard'))
    return render_template('editar_producto.html', producto=p)

@app.route('/admin/producto/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_producto(id):
    p = Producto.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/cliente/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_cliente(id):
    c = Cliente.query.get_or_404(id)
    db.session.delete(c)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# NUEVAS RUTAS DE GALERÍA
@app.route('/agregar_galeria', methods=['POST'])
@login_required
def agregar_galeria():
    foto = request.files.get('foto')
    if foto and foto.filename != '':
        upload_result = cloudinary.uploader.upload(foto)
        nueva_foto = Galeria(imagen_url=upload_result.get('secure_url'))
        db.session.add(nueva_foto)
        db.session.commit()
        flash('Foto agregada a la galería', 'exito')
    return redirect(url_for('admin_dashboard'))

@app.route('/eliminar_galeria/<int:id>')
@login_required
def eliminar_galeria(id):
    foto = Galeria.query.get_or_404(id)
    db.session.delete(foto)
    db.session.commit()
    flash('Foto de galería eliminada', 'exito')
    return redirect(url_for('admin_dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    app.run(debug=True, port=10000)