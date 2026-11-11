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
    mensaje_en = db.Column(db.String(250), nullable=True)
    color = db.Column(db.String(50), default="bg-dark text-white")
    imagen_url = db.Column(db.String(255), nullable=True)
    texto_boton = db.Column(db.String(50), nullable=True)
    texto_boton_en = db.Column(db.String(50), nullable=True)
    enlace = db.Column(db.String(500), nullable=True)
    activo = db.Column(db.Boolean, default=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- AUTO-PARCHE INICIAL ---
with app.app_context():
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
            "ALTER TABLE galeria ADD COLUMN IF NOT EXISTS descripcion VARCHAR(250);"
        ]
        for sql in instrucciones:
            db.session.execute(text(sql))
        db.session.commit()
    except Exception:
        db.session.rollback()

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

@app.route('/forzar_borrado_anuncios')
def forzar_borrado_anuncios():
    try:
        db.session.execute(text("DROP TABLE IF EXISTS anuncio;"))
        db.session.commit()
        db.create_all()
        return "<h1>¡Tabla de Anuncios Recreada Correctamente! 🚀</h1><a href='/admin_dashboard'>Volver al Panel</a>"
    except Exception as e:
        return f"<h1>Error al recrear tabla:</h1><p>{str(e)}</p>"

# --- RUTA OCULTA DE RESPALDO: CARGAR MENÚ PDF ---
@app.route('/cargar_menu_pdf')
@login_required
def cargar_menu_pdf():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
        
    categorias_pdf = [
        ("Desayunos", "Breakfast"), ("Entradas", "Starters"), ("Sándwiches Bistró", "Bistro Sandwiches"),
        ("Hamburguesas", "Burgers"), ("Antojitos", "Mexican Cravings"), ("Platillos Bistró", "Bistro Dishes"),
        ("Postres", "Desserts"), ("Bebidas Calientes", "Hot Drinks"), ("Bebidas Frías", "Cold Drinks"),
        ("Frappés", "Frappes"), ("Infusiones", "Infusions"), ("Jugos Naturales", "Natural Juices"),
        ("Refrescos", "Soft Drinks"), ("Aguas Naturales", "Fresh Fruit Waters")
    ]
    for nom_es, nom_en in categorias_pdf:
        cat_existente = CategoriaMenu.query.filter_by(nombre=nom_es).first()
        if not cat_existente:
            db.session.add(CategoriaMenu(nombre=nom_es, nombre_en=nom_en))
        elif not cat_existente.nombre_en:
            cat_existente.nombre_en = nom_en
    db.session.commit()

    platillos_pdf = [
        ("Huevos Revueltos al Gusto", "Scrambled Eggs to Taste", "(Chorizo, jamón, tocino o a la mexicana) Acompañado de chilaquiles y frijoles fritos con queso. Horario: 8:00 am a 12:30 pm.", "(Chorizo, ham, bacon, or Mexican style) Served with chilaquiles and fried beans with cheese. Hours: 8:00 am to 12:30 pm.", 85.0, "Desayunos", False),
        ("Huevos Motuleños", "Motuleño Eggs", "Estrellados sobre una tortilla frita bañados con salsa de tomate, jamón, queso amarillo, chícharos y crema.", "Sunny-side up eggs over a fried tortilla bathed in tomato sauce, ham, yellow cheese, peas, and cream.", 175.0, "Desayunos", True),
        ("Huevos Rancheros", "Ranchero Eggs", "Estrellados sobre tortilla frita, cubiertos con salsa ranchera tradicional y acompañados de frijoles refritos.", "Sunny-side up eggs on a fried tortilla, covered with traditional ranchera sauce and served with refried beans.", 95.0, "Desayunos", False),
        ("Huevos Estrellados", "Sunny-Side Up Eggs", "Acompañados de frijoles fritos, guarnición de chilaquiles y tocineta frita.", "Served with fried beans, a side of chilaquiles, and fried bacon.", 85.0, "Desayunos", False),
        ("Omelete", "Mushroom & Cheese Omelette", "Omelette de champiñones y queso, servido con frijoles refritos y guarnición de chilaquiles.", "Mushroom and cheese omelette, served with refried beans and a side of chilaquiles.", 170.0, "Desayunos", False),
        ("Chilaquiles Rojos", "Red Chilaquiles", "Totopos en salsa roja tradicional, con crema, queso y cebolla morada. Acompáñalos con huevos estrellados o pollo deshebrado.", "Tortilla chips in traditional red sauce with cream, cheese, and red onion. Served with sunny-side up eggs or shredded chicken.", 160.0, "Desayunos", True),
        ("Hot Cakes", "Hot Cakes with Red Berries", "Espolvoreados con azúcar, acompañados de frutos rojos.", "Dusted with powdered sugar and served with fresh red berries.", 145.0, "Desayunos", False),
        ("Café Refill", "Refill Coffee", "El refill es para consumo individual, no compartido.", "Refill is for individual consumption only, not shared.", 55.0, "Desayunos", False),
        ("Papas Gajo", "Potato Wedges", "Papas gajo doradas y sazonadas.", "Golden seasoned potato wedges.", 65.0, "Entradas", False),
        ("Tapitas del Quiosco", "Quiosco Tapas", "Tapas de pan artesanal inspiradas en nuestros sándwiches bistró.", "Artisanal bread tapas inspired by our bistro sandwiches.", 89.0, "Entradas", False),
        ("Guacamole", "Fresh Guacamole", "Guacamole tradicional preparado al momento.", "Traditional freshly made guacamole.", 89.0, "Entradas", False),
        ("Nachos", "Loaded Nachos", "Con frijoles, queso amarillo y chile jalapeño (+$25 con chorizo frito).", "With beans, yellow cheese, and jalapeño peppers (+$25 with fried chorizo).", 95.0, "Entradas", False),
        ("Sandwich Morisco", "Morisco Sandwich", "Jamón serrano, aderezo de queso de cabra, fresa, frambuesa, arúgula y vinagreta.", "Serrano ham, goat cheese dressing, strawberry, raspberry, arugula, and vinaigrette.", 132.0, "Sándwiches Bistró", True),
        ("Sandwich de Pollo", "Chicken Sandwich", "Pechuga de pollo, tomate cherry, arúgula, aderezo de aguacate y vinagreta.", "Chicken breast, cherry tomato, arugula, avocado dressing, and vinaigrette.", 115.0, "Sándwiches Bistró", False),
        ("Cuernito Pomposo", "Pomposo Croissant", "Jamón serrano, aderezo de queso, arúgula, tomate cherry y queso mozzarella.", "Serrano ham, cheese dressing, arugula, cherry tomato, and mozzarella cheese.", 125.0, "Sándwiches Bistró", False),
        ("Hamburguesa Morisco", "Morisco Burger", "Carne de res, tocino, ensalada, aderezo de mayonesa y queso mozzarella.", "Beef patty, bacon, salad, mayo dressing, and mozzarella cheese.", 115.0, "Hamburguesas", True),
        ("Hamburguesa Hawaiana", "Hawaiian Burger", "Carne de res, tocino, piña, ensalada, aderezo de mayonesa y queso mozzarella.", "Beef patty, bacon, pineapple, salad, mayo dressing, and mozzarella cheese.", 123.0, "Hamburguesas", False),
        ("Enchiladas Coletas", "Coletas Mole Enchiladas", "Enchiladas de pollo bañadas en mole tradicional coleto, acompañadas con queso y crema.", "Chicken enchiladas bathed in traditional San Cristobal mole, topped with cheese and cream.", 155.0, "Antojitos", True),
        ("Tacos SC", "Tacos SC (Asado Coleto)", "De asado tradicional coleto, acompañados de cilantro y salsa verde.", "Traditional San Cristobal pork stew tacos, served with cilantro and green salsa.", 140.0, "Antojitos", False),
        ("Tostadas de Pollo", "Chicken Tostadas", "Tostadas doradas cubiertas con lechuga, queso, crema, aguacate y pollo. Acompañadas de pico de gallo.", "Crispy tortillas topped with lettuce, cheese, cream, avocado, and chicken. Served with pico de gallo.", 95.0, "Antojitos", False),
        ("Tacos Dorados", "Crispy Chicken Tacos", "Orden de 4 tacos dorados, rellenos de pollo, servidos con lechuga, queso, crema y pico de gallo.", "Order of 4 crispy tacos filled with chicken, served with lettuce, cheese, cream, and pico de gallo.", 80.0, "Antojitos", False),
        ("Quesadillas", "Quesadillas", "Orden de 3 quesadillas, acompañadas de ensalada.", "Order of 3 quesadillas, served with salad.", 105.0, "Antojitos", False),
        ("Club Sandwich", "Club Sandwich", "Con pollo, jamón y queso gratinado.", "With chicken, ham, and melted gratin cheese.", 155.0, "Platillos Bistró", False),
        ("Plátanos Fritos", "Fried Plantains", "Plátanos fritos tradicionales.", "Traditional sweet fried plantains.", 60.0, "Postres", False),
        ("Cuernito Relleno de Nutella", "Nutella Stuffed Croissant", "Crujiente cuernito relleno de Nutella.", "Crispy croissant filled with Nutella.", 62.0, "Postres", False),
        ("Corbata de Frutos Rojos", "Red Berries Tie Pastry", "Hojaldre crujiente con frutos rojos.", "Crispy puff pastry with red berries.", 60.0, "Postres", False),
        ("Relleno de Guayaba", "Guava Filled Pastry", "Pan artesanal relleno de dulce de guayaba.", "Artisanal pastry filled with sweet guava.", 58.0, "Postres", False),
        ("Chocolatín", "Pain au Chocolat", "Hojaldre relleno de chocolate.", "Flaky pastry filled with chocolate.", 50.0, "Postres", False),
        ("Pan Regional", "Regional Sweet Bread", "Orden de 6 piezas de pan tradicional coleto.", "Order of 6 pieces of traditional regional bread.", 35.0, "Postres", False),
        ("Expresso", "Espresso", "Sencillo $40 | Doble +$20 | Cortado +$15.", "Single $40 | Double +$20 | Cortado +$15.", 40.0, "Bebidas Calientes", False),
        ("Americano", "Americano Coffee", "Café americano recién extraído.", "Freshly brewed Americano coffee.", 55.0, "Bebidas Calientes", False),
        ("Mocha", "Hot Mocha", "Espresso con chocolate y leche vaporizada.", "Espresso with chocolate and steamed milk.", 72.0, "Bebidas Calientes", False),
        ("Café Latte", "Cafe Latte", "Espresso con leche suave vaporizada.", "Espresso with smooth steamed milk.", 65.0, "Bebidas Calientes", False),
        ("Capuchino", "Cappuccino", "Clásico capuchino espumoso (Moka +$10).", "Classic foamy cappuccino (Mocha +$10).", 65.0, "Bebidas Calientes", True),
        ("Chai Latte", "Hot Chai Latte", "Té chai especiado con leche vaporizada.", "Spiced chai tea with steamed milk.", 70.0, "Bebidas Calientes", False),
        ("Chocolate", "Hot Chocolate", "Chocolate caliente tradicional.", "Traditional hot chocolate.", 70.0, "Bebidas Calientes", False),
        ("Americano Frío", "Iced Americano", "Café americano servido en las rocas.", "Americano coffee served over ice.", 55.0, "Bebidas Frías", False),
        ("Expresso Menta", "Mint Iced Espresso", "Refrescante espresso frío con un toque de menta.", "Refreshing iced espresso with a touch of mint.", 68.0, "Bebidas Frías", False),
        ("Café Latte Frío", "Iced Cafe Latte", "Espresso con leche fría y hielo.", "Espresso with cold milk and ice.", 65.0, "Bebidas Frías", False),
        ("Capuchino Frío", "Iced Cappuccino", "Capuchino frío (Moka +$10).", "Iced cappuccino (Mocha +$10).", 65.0, "Bebidas Frías", False),
        ("Chai Latte Frío", "Iced Chai Latte", "Té chai especiado con leche y hielo.", "Spiced chai tea with milk and ice.", 70.0, "Bebidas Frías", False),
        ("Chocolate Frío", "Iced Chocolate", "Chocolate frío espumoso.", "Frothy iced chocolate.", 70.0, "Bebidas Frías", False),
        ("Frappé Moka", "Mocha Frappe", "Frappé de café con chocolate.", "Blended coffee and chocolate frappe.", 90.0, "Frappés", False),
        ("Frappé Café", "Coffee Frappe", "Clásico frappé de café.", "Classic blended coffee frappe.", 90.0, "Frappés", False),
        ("Frappé Taro", "Taro Frappe", "Frappé cremoso de taro.", "Creamy taro frappe.", 85.0, "Frappés", False),
        ("Frappé Chai", "Chai Frappe", "Frappé de té chai especiado.", "Spiced chai tea frappe.", 85.0, "Frappés", False),
        ("Bae", "Bae (Taro Bubble Tea)", "Taro, lácteos, té negro y tapioca.", "Taro, dairy, black tea, and tapioca pearls.", 90.0, "Frappés", True),
        ("Bubba Ti", "Bubba Ti (Cold Brew Bubble Tea)", "Cold brew, té negro, lácteos y tapioca.", "Cold brew, black tea, dairy, and tapioca pearls.", 95.0, "Frappés", False),
        ("Leche Dorada", "Golden Milk", "Infusión reconfortante a base de cúrcuma y especias. *Pregunta por nuestras bebidas de temporada.", "Soothing turmeric and spice infusion. *Ask about our seasonal drinks.", 70.0, "Infusiones", False),
        ("Infusión de Maracuyá", "Passion Fruit Infusion", "Infusión aromática de maracuyá. *Pregunta por nuestras bebidas de temporada.", "Aromatic passion fruit infusion. *Ask about our seasonal drinks.", 65.0, "Infusiones", False),
        ("Moon Milk", "Moon Milk", "Infusión relajante de leche especiada. *Pregunta por nuestras bebidas de temporada.", "Relaxing spiced milk infusion. *Ask about our seasonal drinks.", 70.0, "Infusiones", False),
        ("Agua Moriska", "Moriska Cooler", "Fresa, pepino y menta.", "Strawberry, cucumber, and fresh mint.", 80.0, "Jugos Naturales", True),
        ("Vergel", "Vergel Green Juice", "Piña, naranja y arúgula.", "Pineapple, orange, and arugula.", 65.0, "Jugos Naturales", False),
        ("Rosal", "Rosal Cold Brew Tonic", "Cold brew, mora y miel.", "Cold brew coffee, blackberry, and honey.", 80.0, "Jugos Naturales", False),
        ("Coca Cola Lata", "Canned Coca-Cola", "Lata 355 ml.", "355 ml can.", 50.0, "Refrescos", False),
        ("Sprite Lata", "Canned Sprite", "Lata 355 ml.", "355 ml can.", 50.0, "Refrescos", False),
        ("Sidral Mundet", "Sidral Mundet Apple Soda", "Lata 355 ml.", "355 ml can.", 50.0, "Refrescos", False),
        ("Agua Ciel 600", "Bottled Water (600 ml)", "Botella de agua natural 600 ml.", "600 ml natural bottled water.", 30.0, "Refrescos", False),
        ("Agua Mineral", "Sparkling Mineral Water", "Agua mineral refrescante.", "Refreshing sparkling mineral water.", 45.0, "Refrescos", False),
        ("Agua de Jamaica", "Hibiscus Water", "Agua fresca natural de flor de jamaica.", "Fresh natural hibiscus flower water.", 40.0, "Aguas Naturales", False),
        ("Naranjada", "Fresh Orangeade", "Preparada con jugo de naranja natural.", "Made with fresh-squeezed orange juice.", 40.0, "Aguas Naturales", False),
        ("Naranjada Mineral", "Sparkling Orangeade", "Jugo de naranja natural con agua mineral.", "Fresh orange juice with sparkling mineral water.", 52.0, "Aguas Naturales", False),
        ("Limonada", "Fresh Lemonade", "Preparada con jugo de limón natural.", "Made with fresh lime juice.", 40.0, "Aguas Naturales", False),
        ("Limonada Mineral", "Sparkling Lemonade", "Jugo de limón natural con agua mineral.", "Fresh lime juice with sparkling mineral water.", 52.0, "Aguas Naturales", False)
    ]

    for nom_es, nom_en, desc_es, desc_en, precio, cat, dest in platillos_pdf:
        prod_existente = Producto.query.filter_by(nombre=nom_es).first()
        if not prod_existente:
            db.session.add(Producto(
                nombre=nom_es, nombre_en=nom_en,
                descripcion=desc_es, descripcion_en=desc_en,
                precio=precio, categoria=cat, destacado=dest, agotado=False
            ))
    db.session.commit()
    flash('¡Menú de respaldo restaurado con éxito!', 'success')
    return redirect(url_for('admin_dashboard'))


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
    return "<h1>¡BD Reconstruida!</h1><p>Vuelve al <a href='/admin_login'>login</a>.</p>"

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
    clientes_top = Cliente.query.order_by(Cliente.visitas.desc(), Cliente.fecha_registro.desc()).limit(30).all()

    return render_template('admin_dashboard.html', 
                           categorias=CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all(),
                           premios=Premio.query.order_by(Premio.visitas_necesarias.asc()).all(),
                           productos=Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all(), 
                           pins=PinCaja.query.filter_by(activo=True).all(),
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
        
    categorias_bd = CategoriaMenu.query.order_by(CategoriaMenu.id.asc()).all()
    return render_template('editar_producto.html', producto=p, categorias=categorias_bd)

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

# --- ANUNCIOS (SOPORTE MULTI-BANNER CARRUSEL) ---
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