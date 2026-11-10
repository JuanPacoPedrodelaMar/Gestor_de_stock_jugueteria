"""
Cliente HTTP hacia el servicio de Productos.

Movimientos nunca accede directamente a la base de datos de Productos: toda
interacción pasa por esta capa, que llama a la API REST de Productos con un
timeout explícito y traduce cualquier falla (timeout, conexión rechazada,
401, 403, 404, 409, 5xx) a un error consistente (ProductosClientError) que
el router convierte 1 a 1 en una respuesta HTTP para el cliente.

Autenticación: Productos exige JWT en todos sus endpoints. El token del
usuario que originó el movimiento se propaga desde el router de Movimientos
hacia acá, y de acá hacia Productos en el header Authorization. No se usan
credenciales de servicio: se reenvía el token del usuario original, así
Productos aplica sus propias reglas de rol sobre ese usuario.

PRODUCTOS_SERVICE_URL apunta, dentro de la red interna de Docker Compose,
al nombre del servicio ("http://productos:8000"); en desarrollo local sin
Docker, por defecto usa "http://localhost:8000".
"""
import os
from typing import Optional

import httpx

from app.core import observabilidad
from app.core.resiliencia import CircuitBreaker, con_reintentos

PRODUCTOS_SERVICE_URL = os.getenv("PRODUCTOS_SERVICE_URL", "http://localhost:8000")
TIMEOUT_SEGUNDOS = float(os.getenv("PRODUCTOS_SERVICE_TIMEOUT", "5"))

# Resiliencia (ver app/core/resiliencia.py y docs/adr/0005-resiliencia.md).
# El circuit breaker abre tras CB_UMBRAL_FALLOS fallos seguidos y rechaza al
# instante durante CB_ESPERA_SEGUNDOS; después deja pasar una llamada de prueba.
REINTENTOS = int(os.getenv("PRODUCTOS_REINTENTOS", "1"))
REINTENTO_ESPERA_SEGUNDOS = float(os.getenv("PRODUCTOS_REINTENTO_ESPERA", "0.2"))
_BREAKER = CircuitBreaker(
    "productos",
    umbral_fallos=int(os.getenv("CB_UMBRAL_FALLOS", "5")),
    espera_segundos=float(os.getenv("CB_ESPERA_SEGUNDOS", "15")),
    registro=observabilidad.REGISTRO,
)
MENSAJE_CIRCUITO_ABIERTO = (
    "El servicio de Productos no está respondiendo y se pausaron los pedidos unos segundos. "
    "Si era un movimiento, quedó pendiente: reintentalo en un momento."
)
# Una escritura se reintenta solo si el pedido nunca llegó al servidor (no se pudo conectar).
_ERRORES_DE_CONEXION = (httpx.ConnectError, httpx.ConnectTimeout)
# Una lectura se puede repetir ante cualquier falla de transporte.
_ERRORES_DE_TRANSPORTE = (httpx.TransportError,)


class ProductosClientError(Exception):
    """
    Error estandarizado de la comunicación con Productos. status_code ya
    viene resuelto al código HTTP que corresponde devolver desde Movimientos
    (ej. 401 si el token venció, 403 si el rol no alcanza, 404 si el producto
    no existe, 409 si no hay stock, 503 si Productos no respondió a tiempo).
    """

    def __init__(self, status_code: int, mensaje: str):
        self.status_code = status_code
        self.mensaje = mensaje
        super().__init__(mensaje)


def _headers_con_token(token: str) -> dict:
    # X-Request-ID: el mismo ID de correlación viaja a Productos (ver observabilidad.py).
    return {"Authorization": f"Bearer {token}", **observabilidad.cabeceras_propagacion()}


def _verificar_circuito() -> None:
    """Falla rápido (503) si el circuito está abierto, sin llamar a la red."""
    if not _BREAKER.permitir():
        raise ProductosClientError(503, MENSAJE_CIRCUITO_ABIERTO)


def _registrar_respuesta(respuesta: httpx.Response) -> None:
    """Un 5xx indica un servicio enfermo (fallo); el resto, incluidos 404/409, son respuestas normales."""
    if respuesta.status_code >= 500:
        _BREAKER.fallo()
    else:
        _BREAKER.exito()


def _traducir_error(respuesta: httpx.Response, id_producto: int, contexto: str) -> ProductosClientError:
    """
    Traduce una respuesta HTTP de error de Productos a un ProductosClientError.
    contexto: "consultar el producto" o "ajustar el stock", para que el
    mensaje final quede claro.
    """
    if respuesta.status_code == 401:
        return ProductosClientError(
            401, "Tu sesión venció o el token es inválido. Iniciá sesión de nuevo."
        )
    if respuesta.status_code == 403:
        return ProductosClientError(
            403, "No tenés permisos para esta operación sobre el stock."
        )
    if respuesta.status_code == 404:
        return ProductosClientError(404, f"No existe el producto con id_producto={id_producto}.")
    if respuesta.status_code == 409:
        return ProductosClientError(409, "Stock insuficiente para registrar este movimiento.")
    return ProductosClientError(
        502, f"El servicio de Productos devolvió un error inesperado al {contexto}."
    )


