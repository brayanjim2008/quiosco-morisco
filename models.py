from datetime import datetime, timedelta, timezone
import os
import secrets
import string
import threading
import time
import zlib
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, current_user
from sqlalchemy import text, event
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


# ------------------------------------------------------------------------------
# Caché en memoria por worker + versión compartida en PostgreSQL (config_pos.version_cache_publico).
# invalidar_cache_publico() sube la versión; cada worker la revisa como máximo cada CACHE_REVISION_SEG
# y, si cambió, vacía su caché. Así un platillo agotado se ve en ~3 s en TODOS los workers (antes hasta 45 s).
# Las lecturas/escrituras de la versión usan su propia conexión: no tocan la transacción de la ruta.
# ------------------------------------------------------------------------------
CACHE_REVISION_SEG = 3
CLAVE_VERSION_CACHE = 'version_cache_publico'
_CACHE_VERSION = {'local': None, 'revisado': 0.0}


def _log_aviso(msg, *args):
    try:
        from flask import current_app
        current_app.logger.warning(msg, *args)
    except Exception:
        import logging
        logging.getLogger('comensal').warning(msg, *args)


def _leer_version_cache():
    with db.engine.connect() as conn:
        v = conn.execute(text("SELECT valor_json FROM config_pos WHERE clave = :c"), {'c': CLAVE_VERSION_CACHE}).scalar()
    return str(v) if v is not None else '0'


def _sincronizar_version_cache():
    """Si otro worker invalidó la caché (subió la versión), vacía la caché local. Falla abierta."""
    ahora = time.monotonic()
    with _CACHE_LOCK:
        if ahora - _CACHE_VERSION['revisado'] < CACHE_REVISION_SEG:
            return
        _CACHE_VERSION['revisado'] = ahora
    try:
        version = _leer_version_cache()
    except Exception as e:
        _log_aviso('No se pudo leer la versión de caché (se sigue con la caché local): %s', e)
        return
    with _CACHE_LOCK:
        if _CACHE_VERSION['local'] is not None and version != _CACHE_VERSION['local']:
            _CACHE_STORE.clear()
        _CACHE_VERSION['local'] = version


def cache_get(clave, ttl_segundos):
    _sincronizar_version_cache()
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
    """Vacía la caché de este worker y sube la versión compartida para que los demás la vacíen.
    Llamar DESPUÉS del commit de la ruta (si no, otro worker podría recargar datos viejos)."""
    with _CACHE_LOCK:
        _CACHE_STORE.clear()
    try:
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO config_pos (clave, valor_json) VALUES (:c, '1') "
                "ON CONFLICT (clave) DO UPDATE SET valor_json = "
                "CAST(CAST(config_pos.valor_json AS INTEGER) + 1 AS VARCHAR(20))"
            ), {'c': CLAVE_VERSION_CACHE})
        version = _leer_version_cache()
        with _CACHE_LOCK:
            _CACHE_VERSION['local'] = version
            _CACHE_VERSION['revisado'] = time.monotonic()
    except Exception as e:
        _log_aviso('No se pudo publicar la invalidación de caché (los otros workers tardarán hasta su TTL): %s', e)

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

DATOS_TICKET_SUCURSAL = {
    'Quiosco Morisco (Matriz)': {
        'nombre_comercial': 'QUIOSCO MORISCO BISTRO',
        'razon_social': 'RAQUEL ABIGAIL BERMUDEZ GARCIA',
        'rfc': 'BEGR020115TD5',
        'direccion': 'CALLE GUADALUPE VICTORIA, SIN NUM. COL. CENTRO',
        'ciudad': 'SAN CRISTOBAL DE LAS CASAS CHIAPAS MEXICO CP 29200',
        'telefono': '9671802660',
        'wifi_red': 'QuioscoMoriscoB',
        'wifi_clave': 'Corazonsc31'
    },
    'Caminante 1': {
        'nombre_comercial': 'CAMINANTE 1',
        'razon_social': 'RAQUEL ABIGAIL BERMUDEZ GARCIA',
        'rfc': 'BEGR020115TD5',
        'direccion': 'COL. CENTRO',
        'ciudad': 'SAN CRISTOBAL DE LAS CASAS CHIAPAS MEXICO CP 29200',
        'telefono': '9671802660',
        'wifi_red': 'Caminante1',
        'wifi_clave': 'Corazonsc31'
    },
    'Caminante 2': {
        'nombre_comercial': 'CAMINANTE 2',
        'razon_social': 'RAQUEL ABIGAIL BERMUDEZ GARCIA',
        'rfc': 'BEGR020115TD5',
        'direccion': 'COL. CENTRO',
        'ciudad': 'SAN CRISTOBAL DE LAS CASAS CHIAPAS MEXICO CP 29200',
        'telefono': '9671802660',
        'wifi_red': 'Caminante2',
        'wifi_clave': 'Corazonsc31'
    },
    'Caminante 3': {
        'nombre_comercial': 'CAMINANTE 3',
        'razon_social': 'RAQUEL ABIGAIL BERMUDEZ GARCIA',
        'rfc': 'BEGR020115TD5',
        'direccion': 'COL. CENTRO',
        'ciudad': 'SAN CRISTOBAL DE LAS CASAS CHIAPAS MEXICO CP 29200',
        'telefono': '9671802660',
        'wifi_red': 'Caminante3',
        'wifi_clave': 'Corazonsc31'
    }
}


_CARACTERES_HTML = str.maketrans('', '', '<>"\'`')


def quitar_caracteres_html(valor):
    """Quita < > " ' ` (con ellos se arma HTML/JS). Se usa para el texto que escribe el público y para
    comparar ese texto contra el catálogo con la misma limpieza."""
    return str(valor or '').translate(_CARACTERES_HTML)


CLAVE_CFG_DATOS_TICKET = 'datos_ticket_sucursal'
CAMPOS_DATOS_TICKET = {  # campo -> largo máximo
    'nombre_comercial': 80, 'razon_social': 120, 'rfc': 13, 'direccion': 150, 'ciudad': 120,
    'telefono': 20, 'wifi_red': 32, 'wifi_clave': 63,
}


def _datos_ticket_editados():
    """Lo que el admin editó desde el panel (config_pos), con caché que se invalida al guardar."""
    cache = cache_get('datos_ticket_bd', 60)
    if cache is not None:
        return cache
    try:
        datos = cfg_cargar(CLAVE_CFG_DATOS_TICKET, {})
    except Exception:
        datos = {}
    return cache_set('datos_ticket_bd', datos if isinstance(datos, dict) else {})


def obtener_datos_ticket(sucursal):
    """Datos fiscales y Wi-Fi de la sucursal: valores base del código + lo editado por el admin."""
    base = dict(DATOS_TICKET_SUCURSAL.get(sucursal, DATOS_TICKET_SUCURSAL[SUCURSAL_DEFAULT_TICKET]))
    editados = _datos_ticket_editados().get(sucursal) or {}
    for campo in CAMPOS_DATOS_TICKET:
        valor = editados.get(campo)
        if isinstance(valor, str) and valor.strip():
            base[campo] = valor.strip()
    return base


SUCURSAL_DEFAULT_TICKET = 'Quiosco Morisco (Matriz)'


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
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')


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
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')


# ==============================================================================
# MODELOS COMENSAL CONECTADO (POS MULTI-SUCURSAL)
# ==============================================================================
class ConfigPermisosPOS(db.Model):
    __tablename__ = 'config_permisos_pos'
    id = db.Column(db.Integer, primary_key=True)
    cajero_puede_cancelar = db.Column(db.Boolean, default=False)
    cajero_puede_descontar = db.Column(db.Boolean, default=False)
    cajero_puede_cambiar_pago = db.Column(db.Boolean, default=False)
    cajero_puede_reimprimir = db.Column(db.Boolean, default=False)
    cajero_puede_retirar = db.Column(db.Boolean, default=False)
    cajero_ver_esperado_z = db.Column(db.Boolean, default=False)


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
    categoria_gasto = db.Column(db.String(60), nullable=True)  # solo RETIRO: catálogo de gastos operativos


CLAVE_CFG_CATALOGO_GASTOS = 'catalogo_gastos'
CATALOGO_GASTOS_DEFAULT = ['HIELO', 'GAS', 'AGUA / GARRAFONES', 'LIMPIEZA', 'COMPRA URGENTE DE INSUMOS',
                           'MANTENIMIENTO', 'PAPELERIA', 'TRANSPORTE / ENVIOS', 'PAGO A PROVEEDOR', 'OTROS']

# Arqueo por denominaciones (pesos mexicanos). Clave -> valor; B = billete, M = moneda.
DENOMINACIONES_MXN = [('B1000', 1000.0), ('B500', 500.0), ('B200', 200.0), ('B100', 100.0), ('B50', 50.0),
                      ('B20', 20.0), ('M20', 20.0), ('M10', 10.0), ('M5', 5.0), ('M2', 2.0), ('M1', 1.0),
                      ('M050', 0.5)]


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
    pago_credito = db.Column(db.Float, default=0.0)  # Fiado a cliente de crédito
    cliente_credito_id = db.Column(db.Integer, nullable=True)
    tarjeta_ultimos4 = db.Column(db.String(10), default='')
    propina_tarjeta = db.Column(db.Float, default=0.0)
    cambio = db.Column(db.Float, default=0.0)

    recetas_descontadas = db.Column(db.Boolean, default=False)
    estado = db.Column(db.String(20), default='ABIERTA')  # ABIERTA | PAGADA | DIVIDIDA | COMBINADA | CANCELADA
    descuento_fijo = db.Column(db.Float, default=0.0)  # descuento general en pesos (excluyente con descuento_pct)
    cobro_idem = db.Column(db.String(64), nullable=True)  # llave de idempotencia del cobro (reintentos por red)
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
    # Monitor de cocina/barra (KDS)
    enviado_en = db.Column(db.DateTime, nullable=True)        # cuándo se mandó a cocina/barra
    kds_estado = db.Column(db.String(12), default='PENDIENTE')  # PENDIENTE | PREPARANDO | LISTO | ENTREGADO
    kds_listo_en = db.Column(db.DateTime, nullable=True)


