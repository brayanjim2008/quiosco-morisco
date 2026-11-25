"""Pruebas automáticas de Comensal Conectado.

La app lee DATABASE_URL/SECRET_KEY al importarse, así que cada escenario corre en su propio proceso
(base de datos temporal y limpia en cada corrida). Correr con:   python -m pytest -q
"""
import os
import subprocess
import sys

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
PROYECTO = os.path.dirname(AQUI)
USA_POSTGRES = bool(os.environ.get('PRUEBAS_DATABASE_URL', '').strip())


def _correr(script):
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONWARNINGS='ignore')
    return subprocess.run([sys.executable, os.path.join(AQUI, script)], cwd=PROYECTO, env=env,
                          capture_output=True, text=True, encoding='utf-8', timeout=900)


def _resumen(r):
    lineas = (r.stdout or '').splitlines()
    fallos = [l for l in lineas if l.startswith('FALLO')]
    cola = '\n'.join(lineas[-25:])
    return f"{len(fallos)} comprobación(es) fallaron:\n" + '\n'.join(fallos) + \
        f"\n\n--- final de la salida ---\n{cola}\n--- stderr ---\n{(r.stderr or '')[-3000:]}"


def test_escenario_completo():
    """~200 comprobaciones: roles y pantallas, CSRF/XSS, cobro y cambio, pre-órdenes por sucursal, PINs,
    nómina, cola de impresión, límite de intentos, caché compartida, costo promedio y conteo físico."""
    r = _correr('escenario_humo.py')
    ok = sum(1 for l in (r.stdout or '').splitlines() if l.startswith('OK'))
    assert r.returncode == 0 and 'RESULTADO: TODO OK' in r.stdout, _resumen(r)
    assert ok >= 150, f'Se esperaban al menos 150 comprobaciones y corrieron {ok}.'


@pytest.mark.skipif(USA_POSTGRES, reason='Escenario de arranque usa archivos SQLite (DROP COLUMN) a propósito.')
def test_arranque_detecta_esquema_faltante():
    """ESQUEMA_REQUERIDO: con una columna faltante o una base vacía, la app migra sola al arrancar."""
    r = _correr('escenario_arranque.py')
    assert r.returncode == 0, _resumen(r)
