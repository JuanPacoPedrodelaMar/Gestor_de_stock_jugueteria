  // Alternar entre las vistas "Inventario", "Movimientos" y "Clientes".
  // Cada pestaña se muestra solo si el rol del usuario la puede usar (app.js:
  // aplicarPermisosDeRol oculta los botones que no corresponden).
  const VISTAS_APP = {
    productos: {
      boton: "tab-btn-productos",
      vista: "vista-productos",
      cargar: () => { if (typeof cargarProductos === "function") cargarProductos(); },
    },
    movimientos: {
      boton: "tab-btn-movimientos",
      vista: "vista-movimientos",
      cargar: () => {
        if (typeof cargarOpcionesDeProductos === "function") cargarOpcionesDeProductos();
        if (typeof cargarMovimientos === "function") cargarMovimientos();
      },
    },
    clientes: {
      boton: "tab-btn-clientes",
      vista: "vista-clientes",
      cargar: () => { if (typeof cargarClientes === "function") cargarClientes(); },
    },
  };

  function activarVista(nombre) {
    const destino = VISTAS_APP[nombre];
    // Si la pestaña pedida está oculta para este rol, se vuelve a Inventario.
    if (!destino || document.getElementById(destino.boton).style.display === "none") {
      nombre = "productos";
    }
    Object.entries(VISTAS_APP).forEach(([clave, v]) => {
      document.getElementById(v.boton).classList.toggle("activo", clave === nombre);
      document.getElementById(v.vista).classList.toggle("activa", clave === nombre);
    });
    VISTAS_APP[nombre].cargar();
  }

  Object.entries(VISTAS_APP).forEach(([clave, v]) => {
    document.getElementById(v.boton).addEventListener("click", () => activarVista(clave));
  });

  // Se arranca la sesión recién ahora, con todos los scripts ya cargados.
  restaurarSesion();
