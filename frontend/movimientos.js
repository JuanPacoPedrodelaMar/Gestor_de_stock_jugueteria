/**
 * Frontend de la pantalla de Movimientos (venta, ingreso, estropeo, devolución).
 * Consume la API REST del servicio "movimientos" (services/movimientos).
 *
 * Autenticación: reutiliza apiFetch() de app.js, que agrega automáticamente
 * el header Authorization: Bearer <access_token> y maneja el refresco de la
 * sesión.
 *
 * Dropdowns custom (producto, categoría y cliente): no se usa <datalist> ni
 * <select> nativos porque queremos consistencia visual, control total del
 * estilo, y poder mostrar nombres largos en varias líneas. El valor
 * seleccionado se guarda en variables, no se parsea del texto del input.
 * La categoría y el producto se pueden ESCRIBIR para filtrar la lista.
 *
 * El empleado del movimiento no se completa acá: el servidor lo toma del DNI
 * de la sesión. El cliente se elige de la lista o se crea (ver clientes.js).
 */
const MOVIMIENTOS_API_BASE = `${(window.APP_CONFIG && window.APP_CONFIG.MOVIMIENTOS_API_URL) || "http://localhost:8002"}/api/v1`;

const formMovimiento = document.getElementById("form-movimiento");

// Dropdown de productos
const wrapperProducto = document.getElementById("mov-producto-dropdown");
const inputProducto = document.getElementById("mov_producto_input");
const listaProductos = document.getElementById("mov-productos-lista");

// Dropdown de categorías
const wrapperCategoria = document.getElementById("mov-categoria-dropdown");
const inputCategoria = document.getElementById("mov_categoria_input");
const listaCategorias = document.getElementById("mov-categorias-lista");

const campoCantidad = document.getElementById("mov_cantidad");
const tablaMovimientos = document.getElementById("tabla-movimientos");
const btnGuardarMovimiento = document.getElementById("btn-guardar-movimiento");

const ETIQUETAS_CATEGORIA = {
  venta: { texto: "Venta", clase: "badge-venta" },
  ingreso: { texto: "Ingreso", clase: "badge-ingreso" },
  estropeo: { texto: "Estropeo", clase: "badge-estropeo" },
  devolucion: { texto: "Devolución", clase: "badge-devolucion" },
};

const CATEGORIAS_MOVIMIENTO = [
  { valor: "venta", texto: "Venta (descuenta)" },
  { valor: "ingreso", texto: "Ingreso (incrementa)" },
  { valor: "estropeo", texto: "Estropeo (descuenta)" },
  { valor: "devolucion", texto: "Devolución (incrementa)" },
];

const CATEGORIA_POR_DEFECTO = "venta";

// Estado de los dropdowns
let productosDisponibles = [];
let productoSeleccionadoId = null;
let categoriaSeleccionada = CATEGORIA_POR_DEFECTO; // null mientras lo escrito no coincide con ninguna

