from datetime import datetime, timedelta, timezone
import random
import string
import threading
import time
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, current_user
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from zoneinfo import ZoneInfo
    TZ_CHIAPAS = ZoneInfo("America/Mexico_City")
except Exception:
    TZ_CHIAPAS = timezone(timedelta(hours=-6))

db = SQLAlchemy()
login_manager = LoginManager()

_CACHE_LOCK = threading.Lock()
_CACHE_STORE = {}


def cache_get(clave, ttl_segundos):
    with _CACHE_LOCK:
        item = _CACHE_STORE.get(clave)
        if item and (time.monotonic() - item[0]) < ttl_segundos:
            return item[1]
    return None


def cache_set(clave, valor):
    with _CACHE_LOCK:
        _CACHE_STORE[clave] = (time.monotonic(), valor)
    return valor


def invalidar_cache_publico():
    with _CACHE_LOCK:
        _CACHE_STORE.pop('menu_publico', None)
        _CACHE_STORE.pop('estado_agotados', None)

SUCURSALES_OFICIALES = [
    'Quiosco Morisco (Matriz)',
    'Caminante 1',
    'Caminante 2',
    'Caminante 3'
]

PREFIJO_SUCURSAL = {
    'Quiosco Morisco (Matriz)': 'QM',
    'Caminante 1': 'C1',
    'Caminante 2': 'C2',
    'Caminante 3': 'C3'
}

MAPA_SUCURSAL_USUARIO = {
    'quiosco': 'Quiosco Morisco (Matriz)',
    'caminante1': 'Caminante 1',
    'caminante2': 'Caminante 2',
    'caminante3': 'Caminante 3'
}


def ahora_local():
    """Fecha y hora actual de San Cristóbal de las Casas (naive para PostgreSQL)."""
    return datetime.now(TZ_CHIAPAS).replace(tzinfo=None)


def inicio_hoy_local():
    return ahora_local().replace(hour=0, minute=0, second=0, microsecond=0)


# ==============================================================================
# MODELOS BASE (USUARIOS, MENÚ PÚBLICO Y FIDELIDAD)
# ==============================================================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='cajero')
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')


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
    fecha = db.Column(db.DateTime, default=ahora_local)


class Galeria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    imagen_url = db.Column(db.String(255), nullable=False)
    titulo = db.Column(db.String(100), nullable=True)
    descripcion = db.Column(db.String(250), nullable=True)
    fecha_subida = db.Column(db.DateTime, default=ahora_local)


class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    visitas = db.Column(db.Integer, default=0)
    fecha_registro = db.Column(db.DateTime, default=ahora_local)


class PinCaja(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True)
    creado_por = db.Column(db.String(80), nullable=True, default='caja')
    folio_sr = db.Column(db.String(50), nullable=True, default='')
    fecha_creacion = db.Column(db.DateTime, default=ahora_local)
    usado_por = db.Column(db.String(120), nullable=True)
    fecha_uso = db.Column(db.DateTime, nullable=True)


class Evaluacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesero_nombre = db.Column(db.String(100), nullable=False)
    mesero_calificacion = db.Column(db.Integer, nullable=False)
    limpieza = db.Column(db.Integer, nullable=False)
    calidad_comida = db.Column(db.Integer, nullable=False)
    comentarios = db.Column(db.Text, nullable=True)
    fecha = db.Column(db.DateTime, default=ahora_local)


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
    fecha = db.Column(db.DateTime, default=ahora_local)


# ==============================================================================
# MODELOS COMENSAL CONECTADO (POS MULTI-SUCURSAL)
# ==============================================================================
class ConfigPermisosPOS(db.Model):
    __tablename__ = 'config_permisos_pos'
    id = db.Column(db.Integer, primary_key=True)
    cajero_puede_cancelar = db.Column(db.Boolean, default=True)
    cajero_puede_descontar = db.Column(db.Boolean, default=True)
    cajero_puede_cambiar_pago = db.Column(db.Boolean, default=True)