@event.listens_for(DetallePOS.impreso_comanda, 'set')
def _marcar_envio_cocina(target, value, oldvalue, initiator):
    """Registra la hora en que el platillo se manda a cocina/barra (alimenta el KDS) sin tocar cada ruta de envío.
    Si quien crea el detalle pasa enviado_en explícito (p. ej. al dividir una cuenta), ese valor prevalece."""
    if value and target.enviado_en is None:
        target.enviado_en = ahora_local()


class Reservacion(db.Model):
    """Reservación ligada a una mesa: al llegar el cliente se abre (o liga) la cuenta de esa mesa."""
    __tablename__ = 'reservaciones'
    id = db.Column(db.Integer, primary_key=True)
    sucursal = db.Column(db.String(100), nullable=False)
    fecha_hora = db.Column(db.DateTime, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20), default='')
    personas = db.Column(db.Integer, default=2)
    mesa = db.Column(db.String(25), nullable=True)
    notas = db.Column(db.String(250), default='')
    estado = db.Column(db.String(15), default='PENDIENTE')  # PENDIENTE | CONFIRMADA | LLEGO | NO_LLEGO | CANCELADA
    creado_por = db.Column(db.String(80), nullable=False)
    creado_en = db.Column(db.DateTime, default=ahora_local)
    cuenta_id = db.Column(db.Integer, nullable=True)


class ColaImpresionPOS(db.Model):
    __tablename__ = 'cola_impresion_pos'
    id = db.Column(db.Integer, primary_key=True)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')
    tipo = db.Column(db.String(30), nullable=False)
    contenido_html = db.Column(db.Text, nullable=False)
    impreso = db.Column(db.Boolean, default=False)  # se conserva para la limpieza de >7 días y compatibilidad
    fecha = db.Column(db.DateTime, default=ahora_local)
    # PENDIENTE -> EN_PROCESO (una PC lo reclamó) -> IMPRESO (esa PC confirmó con ACK).
    # Si no llega el ACK en COLA_REINTENTO_SEG, otra PC puede reclamarlo: mejor reimprimir que perder una comanda.
    estado = db.Column(db.String(15), default='PENDIENTE')
    reclamado_en = db.Column(db.DateTime, nullable=True)
    reclamado_por = db.Column(db.String(60), nullable=True)


COLA_REINTENTO_SEG = 150


class ModificadorPOS(db.Model):
    __tablename__ = 'modificadores_pos'
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(20), nullable=False, default='03001')
    grupo = db.Column(db.String(50), nullable=False, default='SABORES')
    nombre = db.Column(db.String(100), nullable=False)
    precio = db.Column(db.Float, default=0.0)
    area_impresion = db.Column(db.String(20), nullable=True)  # None = hereda del platillo; 'BARRA' o 'COCINA' fuerza área
    activo = db.Column(db.Boolean, default=True)


class ProductoGrupoMod(db.Model):
    __tablename__ = 'producto_grupo_mod'
    id = db.Column(db.Integer, primary_key=True)
    platillo_nombre = db.Column(db.String(150), nullable=False)
    grupo = db.Column(db.String(50), nullable=False)
    etiqueta = db.Column(db.String(80), nullable=False)
    orden = db.Column(db.Integer, default=1)
    obligatorio = db.Column(db.Boolean, default=True)
    max_seleccion = db.Column(db.Integer, default=1)  # 1 = opción única con avance automático; 0 = múltiple


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
    denominaciones_json = db.Column(db.Text, nullable=True)  # {"B500": 3, "M10": 7, ...} si se contó por denominación


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
    activo = db.Column(db.Boolean, default=True)


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
    cantidad_recibida = db.Column(db.Float, nullable=True)
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
    dias_base = db.Column(db.Integer, default=6)
    pin_checador = db.Column(db.String(12), nullable=True)
    descuento_pct = db.Column(db.Float, default=0.0)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')  # sucursal principal


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
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')  # donde se registró el vale


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
    dias_base = db.Column(db.Integer, default=6)
    dias_trabajados = db.Column(db.Float, default=6.0)
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')  # sucursal principal del empleado


class ClienteCredito(db.Model):
    """Cliente con cuenta de crédito / fiado."""
    __tablename__ = 'clientes_credito'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(40), default='')
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')
    limite_credito = db.Column(db.Float, default=0.0)  # 0 = sin límite
    saldo_pendiente = db.Column(db.Float, default=0.0)
    activo = db.Column(db.Boolean, default=True)
    creado = db.Column(db.DateTime, default=ahora_local)


class MovimientoCredito(db.Model):
    __tablename__ = 'movimientos_credito'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes_credito.id'), nullable=False)
    cliente_nombre = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # CARGO | ABONO
    monto = db.Column(db.Float, nullable=False)
    concepto = db.Column(db.String(200), default='')
    cuenta_id = db.Column(db.Integer, nullable=True)
    usuario = db.Column(db.String(80), default='')
    sucursal = db.Column(db.String(100), default='Quiosco Morisco (Matriz)')


class TraspasoSucursal(db.Model):
    """Traspaso directo de insumos entre sucursales (sin pasar por Bodega Central).
    ENVIADO: el origen ya descontó su stock. RECIBIDO: el destino sumó lo recibido; lo que faltó regresa al origen.
    RECHAZADO: todo regresa al origen."""
    __tablename__ = 'traspasos_sucursal'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
    origen = db.Column(db.String(100), nullable=False)
    destino = db.Column(db.String(100), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey('insumos_bodega_pro.id'), nullable=False)
    insumo_nombre = db.Column(db.String(120), nullable=False)
    unidad = db.Column(db.String(20), default='')
    cantidad = db.Column(db.Float, nullable=False)
    cantidad_recibida = db.Column(db.Float, nullable=True)
    estado = db.Column(db.String(15), default='ENVIADO')  # ENVIADO | RECIBIDO | RECHAZADO
    nota = db.Column(db.String(200), default='')
    enviado_por = db.Column(db.String(80), nullable=False)
    recibido_por = db.Column(db.String(80), nullable=True)
    recibido_en = db.Column(db.DateTime, nullable=True)


CONTEO_TOPE_SIN_CLAVE = 500.0  # suma de |valor_diferencia| a partir de la cual se pide clave de Admin/Gerente
CONTEO_BORRADOR_VIEJO_HORAS = 24


class ConteoInventario(db.Model):
    """Inventario físico: conteo real contra teórico en BODEGA o en una sucursal."""
    __tablename__ = 'conteos_inventario'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_local)
    ubicacion = db.Column(db.String(100), nullable=False)  # 'BODEGA' o nombre de sucursal
    usuario = db.Column(db.String(80), nullable=False)
    estado = db.Column(db.String(15), default='BORRADOR')  # BORRADOR | APLICADO | CANCELADO
    nota = db.Column(db.String(250), default='')
    aplicado_en = db.Column(db.DateTime, nullable=True)
    aplicado_por = db.Column(db.String(80), nullable=True)
    autorizo = db.Column(db.String(80), nullable=True)
    valor_abs_total = db.Column(db.Float, default=0.0)  # Σ |valor_diferencia| al aplicar


class ConteoInventarioDetalle(db.Model):
    __tablename__ = 'conteos_inventario_detalle'
    id = db.Column(db.Integer, primary_key=True)
    conteo_id = db.Column(db.Integer, db.ForeignKey('conteos_inventario.id'), nullable=False, index=True)
    insumo_id = db.Column(db.Integer, nullable=False)
    insumo_nombre = db.Column(db.String(120), nullable=False)
    unidad = db.Column(db.String(20), default='')
    teorico = db.Column(db.Float, default=0.0)       # al iniciar = foto; al aplicar = releído en ese momento
    contado = db.Column(db.Float, nullable=True)      # None = no capturado (se omite, NO se pone en 0)
    diferencia = db.Column(db.Float, nullable=True)
    costo_unitario = db.Column(db.Float, default=0.0)
    valor_diferencia = db.Column(db.Float, nullable=True)


class LimiteIntento(db.Model):
    """Contador de intentos por clave (login:usuario, pin:IP, preorden:IP...) compartido por todos los workers."""
    __tablename__ = 'limites_intentos'
    clave = db.Column(db.String(200), primary_key=True)
    conteo = db.Column(db.Integer, nullable=False, default=0)
    ventana_inicio = db.Column(db.DateTime, nullable=False, default=ahora_local)


class ConfigPOS(db.Model):
    """Configuración en base de datos (reemplaza los .json locales, que se pierden en cada deploy de Render)."""
    __tablename__ = 'config_pos'
    clave = db.Column(db.String(80), primary_key=True)
    valor_json = db.Column(db.Text, nullable=False, default='null')


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


