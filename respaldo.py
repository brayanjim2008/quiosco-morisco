"""Respaldo completo de la información del restaurante (ventas, cortes, inventario, nómina, menú, clientes...).

- Descargable por el dueño (Administración → Respaldo).
- Automático una vez al día al cerrar el primer Corte Z, y enviado por Telegram si se activa.
- Se restaura con:  python restaurar_respaldo.py respaldo.zip   (sobre una base de datos VACÍA).

Formato: un .zip con un archivo JSON-lines por tabla (una fila por renglón) y un manifiesto con los conteos.
Se escribe a un archivo temporal en disco, tabla por tabla, para no llenar la memoria del servidor."""
import io
import json
import os
import tempfile
import threading
import urllib.request
import uuid
import zipfile
from datetime import date, datetime, time
from decimal import Decimal

from flask import Blueprint, jsonify, request, send_file
from flask_login import login_required, current_user
from sqlalchemy import select, text

from models import db, ahora_local, cfg_cargar, cfg_guardar, registrar_bitacora

respaldo_bp = Blueprint('respaldo', __name__)

VERSION_FORMATO = 1
CLAVE_ESTADO = 'respaldo_estado'
# Tablas que no vale la pena respaldar: se regeneran solas o son temporales.
TABLAS_OMITIDAS = {'cola_impresion_pos', 'limites_intentos'}
LIMITE_TELEGRAM = 45 * 1024 * 1024   # Telegram acepta archivos de hasta 50 MB


