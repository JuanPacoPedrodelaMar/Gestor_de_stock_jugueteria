/**
 * Clientes: selector del formulario de Movimientos y pestaña "Clientes".
 * Consume la API del servicio "clientes" (/api/v1/clientes), que es dueño de
 * los datos de clientes. El historial de compras de un cliente, en cambio, lo
 * tiene el servicio "movimientos" (GET /movimientos?id_cliente=N).
 *
 * Cada cliente tiene un ID que asigna el sistema. El documento no es único ni
 * se valida como DNI argentino (puede haber clientes de otros países o
 * documentos repetidos); el email y el teléfono son opcionales. Pueden usar
 * esta pantalla el administrador y los roles de ventas y mixto.
 *
 * Usa funciones de app.js (apiFetch, crearCombo, marcarCampoInvalido, ...) y
 * de movimientos.js (MOVIMIENTOS_API_BASE, formatearFecha, ETIQUETAS_CATEGORIA).
 */
const CLIENTES_API_BASE = `${(window.APP_CONFIG && window.APP_CONFIG.CLIENTES_API_URL) || "http://localhost:8004"}/api/v1`;
const CLIENTES_API = `${CLIENTES_API_BASE}/clientes`;

// ---------------------------------------------------------------------------
// Acceso a la API
// ---------------------------------------------------------------------------

/** Busca clientes por ID, documento, email o teléfono. Ante cualquier falla devuelve []. */
async function buscarClientesApi(texto, limite = 20) {
  try {
    const q = encodeURIComponent((texto || "").trim());
    const resp = await apiFetch(`${CLIENTES_API}?q=${q}&limite=${limite}`);
    return resp.ok ? await resp.json() : [];
  } catch (error) {
    return [];
  }
}

/** Crea un cliente. Devuelve { resp, data } para que quien llama decida qué mostrar. */
async function crearClienteApi(datos) {
  const resp = await apiFetchConTimeout(CLIENTES_API, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(datos),
  });
  return { resp, data: await leerJson(resp) };
}

/** Lee los tres campos de un formulario de cliente (el opcional vacío viaja como null). */
function leerDatosDeCliente(prefijo) {
  const valor = (campo) => document.getElementById(`${prefijo}_${campo}`).value.trim();
  return {
    documento: valor("documento"),
    email: valor("email") || null,
    telefono: valor("telefono") || null,
  };
}

// Mensajes propios de cada campo cuando el backend responde 400.
const TRADUCCIONES_CLIENTE = {
  documento: (err) =>
    err.type === "missing" || err.type === "string_too_short"
      ? "Ingresá el documento del cliente."
      : "El documento admite letras, números, espacios, puntos, guiones y barras (hasta 30 caracteres).",
  email: () => "Ingresá un email válido, por ejemplo nombre@dominio.com.",
  telefono: () =>
    "Ingresá un teléfono válido: números, espacios, paréntesis o guiones, y puede empezar con + (de 6 a 25 caracteres).",
};

/** "#12 · 30123456 · ana@mail.com · +54 376 4123456" */
function textoDeCliente(cliente) {
  return [`#${cliente.id_cliente}`, cliente.documento, cliente.email, cliente.telefono]
    .filter(Boolean)
    .join(" · ");
}

/** Nombre legible de un producto a partir de los listados ya cargados. */
function nombreDeProducto(idProducto) {
  const conocidos = [
    ...(typeof productosCargados !== "undefined" ? productosCargados : []),
    ...(typeof productosDisponibles !== "undefined" ? productosDisponibles : []),
  ];
  const producto = conocidos.find((p) => p.id_producto === idProducto);
  return producto ? `#${idProducto} — ${producto.nombre}` : `#${idProducto}`;
}

// ---------------------------------------------------------------------------
// Selector de cliente del formulario de Movimientos
// ---------------------------------------------------------------------------

const inputCliente = document.getElementById("mov_cliente_input");
const listaClientes = document.getElementById("mov-clientes-lista");
const btnNuevoClienteMov = document.getElementById("btn-nuevo-cliente-mov");
const btnQuitarCliente = document.getElementById("btn-quitar-cliente");
const panelNuevoClienteMov = document.getElementById("nuevo-cliente-mov");
const btnGuardarClienteMov = document.getElementById("btn-guardar-cliente-mov");
const btnCancelarClienteMov = document.getElementById("btn-cancelar-cliente-mov");