SUCURSAL_POR_PREFIJO = {v: k for k, v in PREFIJO_SUCURSAL.items()}  # 'C1' -> 'Caminante 1'
SUCURSAL_DEFAULT = 'Quiosco Morisco (Matriz)'


def sucursal_desde_codigo(codigo):
    """Código corto de los QR/NFC de mesa (?suc=QM|C1|C2|C3). Sin código o inválido -> Matriz,
    así los QR/NFC ya instalados (sin ?suc=) siguen llegando a Quiosco Morisco."""
    return SUCURSAL_POR_PREFIJO.get(str(codigo or '').strip().upper(), SUCURSAL_DEFAULT)


def sucursal_filtro(session_obj=None):
    """None = el admin ve todas las sucursales; cualquier otro rol solo ve su sucursal activa."""
    if current_user.is_authenticated and current_user.role == 'admin':
        return None
    return obtener_sucursal_activa(session_obj)




def cfg_cargar(clave, default, archivo_legado=None):
    """Lee config desde PostgreSQL (tabla config_pos). Si aún no se ha guardado nada, usa el .json local
    heredado (si existe) o el valor por defecto. No escribe: solo cfg_guardar escribe."""
    import json as _j
    try:
        fila = ConfigPOS.query.get(clave)
        if fila is not None:
            return _j.loads(fila.valor_json)
    except Exception:
        db.session.rollback()
    if archivo_legado:
        try:
            import os as _os
            if _os.path.exists(archivo_legado):
                with open(archivo_legado, 'r', encoding='utf-8') as fh:
                    return _j.load(fh)
        except Exception:
            pass
    return _j.loads(_j.dumps(default))


def cfg_guardar(clave, valor):
    import json as _j
    fila = ConfigPOS.query.get(clave)
    txt = _j.dumps(valor, ensure_ascii=False)
    if fila is None:
        db.session.add(ConfigPOS(clave=clave, valor_json=txt))
    else:
        fila.valor_json = txt
    db.session.commit()


# ------------------------------------------------------------------------------
# Límite de intentos compartido por todos los workers (tabla limites_intentos, ventana fija por clave).
# - Las escrituras usan su PROPIA conexión (db.engine.begin()): un db.session.rollback() de la ruta no borra
#   el intento fallido, y registrar un intento no hace commit de la transacción de la ruta.
# - Si la base falla, se "falla abierto" (se deja pasar y se avisa en el log) para no tumbar el menú público.
# ------------------------------------------------------------------------------
LIMPIEZA_INTENTOS_CADA = 200          # ~1 de cada 200 escrituras borra registros vencidos
LIMPIEZA_INTENTOS_VIGENCIA_SEG = 3600  # mayor que la ventana más larga en uso (600 s)


def limite_intentos_excedido(clave, max_intentos=5, ventana_seg=300):
    """True si esa clave (usuario/IP) acumuló max_intentos dentro de su ventana actual."""
    try:
        with db.engine.connect() as conn:
            fila = conn.execute(text(
                "SELECT conteo, ventana_inicio FROM limites_intentos WHERE clave = :c"
            ), {'c': str(clave)[:200]}).first()
    except Exception as e:
        _log_aviso('Límite de intentos no disponible (se deja pasar): %s', e)
        return False
    if not fila:
        return False
    conteo, inicio = fila[0], fila[1]
    if isinstance(inicio, str):  # SQLite devuelve texto con conexiones crudas
        inicio = datetime.fromisoformat(inicio)
    if inicio is None or inicio < ahora_local() - timedelta(seconds=ventana_seg):
        return False  # la ventana ya venció
    return int(conteo or 0) >= max_intentos


def registrar_intento_fallido(clave, ventana_seg=300):
    """Suma 1 intento (atómico con ON CONFLICT). Si la ventana de esa clave ya venció, reinicia en 1."""
    ahora = ahora_local()
    corte = ahora - timedelta(seconds=ventana_seg)
    try:
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO limites_intentos (clave, conteo, ventana_inicio) VALUES (:c, 1, :ahora) "
                "ON CONFLICT (clave) DO UPDATE SET "
                "conteo = CASE WHEN limites_intentos.ventana_inicio < :corte THEN 1 ELSE limites_intentos.conteo + 1 END, "
                "ventana_inicio = CASE WHEN limites_intentos.ventana_inicio < :corte THEN :ahora ELSE limites_intentos.ventana_inicio END"
            ), {'c': str(clave)[:200], 'ahora': ahora, 'corte': corte})
            if secrets.randbelow(LIMPIEZA_INTENTOS_CADA) == 0:
                conn.execute(text("DELETE FROM limites_intentos WHERE ventana_inicio < :viejo"),
                             {'viejo': ahora - timedelta(seconds=LIMPIEZA_INTENTOS_VIGENCIA_SEG)})
    except Exception as e:
        _log_aviso('No se pudo registrar el intento de %s: %s', clave, e)


def limpiar_intentos(clave):
    try:
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM limites_intentos WHERE clave = :c"), {'c': str(clave)[:200]})
    except Exception as e:
        _log_aviso('No se pudo limpiar los intentos de %s: %s', clave, e)


def validar_clave_admin(clave_ingresada):
    """Autoriza operaciones sensibles con la contraseña de cualquier Admin o Gerente."""
    clave = str(clave_ingresada or '').strip()
    if not clave:
        return None
    id_rl = f"adminkey:{getattr(current_user, 'id', 'anon')}"
    if limite_intentos_excedido(id_rl, 5, 300):
        return None  # bloqueado temporalmente por demasiados intentos fallidos
    for auth_u in User.query.filter(User.role.in_(['admin', 'gerente'])).all():
        if check_password_hash(auth_u.password, clave):
            limpiar_intentos(id_rl)
            return f"{auth_u.username.upper()} ({auth_u.role.upper()})"
    registrar_intento_fallido(id_rl)
    return None


def numero_a_letras_mxn(monto):
    monto = round(float(monto or 0.0), 2)
    entero = int(monto)
    centavos = int(round((monto - entero) * 100))
    if centavos == 100:
        entero += 1
        centavos = 0

    unidades = ['', 'UN', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE']
    especiales = {
        10: 'DIEZ', 11: 'ONCE', 12: 'DOCE', 13: 'TRECE', 14: 'CATORCE', 15: 'QUINCE',
        16: 'DIECISEIS', 17: 'DIECISIETE', 18: 'DIECIOCHO', 19: 'DIECINUEVE',
        20: 'VEINTE', 21: 'VEINTIUN', 22: 'VEINTIDOS', 23: 'VEINTITRES', 24: 'VEINTICUATRO',
        25: 'VEINTICINCO', 26: 'VEINTISEIS', 27: 'VEINTISIETE', 28: 'VEINTIOCHO', 29: 'VEINTINUEVE'
    }
    decenas = ['', '', '', 'TREINTA', 'CUARENTA', 'CINCUENTA', 'SESENTA', 'SETENTA', 'OCHENTA', 'NOVENTA']
    centenas = ['', 'CIENTO', 'DOSCIENTOS', 'TRESCIENTOS', 'CUATROCIENTOS', 'QUINIENTOS',
                'SEISCIENTOS', 'SETECIENTOS', 'OCHOCIENTOS', 'NOVECIENTOS']

    def _menor_1000(n):
        if n == 0:
            return ''
        if n == 100:
            return 'CIEN'
        c, r = divmod(n, 100)
        partes = []
        if c > 0:
            partes.append(centenas[c])
        if r > 0:
            if r < 10:
                partes.append(unidades[r])
            elif r < 30:
                partes.append(especiales[r])
            else:
                d, u = divmod(r, 10)
                partes.append(f"{decenas[d]} Y {unidades[u]}" if u else decenas[d])
        return ' '.join(partes)

    if entero == 0:
        texto = 'CERO'
    else:
        millones, resto = divmod(entero, 1_000_000)
        miles, unidades_mil = divmod(resto, 1000)
        partes = []
        if millones == 1:
            partes.append('UN MILLON')
        elif millones > 1:
            partes.append(f"{_menor_1000(millones)} MILLONES")
        if miles == 1:
            partes.append('MIL')
        elif miles > 1:
            partes.append(f"{_menor_1000(miles)} MIL")
        if unidades_mil > 0:
            partes.append(_menor_1000(unidades_mil))
        texto = ' '.join(partes)

    moneda = 'PESO' if entero == 1 else 'PESOS'
    return f"SON: {texto} {moneda} {centavos:02d}/100 M.N." 


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
    """Genera PIN numérico único; salta a 6 dígitos automáticamente para evitar saturación a largo plazo."""
    if PinCaja.query.count() < 6000:
        for _ in range(25):
            cod = ''.join(secrets.choice(string.digits) for _ in range(4))
            if not PinCaja.query.filter_by(codigo=cod).first():
                return cod
    while True:
        cod = ''.join(secrets.choice(string.digits) for _ in range(6))
        if not PinCaja.query.filter_by(codigo=cod).first():
            return cod


def detectar_area_impresion(categoria_nombre):
    cat = (categoria_nombre or '').lower()
    palabras_barra = [
        'caliente', 'fría', 'fria', 'frapp', 'infus', 'jugo',
        'refresco', 'agua', 'postre', 'cerveza', 'coctel', 'cóctel', 'vino',
        'café', 'cafe', 'bebida', 'barra', 'fruta', 'té', 'te refill'
    ]
    for p in palabras_barra:
        if p in cat:
            return 'BARRA'
    return 'COCINA'


def obtener_turno_activo(sucursal='Quiosco Morisco (Matriz)'):
    t = TurnoPOS.query.filter_by(sucursal=sucursal, estado='ABIERTO').order_by(TurnoPOS.id.desc()).first()
    if not t:
        # Dos peticiones a la vez no deben abrir dos turnos: se serializa por sucursal y se vuelve a consultar.
        try:
            if db.engine.dialect.name == 'postgresql':
                db.session.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                                   {'k': zlib.crc32(f'turno:{sucursal}'.encode('utf-8'))})
        except Exception:
            pass
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

    if (c.descuento_pct or 0.0) > 0:
        desc_gral = round(bruto_cuenta * ((c.descuento_pct or 0.0) / 100.0), 2)
    else:
        # Descuento en pesos: nunca mayor que la cuenta (el total no puede quedar negativo).
        desc_gral = round(min(max(0.0, float(c.descuento_fijo or 0.0)), bruto_cuenta), 2)
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
        desc_raw = (det.descripcion or '').strip().upper()
        desc_sin_gt = desc_raw.lstrip('>').strip()
        recs = mapa_recetas.get(desc_raw) or mapa_recetas.get(desc_sin_gt) or []
        for r in recs:
            st = StockSucursal.query.filter_by(sucursal=suc, insumo_id=r.insumo_id).first()
            if not st:
                st = StockSucursal(sucursal=suc, insumo_id=r.insumo_id, stock_actual=0.0, stock_minimo=2.0)
                db.session.add(st)
            st.stock_actual = round(max(0.0, st.stock_actual - (r.cantidad_descontar * det.cantidad)), 3)

    cuenta_obj.recetas_descontadas = True