class TurnoPOS(db.Model):
    __tablename__ = 'turnos_pos'
    id = db.Column(db.Integer, primary_key=True)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')
    cajero = db.Column(db.String(80), nullable=False)
    apertura = db.Column(db.DateTime, default=ahora_local)
    cierre = db.Column(db.DateTime, nullable=True)
    fondo_inicial = db.Column(db.Float, default=0.0)
    depositos_efectivo = db.Column(db.Float, default=0.0)
    retiros_efectivo = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(20), default='ABIERTO')


class MovimientoCajaPOS(db.Model):
    __tablename__ = 'movimientos_caja_pos'
    id = db.Column(db.Integer, primary_key=True)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos_pos.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    concepto = db.Column(db.String(200), nullable=False)
    usuario = db.Column(db.String(80), nullable=False)
    fecha = db.Column(db.DateTime, default=ahora_local)


class CuentaPOS(db.Model):
    __tablename__ = 'cuentas_pos'
    id = db.Column(db.Integer, primary_key=True)
    turno_id = db.Column(db.Integer, db.ForeignKey('turnos_pos.id'), nullable=True)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')
    parent_cuenta_id = db.Column(db.Integer, nullable=True)
    es_subcuenta_parte = db.Column(db.Boolean, default=False)
    folio = db.Column(db.String(25), unique=True, nullable=True)
    orden = db.Column(db.String(15), nullable=False)
    area = db.Column(db.String(40), default='01 COMEDOR')
    mesa = db.Column(db.String(30), nullable=False)
    mesero = db.Column(db.String(60), default='MESERO')
    personas = db.Column(db.Integer, default=1)
    observaciones = db.Column(db.Text, nullable=True)
    apertura = db.Column(db.DateTime, default=ahora_local)
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
    pago_transferencia = db.Column(db.Float, default=0.0)
    pago_otros = db.Column(db.Float, default=0.0)  # Vale / Consumo empleado
    tarjeta_ultimos4 = db.Column(db.String(10), default='')
    propina_tarjeta = db.Column(db.Float, default=0.0)
    cambio = db.Column(db.Float, default=0.0)

    recetas_descontadas = db.Column(db.Boolean, default=False)
    estado = db.Column(db.String(20), default='ABIERTA')  # ABIERTA | PAGADA | DIVIDIDA | COMBINADA | CANCELADA
    detalles = db.relationship('DetallePOS', backref='cuenta', lazy=True, cascade="all, delete-orphan")


class DetallePOS(db.Model):
    __tablename__ = 'detalles_pos'
    id = db.Column(db.Integer, primary_key=True)
    cuenta_id = db.Column(db.Integer, db.ForeignKey('cuentas_pos.id'), nullable=False)
    parent_detalle_id = db.Column(db.Integer, nullable=True)
    num_comanda = db.Column(db.Integer, default=1)
    cantidad = db.Column(db.Float, default=1.0)
    clave = db.Column(db.String(20), default='00001')
    descripcion = db.Column(db.String(150), nullable=False)
    area_impresion = db.Column(db.String(20), default='BARRA')
    es_modificador = db.Column(db.Boolean, default=False)
    precio_unitario = db.Column(db.Float, default=0.0)
    descuento_pct = db.Column(db.Float, default=0.0)
    descuento_monto = db.Column(db.Float, default=0.0)
    promo_aplicada = db.Column(db.String(100), nullable=True)
    importe = db.Column(db.Float, default=0.0)
    impreso_comanda = db.Column(db.Boolean, default=False)


class ColaImpresionPOS(db.Model):
    __tablename__ = 'cola_impresion_pos'
    id = db.Column(db.Integer, primary_key=True)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')
    tipo = db.Column(db.String(30), nullable=False)
    contenido_html = db.Column(db.Text, nullable=False)
    impreso = db.Column(db.Boolean, default=False)
    fecha = db.Column(db.DateTime, default=ahora_local)


