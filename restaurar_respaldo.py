"""Restaura un respaldo (.zip de Administración → Respaldo) en una base de datos VACÍA.

Uso (en una terminal, con la base NUEVA en DATABASE_URL):
    set DATABASE_URL=postgresql://usuario:clave@host/base      (Windows)
    set SECRET_KEY=cualquier-texto
    python restaurar_respaldo.py respaldo_restaurante_20261127_2300.zip

No borra nada: si la base ya tiene ventas, se detiene para no mezclar información.
"""
import json
import sys
import zipfile
from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, Time, text


def _convertir(col, valor):
    if valor is None:
        return None
    tipo = col.type
    if isinstance(tipo, DateTime):
        return datetime.fromisoformat(valor)
    if isinstance(tipo, Date):
        return date.fromisoformat(valor[:10])
    if isinstance(tipo, Time):
        return time.fromisoformat(valor)
    return valor


def restaurar(ruta_zip, app, db, forzar=False, salida=print):
    with zipfile.ZipFile(ruta_zip) as z, app.app_context():
        manifiesto = json.loads(z.read('manifiesto.json'))
        db.create_all()
        tablas = {t.name: t for t in db.metadata.sorted_tables}
        if not forzar:
            with db.engine.connect() as cx:
                if cx.execute(text('SELECT COUNT(*) FROM cuentas_pos')).scalar():
                    raise SystemExit('La base de datos destino ya tiene ventas. Usa una base vacía.')
        # Se vacían las tablas que el arranque llena solo (usuarios, catálogos de ejemplo) y se cargan las del respaldo.
        with db.engine.begin() as cx:
            for t in reversed(db.metadata.sorted_tables):
                if t.name in manifiesto['tablas']:
                    cx.execute(t.delete())
            for nombre in manifiesto['orden']:
                t = tablas.get(nombre)
                if t is None:
                    salida(f'  (se omite {nombre}: ya no existe en esta versión)')
                    continue
                cols = {c.name: c for c in t.columns}
                lote, total = [], 0
                with z.open(f'tablas/{nombre}.jsonl') as f:
                    for renglon in f:
                        fila = json.loads(renglon)
                        lote.append({k: _convertir(cols[k], v) for k, v in fila.items() if k in cols})
                        if len(lote) >= 1000:
                            cx.execute(t.insert(), lote)
                            total += len(lote)
                            lote = []
                if lote:
                    cx.execute(t.insert(), lote)
                    total += len(lote)
                salida(f'  {nombre}: {total:,} filas')
            # En PostgreSQL los contadores de id deben seguir después del último restaurado.
            if db.engine.dialect.name == 'postgresql':
                for t in db.metadata.sorted_tables:
                    pk = [c for c in t.primary_key.columns]
                    if len(pk) == 1 and pk[0].autoincrement and str(pk[0].type).upper().startswith('INTEGER'):
                        cx.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('\"{t.name}\"', '{pk[0].name}'), "
                            f"COALESCE((SELECT MAX(\"{pk[0].name}\") FROM \"{t.name}\"), 0) + 1, false)"))
        return manifiesto


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    import app as _app
    from models import db as _db
    m = restaurar(sys.argv[1], _app.app, _db)
    print(f"Listo: respaldo del {m['creado']} restaurado.")