function formatearFecha(iso) {
  try {
    return new Date(iso).toLocaleString("es-AR");
  } catch (error) {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Carga de productos desde la API
// ---------------------------------------------------------------------------

function textoOpcionProducto(producto) {
  return `#${producto.id_producto} — ${producto.nombre}`;
}

async function cargarOpcionesDeProductos() {
  try {
    const resp = await apiFetch(API_BASE_URL);
    if (!resp.ok) throw new Error("No se pudo obtener el listado de productos.");
    productosDisponibles = await resp.json();
  } catch (error) {
    if (error.sesionExpirada) return;
    productosDisponibles = [];
  }
}

// ---------------------------------------------------------------------------
// Dropdown de productos
// ---------------------------------------------------------------------------

function filtrarProductos(filtro) {
  const texto = (filtro || "").trim().toLowerCase();
  if (!texto) return productosDisponibles;
  return productosDisponibles.filter((p) =>
    textoOpcionProducto(p).toLowerCase().includes(texto)
  );
}

function renderizarListaProductos(filtro) {
  const filtrados = filtrarProductos(filtro);
  if (!filtrados.length) {
    listaProductos.innerHTML = `<div class="dropdown-opcion sin-resultados">Sin coincidencias</div>`;
    return;
  }
  resaltadaProducto = -1;
  listaProductos.innerHTML = filtrados
    .map(
      (p, i) =>
        `<div class="dropdown-opcion" role="option" id="mov-productos-lista-op-${i}" aria-selected="false" data-id="${p.id_producto}">${escaparHtml(textoOpcionProducto(p))}</div>`
    )
    .join("");
}

// Accesibilidad: patrón ARIA combobox/listbox, igual que crearCombo() en app.js.
let resaltadaProducto = -1;
inputProducto.setAttribute("role", "combobox");
inputProducto.setAttribute("aria-autocomplete", "list");
inputProducto.setAttribute("aria-expanded", "false");
inputProducto.setAttribute("aria-controls", "mov-productos-lista");
listaProductos.setAttribute("role", "listbox");

function resaltarProducto(indice) {
  const opciones = [...listaProductos.querySelectorAll(".dropdown-opcion[data-id]")];
  resaltadaProducto = indice;
  opciones.forEach((el, i) => {
    el.classList.toggle("resaltada", i === indice);
    el.setAttribute("aria-selected", String(i === indice));
  });
  if (opciones[indice]) {
    if (opciones[indice].scrollIntoView) opciones[indice].scrollIntoView({ block: "nearest" });
    inputProducto.setAttribute("aria-activedescendant", opciones[indice].id);
  } else {
    inputProducto.removeAttribute("aria-activedescendant");
  }
}

function mostrarListaProductos(filtro = "") {
  renderizarListaProductos(filtro);
  listaProductos.hidden = false;
  inputProducto.setAttribute("aria-expanded", "true");
  inputProducto.removeAttribute("aria-activedescendant");
}

function ocultarListaProductos() {
  listaProductos.hidden = true;
  inputProducto.setAttribute("aria-expanded", "false");
  inputProducto.removeAttribute("aria-activedescendant");
}

function seleccionarProducto(idProducto) {
  const producto = productosDisponibles.find((p) => p.id_producto === idProducto);
  if (!producto) return;
  productoSeleccionadoId = producto.id_producto;
  inputProducto.value = textoOpcionProducto(producto);
  limpiarErrorDeCampo(inputProducto);
  ocultarListaProductos();
}

function limpiarSeleccionProducto() {
  productoSeleccionadoId = null;
  inputProducto.value = "";
}

inputProducto.addEventListener("input", () => {
  productoSeleccionadoId = null;
  mostrarListaProductos(inputProducto.value);
});

inputProducto.addEventListener("focus", () => {
  mostrarListaProductos(inputProducto.value);
});

listaProductos.addEventListener("click", (evento) => {
  const opcion = evento.target.closest(".dropdown-opcion[data-id]");
  if (!opcion) return;
  seleccionarProducto(parseInt(opcion.dataset.id, 10));
  inputProducto.focus();
});

inputProducto.addEventListener("keydown", (evento) => {
  if (evento.key === "Escape") {
    ocultarListaProductos();
    return;
  }
  const opciones = [...listaProductos.querySelectorAll(".dropdown-opcion[data-id]")];
  if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
    if (listaProductos.hidden) {
      mostrarListaProductos(inputProducto.value);
      return;
    }
    if (!opciones.length) return;
    evento.preventDefault();
    const paso = evento.key === "ArrowDown" ? 1 : -1;
    resaltarProducto((resaltadaProducto + paso + opciones.length) % opciones.length);
    return;
  }
  if (evento.key === "Enter" && !listaProductos.hidden) {
    // Con una opción resaltada con las flechas se elige esa; si no, la primera.
    const elegida = opciones[resaltadaProducto >= 0 ? resaltadaProducto : 0];
    if (elegida) {
      evento.preventDefault();
      seleccionarProducto(parseInt(elegida.dataset.id, 10));
    }
  }
});

// ---------------------------------------------------------------------------
// Dropdown de categorías (se puede escribir para filtrar)
// ---------------------------------------------------------------------------

function categoriaPorTexto(texto) {
  const buscado = normalizarTexto(texto);
  if (!buscado) return null;
  // Coincidencia exacta con el texto de la opción, su valor ("venta") o su nombre sin la aclaración.
  const exacta = CATEGORIAS_MOVIMIENTO.find(
    (c) => normalizarTexto(c.texto) === buscado ||
           c.valor === buscado ||
           normalizarTexto(c.texto.split("(")[0]) === buscado
  );
  if (exacta) return exacta;
  // Si lo escrito identifica a una sola opción, también vale ("dev" -> Devolución).
  const parciales = CATEGORIAS_MOVIMIENTO.filter((c) => normalizarTexto(c.texto).includes(buscado));
  return parciales.length === 1 ? parciales[0] : null;
}

function seleccionarCategoria(valor) {
  const categoria = CATEGORIAS_MOVIMIENTO.find((c) => c.valor === valor);
  if (!categoria) return;
  categoriaSeleccionada = categoria.valor;
  inputCategoria.value = categoria.texto;
  limpiarErrorDeCampo(inputCategoria);
}

function reiniciarCategoria() {
  seleccionarCategoria(CATEGORIA_POR_DEFECTO);
}

/** Si el usuario escribió el texto sin elegirlo de la lista, intenta resolverlo. */
function resolverCategoriaEscrita() {
  if (categoriaSeleccionada) return;
  const encontrada = categoriaPorTexto(inputCategoria.value);
  if (encontrada) seleccionarCategoria(encontrada.valor);
}

crearCombo({
  input: inputCategoria,
  lista: listaCategorias,
  opciones: (texto) => {
    // Con una categoría ya elegida, al abrir la lista se muestran todas (no solo la elegida).
    const elegida = CATEGORIAS_MOVIMIENTO.find((c) => c.valor === categoriaSeleccionada);
    const buscado = elegida && texto === elegida.texto ? "" : normalizarTexto(texto);
    return CATEGORIAS_MOVIMIENTO
      .filter((c) => !buscado || normalizarTexto(c.texto).includes(buscado))
      .map((c) => ({ clave: c.valor, texto: c.texto }));
  },
  alElegir: (opcion) => seleccionarCategoria(opcion.clave),
  alEscribir: () => { categoriaSeleccionada = null; },
});
inputCategoria.addEventListener("change", resolverCategoriaEscrita);

// ---------------------------------------------------------------------------
// Cierre del dropdown de productos al hacer click afuera
// (la categoría y el cliente cierran el suyo desde crearCombo)
// ---------------------------------------------------------------------------

document.addEventListener("click", (evento) => {
  if (!wrapperProducto.contains(evento.target)) {
    ocultarListaProductos();
  }
});

// ---------------------------------------------------------------------------
// Listado e historial de movimientos
// ---------------------------------------------------------------------------

async function cargarMovimientos() {
  tablaMovimientos.innerHTML = `
    <tr>
      <td colspan="7">
        <div class="estado-carga">
          <span class="spinner" aria-hidden="true"></span>
          <span>Cargando movimientos...</span>
        </div>
      </td>
    </tr>
  `;

  try {
    const resp = await apiFetch(`${MOVIMIENTOS_API_BASE}/movimientos`);
    if (!resp.ok) throw new Error("No se pudo obtener el historial de movimientos.");
    const movimientos = await resp.json();
    renderizarTablaMovimientos(movimientos);
  } catch (error) {
    if (error.sesionExpirada) return;
    tablaMovimientos.innerHTML = `<tr><td colspan="7" class="vacio">No se pudo conectar con el servicio de Movimientos (${MOVIMIENTOS_API_BASE}).</td></tr>`;
  }
}

/**
 * Cliente de un movimiento: "#12 · 30123456". El documento es una copia que el
 * movimiento guardó al registrarse (los clientes viven en el servicio de
 * Clientes). Los movimientos viejos solo tienen un DNI suelto.
 */
function textoClienteDeMovimiento(mov) {
  if (mov.id_cliente && mov.cliente_documento) return `#${mov.id_cliente} · ${mov.cliente_documento}`;
  if (mov.id_cliente) return `#${mov.id_cliente}`;
  if (mov.dni_cliente) return `${mov.dni_cliente} (sin ficha)`;
  return "—";
}

function renderizarTablaMovimientos(movimientos) {
  if (!movimientos.length) {
    tablaMovimientos.innerHTML = `<tr><td colspan="7" class="vacio">Todavía no hay movimientos registrados.</td></tr>`;
    return;
  }

  tablaMovimientos.innerHTML = movimientos
    .map((mov) => {
      const etiqueta =
        ETIQUETAS_CATEGORIA[mov.categoria_movimiento] || { texto: mov.categoria_movimiento, clase: "" };
      return `
        <tr>
          <td>${mov.id_movimiento}</td>
          <td>${formatearFecha(mov.fecha_hora)}</td>
          <td>
            <span class="badge-categoria ${etiqueta.clase}">${etiqueta.texto}</span>${
              mov.estado === "pendiente"
                ? `<span class="badge-pendiente" title="Se guardó el movimiento pero todavía no se confirmó el ajuste de stock. Reintentá el registro o pedí a un administrador que reconcilie.">Pendiente</span>`
                : ""
            }
          </td>
          <td>#${mov.id_producto}</td>
          <td>${mov.cantidad_movida}</td>
          <td>${escaparHtml(textoClienteDeMovimiento(mov))}</td>
          <td>${escaparHtml(mov.dni_empleado || "—")}</td>
        </tr>
      `;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// Envío del formulario
// ---------------------------------------------------------------------------

// Estado del envío (ver el manejador de submit más abajo).
let envioMovimientoEnCurso = false;
let intentoMovimiento = null; // { clave, huella } del último intento sin respuesta definitiva

// Campo del schema del backend -> id del <input> en el formulario de movimientos.
const MAPA_CAMPOS_MOVIMIENTO = {
  categoria_movimiento: "mov_categoria_input",
  cantidad_movida: "mov_cantidad",
  id_producto: "mov_producto_input",
  id_cliente: "mov_cliente_input",
};

// Mensajes propios de cada campo cuando el backend responde 400 (reemplazan al texto genérico).
const TRADUCCIONES_MOVIMIENTO = {
  categoria_movimiento: () => "Elegí una categoría de la lista.",
  id_producto: () => "Elegí un producto de la lista de sugerencias.",
  cantidad_movida: () => "Ingresá una cantidad entera de 1 en adelante.",
  id_cliente: () => "Elegí un cliente de la lista o creá uno nuevo.",
};

/** UUID v4 para el header Idempotency-Key (con alternativa si el navegador no tiene randomUUID). */
function generarClaveIdempotencia() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(bytes);
  else for (let k = 0; k < 16; k++) bytes[k] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

formMovimiento.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  // Barrera contra envíos duplicados (doble clic, Enter repetido).
  if (envioMovimientoEnCurso) return;

  limpiarErroresDeCampo(formMovimiento);

  // Si el usuario escribió el texto exacto de una opción sin hacer clic,
  // se resuelve el id a partir del texto.
  if (!productoSeleccionadoId) {
    const texto = inputProducto.value.trim();
    const exacto = productosDisponibles.find((p) => textoOpcionProducto(p) === texto);
    if (exacto) productoSeleccionadoId = exacto.id_producto;
  }

  if (!productoSeleccionadoId) {
    marcarCampoInvalido(inputProducto, "Elegí un producto de la lista de sugerencias: escribí parte del nombre y tocá una opción.");
    mostrarEstado("Revisá los campos marcados en rojo.", "error");
    inputProducto.focus();
    return;
  }

  // La categoría también se puede escribir: se resuelve lo tipeado y, si no
  // corresponde a ninguna opción, se pide elegir una.
  resolverCategoriaEscrita();
  if (!categoriaSeleccionada) {
    marcarCampoInvalido(inputCategoria, "Elegí una categoría de la lista: Venta, Ingreso, Estropeo o Devolución.");
    mostrarEstado("Revisá los campos marcados en rojo.", "error");
    inputCategoria.focus();
    return;
  }

  // Cliente (opcional): si escribió algo sin elegir un cliente, se avisa en vez de ignorarlo.
  if (textoDeClienteSinElegir()) {
    marcarCampoInvalido(inputCliente, "Elegí un cliente de la lista de sugerencias, o borrá el texto si no hay cliente.");
    mostrarEstado("Revisá los campos marcados en rojo.", "error");
    inputCliente.focus();
    return;
  }

  // No hay campo de empleado: el servidor lo toma del DNI de tu sesión.
  const cliente = obtenerClienteElegido();
  const payload = {
    categoria_movimiento: categoriaSeleccionada,
    cantidad_movida: parseInt(campoCantidad.value, 10),
    id_producto: productoSeleccionadoId,
    id_cliente: cliente ? cliente.id_cliente : null,
  };

  // Un intento = una Idempotency-Key. Si el intento anterior terminó sin
  // respuesta (timeout, corte de red, 5xx) y el formulario no cambió, se
  // reutiliza la MISMA clave: si el servidor ya había registrado el movimiento,
  // devuelve ese mismo y no vuelve a ajustar el stock. Si los datos cambian,
  // se genera una clave nueva.
  const huella = JSON.stringify(payload);
  if (!intentoMovimiento || intentoMovimiento.huella !== huella) {
    intentoMovimiento = { clave: generarClaveIdempotencia(), huella };
  }

  envioMovimientoEnCurso = true;
  bloquearBoton(btnGuardarMovimiento, "Registrando...");
  formMovimiento.setAttribute("aria-busy", "true");

  try {
    const resp = await apiFetchConTimeout(`${MOVIMIENTOS_API_BASE}/movimientos`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": intentoMovimiento.clave,
      },
      body: JSON.stringify(payload),
    });

    const data = await leerJson(resp);

    // Con una respuesta definitiva (< 500, salvo 401) el intento terminó: el
    // próximo envío usará una clave nueva. Con 5xx el resultado es incierto, y
    // con 401 el servidor pudo haber dejado el movimiento "pendiente" (ver
    // Movimientos): en ambos casos se conserva la clave para que el reintento
    // lo complete en lugar de duplicarlo.
    if (resp.status < 500 && resp.status !== 401) intentoMovimiento = null;

    if (resp.ok) {
      mostrarEstado("Movimiento registrado correctamente. El stock del producto fue actualizado.", "ok");
      formMovimiento.reset();
      limpiarSeleccionProducto();
      limpiarClienteElegido();
      reiniciarCategoria();
      cargarMovimientos();
      cargarOpcionesDeProductos();
      if (typeof cargarProductos === "function") cargarProductos();
    } else if (resp.status === 400 && Array.isArray(data.detalles)) {
      const sinCampo = mostrarErroresDeCampo(data.detalles, MAPA_CAMPOS_MOVIMIENTO, TRADUCCIONES_MOVIMIENTO);
      mostrarEstado(sinCampo.length ? sinCampo.join(" ") : "Revisá los campos marcados en rojo.", "error");
    } else if (resp.status === 409 && /stock insuficiente/i.test(data.mensaje || "")) {
      // Se refresca el stock real para decirle al usuario cuánto puede mover.
      await cargarOpcionesDeProductos();
      const producto = productosDisponibles.find((p) => p.id_producto === payload.id_producto);
      let ayuda = "Reducí la cantidad.";
      if (producto) {
        ayuda = producto.stock_actual > 0
          ? `Hay ${producto.stock_actual} unidad(es) disponibles de "${producto.nombre}": ingresá ${producto.stock_actual} o menos.`
          : `No hay unidades disponibles de "${producto.nombre}".`;
      }
      marcarCampoInvalido(campoCantidad, ayuda);
      campoCantidad.focus();
      mostrarEstado(data.mensaje, "error");
    } else if (resp.status === 404 && /cliente/i.test(data.mensaje || "")) {
      // El cliente elegido ya no existe: se lo quita y se pide elegir otro (o ninguno).
      limpiarClienteElegido();
      marcarCampoInvalido(inputCliente, "Ese cliente ya no existe. Elegí otro, creá uno nuevo o dejalo vacío.");
      inputCliente.focus();
      mostrarEstado(data.mensaje || "El cliente indicado no existe.", "error");
    } else if (resp.status === 404) {
      // El producto elegido ya no existe (p. ej. lo eliminaron desde otra pantalla).
      limpiarSeleccionProducto();
      await cargarOpcionesDeProductos();
      marcarCampoInvalido(inputProducto, "Ese producto ya no existe (puede haberse eliminado). Elegí otro de la lista.");
      inputProducto.focus();
      mostrarEstado(data.mensaje || "El producto indicado no existe.", "error");
    } else {
      mostrarEstado(data.mensaje || data.detail || "Ocurrió un error al registrar el movimiento.", "error");
      // Con un error del servidor el movimiento puede haber quedado "pendiente":
      // se refresca el historial para que se vea (con su etiqueta).
      if (resp.status >= 500) cargarMovimientos();
    }
  } catch (error) {
    if (error.sesionExpirada) return;
    mostrarEstado(
      describirFallaDeRed(
        error,
        "Tus datos siguen en el formulario. Podés reintentar: si el movimiento ya se había registrado, no se duplica."
      ),
      "error"
    );
  } finally {
    envioMovimientoEnCurso = false;
    liberarBoton(btnGuardarMovimiento, "Registrar movimiento");
    formMovimiento.removeAttribute("aria-busy");
  }
});