const MAPA_CAMPOS_CLIENTE_MOV = {
  documento: "ncm_documento",
  email: "ncm_email",
  telefono: "ncm_telefono",
};

let clienteElegido = null; // el objeto cliente elegido de la lista (o recién creado)

function obtenerClienteElegido() {
  return clienteElegido;
}

/** true si hay texto en el campo pero no corresponde a un cliente elegido. */
function textoDeClienteSinElegir() {
  return !clienteElegido && inputCliente.value.trim() !== "";
}

function elegirCliente(cliente) {
  clienteElegido = cliente;
  inputCliente.value = textoDeCliente(cliente);
  limpiarErrorDeCampo(inputCliente);
  btnQuitarCliente.style.display = "";
  cerrarNuevoClienteMov();
}

function limpiarClienteElegido() {
  clienteElegido = null;
  inputCliente.value = "";
  btnQuitarCliente.style.display = "none";
  limpiarErrorDeCampo(inputCliente);
  cerrarNuevoClienteMov();
}

function cerrarNuevoClienteMov() {
  panelNuevoClienteMov.style.display = "none";
  limpiarErroresDeCampo(panelNuevoClienteMov);
  ["documento", "email", "telefono"].forEach((c) => {
    document.getElementById(`ncm_${c}`).value = "";
  });
}

crearCombo({
  input: inputCliente,
  lista: listaClientes,
  retardoMs: 250, // consulta al servidor: se espera a que termine de escribir
  opciones: async (texto) => {
    const clientes = await buscarClientesApi(texto);
    return clientes.map((c) => ({ clave: c.id_cliente, texto: textoDeCliente(c), cliente: c }));
  },
  sinResultados: () => "No hay clientes con ese dato. Podés crear uno con «Cliente nuevo».",
  alElegir: (opcion) => elegirCliente(opcion.cliente),
  alEscribir: () => {
    clienteElegido = null;
    btnQuitarCliente.style.display = "none";
  },
});

btnQuitarCliente.addEventListener("click", () => {
  limpiarClienteElegido();
  inputCliente.focus();
});

btnNuevoClienteMov.addEventListener("click", () => {
  const abierto = panelNuevoClienteMov.style.display !== "none";
  if (abierto) return cerrarNuevoClienteMov();
  panelNuevoClienteMov.style.display = "";
  document.getElementById("ncm_documento").focus();
});

btnCancelarClienteMov.addEventListener("click", cerrarNuevoClienteMov);

let guardandoClienteMov = false;

async function guardarClienteDesdeMovimiento() {
  if (guardandoClienteMov) return;
  limpiarErroresDeCampo(panelNuevoClienteMov);

  const datos = leerDatosDeCliente("ncm");
  if (!datos.documento) {
    marcarCampoInvalido(document.getElementById("ncm_documento"), "Ingresá el documento del cliente.");
    document.getElementById("ncm_documento").focus();
    return;
  }

  guardandoClienteMov = true;
  bloquearBoton(btnGuardarClienteMov, "Guardando...");
  try {
    const { resp, data } = await crearClienteApi(datos);
    if (resp.ok) {
      elegirCliente(data); // queda elegido para este movimiento
      mostrarEstado(`Cliente #${data.id_cliente} creado y elegido para este movimiento.`, "ok");
    } else if (resp.status === 400 && Array.isArray(data.detalles)) {
      const sinCampo = mostrarErroresDeCampo(data.detalles, MAPA_CAMPOS_CLIENTE_MOV, TRADUCCIONES_CLIENTE);
      mostrarEstado(sinCampo.length ? sinCampo.join(" ") : "Revisá los campos marcados en rojo.", "error");
    } else {
      mostrarEstado(data.mensaje || data.detail || "No se pudo crear el cliente.", "error");
    }
  } catch (error) {
    if (error.sesionExpirada) return;
    mostrarEstado(
      describirFallaDeRed(error, "No podemos confirmar si el cliente se guardó: buscalo en la lista antes de crearlo de nuevo."),
      "error"
    );
  } finally {
    guardandoClienteMov = false;
    liberarBoton(btnGuardarClienteMov, "Guardar cliente");
  }
}

btnGuardarClienteMov.addEventListener("click", guardarClienteDesdeMovimiento);

// Estos campos están dentro del formulario de movimientos: Enter guarda el
// cliente en lugar de registrar el movimiento.
panelNuevoClienteMov.addEventListener("keydown", (evento) => {
  if (evento.key !== "Enter") return;
  evento.preventDefault();
  guardarClienteDesdeMovimiento();
});