def obtener_producto(id_producto: int, token: str) -> dict:
    """GET /api/v1/productos/{id} en el servicio de Productos."""
    url = f"{PRODUCTOS_SERVICE_URL}/api/v1/productos/{id_producto}"
    _verificar_circuito()
    try:
        respuesta = con_reintentos(
            lambda: httpx.get(url, headers=_headers_con_token(token), timeout=TIMEOUT_SEGUNDOS),
            _ERRORES_DE_TRANSPORTE, REINTENTOS, REINTENTO_ESPERA_SEGUNDOS,
        )
    except httpx.TimeoutException as error:
        _BREAKER.fallo()
        raise ProductosClientError(503, "El servicio de Productos no respondió a tiempo.") from error
    except httpx.RequestError as error:
        _BREAKER.fallo()
        raise ProductosClientError(503, "No se pudo conectar con el servicio de Productos.") from error
    _registrar_respuesta(respuesta)

    if respuesta.status_code >= 400:
        raise _traducir_error(respuesta, id_producto, "consultar el producto")
    return respuesta.json()


def ajustar_stock(id_producto: int, delta: int, token: str, clave: Optional[str] = None) -> dict:
    """
    PATCH /api/v1/productos/{id}/ajustar-stock en el servicio de Productos.

    delta > 0 incrementa el stock (ingreso, devolución).
    delta < 0 intenta decrementarlo (venta, estropeo); si Productos responde
    409 (ajuste atómico rechazado por falta de stock) se propaga tal cual.

    `clave` se envía como header Idempotency-Key: Productos aplica el ajuste
    UNA sola vez por clave, así que este método se puede repetir sin riesgo
    de descontar dos veces (es lo que permite reintentar y recuperar
    movimientos pendientes, ver services/movimiento_service.py).
    """
    url = f"{PRODUCTOS_SERVICE_URL}/api/v1/productos/{id_producto}/ajustar-stock"
    headers = _headers_con_token(token)
    if clave:
        headers["Idempotency-Key"] = clave
    _verificar_circuito()
    try:
        # Solo se reintenta si no se pudo conectar: el pedido nunca llegó, así que repetirlo es seguro
        # (y aunque llegara, el ajuste es idempotente por clave).
        respuesta = con_reintentos(
            lambda: httpx.patch(url, json={"delta": delta}, headers=headers, timeout=TIMEOUT_SEGUNDOS),
            _ERRORES_DE_CONEXION, REINTENTOS, REINTENTO_ESPERA_SEGUNDOS,
        )
    except httpx.TimeoutException as error:
        _BREAKER.fallo()
        raise ProductosClientError(
            503, "El servicio de Productos no respondió a tiempo al ajustar el stock."
        ) from error
    except httpx.RequestError as error:
        _BREAKER.fallo()
        raise ProductosClientError(
            503, "No se pudo conectar con el servicio de Productos para ajustar el stock."
        ) from error
    _registrar_respuesta(respuesta)

    if respuesta.status_code >= 400:
        raise _traducir_error(respuesta, id_producto, "ajustar el stock")
    return respuesta.json()

def consultar_ajuste(clave: str, token: str) -> Optional[dict]:
    """
    GET /api/v1/productos/ajustes/{clave} en el servicio de Productos.

    Devuelve el registro del ajuste si esa operación llegó a aplicarse, o None
    si nunca se aplicó (404). Se usa para reconciliar movimientos pendientes:
    confirma la verdad sobre el stock sin volver a modificarlo.
    """
    url = f"{PRODUCTOS_SERVICE_URL}/api/v1/productos/ajustes/{clave}"
    _verificar_circuito()
    try:
        respuesta = con_reintentos(
            lambda: httpx.get(url, headers=_headers_con_token(token), timeout=TIMEOUT_SEGUNDOS),
            _ERRORES_DE_TRANSPORTE, REINTENTOS, REINTENTO_ESPERA_SEGUNDOS,
        )
    except httpx.TimeoutException as error:
        _BREAKER.fallo()
        raise ProductosClientError(503, "El servicio de Productos no respondió a tiempo.") from error
    except httpx.RequestError as error:
        _BREAKER.fallo()
        raise ProductosClientError(503, "No se pudo conectar con el servicio de Productos.") from error
    _registrar_respuesta(respuesta)

    if respuesta.status_code == 404:
        return None
    if respuesta.status_code == 401:
        raise ProductosClientError(401, "Tu sesión venció o el token es inválido. Iniciá sesión de nuevo.")
    if respuesta.status_code == 403:
        raise ProductosClientError(403, "No tenés permisos para esta operación sobre el stock.")
    if respuesta.status_code >= 400:
        raise ProductosClientError(502, "El servicio de Productos devolvió un error inesperado al consultar el ajuste.")
    return respuesta.json()