// El error de un campo desaparece apenas el usuario empieza a corregirlo.
formMovimiento.addEventListener("input", (evento) => limpiarErrorDeCampo(evento.target));

// ---------------------------------------------------------------------------
// Inicialización
// ---------------------------------------------------------------------------

// Aplicar restricciones de entrada al formulario de movimientos.
// Las funciones están definidas en app.js (mismo scope global).
restringirInputNumerico(campoCantidad);

/** Se llama al iniciar sesión: muestra con qué DNI va a quedar registrado cada movimiento. */
function prepararMovimientos() {
  const aviso = document.getElementById("mov-registra-como");
  if (!aviso || !usuarioActual) return;
  aviso.textContent = usuarioActual.dni
    ? `Este movimiento va a quedar registrado a nombre de ${usuarioActual.nombre} (DNI ${usuarioActual.dni}). Se completa solo desde tu sesión.`
    : `Este movimiento va a quedar registrado a nombre de ${usuarioActual.nombre}.`;
}

// Categoría por defecto: Venta.
reiniciarCategoria();

// Botón de la guía: completa el formulario con un ejemplo real (no registra nada).
const btnEjemploMovimiento = document.getElementById("btn-ejemplo-movimiento");
btnEjemploMovimiento.addEventListener("click", async () => {
  if (!productosDisponibles.length) await cargarOpcionesDeProductos();
  const producto = productosDisponibles.find((p) => p.stock_actual >= 1) || productosDisponibles[0];
  if (!producto) {
    mostrarEstado("Todavía no hay productos: cargá uno en la pestaña Inventario para probar el ejemplo.", "error");
    return;
  }
  limpiarErroresDeCampo(formMovimiento);
  seleccionarProducto(producto.id_producto);
  // Una venta necesita stock: si el producto no tiene, el ejemplo es un ingreso
  // (siempre válido) para que el ejemplo se pueda registrar tal cual.
  const hayStock = producto.stock_actual >= 1;
  seleccionarCategoria(hayStock ? "venta" : "ingreso");
  if (!hayStock) {
    mostrarEstado("Ese producto no tiene stock, por eso el ejemplo es un ingreso (una venta no se podría registrar).", "ok");
  }
  campoCantidad.value = "1";
  campoCantidad.focus();
});