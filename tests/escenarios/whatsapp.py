# Se ejecuta dentro de tests/escenario_humo.py (usa app, admin, H, check).
# Alertas por WhatsApp Business: plantilla oficial de Meta a varios números (se simula a Meta: no sale nada real).
import json as _jw
import os as _osw
import alertas as _alw

_T = {'X-CSRFToken': H['X-CSRFToken']}
r = admin.post('/api/alertas/config', json={'whatsapp_destinos': '967 123 4567, +52 967 765 4321', 'whatsapp_plantilla': 'alerta_restaurante'}, headers=_T)
check(r.status_code == 200, 'guardar números de WhatsApp')
c = admin.get('/api/alertas/config').json['config']
check(c['whatsapp_destinos'] == '529671234567,529677654321', f'los números quedan con lada de México ({c["whatsapp_destinos"]})')
check(not c['whatsapp_listo'] and not c['whatsapp_claves_puestas'], 'sin claves de Meta, WhatsApp queda apagado')
check(admin.post('/api/alertas/config', json={'whatsapp_destinos': '123'}, headers=_T).status_code == 400, 'un número mal escrito se rechaza')
check(admin.post('/api/alertas/config', json={'whatsapp_plantilla': 'Alerta Mala!'}, headers=_T).status_code == 400, 'nombre de plantilla inválido se rechaza')

_enviados = []


class _Resp:
    def read(self):
        return b'{"messages":[{"id":"x"}]}'


def _falso_urlopen(req, timeout=0):
    _enviados.append((req.full_url, dict(req.header_items()), _jw.loads(req.data.decode('utf-8'))))
    return _Resp()


_orig = _alw.urllib.request.urlopen
_alw.urllib.request.urlopen = _falso_urlopen
_osw.environ['WHATSAPP_TOKEN'], _osw.environ['WHATSAPP_PHONE_ID'] = 'tok-prueba', '1234567890'
try:
    r = admin.post('/api/alertas/prueba', headers=_T)
    check(r.json['enviado'] and r.json['msg'].count('enviado ✓') >= 2, f'prueba de WhatsApp a los 2 números ({r.json["msg"]})')
    url, hdrs, cuerpo = _enviados[0]
    check('graph.facebook.com' in url and url.endswith('/1234567890/messages') and hdrs.get('Authorization') == 'Bearer tok-prueba',
          'se manda a la API oficial de Meta con el número que envía')
    check(cuerpo['type'] == 'template' and cuerpo['template']['name'] == 'alerta_restaurante' and cuerpo['template']['language']['code'] == 'es_MX',
          'usa la plantilla aprobada (requisito de Meta)')
    _enviados.clear()
    with app.app_context():
        _alw.alertar('PRUEBA', 'Cancelación de $500\nen mesa 4', 'Caminante 1', 500)
    import time as _tw
    for _ in range(50):
        if len(_enviados) >= 2:
            break
        _tw.sleep(0.05)
    _txt = _enviados[0][2]['template']['components'][0]['parameters'][0]['text'] if _enviados else ''
    check(len(_enviados) == 2 and '\n' not in _txt and 'Caminante 1' in _txt, f'una alerta real llega a ambos números sin saltos de línea ({_txt})')
    check(admin.get('/api/alertas/config').json['config']['whatsapp_listo'], 'con claves y números, WhatsApp queda listo')
finally:
    _alw.urllib.request.urlopen = _orig
    _osw.environ.pop('WHATSAPP_TOKEN', None)
    _osw.environ.pop('WHATSAPP_PHONE_ID', None)
    admin.post('/api/alertas/config', json={'whatsapp_destinos': ''}, headers=_T)
check("Comensal Conectado: {{1}}" in admin.get('/industrial').get_data(as_text=True), 'la pantalla muestra bien el texto de la plantilla')
