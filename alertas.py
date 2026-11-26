"""Alertas al dueño: cancelaciones y descuentos grandes, faltantes en el corte Z, mucho efectivo en caja,
cuentas reabiertas y cambios de forma de pago. Se guardan en la base (Reportes → Alertas) y, si está
configurado, se mandan al celular por Telegram (bot gratuito)."""
import json
import os
import re
import threading
import urllib.parse
import urllib.request

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from models import db, ahora_local, cfg_cargar, cfg_guardar, AlertaDuenoPOS

alertas_bp = Blueprint('alertas', __name__)

CLAVE_CFG = 'alertas_cfg'
CFG_DEFAULT = {
    'activas': True,
    'cancelacion_min': 200.0,     # cancelación de productos/cuenta desde este monto
    'descuento_min': 150.0,       # descuento desde este monto
    'faltante_min': 50.0,         # faltante en el corte Z desde este monto
    'efectivo_max': 5000.0,       # efectivo en caja que conviene retirar
    'avisar_reabrir': True,       # cuenta impresa que se reabre
    'avisar_cambio_pago': True,   # cambio de forma de pago de una cuenta ya cobrada
    'telegram_chat_id': '',
}


def config():
    c = cfg_cargar(CLAVE_CFG, CFG_DEFAULT)
    for k, v in CFG_DEFAULT.items():
        c.setdefault(k, v)
    return c


def _enviar_telegram(texto):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat = str(config().get('telegram_chat_id') or '').strip()
    if not token or not chat:
        return False

    def _mandar():
        try:
            datos = urllib.parse.urlencode({'chat_id': chat, 'text': texto}).encode()
            urllib.request.urlopen(f'https://api.telegram.org/bot{token}/sendMessage', data=datos, timeout=6).read()
        except Exception:
            pass   # una alerta que no sale nunca debe romper la venta
    threading.Thread(target=_mandar, daemon=True).start()
    return True


def alertar(tipo, texto, sucursal='', monto=0.0):
    """Guarda la alerta y la manda al celular. Nunca lanza error (no debe afectar la operación)."""
    try:
        cfg = config()
        if not cfg.get('activas', True):
            return
        db.session.add(AlertaDuenoPOS(fecha=ahora_local(), sucursal=sucursal or '', tipo=tipo,
                                      texto=texto[:500], monto=float(monto or 0)))
        db.session.commit()
        _enviar_telegram(f'⚠️ {sucursal}\n{texto}')
    except Exception:
        db.session.rollback()


def evaluar_bitacora(accion, mesa, monto, detalle, usuario, autorizo, sucursal):
    """Se llama desde registrar_bitacora: decide si el movimiento amerita alerta."""
    try:
        cfg = config()
        if not cfg.get('activas', True):
            return
        monto = float(monto or 0)
        quien = usuario + (f' (autorizó {autorizo})' if autorizo and not autorizo.startswith(usuario) else '')
        if accion == 'CANCELACION' and monto >= float(cfg['cancelacion_min']):
            alertar('CANCELACION', f'❌ Cancelación de ${monto:,.2f} en mesa {mesa} por {quien}: {detalle}', sucursal, monto)
        elif accion.startswith('DESCUENTO') and monto >= float(cfg['descuento_min']):
            alertar('DESCUENTO', f'🏷️ Descuento de ${monto:,.2f} en mesa {mesa} por {quien}: {detalle}', sucursal, monto)
        elif accion == 'REABRIR_CUENTA' and cfg.get('avisar_reabrir'):
            alertar('REABRIR', f'🔓 Se reabrió la cuenta de la mesa {mesa} (${monto:,.2f}) por {quien}', sucursal, monto)
        elif accion == 'CAMBIO_PAGO' and cfg.get('avisar_cambio_pago'):
            alertar('CAMBIO_PAGO', f'💳 Cambio de forma de pago en {mesa} por {quien}: {detalle}', sucursal, monto)
        elif accion == 'CIERRE_CAJA':
            m = re.search(r'Dif:\s*\$(-?[\d,]+\.?\d*)', detalle or '')
            dif = float(m.group(1).replace(',', '')) if m else 0.0
            if dif <= -float(cfg['faltante_min']):
                alertar('FALTANTE', f'🔴 Corte Z con FALTANTE de ${-dif:,.2f} ({mesa}) cerrado por {quien}', sucursal, dif)
            elif dif >= float(cfg['faltante_min']):
                alertar('SOBRANTE', f'🟡 Corte Z con sobrante de ${dif:,.2f} ({mesa}) cerrado por {quien}', sucursal, dif)
    except Exception:
        pass


