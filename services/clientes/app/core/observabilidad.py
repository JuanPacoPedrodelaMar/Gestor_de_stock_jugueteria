"""
Observabilidad mínima, sin dependencias externas.

Resuelve tres cosas con la biblioteca estándar:

1. LOGS ESTRUCTURADOS: una línea JSON por evento (ts, nivel, servicio, logger,
   mensaje, request_id y los campos extra). Se activa con LOG_FORMAT=json (los
   Dockerfiles lo dejan activo); sin esa variable se usa texto plano.
2. ID DE CORRELACIÓN: cada pedido HTTP recibe (o genera) un `X-Request-ID`. Se
   guarda en una ContextVar, aparece en todos los logs del pedido, se reenvía en
   las llamadas HTTP a otros servicios y viaja dentro del evento de RabbitMQ
   (campo `request_id`). Con él se sigue una venta de punta a punta.
3. MÉTRICAS EN FORMATO PROMETHEUS (`GET /metrics`): contadores, gauges e
   histogramas, expuestos en el formato de texto 0.0.4.

Por qué propio y no `prometheus_client`: el formato de texto es simple, evita una
dependencia más en 5 imágenes y es testeable sin instalar nada. Si el proyecto
creciera, el reemplazo por `prometheus_client` es directo (misma semántica de
contador/gauge/histograma). Ver docs/adr/0006-observabilidad.md.

Este archivo es IDÉNTICO en los 5 servicios (cada uno se construye con su propio
contexto de Docker, por eso se copia). scripts/verificar_copias.py comprueba en
CI que no se desincronicen.
"""
import contextvars
import json
import logging
import math
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

ENCABEZADO_REQUEST_ID = "X-Request-ID"
# Un ID entrante solo se acepta si es "seguro" (evita inyectar saltos de línea o
# basura en los logs y en los encabezados que se reenvían a otros servicios).
_PATRON_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{8,64}\Z")

_REQUEST_ID: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("request_id", default=None)

# Rutas que no se loguean (el healthcheck y el scraping corren cada pocos segundos).
RUTAS_SILENCIOSAS = {"/health", "/healthz", "/metrics"}


# ---------------------------------------------------------------------------
# ID de correlación
# ---------------------------------------------------------------------------

def nuevo_request_id() -> str:
    return uuid.uuid4().hex


def request_id_entrante(valor: Optional[str]) -> str:
    """Usa el ID que llegó en el encabezado si es válido; si no, genera uno nuevo."""
    if valor and _PATRON_REQUEST_ID.match(valor):
        return valor
    return nuevo_request_id()


def request_id_actual() -> Optional[str]:
    return _REQUEST_ID.get()


def fijar_request_id(valor: Optional[str]):
    """Fija el ID del contexto actual y devuelve el token para restablecerlo."""
    return _REQUEST_ID.set(valor)


def restablecer_request_id(token) -> None:
    _REQUEST_ID.reset(token)


def cabeceras_propagacion() -> Dict[str, str]:
    """Encabezados a agregar en las llamadas HTTP salientes para mantener la correlación."""
    rid = request_id_actual()
    return {ENCABEZADO_REQUEST_ID: rid} if rid else {}


# ---------------------------------------------------------------------------
# Logs estructurados
# ---------------------------------------------------------------------------

_RESERVADOS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


