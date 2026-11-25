"""(Solo SQLite) Arranque con esquema incompleto: la app debe detectarlo (ESQUEMA_REQUERIDO) y migrar sola sin RUN_DB_INIT."""
import os, sqlite3, subprocess, sys, tempfile

PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db = os.path.join(tempfile.mkdtemp(), 'arranque.db')
env = dict(os.environ, SECRET_KEY='x', DATABASE_URL='sqlite:///' + db.replace(os.sep, '/'), PYTHONWARNINGS='ignore')

def correr(run_init, codigo):
    e = dict(env, RUN_DB_INIT=run_init)
    return subprocess.run([sys.executable, '-c', codigo], cwd=PROYECTO, env=e, capture_output=True, text=True)

# 1) Base completa
r = correr('1', 'import app')
assert r.returncode == 0, r.stderr[-800:]

# 2) Romper el esquema: quitar una columna requerida y vaciar usuarios (para saber si se re-inicializa)
con = sqlite3.connect(db)
con.execute('ALTER TABLE cola_impresion_pos DROP COLUMN reclamado_por')
con.execute('DELETE FROM "user"')
con.commit(); con.close()

# 3) Arrancar SIN RUN_DB_INIT
codigo = ("import app\n"
          "with app.app.app_context():\n"
          "    print('USUARIOS', app.User.query.count())\n"
          "    print('FALTAN', app.esquema_faltante(app.db.engine))\n")
r = correr('0', codigo)
salida = r.stdout + r.stderr
ok_detecta = 'Esquema incompleto, migrando: cola_impresion_pos.reclamado_por' in salida
ok_migro = 'USUARIOS 11' in r.stdout
print('OK   ' if ok_detecta else 'FALLO', 'arranque detecta columna faltante y lo registra en el log')
print('OK   ' if ok_migro else 'FALLO', 'arranque corre inicializar_sistema sin RUN_DB_INIT (usuarios recreados)')
# En SQLite "ADD COLUMN IF NOT EXISTS" no existe, así que la columna sigue faltando y se registra el error;
# en PostgreSQL (Neon) el ALTER sí la crea. Aquí solo se valida que el aviso de error funcione.
ok_aviso = 'Tras migrar siguen faltando: cola_impresion_pos.reclamado_por' in salida
print('OK   ' if ok_aviso else 'FALLO', 'si algo no se pudo migrar, queda error en el log')

# 4) Base nueva y vacía, sin RUN_DB_INIT
db2 = os.path.join(tempfile.mkdtemp(), 'nueva.db')
e2 = dict(env, DATABASE_URL='sqlite:///' + db2.replace(os.sep, '/'), RUN_DB_INIT='0')
r = subprocess.run([sys.executable, '-c', codigo], cwd=PROYECTO, env=e2, capture_output=True, text=True)
ok_nueva = 'USUARIOS 11' in r.stdout and 'FALTAN []' in r.stdout
print('OK   ' if ok_nueva else 'FALLO', 'base nueva vacía: crea todo y no falta nada')
if not (ok_detecta and ok_migro and ok_aviso and ok_nueva):
    print(salida[-1500:])

sys.exit(0 if (ok_detecta and ok_migro and ok_aviso and ok_nueva) else 1)
