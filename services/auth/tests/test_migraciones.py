"""
Migración del esquema de auth: una base creada con el modelo anterior (sin
columna dni y con el rol genérico "empleado") tiene que quedar utilizable.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.database.migraciones import migrar_esquema


def _base_vieja():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE usuarios (id_usuario INTEGER PRIMARY KEY, email VARCHAR NOT NULL, "
            "password_hash VARCHAR NOT NULL, nombre VARCHAR NOT NULL, rol VARCHAR(8) NOT NULL, "
            "activo BOOLEAN NOT NULL DEFAULT 1)"
        ))
        c.execute(text("INSERT INTO usuarios (email, password_hash, nombre, rol) VALUES ('a@t.com','h','A','ADMIN')"))
        c.execute(text("INSERT INTO usuarios (email, password_hash, nombre, rol) VALUES ('e@t.com','h','E','EMPLEADO')"))
    return engine


def test_agrega_dni_y_convierte_empleado_en_mixto():
    engine = _base_vieja()

    migrar_esquema(engine)

    with engine.connect() as c:
        columnas = [f[1] for f in c.execute(text("PRAGMA table_info(usuarios)"))]
        roles = dict(c.execute(text("SELECT email, rol FROM usuarios")).all())
    assert "dni" in columnas
    assert roles == {"a@t.com": "ADMIN", "e@t.com": "MIXTO"}


def test_es_idempotente():
    engine = _base_vieja()

    migrar_esquema(engine)
    migrar_esquema(engine)  # no debe fallar al repetirse


def test_no_hace_nada_si_la_tabla_no_existe():
    engine = create_engine("sqlite:///:memory:")

    migrar_esquema(engine)
