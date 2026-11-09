"""
Permisos por rol sobre el catálogo y ventana de arrepentimiento para borrar.

Reglas (ver README, "Roles"):
- leer: todos los roles;  cargar: admin, almacen, mixto;  editar: solo admin;
- eliminar: admin siempre; almacen/mixto solo lo que cargaron ELLOS y durante
  los primeros 5 minutos (PRODUCTO_COOLDOWN_BORRADO_SEGUNDOS);  ventas: nunca;
- ajustar stock (lo dispara un movimiento): admin, ventas, mixto.

Los tests cambian de usuario a mitad del caso con `client.como(rol, sub)`.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.producto import Producto
from app.services import producto_service

URL = "/api/v1/productos"


def _cargar(client, producto_payload, rol="admin", sub="1"):
    resp = client.como(rol, sub).post(URL, json=producto_payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _hace(db_session, id_producto, segundos):
    """Hace 'viejo' a un producto: lo cargaron hace `segundos` segundos."""
    producto = db_session.get(Producto, id_producto)
    producto.fecha_creacion = datetime.now(timezone.utc) - timedelta(seconds=segundos)
    db_session.commit()


# ---------------------------------------------------------------------------
# Quién puede cargar, editar y leer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rol", ["admin", "almacen", "mixto"])
def test_cargan_productos_admin_almacen_y_mixto(client, producto_payload, rol):
    resp = client.como(rol, "5").post(URL, json=producto_payload)

    assert resp.status_code == 201
    assert resp.json()["creado_por"] == 5


def test_ventas_no_puede_cargar_productos(client, producto_payload):
    resp = client.como("ventas", "5").post(URL, json=producto_payload)

    assert resp.status_code == 403


@pytest.mark.parametrize("rol", ["almacen", "ventas", "mixto"])
def test_solo_el_admin_edita_productos(client, producto_payload, rol):
    creado = _cargar(client, producto_payload)
    cambios = {**producto_payload, "nombre": "Nombre nuevo"}
    cambios.pop("stock_actual")

    resp = client.como(rol, "5").put(f"{URL}/{creado['id_producto']}", json=cambios)
    assert resp.status_code == 403

    resp = client.como("admin", "1").put(f"{URL}/{creado['id_producto']}", json=cambios)
    assert resp.status_code == 200
    assert resp.json()["nombre"] == "Nombre nuevo"


@pytest.mark.parametrize("rol", ["admin", "almacen", "ventas", "mixto"])
def test_todos_los_roles_leen_el_catalogo(client, producto_payload, rol):
    creado = _cargar(client, producto_payload)

    assert client.como(rol, "7").get(URL).status_code == 200
    assert client.como(rol, "7").get(f"{URL}/{creado['id_producto']}").status_code == 200


# ---------------------------------------------------------------------------
# Ventana de arrepentimiento
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rol", ["almacen", "mixto"])
def test_el_empleado_elimina_lo_que_cargo_dentro_de_la_ventana(client, producto_payload, rol):
    creado = _cargar(client, producto_payload, rol=rol, sub="5")

    resp = client.como(rol, "5").delete(f"{URL}/{creado['id_producto']}")

    assert resp.status_code == 204
    assert client.como("admin", "1").get(f"{URL}/{creado['id_producto']}").status_code == 404


def test_pasada_la_ventana_el_empleado_ya_no_puede_eliminar(client, db_session, producto_payload):
    creado = _cargar(client, producto_payload, rol="almacen", sub="5")
    _hace(db_session, creado["id_producto"], segundos=6 * 60)

    resp = client.como("almacen", "5").delete(f"{URL}/{creado['id_producto']}")

    assert resp.status_code == 403
    assert "minutos" in resp.json()["mensaje"]
    assert client.como("admin", "1").get(f"{URL}/{creado['id_producto']}").status_code == 200


def test_justo_antes_de_cumplirse_la_ventana_todavia_puede(client, db_session, producto_payload):
    creado = _cargar(client, producto_payload, rol="almacen", sub="5")
    _hace(db_session, creado["id_producto"], segundos=290)

    resp = client.como("almacen", "5").delete(f"{URL}/{creado['id_producto']}")

    assert resp.status_code == 204


def test_pasada_la_ventana_el_admin_si_puede(client, db_session, producto_payload):
    creado = _cargar(client, producto_payload, rol="almacen", sub="5")
    _hace(db_session, creado["id_producto"], segundos=60 * 60)

    resp = client.como("admin", "1").delete(f"{URL}/{creado['id_producto']}")

    assert resp.status_code == 204


def test_el_empleado_no_elimina_lo_que_cargo_otro_aunque_sea_reciente(client, producto_payload):
    creado = _cargar(client, producto_payload, rol="almacen", sub="5")

    resp = client.como("almacen", "6").delete(f"{URL}/{creado['id_producto']}")

    assert resp.status_code == 403
    assert "cargaste vos" in resp.json()["mensaje"]


def test_el_empleado_no_elimina_lo_que_cargo_el_admin(client, producto_payload):
    creado = _cargar(client, producto_payload, rol="admin", sub="1")

    assert client.como("mixto", "5").delete(f"{URL}/{creado['id_producto']}").status_code == 403


def test_un_producto_anterior_a_la_autoria_solo_lo_elimina_el_admin(client, db_session, producto_payload):
    creado = _cargar(client, producto_payload, rol="almacen", sub="5")
    producto = db_session.get(Producto, creado["id_producto"])
    producto.creado_por = None
    producto.fecha_creacion = None
    db_session.commit()

    assert client.como("almacen", "5").delete(f"{URL}/{creado['id_producto']}").status_code == 403
    assert client.como("admin", "1").delete(f"{URL}/{creado['id_producto']}").status_code == 204


def test_ventas_nunca_elimina(client, producto_payload):
    creado = _cargar(client, producto_payload)

    assert client.como("ventas", "5").delete(f"{URL}/{creado['id_producto']}").status_code == 403


def test_eliminar_un_producto_inexistente_sigue_siendo_404(client):
    assert client.como("almacen", "5").delete(f"{URL}/9999").status_code == 404


def test_dentro_de_la_ventana_con_movimientos_se_da_de_baja_en_vez_de_borrar(
    client, producto_payload, movimientos_stub
):
    """El empleado arrepentido sigue sujeto a la regla de trazabilidad: con historial, baja lógica."""
    creado = _cargar(client, producto_payload, rol="mixto", sub="5")
    movimientos_stub.cantidad = 3

    resp = client.como("mixto", "5").delete(f"{URL}/{creado['id_producto']}")

    assert resp.status_code == 200
    assert resp.json()["activo"] is False


# ---------------------------------------------------------------------------
# Lo que ve cada usuario: puede_eliminar y segundos_restantes_eliminar
# ---------------------------------------------------------------------------

def test_el_autor_ve_cuanto_le_queda_para_eliminar(client, producto_payload):
    creado = _cargar(client, producto_payload, rol="almacen", sub="5")

    assert creado["puede_eliminar"] is True
    assert 295 <= creado["segundos_restantes_eliminar"] <= 300

    listado = client.como("almacen", "5").get(URL).json()
    assert listado[0]["puede_eliminar"] is True
    assert listado[0]["segundos_restantes_eliminar"] is not None


def test_otro_empleado_no_ve_el_boton_de_eliminar(client, producto_payload):
    _cargar(client, producto_payload, rol="almacen", sub="5")

    listado = client.como("almacen", "6").get(URL).json()

    assert listado[0]["puede_eliminar"] is False
    assert listado[0]["segundos_restantes_eliminar"] is None


def test_pasada_la_ventana_deja_de_figurar_como_eliminable(client, db_session, producto_payload):
    creado = _cargar(client, producto_payload, rol="almacen", sub="5")
    _hace(db_session, creado["id_producto"], segundos=400)

    listado = client.como("almacen", "5").get(URL).json()

    assert listado[0]["puede_eliminar"] is False


def test_el_admin_siempre_figura_como_eliminable_sin_limite(client, producto_payload):
    _cargar(client, producto_payload, rol="almacen", sub="5")

    listado = client.como("admin", "1").get(URL).json()

    assert listado[0]["puede_eliminar"] is True
    assert listado[0]["segundos_restantes_eliminar"] is None


def test_ventas_ve_el_catalogo_pero_nada_es_eliminable(client, producto_payload):
    _cargar(client, producto_payload)

    assert client.como("ventas", "5").get(URL).json()[0]["puede_eliminar"] is False


def test_la_ventana_es_configurable(monkeypatch, client, db_session, producto_payload):
    monkeypatch.setattr(producto_service, "COOLDOWN_BORRADO_SEGUNDOS", 30)
    creado = _cargar(client, producto_payload, rol="almacen", sub="5")
    _hace(db_session, creado["id_producto"], segundos=45)

    assert client.como("almacen", "5").delete(f"{URL}/{creado['id_producto']}").status_code == 403


# ---------------------------------------------------------------------------
# Ajuste de stock y datos de prueba
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rol,esperado", [("admin", 200), ("ventas", 200), ("mixto", 200), ("almacen", 403)])
def test_ajustar_stock_segun_el_rol(client, producto_payload, rol, esperado):
    creado = _cargar(client, producto_payload)

    resp = client.como(rol, "5").patch(f"{URL}/{creado['id_producto']}/ajustar-stock", json={"delta": -1})

    assert resp.status_code == esperado


@pytest.mark.parametrize("rol,esperado", [("admin", 201), ("almacen", 403), ("ventas", 403), ("mixto", 403)])
def test_los_datos_de_prueba_son_solo_del_admin(client, rol, esperado):
    resp = client.como(rol, "5").post("/api/v1/dev/seed-productos?cantidad=3")

    assert resp.status_code == esperado
