"""
Migración mínima del esquema de auth (mismo criterio que en Movimientos).

`Base.metadata.create_all` no agrega columnas a una tabla que ya existe, así
que una base `auth.db` creada antes de los roles de empleado quedaría sin la
columna `dni`. `migrar_esquema` es idempotente (se ejecuta en cada arranque):

- agrega `usuarios.dni` y su índice único;
- convierte el rol genérico "empleado" (ya inexistente) en "mixto", que
  conserva los mismos permisos que tenía.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrar_esquema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "usuarios" not in inspector.get_table_names():
        return  # base nueva: create_all la crea completa

    columnas = {c["name"] for c in inspector.get_columns("usuarios")}
    with engine.begin() as conexion:
        if "dni" not in columnas:
            conexion.execute(text("ALTER TABLE usuarios ADD COLUMN dni VARCHAR(8)"))
        conexion.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_usuarios_dni ON usuarios (dni)"))
        # SQLAlchemy guarda el NOMBRE del miembro del enum ("EMPLEADO"), no su valor.
        conexion.execute(text("UPDATE usuarios SET rol = 'MIXTO' WHERE rol = 'EMPLEADO'"))