def _a_json(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return None
    return v


def generar_respaldo():
    """Crea el .zip en un archivo temporal. Devuelve (ruta, nombre, resumen{tabla: filas})."""
    stamp = ahora_local().strftime('%Y%m%d_%H%M')
    nombre = f'respaldo_restaurante_{stamp}.zip'
    fd, ruta = tempfile.mkstemp(suffix='.zip')
    os.close(fd)
    resumen = {}
    with zipfile.ZipFile(ruta, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for tabla in db.metadata.sorted_tables:
            if tabla.name in TABLAS_OMITIDAS:
                continue
            cols = [c.name for c in tabla.columns]
            n = 0
            with z.open(f'tablas/{tabla.name}.jsonl', 'w') as f:
                res = db.session.execute(select(tabla).execution_options(yield_per=2000))
                for fila in res:
                    f.write((json.dumps({c: _a_json(v) for c, v in zip(cols, fila)}, ensure_ascii=False) + '\n').encode('utf-8'))
                    n += 1
            resumen[tabla.name] = n
        z.writestr('manifiesto.json', json.dumps({
            'formato': VERSION_FORMATO, 'creado': ahora_local().isoformat(), 'tablas': resumen,
            'orden': [t.name for t in db.metadata.sorted_tables if t.name not in TABLAS_OMITIDAS],
        }, ensure_ascii=False, indent=1))
    db.session.rollback()   # cierra la transacción de solo lectura
    return ruta, nombre, resumen


def _estado():
    e = cfg_cargar(CLAVE_ESTADO, {})
    e = e if isinstance(e, dict) else {}
    e.setdefault('telegram', False)
    return e


def _guardar_estado(**cambios):
    e = _estado()
    e.update(cambios)
    cfg_guardar(CLAVE_ESTADO, e)
    return e


def _enviar_documento_telegram(ruta, nombre, texto):
    """Manda el archivo al chat de Telegram configurado en Alertas. True si salió."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    from alertas import config as _cfg_alertas
    chat = str(_cfg_alertas().get('telegram_chat_id') or '').strip()
    if not token or not chat or os.path.getsize(ruta) > LIMITE_TELEGRAM:
        return False
    limite = '----respaldo' + uuid.uuid4().hex
    cuerpo = io.BytesIO()

    def campo(nom, valor):
        cuerpo.write(f'--{limite}\r\nContent-Disposition: form-data; name="{nom}"\r\n\r\n{valor}\r\n'.encode('utf-8'))
    campo('chat_id', chat)
    campo('caption', texto[:900])
    cuerpo.write(f'--{limite}\r\nContent-Disposition: form-data; name="document"; filename="{nombre}"\r\n'
                 f'Content-Type: application/zip\r\n\r\n'.encode('utf-8'))
    with open(ruta, 'rb') as f:
        cuerpo.write(f.read())
    cuerpo.write(f'\r\n--{limite}--\r\n'.encode('utf-8'))
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendDocument', data=cuerpo.getvalue(),
                                 headers={'Content-Type': f'multipart/form-data; boundary={limite}'})
    try:
        urllib.request.urlopen(req, timeout=60).read()
        return True
    except Exception:
        return False


def _texto_resumen(resumen):
    clave = [('cuentas_pos', 'cuentas'), ('detalles_pos', 'productos vendidos'), ('turnos_pos', 'turnos'),
             ('insumos_bodega_pro', 'insumos'), ('empleados_nomina_pos', 'empleados')]
    return ', '.join(f'{resumen.get(t, 0):,} {txt}' for t, txt in clave)


def respaldo_diario(app):
    """Una vez al día (se llama al cerrar un Corte Z). Corre en segundo plano: nunca frena el cierre de caja."""
    hoy = ahora_local().date().isoformat()

    def _trabajo():
        with app.app_context():
            ruta = None
            try:
                # Solo un proceso gana el respaldo del día: la clave es única, el segundo INSERT falla.
                try:
                    db.session.execute(text("INSERT INTO config_pos (clave, valor_json) VALUES (:c, '1')"),
                                       {'c': f'respaldo_auto_{hoy}'})
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    return
                ruta, nombre, resumen = generar_respaldo()
                tam = os.path.getsize(ruta)
                enviado = False
                if _estado().get('telegram'):
                    enviado = _enviar_documento_telegram(ruta, nombre, f'🛟 Respaldo diario {hoy}: {_texto_resumen(resumen)}')
                _guardar_estado(ultimo=ahora_local().strftime('%d/%m/%Y %H:%M'), ultimo_tam=tam,
                                ultimo_enviado=enviado, ultimo_resumen=_texto_resumen(resumen), error='')
            except Exception as e:   # el respaldo nunca debe afectar la operación
                db.session.rollback()
                try:
                    _guardar_estado(error=f'{ahora_local():%d/%m %H:%M}: {type(e).__name__}')
                except Exception:
                    db.session.rollback()
            finally:
                if ruta and os.path.exists(ruta):
                    os.remove(ruta)
    hilo = threading.Thread(target=_trabajo, daemon=True)
    hilo.start()
    return hilo


def _solo_admin():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo el administrador maneja los respaldos.'}), 403
    return None


@respaldo_bp.route('/api/respaldo/estado', methods=['GET', 'POST'])
@login_required
def api_respaldo_estado():
    err = _solo_admin()
    if err:
        return err
    if request.method == 'POST':
        d = request.get_json(silent=True) or {}
        _guardar_estado(telegram=bool(d.get('telegram')))
    e = _estado()
    from alertas import config as _cfg_alertas
    e['telegram_listo'] = bool(os.environ.get('TELEGRAM_BOT_TOKEN')) and bool(_cfg_alertas().get('telegram_chat_id'))
    try:
        e['tamano_bd'] = db.session.execute(text('SELECT pg_database_size(current_database())')).scalar() \
            if db.engine.dialect.name == 'postgresql' else None
    except Exception:
        db.session.rollback()
        e['tamano_bd'] = None
    return jsonify({'ok': True, 'estado': e})


@respaldo_bp.route('/api/respaldo/descargar', methods=['POST'])
@login_required
def api_respaldo_descargar():
    err = _solo_admin()
    if err:
        return err
    ruta, nombre, resumen = generar_respaldo()
    with open(ruta, 'rb') as f:
        datos = io.BytesIO(f.read())
    tam = os.path.getsize(ruta)
    os.remove(ruta)
    _guardar_estado(ultimo=ahora_local().strftime('%d/%m/%Y %H:%M'), ultimo_tam=tam, ultimo_resumen=_texto_resumen(resumen))
    registrar_bitacora('RESPALDO', nombre, 0.0, f'Respaldo completo descargado ({tam // 1024:,} KB)')
    return send_file(datos, mimetype='application/zip', as_attachment=True, download_name=nombre)


@respaldo_bp.route('/api/respaldo/telegram', methods=['POST'])
@login_required
def api_respaldo_telegram_ahora():
    """Prueba: genera y manda el respaldo a Telegram en este momento."""
    err = _solo_admin()
    if err:
        return err
    ruta, nombre, resumen = generar_respaldo()
    try:
        ok = _enviar_documento_telegram(ruta, nombre, f'🛟 Respaldo {ahora_local():%d/%m/%Y %H:%M}: {_texto_resumen(resumen)}')
    finally:
        os.remove(ruta)
    if not ok:
        return jsonify({'ok': False, 'msg': 'No se pudo enviar. Revisa que Telegram esté configurado en Reportes → Alertas.'}), 400
    return jsonify({'ok': True})