def buscar_insumo_activo(nombre):
    nombre = str(nombre or '').strip().upper()
    if not nombre:
        return None
    return InsumoBodegaPro.query.filter(
        db.func.upper(InsumoBodegaPro.nombre) == nombre, InsumoBodegaPro.activo.is_not(False)
    ).first()


def aplicar_merma(nombre, cantidad, motivo, sucursal, usuario, unidad='PZA', costo_unitario=0.0, costo_total=None):
    """Registra una merma de forma unificada (POS y Almacén): descuenta stock (sucursal o bodega),
    guarda RegistroMerma (con usuario) y deja el movimiento en MovimientoAlmacen.
    No hace commit: lo hace quien la llama. Devuelve el costo total."""
    nombre = str(nombre or '').strip().upper()
    ins = buscar_insumo_activo(nombre)
    unidad_f = ins.unidad if ins else (str(unidad or 'PZA').strip().upper() or 'PZA')
    costo_u = float(ins.costo_unitario or 0.0) if ins else float(costo_unitario or 0.0)
    costo_tot = round(float(costo_total), 2) if costo_total is not None else round(cantidad * costo_u, 2)
    if ins:
        st = StockSucursal.query.filter_by(sucursal=sucursal, insumo_id=ins.id).first()
        if st:
            st.stock_actual = round(max(0.0, float(st.stock_actual or 0.0) - cantidad), 3)
        else:
            ins.stock_actual = round(max(0.0, float(ins.stock_actual or 0.0) - cantidad), 3)
    nombre_final = ins.nombre if ins else nombre
    db.session.add(RegistroMerma(
        fecha=ahora_local(), sucursal=sucursal, insumo_nombre=nombre_final,
        cantidad=cantidad, unidad=unidad_f, costo_total=costo_tot, motivo=motivo, usuario=usuario
    ))
    db.session.add(MovimientoAlmacen(
        fecha=ahora_local(), tipo='MERMA', insumo_nombre=nombre_final,
        cantidad=cantidad, costo_total=costo_tot, proveedor='',
        usuario=usuario, nota=f'[{sucursal}] {motivo}'
    ))
    return costo_tot


# ==============================================================================
# INICIALIZACIÓN ÚNICA Y AUTO-MIGRACIÓN SEGURA PARA NEONDB
# ==============================================================================
# Tablas y columnas que el código actual necesita. Al arrancar (app.py) se revisa esta lista: si falta algo,
# se corre inicializar_sistema (create_all + ALTER ... IF NOT EXISTS, sin borrar datos).
# Cada fase nueva solo agrega aquí lo suyo.
ESQUEMA_REQUERIDO = {
    'clientes_credito': set(),
    'pre_orden': {'sucursal'},
    'pin_caja': {'sucursal'},
    'empleados_nomina_pos': {'sucursal'},
    'cola_impresion_pos': {'estado', 'reclamado_en', 'reclamado_por'},
    'limites_intentos': {'clave', 'conteo', 'ventana_inicio'},
    'cuentas_pos': {'descuento_fijo', 'cobro_idem'},
    'movimientos_caja_pos': {'categoria_gasto'},
    'arqueos_turno_pos': {'denominaciones_json'},
    'traspasos_sucursal': {'origen', 'destino', 'insumo_id', 'cantidad', 'cantidad_recibida', 'estado'},
    'detalles_pos': {'enviado_en', 'kds_estado', 'kds_listo_en'},
    'reservaciones': {'sucursal', 'fecha_hora', 'mesa', 'estado', 'cuenta_id'},
    'conteos_inventario': {'ubicacion', 'estado', 'aplicado_en', 'autorizo', 'valor_abs_total'},
    'conteos_inventario_detalle': {'conteo_id', 'insumo_id', 'teorico', 'contado', 'diferencia',
                                   'costo_unitario', 'valor_diferencia'},
}