// ---------------------------------------------------------------------------
// Pestaña "Clientes": búsqueda, alta e historial por cliente
// ---------------------------------------------------------------------------

const formBuscarCliente = document.getElementById("form-buscar-cliente");
const campoBusquedaCliente = document.getElementById("buscar_cliente_q");
const btnBuscarCliente = document.getElementById("btn-buscar-cliente");
const btnNuevoCliente = document.getElementById("btn-nuevo-cliente");
const formClienteNuevo = document.getElementById("form-cliente-nuevo");
const btnGuardarCliente = document.getElementById("btn-guardar-cliente");
const btnCancelarCliente = document.getElementById("btn-cancelar-cliente");
const tablaClientes = document.getElementById("tabla-clientes");
const panelDetalleCliente = document.getElementById("panel-detalle-cliente");
const tituloDetalleCliente = document.getElementById("titulo-detalle-cliente");
const tablaMovimientosCliente = document.getElementById("tabla-movimientos-cliente");

const MAPA_CAMPOS_CLIENTE = {
  documento: "cli_documento",
  email: "cli_email",
  telefono: "cli_telefono",
};

let clientesMostrados = []; // resultado de la última búsqueda
let busquedaClientesActual = 0; // descarta respuestas de búsquedas viejas

function filaVaciaClientes(texto, clase = "vacio") {
  return `<tr><td colspan="6" class="${clase}">${escaparHtml(texto)}</td></tr>`;
}

async function cargarClientes() {
  const numero = ++busquedaClientesActual;
  const texto = campoBusquedaCliente.value.trim();
  tablaClientes.innerHTML = `
    <tr><td colspan="6"><div class="estado-carga"><span class="spinner" aria-hidden="true"></span><span>Buscando clientes...</span></div></td></tr>`;

  try {
    const resp = await apiFetch(`${CLIENTES_API}?q=${encodeURIComponent(texto)}&limite=50`);
    if (numero !== busquedaClientesActual) return;
    if (!resp.ok) throw new Error("No se pudo buscar clientes.");
    clientesMostrados = await resp.json();
    renderizarClientes(clientesMostrados, texto);
  } catch (error) {
    if (error.sesionExpirada || numero !== busquedaClientesActual) return;
    tablaClientes.innerHTML = filaVaciaClientes(
      `No se pudo conectar con el servicio de Clientes (${CLIENTES_API_BASE}).`
    );
  }
}

function renderizarClientes(clientes, texto) {
  if (!clientes.length) {
    tablaClientes.innerHTML = filaVaciaClientes(
      texto ? `No hay clientes que coincidan con «${texto}».` : "Todavía no hay clientes registrados."
    );
    return;
  }
  tablaClientes.innerHTML = clientes
    .map(
      (c) => `
      <tr>
        <td>${c.id_cliente}</td>
        <td>${escaparHtml(c.documento)}</td>
        <td>${escaparHtml(c.email || "—")}</td>
        <td>${escaparHtml(c.telefono || "—")}</td>
        <td>${formatearFecha(c.fecha_alta)}</td>
        <td class="col-acciones">
          <button type="button" class="btn-secundario btn-chico" data-ver-cliente="${c.id_cliente}">Ver movimientos</button>
        </td>
      </tr>`
    )
    .join("");
}

async function verMovimientosDeCliente(idCliente) {
  const cliente = clientesMostrados.find((c) => c.id_cliente === idCliente);
  tituloDetalleCliente.textContent = `🧾 Movimientos del cliente ${cliente ? textoDeCliente(cliente) : "#" + idCliente}`;
  panelDetalleCliente.style.display = "";
  tablaMovimientosCliente.innerHTML = `
    <tr><td colspan="6"><div class="estado-carga"><span class="spinner" aria-hidden="true"></span><span>Cargando movimientos...</span></div></td></tr>`;
  panelDetalleCliente.scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    // Para mostrar nombres de producto, si todavía no se cargó el catálogo.
    if (!productosCargados.length && !productosDisponibles.length) await cargarOpcionesDeProductos();
    // El historial lo tiene Movimientos (dueño de esos datos), no Clientes.
    const resp = await apiFetch(`${MOVIMIENTOS_API_BASE}/movimientos?id_cliente=${idCliente}`);
    if (!resp.ok) throw new Error("No se pudo obtener el historial del cliente.");
    renderizarMovimientosDeCliente(await resp.json());
  } catch (error) {
    if (error.sesionExpirada) return;
    tablaMovimientosCliente.innerHTML = filaVaciaClientes("No se pudo obtener el historial de este cliente.");
  }
}

