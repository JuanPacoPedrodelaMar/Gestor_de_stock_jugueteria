"""
Solicitudes de stock: un empleado de almacén (o mixto) pide reponer un producto;
el admin las atiende o rechaza. No cambian el stock.
"""
import pytest

URL = "/api/v1/solicitudes-stock"
PRODUCTOS = "/api/v1/productos"


@pytest.fixture()
def producto(client, producto_payload):
    return client.como("admin", "1").post(PRODUCTOS, json=producto_payload).json()


def _pedir(client, id_producto, rol="almacen", sub="5", cantidad=10, **extra):
    return client.como(rol, sub).post(URL, json={"id_producto": id_producto, "cantidad": cantidad, **extra})


@pytest.mark.parametrize("rol", ["almacen", "mixto"])
def test_almacen_y_mixto_piden_stock(client, producto, rol):
    resp = _pedir(client, producto["id_producto"], rol=rol, nota="Urgente para el sábado")

    assert resp.status_code == 201
    datos = resp.json()
    assert datos["estado"] == "pendiente"
    assert datos["cantidad"] == 10
    assert datos["nombre_producto"] == producto["nombre"]
    assert datos["solicitante"] == "30000005"  # el DNI viene del token, no del formulario


@pytest.mark.parametrize("rol", ["admin", "ventas"])
def test_admin_y_ventas_no_piden_stock(client, producto, rol):
    assert _pedir(client, producto["id_producto"], rol=rol).status_code == 403


def test_pedir_stock_no_modifica_el_stock(client, producto):
    _pedir(client, producto["id_producto"], cantidad=50)

    actual = client.como("admin", "1").get(f"{PRODUCTOS}/{producto['id_producto']}").json()
    assert actual["stock_actual"] == producto["stock_actual"]


def test_producto_inexistente_devuelve_404(client):
    assert _pedir(client, 9999).status_code == 404


def test_producto_dado_de_baja_devuelve_404(client, producto, movimientos_stub):
    movimientos_stub.cantidad = 1
    client.como("admin", "1").delete(f"{PRODUCTOS}/{producto['id_producto']}")  # baja lógica

    assert _pedir(client, producto["id_producto"]).status_code == 404


@pytest.mark.parametrize("cantidad", [0, -3, 100001])
def test_cantidad_invalida_devuelve_400(client, producto, cantidad):
    assert _pedir(client, producto["id_producto"], cantidad=cantidad).status_code == 400


def test_la_nota_rechaza_caracteres_peligrosos(client, producto):
    assert _pedir(client, producto["id_producto"], nota="<script>alert(1)</script>").status_code == 400


def test_el_admin_ve_todas_y_cada_empleado_solo_las_suyas(client, producto):
    _pedir(client, producto["id_producto"], sub="5")
    _pedir(client, producto["id_producto"], sub="6")

    assert len(client.como("admin", "1").get(URL).json()) == 2
    suyas = client.como("almacen", "5").get(URL).json()
    assert len(suyas) == 1
    assert suyas[0]["solicitante"] == "30000005"


def test_ventas_no_ve_solicitudes(client):
    assert client.como("ventas", "5").get(URL).status_code == 403


def test_filtrar_por_estado(client, producto):
    id_solicitud = _pedir(client, producto["id_producto"]).json()["id_solicitud"]
    _pedir(client, producto["id_producto"])
    client.como("admin", "1").patch(f"{URL}/{id_solicitud}", json={"estado": "atendida"})

    pendientes = client.get(f"{URL}?estado=pendiente").json()
    atendidas = client.get(f"{URL}?estado=atendida").json()

    assert len(pendientes) == 1
    assert [s["id_solicitud"] for s in atendidas] == [id_solicitud]
    assert client.get(f"{URL}?estado=cualquiera").status_code == 400


@pytest.mark.parametrize("estado", ["atendida", "rechazada"])
def test_el_admin_resuelve_una_solicitud(client, producto, estado):
    id_solicitud = _pedir(client, producto["id_producto"]).json()["id_solicitud"]

    resp = client.como("admin", "1").patch(f"{URL}/{id_solicitud}", json={"estado": estado})

    assert resp.status_code == 200
    assert resp.json()["estado"] == estado


def test_una_solicitud_resuelta_no_se_resuelve_de_nuevo(client, producto):
    id_solicitud = _pedir(client, producto["id_producto"]).json()["id_solicitud"]
    client.como("admin", "1").patch(f"{URL}/{id_solicitud}", json={"estado": "atendida"})

    resp = client.patch(f"{URL}/{id_solicitud}", json={"estado": "rechazada"})

    assert resp.status_code == 409


def test_resolver_una_inexistente_devuelve_404(client):
    assert client.como("admin", "1").patch(f"{URL}/9999", json={"estado": "atendida"}).status_code == 404


@pytest.mark.parametrize("rol", ["almacen", "ventas", "mixto"])
def test_solo_el_admin_resuelve(client, producto, rol):
    id_solicitud = _pedir(client, producto["id_producto"]).json()["id_solicitud"]

    resp = client.como(rol, "5").patch(f"{URL}/{id_solicitud}", json={"estado": "atendida"})

    assert resp.status_code == 403


def test_el_estado_a_resolver_solo_admite_atendida_o_rechazada(client, producto):
    id_solicitud = _pedir(client, producto["id_producto"]).json()["id_solicitud"]

    resp = client.como("admin", "1").patch(f"{URL}/{id_solicitud}", json={"estado": "pendiente"})

    assert resp.status_code == 400