def esquema_faltante(engine):
    """Lista de 'tabla' o 'tabla.columna' de ESQUEMA_REQUERIDO que no existen en la base."""
    from sqlalchemy import inspect as _sa_inspect
    insp = _sa_inspect(engine)
    faltan = []
    for tabla, columnas in ESQUEMA_REQUERIDO.items():
        if not insp.has_table(tabla):
            faltan.append(tabla)
            continue
        existentes = {c['name'] for c in insp.get_columns(tabla)}
        faltan.extend(f'{tabla}.{col}' for col in sorted(columnas - existentes))
    return faltan


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
            "ALTER TABLE modificadores_pos ADD COLUMN IF NOT EXISTS area_impresion VARCHAR(20);",
            "ALTER TABLE config_permisos_pos ADD COLUMN IF NOT EXISTS cajero_puede_reimprimir BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE config_permisos_pos ADD COLUMN IF NOT EXISTS cajero_puede_retirar BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE config_permisos_pos ADD COLUMN IF NOT EXISTS cajero_ver_esperado_z BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE requerimientos_bodega ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE requerimientos_bodega ADD COLUMN IF NOT EXISTS cantidad_entregada DOUBLE PRECISION;",
            "ALTER TABLE requerimientos_bodega ADD COLUMN IF NOT EXISTS cantidad_recibida DOUBLE PRECISION;",
            "ALTER TABLE insumos_bodega_pro ADD COLUMN IF NOT EXISTS activo BOOLEAN DEFAULT TRUE;",
            "UPDATE insumos_bodega_pro SET activo = TRUE WHERE activo IS NULL;",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS pago_credito DOUBLE PRECISION DEFAULT 0.0;",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS cliente_credito_id INTEGER;",
            "ALTER TABLE empleados_nomina_pos ADD COLUMN IF NOT EXISTS dias_base INTEGER DEFAULT 6;",
            "ALTER TABLE empleados_nomina_pos ADD COLUMN IF NOT EXISTS pin_checador VARCHAR(12);",
            "ALTER TABLE empleados_nomina_pos ADD COLUMN IF NOT EXISTS descuento_pct DOUBLE PRECISION DEFAULT 0.0;",
            "ALTER TABLE recibos_nomina_pos ADD COLUMN IF NOT EXISTS dias_base INTEGER DEFAULT 6;",
            "ALTER TABLE recibos_nomina_pos ADD COLUMN IF NOT EXISTS dias_trabajados DOUBLE PRECISION DEFAULT 6.0;",
            # Aislamiento por sucursal (los registros existentes quedan en la Matriz; no se reescribe la tabla).
            "ALTER TABLE pre_orden ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE pin_caja ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE empleados_nomina_pos ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE consumos_empleados_pos ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "ALTER TABLE recibos_nomina_pos ADD COLUMN IF NOT EXISTS sucursal VARCHAR(100) DEFAULT 'Quiosco Morisco (Matriz)';",
            "UPDATE pre_orden SET sucursal = 'Quiosco Morisco (Matriz)' WHERE sucursal IS NULL;",
            "UPDATE pin_caja SET sucursal = 'Quiosco Morisco (Matriz)' WHERE sucursal IS NULL;",
            "UPDATE empleados_nomina_pos SET sucursal = 'Quiosco Morisco (Matriz)' WHERE sucursal IS NULL;",
            "UPDATE consumos_empleados_pos SET sucursal = 'Quiosco Morisco (Matriz)' WHERE sucursal IS NULL;",
            "UPDATE recibos_nomina_pos SET sucursal = 'Quiosco Morisco (Matriz)' WHERE sucursal IS NULL;",
            # Cola de impresión con reclamo + ACK. Los tickets ya impresos quedan IMPRESO para no reimprimirse
            # tras el deploy (las filas existentes reciben el DEFAULT 'PENDIENTE' al agregar la columna).
            "ALTER TABLE cola_impresion_pos ADD COLUMN IF NOT EXISTS estado VARCHAR(15) DEFAULT 'PENDIENTE';",
            "ALTER TABLE cola_impresion_pos ADD COLUMN IF NOT EXISTS reclamado_en TIMESTAMP;",
            "ALTER TABLE cola_impresion_pos ADD COLUMN IF NOT EXISTS reclamado_por VARCHAR(60);",
            "UPDATE cola_impresion_pos SET estado = 'IMPRESO' WHERE impreso = TRUE AND (estado IS NULL OR estado = 'PENDIENTE');",
            "UPDATE cola_impresion_pos SET estado = 'PENDIENTE' WHERE estado IS NULL;",
            # Fase 2: descuento en pesos e idempotencia del cobro
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS descuento_fijo DOUBLE PRECISION DEFAULT 0.0;",
            "ALTER TABLE cuentas_pos ADD COLUMN IF NOT EXISTS cobro_idem VARCHAR(64);",
            # Fase 3: gastos por categoría y arqueo por denominaciones
            "ALTER TABLE movimientos_caja_pos ADD COLUMN IF NOT EXISTS categoria_gasto VARCHAR(60);",
            "ALTER TABLE arqueos_turno_pos ADD COLUMN IF NOT EXISTS denominaciones_json TEXT;",
            # Fase 4a: monitor de cocina/barra (las comandas ya enviadas antes no aparecen: enviado_en queda NULL)
            "ALTER TABLE detalles_pos ADD COLUMN IF NOT EXISTS enviado_en TIMESTAMP;",
            "ALTER TABLE detalles_pos ADD COLUMN IF NOT EXISTS kds_estado VARCHAR(12) DEFAULT 'PENDIENTE';",
            "ALTER TABLE detalles_pos ADD COLUMN IF NOT EXISTS kds_listo_en TIMESTAMP;"
        ]
        es_postgres = db.engine.dialect.name == 'postgresql'
        for sql in migraciones:
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception as e_mig:
                db.session.rollback()
                # En SQLite (pruebas locales) "IF NOT EXISTS" no existe en ALTER: create_all ya creó las columnas.
                if es_postgres:
                    app_obj.logger.warning('Migración falló: %s | %s', sql, e_mig)

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
            "CREATE INDEX IF NOT EXISTS idx_consumo_emp_desc ON consumos_empleados_pos (descontado, empleado_id);",
            "CREATE INDEX IF NOT EXISTS idx_prod_grupo_mod_plat ON producto_grupo_mod (platillo_nombre, orden);",
            "CREATE INDEX IF NOT EXISTS idx_pre_orden_suc_estado ON pre_orden (sucursal, estado);",
            "CREATE INDEX IF NOT EXISTS idx_pin_caja_suc_activo ON pin_caja (sucursal, activo);",
            "CREATE INDEX IF NOT EXISTS idx_empleados_nomina_suc ON empleados_nomina_pos (sucursal, activo);",
            "CREATE INDEX IF NOT EXISTS idx_cola_imp_suc_estado ON cola_impresion_pos (sucursal, estado);",
            "CREATE INDEX IF NOT EXISTS idx_traspasos_destino_estado ON traspasos_sucursal (destino, estado);",
            "CREATE INDEX IF NOT EXISTS idx_traspasos_origen ON traspasos_sucursal (origen, fecha);",
            "CREATE INDEX IF NOT EXISTS idx_mov_caja_tipo_fecha ON movimientos_caja_pos (tipo, fecha);",
            "CREATE INDEX IF NOT EXISTS idx_detalles_pos_enviado ON detalles_pos (enviado_en, kds_estado);",
            "CREATE INDEX IF NOT EXISTS idx_reservaciones_suc_fecha ON reservaciones (sucursal, fecha_hora);"
        ]
        for sql in indices:
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception as e_idx:
                db.session.rollback()
                app_obj.logger.warning('Índice falló: %s | %s', sql, e_idx)

        if not ConfigPermisosPOS.query.first():
            db.session.add(ConfigPermisosPOS())
            db.session.commit()

        cuentas_equipo = [
            ('raquel', None, 'admin', 'Quiosco Morisco (Matriz)'),
            ('gerente', None, 'gerente', 'Quiosco Morisco (Matriz)'),
            ('almacen', None, 'almacen', 'Quiosco Morisco (Matriz)'),
            ('quiosco', None, 'sucursal', 'Quiosco Morisco (Matriz)'),
            ('caminante1', None, 'sucursal', 'Caminante 1'),
            ('caminante2', None, 'sucursal', 'Caminante 2'),
            ('caminante3', None, 'sucursal', 'Caminante 3'),
            ('brayan', None, 'cajero', 'Quiosco Morisco (Matriz)'),
            ('emili', None, 'cajero', 'Quiosco Morisco (Matriz)'),
            ('paola', None, 'mesero', 'Quiosco Morisco (Matriz)'),
            ('daniel', None, 'mesero', 'Quiosco Morisco (Matriz)')
        ]
        try:
            for usr, pwd, rol, suc in cuentas_equipo:
                existente = User.query.filter_by(username=usr).first()
                if not existente:
                    pwd_env = os.environ.get(f"PASS_INICIAL_{usr.upper()}")
                    pwd = pwd_env or secrets.token_urlsafe(9)
                    if pwd_env:
                        print(f"[INICIO] Usuario '{usr}' creado con la clave de PASS_INICIAL_{usr.upper()}.")
                    elif os.environ.get('MOSTRAR_CLAVES_INICIALES') == '1':
                        # Solo si se pide explícitamente: los logs de Render los puede ver cualquiera con acceso al panel.
                        print(f"[INICIO] Usuario '{usr}' creado con clave temporal: {pwd}  (cámbiala desde el panel de admin)")
                    else:
                        print(f"[INICIO] Usuario '{usr}' creado con clave aleatoria. Define PASS_INICIAL_{usr.upper()} "
                              f"o MOSTRAR_CLAVES_INICIALES=1 antes del primer arranque para conocerla.")
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

        if ProductoGrupoMod.query.count() == 0:
            sincronizar_modificadores_guiados_quiosco()

