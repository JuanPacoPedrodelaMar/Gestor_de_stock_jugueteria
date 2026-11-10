import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import observabilidad
from app.database.db import Base, engine, SessionLocal
from app.database.migraciones import migrar_esquema
from app.models.usuario import Usuario, RolUsuario
from app.core.security import hashear_password
from app.routers import auth_router


def crear_admin_inicial_si_no_existe():
    """
    Crea un usuario admin inicial a partir de las variables de entorno
    AUTH_ADMIN_EMAIL / AUTH_ADMIN_PASSWORD, solo si todavía no existe
    ningún usuario en la base. Esto resuelve el problema de "arranque en
    frío": sin esto, nadie podría crear el primer usuario admin, porque
    POST /api/v1/auth/usuarios ya requiere estar autenticado como admin.

    Si las variables de entorno no están seteadas, no crea nada (se
    documenta como requerido en .env.example).
    """
    db = SessionLocal()
    try:
        if db.query(Usuario).count() > 0:
            return

        email = os.getenv("AUTH_ADMIN_EMAIL")
        password = os.getenv("AUTH_ADMIN_PASSWORD")
        if not email or not password:
            return

        admin = Usuario(
            email=email,
            password_hash=hashear_password(password),
            nombre="Administrador",
            rol=RolUsuario.ADMIN,
            dni=os.getenv("AUTH_ADMIN_DNI") or None,
        )
        db.add(admin)
        db.commit()
    finally:
        db.close()


def crear_usuarios_de_prueba_si_no_existen():
    """
    SOLO PARA ENTORNOS DE PRUEBA. Si HABILITAR_USUARIOS_PRUEBA=true, crea una
    cuenta por rol (admin, almacen, ventas, mixto) con las credenciales de las
    variables PRUEBA_<ROL>_EMAIL / _PASSWORD / _DNI (ver .env.example).

    Es idempotente: si el email ya existe no lo recrea (solo le completa el DNI
    si todavía no tenía). El frontend usa esas mismas variables para mostrar
    los botones de "acceso rápido" por rol. Poner HABILITAR_USUARIOS_PRUEBA=false
    en cualquier entorno real.
    """
    if os.getenv("HABILITAR_USUARIOS_PRUEBA", "false").lower() != "true":
        return

    usuarios_prueba = [
        ("PRUEBA_ADMIN", "Admin (prueba)", RolUsuario.ADMIN),
        ("PRUEBA_ALMACEN", "Empleado de almacén (prueba)", RolUsuario.ALMACEN),
        ("PRUEBA_VENTAS", "Empleado de ventas (prueba)", RolUsuario.VENTAS),
        ("PRUEBA_MIXTO", "Empleado mixto (prueba)", RolUsuario.MIXTO),
    ]

    db = SessionLocal()
    try:
        for prefijo, nombre, rol in usuarios_prueba:
            email = os.getenv(f"{prefijo}_EMAIL")
            password = os.getenv(f"{prefijo}_PASSWORD")
            dni = os.getenv(f"{prefijo}_DNI") or None
            if not email or not password:
                continue
            existente = db.query(Usuario).filter(Usuario.email == email).first()
            if existente:
                if dni and not existente.dni and not db.query(Usuario).filter(Usuario.dni == dni).first():
                    existente.dni = dni
                continue
            db.add(Usuario(
                email=email,
                password_hash=hashear_password(password),
                nombre=nombre,
                rol=rol,
                dni=dni,
            ))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrar_esquema(engine)
    Base.metadata.create_all(bind=engine)
    crear_admin_inicial_si_no_existe()
    crear_usuarios_de_prueba_si_no_existen()
    yield


app = FastAPI(
    title="API - Servicio de Autenticación (Gestor de Stock Juguetería)",
    description="Login, JWT de acceso/refresh, roles, y gestión de usuarios.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: en desarrollo "*" (el frontend corre en otro puerto). En un entorno real
# se define CORS_ORIGINS con el origen del frontend (varios, separados por coma).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

observabilidad.configurar_logging("auth")
observabilidad.instalar(app, "auth")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    # POST /refresh devuelve el nuevo refresh token en este header; sin
    # exponerlo, el navegador no deja que el JS del frontend lo lea (CORS).
    expose_headers=["X-New-Refresh-Token"],
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
    # Las respuestas de auth llevan tokens: que ningún intermediario las guarde.
    "Cache-Control": "no-store",
}


@app.middleware("http")
async def agregar_encabezados_seguridad(request: Request, call_next):
    response = await call_next(request)
    for nombre, valor in ENCABEZADOS_SEGURIDAD.items():
        response.headers[nombre] = valor
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": True, "mensaje": "Datos inválidos en la solicitud.", "detalles": jsonable_encoder([{k: v for k, v in e.items() if k != "input"} for e in exc.errors()])},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": True, "mensaje": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": True, "mensaje": "Error interno del servidor."},
        # Este 500 lo arma la capa más externa de Starlette, por fuera del
        # middleware de arriba: los encabezados se agregan acá a mano.
        headers=ENCABEZADOS_SEGURIDAD,
    )


app.include_router(auth_router.router)


@app.get("/", tags=["Root"])
def root():
    return {"mensaje": "API Auth - Gestor de Stock Juguetería. Ver /docs."}


@app.get("/health", tags=["Root"])
def health():
    return {"status": "ok", "service": "auth"}