class FormateadorJson(logging.Formatter):
    """Una línea JSON por registro. Los campos pasados con `extra={...}` se incluyen tal cual."""

    def __init__(self, servicio: str):
        super().__init__()
        self.servicio = servicio

    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "servicio": self.servicio,
            "logger": record.name,
            "mensaje": record.getMessage(),
        }
        rid = request_id_actual()
        if rid:
            datos["request_id"] = rid
        for clave, valor in record.__dict__.items():
            if clave not in _RESERVADOS and not clave.startswith("_"):
                datos[clave] = valor
        if record.exc_info:
            datos["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)


def configurar_logging(servicio: str) -> None:
    """
    Con LOG_FORMAT=json instala un handler JSON en el logger raíz (reemplaza los
    existentes). Con cualquier otro valor deja el formato de texto de siempre.
    """
    nivel = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    if os.getenv("LOG_FORMAT", "texto").lower() == "json":
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(FormateadorJson(servicio))
        raiz = logging.getLogger()
        raiz.handlers = [handler]
        raiz.setLevel(nivel)
    else:
        logging.basicConfig(level=nivel, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ---------------------------------------------------------------------------
# Métricas (formato de texto de Prometheus)
# ---------------------------------------------------------------------------

BUCKETS_LATENCIA = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_Etiquetas = Tuple[Tuple[str, str], ...]


def _etiquetas(d: Optional[Dict[str, str]]) -> _Etiquetas:
    return tuple(sorted((str(k), str(v)) for k, v in (d or {}).items()))


def _escapar(valor: str) -> str:
    return valor.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _fmt_etiquetas(etiquetas: _Etiquetas, extra: Optional[Tuple[str, str]] = None) -> str:
    pares = list(etiquetas) + ([extra] if extra else [])
    if not pares:
        return ""
    return "{" + ",".join(f'{k}="{_escapar(v)}"' for k, v in pares) + "}"


def _fmt_valor(v: float) -> str:
    if isinstance(v, float):
        if math.isinf(v):
            return "+Inf" if v > 0 else "-Inf"
        if math.isnan(v):
            return "NaN"
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return str(v)


class Registro:
    """Registro de métricas seguro para usar desde varios hilos."""

    def __init__(self):
        self._lock = threading.Lock()
        self._meta: Dict[str, Tuple[str, str]] = {}  # nombre -> (tipo, ayuda)
        self._contadores: Dict[str, Dict[_Etiquetas, float]] = {}
        self._gauges: Dict[str, Dict[_Etiquetas, float]] = {}
        self._histogramas: Dict[str, Dict[_Etiquetas, dict]] = {}
        self._buckets: Dict[str, Tuple[float, ...]] = {}
        self._al_exponer: List[Callable[["Registro"], None]] = []

    def _declarar(self, nombre: str, tipo: str, ayuda: str) -> None:
        previo = self._meta.get(nombre)
        if previo is None:
            self._meta[nombre] = (tipo, ayuda)
        elif previo[0] != tipo:
            raise ValueError(f"La métrica {nombre} ya existe como {previo[0]}")

    def inc(self, nombre: str, ayuda: str, etiquetas: Optional[Dict[str, str]] = None, n: float = 1.0) -> None:
        with self._lock:
            self._declarar(nombre, "counter", ayuda)
            serie = self._contadores.setdefault(nombre, {})
            clave = _etiquetas(etiquetas)
            serie[clave] = serie.get(clave, 0.0) + n

    def gauge(self, nombre: str, ayuda: str, valor: float, etiquetas: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            self._declarar(nombre, "gauge", ayuda)
            self._gauges.setdefault(nombre, {})[_etiquetas(etiquetas)] = float(valor)

    def observar(
        self, nombre: str, ayuda: str, valor: float,
        etiquetas: Optional[Dict[str, str]] = None, buckets: Tuple[float, ...] = BUCKETS_LATENCIA,
    ) -> None:
        with self._lock:
            self._declarar(nombre, "histogram", ayuda)
            self._buckets.setdefault(nombre, tuple(buckets))
            limites = self._buckets[nombre]
            serie = self._histogramas.setdefault(nombre, {})
            clave = _etiquetas(etiquetas)
            h = serie.setdefault(clave, {"cuentas": [0] * len(limites), "suma": 0.0, "total": 0})
            for i, limite in enumerate(limites):
                if valor <= limite:
                    h["cuentas"][i] += 1
                    break
            h["suma"] += valor
            h["total"] += 1

    def al_exponer(self, funcion: Callable[["Registro"], None]) -> None:
        """Registra una función que actualiza gauges justo antes de cada lectura de /metrics."""
        self._al_exponer.append(funcion)

    def reiniciar(self) -> None:
        """Borra todo (solo para tests)."""
        with self._lock:
            self._meta.clear(); self._contadores.clear(); self._gauges.clear()
            self._histogramas.clear(); self._buckets.clear()

    def exponer(self) -> str:
        for funcion in list(self._al_exponer):
            try:
                funcion(self)
            except Exception:  # una métrica de negocio rota no debe tirar /metrics
                logging.getLogger(__name__).exception("Falló la actualización de una métrica al exponerla.")
        lineas: List[str] = []
        with self._lock:
            for nombre in sorted(self._meta):
                tipo, ayuda = self._meta[nombre]
                lineas.append(f"# HELP {nombre} {ayuda}")
                lineas.append(f"# TYPE {nombre} {tipo}")
                if tipo == "counter":
                    for et, v in sorted(self._contadores.get(nombre, {}).items()):
                        lineas.append(f"{nombre}{_fmt_etiquetas(et)} {_fmt_valor(v)}")
                elif tipo == "gauge":
                    for et, v in sorted(self._gauges.get(nombre, {}).items()):
                        lineas.append(f"{nombre}{_fmt_etiquetas(et)} {_fmt_valor(v)}")
                else:
                    limites = self._buckets[nombre]
                    for et, h in sorted(self._histogramas.get(nombre, {}).items()):
                        acumulado = 0
                        for limite, cuenta in zip(limites, h["cuentas"]):
                            acumulado += cuenta
                            lineas.append(f"{nombre}_bucket{_fmt_etiquetas(et, ('le', _fmt_valor(float(limite))))} {acumulado}")
                        lineas.append(f"{nombre}_bucket{_fmt_etiquetas(et, ('le', '+Inf'))} {h['total']}")
                        lineas.append(f"{nombre}_sum{_fmt_etiquetas(et)} {_fmt_valor(h['suma'])}")
                        lineas.append(f"{nombre}_count{_fmt_etiquetas(et)} {h['total']}")
        return "\n".join(lineas) + "\n"


REGISTRO = Registro()
CONTENT_TYPE_METRICAS = "text/plain; version=0.0.4; charset=utf-8"


# ---------------------------------------------------------------------------
# Integración con FastAPI (los imports son perezosos: el worker no usa FastAPI)
# ---------------------------------------------------------------------------

def _plantilla_de_ruta(request) -> str:
    """Ruta con parámetros sin reemplazar (/api/v1/productos/{id_producto}): baja cardinalidad."""
    ruta = getattr(request.scope.get("route"), "path", None)
    return ruta or "no_encontrada"


def instalar(app, servicio: str, registro: Registro = REGISTRO) -> None:
    """
    Agrega a la app: el middleware (X-Request-ID, log de acceso en JSON y métricas
    HTTP) y el endpoint GET /metrics. No aparece en OpenAPI.
    """
    from fastapi import Response

    log = logging.getLogger(f"{servicio}.http")

    @app.middleware("http")
    async def observabilidad_http(request, call_next):
        rid = request_id_entrante(request.headers.get(ENCABEZADO_REQUEST_ID))
        token = fijar_request_id(rid)
        inicio = time.perf_counter()
        estado = 500  # si la excepción sube sin respuesta, se cuenta como 500
        try:
            respuesta = await call_next(request)
            estado = respuesta.status_code
            respuesta.headers[ENCABEZADO_REQUEST_ID] = rid
            return respuesta
        finally:
            duracion = time.perf_counter() - inicio
            ruta = _plantilla_de_ruta(request)
            if ruta != "/metrics":
                registro.inc(
                    "http_requests_total", "Pedidos HTTP atendidos.",
                    {"servicio": servicio, "metodo": request.method, "ruta": ruta, "estado": str(estado)},
                )
                registro.observar(
                    "http_request_duration_seconds", "Duración de los pedidos HTTP en segundos.",
                    duracion, {"servicio": servicio, "metodo": request.method, "ruta": ruta},
                )
            if request.url.path not in RUTAS_SILENCIOSAS:
                log.info(
                    "pedido atendido",
                    extra={
                        "evento": "http", "metodo": request.method, "ruta": request.url.path,
                        "estado": estado, "duracion_ms": round(duracion * 1000, 2),
                    },
                )
            restablecer_request_id(token)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(content=registro.exponer(), media_type=CONTENT_TYPE_METRICAS)
