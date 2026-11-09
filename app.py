from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import cloudinary
import cloudinary.uploader
import random
import string
import csv
from io import StringIO

app = Flask(__name__)
app.secret_key = 'clave_secreta_quiosco'

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

class Galeria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    imagen_url = db.Column(db.String(255), nullable=False)
    titulo = db.Column(db.String(100), nullable=True)
    descripcion = db.Column(db.String(250), nullable=True)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)

class Publicacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    titulo_en = db.Column(db.String(150), nullable=True)
    descripcion = db.Column(db.Text, nullable=False)
    descripcion_en = db.Column(db.Text, nullable=True)
    categoria = db.Column(db.String(50), nullable=False) 
    imagen_url = db.Column(db.String(255), nullable=True)
    fecha_publicacion = db.Column(db.DateTime, default=datetime.utcnow)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    visitas = db.Column(db.Integer, default=0)
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

class Anuncio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mensaje = db.Column(db.String(250), nullable=False)
    color = db.Column(db.String(50), default="bg-warning")
    imagen_url = db.Column(db.String(255), nullable=True)
    texto_boton = db.Column(db.String(50), nullable=True)
    enlace = db.Column(db.String(100), nullable=True)
    activo = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- AUTO-PARCHE MÁGICO (Se ejecuta solo sin que hagas nada) ---
with app.app_context():
    parches = [
        "ALTER TABLE anuncio ADD COLUMN imagen_url VARCHAR(255);",
        "ALTER TABLE anuncio ADD COLUMN texto_boton VARCHAR(50);",
        "ALTER TABLE anuncio ADD COLUMN enlace VARCHAR(100);",
        "ALTER TABLE producto ADD COLUMN agotado BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE galeria ADD COLUMN titulo VARCHAR(100);",
        "ALTER TABLE galeria ADD COLUMN descripcion VARCHAR(250);"
    ]
    for sql in parches:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback() # Si la columna ya existe, lo ignora silenciosamente
    db.create_all()


# --- RUTAS PRINCIPALES ---
@app.route('/actualizar_db')
def actualizar_db():
    db.drop_all()
    db.create_all()
    db.session.add(User(username='admin', password=generate_password_hash('12345'), role='admin'))
    db.session.add(User(username='caja1', password=generate_password_hash('caja123'), role='cajero'))
    db.session.add(CategoriaMenu(nombre="Desayunos", nombre_en="Breakfast"))
    db.session.add(CategoriaMenu(nombre="Bebidas Calientes", nombre_en="Hot Drinks"))
    db.session.add(Premio(visitas_necesarias=5, premio_es="Bebida Gratis", premio_en="Free Drink"))
    db.session.add(Premio(visitas_necesarias=10, premio_es="Postre Gratis", premio_en="Free Dessert"))
    db.session.commit()
    return "<h1>¡BD Reconstruida (Permisos y Agotados)!</h1><p>Vuelve al <a href='/admin_login'>login</a>.</p>"

@app.route('/')
def index():
    categorias_bd = CategoriaMenu.query.all()
    categorias_dict = {}
    for cat in categorias_bd:
        productos = Producto.query.filter_by(categoria=cat.nombre).order_by(Producto.destacado.desc(), Producto.id.asc()).all()
        if productos: categorias_dict[cat.nombre] = productos
            
    galeria = Galeria.query.order_by(Galeria.fecha_subida.desc()).all()
    publicaciones = Publicacion.query.order_by(Publicacion.fecha_publicacion.desc()).all()
    premios_bd = Premio.query.order_by(Premio.visitas_necesarias.asc()).all()
    max_visitas = premios_bd[-1].visitas_necesarias if premios_bd else 10
    metas_list = [p.visitas_necesarias for p in premios_bd]
    anuncio = Anuncio.query.filter_by(activo=True).first()
    
    return render_template('index.html', categorias=categorias_dict, galeria=galeria, 
                           publicaciones=publicaciones, premios=premios_bd, 
                           max_visitas=max_visitas, metas_list=metas_list, anuncio=anuncio)

@app.route('/registrar_consumo', methods=['POST'])
def registrar_consumo():
    nombre = request.form.get('nombre')
    telefono = request.form.get('telefono')
    pin_ingresado = request.form.get('pin').upper().strip()
    
    pin_valido = PinCaja.query.filter_by(codigo=pin_ingresado, activo=True).first()
    if not pin_valido:
        flash('PIN inválido o ya utilizado.', 'error')
        return redirect(url_for('index'))
        
    pin_valido.activo = False
    
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

    db.session.commit()
    
    premios_bd = Premio.query.order_by(Premio.visitas_necesarias.asc()).all()
    premio_actual = next((p for p in premios_bd if p.visitas_necesarias == cliente.visitas), None)
    
    if premio_actual: flash(f'¡META ALCANZADA! Muestra esto en caja: {premio_actual.premio_es}', 'premio_interactivo')
    else: flash(f'¡Visita sellada, {nombre}! Llevas {cliente.visitas} consumos.', 'success')
        
    categorias_bd = CategoriaMenu.query.all()
    categorias_dict = {}
    for cat in categorias_bd:
        productos = Producto.query.filter_by(categoria=cat.nombre).order_by(Producto.destacado.desc(), Producto.id.asc()).all()
        if productos: categorias_dict[cat.nombre] = productos
        
    return render_template('index.html', cliente=cliente, progreso=cliente.visitas,
                           categorias=categorias_dict, galeria=Galeria.query.order_by(Galeria.fecha_subida.desc()).all(),
                           publicaciones=Publicacion.query.order_by(Publicacion.fecha_publicacion.desc()).all(),
                           premios=premios_bd, max_visitas=premios_bd[-1].visitas_necesarias if premios_bd else 10,
                           metas_list=[p.visitas_necesarias for p in premios_bd], premio_actual=premio_actual)