class ModificadorPOS(db.Model):
    __tablename__ = 'modificadores_pos'
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(20), nullable=False, default='03001')
    grupo = db.Column(db.String(50), nullable=False, default='SABORES')
    nombre = db.Column(db.String(100), nullable=False)
    precio = db.Column(db.Float, default=0.0)
    activo = db.Column(db.Boolean, default=True)


class PromocionPOS(db.Model):
    __tablename__ = 'promociones_pos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(30), nullable=False, default='DESCUENTO_PCT')  # DESCUENTO_PCT | PRECIO_FIJO | VOLUMEN_2X1
    valor = db.Column(db.Float, default=0.0)       # % descuento o precio fijo
    por_cada = db.Column(db.Integer, default=2)    # Para 2x1 / 3x2
    regala = db.Column(db.Integer, default=1)
    aplica_a = db.Column(db.String(20), default='CATEGORIA')  # PRODUCTO | CATEGORIA
    objetivo = db.Column(db.String(120), nullable=False)
    dias = db.Column(db.String(30), default='0,1,2,3,4,5,6')  # 0=Lun .. 6=Dom
    hora_inicio = db.Column(db.String(5), default='00:00')
    hora_fin = db.Column(db.String(5), default='23:59')
    activa = db.Column(db.Boolean, default=True)


class BitacoraPOS(db.Model):
    __tablename__ = 'bitacora_pos'
    id = db.Column(db.Integer, primary_key=True)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')
    fecha = db.Column(db.DateTime, default=ahora_local)
    usuario = db.Column(db.String(80), nullable=False)
    autorizo = db.Column(db.String(80), nullable=True)
    accion = db.Column(db.String(60), nullable=False)
    mesa = db.Column(db.String(30), nullable=True)
    monto = db.Column(db.Float, default=0.0)
    detalle = db.Column(db.String(255), nullable=True)


class AlertaMesaPOS(db.Model):
    __tablename__ = 'alertas_mesa_pos'
    id = db.Column(db.Integer, primary_key=True)
    cuenta_id = db.Column(db.Integer, unique=True, nullable=False)
    solicito_cuenta = db.Column(db.Boolean, default=False)
    descuento_motivo = db.Column(db.String(200), nullable=True)
    fecha_alerta = db.Column(db.DateTime, default=ahora_local)


class ArqueoTurnoPOS(db.Model):
    __tablename__ = 'arqueos_turno_pos'
    id = db.Column(db.Integer, primary_key=True)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')
    turno_id = db.Column(db.Integer, nullable=False)
    cajero = db.Column(db.String(80), nullable=False)
    fecha = db.Column(db.DateTime, default=ahora_local)
    ef_declarado = db.Column(db.Float, default=0.0)
    td_declarado = db.Column(db.Float, default=0.0)
    tc_declarado = db.Column(db.Float, default=0.0)
    trans_declarado = db.Column(db.Float, default=0.0)
    amex_declarado = db.Column(db.Float, default=0.0)
    cr_declarado = db.Column(db.Float, default=0.0)
    dll_declarado = db.Column(db.Float, default=0.0)
    val_declarado = db.Column(db.Float, default=0.0)
    esperado_total = db.Column(db.Float, default=0.0)
    declarado_total = db.Column(db.Float, default=0.0)
    diferencia = db.Column(db.Float, default=0.0)


# ==============================================================================
# MODELOS BODEGA CENTRAL, STOCK LOCAL, RECETAS, OPERACIÓN Y NÓMINA
# ==============================================================================
class InsumoBodegaPro(db.Model):
    __tablename__ = 'insumos_bodega_pro'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(60), nullable=False, default='ABARROTES')
    unidad = db.Column(db.String(20), nullable=False, default='PZA')
    stock_actual = db.Column(db.Float, default=0.0)
    stock_minimo = db.Column(db.Float, default=2.0)
    costo_unitario = db.Column(db.Float, default=0.0)


