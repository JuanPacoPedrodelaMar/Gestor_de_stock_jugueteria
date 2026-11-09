"""
Migración mínima del esquema de Movimientos.

`Base.metadata.create_all` solo crea tablas que NO existen: no agrega columnas
a una tabla ya creada. Una base `movimientos.db` creada antes de introducir el
estado de la saga (columnas `estado`, `operacion_id`, `idempotency_key`)
quedaría con el esquema viejo y los INSERT/SELECT nuevos fallarían.

`migrar_esquema` agrega lo que falte con ALTER TABLE y crea los índices con
IF NOT EXISTS (idempotente: se puede ejecutar en cada arranque). Los
movimientos ya existentes quedan como `confirmado` (lo eran: antes no había
estados) y con `operacion_id` / `idempotency_key` en NULL.

Con los clientes se suman `id_cliente` y `cliente_documento` (copia del
documento del cliente al momento del movimiento: los clientes viven en el
servicio de Clientes). Los movimientos viejos conservan su `dni_cliente`
(columna de legado) y quedan con `id_cliente` en NULL.

Las tablas nuevas (outbox_eventos) las crea create_all, que se ejecuta
después. No reemplaza a una herramienta de migraciones (Alembic): alcanza para
el alcance de este proyecto.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrar_esquema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "movimientos" not in inspector.get_table_names():
        return  # base nueva: create_all la crea completa

    columnas = {c["name"] for c in inspector.get_columns("movimientos")}
    with engine.begin() as conexion:
        if "estado" not in columnas:
            conexion.execute(
                text("ALTER TABLE movimientos ADD COLUMN estado VARCHAR NOT NULL DEFAULT 'confirmado'")
            )
        if "operacion_id" not in columnas:
            conexion.execute(text("ALTER TABLE movimientos ADD COLUMN operacion_id VARCHAR(64)"))
        if "idempotency_key" not in columnas:
            conexion.execute(text("ALTER TABLE movimientos ADD COLUMN idempotency_key VARCHAR(100)"))
        if "id_cliente" not in columnas:
            conexion.execute(text("ALTER TABLE movimientos ADD COLUMN id_cliente INTEGER"))
        if "cliente_documento" not in columnas:
            conexion.execute(text("ALTER TABLE movimientos ADD COLUMN cliente_documento VARCHAR(30)"))
            # Una versión intermedia guardaba los clientes en esta misma base
            # (tabla `clientes`). Ahora son un servicio aparte: se copia el
            # documento a cada movimiento para no perder el dato en el historial.
            # La tabla vieja NO se borra (es la fuente para
            # services/clientes/importar_desde_movimientos.py).
            if "clientes" in inspector.get_table_names():
                conexion.execute(text(
                    "UPDATE movimientos SET cliente_documento = "
                    "(SELECT documento FROM clientes WHERE clientes.id_cliente = movimientos.id_cliente) "
                    "WHERE id_cliente IS NOT NULL"
                ))

        conexion.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ux_movimientos_operacion_id ON movimientos (operacion_id)")
        )
        conexion.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ux_movimientos_idempotency_key ON movimientos (idempotency_key)")
        )
        conexion.execute(text("CREATE INDEX IF NOT EXISTS ix_movimientos_estado ON movimientos (estado)"))
        conexion.execute(text("CREATE INDEX IF NOT EXISTS ix_movimientos_id_cliente ON movimientos (id_cliente)"))
