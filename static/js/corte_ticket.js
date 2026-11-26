/* Texto de los cortes X / Z (40 columnas, ticket 80 mm) con el orden de Soft Restaurant.
   Lo usan la Caja (al cerrar) y Reportes (historial de cortes) para que el ticket reimpreso sea idéntico. */
// ---------- Texto del corte con el mismo orden que el de Soft Restaurant (40 columnas, ticket 80 mm) ----------
const ANCHO_CORTE = 40;
function _lnC(etq, val) {
  etq = String(etq); val = String(val);
  const esp = Math.max(1, ANCHO_CORTE - etq.length - val.length);
  return etq + ' '.repeat(esp) + val;
}
function _centroC(t) { t = String(t); return ' '.repeat(Math.max(0, Math.floor((ANCHO_CORTE - t.length) / 2))) + t; }
function _$C(v) { return '$' + Number(v || 0).toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
const _RAYA_C = '='.repeat(ANCHO_CORTE), _GUION_C = '-'.repeat(ANCHO_CORTE);

function textoCorteSoft(d, titulo, sucursal) {
  const x = d.detalle || {};
  const n = v => Number(v || 0);
  const tarjeta = n(d.tarj_debito) + n(d.tarj_credito);
  const totalFormas = n(d.efectivo) + tarjeta + n(d.transferencia) + n(d.vales_empleado) + n(d.credito_clientes);
  const L = [];
  L.push(_centroC('COMENSAL CONECTADO'), _centroC(String(sucursal || '').toUpperCase()), _centroC(titulo));
  L.push(`DEL ${d.apertura}`, `AL  ${d.ahora}`, `TURNO: ${d.turno_id || '-'}   CAJERO: ${d.cajero || (typeof USUARIO_POS !== 'undefined' ? USUARIO_POS : '')}`);
  L.push(_RAYA_C, _centroC('CAJA'));
  L.push(_lnC('+FONDO INICIAL:', _$C(d.fondo_inicial)), _lnC('+EFECTIVO:', _$C(d.efectivo)), _lnC('+TARJETA:', _$C(tarjeta)),
         _lnC('+TRANSFERENCIA:', _$C(d.transferencia)), _lnC('+VALES:', _$C(d.vales_empleado)), _lnC('+CREDITO CLIENTES:', _$C(d.credito_clientes)),
         _lnC('+DEPOSITOS EFE:', _$C(d.depositos)), _lnC('-RETIROS EFECT:', _$C(d.retiros)), _lnC('-PROPINAS PAGADAS:', _$C(d.propinas_pagadas)));
  L.push(_GUION_C, _lnC('=SALDO FINAL:', _$C(d.saldo_final)), _lnC('=EFECTIVO FINAL:', _$C(d.efectivo_final)));
  L.push(_RAYA_C, _centroC('FORMA DE PAGO VENTAS'));
  L.push(_lnC('EFECTIVO:', _$C(d.efectivo)), _lnC('TARJ. DEBITO:', _$C(d.tarj_debito)), _lnC('TARJ. CREDITO:', _$C(d.tarj_credito)),
         _lnC('TRANSFERENCIA:', _$C(d.transferencia)), _lnC('VALES:', _$C(d.vales_empleado)), _lnC('CREDITO CLIENTES:', _$C(d.credito_clientes)));
  L.push(_GUION_C, _lnC('TOTAL FORMAS', _$C(totalFormas)));
  L.push(_centroC('FORMA DE PAGO PROPINA'), _lnC('TARJETA:', _$C(d.propinas_pagadas)), _lnC('TOTAL FORMAS PAGO', _$C(d.propinas_pagadas)));
  if (x.por_tipo) {
    L.push(_RAYA_C, _centroC('VENTA (NO INCLUYE IMPUESTOS)'), _centroC('POR TIPO DE PRODUCTO'));
    x.por_tipo.forEach(t => L.push(_lnC(t.tipo + ':', `${_$C(t.venta)} (${t.pct}%) ${t.cantidad}`)));
    L.push(_centroC('POR TIPO DE SERVICIO'));
    x.por_servicio.forEach(s => L.push(_lnC(s.tipo + ':', `${_$C(s.venta)} (${s.pct}%)`)));
    L.push(_GUION_C, _lnC('SUBTOTAL:', _$C(x.subtotal)), _lnC('-DESCUENTOS:', _$C(x.descuentos)), _lnC('VENTA NETA:', _$C(x.venta_neta)));
    L.push(_GUION_C, _lnC('VENTA 16%:', _$C(x.venta_neta)), _lnC('IMPUESTO 16%:', _$C(x.impuestos)), _lnC('IMPUESTOS TOTAL:', _$C(x.impuestos)));
    L.push(_lnC('VENTAS CON IMP.:', _$C(x.ventas_con_imp)));
    L.push(_RAYA_C);
    L.push(_lnC('CUENTAS NORMALES:', x.cuentas_normales), _lnC('CUENTAS CANCELADAS:', x.cuentas_canceladas),
           _lnC('CUENTAS CON DESCUENTO:', x.cuentas_descuento), _lnC('CUENTAS CON CORTESIA:', x.cuentas_cortesia),
           _lnC('CUENTA PROMEDIO:', _$C(x.cuenta_promedio)), _lnC('CONSUMO PROMEDIO:', _$C(x.consumo_promedio)),
           _lnC('COMENSALES:', x.comensales), _lnC('PROPINAS:', _$C(d.propinas_pagadas)),
           _lnC('FOLIO INICIAL:', x.folio_inicial), _lnC('FOLIO FINAL:', x.folio_final));
    x.cortesias.forEach(c => L.push(_lnC('CORTESIA ' + c.tipo + ':', _$C(c.monto))));
    L.push(_GUION_C, _lnC('TOTAL CORTESIAS:', _$C(x.total_cortesias)));
    x.descuentos_tipo.forEach(c => L.push(_lnC('DESCUENTO ' + c.tipo + ':', _$C(c.monto))));
    L.push(_GUION_C, _lnC('TOTAL DESCUENTOS:', _$C(x.total_descuentos)));
  }
  if (x.folios_mesero) {
    L.push(_RAYA_C, _centroC('FOLIOS POR MESERO'));
    x.folios_mesero.forEach(m => L.push(_lnC(m.mesero.slice(0, 16) + ':', `${m.folio_min} a ${m.folio_max}`), _lnC('  ' + m.cuentas + ' CTAS', _$C(m.venta))));
    if (!x.folios_mesero.length) L.push('SIN VENTAS');
    L.push(_RAYA_C, _centroC('CREDITOS COBRADOS'));
    (x.creditos_cobrados_lista || []).forEach(c => L.push(_lnC(c.concepto.slice(0, 22), _$C(c.monto))));
    L.push(_lnC('TOTAL CREDITOS COBRADOS:', _$C(x.creditos_cobrados)));
    L.push(_RAYA_C, _centroC('GASTOS DEL TURNO'));
    (x.gastos || []).forEach(g => L.push(_lnC((g.categoria ? g.categoria + ' ' : '') + g.concepto, _$C(g.monto))));
    L.push(_lnC('TOTAL GASTOS:', _$C(x.total_gastos)));
  }
  L.push(_RAYA_C);
  return L.join('\n');
}

function lineasExtrasZ(ex) {
  if (!ex) return '';
  const L = ['', _RAYA_C, _centroC('VALES Y FACTURAS'),
    _lnC('VALES ADO:', ex.vales_ado), _lnC('VALES OCC DESAYUNO:', ex.vales_occ_desayuno),
    _lnC('VALES OCC COMIDA:', ex.vales_occ_comida), _lnC('VALES OCC CENA:', ex.vales_occ_cena),
    _lnC('FACTURA FOLIO INICIAL:', ex.factura_folio_inicial || '-'), _lnC('FACTURA FOLIO FINAL:', ex.factura_folio_final || '-')];
  if (ex.aclaraciones) L.push(_GUION_C, 'ACLARACIONES:', ...String(ex.aclaraciones).match(/.{1,40}/g));
  return '\n' + L.join('\n');
}

function textoDeclaracionCajero(decl, d) {
  const L = [_centroC('DECLARACION DE CAJERO'), _centroC('POR TIPO DE FORMA DE PAGO'),
             ' '.repeat(16) + 'DECLARADO'.padStart(12) + 'DIFERENCIA'.padStart(12)];
  let totDec = 0, totDif = 0;
  (decl || []).forEach(r => {
    totDec += Number(r.declarado); totDif += Number(r.diferencia);
    L.push((r.forma + ':').padEnd(16) + _$C(r.declarado).padStart(12) + _$C(r.diferencia).padStart(12));
  });
  L.push(_GUION_C, 'TOTAL:'.padEnd(16) + _$C(totDec).padStart(12));
  L.push(_lnC('SOBRANTE(+) O FALTANTE(-):', _$C(d.diferencia)));
  const conDif = (decl || []).filter(r => Math.abs(Number(r.diferencia)) >= 0.01);
  if (conDif.length) {
    L.push(_GUION_C, _centroC('SOBRANTE(+) O FALTANTE(-)'), _centroC('POR FORMA DE PAGO'));
    conDif.forEach(r => L.push(_lnC(r.forma + ':', _$C(r.diferencia))));
  }
  return L.join('\n');
}

function lineasDenominacionesZ(lista) {
  if (!lista || !lista.length) return '';
  const filas = lista.map(x => `${x.tipo === 'BILLETE' ? 'B' : 'M'} $${x.valor} x ${x.piezas} = $${Number(x.importe).toFixed(2)}`);
  return '\nEFECTIVO POR DENOMINACION:\n' + filas.join('\n') + '\n================================';
}


function textoZCompleto(d, cajeroDefault) {
  const cajero = (d.corte && d.corte.cajero) || cajeroDefault || '';
  return (d.corte ? textoCorteSoft(d.corte, 'CORTE DE CAJA Z (CIERRE)', d.sucursal) + '\n' + textoDeclaracionCajero(d.declaracion, d)
    : `COMENSAL CONECTADO - CORTE Z\n${d.sucursal}\nESPERADO: $${d.esperado}\nDECLARADO: $${d.declarado}\nDIFERENCIA: $${d.diferencia}`)
    + lineasDenominacionesZ(d.denominaciones)
    + lineasExtrasZ(d.extras)
    + `\n\n\n________________   ________________\n RESPONSABLE        CAJERO: ${cajero}`
    + (d.extras && d.extras.responsable ? `\n ${d.extras.responsable}` : '');
}