def revisar_efectivo(turno, efectivo, sucursal):
    """Una sola alerta por turno cuando el efectivo en caja pasa del tope."""
    try:
        cfg = config()
        tope = float(cfg['efectivo_max'])
        if efectivo < tope:
            return
        marca = f'TURNO #{turno.id}'
        if AlertaDuenoPOS.query.filter(AlertaDuenoPOS.tipo == 'EFECTIVO_ALTO', AlertaDuenoPOS.sucursal == sucursal,
                                       AlertaDuenoPOS.texto.like(f'%{marca}%')).first():
            return
        alertar('EFECTIVO_ALTO', f'💵 Hay ${efectivo:,.2f} en efectivo en caja ({marca}). Conviene hacer un retiro.', sucursal, efectivo)
    except Exception:
        pass


# ------------------------------------------------------------------ pantallas (solo Admin)
@alertas_bp.route('/api/alertas')
@login_required
def api_alertas():
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    q = AlertaDuenoPOS.query
    if request.args.get('sucursal') and request.args.get('sucursal') != 'TODAS':
        q = q.filter(AlertaDuenoPOS.sucursal == request.args.get('sucursal'))
    filas = q.order_by(AlertaDuenoPOS.id.desc()).limit(300).all()
    return jsonify({'ok': True, 'alertas': [{
        'id': a.id, 'fecha': a.fecha.strftime('%d/%m/%Y %H:%M'), 'sucursal': a.sucursal, 'tipo': a.tipo,
        'texto': a.texto, 'monto': a.monto} for a in filas]})


@alertas_bp.route('/api/alertas/config', methods=['GET', 'POST'])
@login_required
def api_alertas_config():
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    if request.method == 'GET':
        c = config()
        c['telegram_listo'] = bool(os.environ.get('TELEGRAM_BOT_TOKEN')) and bool(c.get('telegram_chat_id'))
        c['telegram_token_puesto'] = bool(os.environ.get('TELEGRAM_BOT_TOKEN'))
        return jsonify({'ok': True, 'config': c})
    d = request.get_json(silent=True) or {}
    nuevo = config()
    try:
        for k in ('cancelacion_min', 'descuento_min', 'faltante_min', 'efectivo_max'):
            if k in d:
                v = float(d[k])
                if not (0 <= v <= 10_000_000):
                    raise ValueError
                nuevo[k] = round(v, 2)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'msg': 'Los montos deben ser números positivos.'}), 400
    for k in ('activas', 'avisar_reabrir', 'avisar_cambio_pago'):
        if k in d:
            nuevo[k] = bool(d[k])
    if 'telegram_chat_id' in d:
        chat = str(d['telegram_chat_id'] or '').strip()
        if chat and not re.fullmatch(r'-?\d{5,20}', chat):
            return jsonify({'ok': False, 'msg': 'El "chat id" de Telegram son solo números.'}), 400
        nuevo['telegram_chat_id'] = chat
    cfg_guardar(CLAVE_CFG, nuevo)
    return jsonify({'ok': True})


@alertas_bp.route('/api/alertas/prueba', methods=['POST'])
@login_required
def api_alertas_prueba():
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    enviado = _enviar_telegram('✅ Prueba de alertas de Comensal Conectado: si ves esto, las alertas llegan a tu celular.')
    return jsonify({'ok': True, 'enviado': enviado,
                    'msg': 'Mensaje de prueba enviado a Telegram.' if enviado else
                    'Falta configurar Telegram (el token en Render y el chat id aquí).'})
