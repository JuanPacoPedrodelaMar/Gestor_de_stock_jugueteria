"""
Migración mínima del esquema de Productos (mismo criterio que en Movimientos).

`create_all` no agrega columnas a una tabla ya creada. Una base creada antes de
la autoría de productos no tiene `creado_por` ni `fecha_creacion`;
`migrar_esquema` las agrega (idempotente, se ejecuta en cada arranque). Los
productos existentes quedan con NULL: solo un admin puede eliminarlos.
La tabla nueva solicitudes_stock la crea create_all.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrar_esquema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "productos" not in inspector.get_table_names():
        return  # base nueva: create_all la crea completa

    columnas = {c["name"] for c in inspector.get_columns("productos")}
    with engine.begin() as conexion:
        if "creado_por" not in columnas:
            conexion.execute(text("ALTER TABLE productos ADD COLUMN creado_por INTEGER"))
        if "fecha_creacion" not in columnas:
            conexion.execute(text("ALTER TABLE productos ADD COLUMN fecha_creacion DATETIME"))
        conexion.execute(text("CREATE INDEX IF NOT EXISTS ix_productos_creado_por ON productos (creado_por)"))
