"""Migración del esquema de Productos: una base anterior a la autoría tiene que quedar utilizable."""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.database.migraciones import migrar_esquema


def _base_vieja():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE productos (id_producto INTEGER PRIMARY KEY, nombre VARCHAR NOT NULL, marca VARCHAR, "
            "precio_venta FLOAT NOT NULL, stock_actual INTEGER NOT NULL, stock_minimo INTEGER NOT NULL, "
            "categoria VARCHAR, activo BOOLEAN NOT NULL DEFAULT 1)"
        ))
        c.execute(text("INSERT INTO productos (nombre, precio_venta, stock_actual, stock_minimo) VALUES ('Viejo', 10, 1, 1)"))
    return engine


def test_agrega_las_columnas_de_autoria_y_conserva_los_datos():
    engine = _base_vieja()

    migrar_esquema(engine)

    with engine.connect() as c:
        columnas = [f[1] for f in c.execute(text("PRAGMA table_info(productos)"))]
        fila = c.execute(text("SELECT nombre, creado_por, fecha_creacion FROM productos")).one()
    assert {"creado_por", "fecha_creacion"} <= set(columnas)
    assert tuple(fila) == ("Viejo", None, None)


def test_es_idempotente():
    engine = _base_vieja()

    migrar_esquema(engine)
    migrar_esquema(engine)


def test_no_hace_nada_si_la_tabla_no_existe():
    migrar_esquema(create_engine("sqlite:///:memory:"))