class StockSucursal(db.Model):
    __tablename__ = 'stock_sucursal'
    id = db.Column(db.Integer, primary_key=True)
    sucursal = db.Column(db.String(100), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey('insumos_bodega_pro.id'), nullable=False)
    stock_actual = db.Column(db.Float, default=0.0)
    stock_minimo = db.Column(db.Float, default=2.0)


class RecetaPOS(db.Model):
    __tablename__ = 'recetas_pos'
    id = db.Column(db.Integer, primary_key=True)
    platillo_nombre = db.Column(db.String(150), nullable=False)  # Ej. CAPUCHINO o >LECHE ALMENDRAS
    insumo_id = db.Column(db.Integer, db.ForeignKey('insumos_bodega_pro.id'), nullable=False)
    cantidad_descontar = db.Column(db.Float, nullable=False)


class RequerimientoBodega(db.Model):
    __tablename__ = 'requerimientos_bodega'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')
    area = db.Column(db.String(30), nullable=False, default='BARRA')
    insumo_id = db.Column(db.Integer, nullable=True)
    insumo_nombre = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(60), nullable=False, default='ABARROTES')
    cantidad = db.Column(db.Float, default=1.0)
    cantidad_entregada = db.Column(db.Float, nullable=True)
    unidad = db.Column(db.String(20), default='PZA')
    estado_bodega = db.Column(db.String(25), default='PENDIENTE')
    confirmado_caja = db.Column(db.Boolean, default=False)
    solicitado_por = db.Column(db.String(60), default='CAJA')
    nota = db.Column(db.String(180), default='')


class MovimientoAlmacen(db.Model):
    __tablename__ = 'movimientos_almacen'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
    tipo = db.Column(db.String(30), nullable=False)
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


class RegistroAsistencia(db.Model):
    __tablename__ = 'registros_asistencia'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
    sucursal = db.Column(db.String(100), nullable=False)
    empleado_nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    notas = db.Column(db.String(150), default='')


class RegistroMerma(db.Model):
    __tablename__ = 'registros_mermas'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
    sucursal = db.Column(db.String(100), nullable=False)
    insumo_nombre = db.Column(db.String(120), nullable=False)
    cantidad = db.Column(db.Float, default=1.0)
    unidad = db.Column(db.String(20), default='PZA')
    costo_total = db.Column(db.Float, default=0.0)
    motivo = db.Column(db.String(200), nullable=False)
    usuario = db.Column(db.String(80), nullable=False)


class EmpleadoNominaPOS(db.Model):
    __tablename__ = 'empleados_nomina_pos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    puesto = db.Column(db.String(60), default='MESERO')
    sueldo_base = db.Column(db.Float, default=1500.0)
    periodo = db.Column(db.String(20), default='SEMANAL')
    activo = db.Column(db.Boolean, default=True)


class ConsumoEmpleadoPOS(db.Model):
    __tablename__ = 'consumos_empleados_pos'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
    empleado_id = db.Column(db.Integer, nullable=False)
    empleado_nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(30), default='CONSUMO')
    concepto = db.Column(db.String(200), nullable=False)
    monto = db.Column(db.Float, default=0.0)
    descontado = db.Column(db.Boolean, default=False)
    registrado_por = db.Column(db.String(60), default='CAJA')


class ReciboNominaPOS(db.Model):
    __tablename__ = 'recibos_nomina_pos'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
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


# ==============================================================================
# FUNCIONES AUXILIARES COMPARTIDAS
# ==============================================================================
def obtener_sucursal_activa(session_obj=None):
    """Retorna la sucursal del usuario (admin puede alternar entre las 4)."""
    if not current_user.is_authenticated:
        return 'Quiosco Morisco (Matriz)'
    if current_user.role == 'admin' and session_obj is not None:
        suc = session_obj.get('sucursal_activa')
        if suc in SUCURSALES_OFICIALES:
            return suc
    usr_suc = getattr(current_user, 'sucursal', None)
    if usr_suc in SUCURSALES_OFICIALES:
        return usr_suc
    return MAPA_SUCURSAL_USUARIO.get(current_user.username.lower(), 'Quiosco Morisco (Matriz)')


