"""Revisa que ninguna plantilla tenga un texto de JavaScript partido en dos renglones (por ejemplo .join(' + salto de
línea). Ese error de sintaxis invalida TODO el <script> de la pantalla y deja botones sin funcionar."""
import glob
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_sin_textos_js_partidos():
    malos = []
    for ruta in glob.glob(os.path.join(RAIZ, 'templates', '*.html')):
        for n, linea in enumerate(open(ruta, encoding='utf-8').read().split('\n'), start=1):
            # una comilla simple que se abre justo antes del fin de línea, dentro de una llamada o asignación
            if re.search(r"[(=,]\s*'$", linea.rstrip()):
                malos.append(f'{os.path.basename(ruta)}:{n}: {linea.strip()[:80]}')
    assert not malos, 'Texto de JavaScript partido en dos renglones:\n' + '\n'.join(malos)
