from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import cloudinary
import cloudinary.uploader
import random
import string

app = Flask(__name__)
app.secret_key = 'clave_secreta_quiosco'  # Cambia esto por algo seguro en producción

# --- CONFIGURACIÓN DE CLOUDINARY ---
cloudinary.config(
    cloud_name = "sgz4qrxq",
    api_key = "881332363648736",
    api_secret = "I7go-7PnNv1DQLJiGdKMB5wtXkc",
    secure = True
)

# --- CONFIGURACIÓN DE LA BASE DE DATOS (RENDER) ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://quiosco_bd_user:7AFl5Li1wKm3VsFipWpTSLm9Z9BGFjUE@dpg-dbcki3ks728c73fbkv3g-a.oregon-postgres.render.com/quiosco_bd'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Opciones para mantener viva la conexión
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

# --- MODELOS DE LA BASE DE DATOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='cajero') 

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    nombre_en = db.Column(db.String(100), nullable=True) # INGLÉS
    descripcion = db.Column(db.Text, nullable=True)
    descripcion_en = db.Column(db.Text, nullable=True) # INGLÉS
    precio = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    imagen_url = db.Column(db.String(255), nullable=True)

class Configuracion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meta_1 = db.Column(db.Integer, default=5)
    premio_1 = db.Column(db.String(100), default="Bebida Gratis")
    premio_1_en = db.Column(db.String(100), default="Free Drink") # INGLÉS
    meta_2 = db.Column(db.Integer, default=10)
    premio_2 = db.Column(db.String(100), default="Postre Gratis")
    premio_2_en = db.Column(db.String(100), default="Free Dessert") # INGLÉS

class Galeria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    imagen_url = db.Column(db.String(255), nullable=False)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nfc_uid = db.Column(db.String(100), unique=True, nullable=False)
    visitas = db.Column(db.Integer, default=0)
    nivel = db.Column(db.Integer, default=0)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

class PinCaja(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True)

class Evaluacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesero_nombre = db.Column(db.String(100), nullable=False)
    mesero_calificacion = db.Column(db.Integer, nullable=False)
    limpieza = db.Column(db.Integer, nullable=False)
    calidad_comida = db.Column(db.Integer, nullable=False)
    comentarios = db.Column(db.Text, nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- RUTAS PRINCIPALES ---

@app.route('/actualizar_db')
def actualizar_db():
    # BORRAR LAS TABLAS VIEJAS PARA EVITAR EL CHOQUE DE COLUMNAS
    db.drop_all()
    # CREAR LAS TABLAS NUEVAS CON LA ESTRUCTURA CORRECTA
    db.create_all()
    
    # Crear configuración por defecto
    nueva_config = Configuracion()
    db.session.add(nueva_config)
    
    # Crear usuario admin por defecto
    admin = User(username='admin', password=generate_password_hash('12345'), role='admin')
    db.session.add(admin)
    
    db.session.commit()
    
    return "<h1>¡Base de datos reconstruida con éxito!</h1><p>Ya puedes volver a <a href='/'>la página de inicio</a> o al <a href='/admin_login'>panel de administrador</a>.</p>"

@app.route('/')
def index():
    productos = Producto.query.all()
    config = Configuracion.query.first()
    galeria = Galeria.query.order_by(Galeria.fecha_subida.desc()).all()
    return render_template('index.html', productos=productos, config=config, galeria=galeria)

# --- EVALUACIONES ---
@app.route('/enviar_evaluacion', methods=['POST'])
def enviar_evaluacion():
    mesero_nombre = request.form.get('mesero_nombre')
    mesero_calificacion = request.form.get('mesero_calificacion')
    limpieza = request.form.get('limpieza')
    calidad_comida = request.form.get('calidad_comida')
    comentarios = request.form.get('comentarios', '')
    
    if mesero_nombre and mesero_calificacion and limpieza and calidad_comida:
        nueva_evaluacion = Evaluacion(
            mesero_nombre=mesero_nombre,
            mesero_calificacion=int(mesero_calificacion),
            limpieza=int(limpieza),
            calidad_comida=int(calidad_comida),
            comentarios=comentarios
        )
        db.session.add(nueva_evaluacion)
        db.session.commit()
        flash('¡Gracias por tu evaluación!', 'success')
    else:
        flash('Por favor, completa todos los campos requeridos.', 'danger')
        
    return redirect(url_for('index'))

# --- AUTENTICACIÓN ---
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('cajero_dashboard'))
        flash('Credenciales incorrectas.', 'danger')
    return render_template('admin_login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# --- PANEL DE ADMINISTRACIÓN ---
@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    config = Configuracion.query.first()
    productos = Producto.query.all()
    pins = PinCaja.query.filter_by(activo=True).all()
    evaluaciones = Evaluacion.query.order_by(Evaluacion.fecha.desc()).all()
    galeria = Galeria.query.order_by(Galeria.fecha_subida.desc()).all()

    return render_template('admin_dashboard.html', 
                           config=config, 
                           meta_1=config.meta_1 if config else 5,
                           premio_1=config.premio_1 if config else '',
                           meta_2=config.meta_2 if config else 10,
                           premio_2=config.premio_2 if config else '',
                           productos=productos, 
                           pins=pins, 
                           evaluaciones=evaluaciones,
                           galeria=galeria)

@app.route('/admin/configurar_premio', methods=['POST'])
@login_required
def configurar_premio():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    config = Configuracion.query.first()
    if not config:
        config = Configuracion()
        db.session.add(config)
    
    config.meta_1 = int(request.form['meta_1'])
    config.premio_1 = request.form['premio_1']
    config.premio_1_en = request.form.get('premio_1_en', request.form['premio_1'])
    
    config.meta_2 = int(request.form['meta_2'])
    config.premio_2 = request.form['premio_2']
    config.premio_2_en = request.form.get('premio_2_en', request.form['premio_2'])
    
    db.session.commit()
    flash('Configuración de premios bilingüe guardada con éxito.')
    return redirect(url_for('admin_dashboard'))

# --- GALERÍA ---
@app.route('/agregar_galeria', methods=['POST'])
@login_required
def agregar_galeria():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    if 'foto' in request.files and request.files['foto'].filename != '':
        foto = request.files['foto']
        try:
            upload_result = cloudinary.uploader.upload(foto)
            nueva_foto = Galeria(imagen_url=upload_result.get('secure_url'))
            db.session.add(nueva_foto)
            db.session.commit()
            flash('Foto subida a la galería exitosamente.')
        except Exception as e:
            flash(f'Error al subir la foto: {str(e)}', 'danger')
            
    return redirect(url_for('admin_dashboard'))

@app.route('/eliminar_galeria/<int:id>')
@login_required
def eliminar_galeria(id):
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    foto = Galeria.query.get_or_404(id)
    db.session.delete(foto)
    db.session.commit()
    flash('Foto eliminada de la galería.')
    return redirect(url_for('admin_dashboard'))

# --- PLATILLOS ---
@app.route('/admin/producto/nuevo', methods=['POST'])
@login_required
def nuevo_producto():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
        
    nombre = request.form['nombre']
    nombre_en = request.form.get('nombre_en', '')
    descripcion = request.form['descripcion']
    descripcion_en = request.form.get('descripcion_en', '')
    precio = request.form['precio']
    categoria = request.form['categoria']
    
    imagen_url = None
    if 'foto' in request.files and request.files['foto'].filename != '':
        foto = request.files['foto']
        try:
            upload_result = cloudinary.uploader.upload(foto)
            imagen_url = upload_result.get('secure_url')
        except Exception as e:
            flash(f"Error subiendo imagen: {e}")

    nuevo = Producto(
        nombre=nombre, nombre_en=nombre_en, 
        descripcion=descripcion, descripcion_en=descripcion_en, 
        precio=precio, categoria=categoria, imagen_url=imagen_url
    )
    db.session.add(nuevo)
    db.session.commit()
    flash('Platillo bilingüe agregado.')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/producto/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_producto(id):
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    p = Producto.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash('Platillo eliminado.')
    return redirect(url_for('admin_dashboard'))

# --- PINES Y CAJEROS ---
@app.route('/caja/generar_pin', methods=['POST'])
@login_required
def generar_pin():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
        
    codigo = ''.join(random.choices(string.digits, k=6))
    nuevo_pin = PinCaja(codigo=codigo)
    db.session.add(nuevo_pin)
    db.session.commit()
    flash(f'Nuevo PIN generado: {codigo}')
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True, port=10000)