import os
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'clave_secreta_quiosco_123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///restaurante.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ================= MODELOS =================
class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    rol = db.Column(db.String(20), nullable=False)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20), unique=True, nullable=False)
    consumos = db.Column(db.Integer, default=0)

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), nullable=False) 
    precio = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    imagen_url = db.Column(db.String(200), nullable=True)

class PinValido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    usado = db.Column(db.Boolean, default=False)
    creado_por = db.Column(db.String(50), nullable=True)
    fecha_creacion = db.Column(db.String(50), nullable=True)

class Configuracion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(50), unique=True, nullable=False)
    valor = db.Column(db.String(200), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# ================= RUTAS DEL CLIENTE =================
@app.route('/')
def inicio():
    productos = Producto.query.all()
    categorias = {}
    for p in productos:
        if p.categoria not in categorias: categorias[p.categoria] = []
        categorias[p.categoria].append(p)
        
    meta1_conf = Configuracion.query.filter_by(clave='meta_1').first()
    meta2_conf = Configuracion.query.filter_by(clave='meta_2').first()
    meta_1 = int(meta1_conf.valor) if meta1_conf else 5
    meta_2 = int(meta2_conf.valor) if meta2_conf else 10
    
    telefono = session.get('telefono_cliente')
    cliente_actual = None
    progreso = 0
    if telefono:
        cliente_actual = Cliente.query.filter_by(telefono=telefono).first()
        if cliente_actual:
            progreso = cliente_actual.consumos % meta_2
            if progreso == 0 and cliente_actual.consumos > 0:
                progreso = meta_2
                
    return render_template('index.html', categorias=categorias, productos=productos, cliente=cliente_actual, meta_1=meta_1, meta_2=meta_2, progreso=progreso)

@app.route('/registrar_consumo', methods=['POST'])
def registrar_consumo():
    telefono = request.form.get('telefono')
    nombre = request.form.get('nombre')
    pin_ingresado = request.form.get('pin')

    pin_obj = PinValido.query.filter_by(codigo=pin_ingresado, usado=False).first()
    if not pin_obj:
        flash('El PIN ingresado es incorrecto o ya fue utilizado.', 'error')
        return redirect(url_for('inicio'))

    cliente = Cliente.query.filter_by(telefono=telefono).first()
    if not cliente:
        cliente = Cliente(nombre=nombre, telefono=telefono, consumos=1)
        db.session.add(cliente)
    else:
        cliente.consumos += 1

    pin_obj.usado = True
    db.session.commit()
    session['telefono_cliente'] = cliente.telefono

    meta1_conf = Configuracion.query.filter_by(clave='meta_1').first()
    meta2_conf = Configuracion.query.filter_by(clave='meta_2').first()
    meta_1 = int(meta1_conf.valor) if meta1_conf else 5
    meta_2 = int(meta2_conf.valor) if meta2_conf else 10

    ciclo_actual = cliente.consumos % meta_2

    if ciclo_actual == meta_1:
        premio1_conf = Configuracion.query.filter_by(clave='premio_1').first()
        texto = premio1_conf.valor if premio1_conf else "Premio Intermedio"
        flash(f'¡Felicidades {cliente.nombre}! Llegaste a {meta_1} visitas. Ganaste: {texto}.', 'premio_interactivo')
    elif ciclo_actual == 0 and cliente.consumos > 0:
        premio2_conf = Configuracion.query.filter_by(clave='premio_2').first()
        texto = premio2_conf.valor if premio2_conf else "Premio Mayor"
        flash(f'¡Felicidades {cliente.nombre}! Llenaste tu tarjeta ({meta_2} visitas). Ganaste: {texto}.', 'premio_interactivo')
    else:
        flash(f'¡Consumo registrado con éxito!', 'exito')

    return redirect(url_for('inicio'))

# ================= RUTAS DEL PANEL =================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = Usuario.query.filter_by(username=request.form.get('username')).first()
        if usuario and check_password_hash(usuario.password_hash, request.form.get('password')):
            login_user(usuario)
            return redirect(url_for('cajero_dashboard' if usuario.rol == 'cajero' else 'admin_dashboard'))
        flash('Usuario o contraseña incorrectos.', 'error')
    return render_template('admin_login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/caja')
@login_required
def cajero_dashboard():
    if current_user.rol not in ['cajero', 'admin', 'superadmin']: return "Denegado"
    return render_template('cajero_dashboard.html', pins=PinValido.query.filter_by(usado=False).all(), clientes=Cliente.query.all())

@app.route('/caja/generar_pin', methods=['POST'])
@login_required
def cajero_generar_pin():
    db.session.add(PinValido(codigo=str(random.randint(1000, 9999)), creado_por=current_user.username, fecha_creacion=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db.session.commit()
    return redirect(url_for('cajero_dashboard' if current_user.rol == 'cajero' else 'admin_dashboard'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.rol not in ['admin', 'superadmin']: return redirect(url_for('cajero_dashboard'))
    def get_conf(clave, default):
        c = Configuracion.query.filter_by(clave=clave).first()
        return c.valor if c else default

    return render_template('admin_dashboard.html', 
                           productos=Producto.query.all(), clientes=Cliente.query.all(), 
                           pins=PinValido.query.filter_by(usado=False).all(), 
                           historial=PinValido.query.filter_by(usado=True).order_by(PinValido.id.desc()).limit(20).all(),
                           meta_1=int(get_conf('meta_1', 5)), premio_1=get_conf('premio_1', 'Bebida Gratis'),
                           meta_2=int(get_conf('meta_2', 10)), premio_2=get_conf('premio_2', 'Platillo Gratis'))

@app.route('/admin/configurar_premio', methods=['POST'])
@login_required
def configurar_premio():
    datos = {'meta_1': request.form.get('meta_1'), 'premio_1': request.form.get('premio_1'), 'meta_2': request.form.get('meta_2'), 'premio_2': request.form.get('premio_2')}
    for clave, valor in datos.items():
        c = Configuracion.query.filter_by(clave=clave).first()
        if c: c.valor = str(valor)
        else: db.session.add(Configuracion(clave=clave, valor=str(valor)))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/cliente/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_cliente(id):
    db.session.delete(Cliente.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/producto/nuevo', methods=['POST'])
@login_required
def nuevo_producto():
    prod = Producto(nombre=request.form.get('nombre'), categoria=request.form.get('categoria'), precio=float(request.form.get('precio')), descripcion=request.form.get('descripcion'))
    if 'foto' in request.files and request.files['foto'].filename != '':
        foto = request.files['foto']
        nombre_arch = f"foto_{int(time.time())}.{foto.filename.split('.')[-1]}"
        foto.save(os.path.join(app.root_path, 'static', nombre_arch))
        prod.imagen_url = f'/static/{nombre_arch}'
    db.session.add(prod)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/producto/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_producto(id):
    db.session.delete(Producto.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# AQUÍ REPARAMOS LA FUNCIÓN PARA QUE SÍ ACTUALICE LA CATEGORÍA
@app.route('/admin/producto/editar/<int:id>', methods=['POST'])
@login_required
def editar_producto(id):
    producto = Producto.query.get_or_404(id)
    producto.nombre = request.form.get('nombre')
    producto.precio = float(request.form.get('precio'))
    producto.categoria = request.form.get('categoria') # ¡Agregado!
    
    if 'foto' in request.files and request.files['foto'].filename != '':
        foto = request.files['foto']
        nombre_arch = f"foto_{int(time.time())}.{foto.filename.split('.')[-1]}"
        foto.save(os.path.join(app.root_path, 'static', nombre_arch))
        producto.imagen_url = f'/static/{nombre_arch}'
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Usuario.query.filter_by(username='brayan_master').first():
            db.session.add(Usuario(username='brayan_master', password_hash=generate_password_hash('master2027'), rol='superadmin'))
            db.session.add(Usuario(username='raquel', password_hash=generate_password_hash('raquel2027'), rol='admin'))
            db.session.add(Usuario(username='cajero1', password_hash=generate_password_hash('contraseña2027'), rol='cajero'))
            db.session.add(Configuracion(clave='meta_1', valor='5'))
            db.session.add(Configuracion(clave='premio_1', valor='Bebida Gratis'))
            db.session.add(Configuracion(clave='meta_2', valor='10'))
            db.session.add(Configuracion(clave='premio_2', valor='Platillo Gratis'))
        db.session.commit()
    app.run(host='0.0.0.0', port=5000, debug=True)