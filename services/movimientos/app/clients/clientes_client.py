"""
Cliente HTTP hacia el servicio de Clientes.

Movimientos no accede a la base de Clientes: para validar el `id_cliente` de un
movimiento llama a la API REST de Clientes, con un timeout explícito, y traduce
cualquier falla (timeout, conexión rechazada, 401, 403, 404, 5xx) a un error
consistente (ClientesClientError) que el router convierte 1 a 1 en una respuesta
HTTP. Mismo patrón que productos_client.py.

Autenticación: igual que con Productos, se reenvía el token del usuario que
registra el movimiento (no hay credenciales de servicio). Los roles que pueden
registrar movimientos (admin, ventas, mixto) son los mismos que pueden consultar
clientes, así que un 403 acá sería una inconsistencia de configuración.

CLIENTES_SERVICE_URL apunta, dentro de la red de Docker Compose, al nombre del
servicio ("http://clientes:8000"); en desarrollo local usa "http://localhost:8004".
"""
import os

import httpx

from app.core import observabilidad
from app.core.resiliencia import CircuitBreaker, con_reintentos

CLIENTES_SERVICE_URL = os.getenv("CLIENTES_SERVICE_URL", "http://localhost:8004")
TIMEOUT_SEGUNDOS = float(os.getenv("CLIENTES_SERVICE_TIMEOUT", "5"))

# Mismo esquema de resiliencia que productos_client (ver app/core/resiliencia.py).
REINTENTOS = int(os.getenv("CLIENTES_REINTENTOS", "1"))
REINTENTO_ESPERA_SEGUNDOS = float(os.getenv("CLIENTES_REINTENTO_ESPERA", "0.2"))
_BREAKER = CircuitBreaker(
    "clientes",
    umbral_fallos=int(os.getenv("CB_UMBRAL_FALLOS", "5")),
    espera_segundos=float(os.getenv("CB_ESPERA_SEGUNDOS", "15")),
    registro=observabilidad.REGISTRO,
)


class ClientesClientError(Exception):
    """
    Error estandarizado de la comunicación con Clientes. status_code ya viene
    resuelto al código HTTP que corresponde devolver desde Movimientos (404 si el
    cliente no existe, 401/403 si el token no sirve, 503 si Clientes no respondió).
    """

    def __init__(self, status_code: int, mensaje: str):
        self.status_code = status_code
        self.mensaje = mensaje
        super().__init__(mensaje)


def obtener_cliente(id_cliente: int, token: str) -> dict:
    """GET /api/v1/clientes/{id} en el servicio de Clientes."""
    url = f"{CLIENTES_SERVICE_URL}/api/v1/clientes/{id_cliente}"
    if not _BREAKER.permitir():
        raise ClientesClientError(
            503, "El servicio de Clientes no está respondiendo; se pausaron los pedidos unos segundos."
        )
    headers = {"Authorization": f"Bearer {token}", **observabilidad.cabeceras_propagacion()}
    try:
        respuesta = con_reintentos(
            lambda: httpx.get(url, headers=headers, timeout=TIMEOUT_SEGUNDOS),
            (httpx.TransportError,), REINTENTOS, REINTENTO_ESPERA_SEGUNDOS,
        )
    except httpx.TimeoutException as error:
        _BREAKER.fallo()
        raise ClientesClientError(503, "El servicio de Clientes no respondió a tiempo.") from error
    except httpx.RequestError as error:
        _BREAKER.fallo()
        raise ClientesClientError(503, "No se pudo conectar con el servicio de Clientes.") from error
    if respuesta.status_code >= 500:
        _BREAKER.fallo()
    else:
        _BREAKER.exito()

    if respuesta.status_code == 404:
        raise ClientesClientError(404, f"No existe un cliente con id_cliente={id_cliente}.")
    if respuesta.status_code == 401:
        raise ClientesClientError(401, "Tu sesión venció o el token es inválido. Iniciá sesión de nuevo.")
    if respuesta.status_code == 403:
        raise ClientesClientError(403, "No tenés permisos para consultar clientes.")
    if respuesta.status_code >= 400:
        raise ClientesClientError(502, "El servicio de Clientes devolvió un error inesperado.")
    return respuesta.json()
