/**
 * Solicitudes de stock: un empleado de almacén (o mixto) pide reponer un
 * producto y el administrador la atiende o la rechaza.
 * Consume la API del servicio "productos" (/api/v1/solicitudes-stock).
 *
 * Una solicitud NO cambia el stock: es un aviso. Cuando llega la mercadería se
 * registra el ingreso en Movimientos, como siempre.
 *
 * Usa funciones de app.js (apiFetch, crearCombo, mostrarErroresDeCampo, ...).
 */
const SOLICITUDES_API = `${RAIZ_API_URL}/api/v1/solicitudes-stock`;

const formSolicitud = document.getElementById("form-solicitud");
const inputSolProducto = document.getElementById("sol_producto_input");
const listaSolProductos = document.getElementById("sol-productos-lista");
const campoSolCantidad = document.getElementById("sol_cantidad");
const campoSolNota = document.getElementById("sol_nota");
const btnSolicitar = document.getElementById("btn-solicitar");
const tablaSolicitudes = document.getElementById("tabla-solicitudes");
const ayudaSolicitudes = document.getElementById("ayuda-solicitudes");

const MAPA_CAMPOS_SOLICITUD = {
  id_producto: "sol_producto_input",
  cantidad: "sol_cantidad",
  nota: "sol_nota",
};

const TRADUCCIONES_SOLICITUD = {
  id_producto: () => "Elegí un producto de la lista de sugerencias.",
  cantidad: () => "Ingresá una cantidad entera entre 1 y 100.000.",
  nota: () => "La nota admite hasta 200 caracteres y no puede incluir < > ; = { }.",
};

const ETIQUETA_ESTADO_SOLICITUD = {
  pendiente: "Pendiente",
  atendida: "Atendida",
  rechazada: "Rechazada",
};

let solProductoElegidoId = null;

function textoOpcionSolicitud(producto) {
  return `#${producto.id_producto} — ${producto.nombre} (stock: ${producto.stock_actual})`;
}

crearCombo({
  input: inputSolProducto,
  lista: listaSolProductos,
  opciones: (texto) => {
    const buscado = normalizarTexto(texto);
    return productosCargados
      .filter((p) => !buscado || normalizarTexto(textoOpcionSolicitud(p)).includes(buscado))
      .map((p) => ({ clave: p.id_producto, texto: textoOpcionSolicitud(p) }));
  },
  alElegir: (opcion) => {
    solProductoElegidoId = opcion.clave;
    inputSolProducto.value = opcion.texto;
    limpiarErrorDeCampo(inputSolProducto);
  },
  alEscribir: () => { solProductoElegidoId = null; },
});

function limpiarFormularioSolicitud() {
  formSolicitud.reset();
  limpiarErroresDeCampo(formSolicitud);
  solProductoElegidoId = null;
}

// ---------------------------------------------------------------------------
// Listado
// ---------------------------------------------------------------------------

function filaVaciaSolicitudes(texto) {
  return `<tr><td colspan="7" class="vacio">${escaparHtml(texto)}</td></tr>`;
}

async function cargarSolicitudes() {
  if (!veSolicitudes()) return;
  tablaSolicitudes.innerHTML = `
    <tr><td colspan="7"><div class="estado-carga"><span class="spinner" aria-hidden="true"></span><span>Cargando solicitudes...</span></div></td></tr>`;
  try {
    const resp = await apiFetch(SOLICITUDES_API);
    if (!resp.ok) throw new Error("No se pudo obtener las solicitudes.");
    renderizarSolicitudes(await resp.json());
  } catch (error) {
    if (error.sesionExpirada) return;
    tablaSolicitudes.innerHTML = filaVaciaSolicitudes("No se pudieron cargar las solicitudes de stock.");
  }
}

