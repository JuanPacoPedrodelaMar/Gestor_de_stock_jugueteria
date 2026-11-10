import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import observabilidad
from app.database.db import Base, engine
from app.database.migraciones import migrar_esquema
from app.models import solicitud_stock as _modelo_solicitud  # noqa: F401  (registra la tabla en Base)
from app.routers import producto_router, seed_router, solicitud_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Crea las tablas definidas en los modelos si todavía no existen, al
    arrancar la aplicación (no al importar el módulo). Esto evita que el
    simple hecho de importar app.main (por ejemplo, desde los tests)
    intente escribir en el archivo de base de datos real: los tests
    sobreescriben la dependencia get_db con su propia sesión en memoria y
    crean sus tablas por su cuenta (ver tests/conftest.py).
    """
    migrar_esquema(engine)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="API - Sistema de Gestión de Stock para Juguetería",
    description="AE1 - CRUD funcional de la entidad Producto",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: en desarrollo "*" (el frontend corre en otro puerto). En un entorno real
# se define CORS_ORIGINS con el origen del frontend (varios, separados por coma).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

observabilidad.configurar_logging("productos")
observabilidad.instalar(app, "productos")


def _metricas_de_negocio(registro) -> None:
    """Gauges de negocio, calculados al momento de cada lectura de /metrics."""
    from sqlalchemy import func

    from app.database.db import SessionLocal
    from app.models.producto import Producto

    db = SessionLocal()
    try:
        activos = db.query(func.count(Producto.id_producto)).filter(Producto.activo.is_(True)).scalar() or 0
        bajos = (
            db.query(func.count(Producto.id_producto))
            .filter(Producto.activo.is_(True), Producto.stock_actual <= Producto.stock_minimo)
            .scalar() or 0
        )
    finally:
        db.close()
    registro.gauge("productos_activos", "Productos activos en el catálogo.", activos)
    registro.gauge("productos_stock_bajo", "Productos activos con stock_actual <= stock_minimo.", bajos)


observabilidad.REGISTRO.al_exponer(_metricas_de_negocio)


# CORS: permite que el frontend, servido desde otro origen/puerto, llame a la API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Encabezados de seguridad (se agregan a TODA respuesta, incluidos los errores)
# ---------------------------------------------------------------------------
ENCABEZADOS_SEGURIDAD = {
    # Anti-sniffing: el navegador respeta el Content-Type declarado y no "adivina".
    "X-Content-Type-Options": "nosniff",
    # Anti-clickjacking: ningún sitio ajeno puede mostrar esta respuesta en un iframe.
    "X-Frame-Options": "DENY",
    # Equivalente moderno de X-Frame-Options (los navegadores nuevos lo priorizan).
    "Content-Security-Policy": "frame-ancestors 'none'",
}


@app.middleware("http")
async def agregar_encabezados_seguridad(request: Request, call_next):
    response = await call_next(request)
    for nombre, valor in ENCABEZADOS_SEGURIDAD.items():
        response.headers[nombre] = valor
    return response


# ---------------------------------------------------------------------------
# Middleware centralizado de manejo de errores
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Captura errores de validación de Pydantic (campos faltantes, tipos
    inválidos, stock negativo, etc.) y los traduce a 400 Bad Request.
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": True,
            "mensaje": "Datos inválidos en la solicitud.",
            "detalles": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Estandariza las respuestas de error (ej. 404 Not Found) en formato JSON."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": True, "mensaje": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Captura cualquier excepción no controlada y devuelve 500 Internal
    Server Error sin exponer trazas internas del servidor.
    """
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": True, "mensaje": "Error interno del servidor."},
        # Este 500 lo arma la capa más externa de Starlette, por fuera del
        # middleware de arriba: los encabezados se agregan acá a mano.
        headers=ENCABEZADOS_SEGURIDAD,
    )


# ---------------------------------------------------------------------------
# Registro de rutas
# ---------------------------------------------------------------------------
app.include_router(producto_router.router)
app.include_router(solicitud_router.router)
app.include_router(seed_router.router)


@app.get("/", tags=["Root"])
def root():
    """Endpoint raíz simple para verificar que el servidor está activo."""
    return {"mensaje": "API Gestor de Stock - Juguetería. Ver /docs para la documentación interactiva."}


@app.get("/health", tags=["Root"])
def health():
    """
    Healthcheck simple para orquestadores (Docker healthcheck, balanceadores,
    monitoreo). Devuelve 200 si el proceso está vivo y puede responder.
    """
    return {"status": "ok", "service": "productos"}
