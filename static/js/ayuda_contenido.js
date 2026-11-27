/* Textos de ayuda por pantalla (botón "Ayuda" o tecla F1). Lenguaje sencillo, pasos cortos. */
window.AYUDAS = {
  '/platillos': {
    titulo: 'Menú y Platillos: todo el menú en un solo lugar',
    secciones: [
      { t: 'Cambiar o crear un platillo', pasos: [
        'Busca el platillo en la lista de la izquierda (o toca "+ Nuevo").',
        'Cambia nombre, precio, categoría, foto o descripción y toca "Guardar platillo".',
        '"¿Dónde se prepara?": Cocina o Barra decide a qué impresora sale su comanda.',
        '"Traducir" llena el inglés solo; revísalo antes de guardar.',
        'Si hoy no hay, marca "Agotado" en lugar de borrarlo.'] },
      { t: 'Lo que se pregunta al pedirlo (modificadores)', pasos: [
        'En "Al pedirlo, preguntar" agrega las preguntas en orden: por ejemplo 1. Tipo de leche, 2. Sabor, 3. Temperatura.',
        'Obligatorio = el mesero no puede seguir sin elegir. Una = solo una opción; Varias = puede marcar varias.',
        'Debajo de cada pregunta ves sus opciones y lo que cobran extra. Toca "Guardar preguntas".'] },
      { t: 'Precio por sucursal', pasos: [
        'Escribe el precio de esa sucursal (vacío = precio general) o quita la palomita si ahí no se vende. Se guarda solo.'] },
      { t: 'Categorías y modificadores', pasos: [
        '"2. Categorías": nombre, inglés y el ícono (o foto) del círculo que ve el cliente en el menú.',
        '"3. Modificadores": agrega opciones a un grupo (ej. LECHE DE AVENA +$8 en TIPO DE LECHE) o cambia su precio y toca ✓.'] },
    ],
  },
  '/pos': {
    titulo: 'Caja: cómo se trabaja',
    secciones: [
      { t: 'Al llegar (una vez por turno)', pasos: [
        'Toca "Abrir turno", escribe el dinero con el que empieza la caja (fondo) y presiona "Abrir Turno".',
        'Sin turno abierto no se puede abrir mesas ni cobrar: el sistema te lo pedirá.'] },
      { t: 'Atender una mesa (los 4 pasos de la barra de abajo)', pasos: [
        'Entra a "Mesas", toca "+ Mesa", elige la mesa y cuántas personas.',
        '① CAPTURAR: agrega los platillos y bebidas.',
        '② ENVIAR A COCINA: imprime la comanda en cocina o barra.',
        '③ IMPRIMIR CUENTA: cuando el cliente la pida (sale con su QR/PIN de puntos). Si algo no se había enviado, se envía solo.',
        '④ COBRAR: toca la forma de pago (botones grandes de la izquierda), escribe con cuánto paga o usa "Exacto" / $100 / $200 / $500, y ACEPTAR (F2). Sale la nota de consumo.',
        'Pago con tarjeta y propina: toca PROPINA y elige 10%, 15% o 20%; abajo dice cuánto cobrar en la terminal.'] },
      { t: 'Si algo cambia', pasos: [
        'Cancelar un producto o hacer un descuento pide la clave del gerente.',
        'Para agregar algo a una cuenta ya impresa, usa "Más opciones → Reabrir" (pide clave).',
        'Mover de mesa, dividir o juntar cuentas están en la columna derecha y en "Más opciones".'] },
      { t: 'Al terminar el turno', pasos: [
        'Toca "Corte" para ver cuánto se vendió (Corte X).',
        'Para cerrar: "Cerrar Turno (Corte Z)", cuenta el dinero, escribe lo de cada forma de pago y confirma. Se imprime el corte.',
        'Después del Z la caja queda sin turno hasta que el siguiente cajero abra el suyo.'] },
    ],
  },
  '/mesero_dashboard': {
    titulo: 'Tablet del mesero',
    secciones: [
      { t: 'Tomar una orden', pasos: [
        'Toca tu mesa (verde = libre). Si es nueva, escoge cuántas personas.',
        'Elige la categoría y toca los platillos. Puedes agregar notas (sin cebolla, término, etc.).',
        'Revisa la ronda y toca "Enviar": la comanda sale en cocina y barra.'] },
      { t: 'La cuenta', pasos: [
        'Cuando el cliente la pida, toca "Pedir cuenta": la caja recibe el aviso.',
        'Solo ves tus propias mesas; las de otros meseros no aparecen.'] },
    ],
  },
  '/kds': {
    titulo: 'Pantalla de Cocina / Barra',
    secciones: [
      { t: 'Cómo se usa', pasos: [
        'Cada tarjeta es una comanda, la más antigua primero. El color avisa cuánto tiempo lleva.',
        'Toca "Listo" cuando el platillo esté terminado para que desaparezca de la lista.'] },
    ],
  },
  '/reservaciones': {
    titulo: 'Reservaciones',
    secciones: [
      { t: 'Cómo se usa', pasos: [
        'Captura nombre, teléfono, fecha, hora y personas, y asígnale una mesa.',
        'Cuando el cliente llegue, márcala como "Llegó": se abre su cuenta en esa mesa.'] },
    ],
  },
  '/nomina_creditos': {
    titulo: 'Créditos, checador y nómina',
    secciones: [
      { t: 'Checador (todos los empleados)', pasos: [
        'En "Checador PIN" cada empleado escribe su PIN y toca "Checar": la primera vez del día es ENTRADA y la siguiente SALIDA.'] },
      { t: 'Créditos de clientes', pasos: [
        'En "Créditos Pendientes" ves lo que debe cada cliente.',
        'Para cobrar un abono, toca "Abonar", escribe el monto y si entra a la caja.'] },
      { t: 'Nómina (solo Admin)', pasos: [
        '"Personal Activo": alta de empleados con su ficha, documentos y PIN.',
        '"Descuentos, Aguinaldo...": elige al empleado y registra lo que corresponda.',
        '"Pagar Nómina": elige al empleado; el sistema suma y resta solo (vales, permisos, faltas, prima) e imprime el recibo.'] },
    ],
  },
  '/industrial': {
    titulo: 'Reportes (dueño / administración)',
    secciones: [
      { t: 'Lo más usado', pasos: [
        '"Ventas 4 Sucursales": cuánto se ha vendido hoy en cada sucursal.',
        '"Cortes Z": elige fechas y sucursal; con "Ver" abres y reimprimes cualquier corte, aunque sea de hace un año.',
        '"Asistencia": quién checó y a qué hora, por fechas; se baja a Excel.',
        '"Cancelaciones": quién canceló qué y quién lo autorizó.',
        '"Reportes / Fechas": ventas por producto, categoría y mesero en cualquier periodo.'] },
    ],
  },
  '/pedidos_sucursal': {
    titulo: 'Sucursal: pedidos a bodega',
    secciones: [
      { t: 'Pedir mercancía', pasos: [
        'Elige los insumos y cantidades que necesitas y envía el pedido a bodega.',
        'Cuando llegue la mercancía, confirma lo que recibiste.'] },
      { t: 'Mermas y checador', pasos: [
        'Las mermas (algo que se tiró o se echó a perder) piden la clave del gerente.',
        'El personal checa con su PIN desde el botón "Abrir Checador por PIN".'] },
    ],
  },
  '/almacen_pro': {
    titulo: 'Bodega',
    secciones: [
      { t: 'Cómo se usa', pasos: [
        'Revisa los pedidos de las sucursales, surte y márcalos como enviados.',
        'Registra las compras que llegan de los proveedores para que suba el inventario.',
        'Haz conteos físicos para corregir diferencias de inventario.'] },
    ],
  },
  '/cajero_dashboard': {
    titulo: 'PINs de fidelidad',
    secciones: [
      { t: 'Cómo se usa', pasos: [
        'Genera PINs para que los clientes acumulen puntos en el menú digital.',
        'Normalmente no hace falta: el PIN sale solo en el ticket al cobrar.'] },
    ],
  },
  '/admin_dashboard': {
    titulo: 'Administración',
    secciones: [
      { t: 'Cómo se usa', pasos: [
        'Aquí se dan de alta usuarios (cajeros, meseros, gerentes) y sus contraseñas.',
        'También se editan premios, anuncios, galería y datos del ticket.',
        'Los platillos, categorías y modificadores se cambian en "Menú" (botón de arriba): todo en un solo lugar.'] },
    ],
  },
};