def validar_clave_admin(clave_ingresada):
    clave = str(clave_ingresada or '').strip()
    if not clave:
        return None
    for adm in User.query.filter_by(role='admin').all():
        if check_password_hash(adm.password, clave):
            return adm.username.upper()
    return None


def registrar_bitacora(accion, mesa='', monto=0.0, detalle='', autorizo='', sucursal=None):
    try:
        suc = sucursal or getattr(current_user, 'sucursal', None) or 'Quiosco Morisco (Matriz)'
        db.session.add(BitacoraPOS(
            sucursal=suc,
            fecha=ahora_local(),
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


def generar_pin_unico():
    """Genera un PIN único en TODA la tabla PinCaja (activos y usados) sin error IntegrityError."""
    for _ in range(150):
        cod = ''.join(random.choices(string.digits, k=4))
        if not PinCaja.query.filter_by(codigo=cod).first():
            return cod
    while True:
        cod = ''.join(random.choices(string.digits, k=6))
        if not PinCaja.query.filter_by(codigo=cod).first():
            return cod


def detectar_area_impresion(categoria_nombre):
    cat = (categoria_nombre or '').lower()
    palabras_barra = [
        'caliente', 'fría', 'fria', 'frapp', 'infus', 'jugo',
        'refresco', 'agua', 'postre', 'cerveza', 'coctel', 'café', 'cafe', 'bebida'
    ]
    for p in palabras_barra:
        if p in cat:
            return 'BARRA'
    return 'COCINA'


def obtener_turno_activo(sucursal='Quiosco Morisco (Matriz)'):
    t = TurnoPOS.query.filter_by(sucursal=sucursal, estado='ABIERTO').order_by(TurnoPOS.id.desc()).first()
    if not t:
        cajero_nom = current_user.username.upper() if current_user.is_authenticated else 'CAJA'
        t = TurnoPOS(sucursal=sucursal, cajero=cajero_nom, fondo_inicial=0.0, estado='ABIERTO', apertura=ahora_local())
        db.session.add(t)
        db.session.commit()
    return t


def _mapa_categorias_productos():
    return {p.nombre.strip().upper(): p.categoria.strip().upper() for p in Producto.query.all()}


def aplicar_promociones_cuenta(c):
    """Evalúa promociones automáticas activas según día y hora local de Chiapas."""
    if c.es_subcuenta_parte:
        return
    ahora = ahora_local()
    dia_hoy = str(ahora.weekday())  # 0=Lunes .. 6=Domingo
    hora_str = ahora.strftime('%H:%M')

    promos = PromocionPOS.query.filter_by(activa=True).all()
    promos_vigentes = []
    for pr in promos:
        dias_ok = dia_hoy in [x.strip() for x in (pr.dias or '').split(',')]
        hora_ok = (pr.hora_inicio or '00:00') <= hora_str <= (pr.hora_fin or '23:59')
        if dias_ok and hora_ok:
            promos_vigentes.append(pr)

    # Limpia solo descuentos puestos por promociones anteriores (respeta descuentos manuales)
    for d in c.detalles:
        if d.promo_aplicada:
            d.descuento_pct = 0.0
            d.descuento_monto = 0.0
            d.promo_aplicada = None

    if not promos_vigentes:
        return

    mapa_cat = _mapa_categorias_productos()
    items_reales = [d for d in c.detalles if not d.es_modificador and d.precio_unitario > 0]

    for pr in promos_vigentes:
        objetivo = (pr.objetivo or '').strip().upper()
        coincidentes = []
        for d in items_reales:
            if d.descuento_pct > 0 and not d.promo_aplicada:
                continue  # Tiene descuento manual de gerente, no sobreescribir
            nom = d.descripcion.strip().upper()
            cat = mapa_cat.get(nom, '')
            if (pr.aplica_a == 'PRODUCTO' and nom == objetivo) or (pr.aplica_a == 'CATEGORIA' and cat == objetivo):
                coincidentes.append(d)

        if not coincidentes:
            continue

        if pr.tipo == 'DESCUENTO_PCT':
            for d in coincidentes:
                d.descuento_pct = max(0.0, min(100.0, float(pr.valor or 0)))
                d.promo_aplicada = pr.nombre
        elif pr.tipo == 'PRECIO_FIJO':
            for d in coincidentes:
                if d.precio_unitario > pr.valor:
                    desc_u = round(d.precio_unitario - pr.valor, 2)
                    d.descuento_pct = 0.0
                    d.descuento_monto = round(desc_u * d.cantidad, 2)
                    d.promo_aplicada = pr.nombre
        elif pr.tipo == 'VOLUMEN_2X1':
            por_cada = max(2, int(pr.por_cada or 2))
            regala = max(1, int(pr.regala or 1))
            total_u = int(sum(d.cantidad for d in coincidentes))
            gratis = (total_u // por_cada) * regala
            if gratis > 0:
                coincidentes.sort(key=lambda x: x.precio_unitario)
                restantes = gratis
                for d in coincidentes:
                    if restantes <= 0:
                        break
                    aplica_u = min(int(d.cantidad), restantes)
                    d.descuento_pct = 0.0
                    d.descuento_monto = round((d.descuento_monto or 0.0) + (aplica_u * d.precio_unitario), 2)
                    d.promo_aplicada = pr.nombre
                    restantes -= aplica_u


def recalcular_totales_cuenta(c):
    if not c.es_subcuenta_parte:
        aplicar_promociones_cuenta(c)

    bruto_cuenta = 0.0
    for d in c.detalles:
        bruto_item = round(float(d.cantidad or 0) * float(d.precio_unitario or 0), 2)
        if (d.descuento_pct or 0) > 0:
            d.descuento_monto = round(bruto_item * (d.descuento_pct / 100.0), 2)
        elif not d.promo_aplicada:
            d.descuento_monto = round(float(d.descuento_monto or 0.0), 2)
        d.importe = round(max(0.0, bruto_item - (d.descuento_monto or 0.0)), 2)
        bruto_cuenta += d.importe

    desc_gral = round(bruto_cuenta * ((c.descuento_pct or 0.0) / 100.0), 2)
    c.descuento_monto = desc_gral
    c.total = round(max(0.0, bruto_cuenta - desc_gral), 2)
    c.subtotal = round(c.total / 1.16, 2)
    c.iva = round(c.total - c.subtotal, 2)


def sumar_stock_sucursal(sucursal, insumo_id, cantidad):
    """Suma mercancía recibida al stock local de la sucursal (Opción A)."""
    if not insumo_id or not cantidad:
        return
    st = StockSucursal.query.filter_by(sucursal=sucursal, insumo_id=insumo_id).first()
    if not st:
        st = StockSucursal(sucursal=sucursal, insumo_id=insumo_id, stock_actual=0.0, stock_minimo=2.0)
        db.session.add(st)
    st.stock_actual = round(max(0.0, st.stock_actual + float(cantidad)), 3)


def descontar_recetas_local(cuenta_obj):
    """Descuenta recetas de platillos y modificadores del stock local de la sucursal una sola vez."""
    if not cuenta_obj or cuenta_obj.recetas_descontadas:
        return
    # Si es subcuenta de partes iguales, descontar usando la cuenta padre que tiene los platillos reales
    if cuenta_obj.es_subcuenta_parte and cuenta_obj.parent_cuenta_id:
        padre = CuentaPOS.query.get(cuenta_obj.parent_cuenta_id)
        if padre and not padre.recetas_descontadas:
            descontar_recetas_local(padre)
        cuenta_obj.recetas_descontadas = True
        return

    recetas = RecetaPOS.query.all()
    if not recetas:
        cuenta_obj.recetas_descontadas = True
        return

    mapa_recetas = {}
    for r in recetas:
        key = r.platillo_nombre.strip().upper()
        mapa_recetas.setdefault(key, []).append(r)

    suc = cuenta_obj.sucursal or 'Quiosco Morisco (Matriz)'
    for det in cuenta_obj.detalles:
        desc_raw = det.descripcion.strip().upper()
        desc_sin_gt = desc_raw.lstrip('>').strip()
        recs = mapa_recetas.get(desc_raw) or mapa_recetas.get(desc_sin_gt) or []
        for r in recs:
            st = StockSucursal.query.filter_by(sucursal=suc, insumo_id=r.insumo_id).first()
            if not st:
                st = StockSucursal(sucursal=suc, insumo_id=r.insumo_id, stock_actual=0.0, stock_minimo=2.0)
                db.session.add(st)
            st.stock_actual = round(max(0.0, st.stock_actual - (r.cantidad_descontar * det.cantidad)), 3)

    cuenta_obj.recetas_descontadas = True


# ==============================================================================
# INICIALIZACIÓN ÚNICA Y AUTO-MIGRACIÓN SEGURA PARA NEONDB
# ==============================================================================
def inicializar_sistema(app_obj):
    with app_obj.app_context():
        db.create_all()

        migraciones = [
            'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT \'Quiosco Morisco (Matriz)\';',
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
            "ALTER TABLE pre_orden ADD COLUMN IF NOT EXISTS atendido_por VARCHAR(80);",
            "ALTER TABLE turnos_pos ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS parent_cuenta_id INTEGER;",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS es_subcuenta_parte BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS pago_transferencia DOUBLE PRECISION DEFAULT 0.0;",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS tarjeta_ultimos4 VARCHAR(10) DEFAULT '';",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS recetas_descontadas BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE detalles_pos ADD COLUMN IF NOT EXISTS parent_detalle_id INTEGER;",
            "ALTER TABLE detalles_pos ADD COLUMN IF NOT EXISTS descuento_pct DOUBLE PRECISION DEFAULT 0.0;",
            "ALTER TABLE detalles_pos ADD COLUMN IF NOT EXISTS descuento_monto DOUBLE PRECISION DEFAULT 0.0;",
            "ALTER TABLE detalles_pos ADD COLUMN IF NOT EXISTS promo_aplicada VARCHAR(100);",
            "ALTER TABLE cola_impresion_pos ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE bitacora_pos ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE arqueos_turno_pos ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE arqueos_turno_pos ADD COLUMN IF NOT EXISTS trans_declarado DOUBLE PRECISION DEFAULT 0.0;",
            "ALTER TABLE modificadores_pos ADD COLUMN IF NOT EXISTS grupo VARCHAR(50) DEFAULT 'SABORES';",
            "ALTER TABLE requerimientos_bodega ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE requerimientos_bodega ADD COLUMN IF NOT EXISTS cantidad_entregada DOUBLE PRECISION;"
        ]
        for sql in migraciones:
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

        indices = [
            "CREATE INDEX IF NOT EXISTS idx_cuentas_pos_suc_est ON cuentas_pos (sucursal, estado);",
            "CREATE INDEX IF NOT EXISTS idx_cuentas_pos_cierre_est ON cuentas_pos (cierre, estado);",
            "CREATE INDEX IF NOT EXISTS idx_cuentas_pos_turno_est ON cuentas_pos (turno_id, estado);",
            "CREATE INDEX IF NOT EXISTS idx_cuentas_pos_parent ON cuentas_pos (parent_cuenta_id);",
            "CREATE INDEX IF NOT EXISTS idx_detalles_pos_cta_imp ON detalles_pos (cuenta_id, impreso_comanda);",
            "CREATE INDEX IF NOT EXISTS idx_detalles_pos_parent ON detalles_pos (parent_detalle_id);",
            "CREATE INDEX IF NOT EXISTS idx_cola_imp_suc_imp ON cola_impresion_pos (sucursal, impreso);",
            "CREATE INDEX IF NOT EXISTS idx_pre_orden_estado_fecha ON pre_orden (estado, fecha);",
            "CREATE INDEX IF NOT EXISTS idx_bitacora_fecha_accion ON bitacora_pos (fecha, accion);",
            "CREATE INDEX IF NOT EXISTS idx_bitacora_suc ON bitacora_pos (sucursal);",
            "CREATE INDEX IF NOT EXISTS idx_req_bodega_fecha_suc ON requerimientos_bodega (fecha, sucursal);",
            "CREATE INDEX IF NOT EXISTS idx_turnos_pos_suc_est ON turnos_pos (sucursal, estado);",
            "CREATE INDEX IF NOT EXISTS idx_pin_caja_activo ON pin_caja (activo);",
            "CREATE INDEX IF NOT EXISTS idx_producto_cat_agot ON producto (categoria, agotado);",
            "CREATE INDEX IF NOT EXISTS idx_stock_suc_suc_ins ON stock_sucursal (sucursal, insumo_id);",
            "CREATE INDEX IF NOT EXISTS idx_consumo_emp_desc ON consumos_empleados_pos (descontado, empleado_id);"
        ]
        for sql in indices:
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

        if not ConfigPermisosPOS.query.first():
            db.session.add(ConfigPermisosPOS())
            db.session.commit()

        cuentas_equipo = [
            ('raquel', 'raquel2026', 'admin', 'Quiosco Morisco (Matriz)'),
            ('almacen', 'almacen123', 'almacen', 'Quiosco Morisco (Matriz)'),
            ('quiosco', 'quiosco123', 'sucursal', 'Quiosco Morisco (Matriz)'),
            ('caminante1', 'caminante1123', 'sucursal', 'Caminante 1'),
            ('caminante2', 'caminante2123', 'sucursal', 'Caminante 2'),
            ('caminante3', 'caminante3123', 'sucursal', 'Caminante 3'),
            ('brayan', 'brayan123', 'cajero', 'Quiosco Morisco (Matriz)'),
            ('emili', 'emili123', 'cajero', 'Quiosco Morisco (Matriz)'),
            ('paola', 'paola123', 'mesero', 'Quiosco Morisco (Matriz)'),
            ('daniel', 'daniel123', 'mesero', 'Quiosco Morisco (Matriz)')
        ]
        try:
            for usr, pwd, rol, suc in cuentas_equipo:
                existente = User.query.filter_by(username=usr).first()
                if not existente:
                    db.session.add(User(username=usr, password=generate_password_hash(pwd), role=rol, sucursal=suc))
                elif not existente.sucursal:
                    existente.sucursal = suc
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Sembrar modificadores base solo si está vacío
        if ModificadorPOS.query.count() == 0:
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
                db.session.add(ModificadorPOS(clave=clv, grupo=grp, nombre=nom, precio=pre, activo=True))
            db.session.commit()

        # Sembrar empleados de nómina solo si está vacío
        if EmpleadoNominaPOS.query.count() == 0:
            base_emp = [
                ('PAOLA', 'MESERO', 1500.0, 'SEMANAL'),
                ('DANIEL', 'MESERO', 1500.0, 'SEMANAL'),
                ('BRAYAN', 'CAJERO / BARISTA', 1800.0, 'SEMANAL'),
                ('EMILI', 'CAJERO', 1600.0, 'SEMANAL')
            ]
            for nom, pue, sue, per in base_emp:
                db.session.add(EmpleadoNominaPOS(nombre=nom, puesto=pue, sueldo_base=sue, periodo=per, activo=True))
            db.session.commit()