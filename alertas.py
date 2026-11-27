"""Alertas al dueño: cancelaciones y descuentos grandes, faltantes en el corte Z, mucho efectivo en caja,
cuentas reabiertas y cambios de forma de pago. Se guardan en la base (Reportes → Alertas) y, si está
configurado, se mandan al celular por WhatsApp Business (API oficial de Meta) y/o Telegram (bot gratuito).

WhatsApp Business: variables en Render WHATSAPP_TOKEN y WHATSAPP_PHONE_ID (del número que MANDA, dado de alta en
Meta) y, opcional, WHATSAPP_API_VERSION. Meta solo deja que un sistema inicie mensajes con una PLANTILLA aprobada:
categoría "Utilidad", nombre alerta_restaurante, idioma Español (MEX), cuerpo "Aviso de Comensal Conectado: {{1}}"."""
import json
import os
import re
import threading
import urllib.parse
import urllib.error
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
    'whatsapp_destinos': '',                    # números que reciben, separados por coma (10 dígitos o con lada)
    'whatsapp_plantilla': 'alerta_restaurante',
    'whatsapp_idioma': 'es_MX',
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


def _destinos_whatsapp(cfg=None):
    cfg = cfg or config()
    return [d for d in str(cfg.get('whatsapp_destinos') or '').split(',') if d.strip()]


def whatsapp_listo(cfg=None):
    return bool(os.environ.get('WHATSAPP_TOKEN', '').strip() and os.environ.get('WHATSAPP_PHONE_ID', '').strip()
                and _destinos_whatsapp(cfg))


def _texto_para_plantilla(texto):
    """Meta no acepta saltos de línea, tabulaciones ni más de 4 espacios seguidos dentro de una variable."""
    t = re.sub(r'[\r\n\t]+', ' · ', str(texto or ''))
    return re.sub(r' {2,}', ' ', t).strip()[:900] or '-'


def _mandar_whatsapp(numero, texto, cfg):
    """Manda la plantilla a un número. Devuelve (ok, mensaje de error de Meta)."""
    token = os.environ.get('WHATSAPP_TOKEN', '').strip()
    phone_id = os.environ.get('WHATSAPP_PHONE_ID', '').strip()
    version = os.environ.get('WHATSAPP_API_VERSION', 'v23.0').strip() or 'v23.0'
    cuerpo = json.dumps({
        'messaging_product': 'whatsapp', 'to': numero, 'type': 'template',
        'template': {'name': cfg.get('whatsapp_plantilla') or 'alerta_restaurante',
                     'language': {'code': cfg.get('whatsapp_idioma') or 'es_MX'},
                     'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': _texto_para_plantilla(texto)}]}]},
    }).encode('utf-8')
    req = urllib.request.Request(f'https://graph.facebook.com/{version}/{phone_id}/messages', data=cuerpo,
                                 headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=8).read()
        return True, ''
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode('utf-8')).get('error', {})
            return False, (err.get('error_user_msg') or err.get('message') or f'Error {e.code}')[:200]
        except Exception:
            return False, f'Error {e.code}'
    except Exception as e:
        return False, type(e).__name__


def enviar_whatsapp(texto, esperar=False):
    """Manda el aviso a todos los números configurados. Sin esperar (alertas): en segundo plano, nunca frena la venta.
    esperar=True (prueba): devuelve [(número, ok, error)]."""
    cfg = config()
    if not whatsapp_listo(cfg):
        return [] if esperar else False
    destinos = _destinos_whatsapp(cfg)
    if esperar:
        return [(n, *_mandar_whatsapp(n, texto, cfg)) for n in destinos]
    threading.Thread(target=lambda: [_mandar_whatsapp(n, texto, cfg) for n in destinos], daemon=True).start()
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
        enviar_whatsapp(f'{sucursal}: {texto}' if sucursal else texto)
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
        c['whatsapp_listo'] = whatsapp_listo(c)
        c['whatsapp_claves_puestas'] = bool(os.environ.get('WHATSAPP_TOKEN') and os.environ.get('WHATSAPP_PHONE_ID'))
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
    if 'whatsapp_destinos' in d:
        numeros = []
        for n in re.split(r'[,;\n]+', str(d['whatsapp_destinos'] or '')):
            n = re.sub(r'\D', '', n)
            if not n:
                continue
            if len(n) == 10:          # número de México sin lada de país
                n = '52' + n
            if not (11 <= len(n) <= 15):
                return jsonify({'ok': False, 'msg': f'El número {n} no se ve bien: escribe 10 dígitos (o con lada de país).'}), 400
            numeros.append(n)
        if len(numeros) > 5:
            return jsonify({'ok': False, 'msg': 'Máximo 5 números.'}), 400
        nuevo['whatsapp_destinos'] = ','.join(dict.fromkeys(numeros))
    if 'whatsapp_plantilla' in d:
        plantilla = str(d['whatsapp_plantilla'] or '').strip().lower()
        if plantilla and not re.fullmatch(r'[a-z0-9_]{1,60}', plantilla):
            return jsonify({'ok': False, 'msg': 'El nombre de la plantilla lleva solo minúsculas, números y guion bajo.'}), 400
        nuevo['whatsapp_plantilla'] = plantilla or 'alerta_restaurante'
    cfg_guardar(CLAVE_CFG, nuevo)
    return jsonify({'ok': True})


@alertas_bp.route('/api/alertas/prueba', methods=['POST'])
@login_required
def api_alertas_prueba():
    if current_user.role != 'admin':
        return jsonify({'ok': False}), 403
    texto = '✅ Prueba de alertas: si ves esto, las alertas llegan a tu celular.'
    enviado = _enviar_telegram(texto)
    wa = enviar_whatsapp(texto, esperar=True)
    partes = []
    if wa:
        for numero, ok, err in wa:
            partes.append(f'WhatsApp {numero[-4:].rjust(10, "•")}: ' + ('enviado ✓' if ok else f'NO se envió ({err})'))
    elif config().get('whatsapp_destinos') or os.environ.get('WHATSAPP_TOKEN'):
        partes.append('WhatsApp: faltan datos (las claves en Render o los números aquí).')
    partes.append('Telegram: enviado ✓' if enviado else 'Telegram: no configurado.')
    return jsonify({'ok': True, 'enviado': enviado or any(ok for _, ok, _ in wa), 'msg': '\n'.join(partes)})
