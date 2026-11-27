"""Reportes del dueño: análisis de platillos (barras) y estado de resultados por mes y sucursal.

Estado de resultados (todo sin IVA):
    Ventas netas  = cuentas cobradas / 1.16 (los precios del menú incluyen IVA; los descuentos ya están restados)
  − Costo de lo vendido = cantidad vendida × costo de su receta (al costo actual de los insumos)
  − Mermas       = lo tirado/caducado (costo registrado)
  − Gastos       = retiros de caja con categoría de gasto
  − Nómina       = recibos de nómina pagados (sin las propinas, que vienen de los clientes)
  = Utilidad
Las compras a proveedores NO se restan aparte: entran como costo al venderse (si se restaran, se contarían dos veces).
"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import and_, false, func, or_

from models import (
    db, ahora_local, CuentaPOS, DetallePOS, RecetaPOS, InsumoBodegaPro, Producto, RegistroMerma,
    MovimientoCajaPOS, TurnoPOS, ReciboNominaPOS, SUCURSALES_OFICIALES,
)

reportes_bp = Blueprint('reportes', __name__)
IVA_FACTOR = 1.16
MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def _solo_admin():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'msg': 'Solo el administrador ve estos reportes.'}), 403
    return None


def _sucursal_arg():
    suc = request.args.get('sucursal', 'TODAS')
    return suc if suc in SUCURSALES_OFICIALES else 'TODAS'


def _rango_arg():
    """?desde=AAAA-MM-DD&hasta=AAAA-MM-DD (incluido). Sin fechas: este mes."""
    hoy = ahora_local().replace(tzinfo=None)
    try:
        ini = datetime.strptime(request.args.get('desde', '')[:10], '%Y-%m-%d')
    except ValueError:
        ini = hoy.replace(day=1)
    try:
        fin = datetime.strptime(request.args.get('hasta', '')[:10], '%Y-%m-%d')
    except ValueError:
        fin = hoy
    if fin < ini:
        ini, fin = fin, ini
    if (fin - ini).days > 400:
        raise ValueError('Rango demasiado grande')
    ini = ini.replace(hour=0, minute=0, second=0, microsecond=0)
    fin = fin.replace(hour=0, minute=0, second=0, microsecond=0)
    return ini, fin + timedelta(days=1)


def costos_unitarios():
    """{NOMBRE EN MAYÚSCULAS o >MODIFICADOR: costo de su receta} al costo actual de los insumos."""
    costo_ins = {i.id: float(i.costo_unitario or 0.0) for i in InsumoBodegaPro.query.all()}
    costos = {}
    for r in RecetaPOS.query.all():
        k = (r.platillo_nombre or '').strip().upper()
        costos[k] = costos.get(k, 0.0) + float(r.cantidad_descontar or 0.0) * costo_ins.get(r.insumo_id, 0.0)
    return costos


def _cond_vendidas(ini, fin, suc):
    """Cuentas cuyos productos cuentan como vendidos en el periodo. Las subcuentas de "partes iguales" solo
    llevan una línea PARTE n/N: los platillos reales están en la cuenta padre (DIVIDIDA)."""
    q = CuentaPOS.query.filter(CuentaPOS.estado == 'PAGADA', CuentaPOS.cierre >= ini, CuentaPOS.cierre < fin)
    if suc != 'TODAS':
        q = q.filter(CuentaPOS.sucursal == suc)
    padres = list({c.parent_cuenta_id for c in q.filter(CuentaPOS.es_subcuenta_parte.is_(True)).all() if c.parent_cuenta_id})
    return or_(and_(CuentaPOS.estado == 'PAGADA', CuentaPOS.es_subcuenta_parte.is_not(True),
                    CuentaPOS.cierre >= ini, CuentaPOS.cierre < fin),
               CuentaPOS.id.in_(padres) if padres else false())


def _lineas_vendidas(ini, fin, suc):
    """[(descripcion, es_modificador, cantidad, importe)] agrupado."""
    q = db.session.query(DetallePOS.descripcion, DetallePOS.es_modificador,
                         func.coalesce(func.sum(DetallePOS.cantidad), 0.0), func.coalesce(func.sum(DetallePOS.importe), 0.0)
                         ).join(CuentaPOS, CuentaPOS.id == DetallePOS.cuenta_id).filter(_cond_vendidas(ini, fin, suc))
    if suc != 'TODAS':
        q = q.filter(CuentaPOS.sucursal == suc)
    return q.group_by(DetallePOS.descripcion, DetallePOS.es_modificador).all()


def _clave_costo(desc, es_mod):
    d = (desc or '').strip().upper()
    if es_mod or d.startswith('>'):
        return '>' + d.lstrip('>').strip()
    return d


def resultados_periodo(ini, fin, suc, costos=None):
    costos = costos if costos is not None else costos_unitarios()
    qc = db.session.query(func.coalesce(func.sum(CuentaPOS.total), 0.0)).filter(
        CuentaPOS.estado == 'PAGADA', CuentaPOS.cierre >= ini, CuentaPOS.cierre < fin)
    if suc != 'TODAS':
        qc = qc.filter(CuentaPOS.sucursal == suc)
    venta_con_iva = float(qc.scalar() or 0.0)
    ventas = venta_con_iva / IVA_FACTOR

    costo, importe_con_receta, importe_total = 0.0, 0.0, 0.0
    for desc, es_mod, cant, imp in _lineas_vendidas(ini, fin, suc):
        c_u = costos.get(_clave_costo(desc, es_mod))
        importe_total += float(imp or 0.0)
        if c_u is not None:
            costo += c_u * float(cant or 0.0)
            importe_con_receta += float(imp or 0.0)

    qm = db.session.query(func.coalesce(func.sum(RegistroMerma.costo_total), 0.0)).filter(
        RegistroMerma.fecha >= ini, RegistroMerma.fecha < fin)
    if suc != 'TODAS':
        qm = qm.filter(RegistroMerma.sucursal == suc)
    mermas = float(qm.scalar() or 0.0)

    qg = db.session.query(func.coalesce(func.sum(MovimientoCajaPOS.monto), 0.0)).join(
        TurnoPOS, TurnoPOS.id == MovimientoCajaPOS.turno_id).filter(
        MovimientoCajaPOS.tipo == 'RETIRO', MovimientoCajaPOS.fecha >= ini, MovimientoCajaPOS.fecha < fin)
    if suc != 'TODAS':
        qg = qg.filter(TurnoPOS.sucursal == suc)
    gastos = float(qg.scalar() or 0.0)

    qn = db.session.query(func.coalesce(func.sum(ReciboNominaPOS.total_neto), 0.0),
                          func.coalesce(func.sum(ReciboNominaPOS.propinas), 0.0)).filter(
        ReciboNominaPOS.fecha >= ini, ReciboNominaPOS.fecha < fin)
    if suc != 'TODAS':
        qn = qn.filter(ReciboNominaPOS.sucursal == suc)
    neto, propinas = qn.one()
    nomina = max(0.0, float(neto or 0.0) - float(propinas or 0.0))

    utilidad = ventas - costo - mermas - gastos - nomina
    r2 = lambda x: round(x, 2)  # noqa: E731
    return {
        'venta_con_iva': r2(venta_con_iva), 'iva': r2(venta_con_iva - ventas), 'ventas': r2(ventas),
        'costo': r2(costo), 'utilidad_bruta': r2(ventas - costo), 'mermas': r2(mermas), 'gastos': r2(gastos),
        'nomina': r2(nomina), 'utilidad': r2(utilidad),
        'margen_pct': round(utilidad / ventas * 100, 1) if ventas > 0 else None,
        'cobertura_recetas_pct': round(importe_con_receta / importe_total * 100, 1) if importe_total > 0 else None,
    }


@reportes_bp.route('/api/reportes/platillos')
@login_required
def api_reportes_platillos():
    """Por platillo: cuántos se vendieron, cuánto dejaron y cuánto ganaron (si tiene receta)."""
    err = _solo_admin()
    if err:
        return err
    ini, fin = _rango_arg()
    suc = _sucursal_arg()
    costos = costos_unitarios()
    cat_map = {p.nombre.strip().upper(): p.categoria or '' for p in Producto.query.all()}
    filas = []
    for desc, es_mod, cant, imp in _lineas_vendidas(ini, fin, suc):
        nombre = (desc or '').strip()
        if es_mod or nombre.startswith('>') or nombre.upper().startswith('PARTE ') or not nombre or nombre.startswith('='):
            continue
        cant, imp = float(cant or 0.0), float(imp or 0.0)
        c_u = costos.get(nombre.upper())
        venta_sin_iva = imp / IVA_FACTOR
        filas.append({
            'platillo': nombre, 'categoria': cat_map.get(nombre.upper(), ''), 'cantidad': round(cant, 2),
            'venta': round(imp, 2), 'costo_unitario': None if c_u is None else round(c_u, 2),
            'utilidad': None if c_u is None else round(venta_sin_iva - c_u * cant, 2),
        })
    vendidos = {f['platillo'].upper() for f in filas}
    sin_venta = [{'platillo': p.nombre, 'categoria': p.categoria, 'precio': p.precio}
                 for p in Producto.query.order_by(Producto.categoria.asc(), Producto.nombre.asc()).all()
                 if p.nombre.strip().upper() not in vendidos and not p.agotado]
    return jsonify({'ok': True, 'desde': ini.strftime('%Y-%m-%d'), 'hasta': fin.strftime('%Y-%m-%d'),
                    'platillos': filas, 'sin_venta': sin_venta,
                    'total_venta': round(sum(f['venta'] for f in filas), 2)})


@reportes_bp.route('/api/reportes/estado_resultados')
@login_required
def api_reportes_estado_resultados():
    """Mes por mes del año elegido (hasta el mes actual) y el total del año."""
    err = _solo_admin()
    if err:
        return err
    hoy = ahora_local()
    try:
        anio = int(request.args.get('anio') or hoy.year)
    except ValueError:
        anio = hoy.year
    anio = max(2020, min(hoy.year, anio))
    suc = _sucursal_arg()
    costos = costos_unitarios()
    ultimo_mes = hoy.month if anio == hoy.year else 12
    meses = []
    for m in range(1, ultimo_mes + 1):
        ini = datetime(anio, m, 1)
        fin = datetime(anio + 1, 1, 1) if m == 12 else datetime(anio, m + 1, 1)
        r = resultados_periodo(ini, fin, suc, costos)
        r['mes'] = MESES[m - 1]
        r['numero'] = m
        meses.append(r)
    claves = ('venta_con_iva', 'iva', 'ventas', 'costo', 'utilidad_bruta', 'mermas', 'gastos', 'nomina', 'utilidad')
    total = {k: round(sum(x[k] for x in meses), 2) for k in claves}
    total['margen_pct'] = round(total['utilidad'] / total['ventas'] * 100, 1) if total['ventas'] > 0 else None
    cob = [x['cobertura_recetas_pct'] for x in meses if x['cobertura_recetas_pct'] is not None]
    total['cobertura_recetas_pct'] = round(sum(cob) / len(cob), 1) if cob else None
    return jsonify({'ok': True, 'anio': anio, 'sucursal': suc, 'meses': meses, 'total': total})