function renderizarSolicitudes(solicitudes) {
  if (!solicitudes.length) {
    tablaSolicitudes.innerHTML = filaVaciaSolicitudes(
      esAdmin() ? "No hay solicitudes de stock." : "Todavía no pediste reposición de ningún producto."
    );
    return;
  }
  tablaSolicitudes.innerHTML = solicitudes
    .map((sol) => {
      const acciones =
        esAdmin() && sol.estado === "pendiente"
          ? `<button type="button" class="btn-primario btn-chico" data-resolver="${sol.id_solicitud}" data-estado="atendida">Atender</button>
             <button type="button" class="btn-secundario btn-chico" data-resolver="${sol.id_solicitud}" data-estado="rechazada">Rechazar</button>`
          : "";
      const nota = sol.nota ? `<br><small class="ayuda-campo">${escaparHtml(sol.nota)}</small>` : "";
      return `
      <tr>
        <td>${sol.id_solicitud}</td>
        <td>${formatearFecha(sol.fecha_hora)}</td>
        <td>#${sol.id_producto} — ${escaparHtml(sol.nombre_producto)}${nota}</td>
        <td>${sol.cantidad}</td>
        <td>${escaparHtml(sol.solicitante)}</td>
        <td><span class="badge-estado ${sol.estado}">${ETIQUETA_ESTADO_SOLICITUD[sol.estado] || escaparHtml(sol.estado)}</span></td>
        <td class="col-acciones">${acciones}</td>
      </tr>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// Pedir reposición
// ---------------------------------------------------------------------------

let envioSolicitudEnCurso = false;

formSolicitud.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (envioSolicitudEnCurso) return;
  limpiarErroresDeCampo(formSolicitud);

  // Si escribió el texto exacto de una opción sin hacer clic, se resuelve el producto.
  if (!solProductoElegidoId) {
    const texto = inputSolProducto.value.trim();
    const exacto = productosCargados.find((p) => textoOpcionSolicitud(p) === texto);
    if (exacto) solProductoElegidoId = exacto.id_producto;
  }
  if (!solProductoElegidoId) {
    marcarCampoInvalido(inputSolProducto, "Elegí un producto de la lista de sugerencias: escribí parte del nombre y tocá una opción.");
    mostrarEstado("Revisá los campos marcados en rojo.", "error");
    inputSolProducto.focus();
    return;
  }

  const payload = {
    id_producto: solProductoElegidoId,
    cantidad: parseInt(campoSolCantidad.value, 10),
    nota: campoSolNota.value.trim() || null,
  };

  envioSolicitudEnCurso = true;
  bloquearBoton(btnSolicitar, "Enviando...");
  try {
    const resp = await apiFetchConTimeout(SOLICITUDES_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await leerJson(resp);

    if (resp.ok) {
      mostrarEstado("Pedido de reposición enviado. Un administrador lo va a revisar.", "ok");
      limpiarFormularioSolicitud();
      cargarSolicitudes();
    } else if (resp.status === 400 && Array.isArray(data.detalles)) {
      const sinCampo = mostrarErroresDeCampo(data.detalles, MAPA_CAMPOS_SOLICITUD, TRADUCCIONES_SOLICITUD);
      mostrarEstado(sinCampo.length ? sinCampo.join(" ") : "Revisá los campos marcados en rojo.", "error");
    } else if (resp.status === 404) {
      limpiarFormularioSolicitud();
      cargarProductos();
      marcarCampoInvalido(inputSolProducto, "Ese producto ya no existe o fue dado de baja. Elegí otro.");
      mostrarEstado(data.mensaje || "El producto indicado no existe.", "error");
    } else {
      mostrarEstado(data.mensaje || data.detail || "No se pudo enviar el pedido de reposición.", "error");
    }
  } catch (error) {
    if (error.sesionExpirada) return;
    mostrarEstado(
      describirFallaDeRed(error, "No podemos confirmar si el pedido se envió: revisá la lista de abajo antes de volver a pedirlo."),
      "error"
    );
    cargarSolicitudes();
  } finally {
    envioSolicitudEnCurso = false;
    liberarBoton(btnSolicitar, "Pedir reposición");
  }
});

formSolicitud.addEventListener("input", (evento) => limpiarErrorDeCampo(evento.target));
restringirInputNumerico(campoSolCantidad);

// ---------------------------------------------------------------------------
// Resolver (solo administrador)
// ---------------------------------------------------------------------------

async function resolverSolicitud(idSolicitud, estado) {
  if (estado === "rechazada" && !confirm("¿Rechazar este pedido de reposición?")) return;
  try {
    const resp = await apiFetch(`${SOLICITUDES_API}/${idSolicitud}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ estado }),
    });
    const data = await leerJson(resp);
    if (resp.ok) {
      mostrarEstado(`Solicitud ${estado === "atendida" ? "atendida" : "rechazada"}.`, "ok");
    } else {
      mostrarEstado(data.mensaje || data.detail || "No se pudo actualizar la solicitud.", "error");
    }
    cargarSolicitudes();
  } catch (error) {
    if (error.sesionExpirada) return;
    mostrarEstado("Error de conexión al actualizar la solicitud.", "error");
  }
}

tablaSolicitudes.addEventListener("click", (evento) => {
  const boton = evento.target.closest("[data-resolver]");
  if (boton) resolverSolicitud(parseInt(boton.dataset.resolver, 10), boton.dataset.estado);
});

/** Se llama al iniciar sesión: texto de ayuda según el rol y primera carga. */
function prepararSolicitudes() {
  limpiarFormularioSolicitud();
  if (!veSolicitudes()) return;
  ayudaSolicitudes.textContent = esAdmin()
    ? "Pedidos de reposición del equipo. Cuando llegue la mercadería, registrá el ingreso en Movimientos y marcá la solicitud como atendida."
    : "Pedí reposición de un producto que se está quedando sin stock. No cambia el stock: un administrador la revisa y, cuando llega la mercadería, la registra.";
  cargarSolicitudes();
}
