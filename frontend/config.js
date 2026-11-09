// Configuración para correr el frontend FUERA de Docker (ejecutar_local.ps1).
// En Docker este archivo lo genera docker-entrypoint.sh a partir de config.js.template.
window.APP_CONFIG = {
  PRODUCTOS_API_URL: "http://localhost:8000",
  AUTH_API_URL: "http://localhost:8001",
  MOVIMIENTOS_API_URL: "http://localhost:8002",
  CLIENTES_API_URL: "http://localhost:8004",
  // Acceso rápido por rol (solo entorno de pruebas). Tienen que coincidir con
  // los PRUEBA_* que levanta el servicio auth (ver ejecutar_local.ps1).
  USUARIOS_PRUEBA: {
    habilitado: true,
    admin:   { email: "admin@test.com",   dni: "20000001", password: "admin12345" },
    almacen: { email: "almacen@test.com", dni: "30000002", password: "almacen123" },
    ventas:  { email: "ventas@test.com",  dni: "30000003", password: "ventas123" },
    mixto:   { email: "mixto@test.com",   dni: "30000004", password: "mixto123" }
  }
};
