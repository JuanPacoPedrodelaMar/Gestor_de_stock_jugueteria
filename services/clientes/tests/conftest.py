"""
Fixtures de los tests de Clientes. No necesitan Auth, Redis ni otros servicios:
la autenticación se simula devolviendo un payload ya validado (como si el JWT
fuera correcto) y la base es un archivo SQLite temporal.
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# app.core.jwt_auth exige AUTH_SECRET_KEY al importarse. Valor de prueba (no es
# un secreto real); si el entorno ya la define (CI), se respeta.
os.environ.setdefault("AUTH_SECRET_KEY", "clave-de-test-no-usar-en-produccion")

from app.database.db import Base  # noqa: E402
from app.models import cliente as _c  # noqa: E402,F401  (registra la tabla en Base)

TOKEN_FALSO = "token-de-prueba-no-valido"


def payload_de(rol, sub="1", dni=None):
    """Payload de un access token ya validado, para simular a un usuario de ese rol."""
    return {
        "sub": str(sub),
        "email": f"{rol}{sub}@test.com",
        "rol": rol,
        "dni": dni or f"2000000{sub}",
        "tipo": "access",
        "jti": f"jti-fake-{rol}-{sub}",
    }


@pytest.fixture()
def SessionLocal():
    """Sesiones sobre un archivo SQLite temporal (cada sesión abre su propia conexión)."""
    archivo = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    archivo.close()
    engine = create_engine(
        f"sqlite:///{archivo.name}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()
    os.remove(archivo.name)


def _armar_cliente_http(SessionLocal, monkeypatch, autenticado):
    from fastapi.testclient import TestClient

    from app import main as main_module
    from app.core.jwt_auth import obtener_token_y_payload
    from app.database.db import get_db
    from app.main import app

    # No tocar la base real al arrancar.
    monkeypatch.setattr(main_module, "inicializar_base", lambda: None)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    if autenticado:
        app.dependency_overrides[obtener_token_y_payload] = lambda: (TOKEN_FALSO, payload_de("admin", "1", "20000001"))
    return app, TestClient


@pytest.fixture()
def client(SessionLocal, monkeypatch):
    """TestClient con la autenticación simulada como admin. `client.como(rol, sub, dni)` cambia de usuario."""
    app, TestClient = _armar_cliente_http(SessionLocal, monkeypatch, autenticado=True)
    from app.core.jwt_auth import obtener_token_y_payload

    with TestClient(app) as test_client:
        def como(rol, sub="1", dni=None):
            app.dependency_overrides[obtener_token_y_payload] = lambda: (TOKEN_FALSO, payload_de(rol, sub, dni))
            return test_client

        test_client.como = como
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def client_sin_auth(SessionLocal, monkeypatch):
    """TestClient SIN simular la autenticación: usa la validación real del JWT."""
    app, TestClient = _armar_cliente_http(SessionLocal, monkeypatch, autenticado=False)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