def sincronizar_modificadores_guiados_quiosco():
    """Asegura modificadores y flujos guiados paso a paso para Quiosco Morisco (con ruteo Cocina/Barra)."""
    mods_def = [
        # --- BEBIDAS CALIENTES / FRÍAS ---
        ('03001', 'TIPO DE LECHE', 'ENTERA', 0.0, 'BARRA'),
        ('03002', 'TIPO DE LECHE', 'DESLACTOSADA', 0.0, 'BARRA'),
        ('03003', 'TIPO DE LECHE', 'ALMENDRAS', 15.0, 'BARRA'),
        ('03010', 'CARGAS DE CAFE', 'CARGA NORMAL', 0.0, 'BARRA'),
        ('03011', 'CARGAS DE CAFE', 'EXTRA SHOT CAFE', 18.0, 'BARRA'),
        ('03012', 'CARGAS DE CAFE', 'DESCAFEINADO', 0.0, 'BARRA'),
        ('03020', 'SABORES LATTE', 'NORMAL', 0.0, 'BARRA'),
        ('03021', 'SABORES LATTE', 'VAINILLA', 15.0, 'BARRA'),
        ('03022', 'SABORES LATTE', 'CARAMELO', 15.0, 'BARRA'),
        ('03023', 'SABORES', 'NORMAL', 0.0, 'BARRA'),
        ('03024', 'SABORES', 'VAINILLA', 15.0, 'BARRA'),
        ('03025', 'SABORES', 'CARAMELO', 15.0, 'BARRA'),
        ('03026', 'SABORES', 'MOKA', 15.0, 'BARRA'),
        ('03027', 'EXTRA CHAI', 'CHAI NORMAL', 0.0, 'BARRA'),
        ('03028', 'EXTRA CHAI', 'CHAI SUCIO', 10.0, 'BARRA'),
        ('03030', 'FRIO O CALIENTE', 'CALIENTE', 0.0, 'BARRA'),
        ('03031', 'FRIO O CALIENTE', 'VERSION FRIA', 5.0, 'BARRA'),
        # --- CERVEZAS ---
        ('03035', 'PREP CERVEZA', 'SOLA', 0.0, 'BARRA'),
        ('03036', 'PREP CERVEZA', 'CHELADA', 25.0, 'BARRA'),
        ('03037', 'PREP CERVEZA', 'MICHELADA', 30.0, 'BARRA'),
        # --- DESAYUNOS Y ALIMENTOS ---
        ('03050', 'PREP HUEVOS', 'CON CHORIZO', 0.0, 'COCINA'),
        ('03051', 'PREP HUEVOS', 'CON JAMON', 0.0, 'COCINA'),
        ('03052', 'PREP HUEVOS', 'CON TOCINO', 0.0, 'COCINA'),
        ('03053', 'PREP HUEVOS', 'RANCHEROS', 0.0, 'COCINA'),
        ('03054', 'PREP HUEVOS', 'ESTRELLADOS', 0.0, 'COCINA'),
        ('03055', 'PREP HUEVOS', 'A LA MEXICANA', 0.0, 'COCINA'),
        ('03060', 'ING OMELETE', 'CHAMPINONES Y QUESO', 0.0, 'COCINA'),
        ('03061', 'ING OMELETE', 'JAMON Y QUESO', 0.0, 'COCINA'),
        ('03062', 'ING OMELETE', 'TOCINO Y QUESO', 0.0, 'COCINA'),
        ('03063', 'ING OMELETE', 'CHORIZO Y QUESO', 0.0, 'COCINA'),
        ('03065', 'SALSA CHILAQUILES', 'SALSA VERDE', 0.0, 'COCINA'),
        ('03066', 'SALSA CHILAQUILES', 'SALSA ROJA', 0.0, 'COCINA'),
        ('03068', 'PROT CHILAQUILES', 'POLLO DESHEBRADO', 0.0, 'COCINA'),
        ('03069', 'PROT CHILAQUILES', 'HUEVOS ESTRELLADOS', 0.0, 'COCINA'),
        # --- PAQUETES (PLATILLOS EN COCINA, BEBIDAS/FRUTA EN BARRA) ---
        ('03070', 'PLAT PAQ BOLERO', 'HUEVOS MOTULENOS', 0.0, 'COCINA'),
        ('03071', 'PLAT PAQ BOLERO', 'OMELETE CHAMPINONES', 0.0, 'COCINA'),
        ('03072', 'PLAT PAQ BOLERO', 'OMELETE CHORIZO', 0.0, 'COCINA'),
        ('03073', 'PLAT PAQ BOLERO', 'OMELETE TOCINO', 0.0, 'COCINA'),
        ('03074', 'PLAT PAQ BOLERO', 'OMELETE JAMON Y QUESO', 0.0, 'COCINA'),
        ('03075', 'BEB CAL PAQUETE', 'CAFE TRADICIONAL REFILL', 0.0, 'BARRA'),
        ('03076', 'BEB CAL PAQUETE', 'TE REFILL', 0.0, 'BARRA'),
        ('03078', 'ACOMP PAQ DESAYUNO', 'AGUA DEL DIA', 0.0, 'BARRA'),
        ('03079', 'ACOMP PAQ DESAYUNO', 'FRUTA', 0.0, 'BARRA'),
        ('03080', 'PLAT PAQ MORISCO', 'SANDWICH DE POLLO', 0.0, 'COCINA'),
        ('03081', 'PLAT PAQ MORISCO', 'CUERNITO POMPOSO', 0.0, 'COCINA'),
        ('03082', 'PLAT PAQ MORISCO', 'HAMBURGUESA MORISCO', 0.0, 'COCINA'),
        ('03083', 'PLAT PAQ MARIMBERO', 'TOSTADAS DE POLLO', 0.0, 'COCINA'),
        ('03084', 'PLAT PAQ MARIMBERO', 'QUESADILLAS', 0.0, 'COCINA'),
        ('03085', 'PLAT PAQ PORTALES', 'ENCHILADAS COLETAS', 0.0, 'COCINA'),
        ('03086', 'PLAT PAQ PORTALES', 'SANDWICH MORISCO', 0.0, 'COCINA'),
        ('03087', 'BEB PAQ DIA', 'COCA COLA 355ML', 0.0, 'BARRA'),
        ('03088', 'BEB PAQ DIA', 'SPRITE 355ML', 0.0, 'BARRA'),
        ('03089', 'BEB PAQ DIA', 'SIDRAL 355ML', 0.0, 'BARRA'),
        ('03090', 'BEB PAQ DIA', 'AGUA DEL DIA', 0.0, 'BARRA'),
        # --- EXTRAS ESPECÍFICOS ---
        ('03091', 'EXTRAS NACHOS', 'CON CHORIZO FRITO', 25.0, 'COCINA'),
        ('03092', 'EXTRAS NACHOS', 'SIN JALAPENO', 0.0, 'COCINA'),
        ('03093', 'EXTRAS NACHOS', 'SIN FRIJOLES', 0.0, 'COCINA'),
        ('03094', 'ACOMP PLATANOS', 'CON QUESO Y CREMA', 0.0, 'COCINA'),
        ('03095', 'ACOMP PLATANOS', 'CON LECHERA', 0.0, 'COCINA'),
        ('03096', 'EXTRAS ALIMENTOS', 'SIN CEBOLLA', 0.0, None),
        ('03097', 'EXTRAS ALIMENTOS', 'SIN HIELO', 0.0, 'BARRA'),
        ('03098', 'EXTRAS ALIMENTOS', 'PARA LLEVAR', 0.0, None),
    ]
    for clv, grp, nom, pre, area in mods_def:
        ex = ModificadorPOS.query.filter_by(grupo=grp, nombre=nom).first()
        if not ex:
            db.session.add(ModificadorPOS(clave=clv, grupo=grp, nombre=nom, precio=pre, area_impresion=area, activo=True))
        else:
            ex.precio = pre
            ex.area_impresion = area
            ex.activo = True

    flujos = [
        # Desayunos individuales
        ('HUEVOS REVUELTOS AL GUSTO', 'PREP HUEVOS', '1. Preparación de huevos', 1, True, 1),
        ('OMELETE', 'ING OMELETE', '1. Ingrediente del omelete', 1, True, 1),
        ('CHILAQUILES', 'SALSA CHILAQUILES', '1. Salsa', 1, True, 1),
        ('CHILAQUILES', 'PROT CHILAQUILES', '2. Acompañados con', 2, True, 1),
        # Paquetes desayunos
        ('PAQUETE QUIOSCO', 'SALSA CHILAQUILES', '1. Salsa chilaquiles', 1, True, 1),
        ('PAQUETE QUIOSCO', 'PROT CHILAQUILES', '2. Proteína', 2, True, 1),
        ('PAQUETE QUIOSCO', 'BEB CAL PAQUETE', '3. Café o Té (Barra)', 3, True, 1),
        ('PAQUETE QUIOSCO', 'ACOMP PAQ DESAYUNO', '4. Agua o Fruta (Barra)', 4, True, 1),
        ('PAQUETE DEL PARQUE', 'PREP HUEVOS', '1. Huevos al gusto', 1, True, 1),
        ('PAQUETE DEL PARQUE', 'BEB CAL PAQUETE', '2. Café o Té (Barra)', 2, True, 1),
        ('PAQUETE DEL PARQUE', 'ACOMP PAQ DESAYUNO', '3. Agua o Fruta (Barra)', 3, True, 1),
        ('PAQUETE BOLERO', 'PLAT PAQ BOLERO', '1. Motuleños u Omelete', 1, True, 1),
        ('PAQUETE BOLERO', 'BEB CAL PAQUETE', '2. Café o Té (Barra)', 2, True, 1),
        ('PAQUETE BOLERO', 'ACOMP PAQ DESAYUNO', '3. Agua o Fruta (Barra)', 3, True, 1),
        # Paquetes durante el día
        ('PAQUETE MORISCO', 'PLAT PAQ MORISCO', '1. Platillo principal', 1, True, 1),
        ('PAQUETE MORISCO', 'BEB PAQ DIA', '2. Bebida (Barra)', 2, True, 1),
        ('PAQUETE MARIMBERO', 'PLAT PAQ MARIMBERO', '1. Platillo principal', 1, True, 1),
        ('PAQUETE MARIMBERO', 'BEB PAQ DIA', '2. Bebida (Barra)', 2, True, 1),
        ('PAQUETE PORTALES', 'PLAT PAQ PORTALES', '1. Platillo principal', 1, True, 1),
        ('PAQUETE PORTALES', 'BEB PAQ DIA', '2. Bebida (Barra)', 2, True, 1),
        # Especiales y Postres
        ('NACHOS', 'EXTRAS NACHOS', '1. Extras / Modificadores', 1, False, 0),
        ('PLÁTANOS FRITOS', 'ACOMP PLATANOS', '1. Acompañamiento', 1, True, 1),
        ('PLATANOS FRITOS', 'ACOMP PLATANOS', '1. Acompañamiento', 1, True, 1),
        # Bebidas calientes e infusiones
        ('LATTE', 'TIPO DE LECHE', '1. Tipo de leche', 1, True, 1),
        ('LATTE', 'SABORES LATTE', '2. Sabor (+$15)', 2, False, 1),
        ('LATTE', 'FRIO O CALIENTE', '3. Temperatura', 3, True, 1),
        ('LATTE', 'CARGAS DE CAFE', '4. Cargas', 4, False, 1),
        ('CAPUCHINO', 'TIPO DE LECHE', '1. Tipo de leche', 1, True, 1),
        ('CAPUCHINO', 'SABORES', '2. Sabor (+$15)', 2, False, 1),
        ('CAPUCHINO', 'FRIO O CALIENTE', '3. Temperatura', 3, True, 1),
        ('CAPUCHINO', 'CARGAS DE CAFE', '4. Cargas', 4, False, 1),
        ('CHAI LATTE', 'TIPO DE LECHE', '1. Tipo de leche', 1, True, 1),
        ('CHAI LATTE', 'EXTRA CHAI', '2. Chai Sucio (+$10)', 2, False, 1),
        ('CHAI LATTE', 'FRIO O CALIENTE', '3. Temperatura', 3, True, 1),
        ('MOCHA', 'TIPO DE LECHE', '1. Tipo de leche', 1, True, 1),
        ('MOCHA', 'FRIO O CALIENTE', '2. Temperatura', 2, True, 1),
        ('CHOCOLATE', 'TIPO DE LECHE', '1. Tipo de leche', 1, True, 1),
        ('CHOCOLATE', 'FRIO O CALIENTE', '2. Temperatura', 2, True, 1),
        ('LECHE DORADA', 'TIPO DE LECHE', '1. Tipo de leche', 1, True, 1),
        ('LECHE DORADA', 'FRIO O CALIENTE', '2. Temperatura', 2, True, 1),
        ('MARACUYÁ', 'FRIO O CALIENTE', '1. Temperatura', 1, True, 1),
        ('FRUTOS ROJOS', 'FRIO O CALIENTE', '1. Temperatura', 1, True, 1),
        # Cervezas
        ('XX LAGER', 'PREP CERVEZA', '1. Preparación', 1, True, 1),
        ('XX ÁMBAR', 'PREP CERVEZA', '1. Preparación', 1, True, 1),
        ('BOHEMIA OSCURA', 'PREP CERVEZA', '1. Preparación', 1, True, 1),
        ('BOHEMIA CLARA', 'PREP CERVEZA', '1. Preparación', 1, True, 1),
    ]
    for plat, grp, etiq, ord_n, oblig, max_s in flujos:
        ex = ProductoGrupoMod.query.filter_by(platillo_nombre=plat, grupo=grp).first()
        if not ex:
            db.session.add(ProductoGrupoMod(
                platillo_nombre=plat, grupo=grp, etiqueta=etiq,
                orden=ord_n, obligatorio=oblig, max_seleccion=max_s
            ))
        else:
            ex.etiqueta = etiq
            ex.orden = ord_n
            ex.obligatorio = oblig
            ex.max_seleccion = max_s
    db.session.commit()


