"""
Importa al servicio de Clientes los clientes que una versión anterior guardaba
en la base de Movimientos (tabla `clientes` de movimientos.db).

Uso (con los servicios detenidos o, al menos, sin escrituras en curso):

    python importar_desde_movimientos.py --origen RUTA/movimientos.db --destino RUTA/clientes.db

- Conserva el `id_cliente` de cada cliente: los movimientos ya registrados siguen
  apuntando al cliente correcto.
- Es idempotente: si se corre dos veces, no duplica (los ids que ya existen en el
  destino se saltean).
- No modifica ni borra nada del origen.

Con Docker Compose, los archivos están en los volúmenes `movimientos_data` y
`clientes_data` (ver README, "Migrar clientes de la versión anterior").
"""
import argparse
import sqlite3
import sys

from sqlalchemy import create_engine, text

from app.database.db import Base
from app.models import cliente as _modelo_cliente  # noqa: F401  (registra la tabla en Base)

COLUMNAS = ["id_cliente", "documento", "email", "telefono", "fecha_alta", "creado_por_dni"]


def importar(origen: str, destino: str) -> dict:
    """Copia los clientes de `origen` a `destino` (rutas de archivos SQLite). Devuelve un resumen."""
    fuente = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
    try:
        existentes = {fila[1] for fila in fuente.execute("PRAGMA table_info(clientes)")}
        if not existentes:
            raise ValueError("la base de origen no tiene la tabla `clientes` (¿es la de Movimientos?).")
        columnas = [c for c in COLUMNAS if c in existentes]
        filas = fuente.execute(f"SELECT {', '.join(columnas)} FROM clientes ORDER BY id_cliente").fetchall()
    finally:
        fuente.close()

    motor = create_engine(f"sqlite:///{destino}")
    Base.metadata.create_all(bind=motor)
    importados = 0
    with motor.begin() as conexion:
        sentencia = text(
            f"INSERT OR IGNORE INTO clientes ({', '.join(columnas)}) "
            f"VALUES ({', '.join(':' + c for c in columnas)})"
        )
        for fila in filas:
            importados += conexion.execute(sentencia, dict(zip(columnas, fila))).rowcount
    motor.dispose()
    return {"leidos": len(filas), "importados": importados, "ya_existian": len(filas) - importados}


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa los clientes de movimientos.db a clientes.db.")
    parser.add_argument("--origen", required=True, help="Ruta de movimientos.db (solo lectura)")
    parser.add_argument("--destino", required=True, help="Ruta de clientes.db (se crea si no existe)")
    argumentos = parser.parse_args()
    try:
        resumen = importar(argumentos.origen, argumentos.destino)
    except (ValueError, sqlite3.Error) as error:
        sys.exit(f"No se pudo importar: {error}")
    print(
        f"Clientes leídos: {resumen['leidos']} | importados: {resumen['importados']} | "
        f"ya existían: {resumen['ya_existian']}"
    )


if __name__ == "__main__":
    main()