function renderizarMovimientosDeCliente(movimientos) {
  if (!movimientos.length) {
    tablaMovimientosCliente.innerHTML = filaVaciaClientes("Este cliente todavía no tiene movimientos.");
    return;
  }
  tablaMovimientosCliente.innerHTML = movimientos
    .map((mov) => {
      const etiqueta = ETIQUETAS_CATEGORIA[mov.categoria_movimiento] || { texto: mov.categoria_movimiento, clase: "" };
      return `
      <tr>
        <td>${mov.id_movimiento}</td>
        <td>${formatearFecha(mov.fecha_hora)}</td>
        <td><span class="badge-categoria ${etiqueta.clase}">${escaparHtml(etiqueta.texto)}</span></td>
        <td>${escaparHtml(nombreDeProducto(mov.id_producto))}</td>
        <td>${mov.cantidad_movida}</td>
        <td>${escaparHtml(mov.dni_empleado || "—")}</td>
      </tr>`;
    })
    .join("");
}

tablaClientes.addEventListener("click", (evento) => {
  const boton = evento.target.closest("[data-ver-cliente]");
  if (boton) verMovimientosDeCliente(parseInt(boton.dataset.verCliente, 10));
});

formBuscarCliente.addEventListener("submit", (evento) => {
  evento.preventDefault();
  btnBuscarCliente.blur();
  panelDetalleCliente.style.display = "none";
  cargarClientes();
});

// --- Alta de un cliente desde la pestaña ---

function cerrarFormularioCliente() {
  formClienteNuevo.reset();
  limpiarErroresDeCampo(formClienteNuevo);
  formClienteNuevo.style.display = "none";
}

btnNuevoCliente.addEventListener("click", () => {
  if (formClienteNuevo.style.display !== "none") return cerrarFormularioCliente();
  formClienteNuevo.style.display = "";
  document.getElementById("cli_documento").focus();
});

btnCancelarCliente.addEventListener("click", cerrarFormularioCliente);

let guardandoCliente = false;

formClienteNuevo.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (guardandoCliente) return;
  limpiarErroresDeCampo(formClienteNuevo);

  guardandoCliente = true;
  bloquearBoton(btnGuardarCliente, "Guardando...");
  try {
    const { resp, data } = await crearClienteApi(leerDatosDeCliente("cli"));
    if (resp.ok) {
      mostrarEstado(`Cliente #${data.id_cliente} creado correctamente.`, "ok");
      cerrarFormularioCliente();
      // Se lo muestra: la búsqueda pasa a ser por su ID.
      campoBusquedaCliente.value = `#${data.id_cliente}`;
      cargarClientes();
    } else if (resp.status === 400 && Array.isArray(data.detalles)) {
      const sinCampo = mostrarErroresDeCampo(data.detalles, MAPA_CAMPOS_CLIENTE, TRADUCCIONES_CLIENTE);
      mostrarEstado(sinCampo.length ? sinCampo.join(" ") : "Revisá los campos marcados en rojo.", "error");
    } else {
      mostrarEstado(data.mensaje || data.detail || "No se pudo crear el cliente.", "error");
    }
  } catch (error) {
    if (error.sesionExpirada) return;
    // POST de cliente no es idempotente: si la respuesta no llegó, pudo haberse creado igual.
    mostrarEstado(
      describirFallaDeRed(error, "No podemos confirmar si el cliente se guardó: buscalo antes de volver a crearlo, para no duplicarlo."),
      "error"
    );
  } finally {
    guardandoCliente = false;
    liberarBoton(btnGuardarCliente, "Guardar cliente");
  }
});

formClienteNuevo.addEventListener("input", (evento) => limpiarErrorDeCampo(evento.target));
panelNuevoClienteMov.addEventListener("input", (evento) => limpiarErrorDeCampo(evento.target));

/** Se llama al iniciar sesión: deja la pestaña Clientes en su estado inicial. */
function prepararClientes() {
  campoBusquedaCliente.value = "";
  cerrarFormularioCliente();
  panelDetalleCliente.style.display = "none";
  limpiarClienteElegido();
}
