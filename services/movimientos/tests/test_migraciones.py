"""
Test de la migración de esquema: una base `movimientos.db` creada con el
esquema ANTERIOR (sin estado ni claves) debe seguir funcionando tras
actualizar, conservando sus movimientos como confirmados.
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.database.db import Base
from app.database.migraciones import migrar_esquema
from app.models.movimiento import ESTADO_CONFIRMADO, Movimiento

ESQUEMA_VIEJO = """
CREATE TABLE movimientos (
    id_movimiento INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    categoria_movimiento VARCHAR NOT NULL,
    cantidad_movida INTEGER NOT NULL,
    id_producto INTEGER NOT NULL,
    dni_cliente VARCHAR,
    dni_empleado VARCHAR
)
"""


@pytest.fixture()
def engine_con_base_vieja():
    archivo = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    archivo.close()
    engine = create_engine(f"sqlite:///{archivo.name}", connect_args={"check_same_thread": False})
    with engine.begin() as conexion:
        conexion.execute(text(ESQUEMA_VIEJO))
        conexion.execute(text("INSERT INTO movimientos (categoria_movimiento, cantidad_movida, id_producto) VALUES ('venta', 2, 1)"))
        conexion.execute(text("INSERT INTO movimientos (categoria_movimiento, cantidad_movida, id_producto) VALUES ('ingreso', 5, 1)"))
    yield engine
    engine.dispose()
    os.remove(archivo.name)


def test_migra_una_base_con_el_esquema_viejo(engine_con_base_vieja):
    engine = engine_con_base_vieja

    migrar_esquema(engine)
    Base.metadata.create_all(bind=engine)

    columnas = {c["name"] for c in inspect(engine).get_columns("movimientos")}
    assert {"estado", "operacion_id", "idempotency_key"} <= columnas
    assert "outbox_eventos" in inspect(engine).get_table_names()

    db = sessionmaker(bind=engine)()
    movimientos = db.query(Movimiento).all()
    assert len(movimientos) == 2  # no se perdió ningún movimiento
    assert {m.estado for m in movimientos} == {ESTADO_CONFIRMADO}  # antes no había estados: todos estaban confirmados
    assert all(m.operacion_id is None and m.idempotency_key is None for m in movimientos)
    db.close()


def test_la_base_migrada_acepta_movimientos_nuevos_y_hace_cumplir_la_clave_unica(engine_con_base_vieja):
    engine = engine_con_base_vieja
    migrar_esquema(engine)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    db.add(Movimiento(categoria_movimiento="venta", cantidad_movida=1, id_producto=1, idempotency_key="k1", operacion_id="o1"))
    db.commit()
    db.add(Movimiento(categoria_movimiento="venta", cantidad_movida=1, id_producto=1, idempotency_key="k1", operacion_id="o2"))
    with pytest.raises(Exception) as error:
        db.commit()

    assert "UNIQUE" in str(error.value).upper()
    db.close()


def test_migrar_dos_veces_no_falla(engine_con_base_vieja):
    migrar_esquema(engine_con_base_vieja)
    migrar_esquema(engine_con_base_vieja)  # idempotente: se ejecuta en cada arranque


def test_en_una_base_nueva_no_hace_nada(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'nueva.db'}")

    migrar_esquema(engine)  # no existe la tabla todavía: no debe fallar
    Base.metadata.create_all(bind=engine)

    assert "estado" in {c["name"] for c in inspect(engine).get_columns("movimientos")}
    engine.dispose()


def test_migra_agregando_las_columnas_de_cliente_y_conserva_el_dni_de_legado(engine_con_base_vieja):
    """Una base anterior a los clientes: los movimientos viejos quedan sin cliente y no se pierde su dni_cliente."""
    engine = engine_con_base_vieja
    with engine.begin() as conexion:
        conexion.execute(text("UPDATE movimientos SET dni_cliente = '20111222' WHERE id_movimiento = 1"))

    migrar_esquema(engine)

    columnas = {c["name"] for c in inspect(engine).get_columns("movimientos")}
    assert {"id_cliente", "cliente_documento"} <= columnas
    assert "clientes" not in inspect(engine).get_table_names()  # los clientes ya no viven acá

    db = sessionmaker(bind=engine)()
    viejo = db.query(Movimiento).filter(Movimiento.id_movimiento == 1).one()
    assert viejo.id_cliente is None and viejo.cliente_documento is None
    assert viejo.dni_cliente == "20111222"  # el dato de legado se conserva
    db.add(Movimiento(categoria_movimiento="venta", cantidad_movida=1, id_producto=1, id_cliente=7, cliente_documento="X-1"))
    db.commit()
    assert db.query(Movimiento).filter(Movimiento.id_cliente == 7).one().cliente_documento == "X-1"
    db.close()


def test_copia_el_documento_de_la_tabla_clientes_de_la_version_intermedia(engine_con_base_vieja):
    """
    Una versión intermedia guardaba los clientes en esta misma base. Al migrar, el
    documento se copia a cada movimiento (para no perderlo del historial) y la
    tabla vieja NO se borra: es la fuente para importarla al servicio de Clientes.
    """
    engine = engine_con_base_vieja
    with engine.begin() as conexion:
        conexion.execute(text("ALTER TABLE movimientos ADD COLUMN id_cliente INTEGER"))
        conexion.execute(text("CREATE TABLE clientes (id_cliente INTEGER PRIMARY KEY, documento VARCHAR(30) NOT NULL)"))
        conexion.execute(text("INSERT INTO clientes (id_cliente, documento) VALUES (5, 'X-1234.567/A')"))
        conexion.execute(text("UPDATE movimientos SET id_cliente = 5 WHERE id_movimiento = 1"))

    migrar_esquema(engine)

    with engine.connect() as conexion:
        documento = conexion.execute(text("SELECT cliente_documento FROM movimientos WHERE id_movimiento = 1")).scalar()
        sin_cliente = conexion.execute(text("SELECT cliente_documento FROM movimientos WHERE id_movimiento = 2")).scalar()
    assert documento == "X-1234.567/A"
    assert sin_cliente is None
    assert "clientes" in inspect(engine).get_table_names()  # no se borra
