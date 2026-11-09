"""
Importación de los clientes que la versión anterior guardaba en la base de
Movimientos: conserva los ids, no duplica y no toca el origen.
"""
import sqlite3

import pytest

from importar_desde_movimientos import importar


@pytest.fixture()
def origen(tmp_path):
    ruta = tmp_path / "movimientos.db"
    con = sqlite3.connect(ruta)
    con.execute(
        "CREATE TABLE clientes (id_cliente INTEGER PRIMARY KEY AUTOINCREMENT, documento VARCHAR(30) NOT NULL, "
        "email VARCHAR(120), telefono VARCHAR(30), fecha_alta DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "creado_por_dni VARCHAR(8))"
    )
    con.execute("INSERT INTO clientes VALUES (3, 'X-1234.567/A', 'ana@ejemplo.com', '+54 376 4123456', '2026-11-01 10:00:00', '30000003')")
    con.execute("INSERT INTO clientes VALUES (7, 'X-1234.567/A', NULL, NULL, '2026-11-02 11:30:00', NULL)")  # mismo documento
    con.commit()
    con.close()
    return str(ruta)


def _leer(destino):
    con = sqlite3.connect(destino)
    try:
        return con.execute(
            "SELECT id_cliente, documento, email, telefono, fecha_alta, creado_por_dni FROM clientes ORDER BY id_cliente"
        ).fetchall()
    finally:
        con.close()


def test_importa_conservando_ids_y_datos(origen, tmp_path):
    destino = str(tmp_path / "clientes.db")

    resumen = importar(origen, destino)

    assert resumen == {"leidos": 2, "importados": 2, "ya_existian": 0}
    filas = _leer(destino)
    assert [f[0] for f in filas] == [3, 7]  # los ids se conservan (los movimientos apuntan a ellos)
    assert filas[0][1:] == ("X-1234.567/A", "ana@ejemplo.com", "+54 376 4123456", "2026-11-01 10:00:00", "30000003")
    assert filas[1][1] == "X-1234.567/A"  # documento repetido: son dos clientes distintos


def test_es_idempotente(origen, tmp_path):
    destino = str(tmp_path / "clientes.db")
    importar(origen, destino)

    resumen = importar(origen, destino)

    assert resumen == {"leidos": 2, "importados": 0, "ya_existian": 2}
    assert len(_leer(destino)) == 2


def test_no_pisa_a_un_cliente_que_ya_existe_en_el_destino(origen, tmp_path):
    destino = str(tmp_path / "clientes.db")
    importar(origen, destino)
    con = sqlite3.connect(destino)
    con.execute("UPDATE clientes SET email = 'corregido@ejemplo.com' WHERE id_cliente = 3")
    con.commit()
    con.close()

    importar(origen, destino)

    assert _leer(destino)[0][2] == "corregido@ejemplo.com"


def test_los_clientes_nuevos_siguen_la_numeracion(origen, tmp_path):
    destino = str(tmp_path / "clientes.db")
    importar(origen, destino)
    con = sqlite3.connect(destino)
    con.execute("INSERT INTO clientes (documento) VALUES ('NUEVO')")
    con.commit()
    id_nuevo = con.execute("SELECT id_cliente FROM clientes WHERE documento = 'NUEVO'").fetchone()[0]
    con.close()

    assert id_nuevo == 8  # sigue después del mayor id importado


def test_no_modifica_el_origen(origen, tmp_path):
    antes = _leer(origen)

    importar(origen, str(tmp_path / "clientes.db"))

    assert _leer(origen) == antes


def test_un_origen_sin_tabla_clientes_da_un_error_claro(tmp_path):
    vacia = tmp_path / "otra.db"
    sqlite3.connect(vacia).close()

    with pytest.raises(ValueError, match="no tiene la tabla"):
        importar(str(vacia), str(tmp_path / "clientes.db"))