@app.route('/enviar_evaluacion', methods=['POST'])
def enviar_evaluacion():
    db.session.add(Evaluacion(
        mesero_nombre=request.form.get('mesero_nombre'), mesero_calificacion=int(request.form.get('mesero_calificacion')),
        limpieza=int(request.form.get('limpieza')), calidad_comida=int(request.form.get('calidad_comida')), comentarios=request.form.get('comentarios', '')
    ))
    db.session.commit()
    flash('¡Gracias por tu evaluación!', 'success')
    return redirect(url_for('index'))

# --- ADMIN Y AUTENTICACIÓN ---
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
        flash('Credenciales incorrectas.', 'error')
    return render_template('admin_login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('cajero_dashboard'))
        
    total_clientes = Cliente.query.count()
    total_visitas = db.session.query(db.func.sum(Cliente.visitas)).scalar() or 0
    promedio_est = db.session.query(db.func.avg(Evaluacion.mesero_calificacion)).scalar() or 0

    return render_template('admin_dashboard.html', 
                           categorias=CategoriaMenu.query.all(),
                           premios=Premio.query.order_by(Premio.visitas_necesarias.asc()).all(),
                           productos=Producto.query.order_by(Producto.destacado.desc()).all(), 
                           pins=PinCaja.query.filter_by(activo=True).all(),
                           evaluaciones=Evaluacion.query.order_by(Evaluacion.fecha.desc()).limit(50).all(),
                           galeria=Galeria.query.order_by(Galeria.fecha_subida.desc()).all(),
                           publicaciones=Publicacion.query.order_by(Publicacion.fecha_publicacion.desc()).all(),
                           anuncios=Anuncio.query.all(),
                           total_clientes=total_clientes, total_visitas=total_visitas, promedio_est=round(promedio_est, 1))

@app.route('/cajero_dashboard')
@login_required
def cajero_dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
        
    pins = PinCaja.query.filter_by(activo=True).all()
    return render_template('cajero_dashboard.html', pins=pins)

@app.route('/admin/exportar_clientes')
@login_required
def exportar_clientes():
    if current_user.role != 'admin': return redirect(url_for('index'))
    clientes = Cliente.query.all()
    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(('ID', 'Nombre', 'Telefono', 'Visitas', 'Fecha_Registro'))
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        for c in clientes:
            writer.writerow((c.id, c.nombre, c.telefono, c.visitas, c.fecha_registro.strftime('%Y-%m-%d')))
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)
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
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        for e in evaluaciones:
            writer.writerow((e.id, e.mesero_nombre, e.mesero_calificacion, e.limpieza, e.calidad_comida, e.comentarios, e.fecha.strftime('%Y-%m-%d')))
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)
    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="Evaluaciones_Meseros.csv")
    return response

# --- RUTAS DE PREMIOS ---
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

# --- PRODUCTOS ---
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
        
    return render_template('editar_producto.html', producto=p)

@app.route('/admin/producto/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_producto(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    db.session.delete(Producto.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- PUBLICACIONES Y GALERÍA ---
@app.route('/admin/publicacion/nueva', methods=['POST'])
@login_required
def nueva_publicacion():
    if current_user.role != 'admin': return redirect(url_for('index'))
    img_url = cloudinary.uploader.upload(request.files['foto']).get('secure_url') if 'foto' in request.files and request.files['foto'].filename != '' else None
    db.session.add(Publicacion(
        titulo=request.form['titulo'], titulo_en=request.form.get('titulo_en', ''), descripcion=request.form['descripcion'], 
        descripcion_en=request.form.get('descripcion_en', ''), categoria=request.form['categoria'], imagen_url=img_url
    ))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/publicacion/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_publicacion(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    db.session.delete(Publicacion.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

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

@app.route('/admin/anuncio/nuevo', methods=['POST'])
@login_required
def nuevo_anuncio():
    if current_user.role != 'admin': return redirect(url_for('index'))
    
    if request.form.get('activo') == 'on':
        Anuncio.query.update({Anuncio.activo: False})
    
    img_url = cloudinary.uploader.upload(request.files['foto']).get('secure_url') if 'foto' in request.files and request.files['foto'].filename != '' else None
    
    db.session.add(Anuncio(
        mensaje=request.form['mensaje'],
        color=request.form.get('color', 'bg-warning'),
        imagen_url=img_url, 
        texto_boton=request.form.get('texto_boton', ''), 
        enlace=request.form.get('enlace', ''), 
        activo=True if request.form.get('activo') == 'on' else False
    ))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/anuncio/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_anuncio(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    db.session.delete(Anuncio.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- CAJA ---
@app.route('/caja/generar_pin', methods=['POST'])
@login_required
def generar_pin():
    cantidad = int(request.form.get('cantidad', 1))
    for _ in range(cantidad):
        codigo = ''.join(random.choices(string.digits, k=4))
        db.session.add(PinCaja(codigo=codigo))
    db.session.commit()
    flash(f'¡Se generaron {cantidad} PIN(s) con éxito!', 'success')
    
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('cajero_dashboard'))

if __name__ == '__main__':
    app.run(debug=True, port=10000)