def cargar_menu_quiosco_oficial():
    """Actualiza el menú oficial de Quiosco Morisco (67 ítems en 18 categorías) conservando fotos de Cloudinary."""
    categorias_def = [
        ('Desayunos Individuales', 'Individual Breakfasts'),
        ('Paquetes Desayunos', 'Breakfast Packages'),
        ('Paquetes Durante el Día', 'Daytime Packages'),
        ('Entradas', 'Starters'),
        ('Hamburguesas', 'Burgers'),
        ('Sándwiches Bistró', 'Bistro Sandwiches'),
        ('Antojitos', 'Mexican Specialties'),
        ('Platillos Bistró', 'Bistro Dishes'),
        ('Postres', 'Desserts'),
        ('Bebidas Calientes', 'Hot Drinks'),
        ('Infusiones', 'Herbal Infusions'),
        ('Frappes', 'Frappes'),
        ('Jugos Naturales', 'Natural Juices'),
        ('Aguas Naturales', 'Fresh Waters'),
        ('Refrescos', 'Soft Drinks'),
        ('Cócteles', 'Cocktails'),
        ('Vino', 'Wine'),
        ('Cervezas', 'Beers'),
    ]
    for nom_es, nom_en in categorias_def:
        c = CategoriaMenu.query.filter_by(nombre=nom_es).first()
        if not c:
            db.session.add(CategoriaMenu(nombre=nom_es, nombre_en=nom_en))
        elif not c.nombre_en:
            c.nombre_en = nom_en

    # (categoria, nombre_es, nombre_en, desc_es, desc_en, precio)
    productos_def = [
        # Desayunos Individuales
        ('Desayunos Individuales', 'Huevos Revueltos al Gusto', 'Scrambled Eggs Your Way', 'Chorizo, jamón, tocino, rancheros, estrellados o a la mexicana. Acompañado de chilaquiles, ensalada y frijoles fritos.', 'Chorizo, ham, bacon, ranchero, fried or Mexican style. Served with chilaquiles, salad and refried beans.', 85.0),
        ('Desayunos Individuales', 'Huevos Motuleños', 'Motuleños Eggs', 'Estrellados sobre tortilla frita bañados con salsa de tomate, jamón, queso amarillo, chícharos, aguacate y crema, con plátanos fritos.', 'Fried eggs on crispy tortilla with tomato sauce, ham, cheese, peas, avocado, cream and fried plantains.', 165.0),
        ('Desayunos Individuales', 'Huevos Divorciados', 'Divorced Eggs', 'Estrellados sobre tortilla frita cubiertos con salsa roja y verde, acompañados de frijoles fritos y ensalada.', 'Fried eggs on crispy tortilla topped with red and green salsa, served with refried beans and salad.', 109.0),
        ('Desayunos Individuales', 'Tosta de Jamón Serrano', 'Serrano Ham Toast', 'Aguacate, jamón serrano, huevo estrellado, tomates cherry y alfalfa.', 'Avocado, Serrano ham, fried egg, cherry tomatoes and alfalfa sprouts.', 175.0),
        ('Desayunos Individuales', 'Omelete', 'Omelette', 'Omelete de champiñones, jamón, tocino o chorizo y queso, servido con frijoles refritos y guarnición de chilaquiles.', 'Mushrooms, ham, bacon or chorizo & cheese omelette, served with refried beans and chilaquiles.', 155.0),
        ('Desayunos Individuales', 'Chilaquiles', 'Chilaquiles', 'Totopos en salsa verde o roja, con crema, queso y cebolla morada. Acompañados con huevos estrellados o pollo deshebrado.', 'Tortilla chips in green or red salsa with cream, cheese and red onion. Topped with fried eggs or shredded chicken.', 150.0),
        ('Desayunos Individuales', 'Hot Cakes', 'Pancakes', 'Espolvoreados con azúcar, acompañados de frutos rojos.', 'Dusted with sugar and served with mixed berries.', 125.0),
        ('Desayunos Individuales', 'Pan Francés', 'French Toast', 'Espolvoreados con azúcar, acompañados de frutos rojos.', 'Dusted with sugar and served with mixed berries.', 125.0),
        # Paquetes Desayunos
        ('Paquetes Desayunos', 'Paquete Quiosco', 'Quiosco Package', 'Chilaquiles en salsa verde o roja (pollo o huevos estrellados) + Café tradicional o té refill + Agua del día o fruta.', 'Chilaquiles (chicken or fried eggs) + Refill coffee or tea + Fresh water or fruit.', 185.0),
        ('Paquetes Desayunos', 'Paquete Del Parque', 'Del Parque Package', 'Huevos al gusto con chilaquiles, ensalada y frijoles refritos con queso + Café tradicional o té refill + Agua del día o fruta.', 'Eggs your way with chilaquiles, salad and beans + Refill coffee or tea + Fresh water or fruit.', 125.0),
        ('Paquetes Desayunos', 'Paquete Bolero', 'Bolero Package', 'Huevos motuleños u omelete al gusto + Café tradicional o té refill + Agua del día o fruta.', 'Motuleños eggs or omelette your way + Refill coffee or tea + Fresh water or fruit.', 198.0),
        # Paquetes Durante el Día
        ('Paquetes Durante el Día', 'Paquete Morisco', 'Morisco Package', 'Sándwich de pollo, cuernito pomposo o hamburguesa (a elegir) + Papas fritas + Refresco 355 ml o agua del día.', 'Chicken sandwich, croissant or burger + French fries + 355ml soda or fresh water.', 165.0),
        ('Paquetes Durante el Día', 'Paquete Marimbero', 'Marimbero Package', 'Tostadas de pollo o quesadillas + Papas fritas + Refresco 355 ml o agua del día.', 'Chicken tostadas or quesadillas + French fries + 355ml soda or fresh water.', 140.0),
        ('Paquetes Durante el Día', 'Paquete Portales', 'Portales Package', 'Enchiladas coletas o sándwich morisco (a elegir) + Postre del día + Refresco 355 ml o agua del día.', 'Coleta enchiladas or Morisco sandwich + Dessert of the day + 355ml soda or fresh water.', 185.0),
        # Entradas
        ('Entradas', 'Papas Gajo', 'Potato Wedges', 'Crujientes papas gajo sazonadas.', 'Crispy seasoned potato wedges.', 65.0),
        ('Entradas', 'Tapitas del Quiosco', 'Quiosco Tapas', 'Tapas de pan artesanal inspiradas en nuestros sándwiches bistró.', 'Artisanal bread tapas inspired by our bistro sandwiches.', 89.0),
        ('Entradas', 'Nachos', 'Nachos', 'Con frijoles, queso amarillo, chile jalapeño, queso y crema (+$25 con chorizo frito).', 'With beans, cheddar cheese, jalapeño, cheese and cream (+$25 with fried chorizo).', 95.0),
        # Hamburguesas
        ('Hamburguesas', 'Hamburguesa Morisco', 'Morisco Burger', 'Carne de res, tocineta, ensalada, aderezo de mayonesa y queso mozzarella.', 'Beef patty, bacon, salad, mayo dressing and mozzarella cheese.', 118.0),
        # Sándwiches Bistró
        ('Sándwiches Bistró', 'Sándwich Morisco', 'Morisco Sandwich', 'Jamón serrano, aderezo de queso de cabra, frutos rojos, arúgula y vinagreta.', 'Serrano ham, goat cheese dressing, berries, arugula and vinaigrette.', 132.0),
        ('Sándwiches Bistró', 'Sándwich de Pollo', 'Chicken Sandwich', 'Pechuga de pollo, tomate cherry, arúgula, aderezo de aguacate y vinagreta.', 'Chicken breast, cherry tomatoes, arugula, avocado dressing and vinaigrette.', 118.0),
        ('Sándwiches Bistró', 'Cuernito Pomposo', 'Pomposo Croissant', 'Jamón serrano, aderezo de queso, arúgula, tomate cherry y queso mozzarella.', 'Serrano ham, cheese dressing, arugula, cherry tomatoes and mozzarella.', 125.0),
        # Antojitos
        ('Antojitos', 'Tostadas de Pollo', 'Chicken Tostadas', 'Tostadas doradas cubiertas con lechuga, queso, crema, aguacate y pollo. Acompañadas de pico de gallo.', 'Crispy tostadas topped with lettuce, cheese, cream, avocado and chicken. Served with pico de gallo.', 98.0),
        ('Antojitos', 'Quesadillas', 'Quesadillas', 'Orden de 3 quesadillas, acompañadas de ensalada.', 'Order of 3 quesadillas, served with salad.', 105.0),
        # Platillos Bistró
        ('Platillos Bistró', 'Enchiladas Coletas', 'Coleta Enchiladas', 'Enchiladas de pollo bañadas en mole tradicional coleto, acompañadas con queso y crema.', 'Chicken enchiladas bathed in traditional San Cristobal mole with cheese and cream.', 155.0),
        # Postres (Pay de Queso = Cheesecake)
        ('Postres', 'Plátanos Fritos', 'Fried Plantains', 'Con queso y crema o lechera.', 'With cheese & cream or condensed milk.', 60.0),
        ('Postres', 'Pan Regional', 'Regional Sweet Bread', 'Orden de 6 piezas.', 'Order of 6 pieces.', 35.0),
        ('Postres', 'Pay de Queso', 'Cheesecake', 'Pay de queso artesanal de la casa.', 'House-made cheesecake.', 55.0),
        ('Postres', 'Flan Napolitano', 'Neapolitan Flan', 'Flan napolitano casero.', 'Homemade Neapolitan flan.', 65.0),
        # Bebidas Calientes
        ('Bebidas Calientes', 'Espresso', 'Espresso', 'Shot de espresso chiapaneco.', 'Chiapas espresso shot.', 40.0),
        ('Bebidas Calientes', 'Americano', 'Americano', 'Café americano recién extraído.', 'Freshly brewed Americano.', 55.0),
        ('Bebidas Calientes', 'Mocha', 'Mocha', 'Espresso, chocolate y leche vaporizada.', 'Espresso, chocolate and steamed milk.', 75.0),
        ('Bebidas Calientes', 'Latte', 'Latte', 'Vainilla o caramelo +$15.', 'Vanilla or caramel +$15.', 65.0),
        ('Bebidas Calientes', 'Capuchino', 'Cappuccino', 'Vainilla, moka o caramelo +$15.', 'Vanilla, mocha or caramel +$15.', 65.0),
        ('Bebidas Calientes', 'Chai Latte', 'Chai Latte', 'Sucio +$10.', 'Dirty +$10.', 65.0),
        ('Bebidas Calientes', 'Chocolate', 'Hot Chocolate', 'Chocolate tradicional caliente.', 'Traditional hot chocolate.', 70.0),
        ('Bebidas Calientes', 'Leche Dorada', 'Golden Milk', 'Infusión especiada de cúrcuma y leche.', 'Spiced turmeric golden milk.', 70.0),
        ('Bebidas Calientes', 'Café Tradicional Refill', 'Traditional Refill Coffee', 'Café de olla / americano tradicional con refill.', 'Traditional coffee with refill.', 50.0),
        # Infusiones
        ('Infusiones', 'Maracuyá', 'Passion Fruit Infusion', 'Infusión natural (versión fría +$5).', 'Natural infusion (iced +$5).', 65.0),
        ('Infusiones', 'Frutos Rojos', 'Red Berries Infusion', 'Infusión natural (versión fría +$5).', 'Natural infusion (iced +$5).', 70.0),
        # Frappes
        ('Frappes', 'Frappe Chocolate', 'Chocolate Frappe', 'Bebida helada cremosa de chocolate.', 'Creamy iced chocolate frappe.', 90.0),
        ('Frappes', 'Frappe Café', 'Coffee Frappe', 'Bebida helada de café de altura.', 'Iced highland coffee frappe.', 85.0),
        ('Frappes', 'Frappe Taro', 'Taro Frappe', 'Bebida helada cremosa de taro.', 'Creamy iced taro frappe.', 90.0),
        ('Frappes', 'Bubba Ti', 'Bubba Ti', 'Cold brew, té negro, lácteos y tapioca.', 'Cold brew, black tea, milk and tapioca pearls.', 95.0),
        # Jugos Naturales
        ('Jugos Naturales', 'Agua Moriska', 'Moriska Juice', 'Fresa, pepino y menta.', 'Strawberry, cucumber and mint.', 80.0),
        ('Jugos Naturales', 'Vergel', 'Vergel Juice', 'Piña, naranja y arúgula.', 'Pineapple, orange and arugula.', 70.0),
        ('Jugos Naturales', 'Rosal', 'Rosal Juice', 'Té negro, mora y miel.', 'Black tea, blackberry and honey.', 85.0),
        # Aguas Naturales
        ('Aguas Naturales', 'Jamaica', 'Hibiscus Water', 'Agua fresca natural de jamaica.', 'Fresh hibiscus water.', 40.0),
        ('Aguas Naturales', 'Horchata', 'Horchata', 'Agua fresca tradicional de horchata.', 'Traditional horchata.', 40.0),
        ('Aguas Naturales', 'Naranjada', 'Orangeade', 'Naranjada natural.', 'Fresh orangeade.', 40.0),
        ('Aguas Naturales', 'Naranjada Mineral', 'Sparkling Orangeade', 'Naranjada con agua mineral.', 'Sparkling fresh orangeade.', 52.0),
        ('Aguas Naturales', 'Limonada', 'Lemonade', 'Limonada natural.', 'Fresh lemonade.', 40.0),
        ('Aguas Naturales', 'Limonada Mineral', 'Sparkling Lemonade', 'Limonada con agua mineral.', 'Sparkling fresh lemonade.', 52.0),
        # Refrescos
        ('Refrescos', 'Coca Cola Lata', 'Coca Cola Can', 'Lata 355 ml.', '355 ml can.', 50.0),
        ('Refrescos', 'Sprite Lata', 'Sprite Can', 'Lata 355 ml.', '355 ml can.', 50.0),
        ('Refrescos', 'Sidral Lata', 'Sidral Can', 'Lata 355 ml.', '355 ml can.', 50.0),
        ('Refrescos', 'Agua Ciel 600 ml', 'Ciel Water 600ml', 'Botella 600 ml.', '600 ml bottle.', 30.0),
        ('Refrescos', 'Agua Mineral Lata', 'Sparkling Water Can', 'Lata 355 ml.', '355 ml can.', 45.0),
        # Cócteles
        ('Cócteles', 'Guabi', 'Guabi Cocktail', 'Ron, chocolate blanco y guanábana.', 'Rum, white chocolate and soursop.', 160.0),
        ('Cócteles', 'Naked Mumo', 'Naked Mumo Cocktail', 'Mezcal, mumo y curacao.', 'Mezcal, mumo and curacao.', 160.0),
        ('Cócteles', 'Morajillo', 'Morajillo Cocktail', 'Posh, cacao y licor de café.', 'Posh, cacao and coffee liqueur.', 140.0),
        ('Cócteles', 'Negroni', 'Negroni', 'Vermouth, gin y Campari.', 'Vermouth, gin and Campari.', 155.0),
        # Vino
        ('Vino', 'Vino de la Casa (Por Copeo)', 'House Wine (Glass)', 'Copa de vino de la casa.', 'Glass of house wine.', 80.0),
        ('Vino', 'Vino de la Casa (Por Botella)', 'House Wine (Bottle)', 'Botella de vino de la casa.', 'Bottle of house wine.', 320.0),
        # Cervezas
        ('Cervezas', 'XX Lager', 'XX Lager Beer', 'Cerveza XX Lager (+$25 chelada, +$30 michelada).', 'XX Lager beer (+$25 chelada, +$30 michelada).', 48.0),
        ('Cervezas', 'XX Ámbar', 'XX Ambar Beer', 'Cerveza XX Ámbar (+$25 chelada, +$30 michelada).', 'XX Ambar beer (+$25 chelada, +$30 michelada).', 48.0),
        ('Cervezas', 'Bohemia Oscura', 'Bohemia Dark Beer', 'Cerveza Bohemia Oscura (+$25 chelada, +$30 michelada).', 'Bohemia Dark beer (+$25 chelada, +$30 michelada).', 55.0),
        ('Cervezas', 'Bohemia Clara', 'Bohemia Light Beer', 'Cerveza Bohemia Clara (+$25 chelada, +$30 michelada).', 'Bohemia Light beer (+$25 chelada, +$30 michelada).', 55.0),
    ]

    creados, actualizados = 0, 0
    for cat, nom, nom_en, desc, desc_en, pre in productos_def:
        p = Producto.query.filter(db.func.lower(Producto.nombre) == nom.lower()).first()
        if not p:
            db.session.add(Producto(
                categoria=cat, nombre=nom, nombre_en=nom_en,
                descripcion=desc, descripcion_en=desc_en, precio=pre
            ))
            creados += 1
        else:
            p.categoria = cat
            p.precio = pre
            p.descripcion = desc
            if not p.nombre_en:
                p.nombre_en = nom_en
            if not p.descripcion_en:
                p.descripcion_en = desc_en
            actualizados += 1

    db.session.commit()
    sincronizar_modificadores_guiados_quiosco()
    invalidar_cache_publico()
    return creados, actualizados